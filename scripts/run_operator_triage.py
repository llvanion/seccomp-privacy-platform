#!/usr/bin/env python3
"""Chain dashboard + alert check + health + workflow status into a single operator triage report."""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
TRIAGE_SCHEMA = "operator_triage_report/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def repo_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def load_optional_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def run_script(script: str, *args: str) -> dict[str, Any] | None:
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / script), *args]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None


def section_dashboard(
    observability_path: Path | None,
    platform_health_path: Path | None,
) -> dict[str, Any]:
    if observability_path is None or not observability_path.is_file():
        return {"available": False, "reason": "pipeline_observability.json not found"}
    args = ["--observability", str(observability_path)]
    if platform_health_path and platform_health_path.is_file():
        args += ["--platform-health", str(platform_health_path)]
    dashboard = run_script("build_observability_dashboard.py", *args)
    if dashboard is None:
        return {"available": False, "reason": "build_observability_dashboard.py failed"}
    summary = dashboard.get("summary") or {}
    return {
        "available": True,
        "overall_status": summary.get("overall_status"),
        "total_events": summary.get("total_events"),
        "panel_count": summary.get("panel_count"),
        "has_failures": bool((dashboard.get("panels") or {}).get("failure_summary", {}).get("row_count", 0)),
    }


def section_alerts(dashboard_path: Path | None, platform_health_path: Path | None) -> dict[str, Any]:
    if dashboard_path is None or not dashboard_path.is_file():
        return {"available": False, "reason": "observability_dashboard.json not found"}
    args = ["--dashboard", str(dashboard_path)]
    if platform_health_path and platform_health_path.is_file():
        args += ["--platform-health", str(platform_health_path)]
    report = run_script("check_observability_alerts.py", *args)
    if report is None:
        return {"available": False, "reason": "check_observability_alerts.py failed"}
    return {
        "available": True,
        "overall_status": report.get("overall_status"),
        "alert_count": report.get("alert_count"),
        "firing_count": report.get("firing_count"),
        "firing_alert_ids": [
            a["alert_id"] for a in (report.get("alerts") or []) if a.get("firing")
        ],
    }


def section_platform_health(platform_health_path: Path | None) -> dict[str, Any]:
    if platform_health_path is None or not platform_health_path.is_file():
        return {"available": False, "reason": "platform_health.json not found"}
    ph = load_optional_json_object(platform_health_path)
    if ph is None:
        return {"available": False, "reason": "platform_health.json could not be parsed"}
    ph_summary = ph.get("summary") or {}
    checks = ph.get("checks")
    return {
        "available": True,
        "status": ph_summary.get("status"),
        "ok": ph_summary.get("ok"),
        "warn": ph_summary.get("warn"),
        "error": ph_summary.get("error"),
        "check_count": len(checks) if isinstance(checks, list) else 0,
    }


def section_workflow_status(status_path: Path | None) -> dict[str, Any]:
    if status_path is None or not status_path.is_file():
        return {"available": False, "reason": "query_workflow/status.json not found"}
    ws = load_optional_json_object(status_path)
    if ws is None:
        return {"available": False, "reason": "status.json could not be parsed"}
    retry_section: dict[str, Any] = {}
    receipts_path = status_path.parent / "execution_receipts.jsonl"
    retry_report = run_script(
        "check_workflow_retry_eligibility.py",
        "--status-file", str(status_path),
        *(["--receipts-file", str(receipts_path)] if receipts_path.is_file() else []),
    )
    if retry_report:
        retry_section = {
            "retryable": retry_report.get("retryable"),
            "resubmit_required": retry_report.get("resubmit_required"),
            "recommended_action": retry_report.get("recommended_action"),
        }
    return {
        "available": True,
        "job_id": ws.get("job_id"),
        "state": ws.get("state"),
        "terminal": ws.get("terminal"),
        "last_exit_code": ws.get("last_exit_code"),
        "receipt_count": ws.get("receipt_count"),
        "last_updated_at_utc": ws.get("last_updated_at_utc"),
        **retry_section,
    }


def overall_status(sections: dict[str, Any]) -> str:
    dashboard_status = (sections.get("dashboard") or {}).get("overall_status") or "unknown"
    alert_status = (sections.get("alerts") or {}).get("overall_status") or "unknown"
    health_status = (sections.get("platform_health") or {}).get("status") or "unknown"
    statuses = {dashboard_status, alert_status, health_status}
    if "error" in statuses:
        return "error"
    if "warn" in statuses:
        return "warn"
    if all(s == "ok" for s in statuses if s != "unknown"):
        return "ok"
    return "warn"


def build_triage_report(
    out_base: Path,
    *,
    observability_path: Path | None,
    platform_health_path: Path | None,
    dashboard_path: Path | None,
    workflow_status_path: Path | None,
) -> dict[str, Any]:
    # Run dashboard section (builds dashboard inline from observability)
    dash_section = section_dashboard(observability_path, platform_health_path)
    # For alert section, use a pre-built dashboard path or build it in temp
    effective_dashboard_path = dashboard_path
    if effective_dashboard_path is None or not effective_dashboard_path.is_file():
        # Try building dashboard to a temp location
        if observability_path and observability_path.is_file():
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                tmp_dash = Path(tmp.name)
            args = ["--observability", str(observability_path), "--out", str(tmp_dash)]
            if platform_health_path and platform_health_path.is_file():
                args += ["--platform-health", str(platform_health_path)]
            result = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "build_observability_dashboard.py")] + args,
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and tmp_dash.is_file():
                effective_dashboard_path = tmp_dash
    alert_section = section_alerts(effective_dashboard_path, platform_health_path)
    health_section = section_platform_health(platform_health_path)
    workflow_section = section_workflow_status(workflow_status_path)
    sections = {
        "dashboard": dash_section,
        "alerts": alert_section,
        "platform_health": health_section,
        "workflow_status": workflow_section,
    }
    return {
        "schema": TRIAGE_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "out_base": str(out_base),
        "overall_status": overall_status(sections),
        "sections": sections,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Produce a unified operator triage report from sidecar artifacts.",
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--out-base", default="", help="Run out_base; infers all sidecar paths")
    src.add_argument("--observability", default="", help="Explicit path to pipeline_observability.json")
    ap.add_argument("--platform-health", default="", help="Optional explicit path to platform_health.json")
    ap.add_argument("--dashboard", default="", help="Optional explicit path to observability_dashboard.json (avoids rebuild)")
    ap.add_argument("--workflow-status", default="", help="Optional explicit path to query_workflow/status.json")
    ap.add_argument("--out", default="", help="Output path for operator_triage_report.json")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.out_base:
        base = repo_path(args.out_base)
        observability_path: Path | None = base / "pipeline_observability.json"
        platform_health_path: Path | None = base / "platform_health.json" if not args.platform_health else repo_path(args.platform_health)
        dashboard_path: Path | None = base / "observability_dashboard.json" if not args.dashboard else repo_path(args.dashboard)
        workflow_status_path: Path | None = base / "query_workflow" / "status.json" if not args.workflow_status else repo_path(args.workflow_status)
    else:
        base = repo_path(args.observability).parent
        observability_path = repo_path(args.observability)
        platform_health_path = repo_path(args.platform_health) if args.platform_health else None
        dashboard_path = repo_path(args.dashboard) if args.dashboard else None
        workflow_status_path = repo_path(args.workflow_status) if args.workflow_status else None
    report = build_triage_report(
        base,
        observability_path=observability_path,
        platform_health_path=platform_health_path,
        dashboard_path=dashboard_path,
        workflow_status_path=workflow_status_path,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out_path = repo_path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
