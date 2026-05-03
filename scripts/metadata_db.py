#!/usr/bin/env python3
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "migrations" / "metadata"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def connect_db(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version TEXT PRIMARY KEY,
          applied_at_utc TEXT NOT NULL
        )
        """
    )


def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    ensure_schema_migrations_table(conn)
    applied = {
        row["version"]
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    versions: list[str] = []
    for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = migration_path.name
        if version in applied:
            continue
        conn.executescript(migration_path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at_utc) VALUES(?, ?)",
            (version, utc_now()),
        )
        versions.append(version)
    conn.commit()
    return versions


def expected_migration_versions() -> list[str]:
    return [migration_path.name for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql"))]


def sha256_file(path: str | Path | None) -> str | None:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.is_file():
        return None
    digest = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_format(path: str | Path | None) -> str | None:
    if not path:
        return None
    suffix = Path(path).suffix.lower().lstrip(".")
    return suffix or None


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}
