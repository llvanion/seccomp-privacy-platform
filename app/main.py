from __future__ import annotations

from datetime import datetime, timezone
import logging
import subprocess
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from app.config import settings
from app.errors import GatewayError
from app.logging_setup import setup_logging
from app.schemas import (
    ApiResponse,
    AttributionRunData,
    AttributionRunRequest,
    AuditQueryData,
    AuditRow,
    HealthData,
    SeBuildData,
    SeBuildRequest,
    SeSearchData,
    SeSearchRequest,
)
from app.services.a_adapter import AAdapter
from app.services.audit import AuditService
from app.services.b_adapter import BAdapter
from app.services.ratelimit import build_rate_limiter

setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version="0.2.0")

_a_adapter = AAdapter()
_b_adapter = BAdapter(
    backend=settings.b_backend,
    sse_root=settings.b_sse_root,
    server_uri=settings.b_server_uri,
    scheme=settings.b_scheme,
)
_audit = AuditService(
    backend=settings.audit_backend,
    sqlite_path=settings.audit_db_path,
    jsonl_path=settings.audit_jsonl_path,
)
_rl = build_rate_limiter(
    backend=settings.rate_limit_backend,
    redis_url=settings.redis_url,
    max_per_actor_action=settings.rate_limit_max_per_actor_action,
    window_seconds=settings.rate_limit_window_seconds,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error_payload(err: GatewayError) -> dict[str, Any]:
    return {
        "code": err.status_code,
        "message": err.message,
        "data": {"reason_code": err.reason_code, "details": err.details},
        "timestamp": _now_iso(),
    }


@app.exception_handler(GatewayError)
async def handle_gateway_error(_, exc: GatewayError):
    return JSONResponse(status_code=exc.status_code, content=_error_payload(exc))


@app.get("/health", response_model=ApiResponse[HealthData])
def health() -> ApiResponse[HealthData]:
    return ApiResponse(data=HealthData(service=settings.app_name, status="healthy"))


@app.get("/audit/query", response_model=ApiResponse[AuditQueryData])
def audit_query(
    action: str | None = None,
    actor: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> ApiResponse[AuditQueryData]:
    rows = _audit.query(action=action, actor=actor, start_ts=start_ts, end_ts=end_ts, limit=limit)
    return ApiResponse(data=AuditQueryData(total=len(rows), rows=[AuditRow(**r) for r in rows]))


@app.post("/attribution/run", response_model=ApiResponse[AttributionRunData])
def attribution_run(req: AttributionRunRequest) -> ApiResponse[AttributionRunData]:
    allowed, used, limit = _rl.hit(req.caller, "psi_run")
    if not allowed:
        _audit.log("rate_limit", req.caller, {"action": "psi_run", "used": used, "limit": limit})
        raise GatewayError("rate_limit_exceeded", "rate limit exceeded", status_code=429)

    try:
        report = _a_adapter.run_psi(
            job_id=req.job_id,
            start=req.start_ts,
            end=req.end_ts,
            k=req.k,
            caller=req.caller,
            n=req.n,
            value_mode=req.value_mode,
            out_dir=req.out_dir,
        )
    except subprocess.CalledProcessError as exc:
        logger.exception("A pipeline failed")
        _audit.log("psi_run", req.caller, {"job_id": req.job_id, "error": str(exc)})
        raise GatewayError("a_pipeline_failed", "A pipeline failed", status_code=502) from exc

    released = bool(report.get("released", False))
    reason_code = str(report.get("reason_code", "unknown"))
    _audit.log("psi_run", req.caller, {"job_id": req.job_id, "released": released, "reason_code": reason_code})

    return ApiResponse(
        data=AttributionRunData(job_id=req.job_id, released=released, reason_code=reason_code, report=report)
    )


@app.post("/se/index/build", response_model=ApiResponse[SeBuildData])
def se_index_build(req: SeBuildRequest) -> ApiResponse[SeBuildData]:
    indexed_count = _b_adapter.build_index(req.index_name, req.records)
    _audit.log(
        "se_index_build",
        "system",
        {
            "index_name": req.index_name,
            "indexed_count": indexed_count,
            "backend_used": _b_adapter.backend_used,
        },
    )
    return ApiResponse(
        data=SeBuildData(index_name=req.index_name, indexed_count=indexed_count, backend_used=_b_adapter.backend_used)
    )


@app.post("/se/search", response_model=ApiResponse[SeSearchData])
def se_search(req: SeSearchRequest) -> ApiResponse[SeSearchData]:
    results, latency_ms = _b_adapter.search(req.index_name, req.keyword)
    _audit.log(
        "se_search",
        "system",
        {
            "index_name": req.index_name,
            "keyword": req.keyword,
            "result_count": len(results),
            "latency_ms": latency_ms,
            "backend_used": _b_adapter.backend_used,
        },
    )
    return ApiResponse(
        data=SeSearchData(
            index_name=req.index_name,
            keyword=req.keyword,
            result_count=len(results),
            encrypted_results=results,
            backend_used=_b_adapter.backend_used,
        )
    )

