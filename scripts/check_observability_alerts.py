#!/usr/bin/env python3
"""Evaluate operator alert conditions against observability_dashboard/v1."""
import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = "observability_alert_report/v1"
DASHBOARD_SCHEMA = "observability_dashboard/v1"
CORE_STAGES = {"sse_export", "record_recovery_service", "bridge", "pjc", "policy_release"}
WEBHOOK_FORMATS = ("slack", "alertmanager")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def repo_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def load_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def load_optional_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _alert(
    alert_id: str,
    name: str,
    severity: str,
    firing: bool,
    message: str,
    triage_path: list[str],
) -> dict[str, Any]:
    return {
        "alert_id": alert_id,
        "name": name,
        "severity": severity,
        "firing": firing,
        "message": message,
        "triage_path": triage_path,
    }


def check_repeated_stage_error(panels: dict[str, Any]) -> dict[str, Any]:
    summary_rows: list[dict[str, Any]] = (panels.get("stage_summary") or {}).get("rows") or []
    firing_stages = [
        row["stage"] for row in summary_rows
        if isinstance(row, dict) and row.get("error", 0) >= 2
    ]
    firing = bool(firing_stages)
    message = (
        f"Stage(s) with ≥2 error events: {', '.join(firing_stages)}"
        if firing
        else "No stage has repeated error events"
    )
    return _alert(
        alert_id="repeated_stage_error",
        name="Repeated Stage Error",
        severity="error",
        firing=firing,
        message=message,
        triage_path=[
            "Review failure_summary panel in observability_dashboard/v1 for the affected stage(s)",
            "Use audit read adapter: GET /v1/observability or GET /v1/audit-chain",
            f"Check stage-specific audit records in audit_chain.json (affected: {firing_stages or 'none'})",
        ],
    )


def check_release_failure_after_success(panels: dict[str, Any]) -> dict[str, Any]:
    summary_rows: list[dict[str, Any]] = (panels.get("stage_summary") or {}).get("rows") or []
    by_stage = {row["stage"]: row for row in summary_rows if isinstance(row, dict) and "stage" in row}
    release_row = by_stage.get("policy_release", {})
    bridge_row = by_stage.get("bridge", {})
    pjc_row = by_stage.get("pjc", {})
    release_has_error = release_row.get("error", 0) > 0
    bridge_all_ok = bridge_row.get("error", 0) == 0 and bridge_row.get("ok", 0) > 0
    pjc_all_ok = pjc_row.get("error", 0) == 0 and pjc_row.get("ok", 0) > 0
    firing = release_has_error and bridge_all_ok and pjc_all_ok
    message = (
        "Policy release failed after bridge and PJC succeeded — check k-threshold or release policy"
        if firing
        else "No release failure after successful upstream pipeline"
    )
    return _alert(
        alert_id="release_failure_after_success",
        name="Release Failure After Upstream Success",
        severity="error",
        firing=firing,
        message=message,
        triage_path=[
            "Check release_outcomes panel in observability_dashboard/v1 for tenant_id and last_status",
            "Use audit read adapter: GET /v1/public-report for the release decision and reason_code",
            "Review release policy configuration and k-threshold settings",
        ],
    )


def check_platform_health_degraded(health_summary: dict[str, Any] | None) -> dict[str, Any]:
    if health_summary is None:
        return _alert(
            alert_id="platform_health_degraded",
            name="Platform Health Degraded",
            severity="warn",
            firing=False,
            message="platform_health/v1 not available — health check skipped",
            triage_path=[
                "Run scripts/check_platform_health.py to generate platform_health.json",
                "Then re-run alert check with --platform-health or --out-base",
            ],
        )
    status = str(health_summary.get("status") or "unknown")
    firing = status in {"warn", "error"}
    severity = "error" if status == "error" else "warn"
    ok = health_summary.get("ok", 0)
    warn = health_summary.get("warn", 0)
    error = health_summary.get("error", 0)
    message = (
        f"Platform health is {status!r}: ok={ok} warn={warn} error={error}"
        if firing
        else f"Platform health is ok: ok={ok} warn={warn} error={error}"
    )
    return _alert(
        alert_id="platform_health_degraded",
        name="Platform Health Degraded",
        severity=severity,
        firing=firing,
        message=message,
        triage_path=[
            "Use platform health API: GET /v1/platform-health?out_base=<path>&metadata_db=<path>",
            "Check individual component failures via scripts/check_platform_health.py --verbose",
            "Restart degraded services before re-submitting query workflows",
        ],
    )


def check_stage_coverage_gap(panels: dict[str, Any]) -> dict[str, Any]:
    summary_rows: list[dict[str, Any]] = (panels.get("stage_summary") or {}).get("rows") or []
    present_stages = {row["stage"] for row in summary_rows if isinstance(row, dict) and "stage" in row}
    missing = sorted(CORE_STAGES - present_stages)
    firing = bool(missing)
    message = (
        f"Core pipeline stage(s) absent from observability export: {', '.join(missing)}"
        if firing
        else "All core pipeline stages are present in the observability export"
    )
    return _alert(
        alert_id="stage_coverage_gap",
        name="Stage Coverage Gap",
        severity="warn",
        firing=firing,
        message=message,
        triage_path=[
            "Re-run scripts/export_observability_events.py --audit-chain <path> to regenerate",
            "Check that audit_chain.json was built after the full pipeline completed",
            f"Missing stages: {missing or 'none'}",
        ],
    )


def build_alert_report(
    dashboard: dict[str, Any],
    *,
    platform_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if dashboard.get("schema") != DASHBOARD_SCHEMA:
        raise ValueError(f"unexpected dashboard schema: {dashboard.get('schema')!r}")
    panels = dashboard.get("panels") or {}
    health_summary = dashboard.get("health_summary")
    if health_summary is None and platform_health:
        ph_summary = platform_health.get("summary")
        if isinstance(ph_summary, dict):
            checks = platform_health.get("checks")
            health_summary = {
                "status": ph_summary.get("status"),
                "ok": ph_summary.get("ok"),
                "warn": ph_summary.get("warn"),
                "error": ph_summary.get("error"),
                "check_count": len(checks) if isinstance(checks, list) else 0,
            }
    alerts = [
        check_repeated_stage_error(panels),
        check_release_failure_after_success(panels),
        check_platform_health_degraded(health_summary),
        check_stage_coverage_gap(panels),
    ]
    firing_alerts = [a for a in alerts if a["firing"]]
    firing_severities = {a["severity"] for a in firing_alerts}
    if "error" in firing_severities:
        overall_status = "error"
    elif "warn" in firing_severities:
        overall_status = "warn"
    else:
        overall_status = "ok"
    return {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "job_id": dashboard.get("job_id"),
        "correlation_id": dashboard.get("correlation_id"),
        "caller": dashboard.get("caller"),
        "tenant_id": dashboard.get("tenant_id"),
        "alert_count": len(alerts),
        "firing_count": len(firing_alerts),
        "overall_status": overall_status,
        "alerts": alerts,
    }


def _format_slack_payload(report: dict[str, Any]) -> dict[str, Any]:
    firing = [a for a in report.get("alerts", []) if a.get("firing")]
    if not firing:
        text = (
            f":white_check_mark: All clear — overall_status={report.get('overall_status')}"
            f" job_id={report.get('job_id')} tenant={report.get('tenant_id')}"
        )
        return {"text": text}
    lines = [
        f":rotating_light: *{len(firing)} firing* (overall {report.get('overall_status')})"
        f" — job_id=`{report.get('job_id')}` tenant=`{report.get('tenant_id')}`",
    ]
    for alert in firing:
        triage = " ; ".join(alert.get("triage_path", []) or [])
        lines.append(
            f"• *{alert['alert_id']}* ({alert['severity']}): {alert['message']}"
            + (f"\n   _Triage:_ {triage}" if triage else "")
        )
    return {"text": "\n".join(lines)}


def _format_alertmanager_payload(report: dict[str, Any]) -> list[dict[str, Any]]:
    job_id = report.get("job_id") or ""
    tenant_id = report.get("tenant_id") or ""
    correlation_id = report.get("correlation_id") or ""
    out: list[dict[str, Any]] = []
    for alert in report.get("alerts", []) or []:
        if not alert.get("firing"):
            continue
        labels = {
            "alertname": str(alert["alert_id"]),
            "severity": str(alert["severity"]),
            "service": "seccomp-privacy-platform",
        }
        if job_id:
            labels["job_id"] = str(job_id)
        if tenant_id:
            labels["tenant_id"] = str(tenant_id)
        if correlation_id:
            labels["correlation_id"] = str(correlation_id)
        annotations = {
            "summary": str(alert.get("name") or alert["alert_id"]),
            "description": str(alert.get("message") or ""),
            "triage_path": " ; ".join(alert.get("triage_path", []) or []),
        }
        out.append({
            "labels": labels,
            "annotations": annotations,
            "startsAt": utc_now_iso(),
        })
    return out


_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _is_loopback_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    return host in {"localhost", "127.0.0.1", "::1"} or host.startswith("127.")


def _post_webhook(url: str, payload: Any, *, timeout_sec: float, bearer_token: str | None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    open_fn = _NO_PROXY_OPENER.open if _is_loopback_url(url) else urllib.request.urlopen
    try:
        with open_fn(req, timeout=timeout_sec) as resp:  # noqa: S310 — operator-supplied URL
            status_code = int(resp.status)
            ok = 200 <= status_code < 300
            return {
                "endpoint_url": url,
                "status_code": status_code,
                "ok": ok,
                "transport_error": None,
                "payload_byte_count": len(body),
            }
    except urllib.error.HTTPError as exc:
        return {
            "endpoint_url": url,
            "status_code": int(exc.code),
            "ok": False,
            "transport_error": f"HTTPError: {exc.reason}",
            "payload_byte_count": len(body),
        }
    except (urllib.error.URLError, OSError) as exc:
        return {
            "endpoint_url": url,
            "status_code": 0,
            "ok": False,
            "transport_error": f"{exc.__class__.__name__}: {exc}",
            "payload_byte_count": len(body),
        }


def dispatch_webhook(
    report: dict[str, Any],
    *,
    url: str,
    fmt: str,
    timeout_sec: float = 5.0,
    bearer_token: str | None = None,
    only_firing: bool = True,
) -> dict[str, Any]:
    """Post the alert report to a Slack or Alertmanager webhook.

    Returns a dispatch summary suitable for the optional ``webhook_dispatch``
    block on ``observability_alert_report/v1``. The summary records the
    endpoint URL, HTTP status, success boolean, and any transport error so
    operators can see whether notifications actually reached the receiver.
    """
    if fmt not in WEBHOOK_FORMATS:
        raise SystemExit(f"[ERROR] webhook format must be one of {WEBHOOK_FORMATS}, got {fmt!r}")
    firing_count = int(report.get("firing_count") or 0)
    if only_firing and firing_count == 0:
        return {
            "endpoint_url": url,
            "format": fmt,
            "skipped_reason": "no_firing_alerts",
            "ok": True,
            "status_code": 0,
            "transport_error": None,
            "payload_byte_count": 0,
            "firing_count": firing_count,
        }
    if fmt == "slack":
        payload: Any = _format_slack_payload(report)
    else:
        payload = _format_alertmanager_payload(report)
    result = _post_webhook(url, payload, timeout_sec=timeout_sec, bearer_token=bearer_token)
    result.update({
        "format": fmt,
        "skipped_reason": None,
        "firing_count": firing_count,
    })
    return result


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Evaluate operator alert conditions against observability_dashboard/v1.",
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--dashboard", default="", help="Path to observability_dashboard.json")
    src.add_argument("--out-base", default="", help="Run out_base; infers observability_dashboard.json")
    ap.add_argument("--platform-health", default="", help="Optional path to platform_health.json (supplement to dashboard health_summary)")
    ap.add_argument("--out", default="", help="Output path for observability_alert_report.json")
    ap.add_argument("--webhook-url", default="", help="Optional webhook URL (Slack incoming-webhook or Alertmanager /api/v1/alerts)")
    ap.add_argument("--webhook-format", choices=list(WEBHOOK_FORMATS), default="slack", help="Webhook payload format")
    ap.add_argument("--webhook-bearer-env", default="", help="Optional env var holding a bearer token added to the webhook Authorization header")
    ap.add_argument("--webhook-timeout-sec", type=float, default=5.0)
    ap.add_argument("--webhook-include-resolved", action="store_true", help="Always POST even if zero alerts are firing (default: skip empty notifications)")
    ap.add_argument("--require-webhook-ok", action="store_true", help="Exit non-zero if webhook dispatch failed")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.dashboard:
        dash_path = repo_path(args.dashboard)
    else:
        dash_path = repo_path(args.out_base) / "observability_dashboard.json"
    dashboard = load_json_object(dash_path)
    platform_health: dict[str, Any] | None = None
    if args.platform_health:
        platform_health = load_optional_json_object(repo_path(args.platform_health))
    elif args.out_base:
        platform_health = load_optional_json_object(repo_path(args.out_base) / "platform_health.json")
    report = build_alert_report(dashboard, platform_health=platform_health)
    if args.webhook_url:
        bearer_token = None
        if args.webhook_bearer_env:
            bearer_token = os.environ.get(args.webhook_bearer_env) or None
        report["webhook_dispatch"] = dispatch_webhook(
            report,
            url=args.webhook_url,
            fmt=args.webhook_format,
            timeout_sec=args.webhook_timeout_sec,
            bearer_token=bearer_token,
            only_firing=not args.webhook_include_resolved,
        )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out_path = repo_path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.require_webhook_ok and "webhook_dispatch" in report and not report["webhook_dispatch"].get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
