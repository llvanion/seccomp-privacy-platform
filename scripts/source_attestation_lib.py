#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from validate_json_contract import load_json, validate_value

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

    _CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when cryptography is missing
    serialization = None
    Ed25519PrivateKey = Any  # type: ignore[assignment]
    Ed25519PublicKey = Any  # type: ignore[assignment]
    _CRYPTO_AVAILABLE = False


SIGNATURE_CANONICALIZATION = "json/sort_keys/separators=comma-colon/utf8"
SOURCE_EXPORT_MANIFEST_SCHEMA = "source_export_manifest/v1"
SOURCE_ATTESTATION_SCHEMA = "source_attestation/v1"
SOURCE_TRUTHFULNESS_REPORT_SCHEMA = "source_truthfulness_report/v1"
RELEASE_GOVERNANCE_REPORT_SCHEMA = "release_governance_report/v1"
SOURCE_ATTESTATION_SIGNATURE_FIELDS = (
    "signature_algorithm",
    "canonicalization",
    "payload_sha256",
    "signature",
    "public_key_pem",
    "public_key_fingerprint_sha256",
    "signed_at_utc",
)
SOURCE_ATTESTATION_MODES = {"planned", "local", "manual", "operator", "external"}
SOURCE_ATTESTATION_STRICT_FAIL_MODES = {"planned", "local", "manual"}
SOURCE_ATTESTATION_SIGNOFF_STATUSES = {"planned", "pending", "approved", "approved_dual", "rejected"}
SOURCE_ATTESTATION_APPROVED_STATUSES = {"approved", "approved_dual"}


def utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_payload_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def file_descriptor(*, label: str, path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "label": label,
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def combined_hash(descriptors: Iterable[dict[str, Any]]) -> str:
    normalized = [
        {
            "label": str(item["label"]),
            "sha256": str(item["sha256"]),
        }
        for item in descriptors
    ]
    normalized.sort(key=lambda item: item["label"])
    return canonical_payload_sha256(normalized)


def validate_schema(payload: dict[str, Any], *, repo_root: Path, schema_filename: str) -> None:
    schema = load_json(str(repo_root / "schemas" / schema_filename))
    validate_value(payload, schema)


def normalized_identity(value: Any) -> str:
    text = str(value or "").strip()
    return text.casefold() if text else ""


def same_identity(left: Any, right: Any) -> bool:
    normalized_left = normalized_identity(left)
    normalized_right = normalized_identity(right)
    return bool(normalized_left) and normalized_left == normalized_right


def signable_payload(attestation: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in attestation.items() if key not in SOURCE_ATTESTATION_SIGNATURE_FIELDS}


def _b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package is required for Ed25519 signing")
    raw = path.read_bytes()
    key = serialization.load_pem_private_key(raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("source attestation signing key must be Ed25519")
    return key


def _load_public_key_from_pem(pem: str) -> Ed25519PublicKey:
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package is required for Ed25519 verification")
    key = serialization.load_pem_public_key(pem.encode("utf-8"))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("source attestation public key must be Ed25519")
    return key


def public_key_pem(private_key: Ed25519PrivateKey) -> str:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


def public_key_fingerprint(public_key_pem_text: str) -> str:
    return hashlib.sha256(public_key_pem_text.encode("utf-8")).hexdigest()


def attach_ed25519_signature(
    *,
    attestation: dict[str, Any],
    signing_key_path: Path,
    signed_at_utc: str | None = None,
) -> dict[str, Any]:
    private_key = _load_private_key(signing_key_path)
    payload = signable_payload(attestation)
    payload_sha256 = canonical_payload_sha256(payload)
    signature = private_key.sign(canonical_json_bytes(payload))
    public_pem = public_key_pem(private_key)
    signed = dict(attestation)
    signed.update(
        {
            "signature_algorithm": "ed25519",
            "canonicalization": SIGNATURE_CANONICALIZATION,
            "payload_sha256": payload_sha256,
            "signature": _b64encode(signature),
            "public_key_pem": public_pem,
            "public_key_fingerprint_sha256": public_key_fingerprint(public_pem),
            "signed_at_utc": signed_at_utc or utc_now_iso(),
        }
    )
    return signed


def verify_ed25519_signature(attestation: dict[str, Any]) -> tuple[bool, str | None]:
    if attestation.get("signature_algorithm") in (None, ""):
        return False, "signature_missing"
    if attestation.get("signature_algorithm") != "ed25519":
        return False, "signature_algorithm_unsupported"
    if attestation.get("canonicalization") != SIGNATURE_CANONICALIZATION:
        return False, "signature_canonicalization_invalid"
    payload = signable_payload(attestation)
    expected_sha = canonical_payload_sha256(payload)
    actual_sha = str(attestation.get("payload_sha256") or "")
    if actual_sha != expected_sha:
        return False, "payload_sha256_mismatch"
    public_pem = str(attestation.get("public_key_pem") or "")
    if not public_pem:
        return False, "public_key_missing"
    expected_fp = public_key_fingerprint(public_pem)
    if str(attestation.get("public_key_fingerprint_sha256") or "") != expected_fp:
        return False, "public_key_fingerprint_mismatch"
    signature_b64 = str(attestation.get("signature") or "")
    if not signature_b64:
        return False, "signature_missing"
    public_key = _load_public_key_from_pem(public_pem)
    try:
        public_key.verify(_b64decode(signature_b64), canonical_json_bytes(payload))
    except Exception:
        return False, "signature_invalid"
    return True, None
