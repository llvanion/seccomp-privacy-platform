from __future__ import annotations

from typing import Any

from ad_client.core.domain.models import AdvertiserPsiResult, AdvertiserPsiRunRequest, ExposureRecord
from ad_client.core.ports.gateway_port import GatewayPort


class AdvertiserClientService:
    def __init__(self, gateway: GatewayPort) -> None:
        self.gateway = gateway

    def health(self) -> dict[str, Any]:
        return self.gateway.health()

    def run_psi(
        self,
        *,
        job_id: str,
        start_ts: int,
        end_ts: int,
        caller: str,
        exposure_records: list[dict[str, Any]],
        k: int = 20,
        n: int = 5,
        value_mode: str = "count",
        bucket_by: str | None = None,
        out_dir: str | None = None,
    ) -> AdvertiserPsiResult:
        records = [
            ExposureRecord(
                user_id=str(record["user_id"]),
                timestamp=record.get("timestamp"),
                tag=record.get("tag"),
                labels=record.get("labels"),
            )
            for record in exposure_records
        ]
        return self.gateway.run_psi(
            AdvertiserPsiRunRequest(
                job_id=job_id,
                start_ts=start_ts,
                end_ts=end_ts,
                caller=caller,
                exposure_records=records,
                k=k,
                n=n,
                value_mode=value_mode,
                bucket_by=bucket_by,
                out_dir=out_dir,
            )
        )

    def get_result(self, job_id: str) -> AdvertiserPsiResult:
        return self.gateway.get_result(job_id)
