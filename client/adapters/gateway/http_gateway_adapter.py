from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict, Optional
from urllib import parse, request
from urllib.error import HTTPError, URLError

from client.app.config import ClientSettings
from client.core.domain.models import (
    AttributionRunRequest,
    AuditQueryRequest,
    SeBuildRequest,
    SeSearchRequest,
    SensitiveReadRequest,
    TokenIssueRequest,
    TokenRevokeRequest,
)


class GatewayRequestError(RuntimeError):
    pass


class HttpGatewayAdapter:
    def __init__(self, settings: ClientSettings) -> None:
        self.settings = settings

    def _build_url(self, path: str, query: Optional[Dict[str, Any]] = None) -> str:
        url = f"{self.settings.gateway_base_url}{path}"
        if query:
            safe_query = {k: v for k, v in query.items() if v is not None}
            if safe_query:
                url = f"{url}?{parse.urlencode(safe_query)}"
        return url

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = self._build_url(path, query=query)
        data = None
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)

        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        req = request.Request(url=url, method=method.upper(), data=data, headers=req_headers)
        try:
            with request.urlopen(req, timeout=self.settings.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {"code": 0, "message": "ok", "data": None}
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
            raise GatewayRequestError(f"HTTP {exc.code}: {body or exc.reason}") from exc
        except URLError as exc:
            raise GatewayRequestError(f"Network error: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise GatewayRequestError("Invalid JSON response from gateway") from exc

    def health(self) -> Dict[str, Any]:
        return self._request_json("GET", "/health", payload=None)

    def run_attribution(self, req: AttributionRunRequest) -> Dict[str, Any]:
        payload = asdict(req)
        return self._request_json("POST", "/attribution/run", payload=payload)

    def build_se_index(self, req: SeBuildRequest) -> Dict[str, Any]:
        payload = asdict(req)
        return self._request_json("POST", "/se/index/build", payload=payload)

    def search_se(self, req: SeSearchRequest) -> Dict[str, Any]:
        payload = asdict(req)
        return self._request_json("POST", "/se/search", payload=payload)

    def issue_token(self, req: TokenIssueRequest) -> Dict[str, Any]:
        payload = asdict(req)
        return self._request_json("POST", "/access/token/issue", payload=payload)

    def revoke_token(self, req: TokenRevokeRequest) -> Dict[str, Any]:
        payload = asdict(req)
        return self._request_json("POST", "/access/token/revoke", payload=payload)

    def query_audit(self, req: AuditQueryRequest) -> Dict[str, Any]:
        query = asdict(req)
        return self._request_json("GET", "/audit/query", query=query)

    def read_sensitive(self, req: SensitiveReadRequest) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {req.bearer_token}"}
        path = f"/orders/{parse.quote(req.order_id)}/sensitive"
        return self._request_json("GET", path, headers=headers)
