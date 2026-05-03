#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.load(path.open("r", encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def require_error_contains(payload: dict[str, Any], *, schema: str, text: str, label: str) -> None:
    require(payload.get("schema") == schema, f"{label} returned wrong schema: {payload}")
    require(text in (payload.get("error") or ""), f"{label} returned wrong error payload: {payload}")


def require_mainline_summary(summary: dict[str, Any], *, label: str) -> None:
    require(
        summary.get("schema") == "mainline_contract_check/v1"
        and summary.get("status") == "ok"
        and summary.get("embedded_in_audit_chain") is True,
        f"{label} missing embedded mainline contract summary: {summary}",
    )
    handoff = summary.get("handoff_cleanup") or {}
    require(
        handoff.get("server") == "removed" and handoff.get("client") == "cleaned",
        f"{label} returned invalid handoff cleanup summary: {summary}",
    )
    service_consistency = summary.get("service_audit_consistency") or {}
    require(
        service_consistency.get("server") == "not_applicable"
        and service_consistency.get("client") == "ok"
        and service_consistency.get("error_count") == 0,
        f"{label} returned invalid service audit consistency summary: {summary}",
    )


def require_mainline_summary_counts(result: dict[str, Any], *, label: str, expected_job_count: int) -> None:
    counts = result.get("mainline_contract_summary_counts") or {}
    require(counts.get("job_count") == expected_job_count, f"{label} returned wrong mainline summary job_count: {result}")
    embedded = counts.get("embedded_in_audit_chain") or {}
    require(
        embedded.get("true") == expected_job_count and embedded.get("false") == 0 and embedded.get("unknown") == 0,
        f"{label} returned invalid embedded mainline summary counts: {result}",
    )
    handoff = counts.get("handoff_cleanup") or {}
    require(
        ((handoff.get("server") or {}).get("removed") == expected_job_count)
        and ((handoff.get("client") or {}).get("cleaned") == expected_job_count),
        f"{label} returned invalid handoff cleanup counts: {result}",
    )
    service_consistency = counts.get("service_audit_consistency") or {}
    require(
        ((service_consistency.get("server") or {}).get("not_applicable") == expected_job_count)
        and ((service_consistency.get("client") or {}).get("ok") == expected_job_count)
        and service_consistency.get("error_count_total") == 0,
        f"{label} returned invalid service audit consistency counts: {result}",
    )


def require_pagination(
    result: dict[str, Any],
    *,
    label: str,
    limit: int,
    offset: int,
    returned_count: int,
    total_matching_count: int,
    has_more: bool,
) -> None:
    pagination = result.get("pagination") or {}
    require(pagination.get("limit") == limit, f"{label} returned wrong pagination limit: {result}")
    require(pagination.get("offset") == offset, f"{label} returned wrong pagination offset: {result}")
    require(pagination.get("returned_count") == returned_count, f"{label} returned wrong pagination returned_count: {result}")
    require(
        pagination.get("total_matching_count") == total_matching_count,
        f"{label} returned wrong pagination total_matching_count: {result}",
    )
    require(pagination.get("has_more") is has_more, f"{label} returned wrong pagination has_more: {result}")
    expected_next_offset = offset + returned_count if has_more else None
    expected_previous_offset = max(offset - limit, 0) if offset > 0 else None
    require(
        pagination.get("next_offset") == expected_next_offset,
        f"{label} returned wrong pagination next_offset: {result}",
    )
    require(
        pagination.get("previous_offset") == expected_previous_offset,
        f"{label} returned wrong pagination previous_offset: {result}",
    )


def expect_query_submission_wrapper(
    payload: dict[str, Any],
    *,
    cleanup_expected: bool,
    repo_root: Path,
    require_resolved_paths: bool,
) -> None:
    expected_command_prefix = ["bash", str(repo_root / "scripts" / "run_sse_bridge_pipeline.sh")]
    require(payload.get("schema") == "query_workflow_submission/v1", f"query workflow wrapper returned wrong schema: {payload}")
    require(payload.get("mode") == "dry_run", f"query workflow wrapper returned wrong mode: {payload}")
    require(payload.get("workflow") == "sse_bridge_pipeline", f"query workflow wrapper returned wrong workflow: {payload}")

    summary = payload.get("request_summary") or {}
    require(summary.get("cleanup_sse_export_handoff_files_after_bridge") is cleanup_expected,
            f"query workflow wrapper returned wrong cleanup handoff summary: {payload}")
    command = payload.get("command") or []
    require(command[:2] == expected_command_prefix, f"query workflow wrapper returned wrong command prefix: {payload}")

    if cleanup_expected:
        require(summary.get("token_secret") == "<redacted>",
                f"query workflow wrapper failed to redact token_secret in summary: {payload}")
        require("<redacted>" in command, f"query workflow wrapper failed to redact token_secret in command: {payload}")
        require("--deny-duplicate-query" in command, f"query workflow wrapper lost deny-duplicate-query flag: {payload}")
        require("--sse-export-handoff-mode" in command and "fifo" in command,
                f"query workflow wrapper lost fifo handoff setting: {payload}")
        require("--cleanup-sse-export-handoff-files-after-bridge" in command,
                f"query workflow wrapper lost cleanup handoff flag: {payload}")
        if require_resolved_paths:
            expected_paths = {
                str(repo_root / "sse" / "examples" / "bridge_server_records.jsonl"),
                str(repo_root / "sse" / "examples" / "bridge_client_records.jsonl"),
                str(repo_root / "sse" / "config" / "export_policy.example.json"),
            }
            for required_path in expected_paths:
                require(required_path in command,
                        f"query workflow wrapper did not resolve request-relative path {required_path}: {payload}")
    else:
        require(summary.get("handoff_retention_reason") == "contract_keep_fixture",
                f"query workflow keep wrapper lost handoff retention reason: {payload}")
        require("--keep-sse-export-handoff-files" in command,
                f"query workflow keep wrapper lost explicit keep handoff flag: {payload}")
        require("--handoff-retention-reason" in command and "contract_keep_fixture" in command,
                f"query workflow keep wrapper lost explicit retained handoff reason: {payload}")
        require("--cleanup-sse-export-handoff-files-after-bridge" not in command,
                f"query workflow keep wrapper emitted conflicting cleanup flag: {payload}")


def validate_query_submissions(tmp_dir: Path, repo_root: Path) -> None:
    for name in ("query_workflow_stdout.json", "query_workflow_manifest.json"):
        expect_query_submission_wrapper(
            load(tmp_dir / name),
            cleanup_expected=True,
            repo_root=repo_root,
            require_resolved_paths=True,
        )
    for name in ("query_workflow_keep_stdout.json", "query_workflow_keep_manifest.json"):
        expect_query_submission_wrapper(
            load(tmp_dir / name),
            cleanup_expected=False,
            repo_root=repo_root,
            require_resolved_paths=False,
        )


def validate_query_api(tmp_dir: Path) -> None:
    health = load(tmp_dir / "query_workflow_api_health.json")
    client_health = load(tmp_dir / "query_workflow_client_health.json")
    dry_run = load(tmp_dir / "query_workflow_api_dry_run.json")
    client_dry_run = load(tmp_dir / "query_workflow_client_dry_run.json")
    unauth_error = load(tmp_dir / "query_workflow_api_unauth_error.json")
    execute_disabled_error = load(tmp_dir / "query_workflow_api_execute_disabled_error.json")
    client_execute_disabled_error = load(tmp_dir / "query_workflow_client_execute_disabled_error.json")

    for payload in (health, client_health):
        require(payload.get("schema") == "query_workflow_api_health/v1" and payload.get("ok") is True,
                f"query workflow API health endpoint failed: {payload}")
        require(payload.get("auth_required") is True and payload.get("allow_execute") is False,
                f"query workflow API health endpoint returned wrong capability flags: {payload}")

    require(dry_run.get("schema") == "query_workflow_api_response/v1",
            f"query workflow API dry-run returned wrong schema: {dry_run}")
    manifest = (dry_run.get("result") or {}).get("manifest") or {}
    require(manifest.get("schema") == "query_workflow_submission/v1" and manifest.get("mode") == "dry_run",
            f"query workflow API dry-run returned wrong manifest: {dry_run}")
    require((manifest.get("request_summary") or {}).get("token_secret") == "<redacted>",
            f"query workflow API dry-run failed to redact token_secret: {dry_run}")
    require((manifest.get("request_summary") or {}).get("cleanup_sse_export_handoff_files_after_bridge") is True,
            f"query workflow API dry-run lost cleanup handoff flag: {dry_run}")

    require(client_dry_run.get("schema") == "query_workflow_api_response/v1",
            f"platform API client query dry-run returned wrong schema: {client_dry_run}")
    client_manifest = (client_dry_run.get("result") or {}).get("manifest") or {}
    require(client_manifest.get("schema") == "query_workflow_submission/v1" and client_manifest.get("mode") == "dry_run",
            f"platform API client query dry-run returned wrong manifest: {client_dry_run}")
    require(client_manifest.get("request_file") == "http_request_body",
            f"platform API client query dry-run returned wrong request source: {client_dry_run}")
    require((client_manifest.get("request_summary") or {}).get("cleanup_sse_export_handoff_files_after_bridge") is True,
            f"platform API client query dry-run lost cleanup handoff flag: {client_dry_run}")

    require_error_contains(
        unauth_error,
        schema="query_workflow_api_error/v1",
        text="missing bearer token",
        label="query workflow API unauthenticated error payload",
    )
    require_error_contains(
        execute_disabled_error,
        schema="query_workflow_api_error/v1",
        text="disabled",
        label="query workflow API execute-disabled error payload",
    )
    require_error_contains(
        client_execute_disabled_error,
        schema="query_workflow_api_error/v1",
        text="disabled",
        label="platform API client query execute-disabled error payload",
    )

    for lifecycle_name in ("query_workflow_api.pid", "query_workflow_api.ready"):
        require(not (tmp_dir / lifecycle_name).exists(), "query workflow API lifecycle files still exist after shutdown")


def validate_metadata_api(tmp_dir: Path) -> None:
    health = load(tmp_dir / "metadata_api_health.json")
    client_health = load(tmp_dir / "metadata_api_client_health.json")
    job = load(tmp_dir / "metadata_api_job.json")
    jobs = load(tmp_dir / "metadata_api_jobs.json")
    policies = load(tmp_dir / "metadata_api_policies.json")
    permissions = load(tmp_dir / "metadata_api_permissions.json")
    permissions_page = load(tmp_dir / "metadata_api_permissions_page.json")
    client_job = load(tmp_dir / "metadata_api_client_job.json")
    client_jobs = load(tmp_dir / "metadata_api_client_jobs.json")
    client_permissions = load(tmp_dir / "metadata_api_client_permissions.json")
    unauth_error = load(tmp_dir / "metadata_api_unauth_error.json")

    for payload in (health, client_health):
        require(payload.get("schema") == "metadata_api_health/v1" and payload.get("ok") is True,
                f"metadata API health endpoint failed: {payload}")
        require(payload.get("auth_required") is True,
                f"metadata API health endpoint did not report auth requirement: {payload}")

    for payload in (job, jobs, policies, permissions, permissions_page, client_job, client_jobs, client_permissions):
        require(payload.get("schema") == "metadata_api_response/v1",
                f"metadata API returned unexpected response schema: {payload}")

    job_result = (job.get("result") or {}).get("job") or {}
    require(job_result.get("job_id") == "contract-check", f"metadata API job detail returned wrong job: {job}")
    require_mainline_summary((job.get("result") or {}).get("mainline_contract_summary") or {}, label="metadata API job detail")

    jobs_result = (jobs.get("result") or {}).get("jobs") or []
    require(len(jobs_result) == 1 and jobs_result[0].get("job_id") == "contract-check",
            f"metadata API jobs list returned unexpected rows: {jobs}")
    require(((jobs.get("result") or {}).get("filters") or {}).get("stage") == "bridge",
            f"metadata API jobs list lost stage filter: {jobs}")
    require_pagination(
        jobs.get("result") or {},
        label="metadata API jobs list",
        limit=5,
        offset=0,
        returned_count=1,
        total_matching_count=1,
        has_more=False,
    )
    require_mainline_summary(jobs_result[0].get("mainline_contract_summary") or {}, label="metadata API jobs list")
    require_mainline_summary_counts(jobs.get("result") or {}, label="metadata API jobs list", expected_job_count=1)

    client_jobs_result = (client_jobs.get("result") or {}).get("jobs") or []
    require(len(client_jobs_result) == 1 and client_jobs_result[0].get("job_id") == "contract-check",
            f"platform API client metadata jobs returned unexpected rows: {client_jobs}")
    require(((client_jobs.get("result") or {}).get("filters") or {}).get("stage") == "bridge",
            f"platform API client metadata jobs lost stage filter: {client_jobs}")
    require_pagination(
        client_jobs.get("result") or {},
        label="platform API client metadata jobs",
        limit=5,
        offset=0,
        returned_count=1,
        total_matching_count=1,
        has_more=False,
    )
    require_mainline_summary(client_jobs_result[0].get("mainline_contract_summary") or {}, label="platform API client metadata jobs")
    require_mainline_summary_counts(client_jobs.get("result") or {}, label="platform API client metadata jobs", expected_job_count=1)

    policy_rows = (policies.get("result") or {}).get("items") or []
    require(any(row.get("schema_name") == "sse_export_policy/v1" for row in policy_rows),
            f"metadata API policy list missing export policy: {policies}")
    require_pagination(
        policies.get("result") or {},
        label="metadata API policy list",
        limit=5,
        offset=0,
        returned_count=len(policy_rows),
        total_matching_count=len(policy_rows),
        has_more=False,
    )

    permission_rows = (permissions.get("result") or {}).get("items") or []
    require(any(row.get("permission_key") == "can_run_bridge" for row in permission_rows),
            f"metadata API caller permission list missing can_run_bridge: {permissions}")
    require_pagination(
        permissions.get("result") or {},
        label="metadata API caller permission list",
        limit=20,
        offset=0,
        returned_count=len(permission_rows),
        total_matching_count=len(permission_rows),
        has_more=False,
    )
    permission_summary = ((permissions.get("result") or {}).get("permission_summary") or {})
    require(permission_summary.get("caller_count") == 1, f"metadata API caller permission summary returned wrong caller_count: {permissions}")
    require(permission_summary.get("callers") == ["auto_demo"], f"metadata API caller permission summary returned wrong callers: {permissions}")
    require(permission_summary.get("tenant_ids") == ["contract-tenant"], f"metadata API caller permission summary returned wrong tenants: {permissions}")
    require(permission_summary.get("allowed_dataset_ids") == ["contract-dataset"], f"metadata API caller permission summary returned wrong datasets: {permissions}")
    require(permission_summary.get("allowed_service_ids") == ["contract-recovery-service"], f"metadata API caller permission summary returned wrong services: {permissions}")
    require(((permission_summary.get("enabled_counts") or {}).get("true")) == 1, f"metadata API caller permission summary returned wrong enabled counts: {permissions}")
    role_counts = permission_summary.get("platform_role_counts") or {}
    require(role_counts.get("query_submitter") == 1, f"metadata API caller permission summary returned wrong query_submitter count: {permissions}")
    require(role_counts.get("privacy_operator") == 1, f"metadata API caller permission summary returned wrong privacy_operator count: {permissions}")
    access_profiles = permission_summary.get("access_profiles") or []
    require(len(access_profiles) == 1 and access_profiles[0].get("access_profile") == "commerce_ops_owner", f"metadata API caller permission summary returned wrong access profiles: {permissions}")
    permission_flags = permission_summary.get("permissions") or {}
    require(((permission_flags.get("can_run_pjc") or {}).get("true")) == 1, f"metadata API caller permission summary returned wrong can_run_pjc: {permissions}")
    paged_permission_rows = (permissions_page.get("result") or {}).get("items") or []
    require(
        len(paged_permission_rows) == 2 and all(row.get("caller") == "auto_demo" for row in paged_permission_rows),
        f"metadata API paged permission list returned unexpected rows: {permissions_page}",
    )
    require_pagination(
        permissions_page.get("result") or {},
        label="metadata API paged permission list",
        limit=2,
        offset=2,
        returned_count=2,
        total_matching_count=len(permission_rows),
        has_more=True,
    )
    require(
        ((permissions_page.get("result") or {}).get("permission_summary") or {}).get("caller_count") == 1,
        f"metadata API paged permission list lost full permission summary: {permissions_page}",
    )

    client_job_result = (client_job.get("result") or {}).get("job") or {}
    require(client_job_result.get("job_id") == "contract-check",
            f"platform API client metadata job returned wrong job: {client_job}")
    require_mainline_summary((client_job.get("result") or {}).get("mainline_contract_summary") or {}, label="platform API client metadata job detail")
    client_permission_rows = (client_permissions.get("result") or {}).get("items") or []
    require(any(row.get("permission_key") == "can_run_bridge" for row in client_permission_rows),
            f"platform API client metadata query missing can_run_bridge: {client_permissions}")
    require_pagination(
        client_permissions.get("result") or {},
        label="platform API client metadata permissions",
        limit=20,
        offset=0,
        returned_count=len(client_permission_rows),
        total_matching_count=len(client_permission_rows),
        has_more=False,
    )
    client_permission_summary = ((client_permissions.get("result") or {}).get("permission_summary") or {})
    require(client_permission_summary.get("caller_count") == 1, f"platform API client caller permission summary returned wrong caller_count: {client_permissions}")
    require(client_permission_summary.get("callers") == ["auto_demo"], f"platform API client caller permission summary returned wrong callers: {client_permissions}")
    require(client_permission_summary.get("tenant_ids") == ["contract-tenant"], f"platform API client caller permission summary returned wrong tenants: {client_permissions}")
    require(((client_permission_summary.get("platform_role_counts") or {}).get("query_submitter")) == 1, f"platform API client caller permission summary returned wrong query_submitter count: {client_permissions}")
    require(((client_permission_summary.get("permissions") or {}).get("can_run_pjc") or {}).get("true") == 1, f"platform API client caller permission summary returned wrong can_run_pjc: {client_permissions}")

    require_error_contains(
        unauth_error,
        schema="metadata_api_error/v1",
        text="missing bearer token",
        label="metadata API unauthenticated error payload",
    )

    for lifecycle_name in ("metadata_api.pid", "metadata_api.ready"):
        require(not (tmp_dir / lifecycle_name).exists(), "metadata API lifecycle files still exist after shutdown")


def count_stage_events(payload: dict[str, Any], stage: str) -> int:
    events = (payload.get("result") or {}).get("events") or []
    return sum(1 for item in events if item.get("stage") == stage)


def require_catalog_mainline_summary(payload: dict[str, Any], *, label: str) -> None:
    result = payload.get("result") or {}
    mainline = result.get("mainline_contract_summary") or {}
    require(
        mainline.get("schema") == "mainline_contract_check/v1"
        and mainline.get("status") == "ok"
        and mainline.get("embedded_in_audit_chain") is True,
        f"{label} missing embedded mainline contract summary: {payload}",
    )
    service_consistency = mainline.get("service_audit_consistency") or {}
    require(
        service_consistency.get("server") == "not_applicable"
        and service_consistency.get("client") == "ok"
        and service_consistency.get("error_count") == 0,
        f"{label} returned invalid service audit consistency summary: {payload}",
    )


def validate_audit_query_api(tmp_dir: Path) -> None:
    health = load(tmp_dir / "audit_query_api_health.json")
    client_health = load(tmp_dir / "audit_query_client_health.json")
    public_report = load(tmp_dir / "audit_query_api_public_report.json")
    audit_chain = load(tmp_dir / "audit_query_api_audit_chain.json")
    observability = load(tmp_dir / "audit_query_api_observability.json")
    catalog_lineage = load(tmp_dir / "audit_query_api_catalog_lineage.json")
    client_audit_chain = load(tmp_dir / "audit_query_client_audit_chain.json")
    client_public_report = load(tmp_dir / "audit_query_client_public_report.json")
    client_observability = load(tmp_dir / "audit_query_client_observability.json")
    client_catalog_lineage = load(tmp_dir / "audit_query_client_catalog_lineage.json")
    client_catalog_lineage_with_paths = load(tmp_dir / "audit_query_client_catalog_lineage_with_paths.json")
    unauth_error = load(tmp_dir / "audit_query_api_unauth_error.json")
    bad_query_error = load(tmp_dir / "audit_query_api_bad_query_error.json")

    required_results = {"public_report/v2", "audit_chain/v1", "pipeline_observability/v1", "catalog_lineage/v1"}
    for payload in (health, client_health):
        require(payload.get("schema") == "audit_query_api_health/v1" and payload.get("ok") is True,
                f"audit query API health endpoint failed: {payload}")
        require(payload.get("auth_required") is True,
                f"audit query API health endpoint did not report auth requirement: {payload}")
        require(required_results.issubset(set(payload.get("available_results") or [])),
                f"audit query API health endpoint missing available results: {payload}")

    response_payloads = (
        public_report,
        audit_chain,
        observability,
        catalog_lineage,
        client_audit_chain,
        client_public_report,
        client_observability,
        client_catalog_lineage,
        client_catalog_lineage_with_paths,
    )
    for payload in response_payloads:
        require(payload.get("schema") == "audit_query_api_response/v1",
                f"audit query API returned unexpected response schema: {payload}")

    public_report_result = public_report.get("result") or {}
    require(public_report.get("result_schema") == "public_report/v2" and public_report_result.get("job_id") == "contract-check",
            f"audit query API public report returned wrong payload: {public_report}")

    audit_chain_result = audit_chain.get("result") or {}
    require(audit_chain.get("result_schema") == "audit_chain/v1" and audit_chain_result.get("job_id") == "contract-check",
            f"audit query API audit-chain returned wrong payload: {audit_chain}")
    require((audit_chain_result.get("mainline_contract_check") or {}).get("schema") == "mainline_contract_check/v1",
            f"audit query API audit-chain missing embedded mainline contract check: {audit_chain}")

    require(observability.get("result_schema") == "pipeline_observability/v1",
            f"audit query API observability returned wrong payload: {observability}")
    require(len((observability.get("result") or {}).get("events") or []) >= 5,
            f"audit query API observability returned too few events: {observability}")
    require(count_stage_events(observability, "handoff_cleanup") == 2,
            f"audit query API observability missing handoff_cleanup events: {observability}")

    catalog_lineage_result = catalog_lineage.get("result") or {}
    require(catalog_lineage.get("result_schema") == "catalog_lineage/v1",
            f"audit query API catalog-lineage returned wrong payload: {catalog_lineage}")
    require(((catalog_lineage_result.get("privacy") or {}).get("paths_included")) is False,
            f"audit query API catalog-lineage unexpectedly included paths by default: {catalog_lineage}")
    require_catalog_mainline_summary(catalog_lineage, label="audit query API catalog-lineage")

    client_audit_chain_result = client_audit_chain.get("result") or {}
    require(client_audit_chain.get("result_schema") == "audit_chain/v1" and client_audit_chain_result.get("job_id") == "contract-check",
            f"platform API client audit chain call returned wrong payload: {client_audit_chain}")
    require((client_audit_chain_result.get("mainline_contract_check") or {}).get("schema") == "mainline_contract_check/v1",
            f"platform API client audit chain missing embedded mainline contract check: {client_audit_chain}")

    client_public_report_result = client_public_report.get("result") or {}
    require(client_public_report.get("result_schema") == "public_report/v2" and client_public_report_result.get("job_id") == "contract-check",
            f"platform API client public report call returned wrong payload: {client_public_report}")

    require(client_observability.get("result_schema") == "pipeline_observability/v1"
            and len((client_observability.get("result") or {}).get("events") or []) >= 5,
            f"platform API client observability call returned wrong payload: {client_observability}")
    require(count_stage_events(client_observability, "handoff_cleanup") == 2,
            f"platform API client observability missing handoff_cleanup events: {client_observability}")

    client_catalog_lineage_result = client_catalog_lineage.get("result") or {}
    require(client_catalog_lineage.get("result_schema") == "catalog_lineage/v1",
            f"platform API client catalog-lineage call returned wrong payload: {client_catalog_lineage}")
    require(((client_catalog_lineage_result.get("privacy") or {}).get("paths_included")) is False,
            f"platform API client catalog-lineage unexpectedly included paths by default: {client_catalog_lineage}")
    require_catalog_mainline_summary(client_catalog_lineage, label="platform API client catalog-lineage")

    client_catalog_lineage_with_paths_result = client_catalog_lineage_with_paths.get("result") or {}
    require(client_catalog_lineage_with_paths.get("result_schema") == "catalog_lineage/v1",
            f"platform API client catalog-lineage include-paths call returned wrong payload: {client_catalog_lineage_with_paths}")
    require(((client_catalog_lineage_with_paths_result.get("privacy") or {}).get("paths_included")) is True,
            f"platform API client catalog-lineage include-paths did not include paths: {client_catalog_lineage_with_paths}")
    require_catalog_mainline_summary(client_catalog_lineage_with_paths, label="platform API client catalog-lineage include-paths")

    require_error_contains(
        unauth_error,
        schema="audit_query_api_error/v1",
        text="missing bearer token",
        label="audit query API unauthenticated error payload",
    )
    require_error_contains(
        bad_query_error,
        schema="audit_query_api_error/v1",
        text="include_paths",
        label="audit query API bad-query error payload",
    )

    for lifecycle_name in ("audit_query_api.pid", "audit_query_api.ready"):
        require(not (tmp_dir / lifecycle_name).exists(), "audit query API lifecycle files still exist after shutdown")


def validate_platform_health_payload(payload: dict[str, Any], *, label: str) -> None:
    require(payload.get("schema") == "platform_health/v1" or payload.get("schema") == "platform_health_api_response/v1",
            f"{label} returned wrong schema: {payload}")
    result = payload if payload.get("schema") == "platform_health/v1" else (payload.get("result") or {})
    if payload.get("schema") == "platform_health_api_response/v1":
        require(payload.get("result_schema") == "platform_health/v1", f"{label} returned wrong result schema: {payload}")
    summary = result.get("summary") or {}
    require(summary.get("status") == "ok", f"{label} returned non-ok summary: {payload}")
    checks = result.get("checks") or []
    components = {item.get("component") for item in checks}
    require({"pipeline_run", "metadata_db"}.issubset(components), f"{label} returned wrong components: {payload}")
    pipeline_entries = [item for item in checks if item.get("component") == "pipeline_run"]
    require(len(pipeline_entries) == 1, f"{label} returned wrong pipeline_run checks: {payload}")
    pipeline_details = pipeline_entries[0].get("details") or {}
    audit_chain = pipeline_details.get("audit_chain") or {}
    require(audit_chain.get("mainline_contract_check_embedded") is True,
            f"{label} did not report embedded mainline contract check: {payload}")
    mainline = pipeline_details.get("mainline_contract_check") or {}
    require(mainline.get("schema") == "mainline_contract_check/v1" and mainline.get("status") == "ok",
            f"{label} returned invalid mainline contract summary: {payload}")
    handoff = mainline.get("handoff_cleanup") or {}
    for role_name in ("server", "client"):
        require(((handoff.get(role_name) or {}).get("status")) in {"cleaned", "removed", "retained"},
                f"{label} returned invalid handoff cleanup state: {payload}")


def validate_platform_health_api(tmp_dir: Path) -> None:
    health = load(tmp_dir / "platform_health_api_health.json")
    client_health = load(tmp_dir / "platform_health_client_health.json")
    report = load(tmp_dir / "platform_health_api_report.json")
    client_report = load(tmp_dir / "platform_health_client_report.json")
    unauth_error = load(tmp_dir / "platform_health_api_unauth_error.json")

    for payload in (health, client_health):
        require(payload.get("schema") == "platform_health_api_health/v1" and payload.get("ok") is True,
                f"platform health API health endpoint failed: {payload}")
        require(payload.get("auth_required") is True,
                f"platform health API health endpoint did not report auth requirement: {payload}")
        require(set(payload.get("available_results") or []) == {"platform_health/v1"},
                f"platform health API health endpoint returned wrong available_results: {payload}")

    validate_platform_health_payload(report, label="platform health API")
    validate_platform_health_payload(client_report, label="platform API client platform health")
    require_error_contains(
        unauth_error,
        schema="platform_health_api_error/v1",
        text="missing bearer token",
        label="platform health API unauthenticated error payload",
    )

    for lifecycle_name in ("platform_health_api.pid", "platform_health_api.ready"):
        require(not (tmp_dir / lifecycle_name).exists(), "platform health API lifecycle files still exist after shutdown")


def validate_platform_health_cli(tmp_dir: Path) -> None:
    validate_platform_health_payload(load(tmp_dir / "platform_health.json"), label="platform health check")


def validate_identity_api_authz(tmp_dir: Path) -> None:
    metadata_identity = load(tmp_dir / "metadata_api_identity.json")
    metadata_policies_forbidden = load(tmp_dir / "metadata_api_identity_forbidden_policies.json")
    query_identity_dry_run = load(tmp_dir / "query_workflow_identity_dry_run.json")
    query_identity_execute_forbidden = load(tmp_dir / "query_workflow_identity_execute_forbidden.json")
    audit_identity_public_report = load(tmp_dir / "audit_query_api_identity_public_report.json")
    audit_identity_include_paths_forbidden = load(tmp_dir / "audit_query_api_identity_include_paths_forbidden.json")
    platform_health_identity_forbidden = load(tmp_dir / "platform_health_api_identity_forbidden.json")

    require(metadata_identity.get("schema") == "metadata_api_response/v1", f"metadata identity endpoint returned wrong schema: {metadata_identity}")
    identity_result = metadata_identity.get("result") or {}
    require(identity_result.get("schema") == "api_identity_resolution/v1", f"metadata identity endpoint returned wrong result: {metadata_identity}")
    resolved = identity_result.get("identity") or {}
    access_summary = identity_result.get("access_summary") or {}
    require(resolved.get("caller") == "commerce_ops_demo", f"metadata identity endpoint returned wrong caller: {metadata_identity}")
    require(access_summary.get("query_execute_allowed") is True, f"metadata identity endpoint returned wrong execute scope: {metadata_identity}")
    require(access_summary.get("metadata_privileged") is False, f"metadata identity endpoint returned wrong metadata scope: {metadata_identity}")

    require_error_contains(
        metadata_policies_forbidden,
        schema="metadata_api_error/v1",
        text="privileged platform role",
        label="metadata identity policies forbidden payload",
    )

    require(query_identity_dry_run.get("schema") == "query_workflow_api_response/v1", f"identity query dry-run returned wrong schema: {query_identity_dry_run}")
    dry_run_identity = ((query_identity_dry_run.get("result") or {}).get("authenticated_identity") or {})
    require(dry_run_identity.get("caller") == "marketing_analyst_demo", f"identity query dry-run returned wrong identity: {query_identity_dry_run}")
    dry_run_manifest = (query_identity_dry_run.get("result") or {}).get("manifest") or {}
    require(dry_run_manifest.get("schema") == "query_workflow_submission/v1", f"identity query dry-run returned wrong manifest: {query_identity_dry_run}")

    require_error_contains(
        query_identity_execute_forbidden,
        schema="query_workflow_api_error/v1",
        text="privacy_operator or platform_admin",
        label="identity query execute forbidden payload",
    )

    require(audit_identity_public_report.get("schema") == "audit_query_api_response/v1", f"identity audit public report returned wrong schema: {audit_identity_public_report}")
    audit_identity = audit_identity_public_report.get("authenticated_identity") or {}
    require(audit_identity.get("caller") == "auto_demo", f"identity audit public report returned wrong identity: {audit_identity_public_report}")

    require_error_contains(
        audit_identity_include_paths_forbidden,
        schema="audit_query_api_error/v1",
        text="include_paths",
        label="identity audit include-paths forbidden payload",
    )
    require_error_contains(
        platform_health_identity_forbidden,
        schema="platform_health_api_error/v1",
        text="platform_admin, platform_auditor, or service_operator",
        label="identity platform health forbidden payload",
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Validate platform API/query smoke reports materialized by check_json_contracts.sh.")
    ap.add_argument("--tmp-dir", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    tmp_dir = Path(args.tmp_dir).resolve()
    repo_root = Path(__file__).resolve().parent.parent
    require(tmp_dir.is_dir(), f"tmp dir does not exist: {tmp_dir}")

    validate_query_submissions(tmp_dir, repo_root)
    validate_query_api(tmp_dir)
    validate_metadata_api(tmp_dir)
    validate_audit_query_api(tmp_dir)
    validate_platform_health_api(tmp_dir)
    validate_platform_health_cli(tmp_dir)
    validate_identity_api_authz(tmp_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
