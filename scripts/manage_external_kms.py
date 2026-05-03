#!/usr/bin/env python3
import argparse
import json
import os

from external_kms_lib import (
    load_external_kms_config,
    rotate_external_key,
    set_external_key_status,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Manage key lifecycle through the external KMS HTTP API.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    rotate = sub.add_parser("rotate")
    rotate.add_argument("--config", required=True)
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
    rotate.add_argument("--identity-token-env", default="")

    set_status = sub.add_parser("set-status")
    set_status.add_argument("--config", required=True)
    set_status.add_argument("--key-name", required=True)
    set_status.add_argument("--version", required=True)
    set_status.add_argument("--status", required=True)
    set_status.add_argument("--caller", required=True)
    set_status.add_argument("--identity-token-env", default="")

    args = ap.parse_args()
    config = load_external_kms_config(args.config)
    identity_bearer_token = ""
    if getattr(args, "identity_token_env", ""):
        identity_bearer_token = os.environ.get(args.identity_token_env, "")
        if not identity_bearer_token:
            raise SystemExit(f"[ERROR] environment variable {args.identity_token_env} is not set")

    if args.cmd == "rotate":
        result = rotate_external_key(
            config,
            key_name=args.key_name,
            purpose=args.purpose,
            new_version=args.new_version,
            secret_env=args.secret_env,
            secret_ref_kind=args.secret_ref_kind,
            secret_ref_name=args.secret_ref_name,
            secret_ref_version=args.secret_ref_version,
            secret_ref_field=args.secret_ref_field,
            caller=args.caller,
            activate=args.activate,
            create_key=args.create_key,
            identity_bearer_token=identity_bearer_token,
        )
    else:
        result = set_external_key_status(
            config,
            key_name=args.key_name,
            version=args.version,
            status=args.status,
            caller=args.caller,
            identity_bearer_token=identity_bearer_token,
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
