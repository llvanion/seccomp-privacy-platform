#!/usr/bin/env python3
"""Smoke-test the console's HttpOnly browser session path.

The security property here is deliberately narrow: when the console is served
same-origin by ``serve_operator_dashboard.py``, a user can exchange an identity
bearer token for an HttpOnly/SameSite cookie and then make API reads without
JavaScript retaining the bearer token in sessionStorage or an Authorization
header.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import serve_operator_dashboard as dashboard
from metadata_db import apply_migrations, connect_db
from runtime_service_helpers import available_port


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "console_browser_session_check/v1"
TOKEN_ENV = "SECCOMP_CONSOLE_BROWSER_SESSION_TOKEN"
TOKEN_VALUE = "console-browser-session-token"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def request_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str = "",
) -> tuple[int, dict[str, Any], dict[str, str]]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return int(response.status), json.loads(raw) if raw else {}, dict(response.headers.items())
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return int(exc.code), json.loads(raw) if raw else {"error": "empty_error_response"}, dict(exc.headers.items())


def seed_identity_metadata(db_path: Path, *, token_config_path: Path) -> None:
    now = utc_now_iso()
    os.environ[TOKEN_ENV] = TOKEN_VALUE
    token_config_path.write_text(
        json.dumps(
            {
                "schema": "api_identity_token_map/v1",
                "tokens": [
                    {"token_env": TOKEN_ENV, "issuer": "local", "subject": "user:console-session"},
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
            ("console_tenant", now, "console_browser_session_smoke"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO callers(caller, tenant_id, created_at_utc, source) VALUES(?, ?, ?, ?)",
            ("console_operator", "console_tenant", now, "console_browser_session_smoke"),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO caller_identities(
              caller, issuer, subject, subject_type, display_name,
              platform_roles_json, enabled, source, created_at_utc
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "console_operator",
                "local",
                "user:console-session",
                "user",
                "Console Session Operator",
                json.dumps(["platform_admin"]),
                1,
                "console_browser_session_smoke",
                now,
            ),
        )
        conn.commit()


def seed_run(out_base: Path) -> None:
    a_psi = out_base / "a_psi_run"
    qwf = out_base / "query_workflow"
    a_psi.mkdir(parents=True, exist_ok=True)
    qwf.mkdir(parents=True, exist_ok=True)
    (a_psi / "public_report.json").write_text(
        json.dumps(
            {
                "schema": "public_report/v2",
                "generated_at_utc": "2026-06-02T00:00:00Z",
                "policy_version": "console-browser-session-smoke",
                "job_id": "console-browser-session-smoke",
                "correlation_id": "console-browser-session-smoke",
                "caller": "console_operator",
                "released": True,
                "reason": "ok",
                "reason_code": "ok",
                "window": {"start": None, "end": None},
                "k_threshold": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (qwf / "status.json").write_text(
        json.dumps(
            {
                "schema": "query_workflow_status/v1",
                "workflow": "query_workflow",
                "mode": "execute",
                "job_id": "console-browser-session-smoke",
                "out_base": str(out_base),
                "state": "completed",
                "terminal": True,
                "last_updated_at_utc": "2026-06-02T00:00:00Z",
                "latest_receipt_id": "receipt-1",
                "receipt_count": 1,
                "last_exit_code": 0,
                "artifact_summary": {},
                "public_report_available": True,
                "audit_chain_available": False,
                "caller": "console_operator",
                "tenant_id": "console_tenant",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def build_report(*, checks: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "status": "fail" if findings else "ok",
        "checks": checks,
        "finding_count": len(findings),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test HttpOnly console browser sessions.")
    parser.add_argument("--out", default="", help="Optional path for the JSON report")
    args = parser.parse_args()

    findings: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="seccomp_console_session.") as tmp_raw:
        tmp_dir = Path(tmp_raw)
        out_base = tmp_dir / "run"
        out_base.mkdir(parents=True)
        seed_run(out_base)
        db_path = tmp_dir / "metadata.db"
        token_config_path = tmp_dir / "identity_tokens.json"
        seed_identity_metadata(db_path, token_config_path=token_config_path)

        port = available_port()
        server = dashboard.DashboardServer(
            ("127.0.0.1", port),
            dashboard.DashboardHandler,
            out_base=out_base,
            history_root=tmp_dir,
            history_limit=4,
            pid_file="",
            ready_file="",
            max_concurrent_jobs_per_tenant=0,
            metadata_db_path=str(db_path),
            identity_token_config=str(token_config_path),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)
        cookie_jar = CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar),
            urllib.request.ProxyHandler({}),
        )
        base = f"http://127.0.0.1:{port}"
        try:
            unauth_status, unauth, _ = request_json(opener, f"{base}/v1/dashboard")
            checks["unauth_dashboard_status"] = unauth_status
            if unauth_status != 403:
                findings.append({"message": "dashboard allowed request without bearer or session cookie", "actual": unauth})

            login_status, login, login_headers = request_json(
                opener,
                f"{base}/v1/session/login",
                method="POST",
                payload={"bearer_token": TOKEN_VALUE, "max_age_seconds": 600},
            )
            set_cookie = login_headers.get("Set-Cookie", "")
            checks["login_status"] = login_status
            checks["set_cookie_contains_httponly"] = "HttpOnly" in set_cookie
            checks["set_cookie_contains_samesite_strict"] = "SameSite=Strict" in set_cookie
            checks["login_auth_source"] = (login.get("authenticated_identity") or {}).get("auth_source")
            if login_status != 200:
                findings.append({"message": "session login failed", "actual": login})
            if "HttpOnly" not in set_cookie or "SameSite=Strict" not in set_cookie:
                findings.append({"message": "session cookie missing HttpOnly/SameSite=Strict", "actual": set_cookie})

            cookie_names = sorted(cookie.name for cookie in cookie_jar)
            checks["cookie_names"] = cookie_names
            if dashboard.DEFAULT_IDENTITY_SESSION_COOKIE_NAME not in cookie_names:
                findings.append({"message": "identity session cookie was not stored by the HTTP client", "actual": cookie_names})

            cookie_status, cookie_payload, _ = request_json(opener, f"{base}/v1/dashboard")
            checks["cookie_dashboard_status"] = cookie_status
            checks["cookie_dashboard_schema"] = cookie_payload.get("schema")
            if cookie_status != 200:
                findings.append({"message": "cookie-only dashboard request failed", "actual": cookie_payload})

            session_status, session_payload, _ = request_json(opener, f"{base}/v1/session")
            checks["session_status"] = session_status
            checks["session_auth_source"] = (session_payload.get("authenticated_identity") or {}).get("auth_source")
            if session_status != 200 or (session_payload.get("authenticated_identity") or {}).get("auth_source") != "httponly_cookie":
                findings.append({"message": "session status did not resolve through HttpOnly cookie", "actual": session_payload})

            logout_status, logout_payload, logout_headers = request_json(opener, f"{base}/v1/session/logout", method="POST", payload={})
            checks["logout_status"] = logout_status
            checks["logout_set_cookie"] = logout_headers.get("Set-Cookie", "")
            if logout_status != 200 or "Max-Age=0" not in logout_headers.get("Set-Cookie", ""):
                findings.append({"message": "logout did not clear session cookie", "actual": logout_payload})
        finally:
            server.shutdown()
            server.server_close()

    report = build_report(checks=checks, findings=findings)
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
