from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditService:
    def __init__(
        self,
        *,
        backend: str,
        sqlite_path: Path,
        jsonl_path: Path,
    ) -> None:
        self.backend = backend
        self.sqlite_path = sqlite_path
        self.jsonl_path = jsonl_path

        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)

        if self.backend == "sqlite":
            self._init_sqlite()

    def _init_sqlite(self) -> None:
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_utc TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_logs(ts_utc)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs(actor)")
            conn.commit()

    def log(self, action: str, actor: str, payload: dict[str, Any]) -> None:
        record = {
            "ts_utc": utc_now_iso(),
            "action": action,
            "actor": actor,
            "payload": payload,
        }
        if self.backend == "sqlite":
            with sqlite3.connect(self.sqlite_path) as conn:
                conn.execute(
                    "INSERT INTO audit_logs(ts_utc, action, actor, payload_json) VALUES (?, ?, ?, ?)",
                    (record["ts_utc"], action, actor, json.dumps(payload, ensure_ascii=False)),
                )
                conn.commit()
            return

        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def query(
        self,
        *,
        action: str | None = None,
        actor: str | None = None,
        start_ts: str | None = None,
        end_ts: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if self.backend == "sqlite":
            where = []
            params: list[Any] = []

            if action:
                where.append("action = ?")
                params.append(action)
            if actor:
                where.append("actor = ?")
                params.append(actor)
            if start_ts:
                where.append("ts_utc >= ?")
                params.append(start_ts)
            if end_ts:
                where.append("ts_utc <= ?")
                params.append(end_ts)

            sql = "SELECT ts_utc, action, actor, payload_json FROM audit_logs"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)

            with sqlite3.connect(self.sqlite_path) as conn:
                rows = conn.execute(sql, params).fetchall()

            out: list[dict[str, Any]] = []
            for ts_utc, row_action, row_actor, payload_json in rows:
                out.append(
                    {
                        "ts_utc": ts_utc,
                        "action": row_action,
                        "actor": row_actor,
                        "payload": json.loads(payload_json),
                    }
                )
            return out

        if not self.jsonl_path.exists():
            return []

        rows: list[dict[str, Any]] = []
        for line in self.jsonl_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if action and row.get("action") != action:
                continue
            if actor and row.get("actor") != actor:
                continue
            ts_utc = row.get("ts_utc", "")
            if start_ts and ts_utc < start_ts:
                continue
            if end_ts and ts_utc > end_ts:
                continue
            rows.append(row)

        rows.reverse()
        return rows[:limit]

