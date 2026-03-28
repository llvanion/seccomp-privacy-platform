from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    app_name: str = "member-c-access-gateway"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    a_pipeline_script: str = os.getenv("A_PIPELINE_SCRIPT", "")
    a_criteo_tsv: str = os.getenv("A_CRITEO_TSV", "")

    b_backend: str = os.getenv("B_BACKEND", "auto")  # auto | python_api | local
    b_sse_root: str = os.getenv("B_SSE_ROOT", "")
    b_server_uri: str = os.getenv("B_SERVER_URI", "ws://127.0.0.1:8001")
    b_scheme: str = os.getenv("B_SCHEME", "CJJ14.PiBas")

    rate_limit_backend: str = os.getenv("RATE_LIMIT_BACKEND", "auto")  # auto | redis | memory
    rate_limit_max_per_actor_action: int = int(os.getenv("RATE_LIMIT_MAX_PER_ACTOR_ACTION", "200"))
    rate_limit_window_seconds: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "3600"))
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    audit_backend: str = os.getenv("AUDIT_BACKEND", "sqlite")  # sqlite | jsonl
    audit_db_path: Path = Path(os.getenv("AUDIT_DB_PATH", "./runs/gateway_audit.db"))
    audit_jsonl_path: Path = Path(os.getenv("AUDIT_JSONL_PATH", "./runs/gateway_audit.jsonl"))
    token_secret: str = os.getenv("TOKEN_SECRET", "change-me-in-production")
    token_issuer: str = os.getenv("TOKEN_ISSUER", "member-c-access-gateway")
    token_default_expire_seconds: int = int(os.getenv("TOKEN_DEFAULT_EXPIRE_SECONDS", "900"))
    token_db_path: Path = Path(os.getenv("TOKEN_DB_PATH", "./runs/gateway_tokens.db"))
    token_jsonl_path: Path = Path(os.getenv("TOKEN_JSONL_PATH", "./runs/gateway_tokens.jsonl"))

    runs_root: Path = Path(os.getenv("RUNS_ROOT", "./runs"))


settings = Settings()
settings.runs_root.mkdir(parents=True, exist_ok=True)
settings.audit_db_path.parent.mkdir(parents=True, exist_ok=True)
settings.audit_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
settings.token_db_path.parent.mkdir(parents=True, exist_ok=True)
settings.token_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
