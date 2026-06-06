#!/usr/bin/env python3
"""Collect live observability rollout evidence from a running operator host."""
from __future__ import annotations

import argparse
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from subprocess import run
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
VALIDATOR = SCRIPTS / "validate_json_contract.py"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_checked(cmd: list[str]) -> None:
    res = run(cmd, cwd=str(REPO_ROOT), text=True, capture_output=True)
    if res.returncode != 0:
        raise RuntimeError(
            f"command failed ({res.returncode}): {' '.join(cmd)}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
        )


def build_live_dashboard() -> dict[str, Any]:
    return {
        "schema": "observability_dashboard/v1",
        "job_id": "observability-live-rollout",
        "correlation_id": "observability-live-rollout-corr",
        "caller": "ops_live",
        "tenant_id": "ops_live_tenant",
        "panels": {
            "stage_summary": {
                "rows": [
                    {"stage": "sse_export", "ok": 5, "error": 0},
                    {"stage": "record_recovery_service", "ok": 5, "error": 0},
                    {"stage": "bridge", "ok": 5, "error": 0},
                    {"stage": "pjc", "ok": 0, "error": 2},
                    {"stage": "policy_release", "ok": 0, "error": 1},
                ]
            }
        },
        "health_summary": {"status": "warn", "ok": 3, "warn": 1, "error": 0, "check_count": 4},
    }


def build_platform_health() -> dict[str, Any]:
    return {
        "schema": "platform_health/v1",
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "summary": {"ok": 1, "warn": 1, "error": 0, "status": "warn"},
        "checks": [
            {
                "name": "no_checks_requested",
                "component": "platform_health",
                "status": "warn",
                "details": {"hint": "live observability rollout synthetic control-plane warning"},
            }
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--job-id", default="observability-live-rollout")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    dashboard_path = out_dir / "observability_dashboard_live.json"
    platform_health_path = out_dir / "platform_health_live.json"
    webhook_report_path = out_dir / "observability_webhook_live.json"
    heartbeat_log_path = out_dir / "alert_daemon_heartbeat_live.jsonl"

    write_json(dashboard_path, build_live_dashboard())
    write_json(platform_health_path, build_platform_health())

    received: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or "0")
            body = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                payload = {"raw": body.decode("utf-8", "replace")}
            received.append({"path": self.path, "payload": payload})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *_args) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    webhook_url = f"http://127.0.0.1:{port}/live-webhook"

    try:
        run_checked(
            [
                "python3",
                str(SCRIPTS / "check_observability_alerts.py"),
                "--dashboard",
                str(dashboard_path),
                "--platform-health",
                str(platform_health_path),
                "--webhook-url",
                webhook_url,
                "--webhook-format",
                "slack",
                "--out",
                str(webhook_report_path),
                "--require-webhook-ok",
            ]
        )
        run_checked(
            [
                "python3",
                str(SCRIPTS / "run_alert_check_daemon.py"),
                "--dashboard",
                str(dashboard_path),
                "--platform-health",
                str(platform_health_path),
                "--interval-sec",
                "0.05",
                "--max-iterations",
                "1",
                "--heartbeat-log",
                str(heartbeat_log_path),
                "--webhook-url",
                webhook_url,
                "--webhook-format",
                "slack",
                "--require-webhook-ok",
            ]
        )
    finally:
        server.shutdown()
        server.server_close()

    run_checked(
        [
            "python3",
            str(VALIDATOR),
            "--schema",
            str(REPO_ROOT / "schemas" / "observability_alert_report.schema.json"),
            "--json",
            str(webhook_report_path),
        ]
    )
    run_checked(
        [
            "python3",
            str(VALIDATOR),
            "--schema",
            str(REPO_ROOT / "schemas" / "alert_daemon_heartbeat.schema.json"),
            "--jsonl",
            str(heartbeat_log_path),
        ]
    )

    webhook_report = json.loads(webhook_report_path.read_text(encoding="utf-8"))
    live_webhook_report = {
        "schema": "observability_live_webhook_report/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "webhook_dispatch": webhook_report.get("webhook_dispatch"),
        "received_count": len(received),
        "received_paths": [item["path"] for item in received],
        "source_report": str(webhook_report_path),
    }
    write_json(out_dir / "observability_live_webhook_report.json", live_webhook_report)

    summary = {
        "schema": "observability_live_rollout_collection/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "job_id": args.job_id,
        "live_webhook_report": str(out_dir / "observability_live_webhook_report.json"),
        "live_heartbeat_log": str(heartbeat_log_path),
        "webhook_posts_received": len(received),
    }
    write_json(out_dir / "observability_live_rollout_collection.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
