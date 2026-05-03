#!/usr/bin/env python3
"""Export and validate the Postgres DDL target for the metadata sidecar.

Reads migrations/postgres/001_init.sql, parses table/index declarations,
and cross-validates them against the SQLite migration baseline to ensure
structural parity. Outputs postgres_ddl_export/v1.
"""
import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA_ID = "postgres_ddl_export/v1"
REPO_ROOT = Path(__file__).parent.parent
POSTGRES_DDL_PATH = REPO_ROOT / "migrations" / "postgres" / "001_init.sql"
SQLITE_MIGRATIONS_DIR = REPO_ROOT / "migrations" / "metadata"

POSTGRES_ONLY_TYPES = {"SERIAL", "BIGSERIAL", "TIMESTAMPTZ", "JSONB", "BOOLEAN"}
SQLITE_ONLY_TOKENS = {"PRAGMA", "AUTOINCREMENT"}

# Columns that use TEXT in SQLite but should map to typed columns in Postgres
TYPE_UPGRADE_MAP = {
    "_utc": "TIMESTAMPTZ",
    "_json": "JSONB",
}
BOOL_COLUMNS = {
    "exists_on_disk", "signed", "enabled", "public_report_released",
}


def parse_tables(ddl: str) -> list[dict]:
    """Extract table names and column definitions from DDL."""
    tables = []
    pattern = re.compile(
        r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.+?)\);",
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(ddl):
        name = match.group(1)
        body = match.group(2)
        columns = []
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line or line.upper().startswith(("PRIMARY KEY", "UNIQUE", "CHECK", "CONSTRAINT", "FOREIGN KEY")):
                continue
            # grab first word (col name) and second word (type)
            parts = line.split()
            if len(parts) >= 2:
                col_name = parts[0]
                col_type = parts[1].rstrip(",").upper()
                columns.append({"name": col_name, "type": col_type})
        tables.append({"table": name, "columns": columns})
    return tables


def parse_indexes(ddl: str) -> list[str]:
    pattern = re.compile(r"CREATE INDEX IF NOT EXISTS\s+(\w+)\s+ON", re.IGNORECASE)
    return [m.group(1) for m in pattern.finditer(ddl)]


def collect_sqlite_tables() -> set[str]:
    names: set[str] = set()
    for sql_file in sorted(SQLITE_MIGRATIONS_DIR.glob("*.sql")):
        text = sql_file.read_text(encoding="utf-8")
        for m in re.finditer(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", text, re.IGNORECASE):
            names.add(m.group(1))
    return names


def collect_sqlite_columns() -> dict[str, list[str]]:
    """Collect {table: [col_name]} from all SQLite migrations."""
    tables: dict[str, list[str]] = {}
    col_pat = re.compile(
        r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.+?)\);", re.DOTALL | re.IGNORECASE
    )
    alter_pat = re.compile(
        r"ALTER TABLE\s+(\w+)\s+ADD COLUMN\s+(\w+)", re.IGNORECASE
    )
    for sql_file in sorted(SQLITE_MIGRATIONS_DIR.glob("*.sql")):
        text = sql_file.read_text(encoding="utf-8")
        for m in col_pat.finditer(text):
            tname = m.group(1)
            body = m.group(2)
            cols = []
            for line in body.splitlines():
                line = line.strip().rstrip(",")
                if not line or line.upper().startswith(
                    ("PRIMARY KEY", "UNIQUE", "CHECK", "CONSTRAINT", "FOREIGN KEY")
                ):
                    continue
                parts = line.split()
                if parts:
                    cols.append(parts[0])
            tables.setdefault(tname, [])
            tables[tname].extend(cols)
        for m in alter_pat.finditer(text):
            tname, col = m.group(1), m.group(2)
            tables.setdefault(tname, [])
            if col not in tables[tname]:
                tables[tname].append(col)
    return tables


def validate_type_upgrades(tables: list[dict]) -> list[dict]:
    """Check that _utc columns use TIMESTAMPTZ and _json columns use JSONB."""
    issues = []
    for tbl in tables:
        for col in tbl["columns"]:
            cname = col["name"].lower()
            ctype = col["type"]
            for suffix, expected_type in TYPE_UPGRADE_MAP.items():
                if cname.endswith(suffix) and ctype != expected_type:
                    issues.append({
                        "table": tbl["table"],
                        "column": col["name"],
                        "expected_type": expected_type,
                        "actual_type": ctype,
                        "rule": f"columns ending in '{suffix}' must use {expected_type}",
                    })
            if cname in BOOL_COLUMNS and ctype not in ("BOOLEAN", "BOOL"):
                issues.append({
                    "table": tbl["table"],
                    "column": col["name"],
                    "expected_type": "BOOLEAN",
                    "actual_type": ctype,
                    "rule": f"known boolean column '{cname}' must use BOOLEAN",
                })
    return issues


def check_table_parity(pg_tables: list[dict], sqlite_tables: set[str]) -> dict:
    pg_names = {t["table"] for t in pg_tables}
    missing_in_pg = sorted(sqlite_tables - pg_names)
    extra_in_pg = sorted(pg_names - sqlite_tables)
    return {"missing_in_postgres": missing_in_pg, "extra_in_postgres": extra_in_pg}


def check_column_parity(pg_tables: list[dict], sqlite_cols: dict[str, list[str]]) -> list[dict]:
    issues = []
    pg_col_map = {t["table"]: [c["name"] for c in t["columns"]] for t in pg_tables}
    for table, sq_cols in sqlite_cols.items():
        pg_cols = pg_col_map.get(table, [])
        for col in sq_cols:
            if col not in pg_cols:
                issues.append({
                    "table": table,
                    "column": col,
                    "issue": "present in SQLite migrations but missing in Postgres DDL",
                })
    return issues


def strip_sql_comments(ddl: str) -> str:
    """Remove single-line SQL comments so token checks don't flag comment text."""
    lines = []
    for line in ddl.splitlines():
        # Remove everything after --
        idx = line.find("--")
        lines.append(line[:idx] if idx >= 0 else line)
    return "\n".join(lines)


def check_no_sqlite_tokens(ddl: str) -> list[str]:
    code_only = strip_sql_comments(ddl)
    upper = code_only.upper()
    return [tok for tok in SQLITE_ONLY_TOKENS if tok in upper]


def check_postgres_types_present(ddl: str) -> list[str]:
    upper = ddl.upper()
    return [t for t in POSTGRES_ONLY_TYPES if t in upper]


def main() -> None:
    parser = argparse.ArgumentParser(description="Export and validate Postgres DDL target")
    parser.add_argument("--output", default=None, help="Write JSON report to file")
    parser.add_argument("--fail-on-issues", action="store_true",
                        help="Exit non-zero if any validation issues found")
    args = parser.parse_args()

    if not POSTGRES_DDL_PATH.exists():
        print(json.dumps({"error": f"Postgres DDL not found: {POSTGRES_DDL_PATH}"}))
        sys.exit(1)

    ddl = POSTGRES_DDL_PATH.read_text(encoding="utf-8")

    pg_tables = parse_tables(ddl)
    pg_indexes = parse_indexes(ddl)
    sqlite_tables = collect_sqlite_tables()
    sqlite_cols = collect_sqlite_columns()

    type_issues = validate_type_upgrades(pg_tables)
    parity = check_table_parity(pg_tables, sqlite_tables)
    col_issues = check_column_parity(pg_tables, sqlite_cols)
    sqlite_tokens = check_no_sqlite_tokens(ddl)
    pg_types_present = check_postgres_types_present(ddl)

    all_issues = type_issues + col_issues
    if parity["missing_in_postgres"]:
        all_issues.append({"issue": "tables_missing_in_postgres", **parity})
    # Extra tables in Postgres (like control_plane_mutations) are intentional
    # forward-looking additions — treated as informational, not errors.
    if sqlite_tokens:
        all_issues.append({"issue": "sqlite_only_tokens_found", "tokens": sqlite_tokens})

    report = {
        "schema": SCHEMA_ID,
        "postgres_ddl_path": str(POSTGRES_DDL_PATH.relative_to(REPO_ROOT)),
        "tables_count": len(pg_tables),
        "indexes_count": len(pg_indexes),
        "tables": [t["table"] for t in pg_tables],
        "indexes": pg_indexes,
        "postgres_types_confirmed": pg_types_present,
        "sqlite_only_tokens": sqlite_tokens,
        "table_parity": parity,
        "type_upgrade_issues": type_issues,
        "column_parity_issues": col_issues,
        "total_issues": len(all_issues),
        "valid": len(all_issues) == 0,
    }

    out = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        print(out)

    if args.fail_on_issues and not report["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
