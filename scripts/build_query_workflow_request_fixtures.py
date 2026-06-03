#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path


def build_payload(*, repo_root: Path, request_dir: Path, keep_handoff_files: bool) -> dict[str, object]:
    token_scope = "contract-query-scope-keep" if keep_handoff_files else "contract-query-scope"
    job_id = "contract-query-workflow-keep" if keep_handoff_files else "contract-query-workflow"
    out_base = "../query_workflow_out_keep" if keep_handoff_files else "../query_workflow_out"
    handoff_mode = "file" if keep_handoff_files else "fifo"
    payload = {
        "schema": "query_workflow_request/v1",
        "query_type": "cross_party_match",
        "server_source": os.path.relpath(repo_root / "sse/examples/bridge_server_records.jsonl", request_dir),
        "client_source": os.path.relpath(repo_root / "sse/examples/bridge_client_records.jsonl", request_dir),
        "server_join_key_field": "email",
        "client_join_key_field": "email",
        "client_value_field": "amount",
        "server_normalizer": "email",
        "client_normalizer": "email",
        "client_value_mode": "raw-int",
        "client_value_min": 0,
        "client_value_max": 1000000,
        "server_filters": ["campaign=demo"],
        "client_filters": ["campaign=demo"],
        "token_scope": token_scope,
        "token_secret": "query-workflow-secret",
        "job_id": job_id,
        "out_base": out_base,
        "caller": "auto_demo",
        "tenant_id": "demo_tenant",
        "dataset_id": "bridge_demo_dataset",
        "pjc_resource_limits": os.path.relpath(repo_root / "config/pjc_resource_limits.example.json", request_dir),
        "k": 1,
        "n": 5,
        "sse_export_policy_config": os.path.relpath(repo_root / "sse/config/export_policy.example.json", request_dir),
        "deny_duplicate_query": True,
        "sse_export_handoff_mode": handoff_mode,
        "cleanup_sse_export_handoff_files_after_bridge": not keep_handoff_files,
    }
    if keep_handoff_files:
        payload["handoff_retention_reason"] = "contract_keep_fixture"
    return payload


def build_ecommerce_payload(*, repo_root: Path, request_dir: Path) -> dict[str, object]:
    return {
        "schema": "query_workflow_request/v1",
        "query_type": "cross_party_match",
        "server_source": os.path.relpath(repo_root / "sse/examples/bridge_server_records.jsonl", request_dir),
        "client_source": os.path.relpath(repo_root / "sse/examples/bridge_client_records.jsonl", request_dir),
        "server_join_key_field": "email",
        "client_join_key_field": "email",
        "client_value_field": "amount",
        "server_normalizer": "email",
        "client_normalizer": "email",
        "client_value_mode": "raw-int",
        "client_value_min": 0,
        "client_value_max": 1000000,
        "server_filters": ["campaign=retargeting"],
        "client_filters": ["campaign=retargeting"],
        "token_scope": "ecommerce-query-scope",
        "token_secret": "query-workflow-secret",
        "job_id": "ecommerce-query-workflow",
        "out_base": "../ecommerce_query_workflow_out",
        "caller": "marketing_analyst_demo",
        "tenant_id": "commerce_tenant",
        "dataset_id": "orders_analytics",
        "k": 10,
        "n": 50,
        "sse_export_policy_config": os.path.relpath(repo_root / "sse/config/ecommerce_access_policy.example.json", request_dir),
        "deny_duplicate_query": True,
        "sse_export_handoff_mode": "fifo",
        "cleanup_sse_export_handoff_files_after_bridge": True,
    }


def build_privacy_budget_payload(*, repo_root: Path, request_dir: Path) -> dict[str, object]:
    payload = build_payload(repo_root=repo_root, request_dir=request_dir, keep_handoff_files=False)
    payload.update(
        {
            "job_id": "contract-query-workflow-privacy-budget",
            "out_base": "../query_workflow_out_privacy_budget",
            "privacy_budget_required": True,
            "privacy_budget_config": os.path.relpath(repo_root / "config/privacy_budget.example.json", request_dir),
            "privacy_budget_ledger": "../query_workflow_privacy_budget_ledger.jsonl",
            "privacy_budget_approval_queue": "../query_workflow_privacy_budget_approval_queue.jsonl",
            "privacy_budget_purpose": "campaign_measurement",
            "privacy_budget_limit": 3,
            "privacy_budget_cost": 1.0,
            "release_policy_gate_config": os.path.relpath(repo_root / "config/release_policy_gate.local-contract.example.json", request_dir),
            "policy_require_dp": True,
            "dp_epsilon": 1.0,
            "dp_sensitivity": 500,
            "public_report_redact_operator_fields": True,
            "operator_report_path": "../query_workflow_out_privacy_budget/a_psi_run/operator_report.json",
        }
    )
    return payload


def build_privacy_budget_invalid_payload(
    *,
    repo_root: Path,
    request_dir: Path,
    missing_field: str,
) -> dict[str, object]:
    payload = build_privacy_budget_payload(repo_root=repo_root, request_dir=request_dir)
    payload["job_id"] = f"contract-query-workflow-privacy-budget-missing-{missing_field}"
    payload["out_base"] = f"../query_workflow_out_privacy_budget_missing_{missing_field}"
    payload.pop(missing_field)
    return payload


def write_request(path: Path, *, keep_handoff_files: bool) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    payload = build_payload(
        repo_root=repo_root,
        request_dir=path.resolve().parent,
        keep_handoff_files=keep_handoff_files,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_ecommerce_request(path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    payload = build_ecommerce_payload(repo_root=repo_root, request_dir=path.resolve().parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_privacy_budget_request(path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    payload = build_privacy_budget_payload(repo_root=repo_root, request_dir=path.resolve().parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_privacy_budget_invalid_request(path: Path, *, missing_field: str) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    payload = build_privacy_budget_invalid_payload(
        repo_root=repo_root,
        request_dir=path.resolve().parent,
        missing_field=missing_field,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Build query workflow request fixtures for contract smoke.")
    ap.add_argument("--default-out", required=True)
    ap.add_argument("--keep-out", required=True)
    ap.add_argument("--ecommerce-out", default="")
    ap.add_argument("--privacy-budget-out", default="")
    ap.add_argument("--privacy-budget-missing-config-out", default="")
    ap.add_argument("--privacy-budget-missing-ledger-out", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    write_request(Path(args.default_out), keep_handoff_files=False)
    write_request(Path(args.keep_out), keep_handoff_files=True)
    if args.ecommerce_out:
        write_ecommerce_request(Path(args.ecommerce_out))
    if args.privacy_budget_out:
        write_privacy_budget_request(Path(args.privacy_budget_out))
    if args.privacy_budget_missing_config_out:
        write_privacy_budget_invalid_request(
            Path(args.privacy_budget_missing_config_out),
            missing_field="privacy_budget_config",
        )
    if args.privacy_budget_missing_ledger_out:
        write_privacy_budget_invalid_request(
            Path(args.privacy_budget_missing_ledger_out),
            missing_field="privacy_budget_ledger",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
