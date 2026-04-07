from __future__ import annotations

from client.adapters.gateway.http_gateway_adapter import HttpGatewayAdapter
from client.app.config import ClientSettings, load_settings
from client.core.usecases.client_service import ClientService


def build_client_service(
    *,
    gateway_base_url: str | None = None,
    timeout_seconds: int | None = None,
) -> tuple[ClientSettings, ClientService]:
    settings = load_settings(gateway_base_url=gateway_base_url, timeout_seconds=timeout_seconds)
    gateway = HttpGatewayAdapter(settings=settings)
    return settings, ClientService(gateway=gateway)
