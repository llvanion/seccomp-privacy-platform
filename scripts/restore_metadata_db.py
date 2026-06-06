#!/usr/bin/env python3
"""F4-b: restore the metadata sidecar DB from a previous backup.

SQLite restore copies the backup file via the sqlite3 backup API into a fresh
target file. PostgreSQL restore invokes `pg_restore` (custom format) or `psql`
(plain SQL) against the destination DSN. Optional --verify-portability runs
check_metadata_schema_portability against the restored DB to confirm the
schema matches the current migration baseline.

S3 download (--download-s3) lazy-imports boto3. Without --execute it stays in
plan mode, so default contract smoke does not need AWS credentials.
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
from scripts.manage_metadata_db import build_status_report  # noqa: E402


SCHEMA_ID = "metadata_db_restore_report/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def redact_dsn(dsn: str) -> str:
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


def detect_backup_format(backup_path: Path) -> str | None:
    """Best-effort backup format detection.

    SQLite files start with `SQLite format 3\0`. pg_dump custom-format files
    start with `PGDMP`. Plain SQL dumps start with the comment header and are
    treated as `pg_dump_plain` only when the caller explicitly opts in.
    """
    try:
        with backup_path.open("rb") as fh:
            head = fh.read(16)
    except OSError:
        return None
    if head.startswith(b"SQLite format 3"):
        return "sqlite_backup_api"
    if head.startswith(b"PGDMP"):
        return "pg_dump_custom"
    return None


def restore_sqlite(backup_path: Path, restored_path: Path) -> None:
    if restored_path.exists():
        restored_path.unlink()
    restored_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(backup_path))
    try:
        dst = sqlite3.connect(str(restored_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def run_pg_restore(dsn: str, backup_path: Path, *, plain: bool) -> str:
    if plain:
        cmd = ["psql", dsn, "--file", str(backup_path)]
        redacted = ["psql", "<dsn-redacted>", "--file", str(backup_path)]
    else:
        cmd = ["pg_restore", "--dbname", dsn, "--no-owner", "--clean", "--if-exists", str(backup_path)]
        redacted = ["pg_restore", "--dbname", "<dsn-redacted>", "--no-owner", "--clean", "--if-exists", str(backup_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exited {proc.returncode}: {proc.stderr.strip()}")
    return " ".join(redacted)


def run_portability_check_postgres(dsn: str) -> tuple[str, str, dict[str, Any] | None]:
    """For Postgres restores, replay migrations against the restore DSN and emit metadata_schema_portability/v1."""
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "check_metadata_schema_portability.py"),
        "--db-dsn",
        dsn,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    report: dict[str, Any] | None = None
    if proc.stdout.strip():
        try:
            report = json.loads(proc.stdout)
        except json.JSONDecodeError:
            report = None
    if proc.returncode != 0:
        details = (proc.stderr or proc.stdout).strip().splitlines()
        return "error", details[-1] if details else f"exit code {proc.returncode}", report
    return "ok", "metadata_schema_portability/v1 returned ok", report


def run_portability_check_sqlite(restored_path: Path) -> tuple[str, str, dict[str, Any] | None]:
    """For SQLite restores, open the restored DB and confirm applied migrations match the expected baseline."""
    status = build_status_report(db_path=str(restored_path))
    pending = list(status.get("pending_migrations") or [])
    applied = list(status.get("applied_migrations") or [])
    if pending:
        return "error", f"restored DB is missing migrations: {pending}", status
    if not applied:
        return "error", "restored DB has no applied migrations", status
    return "ok", f"restored DB has {len(applied)} applied migrations and 0 pending", status


def download_s3(local_path: Path, source_uri: str) -> tuple[str, str]:
    if not source_uri.startswith("s3://"):
        return "error", f"unsupported S3 URI: {source_uri}"
    try:
        import boto3  # type: ignore
    except ImportError:
        return "error", "boto3 is required for S3 download; install boto3"
    parsed = urlparse(source_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket or not key:
        return "error", f"S3 URI must include bucket and key: {source_uri}"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    client = boto3.client("s3")
    client.download_file(bucket, key, str(local_path))
    return "downloaded", f"downloaded from s3://{bucket}/{key}"


def load_expected_backup_sha256(report_path: str) -> str:
    if not report_path:
        return ""
    payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("backup report must be a JSON object")
    if payload.get("schema") != "metadata_db_backup_report/v1":
        raise ValueError(f"unexpected backup report schema: {payload.get('schema')!r}")
    backup = payload.get("backup")
    if not isinstance(backup, dict):
        raise ValueError("backup report is missing backup object")
    value = backup.get("sha256")
    return str(value or "")


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore the metadata sidecar DB from a SQLite or pg_dump backup.")
    parser.add_argument("--backup-path", required=True, help="Backup file source path")
    parser.add_argument("--backup-report", default="", help="Optional metadata_db_backup_report/v1 whose backup.sha256 must match --backup-path before restore")
    parser.add_argument("--expect-backup-sha256", default="", help="Optional expected backup file SHA-256; rejects restore when it does not match")
    parser.add_argument("--out-db-path", default="", help="SQLite metadata DB destination path")
    parser.add_argument("--restore-dsn", default="", help="PostgreSQL destination DSN")
    parser.add_argument(
        "--format",
        choices=("auto", "sqlite", "custom", "plain"),
        default="auto",
        help="Backup file format; auto-detects between sqlite and pg_dump custom format",
    )
    parser.add_argument(
        "--verify-portability",
        action="store_true",
        help="Run check_metadata_schema_portability.py against the restored DB",
    )
    parser.add_argument("--download-s3", default="", help="Optional s3://bucket/key source for the backup file")
    parser.add_argument("--execute", action="store_true", help="Actually perform the S3 download (default leaves it in planned mode)")
    parser.add_argument("--output", default="", help="Optional output path for the JSON report")
    parser.add_argument("--assert-ok", action="store_true", help="Exit non-zero if status != ok")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite the restored DB file if it already exists")
    args = parser.parse_args()

    if not args.out_db_path and not args.restore_dsn:
        raise SystemExit("[ERROR] one of --out-db-path or --restore-dsn is required")
    if args.out_db_path and args.restore_dsn:
        raise SystemExit("[ERROR] --out-db-path and --restore-dsn are mutually exclusive")

    backup_path = Path(args.backup_path).resolve()

    errors: list[str] = []

    s3_download: dict[str, Any] = {
        "requested": bool(args.download_s3),
        "executed": False,
        "source_uri": args.download_s3 or None,
        "status": "skipped",
        "details": None,
    }
    if args.download_s3:
        if not args.execute:
            s3_download["status"] = "planned"
            s3_download["details"] = "S3 download skipped: pass --execute to actually download"
        else:
            try:
                d_status, d_details = download_s3(backup_path, args.download_s3)
                s3_download["executed"] = d_status == "downloaded"
                s3_download["status"] = d_status
                s3_download["details"] = d_details
                if d_status != "downloaded":
                    errors.append(f"S3 download failed: {d_details}")
            except Exception as exc:
                s3_download["status"] = "error"
                s3_download["details"] = str(exc)
                errors.append(f"S3 download raised: {exc}")

    if not backup_path.is_file() and not errors:
        raise SystemExit(f"[ERROR] backup file does not exist: {backup_path}")

    detected = detect_backup_format(backup_path) if backup_path.is_file() else None
    if args.format == "auto":
        backup_format = detected
    elif args.format == "sqlite":
        backup_format = "sqlite_backup_api"
    elif args.format == "custom":
        backup_format = "pg_dump_custom"
    else:
        backup_format = "pg_dump_plain"

    backup_size = file_size_bytes(backup_path)
    backup_sha = sha256_file(backup_path) if backup_path.is_file() else None
    expected_backup_sha = str(args.expect_backup_sha256 or "").strip()
    backup_report_sha = ""
    if args.backup_report:
        try:
            backup_report_sha = load_expected_backup_sha256(args.backup_report)
        except Exception as exc:
            errors.append(f"backup report validation failed: {exc}")
        if expected_backup_sha and backup_report_sha and expected_backup_sha != backup_report_sha:
            errors.append(
                "backup report SHA-256 does not match --expect-backup-sha256: "
                f"report={backup_report_sha} expected={expected_backup_sha}"
            )
        if not expected_backup_sha:
            expected_backup_sha = backup_report_sha
    backup_sha_match: bool | None = None
    if expected_backup_sha:
        backup_sha_match = backup_sha == expected_backup_sha
        if not backup_sha_match:
            errors.append(
                "backup SHA-256 mismatch: "
                f"expected={expected_backup_sha} actual={backup_sha}"
            )

    backend = "sqlite" if args.out_db_path else "postgres"
    restored_path: Path | None = None
    restored_command: str | None = None

    if not errors:
        if backend == "sqlite":
            if backup_format and backup_format != "sqlite_backup_api":
                errors.append(f"SQLite restore requires a SQLite backup file; got {backup_format}")
            else:
                restored_path = Path(args.out_db_path).resolve()
                if restored_path.exists() and not args.overwrite:
                    raise SystemExit(f"[ERROR] restored DB exists; pass --overwrite to replace: {restored_path}")
                if restored_path == backup_path:
                    raise SystemExit("[ERROR] restored DB path must differ from backup path")
                try:
                    restore_sqlite(backup_path, restored_path)
                    restored_command = "sqlite3.Connection.backup"
                except Exception as exc:
                    errors.append(f"sqlite restore failed: {exc}")
        else:
            if backup_format == "sqlite_backup_api":
                errors.append("PostgreSQL restore requires a pg_dump backup file; got SQLite")
            else:
                plain = backup_format == "pg_dump_plain"
                try:
                    restored_command = run_pg_restore(args.restore_dsn, backup_path, plain=plain)
                except FileNotFoundError:
                    tool = "psql" if plain else "pg_restore"
                    errors.append(f"{tool} not found on PATH; install postgresql-client")
                except RuntimeError as exc:
                    errors.append(str(exc))

    restored_size: int | None = None
    restored_sha: str | None = None
    if backend == "sqlite" and restored_path is not None and restored_path.is_file():
        restored_size = file_size_bytes(restored_path)
        restored_sha = sha256_file(restored_path)

    portability: dict[str, Any] = {
        "enabled": bool(args.verify_portability),
        "status": "skipped",
        "details": None,
    }
    if args.verify_portability and not errors:
        try:
            if backend == "sqlite" and restored_path is not None:
                p_status, p_details, p_report = run_portability_check_sqlite(restored_path)
            elif backend == "postgres":
                p_status, p_details, p_report = run_portability_check_postgres(args.restore_dsn)
            else:
                p_status, p_details, p_report = "skipped", "no restored DB target available", None
            portability["status"] = p_status
            portability["details"] = p_details
            if p_report is not None:
                portability["report"] = p_report
            if p_status not in ("ok", "skipped"):
                errors.append(f"portability check failed: {p_details}")
        except Exception as exc:
            portability["status"] = "error"
            portability["details"] = str(exc)
            errors.append(f"portability check raised: {exc}")

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if not errors else "error",
        "backend": backend,
        "backup": {
            "path": str(backup_path),
            "size_bytes": backup_size,
            "sha256": backup_sha,
            "expected_sha256": expected_backup_sha or None,
            "sha256_match": backup_sha_match,
            "report_path": str(Path(args.backup_report).resolve()) if args.backup_report else None,
            "format": backup_format,
        },
        "restore": {
            "db_path": str(restored_path) if restored_path is not None else None,
            "db_dsn_redacted": redact_dsn(args.restore_dsn) if args.restore_dsn else None,
            "size_bytes": restored_size,
            "sha256": restored_sha,
            "command": restored_command,
        },
        "portability_check": portability,
        "s3_download": s3_download,
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
