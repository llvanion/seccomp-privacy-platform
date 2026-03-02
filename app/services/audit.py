from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json


class AuditService:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, action: str, actor: str, payload: dict) -> None:
        record = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "actor": actor,
            "payload": payload,
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
