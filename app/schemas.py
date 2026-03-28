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
    backend_used: str


class SeSearchRequest(BaseModel):
    index_name: str
    keyword: str


class SeSearchData(BaseModel):
    index_name: str
    keyword: str
    result_count: int
    encrypted_results: list[str]
    backend_used: str


class AuditRow(BaseModel):
    ts_utc: str
    action: str
    actor: str
    payload: dict[str, Any]


class AuditQueryData(BaseModel):
    total: int
    rows: list[AuditRow]


class TokenIssueRequest(BaseModel):
    actor: str
    scopes: list[str]
    resource_id: str | None = None
    expire_seconds: int | None = Field(default=None, ge=1, le=86400)


class TokenIssueData(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_at: str
    jti: str
    actor: str
    scopes: list[str]
    resource_id: str | None = None


class TokenRevokeRequest(BaseModel):
    jti: str | None = None
    token: str | None = None
    revoked_by: str = "system"
    reason: str = "manual_revoke"


class TokenRevokeData(BaseModel):
    revoked: bool
    jti: str
    revoked_by: str
    reason: str


class SensitiveOrderData(BaseModel):
    order_id: str
    actor: str
    masked: bool
    allowed_scopes: list[str]
    data: dict[str, Any]
