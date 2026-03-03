from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GatewayError(Exception):
    reason_code: str
    message: str
    status_code: int = 400
    details: dict[str, Any] = field(default_factory=dict)

