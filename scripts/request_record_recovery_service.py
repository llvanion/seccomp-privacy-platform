#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _sse_root() -> Path:
    return REPO_ROOT / "sse"


sys.path.insert(0, str(_sse_root()))
sys.path.insert(0, str(REPO_ROOT))

from services.record_recovery.config import (  # noqa: E402
    load_resolved_record_recovery_service_config,
    merged_record_recovery_service_value,
)
from services.record_recovery.client import request_record_recovery_health  # noqa: E402


def optional_repo_path(path_value: str) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    if path.is_absolute():
        return str(path)
    return str((REPO_ROOT / path).resolve())


def main() -> int:
    ap = argparse.ArgumentParser(description="Request a health snapshot from a record recovery service endpoint or Unix socket.")
    ap.add_argument("--config", default="")
    ap.add_argument("--socket-path", default="")
    ap.add_argument("--endpoint-url", default="")
    ap.add_argument("--auth-token-env", default="")
    ap.add_argument("--identity-token-env", default="")
    args = ap.parse_args()

    config = load_resolved_record_recovery_service_config(optional_repo_path(args.config)) if args.config else {}
    socket_path = merged_record_recovery_service_value(args.socket_path, config.get("socket_path", ""))
    endpoint_url = merged_record_recovery_service_value(args.endpoint_url, config.get("endpoint_url", ""))
    auth_token_env = merged_record_recovery_service_value(args.auth_token_env, config.get("auth_token_env", ""))
    tls_config = config.get("tls") if isinstance(config.get("tls"), dict) else None
    if not socket_path and not endpoint_url:
        raise SystemExit("[ERROR] --socket-path / --endpoint-url or a config with one of them is required")

    result = request_record_recovery_health(
        socket_path=Path(socket_path) if socket_path else None,
        endpoint_url=endpoint_url,
        auth_env=auth_token_env,
        identity_auth_env=args.identity_token_env,
        tls_config=tls_config,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        raise SystemExit(f"[ERROR] {e}") from e
