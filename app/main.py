from __future__ import annotations

from datetime import datetime, timezone
import logging
import subprocess
from typing import Any

from fastapi import FastAPI, Header, Query
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
    SensitiveOrderData,
    SeBuildData,
    SeBuildRequest,
    SeSearchData,
    SeSearchRequest,
    TokenIssueData,
    TokenIssueRequest,
    TokenRevokeData,
    TokenRevokeRequest,
)
from app.services.a_adapter import AAdapter
from app.services.audit import AuditService
from app.services.b_adapter import BAdapter
from app.services.ratelimit import build_rate_limiter
from app.services.sensitive_data import get_sensitive_order, mask_sensitive_order
from app.services.token import TokenService

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
_token_service = TokenService(
    secret=settings.token_secret,
    issuer=settings.token_issuer,
    default_expire_seconds=settings.token_default_expire_seconds,
    backend=settings.audit_backend,
    sqlite_path=settings.token_db_path,
    jsonl_path=settings.token_jsonl_path,
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


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise GatewayError("missing_authorization", "missing Authorization header", status_code=401)
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise GatewayError("bad_authorization", "Authorization header must be Bearer token", status_code=401)
    return token.strip()


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


@app.post("/access/token/issue", response_model=ApiResponse[TokenIssueData])
def issue_access_token(req: TokenIssueRequest) -> ApiResponse[TokenIssueData]:
    token, claims = _token_service.issue_token(
        actor=req.actor,
        scopes=req.scopes,
        resource_id=req.resource_id,
        expire_seconds=req.expire_seconds,
    )
    _audit.log(
        "access_token_issue",
        req.actor,
        {
            "jti": claims.jti,
            "scopes": claims.scope,
            "resource_id": claims.resource_id,
            "expires_at": claims.expires_at,
        },
    )
    return ApiResponse(
        data=TokenIssueData(
            access_token=token,
            expires_at=claims.expires_at,
            jti=claims.jti,
            actor=claims.sub,
            scopes=claims.scope,
            resource_id=claims.resource_id,
        )
    )


@app.post("/access/token/revoke", response_model=ApiResponse[TokenRevokeData])
def revoke_access_token(req: TokenRevokeRequest) -> ApiResponse[TokenRevokeData]:
    if not req.jti and not req.token:
        raise GatewayError("missing_revoke_target", "either jti or token is required", status_code=400)
    jti = req.jti or _token_service.extract_jti(req.token or "")
    _token_service.revoke_token(jti=jti, revoked_by=req.revoked_by, reason=req.reason)
    _audit.log(
        "access_token_revoke",
        req.revoked_by,
        {
            "jti": jti,
            "reason": req.reason,
        },
    )
    return ApiResponse(data=TokenRevokeData(revoked=True, jti=jti, revoked_by=req.revoked_by, reason=req.reason))


@app.get("/orders/{order_id}/sensitive", response_model=ApiResponse[SensitiveOrderData])
def get_order_sensitive(
    order_id: str,
    authorization: str | None = Header(default=None),
) -> ApiResponse[SensitiveOrderData]:
    token = _extract_bearer_token(authorization)
    claims = _token_service.parse_and_validate(token)
    _token_service.require_scope(claims, "orders:sensitive:read", resource_id=order_id)

    order = get_sensitive_order(order_id)
    is_full_access = "orders:sensitive:read:full" in claims.scope
    payload = order if is_full_access else mask_sensitive_order(order)

    _audit.log(
        "orders_sensitive_read",
        claims.sub,
        {
            "order_id": order_id,
            "jti": claims.jti,
            "masked": not is_full_access,
            "scopes": claims.scope,
        },
    )
    return ApiResponse(
        data=SensitiveOrderData(
            order_id=order_id,
            actor=claims.sub,
            masked=not is_full_access,
            allowed_scopes=claims.scope,
            data=payload,
        )
    )


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
