#!/usr/bin/env python3
"""
S7 PJC mTLS identity gate.

Loads a peer X.509 certificate (PEM) and checks:

1. The cert is parseable.
2. `notBefore <= now <= notAfter` (with optional clock-skew override).
3. The SHA-256 fingerprint matches `--expected-fingerprint-sha256` if provided.
4. The peer identity (CN or any DNS SAN) matches `--expected-peer-identity`
   if provided. Identity strings should be `job-id-bound`, e.g.
   `job-<job_id>.partyA.example`.
5. The cert is signed by the supplied CA when `--ca-cert` is given (the
   verification uses cryptography's certificate-signature interface; full
   path validation against intermediates is out of scope and should be
   handled by the gRPC stack itself).

Emits `pjc_tls_identity_check/v1`. Exits non-zero on `decision=deny`
when `--assert-allow` is set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, ec

SCHEMA_ID = "pjc_tls_identity_check/v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_cert(path: str) -> x509.Certificate:
    with open(path, "rb") as fh:
        return x509.load_pem_x509_certificate(fh.read())


def _fingerprint_sha256(cert: x509.Certificate) -> str:
    der = cert.public_bytes(serialization.Encoding.DER)
    return hashlib.sha256(der).hexdigest()


def _san_dns_names(cert: x509.Certificate) -> list[str]:
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return []
    return list(ext.value.get_values_for_type(x509.DNSName))


def _common_name(name: x509.Name) -> Optional[str]:
    for attr in name:
        if attr.oid == x509.NameOID.COMMON_NAME:
            return str(attr.value)
    return None


def _verify_ca_signature(cert: x509.Certificate, ca: x509.Certificate) -> bool:
    public_key = ca.public_key()
    try:
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(
                cert.signature,
                cert.tbs_certificate_bytes,
                padding.PKCS1v15(),
                cert.signature_hash_algorithm,
            )
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(
                cert.signature,
                cert.tbs_certificate_bytes,
                ec.ECDSA(cert.signature_hash_algorithm),
            )
        else:
            return False
    except InvalidSignature:
        return False
    return True


def evaluate(
    *,
    cert_path: str,
    ca_path: Optional[str],
    role: str,
    job_id: str,
    expected_fingerprint: Optional[str],
    expected_peer_identity: Optional[str],
    now_override: Optional[str],
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    try:
        cert = _load_cert(cert_path)
    except Exception as exc:
        return {
            "schema": SCHEMA_ID,
            "generated_at_utc": now_override or _utc_now_iso(),
            "decision": "deny",
            "reason_code": "cert_unreadable",
            "reason": f"failed to parse cert at {cert_path}: {exc}",
            "role": role,
            "job_id": job_id,
            "cert_path": cert_path,
            "ca_path": ca_path,
            "fingerprint_sha256": "0" * 64,
            "subject": "",
            "issuer": None,
            "san_dns_names": [],
            "validity": {
                "not_before_utc": "1970-01-01T00:00:00Z",
                "not_after_utc": "1970-01-01T00:00:00Z",
                "now_utc": now_override or _utc_now_iso(),
            },
            "checks": {
                "validity_window_ok": False,
                "fingerprint_ok": None,
                "peer_identity_ok": None,
                "ca_signed_ok": None,
                "expected_fingerprint_sha256": expected_fingerprint,
                "expected_peer_identity": expected_peer_identity,
            },
            "findings": [
                {"kind": "cert_unreadable", "message": str(exc), "expected": "PEM cert", "actual": cert_path}
            ],
        }

    fingerprint = _fingerprint_sha256(cert)
    subject_common_name = _common_name(cert.subject) or ""
    subject_str = cert.subject.rfc4514_string()
    issuer_str = cert.issuer.rfc4514_string()
    san_dns = _san_dns_names(cert)
    not_before = _aware(cert.not_valid_before_utc) if hasattr(cert, "not_valid_before_utc") else _aware(cert.not_valid_before)
    not_after = _aware(cert.not_valid_after_utc) if hasattr(cert, "not_valid_after_utc") else _aware(cert.not_valid_after)
    now_dt = _aware(datetime.fromisoformat(now_override.replace("Z", "+00:00"))) if now_override else _aware(datetime.now(timezone.utc))

    validity_window_ok = not_before <= now_dt <= not_after
    if now_dt < not_before:
        findings.append(
            {
                "kind": "cert_not_yet_valid",
                "message": f"now {now_dt.isoformat()} < notBefore {not_before.isoformat()}",
                "expected": f">= {not_before.isoformat()}",
                "actual": now_dt.isoformat(),
            }
        )
    elif now_dt > not_after:
        findings.append(
            {
                "kind": "cert_expired",
                "message": f"now {now_dt.isoformat()} > notAfter {not_after.isoformat()}",
                "expected": f"<= {not_after.isoformat()}",
                "actual": now_dt.isoformat(),
            }
        )

    fingerprint_ok: Optional[bool] = None
    if expected_fingerprint:
        fingerprint_ok = expected_fingerprint.lower() == fingerprint.lower()
        if not fingerprint_ok:
            findings.append(
                {
                    "kind": "fingerprint_mismatch",
                    "message": "cert SHA-256 fingerprint does not match expected",
                    "expected": expected_fingerprint.lower(),
                    "actual": fingerprint,
                }
            )

    peer_identity_ok: Optional[bool] = None
    if expected_peer_identity:
        candidates = set(san_dns) | ({subject_common_name} if subject_common_name else set())
        peer_identity_ok = expected_peer_identity in candidates
        if not peer_identity_ok:
            findings.append(
                {
                    "kind": "peer_identity_mismatch",
                    "message": "expected peer identity not found in CN or DNS SANs",
                    "expected": expected_peer_identity,
                    "actual": sorted(candidates),
                }
            )

    ca_signed_ok: Optional[bool] = None
    if ca_path:
        try:
            ca_cert = _load_cert(ca_path)
            ca_signed_ok = _verify_ca_signature(cert, ca_cert)
            if not ca_signed_ok:
                findings.append(
                    {
                        "kind": "ca_mismatch",
                        "message": "cert signature does not verify against supplied CA",
                        "expected": "valid signature by supplied CA",
                        "actual": "verification failed",
                    }
                )
        except Exception as exc:
            ca_signed_ok = False
            findings.append(
                {
                    "kind": "ca_mismatch",
                    "message": f"failed to verify against CA at {ca_path}: {exc}",
                    "expected": "readable PEM CA",
                    "actual": ca_path,
                }
            )

    if findings:
        decision = "deny"
        reason_code = findings[0]["kind"]
        reason = findings[0]["message"]
    else:
        decision = "allow"
        reason_code = "ok"
        reason = None

    return {
        "schema": SCHEMA_ID,
        "generated_at_utc": now_override or _utc_now_iso(),
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason,
        "role": role,
        "job_id": job_id,
        "cert_path": cert_path,
        "ca_path": ca_path,
        "fingerprint_sha256": fingerprint,
        "subject": subject_str,
        "issuer": issuer_str,
        "san_dns_names": san_dns,
        "validity": {
            "not_before_utc": not_before.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "not_after_utc": not_after.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "now_utc": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "checks": {
            "validity_window_ok": bool(validity_window_ok),
            "fingerprint_ok": fingerprint_ok,
            "peer_identity_ok": peer_identity_ok,
            "ca_signed_ok": ca_signed_ok,
            "expected_fingerprint_sha256": expected_fingerprint.lower() if expected_fingerprint else None,
            "expected_peer_identity": expected_peer_identity,
        },
        "findings": findings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="S7 PJC mTLS peer identity / fingerprint / validity check")
    ap.add_argument("--cert", required=True, help="PEM cert to inspect (peer cert)")
    ap.add_argument("--ca-cert", default=None, help="Optional CA cert PEM to verify cert signature against")
    ap.add_argument("--role", choices=("server", "client", "peer"), default="peer")
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--expected-fingerprint-sha256", default=None,
                    help="Hex SHA-256 fingerprint to compare to (case-insensitive)")
    ap.add_argument("--expected-peer-identity", default=None,
                    help="DNS SAN (or CN) the cert must present, e.g. job-<id>.partyA.example")
    ap.add_argument("--now-utc", default=None,
                    help="Override current time (ISO8601 UTC); only intended for testing")
    ap.add_argument("--output", default="", help="Write report JSON here (default: stdout)")
    ap.add_argument("--assert-allow", action="store_true",
                    help="Exit non-zero if decision is not 'allow'")
    args = ap.parse_args()

    report = evaluate(
        cert_path=args.cert,
        ca_path=args.ca_cert,
        role=args.role,
        job_id=args.job_id,
        expected_fingerprint=args.expected_fingerprint_sha256,
        expected_peer_identity=args.expected_peer_identity,
        now_override=args.now_utc,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")
    if args.assert_allow and report["decision"] != "allow":
        print(
            f"[error] mTLS identity check denied {args.role} cert: "
            f"{report['reason_code']}: {report['reason']}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
