#!/usr/bin/env python3
"""
B13: OpenTelemetry / Grafana bridge adapter.

Converts pipeline_observability/v1 stage events into OTLP-compatible span
records (JSON) that can be ingested by Grafana Tempo, Jaeger, or any
OpenTelemetry-compatible collector without requiring each module to do
native instrumentation.

Output:
  --spans-out  <path>.jsonl   one OTLP span JSON per line
  --report-out <path>.json    otel_export_report/v1 summary

Span format follows the OTLP JSON export shape used by OpenTelemetry Collector.
Each pipeline stage becomes one span. The job-level root span is the parent.

Usage:
  python3 scripts/export_otel_events.py \
    --observability tmp/run/pipeline_observability.json \
    --spans-out    tmp/run/otel_spans.jsonl \
    --report-out   tmp/run/otel_export_report.json
"""
import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "otel_export_report/v1"
SCOPE_NAME = "seccomp-privacy-platform"
SCOPE_VERSION = "0.1.0"

_STATUS_OK = {"code": 1}        # OTLP STATUS_CODE_OK
_STATUS_ERROR = {"code": 2}     # OTLP STATUS_CODE_ERROR
_STATUS_UNSET = {"code": 0}     # OTLP STATUS_CODE_UNSET


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_trace_id(job_id: str) -> str:
    """Derive a deterministic 32-hex trace ID from the job_id."""
    h = hashlib.sha256(f"trace:{job_id}".encode()).hexdigest()
    return h[:32]


def _to_span_id(job_id: str, stage: str, role: str = "") -> str:
    """Derive a deterministic 16-hex span ID from job+stage+role."""
    key = f"span:{job_id}:{stage}:{role}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _parse_ts(ts: str | None) -> int | None:
    """Parse ISO-8601 UTC timestamp to Unix nanoseconds."""
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1_000_000_000)
        except ValueError:
            pass
    return None


def _duration_to_ns(ms: float | int | None) -> int | None:
    if ms is None:
        return None
    return int(ms * 1_000_000)


def _status(event_status: str | None) -> dict[str, int]:
    if event_status == "ok":
        return _STATUS_OK
    if event_status == "error":
        return _STATUS_ERROR
    return _STATUS_UNSET


def _attr(key: str, value: Any) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": value}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _attrs(*pairs: tuple[str, Any]) -> list[dict[str, Any]]:
    return [a for k, v in pairs if (a := _attr(k, v)) is not None]


def _build_root_span(
    *,
    trace_id: str,
    job_id: str,
    scope: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    span_id = _to_span_id(job_id, "_root_")

    # Derive start from first event, end from last
    start_ns: int | None = None
    end_ns: int | None = None
    for e in events:
        ts_ns = _parse_ts(e.get("ts_utc"))
        if ts_ns is not None:
            if start_ns is None or ts_ns < start_ns:
                start_ns = ts_ns
            dur_ns = _duration_to_ns(e.get("duration_ms"))
            candidate_end = ts_ns + (dur_ns or 0)
            if end_ns is None or candidate_end > end_ns:
                end_ns = candidate_end

    now_ns = int(time.time() * 1_000_000_000)
    start_ns = start_ns or now_ns
    end_ns = end_ns or now_ns

    overall_status = "error" if any(e.get("status") == "error" for e in events) else "ok"

    return {
        "traceId": trace_id,
        "spanId": span_id,
        "parentSpanId": "",
        "name": f"pipeline/{job_id}",
        "kind": 1,  # SPAN_KIND_INTERNAL
        "startTimeUnixNano": start_ns,
        "endTimeUnixNano": end_ns,
        "status": _status(overall_status),
        "attributes": _attrs(
            ("job_id", scope.get("job_id")),
            ("correlation_id", scope.get("correlation_id")),
            ("caller", scope.get("caller")),
            ("tenant_id", scope.get("tenant_id")),
            ("dataset_id", scope.get("dataset_id")),
            ("service_id", scope.get("service_id")),
            ("pipeline.job_id", job_id),
        ),
    }


def _build_stage_span(
    *,
    trace_id: str,
    root_span_id: str,
    job_id: str,
    event: dict[str, Any],
) -> dict[str, Any]:
    stage = str(event.get("stage") or "unknown")
    role = str(event.get("role") or "")
    span_id = _to_span_id(job_id, stage, role)

    ts_ns = _parse_ts(event.get("ts_utc"))
    dur_ns = _duration_to_ns(event.get("duration_ms"))
    now_ns = int(time.time() * 1_000_000_000)
    start_ns = ts_ns or now_ns
    end_ns = (start_ns + dur_ns) if dur_ns else start_ns

    name = f"pipeline/{stage}/{role}" if role else f"pipeline/{stage}"

    return {
        "traceId": trace_id,
        "spanId": span_id,
        "parentSpanId": root_span_id,
        "name": name,
        "kind": 1,
        "startTimeUnixNano": start_ns,
        "endTimeUnixNano": end_ns,
        "status": _status(event.get("status")),
        "attributes": _attrs(
            ("pipeline.stage", stage),
            ("pipeline.role", role or None),
            ("pipeline.status", event.get("status")),
            ("pipeline.decision", event.get("decision")),
            ("pipeline.reason_code", event.get("reason_code")),
            ("pipeline.row_count", event.get("row_count")),
            ("pipeline.duration_ms", event.get("duration_ms")),
            ("job_id", job_id),
        ),
    }


def _push_otlp_http(
    *,
    endpoint_url: str,
    spans: list[dict[str, Any]],
    timeout_sec: float,
    bearer_token: str | None,
) -> dict[str, Any]:
    """Best-effort OTLP/HTTP-JSON push of pre-built spans.

    Wraps the spans in the OTLP ExportTraceServiceRequest JSON shape and POSTs
    to ``<endpoint_url>/v1/traces``. Resource and instrumentation-scope blocks
    are kept minimal so the receiver can still index by trace id without
    bringing in the full ``opentelemetry-exporter-otlp`` dependency. Returns a
    push-result summary (status_code or transport_error)."""
    import urllib.error
    import urllib.request

    base = endpoint_url.rstrip("/")
    target_url = base if base.endswith("/v1/traces") else f"{base}/v1/traces"
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "seccomp-privacy-pipeline"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "seccomp-privacy-platform.observability"},
                        "spans": spans,
                    }
                ],
            }
        ]
    }
    headers = {"Content-Type": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(target_url, data=body, method="POST", headers=headers)
    started_at = time.perf_counter() if "time" in globals() else None
    status_code = 0
    transport_error: str | None = None
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            response.read()
            status_code = int(response.status)
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        transport_error = f"HTTPError: {exc}"
    except Exception as exc:
        transport_error = f"{type(exc).__name__}: {exc}"
    return {
        "endpoint_url": target_url,
        "span_count": len(spans),
        "status_code": status_code,
        "ok": transport_error is None and 200 <= status_code < 300,
        "transport_error": transport_error,
    }


def export_spans(
    *,
    observability_path: str,
    spans_out: str,
    report_out: str,
    otlp_endpoint: str = "",
    otlp_bearer_env: str = "",
    otlp_timeout_sec: float = 5.0,
) -> dict[str, Any]:
    obs_path = Path(observability_path)
    obs = json.loads(obs_path.read_text(encoding="utf-8"))

    job_id = str(obs.get("job_id") or "unknown")
    scope = {
        "job_id": obs.get("job_id"),
        "correlation_id": obs.get("correlation_id"),
        "caller": obs.get("caller"),
        "tenant_id": obs.get("tenant_id"),
        "dataset_id": obs.get("dataset_id"),
        "service_id": obs.get("service_id"),
    }
    events: list[dict[str, Any]] = obs.get("events") or []

    trace_id = _to_trace_id(job_id)
    root_span = _build_root_span(trace_id=trace_id, job_id=job_id, scope=scope, events=events)
    root_span_id = root_span["spanId"]

    stage_spans = [
        _build_stage_span(trace_id=trace_id, root_span_id=root_span_id, job_id=job_id, event=e)
        for e in events
    ]
    all_spans = [root_span] + stage_spans

    # Write OTLP-compatible JSONL (one span per line)
    spans_path = Path(spans_out)
    spans_path.parent.mkdir(parents=True, exist_ok=True)
    with spans_path.open("w", encoding="utf-8") as f:
        for span in all_spans:
            f.write(json.dumps(span, ensure_ascii=False) + "\n")

    # Compute total duration
    total_ms: float | None = None
    dur_values = [e.get("duration_ms") for e in events if e.get("duration_ms") is not None]
    if dur_values:
        total_ms = sum(float(v) for v in dur_values)

    report = {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": _utc_now(),
        "source_path": str(obs_path.resolve()),
        "job_id": scope["job_id"],
        "correlation_id": scope["correlation_id"],
        "caller": scope["caller"],
        "tenant_id": scope["tenant_id"],
        "trace_id": trace_id,
        "root_span_id": root_span_id,
        "span_count": len(all_spans),
        "spans_path": str(spans_path.resolve()),
        "stage_names": sorted({str(e.get("stage") or "") for e in events if e.get("stage")}),
        "duration_ms_total": total_ms,
    }

    if otlp_endpoint:
        bearer_token = os.environ.get(otlp_bearer_env, "").strip() if otlp_bearer_env else ""
        push_result = _push_otlp_http(
            endpoint_url=otlp_endpoint,
            spans=all_spans,
            timeout_sec=otlp_timeout_sec,
            bearer_token=bearer_token or None,
        )
        report["otlp_push"] = push_result

    if report_out:
        report_path = Path(report_out)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return report


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="B13: Convert pipeline_observability/v1 to OpenTelemetry OTLP-compatible spans"
    )
    ap.add_argument("--observability", required=True, help="Path to pipeline_observability/v1 JSON file")
    ap.add_argument("--spans-out", required=True, help="Path to write OTel spans JSONL")
    ap.add_argument("--report-out", default="", help="Path to write otel_export_report/v1 JSON")
    ap.add_argument("--out-base", default="", help="Infer --observability and --spans-out from this run directory")
    ap.add_argument("--otlp-endpoint", default="", help="If set, also POST the spans as OTLP/HTTP-JSON to <endpoint>/v1/traces (best-effort; transport errors are recorded in the report).")
    ap.add_argument("--otlp-bearer-env", default="", help="Optional env var holding a bearer token to attach as Authorization: Bearer <token>.")
    ap.add_argument("--otlp-timeout-sec", type=float, default=5.0, help="Timeout for the OTLP/HTTP push.")
    return ap


def main() -> int:
    args = build_parser().parse_args()

    observability = args.observability
    spans_out = args.spans_out

    if args.out_base and not observability:
        base = Path(args.out_base)
        observability = str(base / "pipeline_observability.json")
        if not spans_out:
            spans_out = str(base / "otel_spans.jsonl")
        if not args.report_out:
            args.report_out = str(base / "otel_export_report.json")

    if not observability:
        raise SystemExit("[ERROR] --observability or --out-base is required")
    if not spans_out:
        raise SystemExit("[ERROR] --spans-out or --out-base is required")

    report = export_spans(
        observability_path=observability,
        spans_out=spans_out,
        report_out=args.report_out,
        otlp_endpoint=args.otlp_endpoint,
        otlp_bearer_env=args.otlp_bearer_env,
        otlp_timeout_sec=args.otlp_timeout_sec,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
