import logging
import os


# FOR CLIENT
class ClientConfig:
    SERVER_URI = os.getenv("SSE_SERVER_URI", "ws://127.0.0.1:8001")
    CONSOLE_LOG_LEVEL = logging.WARNING
    FILE_LOG_LEVEL = logging.INFO


# FOR SERVER
class ServerConfig:
    HOST = os.getenv("SSE_SERVER_HOST", "")
    PORT = int(os.getenv("SSE_SERVER_PORT", "8001"))
