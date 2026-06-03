#!/usr/bin/env python3
"""Manage privacy-budget approval requests in the transactional store."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_SCRIPTS = REPO_ROOT / "a-psi" / "moduleA_psi" / "scripts"
sys.path.insert(0, str(POLICY_SCRIPTS))

import policy_release  # noqa: E402


def append_jsonl(path: str, record: dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def require_reason(action: str, reason: str) -> str:
    reason = reason.strip()
    if action in {"reject", "expire"} and not reason:
        raise SystemExit(f"[ERROR] {action} requires --reason")
    return reason


def build_decision_record(
    *,
    request: dict[str, Any],
    action: str,
    actor: str,
    reason: str,
    expires_at_utc: str | None,
) -> dict[str, Any]:
    status = {
        "approve": "approved",
        "reject": "rejected",
        "expire": "expired",
    }[action]
    return {
        "schema": "privacy_budget_approval_decision/v1",
        "created_at_utc": policy_release.utc_now_iso(),
        "action": action,
        "status": status,
        "request_id": request["request_id"],
        "actor": actor,
        "caller": request["caller"],
        "tenant_id": request.get("tenant_id"),
        "dataset_id": request.get("dataset_id"),
        "purpose": request.get("purpose"),
        "job_id": request.get("job_id"),
        "consuming_job_id": None,
        "query_fingerprint": request.get("query_fingerprint"),
        "query_payload_sha256": request.get("query_payload_sha256"),
        "reason": reason or f"privacy budget approval {action}",
        "expires_at_utc": expires_at_utc,
        "public_report_sha256": request.get("public_report_sha256"),
        "budget_consumed": False,
        "consuming_event_id": None,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Approve, reject, expire, or list privacy-budget approval requests.")
    ap.add_argument("--store", required=True, help="SQLite privacy-budget store path")
    ap.add_argument("--approval-queue", default="", help="Optional privacy_budget_approval_request/v1 JSONL to bootstrap into the store")
    ap.add_argument("--decisions", default="", help="Optional privacy_budget_approval_decision/v1 JSONL path")
    ap.add_argument("--request-id", default="", help="Approval request id for approve/reject/expire")
    ap.add_argument("--actor", default="", help="Identity performing the transition")
    ap.add_argument("--reason", default="", help="Decision reason")
    ap.add_argument("--expires-at-utc", default="", help="Optional approval expiry timestamp")
    ap.add_argument("--status", default="", help="Filter for list action")
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="List approval requests")
    sub.add_parser("approve", help="Approve a pending request")
    sub.add_parser("reject", help="Reject a pending request")
    sub.add_parser("expire", help="Expire a pending or approved request")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.action != "list":
        if not args.request_id:
            raise SystemExit("[ERROR] transition action requires --request-id")
        if not args.actor:
            raise SystemExit("[ERROR] transition action requires --actor")
    with policy_release.PrivacyBudgetStore(os.path.abspath(args.store)) as store:
        store.begin_immediate()
        store.bootstrap_approval_requests(args.approval_queue or None)
        store.bootstrap_approval_decisions(args.decisions or None)
        if args.action == "list":
            requests = store.list_approval_requests(status=args.status or None)
            store.commit()
            report = {
                "schema": "privacy_budget_approval_list/v1",
                "status": "ok",
                "filter_status": args.status or None,
                "returned_count": len(requests),
                "requests": requests,
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        request = store.load_approval_request(args.request_id)
        if request is None:
            raise SystemExit(f"[ERROR] approval request not found: {args.request_id}")
        reason = require_reason(args.action, args.reason)
        if args.action == "approve" and args.actor == str(request.get("caller") or ""):
            raise SystemExit("[ERROR] same_identity_self_approval")
        record = build_decision_record(
            request=request,
            action=args.action,
            actor=args.actor,
            reason=reason,
            expires_at_utc=args.expires_at_utc or None,
        )
        updated = store.transition_approval_request(
            request_id=args.request_id,
            action=args.action,
            actor=args.actor,
            reason=reason,
            expires_at_utc=args.expires_at_utc or None,
            decision_record=record,
        )
        if args.decisions:
            append_jsonl(args.decisions, record)
        store.commit()
        if updated.get("status") != record["status"]:
            raise SystemExit(f"[ERROR] transition did not reach expected status: {updated.get('status')}")
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
