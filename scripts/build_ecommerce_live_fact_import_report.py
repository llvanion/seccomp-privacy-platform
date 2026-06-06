#!/usr/bin/env python3
"""Build a typed live e-commerce fact-import report from verifier-facing evidence."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "ecommerce_live_fact_import_report/v1"
JOB_SMOKE_SCHEMA = "ecommerce_fact_import_job_smoke/v1"
JOB_REPORT_SCHEMA = "ecommerce_fact_import_job/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path_value: str) -> dict[str, Any]:
    path = Path(path_value).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def write_json(path_value: str, payload: dict[str, Any]) -> None:
    path = Path(path_value).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_schema(payload: dict[str, Any], *, expected: str, label: str) -> None:
    actual = str(payload.get("schema") or "")
    if actual != expected:
        raise ValueError(f"{label} must use {expected}; got {actual!r}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant-id", default="commerce_tenant")
    ap.add_argument("--dataset-id", default="orders_analytics")
    ap.add_argument("--table", default="orders")
    ap.add_argument("--source-kind", default="batch_manifest")
    ap.add_argument("--job-smoke-report", required=True)
    ap.add_argument("--allow-job-report", required=True)
    ap.add_argument("--reject-job-report", required=True)
    ap.add_argument("--operator-approval-ref", default="")
    ap.add_argument("--output", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()

    smoke = load_json(args.job_smoke_report)
    require_schema(smoke, expected=JOB_SMOKE_SCHEMA, label="--job-smoke-report")

    allow_job = load_json(args.allow_job_report)
    reject_job = load_json(args.reject_job_report)
    require_schema(allow_job, expected=JOB_REPORT_SCHEMA, label="--allow-job-report")
    require_schema(reject_job, expected=JOB_REPORT_SCHEMA, label="--reject-job-report")

    findings: list[str] = []
    allow_job_status = str(smoke.get("allow_job_status") or "")
    allow_result_decision = str(smoke.get("allow_result_decision") or "")
    allow_inserted = int(smoke.get("allow_inserted_row_count") or 0)
    reject_job_status = str(smoke.get("reject_job_status") or "")
    reject_result_decision = str(smoke.get("reject_result_decision") or "")
    reject_reason_code = str(smoke.get("reject_reason_code") or "") or None

    if smoke.get("status") != "ok":
        findings.append("fact import smoke status is not ok")
    if allow_job_status != "ok":
        findings.append("allow path fact import job did not finish with status=ok")
    if allow_result_decision != "allow":
        findings.append("allow path fact import result did not return decision=allow")
    if allow_inserted <= 0:
        findings.append("allow path fact import did not insert any rows")
    if reject_job_status != "ok":
        findings.append("reject path fact import job did not finish with status=ok")
    if reject_result_decision != "deny":
        findings.append("reject path fact import result did not return decision=deny")
    if not reject_reason_code:
        findings.append("reject path fact import did not expose a reason_code")
    if int(smoke.get("orders_row_count_after_allow") or 0) != int(smoke.get("orders_row_count_after_reject") or 0):
        findings.append("reject path fact import changed post-allow row count")

    import_job = {
        "job_id": str(allow_job.get("job_id") or "ecommerce-live-fact-import"),
        "source_kind": args.source_kind,
        "table": args.table,
        "tenant_id": args.tenant_id,
        "dataset_id": args.dataset_id,
    }
    result = {
        "decision": "allow" if allow_result_decision == "allow" else "deny",
        "inserted_row_count": allow_inserted,
        "protected_column_reject_verified": reject_result_decision == "deny",
        "reason_code": reject_reason_code,
    }
    evidence = {
        "job_report_path": str(Path(args.allow_job_report).resolve()),
        "result_report_path": str(Path(args.job_smoke_report).resolve()),
        "operator_approval_ref": args.operator_approval_ref or None,
    }
    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if not findings else "fail",
        "import_job": import_job,
        "result": result,
        "evidence": evidence,
        "findings": findings,
    }
    write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
