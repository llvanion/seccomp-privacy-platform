#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from check_business_access_policy import load_json_object
from metadata_db import apply_migrations, connect_db, database_backend
from validate_ecommerce_fact_import import DEFAULT_POLICY, TABLE_SPECS, build_validation_report


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "ecommerce_fact_import_result/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def insert_rows(conn: Any, *, table: str, rows: list[dict[str, Any]]) -> int:
    spec = TABLE_SPECS[table]
    columns = sorted(set(spec["required"]) | set(spec["optional"]))
    if "id" in columns:
        columns.remove("id")
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    sql = f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})"
    values = [tuple(row.get(column) for column in columns) for row in rows]
    conn.executemany(sql, values)
    return len(values)


def table_count(conn: Any, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    if row is None:
        return 0
    try:
        return int(row["count"])
    except (KeyError, TypeError):
        return int(row[0])


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Validate and transactionally import e-commerce fact-layer JSONL rows.")
    ap.add_argument("--table", required=True, choices=sorted(TABLE_SPECS))
    ap.add_argument("--input", required=True, help="JSONL file containing candidate fact rows")
    ap.add_argument("--metadata-db", default="", help="SQLite metadata DB path")
    ap.add_argument("--metadata-dsn", default="", help="PostgreSQL metadata DSN")
    ap.add_argument("--business-access-policy", default=str(DEFAULT_POLICY))
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-reject", action="store_true", help="Exit 0 when validation denies the import")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        raise SystemExit(f"[ERROR] input file does not exist: {input_path}")
    if not args.metadata_db and not args.metadata_dsn:
        raise SystemExit("[ERROR] either --metadata-db or --metadata-dsn is required")

    policy = load_json_object(args.business_access_policy)
    validation, rows = build_validation_report(table=args.table, input_path=input_path, policy=policy)
    report: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "table": args.table,
        "input_path": str(input_path),
        "input_sha256": sha256_file(input_path),
        "database_backend": None,
        "decision": validation["decision"],
        "reason_code": validation["reason_code"],
        "validation": validation,
        "inserted_row_count": 0,
        "table_row_count_before": None,
        "table_row_count_after": None,
        "transaction": "not_started",
    }

    conn = connect_db(args.metadata_db, dsn=args.metadata_dsn)
    try:
        report["database_backend"] = database_backend(conn)
        apply_migrations(conn)
        before = table_count(conn, args.table)
        report["table_row_count_before"] = before
        if validation["decision"] == "deny":
            report["transaction"] = "rejected_before_insert"
            report["table_row_count_after"] = before
        else:
            try:
                inserted = insert_rows(conn, table=args.table, rows=rows)
                conn.commit()
                report["inserted_row_count"] = inserted
                report["table_row_count_after"] = table_count(conn, args.table)
                report["transaction"] = "committed"
            except Exception as exc:
                conn.rollback()
                report["decision"] = "deny"
                report["reason_code"] = "insert_failed"
                report["transaction"] = "rolled_back"
                report["table_row_count_after"] = table_count(conn, args.table)
                report["insert_error"] = str(exc)
    finally:
        conn.close()

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if report["decision"] == "deny" and not args.allow_reject:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
