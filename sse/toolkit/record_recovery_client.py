import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Compatibility shim: recovery-service client protocol now lives under services/record_recovery.
from services.record_recovery.client import (  # noqa: F401
    request_record_recovery,
    request_record_recovery_health,
)
