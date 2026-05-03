#!/usr/bin/env python3
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from runtime_service_helpers import available_port, wait_for_json_health


REPO_ROOT = Path(__file__).resolve().parents[1]
MODES = (
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
)
FIXTURE_PROFILE = "synthetic_completed_run_v1"
FIXTURE_JOB_ID = "benchmark-read-adapters"
FIXTURE_CORRELATION_ID = "benchmark-read-adapters"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * pct
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    weight = pos - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [float(item["duration_ms"]) for item in results if item.get("exit_code") == 0]
    failures = sum(1 for item in results if item.get("exit_code") != 0)
    return {
        "iterations": len(results),
        "successful_iterations": len(durations),
        "failed_iterations": failures,
        "duration_ms": {
            "min": round(min(durations), 3) if durations else None,
            "mean": round(statistics.fmean(durations), 3) if durations else None,
            "p50": round(percentile(durations, 0.50), 3) if durations else None,
            "p95": round(percentile(durations, 0.95), 3) if durations else None,
            "max": round(max(durations), 3) if durations else None,
        },
    }


def run_command(command: list[str], *, env: dict[str, str], timeout_sec: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_sec,
            env=env,
        )
        timed_out = False
        exit_code = result.returncode
        stderr_tail = "\n".join(result.stderr.splitlines()[-20:]) if result.stderr else ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        stderr_tail = str(exc)
    duration_ms = (time.perf_counter() - started) * 1000
    return {
        "duration_ms": round(duration_ms, 3),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stderr_tail": stderr_tail,
    }


def get_http_json(
    *,
    url: str,
    auth_token: str,
    timeout_sec: float,
    expected_schema: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    started = time.perf_counter()
    opener = build_opener(ProxyHandler({}))
    request = Request(url, method="GET")
    if auth_token:
        request.add_header("Authorization", f"Bearer {auth_token}")
    try:
        with opener.open(request, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("schema") != expected_schema:
            raise RuntimeError(f"unexpected response schema: {payload}")
        timed_out = False
        exit_code = 0
        stderr_tail = ""
    except HTTPError as exc:
        timed_out = False
        exit_code = exc.code
        stderr_tail = exc.read().decode("utf-8", errors="replace")
        payload = None
    except URLError as exc:
        timed_out = False
        exit_code = 1
        stderr_tail = str(exc)
        payload = None
    except Exception as exc:
        timed_out = False
        exit_code = 1
        stderr_tail = str(exc)
        payload = None
    duration_ms = (time.perf_counter() - started) * 1000
    return (
        {
            "duration_ms": round(duration_ms, 3),
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stderr_tail": stderr_tail,
        },
        payload if isinstance(payload, dict) else None,
    )


def ensure_ok(result: subprocess.CompletedProcess[str], *, label: str) -> None:
    if result.returncode != 0:
        raise SystemExit(f"[ERROR] {label} failed:\n{result.stderr}")


def run_checked(command: list[str], *, env: dict[str, str] | None = None, label: str) -> None:
    result = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    ensure_ok(result, label=label)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    path.write_text(rendered, encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_policy_fixture(path: Path, *, tenant_id: str, dataset_id: str, service_id: str) -> None:
    write_json(
        path,
        {
            "schema": "sse_export_policy/v1",
            "callers": {
                "auto_demo": {
                    "enabled": True,
                    "tenant_id": tenant_id,
                    "allowed_dataset_ids": [dataset_id],
                    "allowed_service_ids": [service_id],
                    "platform_roles": ["query_submitter", "privacy_operator"],
                    "access_profile": "commerce_ops_owner",
                    "allowed_roles": ["server", "client"],
                    "allowed_fields": ["email", "amount"],
                    "allowed_join_key_fields": ["email"],
                    "allowed_value_fields": ["amount"],
                    "allowed_filter_fields": ["campaign"],
                    "required_filters": ["campaign"],
                    "allowed_filter_values": {"campaign": ["demo"]},
                    "max_export_rows": 100000,
                    "min_export_rows": 1,
                    "can_use_record_recovery_service": True,
                    "can_run_bridge": True,
                    "can_run_pjc": True,
                    "can_release": True,
                },
                "marketing_analyst_demo": {
                    "enabled": True,
                    "tenant_id": tenant_id,
                    "allowed_dataset_ids": [dataset_id],
                    "allowed_service_ids": [service_id],
                    "platform_roles": ["query_submitter"],
                    "access_profile": "campaign_analyst",
                    "allowed_roles": ["client"],
                    "allowed_fields": ["email", "amount"],
                    "allowed_join_key_fields": ["email"],
                    "allowed_value_fields": ["amount"],
                    "allowed_filter_fields": ["campaign"],
                    "required_filters": ["campaign"],
                    "allowed_filter_values": {"campaign": ["demo"]},
                    "max_export_rows": 25000,
                    "min_export_rows": 1,
                    "can_use_record_recovery_service": True,
                    "can_run_bridge": True,
                    "can_run_pjc": True,
                    "can_release": False,
                },
                "audit_reviewer_demo": {
                    "enabled": False,
                    "tenant_id": tenant_id,
                    "allowed_dataset_ids": [dataset_id],
                    "allowed_service_ids": [],
                    "platform_roles": ["platform_auditor"],
                    "access_profile": "compliance_auditor",
                    "allowed_roles": [],
                    "allowed_fields": [],
                    "allowed_join_key_fields": [],
                    "allowed_value_fields": [],
                    "allowed_filter_fields": [],
                    "required_filters": [],
                    "allowed_filter_values": {},
                    "max_export_rows": 1,
                    "min_export_rows": 0,
                    "can_use_record_recovery_service": False,
                    "can_run_bridge": False,
                    "can_run_pjc": False,
                    "can_release": False,
                },
            },
        },
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def validate_mainline_summary(summary: dict[str, Any], *, label: str) -> dict[str, Any]:
    require(
        summary.get("schema") == "mainline_contract_check/v1"
        and summary.get("status") == "ok"
        and summary.get("embedded_in_audit_chain") is True,
        f"{label} missing embedded mainline contract summary: {summary}",
    )
    handoff = summary.get("handoff_cleanup")
    require(isinstance(handoff, dict), f"{label} missing handoff cleanup summary: {summary}")
    require(
        handoff.get("server") == "removed" and handoff.get("client") == "cleaned",
        f"{label} returned invalid handoff cleanup summary: {summary}",
    )
    service_consistency = summary.get("service_audit_consistency")
    require(isinstance(service_consistency, dict), f"{label} missing service audit consistency summary: {summary}")
    require(
        service_consistency.get("server") == "not_applicable"
        and service_consistency.get("client") == "ok"
        and service_consistency.get("error_count") == 0,
        f"{label} returned invalid service audit consistency summary: {summary}",
    )
    return {
        "mainline_contract_embedded": True,
        "handoff_cleanup_server": handoff.get("server"),
        "handoff_cleanup_client": handoff.get("client"),
        "service_audit_consistency_server": service_consistency.get("server"),
        "service_audit_consistency_client": service_consistency.get("client"),
        "service_audit_consistency_error_count": service_consistency.get("error_count"),
    }


def empty_semantics() -> dict[str, Any]:
    return {
        "result_schema": None,
        "job_count": None,
        "pagination_limit": None,
        "pagination_offset": None,
        "pagination_returned_count": None,
        "pagination_total_matching_count": None,
        "pagination_has_more": None,
        "pagination_next_offset": None,
        "pagination_previous_offset": None,
        "mainline_contract_embedded": None,
        "handoff_cleanup_server": None,
        "handoff_cleanup_client": None,
        "service_audit_consistency_server": None,
        "service_audit_consistency_client": None,
        "service_audit_consistency_error_count": None,
        "mainline_summary_rollup_job_count": None,
        "mainline_summary_rollup_server_removed_count": None,
        "mainline_summary_rollup_client_cleaned_count": None,
        "mainline_summary_rollup_server_not_applicable_count": None,
        "mainline_summary_rollup_client_ok_count": None,
        "permission_summary_caller_count": None,
        "permission_summary_dataset_count": None,
        "permission_summary_service_count": None,
        "permission_summary_platform_role_count": None,
        "permission_summary_has_query_submitter": None,
        "permission_summary_has_privacy_operator": None,
        "permission_summary_can_run_bridge_true": None,
        "permission_summary_can_release_true": None,
        "permission_summary_can_use_record_recovery_service_true": None,
    }


def validate_pagination(
    payload: dict[str, Any],
    *,
    label: str,
    limit: int,
    offset: int,
    returned_count: int,
    total_matching_count: int,
    has_more: bool,
) -> dict[str, Any]:
    pagination = payload.get("pagination")
    require(isinstance(pagination, dict), f"{label} missing pagination payload: {payload}")
    require(pagination.get("limit") == limit, f"{label} returned wrong pagination limit: {payload}")
    require(pagination.get("offset") == offset, f"{label} returned wrong pagination offset: {payload}")
    require(pagination.get("returned_count") == returned_count, f"{label} returned wrong pagination returned_count: {payload}")
    require(
        pagination.get("total_matching_count") == total_matching_count,
        f"{label} returned wrong pagination total_matching_count: {payload}",
    )
    require(pagination.get("has_more") is has_more, f"{label} returned wrong pagination has_more: {payload}")
    expected_next_offset = offset + returned_count if has_more else None
    expected_previous_offset = max(offset - limit, 0) if offset > 0 else None
    require(pagination.get("next_offset") == expected_next_offset, f"{label} returned wrong pagination next_offset: {payload}")
    require(
        pagination.get("previous_offset") == expected_previous_offset,
        f"{label} returned wrong pagination previous_offset: {payload}",
    )
    return {
        "pagination_limit": pagination.get("limit"),
        "pagination_offset": pagination.get("offset"),
        "pagination_returned_count": pagination.get("returned_count"),
        "pagination_total_matching_count": pagination.get("total_matching_count"),
        "pagination_has_more": pagination.get("has_more"),
        "pagination_next_offset": pagination.get("next_offset"),
        "pagination_previous_offset": pagination.get("previous_offset"),
    }


def validate_metadata_job_payload(payload: dict[str, Any], *, label: str) -> dict[str, Any]:
    job = payload.get("job")
    require(isinstance(job, dict) and job.get("job_id") == FIXTURE_JOB_ID, f"{label} returned wrong job payload: {payload}")
    semantics = validate_mainline_summary(payload.get("mainline_contract_summary") or {}, label=label)
    return {
        "result_schema": "query_metadata/job_detail",
        "job_count": 1,
        **semantics,
    }


def validate_metadata_jobs_payload(payload: dict[str, Any], *, label: str) -> dict[str, Any]:
    jobs = payload.get("jobs")
    require(isinstance(jobs, list) and len(jobs) == 1, f"{label} returned wrong jobs payload: {payload}")
    job = jobs[0]
    require(isinstance(job, dict) and job.get("job_id") == FIXTURE_JOB_ID, f"{label} returned wrong jobs row: {payload}")
    semantics = validate_mainline_summary(job.get("mainline_contract_summary") or {}, label=label)
    rollup = payload.get("mainline_contract_summary_counts") or {}
    require(rollup.get("job_count") == 1, f"{label} returned wrong mainline summary rollup job_count: {payload}")
    require(
        ((rollup.get("handoff_cleanup") or {}).get("server") or {}).get("removed") == 1
        and ((rollup.get("handoff_cleanup") or {}).get("client") or {}).get("cleaned") == 1,
        f"{label} returned wrong handoff cleanup rollup: {payload}",
    )
    require(
        ((rollup.get("service_audit_consistency") or {}).get("server") or {}).get("not_applicable") == 1
        and ((rollup.get("service_audit_consistency") or {}).get("client") or {}).get("ok") == 1
        and (rollup.get("service_audit_consistency") or {}).get("error_count_total") == 0,
        f"{label} returned wrong service audit consistency rollup: {payload}",
    )
    pagination = validate_pagination(
        payload,
        label=label,
        limit=20,
        offset=0,
        returned_count=1,
        total_matching_count=1,
        has_more=False,
    )
    return {
        "result_schema": "query_metadata/jobs_list",
        "job_count": len(jobs),
        **pagination,
        **semantics,
        "mainline_summary_rollup_job_count": rollup.get("job_count"),
        "mainline_summary_rollup_server_removed_count": ((rollup.get("handoff_cleanup") or {}).get("server") or {}).get("removed"),
        "mainline_summary_rollup_client_cleaned_count": ((rollup.get("handoff_cleanup") or {}).get("client") or {}).get("cleaned"),
        "mainline_summary_rollup_server_not_applicable_count": ((rollup.get("service_audit_consistency") or {}).get("server") or {}).get("not_applicable"),
        "mainline_summary_rollup_client_ok_count": ((rollup.get("service_audit_consistency") or {}).get("client") or {}).get("ok"),
    }


def validate_metadata_api_job_payload(payload: dict[str, Any], *, label: str) -> dict[str, Any]:
    require(payload.get("schema") == "metadata_api_response/v1", f"{label} returned wrong schema: {payload}")
    result = payload.get("result")
    require(isinstance(result, dict), f"{label} returned malformed result payload: {payload}")
    semantics = validate_metadata_job_payload(result, label=label)
    semantics["result_schema"] = "metadata_api_response/v1"
    return semantics


def validate_metadata_api_jobs_payload(payload: dict[str, Any], *, label: str) -> dict[str, Any]:
    require(payload.get("schema") == "metadata_api_response/v1", f"{label} returned wrong schema: {payload}")
    result = payload.get("result")
    require(isinstance(result, dict), f"{label} returned malformed result payload: {payload}")
    semantics = validate_metadata_jobs_payload(result, label=label)
    semantics["result_schema"] = "metadata_api_response/v1"
    return semantics


def validate_metadata_permissions_payload(payload: dict[str, Any], *, label: str) -> dict[str, Any]:
    items = payload.get("items")
    require(isinstance(items, list) and len(items) >= 5, f"{label} returned wrong permission payload: {payload}")
    summary = payload.get("permission_summary")
    require(isinstance(summary, dict), f"{label} missing permission summary: {payload}")
    permissions = summary.get("permissions") or {}
    require(summary.get("caller_count") == 1, f"{label} returned wrong permission caller_count: {payload}")
    require(summary.get("callers") == ["auto_demo"], f"{label} returned wrong permission callers: {payload}")
    require(summary.get("tenant_ids") == ["contract-tenant"], f"{label} returned wrong permission tenants: {payload}")
    require(summary.get("allowed_dataset_ids") == ["contract-dataset"], f"{label} returned wrong permission datasets: {payload}")
    require(summary.get("allowed_service_ids") == ["contract-recovery-service"], f"{label} returned wrong permission services: {payload}")
    require((summary.get("enabled_counts") or {}).get("true") == 1, f"{label} returned wrong enabled counts: {payload}")
    role_counts = summary.get("platform_role_counts") or {}
    require(role_counts.get("query_submitter") == 1, f"{label} returned wrong query_submitter role count: {payload}")
    require(role_counts.get("privacy_operator") == 1, f"{label} returned wrong privacy_operator role count: {payload}")
    profiles = summary.get("access_profiles") or []
    require(len(profiles) == 1 and profiles[0].get("caller") == "auto_demo", f"{label} returned wrong access profiles: {payload}")
    require(profiles[0].get("access_profile") == "commerce_ops_owner", f"{label} returned wrong access profile: {payload}")
    pagination = validate_pagination(
        payload,
        label=label,
        limit=20,
        offset=0,
        returned_count=len(items),
        total_matching_count=len(items),
        has_more=False,
    )
    return {
        "result_schema": "query_metadata/caller_permissions",
        "job_count": None,
        **pagination,
        "permission_summary_caller_count": summary.get("caller_count"),
        "permission_summary_dataset_count": len(summary.get("allowed_dataset_ids") or []),
        "permission_summary_service_count": len(summary.get("allowed_service_ids") or []),
        "permission_summary_platform_role_count": sum(1 for count in role_counts.values() if count),
        "permission_summary_has_query_submitter": role_counts.get("query_submitter"),
        "permission_summary_has_privacy_operator": role_counts.get("privacy_operator"),
        "permission_summary_can_run_bridge_true": ((permissions.get("can_run_bridge") or {}).get("true")),
        "permission_summary_can_release_true": ((permissions.get("can_release") or {}).get("true")),
        "permission_summary_can_use_record_recovery_service_true": ((permissions.get("can_use_record_recovery_service") or {}).get("true")),
        **{key: value for key, value in empty_semantics().items() if key not in {
            "result_schema",
            "job_count",
            "pagination_limit",
            "pagination_offset",
            "pagination_returned_count",
            "pagination_total_matching_count",
            "pagination_has_more",
            "pagination_next_offset",
            "pagination_previous_offset",
            "permission_summary_caller_count",
            "permission_summary_dataset_count",
            "permission_summary_service_count",
            "permission_summary_platform_role_count",
            "permission_summary_has_query_submitter",
            "permission_summary_has_privacy_operator",
            "permission_summary_can_run_bridge_true",
            "permission_summary_can_release_true",
            "permission_summary_can_use_record_recovery_service_true",
        }},
    }


def validate_metadata_api_permissions_payload(payload: dict[str, Any], *, label: str) -> dict[str, Any]:
    require(payload.get("schema") == "metadata_api_response/v1", f"{label} returned wrong schema: {payload}")
    result = payload.get("result")
    require(isinstance(result, dict), f"{label} returned malformed result payload: {payload}")
    semantics = validate_metadata_permissions_payload(result, label=label)
    semantics["result_schema"] = "metadata_api_response/v1"
    return semantics


def materialize_fixture(run_root: Path, *, env: dict[str, str]) -> tuple[Path, Path]:
    out_base = run_root / "completed_run"
    sse_exports = out_base / "sse_exports"
    bridge_job = out_base / "bridge_job"
    a_psi_run = out_base / "a_psi_run"
    policy_path = str((run_root / "benchmark_export_policy.json").resolve())
    write_policy_fixture(
        Path(policy_path),
        tenant_id="contract-tenant",
        dataset_id="contract-dataset",
        service_id="contract-recovery-service",
    )

    write_jsonl(
        sse_exports / "export_audit.jsonl",
        [
            {
                "schema": "sse_bridge_export_audit/v1",
                "ts_utc": "2026-04-26T00:00:00Z",
                "event": "sse_bridge_export",
                "caller": "auto_demo",
                "correlation_id": FIXTURE_CORRELATION_ID,
                "job_id": FIXTURE_JOB_ID,
                "role": "server",
                "source_file": None,
                "source_sha256": None,
                "output_file": str((out_base / "sse_exports" / "server.fifo").resolve()),
                "output_file_type": "fifo",
                "output_sha256": "abc",
                "source_format": "jsonl",
                "out_format": "csv",
                "join_key_field": "email",
                "value_field": None,
                "filters": [],
                "input_rows": 2,
                "output_rows": 2,
                "policy_config": policy_path,
                "candidate_source": "local_filter",
                "record_id_field": None,
                "candidate_count": None,
                "record_store_file": None,
                "record_store_sha256": None,
                "tenant_id": "contract-tenant",
                "dataset_id": "contract-dataset",
                "service_id": "contract-recovery-service",
                "duration_ms": 12,
                "decision": "allow",
                "reason_code": "ok",
                "reason": "ok",
            },
            {
                "schema": "sse_bridge_export_audit/v1",
                "ts_utc": "2026-04-26T00:00:01Z",
                "event": "sse_bridge_export",
                "caller": "auto_demo",
                "correlation_id": FIXTURE_CORRELATION_ID,
                "job_id": FIXTURE_JOB_ID,
                "role": "client",
                "source_file": None,
                "source_sha256": None,
                "output_file": str((out_base / "sse_exports" / "client.csv").resolve()),
                "output_file_type": "file",
                "output_sha256": "def",
                "source_format": "jsonl",
                "out_format": "csv",
                "join_key_field": "email",
                "value_field": "amount",
                "filters": [{"field": "campaign", "value_sha256": "123"}],
                "input_rows": 2,
                "output_rows": 2,
                "policy_config": policy_path,
                "candidate_source": "sse_query",
                "record_id_field": "email_hex",
                "candidate_count": 2,
                "record_store_file": str((run_root / "client_store.enc.jsonl").resolve()),
                "record_store_sha256": "abc",
                "record_recovery_boundary": "service_socket",
                "tenant_id": "contract-tenant",
                "dataset_id": "contract-dataset",
                "service_id": "contract-recovery-service",
                "duration_ms": 34,
                "decision": "allow",
                "reason_code": "ok",
                "reason": "ok",
            },
        ],
    )

    write_json(
        sse_exports / "record_recovery_service_config.json",
        {
            "schema": "record_recovery_service_config/v1",
            "service_id": "contract-recovery-service",
            "tenant_id": "contract-tenant",
            "dataset_id": "contract-dataset",
            "socket_path": str((run_root / "record_recovery.sock").resolve()),
            "socket_mode": "600",
            "auth_token_env": "SSE_RECORD_RECOVERY_TOKEN",
            "allowed_callers": ["auto_demo"],
            "allowed_output_roots": [str(run_root.resolve())],
            "allowed_record_store_roots": [str(run_root.resolve())],
            "audit_log": str((out_base / "sse_exports" / "record_recovery_service_audit.jsonl").resolve()),
        },
    )
    write_json(
        sse_exports / "record_recovery_service_health.json",
        {
            "schema": "sse_record_recovery_health/v1",
            "ok": True,
            "service_id": "contract-recovery-service",
            "tenant_id": "contract-tenant",
            "dataset_id": "contract-dataset",
            "transport": "unix_socket",
            "socket_path": str((run_root / "record_recovery.sock").resolve()),
            "endpoint_url": None,
            "auth_required": True,
        },
    )
    write_jsonl(
        sse_exports / "record_recovery_service_audit.jsonl",
        [
            {
                "schema": "sse_record_recovery_service_audit/v1",
                "ts_utc": "2026-04-26T00:00:00Z",
                "event": "record_recovery_service_request",
                "service_id": "contract-recovery-service",
                "tenant_id": "contract-tenant",
                "dataset_id": "contract-dataset",
                "caller": "auto_demo",
                "correlation_id": FIXTURE_CORRELATION_ID,
                "job_id": FIXTURE_JOB_ID,
                "role": "client",
                "auth_mode": "env_token",
                "transport": "unix_socket",
                "socket_path": str((run_root / "record_recovery.sock").resolve()),
                "endpoint_url": None,
                "authz_policy_config": policy_path,
                "record_store_file": str((run_root / "client_store.enc.jsonl").resolve()),
                "record_store_sha256": "abc",
                "output_file": str((out_base / "sse_exports" / "client.csv").resolve()),
                "output_file_type": "file",
                "output_sha256": "def",
                "join_key_field": "email",
                "value_field": "amount",
                "candidate_count": 2,
                "filters": [{"field": "campaign", "value_sha256": "123"}],
                "input_rows": 2,
                "output_rows": 2,
                "duration_ms": 23,
                "decision": "allow",
                "reason_code": "ok",
                "reason": "ok",
            }
        ],
    )

    write_jsonl(
        bridge_job / "bridge_audit.jsonl",
        [
            {
                "schema": "bridge_audit/v1",
                "ts_unix_ms": 1,
                "event": "bridge_prepare_job",
                "job_id": FIXTURE_JOB_ID,
                "correlation_id": FIXTURE_CORRELATION_ID,
                "server_input_file_type": "fifo",
                "server_input_sha256": None,
                "client_input_file_type": "file",
                "client_input_sha256": "def",
                "duration_ms": 56,
                "decision": "allow",
                "reason_code": "ok",
                "token_secret_source": {"kind": "cli"},
            }
        ],
    )
    write_json(
        bridge_job / "job_meta.json",
        {
            "schema": "bridge_job_meta/v1",
            "job_id": FIXTURE_JOB_ID,
            "job_type": "bridge_prepared_csv",
            "generator": "bridge-rust-v0",
            "input_sizes": {"exposure_n": 2, "purchase_n": 2},
            "bridge": {
                "token_scheme": "bridge-hmac-sha256-v1",
                "token_scope": "benchmark-scope",
                "token_key_version": "1",
                "normalize_version": "1",
                "normalizer_schema_version": "normalizer-schema/v1",
                "dedup_policy": "one",
                "server": {"join_key_column": "email", "normalizer": "email"},
                "client": {"join_key_column": "email", "normalizer": "email"},
            },
            "inputs": {},
            "counts": {},
        },
    )
    write_text(
        bridge_job / "server.csv",
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n"
        "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789\n",
    )
    write_text(
        bridge_job / "client.csv",
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef,125\n"
        "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789,300\n",
    )

    write_jsonl(
        a_psi_run / "pjc_audit.jsonl",
        [
            {
                "schema": "pjc_audit/v1",
                "ts_utc": "2026-04-26T00:00:02Z",
                "event": "pjc_run",
                "job_id": FIXTURE_JOB_ID,
                "correlation_id": FIXTURE_CORRELATION_ID,
                "out_dir": str(a_psi_run.resolve()),
                "server_csv": str((bridge_job / "server.csv").resolve()),
                "server_csv_sha256": "abc",
                "client_csv": str((bridge_job / "client.csv").resolve()),
                "client_csv_sha256": "def",
                "server_log": str((a_psi_run / "server.log").resolve()),
                "server_log_sha256": "123",
                "client_log": str((a_psi_run / "client.log").resolve()),
                "client_log_sha256": "456",
                "result_file": str((a_psi_run / "attribution_result.json").resolve()),
                "result_sha256": "789",
                "duration_ms": 78,
                "decision": "allow",
                "reason_code": "ok",
                "reason": "ok",
                "exit_code": 0,
            }
        ],
    )
    write_json(
        a_psi_run / "attribution_result.json",
        {
            "job_id": FIXTURE_JOB_ID,
            "correlation_id": FIXTURE_CORRELATION_ID,
            "intersection_size": 2,
            "intersection_sum": 425,
        },
    )
    write_json(
        a_psi_run / "public_report.json",
        {
            "schema": "public_report/v2",
            "generated_at_utc": "2026-04-26T00:00:03Z",
            "policy_version": "w2-hmac-v1",
            "job_id": FIXTURE_JOB_ID,
            "correlation_id": FIXTURE_CORRELATION_ID,
            "caller": "auto_demo",
            "released": False,
            "reason": "below k",
            "reason_code": "below_k",
            "window": {"start": None, "end": None},
            "k_threshold": 20,
        },
    )
    write_jsonl(
        a_psi_run / "audit_log.jsonl",
        [
            {
                "schema": "policy_audit/v1",
                "ts_utc": "2026-04-26T00:00:03Z",
                "event": "policy_release",
                "policy_version": "w2-hmac-v1",
                "job_id": FIXTURE_JOB_ID,
                "correlation_id": FIXTURE_CORRELATION_ID,
                "caller": "auto_demo",
                "window": {"start": None, "end": None},
                "bucket": None,
                "value_mode": None,
                "bridge": None,
                "input_sizes": {},
                "input_file": str((a_psi_run / "attribution_result.json").resolve()),
                "input_sha256": "abc",
                "pjc_result_file": str((a_psi_run / "attribution_result.json").resolve()),
                "pjc_result_sha256": "abc",
                "release_file": str((a_psi_run / "public_report.json").resolve()),
                "release_sha256": "def",
                "threshold_k": 20,
                "round_sum_to": None,
                "rate_limit_used": 0,
                "rate_limit_max": 5,
                "canonical_query_signature": "sig",
                "parsed_metrics": {},
                "duration_ms": 11,
                "decision": "deny",
                "reason": "below k",
                "reason_code": "below_k",
                "released": None,
                "auth": {
                    "mode": "disabled_or_caller_only",
                    "key_id": None,
                    "timestamp": None,
                    "nonce": None,
                    "auth_ok": True,
                    "auth_reason_code": "auth_disabled",
                },
            }
        ],
    )

    run_checked(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "check_mainline_contract.py"),
            "--out-base",
            str(out_base),
            "--job-id",
            FIXTURE_JOB_ID,
            "--output",
            str((out_base / "mainline_contract_check.json").resolve()),
        ],
        env=env,
        label="check_mainline_contract",
    )
    run_checked(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_audit_chain.py"), "--out-base", str(out_base), "--job-id", FIXTURE_JOB_ID],
        env=env,
        label="build_audit_chain",
    )

    db_path = run_root / "platform_metadata.db"
    run_checked(
        [sys.executable, str(REPO_ROOT / "scripts" / "init_metadata_db.py"), "--db-path", str(db_path)],
        env=env,
        label="init_metadata_db",
    )
    run_checked(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "import_run_metadata.py"),
            "--out-base",
            str(out_base),
            "--db-path",
            str(db_path),
        ],
        env=env,
        label="import_run_metadata",
    )
    return out_base, db_path


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Benchmark metadata and completed-run audit read adapters without modifying the privacy pipeline.")
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--mode", choices=("all",) + MODES, default="all")
    ap.add_argument("--timeout-sec", type=float, default=30.0)
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-failures", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.iterations <= 0:
        raise SystemExit("[ERROR] --iterations must be positive")
    if args.timeout_sec <= 0:
        raise SystemExit("[ERROR] --timeout-sec must be positive")

    selected_modes = list(MODES) if args.mode == "all" else [args.mode]
    common_env = dict(os.environ)
    common_env.setdefault("SSE_RECORD_RECOVERY_TOKEN", "benchmark-record-recovery-token")

    metadata_api_process: subprocess.Popen[str] | None = None
    audit_api_process: subprocess.Popen[str] | None = None
    metadata_api_base_url = ""
    audit_api_base_url = ""
    metadata_startup_ms: float | None = None
    audit_startup_ms: float | None = None

    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="seccomp_read_adapter_bench.") as tmp_dir:
        run_root = Path(tmp_dir)
        out_base, db_path = materialize_fixture(run_root, env=common_env)

        metadata_env = dict(common_env)
        metadata_env["SECCOMP_METADATA_API_TOKEN"] = "benchmark-metadata-token"
        audit_env = dict(common_env)
        audit_env["SECCOMP_AUDIT_QUERY_API_TOKEN"] = "benchmark-audit-token"

        try:
            if any(mode.startswith("metadata_http_") or mode.startswith("metadata_client_") for mode in selected_modes):
                metadata_port = available_port()
                metadata_api_base_url = f"http://127.0.0.1:{metadata_port}"
                metadata_command = [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "serve_metadata_api.py"),
                    "--db-path",
                    str(db_path),
                    "--bind-host",
                    "127.0.0.1",
                    "--port",
                    str(metadata_port),
                    "--auth-token-env",
                    "SECCOMP_METADATA_API_TOKEN",
                ]
                started = time.perf_counter()
                metadata_api_process = subprocess.Popen(
                    metadata_command,
                    cwd=str(REPO_ROOT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=metadata_env,
                    text=True,
                )
                wait_for_json_health(url=f"{metadata_api_base_url}/healthz", timeout_sec=args.timeout_sec, interval_sec=0.05)
                metadata_startup_ms = round((time.perf_counter() - started) * 1000, 3)

            if any(mode.startswith("audit_http_") or mode.startswith("audit_client_") for mode in selected_modes):
                audit_port = available_port()
                audit_api_base_url = f"http://127.0.0.1:{audit_port}"
                audit_command = [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "serve_audit_query_api.py"),
                    "--out-base",
                    str(out_base),
                    "--bind-host",
                    "127.0.0.1",
                    "--port",
                    str(audit_port),
                    "--auth-token-env",
                    "SECCOMP_AUDIT_QUERY_API_TOKEN",
                ]
                started = time.perf_counter()
                audit_api_process = subprocess.Popen(
                    audit_command,
                    cwd=str(REPO_ROOT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=audit_env,
                    text=True,
                )
                wait_for_json_health(url=f"{audit_api_base_url}/healthz", timeout_sec=args.timeout_sec, interval_sec=0.05)
                audit_startup_ms = round((time.perf_counter() - started) * 1000, 3)

            for mode in selected_modes:
                mode_results: list[dict[str, Any]] = []
                family: str
                mode_command: list[str]
                server_startup_ms: float | None = None

                if mode == "metadata_cli_job":
                    family = "metadata"
                    output_path = run_root / f"{mode}.json"
                    mode_command = [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "query_metadata.py"),
                        "--db-path",
                        str(db_path),
                        "--job-id",
                        FIXTURE_JOB_ID,
                        "--output-file",
                        str(output_path),
                    ]
                    for _ in range(args.iterations):
                        result = run_command(mode_command, env=common_env, timeout_sec=args.timeout_sec)
                        if result["exit_code"] == 0:
                            result.update(validate_metadata_job_payload(load_json(output_path), label=mode))
                        else:
                            result.update(empty_semantics())
                        mode_results.append(result)
                elif mode == "metadata_cli_jobs":
                    family = "metadata"
                    output_path = run_root / f"{mode}.json"
                    mode_command = [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "query_metadata.py"),
                        "--db-path",
                        str(db_path),
                        "--caller",
                        "auto_demo",
                        "--stage",
                        "bridge",
                        "--limit",
                        "20",
                        "--output-file",
                        str(output_path),
                    ]
                    for _ in range(args.iterations):
                        result = run_command(mode_command, env=common_env, timeout_sec=args.timeout_sec)
                        if result["exit_code"] == 0:
                            result.update(validate_metadata_jobs_payload(load_json(output_path), label=mode))
                        else:
                            result.update(empty_semantics())
                        mode_results.append(result)
                elif mode == "metadata_http_job":
                    family = "metadata"
                    mode_command = ["GET", f"{metadata_api_base_url}/v1/jobs/{FIXTURE_JOB_ID}"]
                    server_startup_ms = metadata_startup_ms
                    for _ in range(args.iterations):
                        result, payload = get_http_json(
                                url=f"{metadata_api_base_url}/v1/jobs/{FIXTURE_JOB_ID}",
                                auth_token=metadata_env["SECCOMP_METADATA_API_TOKEN"],
                                timeout_sec=args.timeout_sec,
                                expected_schema="metadata_api_response/v1",
                            )
                        if result["exit_code"] == 0 and payload is not None:
                            result.update(validate_metadata_api_job_payload(payload, label=mode))
                        else:
                            result.update(empty_semantics())
                        mode_results.append(result)
                elif mode == "metadata_http_jobs":
                    family = "metadata"
                    mode_command = ["GET", f"{metadata_api_base_url}/v1/jobs?caller=auto_demo&stage=bridge&limit=20"]
                    server_startup_ms = metadata_startup_ms
                    for _ in range(args.iterations):
                        result, payload = get_http_json(
                            url=f"{metadata_api_base_url}/v1/jobs?caller=auto_demo&stage=bridge&limit=20",
                            auth_token=metadata_env["SECCOMP_METADATA_API_TOKEN"],
                            timeout_sec=args.timeout_sec,
                            expected_schema="metadata_api_response/v1",
                        )
                        if result["exit_code"] == 0 and payload is not None:
                            result.update(validate_metadata_api_jobs_payload(payload, label=mode))
                        else:
                            result.update(empty_semantics())
                        mode_results.append(result)
                elif mode == "metadata_client_job":
                    family = "metadata"
                    output_path = run_root / f"{mode}.json"
                    mode_command = [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "platform_api_client.py"),
                        "metadata-job",
                        "--base-url",
                        metadata_api_base_url,
                        "--auth-token-env",
                        "SECCOMP_METADATA_API_TOKEN",
                        "--job-id",
                        FIXTURE_JOB_ID,
                        "--output-file",
                        str(output_path),
                    ]
                    server_startup_ms = metadata_startup_ms
                    for _ in range(args.iterations):
                        result = run_command(mode_command, env=metadata_env, timeout_sec=args.timeout_sec)
                        if result["exit_code"] == 0:
                            result.update(validate_metadata_api_job_payload(load_json(output_path), label=mode))
                        else:
                            result.update(empty_semantics())
                        mode_results.append(result)
                elif mode == "metadata_client_jobs":
                    family = "metadata"
                    output_path = run_root / f"{mode}.json"
                    mode_command = [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "platform_api_client.py"),
                        "metadata-jobs",
                        "--base-url",
                        metadata_api_base_url,
                        "--auth-token-env",
                        "SECCOMP_METADATA_API_TOKEN",
                        "--param",
                        "caller=auto_demo",
                        "--param",
                        "stage=bridge",
                        "--param",
                        "limit=20",
                        "--output-file",
                        str(output_path),
                    ]
                    server_startup_ms = metadata_startup_ms
                    for _ in range(args.iterations):
                        result = run_command(mode_command, env=metadata_env, timeout_sec=args.timeout_sec)
                        if result["exit_code"] == 0:
                            result.update(validate_metadata_api_jobs_payload(load_json(output_path), label=mode))
                        else:
                            result.update(empty_semantics())
                        mode_results.append(result)
                elif mode == "metadata_http_entity":
                    family = "metadata"
                    mode_command = ["GET", f"{metadata_api_base_url}/v1/entities/caller-permissions?caller=auto_demo&limit=20"]
                    server_startup_ms = metadata_startup_ms
                    for _ in range(args.iterations):
                        result, payload = get_http_json(
                                url=f"{metadata_api_base_url}/v1/entities/caller-permissions?caller=auto_demo&limit=20",
                                auth_token=metadata_env["SECCOMP_METADATA_API_TOKEN"],
                                timeout_sec=args.timeout_sec,
                                expected_schema="metadata_api_response/v1",
                            )
                        if result["exit_code"] == 0 and payload is not None:
                            result.update(validate_metadata_api_permissions_payload(payload, label=mode))
                        else:
                            result.update(empty_semantics())
                        mode_results.append(result)
                elif mode == "metadata_client_entity":
                    family = "metadata"
                    output_path = run_root / f"{mode}.json"
                    mode_command = [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "platform_api_client.py"),
                        "metadata-entity",
                        "--base-url",
                        metadata_api_base_url,
                        "--auth-token-env",
                        "SECCOMP_METADATA_API_TOKEN",
                        "--entity",
                        "caller-permissions",
                        "--param",
                        "caller=auto_demo",
                        "--param",
                        "limit=20",
                        "--output-file",
                        str(output_path),
                    ]
                    server_startup_ms = metadata_startup_ms
                    for _ in range(args.iterations):
                        result = run_command(mode_command, env=metadata_env, timeout_sec=args.timeout_sec)
                        if result["exit_code"] == 0:
                            result.update(validate_metadata_api_permissions_payload(load_json(output_path), label=mode))
                        else:
                            result.update(empty_semantics())
                        mode_results.append(result)
                elif mode == "audit_http_audit_chain":
                    family = "audit"
                    mode_command = ["GET", f"{audit_api_base_url}/v1/audit-chain"]
                    server_startup_ms = audit_startup_ms
                    for _ in range(args.iterations):
                        result, _payload = get_http_json(
                                url=f"{audit_api_base_url}/v1/audit-chain",
                                auth_token=audit_env["SECCOMP_AUDIT_QUERY_API_TOKEN"],
                                timeout_sec=args.timeout_sec,
                                expected_schema="audit_query_api_response/v1",
                            )
                        result.update(empty_semantics())
                        mode_results.append(result)
                elif mode == "audit_http_public_report":
                    family = "audit"
                    mode_command = ["GET", f"{audit_api_base_url}/v1/public-report"]
                    server_startup_ms = audit_startup_ms
                    for _ in range(args.iterations):
                        result, _payload = get_http_json(
                                url=f"{audit_api_base_url}/v1/public-report",
                                auth_token=audit_env["SECCOMP_AUDIT_QUERY_API_TOKEN"],
                                timeout_sec=args.timeout_sec,
                                expected_schema="audit_query_api_response/v1",
                            )
                        result.update(empty_semantics())
                        mode_results.append(result)
                elif mode == "audit_http_observability":
                    family = "audit"
                    mode_command = ["GET", f"{audit_api_base_url}/v1/observability"]
                    server_startup_ms = audit_startup_ms
                    for _ in range(args.iterations):
                        result, _payload = get_http_json(
                                url=f"{audit_api_base_url}/v1/observability",
                                auth_token=audit_env["SECCOMP_AUDIT_QUERY_API_TOKEN"],
                                timeout_sec=args.timeout_sec,
                                expected_schema="audit_query_api_response/v1",
                            )
                        result.update(empty_semantics())
                        mode_results.append(result)
                elif mode == "audit_http_catalog_lineage":
                    family = "audit"
                    mode_command = ["GET", f"{audit_api_base_url}/v1/catalog-lineage"]
                    server_startup_ms = audit_startup_ms
                    for _ in range(args.iterations):
                        result, _payload = get_http_json(
                                url=f"{audit_api_base_url}/v1/catalog-lineage",
                                auth_token=audit_env["SECCOMP_AUDIT_QUERY_API_TOKEN"],
                                timeout_sec=args.timeout_sec,
                                expected_schema="audit_query_api_response/v1",
                            )
                        result.update(empty_semantics())
                        mode_results.append(result)
                elif mode == "audit_client_audit_chain":
                    family = "audit"
                    mode_command = [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "platform_api_client.py"),
                        "audit-chain",
                        "--base-url",
                        audit_api_base_url,
                        "--auth-token-env",
                        "SECCOMP_AUDIT_QUERY_API_TOKEN",
                    ]
                    server_startup_ms = audit_startup_ms
                    for _ in range(args.iterations):
                        result = run_command(mode_command, env=audit_env, timeout_sec=args.timeout_sec)
                        result.update(empty_semantics())
                        mode_results.append(result)
                elif mode == "audit_client_public_report":
                    family = "audit"
                    mode_command = [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "platform_api_client.py"),
                        "audit-public-report",
                        "--base-url",
                        audit_api_base_url,
                        "--auth-token-env",
                        "SECCOMP_AUDIT_QUERY_API_TOKEN",
                    ]
                    server_startup_ms = audit_startup_ms
                    for _ in range(args.iterations):
                        result = run_command(mode_command, env=audit_env, timeout_sec=args.timeout_sec)
                        result.update(empty_semantics())
                        mode_results.append(result)
                elif mode == "audit_client_observability":
                    family = "audit"
                    mode_command = [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "platform_api_client.py"),
                        "audit-observability",
                        "--base-url",
                        audit_api_base_url,
                        "--auth-token-env",
                        "SECCOMP_AUDIT_QUERY_API_TOKEN",
                    ]
                    server_startup_ms = audit_startup_ms
                    for _ in range(args.iterations):
                        result = run_command(mode_command, env=audit_env, timeout_sec=args.timeout_sec)
                        result.update(empty_semantics())
                        mode_results.append(result)
                elif mode == "audit_client_catalog_lineage":
                    family = "audit"
                    mode_command = [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "platform_api_client.py"),
                        "audit-catalog-lineage",
                        "--base-url",
                        audit_api_base_url,
                        "--auth-token-env",
                        "SECCOMP_AUDIT_QUERY_API_TOKEN",
                    ]
                    server_startup_ms = audit_startup_ms
                    for _ in range(args.iterations):
                        result = run_command(mode_command, env=audit_env, timeout_sec=args.timeout_sec)
                        result.update(empty_semantics())
                        mode_results.append(result)
                else:
                    raise SystemExit(f"[ERROR] unsupported mode: {mode}")

                entry: dict[str, Any] = {
                    "mode": mode,
                    "family": family,
                    "command": mode_command,
                    "summary": summarize(mode_results),
                    "results": mode_results,
                }
                if server_startup_ms is not None:
                    entry["server_startup_ms"] = server_startup_ms
                results.append(entry)
        finally:
            if metadata_api_process is not None:
                metadata_api_process.terminate()
                try:
                    metadata_api_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    metadata_api_process.kill()
                    metadata_api_process.wait(timeout=5)
            if audit_api_process is not None:
                audit_api_process.terminate()
                try:
                    audit_api_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    audit_api_process.kill()
                    audit_api_process.wait(timeout=5)

    report = {
        "schema": "read_adapter_benchmark/v1",
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "fixture_profile": FIXTURE_PROFILE,
        "fixture_job_id": FIXTURE_JOB_ID,
        "iterations": args.iterations,
        "modes": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = (REPO_ROOT / output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)

    if args.allow_failures:
        return 0
    failures = sum(item["summary"]["failed_iterations"] for item in results)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
