from __future__ import annotations

from typing import Any, Dict, Optional

from client.core.domain.models import (
    AttributionRunRequest,
    AuditQueryRequest,
    SeBuildRequest,
    SeSearchRequest,
    SensitiveReadRequest,
    TokenIssueRequest,
    TokenRevokeRequest,
)
from client.core.ports.gateway_port import GatewayPort


class ClientService:
    def __init__(self, gateway: GatewayPort) -> None:
        self.gateway = gateway

    def health(self) -> Dict[str, Any]:
        return self.gateway.health()

    def attribution_run(
        self,
        *,
        job_id: str,
        start_ts: int,
        end_ts: int,
        caller: str,
        k: int = 20,
        n: int = 5,
        value_mode: str = "count",
        out_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.gateway.run_attribution(
            AttributionRunRequest(
                job_id=job_id,
                start_ts=start_ts,
                end_ts=end_ts,
                caller=caller,
                k=k,
                n=n,
                value_mode=value_mode,
                out_dir=out_dir,
            )
        )

    def se_build_index(self, *, index_name: str, records: list[dict[str, Any]]) -> Dict[str, Any]:
        return self.gateway.build_se_index(SeBuildRequest(index_name=index_name, records=records))

    def se_search(self, *, index_name: str, keyword: str) -> Dict[str, Any]:
        return self.gateway.search_se(SeSearchRequest(index_name=index_name, keyword=keyword))

    def token_issue(
        self,
        *,
        actor: str,
        scopes: list[str],
        resource_id: Optional[str] = None,
        expire_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self.gateway.issue_token(
            TokenIssueRequest(
                actor=actor,
                scopes=scopes,
                resource_id=resource_id,
                expire_seconds=expire_seconds,
            )
        )

    def token_revoke(
        self,
        *,
        revoked_by: str,
        reason: str,
        jti: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.gateway.revoke_token(
            TokenRevokeRequest(revoked_by=revoked_by, reason=reason, jti=jti, token=token)
        )

    def audit_query(
        self,
        *,
        action: Optional[str] = None,
        actor: Optional[str] = None,
        start_ts: Optional[str] = None,
        end_ts: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        return self.gateway.query_audit(
            AuditQueryRequest(action=action, actor=actor, start_ts=start_ts, end_ts=end_ts, limit=limit)
        )

    def sensitive_read(self, *, order_id: str, bearer_token: str) -> Dict[str, Any]:
        return self.gateway.read_sensitive(SensitiveReadRequest(order_id=order_id, bearer_token=bearer_token))
