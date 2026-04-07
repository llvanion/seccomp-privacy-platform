from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ClientSettings:
    gateway_base_url: str = "http://127.0.0.1:8000"
    timeout_seconds: int = 30


def load_settings(gateway_base_url: str | None = None, timeout_seconds: int | None = None) -> ClientSettings:
    base_url = gateway_base_url or os.getenv("CLIENT_GATEWAY_BASE_URL") or "http://127.0.0.1:8000"
    timeout = timeout_seconds or int(os.getenv("CLIENT_TIMEOUT_SECONDS", "30"))
    return ClientSettings(gateway_base_url=base_url.rstrip("/"), timeout_seconds=timeout)
