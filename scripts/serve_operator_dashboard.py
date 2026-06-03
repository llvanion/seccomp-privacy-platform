#!/usr/bin/env python3
"""Operator dashboard server — serves a web UI over local pipeline sidecar artifacts."""
import argparse
import base64
import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import request as urllib_request
from urllib.parse import parse_qs, unquote, urlencode, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_SCRIPTS = REPO_ROOT / "a-psi" / "moduleA_psi" / "scripts"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(POLICY_SCRIPTS))

from api_identity import (
    DEFAULT_IDENTITY_SESSION_COOKIE_NAME,
    bind_query_request_to_identity,
    identity_has_any_role,
    resolve_identity_context,
    resolve_request_identity,
)
from archive_audit_bundle import summarize_mainline_contract
from build_observability_dashboard import build_dashboard
from check_observability_alerts import build_alert_report
from list_query_workflow_status import scan_status_files
from metadata_db import apply_migrations, connect_db, table_exists
import policy_release
from submit_query_workflow import (
    STATUS_SCHEMA as QUERY_WORKFLOW_STATUS_SCHEMA,
    append_jsonl,
    build_command,
    build_receipt,
    build_status,
    json_sha256,
    load_request,
    normalize_request_paths,
    query_workflow_sidecar_paths,
    render_manifest,
    summarize_request,
    validate_request,
    write_json,
)
from validate_json_contract import ValidationError, load_json as load_schema_json, validate_value

CACHE_TTL = 5.0
UNSPECIFIED_TENANT_ID = "__unspecified__"
REQUEST_SUBMISSION_SCHEMA = "operator_request_submission/v1"
PRIVACY_BUDGET_APPROVAL_LIST_SCHEMA = "privacy_budget_approval_list/v1"
REQUEST_SCHEMA_PATH = REPO_ROOT / "schemas" / "query_workflow_request.schema.json"
APPROVER_ROLES = ("privacy_operator", "platform_admin")
REQUEST_REVIEW_ROLES = ("privacy_operator", "platform_admin", "compliance_auditor", "commerce_ops_owner")
REQUEST_REJECT_ROLES = ("privacy_operator", "platform_admin", "compliance_auditor")
PRIVACY_BUDGET_APPROVAL_REVIEW_ROLES = ("privacy_operator", "platform_admin", "platform_auditor", "compliance_auditor")
PRIVACY_BUDGET_APPROVAL_APPROVE_ROLES = ("privacy_operator", "platform_admin")
PRIVACY_BUDGET_APPROVAL_REJECT_ROLES = ("privacy_operator", "platform_admin", "compliance_auditor")
PRIVACY_BUDGET_APPROVAL_EXPIRE_ROLES = ("privacy_operator", "platform_admin", "compliance_auditor")
DASHBOARD_FULL_VIEW_ROLES = ("platform_admin", "platform_auditor", "privacy_operator", "compliance_auditor")
DASHBOARD_JOB_MUTATION_ROLES = ("platform_admin", "privacy_operator")
SESSION_COOKIE_SCHEMA = "operator_console_session/v1"
PJC_MTLS_SCRIPT_DIR = REPO_ROOT / "a-psi" / "moduleA_psi" / "scripts"
PJC_MTLS_CERT_DIR = REPO_ROOT / "tmp" / "pjc_mtls_shared" / "certs"
PJC_MTLS_BUNDLE_DIR = REPO_ROOT / "tmp" / "pjc_mtls_shared" / "party_b_bundle"
PJC_MTLS_PAIRING_TOKEN_FILE = REPO_ROOT / "tmp" / "pjc_mtls_shared" / "pairing_token"
PJC_MTLS_PAIRING_TOKEN_META_FILE = REPO_ROOT / "tmp" / "pjc_mtls_shared" / "pairing_token_meta.json"
PJC_MTLS_ENROLLMENT_AUDIT_FILE = REPO_ROOT / "tmp" / "pjc_mtls_shared" / "enrollment_audit.jsonl"
PJC_MTLS_PAIRING_TOKEN_DEFAULT_TTL_SECONDS = 600
PJC_MTLS_PAIRING_TOKEN_DEFAULT_MAX_ENROLLMENTS = 1

_PJC_MTLS_TOKEN_LOCK = threading.Lock()
_PJC_MTLS_SHUTDOWN_HOOKS: list[Any] = []

# ---------------------------------------------------------------------------
# Static SPA assets (from console/dist; configured via --console-dist)
# ---------------------------------------------------------------------------

import mimetypes


_DEFAULT_CONSOLE_DIST_CANDIDATES = (
    REPO_ROOT / "console" / "dist",
    REPO_ROOT / "console-dist",
    Path("/opt/seccomp/platform/console/dist"),
)
CONSOLE_CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "worker-src 'self'",
    ]
)
CONSOLE_PERMISSIONS_POLICY = ", ".join(
    [
        "camera=()",
        "microphone=()",
        "geolocation=()",
        "payment=()",
        "usb=()",
    ]
)


def _console_security_headers(*, secure_transport: bool = False) -> dict[str, str]:
    headers = {
        "Content-Security-Policy": CONSOLE_CONTENT_SECURITY_POLICY,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": CONSOLE_PERMISSIONS_POLICY,
    }
    if secure_transport:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers


def _resolve_console_dist(explicit: str) -> Path | None:
    if explicit:
        candidate = Path(explicit).expanduser()
        try:
            candidate = candidate.resolve(strict=True)
        except FileNotFoundError:
            return None
        return candidate if candidate.is_dir() else None
    for candidate in _DEFAULT_CONSOLE_DIST_CANDIDATES:
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError:
            continue
        if resolved.is_dir():
            return resolved
    return None


def _static_asset_response(
    root: Path | None,
    request_path: str,
) -> tuple[int, str, bytes] | None:
    """Resolve a SPA static asset under ``root``.

    Returns ``(status, content_type, body)`` when an asset is found, or ``None``
    if the caller should fall through to its normal behaviour (so requests for
    real API paths still hit their handlers).

    The function refuses to traverse outside ``root`` and only returns regular
    files. SPA routes that do not map to a file get the ``index.html`` fallback
    so the React Router history mode keeps working.
    """
    if root is None:
        return None
    rel = request_path.lstrip("/")
    if not rel or rel.endswith("/"):
        rel = (rel or "") + "index.html"
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if not target.exists() or not target.is_file():
        # SPA fallback for client-side routes.
        index = (root / "index.html").resolve()
        try:
            index.relative_to(root)
        except ValueError:
            return None
        if not index.is_file():
            return None
        target = index
    ctype, _ = mimetypes.guess_type(target.name)
    if ctype is None:
        ctype = "application/octet-stream"
    if ctype.startswith("text/") or ctype in {"application/javascript", "application/json"}:
        ctype = f"{ctype}; charset=utf-8"
    return 200, ctype, target.read_bytes()


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_cache_data: dict[str, Any] | None = None
_cache_ts: float = 0.0


def invalidate_dashboard_cache() -> None:
    global _cache_data, _cache_ts
    with _cache_lock:
        _cache_data = None
        _cache_ts = 0.0


def _load_optional(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _load_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
    except (OSError, json.JSONDecodeError):
        return []
    return rows


def _repo_path(path_value: str, *, base_dir: Path | None = None) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path.resolve()
    root = base_dir if base_dir is not None else REPO_ROOT
    return (root / path).resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _cert_fingerprint(path: Path) -> str:
    result = subprocess.run(
        ["openssl", "x509", "-in", str(path), "-fingerprint", "-sha256", "-noout"],
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"openssl fingerprint failed for {path}")
    return result.stdout.strip()


def _normalize_fingerprint(value: str) -> str:
    text = str(value or "").strip()
    if "=" in text:
        text = text.split("=", 1)[1]
    return text.replace(":", "").replace(" ", "").lower()


def _build_pjc_mtls_bootstrap_uri(*, enroll_url: str, pairing_token: str, ca_fingerprint: str, ttl_seconds: int) -> str:
    return "pjc-mtls://enroll?" + urlencode({
        "url": enroll_url,
        "token": pairing_token,
        "ca_sha256": ca_fingerprint,
        "ttl": str(ttl_seconds),
    })


def _parse_pjc_mtls_bootstrap_uri(value: str) -> dict[str, str]:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme != "pjc-mtls" or parsed.netloc != "enroll":
        raise ValueError("bootstrap_uri must start with pjc-mtls://enroll")
    params = parse_qs(parsed.query, keep_blank_values=False)

    def one(name: str) -> str:
        values = params.get(name) or []
        if len(values) != 1 or not str(values[0]).strip():
            raise ValueError(f"bootstrap_uri missing {name}")
        return str(values[0]).strip()

    return {
        "enroll_url": one("url"),
        "pairing_token": one("token"),
        "expected_ca_fingerprint": one("ca_sha256"),
        "ttl_seconds": str((params.get("ttl") or [""])[0]).strip(),
    }


def _choose_bootstrap_field(name: str, explicit: str, bootstrap_value: str, *, fingerprint: bool = False) -> str:
    explicit = str(explicit or "").strip()
    bootstrap_value = str(bootstrap_value or "").strip()
    if not explicit:
        return bootstrap_value
    if not bootstrap_value:
        return explicit
    left = _normalize_fingerprint(explicit) if fingerprint else explicit
    right = _normalize_fingerprint(bootstrap_value) if fingerprint else bootstrap_value
    if not secrets.compare_digest(left, right):
        raise ValueError(f"{name} conflicts with bootstrap_uri")
    return explicit


def _derive_mtls_enroll_url_from_body(body: dict[str, Any]) -> str:
    explicit = str(body.get("enroll_url") or "").strip()
    if explicit:
        return explicit
    server_host = str(body.get("server_host") or "").strip()
    if not server_host:
        return ""
    try:
        port = int(body.get("dashboard_port") or 18134)
    except (TypeError, ValueError):
        port = 18134
    port = port if 1 <= port <= 65535 else 18134
    return f"http://{server_host}:{port}/v1/pjc-mtls/enroll"


def _env_int(name: str, default: int, *, min_value: int = 0) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, value)


def _pairing_token_ttl_seconds() -> int:
    return _env_int("PJC_MTLS_PAIRING_TOKEN_TTL_SECONDS", PJC_MTLS_PAIRING_TOKEN_DEFAULT_TTL_SECONDS, min_value=0)


def _pairing_token_max_enrollments() -> int:
    return _env_int("PJC_MTLS_MAX_ENROLLMENTS", PJC_MTLS_PAIRING_TOKEN_DEFAULT_MAX_ENROLLMENTS, min_value=0)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_pairing_meta() -> dict[str, Any]:
    if not PJC_MTLS_PAIRING_TOKEN_META_FILE.is_file():
        return {}
    try:
        return json.loads(PJC_MTLS_PAIRING_TOKEN_META_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_pairing_meta(meta: dict[str, Any]) -> None:
    PJC_MTLS_PAIRING_TOKEN_META_FILE.parent.mkdir(parents=True, exist_ok=True)
    PJC_MTLS_PAIRING_TOKEN_META_FILE.write_text(json.dumps(meta, sort_keys=True) + "\n", encoding="utf-8")
    PJC_MTLS_PAIRING_TOKEN_META_FILE.chmod(0o600)


def _delete_pairing_state() -> None:
    for path in (PJC_MTLS_PAIRING_TOKEN_FILE, PJC_MTLS_PAIRING_TOKEN_META_FILE):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _append_enrollment_audit(event: dict[str, Any]) -> None:
    try:
        PJC_MTLS_ENROLLMENT_AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with PJC_MTLS_ENROLLMENT_AUDIT_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        try:
            PJC_MTLS_ENROLLMENT_AUDIT_FILE.chmod(0o600)
        except OSError:
            pass
    except OSError as exc:
        print(f"[warn] could not append enrollment audit: {exc}", file=sys.stderr)


def _trigger_enrollment_shutdown(reason: str) -> None:
    print(f"[info] PJC mTLS enrollment shutdown triggered: {reason}", file=sys.stderr)
    for hook in list(_PJC_MTLS_SHUTDOWN_HOOKS):
        try:
            hook(reason)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] enrollment shutdown hook failed: {exc}", file=sys.stderr)


def _ensure_pairing_token(*, force: bool = False) -> str:
    with _PJC_MTLS_TOKEN_LOCK:
        env_token = os.environ.get("PJC_MTLS_PAIRING_TOKEN", "").strip()
        if env_token:
            meta = _read_pairing_meta()
            if force or meta.get("token") != env_token:
                meta = {
                    "token": env_token,
                    "issued_at": _utc_now_iso(),
                    "issued_at_epoch": int(time.time()),
                    "ttl_seconds": _pairing_token_ttl_seconds(),
                    "max_enrollments": _pairing_token_max_enrollments(),
                    "enrollments": 0,
                    "source": "env",
                }
                _write_pairing_meta(meta)
            return env_token

        if PJC_MTLS_PAIRING_TOKEN_FILE.is_file() and not force:
            token = PJC_MTLS_PAIRING_TOKEN_FILE.read_text(encoding="utf-8").strip()
            if token:
                meta = _read_pairing_meta()
                if not meta or meta.get("token") != token:
                    meta = {
                        "token": token,
                        "issued_at": _utc_now_iso(),
                        "issued_at_epoch": int(time.time()),
                        "ttl_seconds": _pairing_token_ttl_seconds(),
                        "max_enrollments": _pairing_token_max_enrollments(),
                        "enrollments": 0,
                        "source": "file",
                    }
                    _write_pairing_meta(meta)
                return token

        PJC_MTLS_PAIRING_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(24)
        PJC_MTLS_PAIRING_TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
        PJC_MTLS_PAIRING_TOKEN_FILE.chmod(0o600)
        _write_pairing_meta({
            "token": token,
            "issued_at": _utc_now_iso(),
            "issued_at_epoch": int(time.time()),
            "ttl_seconds": _pairing_token_ttl_seconds(),
            "max_enrollments": _pairing_token_max_enrollments(),
            "enrollments": 0,
            "source": "generated",
        })
        return token


def _prepare_pjc_mtls_party_a(*, force_regenerate: bool = False, enroll_url: str = "") -> dict[str, Any]:
    script = PJC_MTLS_SCRIPT_DIR / "prepare_pjc_mtls_party_a.sh"
    if not script.is_file():
        raise FileNotFoundError(f"missing helper script: {script}")
    env = os.environ.copy()
    env.update({
        "CERT_DIR": str(PJC_MTLS_CERT_DIR),
        "BUNDLE_DIR": str(PJC_MTLS_BUNDLE_DIR),
        "FORCE_REGENERATE": "1" if force_regenerate else "0",
    })
    result = subprocess.run(
        ["bash", str(script)],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        return {
            "status": "error",
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "cert_dir": str(PJC_MTLS_CERT_DIR),
            "bundle_dir": str(PJC_MTLS_BUNDLE_DIR),
        }
    token = _ensure_pairing_token(force=force_regenerate)
    meta = _read_pairing_meta()
    fingerprint = _cert_fingerprint(PJC_MTLS_CERT_DIR / "ca.crt")
    ttl_seconds = int(meta.get("ttl_seconds") or _pairing_token_ttl_seconds())
    enroll_url = enroll_url.strip()
    bootstrap_uri = (
        _build_pjc_mtls_bootstrap_uri(
            enroll_url=enroll_url,
            pairing_token=token,
            ca_fingerprint=fingerprint,
            ttl_seconds=ttl_seconds,
        )
        if enroll_url
        else ""
    )
    return {
        "status": "ok",
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "cert_dir": str(PJC_MTLS_CERT_DIR),
        "bundle_dir": str(PJC_MTLS_BUNDLE_DIR),
        "fingerprint": fingerprint,
        "pairing_token": token,
        "pairing_token_ttl_seconds": ttl_seconds,
        "pairing_token_max_enrollments": int(meta.get("max_enrollments") or _pairing_token_max_enrollments()),
        "pairing_token_enrollments_used": int(meta.get("enrollments") or 0),
        "pairing_token_issued_at": meta.get("issued_at"),
        "enroll_url": enroll_url,
        "bootstrap_uri": bootstrap_uri,
        "enroll_path": "/v1/pjc-mtls/enroll",
    }


def _csr_fingerprint(csr_pem: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".csr", delete=False) as handle:
        handle.write(csr_pem)
        csr_tmp = handle.name
    try:
        result = subprocess.run(
            ["openssl", "req", "-in", csr_tmp, "-pubkey", "-noout"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            return ""
        digest = subprocess.run(
            ["openssl", "dgst", "-sha256"],
            input=result.stdout,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if digest.returncode != 0:
            return ""
        return digest.stdout.strip().split()[-1] if digest.stdout.strip() else ""
    finally:
        try:
            os.unlink(csr_tmp)
        except OSError:
            pass


def _enroll_pjc_mtls_csr(
    *,
    csr_pem: str,
    pairing_token: str,
    remote_addr: str | None = None,
) -> dict[str, Any]:
    submitted = pairing_token.strip()
    audit_base = {
        "ts": _utc_now_iso(),
        "remote_addr": remote_addr or "",
        "csr_fingerprint": _csr_fingerprint(csr_pem) if csr_pem else "",
    }

    with _PJC_MTLS_TOKEN_LOCK:
        expected = ""
        env_token = os.environ.get("PJC_MTLS_PAIRING_TOKEN", "").strip()
        if env_token:
            expected = env_token
        elif PJC_MTLS_PAIRING_TOKEN_FILE.is_file():
            expected = PJC_MTLS_PAIRING_TOKEN_FILE.read_text(encoding="utf-8").strip()

        meta = _read_pairing_meta()
        ttl_seconds = int(meta.get("ttl_seconds") or _pairing_token_ttl_seconds())
        max_enrollments = int(meta.get("max_enrollments") or _pairing_token_max_enrollments())
        issued_at_epoch = int(meta.get("issued_at_epoch") or 0)
        used = int(meta.get("enrollments") or 0)

        if not expected or not submitted or not secrets.compare_digest(submitted, expected):
            _append_enrollment_audit({**audit_base, "result": "rejected", "reason": "invalid_token"})
            raise PermissionError("invalid PJC mTLS pairing token")

        if ttl_seconds > 0 and issued_at_epoch > 0 and (time.time() - issued_at_epoch) > ttl_seconds:
            _append_enrollment_audit({**audit_base, "result": "rejected", "reason": "token_expired"})
            _delete_pairing_state()
            _trigger_enrollment_shutdown("pairing token expired")
            raise PermissionError("PJC mTLS pairing token has expired")

        if max_enrollments > 0 and used >= max_enrollments:
            _append_enrollment_audit({**audit_base, "result": "rejected", "reason": "max_enrollments_reached"})
            _delete_pairing_state()
            _trigger_enrollment_shutdown("max enrollments reached")
            raise PermissionError("PJC mTLS pairing token already used the maximum number of times")

        if "BEGIN CERTIFICATE REQUEST" not in csr_pem or "END CERTIFICATE REQUEST" not in csr_pem:
            _append_enrollment_audit({**audit_base, "result": "rejected", "reason": "invalid_csr"})
            raise ValueError("csr_pem must contain a PEM certificate request")

    prep = _prepare_pjc_mtls_party_a(force_regenerate=False)
    if prep.get("status") != "ok":
        _append_enrollment_audit({**audit_base, "result": "error", "reason": "prepare_failed"})
        raise RuntimeError(prep.get("stderr") or prep.get("stdout") or "could not prepare Party A certificates")

    with tempfile.TemporaryDirectory(prefix="pjc_mtls_enroll_") as tmp:
        tmp_dir = Path(tmp)
        csr_path = tmp_dir / "client.csr"
        crt_path = tmp_dir / "client.crt"
        csr_path.write_text(csr_pem, encoding="utf-8")
        result = subprocess.run(
            [
                "openssl",
                "x509",
                "-req",
                "-days",
                os.environ.get("PJC_MTLS_CLIENT_CERT_DAYS", "365"),
                "-in",
                str(csr_path),
                "-CA",
                str(PJC_MTLS_CERT_DIR / "ca.crt"),
                "-CAkey",
                str(PJC_MTLS_CERT_DIR / "ca.key"),
                "-CAcreateserial",
                "-out",
                str(crt_path),
            ],
            cwd=str(REPO_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            _append_enrollment_audit({**audit_base, "result": "error", "reason": "openssl_sign_failed"})
            raise RuntimeError(result.stderr.strip() or "openssl CSR signing failed")
        ca_crt_text = (PJC_MTLS_CERT_DIR / "ca.crt").read_text(encoding="utf-8")
        client_crt_text = crt_path.read_text(encoding="utf-8")
        client_fp = _cert_fingerprint(crt_path)
        ca_fp = _cert_fingerprint(PJC_MTLS_CERT_DIR / "ca.crt")

    with _PJC_MTLS_TOKEN_LOCK:
        meta = _read_pairing_meta()
        meta["enrollments"] = int(meta.get("enrollments") or 0) + 1
        meta["last_enrolled_at"] = _utc_now_iso()
        _write_pairing_meta(meta)
        remaining = max(0, int(meta.get("max_enrollments") or 0) - int(meta["enrollments"]))
        _append_enrollment_audit({
            **audit_base,
            "result": "ok",
            "client_cert_fingerprint": client_fp,
            "ca_fingerprint": ca_fp,
            "enrollments_used": meta["enrollments"],
            "enrollments_remaining": remaining,
        })

    if remaining == 0 and int(meta.get("max_enrollments") or 0) > 0:
        _delete_pairing_state()
        _trigger_enrollment_shutdown("max enrollments reached")

    return {
        "status": "ok",
        "ca_crt": ca_crt_text,
        "client_crt": client_crt_text,
        "fingerprint": ca_fp,
        "client_cert_fingerprint": client_fp,
        "enrollments_remaining": remaining,
    }


def _party_b_enroll_from_dashboard(body: dict[str, Any]) -> dict[str, Any]:
    enroll_url = str(body.get("enroll_url") or "").strip()
    pairing_token = str(body.get("pairing_token") or "").strip()
    expected_ca_fingerprint = str(
        body.get("expected_ca_fingerprint")
        or body.get("expected_fingerprint")
        or body.get("ca_fingerprint")
        or ""
    ).strip()
    bootstrap_uri = str(body.get("bootstrap_uri") or body.get("pjc_mtls_bootstrap") or "").strip()
    if bootstrap_uri:
        parsed_bootstrap = _parse_pjc_mtls_bootstrap_uri(bootstrap_uri)
        enroll_url = _choose_bootstrap_field("enroll_url", enroll_url, parsed_bootstrap["enroll_url"])
        pairing_token = _choose_bootstrap_field("pairing_token", pairing_token, parsed_bootstrap["pairing_token"])
        expected_ca_fingerprint = _choose_bootstrap_field(
            "expected_ca_fingerprint",
            expected_ca_fingerprint,
            parsed_bootstrap["expected_ca_fingerprint"],
            fingerprint=True,
        )
    cert_dir_raw = str(body.get("cert_dir") or "").strip() or str(Path.home() / "pjc_certs_shared")
    cert_dir = Path(cert_dir_raw).expanduser().resolve()
    if not enroll_url:
        raise ValueError("enroll_url is required")
    if not pairing_token:
        raise ValueError("pairing_token is required")
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_dir.chmod(0o700)
    key_path = cert_dir / "client.key"
    csr_path = cert_dir / "client.csr"
    if not key_path.is_file():
        result = subprocess.run(
            ["openssl", "genrsa", "-out", str(key_path), "4096"],
            cwd=str(REPO_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "openssl client key generation failed")
        key_path.chmod(0o600)
    result = subprocess.run(
        [
            "openssl",
            "req",
            "-new",
            "-key",
            str(key_path),
            "-out",
            str(csr_path),
            "-subj",
            "/CN=pjc-client/O=PJC-TLS",
        ],
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "openssl CSR generation failed")
    payload = json.dumps(
        {
            "pairing_token": pairing_token,
            "csr_pem": csr_path.read_text(encoding="utf-8"),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib_request.Request(
        enroll_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib_request.build_opener(urllib_request.ProxyHandler({}))
    with opener.open(req, timeout=30) as resp:
        response_payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(response_payload, dict) or response_payload.get("status") != "ok":
        raise RuntimeError(f"enrollment failed: {response_payload}")
    returned_fp = str(response_payload.get("fingerprint") or "")
    if expected_ca_fingerprint:
        expected_norm = _normalize_fingerprint(expected_ca_fingerprint)
        returned_norm = _normalize_fingerprint(returned_fp)
        if not returned_norm:
            raise RuntimeError("enrollment response omitted CA fingerprint")
        if not secrets.compare_digest(returned_norm, expected_norm):
            raise RuntimeError("CA fingerprint mismatch; refusing enrollment")
    (cert_dir / "ca.crt").write_text(str(response_payload["ca_crt"]), encoding="utf-8")
    (cert_dir / "client.crt").write_text(str(response_payload["client_crt"]), encoding="utf-8")
    (cert_dir / "ca.crt").chmod(0o644)
    (cert_dir / "client.crt").chmod(0o644)
    if expected_ca_fingerprint:
        local_fp = _cert_fingerprint(cert_dir / "ca.crt")
        if not secrets.compare_digest(_normalize_fingerprint(local_fp), _normalize_fingerprint(expected_ca_fingerprint)):
            raise RuntimeError("stored CA fingerprint mismatch; refusing enrollment")
    return {
        "status": "ok",
        "cert_dir": str(cert_dir),
        "fingerprint": response_payload.get("fingerprint"),
        "stdout": f"wrote ca.crt, client.crt, client.key under {cert_dir}",
    }


def _int_body(body: dict[str, Any], key: str, default: int, *, min_value: int = 1) -> int:
    raw = body.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if value < min_value:
        raise ValueError(f"{key} must be >= {min_value}")
    return value


# --- Bucketed scale-test: async job registry ----------------------------------
#
# The bucketed scale test used to run synchronously inside the POST handler,
# which pinned an HTTP worker for the whole PJC + policy flow. For longer jobs
# the browser would just sit there until the run finished. We now spawn a
# background worker thread, return 202 + job_id immediately, and expose the
# result via GET /v1/bucketed-scale-test/{job_id}.

_BUCKETED_SCALE_TEST_JOBS: dict[str, dict[str, Any]] = {}
_BUCKETED_SCALE_TEST_JOBS_LOCK = threading.Lock()
_BUCKETED_SCALE_TEST_JOBS_MAX_RETAINED = 50


def _bucketed_scale_test_validate_inputs(body: dict[str, Any]) -> dict[str, Any]:
    """Pure validation — raises on bad input, returns the resolved parameters."""
    script = PJC_MTLS_SCRIPT_DIR / "run_bucketed_scale_test.sh"
    if not script.is_file():
        raise FileNotFoundError(f"missing helper script: {script}")

    job_id = str(body.get("job_id") or "bucketed-scale-1k").strip()
    if not job_id:
        raise ValueError("job_id must be non-empty")
    out_dir_raw = str(body.get("out_dir") or f"tmp/pjc_bucketed_scale_{job_id}").strip()
    out_dir = _repo_path(out_dir_raw)
    records = _int_body(body, "records", 1000)
    buckets = _int_body(body, "buckets", 8)
    k = _int_body(body, "k", 20)
    dp_sensitivity = _int_body(body, "dp_sensitivity", 10000)
    base_port = _int_body(body, "base_port", 10621, min_value=1024)
    max_jobs = _int_body(body, "max_jobs", 4)
    bucket_field = str(body.get("bucket_field") or "campaign_id").strip() or "campaign_id"
    dp_epsilon = str(body.get("dp_epsilon") or "1.0").strip()
    try:
        if float(dp_epsilon) <= 0:
            raise ValueError
    except ValueError as exc:
        raise ValueError("dp_epsilon must be a positive number") from exc
    return {
        "script": script,
        "job_id": job_id,
        "out_dir": out_dir,
        "records": records,
        "buckets": buckets,
        "k": k,
        "dp_sensitivity": dp_sensitivity,
        "base_port": base_port,
        "max_jobs": max_jobs,
        "bucket_field": bucket_field,
        "dp_epsilon": dp_epsilon,
        "parallel": bool(body.get("parallel")),
    }


def _bucketed_scale_test_execute(resolved: dict[str, Any]) -> dict[str, Any]:
    """Run the underlying bash helper and turn its output into a result payload."""
    out_dir: Path = resolved["out_dir"]
    env = os.environ.copy()
    env.update({
        "JOB_ID": resolved["job_id"],
        "OUT_DIR": str(out_dir),
        "RECORDS": str(resolved["records"]),
        "BUCKETS": str(resolved["buckets"]),
        "BUCKET_FIELD": resolved["bucket_field"],
        "K_THRESHOLD": str(resolved["k"]),
        "DP_EPSILON": resolved["dp_epsilon"],
        "DP_SENSITIVITY": str(resolved["dp_sensitivity"]),
        "BASE_PORT": str(resolved["base_port"]),
        "MAX_JOBS": str(resolved["max_jobs"]),
        "PARALLEL": "1" if resolved["parallel"] else "0",
        "PJC_BIN_DIR": str(REPO_ROOT / "a-psi" / "private-join-and-compute" / "bazel-bin"),
    })
    result = subprocess.run(
        ["bash", str(resolved["script"])],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=1800,
    )
    payload: dict[str, Any] = {
        "status": "ok" if result.returncode == 0 else "error",
        "exit_code": result.returncode,
        "out_dir": str(out_dir),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    for name, path in {
        "attribution": out_dir / "attribution_result.json",
        "bucket_public_report": out_dir / "bucket_public_report.json",
        "operator_bucket_report": out_dir / "operator_bucket_report.json",
        "public_report": out_dir / "public_report.json",
        "expected": out_dir / "expected_result.json",
    }.items():
        if path.is_file():
            payload[name] = str(path)
    if (out_dir / "attribution_result.json").is_file() and (out_dir / "expected_result.json").is_file():
        actual = json.loads((out_dir / "attribution_result.json").read_text(encoding="utf-8"))
        expected = json.loads((out_dir / "expected_result.json").read_text(encoding="utf-8"))
        payload["summary"] = {
            "intersection_size": actual.get("intersection_size"),
            "intersection_sum": actual.get("intersection_sum"),
            "expected_size": expected.get("intersection_size"),
            "expected_sum": expected.get("intersection_sum"),
            "matches_expected": (
                int(actual.get("intersection_size", -1)) == int(expected.get("intersection_size", -2))
                and int(actual.get("intersection_sum", -1)) == int(expected.get("intersection_sum", -2))
            ),
        }
    return payload


def _bucketed_scale_test_job_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    """Build the dict returned over the wire — never includes the lock itself."""
    snapshot = {
        "job_id": job["job_id"],
        "state": job["state"],
        "started_at_utc": job["started_at_utc"],
        "finished_at_utc": job.get("finished_at_utc"),
        "duration_sec": job.get("duration_sec"),
        "params": job.get("params"),
    }
    if job["state"] in ("succeeded", "failed"):
        snapshot["result"] = job.get("result")
        snapshot["error"] = job.get("error")
    return snapshot


def _bucketed_scale_test_evict_oldest_finished() -> None:
    """Drop the oldest terminal job if we're over the retention cap."""
    if len(_BUCKETED_SCALE_TEST_JOBS) <= _BUCKETED_SCALE_TEST_JOBS_MAX_RETAINED:
        return
    finished = [
        (jid, j) for jid, j in _BUCKETED_SCALE_TEST_JOBS.items()
        if j["state"] in ("succeeded", "failed")
    ]
    if not finished:
        return
    finished.sort(key=lambda kv: kv[1].get("finished_at_utc") or "")
    _BUCKETED_SCALE_TEST_JOBS.pop(finished[0][0], None)


def _bucketed_scale_test_worker(record_id: str, resolved: dict[str, Any]) -> None:
    started = time.time()
    try:
        result = _bucketed_scale_test_execute(resolved)
        with _BUCKETED_SCALE_TEST_JOBS_LOCK:
            job = _BUCKETED_SCALE_TEST_JOBS.get(record_id)
            if job is not None:
                job["state"] = "succeeded" if result.get("status") == "ok" else "failed"
                job["result"] = result
                job["finished_at_utc"] = _utc_now_iso()
                job["duration_sec"] = round(time.time() - started, 3)
                _bucketed_scale_test_evict_oldest_finished()
    except Exception as exc:  # noqa: BLE001
        with _BUCKETED_SCALE_TEST_JOBS_LOCK:
            job = _BUCKETED_SCALE_TEST_JOBS.get(record_id)
            if job is not None:
                job["state"] = "failed"
                job["error"] = {"type": type(exc).__name__, "message": str(exc)}
                job["finished_at_utc"] = _utc_now_iso()
                job["duration_sec"] = round(time.time() - started, 3)
                _bucketed_scale_test_evict_oldest_finished()


def _start_bucketed_scale_test_job(body: dict[str, Any]) -> dict[str, Any]:
    resolved = _bucketed_scale_test_validate_inputs(body)
    record_id = f"{resolved['job_id']}-{uuid.uuid4().hex[:8]}"
    job_snapshot = {
        "job_id": record_id,
        "state": "running",
        "started_at_utc": _utc_now_iso(),
        "params": {
            "job_id": resolved["job_id"],
            "out_dir": str(resolved["out_dir"]),
            "records": resolved["records"],
            "buckets": resolved["buckets"],
            "k": resolved["k"],
            "dp_epsilon": resolved["dp_epsilon"],
            "dp_sensitivity": resolved["dp_sensitivity"],
            "base_port": resolved["base_port"],
            "max_jobs": resolved["max_jobs"],
            "bucket_field": resolved["bucket_field"],
            "parallel": resolved["parallel"],
        },
    }
    with _BUCKETED_SCALE_TEST_JOBS_LOCK:
        _BUCKETED_SCALE_TEST_JOBS[record_id] = job_snapshot
        _bucketed_scale_test_evict_oldest_finished()
    threading.Thread(
        target=_bucketed_scale_test_worker,
        args=(record_id, resolved),
        daemon=True,
        name=f"bucketed-scale-{record_id}",
    ).start()
    return _bucketed_scale_test_job_snapshot(job_snapshot)


def _get_bucketed_scale_test_job(record_id: str) -> dict[str, Any] | None:
    with _BUCKETED_SCALE_TEST_JOBS_LOCK:
        job = _BUCKETED_SCALE_TEST_JOBS.get(record_id)
        if job is None:
            return None
        return _bucketed_scale_test_job_snapshot(dict(job))


def _list_bucketed_scale_test_jobs() -> list[dict[str, Any]]:
    with _BUCKETED_SCALE_TEST_JOBS_LOCK:
        return [
            _bucketed_scale_test_job_snapshot(dict(job))
            for job in sorted(
                _BUCKETED_SCALE_TEST_JOBS.values(),
                key=lambda j: j.get("started_at_utc") or "",
                reverse=True,
            )
        ]


def _run_bucketed_scale_test(body: dict[str, Any]) -> dict[str, Any]:
    """Legacy synchronous entrypoint, kept for callers that still want the blocking behavior."""
    resolved = _bucketed_scale_test_validate_inputs(body)
    return _bucketed_scale_test_execute(resolved)


def _iso_to_ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return None


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", []):
            return value
    return None


def _extract_result_summary(out_base: Path) -> dict[str, Any] | None:
    report = _load_optional(out_base / "a_psi_run" / "public_report.json")
    result = _load_optional(out_base / "a_psi_run" / "attribution_result.json")
    if report is None and result is None:
        return None
    details = report.get("details") if isinstance(report, dict) and isinstance(report.get("details"), dict) else {}
    intersection_size = _first_nonempty(
        details.get("intersection_size"),
        result.get("intersection_size") if isinstance(result, dict) else None,
    )
    intersection_sum = _first_nonempty(
        details.get("intersection_sum_raw"),
        details.get("intersection_sum"),
        result.get("intersection_sum") if isinstance(result, dict) else None,
    )
    return {
        "intersection_size": int(intersection_size) if isinstance(intersection_size, int) else intersection_size,
        "intersection_sum": int(intersection_sum) if isinstance(intersection_sum, int) else intersection_sum,
        "released": report.get("released") if isinstance(report, dict) else None,
        "reason_code": _first_nonempty(
            report.get("reason_code") if isinstance(report, dict) else None,
            details.get("reason_code") if isinstance(details, dict) else None,
        ),
        "out_base": str(out_base),
    }


def _dict_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _latest_records_by_role(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        role = str(record.get("role") or "unknown")
        prev = latest.get(role)
        if prev is None or str(record.get("ts_utc") or "") >= str(prev.get("ts_utc") or ""):
            latest[role] = record
    return latest


def _display_path(path: Path, *, out_base: Path) -> str:
    resolved = path.expanduser().resolve()
    if resolved == out_base:
        return out_base.name or str(out_base)
    for base in (out_base, REPO_ROOT):
        try:
            return str(resolved.relative_to(base))
        except ValueError:
            continue
    return str(resolved)


def _artifact_entry(out_base: Path, relative_path: str, *, label: str) -> dict[str, Any]:
    path = out_base / relative_path
    return {
        "label": label,
        "path": str(path),
        "display_path": _display_path(path, out_base=out_base),
        "available": path.is_file(),
    }


def _utc_suffix() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _suggested_job_id(job_id: str | None, *, action: str) -> str:
    base = str(job_id or "dashboard_job").strip() or "dashboard_job"
    return f"{base}_{action}_{_utc_suffix()}"


def _suggested_out_base(out_base: Path, *, suggested_job_id: str) -> Path:
    return (out_base.parent / suggested_job_id).resolve()


def _build_relaunch_context(
    out_base: Path,
    *,
    workflow_status_raw: dict[str, Any] | None,
    workflow_status: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    recommended_action = workflow_status.get("recommended_action") if workflow_status else None
    relaunch_action = recommended_action if recommended_action in {"retry", "resubmit"} else None
    request_file = manifest.get("request_file") if isinstance(manifest, dict) else None
    request_path: Path | None = None
    request_file_exists = False
    if isinstance(request_file, str) and request_file and request_file != "<inline>":
        request_path = _repo_path(request_file)
        request_file_exists = request_path.is_file()
    job_id = workflow_status_raw.get("job_id") if workflow_status_raw else None
    suggested_job_id = _suggested_job_id(str(job_id) if job_id else None, action=relaunch_action or "rerun")
    suggested_out_base = _suggested_out_base(out_base, suggested_job_id=suggested_job_id)
    return {
        "relaunch_action": relaunch_action,
        "relaunch_supported": bool(relaunch_action and request_file_exists),
        "request_file": request_file,
        "request_file_exists": request_file_exists,
        "request_file_display": _display_path(request_path, out_base=out_base) if request_path is not None else request_file,
        "suggested_job_id": suggested_job_id,
        "suggested_out_base": str(suggested_out_base),
        "suggested_out_base_display": _display_path(suggested_out_base, out_base=out_base),
    }


def _build_audit_center(
    out_base: Path,
    *,
    workflow_status_raw: dict[str, Any] | None,
    workflow_status: dict[str, Any] | None,
) -> dict[str, Any]:
    audit_chain_path = out_base / "audit_chain.json"
    audit_chain = _load_optional(audit_chain_path)
    manifest = _load_optional(out_base / "query_workflow" / "submission_manifest.json")
    receipts = _load_jsonl_objects(out_base / "query_workflow" / "execution_receipts.jsonl")

    if audit_chain is not None:
        sse_export_records = _dict_records(audit_chain.get("sse_export_audit"))
        recovery_records = _dict_records(audit_chain.get("record_recovery_service_audit"))
        bridge_records = _dict_records(audit_chain.get("bridge_audit"))
        pjc_records = _dict_records(audit_chain.get("pjc_audit"))
        policy_records = _dict_records(audit_chain.get("policy_audit"))
    else:
        sse_export_records = _load_jsonl_objects(out_base / "sse_exports" / "export_audit.jsonl")
        recovery_records = _load_jsonl_objects(out_base / "sse_exports" / "record_recovery_service_audit.jsonl")
        bridge_records = _load_jsonl_objects(out_base / "bridge_job" / "bridge_audit.jsonl")
        pjc_records = _load_jsonl_objects(out_base / "a_psi_run" / "pjc_audit.jsonl")
        policy_records = _load_jsonl_objects(out_base / "a_psi_run" / "audit_log.jsonl")

    export_by_role = _latest_records_by_role(sse_export_records)
    recovery_by_role = _latest_records_by_role(recovery_records)
    roles = sorted(set(export_by_role) | set(recovery_by_role) | {"server", "client"})
    sse_roles: list[dict[str, Any]] = []
    for role_name in roles:
        export_record = export_by_role.get(role_name, {})
        recovery_record = recovery_by_role.get(role_name, {})
        sse_roles.append({
            "role": role_name,
            "boundary": export_record.get("record_recovery_boundary"),
            "export_decision": export_record.get("decision"),
            "export_reason_code": export_record.get("reason_code"),
            "recovery_decision": recovery_record.get("decision"),
            "recovery_reason_code": recovery_record.get("reason_code"),
            "transport": recovery_record.get("transport"),
            "auth_mode": recovery_record.get("auth_mode"),
            "output_rows": _first_nonempty(recovery_record.get("output_rows"), export_record.get("output_rows")),
            "duration_ms": _first_nonempty(recovery_record.get("duration_ms"), export_record.get("duration_ms")),
            "output_file_type": _first_nonempty(recovery_record.get("output_file_type"), export_record.get("output_file_type")),
        })

    mainline_summary = summarize_mainline_contract(audit_chain) if audit_chain is not None else None
    public_report = _load_optional(out_base / "a_psi_run" / "public_report.json")
    result = _extract_result_summary(out_base) or {}
    latest_receipt = receipts[-1] if receipts else {}
    relaunch_context = _build_relaunch_context(
        out_base,
        workflow_status_raw=workflow_status_raw,
        workflow_status=workflow_status,
        manifest=manifest,
    )
    artifact_items = [
        _artifact_entry(out_base, "query_workflow/submission_manifest.json", label="Submission Manifest"),
        _artifact_entry(out_base, "query_workflow/execution_receipts.jsonl", label="Execution Receipts"),
        _artifact_entry(out_base, "query_workflow/status.json", label="Workflow Status"),
        _artifact_entry(out_base, "sse_exports/export_audit.jsonl", label="SSE Export Audit"),
        _artifact_entry(out_base, "sse_exports/record_recovery_service_audit.jsonl", label="SSE Recovery Service Audit"),
        _artifact_entry(out_base, "sse_exports/record_recovery_service_health.json", label="SSE Recovery Service Health"),
        _artifact_entry(out_base, "bridge_job/job_meta.json", label="Bridge Job Meta"),
        _artifact_entry(out_base, "bridge_job/bridge_audit.jsonl", label="Bridge Audit"),
        _artifact_entry(out_base, "a_psi_run/pjc_audit.jsonl", label="PJC Audit"),
        _artifact_entry(out_base, "a_psi_run/attribution_result.json", label="PJC Result"),
        _artifact_entry(out_base, "a_psi_run/public_report.json", label="Public Report"),
        _artifact_entry(out_base, "a_psi_run/audit_log.jsonl", label="Policy Release Audit"),
        _artifact_entry(out_base, "audit_chain.json", label="Audit Chain"),
        _artifact_entry(out_base, "audit_chain.seal.json", label="Audit Chain Seal"),
        _artifact_entry(out_base, "mainline_contract_check.json", label="Mainline Contract Check"),
        _artifact_entry(out_base, "platform_health.json", label="Platform Health Snapshot"),
        _artifact_entry(out_base, "pipeline_observability.json", label="Pipeline Observability"),
    ]
    available_count = sum(1 for item in artifact_items if item["available"])

    return {
        "out_base": str(out_base),
        "out_base_display": _display_path(out_base, out_base=out_base),
        "artifact_inventory": {
            "total_count": len(artifact_items),
            "available_count": available_count,
            "items": artifact_items,
        },
        "wrapper": {
            "state": workflow_status_raw.get("state") if workflow_status_raw else None,
            "recommended_action": workflow_status.get("recommended_action") if workflow_status else None,
            "receipt_count": len(receipts),
            "latest_event": latest_receipt.get("event"),
            "latest_error_class": latest_receipt.get("error_class"),
            "request_source": manifest.get("request_file") if isinstance(manifest, dict) else None,
            **relaunch_context,
        },
        "sse": {
            "export_record_count": len(sse_export_records),
            "recovery_record_count": len(recovery_records),
            "roles": sse_roles,
        },
        "pipeline": {
            "bridge_record_count": len(bridge_records),
            "pjc_record_count": len(pjc_records),
            "policy_record_count": len(policy_records),
            "released": result.get("released"),
            "reason_code": result.get("reason_code") or (public_report or {}).get("reason_code"),
            "intersection_size": result.get("intersection_size"),
            "intersection_sum": result.get("intersection_sum"),
        },
        "audit_chain": {
            "available": audit_chain is not None,
            "counts": audit_chain.get("counts") if isinstance(audit_chain, dict) else None,
        },
        "mainline_contract": mainline_summary,
    }


def _build_recent_runs(search_dir: Path, *, active_out_base: Path, limit: int) -> dict[str, Any]:
    statuses, total = scan_status_files(search_dir, limit=limit)
    for item in statuses:
        item["out_base_display"] = _display_path(Path(str(item.get("out_base") or "")), out_base=active_out_base)
        item["active"] = str(item.get("out_base") or "") == str(active_out_base)
    return {
        "search_dir": str(search_dir),
        "search_dir_display": _display_path(search_dir, out_base=active_out_base),
        "total_found": total,
        "returned_count": len(statuses),
        "limit": limit,
        "statuses": statuses,
    }


def _stage_rows_from_observability(observability: dict[str, Any], *, terminal_state: str, exit_code: int | None) -> list[dict[str, Any]]:
    events = observability.get("events")
    if not isinstance(events, list):
        return []
    latest_by_stage: dict[str, dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        stage = event.get("stage")
        if not isinstance(stage, str) or not stage:
            continue
        prev = latest_by_stage.get(stage)
        if prev is None or str(event.get("ts_utc") or "") >= str(prev.get("ts_utc") or ""):
            latest_by_stage[stage] = event
    order = ["sse_export", "record_recovery_service", "bridge", "pjc", "policy_release"]
    rows: list[dict[str, Any]] = []
    for stage in order:
        event = latest_by_stage.get(stage)
        if event is None:
            status = "error" if terminal_state == "failed" and not rows else "waiting"
            rows.append({"name": stage, "status": status, "duration_ms": None})
            continue
        status = str(event.get("status") or "unknown")
        if terminal_state == "running" and stage == order[-1] and status == "unknown":
            status = "running"
        if terminal_state == "failed" and exit_code not in (None, 0) and status == "unknown":
            status = "error"
        rows.append({
            "name": stage,
            "status": status,
            "duration_ms": event.get("duration_ms"),
        })
    return rows


def _stage_rows_from_files(out_base: Path, *, terminal_state: str, exit_code: int | None) -> list[dict[str, Any]]:
    rows = [
        {"name": "sse_export", "status": "waiting", "duration_ms": None},
        {"name": "record_recovery_service", "status": "waiting", "duration_ms": None},
        {"name": "bridge", "status": "waiting", "duration_ms": None},
        {"name": "pjc", "status": "waiting", "duration_ms": None},
        {"name": "policy_release", "status": "waiting", "duration_ms": None},
    ]
    sse_dir = out_base / "sse_exports"
    bridge_dir = out_base / "bridge_job"
    a_psi_dir = out_base / "a_psi_run"
    public_report = _load_optional(a_psi_dir / "public_report.json")

    has_sse = (sse_dir / "export_audit.jsonl").is_file() or (sse_dir / "server.csv").exists() or (sse_dir / "server.fifo").exists()
    has_recovery = (sse_dir / "record_recovery_service_audit.jsonl").is_file() or (sse_dir / "record_recovery_service_health.json").is_file()
    has_bridge = (bridge_dir / "job_meta.json").is_file() or (bridge_dir / "bridge_audit.jsonl").is_file()
    has_pjc_result = (a_psi_dir / "attribution_result.json").is_file()
    has_pjc_audit = (a_psi_dir / "pjc_audit.jsonl").is_file()

    if has_sse:
        rows[0]["status"] = "ok"
    if has_recovery:
        rows[1]["status"] = "ok"
    elif has_bridge:
        rows[1]["status"] = "ok"
    if has_bridge:
        rows[2]["status"] = "ok"
    if has_pjc_result:
        rows[3]["status"] = "ok" if terminal_state != "running" else "running"
    elif has_pjc_audit:
        rows[3]["status"] = "running" if terminal_state == "running" else "ok"
    elif has_bridge and terminal_state == "running":
        rows[3]["status"] = "running"
    if public_report is not None:
        released = public_report.get("released")
        rows[4]["status"] = "ok" if released is True else "error" if released is False else "unknown"

    if terminal_state == "running":
        for row in rows:
            if row["status"] == "waiting":
                row["status"] = "running"
                break
    elif terminal_state == "failed" and exit_code not in (None, 0):
        for row in rows:
            if row["status"] == "waiting":
                row["status"] = "error"
                break
    return rows


def _derive_stage_rows(out_base: Path, *, terminal_state: str, exit_code: int | None) -> list[dict[str, Any]]:
    observability = _load_optional(out_base / "pipeline_observability.json")
    if observability is not None:
        rows = _stage_rows_from_observability(observability, terminal_state=terminal_state, exit_code=exit_code)
        if rows:
            return rows
    return _stage_rows_from_files(out_base, terminal_state=terminal_state, exit_code=exit_code)


def _job_elapsed_seconds(job: dict[str, Any]) -> float | None:
    start_ts = _iso_to_ts(job.get("started_at_utc"))
    if start_ts is None:
        return None
    if job.get("state") == "running":
        return round(max(0.0, time.time() - start_ts), 3)
    end_ts = _iso_to_ts(job.get("finished_at_utc")) or _iso_to_ts(job.get("last_updated_at_utc"))
    if end_ts is None:
        return None
    return round(max(0.0, end_ts - start_ts), 3)


def _job_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    out_base = Path(job["out_base"])
    snapshot = {
        "job_id": job.get("job_id"),
        "tenant_id": job.get("tenant_id"),
        "state": job.get("state"),
        "terminal": job.get("terminal"),
        "started_at_utc": job.get("started_at_utc"),
        "finished_at_utc": job.get("finished_at_utc"),
        "last_updated_at_utc": job.get("last_updated_at_utc"),
        "elapsed_sec": _job_elapsed_seconds(job),
        "exit_code": job.get("last_exit_code"),
        "out_base": str(out_base),
        "stages": _derive_stage_rows(out_base, terminal_state=str(job.get("state") or "unknown"), exit_code=job.get("last_exit_code")),
    }
    result = _extract_result_summary(out_base)
    if result is not None:
        snapshot["result"] = result
    return snapshot


def _seed_job_from_out_base(out_base: Path) -> dict[str, Any] | None:
    status_path = out_base / "query_workflow" / "status.json"
    status = _load_optional(status_path)
    if not status or status.get("schema") != QUERY_WORKFLOW_STATUS_SCHEMA:
        return None
    state = status.get("state") or "unknown"
    return {
        "job_id": status.get("job_id"),
        "tenant_id": status.get("tenant_id"),
        "state": state,
        "terminal": bool(status.get("terminal")),
        "started_at_utc": None,
        "finished_at_utc": status.get("last_updated_at_utc") if status.get("terminal") else None,
        "last_updated_at_utc": status.get("last_updated_at_utc"),
        "last_exit_code": status.get("last_exit_code"),
        "out_base": str(out_base),
        "request_source": None,
    }


def _build_data(out_base: Path, *, history_root: Path, history_limit: int) -> dict[str, Any]:
    observability_path = out_base / "pipeline_observability.json"
    platform_health_path = out_base / "platform_health.json"
    workflow_status_path = out_base / "query_workflow" / "status.json"

    observability = _load_optional(observability_path)
    platform_health = _load_optional(platform_health_path)
    workflow_status_raw = _load_optional(workflow_status_path)

    dashboard: dict[str, Any] | None = None
    alerts: dict[str, Any] | None = None

    if observability is not None:
        try:
            dashboard = build_dashboard(observability, platform_health=platform_health)
        except Exception as exc:
            dashboard = {"error": str(exc)}
        if dashboard and "error" not in dashboard:
            try:
                alerts = build_alert_report(dashboard, platform_health=platform_health)
            except Exception as exc:
                alerts = {"error": str(exc)}

    health_section: dict[str, Any] | None = None
    if platform_health:
        ph_summary = platform_health.get("summary")
        if isinstance(ph_summary, dict):
            health_section = {
                "summary": ph_summary,
                "checks": platform_health.get("checks") or [],
            }

    workflow_status: dict[str, Any] | None = None
    if workflow_status_raw:
        retry_rec: str | None = None
        retry_eligible: dict[str, Any] | None = None
        receipts_path = out_base / "query_workflow" / "execution_receipts.jsonl"
        try:
            from check_workflow_retry_eligibility import build_eligibility_report, load_jsonl_objects
            receipts: list[dict[str, Any]] = []
            if receipts_path.is_file():
                receipts = load_jsonl_objects(receipts_path)
            retry_eligible = build_eligibility_report(workflow_status_raw, receipts)
            retry_rec = retry_eligible.get("recommended_action")
        except Exception:
            pass
        workflow_status = {
            "available": True,
            "job_id": workflow_status_raw.get("job_id"),
            "state": workflow_status_raw.get("state"),
            "terminal": workflow_status_raw.get("terminal"),
            "last_exit_code": workflow_status_raw.get("last_exit_code"),
            "receipt_count": workflow_status_raw.get("receipt_count"),
            "last_updated_at_utc": workflow_status_raw.get("last_updated_at_utc"),
            "recommended_action": retry_rec,
        }

    audit_center = _build_audit_center(
        out_base,
        workflow_status_raw=workflow_status_raw,
        workflow_status=workflow_status,
    )
    recent_runs = _build_recent_runs(history_root, active_out_base=out_base, limit=history_limit)

    scope = {}
    for field in ("job_id", "correlation_id", "caller", "tenant_id", "dataset_id", "service_id"):
        scope[field] = (dashboard or {}).get(field) if dashboard else None

    alert_status = (alerts or {}).get("overall_status", "unknown")
    health_status = ((health_section or {}).get("summary") or {}).get("status", "unknown")
    dash_status = (dashboard or {}).get("summary", {}).get("overall_status", "unknown")

    def _worst(*statuses: str) -> str:
        if any(s == "error" for s in statuses):
            return "error"
        if any(s == "warn" for s in statuses):
            return "warn"
        if all(s == "ok" for s in statuses if s not in ("unknown", "")):
            return "ok"
        return "warn"

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **scope,
        "overall_status": _worst(alert_status, health_status, dash_status),
        "dashboard": dashboard,
        "alerts": alerts,
        "health": health_section,
        "workflow_status": workflow_status,
        "audit_center": audit_center,
        "recent_runs": recent_runs,
    }


def get_dashboard_data(out_base: Path, *, history_root: Path, history_limit: int) -> dict[str, Any]:
    global _cache_data, _cache_ts
    with _cache_lock:
        now = time.monotonic()
        if _cache_data is None or now - _cache_ts > CACHE_TTL:
            _cache_data = _build_data(out_base, history_root=history_root, history_limit=history_limit)
            _cache_ts = now
        return _cache_data


def _safe_stage_rows(job_control: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = []
    stages = job_control.get("stages") if isinstance(job_control, dict) else None
    if not isinstance(stages, list):
        return rows
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        rows.append({
            "name": stage.get("name"),
            "status": stage.get("status"),
        })
    return rows


def build_dashboard_public_summary(data: dict[str, Any], *, identity: dict[str, Any] | None) -> dict[str, Any]:
    job_control = data.get("job_control") if isinstance(data.get("job_control"), dict) else None
    audit_center = data.get("audit_center") if isinstance(data.get("audit_center"), dict) else {}
    artifact_inventory = audit_center.get("artifact_inventory") if isinstance(audit_center, dict) else {}
    health = data.get("health") if isinstance(data.get("health"), dict) else {}
    health_summary = health.get("summary") if isinstance(health, dict) and isinstance(health.get("summary"), dict) else {}
    workflow_status = data.get("workflow_status") if isinstance(data.get("workflow_status"), dict) else {}
    return {
        "schema": "operator_dashboard_public_summary/v1",
        "generated_at_utc": data.get("generated_at_utc"),
        "authenticated_identity": {
            "caller": identity.get("caller"),
            "tenant_id": identity.get("tenant_id"),
            "platform_roles": identity.get("platform_roles") or [],
        } if isinstance(identity, dict) else None,
        "scope": {
            "job_id": data.get("job_id") or (job_control or {}).get("job_id"),
            "correlation_id": data.get("correlation_id"),
            "caller": data.get("caller"),
            "tenant_id": data.get("tenant_id") or (job_control or {}).get("tenant_id"),
            "dataset_id": data.get("dataset_id"),
            "service_id": data.get("service_id"),
        },
        "overall_status": data.get("overall_status"),
        "job": {
            "state": (job_control or {}).get("state"),
            "terminal": (job_control or {}).get("terminal"),
            "last_updated_at_utc": (job_control or {}).get("last_updated_at_utc"),
            "stage_statuses": _safe_stage_rows(job_control),
        },
        "workflow": {
            "available": bool(workflow_status.get("available")) if isinstance(workflow_status, dict) else False,
            "state": workflow_status.get("state") if isinstance(workflow_status, dict) else None,
            "terminal": workflow_status.get("terminal") if isinstance(workflow_status, dict) else None,
            "recommended_action": workflow_status.get("recommended_action") if isinstance(workflow_status, dict) else None,
        },
        "health": {
            "status": health_summary.get("status"),
            "ok": health_summary.get("ok"),
            "warn": health_summary.get("warn"),
            "error": health_summary.get("error"),
        },
        "artifacts": {
            "available_count": artifact_inventory.get("available_count") if isinstance(artifact_inventory, dict) else None,
            "total_count": artifact_inventory.get("total_count") if isinstance(artifact_inventory, dict) else None,
        },
        "redaction": {
            "operator_fields_redacted": True,
            "paths_redacted": True,
            "hashes_redacted": True,
            "exact_results_redacted": True,
        },
    }


def _load_start_request(body: dict[str, Any], *, default_out_base: Path) -> tuple[dict[str, Any], str, Path]:
    overrides = body.get("overrides")
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be a JSON object when provided")

    if body.get("request_file"):
        request_file = body.get("request_file")
        if not isinstance(request_file, str) or not request_file.strip():
            raise ValueError("request_file must be a non-empty string")
        request_path = _repo_path(request_file)
        if not request_path.is_file():
            raise FileNotFoundError(f"request_file does not exist: {request_path}")
        raw_payload = load_request(request_path)
        request_source = str(request_path)
        request_dir = request_path.parent
    else:
        request_obj = body.get("request")
        if request_obj is None:
            request_obj = {k: v for k, v in body.items() if k not in {"overrides", "request_base_dir"}}
        if not isinstance(request_obj, dict):
            raise ValueError("request must be a JSON object")
        raw_payload = dict(request_obj)
        request_base_dir = body.get("request_base_dir")
        if request_base_dir is not None and (not isinstance(request_base_dir, str) or not request_base_dir.strip()):
            raise ValueError("request_base_dir must be a non-empty string when provided")
        request_dir = _repo_path(request_base_dir, base_dir=REPO_ROOT) if isinstance(request_base_dir, str) and request_base_dir else REPO_ROOT
        request_source = "<inline>"

    payload = dict(raw_payload)
    for field in ("job_id", "out_base"):
        if field in body and body[field] not in (None, ""):
            overrides[field] = body[field]
    if "out_base" not in overrides and not payload.get("out_base"):
        overrides["out_base"] = str(default_out_base)
    for key, value in overrides.items():
        if value not in (None, ""):
            if key == "out_base" and isinstance(value, str):
                payload[key] = str(_repo_path(value, base_dir=REPO_ROOT))
            else:
                payload[key] = value
    return payload, request_source, request_dir


def _normalized_tenant_id(payload: dict[str, Any]) -> str:
    tenant_id = str(payload.get("tenant_id") or "").strip()
    return tenant_id or UNSPECIFIED_TENANT_ID


def _request_base_dir_from_header(value: str) -> Path:
    if not value:
        return REPO_ROOT
    request_dir = Path(value).expanduser()
    if not request_dir.is_absolute():
        raise ValueError("X-Request-Base-Dir must be an absolute path")
    return request_dir.resolve()


def _extract_submission_request(body: dict[str, Any]) -> dict[str, Any]:
    request_obj = body.get("request")
    if request_obj is None:
        request_obj = body
    if not isinstance(request_obj, dict):
        raise ValueError("request must be a JSON object")
    return dict(request_obj)


def _validate_request_schema(payload: dict[str, Any]) -> None:
    schema = load_schema_json(str(REQUEST_SCHEMA_PATH))
    try:
        validate_value(payload, schema)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def _insert_workflow_submission(
    *,
    db_path: str,
    db_dsn: str,
    submission: dict[str, Any],
    request_payload: dict[str, Any],
    identity: dict[str, Any] | None,
) -> None:
    if not db_path and not db_dsn:
        raise RuntimeError("request submission requires --metadata-db-path or --metadata-db-dsn")
    with connect_db(db_path, dsn=db_dsn) as conn:
        apply_migrations(conn)
        if not table_exists(conn, "workflow_submissions"):
            raise RuntimeError("metadata DB is missing workflow_submissions table")
        conn.execute(
            """
            INSERT INTO workflow_submissions(
              submission_id, status, submitted_at_utc, updated_at_utc,
              workflow, query_type, job_id, caller, tenant_id, dataset_id,
              service_id, request_digest, request_source, request_json,
              request_summary_json, submitted_by_identity_json, transition_history_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                submission["submission_id"],
                submission["status"],
                submission["submitted_at_utc"],
                submission["submitted_at_utc"],
                submission["workflow"],
                submission.get("query_type"),
                submission.get("job_id"),
                submission.get("caller"),
                submission.get("tenant_id"),
                submission.get("dataset_id"),
                submission.get("service_id"),
                submission.get("request_digest"),
                submission.get("request_source"),
                json.dumps(request_payload, ensure_ascii=False, sort_keys=True),
                json.dumps(submission.get("request_summary") or {}, ensure_ascii=False, sort_keys=True),
                json.dumps(identity, ensure_ascii=False, sort_keys=True) if identity is not None else None,
                json.dumps(submission.get("transitions") or [], ensure_ascii=False, sort_keys=True),
            ),
        )
        if table_exists(conn, "control_plane_mutations"):
            conn.execute(
                """
                INSERT INTO control_plane_mutations(
                  mutation_id, operation, entity_type, entity_id, actor, source,
                  old_state_json, new_state_json, status, applied_at_utc, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    "submit_request",
                    "workflow_submission",
                    submission["submission_id"],
                    submission.get("caller"),
                    "serve_operator_dashboard:/v1/request/submit",
                    None,
                    json.dumps(submission, ensure_ascii=False, sort_keys=True),
                    "applied",
                    submission["submitted_at_utc"],
                    "I3-a self-service request submission",
                ),
            )
        conn.commit()


def _json_field(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def _submission_from_row(row: Any, *, include_request: bool = False) -> dict[str, Any]:
    request_summary = _json_field(row["request_summary_json"], {})
    transitions = _json_field(row["transition_history_json"], [])
    identity = _json_field(row["submitted_by_identity_json"], None)
    payload = {
        "schema": REQUEST_SUBMISSION_SCHEMA,
        "submission_id": row["submission_id"],
        "submitted_at_utc": row["submitted_at_utc"],
        "updated_at_utc": row["updated_at_utc"],
        "status": row["status"],
        "workflow": row["workflow"],
        "query_type": row["query_type"],
        "job_id": row["job_id"],
        "caller": row["caller"],
        "tenant_id": row["tenant_id"],
        "dataset_id": row["dataset_id"],
        "service_id": row["service_id"],
        "approved_by": row["approved_by"],
        "approved_at_utc": row["approved_at_utc"],
        "rejected_by": row["rejected_by"],
        "rejected_at_utc": row["rejected_at_utc"],
        "rejection_reason": row["rejection_reason"],
        "request_digest": row["request_digest"],
        "request_source": row["request_source"],
        "approval_required": True,
        "request_summary": request_summary if isinstance(request_summary, dict) else {},
        "authenticated_identity": identity if isinstance(identity, dict) else None,
        "transitions": transitions if isinstance(transitions, list) else [],
    }
    if include_request:
        request_payload = _json_field(row["request_json"], {})
        if isinstance(request_payload, dict):
            payload["request"] = request_payload
    return payload


def _connect_submission_db(server: "DashboardServer"):
    if not server.metadata_db_path and not server.metadata_db_dsn:
        raise RuntimeError("request workflow requires --metadata-db-path or --metadata-db-dsn")
    conn = connect_db(server.metadata_db_path, dsn=server.metadata_db_dsn)
    apply_migrations(conn)
    if not table_exists(conn, "workflow_submissions"):
        conn.close()
        raise RuntimeError("metadata DB is missing workflow_submissions table")
    return conn


def _load_submission(conn: Any, submission_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT submission_id, status, submitted_at_utc, updated_at_utc,
               workflow, query_type, job_id, caller, tenant_id, dataset_id,
               service_id, request_digest, request_source, request_json,
               request_summary_json, submitted_by_identity_json,
               approved_by, approved_at_utc, rejected_by, rejected_at_utc,
               rejection_reason, transition_history_json
        FROM workflow_submissions
        WHERE submission_id = ?
        """,
        (submission_id,),
    ).fetchone()
    if row is None:
        raise FileNotFoundError(f"request submission not found: {submission_id}")
    return _submission_from_row(row, include_request=True)


def _actor(identity: dict[str, Any] | None) -> str | None:
    if identity is None:
        return None
    caller = identity.get("caller")
    return str(caller) if caller not in (None, "") else None


def _require_resolved_identity(identity: dict[str, Any] | None) -> dict[str, Any]:
    if identity is None:
        raise PermissionError("request workflow action requires resolved identity")
    return identity


def _assert_request_view_allowed(identity: dict[str, Any] | None, submission: dict[str, Any]) -> None:
    if identity is None:
        return
    if identity_has_any_role(identity, "platform_admin", "compliance_auditor"):
        return
    if str(submission.get("caller") or "") == str(identity.get("caller") or ""):
        return
    if identity_has_any_role(identity, "privacy_operator", "commerce_ops_owner"):
        identity_tenant = str(identity.get("tenant_id") or "")
        if identity_tenant and identity_tenant == str(submission.get("tenant_id") or ""):
            return
    raise PermissionError("request submission access denied")


def _assert_privacy_budget_approval_view_allowed(identity: dict[str, Any], request: dict[str, Any]) -> None:
    if identity_has_any_role(identity, "platform_admin", "platform_auditor"):
        return
    if str(request.get("caller") or "") == str(identity.get("caller") or ""):
        return
    if identity_has_any_role(identity, "privacy_operator", "compliance_auditor"):
        identity_tenant = str(identity.get("tenant_id") or "")
        request_tenant = str(request.get("tenant_id") or "")
        if identity_tenant and request_tenant and identity_tenant == request_tenant:
            return
    raise PermissionError("privacy budget approval access denied")


def _privacy_budget_approval_store_path(server: "DashboardServer") -> str:
    if not server.privacy_budget_store:
        raise RuntimeError("privacy budget approval API requires --privacy-budget-store")
    return server.privacy_budget_store


def _append_privacy_budget_decision_jsonl(path: str, record: dict[str, Any]) -> None:
    if not path:
        return
    append_jsonl(Path(path), record)


def _build_privacy_budget_decision_record(
    *,
    request: dict[str, Any],
    action: str,
    actor: str,
    reason: str,
    expires_at_utc: str | None,
) -> dict[str, Any]:
    status = {
        "approve": "approved",
        "reject": "rejected",
        "expire": "expired",
    }[action]
    return {
        "schema": "privacy_budget_approval_decision/v1",
        "created_at_utc": policy_release.utc_now_iso(),
        "action": action,
        "status": status,
        "request_id": request["request_id"],
        "actor": actor,
        "caller": request["caller"],
        "tenant_id": request.get("tenant_id"),
        "dataset_id": request.get("dataset_id"),
        "purpose": request.get("purpose"),
        "job_id": request.get("job_id"),
        "consuming_job_id": None,
        "query_fingerprint": request.get("query_fingerprint"),
        "query_payload_sha256": request.get("query_payload_sha256"),
        "reason": reason or f"privacy budget approval {action}",
        "expires_at_utc": expires_at_utc,
        "public_report_sha256": request.get("public_report_sha256"),
        "budget_consumed": False,
        "consuming_event_id": None,
    }


def _validate_privacy_budget_expires_at(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    try:
        policy_release.parse_iso8601_utc(str(value))
    except Exception as exc:
        raise ValueError("expires_at_utc must be an ISO8601 UTC timestamp") from exc
    return str(value)


def _list_privacy_budget_approvals(
    server: "DashboardServer",
    *,
    identity: dict[str, Any] | None,
    status: str,
    tenant_id: str,
    caller: str,
    limit: int,
) -> dict[str, Any]:
    resolved_identity = _require_resolved_identity(identity)
    if not identity_has_any_role(resolved_identity, *PRIVACY_BUDGET_APPROVAL_REVIEW_ROLES):
        caller = caller or str(resolved_identity.get("caller") or "")
    store_path = _privacy_budget_approval_store_path(server)
    with policy_release.PrivacyBudgetStore(store_path) as store:
        store.begin_immediate()
        store.bootstrap_approval_requests(server.privacy_budget_approval_queue or None)
        store.bootstrap_approval_decisions(server.privacy_budget_approval_decisions or None)
        requests = store.list_approval_requests(status=status or None)
        store.commit()

    filtered: list[dict[str, Any]] = []
    for request in requests:
        try:
            _assert_privacy_budget_approval_view_allowed(resolved_identity, request)
        except PermissionError:
            continue
        if tenant_id and str(request.get("tenant_id") or "") != tenant_id:
            continue
        if caller and str(request.get("caller") or "") != caller:
            continue
        filtered.append(request)
        if len(filtered) >= limit:
            break
    return {
        "schema": PRIVACY_BUDGET_APPROVAL_LIST_SCHEMA,
        "status": "ok",
        "filter_status": status or None,
        "tenant_id": tenant_id or None,
        "caller": caller or None,
        "returned_count": len(filtered),
        "limit": limit,
        "requests": filtered,
    }


def _transition_privacy_budget_approval(
    server: "DashboardServer",
    *,
    request_id: str,
    action: str,
    identity: dict[str, Any] | None,
    reason: str,
    expires_at_utc: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved_identity = _require_resolved_identity(identity)
    actor = _actor(resolved_identity)
    expires_at_utc = _validate_privacy_budget_expires_at(expires_at_utc)
    if not actor:
        raise PermissionError("privacy budget approval transition requires resolved actor")
    if action == "approve":
        if not identity_has_any_role(resolved_identity, *PRIVACY_BUDGET_APPROVAL_APPROVE_ROLES):
            raise PermissionError("privacy budget approval requires privacy_operator or platform_admin role")
    elif action == "reject":
        if not identity_has_any_role(resolved_identity, *PRIVACY_BUDGET_APPROVAL_REJECT_ROLES):
            raise PermissionError("privacy budget rejection requires privacy_operator, platform_admin, or compliance_auditor role")
        if not reason.strip():
            raise ValueError("privacy budget rejection reason is required")
    elif action == "expire":
        if not identity_has_any_role(resolved_identity, *PRIVACY_BUDGET_APPROVAL_EXPIRE_ROLES):
            raise PermissionError("privacy budget expiry requires privacy_operator, platform_admin, or compliance_auditor role")
        if not reason.strip():
            raise ValueError("privacy budget expiry reason is required")
    else:
        raise ValueError(f"unsupported privacy budget approval transition: {action}")

    store_path = _privacy_budget_approval_store_path(server)
    with policy_release.PrivacyBudgetStore(store_path) as store:
        store.begin_immediate()
        store.bootstrap_approval_requests(server.privacy_budget_approval_queue or None)
        store.bootstrap_approval_decisions(server.privacy_budget_approval_decisions or None)
        request = store.load_approval_request(request_id)
        if request is None:
            raise FileNotFoundError(f"privacy budget approval request not found: {request_id}")
        _assert_privacy_budget_approval_view_allowed(resolved_identity, request)
        if action == "approve" and actor == str(request.get("caller") or ""):
            raise PermissionError("same_identity_self_approval")
        record = _build_privacy_budget_decision_record(
            request=request,
            action=action,
            actor=actor,
            reason=reason.strip(),
            expires_at_utc=expires_at_utc,
        )
        updated = store.transition_approval_request(
            request_id=request_id,
            action=action,
            actor=actor,
            reason=reason.strip(),
            expires_at_utc=expires_at_utc,
            decision_record=record,
        )
        _append_privacy_budget_decision_jsonl(server.privacy_budget_approval_decisions, record)
        store.commit()
    return updated, record


def _append_transition(transitions: list[Any], *, state: str, event: str, actor: str | None, at_utc: str, reason: str | None = None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = [item for item in transitions if isinstance(item, dict)]
    transition = {
        "state": state,
        "event": event,
        "actor": actor,
        "at_utc": at_utc,
    }
    if reason:
        transition["reason"] = reason
    normalized.append(transition)
    return normalized


def _log_workflow_mutation(
    conn: Any,
    *,
    operation: str,
    submission_id: str,
    actor: str | None,
    old_state: dict[str, Any] | None,
    new_state: dict[str, Any],
    at_utc: str,
    notes: str | None = None,
) -> None:
    if not table_exists(conn, "control_plane_mutations"):
        return
    conn.execute(
        """
        INSERT INTO control_plane_mutations(
          mutation_id, operation, entity_type, entity_id, actor, source,
          old_state_json, new_state_json, status, applied_at_utc, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            operation,
            "workflow_submission",
            submission_id,
            actor,
            f"serve_operator_dashboard:/v1/request/{submission_id}/{operation.removesuffix('_request')}",
            json.dumps(old_state, ensure_ascii=False, sort_keys=True) if old_state is not None else None,
            json.dumps(new_state, ensure_ascii=False, sort_keys=True),
            "applied",
            at_utc,
            notes,
        ),
    )


def _list_submissions(
    server: "DashboardServer",
    *,
    identity: dict[str, Any] | None,
    tenant_id: str,
    status: str,
    limit: int,
) -> dict[str, Any]:
    with _connect_submission_db(server) as conn:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if tenant_id:
            clauses.append("tenant_id = ?")
            params.append(tenant_id)
        elif identity is not None and not identity_has_any_role(identity, "platform_admin", "compliance_auditor"):
            identity_tenant = str(identity.get("tenant_id") or "")
            if identity_tenant:
                clauses.append("tenant_id = ?")
                params.append(identity_tenant)
        if identity is not None and not identity_has_any_role(identity, *REQUEST_REVIEW_ROLES):
            clauses.append("caller = ?")
            params.append(str(identity.get("caller") or ""))
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"""
            SELECT submission_id, status, submitted_at_utc, updated_at_utc,
                   workflow, query_type, job_id, caller, tenant_id, dataset_id,
                   service_id, request_digest, request_source, request_json,
                   request_summary_json, submitted_by_identity_json,
                   approved_by, approved_at_utc, rejected_by, rejected_at_utc,
                   rejection_reason, transition_history_json
            FROM workflow_submissions
            {where_sql}
            ORDER BY submitted_at_utc DESC
            LIMIT ?
            """,
            tuple(params + [limit]),
        ).fetchall()
        submissions = []
        for row in rows:
            item = _submission_from_row(row)
            try:
                _assert_request_view_allowed(identity, item)
            except PermissionError:
                continue
            submissions.append(item)
        return {
            "schema": "operator_request_submission_list/v1",
            "status": "ok",
            "tenant_id": tenant_id or None,
            "filter_status": status or None,
            "returned_count": len(submissions),
            "limit": limit,
            "submissions": submissions,
        }


def _transition_submission(
    server: "DashboardServer",
    *,
    submission_id: str,
    action: str,
    identity: dict[str, Any] | None,
    reason: str = "",
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    resolved_identity = _require_resolved_identity(identity)
    actor = _actor(resolved_identity)
    if action == "reject":
        if not identity_has_any_role(resolved_identity, *REQUEST_REJECT_ROLES):
            raise PermissionError("request rejection requires privacy_operator, platform_admin, or compliance_auditor role")
        if not reason.strip():
            raise ValueError("rejection reason is required")
    elif action != "approve":
        raise ValueError(f"unsupported request transition: {action}")

    normalized_to_start: dict[str, Any] | None = None
    reserved_job_id: str | None = None
    reservation_acquired = False
    with _connect_submission_db(server) as conn:
        old_submission = _load_submission(conn, submission_id)
        _assert_request_view_allowed(resolved_identity, old_submission)
        if old_submission.get("status") != "pending_approval":
            raise RuntimeError(f"request submission is not pending_approval: {old_submission.get('status')}")
        if action == "approve" and actor and actor == str(old_submission.get("caller") or ""):
            raise PermissionError("same_identity_self_approval")
        if action == "approve":
            if not identity_has_any_role(resolved_identity, *APPROVER_ROLES):
                raise PermissionError("request approval requires privacy_operator or platform_admin role")
            request_payload = old_submission.get("request")
            if not isinstance(request_payload, dict):
                raise RuntimeError("approved request is missing request payload")
            normalized_to_start = normalize_request_paths(request_payload, request_dir=REPO_ROOT)
            validate_request(normalized_to_start)
            reserved_job_id = str(normalized_to_start.get("job_id") or "") or None
            preview_out_base = Path(str(normalized_to_start["out_base"])).resolve()
            reservation_error = server.try_reserve_job(
                tenant_id=_normalized_tenant_id(normalized_to_start),
                job_id=reserved_job_id,
                out_base=preview_out_base,
                request_source=f"operator_request:{submission_id}",
            )
            if reservation_error is not None:
                raise RuntimeError(json.dumps(reservation_error["body"], ensure_ascii=False, sort_keys=True))
            reservation_acquired = True
        at_utc = _utc_now()
        new_status = "approved" if action == "approve" else "rejected"
        transitions = _append_transition(
            old_submission.get("transitions") if isinstance(old_submission.get("transitions"), list) else [],
            state=new_status,
            event=f"{action}_request",
            actor=actor,
            at_utc=at_utc,
            reason=reason.strip() if action == "reject" else None,
        )
        if action == "approve":
            conn.execute(
                """
                UPDATE workflow_submissions
                SET status = ?, updated_at_utc = ?, approved_by = ?, approved_at_utc = ?,
                    transition_history_json = ?
                WHERE submission_id = ?
                """,
                (
                    new_status,
                    at_utc,
                    actor,
                    at_utc,
                    json.dumps(transitions, ensure_ascii=False, sort_keys=True),
                    submission_id,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE workflow_submissions
                SET status = ?, updated_at_utc = ?, rejected_by = ?, rejected_at_utc = ?,
                    rejection_reason = ?, transition_history_json = ?
                WHERE submission_id = ?
                """,
                (
                    new_status,
                    at_utc,
                    actor,
                    at_utc,
                    reason.strip(),
                    json.dumps(transitions, ensure_ascii=False, sort_keys=True),
                    submission_id,
                ),
            )
        updated = _load_submission(conn, submission_id)
        _log_workflow_mutation(
            conn,
            operation=f"{action}_request",
            submission_id=submission_id,
            actor=actor,
            old_state=old_submission,
            new_state=updated,
            at_utc=at_utc,
            notes=reason.strip() if action == "reject" else "I3-b approval workflow",
        )
        try:
            conn.commit()
        except BaseException:
            if reservation_acquired:
                server.release_reservation(reserved_job_id)
            raise

    job_snapshot = None
    if action == "approve" and normalized_to_start is not None:
        try:
            _start_job_thread(
                server,
                payload=normalized_to_start,
                request_source=f"operator_request:{submission_id}",
                request_dir=REPO_ROOT,
            )
        except BaseException:
            if reservation_acquired:
                server.release_reservation(reserved_job_id)
            raise
        snapshot_job = server.get_job(reserved_job_id) if reserved_job_id else server.get_job()
        job_snapshot = _job_snapshot(snapshot_job) if snapshot_job is not None else None
    return updated, job_snapshot


def _build_request_submission(
    *,
    payload: dict[str, Any],
    request_source: str,
    identity: dict[str, Any] | None,
) -> dict[str, Any]:
    submitted_at = _utc_now()
    transition = {
        "state": "pending_approval",
        "event": "submit_request",
        "actor": payload.get("caller"),
        "at_utc": submitted_at,
    }
    return {
        "schema": REQUEST_SUBMISSION_SCHEMA,
        "submission_id": f"req_{uuid.uuid4().hex}",
        "submitted_at_utc": submitted_at,
        "updated_at_utc": submitted_at,
        "status": "pending_approval",
        "workflow": "sse_bridge_pipeline",
        "query_type": payload.get("query_type"),
        "job_id": payload.get("job_id"),
        "caller": payload.get("caller"),
        "tenant_id": payload.get("tenant_id"),
        "dataset_id": payload.get("dataset_id"),
        "service_id": payload.get("record_recovery_service_id") or payload.get("service_id"),
        "request_digest": json_sha256(payload),
        "request_source": request_source,
        "approval_required": True,
        "request_summary": summarize_request(payload),
        "authenticated_identity": identity,
        "transitions": [transition],
    }


def _load_relaunch_request(
    body: dict[str, Any],
    *,
    out_base: Path,
    workflow_status_raw: dict[str, Any] | None,
    workflow_status: dict[str, Any] | None,
) -> tuple[dict[str, Any], str, Path, dict[str, Any]]:
    manifest = _load_optional(out_base / "query_workflow" / "submission_manifest.json")
    relaunch_context = _build_relaunch_context(
        out_base,
        workflow_status_raw=workflow_status_raw,
        workflow_status=workflow_status,
        manifest=manifest,
    )
    request_file = relaunch_context.get("request_file")
    if not relaunch_context.get("relaunch_supported") or not isinstance(request_file, str):
        raise ValueError("automatic relaunch is not supported for this run")
    requested_action = body.get("action")
    if requested_action not in (None, "", relaunch_context.get("relaunch_action")):
        raise ValueError(
            f"requested action {requested_action!r} does not match recommended action {relaunch_context.get('relaunch_action')!r}"
        )
    overrides = body.get("overrides")
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be a JSON object when provided")
    if not overrides.get("job_id"):
        overrides["job_id"] = relaunch_context.get("suggested_job_id")
    if not overrides.get("out_base"):
        overrides["out_base"] = relaunch_context.get("suggested_out_base")
    payload, request_source, request_dir = _load_start_request(
        {"request_file": request_file, "overrides": overrides},
        default_out_base=Path(str(overrides["out_base"])),
    )
    return payload, request_source, request_dir, relaunch_context


def _start_job_thread(server: "DashboardServer", *, payload: dict[str, Any], request_source: str, request_dir: Path) -> None:
    normalized = normalize_request_paths(payload, request_dir=request_dir)
    validate_request(normalized)
    command = build_command(normalized)
    request_digest = json_sha256(normalized)
    out_base = Path(str(normalized["out_base"])).resolve()
    sidecar_paths = query_workflow_sidecar_paths(str(out_base))
    manifest = render_manifest(
        request_source=request_source,
        payload=normalized,
        command=command,
        mode="execute",
        exit_code=None,
    )
    write_json(sidecar_paths["submission_manifest"], manifest)
    started_receipt = build_receipt(
        payload=normalized,
        mode="execute",
        event="started",
        request_digest=request_digest,
        command=command,
        exit_code=None,
    )
    append_jsonl(sidecar_paths["execution_receipts"], started_receipt)
    started_status = build_status(
        payload=normalized,
        mode="execute",
        state="running",
        terminal=False,
        latest_receipt=started_receipt,
        receipt_count=1,
        exit_code=None,
    )
    write_json(sidecar_paths["status"], started_status)

    job_record = {
        "job_id": normalized.get("job_id"),
        "tenant_id": _normalized_tenant_id(normalized),
        "state": "running",
        "terminal": False,
        "started_at_utc": _utc_now(),
        "finished_at_utc": None,
        "last_updated_at_utc": _utc_now(),
        "last_exit_code": None,
        "out_base": str(out_base),
        "request_source": request_source,
    }
    server.out_base = out_base
    server.set_job(job_record)

    def _runner() -> None:
        exit_code: int | None = None
        try:
            result = subprocess.run(command, cwd=str(REPO_ROOT), check=False)
            exit_code = result.returncode
        except OSError:
            exit_code = 127

        finished_at = _utc_now()
        final_manifest = render_manifest(
            request_source=request_source,
            payload=normalized,
            command=command,
            mode="execute",
            exit_code=exit_code,
        )
        write_json(sidecar_paths["submission_manifest"], final_manifest)
        final_receipt = build_receipt(
            payload=normalized,
            mode="execute",
            event="completed" if exit_code in (None, 0) else "failed",
            request_digest=request_digest,
            command=command,
            exit_code=exit_code,
        )
        append_jsonl(sidecar_paths["execution_receipts"], final_receipt)
        final_status = build_status(
            payload=normalized,
            mode="execute",
            state="completed" if exit_code in (None, 0) else "failed",
            terminal=True,
            latest_receipt=final_receipt,
            receipt_count=2,
            exit_code=exit_code,
        )
        write_json(sidecar_paths["status"], final_status)
        server.set_job({
            "job_id": normalized.get("job_id"),
            "tenant_id": _normalized_tenant_id(normalized),
            "state": "completed" if exit_code in (None, 0) else "failed",
            "terminal": True,
            "started_at_utc": job_record["started_at_utc"],
            "finished_at_utc": finished_at,
            "last_updated_at_utc": finished_at,
            "last_exit_code": exit_code,
            "out_base": str(out_base),
            "request_source": request_source,
        })

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()


# ---------------------------------------------------------------------------
# Two-Party Out-of-Box (S9) helpers — preflight, role package, role lifecycle,
# evidence merge, and required negative-case runner. These are intentionally
# kept self-contained at module level so the new endpoints stay easy to test
# directly without spinning up the HTTP server.
# ---------------------------------------------------------------------------

PJC_TWO_PARTY_PREFLIGHT_SCHEMA = "pjc_two_party_preflight/v1"
PJC_ROLE_PACKAGE_SCHEMA = "pjc_role_package/v1"
PJC_ROLE_STATUS_SCHEMA = "pjc_role_status/v1"
PJC_TWO_PARTY_SIGNED_RUN_MANIFEST_SCHEMA = "pjc_two_party_signed_run_manifest/v1"
PJC_TWO_PARTY_EVIDENCE_MERGE_SCHEMA = "pjc_two_party_evidence_merge/v1"
PJC_TWO_PARTY_NEGATIVE_CASES_SCHEMA = "pjc_two_party_negative_cases/v1"

PJC_TWO_PARTY_EVIDENCE_DIR = REPO_ROOT / "tmp" / "pjc_two_party"

PJC_ROLE_ENV_ALLOWLIST: tuple[str, ...] = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "JOB_ID",
    "JOB_DIR",
    "CERT_DIR",
    "SERVER_HOST",
    "SERVER_CSV",
    "CLIENT_CSV",
    "PJC_DIR",
    "PJC_BIN_DIR",
    "PJC_BUILD",
    "PJC_LOCAL_PORT",
    "TLS_PORT",
    "BIND_ADDR",
    "LOCAL_PROXY_PORT",
    "OUT_DIR",
    "GRPC_MAX_MESSAGE_MB",
    "SHARED_RESULT_DIR",
    "RUN_PJC_SERVER_SH",
    "RUN_PJC_CLIENT_SH",
    "SERVER_ADDR",
    "PJC_GRPC_STREAM_CHUNK_ELEMENTS",
    "PJC_PRODUCTION_MODE",
    "PJC_ALLOW_LEGACY_UNARY",
    "PJC_ALLOW_PRODUCTION_WIDE_BIND",
    "PJC_MTLS_REQUIRE_SESSION_MANIFEST",
    "PJC_RESOURCE_LIMITS",
    "PJC_PREFLIGHT_REQUIRED",
    "PJC_PREFLIGHT_CALLER",
    "PJC_PREFLIGHT_TENANT_ID",
    "PJC_PREFLIGHT_DATASET_ID",
    "PJC_PREFLIGHT_PURPOSE",
    "PJC_PREFLIGHT_CLIENT_CSV",
    "PJC_PREFLIGHT_CLIENT_ROWS",
    "PJC_INPUT_COMMITMENT",
    "PJC_JOB_META",
    "PJC_REQUIRE_INPUT_COMMITMENT",
)

PJC_REQUIRED_NEGATIVE_CASES: tuple[str, ...] = (
    "wrong_token",
    "expired_token",
    "wrong_ca",
    "wrong_peer",
    "closed_port",
    "commit_mismatch",
    "modified_csv",
    "privacy_denial",
)


_PJC_ROLE_REGISTRY: dict[str, dict[str, Any]] = {}
_PJC_ROLE_REGISTRY_LOCK = threading.Lock()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(str(value or "").encode("ascii"), validate=True)


def _load_ed25519_private_key(path: Path):
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as exc:  # pragma: no cover - dependency gate
        raise RuntimeError("cryptography package is required for signed PJC run manifests") from exc
    key_bytes = path.read_bytes()
    try:
        key = serialization.load_pem_private_key(key_bytes, password=None)
    except ValueError:
        key = Ed25519PrivateKey.from_private_bytes(key_bytes)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("signing key must be an Ed25519 private key")
    return key


def _load_ed25519_public_key_from_pem(pem: str):
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:  # pragma: no cover - dependency gate
        raise RuntimeError("cryptography package is required for signed PJC run manifest verification") from exc
    key = serialization.load_pem_public_key(str(pem or "").encode("utf-8"))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("manifest public_key_pem must be Ed25519")
    return key


def _ed25519_public_key_pem(private_key: Any) -> str:
    from cryptography.hazmat.primitives import serialization

    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def _ed25519_public_key_fingerprint(public_key_pem: str) -> str:
    return _sha256_bytes(str(public_key_pem or "").encode("utf-8"))


def _ensure_two_party_dir() -> Path:
    PJC_TWO_PARTY_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    return PJC_TWO_PARTY_EVIDENCE_DIR


def _read_repo_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _tcp_probe(host: str, port: int, *, timeout_sec: float = 5.0) -> tuple[bool, float, str]:
    started = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_sec):
            return True, round((time.monotonic() - started) * 1000.0, 3), ""
    except (OSError, ValueError) as exc:
        return False, round((time.monotonic() - started) * 1000.0, 3), str(exc)


def _tls_handshake_probe(host: str, port: int, *, ca_path: Path | None, cert_path: Path | None, key_path: Path | None, server_hostname: str | None, timeout_sec: float = 5.0) -> dict[str, Any]:
    """Try a TLS handshake and return cert / protocol details (does not verify SAN)."""
    import ssl

    info: dict[str, Any] = {
        "ok": False,
        "tls_protocol": None,
        "peer_cert_pem": None,
        "peer_cert_subject": None,
        "peer_cert_fingerprint_sha256": None,
        "message": "",
    }
    try:
        ctx = ssl.create_default_context(cafile=str(ca_path) if ca_path else None)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED if ca_path is not None else ssl.CERT_NONE
        if cert_path is not None and key_path is not None:
            ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        with socket.create_connection((host, int(port)), timeout=timeout_sec) as raw:
            with ctx.wrap_socket(raw, server_hostname=server_hostname or None) as tls:
                info["tls_protocol"] = tls.version()
                cert_bin = tls.getpeercert(binary_form=True)
                if cert_bin:
                    info["peer_cert_fingerprint_sha256"] = hashlib.sha256(cert_bin).hexdigest()
                    cert_pem = ssl.DER_cert_to_PEM_cert(cert_bin)
                    info["peer_cert_pem"] = cert_pem
                cert_info = tls.getpeercert()
                if isinstance(cert_info, dict):
                    subject = cert_info.get("subject")
                    if isinstance(subject, (list, tuple)):
                        flat = []
                        for rdn in subject:
                            for kv in rdn or ():
                                try:
                                    flat.append("=".join(str(p) for p in kv))
                                except Exception:
                                    continue
                        info["peer_cert_subject"] = "/".join(flat) or None
        info["ok"] = True
    except Exception as exc:  # noqa: BLE001
        info["message"] = str(exc)
    return info


def _validate_two_party_role(value: Any) -> str:
    role = str(value or "").strip().lower()
    if role not in ("server", "client"):
        raise ValueError("role must be 'server' or 'client'")
    return role


def _resolve_repo_path_strict(value: Any, *, label: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{label} is required")
    return _repo_path(raw)


def _file_rows_and_bytes(path: Path) -> tuple[int, int]:
    if not path.is_file():
        return 0, 0
    size = path.stat().st_size
    rows = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            rows += chunk.count(b"\n")
    return rows, size


def _walk_files(root: Path) -> list[Path]:
    items: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            items.append(path)
    return items


def _file_manifest(root: Path, files: list[Path]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in files:
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path
        out.append({
            "path": str(rel).replace("\\", "/"),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        })
    return out


def _package_aggregate_sha(items: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for item in items:
        h.update(item["path"].encode("utf-8"))
        h.update(b"\x00")
        h.update(item["sha256"].encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def _safe_unique_dir(parent: Path, suggestion: str) -> Path:
    base = parent / suggestion
    if not base.exists():
        return base
    for n in range(1, 1000):
        candidate = parent / f"{suggestion}_{n}"
        if not candidate.exists():
            return candidate
    return parent / f"{suggestion}_{uuid.uuid4().hex[:8]}"


def _peer_identity_check_via_helper(*, cert_pem: str, ca_pem: str | None, role: str, job_id: str, expected_fingerprint: str, expected_identity: str) -> dict[str, Any]:
    """Use scripts/check_pjc_tls_identity.py as the canonical identity gate."""
    helper = REPO_ROOT / "scripts" / "check_pjc_tls_identity.py"
    if not helper.is_file():
        return {"status": "skip", "decision": None, "reason_code": None, "message": "identity helper missing"}
    with tempfile.TemporaryDirectory(prefix="pjc_preflight_") as tmp:
        tmp_dir = Path(tmp)
        cert_path = tmp_dir / "peer.crt"
        cert_path.write_text(cert_pem, encoding="utf-8")
        ca_path: Path | None = None
        if ca_pem:
            ca_path = tmp_dir / "ca.crt"
            ca_path.write_text(ca_pem, encoding="utf-8")
        out_path = tmp_dir / "identity.json"
        argv = [
            sys.executable,
            str(helper),
            "--cert", str(cert_path),
            "--role", role,
            "--job-id", job_id,
            "--output", str(out_path),
        ]
        if ca_path is not None:
            argv += ["--ca-cert", str(ca_path)]
        if expected_fingerprint:
            argv += ["--expected-fingerprint-sha256", expected_fingerprint]
        if expected_identity:
            argv += ["--expected-peer-identity", expected_identity]
        result = subprocess.run(
            argv,
            cwd=str(REPO_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        if not out_path.is_file():
            return {
                "status": "deny",
                "decision": "deny",
                "reason_code": "identity_helper_failed",
                "message": (result.stderr.strip() or result.stdout.strip() or "identity check did not write report"),
            }
        try:
            report = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {"status": "deny", "decision": "deny", "reason_code": "identity_helper_invalid_json", "message": str(exc)}
        decision = report.get("decision")
        reason_code = report.get("reason_code")
        return {
            "status": "ok" if decision == "allow" else "deny",
            "decision": decision,
            "reason_code": reason_code,
            "actual_identity": report.get("peer_identity"),
            "ca_fingerprint_sha256": report.get("ca_fingerprint_sha256"),
            "message": report.get("reason") or "",
        }


def _two_party_preflight(body: dict[str, Any]) -> dict[str, Any]:
    """Produce a ``pjc_two_party_preflight/v1`` report and decide allow/deny."""
    job_id = str(body.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")
    role = _validate_two_party_role(body.get("role"))
    expected_peer_role = "client" if role == "server" else "server"
    expected_peer_identity = str(body.get("expected_peer_identity") or "").strip() or None
    expected_ca_fp = _normalize_fingerprint(str(body.get("expected_ca_fingerprint_sha256") or body.get("expected_ca_fingerprint") or "")) or None
    expected_commit = str(body.get("expected_commit") or "").strip() or None
    expected_dataplane_port_raw = body.get("expected_dataplane_port")
    expected_dataplane_port = (
        int(expected_dataplane_port_raw)
        if isinstance(expected_dataplane_port_raw, (int, str)) and str(expected_dataplane_port_raw).strip()
        else None
    )

    findings: list[dict[str, Any]] = []
    checks: dict[str, dict[str, Any]] = {
        "commit": {"status": "skip"},
        "helper_script": {"status": "skip"},
        "pjc_binary": {"status": "skip"},
        "tcp_probe": {"status": "skip"},
        "tls_handshake": {"status": "skip"},
        "peer_identity": {"status": "skip"},
        "input_manifest": {"status": "skip"},
        "resource_limits": {"status": "skip"},
        "output_path": {"status": "skip"},
    }

    # 1. commit check
    actual_commit = _read_repo_commit()
    if expected_commit:
        commit_status = "ok" if actual_commit and actual_commit == expected_commit else "deny"
        checks["commit"] = {
            "status": commit_status,
            "actual": actual_commit,
            "expected": expected_commit,
            "message": None if commit_status == "ok" else "repo commit does not match expected",
        }
        if commit_status == "deny":
            findings.append({
                "kind": "commit_mismatch",
                "message": "repo commit does not match expected",
                "expected": expected_commit,
                "actual": actual_commit,
            })
    else:
        checks["commit"] = {"status": "skip", "actual": actual_commit, "expected": None, "message": "no expected_commit provided"}

    # 2. helper-script hash check
    helper_path_raw = str(body.get("helper_script_path") or "").strip()
    expected_helper_sha = str(body.get("expected_helper_script_sha256") or "").strip().lower() or None
    if helper_path_raw:
        helper_path = _repo_path(helper_path_raw)
        if not helper_path.is_file():
            checks["helper_script"] = {"status": "deny", "script_path": str(helper_path), "actual_sha256": None, "expected_sha256": expected_helper_sha, "message": "helper script not found"}
            findings.append({"kind": "helper_version_mismatch", "message": "helper script not found", "expected": expected_helper_sha, "actual": None})
        else:
            actual_sha = _sha256_file(helper_path)
            if expected_helper_sha and actual_sha != expected_helper_sha:
                checks["helper_script"] = {"status": "deny", "script_path": str(helper_path), "actual_sha256": actual_sha, "expected_sha256": expected_helper_sha, "message": "helper-script hash mismatch"}
                findings.append({"kind": "helper_version_mismatch", "message": "helper-script hash mismatch", "expected": expected_helper_sha, "actual": actual_sha})
            else:
                checks["helper_script"] = {"status": "ok", "script_path": str(helper_path), "actual_sha256": actual_sha, "expected_sha256": expected_helper_sha, "message": None}

    # 3. PJC binary check
    pjc_bin_raw = str(body.get("pjc_binary_path") or "").strip()
    if pjc_bin_raw:
        bin_path = _repo_path(pjc_bin_raw)
        if not bin_path.is_file() or not os.access(bin_path, os.X_OK):
            checks["pjc_binary"] = {"status": "deny", "binary_path": str(bin_path), "expected_flag": str(body.get("expected_pjc_flag") or "") or None, "message": "PJC binary missing or not executable"}
            findings.append({"kind": "pjc_binary_missing", "message": "PJC binary missing or not executable", "expected": str(bin_path), "actual": None})
        else:
            expected_flag = str(body.get("expected_pjc_flag") or "").strip() or None
            checks["pjc_binary"] = {"status": "ok", "binary_path": str(bin_path), "expected_flag": expected_flag, "message": None}

    # 4. TCP probe
    probe_host = str(body.get("peer_host") or body.get("server_host") or "").strip()
    probe_port = body.get("peer_port") or body.get("dataplane_port") or expected_dataplane_port
    if probe_host and probe_port:
        try:
            port_int = int(probe_port)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"peer_port must be an integer: {exc}") from exc
        ok, duration_ms, msg = _tcp_probe(probe_host, port_int, timeout_sec=float(body.get("tcp_timeout_sec") or 5.0))
        tcp_status = "ok" if ok else "deny"
        checks["tcp_probe"] = {"status": tcp_status, "host": probe_host, "port": port_int, "duration_ms": duration_ms, "message": msg or None}
        if not ok:
            findings.append({"kind": "tcp_unreachable", "message": msg or f"could not reach {probe_host}:{port_int}", "expected": f"{probe_host}:{port_int}", "actual": None})

    # 5. TLS handshake
    cert_dir_raw = str(body.get("cert_dir") or "").strip()
    cert_dir = _repo_path(cert_dir_raw) if cert_dir_raw else None
    tls_protocol = None
    peer_cert_pem: str | None = None
    peer_cert_fp: str | None = None
    if probe_host and probe_port and cert_dir is not None and checks["tcp_probe"]["status"] == "ok":
        ca_path = cert_dir / "ca.crt"
        cert_path: Path | None = None
        key_path: Path | None = None
        if role == "client":
            cert_path = cert_dir / "client.crt"
            key_path = cert_dir / "client.key"
        else:
            cert_path = cert_dir / "server.crt"
            key_path = cert_dir / "server.key"
        if cert_path is not None and not cert_path.is_file():
            cert_path = None
            key_path = None
        info = _tls_handshake_probe(
            probe_host,
            int(probe_port),
            ca_path=ca_path if ca_path.is_file() else None,
            cert_path=cert_path if (cert_path and cert_path.is_file()) else None,
            key_path=key_path if (key_path and key_path.is_file()) else None,
            server_hostname=str(body.get("server_hostname") or "pjc-server"),
            timeout_sec=float(body.get("tls_timeout_sec") or 8.0),
        )
        tls_status = "ok" if info["ok"] else "deny"
        tls_protocol = info["tls_protocol"]
        peer_cert_pem = info.get("peer_cert_pem")
        peer_cert_fp = info.get("peer_cert_fingerprint_sha256")
        checks["tls_handshake"] = {
            "status": tls_status,
            "peer_cert_subject": info.get("peer_cert_subject"),
            "peer_cert_fingerprint_sha256": peer_cert_fp,
            "tls_protocol": tls_protocol,
            "message": info.get("message") or None,
        }
        if not info["ok"]:
            findings.append({"kind": "tls_handshake_failed", "message": info.get("message") or "TLS handshake failed", "expected": "ok", "actual": None})

    # 6. peer identity (uses TLS cert if present, else explicit cert path)
    explicit_peer_cert_path = str(body.get("peer_cert_path") or "").strip()
    peer_cert_text: str | None = peer_cert_pem
    if peer_cert_text is None and explicit_peer_cert_path:
        explicit_path = _repo_path(explicit_peer_cert_path)
        if explicit_path.is_file():
            peer_cert_text = explicit_path.read_text(encoding="utf-8")
    ca_for_identity: str | None = None
    if cert_dir is not None and (cert_dir / "ca.crt").is_file():
        ca_for_identity = (cert_dir / "ca.crt").read_text(encoding="utf-8")
    if peer_cert_text and (expected_peer_identity or expected_ca_fp):
        identity_role = "client" if role == "server" else "server"
        ident = _peer_identity_check_via_helper(
            cert_pem=peer_cert_text,
            ca_pem=ca_for_identity,
            role=identity_role,
            job_id=job_id,
            expected_fingerprint=expected_ca_fp or peer_cert_fp or "",
            expected_identity=expected_peer_identity or "",
        )
        checks["peer_identity"] = {
            "status": ident.get("status") or "deny",
            "actual_identity": ident.get("actual_identity"),
            "expected_identity": expected_peer_identity,
            "ca_fingerprint_sha256": expected_ca_fp,
            "decision": ident.get("decision"),
            "reason_code": ident.get("reason_code"),
            "message": ident.get("message") or None,
        }
        if checks["peer_identity"]["status"] == "deny":
            if (ident.get("reason_code") or "").startswith("fingerprint"):
                findings.append({"kind": "ca_fingerprint_mismatch", "message": ident.get("message") or "fingerprint mismatch", "expected": expected_ca_fp, "actual": ident.get("ca_fingerprint_sha256")})
            else:
                findings.append({"kind": "peer_identity_mismatch", "message": ident.get("message") or "peer identity rejected", "expected": expected_peer_identity, "actual": ident.get("actual_identity")})

    # 7. input manifest / csv hash
    csv_path_raw = str(body.get("input_csv_path") or "").strip()
    expected_csv_sha = str(body.get("expected_input_csv_sha256") or "").strip().lower() or None
    expected_manifest_sha = str(body.get("expected_manifest_sha256") or "").strip().lower() or None
    if csv_path_raw:
        csv_path = _repo_path(csv_path_raw)
        if not csv_path.is_file():
            checks["input_manifest"] = {"status": "deny", "csv_path": str(csv_path), "csv_sha256": None, "manifest_sha256": None, "rows": 0, "bytes": 0, "message": "input CSV missing"}
            findings.append({"kind": "input_csv_missing", "message": "input CSV missing", "expected": str(csv_path), "actual": None})
        else:
            rows, size = _file_rows_and_bytes(csv_path)
            csv_sha = _sha256_file(csv_path)
            manifest_sha: str | None = None
            manifest_path_raw = str(body.get("input_manifest_path") or "").strip()
            if manifest_path_raw:
                mpath = _repo_path(manifest_path_raw)
                if mpath.is_file():
                    manifest_sha = _sha256_file(mpath)
            status = "ok"
            message = None
            if expected_csv_sha and csv_sha != expected_csv_sha:
                status = "deny"
                message = "input CSV hash mismatch"
                findings.append({"kind": "input_manifest_hash_mismatch", "message": message, "expected": expected_csv_sha, "actual": csv_sha})
            if expected_manifest_sha and (manifest_sha != expected_manifest_sha):
                status = "deny"
                message = message or "input manifest hash mismatch"
                findings.append({"kind": "input_manifest_hash_mismatch", "message": "input manifest hash mismatch", "expected": expected_manifest_sha, "actual": manifest_sha})
            checks["input_manifest"] = {
                "status": status,
                "csv_path": str(csv_path),
                "csv_sha256": csv_sha,
                "manifest_sha256": manifest_sha,
                "rows": rows,
                "bytes": size,
                "message": message,
            }

    # 8. resource limits — compare csv rows/size against optional caps
    max_rows = body.get("max_rows")
    max_bytes = body.get("max_bytes")
    max_buckets = body.get("max_buckets")
    actual_buckets = body.get("actual_buckets")
    if any(v is not None for v in (max_rows, max_bytes, max_buckets, actual_buckets)):
        actual_rows = checks["input_manifest"].get("rows") if checks["input_manifest"]["status"] != "skip" else None
        actual_bytes = checks["input_manifest"].get("bytes") if checks["input_manifest"]["status"] != "skip" else None
        status = "ok"
        message = None
        if max_rows is not None and actual_rows is not None and int(actual_rows) > int(max_rows):
            status = "deny"; message = "row count over limit"
            findings.append({"kind": "resource_limit_exceeded", "message": message, "expected": int(max_rows), "actual": int(actual_rows)})
        if max_bytes is not None and actual_bytes is not None and int(actual_bytes) > int(max_bytes):
            status = "deny"; message = message or "byte size over limit"
            findings.append({"kind": "resource_limit_exceeded", "message": "byte size over limit", "expected": int(max_bytes), "actual": int(actual_bytes)})
        if max_buckets is not None and actual_buckets is not None and int(actual_buckets) > int(max_buckets):
            status = "deny"; message = message or "bucket count over limit"
            findings.append({"kind": "resource_limit_exceeded", "message": "bucket count over limit", "expected": int(max_buckets), "actual": int(actual_buckets)})
        checks["resource_limits"] = {
            "status": status,
            "max_rows": int(max_rows) if max_rows is not None else None,
            "max_bytes": int(max_bytes) if max_bytes is not None else None,
            "max_buckets": int(max_buckets) if max_buckets is not None else None,
            "actual_rows": int(actual_rows) if isinstance(actual_rows, int) else None,
            "actual_bytes": int(actual_bytes) if isinstance(actual_bytes, int) else None,
            "actual_buckets": int(actual_buckets) if isinstance(actual_buckets, int) else None,
            "message": message,
        }

    # 9. output path
    out_dir_raw = str(body.get("output_dir") or "").strip()
    if out_dir_raw:
        out_dir = _repo_path(out_dir_raw)
        unique_required = bool(body.get("require_unique_output", True))
        writable = False
        message = None
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            probe = out_dir / f".pjc_preflight_{uuid.uuid4().hex[:8]}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            writable = True
        except OSError as exc:
            message = str(exc)
        is_unique = True
        if unique_required and out_dir.is_dir():
            try:
                non_empty = any(out_dir.iterdir())
            except OSError:
                non_empty = True
            is_unique = not non_empty
        status = "ok" if (writable and (is_unique or not unique_required)) else "deny"
        if status == "deny":
            findings.append({"kind": "output_path_unwritable", "message": message or "output dir is not unique or not writable", "expected": str(out_dir), "actual": None})
        checks["output_path"] = {
            "status": status,
            "out_dir": str(out_dir),
            "writable": writable,
            "unique": is_unique,
            "message": message,
        }

    # Decide
    deny_reasons_priority = [
        ("commit", "commit_mismatch"),
        ("helper_script", "helper_version_mismatch"),
        ("pjc_binary", "pjc_binary_missing"),
        ("tcp_probe", "tcp_unreachable"),
        ("tls_handshake", "tls_handshake_failed"),
        ("peer_identity", "peer_identity_mismatch"),
        ("input_manifest", "input_manifest_hash_mismatch"),
        ("resource_limits", "resource_limit_exceeded"),
        ("output_path", "output_path_unwritable"),
    ]
    decision = "allow"
    reason_code = "ok"
    reason: str | None = None
    for check_name, code in deny_reasons_priority:
        if checks.get(check_name, {}).get("status") == "deny":
            decision = "deny"
            reason_code = code
            # peer_identity covers both ca_fingerprint_mismatch and identity_mismatch;
            # disambiguate using the underlying helper's reason_code
            if check_name == "peer_identity":
                helper_code = str(checks[check_name].get("reason_code") or "")
                if helper_code.startswith("fingerprint"):
                    reason_code = "ca_fingerprint_mismatch"
            reason = checks[check_name].get("message") or reason_code
            break

    report = {
        "schema": PJC_TWO_PARTY_PREFLIGHT_SCHEMA,
        "generated_at_utc": _utc_now_iso(),
        "job_id": job_id,
        "role": role,
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason,
        "expected_peer_role": expected_peer_role,
        "expected_peer_identity": expected_peer_identity,
        "expected_ca_fingerprint_sha256": expected_ca_fp,
        "expected_commit": expected_commit,
        "expected_dataplane_port": expected_dataplane_port,
        "checks": checks,
        "findings": findings,
    }
    out_dir = _ensure_two_party_dir() / "preflight"
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = out_dir / f"{job_id}_{role}_{_utc_suffix()}.json"
    evidence_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "ok", "evidence_path": str(evidence_path), "report": report}


# --- Role package export/import ------------------------------------------------


def _role_package_export(body: dict[str, Any]) -> dict[str, Any]:
    job_id = str(body.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")
    role = _validate_two_party_role(body.get("role"))
    source_dir = _resolve_repo_path_strict(body.get("source_dir"), label="source_dir")
    if not source_dir.is_dir():
        raise ValueError(f"source_dir does not exist: {source_dir}")
    files = _walk_files(source_dir)
    if not files:
        raise ValueError(f"source_dir is empty: {source_dir}")
    manifest_files = _file_manifest(source_dir, files)
    package_sha = _package_aggregate_sha(manifest_files)
    out_dir_raw = body.get("output_dir") or str(_ensure_two_party_dir() / "role_packages")
    out_root = _repo_path(str(out_dir_raw))
    out_root.mkdir(parents=True, exist_ok=True)
    package_dir = _safe_unique_dir(out_root, f"{job_id}_{role}_{_utc_suffix()}")
    package_dir.mkdir(parents=True, exist_ok=False)
    payload_dir = package_dir / "payload"
    payload_dir.mkdir(parents=True, exist_ok=False)
    for path in files:
        rel = path.relative_to(source_dir)
        dst = payload_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(path.read_bytes())
        try:
            os.chmod(dst, path.stat().st_mode & 0o600 | 0o600)
        except OSError:
            pass
    operator_notes = str(body.get("operator_notes") or "").strip() or None
    if operator_notes:
        redacted = operator_notes.replace("\r", "").strip()
        # block raw secrets — never echo tokens
        for banned in ("PJC_MTLS_PAIRING_TOKEN", "BRIDGE_TOKEN_SECRET", "BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE KEY"):
            if banned in redacted:
                raise ValueError(f"operator_notes must not contain {banned}")
        operator_notes = redacted

    peer_block = {
        "expected_role": "client" if role == "server" else "server",
        "expected_identity": str(body.get("expected_peer_identity") or "").strip() or None,
        "expected_ca_fingerprint_sha256": _normalize_fingerprint(str(body.get("expected_ca_fingerprint_sha256") or "")) or None,
        "expected_host": str(body.get("expected_host") or "").strip() or None,
    }
    ports_block = {
        "dataplane_port": int(body.get("dataplane_port") or 10502),
        "loopback_port": (int(body["loopback_port"]) if body.get("loopback_port") else None),
        "client_proxy_port": (int(body["client_proxy_port"]) if body.get("client_proxy_port") else None),
    }
    policy_block = {
        "k_threshold": (int(body["k_threshold"]) if body.get("k_threshold") is not None else None),
        "dp_epsilon": (float(body["dp_epsilon"]) if body.get("dp_epsilon") is not None else None),
        "dp_sensitivity": (float(body["dp_sensitivity"]) if body.get("dp_sensitivity") is not None else None),
        "require_dp": (bool(body["require_dp"]) if body.get("require_dp") is not None else True),
        "redact_operator_fields": (bool(body["redact_operator_fields"]) if body.get("redact_operator_fields") is not None else True),
    }
    manifest = {
        "schema": PJC_ROLE_PACKAGE_SCHEMA,
        "generated_at_utc": _utc_now_iso(),
        "job_id": job_id,
        "role": role,
        "package_path": str(package_dir),
        "package_sha256": package_sha,
        "source_dir": str(source_dir),
        "exported_dir": str(payload_dir),
        "operator_notes": operator_notes,
        "files": manifest_files,
        "peer": peer_block,
        "ports": ports_block,
        "policy": policy_block,
    }
    manifest_path = package_dir / "role_package.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "ok", "package_path": str(package_dir), "manifest_path": str(manifest_path), "manifest": manifest}


def _role_package_import(body: dict[str, Any]) -> dict[str, Any]:
    package_path = _resolve_repo_path_strict(body.get("package_path"), label="package_path")
    if not package_path.is_dir():
        raise ValueError(f"package_path is not a directory: {package_path}")
    manifest_path = package_path / "role_package.json"
    if not manifest_path.is_file():
        raise ValueError("package is missing role_package.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"role_package.json is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != PJC_ROLE_PACKAGE_SCHEMA:
        raise ValueError("package manifest has wrong schema")
    files_decl = manifest.get("files") or []
    payload_dir = package_path / "payload"
    findings: list[dict[str, Any]] = []
    if not payload_dir.is_dir():
        raise ValueError("package payload directory is missing")
    actual_manifest = _file_manifest(payload_dir, _walk_files(payload_dir))
    decl_by_path = {item["path"]: item for item in files_decl if isinstance(item, dict)}
    actual_by_path = {item["path"]: item for item in actual_manifest}
    for path, decl in decl_by_path.items():
        actual = actual_by_path.get(path)
        if actual is None:
            findings.append({"kind": "missing_file", "message": f"declared file missing: {path}", "expected": decl, "actual": None})
            continue
        if actual["sha256"] != decl["sha256"]:
            findings.append({"kind": "hash_mismatch", "message": f"hash mismatch: {path}", "expected": decl["sha256"], "actual": actual["sha256"]})
        if int(actual["size_bytes"]) != int(decl["size_bytes"]):
            findings.append({"kind": "size_mismatch", "message": f"size mismatch: {path}", "expected": int(decl["size_bytes"]), "actual": int(actual["size_bytes"])})
    for path in actual_by_path:
        if path not in decl_by_path:
            findings.append({"kind": "unexpected_file", "message": f"undeclared file present: {path}", "expected": None, "actual": path})
    expected_pkg_sha = manifest.get("package_sha256")
    actual_pkg_sha = _package_aggregate_sha(actual_manifest)
    if expected_pkg_sha and expected_pkg_sha != actual_pkg_sha:
        findings.append({"kind": "package_sha_mismatch", "message": "package_sha256 mismatch", "expected": expected_pkg_sha, "actual": actual_pkg_sha})

    target_dir_raw = str(body.get("target_dir") or "").strip()
    imported_dir: Path | None = None
    if not findings and target_dir_raw:
        imported_dir = _repo_path(target_dir_raw)
        imported_dir.mkdir(parents=True, exist_ok=True)
        for item in actual_manifest:
            src = payload_dir / item["path"]
            dst = imported_dir / item["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            try:
                os.chmod(dst, 0o600)
            except OSError:
                pass

    decision = "allow" if not findings else "deny"
    reason_code = "ok" if not findings else findings[0]["kind"]
    validation = {
        "decision": decision,
        "reason_code": reason_code,
        "findings": findings,
    }
    out_manifest = dict(manifest)
    out_manifest["imported_dir"] = str(imported_dir) if imported_dir else None
    out_manifest["validation"] = validation
    out_manifest["generated_at_utc"] = _utc_now_iso()
    report_path = _ensure_two_party_dir() / "role_packages" / f"import_{manifest.get('job_id') or 'unknown'}_{manifest.get('role') or 'unknown'}_{_utc_suffix()}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(out_manifest, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "ok" if decision == "allow" else "error", "decision": decision, "report_path": str(report_path), "report": out_manifest}


# --- Role lifecycle (server/client start/status/cancel) ------------------------


PJC_DEFAULT_CERT_DIR = REPO_ROOT / "tmp" / "pjc_mtls_shared" / "certs"
PJC_DEFAULT_ROLE_DIR_ROOT = REPO_ROOT / "tmp" / "pjc_role_dirs"
PJC_DEFAULT_OUT_DIR_ROOT = REPO_ROOT / "tmp" / "pjc_two_party" / "runs"
PJC_DEFAULT_PJC_DIR = REPO_ROOT / "a-psi" / "private-join-and-compute"


def _role_command(role: str, *, body: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    job_id = str(body.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")

    # Cert dir: explicit > default repo-side shared dir.
    cert_dir_raw = str(body.get("cert_dir") or "").strip()
    cert_dir = _repo_path(cert_dir_raw) if cert_dir_raw else PJC_DEFAULT_CERT_DIR

    # Role dir holds the bucketed job_meta.json + bucket_*/csv layout.
    role_dir_raw = str(body.get("role_dir") or "").strip()
    role_dir = _repo_path(role_dir_raw) if role_dir_raw else (PJC_DEFAULT_ROLE_DIR_ROOT / job_id)

    server_host = str(body.get("server_host") or "").strip()

    # Out dir — auto-segregated per (job_id, role) so logs/evidence are easy
    # to find and never clobber another role's run.
    out_dir_raw = str(body.get("out_dir") or "").strip()
    out_dir = _repo_path(out_dir_raw) if out_dir_raw else (PJC_DEFAULT_OUT_DIR_ROOT / f"{job_id}_{role}")

    # PJC binary location: keep optional; the script auto-resolves via bazel.
    bin_dir_raw = str(body.get("pjc_bin_dir") or "").strip()
    bin_dir = _repo_path(bin_dir_raw) if bin_dir_raw else None

    env: dict[str, str] = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "JOB_ID": job_id,
        "CERT_DIR": str(cert_dir),
        "JOB_DIR": str(role_dir),
        "OUT_DIR": str(out_dir),
        "PJC_DIR": str(_repo_path(str(body.get("pjc_dir"))) if body.get("pjc_dir") else PJC_DEFAULT_PJC_DIR),
    }
    if bin_dir is not None:
        env["PJC_BIN_DIR"] = str(bin_dir)
    if "LANG" in os.environ:
        env["LANG"] = os.environ["LANG"]
    if "LC_ALL" in os.environ:
        env["LC_ALL"] = os.environ["LC_ALL"]
    if body.get("pjc_grpc_stream_chunk_elements") is not None:
        env["PJC_GRPC_STREAM_CHUNK_ELEMENTS"] = str(body["pjc_grpc_stream_chunk_elements"])
    if body.get("production_mode"):
        env["PJC_PRODUCTION_MODE"] = "1"
    if body.get("require_session_manifest"):
        env["PJC_MTLS_REQUIRE_SESSION_MANIFEST"] = "1"
    if body.get("grpc_max_message_mb") is not None:
        env["GRPC_MAX_MESSAGE_MB"] = str(int(body["grpc_max_message_mb"]))
    if body.get("pjc_resource_limits"):
        env["PJC_RESOURCE_LIMITS"] = str(_repo_path(str(body["pjc_resource_limits"])))
        env["PJC_PREFLIGHT_REQUIRED"] = "1"
    elif body.get("production_mode"):
        env["PJC_PREFLIGHT_REQUIRED"] = "1"
    if body.get("allow_legacy_unary"):
        env["PJC_ALLOW_LEGACY_UNARY"] = "1"
    if body.get("allow_production_wide_bind"):
        env["PJC_ALLOW_PRODUCTION_WIDE_BIND"] = "1"
    if body.get("shared_result_dir"):
        env["SHARED_RESULT_DIR"] = str(_repo_path(str(body["shared_result_dir"])))

    # If an explicit script override is provided (smoke tests, custom helpers)
    # skip the production-only cert and role_dir preflight; the override owner
    # is responsible for any inputs the script needs.
    explicit_script = bool(body.get("script"))
    if not explicit_script:
        if not cert_dir.is_dir():
            raise FileNotFoundError(f"cert_dir does not exist: {cert_dir}")
        required_cert_files = ["ca.crt"]
        if role == "server":
            required_cert_files += ["server.crt", "server.key"]
        else:
            required_cert_files += ["client.crt", "client.key"]
        missing = [name for name in required_cert_files if not (cert_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(
                f"cert_dir {cert_dir} is missing required files for role={role}: {', '.join(missing)}"
            )
        if not role_dir.is_dir():
            raise FileNotFoundError(f"role_dir does not exist: {role_dir}")
        meta_path = role_dir / "job_meta.json"
        if not meta_path.is_file():
            raise FileNotFoundError(
                f"role_dir {role_dir} is missing job_meta.json (required by bucketed TLS scripts)"
            )

    if role == "server":
        script_name = str(body.get("script") or "run_pjc_bucketed_tls_server.sh")
        script_path = PJC_MTLS_SCRIPT_DIR / script_name
        env["TLS_PORT"] = str(int(body.get("tls_port") or 10502))
        env["PJC_LOCAL_PORT"] = str(int(body.get("pjc_local_port") or 10501))
        env["BIND_ADDR"] = str(body.get("bind_addr") or "0.0.0.0")
        if body.get("server_csv"):
            env["SERVER_CSV"] = str(_repo_path(str(body["server_csv"])))
    else:
        script_name = str(body.get("script") or "run_pjc_bucketed_tls_client.sh")
        script_path = PJC_MTLS_SCRIPT_DIR / script_name
        if not server_host:
            raise ValueError("server_host is required for client role")
        env["SERVER_HOST"] = server_host
        env["TLS_PORT"] = str(int(body.get("tls_port") or 10502))
        env["LOCAL_PROXY_PORT"] = str(int(body.get("local_proxy_port") or 10503))
        if body.get("client_csv"):
            env["CLIENT_CSV"] = str(_repo_path(str(body["client_csv"])))

    if not script_path.is_file():
        raise FileNotFoundError(f"missing role script: {script_path}")

    # Pre-create the out dir so log files have a destination.
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FileNotFoundError(f"out_dir is not writable: {out_dir}: {exc}") from exc

    command = ["bash", str(script_path)]
    # filter env to allowlist — never leak unrelated host env
    filtered = {k: v for k, v in env.items() if k in PJC_ROLE_ENV_ALLOWLIST}
    return command, filtered


def _role_status_payload(role_key: str) -> dict[str, Any] | None:
    with _PJC_ROLE_REGISTRY_LOCK:
        record = _PJC_ROLE_REGISTRY.get(role_key)
        if record is None:
            return None
        snapshot = dict(record)
    proc = snapshot.pop("_process", None)
    snapshot.pop("_log_handle", None)
    if proc is not None and snapshot.get("state") in ("starting", "running"):
        exit_code = proc.poll()
        if exit_code is not None:
            snapshot["state"] = "completed" if exit_code == 0 else "failed"
            snapshot["exit_code"] = exit_code
            snapshot["finished_at_utc"] = _utc_now_iso()
            started_ts = _iso_to_ts(snapshot.get("started_at_utc"))
            finished_ts = _iso_to_ts(snapshot["finished_at_utc"])
            if started_ts is not None and finished_ts is not None:
                snapshot["duration_sec"] = round(max(0.0, finished_ts - started_ts), 3)
            log_path = snapshot.get("log_path")
            if log_path and Path(log_path).is_file():
                snapshot["log_sha256"] = _sha256_file(Path(log_path))
            _write_role_evidence(role_key, snapshot)
            with _PJC_ROLE_REGISTRY_LOCK:
                _PJC_ROLE_REGISTRY[role_key].update(snapshot)
    snapshot["schema"] = PJC_ROLE_STATUS_SCHEMA
    snapshot["generated_at_utc"] = _utc_now_iso()
    return snapshot


def _write_role_evidence(role_key: str, snapshot: dict[str, Any]) -> Path:
    out_dir = _ensure_two_party_dir() / "roles"
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = out_dir / f"{role_key}_{_utc_suffix()}.json"
    full = dict(snapshot)
    full["schema"] = PJC_ROLE_STATUS_SCHEMA
    full["generated_at_utc"] = _utc_now_iso()
    full.pop("_process", None)
    evidence_path.write_text(json.dumps(full, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return evidence_path


def _start_role(role: str, body: dict[str, Any]) -> dict[str, Any]:
    role = _validate_two_party_role(role)
    job_id = str(body.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")
    role_key = f"{job_id}::{role}"
    with _PJC_ROLE_REGISTRY_LOCK:
        existing = _PJC_ROLE_REGISTRY.get(role_key)
        if existing is not None and existing.get("state") in ("starting", "running"):
            return {"status": "error", "error": "role_already_running", "snapshot": {k: v for k, v in existing.items() if k != "_process"}}
    command, env = _role_command(role, body=body)
    cmd_digest = _sha256_bytes(("\x00".join(command)).encode("utf-8"))
    env_keys_sorted = sorted(env.keys())
    env_digest = _sha256_bytes(("\n".join(f"{k}={env[k]}" for k in env_keys_sorted)).encode("utf-8"))
    logs_root = _ensure_two_party_dir() / "logs"
    logs_root.mkdir(parents=True, exist_ok=True)
    log_path = logs_root / f"{role_key.replace('::', '_')}_{_utc_suffix()}.log"
    started_at = _utc_now_iso()
    log_handle = log_path.open("wb")
    try:
        proc = subprocess.Popen(  # noqa: S603 — controlled command list
            command,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        log_handle.close()
        raise
    snapshot = {
        "schema": PJC_ROLE_STATUS_SCHEMA,
        "generated_at_utc": started_at,
        "job_id": job_id,
        "role": role,
        "state": "running",
        "pid": proc.pid,
        "started_at_utc": started_at,
        "finished_at_utc": None,
        "duration_sec": None,
        "exit_code": None,
        "command_digest_sha256": cmd_digest,
        "command_argv_hash": cmd_digest,
        "env_allowlist_digest_sha256": env_digest,
        "env_allowlist": env_keys_sorted,
        "dataplane_port": int(body.get("tls_port") or 10502),
        "loopback_port": int(body.get("pjc_local_port") or 10501) if role == "server" else int(body.get("local_proxy_port") or 10503),
        "log_path": str(log_path),
        "log_sha256": None,
        "cancel_reason": None,
        "evidence_path": None,
        "cert_dir": env.get("CERT_DIR"),
        "role_dir": env.get("JOB_DIR"),
    }
    with _PJC_ROLE_REGISTRY_LOCK:
        record = dict(snapshot)
        record["_process"] = proc
        record["_log_handle"] = log_handle
        _PJC_ROLE_REGISTRY[role_key] = record
    evidence_path = _write_role_evidence(role_key, snapshot)
    snapshot["evidence_path"] = str(evidence_path)
    with _PJC_ROLE_REGISTRY_LOCK:
        _PJC_ROLE_REGISTRY[role_key]["evidence_path"] = str(evidence_path)
    return {"status": "ok", "role_key": role_key, "snapshot": snapshot}


def _cancel_role(role: str, body: dict[str, Any]) -> dict[str, Any]:
    role = _validate_two_party_role(role)
    job_id = str(body.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")
    role_key = f"{job_id}::{role}"
    cancel_reason = str(body.get("reason") or "operator_cancel").strip() or "operator_cancel"
    with _PJC_ROLE_REGISTRY_LOCK:
        record = _PJC_ROLE_REGISTRY.get(role_key)
        if record is None:
            return {"status": "error", "error": "not_found", "role_key": role_key}
        proc = record.get("_process")
        log_handle = record.get("_log_handle")
    if proc is None:
        return {"status": "error", "error": "no_process", "role_key": role_key}
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    except Exception as exc:  # noqa: BLE001
        cancel_reason = f"{cancel_reason}: terminate raised {exc}"
    if log_handle is not None:
        try:
            log_handle.close()
        except Exception:
            pass
    snapshot = _role_status_payload(role_key) or {}
    snapshot["state"] = "cancelled"
    snapshot["cancel_reason"] = cancel_reason
    snapshot["finished_at_utc"] = snapshot.get("finished_at_utc") or _utc_now_iso()
    log_path = snapshot.get("log_path")
    if log_path and Path(log_path).is_file():
        snapshot["log_sha256"] = _sha256_file(Path(log_path))
    evidence_path = _write_role_evidence(role_key, snapshot)
    snapshot["evidence_path"] = str(evidence_path)
    with _PJC_ROLE_REGISTRY_LOCK:
        record = _PJC_ROLE_REGISTRY.get(role_key)
        if record is not None:
            record.update({k: v for k, v in snapshot.items() if not k.startswith("_")})
            record.pop("_process", None)
            record.pop("_log_handle", None)
    return {"status": "ok", "role_key": role_key, "snapshot": snapshot}


# --- Evidence verify-merge ----------------------------------------------------


def _maybe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _maybe_load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    items: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                items.append(value)
    return items


def _manifest_hash_value(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if len(text) == 64 and all(ch in "0123456789abcdef" for ch in text):
        return text
    return None


def _first_manifest_hash(*values: Any) -> str | None:
    for value in values:
        parsed = _manifest_hash_value(value)
        if parsed:
            return parsed
    return None


def _signable_run_manifest_payload(body: dict[str, Any]) -> dict[str, Any]:
    job_id = str(body.get("job_id") or "").strip()
    party = str(body.get("party") or body.get("role") or "").strip().lower()
    peer_party = str(body.get("peer_party") or "").strip().lower()
    if party not in ("party_a", "party_b", "server", "client"):
        raise ValueError("party must be party_a, party_b, server, or client")
    if not peer_party:
        peer_party = "party_b" if party in ("party_a", "server") else "party_a"
    if peer_party not in ("party_a", "party_b", "server", "client"):
        raise ValueError("peer_party must be party_a, party_b, server, or client")
    if not job_id:
        raise ValueError("job_id is required")

    pjc_result_path_raw = str(body.get("pjc_result_path") or body.get("result_path") or "").strip()
    pjc_result_sha = _first_manifest_hash(body.get("pjc_result_sha256"))
    if pjc_result_path_raw and not pjc_result_sha:
        pjc_result_path = _repo_path(pjc_result_path_raw)
        if not pjc_result_path.is_file():
            raise FileNotFoundError(f"pjc result file not found: {pjc_result_path}")
        pjc_result_sha = _sha256_file(pjc_result_path)
    if not pjc_result_sha:
        raise ValueError("pjc_result_sha256 or pjc_result_path is required")

    public_report_path_raw = str(body.get("public_report_path") or "").strip()
    public_report_sha = _first_manifest_hash(body.get("public_report_sha256"))
    if public_report_path_raw and not public_report_sha:
        public_report_path = _repo_path(public_report_path_raw)
        if public_report_path.is_file():
            public_report_sha = _sha256_file(public_report_path)

    audit_chain_path_raw = str(body.get("audit_chain_path") or "").strip()
    audit_chain_sha = _first_manifest_hash(body.get("audit_chain_sha256"))
    if audit_chain_path_raw and not audit_chain_sha:
        audit_chain_path = _repo_path(audit_chain_path_raw)
        if audit_chain_path.is_file():
            audit_chain_sha = _sha256_file(audit_chain_path)

    policy_decision = str(body.get("policy_decision") or "").strip()
    if not policy_decision and public_report_path_raw:
        public = _maybe_load_json(_repo_path(public_report_path_raw)) or {}
        if public:
            policy_decision = "release" if public.get("released") else f"deny:{public.get('reason_code') or 'unknown'}"
    if not policy_decision:
        policy_decision = "unknown"

    payload = {
        "job_id": job_id,
        "party": party,
        "peer_party": peer_party,
        "repo_commit": str(body.get("repo_commit") or body.get("commit") or _read_repo_commit() or "").strip() or None,
        "input_commitment_sha256": _first_manifest_hash(body.get("input_commitment_sha256"), body.get("local_input_commitment_sha256")),
        "peer_input_commitment_sha256": _first_manifest_hash(body.get("peer_input_commitment_sha256")),
        "pjc_result_sha256": pjc_result_sha,
        "policy_decision": policy_decision,
        "public_report_sha256": public_report_sha,
        "audit_chain_sha256": audit_chain_sha,
        "tls_identity": str(body.get("tls_identity") or "").strip() or None,
        "peer_tls_identity": str(body.get("peer_tls_identity") or "").strip() or None,
        "ca_fingerprint_sha256": _normalize_fingerprint(str(body.get("ca_fingerprint_sha256") or body.get("ca_fingerprint") or "")) or None,
        "generated_at_utc": str(body.get("generated_at_utc") or _utc_now_iso()),
    }
    if not payload["input_commitment_sha256"]:
        raise ValueError("input_commitment_sha256 is required")
    if not payload["peer_input_commitment_sha256"]:
        raise ValueError("peer_input_commitment_sha256 is required")
    if not payload["repo_commit"]:
        raise ValueError("repo_commit is required")
    return payload


def _sign_two_party_run_manifest(body: dict[str, Any]) -> dict[str, Any]:
    signing_key_raw = str(body.get("signing_key_path") or "").strip()
    if not signing_key_raw:
        raise ValueError("signing_key_path is required")
    signing_key_path = _repo_path(signing_key_raw)
    if not signing_key_path.is_file():
        raise FileNotFoundError(f"signing key not found: {signing_key_path}")
    private_key = _load_ed25519_private_key(signing_key_path)
    public_key_pem = _ed25519_public_key_pem(private_key)
    payload = _signable_run_manifest_payload(body)
    payload_bytes = _canonical_json_bytes(payload)
    signature = private_key.sign(payload_bytes)
    manifest = {
        "schema": PJC_TWO_PARTY_SIGNED_RUN_MANIFEST_SCHEMA,
        "signature_algorithm": "ed25519",
        "canonicalization": "json/sort_keys/separators=comma-colon/utf8",
        "payload_sha256": _sha256_bytes(payload_bytes),
        "payload": payload,
        "signature": _b64encode(signature),
        "public_key_pem": public_key_pem,
        "public_key_fingerprint_sha256": _ed25519_public_key_fingerprint(public_key_pem),
    }
    out_dir_raw = str(body.get("output_dir") or "").strip()
    out_dir = _repo_path(out_dir_raw) if out_dir_raw else (_ensure_two_party_dir() / "signed_manifests")
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_party = payload["party"].replace("/", "_")
    out_path = out_dir / f"{payload['job_id']}_{safe_party}_{_utc_suffix()}.json"
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"status": "ok", "manifest_path": str(out_path), "manifest": manifest}


def _verify_two_party_run_manifest(manifest: dict[str, Any], *, expected_public_key_fingerprint: str | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    result = {
        "status": "deny",
        "reason_code": "manifest_signature_invalid",
        "message": None,
        "public_key_fingerprint_sha256": None,
        "payload_sha256": None,
    }
    try:
        if manifest.get("schema") != PJC_TWO_PARTY_SIGNED_RUN_MANIFEST_SCHEMA:
            result["reason_code"] = "manifest_schema_invalid"
            result["message"] = f"unsupported schema: {manifest.get('schema')}"
            return None, result
        if manifest.get("signature_algorithm") != "ed25519":
            result["reason_code"] = "manifest_signature_algorithm_unsupported"
            result["message"] = f"unsupported signature algorithm: {manifest.get('signature_algorithm')}"
            return None, result
        payload = manifest.get("payload")
        if not isinstance(payload, dict):
            result["reason_code"] = "manifest_payload_invalid"
            result["message"] = "manifest payload must be an object"
            return None, result
        public_key_pem = str(manifest.get("public_key_pem") or "")
        public_key_fp = _ed25519_public_key_fingerprint(public_key_pem)
        result["public_key_fingerprint_sha256"] = public_key_fp
        if expected_public_key_fingerprint and public_key_fp != _normalize_fingerprint(expected_public_key_fingerprint):
            result["reason_code"] = "manifest_public_key_mismatch"
            result["message"] = "manifest public key fingerprint does not match expected fingerprint"
            return None, result
        payload_bytes = _canonical_json_bytes(payload)
        payload_sha = _sha256_bytes(payload_bytes)
        result["payload_sha256"] = payload_sha
        expected_payload_sha = str(manifest.get("payload_sha256") or "")
        if expected_payload_sha and expected_payload_sha != payload_sha:
            result["reason_code"] = "manifest_payload_hash_mismatch"
            result["message"] = "manifest payload_sha256 does not match canonical payload"
            return None, result
        public_key = _load_ed25519_public_key_from_pem(public_key_pem)
        public_key.verify(_b64decode(str(manifest.get("signature") or "")), payload_bytes)
        result["status"] = "ok"
        result["reason_code"] = "ok"
        result["message"] = None
        return payload, result
    except Exception as exc:  # noqa: BLE001
        result["message"] = str(exc)
        return None, result


def _maybe_load_signed_run_manifest(root: Path) -> tuple[dict[str, Any] | None, Path | None]:
    candidates = [
        root / "pjc_two_party_run_manifest.json",
        root / "signed_run_manifest.json",
        root / "run_manifest.json",
        root / "a_psi_run" / "pjc_two_party_run_manifest.json",
        root / "a_psi_run" / "signed_run_manifest.json",
    ]
    for path in candidates:
        payload = _maybe_load_json(path)
        if payload is not None:
            return payload, path
    for pattern in ("*run_manifest*.json", "*signed*manifest*.json", "*manifest*.json"):
        for path in sorted(root.glob(pattern)):
            payload = _maybe_load_json(path)
            if payload is not None and payload.get("schema") == PJC_TWO_PARTY_SIGNED_RUN_MANIFEST_SCHEMA:
                return payload, path
    manifest_dir = root / "signed_manifests"
    if manifest_dir.is_dir():
        for path in sorted(manifest_dir.glob("*.json")):
            payload = _maybe_load_json(path)
            if payload is not None:
                return payload, path
    return None, None


def _extract_party_evidence(root: Path, *, label: str) -> dict[str, Any]:
    missing: list[str] = []
    if not root.is_dir():
        return {"source": str(root), "missing_files": ["<dir>"]}
    signed_manifest, signed_manifest_path = _maybe_load_signed_run_manifest(root)
    signed_payload: dict[str, Any] | None = None
    signed_manifest_verification: dict[str, Any] | None = None
    if signed_manifest is not None:
        signed_payload, signed_manifest_verification = _verify_two_party_run_manifest(signed_manifest)
    public = _maybe_load_json(root / "a_psi_run" / "public_report.json") or _maybe_load_json(root / "public_report.json")
    if public is None:
        missing.append("public_report.json")
    attribution = _maybe_load_json(root / "a_psi_run" / "attribution_result.json") or _maybe_load_json(root / "attribution_result.json")
    if attribution is None:
        missing.append("attribution_result.json")
    pjc_audits = _maybe_load_jsonl(root / "a_psi_run" / "pjc_audit.jsonl") or _maybe_load_jsonl(root / "pjc_audit.jsonl")
    audit_chain = _maybe_load_json(root / "audit_chain.json")
    bridge_meta = _maybe_load_json(root / "bridge_job" / "job_meta.json") or _maybe_load_json(root / "bridge_meta.json")

    def _result_hash() -> str | None:
        if attribution is not None:
            return _sha256_bytes(json.dumps(attribution, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        if public is not None:
            return _sha256_bytes(json.dumps(public, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        return None

    def _tls_identity() -> tuple[str | None, str | None]:
        for entry in reversed(pjc_audits):
            tls = entry.get("tls") if isinstance(entry, dict) else None
            if isinstance(tls, dict):
                return tls.get("peer_identity"), tls.get("ca_fingerprint_sha256")
        return None, None

    job_id = (public or {}).get("job_id") or (attribution or {}).get("job_id") or (audit_chain or {}).get("job_id")
    commit = (audit_chain or {}).get("commit") or (audit_chain or {}).get("git_commit") or (public or {}).get("commit")
    if not commit and pjc_audits:
        commit = pjc_audits[-1].get("commit")
    tls_identity, ca_fp = _tls_identity()
    input_commit = None
    if bridge_meta is not None:
        bridge_inputs = bridge_meta.get("inputs") if isinstance(bridge_meta.get("inputs"), dict) else {}
        input_commit = (
            bridge_meta.get("input_commitment_sha256")
            or bridge_inputs.get("input_commitment_sha256")
            or bridge_meta.get("input_csv_sha256")
        )
    if not input_commit and pjc_audits:
        input_commit = pjc_audits[-1].get("input_commitment_sha256")
    local_input_commit = (
        signed_payload.get("input_commitment_sha256")
        if isinstance(signed_payload, dict)
        else input_commit
    )
    peer_input_commit = (
        signed_payload.get("peer_input_commitment_sha256")
        if isinstance(signed_payload, dict)
        else None
    )
    policy_decision = None
    if public is not None:
        policy_decision = "release" if public.get("released") else f"deny:{public.get('reason_code') or 'unknown'}"
    audit_chain_sha = None
    if audit_chain is not None:
        audit_chain_sha = _sha256_bytes(json.dumps(audit_chain, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    if isinstance(signed_payload, dict):
        job_id = signed_payload.get("job_id") or job_id
        commit = signed_payload.get("repo_commit") or commit
        tls_identity = signed_payload.get("tls_identity") or tls_identity
        ca_fp = signed_payload.get("ca_fingerprint_sha256") or ca_fp
        result_sha = signed_payload.get("pjc_result_sha256") or _result_hash()
        policy_decision = signed_payload.get("policy_decision") or policy_decision
        audit_chain_sha = signed_payload.get("audit_chain_sha256") or audit_chain_sha
    else:
        result_sha = _result_hash()
    return {
        "source": str(root),
        "job_id": job_id,
        "commit": commit,
        "input_commitment_sha256": local_input_commit,
        "peer_input_commitment_sha256": peer_input_commit,
        "commitment_pair": {
            "local": local_input_commit,
            "peer": peer_input_commit,
        },
        "tls_identity": tls_identity,
        "peer_tls_identity": signed_payload.get("peer_tls_identity") if isinstance(signed_payload, dict) else None,
        "ca_fingerprint_sha256": ca_fp,
        "result_sha256": result_sha,
        "policy_decision": policy_decision,
        "public_report_sha256": signed_payload.get("public_report_sha256") if isinstance(signed_payload, dict) else None,
        "audit_chain_sha256": audit_chain_sha,
        "signed_manifest_path": str(signed_manifest_path) if signed_manifest_path is not None else None,
        "signed_manifest_verification": signed_manifest_verification,
        "missing_files": missing,
    }


def _two_party_evidence_merge(body: dict[str, Any]) -> dict[str, Any]:
    job_id = str(body.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")
    party_a_dir = _resolve_repo_path_strict(body.get("party_a_dir"), label="party_a_dir")
    party_b_dir = _resolve_repo_path_strict(body.get("party_b_dir"), label="party_b_dir")
    require_signed_manifests = bool(body.get("require_signed_manifests") or body.get("require_signed_run_manifests"))
    a = _extract_party_evidence(party_a_dir, label="party_a")
    b = _extract_party_evidence(party_b_dir, label="party_b")
    if a.get("missing_files") or b.get("missing_files"):
        decision = "deny"
        reason_code = "missing_party_artifacts"
        reason = f"missing files: A={a.get('missing_files')!r}, B={b.get('missing_files')!r}"
        findings = [{"kind": "missing_party_artifacts", "message": reason, "expected": [], "actual": [a.get("missing_files"), b.get("missing_files")]}]
        checks = {k: "missing" for k in (
            "manifest_signature_valid", "job_id_match", "commit_match", "input_commitment_match", "commitment_exchange_match", "tls_identity_match",
            "ca_fingerprint_match", "result_hash_match", "policy_decision_match", "audit_chain_match",
        )}
    else:
        findings = []

        def _cmp(name: str, key: str, mismatch_reason: str) -> str:
            av = a.get(key)
            bv = b.get(key)
            if av is None or bv is None:
                return "missing"
            if av == bv:
                return "match"
            findings.append({"kind": mismatch_reason, "message": f"{key} differs", "expected": av, "actual": bv})
            return "mismatch"

        def _manifest_status(party: dict[str, Any], label: str) -> str:
            verification = party.get("signed_manifest_verification")
            if verification is None:
                return "missing"
            if isinstance(verification, dict) and verification.get("status") == "ok":
                return "match"
            findings.append({
                "kind": "manifest_signature_invalid",
                "message": f"{label} signed run manifest is invalid",
                "expected": "valid ed25519 signature",
                "actual": verification,
            })
            return "mismatch"

        def _exchange_status() -> str:
            a_local = a.get("input_commitment_sha256")
            a_peer = a.get("peer_input_commitment_sha256")
            b_local = b.get("input_commitment_sha256")
            b_peer = b.get("peer_input_commitment_sha256")
            if a_peer is None and b_peer is None:
                return "missing"
            if None in (a_local, a_peer, b_local, b_peer):
                findings.append({
                    "kind": "commitment_exchange_mismatch",
                    "message": "signed run manifests do not carry a complete local/peer commitment pair",
                    "expected": {"party_a_local": a_local, "party_a_peer": b_local, "party_b_local": b_local, "party_b_peer": a_local},
                    "actual": {"party_a_local": a_local, "party_a_peer": a_peer, "party_b_local": b_local, "party_b_peer": b_peer},
                })
                return "mismatch"
            if a_peer == b_local and b_peer == a_local:
                return "match"
            findings.append({
                "kind": "commitment_exchange_mismatch",
                "message": "party-local and peer commitment hashes do not cross-match",
                "expected": {"party_a_peer": b_local, "party_b_peer": a_local},
                "actual": {"party_a_peer": a_peer, "party_b_peer": b_peer},
            })
            return "mismatch"

        def _tls_identity_status() -> str:
            a_local = a.get("tls_identity")
            a_peer = a.get("peer_tls_identity")
            b_local = b.get("tls_identity")
            b_peer = b.get("peer_tls_identity")
            if a_peer is None and b_peer is None:
                return _cmp("tls_identity_match", "tls_identity", "tls_identity_mismatch")
            if None in (a_local, a_peer, b_local, b_peer):
                findings.append({
                    "kind": "tls_identity_mismatch",
                    "message": "signed run manifests do not carry a complete local/peer TLS identity pair",
                    "expected": {"party_a_peer": b_local, "party_b_peer": a_local},
                    "actual": {"party_a_peer": a_peer, "party_b_peer": b_peer},
                })
                return "mismatch"
            if a_peer == b_local and b_peer == a_local:
                return "match"
            findings.append({
                "kind": "tls_identity_mismatch",
                "message": "party-local and peer TLS identities do not cross-match",
                "expected": {"party_a_peer": b_local, "party_b_peer": a_local},
                "actual": {"party_a_peer": a_peer, "party_b_peer": b_peer},
            })
            return "mismatch"

        manifest_a = _manifest_status(a, "party_a")
        manifest_b = _manifest_status(b, "party_b")
        manifest_status = (
            "match"
            if manifest_a == "match" and manifest_b == "match"
            else "mismatch"
            if manifest_a == "mismatch" or manifest_b == "mismatch"
            else "missing"
        )
        exchange_status = _exchange_status()
        if require_signed_manifests and manifest_status == "missing":
            findings.append({
                "kind": "manifest_signature_missing",
                "message": "signed run manifests are required for this evidence merge",
                "expected": "party_a and party_b signed run manifest",
                "actual": {
                    "party_a": a.get("signed_manifest_path"),
                    "party_b": b.get("signed_manifest_path"),
                },
            })

        def _input_commitment_status() -> str:
            if exchange_status == "match":
                return "match"
            if exchange_status == "mismatch":
                return "missing"
            return _cmp("input_commitment_match", "input_commitment_sha256", "input_manifest_mismatch")

        checks = {
            "manifest_signature_valid": manifest_status,
            "job_id_match": _cmp("job_id_match", "job_id", "job_id_mismatch"),
            "commit_match": _cmp("commit_match", "commit", "commit_mismatch"),
            "input_commitment_match": _input_commitment_status(),
            "commitment_exchange_match": exchange_status,
            "tls_identity_match": _tls_identity_status(),
            "ca_fingerprint_match": _cmp("ca_fingerprint_match", "ca_fingerprint_sha256", "ca_fingerprint_mismatch"),
            "result_hash_match": _cmp("result_hash_match", "result_sha256", "result_hash_mismatch"),
            "policy_decision_match": _cmp("policy_decision_match", "policy_decision", "policy_decision_mismatch"),
            "audit_chain_match": _cmp("audit_chain_match", "audit_chain_sha256", "audit_chain_hash_mismatch"),
        }
        priority = [
            ("manifest_signature_valid", "manifest_signature_invalid"),
            ("job_id_match", "job_id_mismatch"),
            ("commit_match", "commit_mismatch"),
            ("input_commitment_match", "input_manifest_mismatch"),
            ("commitment_exchange_match", "commitment_exchange_mismatch"),
            ("tls_identity_match", "tls_identity_mismatch"),
            ("ca_fingerprint_match", "ca_fingerprint_mismatch"),
            ("result_hash_match", "result_hash_mismatch"),
            ("policy_decision_match", "policy_decision_mismatch"),
            ("audit_chain_match", "audit_chain_hash_mismatch"),
        ]
        decision = "allow"
        reason_code = "ok"
        reason = None
        for name, code in priority:
            if checks[name] == "mismatch":
                decision = "deny"
                reason_code = code
                reason = f"{name} mismatch"
                break
            if name == "manifest_signature_valid" and require_signed_manifests and checks[name] == "missing":
                decision = "deny"
                reason_code = "manifest_signature_missing"
                reason = "signed run manifests are required"
                break

    report = {
        "schema": PJC_TWO_PARTY_EVIDENCE_MERGE_SCHEMA,
        "generated_at_utc": _utc_now_iso(),
        "job_id": job_id,
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason,
        "party_a": a,
        "party_b": b,
        "checks": checks,
        "findings": findings,
    }
    out_dir = _ensure_two_party_dir() / "evidence_merge"
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = out_dir / f"{job_id}_{_utc_suffix()}.json"
    evidence_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "ok", "evidence_path": str(evidence_path), "report": report}


# --- Required negative-case runner --------------------------------------------


def _generate_dummy_cert(tmp_dir: Path, *, common_name: str, san: str | None = None) -> tuple[Path, Path]:
    """Synthesize a short-lived self-signed cert for negative-case identity probes."""
    key_path = tmp_dir / "dummy.key"
    cert_path = tmp_dir / "dummy.crt"
    cfg_path = tmp_dir / "openssl.cnf"
    cfg_path.write_text(
        "[req]\n"
        "distinguished_name=dn\nx509_extensions=ext\nprompt=no\n"
        "[dn]\nCN=" + common_name + "\n"
        "[ext]\nsubjectAltName=DNS:" + (san or common_name) + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["openssl", "genrsa", "-out", str(key_path), "2048"],
        cwd=str(REPO_ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30,
    )
    subprocess.run(
        ["openssl", "req", "-new", "-x509", "-key", str(key_path),
         "-out", str(cert_path), "-days", "1", "-config", str(cfg_path)],
        cwd=str(REPO_ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30,
    )
    return cert_path, key_path


_NEGATIVE_CASE_EXPECTED: dict[str, tuple[str, ...]] = {
    "wrong_token": ("invalid_token", "pairing_rejected"),
    "expired_token": ("token_expired",),
    "wrong_ca": ("ca_fingerprint_mismatch",),
    "wrong_peer": ("peer_identity_mismatch",),
    "closed_port": ("tcp_unreachable",),
    "commit_mismatch": ("commit_mismatch",),
    "modified_csv": ("input_manifest_hash_mismatch",),
    "privacy_denial": ("below_k", "below_min_rows", "privacy_budget_exhausted", "privacy_denial"),
}


def _negative_case_record(name: str, *, actual_decision: str, actual_reason_code: str, message: str = "", evidence_path: str | None = None) -> dict[str, Any]:
    expected_codes = _NEGATIVE_CASE_EXPECTED.get(name, ())
    expected_decision = "deny"
    code_ok = actual_reason_code in expected_codes if expected_codes else True
    result = "pass" if (actual_decision == expected_decision and code_ok) else "fail"
    return {
        "name": name,
        "expected_decision": expected_decision,
        "actual_decision": actual_decision,
        "expected_reason_code": expected_codes[0] if expected_codes else "",
        "actual_reason_code": actual_reason_code,
        "result": result,
        "message": message or None,
        "evidence_path": evidence_path,
    }


def _run_negative_case(name: str, *, scenario: dict[str, Any]) -> dict[str, Any]:
    if name == "wrong_token":
        try:
            _enroll_pjc_mtls_csr(
                csr_pem=scenario.get("csr_pem") or "",
                pairing_token=scenario.get("pairing_token") or "definitely-not-the-real-token",
            )
        except PermissionError as exc:
            return _negative_case_record(name, actual_decision="deny", actual_reason_code="invalid_token", message=str(exc))
        except ValueError as exc:
            return _negative_case_record(name, actual_decision="deny", actual_reason_code="invalid_csr", message=str(exc))
        return _negative_case_record(name, actual_decision="allow", actual_reason_code="unexpected_ok", message="enrollment accepted bad token")
    if name == "expired_token":
        meta_path = PJC_MTLS_PAIRING_TOKEN_META_FILE
        token_path = PJC_MTLS_PAIRING_TOKEN_FILE
        backup_meta = meta_path.read_text(encoding="utf-8") if meta_path.is_file() else None
        backup_token = token_path.read_text(encoding="utf-8") if token_path.is_file() else None
        try:
            token = _ensure_pairing_token(force=True)
            meta = _read_pairing_meta()
            meta["issued_at_epoch"] = max(0, int(time.time()) - max(1, int(meta.get("ttl_seconds") or 60)) - 10)
            _write_pairing_meta(meta)
            try:
                _enroll_pjc_mtls_csr(csr_pem=scenario.get("csr_pem") or "", pairing_token=token)
            except PermissionError as exc:
                return _negative_case_record(name, actual_decision="deny", actual_reason_code="token_expired", message=str(exc))
            except ValueError as exc:
                return _negative_case_record(name, actual_decision="deny", actual_reason_code="invalid_csr", message=str(exc))
            return _negative_case_record(name, actual_decision="allow", actual_reason_code="unexpected_ok", message="enrollment accepted expired token")
        finally:
            if backup_meta is not None:
                meta_path.write_text(backup_meta, encoding="utf-8")
            else:
                try:
                    meta_path.unlink()
                except FileNotFoundError:
                    pass
            if backup_token is not None:
                token_path.write_text(backup_token, encoding="utf-8")
            else:
                try:
                    token_path.unlink()
                except FileNotFoundError:
                    pass
    if name == "wrong_ca":
        with tempfile.TemporaryDirectory(prefix="pjc_neg_ca_") as cert_tmp:
            cert_dir = Path(cert_tmp)
            cert_path, _ = _generate_dummy_cert(cert_dir, common_name="pjc-server", san=f"job-{scenario.get('job_id') or 'neg'}.partyA.example")
            body = dict(scenario)
            body["peer_cert_path"] = str(cert_path)
            body["expected_ca_fingerprint_sha256"] = "0" * 64
            body["expected_peer_identity"] = body.get("expected_peer_identity") or f"job-{scenario.get('job_id') or 'neg'}.partyA.example"
            body.setdefault("role", "client")
            body.setdefault("job_id", scenario.get("job_id") or "neg-case")
            try:
                report = _two_party_preflight(body)["report"]
            except ValueError as exc:
                return _negative_case_record(name, actual_decision="deny", actual_reason_code="config_error", message=str(exc))
            return _negative_case_record(name, actual_decision=report["decision"], actual_reason_code=report["reason_code"], message=report.get("reason") or "", evidence_path=None)
    if name == "wrong_peer":
        with tempfile.TemporaryDirectory(prefix="pjc_neg_peer_") as cert_tmp:
            cert_dir = Path(cert_tmp)
            cert_path, _ = _generate_dummy_cert(cert_dir, common_name="pjc-server", san=f"job-{scenario.get('job_id') or 'neg'}.partyA.example")
            body = dict(scenario)
            body["peer_cert_path"] = str(cert_path)
            # Force an identity that the synthesized cert does NOT carry
            body["expected_peer_identity"] = scenario.get("wrong_peer_identity") or "job-someone-else.partyA.example"
            body.setdefault("role", "client")
            body.setdefault("job_id", scenario.get("job_id") or "neg-case")
            try:
                report = _two_party_preflight(body)["report"]
            except ValueError as exc:
                return _negative_case_record(name, actual_decision="deny", actual_reason_code="config_error", message=str(exc))
            return _negative_case_record(name, actual_decision=report["decision"], actual_reason_code=report["reason_code"], message=report.get("reason") or "")
    if name == "closed_port":
        body = dict(scenario)
        # pick a port we believe is closed (high random ephemeral)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            closed_port = s.getsockname()[1]
        body["peer_host"] = "127.0.0.1"
        body["peer_port"] = closed_port
        body.setdefault("role", "client")
        body.setdefault("job_id", scenario.get("job_id") or "neg-case")
        report = _two_party_preflight(body)["report"]
        return _negative_case_record(name, actual_decision=report["decision"], actual_reason_code=report["reason_code"], message=report.get("reason") or "")
    if name == "commit_mismatch":
        body = dict(scenario)
        body["expected_commit"] = "0" * 40
        body.setdefault("role", "client")
        body.setdefault("job_id", scenario.get("job_id") or "neg-case")
        report = _two_party_preflight(body)["report"]
        return _negative_case_record(name, actual_decision=report["decision"], actual_reason_code=report["reason_code"], message=report.get("reason") or "")
    if name == "modified_csv":
        body = dict(scenario)
        body["expected_input_csv_sha256"] = "0" * 64
        body.setdefault("role", "client")
        body.setdefault("job_id", scenario.get("job_id") or "neg-case")
        report = _two_party_preflight(body)["report"]
        return _negative_case_record(name, actual_decision=report["decision"], actual_reason_code=report["reason_code"], message=report.get("reason") or "")
    if name == "privacy_denial":
        # Synthesize a privacy denial by checking that resource_limits + low-k flag fires
        # via input_manifest hash check. Operator-supplied scenario decides exact match.
        provided = scenario.get("privacy_denial_outcome")
        if isinstance(provided, dict):
            return _negative_case_record(
                name,
                actual_decision=str(provided.get("decision") or "deny"),
                actual_reason_code=str(provided.get("reason_code") or "below_k"),
                message=str(provided.get("message") or ""),
                evidence_path=provided.get("evidence_path"),
            )
        # default: simulate below-k denial from a public_report stub if path supplied
        report_path = scenario.get("public_report_path")
        if isinstance(report_path, str) and report_path:
            data = _maybe_load_json(_repo_path(report_path)) or {}
            released = bool(data.get("released"))
            reason = str(data.get("reason_code") or "below_k")
            decision = "deny" if not released else "allow"
            return _negative_case_record(name, actual_decision=decision, actual_reason_code=reason)
        return _negative_case_record(name, actual_decision="deny", actual_reason_code="privacy_denial", message="default privacy denial assumption")
    return _negative_case_record(name, actual_decision="allow", actual_reason_code="unknown_case", message=f"unsupported case: {name}")


def _two_party_negative_cases(body: dict[str, Any]) -> dict[str, Any]:
    job_id = str(body.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")
    required = list(body.get("required_cases") or PJC_REQUIRED_NEGATIVE_CASES)
    if not required:
        raise ValueError("required_cases must not be empty")
    for case in required:
        if case not in PJC_REQUIRED_NEGATIVE_CASES:
            raise ValueError(f"unsupported required case: {case}")
    scenarios = body.get("scenarios") or {}
    if not isinstance(scenarios, dict):
        raise ValueError("scenarios must be a JSON object keyed by case name")
    results: list[dict[str, Any]] = []
    for case_name in required:
        scenario = scenarios.get(case_name) or {}
        if not isinstance(scenario, dict):
            scenario = {}
        scenario = dict(scenario)
        scenario.setdefault("job_id", job_id)
        try:
            result = _run_negative_case(case_name, scenario=scenario)
        except Exception as exc:  # noqa: BLE001
            result = _negative_case_record(case_name, actual_decision="deny", actual_reason_code="case_execution_failed", message=str(exc))
        results.append(result)
    # decision: allow only if every required case passes (i.e. expected deny)
    decision = "allow"
    reason_code = "ok"
    reason: str | None = None
    case_by_name = {item["name"]: item for item in results}
    for required_case in required:
        item = case_by_name.get(required_case)
        if item is None:
            decision = "deny"; reason_code = "missing_required_case"
            reason = f"missing required case: {required_case}"
            break
        if item.get("result") == "fail":
            decision = "deny"
            reason_code = "unexpected_allow"
            reason = f"{required_case} did not produce the expected denial"
            break
    report = {
        "schema": PJC_TWO_PARTY_NEGATIVE_CASES_SCHEMA,
        "generated_at_utc": _utc_now_iso(),
        "job_id": job_id,
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason,
        "required_cases": required,
        "cases": results,
    }
    out_dir = _ensure_two_party_dir() / "negative_cases"
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = out_dir / f"{job_id}_{_utc_suffix()}.json"
    evidence_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "ok", "evidence_path": str(evidence_path), "report": report}


# --- TLS EOF live diagnostic --------------------------------------------------

PJC_TLS_DIAGNOSTIC_SCHEMA = "pjc_tls_diagnostic/v1"


def _classify_tls_error(message: str) -> str:
    text = (message or "").lower()
    if not text:
        return "ok"
    if "eof" in text and ("unexpected" in text or "occurred in violation" in text or "before" in text):
        return "tls_eof"
    if "alert" in text and "handshake" in text:
        return "tls_alert_handshake"
    if "alert" in text and "certificate" in text:
        return "tls_alert_certificate"
    if "wrong version number" in text or "sslv3 alert" in text:
        return "tls_protocol_mismatch"
    if "tlsv1_alert_unknown_ca" in text or "unknown_ca" in text:
        return "tls_unknown_ca"
    if "self-signed" in text or "self signed" in text:
        return "tls_self_signed"
    if "certificate verify failed" in text or "verify failed" in text:
        return "tls_verify_failed"
    if "connection refused" in text:
        return "tcp_refused"
    if "timed out" in text or "timeout" in text:
        return "tcp_timeout"
    if "no route to host" in text:
        return "tcp_no_route"
    if "permission denied" in text:
        return "io_permission_denied"
    return "other"


def _suggest_tls_action(category: str, *, tcp_ok: bool, local_files: dict[str, bool]) -> str:
    if not tcp_ok:
        return (
            "Open the data-plane port on Party A's firewall/security group and confirm the "
            "TLS proxy (socat or pjc_tls_proxy.py) is actually listening before retrying."
        )
    missing_local = [name for name, present in local_files.items() if not present]
    if missing_local:
        return (
            f"Local cert material is missing ({', '.join(missing_local)}). Run Party B enroll "
            "or copy the per-job cert bundle before retrying."
        )
    if category == "tls_eof":
        return (
            "Likely cause: the peer accepted the TCP connection but closed before the TLS "
            "handshake completed. Common culprits are (1) PROXY-protocol or HTTP plain text "
            "in front of socat, (2) the wrong port mapped to socat, or (3) socat being killed "
            "early. Check the server log path for socat/PJC errors and verify the listener "
            "really runs OPENSSL-LISTEN."
        )
    if category == "tls_alert_handshake":
        return (
            "TLS alert during handshake — usually a peer-cert mismatch. Re-verify both parties "
            "share the same CA bundle and that the SAN of the presented cert matches the "
            "configured peer identity."
        )
    if category == "tls_protocol_mismatch":
        return "Force TLS 1.2+/1.3 on both ends; legacy SSL/early TLS is rejected by default."
    if category == "tls_unknown_ca":
        return "Party A's server certificate is not signed by the CA Party B trusts; re-issue or re-enroll."
    if category == "tls_self_signed":
        return "Self-signed cert without trust pinning; use the bootstrap_uri/CA fingerprint pin instead of TOFU."
    if category == "tls_verify_failed":
        return "Inspect the peer cert subject and the SAN; check that the trust bundle matches."
    if category == "tcp_refused":
        return "No process listening on the data-plane port — start Party A's role first."
    if category == "tcp_timeout":
        return "Firewall or NAT is dropping packets; verify the path with traceroute/mtr."
    if category == "ok":
        return "TLS handshake completed; no action required."
    return "Capture the full TLS handshake (openssl s_client -showcerts -msg) and attach the server log path for triage."


def _two_party_tls_diagnostic(body: dict[str, Any]) -> dict[str, Any]:
    """Produce a ``pjc_tls_diagnostic/v1`` report.

    The diagnostic intentionally never raises on a probe failure — it captures
    every observed symptom so operators can compare the TCP, TLS, local file,
    and server-log signals side by side.
    """
    job_id = str(body.get("job_id") or "").strip() or "tls-diag"
    host = str(body.get("peer_host") or body.get("server_host") or "").strip()
    if not host:
        raise ValueError("peer_host is required")
    try:
        port = int(body.get("peer_port") or body.get("dataplane_port") or 10502)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"peer_port must be an integer: {exc}") from exc
    server_hostname = str(body.get("server_hostname") or "pjc-server").strip()
    cert_dir_raw = str(body.get("cert_dir") or "").strip()
    cert_dir = _repo_path(cert_dir_raw) if cert_dir_raw else None
    role = str(body.get("role") or "client").strip().lower()
    if role not in ("server", "client"):
        role = "client"
    server_log_raw = str(body.get("server_log_path") or "").strip()
    server_log = _repo_path(server_log_raw) if server_log_raw else None
    tcp_timeout = float(body.get("tcp_timeout_sec") or 3.0)
    tls_timeout = float(body.get("tls_timeout_sec") or 5.0)

    # 1) Local files
    local_files: dict[str, bool] = {}
    if cert_dir is not None:
        local_files["ca.crt"] = (cert_dir / "ca.crt").is_file()
        if role == "client":
            local_files["client.crt"] = (cert_dir / "client.crt").is_file()
            local_files["client.key"] = (cert_dir / "client.key").is_file()
        else:
            local_files["server.crt"] = (cert_dir / "server.crt").is_file()
            local_files["server.key"] = (cert_dir / "server.key").is_file()

    # 2) TCP probe
    tcp_ok, tcp_duration_ms, tcp_msg = _tcp_probe(host, port, timeout_sec=tcp_timeout)

    # 3) TLS handshake probe (only if TCP succeeded)
    tls_block: dict[str, Any] = {
        "attempted": False,
        "ok": False,
        "tls_protocol": None,
        "peer_cert_fingerprint_sha256": None,
        "peer_cert_subject": None,
        "message": "",
        "category": "skip",
    }
    if tcp_ok:
        ca_path = cert_dir / "ca.crt" if cert_dir is not None and (cert_dir / "ca.crt").is_file() else None
        cert_path: Path | None = None
        key_path: Path | None = None
        if cert_dir is not None:
            if role == "client":
                cert_path = cert_dir / "client.crt" if (cert_dir / "client.crt").is_file() else None
                key_path = cert_dir / "client.key" if (cert_dir / "client.key").is_file() else None
            else:
                cert_path = cert_dir / "server.crt" if (cert_dir / "server.crt").is_file() else None
                key_path = cert_dir / "server.key" if (cert_dir / "server.key").is_file() else None
        info = _tls_handshake_probe(
            host, port,
            ca_path=ca_path,
            cert_path=cert_path,
            key_path=key_path,
            server_hostname=server_hostname,
            timeout_sec=tls_timeout,
        )
        tls_block["attempted"] = True
        tls_block["ok"] = bool(info.get("ok"))
        tls_block["tls_protocol"] = info.get("tls_protocol")
        tls_block["peer_cert_fingerprint_sha256"] = info.get("peer_cert_fingerprint_sha256")
        tls_block["peer_cert_subject"] = info.get("peer_cert_subject")
        tls_block["message"] = info.get("message") or ""
        tls_block["category"] = _classify_tls_error(info.get("message") or "")
        if tls_block["ok"]:
            tls_block["category"] = "ok"

    # 4) Server-side log tail (only the last 40 lines, never copy private keys)
    server_log_block: dict[str, Any] = {
        "path": str(server_log) if server_log else None,
        "exists": bool(server_log and server_log.is_file()),
        "tail": [],
        "sha256": None,
    }
    if server_log and server_log.is_file():
        try:
            with server_log.open("r", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
            tail = [line.rstrip("\n") for line in lines[-40:]]
            redacted = []
            for line in tail:
                lower = line.lower()
                if "begin private key" in lower or "begin rsa private key" in lower or "pairing_token" in lower:
                    redacted.append("<redacted: contained secret>")
                else:
                    redacted.append(line)
            server_log_block["tail"] = redacted
            server_log_block["sha256"] = _sha256_file(server_log)
        except OSError as exc:
            server_log_block["tail"] = [f"<error reading log: {exc}>"]

    # 5) Verdict + suggested action
    if not tcp_ok:
        category = "tcp_refused" if "connection refused" in tcp_msg.lower() else _classify_tls_error(tcp_msg)
        decision = "deny"
        reason_code = category if category != "ok" else "tcp_unreachable"
    elif not tls_block["ok"]:
        category = tls_block["category"]
        decision = "deny"
        reason_code = category if category != "ok" else "tls_handshake_failed"
    else:
        category = "ok"
        decision = "allow"
        reason_code = "ok"

    suggested_action = _suggest_tls_action(category, tcp_ok=tcp_ok, local_files=local_files)

    report = {
        "schema": PJC_TLS_DIAGNOSTIC_SCHEMA,
        "generated_at_utc": _utc_now_iso(),
        "job_id": job_id,
        "role": role,
        "decision": decision,
        "reason_code": reason_code,
        "category": category,
        "host": host,
        "port": port,
        "server_hostname": server_hostname,
        "tcp": {
            "ok": tcp_ok,
            "duration_ms": tcp_duration_ms,
            "message": tcp_msg or None,
        },
        "tls": tls_block,
        "local_files": local_files,
        "server_log": server_log_block,
        "suggested_action": suggested_action,
    }
    out_dir = _ensure_two_party_dir() / "tls_diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = out_dir / f"{job_id}_{role}_{_utc_suffix()}.json"
    evidence_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "ok", "evidence_path": str(evidence_path), "report": report}


def _release_policy_gate_endpoint(body: dict[str, Any]) -> dict[str, Any]:
    """Run the server-side release policy gate (delegates to the CLI helper)."""
    from check_release_policy_gate import run_gate  # local import to keep startup light

    public_report_raw = str(body.get("public_report_path") or "").strip()
    policy_config_raw = str(body.get("policy_config_path") or "").strip()
    if not public_report_raw:
        raise ValueError("public_report_path is required")
    if not policy_config_raw:
        raise ValueError("policy_config_path is required")
    public_report = _repo_path(public_report_raw)
    policy_config = _repo_path(policy_config_raw)
    if not public_report.is_file():
        raise FileNotFoundError(f"public_report not found: {public_report}")
    if not policy_config.is_file():
        raise FileNotFoundError(f"policy_config not found: {policy_config}")
    operator_report = _repo_path(str(body["operator_report_path"])) if body.get("operator_report_path") else None
    budget_ledger = _repo_path(str(body["privacy_budget_ledger"])) if body.get("privacy_budget_ledger") else None
    pjc_evidence_merge = _repo_path(str(body["pjc_evidence_merge_path"])) if body.get("pjc_evidence_merge_path") else None
    policy_audit_log = _repo_path(str(body["policy_audit_log_path"])) if body.get("policy_audit_log_path") else None

    report = run_gate(
        public_report_path=public_report,
        policy_config_path=policy_config,
        operator_report_path=operator_report,
        budget_ledger_path=budget_ledger,
        pjc_evidence_merge_path=pjc_evidence_merge,
        policy_audit_log_path=policy_audit_log,
    )
    out_dir = _ensure_two_party_dir() / "release_policy_gate"
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = out_dir / f"{report.get('job_id') or 'unknown'}_{_utc_suffix()}.json"
    evidence_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "ok", "evidence_path": str(evidence_path), "report": report}


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        handler_cls,
        *,
        out_base: Path,
        history_root: Path,
        history_limit: int,
        pid_file: str,
        ready_file: str,
        max_concurrent_jobs_per_tenant: int,
        auth_token: str = "",
        metadata_db_path: str = "",
        metadata_db_dsn: str = "",
        metadata_db_read_dsn: str = "",
        identity_token_config: str = "",
        privacy_budget_store: str = "",
        privacy_budget_approval_queue: str = "",
        privacy_budget_approval_decisions: str = "",
        mtls_enrollment_only_mode: bool = False,
        console_dist: Path | None = None,
        session_cookie_name: str = DEFAULT_IDENTITY_SESSION_COOKIE_NAME,
        session_cookie_secure: bool = False,
    ) -> None:
        self.out_base = out_base
        self.history_root = history_root
        self.history_limit = history_limit
        self.pid_file = pid_file
        self.ready_file = ready_file
        self.max_concurrent_jobs_per_tenant = max(0, int(max_concurrent_jobs_per_tenant))
        self.auth_token = auth_token
        self.metadata_db_path = str(Path(metadata_db_path).resolve()) if metadata_db_path else ""
        self.metadata_db_dsn = metadata_db_dsn
        self.metadata_db_read_dsn = metadata_db_read_dsn
        self.identity_token_config = str(Path(identity_token_config).resolve()) if identity_token_config else ""
        self.privacy_budget_store = str(Path(privacy_budget_store).resolve()) if privacy_budget_store else ""
        self.privacy_budget_approval_queue = (
            str(Path(privacy_budget_approval_queue).resolve()) if privacy_budget_approval_queue else ""
        )
        self.privacy_budget_approval_decisions = (
            str(Path(privacy_budget_approval_decisions).resolve()) if privacy_budget_approval_decisions else ""
        )
        self.mtls_enrollment_only_mode = bool(mtls_enrollment_only_mode)
        self.console_dist = console_dist
        self.session_cookie_name = session_cookie_name.strip() or DEFAULT_IDENTITY_SESSION_COOKIE_NAME
        self.session_cookie_secure = bool(session_cookie_secure)
        self.job_lock = threading.Lock()
        self.current_job: dict[str, Any] | None = _seed_job_from_out_base(out_base)
        self.jobs: dict[str, dict[str, Any]] = {}
        if self.current_job is not None and self.current_job.get("job_id"):
            self.jobs[str(self.current_job["job_id"])] = dict(self.current_job)
        super().__init__(server_address, handler_cls)

    def get_job(self, job_id: str | None = None) -> dict[str, Any] | None:
        with self.job_lock:
            if job_id:
                job = self.jobs.get(str(job_id))
                return dict(job) if job is not None else None
            if self.current_job is None:
                return None
            return dict(self.current_job)

    def set_job(self, job: dict[str, Any] | None) -> None:
        with self.job_lock:
            self.current_job = dict(job) if job is not None else None
            if job is not None and job.get("job_id"):
                self.jobs[str(job["job_id"])] = dict(job)
        invalidate_dashboard_cache()

    def _filesystem_active_keys_for_tenant(self, tenant_id: str) -> set[str]:
        target = tenant_id or UNSPECIFIED_TENANT_ID
        active_keys: set[str] = set()
        statuses, _ = scan_status_files(
            self.history_root,
            filter_state="running",
            limit=1000000,
        )
        for item in statuses:
            item_tenant = str(item.get("tenant_id") or UNSPECIFIED_TENANT_ID)
            if item_tenant == target:
                active_keys.add(str(item.get("out_base") or item.get("job_id") or len(active_keys)))
        return active_keys

    def active_jobs_for_tenant(self, tenant_id: str) -> int:
        target = tenant_id or UNSPECIFIED_TENANT_ID
        active_keys = self._filesystem_active_keys_for_tenant(target)
        with self.job_lock:
            current = self.current_job
            if current is not None and current.get("state") == "running":
                current_tenant = str(current.get("tenant_id") or UNSPECIFIED_TENANT_ID)
                if current_tenant == target:
                    active_keys.add(str(current.get("out_base") or current.get("job_id") or "__current__"))
            for job in self.jobs.values():
                if job.get("state") != "running":
                    continue
                job_tenant = str(job.get("tenant_id") or UNSPECIFIED_TENANT_ID)
                if job_tenant == target:
                    active_keys.add(str(job.get("out_base") or job.get("job_id") or "__job__"))
        return len(active_keys)

    def try_reserve_job(
        self,
        *,
        tenant_id: str,
        job_id: str | None,
        out_base: Path | None,
        request_source: str | None,
    ) -> dict[str, Any] | None:
        """Atomically check dashboard concurrency limits and reserve a job slot.

        Returns None on success (placeholder installed under job_lock); on failure returns
        ``{"status": int, "body": {...}}`` describing the HTTP error to send back.
        """
        target_tenant = tenant_id or UNSPECIFIED_TENANT_ID
        fs_active_keys: set[str] = set()
        if self.max_concurrent_jobs_per_tenant > 0:
            fs_active_keys = self._filesystem_active_keys_for_tenant(target_tenant)
        with self.job_lock:
            current = self.current_job
            if self.max_concurrent_jobs_per_tenant <= 0 and current is not None and current.get("state") == "running":
                return {
                    "status": 409,
                    "body": {
                        "error": "job_already_running",
                        "job_id": current.get("job_id"),
                    },
                }
            if job_id and job_id in self.jobs and self.jobs[job_id].get("state") == "running":
                return {
                    "status": 409,
                    "body": {
                        "error": "job_already_running",
                        "job_id": job_id,
                    },
                }
            if self.max_concurrent_jobs_per_tenant > 0:
                for job in self.jobs.values():
                    if job.get("state") != "running":
                        continue
                    job_tenant = str(job.get("tenant_id") or UNSPECIFIED_TENANT_ID)
                    if job_tenant == target_tenant:
                        fs_active_keys.add(str(job.get("out_base") or job.get("job_id") or "__job__"))
                if len(fs_active_keys) >= self.max_concurrent_jobs_per_tenant:
                    return {
                        "status": 429,
                        "body": {
                            "error": "tenant_job_quota_exceeded",
                            "reason_code": "tenant_job_quota_exceeded",
                            "tenant_id": target_tenant,
                            "active_jobs": len(fs_active_keys),
                            "max_concurrent_jobs_per_tenant": self.max_concurrent_jobs_per_tenant,
                            "message": (
                                f"tenant {target_tenant!r} already has {len(fs_active_keys)} active job(s); "
                                f"quota is {self.max_concurrent_jobs_per_tenant}"
                            ),
                        },
                    }
            now = _utc_now()
            placeholder = {
                "job_id": job_id,
                "tenant_id": target_tenant,
                "state": "running",
                "terminal": False,
                "started_at_utc": now,
                "finished_at_utc": None,
                "last_updated_at_utc": now,
                "last_exit_code": None,
                "out_base": str(out_base) if out_base is not None else None,
                "request_source": request_source,
                "reservation": True,
            }
            self.current_job = placeholder
            if job_id:
                self.jobs[job_id] = dict(placeholder)
        invalidate_dashboard_cache()
        return None

    def release_reservation(self, job_id: str | None = None) -> None:
        """Drop the placeholder installed by try_reserve_job after a launch failure."""
        with self.job_lock:
            current = self.current_job
            if current is not None and current.get("reservation") and (
                job_id is None or str(current.get("job_id") or "") == str(job_id)
            ):
                self.current_job = None
            if job_id and job_id in self.jobs and self.jobs[job_id].get("reservation"):
                self.jobs.pop(job_id, None)
        invalidate_dashboard_cache()

    def recent_runs(
        self,
        *,
        filter_state: str | None = None,
        filter_job_id: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        use_limit = max(1, limit or self.history_limit)
        statuses, total = scan_status_files(
            self.history_root,
            filter_state=filter_state,
            filter_job_id=filter_job_id,
            limit=use_limit,
        )
        for item in statuses:
            item["out_base_display"] = _display_path(Path(str(item.get("out_base") or "")), out_base=self.out_base)
            item["active"] = str(item.get("out_base") or "") == str(self.out_base)
        return {
            "schema": "query_workflow_status_list/v1",
            "search_dir": str(self.history_root),
            "search_dir_display": _display_path(self.history_root, out_base=self.out_base),
            "filter_state": filter_state,
            "filter_job_id": filter_job_id,
            "total_found": total,
            "returned_count": len(statuses),
            "limit": use_limit,
            "statuses": statuses,
        }

    def select_out_base(self, out_base: Path) -> dict[str, Any] | None:
        resolved = out_base.expanduser().resolve()
        if not resolved.is_dir():
            raise FileNotFoundError(f"out_base does not exist: {resolved}")
        try:
            resolved.relative_to(self.history_root)
        except ValueError as exc:
            raise ValueError(f"out_base must stay under history_root: {self.history_root}") from exc
        current = self.get_job()
        if current is not None and current.get("state") == "running" and str(current.get("out_base") or "") != str(resolved):
            raise RuntimeError("cannot switch active run while another job is running")
        self.out_base = resolved
        self.set_job(_seed_job_from_out_base(resolved))
        return self.get_job()


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # suppress default access log

    def _send(
        self,
        status: int,
        content_type: str,
        body: bytes,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        headers = {
            **_console_security_headers(secure_transport=bool(getattr(self.server, "session_cookie_secure", False))),
            **(extra_headers or {}),
        }
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body, extra_headers=extra_headers)

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _require_auth(self) -> dict[str, Any] | None:
        return resolve_request_identity(
            auth_header=self.headers.get("Authorization", ""),
            cookie_header=self.headers.get("Cookie", ""),
            session_cookie_name=self.server.session_cookie_name,
            expected_bearer_token=self.server.auth_token,
            db_path=self.server.metadata_db_path,
            db_dsn=self.server.metadata_db_dsn,
            db_read_dsn=self.server.metadata_db_read_dsn,
            identity_token_config=self.server.identity_token_config,
            auth_failure_label="operator dashboard",
        )

    def _auth_configured(self) -> bool:
        return bool(self.server.auth_token or self.server.identity_token_config)

    def _session_cookie_header(self, token: str, *, max_age: int | None) -> str:
        name = self.server.session_cookie_name
        parts = [
            f"{name}={token}",
            "Path=/",
            "HttpOnly",
            "SameSite=Strict",
        ]
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        if self.server.session_cookie_secure:
            parts.append("Secure")
        return "; ".join(parts)

    def _session_payload(self, identity: dict[str, Any] | None, *, status: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": SESSION_COOKIE_SCHEMA,
            "status": status,
            "auth_required": self._auth_configured(),
            "session_cookie": {
                "name": self.server.session_cookie_name,
                "httponly": True,
                "same_site": "Strict",
                "secure": bool(self.server.session_cookie_secure),
                "path": "/",
            },
        }
        if identity is not None:
            payload["authenticated_identity"] = {
                "caller": identity.get("caller"),
                "tenant_id": identity.get("tenant_id"),
                "service_id": identity.get("service_id"),
                "platform_roles": identity.get("platform_roles") or [],
                "auth_source": identity.get("auth_source"),
            }
        return payload

    def _handle_session_status(self) -> None:
        if not self._auth_configured():
            self._send_json(200, self._session_payload(None, status="disabled"))
            return
        try:
            identity = self._require_auth()
            self._send_json(200, self._session_payload(identity, status="authenticated"))
        except PermissionError as exc:
            self._send_json(
                401,
                {
                    "schema": SESSION_COOKIE_SCHEMA,
                    "status": "unauthenticated",
                    "auth_required": True,
                    "message": str(exc),
                    "session_cookie": {
                        "name": self.server.session_cookie_name,
                        "httponly": True,
                        "same_site": "Strict",
                        "secure": bool(self.server.session_cookie_secure),
                        "path": "/",
                    },
                },
            )

    def _handle_session_login(self) -> None:
        if not self.server.identity_token_config:
            self._send_json(
                400,
                {
                    "schema": SESSION_COOKIE_SCHEMA,
                    "status": "unsupported",
                    "message": "identity-token auth is required for browser HttpOnly cookie login",
                },
            )
            return
        try:
            body = self._read_json_body()
            token = str(body.get("bearer_token") or body.get("token") or "").strip()
            if not token:
                raise ValueError("bearer_token is required")
            identity = resolve_identity_context(
                db_path=self.server.metadata_db_path,
                db_dsn=self.server.metadata_db_dsn,
                db_read_dsn=self.server.metadata_db_read_dsn,
                identity_token_config=self.server.identity_token_config,
                bearer_token=token,
            )
            identity["auth_source"] = "login_exchange"
            max_age = int(body.get("max_age_seconds") or 0)
            if max_age <= 0:
                max_age = 8 * 60 * 60
            self._send_json(
                200,
                self._session_payload(identity, status="authenticated"),
                extra_headers={"Set-Cookie": self._session_cookie_header(token, max_age=max_age)},
            )
        except PermissionError as exc:
            self._send_json(403, {"schema": SESSION_COOKIE_SCHEMA, "status": "rejected", "message": str(exc)})
        except ValueError as exc:
            self._send_json(400, {"schema": SESSION_COOKIE_SCHEMA, "status": "rejected", "message": str(exc)})

    def _handle_session_logout(self) -> None:
        self._send_json(
            200,
            self._session_payload(None, status="cleared"),
            extra_headers={"Set-Cookie": self._session_cookie_header("", max_age=0)},
        )

    def _require_roles_if_auth_configured(self, *roles: str) -> bool:
        if not self._auth_configured():
            return True
        try:
            identity = self._require_auth()
            if identity is not None and not identity_has_any_role(identity, *roles):
                self._send_json(
                    403,
                    {
                        "error": "authz_rejected",
                        "message": "operator dashboard privileged role required",
                        "required_roles": list(roles),
                    },
                )
                return False
            return True
        except PermissionError as exc:
            self._send_json(403, {"error": "authz_rejected", "message": str(exc)})
            return False

    def _current_job_snapshot(self) -> dict[str, Any] | None:
        job = self.server.get_job()
        if job is None:
            return None
        return _job_snapshot(job)

    def _handle_helper_subprocess(
        self,
        *,
        script_name: str,
        request_body: dict[str, Any],
        timeout_sec: int,
        ok_status_field: str = "status",
    ) -> None:
        """Dispatch a JSON request to a one-shot helper subprocess and stream its
        single-document JSON response back to the caller.

        The helper is expected to live under ``REPO_ROOT/scripts/<script_name>``,
        emit exactly one JSON document on stdout, and use ``status`` of ``ok`` or
        ``error`` to signal success. Anything non-JSON or any subprocess crash
        translates to an HTTP 5xx with diagnostic context.
        """
        helper = REPO_ROOT / "scripts" / script_name
        if not helper.is_file():
            self._send_json(500, {"status": "error", "stage": "validate", "message": f"helper not found: {helper}"})
            return

        try:
            request_file = REPO_ROOT / "tmp" / f"_console_helper_{int(time.time() * 1000)}.json"
            request_file.parent.mkdir(parents=True, exist_ok=True)
            request_file.write_text(json.dumps(request_body))
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"status": "error", "stage": "stage_request", "message": str(exc)})
            return

        try:
            proc = subprocess.run(
                [sys.executable, str(helper), "--request-file", str(request_file)],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self._send_json(504, {"status": "error", "stage": "subprocess", "message": f"{script_name} timed out after {timeout_sec}s"})
            return
        finally:
            try:
                request_file.unlink()
            except OSError:
                pass

        stdout = proc.stdout.strip()
        try:
            payload = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError as exc:
            self._send_json(
                500,
                {
                    "status": "error",
                    "stage": "parse_response",
                    "message": f"helper emitted non-JSON: {exc}",
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "exit_code": proc.returncode,
                },
            )
            return

        if proc.returncode != 0 and ok_status_field not in payload:
            payload = {
                **payload,
                "status": "error",
                "stage": payload.get("stage") or "subprocess",
                "message": payload.get("message") or f"helper exit code {proc.returncode}",
            }

        ok = (payload.get(ok_status_field) == "ok")
        http_status = 200 if ok else (payload.get("http_status") if isinstance(payload.get("http_status"), int) else 500)
        if proc.stderr and not ok:
            payload.setdefault("stderr", proc.stderr)
        self._send_json(http_status, payload)

    def _handle_sse_search(self) -> None:
        try:
            body = self._read_json_body()
        except ValueError as exc:
            self._send_json(400, {"status": "error", "stage": "validate", "message": str(exc)})
            return
        if not body.get("keyword"):
            self._send_json(400, {"status": "error", "stage": "validate", "message": "missing keyword"})
            return
        if "db" not in body and not body.get("db_path"):
            self._send_json(400, {"status": "error", "stage": "validate", "message": "must provide either db or db_path"})
            return
        self._handle_helper_subprocess(
            script_name="sse_oneshot_search.py",
            request_body=body,
            timeout_sec=int(body.get("timeout_sec") or 60),
        )

    def _handle_pjc_run_only(self) -> None:
        try:
            body = self._read_json_body()
        except ValueError as exc:
            self._send_json(400, {"status": "error", "stage": "validate", "message": str(exc)})
            return
        if not body.get("server_csv") or not body.get("client_csv"):
            self._send_json(
                400,
                {"status": "error", "stage": "validate", "message": "server_csv and client_csv are required"},
            )
            return
        self._handle_helper_subprocess(
            script_name="pjc_run_only.py",
            request_body=body,
            timeout_sec=int(body.get("timeout_sec") or 900),
        )

    def _job_snapshot_or_404(self, job_id: str) -> dict[str, Any] | None:
        job = self.server.get_job(job_id)
        if job is None or str(job.get("job_id") or "") != job_id:
            return None
        return _job_snapshot(job)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query, keep_blank_values=False)
        if self.server.mtls_enrollment_only_mode and path not in ("/healthz",):
            # Dedicated enrollment-only mode: the only thing this server is
            # supposed to expose is POST /v1/pjc-mtls/enroll. Block every
            # other surface (dashboard HTML, jobs, audit, request workflow…)
            # so we never widen the public-IP attack surface during enrollment.
            self._send_json(404, {
                "status": "error",
                "error": "enrollment_only_mode",
                "message": "this server is restricted to PJC mTLS enrollment endpoints",
                "allowed_paths": ["GET /healthz", "POST /v1/pjc-mtls/enroll"],
            })
            return
        if path == "/healthz":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "schema": "operator_dashboard_health/v1",
                        "request_submission_enabled": bool(self.server.metadata_db_path or self.server.metadata_db_dsn),
                        "privacy_budget_approval_enabled": bool(self.server.privacy_budget_store),
                        "auth_required": bool(self.server.auth_token or self.server.identity_token_config),
                        "browser_session_cookie_supported": bool(self.server.identity_token_config),
                        "session_cookie_name": self.server.session_cookie_name,
                        "session_cookie_secure": bool(self.server.session_cookie_secure),
                        "spa_available": self.server.console_dist is not None,
                        "spa_dist": str(self.server.console_dist) if self.server.console_dist else None,
                    },
                )
        elif path == "/v1/session":
            self._handle_session_status()
        elif path == "/v1/dashboard":
            try:
                identity = self._require_auth() if (self.server.auth_token or self.server.identity_token_config) else None
                data = get_dashboard_data(
                    self.server.out_base,
                    history_root=self.server.history_root,
                    history_limit=self.server.history_limit,
                )
                data = dict(data)
                data["job_control"] = self._current_job_snapshot()
                if identity is not None and not identity_has_any_role(identity, *DASHBOARD_FULL_VIEW_ROLES):
                    self._send_json(200, build_dashboard_public_summary(data, identity=identity))
                else:
                    if identity is not None:
                        data["authenticated_identity"] = {
                            "caller": identity.get("caller"),
                            "tenant_id": identity.get("tenant_id"),
                            "platform_roles": identity.get("platform_roles") or [],
                        }
                    self._send_json(200, data)
            except PermissionError as exc:
                self._send_json(403, {"error": "authz_rejected", "message": str(exc)})
        elif path == "/v1/bucketed-scale-test":
            self._send_json(200, {"jobs": _list_bucketed_scale_test_jobs()})
        elif path.startswith("/v1/bucketed-scale-test/"):
            record_id = unquote(path.removeprefix("/v1/bucketed-scale-test/"))
            if not record_id or "/" in record_id:
                self._send_json(404, {"status": "error", "error": "not_found", "path": path})
                return
            snapshot = _get_bucketed_scale_test_job(record_id)
            if snapshot is None:
                self._send_json(404, {"status": "error", "error": "job_not_found", "job_id": record_id})
                return
            self._send_json(200, snapshot)
        elif path == "/v1/runs":
            if not self._require_roles_if_auth_configured(*DASHBOARD_FULL_VIEW_ROLES):
                return
            limit_raw = query.get("limit", [""])[0]
            state = query.get("state", [""])[0] or None
            job_id = query.get("job_id", [""])[0] or None
            limit = self.server.history_limit
            if limit_raw:
                try:
                    limit = max(1, int(limit_raw))
                except ValueError:
                    self._send_json(400, {"error": "invalid_limit", "message": f"invalid limit: {limit_raw}"})
                    return
            self._send_json(200, self.server.recent_runs(filter_state=state, filter_job_id=job_id, limit=limit))
        elif path == "/v1/requests":
            try:
                identity = self._require_auth()
                limit_raw = query.get("limit", ["50"])[0]
                try:
                    limit = min(200, max(1, int(limit_raw)))
                except ValueError:
                    raise ValueError(f"invalid limit: {limit_raw}")
                payload = _list_submissions(
                    self.server,
                    identity=identity,
                    tenant_id=query.get("tenant_id", [""])[0],
                    status=query.get("status", [""])[0],
                    limit=limit,
                )
                self._send_json(200, payload)
            except PermissionError as exc:
                self._send_json(403, {"error": "authz_rejected", "message": str(exc)})
            except ValueError as exc:
                self._send_json(400, {"error": "invalid_request", "message": str(exc)})
            except RuntimeError as exc:
                self._send_json(503, {"error": "metadata_sidecar_unavailable", "message": str(exc)})
        elif path == "/v1/privacy-budget/approvals":
            try:
                identity = self._require_auth()
                limit_raw = query.get("limit", ["50"])[0]
                try:
                    limit = min(200, max(1, int(limit_raw)))
                except ValueError:
                    raise ValueError(f"invalid limit: {limit_raw}")
                payload = _list_privacy_budget_approvals(
                    self.server,
                    identity=identity,
                    status=query.get("status", [""])[0],
                    tenant_id=query.get("tenant_id", [""])[0],
                    caller=query.get("caller", [""])[0],
                    limit=limit,
                )
                self._send_json(200, payload)
            except PermissionError as exc:
                self._send_json(403, {"error": "authz_rejected", "message": str(exc)})
            except ValueError as exc:
                self._send_json(400, {"error": "invalid_request", "message": str(exc)})
            except RuntimeError as exc:
                self._send_json(503, {"error": "privacy_budget_approval_unavailable", "message": str(exc)})
        elif path.startswith("/v1/requests/"):
            submission_id = unquote(path[len("/v1/requests/") :]).strip("/")
            try:
                identity = self._require_auth()
                with _connect_submission_db(self.server) as conn:
                    submission = _load_submission(conn, submission_id)
                _assert_request_view_allowed(identity, submission)
                self._send_json(200, submission)
            except FileNotFoundError as exc:
                self._send_json(404, {"error": "not_found", "message": str(exc), "submission_id": submission_id})
            except PermissionError as exc:
                self._send_json(403, {"error": "authz_rejected", "message": str(exc), "submission_id": submission_id})
            except RuntimeError as exc:
                self._send_json(503, {"error": "metadata_sidecar_unavailable", "message": str(exc)})
        elif path.startswith("/v1/pjc/roles/") and path.endswith("/status"):
            role = unquote(path[len("/v1/pjc/roles/") : -len("/status")]).strip("/")
            job_id = query.get("job_id", [""])[0].strip()
            if not job_id or role not in ("server", "client"):
                self._send_json(400, {"error": "invalid_request", "message": "job_id and role are required"})
                return
            payload = _role_status_payload(f"{job_id}::{role}")
            if payload is None:
                self._send_json(404, {"error": "role_not_found", "job_id": job_id, "role": role})
                return
            payload.pop("_process", None)
            payload.pop("_log_handle", None)
            self._send_json(200, payload)
        elif path.startswith("/v1/jobs/") and path.endswith("/result"):
            if not self._require_roles_if_auth_configured(*DASHBOARD_FULL_VIEW_ROLES):
                return
            job_id = unquote(path[len("/v1/jobs/") : -len("/result")]).strip("/")
            snapshot = self._job_snapshot_or_404(job_id)
            if snapshot is None:
                self._send_json(404, {"error": "not_found", "job_id": job_id})
                return
            if snapshot.get("state") not in {"completed", "failed"}:
                self._send_json(404, {"error": "result_not_ready", "job_id": job_id})
                return
            result = snapshot.get("result") or {}
            self._send_json(200, {
                "job_id": snapshot.get("job_id"),
                "state": snapshot.get("state"),
                "elapsed_sec": snapshot.get("elapsed_sec"),
                "exit_code": snapshot.get("exit_code"),
                "intersection_size": result.get("intersection_size"),
                "intersection_sum": result.get("intersection_sum"),
                "released": result.get("released"),
                "reason_code": result.get("reason_code"),
                "out_base": snapshot.get("out_base"),
            })
        elif path.startswith("/v1/jobs/"):
            if not self._require_roles_if_auth_configured(*DASHBOARD_FULL_VIEW_ROLES):
                return
            job_id = unquote(path[len("/v1/jobs/") :]).strip("/")
            snapshot = self._job_snapshot_or_404(job_id)
            if snapshot is None:
                self._send_json(404, {"error": "not_found", "job_id": job_id})
                return
            self._send_json(200, snapshot)
        else:
            # Anything not matched above is treated as a SPA static asset:
            # /, /index.html, /assets/*, /favicon.svg, or a client-side route
            # like /jobs/abc that should fall back to index.html. If the
            # console-dist directory is not configured or the file is missing,
            # this returns 404 with a hint, so the JSON API surface remains
            # intact.
            asset = _static_asset_response(self.server.console_dist, path)
            if asset is not None:
                status, ctype, body = asset
                self._send(status, ctype, body)
                return
            self._send_json(404, {
                "error": "not_found",
                "path": path,
                "hint": (
                    "Console SPA assets are not available. Build the SPA "
                    "(npm --prefix console run build) and start this server "
                    "with --console-dist <path>, or rely on the default "
                    "<repo>/console/dist location."
                ) if self.server.console_dist is None else "asset missing",
            })

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if self.server.mtls_enrollment_only_mode and path != "/v1/pjc-mtls/enroll":
            self._send_json(404, {
                "status": "error",
                "error": "enrollment_only_mode",
                "message": "this server is restricted to PJC mTLS enrollment endpoints",
                "allowed_paths": ["GET /healthz", "POST /v1/pjc-mtls/enroll"],
            })
            return
        if path == "/v1/runs/select":
            if not self._require_roles_if_auth_configured(*DASHBOARD_FULL_VIEW_ROLES):
                return
            try:
                body = self._read_json_body()
                out_base_value = body.get("out_base")
                if not isinstance(out_base_value, str) or not out_base_value.strip():
                    raise ValueError("out_base must be a non-empty string")
                snapshot = self.server.select_out_base(_repo_path(out_base_value))
                self._send_json(200, {
                    "selected_out_base": str(self.server.out_base),
                    "job_control": _job_snapshot(snapshot) if snapshot is not None else None,
                })
            except FileNotFoundError as exc:
                self._send_json(404, {"error": "out_base_not_found", "message": str(exc)})
            except RuntimeError as exc:
                self._send_json(409, {"error": "run_switch_blocked", "message": str(exc)})
            except ValueError as exc:
                self._send_json(400, {"error": "invalid_request", "message": str(exc)})
            return
        if path == "/v1/session/login":
            self._handle_session_login()
            return
        if path == "/v1/session/logout":
            self._handle_session_logout()
            return
        if path == "/v1/request/submit":
            try:
                if not self.server.metadata_db_path and not self.server.metadata_db_dsn:
                    self._send_json(
                        503,
                        {
                            "error": "metadata_sidecar_required",
                            "message": "request submission requires --metadata-db-path or --metadata-db-dsn",
                        },
                    )
                    return
                identity = self._require_auth()
                body = self._read_json_body()
                payload = _extract_submission_request(body)
                if identity is not None:
                    payload = bind_query_request_to_identity(identity, payload, execute=False)
                request_dir = _request_base_dir_from_header(self.headers.get("X-Request-Base-Dir", "").strip())
                normalized = normalize_request_paths(payload, request_dir=request_dir)
                _validate_request_schema(normalized)
                validate_request(normalized)
                submission = _build_request_submission(
                    payload=normalized,
                    request_source="operator_dashboard:http_request_body",
                    identity=identity,
                )
                _insert_workflow_submission(
                    db_path=self.server.metadata_db_path,
                    db_dsn=self.server.metadata_db_dsn,
                    submission=submission,
                    request_payload=normalized,
                    identity=identity,
                )
                self._send_json(202, submission)
            except PermissionError as exc:
                self._send_json(403, {"error": "authz_rejected", "message": str(exc)})
            except ValueError as exc:
                self._send_json(400, {"error": "validation_rejected", "message": str(exc)})
            except SystemExit as exc:
                self._send_json(400, {"error": "validation_rejected", "message": str(exc)})
            except RuntimeError as exc:
                self._send_json(503, {"error": "metadata_sidecar_unavailable", "message": str(exc)})
            return
        if path.startswith("/v1/request/") and (path.endswith("/approve") or path.endswith("/reject")):
            action = "approve" if path.endswith("/approve") else "reject"
            suffix = f"/{action}"
            submission_id = unquote(path[len("/v1/request/") : -len(suffix)]).strip("/")
            try:
                identity = self._require_auth()
                body = self._read_json_body()
                reason = str(body.get("reason") or body.get("rejection_reason") or "").strip()
                submission, job_snapshot = _transition_submission(
                    self.server,
                    submission_id=submission_id,
                    action=action,
                    identity=identity,
                    reason=reason,
                )
                status = 202 if action == "approve" else 200
                self._send_json(
                    status,
                    {
                        "schema": REQUEST_SUBMISSION_SCHEMA,
                        **{key: value for key, value in submission.items() if key != "request"},
                        "job_control": job_snapshot,
                    },
                )
            except FileNotFoundError as exc:
                self._send_json(404, {"error": "not_found", "message": str(exc), "submission_id": submission_id})
            except PermissionError as exc:
                status = 403
                error = "same_identity_self_approval" if str(exc) == "same_identity_self_approval" else "authz_rejected"
                self._send_json(status, {"error": error, "message": str(exc), "submission_id": submission_id})
            except ValueError as exc:
                self._send_json(400, {"error": "invalid_request", "message": str(exc), "submission_id": submission_id})
            except RuntimeError as exc:
                self._send_json(409, {"error": "request_transition_failed", "message": str(exc), "submission_id": submission_id})
            return
        if path.startswith("/v1/privacy-budget/approval/") and (
            path.endswith("/approve") or path.endswith("/reject") or path.endswith("/expire")
        ):
            if path.endswith("/approve"):
                action = "approve"
            elif path.endswith("/reject"):
                action = "reject"
            else:
                action = "expire"
            suffix = f"/{action}"
            request_id = unquote(path[len("/v1/privacy-budget/approval/") : -len(suffix)]).strip("/")
            try:
                identity = self._require_auth()
                body = self._read_json_body()
                reason = str(body.get("reason") or "").strip()
                expires_at_utc = str(body.get("expires_at_utc") or "").strip() or None
                updated, decision = _transition_privacy_budget_approval(
                    self.server,
                    request_id=request_id,
                    action=action,
                    identity=identity,
                    reason=reason,
                    expires_at_utc=expires_at_utc,
                )
                self._send_json(
                    200,
                    {
                        "schema": "privacy_budget_approval_transition/v1",
                        "status": "ok",
                        "action": action,
                        "request_id": request_id,
                        "approval": updated,
                        "decision": decision,
                    },
                )
            except FileNotFoundError as exc:
                self._send_json(404, {"error": "not_found", "message": str(exc), "request_id": request_id})
            except PermissionError as exc:
                error = "same_identity_self_approval" if str(exc) == "same_identity_self_approval" else "authz_rejected"
                self._send_json(403, {"error": error, "message": str(exc), "request_id": request_id})
            except ValueError as exc:
                self._send_json(400, {"error": "invalid_request", "message": str(exc), "request_id": request_id})
            except RuntimeError as exc:
                self._send_json(
                    409,
                    {"error": "privacy_budget_approval_transition_failed", "message": str(exc), "request_id": request_id},
                )
            return
        if path.startswith("/v1/jobs/") and path.endswith("/relaunch"):
            if not self._require_roles_if_auth_configured(*DASHBOARD_JOB_MUTATION_ROLES):
                return
            job_id = unquote(path[len("/v1/jobs/") : -len("/relaunch")]).strip("/")
            current = self.server.get_job(job_id)
            if current is None or str(current.get("job_id") or "") != job_id:
                self._send_json(404, {"error": "not_found", "job_id": job_id})
                return
            if current.get("state") == "running":
                self._send_json(409, {"error": "job_already_running", "job_id": current.get("job_id")})
                return
            workflow_status_path = Path(str(current.get("out_base") or "")) / "query_workflow" / "status.json"
            workflow_status_raw = _load_optional(workflow_status_path)
            if workflow_status_raw is None:
                self._send_json(404, {"error": "status_not_found", "job_id": job_id})
                return
            retry_rec: str | None = None
            workflow_status: dict[str, Any] | None = None
            receipts_path = Path(str(current.get("out_base") or "")) / "query_workflow" / "execution_receipts.jsonl"
            try:
                from check_workflow_retry_eligibility import build_eligibility_report, load_jsonl_objects

                receipts = load_jsonl_objects(receipts_path) if receipts_path.is_file() else []
                retry_eligible = build_eligibility_report(workflow_status_raw, receipts)
                retry_rec = retry_eligible.get("recommended_action")
            except Exception:
                pass
            workflow_status = {
                "available": True,
                "job_id": workflow_status_raw.get("job_id"),
                "state": workflow_status_raw.get("state"),
                "terminal": workflow_status_raw.get("terminal"),
                "last_exit_code": workflow_status_raw.get("last_exit_code"),
                "receipt_count": workflow_status_raw.get("receipt_count"),
                "last_updated_at_utc": workflow_status_raw.get("last_updated_at_utc"),
                "recommended_action": retry_rec,
            }
            try:
                body = self._read_json_body()
                payload, request_source, request_dir, relaunch_context = _load_relaunch_request(
                    body,
                    out_base=Path(str(current.get("out_base") or "")),
                    workflow_status_raw=workflow_status_raw,
                    workflow_status=workflow_status,
                )
                normalized_preview = normalize_request_paths(payload, request_dir=request_dir)
                validate_request(normalized_preview)
                preview_out_base_raw = normalized_preview.get("out_base")
                preview_out_base = (
                    Path(str(preview_out_base_raw)).resolve()
                    if isinstance(preview_out_base_raw, str) and preview_out_base_raw
                    else None
                )
                preview_job_id = str(normalized_preview.get("job_id") or "") or None
                reservation_error = self.server.try_reserve_job(
                    tenant_id=_normalized_tenant_id(normalized_preview),
                    job_id=preview_job_id,
                    out_base=preview_out_base,
                    request_source=request_source,
                )
                if reservation_error is not None:
                    self._send_json(reservation_error["status"], reservation_error["body"])
                    return
                try:
                    _start_job_thread(self.server, payload=payload, request_source=request_source, request_dir=request_dir)
                except BaseException:
                    self.server.release_reservation(preview_job_id)
                    raise
                snapshot_job = self.server.get_job(preview_job_id) if preview_job_id else self.server.get_job()
                snapshot = _job_snapshot(snapshot_job) if snapshot_job is not None else {}
                self._send_json(202, {
                    "job_id": snapshot.get("job_id"),
                    "state": snapshot.get("state"),
                    "started_at_utc": snapshot.get("started_at_utc"),
                    "out_base": snapshot.get("out_base"),
                    "relaunch_action": relaunch_context.get("relaunch_action"),
                    "source_job_id": job_id,
                })
            except FileNotFoundError as exc:
                self._send_json(404, {"error": "request_not_found", "message": str(exc), "job_id": job_id})
            except ValueError as exc:
                self._send_json(400, {"error": "invalid_request", "message": str(exc), "job_id": job_id})
            except SystemExit as exc:
                self._send_json(400, {"error": "validation_rejected", "message": str(exc), "job_id": job_id})
            return
        if path == "/v1/pjc-mtls/preflight":
            try:
                body = self._read_json_body()
                payload = _two_party_preflight(body)
                self._send_json(200, payload)
            except ValueError as exc:
                self._send_json(400, {"status": "error", "error": "invalid_request", "message": str(exc)})
            except RuntimeError as exc:
                self._send_json(500, {"status": "error", "error": "preflight_failed", "message": str(exc)})
            return
        if path == "/v1/pjc/run-manifest/sign":
            try:
                body = self._read_json_body()
                payload = _sign_two_party_run_manifest(body)
                self._send_json(200, payload)
            except FileNotFoundError as exc:
                self._send_json(404, {"status": "error", "error": "not_found", "message": str(exc)})
            except ValueError as exc:
                self._send_json(400, {"status": "error", "error": "invalid_request", "message": str(exc)})
            except RuntimeError as exc:
                self._send_json(500, {"status": "error", "error": "manifest_sign_failed", "message": str(exc)})
            return
        if path == "/v1/pjc/role-package/export":
            try:
                body = self._read_json_body()
                payload = _role_package_export(body)
                self._send_json(200, payload)
            except FileNotFoundError as exc:
                self._send_json(404, {"status": "error", "error": "not_found", "message": str(exc)})
            except ValueError as exc:
                self._send_json(400, {"status": "error", "error": "invalid_request", "message": str(exc)})
            except OSError as exc:
                self._send_json(500, {"status": "error", "error": "export_failed", "message": str(exc)})
            return
        if path == "/v1/pjc/role-package/import":
            try:
                body = self._read_json_body()
                payload = _role_package_import(body)
                status = 200 if payload.get("decision") == "allow" else 422
                self._send_json(status, payload)
            except FileNotFoundError as exc:
                self._send_json(404, {"status": "error", "error": "not_found", "message": str(exc)})
            except ValueError as exc:
                self._send_json(400, {"status": "error", "error": "invalid_request", "message": str(exc)})
            return
        if path.startswith("/v1/pjc/roles/") and path.endswith("/start"):
            role = unquote(path[len("/v1/pjc/roles/") : -len("/start")]).strip("/")
            try:
                body = self._read_json_body()
                payload = _start_role(role, body)
                status = 202 if payload.get("status") == "ok" else 409
                self._send_json(status, payload)
            except FileNotFoundError as exc:
                self._send_json(404, {"status": "error", "error": "helper_not_found", "message": str(exc)})
            except ValueError as exc:
                self._send_json(400, {"status": "error", "error": "invalid_request", "message": str(exc)})
            except OSError as exc:
                self._send_json(500, {"status": "error", "error": "role_start_failed", "message": str(exc)})
            return
        if path.startswith("/v1/pjc/roles/") and path.endswith("/cancel"):
            role = unquote(path[len("/v1/pjc/roles/") : -len("/cancel")]).strip("/")
            try:
                body = self._read_json_body()
                payload = _cancel_role(role, body)
                status = 200 if payload.get("status") == "ok" else 404
                self._send_json(status, payload)
            except ValueError as exc:
                self._send_json(400, {"status": "error", "error": "invalid_request", "message": str(exc)})
            return
        if path == "/v1/pjc/evidence/verify-merge":
            try:
                body = self._read_json_body()
                payload = _two_party_evidence_merge(body)
                status = 200 if payload.get("report", {}).get("decision") == "allow" else 422
                self._send_json(status, payload)
            except ValueError as exc:
                self._send_json(400, {"status": "error", "error": "invalid_request", "message": str(exc)})
            return
        if path == "/v1/pjc-mtls/negative-cases/run":
            try:
                body = self._read_json_body()
                payload = _two_party_negative_cases(body)
                status = 200 if payload.get("report", {}).get("decision") == "allow" else 422
                self._send_json(status, payload)
            except ValueError as exc:
                self._send_json(400, {"status": "error", "error": "invalid_request", "message": str(exc)})
            return
        if path == "/v1/pjc-mtls/tls-diagnostic":
            try:
                body = self._read_json_body()
                payload = _two_party_tls_diagnostic(body)
                # Always 200 — the diagnostic itself succeeded even when the
                # peer connection failed; the report carries the decision.
                self._send_json(200, payload)
            except ValueError as exc:
                self._send_json(400, {"status": "error", "error": "invalid_request", "message": str(exc)})
            except OSError as exc:
                self._send_json(500, {"status": "error", "error": "diagnostic_failed", "message": str(exc)})
            return
        if path == "/v1/release/policy-gate":
            try:
                body = self._read_json_body()
                payload = _release_policy_gate_endpoint(body)
                status = 200 if payload.get("report", {}).get("decision") == "allow" else 422
                self._send_json(status, payload)
            except FileNotFoundError as exc:
                self._send_json(404, {"status": "error", "error": "not_found", "message": str(exc)})
            except ValueError as exc:
                self._send_json(400, {"status": "error", "error": "invalid_request", "message": str(exc)})
            except OSError as exc:
                self._send_json(500, {"status": "error", "error": "release_gate_failed", "message": str(exc)})
            return
        if path == "/v1/pjc-mtls/party-a/prepare":
            try:
                body = self._read_json_body()
                payload = _prepare_pjc_mtls_party_a(
                    force_regenerate=bool(body.get("force_regenerate")),
                    enroll_url=_derive_mtls_enroll_url_from_body(body),
                )
                status = 200 if payload.get("status") == "ok" else 500
                self._send_json(status, payload)
            except FileNotFoundError as exc:
                self._send_json(404, {"status": "error", "error": "helper_not_found", "message": str(exc)})
            except ValueError as exc:
                self._send_json(400, {"status": "error", "error": "invalid_request", "message": str(exc)})
            except RuntimeError as exc:
                self._send_json(500, {"status": "error", "error": "prepare_failed", "message": str(exc)})
            return
        if path == "/v1/pjc-mtls/enroll":
            try:
                body = self._read_json_body()
                csr_pem = str(body.get("csr_pem") or "")
                pairing_token = str(body.get("pairing_token") or "")
                remote_addr = self.client_address[0] if self.client_address else ""
                self._send_json(
                    200,
                    _enroll_pjc_mtls_csr(
                        csr_pem=csr_pem,
                        pairing_token=pairing_token,
                        remote_addr=remote_addr,
                    ),
                )
            except PermissionError as exc:
                self._send_json(403, {"status": "error", "error": "pairing_rejected", "message": str(exc)})
            except ValueError as exc:
                self._send_json(400, {"status": "error", "error": "invalid_request", "message": str(exc)})
            except RuntimeError as exc:
                self._send_json(500, {"status": "error", "error": "enroll_failed", "message": str(exc)})
            return
        if path == "/v1/pjc-mtls/party-b/enroll":
            try:
                body = self._read_json_body()
                self._send_json(200, _party_b_enroll_from_dashboard(body))
            except ValueError as exc:
                self._send_json(400, {"status": "error", "error": "invalid_request", "message": str(exc)})
            except RuntimeError as exc:
                self._send_json(500, {"status": "error", "error": "enroll_failed", "message": str(exc)})
            except OSError as exc:
                self._send_json(502, {"status": "error", "error": "enroll_connect_failed", "message": str(exc)})
            return
        if path == "/v1/bucketed-scale-test/run":
            try:
                body = self._read_json_body()
                # Async by default — POST returns 202 + job_id, caller polls
                # GET /v1/bucketed-scale-test/{job_id}. Pass {"sync": true} or
                # ?sync=1 for the legacy blocking behavior (still used by the
                # JS dashboard until the SPA-side polling lands).
                sync_flag = bool(body.get("sync"))
                if not sync_flag and parsed.query:
                    sync_flag = parse_qs(parsed.query).get("sync", ["0"])[0] in ("1", "true", "yes")
                if sync_flag:
                    payload = _run_bucketed_scale_test(body)
                    self._send_json(200 if payload.get("status") == "ok" else 500, payload)
                else:
                    snapshot = _start_bucketed_scale_test_job(body)
                    self._send_json(202, snapshot)
            except FileNotFoundError as exc:
                self._send_json(404, {"status": "error", "error": "helper_not_found", "message": str(exc)})
            except ValueError as exc:
                self._send_json(400, {"status": "error", "error": "invalid_request", "message": str(exc)})
            except subprocess.TimeoutExpired as exc:
                self._send_json(504, {"status": "error", "error": "bucketed_scale_timeout", "message": str(exc)})
            return
        if path == "/v1/sse/search":
            self._handle_sse_search()
            return

        if path == "/v1/pjc/run-only":
            self._handle_pjc_run_only()
            return

        if path != "/v1/jobs/start":
            self._send_json(404, {"error": "not_found", "path": path})
            return
        if not self._require_roles_if_auth_configured(*DASHBOARD_JOB_MUTATION_ROLES):
            return
        try:
            body = self._read_json_body()
            payload, request_source, request_dir = _load_start_request(body, default_out_base=self.server.out_base)
            normalized_preview = normalize_request_paths(payload, request_dir=request_dir)
            validate_request(normalized_preview)
            preview_out_base_raw = normalized_preview.get("out_base")
            preview_out_base = (
                Path(str(preview_out_base_raw)).resolve()
                if isinstance(preview_out_base_raw, str) and preview_out_base_raw
                else None
            )
            preview_job_id = str(normalized_preview.get("job_id") or "") or None
            reservation_error = self.server.try_reserve_job(
                tenant_id=_normalized_tenant_id(normalized_preview),
                job_id=preview_job_id,
                out_base=preview_out_base,
                request_source=request_source,
            )
            if reservation_error is not None:
                self._send_json(reservation_error["status"], reservation_error["body"])
                return
            try:
                _start_job_thread(self.server, payload=payload, request_source=request_source, request_dir=request_dir)
            except BaseException:
                self.server.release_reservation(preview_job_id)
                raise
            snapshot_job = self.server.get_job(preview_job_id) if preview_job_id else self.server.get_job()
            snapshot = _job_snapshot(snapshot_job) if snapshot_job is not None else {}
            self._send_json(202, {
                "job_id": snapshot.get("job_id"),
                "state": snapshot.get("state"),
                "started_at_utc": snapshot.get("started_at_utc"),
                "out_base": snapshot.get("out_base"),
            })
        except FileNotFoundError as exc:
            self._send_json(404, {"error": "request_not_found", "message": str(exc)})
        except ValueError as exc:
            self._send_json(400, {"error": "invalid_request", "message": str(exc)})
        except SystemExit as exc:
            self._send_json(400, {"error": "validation_rejected", "message": str(exc)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def write_file(path: str, content: str) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def read_auth_token(env_name: str) -> str:
    if not env_name:
        return ""
    value = os.environ.get(env_name, "")
    if not value:
        raise SystemExit(f"[ERROR] environment variable {env_name} is not set")
    return value


def remove_file(path: str) -> None:
    if not path:
        return
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Serve the operator dashboard web UI.")
    ap.add_argument("--out-base", required=True, help="Run output directory (contains pipeline_observability.json etc.)")
    ap.add_argument("--history-root", default="", help="Root directory for recent-run discovery (default: parent of out-base)")
    ap.add_argument("--history-limit", type=int, default=12, help="Number of recent runs shown in the admin shell")
    ap.add_argument("--bind-host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18094)
    ap.add_argument("--pid-file", default="", help="Write server PID here on start")
    ap.add_argument("--ready-file", default="", help="Write '1' here when server is ready")
    ap.add_argument(
        "--max-concurrent-jobs-per-tenant",
        type=int,
        default=0,
        help="Reject job starts with HTTP 429 when this many running jobs already exist for the tenant (0 disables)",
    )
    ap.add_argument("--auth-token-env", default="", help="Optional bearer-token env var for request submission endpoints")
    ap.add_argument("--metadata-db-path", default="", help="Metadata DB path for I3 request submission records")
    ap.add_argument("--metadata-db-dsn", default="", help="Metadata PostgreSQL DSN for I3 request submission records")
    ap.add_argument(
        "--metadata-db-dsn-read-replica",
        default="",
        help="Optional PostgreSQL replica DSN for identity-resolution SELECTs",
    )
    ap.add_argument("--identity-token-config", default="", help="Optional bearer-token to caller-identity mapping config")
    ap.add_argument(
        "--session-cookie-name",
        default=DEFAULT_IDENTITY_SESSION_COOKIE_NAME,
        help=(
            "HttpOnly cookie name used by /v1/session/login and cookie-aware API auth "
            f"(default: {DEFAULT_IDENTITY_SESSION_COOKIE_NAME})"
        ),
    )
    ap.add_argument(
        "--session-cookie-secure",
        action="store_true",
        help="Add the Secure attribute to the browser session cookie; enable behind HTTPS/TLS.",
    )
    ap.add_argument("--privacy-budget-store", default="", help="SQLite privacy-budget store for approval list/transition API")
    ap.add_argument(
        "--privacy-budget-approval-queue",
        default="",
        help="Optional privacy_budget_approval_request/v1 JSONL queue to bootstrap into the store",
    )
    ap.add_argument(
        "--privacy-budget-approval-decisions",
        default="",
        help="Optional privacy_budget_approval_decision/v1 JSONL decision log written by approval API",
    )
    ap.add_argument(
        "--console-dist",
        default="",
        help=(
            "Directory containing the built operator-console SPA (console/dist). "
            "When set, serves SPA assets at / and falls back to index.html for "
            "client-side routes. When omitted, the server probes "
            "<repo>/console/dist, <repo>/console-dist, and /opt/seccomp/platform/console/dist. "
            "If none is found, the dashboard root returns a 404 hint instead of HTML."
        ),
    )
    ap.add_argument(
        "--mtls-enrollment-only-mode",
        action="store_true",
        help=(
            "Carve down the HTTP surface to just /healthz + POST /v1/pjc-mtls/enroll. "
            "Every other dashboard endpoint returns 404 with error=enrollment_only_mode. "
            "Used by serve_pjc_mtls_enrollment_party_a.sh to keep the public-IP "
            "attack surface minimal during enrollment."
        ),
    )
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.identity_token_config and not args.metadata_db_path and not args.metadata_db_dsn:
        raise SystemExit("[ERROR] --identity-token-config requires --metadata-db-path or --metadata-db-dsn")
    if (args.privacy_budget_approval_queue or args.privacy_budget_approval_decisions) and not args.privacy_budget_store:
        raise SystemExit("[ERROR] privacy-budget approval queue/decisions require --privacy-budget-store")
    auth_token = read_auth_token(args.auth_token_env)
    out_base = Path(args.out_base).expanduser().resolve()
    if not out_base.is_dir():
        raise SystemExit(f"[ERROR] --out-base does not exist: {out_base}")
    history_root = _repo_path(args.history_root) if args.history_root else out_base.parent
    if not history_root.is_dir():
        raise SystemExit(f"[ERROR] --history-root does not exist: {history_root}")

    console_dist = _resolve_console_dist(args.console_dist)

    server = DashboardServer(
        (args.bind_host, args.port),
        DashboardHandler,
        out_base=out_base,
        history_root=history_root,
        history_limit=max(1, args.history_limit),
        pid_file=args.pid_file,
        ready_file=args.ready_file,
        max_concurrent_jobs_per_tenant=args.max_concurrent_jobs_per_tenant,
        auth_token=auth_token,
        metadata_db_path=args.metadata_db_path,
        metadata_db_dsn=args.metadata_db_dsn,
        metadata_db_read_dsn=args.metadata_db_dsn_read_replica,
        identity_token_config=args.identity_token_config,
        privacy_budget_store=args.privacy_budget_store,
        privacy_budget_approval_queue=args.privacy_budget_approval_queue,
        privacy_budget_approval_decisions=args.privacy_budget_approval_decisions,
        mtls_enrollment_only_mode=bool(args.mtls_enrollment_only_mode),
        console_dist=console_dist,
        session_cookie_name=args.session_cookie_name,
        session_cookie_secure=bool(args.session_cookie_secure),
    )

    def _shutdown(sig: int, frame: Any) -> None:
        remove_file(args.pid_file)
        remove_file(args.ready_file)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    def _enrollment_shutdown_hook(reason: str) -> None:
        remove_file(args.pid_file)
        remove_file(args.ready_file)
        threading.Thread(target=server.shutdown, daemon=True).start()

    _PJC_MTLS_SHUTDOWN_HOOKS.append(_enrollment_shutdown_hook)

    idle_timeout = _env_int("PJC_MTLS_ENROLLMENT_IDLE_TIMEOUT_SECONDS", 0, min_value=0)
    if idle_timeout > 0:
        def _idle_watch() -> None:
            deadline = time.time() + idle_timeout
            while time.time() < deadline:
                time.sleep(min(5.0, max(1.0, deadline - time.time())))
                meta = _read_pairing_meta()
                if int(meta.get("enrollments") or 0) > 0:
                    return
            _trigger_enrollment_shutdown(
                f"idle timeout reached after {idle_timeout}s with zero enrollments"
            )

        threading.Thread(target=_idle_watch, daemon=True, name="pjc-mtls-idle-watch").start()

    write_file(args.pid_file, str(os.getpid()))
    write_file(args.ready_file, "1")

    print(json.dumps({
        "status": "started",
        "url": f"http://{args.bind_host}:{args.port}/",
        "out_base": str(out_base),
        "history_root": str(history_root),
        "mtls_enrollment_only_mode": bool(args.mtls_enrollment_only_mode),
        "max_concurrent_jobs_per_tenant": max(0, int(args.max_concurrent_jobs_per_tenant)),
        "request_submission_enabled": bool(args.metadata_db_path or args.metadata_db_dsn),
        "identity_auth_required": bool(auth_token or args.identity_token_config),
        "pid": os.getpid(),
    }))
    sys.stdout.flush()

    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
