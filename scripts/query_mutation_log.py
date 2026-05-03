#!/usr/bin/env python3
"""Query the control-plane mutation log from the metadata sidecar DB.

The control_plane_mutations table records every write operation performed
by manage_metadata_db.py apply-registry and related mutation tools,
providing an auditable trail of control-plane state changes over time.

Outputs mutation_log_query/v1.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import apply_migrations, connect_db, utc_now  # noqa: E402

SCHEMA_ID = "mutation_log_query/v1"


def query_mutations(
    conn,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor: str | None = None,
    operation: str | None = None,
    status: str | None = None,
    since_utc: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    where_clauses = []
    params: list = []

    if entity_type:
        where_clauses.append("entity_type = ?")
        params.append(entity_type)
    if entity_id:
        where_clauses.append("entity_id = ?")
        params.append(entity_id)
    if actor:
        where_clauses.append("actor = ?")
        params.append(actor)
    if operation:
        where_clauses.append("operation = ?")
        params.append(operation)
    if status:
        where_clauses.append("status = ?")
        params.append(status)
    if since_utc:
        where_clauses.append("applied_at_utc >= ?")
        params.append(since_utc)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM control_plane_mutations {where_sql}", params
    ).fetchone()[0]

    rows = conn.execute(
        f"""
        SELECT mutation_id, operation, entity_type, entity_id, actor, source,
               old_state_json, new_state_json, status, applied_at_utc, notes
        FROM control_plane_mutations
        {where_sql}
        ORDER BY applied_at_utc DESC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()

    records = []
    for row in rows:
        rec = dict(row)
        for json_field in ("old_state_json", "new_state_json"):
            if rec.get(json_field):
                try:
                    rec[json_field] = json.loads(rec[json_field])
                except (ValueError, TypeError):
                    pass
        records.append(rec)

    return records, total


def main() -> None:
    parser = argparse.ArgumentParser(description="Query control-plane mutation log")
    parser.add_argument("--db-path", required=True, help="Path to metadata SQLite DB")
    parser.add_argument("--entity-type", help="Filter by entity type (tenant/dataset/caller/key_ref/policy/…)")
    parser.add_argument("--entity-id", help="Filter by entity ID")
    parser.add_argument("--actor", help="Filter by actor (caller or tool name)")
    parser.add_argument("--operation", help="Filter by operation (upsert/delete/rotate/…)")
    parser.add_argument("--status", help="Filter by status (applied/rolled_back/failed)")
    parser.add_argument("--since-utc", help="Only return mutations applied at or after this UTC timestamp")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--output", default=None, help="Write JSON to file")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(json.dumps({"error": f"DB not found: {db_path}"}))
        sys.exit(1)

    conn = connect_db(str(db_path))
    apply_migrations(conn)

    records, total = query_mutations(
        conn,
        entity_type=args.entity_type,
        entity_id=args.entity_id,
        actor=args.actor,
        operation=args.operation,
        status=args.status,
        since_utc=args.since_utc,
        limit=args.limit,
        offset=args.offset,
    )

    has_more = (args.offset + len(records)) < total

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now(),
        "db_path": str(db_path),
        "filters": {
            k: v
            for k, v in {
                "entity_type": args.entity_type,
                "entity_id": args.entity_id,
                "actor": args.actor,
                "operation": args.operation,
                "status": args.status,
                "since_utc": args.since_utc,
            }.items()
            if v is not None
        },
        "pagination": {
            "limit": args.limit,
            "offset": args.offset,
            "returned_count": len(records),
            "total_matching_count": total,
            "has_more": has_more,
        },
        "mutations": records,
    }

    out = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        print(out)


if __name__ == "__main__":
    main()
