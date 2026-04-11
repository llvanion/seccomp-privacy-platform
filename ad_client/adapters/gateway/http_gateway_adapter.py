from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any
from urllib import parse, request
from urllib.error import HTTPError, URLError

from ad_client.app.config import AdvertiserClientSettings
from ad_client.core.domain.models import AdvertiserPsiResult, AdvertiserPsiRunRequest


class GatewayRequestError(RuntimeError):
    pass


class HttpGatewayAdapter:
    def __init__(self, settings: AdvertiserClientSettings) -> None:
        self.settings = settings

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.settings.gateway_base_url}{path}"
        data = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        req = request.Request(url=url, method=method.upper(), data=data, headers=headers)
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

    @staticmethod
    def _unwrap_result(payload: dict[str, Any]) -> AdvertiserPsiResult:
        data = payload.get("data") or {}
        return AdvertiserPsiResult(
            job_id=str(data.get("job_id", "")),
            released=bool(data.get("released", False)),
            reason_code=str(data.get("reason_code", "unknown")),
            report=data.get("report") or {},
        )

    def health(self) -> dict[str, Any]:
        return self._request_json("GET", "/health")

    def run_psi(self, req: AdvertiserPsiRunRequest) -> AdvertiserPsiResult:
        payload = asdict(req)
        return self._unwrap_result(self._request_json("POST", "/attribution/run", payload=payload))

    def get_result(self, job_id: str) -> AdvertiserPsiResult:
        path = f"/attribution/report/{parse.quote(job_id)}"
        return self._unwrap_result(self._request_json("GET", path))
