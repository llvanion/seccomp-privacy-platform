#!/usr/bin/env python3
"""Issue recovery-service mTLS certificates from Vault PKI or local mock mode."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.vault_http_client import load_client_config, _approle_login, _vault_request  # noqa: E402
from scripts.metadata_db import utc_now  # noqa: E402

REPORT_SCHEMA = "mtls_cert_issue_report/v1"


def resolve_vault_token(config: dict[str, Any]) -> tuple[str, str, str]:
    token_env = str(config.get("token_env") or "").strip()
    if token_env:
        token = os.environ.get(token_env, "")
        if token:
            return token, "token", "env"
    token = str(config.get("token") or "").strip()
    if token:
        return token, "token", "config"
    if config.get("approle_role_id_env") and config.get("approle_secret_id_env"):
        return _approle_login(config), "approle", "login"
    raise ValueError("Vault token auth requires token_env/token or AppRole env config")


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def _private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _cert_name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _mock_issue(*, out_dir: Path, common_name: str, ip_sans: list[str], dns_sans: list[str], ttl_hours: int, issue_client_cert: bool) -> dict[str, str | None]:
    now = datetime.now(timezone.utc)
    ca_key = _private_key()
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(_cert_name("seccomp-local-dev-ca"))
        .issuer_name(_cert_name("seccomp-local-dev-ca"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=max(ttl_hours, 1)))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    server_key = _private_key()
    san_values: list[x509.GeneralName] = [x509.DNSName(item) for item in dns_sans]
    san_values.extend(x509.IPAddress(ipaddress.ip_address(item)) for item in ip_sans)
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(_cert_name(common_name))
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=max(ttl_hours, 1)))
        .add_extension(x509.SubjectAlternativeName(san_values), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    files: dict[str, str | None] = {
        "ca_cert": _write(out_dir / "ca.crt", ca_cert.public_bytes(serialization.Encoding.PEM)),
        "server_cert": _write(out_dir / "server.crt", server_cert.public_bytes(serialization.Encoding.PEM)),
        "server_key": _write(
            out_dir / "server.key",
            server_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ),
        ),
        "client_cert": None,
        "client_key": None,
    }
    if issue_client_cert:
        client_key = _private_key()
        client_cert = (
            x509.CertificateBuilder()
            .subject_name(_cert_name("seccomp-recovery-client"))
            .issuer_name(ca_cert.subject)
            .public_key(client_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=max(ttl_hours, 1)))
            .sign(ca_key, hashes.SHA256())
        )
        files["client_cert"] = _write(out_dir / "client.crt", client_cert.public_bytes(serialization.Encoding.PEM))
        files["client_key"] = _write(
            out_dir / "client.key",
            client_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ),
        )
    return files


def _vault_issue(*, config: dict[str, Any], out_dir: Path, ttl_hours: int) -> dict[str, str | None]:
    client_config = load_client_config(config["vault_client_config"])
    token, _, _ = resolve_vault_token(client_config)
    base_url = str(client_config.get("base_url") or "").strip()
    if not base_url:
        raise ValueError("Vault PKI issue requires vault client base_url")
    mount = str(config.get("pki_mount") or "pki").strip()
    role = str(config.get("role") or "").strip()
    if not role:
        raise ValueError("Vault PKI config requires role")
    body = {
        "common_name": str(config.get("common_name") or "127.0.0.1"),
        "ttl": f"{ttl_hours}h",
        "ip_sans": ",".join(map(str, config.get("ip_sans") or [])),
        "alt_names": ",".join(map(str, config.get("dns_sans") or [])),
    }
    payload = _vault_request(
        "POST",
        f"{base_url.rstrip('/')}/v1/{mount}/issue/{role}",
        token=token,
        body=body,
        timeout=int(client_config.get("timeout_seconds") or 10),
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return {
        "ca_cert": _write(out_dir / "ca.crt", str(data["issuing_ca"]).encode()),
        "server_cert": _write(out_dir / "server.crt", str(data["certificate"]).encode()),
        "server_key": _write(out_dir / "server.key", str(data["private_key"]).encode()),
        "client_cert": None,
        "client_key": None,
    }


def build_report(config: dict[str, Any], *, out_dir: str) -> dict[str, Any]:
    common_name = str(config.get("common_name") or "127.0.0.1")
    ip_sans = [str(item) for item in (config.get("ip_sans") or [])]
    dns_sans = [str(item) for item in (config.get("dns_sans") or [])]
    ttl_hours = int(config.get("ttl_hours") or 720)
    mode = "mock" if bool(config.get("mock_mode", False)) else "vault_pki"
    try:
        if mode == "mock":
            issued = _mock_issue(
                out_dir=Path(out_dir),
                common_name=common_name,
                ip_sans=ip_sans,
                dns_sans=dns_sans,
                ttl_hours=ttl_hours,
                issue_client_cert=bool(config.get("issue_client_cert", False)),
            )
        else:
            issued = _vault_issue(config=config, out_dir=Path(out_dir), ttl_hours=ttl_hours)
        ok = True
        error = None
    except Exception as exc:
        issued = {"ca_cert": "", "server_cert": "", "server_key": "", "client_cert": None, "client_key": None}
        ok = False
        error = str(exc)
    return {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": utc_now(),
        "mode": mode,
        "ok": ok,
        "error": error,
        "vault_base_url": None,
        "vault_pki_mount": str(config.get("pki_mount") or "pki"),
        "vault_pki_role": str(config.get("role") or "") or None,
        "out_dir": str(Path(out_dir).resolve()),
        "common_name": common_name,
        "ip_sans": ip_sans,
        "dns_sans": dns_sans,
        "ttl_hours": ttl_hours,
        "issued_files": issued,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Issue recovery-service mTLS certificates from Vault PKI or mock mode")
    ap.add_argument("--config", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--output", default="")
    ap.add_argument("--assert-ok", action="store_true")
    args = ap.parse_args()
    report = build_report(_load_json(args.config), out_dir=args.out_dir)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 1 if args.assert_ok and not report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
