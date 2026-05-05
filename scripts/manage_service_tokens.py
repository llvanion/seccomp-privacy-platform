#!/usr/bin/env python3
"""
A4: Service identity token lifecycle manager.

Issues, verifies, lists, and revokes short-lived service identity tokens.
Tokens authenticate service-to-service calls (key agent ↔ pipeline,
recovery service ↔ export, external KMS ↔ key agent) without requiring
manually shared static env tokens.

Token format (dot-separated):
  base64url(header_json).base64url(payload_json).hmac_sha256_hex

Header: {"alg":"HS256","typ":"svc-token"}
Payload: {"jti":"<uuid>","svc":"<service_id>","iat":<unix>,"exp":<unix>,"scp":"<scope>"}

Usage:
  python3 scripts/manage_service_tokens.py issue \
    --token-store tmp/service_tokens.db \
    --service-id orders-recovery \
    --signing-key-env SERVICE_TOKEN_KEY \
    --ttl-seconds 3600

  python3 scripts/manage_service_tokens.py verify \
    --token-store tmp/service_tokens.db \
    --signing-key-env SERVICE_TOKEN_KEY \
    --token "<token>"

  python3 scripts/manage_service_tokens.py revoke \
    --token-store tmp/service_tokens.db \
    --jti "<jti>" \
    --reason "key rotation"

  python3 scripts/manage_service_tokens.py list \
    --token-store tmp/service_tokens.db \
    --service-id orders-recovery
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "service_token_report/v1"
TOKEN_ALG = "HS256"
TOKEN_TYP = "svc-token"
MIGRATION = """
CREATE TABLE IF NOT EXISTS service_tokens (
    id INTEGER PRIMARY KEY,
    jti TEXT NOT NULL UNIQUE,
    service_id TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'service',
    issued_at_utc TEXT NOT NULL,
    expires_at_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    token_hash TEXT NOT NULL,
    issuer TEXT,
    notes TEXT,
    revoked_at_utc TEXT,
    revocation_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_svc_tokens_service ON service_tokens (service_id);
CREATE INDEX IF NOT EXISTS idx_svc_tokens_status ON service_tokens (status);
CREATE INDEX IF NOT EXISTS idx_svc_tokens_expires ON service_tokens (expires_at_utc);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unix_now() -> int:
    return int(time.time())


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    return base64.urlsafe_b64decode(s)


def _sign(signing_key: str, message: str) -> str:
    return hmac.new(signing_key.encode(), message.encode(), hashlib.sha256).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _open_store(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(MIGRATION)
    conn.commit()
    return conn


def _load_signing_key(env_name: str) -> str:
    key = os.environ.get(env_name, "")
    if not key:
        raise SystemExit(f"[ERROR] signing key env var not set: {env_name}")
    return key


def issue_token(
    *,
    store_path: str,
    service_id: str,
    signing_key: str,
    ttl_seconds: int,
    scope: str,
    issuer: str,
    notes: str,
) -> dict[str, Any]:
    jti = str(uuid.uuid4())
    now = _unix_now()
    exp = now + ttl_seconds
    issued_at = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    header = _b64url(json.dumps({"alg": TOKEN_ALG, "typ": TOKEN_TYP}, separators=(",", ":")).encode())
    payload = _b64url(json.dumps(
        {"jti": jti, "svc": service_id, "iat": now, "exp": exp, "scp": scope},
        separators=(",", ":"),
    ).encode())
    message = f"{header}.{payload}"
    signature = _sign(signing_key, message)
    token = f"{message}.{signature}"
    t_hash = _token_hash(token)

    conn = _open_store(store_path)
    try:
        conn.execute(
            """
            INSERT INTO service_tokens
              (jti, service_id, scope, issued_at_utc, expires_at_utc, status, token_hash, issuer, notes)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (jti, service_id, scope, issued_at, expires_at, t_hash, issuer or None, notes or None),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": _utc_now(),
        "operation": "issue",
        "status": "ok",
        "service_id": service_id,
        "jti": jti,
        "issued_at_utc": issued_at,
        "expires_at_utc": expires_at,
        "scope": scope,
        "token_hash": t_hash,
        "token": token,
        "error": None,
        "tokens": None,
    }


def verify_token(
    *,
    store_path: str,
    token: str,
    signing_key: str,
) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        return _error_report("verify", "", "invalid token format: expected 3 dot-separated parts")

    header_b64, payload_b64, signature = parts
    message = f"{header_b64}.{payload_b64}"
    expected_sig = _sign(signing_key, message)
    if not hmac.compare_digest(expected_sig, signature):
        return _error_report("verify", "", "signature verification failed")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception as exc:
        return _error_report("verify", "", f"payload decode failed: {exc}")

    service_id = str(payload.get("svc") or "")
    jti = str(payload.get("jti") or "")
    exp = int(payload.get("exp") or 0)
    now = _unix_now()

    if exp < now:
        return {
            "schema": REPORT_SCHEMA,
            "generated_at_utc": _utc_now(),
            "operation": "verify",
            "status": "expired",
            "service_id": service_id,
            "jti": jti,
            "issued_at_utc": None,
            "expires_at_utc": None,
            "scope": str(payload.get("scp") or ""),
            "token_hash": _token_hash(token),
            "token": None,
            "error": "token has expired",
            "tokens": None,
        }

    t_hash = _token_hash(token)
    conn = _open_store(store_path)
    try:
        row = conn.execute(
            "SELECT status, issued_at_utc, expires_at_utc, scope, revocation_reason FROM service_tokens WHERE jti=?",
            (jti,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return _error_report("verify", service_id, "token jti not found in store")
    if str(row["status"]) != "active":
        return {
            "schema": REPORT_SCHEMA,
            "generated_at_utc": _utc_now(),
            "operation": "verify",
            "status": "revoked",
            "service_id": service_id,
            "jti": jti,
            "issued_at_utc": str(row["issued_at_utc"]),
            "expires_at_utc": str(row["expires_at_utc"]),
            "scope": str(row["scope"]),
            "token_hash": t_hash,
            "token": None,
            "error": str(row["revocation_reason"] or "token has been revoked"),
            "tokens": None,
        }

    return {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": _utc_now(),
        "operation": "verify",
        "status": "ok",
        "service_id": service_id,
        "jti": jti,
        "issued_at_utc": str(row["issued_at_utc"]),
        "expires_at_utc": str(row["expires_at_utc"]),
        "scope": str(row["scope"]),
        "token_hash": t_hash,
        "token": None,
        "error": None,
        "tokens": None,
    }


def revoke_token(
    *,
    store_path: str,
    jti: str,
    reason: str,
) -> dict[str, Any]:
    ts = _utc_now()
    conn = _open_store(store_path)
    try:
        row = conn.execute(
            "SELECT service_id, status FROM service_tokens WHERE jti=?", (jti,)
        ).fetchone()
        if row is None:
            return _error_report("revoke", "", f"jti not found: {jti}")
        service_id = str(row["service_id"])
        conn.execute(
            "UPDATE service_tokens SET status='revoked', revoked_at_utc=?, revocation_reason=? WHERE jti=?",
            (ts, reason or "operator revocation", jti),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": ts,
        "operation": "revoke",
        "status": "ok",
        "service_id": service_id,
        "jti": jti,
        "issued_at_utc": None,
        "expires_at_utc": None,
        "scope": None,
        "token_hash": None,
        "token": None,
        "error": None,
        "tokens": None,
    }


def list_tokens(
    *,
    store_path: str,
    service_id: str,
    status_filter: str,
    include_expired: bool,
) -> dict[str, Any]:
    conn = _open_store(store_path)
    try:
        query = "SELECT jti, service_id, scope, status, issued_at_utc, expires_at_utc, revoked_at_utc, revocation_reason, token_hash FROM service_tokens WHERE 1=1"
        params: list[Any] = []
        if service_id:
            query += " AND service_id=?"
            params.append(service_id)
        if status_filter:
            query += " AND status=?"
            params.append(status_filter)
        if not include_expired:
            query += " AND expires_at_utc >= ?"
            params.append(_utc_now())
        query += " ORDER BY issued_at_utc DESC"
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    tokens = [
        {
            "jti": str(r["jti"]),
            "service_id": str(r["service_id"]),
            "scope": str(r["scope"]),
            "status": str(r["status"]),
            "issued_at_utc": str(r["issued_at_utc"]),
            "expires_at_utc": str(r["expires_at_utc"]),
            "revoked_at_utc": str(r["revoked_at_utc"]) if r["revoked_at_utc"] else None,
            "revocation_reason": str(r["revocation_reason"]) if r["revocation_reason"] else None,
            "token_hash": str(r["token_hash"]),
        }
        for r in rows
    ]

    return {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": _utc_now(),
        "operation": "list",
        "status": "ok",
        "service_id": service_id or "*",
        "jti": None,
        "issued_at_utc": None,
        "expires_at_utc": None,
        "scope": None,
        "token_hash": None,
        "token": None,
        "error": None,
        "tokens": tokens,
    }


def _error_report(operation: str, service_id: str, msg: str) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": _utc_now(),
        "operation": operation,
        "status": "error",
        "service_id": service_id,
        "jti": None,
        "issued_at_utc": None,
        "expires_at_utc": None,
        "scope": None,
        "token_hash": None,
        "token": None,
        "error": msg,
        "tokens": None,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="A4: Service identity token lifecycle manager")
    ap.add_argument("--token-store", required=True, help="Path to SQLite token store")
    ap.add_argument("--output", default="", help="Write JSON report to path (default: stdout)")
    sub = ap.add_subparsers(dest="command", required=True)

    iss = sub.add_parser("issue", help="Issue a new service identity token")
    iss.add_argument("--token-store", required=True)
    iss.add_argument("--service-id", required=True)
    iss.add_argument("--signing-key-env", required=True, help="Env var holding the HMAC signing key")
    iss.add_argument("--ttl-seconds", type=int, default=3600)
    iss.add_argument("--scope", default="service")
    iss.add_argument("--issuer", default="")
    iss.add_argument("--notes", default="")
    iss.add_argument("--output", default="")

    ver = sub.add_parser("verify", help="Verify a service token")
    ver.add_argument("--token-store", required=True)
    ver.add_argument("--token", required=True)
    ver.add_argument("--signing-key-env", required=True)
    ver.add_argument("--output", default="")

    rev = sub.add_parser("revoke", help="Revoke a service token by jti")
    rev.add_argument("--token-store", required=True)
    rev.add_argument("--jti", required=True)
    rev.add_argument("--reason", default="")
    rev.add_argument("--output", default="")

    lst = sub.add_parser("list", help="List service tokens")
    lst.add_argument("--token-store", required=True)
    lst.add_argument("--service-id", default="")
    lst.add_argument("--status", default="", help="Filter by status (active/revoked)")
    lst.add_argument("--include-expired", action="store_true")
    lst.add_argument("--output", default="")

    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    cmd = args.command
    store = args.token_store

    if cmd == "issue":
        key = _load_signing_key(args.signing_key_env)
        report = issue_token(
            store_path=store, service_id=args.service_id, signing_key=key,
            ttl_seconds=args.ttl_seconds, scope=args.scope, issuer=args.issuer, notes=args.notes,
        )
    elif cmd == "verify":
        key = _load_signing_key(args.signing_key_env)
        report = verify_token(store_path=store, token=args.token, signing_key=key)
    elif cmd == "revoke":
        report = revoke_token(store_path=store, jti=args.jti, reason=args.reason)
    elif cmd == "list":
        report = list_tokens(
            store_path=store, service_id=args.service_id,
            status_filter=args.status, include_expired=args.include_expired,
        )
    else:
        raise SystemExit(f"unknown command: {cmd}")

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if report["status"] in ("ok",) else 1


if __name__ == "__main__":
    raise SystemExit(main())
