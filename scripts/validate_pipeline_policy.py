#!/usr/bin/env python3
import argparse
import json
from typing import Any, Dict, NoReturn


def die(msg: str) -> NoReturn:
    raise SystemExit(f"[ERROR] {msg}")


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        die("pipeline policy config must be a JSON object")
    return data


def caller_policy(config: Dict[str, Any], caller: str) -> Dict[str, Any]:
    schema = config.get("schema")
    if schema is not None and schema != "sse_export_policy/v1":
        die(f"unsupported policy schema: {schema}")
    callers = config.get("callers")
    if not isinstance(callers, dict):
        die("pipeline policy config must contain a callers object")
    policy = callers.get(caller)
    if not isinstance(policy, dict):
        die(f"caller {caller} is not allowed")
    if policy.get("enabled", True) is False:
        die(f"caller {caller} is disabled")
    return policy


def require_bool(policy: Dict[str, Any], key: str, caller: str) -> None:
    if policy.get(key) is not True:
        die(f"caller {caller} is missing permission {key}=true")


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate cross-stage pipeline permissions from a policy config.")
    ap.add_argument("--policy-config", required=True)
    ap.add_argument("--caller", required=True)
    ap.add_argument("--require-bridge", action="store_true")
    ap.add_argument("--require-pjc", action="store_true")
    ap.add_argument("--require-release", action="store_true")
    args = ap.parse_args()

    policy = caller_policy(load_json(args.policy_config), args.caller)
    if args.require_bridge:
        require_bool(policy, "can_run_bridge", args.caller)
    if args.require_pjc:
        require_bool(policy, "can_run_pjc", args.caller)
    if args.require_release:
        require_bool(policy, "can_release", args.caller)

    print(f"[ok] pipeline policy validated for caller={args.caller}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
