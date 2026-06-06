# -*- coding:utf-8 _*-
import ipaddress
import os
import urllib.parse
from typing import Any


def production_mode_enabled(*values: Any) -> bool:
    for value in values:
        if isinstance(value, bool):
            if value:
                return True
            continue
        if value is None:
            continue
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on", "production"}:
            return True
    return os.environ.get("RECORD_RECOVERY_PRODUCTION_MODE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "production",
    }


def is_loopback_host(host: str) -> bool:
    lowered = str(host or "").strip().lower()
    if lowered in {"", "localhost"} or lowered.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        return False


def _endpoint_host(endpoint_url: str) -> str:
    if not endpoint_url:
        return ""
    return urllib.parse.urlparse(endpoint_url).hostname or ""


def _tls_requires_client_cert(tls: dict[str, Any]) -> bool:
    return (
        bool(tls.get("enabled"))
        and bool(tls.get("require_client_cert"))
        and bool(str(tls.get("server_cert") or "").strip())
        and bool(str(tls.get("server_key") or "").strip())
        and bool(str(tls.get("ca_cert") or "").strip())
    )


def record_recovery_production_findings(runtime: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if str(runtime.get("transport") or "unix_socket") != "http":
        return findings

    tls = runtime.get("tls") if isinstance(runtime.get("tls"), dict) else {}
    has_mtls = _tls_requires_client_cert(tls)
    has_signed_request_secret = bool(str(runtime.get("auth_token_env") or "").strip())
    has_identity_auth = bool(str(runtime.get("identity_token_config") or "").strip())
    has_request_auth = has_signed_request_secret or has_identity_auth
    has_authz = bool(str(runtime.get("authz_config") or "").strip())
    has_output_roots = bool(runtime.get("allowed_output_roots"))
    has_record_store_roots = bool(runtime.get("allowed_record_store_roots"))
    has_row_cap = int(runtime.get("max_rows_per_request") or 0) > 0

    bind_host = str(runtime.get("bind_host") or "").strip()
    endpoint_host = _endpoint_host(str(runtime.get("endpoint_url") or ""))
    effective_host = bind_host or endpoint_host
    public_bind = not is_loopback_host(effective_host)

    if not has_request_auth:
        findings.append({
            "kind": "missing_request_auth",
            "message": "production HTTP record recovery requires auth_token_env or identity_token_config",
            "expected": "request authentication configured",
            "actual": {
                "auth_token_env": runtime.get("auth_token_env") or None,
                "identity_token_config": runtime.get("identity_token_config") or None,
            },
        })
    if has_identity_auth and not str(runtime.get("metadata_db_path") or "").strip():
        findings.append({
            "kind": "missing_identity_metadata_db",
            "message": "identity_token_config requires metadata_db_path in production",
            "expected": "metadata_db_path",
            "actual": None,
        })
    if not has_authz:
        findings.append({
            "kind": "missing_authz_policy",
            "message": "production HTTP record recovery requires authz_config",
            "expected": "authz_config",
            "actual": None,
        })
    if not has_output_roots:
        findings.append({
            "kind": "missing_output_root_restrictions",
            "message": "production HTTP record recovery requires allowed_output_roots",
            "expected": "at least one allowed output root",
            "actual": runtime.get("allowed_output_roots") or [],
        })
    if not has_record_store_roots:
        findings.append({
            "kind": "missing_record_store_root_restrictions",
            "message": "production HTTP record recovery requires allowed_record_store_roots",
            "expected": "at least one allowed record-store root",
            "actual": runtime.get("allowed_record_store_roots") or [],
        })
    if not has_row_cap:
        findings.append({
            "kind": "missing_max_rows_per_request",
            "message": "production HTTP record recovery requires max_rows_per_request > 0",
            "expected": "> 0",
            "actual": runtime.get("max_rows_per_request"),
        })
    if not (has_signed_request_secret or has_mtls):
        findings.append({
            "kind": "missing_signed_request_or_mtls",
            "message": "production HTTP record recovery requires signed requests or mTLS client certificates",
            "expected": "auth_token_env or tls.require_client_cert with CA",
            "actual": {
                "auth_token_env": runtime.get("auth_token_env") or None,
                "tls": tls or None,
            },
        })
    if public_bind and not has_mtls:
        findings.append({
            "kind": "public_http_requires_mtls",
            "message": "production HTTP record recovery on a non-loopback listener requires mTLS client certificates",
            "expected": "tls.enabled=true, tls.require_client_cert=true, ca_cert/server_cert/server_key set",
            "actual": {"bind_host": effective_host, "tls": tls or None},
        })
    return findings


def enforce_record_recovery_production_gate(runtime: dict[str, Any]) -> None:
    findings = record_recovery_production_findings(runtime)
    if not findings:
        return
    kinds = ", ".join(str(item["kind"]) for item in findings)
    raise SystemExit(f"[ERROR] record recovery production gate failed: {kinds}")
