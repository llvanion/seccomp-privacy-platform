#!/usr/bin/env python3
import argparse
import json

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
    rotate.add_argument("--secret-env", required=True)
    rotate.add_argument("--caller", required=True)
    rotate.add_argument("--activate", action="store_true")
    rotate.add_argument("--create-key", action="store_true")

    set_status = sub.add_parser("set-status")
    set_status.add_argument("--config", required=True)
    set_status.add_argument("--key-name", required=True)
    set_status.add_argument("--version", required=True)
    set_status.add_argument("--status", required=True)
    set_status.add_argument("--caller", required=True)

    args = ap.parse_args()
    config = load_external_kms_config(args.config)

    if args.cmd == "rotate":
        result = rotate_external_key(
            config,
            key_name=args.key_name,
            purpose=args.purpose,
            new_version=args.new_version,
            secret_env=args.secret_env,
            caller=args.caller,
            activate=args.activate,
            create_key=args.create_key,
        )
    else:
        result = set_external_key_status(
            config,
            key_name=args.key_name,
            version=args.version,
            status=args.status,
            caller=args.caller,
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
