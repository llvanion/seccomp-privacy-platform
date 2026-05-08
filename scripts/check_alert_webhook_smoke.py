#!/usr/bin/env python3
"""Smoke harness for the alert webhook adapter (I2-a) and alert daemon (I2-b).

Spawns a small in-process HTTP receiver on loopback, drives
``check_observability_alerts.py`` once per webhook format, drives
``run_alert_check_daemon.py`` for two iterations with a state-flip between
them, validates the resulting reports + heartbeat JSONL against their schemas,
and asserts the dispatch outcomes.

Default contract smoke invokes this. The harness is self-contained so the
JSON contract gate does not need to embed an in-process HTTP server inline.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from subprocess import run

REPO_ROOT = Path(__file__).resolve().parents[1]


def utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def make_dashboard(*, firing: bool) -> dict:
    rows = [
        {"stage": s, "ok": 5, "error": 0}
        for s in ["sse_export", "record_recovery_service", "bridge", "policy_release"]
    ]
    if firing:
        rows.append({"stage": "pjc", "ok": 0, "error": 3})
    else:
        rows.append({"stage": "pjc", "ok": 5, "error": 0})
    return {
        "schema": "observability_dashboard/v1",
        "job_id": "alert-webhook-smoke",
        "correlation_id": "alert-webhook-smoke-corr",
        "caller": "smoke",
        "tenant_id": "smoke-tenant",
        "panels": {"stage_summary": {"rows": rows}},
        "health_summary": {"status": "ok", "ok": 4, "warn": 0, "error": 0, "check_count": 4},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Alert webhook + daemon smoke.")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else b""
            entry = {"path": self.path}
            try:
                entry["body"] = json.loads(body or b"null")
            except Exception:  # noqa: BLE001 — capture raw on parse failure
                entry["body_raw"] = body.decode("utf-8", "replace")
            received.append(entry)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *_a, **_kw):  # noqa: A003
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"

    firing_path = out_dir / "alert_smoke_firing_dashboard.json"
    clean_path = out_dir / "alert_smoke_clean_dashboard.json"
    firing_path.write_text(json.dumps(make_dashboard(firing=True)), encoding="utf-8")
    clean_path.write_text(json.dumps(make_dashboard(firing=False)), encoding="utf-8")

    validator = REPO_ROOT / "scripts" / "validate_json_contract.py"
    alerts = REPO_ROOT / "scripts" / "check_observability_alerts.py"
    daemon = REPO_ROOT / "scripts" / "run_alert_check_daemon.py"
    alert_schema = REPO_ROOT / "schemas" / "observability_alert_report.schema.json"
    heartbeat_schema = REPO_ROOT / "schemas" / "alert_daemon_heartbeat.schema.json"

    # --- I2-a: webhook formats ---
    for fmt, suffix in (("slack", "/slack"), ("alertmanager", "/alerts")):
        report_path = out_dir / f"alert_webhook_{fmt}.json"
        result = run(
            [
                "python3", str(alerts),
                "--dashboard", str(firing_path),
                "--out", str(report_path),
                "--webhook-url", f"{base_url}{suffix}",
                "--webhook-format", fmt,
            ],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode != 0:
            sys.stderr.write(f"[ERROR] alert webhook {fmt} failed: {result.stderr}\n")
            return 1
        rep = json.loads(report_path.read_text(encoding="utf-8"))
        wd = rep.get("webhook_dispatch") or {}
        if not (wd.get("ok") and wd.get("status_code") == 200 and wd.get("format") == fmt):
            sys.stderr.write(f"[ERROR] webhook dispatch {fmt} did not succeed: {wd}\n")
            return 1
        sc = run([
            "python3", str(validator),
            "--schema", str(alert_schema),
            "--json", str(report_path),
        ], capture_output=True, text=True)
        if sc.returncode != 0:
            sys.stderr.write(f"[ERROR] schema validation {fmt}: {sc.stderr}\n")
            return 1
        print(f"[ok] webhook dispatch {fmt}: status_code={wd['status_code']} firing={wd['firing_count']}")

    # Skip-when-no-firing
    skip_report = out_dir / "alert_webhook_skip.json"
    result = run(
        [
            "python3", str(alerts),
            "--dashboard", str(clean_path),
            "--out", str(skip_report),
            "--webhook-url", f"{base_url}/skip",
            "--webhook-format", "slack",
        ],
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode != 0:
        sys.stderr.write(f"[ERROR] skip-mode webhook run failed: {result.stderr}\n")
        return 1
    skip_rep = json.loads(skip_report.read_text(encoding="utf-8"))
    skip_wd = skip_rep.get("webhook_dispatch") or {}
    if skip_wd.get("skipped_reason") != "no_firing_alerts":
        sys.stderr.write(f"[ERROR] skip-mode did not skip empty notifications: {skip_wd}\n")
        return 1
    print(f"[ok] webhook skip-when-clean: skipped_reason={skip_wd['skipped_reason']}")

    # --- I2-b: daemon transitions, in-process ---
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import run_alert_check_daemon as rcd

    parser = rcd.build_parser()
    daemon_log = out_dir / "alert_daemon_heartbeat.jsonl"
    daemon_args = parser.parse_args([
        "--dashboard", str(firing_path),
        "--interval-sec", "0.05",
        "--max-iterations", "0",
        "--heartbeat-log", str(daemon_log),
        "--webhook-url", f"{base_url}/daemon",
        "--webhook-format", "slack",
    ])
    prev = None
    iter0 = rcd.run_iteration(daemon_args, iteration=0, previous_state=prev)
    prev = iter0.pop("_state")
    firing_path.write_text(json.dumps(make_dashboard(firing=False)), encoding="utf-8")
    iter1 = rcd.run_iteration(daemon_args, iteration=1, previous_state=prev)
    iter1.pop("_state")

    if iter0.get("firing_count") < 1:
        sys.stderr.write(f"[ERROR] daemon iter0 expected firing_count>=1: {iter0}\n")
        return 1
    if iter1.get("firing_count") != 0:
        sys.stderr.write(f"[ERROR] daemon iter1 expected firing_count==0: {iter1}\n")
        return 1
    iter1_transitions = iter1.get("transitions") or []
    if not any(t["from"] == "firing" and t["to"] == "resolved" for t in iter1_transitions):
        sys.stderr.write(f"[ERROR] daemon did not record firing→resolved transition: {iter1_transitions}\n")
        return 1

    sc = run([
        "python3", str(validator),
        "--schema", str(heartbeat_schema),
        "--jsonl", str(daemon_log),
    ], capture_output=True, text=True)
    if sc.returncode != 0:
        sys.stderr.write(f"[ERROR] heartbeat schema validation failed: {sc.stderr}\n")
        return 1
    print(f"[ok] alert daemon: iter0_firing={iter0['firing_count']} iter1_firing={iter1['firing_count']} firing→resolved=1")

    server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
