#!/usr/bin/env python3
import argparse
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hmac_sha256_hex(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def resolve_hmac(key_env: str, artifact_sha256: str) -> tuple[Optional[str], Optional[dict]]:
    if not key_env:
        return None, None
    secret = os.environ.get(key_env)
    if not secret:
        raise ValueError(f"audit seal key env {key_env} is not set")
    return hmac_sha256_hex(secret, artifact_sha256), {"kind": "env", "name": key_env}


def main() -> int:
    ap = argparse.ArgumentParser(description="Write a SHA-256/HMAC seal for an audit artifact.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--hmac-key-env", default="")
    args = ap.parse_args()

    data = read_bytes(args.input)
    digest = sha256_hex(data)
    signature, secret_source = resolve_hmac(args.hmac_key_env, digest)
    record = {
        "schema": "audit_seal/v1",
        "ts_utc": utc_now_iso(),
        "event": "audit_seal",
        "job_id": args.job_id,
        "correlation_id": args.job_id,
        "artifact_file": os.path.abspath(args.input),
        "artifact_sha256": digest,
        "signature_algorithm": "hmac-sha256" if signature else None,
        "signature": signature,
        "secret_source": secret_source,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[ok] audit seal: {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        raise SystemExit(f"[ERROR] {e}") from e
