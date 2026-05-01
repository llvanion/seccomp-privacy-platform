import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Compatibility shim: service-owned config logic now lives under services/record_recovery.
from services.record_recovery.config import (  # noqa: F401
    CONFIG_SCHEMA,
    load_json_object,
    load_record_recovery_service_config,
    load_resolved_record_recovery_service_config,
    merged_record_recovery_service_scope_value,
    merged_record_recovery_service_value,
    resolve_record_recovery_service_config,
    resolve_relative_path,
)
