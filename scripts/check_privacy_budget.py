#!/usr/bin/env python3
"""Summarize and assert a privacy_budget_ledger/v1 JSONL file."""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_ID = "privacy_budget_check_report/v1"
LEDGER_SCHEMA_ID = "privacy_budget_ledger/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_ledger(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            if record.get("schema") != LEDGER_SCHEMA_ID:
                raise ValueError(f"{path}:{lineno}: expected schema {LEDGER_SCHEMA_ID}, got {record.get('schema')!r}")
            records.append(record)
    return records


def summarize(records: list[dict[str, Any]], caller_filter: str | None = None) -> dict[str, Any]:
    filtered = [
        record for record in records
        if caller_filter is None or record.get("caller") == caller_filter
    ]
    by_decision = Counter(str(record.get("decision") or "unknown") for record in filtered)
    by_reason_code = Counter(str(record.get("reason_code") or "unknown") for record in filtered)
    by_abuse_signal = Counter(str(record.get("abuse_signal") or "none") for record in filtered)

    callers: dict[str, dict[str, Any]] = {}
    caller_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in filtered:
        caller_records[str(record.get("caller") or "")].append(record)

    for caller, items in sorted(caller_records.items()):
        consumed = 0
        denied = 0
        budget_cost_total = 0.0
        latest_used_after: float | None = None
        for item in items:
            budget = item.get("budget") if isinstance(item.get("budget"), dict) else {}
            if budget.get("consumed") is True:
                consumed += 1
                budget_cost_total += float(budget.get("cost") or 0.0)
                latest_used_after = float(budget.get("used_after") or budget_cost_total)
            if item.get("decision") == "deny":
                denied += 1
        callers[caller] = {
            "record_count": len(items),
            "allow_count": sum(1 for item in items if item.get("decision") == "allow"),
            "deny_count": denied,
            "consumed_count": consumed,
            "budget_cost_total": budget_cost_total,
            "latest_used_after": latest_used_after,
        }

    findings = []
    for record in filtered:
        if record.get("decision") == "deny" or record.get("abuse_signal"):
            findings.append({
                "job_id": record.get("job_id"),
                "caller": record.get("caller"),
                "decision": record.get("decision"),
                "reason_code": record.get("reason_code"),
                "abuse_signal": record.get("abuse_signal"),
                "matched_prior_job_id": record.get("matched_prior_job_id"),
                "matched_prior_relation": record.get("matched_prior_relation"),
            })

    return {
        "total_records": len(filtered),
        "decision_counts": dict(sorted(by_decision.items())),
        "reason_code_counts": dict(sorted(by_reason_code.items())),
        "abuse_signal_counts": dict(sorted(by_abuse_signal.items())),
        "caller_count": len(callers),
        "callers": callers,
        "finding_count": len(findings),
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize and assert a privacy_budget_ledger/v1 JSONL file")
    parser.add_argument("--ledger", required=True, help="privacy_budget_ledger/v1 JSONL path")
    parser.add_argument("--caller", help="Only summarize one caller")
    parser.add_argument("--output", "--out", dest="output", help="Write privacy_budget_check_report/v1 JSON")
    parser.add_argument("--fail-on-deny", action="store_true", help="Exit non-zero when any deny record is present")
    parser.add_argument("--expect-consumed-min", type=int, default=None,
                        help="Require at least this many consumed allow records")
    parser.add_argument("--expect-deny-reason", action="append", default=[],
                        help="Require at least one deny with this reason_code; may be repeated")
    args = parser.parse_args()

    ledger_path = Path(args.ledger)
    records = load_ledger(ledger_path)
    summary = summarize(records, caller_filter=args.caller)

    errors = []
    if args.fail_on_deny and summary["decision_counts"].get("deny", 0) > 0:
        errors.append("deny_records_present")

    consumed_total = sum(caller["consumed_count"] for caller in summary["callers"].values())
    if args.expect_consumed_min is not None and consumed_total < args.expect_consumed_min:
        errors.append(f"consumed_count_below_min:{consumed_total}<{args.expect_consumed_min}")

    reason_counts = summary["reason_code_counts"]
    for reason in args.expect_deny_reason:
        if reason_counts.get(reason, 0) <= 0:
            errors.append(f"missing_deny_reason:{reason}")

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now(),
        "ledger_path": str(ledger_path.resolve()),
        "caller_filter": args.caller,
        "status": "error" if errors else "ok",
        "summary": summary,
        "errors": errors,
    }

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
