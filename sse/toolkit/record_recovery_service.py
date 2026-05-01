import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Compatibility shim: service-owned request handling now lives under services/record_recovery.
from services.record_recovery.service import (  # noqa: F401
    RecordRecoveryRequestHandler,
    RecordRecoveryUnixStreamServer,
    append_record_recovery_service_audit,
    handle_record_recovery_service_payload,
    main,
)


if __name__ == "__main__":
    raise SystemExit(main())
