#!/usr/bin/env python3
"""Operator alert daemon (I2-b).

Wraps ``check_observability_alerts.py`` in a polling loop and POSTs alert
state changes to a Slack or Alertmanager webhook. Tracks the last-known
firing state per ``alert_id`` so it can post:

- A *new firing* notification on `unknown -> firing` or `resolved -> firing`.
- A *resolved* notification on `firing -> resolved` (but only if a webhook
  format that supports resolved notifications is selected, or the operator
  passes ``--webhook-include-resolved``).
- A heartbeat record (`alert_daemon_heartbeat/v1`) every iteration regardless.

The daemon does *not* alter any pipeline output: it is a read-only loop over
``observability_dashboard/v1`` plus ``platform_health/v1`` and a write-only
sink for the heartbeat JSONL log.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
HEARTBEAT_SCHEMA = "alert_daemon_heartbeat/v1"

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_observability_alerts import (  # noqa: E402  — sibling script import
    build_alert_report,
    dispatch_webhook,
    load_json_object,
    load_optional_json_object,
    repo_path,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def alert_state_signature(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sig: dict[str, dict[str, Any]] = {}
    for alert in report.get("alerts") or []:
        if not isinstance(alert, dict):
            continue
        alert_id = str(alert.get("alert_id") or "")
        if not alert_id:
            continue
        sig[alert_id] = {
            "firing": bool(alert.get("firing")),
            "severity": str(alert.get("severity") or "ok"),
            "message": str(alert.get("message") or ""),
        }
    return sig


def compute_transitions(
    previous: dict[str, dict[str, Any]] | None,
    current: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    transitions: list[dict[str, Any]] = []
    prev = previous or {}
    for alert_id, info in current.items():
        prev_info = prev.get(alert_id)
        if prev_info is None:
            from_state = "unknown"
        else:
            from_state = "firing" if prev_info.get("firing") else "resolved"
        to_state = "firing" if info.get("firing") else "resolved"
        if from_state == to_state:
            continue
        transitions.append({
            "alert_id": alert_id,
            "from": from_state,
            "to": to_state,
            "severity": info.get("severity", "ok"),
            "message": info.get("message", ""),
        })
    return transitions


def write_heartbeat(out_path: Path, record: dict[str, Any]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_iteration(
    args: argparse.Namespace,
    *,
    iteration: int,
    previous_state: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    started_at = time.time()
    started_iso = datetime.fromtimestamp(started_at, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    dashboard_path = repo_path(args.dashboard)
    dashboard = load_json_object(dashboard_path)
    platform_health_path: Path | None = None
    platform_health: dict[str, Any] | None = None
    if args.platform_health:
        platform_health_path = repo_path(args.platform_health)
        platform_health = load_optional_json_object(platform_health_path)
    report = build_alert_report(dashboard, platform_health=platform_health)
    current_state = alert_state_signature(report)
    transitions = compute_transitions(previous_state, current_state)

    has_state_change = bool(transitions)
    has_firing = report.get("firing_count", 0) > 0

    webhook_dispatch: dict[str, Any] | None = None
    if args.webhook_url:
        only_firing = not args.webhook_include_resolved
        should_dispatch = (
            (has_firing and only_firing)
            or (has_state_change and not only_firing)
            or args.webhook_always
        )
        if should_dispatch:
            bearer_token = os.environ.get(args.webhook_bearer_env) if args.webhook_bearer_env else None
            webhook_dispatch = dispatch_webhook(
                report,
                url=args.webhook_url,
                fmt=args.webhook_format,
                timeout_sec=args.webhook_timeout_sec,
                bearer_token=bearer_token or None,
                only_firing=only_firing and not args.webhook_always,
            )

    completed_at = time.time()
    completed_iso = datetime.fromtimestamp(completed_at, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    heartbeat = {
        "schema": HEARTBEAT_SCHEMA,
        "iteration": iteration,
        "started_at_utc": started_iso,
        "completed_at_utc": completed_iso,
        "interval_sec": float(args.interval_sec),
        "dashboard_path": str(dashboard_path),
        "platform_health_path": str(platform_health_path) if platform_health_path else None,
        "alert_count": int(report.get("alert_count") or 0),
        "firing_count": int(report.get("firing_count") or 0),
        "overall_status": str(report.get("overall_status") or "ok"),
        "duration_ms": (completed_at - started_at) * 1000.0,
        "alert_state_summary": {
            alert_id: ("firing" if info.get("firing") else "resolved")
            for alert_id, info in current_state.items()
        },
        "transitions": transitions,
    }
    if webhook_dispatch is not None:
        heartbeat["webhook_dispatch"] = webhook_dispatch

    if args.heartbeat_log:
        write_heartbeat(repo_path(args.heartbeat_log), heartbeat)

    if args.alert_report_out:
        out_path = repo_path(args.alert_report_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    heartbeat["_state"] = current_state  # internal handoff; stripped by caller
    return heartbeat


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Run the operator alert check on an interval and post state changes (I2-b)."
    )
    ap.add_argument("--dashboard", required=True, help="Path to observability_dashboard.json")
    ap.add_argument("--platform-health", default="", help="Optional path to platform_health.json")
    ap.add_argument("--interval-sec", type=float, default=60.0, help="Loop interval (seconds)")
    ap.add_argument("--max-iterations", type=int, default=0, help="Stop after N iterations (0 = run forever)")
    ap.add_argument("--heartbeat-log", default="", help="Path to JSONL heartbeat log (alert_daemon_heartbeat/v1)")
    ap.add_argument("--alert-report-out", default="", help="If set, also write the latest observability_alert_report.json each iteration")
    ap.add_argument("--webhook-url", default="", help="Optional webhook URL for state-change posts")
    ap.add_argument("--webhook-format", choices=["slack", "alertmanager"], default="slack")
    ap.add_argument("--webhook-bearer-env", default="", help="Env var holding a bearer token for the webhook Authorization header")
    ap.add_argument("--webhook-timeout-sec", type=float, default=5.0)
    ap.add_argument("--webhook-include-resolved", action="store_true", help="Also POST resolved-state notifications")
    ap.add_argument("--webhook-always", action="store_true", help="POST every iteration regardless of firing state (debug aid)")
    ap.add_argument("--require-webhook-ok", action="store_true", help="Treat a webhook dispatch failure as a fatal error and exit non-zero")
    ap.add_argument("--exit-on-firing", action="store_true", help="Exit non-zero on the first iteration with firing alerts")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.interval_sec <= 0:
        raise SystemExit("[ERROR] --interval-sec must be > 0")

    stop_flag = {"stopped": False}

    def _request_stop(_signum, _frame):
        stop_flag["stopped"] = True

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    iteration = 0
    previous_state: dict[str, dict[str, Any]] | None = None
    last_dispatch_failed = False
    saw_firing = False

    while not stop_flag["stopped"]:
        heartbeat = run_iteration(args, iteration=iteration, previous_state=previous_state)
        previous_state = heartbeat.pop("_state")
        iteration += 1
        if heartbeat.get("firing_count", 0) > 0:
            saw_firing = True
        wd = heartbeat.get("webhook_dispatch")
        if wd is not None and not wd.get("ok"):
            last_dispatch_failed = True
        if args.max_iterations and iteration >= args.max_iterations:
            break
        if stop_flag["stopped"]:
            break
        # Sleep in small slices so signals are observed promptly.
        deadline = time.time() + args.interval_sec
        while time.time() < deadline and not stop_flag["stopped"]:
            time.sleep(min(0.5, max(0.0, deadline - time.time())))

    if args.require_webhook_ok and last_dispatch_failed:
        return 1
    if args.exit_on_firing and saw_firing:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
