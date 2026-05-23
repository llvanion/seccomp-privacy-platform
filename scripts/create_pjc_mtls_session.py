#!/usr/bin/env python3
"""Create a one-job PJC mTLS session bundle.

The legacy PJC mTLS path can reuse a shared CA/client certificate bundle.  That
is convenient, but it means a copied old client certificate can be replayed
against later jobs that keep trusting the same CA.  This helper creates a fresh
CA and fresh Party A/Party B leaf certificates per job, then writes a manifest
that the PJC TLS wrappers can verify before they start.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


SCHEMA_ID = "pjc_mtls_session_manifest/v1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def keypair() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def name(common_name: str, org: str = "PJC-TLS") -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
    ])


def fingerprint(cert: x509.Certificate) -> str:
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def write_private_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    path.chmod(0o600)


def write_cert(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    path.chmod(0o644)


def issue_leaf(
    *,
    ca_key: rsa.RSAPrivateKey,
    ca_cert: x509.Certificate,
    leaf_key: rsa.RSAPrivateKey,
    common_name: str,
    san_dns: list[str],
    not_before: datetime,
    not_after: datetime,
) -> x509.Certificate:
    return (
        x509.CertificateBuilder()
        .subject_name(name(common_name))
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(item) for item in san_dns]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True,
            content_commitment=False,
            key_encipherment=True,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=False,
            crl_sign=False,
            encipher_only=False,
            decipher_only=False,
        ), critical=True)
        .sign(ca_key, hashes.SHA256())
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a one-job PJC mTLS cert bundle and session manifest")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--ttl-hours", type=int, default=24)
    parser.add_argument("--server-common-name", default="pjc-server")
    parser.add_argument("--client-common-name", default="pjc-client")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing non-empty out-dir")
    args = parser.parse_args()

    if args.ttl_hours < 1:
        raise SystemExit("--ttl-hours must be >= 1")
    job_id = args.job_id.strip()
    if not job_id:
        raise SystemExit("--job-id must be non-empty")

    out_dir = Path(args.out_dir).expanduser().resolve()
    if out_dir.exists() and any(out_dir.iterdir()) and not args.force:
        raise SystemExit(f"{out_dir} is not empty; pass --force to replace files")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.chmod(0o700)

    now = utc_now()
    not_before = now - timedelta(minutes=5)
    not_after = now + timedelta(hours=args.ttl_hours)

    ca_key = keypair()
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(name(f"pjc-ca-{job_id}"))
        .issuer_name(name(f"pjc-ca-{job_id}"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True,
            content_commitment=False,
            key_encipherment=False,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=True,
            crl_sign=True,
            encipher_only=False,
            decipher_only=False,
        ), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    server_key = keypair()
    client_key = keypair()
    server_identity = f"job-{job_id}.partyA.example"
    client_identity = f"job-{job_id}.partyB.example"
    server_cert = issue_leaf(
        ca_key=ca_key,
        ca_cert=ca_cert,
        leaf_key=server_key,
        common_name=args.server_common_name,
        san_dns=[args.server_common_name, server_identity],
        not_before=not_before,
        not_after=not_after,
    )
    client_cert = issue_leaf(
        ca_key=ca_key,
        ca_cert=ca_cert,
        leaf_key=client_key,
        common_name=args.client_common_name,
        san_dns=[args.client_common_name, client_identity],
        not_before=not_before,
        not_after=not_after,
    )

    write_private_key(out_dir / "ca.key", ca_key)
    write_cert(out_dir / "ca.crt", ca_cert)
    write_private_key(out_dir / "server.key", server_key)
    write_cert(out_dir / "server.crt", server_cert)
    write_private_key(out_dir / "client.key", client_key)
    write_cert(out_dir / "client.crt", client_cert)

    manifest: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "generated_at_utc": iso(now),
        "job_id": job_id,
        "cert_dir": str(out_dir),
        "session_not_before_utc": iso(not_before),
        "session_not_after_utc": iso(not_after),
        "ttl_hours": args.ttl_hours,
        "server": {
            "cert": "server.crt",
            "key": "server.key",
            "common_name": args.server_common_name,
            "job_bound_identity": server_identity,
            "fingerprint_sha256": fingerprint(server_cert),
        },
        "client": {
            "cert": "client.crt",
            "key": "client.key",
            "common_name": args.client_common_name,
            "job_bound_identity": client_identity,
            "fingerprint_sha256": fingerprint(client_cert),
        },
        "ca": {
            "cert": "ca.crt",
            "key": "ca.key",
            "common_name": f"pjc-ca-{job_id}",
            "fingerprint_sha256": fingerprint(ca_cert),
        },
        "reuse_defense": {
            "per_job_ca": True,
            "job_bound_leaf_identity": True,
            "short_lived_certificates": True,
            "wrapper_manifest_required": True,
        },
    }
    (out_dir / "session_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(out_dir / "session_manifest.json", 0o600)

    party_b_dir = out_dir / "party_b_bundle"
    party_b_dir.mkdir(exist_ok=True)
    party_b_dir.chmod(0o700)
    for name_ in ("ca.crt", "client.crt", "client.key", "session_manifest.json"):
        data = (out_dir / name_).read_bytes()
        target = party_b_dir / name_
        target.write_bytes(data)
        target.chmod(0o600 if name_.endswith(".key") or name_.endswith(".json") else 0o644)

    print(json.dumps({
        "status": "ok",
        "job_id": job_id,
        "cert_dir": str(out_dir),
        "party_b_bundle": str(party_b_dir),
        "ca_fingerprint_sha256": manifest["ca"]["fingerprint_sha256"],
        "server_fingerprint_sha256": manifest["server"]["fingerprint_sha256"],
        "client_fingerprint_sha256": manifest["client"]["fingerprint_sha256"],
        "not_after_utc": manifest["session_not_after_utc"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
