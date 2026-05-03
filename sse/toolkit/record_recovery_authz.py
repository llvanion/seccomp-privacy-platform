import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Compatibility shim: service-owned authz logic now lives under services/record_recovery.
from services.record_recovery.authz import (  # noqa: F401
    PLATFORM_POLICY_SCHEMA,
    POLICY_SCHEMA,
    authorize_record_recovery_request,
    authz_policy_path,
    load_authz_policy,
)
