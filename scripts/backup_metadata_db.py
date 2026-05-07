#!/usr/bin/env python3
"""F4-a: back up the metadata sidecar DB (SQLite copy or pg_dump).

This is a sidecar-only operation: it never touches the privacy pipeline contracts
or main-chain processes. SQLite source uses the sqlite3 backup API for a hot,
consistent file-level copy. PostgreSQL source invokes `pg_dump` via subprocess,
captures the dump to disk, and (with --verify) calls `pg_restore --list` to
confirm the dump is structurally valid.

S3 upload (--upload-s3) lazy-imports boto3. Without --execute the upload step
stays in plan mode so default contract smoke does not need AWS credentials.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import sha256_file  # noqa: E402


SCHEMA_ID = "metadata_db_backup_report/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def redact_dsn(dsn: str) -> str:
    """Strip user info password from a libpq URL DSN; keep the rest verbatim.

    PostgreSQL accepts both URL DSNs (postgresql://user:pass@host/db) and key=value
    DSNs (host=... password=...). For URL form we drop the password. For key=value
    DSNs we filter out password tokens.
    """
    if not dsn:
        return ""
    if "://" in dsn:
        try:
            parsed = urlparse(dsn)
        except ValueError:
            return "<dsn>"
        netloc = parsed.hostname or ""
        if parsed.username:
            netloc = f"{parsed.username}@{netloc}" if netloc else parsed.username
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    parts = []
    for token in dsn.split():
        if "=" in token:
            key, _, _ = token.partition("=")
            if key.strip().lower() == "password":
                parts.append("password=<redacted>")
                continue
        parts.append(token)
    return " ".join(parts)


def file_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return path.stat().st_size


def backup_sqlite(source_path: Path, backup_path: Path) -> None:
    if backup_path.exists():
        backup_path.unlink()
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(source_path))
    try:
        dst = sqlite3.connect(str(backup_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def verify_sqlite_backup(backup_path: Path) -> tuple[str, str]:
    conn = sqlite3.connect(str(backup_path))
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    finally:
        conn.close()
    if rows and rows[0][0] == "ok":
        return "ok", "PRAGMA integrity_check returned ok"
    return "error", f"PRAGMA integrity_check returned: {rows!r}"


def run_pg_dump(dsn: str, backup_path: Path, *, dump_format: str) -> str:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "pg_dump",
        dsn,
        f"--format={dump_format}",
        f"--file={backup_path}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"pg_dump exited {proc.returncode}: {proc.stderr.strip()}")
    return " ".join(["pg_dump", "<dsn-redacted>", f"--format={dump_format}", f"--file={backup_path}"])


def verify_pg_dump(backup_path: Path) -> tuple[str, str]:
    proc = subprocess.run(
        ["pg_restore", "--list", str(backup_path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return "error", f"pg_restore --list exited {proc.returncode}: {proc.stderr.strip()}"
    toc_line_count = sum(1 for line in proc.stdout.splitlines() if line and not line.startswith(";"))
    return "ok", f"pg_restore --list returned {toc_line_count} TOC entries"


def upload_s3(local_path: Path, target_uri: str) -> tuple[str, str]:
    """Lazy-imports boto3 and uploads `local_path` to `target_uri` (s3://bucket/key)."""
    if not target_uri.startswith("s3://"):
        return "error", f"unsupported S3 URI: {target_uri}"
    try:
        import boto3  # type: ignore
    except ImportError:
        return "error", "boto3 is required for S3 upload; install boto3"
    parsed = urlparse(target_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket or not key:
        return "error", f"S3 URI must include bucket and key: {target_uri}"
    client = boto3.client("s3")
    client.upload_file(str(local_path), bucket, key)
    return "uploaded", f"uploaded to s3://{bucket}/{key}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up the metadata sidecar DB (SQLite copy or pg_dump).")
    parser.add_argument("--db-path", default="", help="SQLite metadata DB source path")
    parser.add_argument("--db-dsn", default="", help="PostgreSQL metadata DB source DSN")
    parser.add_argument("--out-path", required=True, help="Backup file destination path")
    parser.add_argument(
        "--format",
        choices=("custom", "plain"),
        default="custom",
        help="pg_dump archive format (PostgreSQL backend only); ignored for SQLite",
    )
    parser.add_argument("--verify", action="store_true", help="Run PRAGMA integrity_check or pg_restore --list against the backup")
    parser.add_argument("--upload-s3", default="", help="Optional s3://bucket/key destination for the backup")
    parser.add_argument("--execute", action="store_true", help="Actually perform the S3 upload (default leaves it in planned mode)")
    parser.add_argument("--output", default="", help="Optional output path for the JSON report")
    parser.add_argument("--assert-ok", action="store_true", help="Exit non-zero if status != ok")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite the backup file if it already exists")
    args = parser.parse_args()

    if not args.db_path and not args.db_dsn:
        raise SystemExit("[ERROR] one of --db-path or --db-dsn is required")
    if args.db_path and args.db_dsn:
        raise SystemExit("[ERROR] --db-path and --db-dsn are mutually exclusive")

    backup_path = Path(args.out_path).resolve()
    if backup_path.exists() and not args.overwrite:
        raise SystemExit(f"[ERROR] backup output exists; pass --overwrite to replace: {backup_path}")

    backend = "sqlite" if args.db_path else "postgres"
    errors: list[str] = []
    backup_format: str | None = None
    backup_command: str | None = None
    source_size: int | None = None
    source_sha: str | None = None

    if backend == "sqlite":
        source_path = Path(args.db_path).resolve()
        if not source_path.is_file():
            raise SystemExit(f"[ERROR] metadata DB does not exist: {source_path}")
        if backup_path == source_path:
            raise SystemExit("[ERROR] backup output must differ from source DB path")
        try:
            backup_sqlite(source_path, backup_path)
            backup_format = "sqlite_backup_api"
            backup_command = "sqlite3.Connection.backup"
            source_size = file_size_bytes(source_path)
            source_sha = sha256_file(source_path)
        except Exception as exc:
            errors.append(f"sqlite backup failed: {exc}")
        source_db_path = str(source_path)
        source_db_dsn_redacted = None
    else:
        try:
            backup_command = run_pg_dump(args.db_dsn, backup_path, dump_format=args.format)
            backup_format = "pg_dump_custom" if args.format == "custom" else "pg_dump_plain"
        except FileNotFoundError:
            errors.append("pg_dump not found on PATH; install postgresql-client")
        except RuntimeError as exc:
            errors.append(str(exc))
        source_db_path = None
        source_db_dsn_redacted = redact_dsn(args.db_dsn)

    backup_size = file_size_bytes(backup_path)
    backup_sha = sha256_file(backup_path) if backup_path.is_file() else None

    verification: dict[str, Any] = {
        "enabled": bool(args.verify),
        "mode": None,
        "status": "skipped",
        "details": None,
    }
    if args.verify and not errors:
        try:
            if backend == "sqlite":
                verification["mode"] = "sqlite_integrity_check"
                v_status, v_details = verify_sqlite_backup(backup_path)
            else:
                verification["mode"] = "pg_restore_list"
                v_status, v_details = verify_pg_dump(backup_path)
            verification["status"] = v_status
            verification["details"] = v_details
            if v_status != "ok":
                errors.append(f"backup verification failed: {v_details}")
        except FileNotFoundError:
            verification["status"] = "error"
            verification["details"] = "pg_restore not found on PATH; install postgresql-client"
            errors.append("pg_restore not found on PATH")
        except Exception as exc:
            verification["status"] = "error"
            verification["details"] = str(exc)
            errors.append(f"backup verification raised: {exc}")

    s3_upload: dict[str, Any] = {
        "requested": bool(args.upload_s3),
        "executed": False,
        "target_uri": args.upload_s3 or None,
        "status": "skipped",
        "details": None,
    }
    if args.upload_s3:
        if not args.execute:
            s3_upload["status"] = "planned"
            s3_upload["details"] = "S3 upload skipped: pass --execute to actually upload"
        elif errors:
            s3_upload["status"] = "skipped"
            s3_upload["details"] = "skipped because backup step failed"
        else:
            try:
                up_status, up_details = upload_s3(backup_path, args.upload_s3)
                s3_upload["executed"] = up_status == "uploaded"
                s3_upload["status"] = up_status
                s3_upload["details"] = up_details
                if up_status != "uploaded":
                    errors.append(f"S3 upload failed: {up_details}")
            except Exception as exc:
                s3_upload["status"] = "error"
                s3_upload["details"] = str(exc)
                errors.append(f"S3 upload raised: {exc}")

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if not errors else "error",
        "backend": backend,
        "source": {
            "db_path": source_db_path,
            "db_dsn_redacted": source_db_dsn_redacted,
            "size_bytes": source_size,
            "sha256": source_sha,
        },
        "backup": {
            "path": str(backup_path),
            "size_bytes": backup_size,
            "sha256": backup_sha,
            "format": backup_format,
            "command": backup_command,
        },
        "verification": verification,
        "s3_upload": s3_upload,
    }
    if errors:
        report["errors"] = errors

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)

    if args.assert_ok and report["status"] != "ok":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
