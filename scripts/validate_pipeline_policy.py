#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
from typing import NoReturn


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "sse"))

from toolkit.platform_policy import (  # noqa: E402
    load_platform_policy,
    platform_policy_for_caller,
    require_platform_permission,
    resolve_platform_scope,
)


def die(msg: str) -> NoReturn:
    raise SystemExit(f"[ERROR] {msg}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate cross-stage pipeline permissions from a policy config.")
    ap.add_argument("--policy-config", required=True)
    ap.add_argument("--caller", required=True)
    ap.add_argument("--tenant-id", default="")
    ap.add_argument("--dataset-id", default="")
    ap.add_argument("--service-id", default="")
    ap.add_argument("--require-bridge", action="store_true")
    ap.add_argument("--require-record-recovery", action="store_true")
    ap.add_argument("--require-pjc", action="store_true")
    ap.add_argument("--require-release", action="store_true")
    args = ap.parse_args()

    try:
        caller_policy = platform_policy_for_caller(load_platform_policy(args.policy_config), args.caller)
        resolve_platform_scope(
            caller_policy=caller_policy,
            caller=args.caller,
            tenant_id=args.tenant_id,
            dataset_id=args.dataset_id,
            service_id=args.service_id,
            require_record_recovery_service=args.require_record_recovery,
        )
        if args.require_bridge:
            require_platform_permission(caller_policy, "can_run_bridge", args.caller)
        if args.require_pjc:
            require_platform_permission(caller_policy, "can_run_pjc", args.caller)
        if args.require_release:
            require_platform_permission(caller_policy, "can_release", args.caller)
    except Exception as exc:
        die(str(exc))

    print(f"[ok] pipeline policy validated for caller={args.caller}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
