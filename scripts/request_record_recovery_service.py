#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _sse_root() -> Path:
    return REPO_ROOT / "sse"


sys.path.insert(0, str(_sse_root()))

from toolkit.record_recovery_client import request_record_recovery_health  # noqa: E402
from toolkit.record_recovery_service_config import (  # noqa: E402
    load_resolved_record_recovery_service_config,
    merged_record_recovery_service_value,
)


def optional_repo_path(path_value: str) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    if path.is_absolute():
        return str(path)
    return str((REPO_ROOT / path).resolve())


def main() -> int:
    ap = argparse.ArgumentParser(description="Request a health snapshot from the local Unix-socket record recovery service.")
    ap.add_argument("--config", default="")
    ap.add_argument("--socket-path", default="")
    ap.add_argument("--auth-token-env", default="")
    args = ap.parse_args()

    config = load_resolved_record_recovery_service_config(optional_repo_path(args.config)) if args.config else {}
    socket_path = merged_record_recovery_service_value(args.socket_path, config.get("socket_path", ""))
    auth_token_env = merged_record_recovery_service_value(args.auth_token_env, config.get("auth_token_env", ""))
    if not socket_path:
        raise SystemExit("[ERROR] --socket-path or --config with socket_path is required")

    result = request_record_recovery_health(
        socket_path=Path(socket_path),
        auth_env=auth_token_env,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        raise SystemExit(f"[ERROR] {e}") from e
