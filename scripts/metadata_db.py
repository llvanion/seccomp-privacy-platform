#!/usr/bin/env python3
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psycopg2  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    psycopg2 = None


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "migrations" / "metadata"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _split_sql_statements(script: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    index = 0
    while index < len(script):
        char = script[index]
        next_char = script[index + 1] if index + 1 < len(script) else ""
        if in_line_comment:
            current.append(char)
            if char == "\n":
                in_line_comment = False
            index += 1
            continue
        if in_block_comment:
            current.append(char)
            if char == "*" and next_char == "/":
                current.append(next_char)
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue
        if not in_single and not in_double and char == "-" and next_char == "-":
            current.append(char)
            current.append(next_char)
            in_line_comment = True
            index += 2
            continue
        if not in_single and not in_double and char == "/" and next_char == "*":
            current.append(char)
            current.append(next_char)
            in_block_comment = True
            index += 2
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            current.append(char)
            index += 1
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            current.append(char)
            index += 1
            continue
        if char == ";" and not in_single and not in_double:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _translate_postgres_statement(statement: str) -> str:
    translated = statement.strip()
    if not translated:
        return ""
    upper = translated.upper()
    if upper.startswith("PRAGMA "):
        return ""
    translated = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\b", "SERIAL PRIMARY KEY", translated, flags=re.IGNORECASE)
    translated = re.sub(r"\bAUTOINCREMENT\b", "", translated, flags=re.IGNORECASE)
    return translated


def _convert_qmark_placeholders(query: str) -> str:
    rendered: list[str] = []
    in_single = False
    in_double = False
    for char in query:
        if char == "'" and not in_double:
            in_single = not in_single
            rendered.append(char)
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            rendered.append(char)
            continue
        if char == "?" and not in_single and not in_double:
            rendered.append("%s")
            continue
        rendered.append(char)
    return "".join(rendered)


def _normalize_param(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


class CompatRow:
    def __init__(self, columns: list[str], values: list[Any]) -> None:
        self._columns = columns
        self._values = values
        self._mapping = {column: values[index] for index, column in enumerate(columns)}

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def keys(self) -> list[str]:
        return list(self._columns)

    def get(self, key: str, default: Any = None) -> Any:
        return self._mapping.get(key, default)


class PostgresCursorWrapper:
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def execute(self, query: str, params: tuple[Any, ...] | list[Any] = ()) -> "PostgresCursorWrapper":
        normalized = tuple(_normalize_param(value) for value in params)
        self._cursor.execute(_convert_qmark_placeholders(query), normalized)
        return self

    def executemany(self, query: str, rows: list[tuple[Any, ...]]) -> "PostgresCursorWrapper":
        normalized_rows = [
            tuple(_normalize_param(value) for value in row)
            for row in rows
        ]
        self._cursor.executemany(_convert_qmark_placeholders(query), normalized_rows)
        return self

    def fetchone(self) -> CompatRow | None:
        row = self._cursor.fetchone()
        if row is None:
            return None
        columns = [item[0] for item in (self._cursor.description or [])]
        return CompatRow(columns, list(row))

    def fetchall(self) -> list[CompatRow]:
        rows = self._cursor.fetchall()
        columns = [item[0] for item in (self._cursor.description or [])]
        return [CompatRow(columns, list(row)) for row in rows]

    def __iter__(self):
        columns = [item[0] for item in (self._cursor.description or [])]
        for row in self._cursor:
            yield CompatRow(columns, list(row))


class PostgresConnectionWrapper:
    def __init__(self, conn: Any, *, dsn: str) -> None:
        self._conn = conn
        self.dsn = dsn
        self.backend = "postgres"

    def cursor(self) -> PostgresCursorWrapper:
        return PostgresCursorWrapper(self._conn.cursor())

    def execute(self, query: str, params: tuple[Any, ...] | list[Any] = ()) -> PostgresCursorWrapper:
        return self.cursor().execute(query, params)

    def executemany(self, query: str, rows: list[tuple[Any, ...]]) -> PostgresCursorWrapper:
        return self.cursor().executemany(query, rows)

    def executescript(self, script: str) -> None:
        cursor = self._conn.cursor()
        try:
            for statement in _split_sql_statements(script):
                translated = _translate_postgres_statement(statement)
                if translated:
                    cursor.execute(translated)
        finally:
            cursor.close()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PostgresConnectionWrapper":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.rollback()
        self.close()
        return False


def connect_db(db_path: str = "", dsn: str = "") -> Any:
    if dsn:
        if psycopg2 is None:
            raise RuntimeError("psycopg2 is required for PostgreSQL; install psycopg2-binary")
        conn = psycopg2.connect(dsn)
        conn.autocommit = False
        return PostgresConnectionWrapper(conn, dsn=dsn)
    if not db_path:
        raise ValueError("either db_path or dsn is required")
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def connect_db_with_retry(
    db_path: str = "",
    dsn: str = "",
    *,
    retries: int = 3,
    delay: float = 1.0,
) -> Any:
    """Like connect_db but retries on OperationalError (useful after Patroni failover)."""
    import time

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return connect_db(db_path, dsn=dsn)
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(delay * (2 ** attempt))
    raise last_exc  # type: ignore[misc]


def connect_read_db(
    db_path: str = "",
    *,
    dsn: str = "",
    read_dsn: str = "",
) -> Any:
    """Open a read-oriented connection, preferring read_dsn (a replica) when set.

    Read-only callers (query CLI, read-only HTTP APIs, identity resolution) use this
    to route SELECTs to a PostgreSQL streaming replica while writers keep targeting
    the primary DSN. When read_dsn is empty the call falls back to the primary
    db_path / dsn pair, so SQLite-only and primary-only deployments are unchanged.
    """
    if read_dsn:
        if psycopg2 is None:
            raise RuntimeError("psycopg2 is required for PostgreSQL read replica; install psycopg2-binary")
        return connect_db("", dsn=read_dsn)
    return connect_db(db_path, dsn=dsn)


def connect_read_db_with_retry(
    db_path: str = "",
    *,
    dsn: str = "",
    read_dsn: str = "",
    retries: int = 3,
    delay: float = 1.0,
) -> Any:
    """Retrying variant of connect_read_db for replicas behind a Patroni-style VIP."""
    import time

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return connect_read_db(db_path, dsn=dsn, read_dsn=read_dsn)
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(delay * (2 ** attempt))
    raise last_exc  # type: ignore[misc]


def database_backend(conn: Any) -> str:
    if isinstance(conn, PostgresConnectionWrapper):
        return "postgres"
    return "sqlite"


def database_version(conn: Any) -> str:
    if database_backend(conn) == "postgres":
        row = conn.execute("SELECT version()").fetchone()
        return str(row[0] if row is not None else "")
    row = conn.execute("SELECT sqlite_version()").fetchone()
    return str(row[0] if row is not None else "")


def table_exists(conn: Any, table_name: str) -> bool:
    if database_backend(conn) == "postgres":
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = ?",
            (table_name,),
        ).fetchone()
        return bool(row)
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row)


def ensure_schema_migrations_table(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version TEXT PRIMARY KEY,
          applied_at_utc TEXT NOT NULL
        )
        """
    )


def apply_migrations(conn: Any) -> list[str]:
    ensure_schema_migrations_table(conn)
    applied = {
        str(row[0])
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    versions: list[str] = []
    for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = migration_path.name
        if version in applied:
            continue
        script = migration_path.read_text(encoding="utf-8")
        if database_backend(conn) == "postgres":
            conn.executescript(script)
        else:
            conn.executescript(script)
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


def row_to_dict(row: Any | None) -> dict | None:
    if row is None:
        return None
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return None
