#!/usr/bin/env python3
"""Submit a pipeline workflow to Temporal.

This is the client-side entrypoint. It constructs a PipelineContext from CLI args
and submits the workflow to a Temporal server.

Usage:
  # Submit a full pipeline workflow
  python3 scripts/temporal/run_workflow.py \\
    --server-source sse/examples/bridge_server_records.jsonl \\
    --client-source sse/examples/bridge_client_records.jsonl \\
    --server-join-key-field email \\
    --client-join-key-field email \\
    --client-value-field amount \\
    --token-scope temporal-demo \\
    --token-secret-env BRIDGE_TOKEN_SECRET \\
    --job-id temporal_demo_job \\
    --out-base tmp/temporal_demo

  # Submit a policy-validation-only workflow
  python3 scripts/temporal/run_workflow.py \\
    --workflow validate-policy-only \\
    --sse-export-policy-config sse/config/export_policy.example.json \\
    --caller auto_demo \\
    --job-id policy_check_job \\
    --out-base tmp/policy_check

Requirements:
  pip install temporalio
"""

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from temporalio.client import Client

from activities import PipelineContext
from workflow import SseBridgeApsiPipelineWorkflow, ValidatePolicyOnlyWorkflow


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def main():
    ap = argparse.ArgumentParser(
        description="Submit a seccomp-privacy-platform pipeline workflow to Temporal"
    )
    ap.add_argument("--temporal-host", default="localhost:7233")
    ap.add_argument("--temporal-namespace", default="seccomp-dev")
    ap.add_argument("--task-queue", default="seccomp-pipeline")
    ap.add_argument("--workflow", choices=["full-pipeline", "validate-policy-only"],
                    default="full-pipeline")
    ap.add_argument("--server-source", default="")
    ap.add_argument("--client-source", default="")
    ap.add_argument("--server-join-key-field", default="email")
    ap.add_argument("--client-join-key-field", default="email")
    ap.add_argument("--client-value-field", default="amount")
    ap.add_argument("--server-normalizer", default="email")
    ap.add_argument("--client-normalizer", default="email")
    ap.add_argument("--client-value-mode", default="raw-int")
    ap.add_argument("--server-filter", default="")
    ap.add_argument("--client-filter", default="")
    ap.add_argument("--token-scope", default="")
    ap.add_argument("--token-secret-env", default="BRIDGE_TOKEN_SECRET")
    ap.add_argument("--token-key-version", default="1")
    ap.add_argument("--production-mode", action="store_true")
    ap.add_argument("--sse-export-policy-config", default="")
    ap.add_argument("--sse-export-handoff-mode", default="file")
    ap.add_argument("--server-sse-keyword", default="")
    ap.add_argument("--client-sse-keyword", default="")
    ap.add_argument("--server-record-id-field", default="")
    ap.add_argument("--client-record-id-field", default="")
    ap.add_argument("--job-id", default="")
    ap.add_argument("--out-base", required=True)
    ap.add_argument("--caller", default="temporal_workflow")
    ap.add_argument("--tenant-id", default="default_tenant")
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--deny-duplicate-query", action="store_true")
    ap.add_argument("--audit-seal-key-env", default="")
    ap.add_argument("--wait", action="store_true", help="Wait for workflow completion")
    args = ap.parse_args()

    job_id = args.job_id or f"temporal_{uuid.uuid4().hex[:12]}"
    out_base = os.path.abspath(args.out_base)

    ctx = PipelineContext(
        job_id=job_id,
        correlation_id=job_id,
        caller=args.caller,
        tenant_id=args.tenant_id,
        out_base=out_base,
        sse_export_dir=os.path.join(out_base, "sse_exports"),
        bridge_job_dir=os.path.join(out_base, "bridge_job"),
        apsi_job_dir=os.path.join(out_base, "a_psi_run"),
        token_scope=args.token_scope or job_id,
        token_secret_env=args.token_secret_env,
        token_key_version=args.token_key_version,
        production_mode=args.production_mode,
        sse_export_policy_config=os.path.abspath(args.sse_export_policy_config) if args.sse_export_policy_config else "",
        sse_export_handoff_mode=args.sse_export_handoff_mode,
        server_source=os.path.abspath(args.server_source) if args.server_source else "",
        client_source=os.path.abspath(args.client_source) if args.client_source else "",
        server_join_key_field=args.server_join_key_field,
        client_join_key_field=args.client_join_key_field,
        client_value_field=args.client_value_field,
        server_normalizer=args.server_normalizer,
        client_normalizer=args.client_normalizer,
        client_value_mode=args.client_value_mode,
        server_filter=args.server_filter,
        client_filter=args.client_filter,
        k_threshold=args.k,
        rate_n=args.n,
        deny_duplicate_query=args.deny_duplicate_query,
        audit_seal_key_env=args.audit_seal_key_env,
        server_sse_keyword=args.server_sse_keyword,
        client_sse_keyword=args.client_sse_keyword,
        server_record_id_field=args.server_record_id_field,
        client_record_id_field=args.client_record_id_field,
    )

    for d in [out_base, ctx.sse_export_dir, ctx.bridge_job_dir, ctx.apsi_job_dir]:
        os.makedirs(d, exist_ok=True)

    ctx_dict = ctx.to_dict()
    client = await Client.connect(args.temporal_host, namespace=args.temporal_namespace)
    print(f"[client] Connected to Temporal: {args.temporal_host} namespace={args.temporal_namespace}")

    if args.workflow == "validate-policy-only":
        wf_id = f"validate-policy-{job_id}"
        print(f"[client] Starting ValidatePolicyOnly workflow: {wf_id}")
        handle = await client.start_workflow(
            ValidatePolicyOnlyWorkflow.run,
            ctx_dict,
            id=wf_id,
            task_queue=args.task_queue,
        )
    else:
        wf_id = f"seccomp-pipeline-{job_id}"
        print(f"[client] Starting SseBridgeApsiPipeline workflow: {wf_id}")
        handle = await client.start_workflow(
            SseBridgeApsiPipelineWorkflow.run,
            ctx_dict,
            id=wf_id,
            task_queue=args.task_queue,
        )

    print(f"[client] Workflow submitted: id={wf_id} run_id={handle.result_run_id}")

    if args.wait:
        print("[client] Waiting for workflow to complete...")
        result = await handle.result()
        result_path = os.path.join(out_base, "workflow_result.json")
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.write("\n")
        final = result.get("final_decision", "unknown")
        print(f"[client] Workflow completed: decision={final}")
        print(f"[client] Result written to: {result_path}")
    else:
        print(f"[client] Workflow running asynchronously. Query with:")
        print(f"  temporal workflow describe --workflow-id {wf_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
