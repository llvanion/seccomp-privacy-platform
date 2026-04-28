#!/usr/bin/env python3
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json_object(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def load_json_if_exists(path: str) -> dict[str, Any] | None:
    if not path or not os.path.isfile(path):
        return None
    return load_json_object(path)


def load_jsonl(path: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path or not os.path.isfile(path):
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError(f"{path}:{line_no} must contain a JSON object")
            records.append(data)
    return records


def sha256_file(path: str) -> str | None:
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def connect_sqlite(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def file_exists(path: str | None) -> bool:
    return bool(path) and os.path.isfile(path)


def ensure_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        return value
    return None


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def upsert_registry_row(
    conn: sqlite3.Connection,
    table: str,
    key_column: str,
    key_value: str | None,
    values: dict[str, Any],
) -> None:
    if not key_value:
        return

    existing = conn.execute(
        f"SELECT 1 FROM {table} WHERE {key_column} = ?",
        (key_value,),
    ).fetchone()
    now = utc_now_iso()
    payload = dict(values)
    payload[key_column] = key_value

    if existing is None:
        payload.setdefault("created_at", now)
        payload.setdefault("updated_at", now)
        columns = ", ".join(payload.keys())
        placeholders = ", ".join("?" for _ in payload)
        conn.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            tuple(payload.values()),
        )
        return

    assignments = ", ".join(f"{column} = ?" for column in payload.keys() if column != key_column)
    update_values = [payload[column] for column in payload.keys() if column != key_column]
    if "updated_at" in values:
        pass
    elif "updated_at" in get_table_columns(conn, table):
        assignments = f"{assignments}, updated_at = ?" if assignments else "updated_at = ?"
        update_values.append(now)
    if not assignments:
        return
    update_values.append(key_value)
    conn.execute(
        f"UPDATE {table} SET {assignments} WHERE {key_column} = ?",
        tuple(update_values),
    )


def get_table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
