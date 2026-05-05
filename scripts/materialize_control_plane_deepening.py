#!/usr/bin/env python3
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import apply_migrations, connect_db, row_to_dict, utc_now  # noqa: E402


SCHEMA_ID = "control_plane_deepening_report/v1"
DERIVED_TABLES = (
    "job_state_transitions",
    "policy_versions",
    "service_versions",
    "catalog_lineage_read_model",
    "retention_reconcile_plan",
)


def fetch_all(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [row_to_dict(row) for row in conn.execute(query, params).fetchall()]


def fetch_scalar(conn: sqlite3.Connection, query: str, params: tuple = ()) -> Any:
    row = conn.execute(query, params).fetchone()
    return row[0] if row is not None else None


def load_json_object(path: str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_version(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json_text(payload).encode("utf-8")).hexdigest()[:12]


def clear_derived_tables(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table_name in DERIVED_TABLES:
        counts[table_name] = int(fetch_scalar(conn, f"SELECT COUNT(*) FROM {table_name}") or 0)
        conn.execute(f"DELETE FROM {table_name}")
    return counts


def build_job_transitions(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    jobs = fetch_all(
        conn,
        """
        SELECT job_id, status, imported_at_utc, created_at_utc, correlation_id, caller,
               tenant_id, dataset_id, service_id
        FROM jobs
        ORDER BY imported_at_utc ASC, job_id ASC
        """,
    )
    rows: list[tuple[Any, ...]] = []
    for job in jobs:
        job_id = str(job["job_id"])
        previous_state: str | None = None
        ordinal = 1

        def add_transition(
            *,
            to_state: str,
            stage: str | None,
            event_type: str,
            ts_utc: str | None,
            source: str,
            source_event_id: int | None = None,
            details: dict[str, Any] | None = None,
        ) -> None:
            nonlocal ordinal, previous_state
            rows.append(
                (
                    job_id,
                    ordinal,
                    previous_state,
                    to_state,
                    stage,
                    event_type,
                    ts_utc,
                    source,
                    source_event_id,
                    json_text(details or {}),
                )
            )
            previous_state = to_state
            ordinal += 1

        add_transition(
            to_state="imported",
            stage="metadata_import",
            event_type="job_imported",
            ts_utc=job.get("imported_at_utc") or job.get("created_at_utc"),
            source="jobs",
            details={
                "correlation_id": job.get("correlation_id"),
                "caller": job.get("caller"),
                "tenant_id": job.get("tenant_id"),
                "dataset_id": job.get("dataset_id"),
                "service_id": job.get("service_id"),
            },
        )

        for stage_row in fetch_all(
            conn,
            """
            SELECT id, stage, status, ts_utc, duration_ms, details_json
            FROM job_stage_status
            WHERE job_id = ?
            ORDER BY COALESCE(ts_utc, ''), id
            """,
            (job_id,),
        ):
            add_transition(
                to_state=f"stage:{stage_row['stage']}:{stage_row['status']}",
                stage=str(stage_row["stage"]),
                event_type="stage_status",
                ts_utc=stage_row.get("ts_utc") or job.get("imported_at_utc"),
                source="job_stage_status",
                source_event_id=int(stage_row["id"]),
                details={
                    "duration_ms": stage_row.get("duration_ms"),
                    "details": json.loads(stage_row["details_json"]) if stage_row.get("details_json") else {},
                },
            )

        final_status = str(job.get("status") or "unknown")
        if previous_state != final_status:
            add_transition(
                to_state=final_status,
                stage="job",
                event_type="job_status",
                ts_utc=job.get("imported_at_utc"),
                source="jobs",
                details={"status": final_status},
            )
    return rows


def insert_job_transitions(conn: sqlite3.Connection, rows: list[tuple[Any, ...]]) -> None:
    conn.executemany(
        """
        INSERT INTO job_state_transitions(
          job_id, transition_ordinal, from_state, to_state, stage, event_type, ts_utc,
          source, source_event_id, details_json
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def build_policy_versions(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for policy in fetch_all(
        conn,
        """
        SELECT p.policy_id, p.policy_kind, p.path, p.sha256, p.schema_name, p.imported_at_utc,
               COUNT(DISTINCT pb.id) AS binding_count,
               COUNT(DISTINCT cp.id) AS permission_count
        FROM policies p
        LEFT JOIN policy_bindings pb ON pb.policy_id = p.policy_id
        LEFT JOIN caller_permissions cp ON cp.policy_id = p.policy_id
        GROUP BY p.policy_id, p.policy_kind, p.path, p.sha256, p.schema_name, p.imported_at_utc
        ORDER BY p.imported_at_utc ASC, p.policy_id ASC
        """,
    ):
        version = str(policy.get("sha256") or "")[:12] or stable_version(policy)
        rows.append(
            (
                policy["policy_id"],
                policy["policy_kind"],
                policy["path"],
                version,
                policy.get("sha256"),
                policy.get("schema_name"),
                policy["imported_at_utc"],
                1,
                json_text(
                    {
                        "binding_count": policy.get("binding_count") or 0,
                        "permission_count": policy.get("permission_count") or 0,
                    }
                ),
            )
        )
    return rows


def insert_policy_versions(conn: sqlite3.Connection, rows: list[tuple[Any, ...]]) -> None:
    conn.executemany(
        """
        INSERT INTO policy_versions(
          policy_id, policy_kind, path, version, sha256, schema_name, imported_at_utc,
          is_current, metadata_json
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def build_service_versions(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for service in fetch_all(
        conn,
        """
        SELECT service_id, tenant_id, dataset_id, service_type, transport, config_path,
               created_at_utc, last_seen_job_id
        FROM services
        ORDER BY created_at_utc ASC, service_id ASC
        """,
    ):
        version_payload = {
            "service_id": service.get("service_id"),
            "tenant_id": service.get("tenant_id"),
            "dataset_id": service.get("dataset_id"),
            "service_type": service.get("service_type"),
            "transport": service.get("transport"),
            "config_path": service.get("config_path"),
        }
        rows.append(
            (
                service["service_id"],
                stable_version(version_payload),
                service.get("tenant_id"),
                service.get("dataset_id"),
                service.get("service_type"),
                service.get("transport"),
                service.get("config_path"),
                service.get("created_at_utc") or utc_now(),
                1,
                json_text({"last_seen_job_id": service.get("last_seen_job_id")}),
            )
        )
    return rows


def insert_service_versions(conn: sqlite3.Connection, rows: list[tuple[Any, ...]]) -> None:
    conn.executemany(
        """
        INSERT INTO service_versions(
          service_id, version, tenant_id, dataset_id, service_type, transport, config_path,
          effective_at_utc, is_current, metadata_json
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def first_existing_job(conn: sqlite3.Connection) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(
            """
            SELECT job_id, correlation_id, caller, tenant_id, dataset_id, service_id, imported_at_utc
            FROM jobs
            ORDER BY imported_at_utc DESC, job_id ASC
            LIMIT 1
            """
        ).fetchone()
    )


def build_catalog_lineage_rows(
    conn: sqlite3.Connection, catalog_lineage: dict[str, Any] | None
) -> list[tuple[Any, ...]]:
    if not catalog_lineage:
        return []
    job = first_existing_job(conn)
    if not job:
        return []
    scope = {
        "job_id": catalog_lineage.get("job_id") or job.get("job_id"),
        "correlation_id": catalog_lineage.get("correlation_id") or job.get("correlation_id"),
        "caller": catalog_lineage.get("caller") or job.get("caller"),
        "tenant_id": catalog_lineage.get("tenant_id") or job.get("tenant_id"),
        "dataset_id": catalog_lineage.get("dataset_id") or job.get("dataset_id"),
        "service_id": catalog_lineage.get("service_id") or job.get("service_id"),
        "imported_at_utc": job.get("imported_at_utc") or utc_now(),
    }
    rows: list[tuple[Any, ...]] = []

    def append_row(
        *,
        lineage_kind: str,
        node_id: str,
        node_type: str | None,
        display_name: str | None,
        role: str | None = None,
        stage: str | None = None,
        source_id: str | None = None,
        target_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        metadata = metadata or {}
        rows.append(
            (
                scope["job_id"],
                scope["correlation_id"],
                scope["caller"],
                scope["tenant_id"],
                scope["dataset_id"],
                scope["service_id"],
                lineage_kind,
                node_id,
                node_type,
                display_name,
                role,
                stage,
                source_id,
                target_id,
                0 if metadata.get("path") else 1,
                json_text(metadata),
                scope["imported_at_utc"],
            )
        )

    for dataset in catalog_lineage.get("datasets") or []:
        if not isinstance(dataset, dict):
            continue
        append_row(
            lineage_kind="dataset",
            node_id=str(dataset.get("id") or dataset.get("dataset_id") or "dataset:unknown"),
            node_type="dataset",
            display_name=str(dataset.get("dataset_id") or dataset.get("id") or "dataset"),
            metadata=dataset,
        )
    for service in catalog_lineage.get("services") or []:
        if not isinstance(service, dict):
            continue
        append_row(
            lineage_kind="service",
            node_id=str(service.get("id") or service.get("service_id") or "service:unknown"),
            node_type=str(service.get("service_type") or "service"),
            display_name=str(service.get("service_id") or service.get("id") or "service"),
            metadata=service,
        )
    for artifact in catalog_lineage.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        append_row(
            lineage_kind="artifact",
            node_id=str(artifact.get("id") or artifact.get("sha256") or "artifact:unknown"),
            node_type=str(artifact.get("artifact_type") or "artifact"),
            display_name=str(artifact.get("artifact_type") or artifact.get("id") or "artifact"),
            role=str(artifact.get("role")) if artifact.get("role") else None,
            stage=str(artifact.get("stage")) if artifact.get("stage") else None,
            metadata=artifact,
        )
    for idx, edge in enumerate(catalog_lineage.get("lineage_edges") or [], start=1):
        if not isinstance(edge, dict):
            continue
        source_id = str(edge.get("source") or "")
        target_id = str(edge.get("target") or "")
        append_row(
            lineage_kind="edge",
            node_id=f"edge:{idx}:{source_id}->{target_id}",
            node_type=str(edge.get("relationship") or "edge"),
            display_name=str(edge.get("relationship") or "edge"),
            stage=str(edge.get("stage")) if edge.get("stage") else None,
            source_id=source_id,
            target_id=target_id,
            metadata=edge,
        )
    return rows


def insert_catalog_lineage_rows(conn: sqlite3.Connection, rows: list[tuple[Any, ...]]) -> None:
    conn.executemany(
        """
        INSERT INTO catalog_lineage_read_model(
          job_id, correlation_id, caller, tenant_id, dataset_id, service_id, lineage_kind,
          node_id, node_type, display_name, role, stage, source_id, target_id, path_redacted,
          metadata_json, imported_at_utc
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def build_retention_plan(conn: sqlite3.Connection, generated_at: str) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []

    def append(
        *,
        scope: str,
        entity_type: str,
        entity_id: str,
        job_id: str | None,
        retention_class: str,
        action: str,
        reason_code: str,
        details: dict[str, Any],
    ) -> None:
        rows.append(
            (
                scope,
                entity_type,
                entity_id,
                job_id,
                retention_class,
                action,
                reason_code,
                0,
                generated_at,
                json_text(details),
            )
        )

    for job in fetch_all(conn, "SELECT job_id, status, imported_at_utc FROM jobs ORDER BY imported_at_utc ASC"):
        job_id = str(job["job_id"])
        audit_count = int(fetch_scalar(conn, "SELECT COUNT(*) FROM audit_events WHERE job_id = ?", (job_id,)) or 0)
        append(
            scope="job",
            entity_type="job",
            entity_id=job_id,
            job_id=job_id,
            retention_class="audit",
            action="retain",
            reason_code="audit_chain_present",
            details={"status": job.get("status"), "audit_event_count": audit_count},
        )
        if audit_count == 0:
            append(
                scope="job",
                entity_type="audit_events",
                entity_id=f"{job_id}:audit_events",
                job_id=job_id,
                retention_class="reconcile",
                action="review",
                reason_code="missing_audit_events",
                details={"status": job.get("status")},
            )

    for policy in fetch_all(conn, "SELECT policy_id, path, imported_at_utc FROM policies ORDER BY imported_at_utc ASC"):
        append(
            scope="registry",
            entity_type="policy",
            entity_id=str(policy["policy_id"]),
            job_id=None,
            retention_class="policy",
            action="retain",
            reason_code="policy_registered",
            details={"path": policy.get("path"), "imported_at_utc": policy.get("imported_at_utc")},
        )

    for key_ref in fetch_all(conn, "SELECT key_name, purpose, service_id, updated_at_utc FROM key_refs ORDER BY updated_at_utc ASC"):
        append(
            scope="registry",
            entity_type="key_ref",
            entity_id=str(key_ref["key_name"]),
            job_id=None,
            retention_class="key_lifecycle",
            action="retain",
            reason_code="key_metadata_registered",
            details={"purpose": key_ref.get("purpose"), "service_id": key_ref.get("service_id")},
        )
    return rows


def insert_retention_plan(conn: sqlite3.Connection, rows: list[tuple[Any, ...]]) -> None:
    conn.executemany(
        """
        INSERT INTO retention_reconcile_plan(
          scope, entity_type, entity_id, job_id, retention_class, recommended_action,
          reason_code, reviewed, created_at_utc, details_json
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def count_table(conn: sqlite3.Connection, table_name: str) -> int:
    return int(fetch_scalar(conn, f"SELECT COUNT(*) FROM {table_name}") or 0)


def main() -> int:
    ap = argparse.ArgumentParser(description="Materialize C1-C5 post-baseline SQL control-plane read models.")
    ap.add_argument("--db-path", required=True)
    ap.add_argument("--catalog-lineage", default="")
    ap.add_argument("--output", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--assert-ok", action="store_true")
    args = ap.parse_args()

    generated_at = utc_now()
    conn = connect_db(args.db_path)
    try:
        apply_migrations(conn)
        catalog_lineage = load_json_object(args.catalog_lineage) if args.catalog_lineage else None
        materialized = {
            "job_state_transitions": build_job_transitions(conn),
            "policy_versions": build_policy_versions(conn),
            "service_versions": build_service_versions(conn),
            "catalog_lineage_read_model": build_catalog_lineage_rows(conn, catalog_lineage),
            "retention_reconcile_plan": build_retention_plan(conn, generated_at),
        }
        previous_counts = {table_name: count_table(conn, table_name) for table_name in DERIVED_TABLES}
        if not args.dry_run:
            clear_derived_tables(conn)
            insert_job_transitions(conn, materialized["job_state_transitions"])
            insert_policy_versions(conn, materialized["policy_versions"])
            insert_service_versions(conn, materialized["service_versions"])
            insert_catalog_lineage_rows(conn, materialized["catalog_lineage_read_model"])
            insert_retention_plan(conn, materialized["retention_reconcile_plan"])
            conn.commit()
        current_counts = {
            table_name: (count_table(conn, table_name) if not args.dry_run else previous_counts[table_name])
            for table_name in DERIVED_TABLES
        }
    finally:
        conn.close()

    actions = [
        {
            "action": "materialize" if not args.dry_run else "plan",
            "table": table_name,
            "count": len(rows),
            "previous_count": previous_counts[table_name],
            "current_count": current_counts[table_name],
        }
        for table_name, rows in materialized.items()
    ]
    summary = {
        "status": "ok",
        "job_transition_count": len(materialized["job_state_transitions"]),
        "policy_version_count": len(materialized["policy_versions"]),
        "service_version_count": len(materialized["service_versions"]),
        "catalog_lineage_count": len(materialized["catalog_lineage_read_model"]),
        "retention_plan_count": len(materialized["retention_reconcile_plan"]),
        "derived_table_count": len(DERIVED_TABLES),
    }
    if args.assert_ok and (
        summary["job_transition_count"] < 1
        or summary["policy_version_count"] < 1
        or summary["service_version_count"] < 1
        or summary["catalog_lineage_count"] < 1
        or summary["retention_plan_count"] < 1
    ):
        summary["status"] = "fail"

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": generated_at,
        "db_path": str(Path(args.db_path).resolve()),
        "mode": "dry_run" if args.dry_run else "apply",
        "summary": summary,
        "actions": actions,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if summary["status"] != "ok" else 0


if __name__ == "__main__":
    raise SystemExit(main())
