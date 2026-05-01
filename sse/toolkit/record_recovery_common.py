import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Compatibility shim: shared recovery payload helpers now live under services/record_recovery.
from services.record_recovery.common import (  # noqa: F401
    ERROR_SCHEMA,
    HEALTH_SCHEMA,
    RESULT_SCHEMA,
    HashingTextWriter,
    build_error,
    build_health_result,
    build_result,
    enforce_row_limits,
    parse_candidate_payload,
    row_matches_filters,
    select_bridge_rows,
    selected_bridge_row,
    stringify_record_id,
    write_selected_rows,
)
