from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExposureRecord:
    user_id: str
    timestamp: int | None = None
    tag: str | None = None
    labels: dict[str, Any] | None = None


@dataclass
class AdvertiserPsiRunRequest:
    job_id: str
    start_ts: int
    end_ts: int
    caller: str
    exposure_records: list[ExposureRecord]
    k: int = 20
    n: int = 5
    value_mode: str = "count"
    bucket_by: str | None = None
    out_dir: str | None = None


@dataclass
class AdvertiserPsiResult:
    job_id: str
    released: bool
    reason_code: str
    report: dict[str, Any] = field(default_factory=dict)
