from __future__ import annotations

import logging
import subprocess

from fastapi import FastAPI, HTTPException

from app.config import settings
from app.logging_setup import setup_logging
from app.schemas import (
    ApiResponse,
    AttributionRunData,
    AttributionRunRequest,
    HealthData,
    SeBuildData,
    SeBuildRequest,
    SeSearchData,
    SeSearchRequest,
)
from app.services.a_adapter import AAdapter
from app.services.audit import AuditService
from app.services.b_adapter import BAdapter
from app.services.ratelimit import InMemoryRateLimit

setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version="0.1.0")

_a_adapter = AAdapter()
_b_adapter = BAdapter()
_audit = AuditService(settings.runs_root / "gateway_audit.jsonl")
_rl = InMemoryRateLimit(max_per_actor_action=200)


@app.get("/health", response_model=ApiResponse[HealthData])
def health() -> ApiResponse[HealthData]:
    return ApiResponse(data=HealthData(service=settings.app_name, status="healthy"))


@app.post("/attribution/run", response_model=ApiResponse[AttributionRunData])
def attribution_run(req: AttributionRunRequest) -> ApiResponse[AttributionRunData]:
    allowed, used, limit = _rl.hit(req.caller, "psi_run")
    if not allowed:
        _audit.log("rate_limit", req.caller, {"action": "psi_run", "used": used, "limit": limit})
        raise HTTPException(status_code=429, detail="rate limit exceeded")

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
    except subprocess.CalledProcessError as e:  # type: ignore[name-defined]
        logger.exception("A pipeline failed")
        _audit.log("psi_run", req.caller, {"job_id": req.job_id, "error": str(e)})
        raise HTTPException(status_code=500, detail="A pipeline failed") from e

    released = bool(report.get("released", False))
    reason_code = str(report.get("reason_code", "unknown"))
    _audit.log("psi_run", req.caller, {"job_id": req.job_id, "released": released, "reason_code": reason_code})

    return ApiResponse(
        data=AttributionRunData(job_id=req.job_id, released=released, reason_code=reason_code, report=report)
    )


@app.post("/se/index/build", response_model=ApiResponse[SeBuildData])
def se_index_build(req: SeBuildRequest) -> ApiResponse[SeBuildData]:
    indexed_count = _b_adapter.build_index(req.index_name, req.records)
    _audit.log("se_index_build", "system", {"index_name": req.index_name, "indexed_count": indexed_count})
    return ApiResponse(data=SeBuildData(index_name=req.index_name, indexed_count=indexed_count))


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
        },
    )
    return ApiResponse(
        data=SeSearchData(
            index_name=req.index_name,
            keyword=req.keyword,
            result_count=len(results),
            encrypted_results=results,
        )
    )
