#!/usr/bin/env python3
"""Repo-side metadata DB backup/restore drill.

This proves the local backup/restore path is not a blind file copy: a restore
can be bound to the backup report SHA-256, a restored DB must retain critical
rows, schema portability must pass, and a tampered backup must be rejected before
restore. Live PostgreSQL/HA remains operator-side evidence.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from metadata_db import apply_migrations, connect_db, sha256_file, utc_now


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "metadata_backup_restore_drill/v1"


def insert_probe_rows(db_path: Path, *, job_id: str) -> None:
    conn = connect_db(str(db_path))
    try:
        apply_migrations(conn)
        conn.execute(
            """
            INSERT INTO jobs (
                job_id, correlation_id, out_base, status,
                intersection_size, intersection_sum, imported_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                f"corr-{job_id}",
                str(db_path.parent / "probe_out"),
                "released",
                2,
                425,
                utc_now(),
            ),
        )
        conn.execute(
            """
            INSERT INTO audit_events (
                job_id, stage, event_type, ts_utc, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                job_id,
                "backup_restore_drill",
                "probe_inserted",
                utc_now(),
                json.dumps({"probe": True}, sort_keys=True),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def query_probe_rows(db_path: Path, *, job_id: str) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    try:
        job_count = int(conn.execute("SELECT COUNT(*) FROM jobs WHERE job_id = ?", (job_id,)).fetchone()[0])
        audit_count = int(conn.execute("SELECT COUNT(*) FROM audit_events WHERE job_id = ?", (job_id,)).fetchone()[0])
        migration_count = int(conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0])
    finally:
        conn.close()
    return {
        "job_count": job_count,
        "audit_event_count": audit_count,
        "migration_count": migration_count,
        "probe_rows_present": job_count == 1 and audit_count >= 1 and migration_count > 0,
    }


def run_json(cmd: list[str]) -> tuple[int, dict[str, Any] | None, str]:
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    payload = None
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = None
    return proc.returncode, payload, (proc.stderr or proc.stdout).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="Run repo-side metadata DB backup/restore drill.")
    ap.add_argument("--out", default="", help=f"Path to write {SCHEMA_ID}")
    args = ap.parse_args()

    findings: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="seccomp_metadata_backup_restore_") as tmpdir:
        root = Path(tmpdir)
        source_db = root / "source.db"
        backup_path = root / "metadata.backup.sqlite"
        restored_db = root / "restored.db"
        tampered_backup = root / "tampered.backup.sqlite"
        backup_report_path = root / "backup_report.json"
        restore_report_path = root / "restore_report.json"
        tampered_report_path = root / "restore_tampered_report.json"
        job_id = "backup-restore-drill-job"

        insert_probe_rows(source_db, job_id=job_id)
        source_sha = sha256_file(source_db)
        source_probe = query_probe_rows(source_db, job_id=job_id)

        backup_rc, backup_report, backup_error = run_json(
            [
                "python3",
                str(REPO_ROOT / "scripts" / "backup_metadata_db.py"),
                "--db-path",
                str(source_db),
                "--out-path",
                str(backup_path),
                "--verify",
                "--overwrite",
                "--output",
                str(backup_report_path),
                "--assert-ok",
            ]
        )
        if backup_rc != 0 or not backup_report or backup_report.get("status") != "ok":
            findings.append({
                "kind": "backup_failed",
                "message": "backup_metadata_db did not produce an ok report",
                "expected": "status=ok",
                "actual": backup_error or backup_report,
            })

        restore_rc, restore_report, restore_error = run_json(
            [
                "python3",
                str(REPO_ROOT / "scripts" / "restore_metadata_db.py"),
                "--backup-path",
                str(backup_path),
                "--backup-report",
                str(backup_report_path),
                "--out-db-path",
                str(restored_db),
                "--verify-portability",
                "--overwrite",
                "--output",
                str(restore_report_path),
                "--assert-ok",
            ]
        )
        restored_probe = query_probe_rows(restored_db, job_id=job_id) if restored_db.is_file() else {}
        if (
            restore_rc != 0
            or not restore_report
            or restore_report.get("status") != "ok"
            or restore_report.get("backup", {}).get("sha256_match") is not True
            or not restored_probe.get("probe_rows_present")
        ):
            findings.append({
                "kind": "restore_failed",
                "message": "restore did not bind backup SHA and preserve probe rows",
                "expected": {"status": "ok", "sha256_match": True, "probe_rows_present": True},
                "actual": {
                    "exit": restore_rc,
                    "report": restore_report,
                    "error": restore_error,
                    "restored_probe": restored_probe,
                },
            })

        tampered_backup.write_bytes(backup_path.read_bytes() + b"tamper")
        tampered_rc, tampered_report, tampered_error = run_json(
            [
                "python3",
                str(REPO_ROOT / "scripts" / "restore_metadata_db.py"),
                "--backup-path",
                str(tampered_backup),
                "--backup-report",
                str(backup_report_path),
                "--out-db-path",
                str(root / "tampered_restore.db"),
                "--verify-portability",
                "--overwrite",
                "--output",
                str(tampered_report_path),
                "--assert-ok",
            ]
        )
        tamper_denied = (
            tampered_rc != 0
            and isinstance(tampered_report, dict)
            and tampered_report.get("status") == "error"
            and tampered_report.get("backup", {}).get("sha256_match") is False
        )
        if not tamper_denied:
            findings.append({
                "kind": "tampered_backup_accepted",
                "message": "restore accepted a backup whose SHA-256 no longer matched the backup report",
                "expected": "restore exits non-zero with backup.sha256_match=false",
                "actual": {"exit": tampered_rc, "report": tampered_report, "error": tampered_error},
            })

        checks = {
            "source": {
                "db_path": str(source_db),
                "sha256": source_sha,
                "probe": source_probe,
            },
            "backup": {
                "exit_code": backup_rc,
                "status": backup_report.get("status") if backup_report else None,
                "sha256": backup_report.get("backup", {}).get("sha256") if backup_report else None,
                "verification_status": backup_report.get("verification", {}).get("status") if backup_report else None,
            },
            "restore": {
                "exit_code": restore_rc,
                "status": restore_report.get("status") if restore_report else None,
                "sha256_match": restore_report.get("backup", {}).get("sha256_match") if restore_report else None,
                "portability_status": restore_report.get("portability_check", {}).get("status") if restore_report else None,
                "probe": restored_probe,
            },
            "tampered_restore_denied": {
                "exit_code": tampered_rc,
                "status": tampered_report.get("status") if tampered_report else None,
                "sha256_match": tampered_report.get("backup", {}).get("sha256_match") if tampered_report else None,
                "denied": tamper_denied,
            },
        }

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now(),
        "status": "fail" if findings else "ok",
        "summary": {
            "finding_count": len(findings),
            "repo_side_claim": "SQLite metadata backup/restore is SHA-bound to its backup report, schema-portability checked, and rejects tampered backups before restore",
            "production_boundary": "not live PostgreSQL/Patroni/pgBouncer HA evidence; operators still need target-environment switchover, external backup storage, and restore drills",
        },
        "checks": checks,
        "findings": findings,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
