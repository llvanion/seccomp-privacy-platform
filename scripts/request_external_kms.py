#!/usr/bin/env python3
import argparse
import json

from external_kms_lib import endpoint_url, load_external_kms_config, resolve_secret_via_external_kms
from keyring_lib import append_key_access_audit


def main() -> int:
    ap = argparse.ArgumentParser(description="Request a secret from the configured external KMS endpoint.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--key-name", required=True)
    ap.add_argument("--purpose", required=True)
    ap.add_argument("--caller", required=True)
    ap.add_argument("--job-id", default="")
    ap.add_argument("--audit-log", required=True)
    args = ap.parse_args()

    config = load_external_kms_config(args.config)
    try:
        result = resolve_secret_via_external_kms(
            config,
            key_name=args.key_name,
            purpose=args.purpose,
            caller=args.caller,
            job_id=args.job_id,
        )
        if result.get("schema") != "external_kms_result/v1":
            raise RuntimeError(f"unexpected external KMS schema: {result.get('schema')}")
        append_key_access_audit(
            path=args.audit_log,
            caller=args.caller,
            job_id=args.job_id,
            key_id=args.key_name,
            key_version=str(result.get("key_version", "")),
            purpose=args.purpose,
            decision="allow",
            reason_code="ok",
            config_file=args.config,
            secret_source_kind="external_kms",
            secret_source_name=endpoint_url(config),
            resolver_kind="external_kms_http",
            endpoint_url=endpoint_url(config),
        )
    except Exception as e:
        append_key_access_audit(
            path=args.audit_log,
            caller=args.caller,
            job_id=args.job_id,
            key_id=args.key_name,
            key_version="unknown",
            purpose=args.purpose,
            decision="deny",
            reason_code="request_failed",
            config_file=args.config,
            secret_source_kind="external_kms",
            secret_source_name=endpoint_url(config),
            resolver_kind="external_kms_http",
            endpoint_url=endpoint_url(config),
            reason=str(e),
        )
        raise SystemExit(f"[ERROR] {e}") from e

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
