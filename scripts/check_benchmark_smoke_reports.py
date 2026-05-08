#!/usr/bin/env python3
import argparse
import json
from typing import Any


def load(path: str) -> dict[str, Any]:
    return json.load(open(path, "r", encoding="utf-8"))


def expect_single_success(entry: dict[str, Any], *, label: str) -> None:
    summary = entry.get("summary") or {}
    if summary.get("iterations") != 1:
        raise SystemExit(f"{label} summary has wrong iteration count: {entry}")
    if summary.get("successful_iterations") != 1 or summary.get("failed_iterations") != 0:
        raise SystemExit(f"{label} reported failures: {entry}")
    results = entry.get("results") or []
    if len(results) != 1:
        raise SystemExit(f"{label} expected exactly one result row: {entry}")
    result = results[0]
    if result.get("exit_code") != 0 or result.get("timed_out") is not False:
        raise SystemExit(f"{label} result did not succeed: {entry}")


def validate_query_workflow(payload: dict[str, Any]) -> None:
    query_modes = payload.get("modes") or []
    expected_query_modes = {"cli_dry_run", "http_dry_run", "client_dry_run"}
    actual_query_modes = {entry.get("mode") for entry in query_modes}
    if actual_query_modes != expected_query_modes:
        raise SystemExit(
            f"query workflow benchmark modes mismatch: expected {sorted(expected_query_modes)}, got {sorted(actual_query_modes)}"
        )
    for entry in query_modes:
        expect_single_success(entry, label=f"query workflow benchmark mode {entry.get('mode')}")
        if entry.get("mode") in {"http_dry_run", "client_dry_run"} and not isinstance(
            entry.get("server_startup_ms"), (int, float)
        ):
            raise SystemExit(f"query workflow benchmark missing server_startup_ms: {entry}")


def validate_read_adapter(payload: dict[str, Any]) -> None:
    expected_read_modes = {
        "metadata_cli_job",
        "metadata_cli_jobs",
        "metadata_http_job",
        "metadata_http_jobs",
        "metadata_client_job",
        "metadata_client_jobs",
        "metadata_http_entity",
        "metadata_client_entity",
        "audit_http_audit_chain",
        "audit_http_public_report",
        "audit_http_observability",
        "audit_http_catalog_lineage",
        "audit_client_audit_chain",
        "audit_client_public_report",
        "audit_client_observability",
        "audit_client_catalog_lineage",
    }
    read_adapter_modes = payload.get("modes") or []
    actual_read_modes = {entry.get("mode") for entry in read_adapter_modes}
    if actual_read_modes != expected_read_modes:
        raise SystemExit(
            f"read adapter benchmark modes mismatch: expected {sorted(expected_read_modes)}, got {sorted(actual_read_modes)}"
        )
    for entry in read_adapter_modes:
        mode = entry.get("mode")
        expect_single_success(entry, label=f"read adapter benchmark mode {mode}")
        result = (entry.get("results") or [None])[0] or {}
        if mode in {
            "metadata_cli_job",
            "metadata_http_job",
            "metadata_client_job",
            "metadata_cli_jobs",
            "metadata_http_jobs",
            "metadata_client_jobs",
        }:
            if (
                result.get("mainline_contract_embedded") is not True
                or result.get("handoff_cleanup_server") != "removed"
                or result.get("handoff_cleanup_client") != "cleaned"
                or result.get("service_audit_consistency_server") != "not_applicable"
                or result.get("service_audit_consistency_client") != "ok"
                or result.get("service_audit_consistency_error_count") != 0
            ):
                raise SystemExit(f"read adapter benchmark metadata mainline summary mismatch: {entry}")
        if mode in {"metadata_cli_job", "metadata_http_job", "metadata_client_job"}:
            if result.get("job_count") != 1:
                raise SystemExit(f"read adapter benchmark metadata job mode returned wrong job_count: {entry}")
        if mode in {"metadata_cli_jobs", "metadata_http_jobs", "metadata_client_jobs"}:
            if (
                result.get("job_count") != 1
                or result.get("mainline_summary_rollup_job_count") != 1
                or result.get("mainline_summary_rollup_server_removed_count") != 1
                or result.get("mainline_summary_rollup_client_cleaned_count") != 1
                or result.get("mainline_summary_rollup_server_not_applicable_count") != 1
                or result.get("mainline_summary_rollup_client_ok_count") != 1
            ):
                raise SystemExit(f"read adapter benchmark metadata jobs mode returned wrong job_count: {entry}")
        if mode in {"metadata_http_entity", "metadata_client_entity"}:
            if (
                result.get("permission_summary_caller_count") != 1
                or result.get("permission_summary_dataset_count") != 1
                or result.get("permission_summary_service_count") != 1
                or result.get("permission_summary_platform_role_count") != 2
                or result.get("permission_summary_has_query_submitter") != 1
                or result.get("permission_summary_has_privacy_operator") != 1
                or result.get("permission_summary_can_run_bridge_true") != 1
                or result.get("permission_summary_can_release_true") != 1
                or result.get("permission_summary_can_use_record_recovery_service_true") != 1
            ):
                raise SystemExit(f"read adapter benchmark metadata entity permission summary mismatch: {entry}")


def validate_record_recovery(payload: dict[str, Any]) -> None:
    expected_record_modes = {
        "unix_socket_health_cli": ("unix_socket", "health"),
        "unix_socket_health_direct": ("unix_socket", "health"),
        "unix_socket_recover_direct": ("unix_socket", "recover"),
        "http_health_cli": ("http", "health"),
        "http_health_direct": ("http", "health"),
        "http_recover_direct": ("http", "recover"),
        "http_recover_concurrent": ("http", "recover"),
    }
    if set(payload.get("transports") or []) != {"unix_socket", "http"}:
        raise SystemExit(f"record recovery benchmark transports mismatch: {payload}")
    if payload.get("candidate_count") != 2:
        raise SystemExit(f"record recovery benchmark candidate_count mismatch: {payload}")
    record_entries = payload.get("modes") or []
    actual_record_modes = {entry.get("mode") for entry in record_entries}
    if actual_record_modes != set(expected_record_modes):
        raise SystemExit(
            f"record recovery benchmark modes mismatch: expected {sorted(expected_record_modes)}, got {sorted(actual_record_modes)}"
        )
    for entry in record_entries:
        mode = entry.get("mode")
        expected_transport, expected_operation = expected_record_modes[mode]
        if entry.get("transport") != expected_transport or entry.get("operation") != expected_operation:
            raise SystemExit(f"record recovery benchmark mode metadata mismatch: {entry}")
        if not isinstance(entry.get("service_startup_ms"), (int, float)):
            raise SystemExit(f"record recovery benchmark missing service_startup_ms: {entry}")
        expect_single_success(entry, label=f"record recovery benchmark mode {mode}")
        result = entry["results"][0]
        if mode.endswith("_health_direct") and result.get("transport") != expected_transport:
            raise SystemExit(f"record recovery direct result transport mismatch: {entry}")
        if mode.endswith("_recover_direct") and result.get("output_rows") != 2:
            raise SystemExit(f"record recovery direct result output_rows mismatch: {entry}")
        if mode == "http_recover_concurrent":
            if (
                result.get("concurrent_requests") != 2
                or result.get("successful_requests") != 2
                or result.get("failed_requests") != 0
                or result.get("total_output_rows") != 4
                or not isinstance(result.get("throughput_rps"), (int, float))
            ):
                raise SystemExit(f"record recovery concurrent result mismatch: {entry}")


def validate_sse_export(payload: dict[str, Any]) -> None:
    if payload.get("schema") != "sse_export_benchmark/v1":
        raise SystemExit(f"SSE export benchmark schema mismatch: {payload}")
    scale = payload.get("scale") or {}
    if scale.get("record_count") != 5 or scale.get("candidate_count") != 3 or scale.get("store_record_count") != 5:
        raise SystemExit(f"SSE export benchmark scale mismatch: {payload}")
    if payload.get("mode") != "encrypted_record_store_worker":
        raise SystemExit(f"SSE export benchmark mode mismatch: {payload}")
    summary = payload.get("summary") or {}
    if summary.get("iterations") != 1 or summary.get("successful_iterations") != 1 or summary.get("failed_iterations") != 0:
        raise SystemExit(f"SSE export benchmark summary mismatch: {payload}")
    results = payload.get("results") or []
    if len(results) != 1:
        raise SystemExit(f"SSE export benchmark expected one result: {payload}")
    result = results[0]
    if (
        result.get("exit_code") != 0
        or result.get("timed_out") is not False
        or result.get("input_rows") != 3
        or result.get("output_rows") != 3
        or result.get("candidate_count") != 3
        or result.get("audit_decision") != "allow"
        or result.get("record_recovery_boundary") != "worker_subprocess"
        or not isinstance(result.get("throughput_records_per_sec"), (int, float))
        or not isinstance(result.get("peak_rss_kb"), int)
    ):
        raise SystemExit(f"SSE export benchmark result mismatch: {payload}")


def validate_bridge(payload: dict[str, Any]) -> None:
    if payload.get("schema") != "bridge_benchmark/v1":
        raise SystemExit(f"bridge benchmark schema mismatch: {payload}")
    scale = payload.get("scale") or {}
    if scale.get("server_rows") != 5 or scale.get("client_rows") != 5:
        raise SystemExit(f"bridge benchmark scale mismatch: {payload}")
    profile = payload.get("profile") or {}
    if profile.get("method") != "external_flamegraph_optional" or not isinstance(profile.get("top_hotspots"), list):
        raise SystemExit(f"bridge benchmark profile metadata mismatch: {payload}")
    entries = payload.get("modes") or []
    actual_modes = {entry.get("mode") for entry in entries}
    if actual_modes != {"prepare_job_jsonl"}:
        raise SystemExit(f"bridge benchmark modes mismatch: {payload}")
    for entry in entries:
        expect_single_success(entry, label=f"bridge benchmark mode {entry.get('mode')}")
        command = entry.get("command") or []
        if (
            "prepare-job" not in command
            or "--server-input-format" not in command
            or "jsonl" not in command
            or "--client-value-mode" not in command
            or "raw-int" not in command
            or "--production-mode" not in command
        ):
            raise SystemExit(f"bridge benchmark command surface mismatch: {entry}")
        result = entry["results"][0]
        if (
            result.get("server_input_rows") != 5
            or result.get("client_input_rows") != 5
            or result.get("server_unique_join_tokens") != 5
            or result.get("client_unique_join_tokens") != 5
            or result.get("server_output_rows") != 5
            or result.get("client_output_rows") != 5
            or result.get("audit_decision") != "allow"
            or result.get("production_mode") is not True
            or result.get("token_secret_source_kind") != "env"
            or not isinstance(result.get("throughput_rows_per_sec"), (int, float))
            or not isinstance(result.get("peak_rss_kb"), int)
        ):
            raise SystemExit(f"bridge benchmark result mismatch: {entry}")


def validate_dashboard_jobs(payload: dict[str, Any]) -> None:
    if payload.get("schema") != "dashboard_jobs_benchmark/v1":
        raise SystemExit(f"dashboard jobs benchmark schema mismatch: {payload}")
    config = payload.get("configuration") or {}
    summary = payload.get("summary") or {}
    concurrency = config.get("concurrency")
    dashboard_reads = config.get("dashboard_reads")
    if concurrency != 5 or not isinstance(dashboard_reads, int) or dashboard_reads < 5:
        raise SystemExit(f"dashboard jobs benchmark config mismatch: {payload}")
    if (
        summary.get("status") != "ok"
        or summary.get("accepted_jobs") != concurrency
        or summary.get("rejected_jobs") != 0
        or summary.get("dashboard_ok_reads") != dashboard_reads
        or summary.get("dashboard_p95_passed") is not True
        or summary.get("memory_leak_check_passed") is not True
        or not isinstance(summary.get("dashboard_p95_ms"), (int, float))
        or summary.get("dashboard_p95_ms") >= 2000
    ):
        raise SystemExit(f"dashboard jobs benchmark summary mismatch: {payload}")
    start_results = (payload.get("start_requests") or {}).get("results") or []
    dashboard_results = (payload.get("dashboard_reads") or {}).get("results") or []
    if len(start_results) != concurrency or len(dashboard_results) != dashboard_reads:
        raise SystemExit(f"dashboard jobs benchmark result count mismatch: {payload}")
    if any(item.get("status_code") != 202 or item.get("state") != "running" for item in start_results):
        raise SystemExit(f"dashboard jobs benchmark start result mismatch: {payload}")
    if any(item.get("status_code") != 200 for item in dashboard_results):
        raise SystemExit(f"dashboard jobs benchmark dashboard read mismatch: {payload}")


def validate_audit_bundle(payload: dict[str, Any]) -> None:
    expected_audit_bundle_modes = {
        "archive_cli",
        "verify_direct_cli",
        "verify_archive_index_cli",
        "verify_archive_index_restore_cli",
    }
    audit_entries = payload.get("modes") or []
    actual_audit_bundle_modes = {entry.get("mode") for entry in audit_entries}
    if actual_audit_bundle_modes != expected_audit_bundle_modes:
        raise SystemExit(
            f"audit bundle benchmark modes mismatch: expected {sorted(expected_audit_bundle_modes)}, got {sorted(actual_audit_bundle_modes)}"
        )
    for entry in audit_entries:
        mode = entry.get("mode")
        expect_single_success(entry, label=f"audit bundle benchmark mode {mode}")
        result = entry["results"][0]
        if result.get("verified") is not True or result.get("signature_verified") is not True:
            raise SystemExit(f"audit bundle benchmark verify flags mismatch: {entry}")
        if result.get("anchor_log_verified") is not True and mode != "verify_direct_cli":
            raise SystemExit(f"audit bundle benchmark anchor verification flag mismatch: {entry}")
        if mode != "verify_direct_cli" and result.get("anchor_signature_verified") is not True:
            raise SystemExit(f"audit bundle benchmark anchor signature flag mismatch: {entry}")
        if mode == "archive_cli":
            if (
                result.get("archive_index_verified") is not True
                or result.get("restored") is not False
                or not result.get("archive_index_path")
                or not result.get("anchor_log_path")
            ):
                raise SystemExit(f"audit bundle archive mode mismatch: {entry}")
        elif mode == "verify_direct_cli":
            if (
                result.get("archive_index_verified") is not False
                or result.get("restored") is not False
                or result.get("archive_index_path") is not None
                or result.get("anchor_log_verified") is not False
                or result.get("anchor_signature_verified") is not None
                or result.get("anchor_log_path") is not None
            ):
                raise SystemExit(f"audit bundle direct verify mode mismatch: {entry}")
        elif mode == "verify_archive_index_cli":
            if (
                result.get("archive_index_verified") is not True
                or result.get("restored") is not False
                or not result.get("archive_index_path")
                or result.get("anchor_log_verified") is not True
                or not result.get("anchor_log_path")
            ):
                raise SystemExit(f"audit bundle archive-index verify mode mismatch: {entry}")
        elif mode == "verify_archive_index_restore_cli":
            if (
                result.get("archive_index_verified") is not True
                or result.get("restored") is not True
                or not result.get("archive_index_path")
                or result.get("anchor_log_verified") is not True
                or not result.get("anchor_log_path")
            ):
                raise SystemExit(f"audit bundle restore mode mismatch: {entry}")


def validate_platform_health(payload: dict[str, Any]) -> None:
    expected_platform_health_full = {
        "pipeline_run_cli",
        "metadata_db_cli",
        "combined_cli",
        "pipeline_run_http",
        "metadata_db_http",
        "combined_http",
        "combined_client",
    }
    expected_platform_health_cli = {
        "pipeline_run_cli",
        "metadata_db_cli",
        "combined_cli",
    }
    platform_entries = payload.get("modes") or []
    actual_platform_health_modes = {entry.get("mode") for entry in platform_entries}
    if (
        actual_platform_health_modes != expected_platform_health_full
        and actual_platform_health_modes != expected_platform_health_cli
    ):
        raise SystemExit(
            "platform health benchmark modes mismatch: "
            f"expected one of {[sorted(expected_platform_health_cli), sorted(expected_platform_health_full)]}, "
            f"got {sorted(actual_platform_health_modes)}"
        )
    expected_platform_components = {
        "pipeline_run_cli": {"pipeline_run"},
        "metadata_db_cli": {"metadata_db"},
        "combined_cli": {"pipeline_run", "metadata_db"},
        "pipeline_run_http": {"pipeline_run"},
        "metadata_db_http": {"metadata_db"},
        "combined_http": {"pipeline_run", "metadata_db"},
        "combined_client": {"pipeline_run", "metadata_db"},
    }
    for entry in platform_entries:
        mode = entry.get("mode")
        expect_single_success(entry, label=f"platform health benchmark mode {mode}")
        result = entry["results"][0]
        expected_components = expected_platform_components[mode]
        if result.get("summary_status") != "ok":
            raise SystemExit(f"platform health benchmark returned non-ok summary: {entry}")
        if result.get("check_count") != len(expected_components):
            raise SystemExit(f"platform health benchmark check_count mismatch: {entry}")
        if set(result.get("components") or []) != expected_components:
            raise SystemExit(f"platform health benchmark components mismatch: {entry}")


def validate_pipeline(payload: dict[str, Any]) -> None:
    expected_modes = {
        "file_handoff": ("cleaned", False),
        "file_handoff_retained": ("retained", True),
        "fifo_handoff": ("removed", False),
    }
    mode_entries = payload.get("modes") or []
    actual_modes = {entry.get("mode") for entry in mode_entries}
    if actual_modes != set(expected_modes):
        raise SystemExit(
            f"pipeline benchmark modes mismatch: expected {sorted(expected_modes)}, got {sorted(actual_modes)}"
        )
    for entry in mode_entries:
        mode = entry.get("mode")
        expect_single_success(entry, label=f"pipeline benchmark mode {mode}")
        result = entry["results"][0]
        expected_status, expected_exists = expected_modes[mode]
        if (
            result.get("mainline_contract_check_embedded") is not True
            or result.get("handoff_cleanup_server_status") != expected_status
            or result.get("handoff_cleanup_client_status") != expected_status
            or result.get("handoff_cleanup_server_exists_after_run") is not expected_exists
            or result.get("handoff_cleanup_client_exists_after_run") is not expected_exists
        ):
            raise SystemExit(f"pipeline benchmark handoff cleanup summary mismatch: {entry}")


def validate_live_sse(payload: dict[str, Any]) -> None:
    expected_modes = {
        "file_handoff": ("cleaned", False),
        "file_handoff_retained": ("retained", True),
        "fifo_handoff": ("removed", False),
    }
    mode_entries = payload.get("modes") or []
    actual_modes = {entry.get("mode") for entry in mode_entries}
    if actual_modes != set(expected_modes):
        raise SystemExit(
            f"live SSE benchmark modes mismatch: expected {sorted(expected_modes)}, got {sorted(actual_modes)}"
        )
    for entry in mode_entries:
        mode = entry.get("mode")
        expect_single_success(entry, label=f"live SSE benchmark mode {mode}")
        result = entry["results"][0]
        expected_status, expected_exists = expected_modes[mode]
        if (
            result.get("mainline_contract_check_embedded") is not True
            or result.get("handoff_cleanup_server_status") != expected_status
            or result.get("handoff_cleanup_client_status") != expected_status
            or result.get("handoff_cleanup_server_exists_after_run") is not expected_exists
            or result.get("handoff_cleanup_client_exists_after_run") is not expected_exists
        ):
            raise SystemExit(f"live SSE benchmark handoff cleanup summary mismatch: {entry}")


def validate_derived_views(payload: dict[str, Any]) -> None:
    expected_derived_modes = {
        "observability_cli",
        "catalog_cli_default",
        "catalog_cli_include_paths",
    }
    derived_entries = payload.get("modes") or []
    actual_derived_modes = {entry.get("mode") for entry in derived_entries}
    if actual_derived_modes != expected_derived_modes:
        raise SystemExit(
            f"derived views benchmark modes mismatch: expected {sorted(expected_derived_modes)}, got {sorted(actual_derived_modes)}"
        )
    for entry in derived_entries:
        mode = entry.get("mode")
        expect_single_success(entry, label=f"derived views benchmark mode {mode}")
        result = entry["results"][0]
        if mode == "observability_cli":
            if result.get("result_schema") != "pipeline_observability/v1" or int(result.get("event_count") or 0) < 5:
                raise SystemExit(f"derived views observability mode mismatch: {entry}")
        elif mode == "catalog_cli_default":
            if result.get("result_schema") != "catalog_lineage/v1" or result.get("paths_included") is not False:
                raise SystemExit(f"derived views catalog default mode mismatch: {entry}")
            if int(result.get("artifact_count") or 0) <= 0 or int(result.get("lineage_edge_count") or 0) <= 0:
                raise SystemExit(f"derived views catalog default counts mismatch: {entry}")
            if (
                result.get("mainline_contract_embedded") is not True
                or result.get("service_audit_consistency_server") != "not_applicable"
                or result.get("service_audit_consistency_client") != "ok"
                or result.get("service_audit_consistency_error_count") != 0
            ):
                raise SystemExit(f"derived views catalog default mainline summary mismatch: {entry}")
        elif mode == "catalog_cli_include_paths":
            if result.get("result_schema") != "catalog_lineage/v1" or result.get("paths_included") is not True:
                raise SystemExit(f"derived views catalog include-paths mode mismatch: {entry}")
            if int(result.get("artifact_count") or 0) <= 0 or int(result.get("lineage_edge_count") or 0) <= 0:
                raise SystemExit(f"derived views catalog include-paths counts mismatch: {entry}")
            if (
                result.get("mainline_contract_embedded") is not True
                or result.get("service_audit_consistency_server") != "not_applicable"
                or result.get("service_audit_consistency_client") != "ok"
                or result.get("service_audit_consistency_error_count") != 0
            ):
                raise SystemExit(f"derived views catalog include-paths mainline summary mismatch: {entry}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Validate benchmark smoke reports against expected mode and result invariants.")
    ap.add_argument("--query-workflow", required=True)
    ap.add_argument("--read-adapter", required=True)
    ap.add_argument("--sse-export", required=True)
    ap.add_argument("--bridge", required=True)
    ap.add_argument("--dashboard-jobs", required=True)
    ap.add_argument("--record-recovery", required=True)
    ap.add_argument("--pipeline", required=True)
    ap.add_argument("--live-sse", required=True)
    ap.add_argument("--audit-bundle", required=True)
    ap.add_argument("--platform-health", required=True)
    ap.add_argument("--derived-views", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    validate_query_workflow(load(args.query_workflow))
    validate_read_adapter(load(args.read_adapter))
    validate_sse_export(load(args.sse_export))
    validate_bridge(load(args.bridge))
    validate_dashboard_jobs(load(args.dashboard_jobs))
    validate_record_recovery(load(args.record_recovery))
    validate_pipeline(load(args.pipeline))
    validate_live_sse(load(args.live_sse))
    validate_audit_bundle(load(args.audit_bundle))
    validate_platform_health(load(args.platform_health))
    validate_derived_views(load(args.derived_views))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
