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
        "server_filters": ["campaign=demo"],
        "client_filters": ["campaign=demo"],
        "token_scope": token_scope,
        "token_secret": "query-workflow-secret",
        "job_id": job_id,
        "out_base": out_base,
        "caller": "auto_demo",
        "tenant_id": "demo_tenant",
        "dataset_id": "bridge_demo_dataset",
        "k": 1,
        "n": 5,
        "sse_export_policy_config": os.path.relpath(repo_root / "sse/config/export_policy.example.json", request_dir),
        "deny_duplicate_query": True,
        "sse_export_handoff_mode": handoff_mode,
        "cleanup_sse_export_handoff_files_after_bridge": not keep_handoff_files,
    }


def write_request(path: Path, *, keep_handoff_files: bool) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    payload = build_payload(
        repo_root=repo_root,
        request_dir=path.resolve().parent,
        keep_handoff_files=keep_handoff_files,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Build query workflow request fixtures for contract smoke.")
    ap.add_argument("--default-out", required=True)
    ap.add_argument("--keep-out", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    write_request(Path(args.default_out), keep_handoff_files=False)
    write_request(Path(args.keep_out), keep_handoff_files=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
