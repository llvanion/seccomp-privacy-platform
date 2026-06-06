#!/usr/bin/env python3
"""Determine whether a failed query workflow job is eligible for retry vs re-submit."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
ELIGIBILITY_SCHEMA = "workflow_retry_eligibility/v1"
STATUS_SCHEMA = "query_workflow_status/v1"
RECEIPT_SCHEMA = "query_workflow_receipt/v1"


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


def load_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                result.append(obj)
        except json.JSONDecodeError:
            pass
    return result


def last_error_class(receipts: list[dict[str, Any]]) -> str | None:
    """Return the error_class of the last receipt that carries one."""
    for receipt in reversed(receipts):
        ec = receipt.get("error_class")
        if ec:
            return str(ec)
    return None


def evaluate(
    status: dict[str, Any],
    receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    state = str(status.get("state") or "unknown")
    terminal = bool(status.get("terminal"))
    last_exit_code = status.get("last_exit_code")
    error_class = last_error_class(receipts)

    if not terminal:
        if state == "queued":
            return {
                "retryable": False,
                "resubmit_required": False,
                "recommended_action": "wait",
                "reason": "Job is queued for a DB-backed worker — wait for a worker claim or cancel the queued execution",
                "triage_steps": [
                    "Run scripts/run_query_workflow_worker.py against the metadata DB",
                    "Inspect query_workflow_executions for lease owner and state",
                ],
            }
        if state == "cancel_requested":
            return {
                "retryable": False,
                "resubmit_required": False,
                "recommended_action": "wait",
                "reason": "Cancellation has been requested and the worker must terminate the execution",
                "triage_steps": [
                    "Poll query_workflow/status.json until terminal=true",
                    "Inspect worker receipts and query_workflow_executions metadata_json for cancel details",
                ],
            }
        return {
            "retryable": False,
            "resubmit_required": False,
            "recommended_action": "wait",
            "reason": f"Job is in non-terminal state '{state}' — wait for completion before deciding",
            "triage_steps": [
                "Poll query_workflow/status.json until terminal=true",
                "Use GET /v1/query-workflows/status?out_base=<path> to read live status",
            ],
        }

    if state == "completed":
        return {
            "retryable": False,
            "resubmit_required": False,
            "recommended_action": "none",
            "reason": "Job completed successfully — no retry needed",
            "triage_steps": [
                "Inspect public_report.json and audit_chain.json for results",
                "Use observability dashboard and alert check for post-run review",
            ],
        }

    if state == "rejected":
        if error_class == "validation_rejected":
            return {
                "retryable": False,
                "resubmit_required": True,
                "recommended_action": "resubmit",
                "reason": "Request failed validation — fix the request shape and re-submit",
                "triage_steps": [
                    "Review the redacted_command and request_summary in submission_manifest.json",
                    "Fix query_workflow_request/v1 fields (schema, query_type, secret mode, etc.)",
                    "Re-submit after correction",
                ],
            }
        if error_class == "authz_rejected":
            return {
                "retryable": False,
                "resubmit_required": True,
                "recommended_action": "resubmit",
                "reason": "Request was rejected by identity/permission check — resolve authz and re-submit",
                "triage_steps": [
                    "Verify caller identity and platform_roles via GET /v1/identity",
                    "Check caller permissions in the metadata DB: scripts/query_metadata.py --list-entity caller-permissions",
                    "Re-submit after identity or permission fix",
                ],
            }
        return {
            "retryable": False,
            "resubmit_required": True,
            "recommended_action": "resubmit",
            "reason": f"Job rejected (error_class={error_class!r}) — re-submit after resolving the rejection cause",
            "triage_steps": [
                "Check execution_receipts.jsonl for the rejection event and error_class",
                "Re-submit after resolving the rejection cause",
            ],
        }

    if state == "failed":
        if error_class == "launch_failed":
            return {
                "retryable": True,
                "resubmit_required": False,
                "recommended_action": "retry",
                "reason": "Pipeline launch failed — transient environment issue; retry is acceptable",
                "triage_steps": [
                    "Check platform health: scripts/check_platform_health.py --out-base <path>",
                    "Verify the pipeline script is executable and dependencies are present",
                    "Retry the same request (duplicate-query guard uses job_id — choose a new job_id if needed)",
                ],
            }
        if error_class == "run_failed" or (last_exit_code is not None and last_exit_code != 0):
            return {
                "retryable": False,
                "resubmit_required": True,
                "recommended_action": "resubmit",
                "reason": (
                    f"Pipeline ran but exited non-zero (exit_code={last_exit_code}) — "
                    "inspect artifacts before re-submitting"
                ),
                "triage_steps": [
                    "Check failure_summary in observability_dashboard/v1 for the failing stage",
                    "Review audit_chain.json and the stage-level audit records for the error",
                    "Fix the underlying issue, then re-submit with a new job_id to avoid duplicate-query guard",
                ],
            }
        return {
            "retryable": False,
            "resubmit_required": True,
            "recommended_action": "resubmit",
            "reason": f"Job failed with unclassified error (error_class={error_class!r}) — investigate before re-submitting",
            "triage_steps": [
                "Review execution_receipts.jsonl for the failure event",
                "Check observability dashboard and platform health before re-submitting",
            ],
        }

    if state == "cancelled":
        return {
            "retryable": False,
            "resubmit_required": True,
            "recommended_action": "resubmit",
            "reason": "Job was cancelled by operator request — submit a new approved request if work should run again",
            "triage_steps": [
                "Review execution_receipts.jsonl for cancel_requested/cancelled events",
                "Confirm the cancellation actor and reason in query_workflow_executions metadata_json",
                "Re-submit with a new job_id/out_base if the query is still needed",
            ],
        }

    if state == "timed_out":
        return {
            "retryable": False,
            "resubmit_required": True,
            "recommended_action": "resubmit",
            "reason": "Worker timeout terminated the run — investigate capacity or input size before re-submitting",
            "triage_steps": [
                "Check worker timeout_seconds and platform SLO tier for this dataset size",
                "Inspect pipeline observability and stage logs if partial artifacts exist",
                "Re-submit with a new job_id/out_base after tuning timeout/capacity",
            ],
        }

    return {
        "retryable": False,
        "resubmit_required": False,
        "recommended_action": "investigate",
        "reason": f"Unrecognised terminal state '{state}' — manual investigation required",
        "triage_steps": [
            "Check execution_receipts.jsonl for the most recent lifecycle event",
            "Contact platform operator if the state is unexpected",
        ],
    }


def build_eligibility_report(
    status: dict[str, Any],
    receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    if status.get("schema") != STATUS_SCHEMA:
        raise ValueError(f"unexpected status schema: {status.get('schema')!r}")
    decision = evaluate(status, receipts)
    return {
        "schema": ELIGIBILITY_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "job_id": status.get("job_id"),
        "correlation_id": status.get("correlation_id"),
        "caller": status.get("caller"),
        "tenant_id": status.get("tenant_id"),
        "current_state": status.get("state"),
        "terminal": status.get("terminal"),
        "last_exit_code": status.get("last_exit_code"),
        "receipt_count": status.get("receipt_count"),
        "retryable": decision["retryable"],
        "resubmit_required": decision["resubmit_required"],
        "recommended_action": decision["recommended_action"],
        "reason": decision["reason"],
        "triage_steps": decision["triage_steps"],
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Determine retry eligibility for a query workflow job.",
    )
    ap.add_argument("--status-file", required=True, help="Path to query_workflow/status.json")
    ap.add_argument("--receipts-file", default="", help="Optional path to execution_receipts.jsonl for richer error_class resolution")
    ap.add_argument("--out", default="", help="Output path for workflow_retry_eligibility.json")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    status_path = repo_path(args.status_file)
    status = load_json_object(status_path)
    receipts: list[dict[str, Any]] = []
    if args.receipts_file:
        receipts_path = repo_path(args.receipts_file)
        if receipts_path.is_file():
            receipts = load_jsonl_objects(receipts_path)
    elif status_path.parent.name == "query_workflow":
        default_receipts = status_path.parent / "execution_receipts.jsonl"
        if default_receipts.is_file():
            receipts = load_jsonl_objects(default_receipts)
    report = build_eligibility_report(status, receipts)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out_path = repo_path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
