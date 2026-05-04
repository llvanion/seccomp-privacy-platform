#!/usr/bin/env python3
import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_SCHEMA = "observability_dashboard/v1"
SOURCE_SCHEMA = "pipeline_observability/v1"


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
    if not isinstance(payload, dict):
        return None
    return payload


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * pct
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    weight = pos - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def build_stage_timeline(events: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        rows.append({
            "stage": ev.get("stage"),
            "role": ev.get("role"),
            "status": ev.get("status"),
            "ts_utc": ev.get("ts_utc"),
            "duration_ms": ev.get("duration_ms"),
            "row_count": ev.get("row_count"),
            "decision": ev.get("decision"),
            "reason_code": ev.get("reason_code"),
        })
    has_ts = sorted([r for r in rows if r.get("ts_utc") is not None], key=lambda r: r["ts_utc"])
    no_ts = [r for r in rows if r.get("ts_utc") is None]
    rows = has_ts + no_ts
    return {
        "type": "stage_timeline",
        "row_count": len(rows),
        "rows": rows,
    }


def build_stage_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_stage: dict[str, dict[str, int]] = {}
    for ev in events:
        if not isinstance(ev, dict):
            continue
        stage = str(ev.get("stage") or "unknown")
        status = str(ev.get("status") or "unknown")
        by_stage.setdefault(stage, {"ok": 0, "error": 0, "unknown": 0})
        if status == "ok":
            by_stage[stage]["ok"] += 1
        elif status == "error":
            by_stage[stage]["error"] += 1
        else:
            by_stage[stage]["unknown"] += 1
    rows = []
    for stage, counts in sorted(by_stage.items()):
        total = counts["ok"] + counts["error"] + counts["unknown"]
        rows.append({
            "stage": stage,
            "ok": counts["ok"],
            "error": counts["error"],
            "unknown": counts["unknown"],
            "total": total,
        })
    return {
        "type": "stage_summary",
        "row_count": len(rows),
        "rows": rows,
    }


def build_stage_duration(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_stage: dict[str, list[float]] = {}
    for ev in events:
        if not isinstance(ev, dict):
            continue
        stage = str(ev.get("stage") or "unknown")
        duration_ms = ev.get("duration_ms")
        if duration_ms is not None and isinstance(duration_ms, (int, float)):
            by_stage.setdefault(stage, [])
            by_stage[stage].append(float(duration_ms))
    rows = []
    for stage, durations in sorted(by_stage.items()):
        if not durations:
            continue
        rows.append({
            "stage": stage,
            "sample_count": len(durations),
            "min_ms": round(min(durations), 3),
            "mean_ms": round(statistics.fmean(durations), 3),
            "p50_ms": round(percentile(durations, 0.50), 3),
            "p95_ms": round(percentile(durations, 0.95), 3),
            "max_ms": round(max(durations), 3),
        })
    return {
        "type": "stage_duration",
        "row_count": len(rows),
        "rows": rows,
    }


def build_release_outcomes(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_tenant: dict[str, dict[str, Any]] = {}
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev.get("stage") != "policy_release":
            continue
        tenant_id = str(ev.get("tenant_id") or "unknown")
        status = str(ev.get("status") or "unknown")
        ts_utc = ev.get("ts_utc")
        entry = by_tenant.setdefault(tenant_id, {
            "tenant_id": tenant_id,
            "ok_count": 0,
            "error_count": 0,
            "unknown_count": 0,
            "last_status": None,
            "last_ts_utc": None,
        })
        if status == "ok":
            entry["ok_count"] += 1
        elif status == "error":
            entry["error_count"] += 1
        else:
            entry["unknown_count"] += 1
        if ts_utc is not None:
            if entry["last_ts_utc"] is None or ts_utc > entry["last_ts_utc"]:
                entry["last_ts_utc"] = ts_utc
                entry["last_status"] = status
        elif entry["last_status"] is None:
            entry["last_status"] = status
    rows = sorted(by_tenant.values(), key=lambda r: str(r["tenant_id"]))
    return {
        "type": "release_outcomes",
        "row_count": len(rows),
        "rows": rows,
    }


def build_failure_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    failure_rows = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev.get("status") != "error":
            continue
        failure_rows.append({
            "caller": ev.get("caller"),
            "stage": ev.get("stage"),
            "role": ev.get("role"),
            "status": ev.get("status"),
            "reason_code": ev.get("reason_code"),
            "ts_utc": ev.get("ts_utc"),
            "duration_ms": ev.get("duration_ms"),
        })
    has_ts = sorted([r for r in failure_rows if r.get("ts_utc") is not None], key=lambda r: r["ts_utc"], reverse=True)
    no_ts = [r for r in failure_rows if r.get("ts_utc") is None]
    return {
        "type": "failure_summary",
        "row_count": len(failure_rows),
        "rows": has_ts + no_ts,
    }


def build_health_summary(platform_health: dict[str, Any] | None) -> dict[str, Any] | None:
    if not platform_health:
        return None
    ph_summary = platform_health.get("summary")
    if not isinstance(ph_summary, dict):
        return None
    checks = platform_health.get("checks")
    return {
        "status": ph_summary.get("status"),
        "ok": ph_summary.get("ok"),
        "warn": ph_summary.get("warn"),
        "error": ph_summary.get("error"),
        "check_count": len(checks) if isinstance(checks, list) else 0,
    }


def build_dashboard(
    observability: dict[str, Any],
    *,
    platform_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if observability.get("schema") != SOURCE_SCHEMA:
        raise ValueError(f"unexpected observability schema: {observability.get('schema')!r}")
    events: list[dict[str, Any]] = observability.get("events") or []
    obs_summary = observability.get("summary") or {}
    return {
        "schema": DASHBOARD_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "job_id": observability.get("job_id"),
        "correlation_id": observability.get("correlation_id"),
        "caller": observability.get("caller"),
        "tenant_id": observability.get("tenant_id"),
        "dataset_id": observability.get("dataset_id"),
        "service_id": observability.get("service_id"),
        "summary": {
            "total_events": obs_summary.get("event_count", len(events)),
            "overall_status": obs_summary.get("status", "unknown"),
            "panel_count": 5,
        },
        "panels": {
            "stage_timeline": build_stage_timeline(events),
            "stage_summary": build_stage_summary(events),
            "stage_duration": build_stage_duration(events),
            "release_outcomes": build_release_outcomes(events),
            "failure_summary": build_failure_summary(events),
        },
        "health_summary": build_health_summary(platform_health),
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Build operator dashboard panels from pipeline_observability/v1.",
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--observability", default="", help="Path to pipeline_observability.json")
    src.add_argument("--out-base", default="", help="Run out_base; infers pipeline_observability.json")
    ap.add_argument("--platform-health", default="", help="Optional path to platform_health.json")
    ap.add_argument("--out", default="", help="Output path for observability_dashboard.json")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.observability:
        obs_path = repo_path(args.observability)
    else:
        obs_path = repo_path(args.out_base) / "pipeline_observability.json"
    observability = load_json_object(obs_path)
    platform_health: dict[str, Any] | None = None
    if args.platform_health:
        platform_health = load_optional_json_object(repo_path(args.platform_health))
    elif args.out_base:
        platform_health = load_optional_json_object(
            repo_path(args.out_base) / "platform_health.json"
        )
    dashboard = build_dashboard(observability, platform_health=platform_health)
    text = json.dumps(dashboard, ensure_ascii=False, indent=2)
    if args.out:
        out_path = repo_path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
