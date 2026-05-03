# -*- coding:utf-8 _*-
import json
import os
import sys
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4


LOG_SCHEMA = "record_recovery_service_log/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def start_timer() -> float:
    return perf_counter()


def elapsed_ms(started_at: float) -> int:
    return int(round((perf_counter() - started_at) * 1000))


def new_request_id() -> str:
    return uuid4().hex


def _server_address(service_state: Any) -> str | None:
    try:
        value = service_state.server_address
    except Exception:
        value = None
    return str(value) if value else None


def emit_structured_service_log(event: str, service_state: Any, **fields: Any) -> None:
    record: dict[str, Any] = {
        "schema": LOG_SCHEMA,
        "ts_utc": utc_now_iso(),
        "event": event,
        "pid": os.getpid(),
        "service_id": getattr(service_state, "service_id", "") or None,
        "tenant_id": getattr(service_state, "tenant_id", "") or None,
        "dataset_id": getattr(service_state, "dataset_id", "") or None,
        "transport": getattr(service_state, "transport", "") or None,
        "server_address": _server_address(service_state),
    }
    for key, value in fields.items():
        if value is not None:
            record[key] = value
    sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()
