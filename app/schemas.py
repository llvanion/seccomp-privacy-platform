from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class HealthData(BaseModel):
    service: str
    status: str


class AttributionRunRequest(BaseModel):
    job_id: str
    start_ts: int
    end_ts: int
    k: int = 20
    caller: str = "demo"
    n: int = 5
    value_mode: str = "count"
    out_dir: str | None = None


class AttributionRunData(BaseModel):
    job_id: str
    released: bool
    reason_code: str
    report: dict[str, Any]


class SeBuildRequest(BaseModel):
    index_name: str
    records: list[dict[str, Any]]


class SeBuildData(BaseModel):
    index_name: str
    indexed_count: int


class SeSearchRequest(BaseModel):
    index_name: str
    keyword: str


class SeSearchData(BaseModel):
    index_name: str
    keyword: str
    result_count: int
    encrypted_results: list[str]
