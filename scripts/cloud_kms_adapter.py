#!/usr/bin/env python3
"""Optional cloud KMS adapter helpers.

The repo does not require boto3 for default CI. The AWS KMS decrypt path is
loaded lazily only when a caller explicitly asks for a live decrypt.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import utc_now  # noqa: E402

REPORT_SCHEMA = "cloud_kms_adapter_result/v1"


def _sha256_b64(value: str) -> str:
    return hashlib.sha256(base64.b64decode(value.encode("ascii"))).hexdigest()


def decrypt_aws_kms(secret_ref: dict[str, Any]) -> str:
    try:
        import boto3  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError("boto3 is required for live aws_kms decrypt") from exc
    region = str(secret_ref.get("region") or "")
    key_id = str(secret_ref.get("key_id") or "")
    ciphertext = base64.b64decode(str(secret_ref.get("ciphertext_b64") or "").encode("ascii"))
    client = boto3.client("kms", region_name=region or None)
    kwargs: dict[str, Any] = {"CiphertextBlob": ciphertext}
    if key_id:
        kwargs["KeyId"] = key_id
    response = client.decrypt(**kwargs)
    return response["Plaintext"].decode("utf-8")


def build_report(*, operation: str, secret_ref: dict[str, Any], redact: bool) -> dict[str, Any]:
    provider = str(secret_ref.get("kind") or "aws_kms")
    key_id = str(secret_ref.get("key_id") or "") or None
    region = str(secret_ref.get("region") or "") or None
    ciphertext_b64 = str(secret_ref.get("ciphertext_b64") or "")
    try:
        if operation == "decrypt":
            value = decrypt_aws_kms(secret_ref)
            output_value = "REDACTED" if redact else value
        else:
            output_value = None
        return {
            "schema": REPORT_SCHEMA,
            "generated_at_utc": utc_now(),
            "operation": operation,
            "provider": provider,
            "key_id": key_id,
            "region": region,
            "ciphertext_sha256": _sha256_b64(ciphertext_b64) if ciphertext_b64 else None,
            "value": output_value,
            "ok": True,
            "error": None,
        }
    except Exception as exc:
        return {
            "schema": REPORT_SCHEMA,
            "generated_at_utc": utc_now(),
            "operation": operation,
            "provider": provider,
            "key_id": key_id,
            "region": region,
            "ciphertext_sha256": _sha256_b64(ciphertext_b64) if ciphertext_b64 else None,
            "value": None,
            "ok": False,
            "error": str(exc),
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="Cloud KMS adapter smoke helper")
    ap.add_argument("operation", choices=["describe", "decrypt"])
    ap.add_argument("--secret-ref", required=True, help="Path to JSON object with kind=aws_kms")
    ap.add_argument("--output", default="")
    ap.add_argument("--redact", action="store_true")
    ap.add_argument("--assert-ok", action="store_true")
    args = ap.parse_args()
    payload = json.loads(Path(args.secret_ref).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("[ERROR] secret ref JSON object expected")
    report = build_report(operation=args.operation, secret_ref=payload, redact=args.redact)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 1 if args.assert_ok and not report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
