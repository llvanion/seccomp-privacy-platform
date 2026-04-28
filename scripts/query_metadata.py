#!/usr/bin/env python3
import argparse
import os
from typing import Any, NoReturn

from platform_metadata_lib import connect_sqlite, json_dumps, rows_to_dicts


def die(msg: str) -> NoReturn:
    raise SystemExit(f"[ERROR] {msg}")


def ensure_one_filter(args: argparse.Namespace) -> tuple[str, str]:
    filters = {
        "job_id": args.job_id,
        "caller": args.caller,
        "tenant_id": args.tenant_id,
        "dataset_id": args.dataset_id,
    }
    chosen = [(key, value) for key, value in filters.items() if value]
    if not chosen:
        die("one filter is required: --job-id, --caller, --tenant-id, or --dataset-id")
    if len(chosen) > 1:
        die("use exactly one filter at a time")
    return chosen[0]


def fetch_job_bundle(conn: Any, job_id: str) -> dict[str, Any]:
    job = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if job is None:
        return {}

    return {
        "job": dict(job),
        "stage_status": rows_to_dicts(conn.execute("SELECT * FROM job_stage_status WHERE job_id = ? ORDER BY stage_name", (job_id,)).fetchall()),
        "artifacts": rows_to_dicts(conn.execute("SELECT * FROM job_artifacts WHERE job_id = ? ORDER BY stage_name, artifact_type", (job_id,)).fetchall()),
        "state_transitions": rows_to_dicts(conn.execute("SELECT * FROM job_state_transitions WHERE job_id = ? ORDER BY transition_id", (job_id,)).fetchall()),
        "audit_event_counts": rows_to_dicts(
            conn.execute(
                """
                SELECT stage_name, event_source, COUNT(*) AS event_count
                FROM audit_events
                WHERE job_id = ?
                GROUP BY stage_name, event_source
                ORDER BY stage_name, event_source
                """,
                (job_id,),
            ).fetchall()
        ),
        "key_access_events": rows_to_dicts(conn.execute("SELECT * FROM key_access_events WHERE job_id = ? ORDER BY key_access_event_id", (job_id,)).fetchall()),
        "audit_chains": rows_to_dicts(conn.execute("SELECT * FROM audit_chains WHERE job_id = ? ORDER BY audit_chain_id", (job_id,)).fetchall()),
        "audit_seals": rows_to_dicts(conn.execute("SELECT * FROM audit_seals WHERE job_id = ? ORDER BY audit_seal_id", (job_id,)).fetchall()),
    }


def query_jobs(conn: Any, field_name: str, field_value: str) -> list[str]:
    rows = conn.execute(
        f"""
        SELECT job_id
        FROM jobs
        WHERE {field_name} = ?
        ORDER BY updated_at DESC, job_id
        """,
        (field_value,),
    ).fetchall()
    return [str(row["job_id"]) for row in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only metadata query CLI for imported control-plane job metadata.")
    ap.add_argument("--db-path", required=True, help="SQLite metadata DB path")
    ap.add_argument("--job-id", default="")
    ap.add_argument("--caller", default="")
    ap.add_argument("--tenant-id", default="")
    ap.add_argument("--dataset-id", default="")
    args = ap.parse_args()

    field_name, field_value = ensure_one_filter(args)
    db_path = os.path.abspath(args.db_path)
    if not os.path.isfile(db_path):
        die(f"missing metadata DB: {db_path}")

    with connect_sqlite(db_path) as conn:
        if field_name == "job_id":
            payload = fetch_job_bundle(conn, field_value)
            if not payload:
                die(f"job not found: {field_value}")
            print(json_dumps(payload))
            return 0

        job_ids = query_jobs(conn, field_name, field_value)
        payload = {
            "filter": {field_name: field_value},
            "job_count": len(job_ids),
            "jobs": [fetch_job_bundle(conn, job_id) for job_id in job_ids],
        }
        print(json_dumps(payload))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
