#!/usr/bin/env python3
import argparse
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Optional

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    _ED25519_AVAILABLE = True
except ImportError:
    _ED25519_AVAILABLE = False


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


def resolve_ed25519(key_env: str, artifact_sha256: str) -> tuple[Optional[str], Optional[str], Optional[dict]]:
    """Sign with Ed25519. key_env holds the 32-byte private key seed as a 64-char hex string.
    Returns (signature_hex, public_key_fingerprint_hex, source_dict)."""
    if not key_env:
        return None, None, None
    if not _ED25519_AVAILABLE:
        raise RuntimeError("cryptography package is not installed; cannot use Ed25519 signing")
    seed_hex = os.environ.get(key_env, "")
    if not seed_hex:
        raise ValueError(f"Ed25519 signing key env {key_env} is not set")
    try:
        seed_bytes = bytes.fromhex(seed_hex.strip())
    except ValueError as exc:
        raise ValueError(f"Ed25519 key in {key_env} must be a 64-char hex string (32-byte seed)") from exc
    if len(seed_bytes) != 32:
        raise ValueError(f"Ed25519 seed must be exactly 32 bytes; got {len(seed_bytes)}")
    private_key = Ed25519PrivateKey.from_private_bytes(seed_bytes)
    # Sign the raw SHA-256 digest bytes (32 bytes)
    sig_bytes = private_key.sign(bytes.fromhex(artifact_sha256))
    pub_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    fingerprint = hashlib.sha256(pub_bytes).hexdigest()
    return sig_bytes.hex(), fingerprint, {"kind": "env", "name": key_env}


def main() -> int:
    ap = argparse.ArgumentParser(description="Write a SHA-256/HMAC seal for an audit artifact.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--hmac-key-env", default="")
    ap.add_argument("--ed25519-signing-key-env", default="",
                    help="Env var holding a 64-char hex Ed25519 private key seed. "
                         "Produces an asymmetric signature verifiable with only the public key.")
    args = ap.parse_args()

    data = read_bytes(args.input)
    digest = sha256_hex(data)
    signature, secret_source = resolve_hmac(args.hmac_key_env, digest)
    ed25519_sig, ed25519_pub_fingerprint, ed25519_source = resolve_ed25519(
        args.ed25519_signing_key_env, digest
    )
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
        "ed25519_signature": ed25519_sig,
        "ed25519_public_key_fingerprint": ed25519_pub_fingerprint,
        "ed25519_secret_source": ed25519_source,
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
