import logging


# FOR CLIENT
class ClientConfig:
    SERVER_URI = "ws://192.168.1.100:8001"
    CONSOLE_LOG_LEVEL = logging.WARNING
    FILE_LOG_LEVEL = logging.INFO


# FOR SERVER
class ServerConfig:
    HOST = ""
    PORT = 8001
