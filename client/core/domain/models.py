from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    job_id: str
    type: str
    status: JobStatus = JobStatus.PENDING
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    input_snapshot: Dict[str, Any] = field(default_factory=dict)
    result_ref: Optional[str] = None
    error: Optional[str] = None


@dataclass
class AttributionRunRequest:
    job_id: str
    start_ts: int
    end_ts: int
    caller: str
    k: int = 20
    n: int = 5
    value_mode: str = "count"
    out_dir: Optional[str] = None


@dataclass
class SeBuildRequest:
    index_name: str
    records: List[Dict[str, Any]]


@dataclass
class SeSearchRequest:
    index_name: str
    keyword: str


@dataclass
class TokenIssueRequest:
    actor: str
    scopes: List[str]
    resource_id: Optional[str] = None
    expire_seconds: Optional[int] = None


@dataclass
class TokenRevokeRequest:
    revoked_by: str
    reason: str
    jti: Optional[str] = None
    token: Optional[str] = None


@dataclass
class AuditQueryRequest:
    action: Optional[str] = None
    actor: Optional[str] = None
    start_ts: Optional[str] = None
    end_ts: Optional[str] = None
    limit: int = 100


@dataclass
class SensitiveReadRequest:
    order_id: str
    bearer_token: str
