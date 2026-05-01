#!/usr/bin/env python3
import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import (  # noqa: E402
    connect_db,
    expected_migration_versions,
    row_to_dict,
    sha256_file,
    utc_now,
)
from scripts.query_metadata import query_entities, query_jobs  # noqa: E402


STATUS_SCHEMA = "metadata_db_status/v1"
BACKUP_SCHEMA = "metadata_db_backup/v1"
EXPORT_SCHEMA = "metadata_db_export/v1"

CORE_TABLES = (
    "schema_migrations",
    "tenants",
    "datasets",
    "services",
    "callers",
    "jobs",
    "job_artifacts",
    "job_stage_status",
    "audit_events",
    "audit_chains",
    "audit_seals",
    "policies",
    "policy_bindings",
    "caller_permissions",
    "key_access_events",
)


def sqlite_scalar(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(query, params).fetchone()
    if row is None:
        return None
    return row[0]


def load_status_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    table_counts: dict[str, int] = {}
    for table_name in CORE_TABLES:
        exists = sqlite_scalar(
            conn,
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        )
        if exists != 1:
            table_counts[table_name] = 0
            continue
        count = sqlite_scalar(conn, f"SELECT COUNT(*) FROM {table_name}")
        table_counts[table_name] = int(count or 0)

    return {
        "tenant_count": table_counts["tenants"],
        "dataset_count": table_counts["datasets"],
        "service_count": table_counts["services"],
        "caller_count": table_counts["callers"],
        "job_count": table_counts["jobs"],
        "artifact_count": table_counts["job_artifacts"],
        "stage_status_count": table_counts["job_stage_status"],
        "audit_event_count": table_counts["audit_events"],
        "audit_chain_count": table_counts["audit_chains"],
        "audit_seal_count": table_counts["audit_seals"],
        "policy_count": table_counts["policies"],
        "policy_binding_count": table_counts["policy_bindings"],
        "caller_permission_count": table_counts["caller_permissions"],
        "key_access_event_count": table_counts["key_access_events"],
        "latest_job_id": sqlite_scalar(
            conn,
            "SELECT job_id FROM jobs ORDER BY imported_at_utc DESC, job_id DESC LIMIT 1",
        ),
        "latest_imported_at_utc": sqlite_scalar(
            conn,
            "SELECT imported_at_utc FROM jobs ORDER BY imported_at_utc DESC, job_id DESC LIMIT 1",
        ),
        "latest_job_created_at_utc": sqlite_scalar(
            conn,
            "SELECT created_at_utc FROM jobs WHERE created_at_utc IS NOT NULL ORDER BY created_at_utc DESC, job_id DESC LIMIT 1",
        ),
        "latest_policy_imported_at_utc": sqlite_scalar(
            conn,
            "SELECT imported_at_utc FROM policies ORDER BY imported_at_utc DESC, policy_id DESC LIMIT 1",
        ),
        "table_counts": table_counts,
    }


def applied_migrations(conn: sqlite3.Connection) -> list[str]:
    exists = sqlite_scalar(
        conn,
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'",
    )
    if exists != 1:
        return []
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    ]


def build_status_report(db_path: str) -> dict[str, Any]:
    path = Path(db_path).resolve()
    if not path.is_file():
        raise SystemExit(f"[ERROR] metadata DB does not exist: {path}")
    conn = connect_db(str(path))
    try:
        sqlite_version = sqlite_scalar(conn, "SELECT sqlite_version()")
        applied = applied_migrations(conn)
        expected = expected_migration_versions()
        pending = [version for version in expected if version not in applied]
        summary = load_status_summary(conn)
    finally:
        conn.close()

    warnings: list[str] = []
    if pending:
        warnings.append("pending_migrations")
    if summary["job_count"] == 0:
        warnings.append("no_jobs_imported")

    return {
        "schema": STATUS_SCHEMA,
        "generated_at_utc": utc_now(),
        "db_path": str(path),
        "status": "warn" if warnings else "ok",
        "sqlite_version": str(sqlite_version or ""),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "applied_migrations": applied,
        "expected_migrations": expected,
        "pending_migrations": pending,
        "summary": summary,
        "warnings": warnings,
    }


def write_json(path_value: str, payload: dict[str, Any]) -> str:
    path = Path(path_value)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def ensure_output_path(out_path: str, *, overwrite: bool) -> Path:
    path = Path(out_path)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    if path.exists() and not overwrite:
        raise SystemExit(f"[ERROR] output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def cmd_status(args: argparse.Namespace) -> int:
    report = build_status_report(args.db_path)
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    source_path = Path(args.db_path).resolve()
    if not source_path.is_file():
        raise SystemExit(f"[ERROR] metadata DB does not exist: {source_path}")
    backup_path = ensure_output_path(args.out_path, overwrite=args.overwrite)
    if backup_path == source_path:
        raise SystemExit("[ERROR] backup output must differ from source DB path")

    source_conn = connect_db(str(source_path))
    try:
        if backup_path.exists():
            backup_path.unlink()
        dest_conn = sqlite3.connect(str(backup_path))
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
        status = build_status_report(str(source_path))
    finally:
        source_conn.close()

    report = {
        "schema": BACKUP_SCHEMA,
        "generated_at_utc": utc_now(),
        "status": "ok",
        "source_db_path": str(source_path),
        "backup_db_path": str(backup_path),
        "source_sha256": sha256_file(source_path),
        "backup_sha256": sha256_file(backup_path),
        "source_size_bytes": source_path.stat().st_size,
        "backup_size_bytes": backup_path.stat().st_size,
        "applied_migrations": status["applied_migrations"],
        "used_sqlite_backup_api": True,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def export_entities(conn: sqlite3.Connection, *, limit: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for entity_name in (
        "tenants",
        "datasets",
        "services",
        "callers",
        "policies",
        "policy-bindings",
        "caller-permissions",
    ):
        result[entity_name] = query_entities(conn, entity=entity_name, limit=limit)
    return result


def cmd_export_json(args: argparse.Namespace) -> int:
    db_path = Path(args.db_path).resolve()
    if not db_path.is_file():
        raise SystemExit(f"[ERROR] metadata DB does not exist: {db_path}")
    if args.job_limit <= 0 or args.entity_limit <= 0:
        raise SystemExit("[ERROR] --job-limit and --entity-limit must be positive")
    out_path = ensure_output_path(args.out_path, overwrite=args.overwrite)

    conn = connect_db(str(db_path))
    try:
        status = build_status_report(str(db_path))
        jobs = query_jobs(conn, limit=args.job_limit)
        entities = export_entities(conn, limit=args.entity_limit)
        sample_artifacts = [
            row_to_dict(row)
            for row in conn.execute(
                """
                SELECT job_id, stage, artifact_type, path, sha256, file_format, exists_on_disk
                FROM job_artifacts
                ORDER BY job_id DESC, stage ASC, artifact_type ASC
                LIMIT ?
                """,
                (args.artifact_limit,),
            ).fetchall()
        ]
    finally:
        conn.close()

    export_payload = {
        "schema": EXPORT_SCHEMA,
        "generated_at_utc": utc_now(),
        "db_path": str(db_path),
        "out_path": str(out_path),
        "job_limit": args.job_limit,
        "entity_limit": args.entity_limit,
        "artifact_limit": args.artifact_limit,
        "status": status,
        "jobs": jobs,
        "entities": entities,
        "sample_artifacts": sample_artifacts,
    }
    out_path.write_text(json.dumps(export_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(export_payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Manage the SQLite metadata sidecar lifecycle.")
    sub = ap.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Report metadata DB status, migrations, and table counts.")
    status.add_argument("--db-path", required=True)
    status.add_argument("--output", default="")

    backup = sub.add_parser("backup", help="Create a consistent SQLite backup copy with the backup API.")
    backup.add_argument("--db-path", required=True)
    backup.add_argument("--out-path", required=True)
    backup.add_argument("--overwrite", action="store_true")

    export_json = sub.add_parser("export-json", help="Export a portable JSON snapshot of the metadata sidecar.")
    export_json.add_argument("--db-path", required=True)
    export_json.add_argument("--out-path", required=True)
    export_json.add_argument("--job-limit", type=int, default=20)
    export_json.add_argument("--entity-limit", type=int, default=20)
    export_json.add_argument("--artifact-limit", type=int, default=20)
    export_json.add_argument("--overwrite", action="store_true")

    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "status":
        return cmd_status(args)
    if args.command == "backup":
        return cmd_backup(args)
    return cmd_export_json(args)


if __name__ == "__main__":
    raise SystemExit(main())
