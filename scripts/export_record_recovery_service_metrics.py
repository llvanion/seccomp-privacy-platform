#!/usr/bin/env python3
"""
D2: derive operational metrics from record_recovery_service_log/v1 JSONL.

This adapter is read-only. It summarizes structured runtime logs emitted by
the standalone record recovery service without changing the service protocol,
audit contract, or pipeline semantics.
"""
import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_SCHEMA = "record_recovery_service_metrics/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"[ERROR] invalid JSONL at {path}:{line_no}: {exc}") from exc
            if not isinstance(payload, dict):
                raise SystemExit(f"[ERROR] JSON object expected at {path}:{line_no}")
            records.append(payload)
    return records


def count_field(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        value = record.get(field)
        if value is None or value == "":
            continue
        counts[str(value)] += 1
    return dict(sorted(counts.items()))


def unique_field(records: list[dict[str, Any]], field: str) -> list[str]:
    values = {
        str(record.get(field))
        for record in records
        if record.get(field) is not None and record.get(field) != ""
    }
    return sorted(values)


def duration_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    values: list[float] = []
    for record in records:
        value = record.get("duration_ms")
        if isinstance(value, (int, float)) and value >= 0:
            values.append(float(value))
    if not values:
        return {"count": 0, "min": None, "max": None, "avg": None, "p95": None}
    values.sort()
    p95_index = min(len(values) - 1, int((len(values) - 1) * 0.95))
    return {
        "count": len(values),
        "min": values[0],
        "max": values[-1],
        "avg": round(sum(values) / len(values), 3),
        "p95": values[p95_index],
    }


def build_report(records: list[dict[str, Any]], source_path: Path) -> dict[str, Any]:
    requests = [r for r in records if r.get("event") == "record_recovery_service_request"]
    decisions = count_field(requests, "decision")
    status_code_counts = count_field(requests, "status_code")
    client_error_count = 0
    server_error_count = 0
    for record in requests:
        status_code = record.get("status_code")
        if isinstance(status_code, int):
            if 400 <= status_code < 500:
                client_error_count += 1
            elif status_code >= 500:
                server_error_count += 1

    candidate_count_total = 0
    for record in requests:
        candidate_count = record.get("candidate_count")
        if isinstance(candidate_count, int) and candidate_count >= 0:
            candidate_count_total += candidate_count

    return {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "source_path": str(source_path.resolve()),
        "event_count": len(records),
        "request_count": len(requests),
        "recover_request_count": sum(1 for r in requests if r.get("op") == "recover"),
        "health_request_count": sum(1 for r in requests if r.get("op") == "health"),
        "allow_count": int(decisions.get("allow", 0)),
        "deny_count": int(decisions.get("deny", 0)),
        "client_error_count": client_error_count,
        "server_error_count": server_error_count,
        "candidate_count_total": candidate_count_total,
        "transports": unique_field(records, "transport"),
        "service_ids": unique_field(records, "service_id"),
        "tenant_ids": unique_field(records, "tenant_id"),
        "dataset_ids": unique_field(records, "dataset_id"),
        "event_counts": count_field(records, "event"),
        "decision_counts": decisions,
        "reason_code_counts": count_field(requests, "reason_code"),
        "op_counts": count_field(requests, "op"),
        "method_counts": count_field(requests, "method"),
        "role_counts": count_field(requests, "role"),
        "status_code_counts": status_code_counts,
        "duration_ms": duration_summary(requests),
    }


def require_expectations(report: dict[str, Any], args: argparse.Namespace) -> None:
    if args.expect_transport and args.expect_transport not in set(report.get("transports") or []):
        raise SystemExit(f"[ERROR] expected transport missing: {args.expect_transport}")
    if args.expect_min_requests is not None and report["request_count"] < args.expect_min_requests:
        raise SystemExit(
            f"[ERROR] expected at least {args.expect_min_requests} requests, got {report['request_count']}"
        )
    event_counts = report.get("event_counts") or {}
    for event in args.expect_event:
        if int(event_counts.get(event, 0)) <= 0:
            raise SystemExit(f"[ERROR] expected event missing: {event}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export record_recovery_service_metrics/v1 from structured service runtime logs."
    )
    parser.add_argument("--log-jsonl", required=True, help="Path to record_recovery_service_log/v1 JSONL")
    parser.add_argument("--out", default="", help="Optional path to write the metrics JSON report")
    parser.add_argument("--expect-transport", choices=["unix_socket", "http"], default="")
    parser.add_argument("--expect-event", action="append", default=[], help="Require at least one event")
    parser.add_argument("--expect-min-requests", type=int, default=None)
    args = parser.parse_args()

    log_path = Path(args.log_jsonl)
    if not log_path.is_file():
        raise SystemExit(f"[ERROR] missing service log: {log_path}")
    report = build_report(load_jsonl(log_path), log_path)
    require_expectations(report, args)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
