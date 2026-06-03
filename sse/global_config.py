import logging
import os
from ipaddress import ip_address


# FOR CLIENT
class ClientConfig:
    SERVER_URI = os.getenv("SSE_SERVER_URI", "ws://127.0.0.1:8001")
    CONSOLE_LOG_LEVEL = logging.WARNING
    FILE_LOG_LEVEL = logging.INFO


# FOR SERVER
class ServerConfig:
    LEGACY_PICKLE_WS_ALLOW_ENV = "SSE_ALLOW_LEGACY_PICKLE_WS"
    # The legacy websocket server is a demo-style interface, so keep it
    # local-only unless an operator explicitly opts into a wider bind address.
    HOST = os.getenv("SSE_SERVER_HOST", "127.0.0.1")
    PORT = int(os.getenv("SSE_SERVER_PORT", "8001"))

    @staticmethod
    def is_loopback_host(host) -> bool:
        value = str(host or "").strip()
        if value in {"localhost", "127.0.0.1", "::1"}:
            return True
        try:
            return ip_address(value).is_loopback
        except ValueError:
            return False

    @classmethod
    def legacy_pickle_wide_bind_allowed(cls) -> bool:
        return os.getenv(cls.LEGACY_PICKLE_WS_ALLOW_ENV, "") == "1"

    @classmethod
    def assert_legacy_pickle_bind_allowed(cls, host) -> None:
        if cls.is_loopback_host(host):
            return
        if cls.legacy_pickle_wide_bind_allowed():
            return
        raise RuntimeError(
            "legacy SSE WebSocket is a local/demo interface; refusing to bind "
            f"to non-loopback host {host!r}. Use SSE_SERVER_HOST=127.0.0.1 "
            f"or set {cls.LEGACY_PICKLE_WS_ALLOW_ENV}=1 for an explicit "
            "legacy/demo-only override."
        )
