from __future__ import annotations

from typing import Any, Protocol

from ad_client.core.domain.models import AdvertiserPsiResult, AdvertiserPsiRunRequest


class GatewayPort(Protocol):
    def health(self) -> dict[str, Any]:
        ...

    def run_psi(self, req: AdvertiserPsiRunRequest) -> AdvertiserPsiResult:
        ...

    def get_result(self, job_id: str) -> AdvertiserPsiResult:
        ...
