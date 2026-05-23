#!/usr/bin/env python3
"""Validate that a PJC mTLS cert bundle is bound to the current job session."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, ec


SCHEMA_ID = "pjc_mtls_session_manifest_check/v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def load_cert(path: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificate(path.read_bytes())


def fp(cert: x509.Certificate) -> str:
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def san_dns(cert: x509.Certificate) -> list[str]:
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return []
    return list(ext.value.get_values_for_type(x509.DNSName))


def verify_signature(cert: x509.Certificate, ca: x509.Certificate) -> bool:
    public_key = ca.public_key()
    try:
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(cert.signature, cert.tbs_certificate_bytes, padding.PKCS1v15(), cert.signature_hash_algorithm)
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(cert.signature_hash_algorithm))
        else:
            return False
    except InvalidSignature:
        return False
    return True


def add(findings: list[dict[str, Any]], kind: str, message: str, expected: Any = None, actual: Any = None) -> None:
    findings.append({"kind": kind, "message": message, "expected": expected, "actual": actual})


def evaluate(*, manifest_path: Path, cert_dir: Path, role: str, job_id: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "schema": SCHEMA_ID,
            "generated_at_utc": now_iso(),
            "decision": "deny",
            "reason_code": "manifest_unreadable",
            "reason": str(exc),
            "role": role,
            "job_id": job_id,
            "manifest_path": str(manifest_path),
            "cert_dir": str(cert_dir),
            "checks": {},
            "findings": [{"kind": "manifest_unreadable", "message": str(exc), "expected": "readable JSON", "actual": str(manifest_path)}],
        }

    if manifest.get("schema") != "pjc_mtls_session_manifest/v1":
        add(findings, "manifest_schema_mismatch", "unexpected session manifest schema", "pjc_mtls_session_manifest/v1", manifest.get("schema"))
    if str(manifest.get("job_id") or "") != job_id:
        add(findings, "job_id_mismatch", "session manifest job_id does not match current JOB_ID", job_id, manifest.get("job_id"))

    now = datetime.now(timezone.utc)
    not_before_raw = str(manifest.get("session_not_before_utc") or "1970-01-01T00:00:00Z")
    not_after_raw = str(manifest.get("session_not_after_utc") or "1970-01-01T00:00:00Z")
    try:
        not_before = parse_dt(not_before_raw)
        not_after = parse_dt(not_after_raw)
        if now < not_before:
            add(findings, "session_not_yet_valid", "mTLS session is not yet valid", not_before_raw, now_iso())
        if now > not_after:
            add(findings, "session_expired", "mTLS session has expired", not_after_raw, now_iso())
    except Exception as exc:
        add(findings, "session_time_invalid", "session validity timestamps are invalid", "ISO-8601 UTC", str(exc))

    try:
        ca_cert = load_cert(cert_dir / "ca.crt")
        server_cert = load_cert(cert_dir / "server.crt") if (cert_dir / "server.crt").exists() else None
        client_cert = load_cert(cert_dir / "client.crt")
    except Exception as exc:
        add(findings, "cert_unreadable", "required certificate could not be read", "ca.crt/client.crt and server.crt for server role", str(exc))
        ca_cert = None
        server_cert = None
        client_cert = None

    checks: dict[str, Any] = {
        "manifest_job_id": manifest.get("job_id"),
        "session_not_before_utc": not_before_raw,
        "session_not_after_utc": not_after_raw,
    }
    if ca_cert is not None:
        ca_actual = fp(ca_cert)
        ca_expected = (((manifest.get("ca") or {}).get("fingerprint_sha256")) or "").lower()
        checks["ca_fingerprint_sha256"] = ca_actual
        if ca_expected and ca_actual != ca_expected:
            add(findings, "ca_fingerprint_mismatch", "CA fingerprint does not match session manifest", ca_expected, ca_actual)

    role_cert = server_cert if role == "server" else client_cert
    role_manifest = manifest.get(role) if isinstance(manifest.get(role), dict) else {}
    if role_cert is not None:
        actual_fp = fp(role_cert)
        expected_fp = str(role_manifest.get("fingerprint_sha256") or "").lower()
        expected_identity = str(role_manifest.get("job_bound_identity") or "")
        checks[f"{role}_fingerprint_sha256"] = actual_fp
        checks[f"{role}_expected_identity"] = expected_identity
        checks[f"{role}_san_dns_names"] = san_dns(role_cert)
        if expected_fp and actual_fp != expected_fp:
            add(findings, "role_cert_fingerprint_mismatch", f"{role} certificate fingerprint does not match session manifest", expected_fp, actual_fp)
        if expected_identity and expected_identity not in san_dns(role_cert):
            add(findings, "job_bound_identity_missing", f"{role} certificate does not contain job-bound DNS SAN", expected_identity, san_dns(role_cert))
        if ca_cert is not None and not verify_signature(role_cert, ca_cert):
            add(findings, "role_cert_ca_mismatch", f"{role} certificate is not signed by session CA", "valid CA signature", "verification failed")

    # The server side must also bind the expected client cert to the same job.
    if role == "server" and client_cert is not None:
        client_manifest = manifest.get("client") if isinstance(manifest.get("client"), dict) else {}
        actual_client_fp = fp(client_cert)
        expected_client_fp = str(client_manifest.get("fingerprint_sha256") or "").lower()
        expected_client_identity = str(client_manifest.get("job_bound_identity") or "")
        checks["expected_client_fingerprint_sha256"] = actual_client_fp
        checks["expected_client_identity"] = expected_client_identity
        if expected_client_fp and actual_client_fp != expected_client_fp:
            add(findings, "expected_client_fingerprint_mismatch", "expected client certificate fingerprint does not match session manifest", expected_client_fp, actual_client_fp)
        if expected_client_identity and expected_client_identity not in san_dns(client_cert):
            add(findings, "expected_client_identity_missing", "expected client certificate does not contain job-bound DNS SAN", expected_client_identity, san_dns(client_cert))
        if ca_cert is not None and not verify_signature(client_cert, ca_cert):
            add(findings, "expected_client_ca_mismatch", "expected client certificate is not signed by session CA", "valid CA signature", "verification failed")

    decision = "deny" if findings else "allow"
    return {
        "schema": SCHEMA_ID,
        "generated_at_utc": now_iso(),
        "decision": decision,
        "reason_code": findings[0]["kind"] if findings else "ok",
        "reason": findings[0]["message"] if findings else None,
        "role": role,
        "job_id": job_id,
        "manifest_path": str(manifest_path),
        "cert_dir": str(cert_dir),
        "checks": checks,
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a job-bound PJC mTLS session manifest")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--cert-dir", required=True)
    parser.add_argument("--role", choices=("server", "client"), required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--output")
    parser.add_argument("--assert-allow", action="store_true")
    args = parser.parse_args()

    report = evaluate(
        manifest_path=Path(args.manifest).expanduser().resolve(),
        cert_dir=Path(args.cert_dir).expanduser().resolve(),
        role=args.role,
        job_id=args.job_id,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.assert_allow and report["decision"] != "allow":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
