import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Compatibility shim: encrypted record-store logic now lives under services/record_recovery.
from services.record_recovery.encrypted_record_store import (  # noqa: F401
    AEAD_NAME,
    KDF_ITERATIONS,
    KDF_NAME,
    KEY_SIZE,
    NONCE_SIZE,
    SALT_SIZE,
    STORE_SCHEMA,
    build_record_store,
    iter_candidate_rows,
    load_candidate_rows,
)
