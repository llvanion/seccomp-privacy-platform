"""Standalone record recovery service implementation package.

Business logic for encrypted record-store recovery, service transports, authz,
service config, and service clients belongs here. The legacy modules under
``sse/toolkit/record_recovery_*`` and ``sse/toolkit/encrypted_record_store.py``
are compatibility shims only.
"""

IMPLEMENTATION_OWNER = "services.record_recovery"
LEGACY_SHIM_PACKAGE = "sse.toolkit"

__all__ = [
    "IMPLEMENTATION_OWNER",
    "LEGACY_SHIM_PACKAGE",
]
