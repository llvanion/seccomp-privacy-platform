#!/usr/bin/env python3
import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn


SCHEMA_VERSION = "2026-04-28-control-plane-v1"
SCHEMA_DESCRIPTION = "Initial platform metadata sidecar schema for control-plane registry, jobs, policies, audits, and keys."


def die(msg: str) -> NoReturn:
    raise SystemExit(f"[ERROR] {msg}")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_schema_path() -> Path:
    return repo_root() / "schemas" / "platform_metadata.sql"


def load_sql(path: Path) -> str:
    if not path.is_file():
        die(f"missing schema file: {path}")
    return path.read_text(encoding="utf-8")


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def schema_version_exists(conn: sqlite3.Connection, version: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version = ?",
        (version,),
    ).fetchone()
    return row is not None


def count_user_tables(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        """
    ).fetchone()
    return int(row[0]) if row else 0


def initialize_db(db_path: Path, schema_path: Path) -> None:
    ensure_parent_dir(db_path)
    schema_sql = load_sql(schema_path)
    now = utc_now_iso()

    with connect(db_path) as conn:
        existing_tables = count_user_tables(conn)
        conn.executescript(schema_sql)
        if not schema_version_exists(conn, SCHEMA_VERSION):
            conn.execute(
                """
                INSERT INTO schema_migrations (version, description, applied_at)
                VALUES (?, ?, ?)
                """,
                (SCHEMA_VERSION, SCHEMA_DESCRIPTION, now),
            )
        conn.commit()

        total_tables = count_user_tables(conn)
        migration_rows = conn.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()
        migration_count = int(migration_rows[0]) if migration_rows else 0

    status = "initialized" if existing_tables == 0 else "updated"
    print(f"[ok] metadata DB {status}: {db_path}")
    print(f"[ok] schema file: {schema_path}")
    print(f"[ok] schema version: {SCHEMA_VERSION}")
    print(f"[ok] user tables: {total_tables}")
    print(f"[ok] migrations tracked: {migration_count}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Initialize the SQLite sidecar metadata DB for the control plane.")
    ap.add_argument("--db-path", required=True, help="SQLite DB path to create or update")
    ap.add_argument(
        "--schema-path",
        default=str(default_schema_path()),
        help="SQL schema file path; defaults to schemas/platform_metadata.sql",
    )
    args = ap.parse_args()

    db_path = Path(os.path.abspath(args.db_path))
    schema_path = Path(os.path.abspath(args.schema_path))
    initialize_db(db_path, schema_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
