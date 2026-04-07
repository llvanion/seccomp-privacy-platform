from __future__ import annotations

from typing import Any, Dict, Protocol

from client.core.domain.models import (
    AttributionRunRequest,
    AuditQueryRequest,
    SeBuildRequest,
    SeSearchRequest,
    SensitiveReadRequest,
    TokenIssueRequest,
    TokenRevokeRequest,
)


class GatewayPort(Protocol):
    def health(self) -> Dict[str, Any]:
        ...

    def run_attribution(self, req: AttributionRunRequest) -> Dict[str, Any]:
        ...

    def build_se_index(self, req: SeBuildRequest) -> Dict[str, Any]:
        ...

    def search_se(self, req: SeSearchRequest) -> Dict[str, Any]:
        ...

    def issue_token(self, req: TokenIssueRequest) -> Dict[str, Any]:
        ...

    def revoke_token(self, req: TokenRevokeRequest) -> Dict[str, Any]:
        ...

    def query_audit(self, req: AuditQueryRequest) -> Dict[str, Any]:
        ...

    def read_sensitive(self, req: SensitiveReadRequest) -> Dict[str, Any]:
        ...
