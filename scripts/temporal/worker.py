#!/usr/bin/env python3
"""Temporal Worker for the SSE-Bridge-A-PSI pipeline.

Starts a Temporal worker that listens for workflow tasks and executes activities.
Each activity wraps an existing CLI call — no privacy-compute logic is rewritten.

Usage:
  # Start a worker (requires Temporal server running)
  python3 scripts/temporal/worker.py --task-queue seccomp-pipeline

  # With custom Temporal endpoint
  python3 scripts/temporal/worker.py \
    --temporal-host localhost:7233 \
    --temporal-namespace seccomp-dev \
    --task-queue seccomp-pipeline

Requirements:
  pip install temporalio
"""

import argparse
import asyncio
import os
import sys

# Add repo root to path so activities can import
sys.path.insert(0, os.path.dirname(__file__))

from temporalio.client import Client
from temporalio.worker import Worker

from activities import (
    build_audit_chain_activity,
    run_bridge_prepare_job_activity,
    run_pjc_activity,
    run_policy_release_activity,
    run_record_recovery_health_check_activity,
    run_runbook_activity,
    run_sse_export_activity,
    run_telemetry_activity,
    validate_policy_activity,
)
from workflow import SseBridgeApsiPipelineWorkflow, ValidatePolicyOnlyWorkflow


def get_activities():
    return [
        validate_policy_activity,
        run_sse_export_activity,
        run_record_recovery_health_check_activity,
        run_bridge_prepare_job_activity,
        run_pjc_activity,
        run_policy_release_activity,
        build_audit_chain_activity,
        run_telemetry_activity,
        run_runbook_activity,
    ]


def get_workflows():
    return [
        SseBridgeApsiPipelineWorkflow,
        ValidatePolicyOnlyWorkflow,
    ]


async def main():
    ap = argparse.ArgumentParser(description="Temporal worker for seccomp-privacy-platform pipeline")
    ap.add_argument("--temporal-host", default="localhost:7233")
    ap.add_argument("--temporal-namespace", default="seccomp-dev")
    ap.add_argument("--task-queue", default="seccomp-pipeline")
    args = ap.parse_args()

    client = await Client.connect(args.temporal_host, namespace=args.temporal_namespace)
    print(f"[worker] Connected to Temporal: {args.temporal_host} namespace={args.temporal_namespace}")

    worker = Worker(
        client,
        task_queue=args.task_queue,
        workflows=get_workflows(),
        activities=get_activities(),
    )

    print(f"[worker] Listening on task queue: {args.task_queue}")
    print(f"[worker] Registered {len(get_workflows())} workflow(s), {len(get_activities())} activity(s)")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
