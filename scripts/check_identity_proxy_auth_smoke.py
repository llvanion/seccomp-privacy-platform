#!/usr/bin/env python3
"""Smoke-test identity proxy fail-closed auth and header injection."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

from api_identity import DEFAULT_IDENTITY_SESSION_COOKIE_NAME
from metadata_db import apply_migrations, connect_db
from runtime_service_helpers import available_port
from serve_identity_proxy import IdentityProxyHandler, IdentityProxyServer


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "identity_proxy_auth_smoke/v1"
TOKEN_ENV = "SECCOMP_IDENTITY_PROXY_AUTH_SMOKE_TOKEN"
TOKEN_VALUE = "identity-proxy-auth-smoke-token"


class EchoHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        body = json.dumps(
            {
                "path": self.path,
                "headers": {key: value for key, value in self.headers.items()},
            },
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def request_json(url: str, *, headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return int(exc.code), json.loads(raw) if raw else {"error": "empty_error_response"}


def seed_identity(db_path: Path, token_config_path: Path) -> None:
    now = utc_now_iso()
    os.environ[TOKEN_ENV] = TOKEN_VALUE
    token_config_path.write_text(
        json.dumps(
            {
                "schema": "api_identity_token_map/v1",
                "tokens": [
                    {"token_env": TOKEN_ENV, "issuer": "local", "subject": "service:proxy-smoke"},
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with connect_db(str(db_path)) as conn:
        apply_migrations(conn)
        conn.execute(
            "INSERT OR IGNORE INTO tenants(tenant_id, created_at_utc, source) VALUES(?, ?, ?)",
            ("proxy_tenant", now, "identity_proxy_auth_smoke"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO datasets(dataset_id, tenant_id, created_at_utc, source) VALUES(?, ?, ?, ?)",
            ("proxy_dataset", "proxy_tenant", now, "identity_proxy_auth_smoke"),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO services(
              service_id, tenant_id, dataset_id, service_type, transport, created_at_utc
            ) VALUES(?, ?, ?, ?, ?, ?)
            """,
            ("proxy_service", "proxy_tenant", "proxy_dataset", "metadata", "http", now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO callers(caller, tenant_id, created_at_utc, source) VALUES(?, ?, ?, ?)",
            ("proxy_caller", "proxy_tenant", now, "identity_proxy_auth_smoke"),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO caller_identities(
              caller, issuer, subject, subject_type, service_id, display_name,
              platform_roles_json, enabled, source, created_at_utc
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "proxy_caller",
                "local",
                "service:proxy-smoke",
                "service_account",
                "proxy_service",
                "Identity Proxy Smoke",
                json.dumps(["query_submitter"]),
                1,
                "identity_proxy_auth_smoke",
                now,
            ),
        )
        conn.commit()


def add_finding(findings: list[dict[str, Any]], message: str, actual: Any) -> None:
    findings.append({"message": message, "actual": actual})


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test identity proxy authentication semantics")
    parser.add_argument("--out", default="", help="Optional path for the JSON report")
    args = parser.parse_args()

    findings: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="seccomp_identity_proxy_auth.") as tmp_raw:
        tmp_dir = Path(tmp_raw)
        db_path = tmp_dir / "metadata.db"
        token_config_path = tmp_dir / "identity_tokens.json"
        seed_identity(db_path, token_config_path)

        upstream_port = available_port()
        proxy_port = available_port()
        upstream = ThreadingHTTPServer(("127.0.0.1", upstream_port), EchoHandler)
        proxy = IdentityProxyServer(
            ("127.0.0.1", proxy_port),
            IdentityProxyHandler,
            upstreams={"metadata": f"http://127.0.0.1:{upstream_port}"},
            identity_token_config=str(token_config_path),
            metadata_db_path=str(db_path),
            admin_token="",
            log_identity=False,
        )
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        upstream_thread.start()
        proxy_thread.start()
        time.sleep(0.1)
        try:
            base = f"http://127.0.0.1:{proxy_port}/metadata/echo"
            unauth_status, unauth = request_json(base)
            checks["unauth_status"] = unauth_status
            if unauth_status != 401:
                add_finding(findings, "identity proxy allowed unauthenticated request while auth is configured", unauth)

            spoof_status, spoof = request_json(
                base,
                headers={
                    "Authorization": f"Bearer {TOKEN_VALUE}",
                    "X-Identity-Caller": "attacker",
                    "X-Identity-Resolved": "true",
                },
            )
            spoof_headers = spoof.get("headers") if isinstance(spoof, dict) else {}
            checks["spoof_status"] = spoof_status
            checks["spoofed_header_overwritten"] = (spoof_headers or {}).get("X-Identity-Caller") == "proxy_caller"
            if spoof_status != 200 or (spoof_headers or {}).get("X-Identity-Caller") != "proxy_caller":
                add_finding(findings, "identity proxy did not overwrite spoofed X-Identity headers", spoof)

            cookie_status, cookie = request_json(
                base,
                headers={"Cookie": f"{DEFAULT_IDENTITY_SESSION_COOKIE_NAME}={TOKEN_VALUE}"},
            )
            cookie_headers = cookie.get("headers") if isinstance(cookie, dict) else {}
            checks["cookie_status"] = cookie_status
            checks["cookie_identity_caller"] = (cookie_headers or {}).get("X-Identity-Caller")
            checks["cookie_forwarded_authorization"] = bool((cookie_headers or {}).get("Authorization"))
            if cookie_status != 200 or (cookie_headers or {}).get("X-Identity-Caller") != "proxy_caller":
                add_finding(findings, "identity proxy did not resolve identity from session cookie", cookie)
            if (cookie_headers or {}).get("Authorization"):
                add_finding(findings, "cookie-only proxy request forwarded an Authorization header", cookie)
        finally:
            proxy.shutdown()
            upstream.shutdown()
            proxy.server_close()
            upstream.server_close()

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "status": "fail" if findings else "ok",
        "checks": checks,
        "finding_count": len(findings),
        "findings": findings,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = (REPO_ROOT / out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
