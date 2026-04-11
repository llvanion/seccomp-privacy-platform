from __future__ import annotations

from ad_client.adapters.gateway.http_gateway_adapter import HttpGatewayAdapter
from ad_client.app.config import AdvertiserClientSettings, load_settings
from ad_client.core.usecases.advertiser_client_service import AdvertiserClientService


def build_advertiser_client_service(
    *,
    gateway_base_url: str | None = None,
    timeout_seconds: int | None = None,
) -> tuple[AdvertiserClientSettings, AdvertiserClientService]:
    settings = load_settings(gateway_base_url=gateway_base_url, timeout_seconds=timeout_seconds)
    gateway = HttpGatewayAdapter(settings=settings)
    return settings, AdvertiserClientService(gateway=gateway)
