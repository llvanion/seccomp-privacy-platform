#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict

from api_identity import resolve_identity_context
from keyring_lib import (
    append_key_lifecycle_audit,
    key_entry,
    load_json_object,
    rotate_key,
    save_json_object,
    set_version_status,
)

ADMIN_PLATFORM_ROLES = {"platform_admin"}
SERVICE_OPERATOR_PLATFORM_ROLES = {"service_operator"}


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


def identity_has_any_role(identity: Dict[str, Any] | None, *roles: str) -> bool:
    if not identity:
        return False
    current = set(identity.get("platform_roles") or [])
    return any(role in current for role in roles)


def resolve_cli_identity(args: argparse.Namespace) -> Dict[str, Any] | None:
    identity_token_env = str(getattr(args, "identity_token_env", "") or "")
    if not identity_token_env:
        return None
    metadata_db_path = str(getattr(args, "metadata_db_path", "") or "")
    identity_token_config = str(getattr(args, "identity_token_config", "") or "")
    if not metadata_db_path or not identity_token_config:
        raise SystemExit("[ERROR] --identity-token-env requires --metadata-db-path and --identity-token-config")
    bearer_token = os.environ.get(identity_token_env, "")
    if not bearer_token:
        raise SystemExit(f"[ERROR] environment variable {identity_token_env} is not set")
    return resolve_identity_context(
        db_path=metadata_db_path,
        identity_token_config=identity_token_config,
        bearer_token=bearer_token,
    )


def authorize_keyring_admin_identity(
    *,
    identity: Dict[str, Any] | None,
    keyring: Dict[str, Any],
    key_name: str,
    caller: str,
    create_key: bool,
) -> str:
    if identity is None:
        return caller
    if caller and caller != identity["caller"]:
        raise PermissionError("keyring admin caller does not match authenticated identity")
    resolved_caller = identity["caller"]
    if identity_has_any_role(identity, *ADMIN_PLATFORM_ROLES):
        return resolved_caller
    if not identity_has_any_role(identity, *SERVICE_OPERATOR_PLATFORM_ROLES):
        raise PermissionError("keyring admin requires platform_admin or service_operator role")
    if create_key:
        raise PermissionError("service_operator cannot create new local keyring keys")
    try:
        entry = key_entry(keyring, key_name)
    except ValueError as exc:
        raise PermissionError(str(exc)) from exc
    allowed_callers = entry.get("allowed_callers", [])
    if not isinstance(allowed_callers, list) or resolved_caller not in {str(item) for item in allowed_callers}:
        raise PermissionError(f"service_operator caller {resolved_caller} is not allowed to manage key {key_name}")
    return resolved_caller


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
    rotate.add_argument("--secret-env", default="")
    rotate.add_argument("--secret-ref-kind", default="")
    rotate.add_argument("--secret-ref-name", default="")
    rotate.add_argument("--secret-ref-version", default="")
    rotate.add_argument("--secret-ref-field", default="")
    rotate.add_argument("--caller", required=True)
    rotate.add_argument("--activate", action="store_true")
    rotate.add_argument("--create-key", action="store_true")
    rotate.add_argument("--audit-log", default="")
    rotate.add_argument("--metadata-db-path", default="")
    rotate.add_argument("--identity-token-config", default="")
    rotate.add_argument("--identity-token-env", default="")

    set_status = sub.add_parser("set-status")
    set_status.add_argument("--keyring", required=True)
    set_status.add_argument("--key-name", required=True)
    set_status.add_argument("--version", required=True)
    set_status.add_argument("--status", required=True, choices=["active", "inactive", "retired"])
    set_status.add_argument("--caller", required=True)
    set_status.add_argument("--audit-log", default="")
    set_status.add_argument("--metadata-db-path", default="")
    set_status.add_argument("--identity-token-config", default="")
    set_status.add_argument("--identity-token-env", default="")

    args = ap.parse_args()

    if args.cmd == "describe":
        keyring = load_json_object(args.keyring)
        print(json.dumps(describe_keyring(keyring), ensure_ascii=False, indent=2))
        return 0

    keyring = load_json_object(args.keyring)
    identity = resolve_cli_identity(args)
    if args.cmd == "rotate":
        caller = authorize_keyring_admin_identity(
            identity=identity,
            keyring=keyring,
            key_name=args.key_name,
            caller=args.caller,
            create_key=args.create_key,
        )
        if args.secret_ref_kind or args.secret_ref_name:
            if not args.secret_ref_kind or not args.secret_ref_name:
                raise SystemExit("[ERROR] --secret-ref-kind and --secret-ref-name must be provided together")
            secret_ref = {
                "kind": args.secret_ref_kind,
                "name": args.secret_ref_name,
            }
            if args.secret_ref_version:
                secret_ref["version"] = args.secret_ref_version
            if args.secret_ref_field:
                secret_ref["field"] = args.secret_ref_field
        else:
            secret_ref = None
        rotate_key(
            keyring=keyring,
            key_name=args.key_name,
            purpose=args.purpose,
            new_version=args.new_version,
            caller=caller,
            activate=args.activate,
            secret_env=args.secret_env,
            secret_ref=secret_ref,
            create_key=args.create_key,
        )
        save_json_object(args.keyring, keyring)
        if args.audit_log:
            if secret_ref is not None:
                secret_source_kind = str(secret_ref["kind"])
                secret_source_name = str(secret_ref["name"])
            else:
                secret_source_kind = "env"
                secret_source_name = args.secret_env
            append_key_lifecycle_audit(
                path=args.audit_log,
                caller=caller,
                keyring_file=args.keyring,
                key_name=args.key_name,
                key_version=args.new_version,
                action="rotate",
                status="active" if args.activate else "inactive",
                decision="allow",
                reason_code="ok",
                secret_source_kind=secret_source_kind,
                secret_source_name=secret_source_name,
            )
        print(json.dumps({
            "key_name": args.key_name,
            "new_version": args.new_version,
            "active_version": key_entry(keyring, args.key_name).get("active_version"),
        }, ensure_ascii=False))
        return 0

    caller = authorize_keyring_admin_identity(
        identity=identity,
        keyring=keyring,
        key_name=args.key_name,
        caller=args.caller,
        create_key=False,
    )
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
            caller=caller,
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
