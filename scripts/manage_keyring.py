#!/usr/bin/env python3
import argparse
import json
from typing import Any, Dict

from keyring_lib import (
    append_key_lifecycle_audit,
    key_entry,
    load_json_object,
    rotate_key,
    save_json_object,
    set_version_status,
)


def describe_keyring(keyring: Dict[str, Any]) -> Dict[str, Any]:
    keys = keyring.get("keys", {})
    if not isinstance(keys, dict):
        raise ValueError("keyring must contain a keys object")
    summary = {"schema": keyring.get("schema"), "keys": {}}
    for key_name, value in keys.items():
        if not isinstance(value, dict):
            raise ValueError(f"key {key_name} must be an object")
        versions = value.get("versions", {})
        summary["keys"][key_name] = {
            "purpose": value.get("purpose"),
            "active_version": value.get("active_version"),
            "allowed_callers": value.get("allowed_callers", []),
            "versions": {
                version_name: {
                    "enabled": version_value.get("enabled"),
                    "status": version_value.get("status"),
                    "secret_ref": version_value.get("secret_ref"),
                }
                for version_name, version_value in versions.items()
                if isinstance(version_value, dict)
            },
        }
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Manage local keyring lifecycle state.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    describe = sub.add_parser("describe")
    describe.add_argument("--keyring", required=True)

    rotate = sub.add_parser("rotate")
    rotate.add_argument("--keyring", required=True)
    rotate.add_argument("--key-name", required=True)
    rotate.add_argument("--purpose", required=True)
    rotate.add_argument("--new-version", required=True)
    rotate.add_argument("--secret-env", required=True)
    rotate.add_argument("--caller", required=True)
    rotate.add_argument("--activate", action="store_true")
    rotate.add_argument("--create-key", action="store_true")
    rotate.add_argument("--audit-log", default="")

    set_status = sub.add_parser("set-status")
    set_status.add_argument("--keyring", required=True)
    set_status.add_argument("--key-name", required=True)
    set_status.add_argument("--version", required=True)
    set_status.add_argument("--status", required=True, choices=["active", "inactive", "retired"])
    set_status.add_argument("--caller", required=True)
    set_status.add_argument("--audit-log", default="")

    args = ap.parse_args()

    if args.cmd == "describe":
        keyring = load_json_object(args.keyring)
        print(json.dumps(describe_keyring(keyring), ensure_ascii=False, indent=2))
        return 0

    keyring = load_json_object(args.keyring)
    if args.cmd == "rotate":
        rotate_key(
            keyring=keyring,
            key_name=args.key_name,
            purpose=args.purpose,
            new_version=args.new_version,
            secret_env=args.secret_env,
            caller=args.caller,
            activate=args.activate,
            create_key=args.create_key,
        )
        save_json_object(args.keyring, keyring)
        if args.audit_log:
            append_key_lifecycle_audit(
                path=args.audit_log,
                caller=args.caller,
                keyring_file=args.keyring,
                key_name=args.key_name,
                key_version=args.new_version,
                action="rotate",
                status="active" if args.activate else "inactive",
                decision="allow",
                reason_code="ok",
                secret_env=args.secret_env,
            )
        print(json.dumps({
            "key_name": args.key_name,
            "new_version": args.new_version,
            "active_version": key_entry(keyring, args.key_name).get("active_version"),
        }, ensure_ascii=False))
        return 0

    set_version_status(
        keyring=keyring,
        key_name=args.key_name,
        version=args.version,
        status=args.status,
    )
    save_json_object(args.keyring, keyring)
    if args.audit_log:
        append_key_lifecycle_audit(
            path=args.audit_log,
            caller=args.caller,
            keyring_file=args.keyring,
            key_name=args.key_name,
            key_version=args.version,
            action="set_status",
            status=args.status,
            decision="allow",
            reason_code="ok",
        )
    print(json.dumps({
        "key_name": args.key_name,
        "version": args.version,
        "status": args.status,
        "active_version": key_entry(keyring, args.key_name).get("active_version"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
