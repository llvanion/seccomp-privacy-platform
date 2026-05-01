import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Compatibility shim: recovery worker subprocess entrypoint now lives under services/record_recovery.
from services.record_recovery.worker import (  # noqa: F401
    main,
    parse_stdin_payload,
)


if __name__ == "__main__":
    raise SystemExit(main())
