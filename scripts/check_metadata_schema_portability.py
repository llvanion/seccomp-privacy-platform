#!/usr/bin/env python3
import argparse
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from metadata_db import MIGRATIONS_DIR, apply_migrations, connect_db, database_backend, database_version, table_exists, utc_now


SCHEMA_ID = "metadata_schema_portability/v1"
SQLITE_ONLY_TOKENS = ("PRAGMA", "AUTOINCREMENT")
EXPECTED_INDEXES = (
    "idx_jobs_caller",
    "idx_jobs_tenant_dataset",
    "idx_jobs_service_id",
    "idx_job_artifacts_job_id",
    "idx_job_stage_status_job_id",
    "idx_audit_events_job_stage",
    "idx_key_access_events_job_id",
    "idx_privacy_budget_source_job_id",
    "idx_privacy_budget_ledger_job_id",
    "idx_privacy_budget_scope",
    "idx_privacy_budget_decision",
    "idx_key_refs_service_id",
    "idx_key_refs_purpose",
    "idx_key_versions_key_name",
    "idx_control_plane_mutations_entity",
    "idx_control_plane_mutations_actor",
    "idx_control_plane_mutations_applied_at",
    "idx_issuer_registry_type",
    "idx_issuer_registry_enabled",
    "idx_job_state_transitions_job_id",
    "idx_job_state_transitions_state",
    "idx_job_state_transitions_ts",
    "idx_policy_versions_policy_id",
    "idx_policy_versions_path_current",
    "idx_service_versions_service_id",
    "idx_service_versions_current",
    "idx_catalog_lineage_job_id",
    "idx_catalog_lineage_dataset_service",
    "idx_catalog_lineage_kind",
    "idx_retention_reconcile_scope",
    "idx_retention_reconcile_job",
    "idx_retention_reconcile_action",
    "idx_workflow_submissions_submission_id",
    "idx_workflow_submissions_status",
    "idx_workflow_submissions_tenant_status",
    "idx_workflow_submissions_caller",
    "idx_workflow_submissions_job_id",
    "idx_query_workflow_executions_state",
    "idx_query_workflow_executions_lease",
    "idx_query_workflow_executions_tenant",
    "idx_query_workflow_executions_digest",
)


def list_tables(conn: Any) -> list[str]:
    if database_backend(conn) == "postgres":
        return [
            str(row[0])
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name"
            ).fetchall()
        ]
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]


def list_indexes(conn: Any) -> list[str]:
    if database_backend(conn) == "postgres":
        return [
            str(row[0])
            for row in conn.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                ORDER BY indexname
                """
            ).fetchall()
        ]
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]


def table_info(conn: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    return [
        {
            "cid": int(row[0]),
            "name": str(row[1]),
            "type": str(row[2] or ""),
            "notnull": bool(row[3]),
            "default_value": row[4],
            "pk_ordinal": int(row[5]),
        }
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    ]


def foreign_keys(conn: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    return [
        {
            "from": str(row[3]),
            "to": str(row[4]),
            "ref_table": str(row[2]),
        }
        for row in conn.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
    ]


def migration_sqlite_only_constructs() -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        text = migration_path.read_text(encoding="utf-8")
        upper = text.upper()
        for token in SQLITE_ONLY_TOKENS:
            if token in upper:
                findings.append(
                    {
                        "migration": migration_path.name,
                        "token": token,
                    }
                )
    return findings


def build_check(name: str, *, ok: bool, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "status": "ok" if ok else "fail",
        "details": details,
    }


def run_postgres_import_query_smoke(conn: Any, *, out_base: str, job_id: str) -> dict[str, Any]:
    from import_run_metadata import import_runs
    from query_metadata import query_job_detail

    imported = import_runs(conn, [Path(out_base).resolve()], dry_run=False)
    query_id = job_id.strip() or str((imported.get("imports") or [{}])[0].get("job_id") or "")
    if not query_id:
        raise ValueError("could not infer job_id for PostgreSQL import/query smoke")
    detail = query_job_detail(conn, query_id)
    job = detail.get("job") or {}
    stage_status = detail.get("stage_status") or []
    return {
        "out_base": str(Path(out_base).resolve()),
        "job_id": query_id,
        "import_mode": imported.get("mode"),
        "import_summary": imported.get("summary"),
        "queried_status": job.get("status"),
        "queried_tenant_id": job.get("tenant_id"),
        "queried_dataset_id": job.get("dataset_id"),
        "queried_service_id": job.get("service_id"),
        "stage_status_count": len(stage_status),
        "audit_event_count": len(detail.get("audit_events") or []),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Check metadata DB migrations for SQLite/PostgreSQL portability baseline.")
    ap.add_argument("--db-dsn", default="", help="Optional PostgreSQL DSN for a live migration smoke")
    ap.add_argument("--smoke-out-base", default="", help="Optional pipeline run directory to import/query during PostgreSQL live smoke")
    ap.add_argument("--smoke-job-id", default="", help="Optional job_id to query after --smoke-out-base import")
    ap.add_argument("--output", default="", help="Optional path to write the JSON report")
    args = ap.parse_args()

    checks: list[dict[str, Any]] = []
    sqlite_only = migration_sqlite_only_constructs()
    checks.append(
        build_check(
            "sqlite_only_constructs",
            ok=not sqlite_only,
            details={"findings": sqlite_only},
        )
    )

    backend = "sqlite"
    db_version = ""
    postgres_import_query_smoke: dict[str, Any] | None = None
    postgres_import_query_error = ""
    with tempfile.TemporaryDirectory(prefix="seccomp_metadata_portability_") as tmpdir:
        db_path = Path(tmpdir) / "metadata_portability.db"
        conn = connect_db("" if args.db_dsn else str(db_path), dsn=args.db_dsn)
        try:
            applied = apply_migrations(conn)
            backend = database_backend(conn)
            db_version = database_version(conn)
            tables = list_tables(conn)
            indexes = list_indexes(conn)
            table_infos = {table_name: table_info(conn, table_name) for table_name in tables} if backend == "sqlite" else {}
            fk_infos = {table_name: foreign_keys(conn, table_name) for table_name in tables} if backend == "sqlite" else {}
            if backend == "postgres" and args.smoke_out_base:
                try:
                    postgres_import_query_smoke = run_postgres_import_query_smoke(
                        conn,
                        out_base=args.smoke_out_base,
                        job_id=args.smoke_job_id,
                    )
                except (Exception, SystemExit) as exc:
                    postgres_import_query_error = str(exc)
        finally:
            conn.close()

    if backend == "sqlite":
        tables_without_pk = sorted(
            table_name
            for table_name, columns in table_infos.items()
            if not any(column["pk_ordinal"] > 0 for column in columns)
        )
        checks.append(
            build_check(
                "primary_keys_present",
                ok=not tables_without_pk,
                details={"tables_without_primary_key": tables_without_pk},
            )
        )

        bad_utc_columns = sorted(
            {
                f"{table_name}.{column['name']}"
                for table_name, columns in table_infos.items()
                for column in columns
                if column["name"].endswith("_utc") and column["type"].upper() != "TEXT"
            }
        )
        checks.append(
            build_check(
                "utc_columns_use_text",
                ok=not bad_utc_columns,
                details={"columns": bad_utc_columns},
            )
        )

        bad_json_columns = sorted(
            {
                f"{table_name}.{column['name']}"
                for table_name, columns in table_infos.items()
                for column in columns
                if column["name"].endswith("_json") and column["type"].upper() != "TEXT"
            }
        )
        checks.append(
            build_check(
                "json_columns_use_text",
                ok=not bad_json_columns,
                details={"columns": bad_json_columns},
            )
        )

    missing_indexes = sorted(index_name for index_name in EXPECTED_INDEXES if index_name not in indexes)
    checks.append(
        build_check(
            "expected_indexes_present",
            ok=not missing_indexes,
            details={"missing_indexes": missing_indexes},
        )
    )

    if backend == "sqlite":
        unknown_fk_targets = sorted(
            {
                f"{table_name}.{fk['from']}->{fk['ref_table']}.{fk['to']}"
                for table_name, fk_rows in fk_infos.items()
                for fk in fk_rows
                if fk["ref_table"] not in table_infos
            }
        )
        checks.append(
            build_check(
                "foreign_key_targets_present",
                ok=not unknown_fk_targets,
                details={"unknown_foreign_key_targets": unknown_fk_targets},
            )
        )
    else:
        checks.append(
            build_check(
                "postgres_live_migration_smoke",
                ok="schema_migrations" in tables and len(applied) == len(list(MIGRATIONS_DIR.glob("*.sql"))),
                details={"db_dsn": bool(args.db_dsn), "table_count": len(tables)},
            )
        )
        if args.smoke_out_base:
            details = postgres_import_query_smoke or {"error": postgres_import_query_error}
            checks.append(
                build_check(
                    "postgres_live_import_query_smoke",
                    ok=postgres_import_query_smoke is not None
                    and int(postgres_import_query_smoke.get("stage_status_count") or 0) > 0
                    and int(postgres_import_query_smoke.get("audit_event_count") or 0) > 0,
                    details=details,
                )
            )

    status = "ok" if all(check["status"] == "ok" for check in checks) else "fail"
    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now(),
        "status": status,
        "backend": backend,
        "database_version": db_version,
        "migrations_dir": str(MIGRATIONS_DIR.resolve()),
        "applied_migrations": applied,
        "summary": {
            "table_count": len(tables),
            "index_count": len(indexes),
            "foreign_key_count": sum(len(items) for items in fk_infos.values()),
            "utc_text_column_count": sum(
                1
                for columns in table_infos.values()
                for column in columns
                if column["name"].endswith("_utc") and column["type"].upper() == "TEXT"
            ),
            "json_text_column_count": sum(
                1
                for columns in table_infos.values()
                for column in columns
                if column["name"].endswith("_json") and column["type"].upper() == "TEXT"
            ),
            "sqlite_only_construct_count": len(sqlite_only),
        },
        "checks": checks,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
