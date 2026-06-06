#!/usr/bin/env python3
"""Validate the e-commerce fact-layer baseline migration.

Parses the checked-in metadata migrations, extracts ``CREATE TABLE`` / ``ALTER
TABLE ADD COLUMN`` / ``CREATE INDEX`` statements, asserts the expected fact
tables are present
with their column lists and at least one supporting index each, and emits a
contract-shaped ``ecommerce_fact_layer_report/v1`` JSON document.

This is a static contract surface — it does not open any database. It exists so
the docs/ECOMMERCE_FACT_LAYER_PLAN.md baseline cannot drift silently from the
checked-in migrations.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "ecommerce_fact_layer_report/v1"
DEFAULT_MIGRATION_GLOB = "0*_*.sql"
EXPECTED_TABLES = [
    "orders",
    "order_items",
    "order_attribution",
    "order_payment",
    "order_fulfillment",
    "delivery_route_legs",
    "customer_service_interactions",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_text(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"[ERROR] migration file missing: {path}")
    return path.read_text(encoding="utf-8")


def strip_comments(sql: str) -> str:
    return "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )


def parse_columns(body: str) -> list[str]:
    columns: list[str] = []
    depth = 0
    current = []
    for ch in body:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            columns.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        tail = "".join(current).strip()
        if tail:
            columns.append(tail)
    column_names: list[str] = []
    for entry in columns:
        if not entry:
            continue
        upper = entry.upper().lstrip()
        if upper.startswith(("UNIQUE", "PRIMARY KEY", "FOREIGN KEY", "CHECK", "CONSTRAINT")):
            continue
        name = entry.split()[0].strip().strip(",")
        if name:
            column_names.append(name)
    return column_names


def parse_tables(sql: str) -> dict[str, list[str]]:
    pattern = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w]*)\s*\((.*?)\)\s*;",
        re.IGNORECASE | re.DOTALL,
    )
    tables: dict[str, list[str]] = {}
    for match in pattern.finditer(sql):
        name = match.group(1).strip()
        body = match.group(2)
        tables[name] = parse_columns(body)
    return tables


def parse_alter_add_columns(sql: str) -> dict[str, list[str]]:
    pattern = re.compile(
        r"ALTER\s+TABLE\s+([A-Za-z_][\w]*)\s+ADD\s+COLUMN\s+([A-Za-z_][\w]*)\b",
        re.IGNORECASE,
    )
    extra: dict[str, list[str]] = {}
    for match in pattern.finditer(sql):
        table_name = match.group(1).strip()
        column_name = match.group(2).strip()
        extra.setdefault(table_name, []).append(column_name)
    return extra


def parse_indexes(sql: str) -> dict[str, list[str]]:
    pattern = re.compile(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w]*)\s+ON\s+([A-Za-z_][\w]*)",
        re.IGNORECASE,
    )
    by_table: dict[str, list[str]] = {}
    for match in pattern.finditer(sql):
        index_name = match.group(1).strip()
        table_name = match.group(2).strip()
        by_table.setdefault(table_name, []).append(index_name)
    return by_table


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Validate the e-commerce fact-layer baseline migration and emit ecommerce_fact_layer_report/v1.",
    )
    ap.add_argument(
        "--migration",
        action="append",
        default=[],
        help="Optional migration path. May be repeated. When omitted, all metadata migrations are scanned in order.",
    )
    ap.add_argument("--output", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.migration:
        migration_paths = [Path(item).resolve() for item in args.migration]
    else:
        migration_paths = sorted((REPO_ROOT / "migrations" / "metadata").glob(DEFAULT_MIGRATION_GLOB))
    if not migration_paths:
        raise SystemExit("[ERROR] no metadata migrations found")
    sql_parts = [strip_comments(read_text(path)) for path in migration_paths]
    sql = "\n\n".join(sql_parts)
    tables = parse_tables(sql)
    added_columns = parse_alter_add_columns(sql)
    for table_name, columns in added_columns.items():
        if table_name in tables:
            for column in columns:
                if column not in tables[table_name]:
                    tables[table_name].append(column)
    indexes = parse_indexes(sql)

    table_entries = []
    tables_present: list[str] = []
    tables_missing: list[str] = []
    total_index_count = 0
    for name in EXPECTED_TABLES:
        if name in tables:
            tables_present.append(name)
            cols = tables[name]
            idx_list = sorted(indexes.get(name, []))
            total_index_count += len(idx_list)
            table_entries.append(
                {
                    "name": name,
                    "column_count": len(cols),
                    "columns": cols,
                    "indexes": idx_list,
                }
            )
        else:
            tables_missing.append(name)

    status = "ok"
    if tables_missing:
        status = "fail"
    else:
        for entry in table_entries:
            if entry["column_count"] < 5:
                status = "fail"
                break
            if not entry["indexes"]:
                status = "fail"
                break

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "migration_path": str(migration_paths[0]),
        "tables": table_entries,
        "summary": {
            "status": status,
            "expected_tables": EXPECTED_TABLES,
            "tables_present": tables_present,
            "tables_missing": tables_missing,
            "table_count": len(tables_present),
            "total_index_count": total_index_count,
            "migration_count": len(migration_paths),
        },
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
