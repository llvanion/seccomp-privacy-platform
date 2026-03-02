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
    runs_root: Path = Path(os.getenv("RUNS_ROOT", "./runs"))


settings = Settings()
settings.runs_root.mkdir(parents=True, exist_ok=True)
