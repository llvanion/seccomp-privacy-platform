"""Temporal Workflow: SSE-Bridge-A-PSI Pipeline with Durable Execution.

This workflow orchestrates the SSE -> Bridge -> PJC -> Policy Release pipeline
using Temporal activities. Each activity wraps an existing CLI call.

The workflow does NOT modify the privacy-compute semantics of the underlying pipeline.
It adds durable execution, retry policies, and structured observability.
"""

from datetime import timedelta
from typing import Any, Dict

from temporalio import workflow
from temporalio.common import RetryPolicy

# Import activities via the standard Temporal pattern
with workflow.unsafe.imports_passed_through():
    from activities import (
        PipelineContext,
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


DEFAULT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],
)


@workflow.defn
class SseBridgeApsiPipelineWorkflow:
    """Durable workflow that executes the full SSE -> Bridge -> A-PSI pipeline.

    Stages:
    1. ValidatePolicy
    2. RunSseExport (server + client)
    3. RunRecordRecoveryHealthCheck
    4. RunBridgePrepareJob
    5. RunPjc
    6. RunPolicyRelease
    7. BuildAuditChain
    8. RunTelemetry
    9. RunRunbook
    """

    @workflow.run
    async def run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        c = PipelineContext.from_dict(ctx)
        workflow.logger.info(f"Workflow started: job_id={c.job_id} caller={c.caller}")

        results: Dict[str, Any] = {
            "job_id": c.job_id,
            "correlation_id": c.correlation_id,
            "caller": c.caller,
            "stages": {},
        }

        # Stage 1: Validate policy
        workflow.logger.info("Stage 1/9: ValidatePolicy")
        policy_result = await workflow.execute_activity(
            validate_policy_activity,
            ctx,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=DEFAULT_RETRY_POLICY,
        )
        results["stages"]["validate_policy"] = policy_result
        if policy_result.get("decision") == "deny":
            workflow.logger.error(f"Policy validation denied: {policy_result.get('reason_code')}")
            results["final_decision"] = "deny"
            results["final_reason"] = "policy_validation_denied"
            return results

        # Stage 2: SSE export
        workflow.logger.info("Stage 2/9: RunSseExport")
        sse_result = await workflow.execute_activity(
            run_sse_export_activity,
            ctx,
            start_to_close_timeout=timedelta(seconds=300),
            retry_policy=DEFAULT_RETRY_POLICY,
        )
        results["stages"]["sse_export"] = sse_result
        if sse_result.get("decision") == "deny":
            workflow.logger.error(f"SSE export denied: {sse_result.get('reason_code')}")
            results["final_decision"] = "deny"
            results["final_reason"] = "sse_export_denied"
            return results

        # Stage 3: Record recovery health check
        workflow.logger.info("Stage 3/9: RunRecordRecoveryHealthCheck")
        recovery_result = await workflow.execute_activity(
            run_record_recovery_health_check_activity,
            ctx,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=DEFAULT_RETRY_POLICY,
        )
        results["stages"]["record_recovery_health_check"] = recovery_result

        # Stage 4: Bridge prepare-job
        workflow.logger.info("Stage 4/9: RunBridgePrepareJob")
        bridge_result = await workflow.execute_activity(
            run_bridge_prepare_job_activity,
            ctx,
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=DEFAULT_RETRY_POLICY,
        )
        results["stages"]["bridge"] = bridge_result
        if bridge_result.get("decision") == "deny":
            workflow.logger.error(f"Bridge denied: {bridge_result.get('reason_code')}")
            results["final_decision"] = "deny"
            results["final_reason"] = "bridge_denied"
            return results

        # Stage 5: PJC execution
        workflow.logger.info("Stage 5/9: RunPjc")
        pjc_result = await workflow.execute_activity(
            run_pjc_activity,
            ctx,
            start_to_close_timeout=timedelta(seconds=600),
            retry_policy=DEFAULT_RETRY_POLICY,
        )
        results["stages"]["pjc"] = pjc_result
        if pjc_result.get("decision") == "deny":
            workflow.logger.error(f"PJC failed: {pjc_result.get('reason_code')}")
            results["final_decision"] = "deny"
            results["final_reason"] = "pjc_failed"
            return results

        # Stage 6: Policy release
        workflow.logger.info("Stage 6/9: RunPolicyRelease")
        release_result = await workflow.execute_activity(
            run_policy_release_activity,
            ctx,
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=DEFAULT_RETRY_POLICY,
        )
        results["stages"]["policy_release"] = release_result

        # Stage 7: Build audit chain
        workflow.logger.info("Stage 7/9: BuildAuditChain")
        audit_result = await workflow.execute_activity(
            build_audit_chain_activity,
            ctx,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=DEFAULT_RETRY_POLICY,
        )
        results["stages"]["audit_chain"] = audit_result

        # Stage 8: Telemetry
        workflow.logger.info("Stage 8/9: RunTelemetry")
        telemetry_result = await workflow.execute_activity(
            run_telemetry_activity,
            ctx,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=DEFAULT_RETRY_POLICY,
        )
        results["stages"]["telemetry"] = telemetry_result

        # Stage 9: Runbook
        workflow.logger.info("Stage 9/9: RunRunbook")
        runbook_result = await workflow.execute_activity(
            run_runbook_activity,
            ctx,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=DEFAULT_RETRY_POLICY,
        )
        results["stages"]["runbook"] = runbook_result

        results["final_decision"] = "allow"
        results["final_reason"] = "pipeline_completed"
        workflow.logger.info(f"Workflow completed: job_id={c.job_id}")
        return results

    @workflow.query
    def get_progress(self) -> Dict[str, Any]:
        return {"job_id": getattr(self, "_job_id", "")}


@workflow.defn
class ValidatePolicyOnlyWorkflow:
    """Lightweight workflow that only validates a pipeline policy."""

    @workflow.run
    async def run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        result = await workflow.execute_activity(
            validate_policy_activity,
            ctx,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=DEFAULT_RETRY_POLICY,
        )
        return result
