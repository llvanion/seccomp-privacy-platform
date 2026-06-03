#!/usr/bin/env python3
"""Smoke-test browser-facing security headers on the operator console server."""
from __future__ import annotations

import argparse
import json
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import serve_operator_dashboard as dashboard
from runtime_service_helpers import available_port


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "console_security_headers_check/v1"

REQUIRED_CSP_DIRECTIVES = {
    "default-src": {"'self'"},
    "script-src": {"'self'"},
    "style-src": {"'self'"},
    "connect-src": {"'self'"},
    "object-src": {"'none'"},
    "base-uri": {"'self'"},
    "frame-ancestors": {"'none'"},
    "form-action": {"'self'"},
}
FORBIDDEN_CSP_TOKENS = {"'unsafe-inline'", "'unsafe-eval'"}
FORBIDDEN_SCRIPT_TOKENS = {"'unsafe-inline'", "'unsafe-eval'"}
REQUIRED_PERMISSIONS_DENIALS = {
    "camera=()",
    "microphone=()",
    "geolocation=()",
    "payment=()",
    "usb=()",
}
SOURCE_INLINE_STYLE_PATTERNS = ("style={", "style = {", "dangerouslySetInnerHTML")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
                "policy_version": "console-security-headers-smoke",
                "job_id": "console-security-headers-smoke",
                "correlation_id": "console-security-headers-smoke",
                "caller": "security_header_smoke",
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
                "job_id": "console-security-headers-smoke",
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
                "caller": "security_header_smoke",
                "tenant_id": "security_header_tenant",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def seed_console_dist(root: Path) -> None:
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(
        "<!doctype html><html><head><title>console</title></head>"
        '<body><div id="root"></div><script type="module" src="/assets/app.js"></script></body></html>\n',
        encoding="utf-8",
    )
    (root / "assets" / "app.js").write_text("console.log('console security header smoke');\n", encoding="utf-8")


def request(url: str) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(url, method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as response:
            return int(response.status), response.read(), dict(response.headers.items())
    except HTTPError as exc:
        return int(exc.code), exc.read(), dict(exc.headers.items())


def parse_csp(value: str) -> dict[str, set[str]]:
    directives: dict[str, set[str]] = {}
    for raw_part in value.split(";"):
        part = raw_part.strip()
        if not part:
            continue
        tokens = part.split()
        if not tokens:
            continue
        directives[tokens[0]] = set(tokens[1:])
    return directives


def check_common_headers(label: str, status: int, headers: dict[str, str], findings: list[dict[str, Any]]) -> dict[str, Any]:
    csp_raw = headers.get("Content-Security-Policy", "")
    csp = parse_csp(csp_raw)
    permissions = headers.get("Permissions-Policy", "")
    check: dict[str, Any] = {
        "status": status,
        "has_csp": bool(csp_raw),
        "x_content_type_options": headers.get("X-Content-Type-Options", ""),
        "x_frame_options": headers.get("X-Frame-Options", ""),
        "referrer_policy": headers.get("Referrer-Policy", ""),
        "permissions_policy": permissions,
        "csp_style_allows_inline": "'unsafe-inline'" in csp.get("style-src", set()),
        "csp_script_allows_inline": bool(csp.get("script-src", set()) & FORBIDDEN_SCRIPT_TOKENS),
        "csp_allows_unsafe_eval": any("'unsafe-eval'" in values for values in csp.values()),
        "csp_connect_src": sorted(csp.get("connect-src", set())),
    }
    if status >= 500:
        findings.append({"message": f"{label} returned server error", "actual": status})
    for directive, required_values in REQUIRED_CSP_DIRECTIVES.items():
        actual_values = csp.get(directive, set())
        missing = sorted(required_values - actual_values)
        if missing:
            findings.append({
                "message": f"{label} CSP missing {directive} values",
                "expected": sorted(required_values),
                "actual": sorted(actual_values),
            })
    for directive, values in csp.items():
        forbidden = sorted(values & FORBIDDEN_CSP_TOKENS)
        if forbidden:
            findings.append({"message": f"{label} CSP contains forbidden token", "actual": {directive: forbidden}})
    script_forbidden = sorted(csp.get("script-src", set()) & FORBIDDEN_SCRIPT_TOKENS)
    if script_forbidden:
        findings.append({"message": f"{label} script-src allows inline/eval scripts", "actual": script_forbidden})
    if headers.get("X-Content-Type-Options") != "nosniff":
        findings.append({"message": f"{label} missing X-Content-Type-Options=nosniff", "actual": headers.get("X-Content-Type-Options")})
    if headers.get("X-Frame-Options") != "DENY":
        findings.append({"message": f"{label} missing X-Frame-Options=DENY", "actual": headers.get("X-Frame-Options")})
    if headers.get("Referrer-Policy") != "no-referrer":
        findings.append({"message": f"{label} missing Referrer-Policy=no-referrer", "actual": headers.get("Referrer-Policy")})
    missing_permissions = sorted(item for item in REQUIRED_PERMISSIONS_DENIALS if item not in permissions)
    if missing_permissions:
        findings.append({
            "message": f"{label} Permissions-Policy missing deny directives",
            "expected": sorted(REQUIRED_PERMISSIONS_DENIALS),
            "actual": permissions,
        })
    return check


def scan_console_source(findings: list[dict[str, Any]]) -> dict[str, Any]:
    checked_files = 0
    inline_style_findings: list[dict[str, Any]] = []
    source_root = REPO_ROOT / "console" / "src"
    for path in sorted(source_root.rglob("*")):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        checked_files += 1
        text = path.read_text(encoding="utf-8")
        for pattern in SOURCE_INLINE_STYLE_PATTERNS:
            if pattern in text:
                inline_style_findings.append({
                    "path": str(path.relative_to(REPO_ROOT)),
                    "pattern": pattern,
                })
    for item in inline_style_findings:
        findings.append({
            "message": "console source contains inline-style or raw HTML sink blocked by strict CSP policy",
            "actual": item,
        })
    return {
        "checked_files": checked_files,
        "inline_style_finding_count": len(inline_style_findings),
    }


def start_server(
    *,
    out_base: Path,
    history_root: Path,
    console_dist: Path,
    secure_cookie: bool,
) -> tuple[dashboard.DashboardServer, int]:
    port = available_port()
    server = dashboard.DashboardServer(
        ("127.0.0.1", port),
        dashboard.DashboardHandler,
        out_base=out_base,
        history_root=history_root,
        history_limit=4,
        pid_file="",
        ready_file="",
        max_concurrent_jobs_per_tenant=0,
        console_dist=console_dist,
        session_cookie_secure=secure_cookie,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    return server, port


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
    parser = argparse.ArgumentParser(description="Smoke-test operator console browser security headers.")
    parser.add_argument("--out", default="", help="Optional path for the JSON report")
    args = parser.parse_args()

    findings: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="seccomp_console_headers.") as tmp_raw:
        tmp_dir = Path(tmp_raw)
        out_base = tmp_dir / "run"
        console_dist = tmp_dir / "console_dist"
        out_base.mkdir(parents=True)
        console_dist.mkdir(parents=True)
        seed_run(out_base)
        seed_console_dist(console_dist)

        server, port = start_server(
            out_base=out_base,
            history_root=tmp_dir,
            console_dist=console_dist,
            secure_cookie=False,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            for label, path in (
                ("healthz", "/healthz"),
                ("dashboard_api", "/v1/dashboard"),
                ("spa_index", "/"),
                ("spa_asset", "/assets/app.js"),
            ):
                status, _, headers = request(f"{base}{path}")
                checks[label] = check_common_headers(label, status, headers, findings)
                checks[label]["hsts_present"] = "Strict-Transport-Security" in headers
                if "Strict-Transport-Security" in headers:
                    findings.append({"message": f"{label} emitted HSTS without secure-cookie mode", "actual": headers.get("Strict-Transport-Security")})
        finally:
            server.shutdown()
            server.server_close()

        secure_server, secure_port = start_server(
            out_base=out_base,
            history_root=tmp_dir,
            console_dist=console_dist,
            secure_cookie=True,
        )
        try:
            status, _, headers = request(f"http://127.0.0.1:{secure_port}/healthz")
            checks["secure_cookie_hsts"] = {
                "status": status,
                "strict_transport_security": headers.get("Strict-Transport-Security", ""),
            }
            if "max-age=31536000" not in headers.get("Strict-Transport-Security", ""):
                findings.append({
                    "message": "secure-cookie mode did not emit Strict-Transport-Security",
                    "actual": headers.get("Strict-Transport-Security", ""),
                })
        finally:
            secure_server.shutdown()
            secure_server.server_close()

        checks["console_source"] = scan_console_source(findings)

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
