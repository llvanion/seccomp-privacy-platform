#!/usr/bin/env python3
import argparse
import csv
import io
import json
import sqlite3
from pathlib import Path
from typing import Any

from archive_audit_bundle import load_json_object, summarize_mainline_contract
from metadata_db import connect_db, row_to_dict


LIST_ENTITY_CHOICES = (
    "tenants",
    "datasets",
    "services",
    "callers",
    "caller-identities",
    "key-refs",
    "key-versions",
    "policies",
    "policy-bindings",
    "caller-permissions",
    "job-state-transitions",
    "policy-versions",
    "service-versions",
    "catalog-lineage-read-model",
    "retention-reconcile-plan",
)

PLATFORM_ROLE_NAMES = (
    "platform_admin",
    "platform_auditor",
    "privacy_operator",
    "query_submitter",
    "service_operator",
)

ENTITY_COLUMNS = {
    "tenants": [
        "tenant_id",
        "created_at_utc",
        "source",
        "last_seen_job_id",
        "job_count",
        "latest_imported_at_utc",
    ],
    "datasets": [
        "dataset_id",
        "tenant_id",
        "created_at_utc",
        "source",
        "last_seen_job_id",
        "job_count",
        "latest_imported_at_utc",
    ],
    "services": [
        "service_id",
        "tenant_id",
        "dataset_id",
        "service_type",
        "transport",
        "config_path",
        "created_at_utc",
        "last_seen_job_id",
        "job_count",
        "latest_imported_at_utc",
    ],
    "callers": [
        "caller",
        "tenant_id",
        "created_at_utc",
        "source",
        "last_seen_job_id",
        "job_count",
        "latest_imported_at_utc",
        "identity_count",
        "enabled_identity_count",
    ],
    "caller-identities": [
        "id",
        "caller",
        "issuer",
        "subject",
        "subject_type",
        "service_id",
        "display_name",
        "platform_roles",
        "enabled",
        "source",
        "created_at_utc",
    ],
    "key-refs": [
        "key_name",
        "purpose",
        "service_id",
        "backend_kind",
        "backend_ref",
        "active_version",
        "allowed_callers",
        "source",
        "created_at_utc",
        "updated_at_utc",
        "version_count",
    ],
    "key-versions": [
        "id",
        "key_name",
        "purpose",
        "service_id",
        "backend_kind",
        "version",
        "enabled",
        "status",
        "secret_ref_kind",
        "secret_ref_name",
        "backend_key_version",
        "created_at_utc",
        "source",
        "metadata",
    ],
    "policies": [
        "policy_id",
        "policy_kind",
        "path",
        "sha256",
        "schema_name",
        "imported_at_utc",
        "binding_count",
        "permission_count",
    ],
    "policy-bindings": [
        "id",
        "policy_id",
        "binding_kind",
        "caller",
        "tenant_id",
        "dataset_id",
        "service_id",
        "source_file",
        "imported_at_utc",
        "binding_json",
    ],
    "caller-permissions": [
        "id",
        "policy_id",
        "caller",
        "permission_key",
        "permission_value",
        "source_file",
        "imported_at_utc",
    ],
    "job-state-transitions": [
        "id",
        "job_id",
        "transition_ordinal",
        "from_state",
        "to_state",
        "stage",
        "event_type",
        "ts_utc",
        "source",
        "source_event_id",
        "details",
    ],
    "policy-versions": [
        "id",
        "policy_id",
        "policy_kind",
        "path",
        "version",
        "sha256",
        "schema_name",
        "imported_at_utc",
        "is_current",
        "metadata",
    ],
    "service-versions": [
        "id",
        "service_id",
        "version",
        "tenant_id",
        "dataset_id",
        "service_type",
        "transport",
        "config_path",
        "effective_at_utc",
        "is_current",
        "metadata",
    ],
    "catalog-lineage-read-model": [
        "id",
        "job_id",
        "correlation_id",
        "caller",
        "tenant_id",
        "dataset_id",
        "service_id",
        "lineage_kind",
        "node_id",
        "node_type",
        "display_name",
        "role",
        "stage",
        "source_id",
        "target_id",
        "path_redacted",
        "metadata",
        "imported_at_utc",
    ],
    "retention-reconcile-plan": [
        "id",
        "scope",
        "entity_type",
        "entity_id",
        "job_id",
        "retention_class",
        "recommended_action",
        "reason_code",
        "reviewed",
        "created_at_utc",
        "details",
    ],
}


def fetch_all_dicts(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict]:
    return [row_to_dict(row) for row in conn.execute(query, params).fetchall()]


def fetch_scalar(conn: sqlite3.Connection, query: str, params: tuple = ()) -> Any:
    row = conn.execute(query, params).fetchone()
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return row[0]
    return row[0]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return bool(
        fetch_scalar(
            conn,
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        )
    )


def as_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    return None


def build_timing_summary(stage_status_rows: list[dict]) -> dict:
    stage_duration_summary: dict[str, int | None] = {}
    missing_duration_stages: list[str] = []
    total_duration_ms = 0
    has_duration = False
    for row in stage_status_rows:
        stage = str(row.get("stage") or "unknown")
        duration_ms = as_int(row.get("duration_ms"))
        stage_duration_summary[stage] = duration_ms
        if duration_ms is None:
            missing_duration_stages.append(stage)
            continue
        total_duration_ms += duration_ms
        has_duration = True
    return {
        "stage_duration_summary": stage_duration_summary,
        "total_stage_duration_ms": total_duration_ms if has_duration else None,
        "missing_duration_stages": missing_duration_stages,
    }


def build_stage_summary(stage: str, stage_rows: list[dict]) -> dict:
    status_counts: dict[str, int] = {}
    for row in stage_rows:
        status = str(row.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "stage": stage,
        "matched_job_count": len(stage_rows),
        "status_counts": status_counts,
        "duration_ms": build_duration_stats((as_int(row.get("duration_ms")) for row in stage_rows), total_count=len(stage_rows)),
        "mainline_contract_summary_counts": build_mainline_contract_summary_counts(stage_rows),
    }


def filter_stage_rows(stage_rows: list[dict], *, stage: str = "", stage_status: str = "") -> list[dict]:
    filtered: list[dict] = []
    for row in stage_rows:
        row_stage = str(row.get("stage") or "")
        row_status = str(row.get("status") or "")
        if stage and row_stage != stage:
            continue
        if stage_status and row_status != stage_status:
            continue
        filtered.append(row)
    return filtered


def build_grouped_stage_summary(stage_rows: list[dict], *, stage: str = "", stage_status: str = "") -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in filter_stage_rows(stage_rows, stage=stage, stage_status=stage_status):
        grouped.setdefault(str(row.get("stage") or "unknown"), []).append(row)
    return [build_stage_summary(stage_name, grouped[stage_name]) for stage_name in sorted(grouped)]


def build_duration_stats(values, *, total_count: int) -> dict:
    durations = [duration for duration in values if duration is not None]
    return {
        "count": len(durations),
        "missing_count": max(total_count - len(durations), 0),
        "total": sum(durations) if durations else None,
        "min": min(durations) if durations else None,
        "max": max(durations) if durations else None,
        "avg": (sum(durations) / len(durations)) if durations else None,
    }


def build_status_summary(status: str, jobs: list[dict]) -> dict:
    release_reason_counts: dict[str, int] = {}
    public_report_released_counts: dict[str, int] = {}
    for job in jobs:
        release_reason = str(job.get("release_reason_code") or "unknown")
        release_reason_counts[release_reason] = release_reason_counts.get(release_reason, 0) + 1
        release_flag = str(job.get("public_report_released"))
        public_report_released_counts[release_flag] = public_report_released_counts.get(release_flag, 0) + 1
    return {
        "status": status,
        "matched_job_count": len(jobs),
        "release_reason_counts": release_reason_counts,
        "public_report_released_counts": public_report_released_counts,
        "total_stage_duration_ms": build_duration_stats((as_int(job.get("total_stage_duration_ms")) for job in jobs), total_count=len(jobs)),
        "mainline_contract_summary_counts": build_mainline_contract_summary_counts(jobs),
    }


def load_mainline_contract_summary(audit_chain_path: str, *, cache: dict[str, dict | None] | None = None) -> dict | None:
    if not audit_chain_path:
        return None
    if cache is not None and audit_chain_path in cache:
        return cache[audit_chain_path]
    path = Path(audit_chain_path)
    summary = None
    if path.is_file():
        try:
            summary = summarize_mainline_contract(load_json_object(str(path)))
        except Exception:
            summary = None
    if cache is not None:
        cache[audit_chain_path] = summary
    return summary


def build_grouped_status_summary(jobs: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for job in jobs:
        grouped.setdefault(str(job.get("status") or "unknown"), []).append(job)
    return [build_status_summary(status, grouped[status]) for status in sorted(grouped)]


def increment_count(bucket: dict[str, int], key: Any) -> None:
    name = str(key) if key not in (None, "") else "unknown"
    bucket[name] = bucket.get(name, 0) + 1


def build_mainline_contract_summary_counts(jobs: list[dict]) -> dict:
    embedded_counts = {"true": 0, "false": 0, "unknown": 0}
    handoff_cleanup = {"server": {}, "client": {}}
    service_audit_consistency = {"server": {}, "client": {}, "error_count_total": 0}
    for job in jobs:
        summary = job.get("mainline_contract_summary")
        if not isinstance(summary, dict):
            embedded_counts["unknown"] += 1
            for role_name in ("server", "client"):
                increment_count(handoff_cleanup[role_name], None)
                increment_count(service_audit_consistency[role_name], None)
            continue
        embedded = summary.get("embedded_in_audit_chain")
        if embedded is True:
            embedded_counts["true"] += 1
        elif embedded is False:
            embedded_counts["false"] += 1
        else:
            embedded_counts["unknown"] += 1
        handoff = summary.get("handoff_cleanup") if isinstance(summary.get("handoff_cleanup"), dict) else {}
        service = (
            summary.get("service_audit_consistency")
            if isinstance(summary.get("service_audit_consistency"), dict)
            else {}
        )
        for role_name in ("server", "client"):
            increment_count(handoff_cleanup[role_name], handoff.get(role_name))
            increment_count(service_audit_consistency[role_name], service.get(role_name))
        service_audit_consistency["error_count_total"] += as_int(service.get("error_count")) or 0
    return {
        "job_count": len(jobs),
        "embedded_in_audit_chain": embedded_counts,
        "handoff_cleanup": handoff_cleanup,
        "service_audit_consistency": service_audit_consistency,
    }


def summary_scalar(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def parse_permission_value(value: Any) -> Any:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if item not in (None, "")})


def permission_values_by_caller(rows: list[dict]) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for row in rows:
        caller = str(row.get("caller") or "unknown")
        permission_key = str(row.get("permission_key") or "")
        if not permission_key:
            continue
        values.setdefault(caller, {})[permission_key] = parse_permission_value(row.get("permission_value"))
    return values


def permission_flag_counts(rows: list[dict], *, key: str) -> dict[str, int]:
    counts = {"true": 0, "false": 0, "unknown": 0}
    by_caller: dict[str, Any] = {}
    for row in rows:
        if row.get("permission_key") != key:
            continue
        caller = str(row.get("caller") or "unknown")
        by_caller[caller] = parse_permission_value(row.get("permission_value"))
    for value in by_caller.values():
        if value is True:
            counts["true"] += 1
        elif value is False:
            counts["false"] += 1
        else:
            counts["unknown"] += 1
    return counts


def build_permission_summary(rows: list[dict]) -> dict:
    values_by_caller = permission_values_by_caller(rows)
    callers = sorted(values_by_caller)
    tenant_ids = sorted(
        {
            str(values.get("tenant_id"))
            for values in values_by_caller.values()
            if values.get("tenant_id") not in (None, "")
        }
    )
    dataset_ids = sorted(
        {
            item
            for values in values_by_caller.values()
            for item in normalize_string_list(values.get("allowed_dataset_ids"))
        }
    )
    service_ids = sorted(
        {
            item
            for values in values_by_caller.values()
            for item in normalize_string_list(values.get("allowed_service_ids"))
        }
    )
    platform_role_counts = {role_name: 0 for role_name in PLATFORM_ROLE_NAMES}
    callers_by_platform_role = {role_name: [] for role_name in PLATFORM_ROLE_NAMES}
    access_profiles: list[dict[str, Any]] = []
    enabled_counts = {"true": 0, "false": 0, "unknown": 0}
    for caller in callers:
        values = values_by_caller.get(caller) or {}
        enabled = values.get("enabled")
        if enabled is True:
            enabled_counts["true"] += 1
        elif enabled is False:
            enabled_counts["false"] += 1
        else:
            enabled_counts["unknown"] += 1
        platform_roles = [role for role in normalize_string_list(values.get("platform_roles")) if role in PLATFORM_ROLE_NAMES]
        for role_name in platform_roles:
            platform_role_counts[role_name] += 1
            callers_by_platform_role[role_name].append(caller)
        access_profiles.append(
            {
                "caller": caller,
                "access_profile": values.get("access_profile"),
                "enabled": enabled,
                "tenant_id": values.get("tenant_id"),
                "platform_roles": platform_roles,
                "allowed_dataset_ids": normalize_string_list(values.get("allowed_dataset_ids")),
                "allowed_service_ids": normalize_string_list(values.get("allowed_service_ids")),
                "permissions": {
                    "can_run_bridge": values.get("can_run_bridge"),
                    "can_run_pjc": values.get("can_run_pjc"),
                    "can_release": values.get("can_release"),
                    "can_use_record_recovery_service": values.get("can_use_record_recovery_service"),
                },
            }
        )
    return {
        "caller_count": len(callers),
        "callers": callers,
        "tenant_ids": tenant_ids,
        "allowed_dataset_ids": dataset_ids,
        "allowed_service_ids": service_ids,
        "enabled_counts": enabled_counts,
        "platform_role_counts": platform_role_counts,
        "callers_by_platform_role": callers_by_platform_role,
        "access_profiles": access_profiles,
        "permissions": {
            "can_run_bridge": permission_flag_counts(rows, key="can_run_bridge"),
            "can_run_pjc": permission_flag_counts(rows, key="can_run_pjc"),
            "can_release": permission_flag_counts(rows, key="can_release"),
            "can_use_record_recovery_service": permission_flag_counts(rows, key="can_use_record_recovery_service"),
        },
    }


def decode_json_object(value: Any) -> Any:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def normalize_issuer(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def enrich_caller_rows_with_identity_counts(conn: sqlite3.Connection, rows: list[dict]) -> None:
    if not rows:
        return
    if not table_exists(conn, "caller_identities"):
        for row in rows:
            row["identity_count"] = 0
            row["enabled_identity_count"] = 0
        return
    caller_names = [str(row.get("caller") or "") for row in rows if row.get("caller") not in (None, "")]
    if not caller_names:
        return
    placeholders = ",".join("?" for _ in caller_names)
    counts = {
        str(row["caller"]): row
        for row in conn.execute(
            f"""
            SELECT
              caller,
              COUNT(*) AS identity_count,
              SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) AS enabled_identity_count
            FROM caller_identities
            WHERE caller IN ({placeholders})
            GROUP BY caller
            """,
            tuple(caller_names),
        ).fetchall()
    }
    for row in rows:
        summary = counts.get(str(row.get("caller") or ""))
        row["identity_count"] = int(summary["identity_count"]) if summary is not None else 0
        row["enabled_identity_count"] = int(summary["enabled_identity_count"]) if summary is not None else 0


def grouped_stage_rows(grouped_stage_summary: list[dict]) -> tuple[list[str], list[dict]]:
    columns = [
        "stage",
        "matched_job_count",
        "status_counts",
        "mainline_job_count",
        "mainline_embedded_true",
        "handoff_cleanup_server_removed",
        "handoff_cleanup_client_cleaned",
        "service_audit_consistency_server_not_applicable",
        "service_audit_consistency_client_ok",
        "service_audit_consistency_error_count_total",
        "duration_count",
        "duration_missing_count",
        "duration_total",
        "duration_min",
        "duration_max",
        "duration_avg",
    ]
    rows = []
    for item in grouped_stage_summary:
        duration = item.get("duration_ms") or {}
        mainline = item.get("mainline_contract_summary_counts") or {}
        rows.append(
            {
                "stage": item.get("stage"),
                "matched_job_count": item.get("matched_job_count"),
                "status_counts": item.get("status_counts"),
                "mainline_job_count": mainline.get("job_count"),
                "mainline_embedded_true": ((mainline.get("embedded_in_audit_chain") or {}).get("true")),
                "handoff_cleanup_server_removed": (((mainline.get("handoff_cleanup") or {}).get("server") or {}).get("removed")),
                "handoff_cleanup_client_cleaned": (((mainline.get("handoff_cleanup") or {}).get("client") or {}).get("cleaned")),
                "service_audit_consistency_server_not_applicable": (((mainline.get("service_audit_consistency") or {}).get("server") or {}).get("not_applicable")),
                "service_audit_consistency_client_ok": (((mainline.get("service_audit_consistency") or {}).get("client") or {}).get("ok")),
                "service_audit_consistency_error_count_total": ((mainline.get("service_audit_consistency") or {}).get("error_count_total")),
                "duration_count": duration.get("count"),
                "duration_missing_count": duration.get("missing_count"),
                "duration_total": duration.get("total"),
                "duration_min": duration.get("min"),
                "duration_max": duration.get("max"),
                "duration_avg": duration.get("avg"),
            }
        )
    return columns, rows


def grouped_status_rows(grouped_status_summary: list[dict]) -> tuple[list[str], list[dict]]:
    columns = [
        "status",
        "matched_job_count",
        "release_reason_counts",
        "public_report_released_counts",
        "mainline_job_count",
        "mainline_embedded_true",
        "handoff_cleanup_server_removed",
        "handoff_cleanup_client_cleaned",
        "service_audit_consistency_server_not_applicable",
        "service_audit_consistency_client_ok",
        "service_audit_consistency_error_count_total",
        "duration_count",
        "duration_missing_count",
        "duration_total",
        "duration_min",
        "duration_max",
        "duration_avg",
    ]
    rows = []
    for item in grouped_status_summary:
        duration = item.get("total_stage_duration_ms") or {}
        mainline = item.get("mainline_contract_summary_counts") or {}
        rows.append(
            {
                "status": item.get("status"),
                "matched_job_count": item.get("matched_job_count"),
                "release_reason_counts": item.get("release_reason_counts"),
                "public_report_released_counts": item.get("public_report_released_counts"),
                "mainline_job_count": mainline.get("job_count"),
                "mainline_embedded_true": ((mainline.get("embedded_in_audit_chain") or {}).get("true")),
                "handoff_cleanup_server_removed": (((mainline.get("handoff_cleanup") or {}).get("server") or {}).get("removed")),
                "handoff_cleanup_client_cleaned": (((mainline.get("handoff_cleanup") or {}).get("client") or {}).get("cleaned")),
                "service_audit_consistency_server_not_applicable": (((mainline.get("service_audit_consistency") or {}).get("server") or {}).get("not_applicable")),
                "service_audit_consistency_client_ok": (((mainline.get("service_audit_consistency") or {}).get("client") or {}).get("ok")),
                "service_audit_consistency_error_count_total": ((mainline.get("service_audit_consistency") or {}).get("error_count_total")),
                "duration_count": duration.get("count"),
                "duration_missing_count": duration.get("missing_count"),
                "duration_total": duration.get("total"),
                "duration_min": duration.get("min"),
                "duration_max": duration.get("max"),
                "duration_avg": duration.get("avg"),
            }
        )
    return columns, rows


def grouped_output_rows(result: dict, *, group_by: str) -> tuple[list[str], list[dict]]:
    if group_by == "stage":
        return grouped_stage_rows(result.get("grouped_stage_summary") or [])
    if group_by == "status":
        return grouped_status_rows(result.get("grouped_status_summary") or [])
    raise SystemExit("[ERROR] --output-format csv/tsv currently requires --group-by stage|status")


def parse_requested_columns(columns_arg: str, *, available_columns: list[str]) -> list[str]:
    if not columns_arg:
        return available_columns
    requested = [item.strip() for item in columns_arg.split(",") if item.strip()]
    if not requested:
        raise SystemExit("[ERROR] --columns must include at least one non-empty column name")
    unknown = [item for item in requested if item not in available_columns]
    if unknown:
        raise SystemExit(
            f"[ERROR] unknown columns for grouped output: {', '.join(unknown)}; "
            f"available columns: {', '.join(available_columns)}"
        )
    return requested


def render_delimited(result: dict, *, group_by: str, output_format: str, columns_arg: str) -> str:
    available_columns, rows = grouped_output_rows(result, group_by=group_by)
    columns = parse_requested_columns(columns_arg, available_columns=available_columns)

    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=columns,
        delimiter="\t" if output_format == "tsv" else ",",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({key: summary_scalar(row.get(key)) for key in columns})
    return buffer.getvalue()


def duration_sort_value(job: dict, *, stage: str) -> int | None:
    if stage:
        matched_stage = job.get("matched_stage")
        if isinstance(matched_stage, dict):
            return as_int(matched_stage.get("duration_ms"))
        return None
    return as_int(job.get("total_stage_duration_ms"))


def sort_jobs_by_duration(jobs: list[dict], *, stage: str, descending: bool) -> list[dict]:
    def key(job: dict) -> tuple[bool, int]:
        duration = duration_sort_value(job, stage=stage)
        numeric = duration if duration is not None else 0
        return (duration is None, -numeric if descending else numeric)

    return sorted(jobs, key=key)


def render_entity_delimited(result: dict, *, output_format: str, columns_arg: str) -> str:
    entity = str(result.get("entity") or "")
    available_columns = ENTITY_COLUMNS.get(entity)
    if not available_columns:
        rows = result.get("items") or []
        available_columns = list(rows[0].keys()) if rows else []
    columns = parse_requested_columns(columns_arg, available_columns=available_columns)
    rows = result.get("items") or []

    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=columns,
        delimiter="\t" if output_format == "tsv" else ",",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({key: summary_scalar(row.get(key)) for key in columns})
    return buffer.getvalue()


def build_pagination(*, limit: int, offset: int, returned_count: int, total_matching_count: int) -> dict:
    next_offset = offset + returned_count if (offset + returned_count) < total_matching_count else None
    previous_offset = max(offset - limit, 0) if offset > 0 else None
    return {
        "limit": limit,
        "offset": offset,
        "returned_count": returned_count,
        "total_matching_count": total_matching_count,
        "has_more": next_offset is not None,
        "next_offset": next_offset,
        "previous_offset": previous_offset,
    }


def validate_limit_offset(limit: int, offset: int) -> tuple[int, int]:
    if limit <= 0:
        raise SystemExit("[ERROR] --limit must be greater than 0")
    if limit > 1000:
        raise SystemExit("[ERROR] --limit must be <= 1000")
    if offset < 0:
        raise SystemExit("[ERROR] --offset must be >= 0")
    return limit, offset


def build_jobs_where_clause(
    *,
    caller: str,
    tenant_id: str,
    dataset_id: str,
    service_id: str,
    stage: str,
    stage_status: str,
) -> tuple[str, list[object]]:
    filters: list[str] = []
    params: list[object] = []
    if caller:
        filters.append("caller = ?")
        params.append(caller)
    if tenant_id:
        filters.append("tenant_id = ?")
        params.append(tenant_id)
    if dataset_id:
        filters.append("dataset_id = ?")
        params.append(dataset_id)
    if service_id:
        filters.append("service_id = ?")
        params.append(service_id)
    if stage and stage_status:
        filters.append("job_id IN (SELECT job_id FROM job_stage_status WHERE stage = ? AND status = ?)")
        params.extend((stage, stage_status))
    elif stage:
        filters.append("job_id IN (SELECT job_id FROM job_stage_status WHERE stage = ?)")
        params.append(stage)
    elif stage_status:
        filters.append("job_id IN (SELECT job_id FROM job_stage_status WHERE status = ?)")
        params.append(stage_status)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    return where, params


def query_job_detail(conn: sqlite3.Connection, job_id: str) -> dict:
    job = row_to_dict(conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone())
    if not job:
        raise SystemExit(f"[ERROR] job_id not found: {job_id}")
    stage_status = fetch_all_dicts(conn, "SELECT stage, status, ts_utc, duration_ms, details_json FROM job_stage_status WHERE job_id = ? ORDER BY stage", (job_id,))
    mainline_contract_summary = load_mainline_contract_summary(str(job.get("audit_chain_path") or ""))
    return {
        "job": job,
        "artifacts": fetch_all_dicts(conn, "SELECT stage, artifact_type, path, sha256, file_format, exists_on_disk, metadata_json FROM job_artifacts WHERE job_id = ? ORDER BY stage, artifact_type", (job_id,)),
        "stage_status": stage_status,
        "timing_summary": build_timing_summary(stage_status),
        "audit_events": fetch_all_dicts(conn, "SELECT stage, event_type, ts_utc, caller, tenant_id, dataset_id, service_id, decision, reason_code, artifact_path, duration_ms FROM audit_events WHERE job_id = ? ORDER BY id", (job_id,)),
        "key_access_events": fetch_all_dicts(conn, "SELECT ts_utc, caller, key_id, key_version, purpose, decision, reason_code FROM key_access_events WHERE job_id = ? ORDER BY id", (job_id,)),
        "audit_chain": row_to_dict(conn.execute("SELECT path, sha256, generated_at_utc, counts_json FROM audit_chains WHERE job_id = ?", (job_id,)).fetchone()),
        "audit_seal": row_to_dict(conn.execute("SELECT path, sha256, algorithm, signed FROM audit_seals WHERE job_id = ?", (job_id,)).fetchone()),
        "mainline_contract_summary": mainline_contract_summary,
    }


def query_jobs(
    conn: sqlite3.Connection,
    *,
    caller: str = "",
    tenant_id: str = "",
    dataset_id: str = "",
    service_id: str = "",
    stage: str = "",
    stage_status: str = "",
    stage_sort: str = "recent",
    group_by: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    limit, offset = validate_limit_offset(limit, offset)
    where, params = build_jobs_where_clause(
        caller=caller,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        service_id=service_id,
        stage=stage,
        stage_status=stage_status,
    )
    total_matching_count = int(
        fetch_scalar(
            conn,
            f"SELECT COUNT(*) FROM jobs {where}",
            tuple(params),
        )
        or 0
    )
    query_params = list(params)
    pagination_clause = ""
    if stage_sort == "recent":
        query_params.extend((limit, offset))
        pagination_clause = "LIMIT ? OFFSET ?"
    jobs = fetch_all_dicts(
        conn,
        f"""
        SELECT job_id, correlation_id, caller, tenant_id, dataset_id, service_id,
               status, release_reason_code, public_report_released,
               intersection_size, intersection_sum, created_at_utc, imported_at_utc,
               out_base, public_report_path, audit_chain_path
        FROM jobs
        {where}
        ORDER BY imported_at_utc DESC
        {pagination_clause}
        """,
        tuple(query_params),
    )
    all_stage_rows: list[dict] = []
    if jobs:
        summary_cache: dict[str, dict | None] = {}
        all_jobs = jobs
        if stage_sort != "recent":
            all_job_ids = [str(job["job_id"]) for job in all_jobs if job.get("job_id")]
            all_placeholders = ", ".join("?" for _ in all_job_ids)
            all_stage_rows = fetch_all_dicts(
                conn,
                f"""
                SELECT job_id, stage, status, ts_utc, duration_ms, details_json
                FROM job_stage_status
                WHERE job_id IN ({all_placeholders})
                ORDER BY job_id, stage
                """,
                tuple(all_job_ids),
            )
            stage_rows_by_job: dict[str, list[dict]] = {}
            for row in all_stage_rows:
                stage_rows_by_job.setdefault(str(row["job_id"]), []).append(row)
            for job in all_jobs:
                job_stage_rows = stage_rows_by_job.get(str(job["job_id"]), [])
                timing_summary = build_timing_summary(job_stage_rows)
                job["stage_duration_summary"] = timing_summary["stage_duration_summary"]
                job["total_stage_duration_ms"] = timing_summary["total_stage_duration_ms"]
                job["missing_duration_stages"] = timing_summary["missing_duration_stages"]
                job["mainline_contract_summary"] = load_mainline_contract_summary(
                    str(job.get("audit_chain_path") or ""),
                    cache=summary_cache,
                )
                if stage:
                    matched_stage = next((row for row in job_stage_rows if str(row.get("stage") or "") == stage), None)
                    job["matched_stage"] = {
                        "stage": matched_stage.get("stage"),
                        "status": matched_stage.get("status"),
                        "ts_utc": matched_stage.get("ts_utc"),
                        "duration_ms": matched_stage.get("duration_ms"),
                        "details_json": matched_stage.get("details_json"),
                    } if matched_stage else None
            if stage_sort == "duration_desc":
                all_jobs = sort_jobs_by_duration(all_jobs, stage=stage, descending=True)
            elif stage_sort == "duration_asc":
                all_jobs = sort_jobs_by_duration(all_jobs, stage=stage, descending=False)
            jobs = all_jobs[offset:offset + limit]
        job_ids = [str(job["job_id"]) for job in jobs if job.get("job_id")]
        if not job_ids:
            jobs = []
        else:
            placeholders = ", ".join("?" for _ in job_ids)
            stage_rows = fetch_all_dicts(
                conn,
                f"""
                SELECT job_id, stage, status, ts_utc, duration_ms, details_json
                FROM job_stage_status
                WHERE job_id IN ({placeholders})
                ORDER BY job_id, stage
                """,
                tuple(job_ids),
            )
            all_stage_rows = stage_rows
            stage_rows_by_job = {}
            for row in stage_rows:
                stage_rows_by_job.setdefault(str(row["job_id"]), []).append(row)
            for job in jobs:
                job_stage_rows = stage_rows_by_job.get(str(job["job_id"]), [])
                if stage_sort == "recent":
                    timing_summary = build_timing_summary(job_stage_rows)
                    job["stage_duration_summary"] = timing_summary["stage_duration_summary"]
                    job["total_stage_duration_ms"] = timing_summary["total_stage_duration_ms"]
                    job["missing_duration_stages"] = timing_summary["missing_duration_stages"]
                    job["mainline_contract_summary"] = load_mainline_contract_summary(
                        str(job.get("audit_chain_path") or ""),
                        cache=summary_cache,
                    )
                    if stage:
                        matched_stage = next((row for row in job_stage_rows if str(row.get("stage") or "") == stage), None)
                        job["matched_stage"] = {
                            "stage": matched_stage.get("stage"),
                            "status": matched_stage.get("status"),
                            "ts_utc": matched_stage.get("ts_utc"),
                            "duration_ms": matched_stage.get("duration_ms"),
                            "details_json": matched_stage.get("details_json"),
                        } if matched_stage else None
                for row in job_stage_rows:
                    row["mainline_contract_summary"] = job.get("mainline_contract_summary")
    matched_stage_rows = []
    if stage and jobs:
        for job in jobs:
            matched_stage = job.get("matched_stage")
            if isinstance(matched_stage, dict):
                matched_stage_rows.append(matched_stage)
    return {
        "filters": {
            "caller": caller or None,
            "tenant_id": tenant_id or None,
            "dataset_id": dataset_id or None,
            "service_id": service_id or None,
            "stage": stage or None,
            "stage_status": stage_status or None,
            "stage_sort": stage_sort,
            "group_by": group_by or None,
            "limit": limit,
            "offset": offset,
        },
        "count": len(jobs),
        "pagination": build_pagination(
            limit=limit,
            offset=offset,
            returned_count=len(jobs),
            total_matching_count=total_matching_count,
        ),
        "jobs": jobs,
        "mainline_contract_summary_counts": build_mainline_contract_summary_counts(jobs),
        "stage_summary": build_stage_summary(stage, matched_stage_rows) if stage else None,
        "grouped_stage_summary": build_grouped_stage_summary(all_stage_rows, stage=stage, stage_status=stage_status) if group_by == "stage" else None,
        "grouped_status_summary": build_grouped_status_summary(jobs) if group_by == "status" else None,
    }


def query_entities(
    conn: sqlite3.Connection,
    *,
    entity: str,
    caller: str = "",
    tenant_id: str = "",
    dataset_id: str = "",
    service_id: str = "",
    policy_id: str = "",
    binding_kind: str = "",
    permission_key: str = "",
    subject_type: str = "",
    issuer: str = "",
    key_name: str = "",
    purpose: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    limit, offset = validate_limit_offset(limit, offset)
    filters: list[str] = []
    params: list[object] = []
    rows: list[dict]
    permission_summary_rows: list[dict] | None = None

    if entity == "tenants":
        if tenant_id:
            filters.append("t.tenant_id = ?")
            params.append(tenant_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        total_matching_count = int(
            fetch_scalar(
                conn,
                f"""
                SELECT COUNT(*)
                FROM (
                  SELECT t.tenant_id
                  FROM tenants t
                  LEFT JOIN jobs j ON j.tenant_id = t.tenant_id
                  {where}
                  GROUP BY t.tenant_id, t.created_at_utc, t.source, t.last_seen_job_id
                )
                """,
                tuple(params),
            )
            or 0
        )
        rows = fetch_all_dicts(
            conn,
            f"""
            SELECT
              t.tenant_id,
              t.created_at_utc,
              t.source,
              t.last_seen_job_id,
              COUNT(DISTINCT j.job_id) AS job_count,
              MAX(j.imported_at_utc) AS latest_imported_at_utc
            FROM tenants t
            LEFT JOIN jobs j ON j.tenant_id = t.tenant_id
            {where}
            GROUP BY t.tenant_id, t.created_at_utc, t.source, t.last_seen_job_id
            ORDER BY latest_imported_at_utc DESC, t.tenant_id ASC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
    elif entity == "datasets":
        if tenant_id:
            filters.append("d.tenant_id = ?")
            params.append(tenant_id)
        if dataset_id:
            filters.append("d.dataset_id = ?")
            params.append(dataset_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        total_matching_count = int(
            fetch_scalar(
                conn,
                f"""
                SELECT COUNT(*)
                FROM (
                  SELECT d.dataset_id
                  FROM datasets d
                  LEFT JOIN jobs j ON j.dataset_id = d.dataset_id
                  {where}
                  GROUP BY d.dataset_id, d.tenant_id, d.created_at_utc, d.source, d.last_seen_job_id
                )
                """,
                tuple(params),
            )
            or 0
        )
        rows = fetch_all_dicts(
            conn,
            f"""
            SELECT
              d.dataset_id,
              d.tenant_id,
              d.created_at_utc,
              d.source,
              d.last_seen_job_id,
              COUNT(DISTINCT j.job_id) AS job_count,
              MAX(j.imported_at_utc) AS latest_imported_at_utc
            FROM datasets d
            LEFT JOIN jobs j ON j.dataset_id = d.dataset_id
            {where}
            GROUP BY d.dataset_id, d.tenant_id, d.created_at_utc, d.source, d.last_seen_job_id
            ORDER BY latest_imported_at_utc DESC, d.dataset_id ASC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
    elif entity == "services":
        if tenant_id:
            filters.append("s.tenant_id = ?")
            params.append(tenant_id)
        if dataset_id:
            filters.append("s.dataset_id = ?")
            params.append(dataset_id)
        if service_id:
            filters.append("s.service_id = ?")
            params.append(service_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        total_matching_count = int(
            fetch_scalar(
                conn,
                f"""
                SELECT COUNT(*)
                FROM (
                  SELECT s.service_id
                  FROM services s
                  LEFT JOIN jobs j ON j.service_id = s.service_id
                  {where}
                  GROUP BY
                    s.service_id, s.tenant_id, s.dataset_id, s.service_type, s.transport,
                    s.config_path, s.created_at_utc, s.last_seen_job_id
                )
                """,
                tuple(params),
            )
            or 0
        )
        rows = fetch_all_dicts(
            conn,
            f"""
            SELECT
              s.service_id,
              s.tenant_id,
              s.dataset_id,
              s.service_type,
              s.transport,
              s.config_path,
              s.created_at_utc,
              s.last_seen_job_id,
              COUNT(DISTINCT j.job_id) AS job_count,
              MAX(j.imported_at_utc) AS latest_imported_at_utc
            FROM services s
            LEFT JOIN jobs j ON j.service_id = s.service_id
            {where}
            GROUP BY
              s.service_id, s.tenant_id, s.dataset_id, s.service_type, s.transport,
              s.config_path, s.created_at_utc, s.last_seen_job_id
            ORDER BY latest_imported_at_utc DESC, s.service_id ASC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
    elif entity == "callers":
        if caller:
            filters.append("c.caller = ?")
            params.append(caller)
        if tenant_id:
            filters.append("c.tenant_id = ?")
            params.append(tenant_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        total_matching_count = int(
            fetch_scalar(
                conn,
                f"""
                SELECT COUNT(*)
                FROM (
                  SELECT c.caller
                  FROM callers c
                  LEFT JOIN jobs j ON j.caller = c.caller
                  {where}
                  GROUP BY c.caller, c.tenant_id, c.created_at_utc, c.source, c.last_seen_job_id
                )
                """,
                tuple(params),
            )
            or 0
        )
        rows = fetch_all_dicts(
            conn,
            f"""
            SELECT
              c.caller,
              c.tenant_id,
              c.created_at_utc,
              c.source,
              c.last_seen_job_id,
              COUNT(DISTINCT j.job_id) AS job_count,
              MAX(j.imported_at_utc) AS latest_imported_at_utc
            FROM callers c
            LEFT JOIN jobs j ON j.caller = c.caller
            {where}
            GROUP BY c.caller, c.tenant_id, c.created_at_utc, c.source, c.last_seen_job_id
            ORDER BY latest_imported_at_utc DESC, c.caller ASC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
        enrich_caller_rows_with_identity_counts(conn, rows)
    elif entity == "caller-identities":
        if caller:
            filters.append("caller = ?")
            params.append(caller)
        if service_id:
            filters.append("service_id = ?")
            params.append(service_id)
        if subject_type:
            filters.append("subject_type = ?")
            params.append(subject_type)
        if issuer:
            filters.append("issuer = ?")
            params.append(issuer)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        total_matching_count = int(
            fetch_scalar(
                conn,
                f"SELECT COUNT(*) FROM caller_identities {where}",
                tuple(params),
            )
            or 0
        )
        rows = fetch_all_dicts(
            conn,
            f"""
            SELECT
              id,
              caller,
              issuer,
              subject,
              subject_type,
              service_id,
              display_name,
              platform_roles_json,
              enabled,
              source,
              created_at_utc
            FROM caller_identities
            {where}
            ORDER BY created_at_utc DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
        for row in rows:
            row["issuer"] = normalize_issuer(row.get("issuer"))
            row["platform_roles"] = decode_json_object(row.pop("platform_roles_json"))
            row["enabled"] = as_bool(row.get("enabled"))
    elif entity == "key-refs":
        if key_name:
            filters.append("kr.key_name = ?")
            params.append(key_name)
        if service_id:
            filters.append("kr.service_id = ?")
            params.append(service_id)
        if purpose:
            filters.append("kr.purpose = ?")
            params.append(purpose)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        total_matching_count = int(
            fetch_scalar(
                conn,
                f"""
                SELECT COUNT(*)
                FROM (
                  SELECT kr.key_name
                  FROM key_refs kr
                  LEFT JOIN key_versions kv ON kv.key_name = kr.key_name
                  {where}
                  GROUP BY
                    kr.key_name, kr.purpose, kr.service_id, kr.backend_kind, kr.backend_ref,
                    kr.active_version, kr.allowed_callers_json, kr.source, kr.created_at_utc, kr.updated_at_utc
                )
                """,
                tuple(params),
            )
            or 0
        )
        rows = fetch_all_dicts(
            conn,
            f"""
            SELECT
              kr.key_name,
              kr.purpose,
              kr.service_id,
              kr.backend_kind,
              kr.backend_ref,
              kr.active_version,
              kr.allowed_callers_json,
              kr.source,
              kr.created_at_utc,
              kr.updated_at_utc,
              COUNT(DISTINCT kv.id) AS version_count
            FROM key_refs kr
            LEFT JOIN key_versions kv ON kv.key_name = kr.key_name
            {where}
            GROUP BY
              kr.key_name, kr.purpose, kr.service_id, kr.backend_kind, kr.backend_ref,
              kr.active_version, kr.allowed_callers_json, kr.source, kr.created_at_utc, kr.updated_at_utc
            ORDER BY kr.updated_at_utc DESC, kr.key_name ASC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
        for row in rows:
            row["allowed_callers"] = decode_json_object(row.pop("allowed_callers_json"))
    elif entity == "key-versions":
        if key_name:
            filters.append("kv.key_name = ?")
            params.append(key_name)
        if service_id:
            filters.append("kr.service_id = ?")
            params.append(service_id)
        if purpose:
            filters.append("kr.purpose = ?")
            params.append(purpose)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        total_matching_count = int(
            fetch_scalar(
                conn,
                f"""
                SELECT COUNT(*)
                FROM key_versions kv
                JOIN key_refs kr ON kr.key_name = kv.key_name
                {where}
                """,
                tuple(params),
            )
            or 0
        )
        rows = fetch_all_dicts(
            conn,
            f"""
            SELECT
              kv.id,
              kv.key_name,
              kr.purpose,
              kr.service_id,
              kr.backend_kind,
              kv.version,
              kv.enabled,
              kv.status,
              kv.secret_ref_kind,
              kv.secret_ref_name,
              kv.backend_key_version,
              kv.created_at_utc,
              kv.source,
              kv.metadata_json
            FROM key_versions kv
            JOIN key_refs kr ON kr.key_name = kv.key_name
            {where}
            ORDER BY kv.created_at_utc DESC, kv.id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
        for row in rows:
            row["enabled"] = as_bool(row.get("enabled"))
            row["metadata"] = decode_json_object(row.pop("metadata_json"))
    elif entity == "policies":
        if policy_id:
            filters.append("p.policy_id = ?")
            params.append(policy_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        total_matching_count = int(
            fetch_scalar(
                conn,
                f"""
                SELECT COUNT(*)
                FROM (
                  SELECT p.policy_id
                  FROM policies p
                  LEFT JOIN policy_bindings pb ON pb.policy_id = p.policy_id
                  LEFT JOIN caller_permissions cp ON cp.policy_id = p.policy_id
                  {where}
                  GROUP BY p.policy_id, p.policy_kind, p.path, p.sha256, p.schema_name, p.imported_at_utc
                )
                """,
                tuple(params),
            )
            or 0
        )
        rows = fetch_all_dicts(
            conn,
            f"""
            SELECT
              p.policy_id,
              p.policy_kind,
              p.path,
              p.sha256,
              p.schema_name,
              p.imported_at_utc,
              COUNT(DISTINCT pb.id) AS binding_count,
              COUNT(DISTINCT cp.id) AS permission_count
            FROM policies p
            LEFT JOIN policy_bindings pb ON pb.policy_id = p.policy_id
            LEFT JOIN caller_permissions cp ON cp.policy_id = p.policy_id
            {where}
            GROUP BY p.policy_id, p.policy_kind, p.path, p.sha256, p.schema_name, p.imported_at_utc
            ORDER BY p.imported_at_utc DESC, p.policy_id ASC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
    elif entity == "policy-bindings":
        if policy_id:
            filters.append("policy_id = ?")
            params.append(policy_id)
        if binding_kind:
            filters.append("binding_kind = ?")
            params.append(binding_kind)
        if caller:
            filters.append("caller = ?")
            params.append(caller)
        if tenant_id:
            filters.append("tenant_id = ?")
            params.append(tenant_id)
        if dataset_id:
            filters.append("dataset_id = ?")
            params.append(dataset_id)
        if service_id:
            filters.append("service_id = ?")
            params.append(service_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        total_matching_count = int(
            fetch_scalar(
                conn,
                f"SELECT COUNT(*) FROM policy_bindings {where}",
                tuple(params),
            )
            or 0
        )
        rows = fetch_all_dicts(
            conn,
            f"""
            SELECT
              id,
              policy_id,
              binding_kind,
              caller,
              tenant_id,
              dataset_id,
              service_id,
              source_file,
              imported_at_utc,
              binding_json
            FROM policy_bindings
            {where}
            ORDER BY imported_at_utc DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
    elif entity == "caller-permissions":
        if policy_id:
            filters.append("policy_id = ?")
            params.append(policy_id)
        if caller:
            filters.append("caller = ?")
            params.append(caller)
        if permission_key:
            filters.append("permission_key = ?")
            params.append(permission_key)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        total_matching_count = int(
            fetch_scalar(
                conn,
                f"SELECT COUNT(*) FROM caller_permissions {where}",
                tuple(params),
            )
            or 0
        )
        permission_summary_rows = fetch_all_dicts(
            conn,
            f"""
            SELECT
              id,
              policy_id,
              caller,
              permission_key,
              permission_value,
              source_file,
              imported_at_utc
            FROM caller_permissions
            {where}
            ORDER BY imported_at_utc DESC, id DESC
            """,
            tuple(params),
        )
        rows = fetch_all_dicts(
            conn,
            f"""
            SELECT
              id,
              policy_id,
              caller,
              permission_key,
              permission_value,
              source_file,
              imported_at_utc
            FROM caller_permissions
            {where}
            ORDER BY imported_at_utc DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
    elif entity == "job-state-transitions":
        total_matching_count = int(fetch_scalar(conn, "SELECT COUNT(*) FROM job_state_transitions") or 0)
        rows = fetch_all_dicts(
            conn,
            """
            SELECT
              id,
              job_id,
              transition_ordinal,
              from_state,
              to_state,
              stage,
              event_type,
              ts_utc,
              source,
              source_event_id,
              details_json
            FROM job_state_transitions
            ORDER BY job_id ASC, transition_ordinal ASC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        for row in rows:
            row["details"] = decode_json_object(row.pop("details_json"))
    elif entity == "policy-versions":
        if policy_id:
            filters.append("policy_id = ?")
            params.append(policy_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        total_matching_count = int(
            fetch_scalar(conn, f"SELECT COUNT(*) FROM policy_versions {where}", tuple(params)) or 0
        )
        rows = fetch_all_dicts(
            conn,
            f"""
            SELECT
              id,
              policy_id,
              policy_kind,
              path,
              version,
              sha256,
              schema_name,
              imported_at_utc,
              is_current,
              metadata_json
            FROM policy_versions
            {where}
            ORDER BY imported_at_utc DESC, policy_id ASC, version DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
        for row in rows:
            row["is_current"] = as_bool(row.get("is_current"))
            row["metadata"] = decode_json_object(row.pop("metadata_json"))
    elif entity == "service-versions":
        if service_id:
            filters.append("service_id = ?")
            params.append(service_id)
        if tenant_id:
            filters.append("tenant_id = ?")
            params.append(tenant_id)
        if dataset_id:
            filters.append("dataset_id = ?")
            params.append(dataset_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        total_matching_count = int(
            fetch_scalar(conn, f"SELECT COUNT(*) FROM service_versions {where}", tuple(params)) or 0
        )
        rows = fetch_all_dicts(
            conn,
            f"""
            SELECT
              id,
              service_id,
              version,
              tenant_id,
              dataset_id,
              service_type,
              transport,
              config_path,
              effective_at_utc,
              is_current,
              metadata_json
            FROM service_versions
            {where}
            ORDER BY effective_at_utc DESC, service_id ASC, version DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
        for row in rows:
            row["is_current"] = as_bool(row.get("is_current"))
            row["metadata"] = decode_json_object(row.pop("metadata_json"))
    elif entity == "catalog-lineage-read-model":
        if caller:
            filters.append("caller = ?")
            params.append(caller)
        if tenant_id:
            filters.append("tenant_id = ?")
            params.append(tenant_id)
        if dataset_id:
            filters.append("dataset_id = ?")
            params.append(dataset_id)
        if service_id:
            filters.append("service_id = ?")
            params.append(service_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        total_matching_count = int(
            fetch_scalar(conn, f"SELECT COUNT(*) FROM catalog_lineage_read_model {where}", tuple(params)) or 0
        )
        rows = fetch_all_dicts(
            conn,
            f"""
            SELECT
              id,
              job_id,
              correlation_id,
              caller,
              tenant_id,
              dataset_id,
              service_id,
              lineage_kind,
              node_id,
              node_type,
              display_name,
              role,
              stage,
              source_id,
              target_id,
              path_redacted,
              metadata_json,
              imported_at_utc
            FROM catalog_lineage_read_model
            {where}
            ORDER BY imported_at_utc DESC, lineage_kind ASC, id ASC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
        for row in rows:
            row["path_redacted"] = as_bool(row.get("path_redacted"))
            row["metadata"] = decode_json_object(row.pop("metadata_json"))
    elif entity == "retention-reconcile-plan":
        total_matching_count = int(fetch_scalar(conn, "SELECT COUNT(*) FROM retention_reconcile_plan") or 0)
        rows = fetch_all_dicts(
            conn,
            """
            SELECT
              id,
              scope,
              entity_type,
              entity_id,
              job_id,
              retention_class,
              recommended_action,
              reason_code,
              reviewed,
              created_at_utc,
              details_json
            FROM retention_reconcile_plan
            ORDER BY created_at_utc DESC, scope ASC, entity_type ASC, id ASC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        for row in rows:
            row["reviewed"] = as_bool(row.get("reviewed"))
            row["details"] = decode_json_object(row.pop("details_json"))
    else:
        raise SystemExit(f"[ERROR] unsupported --list-entity value: {entity}")

    return {
        "entity": entity,
        "filters": {
            "caller": caller or None,
            "tenant_id": tenant_id or None,
            "dataset_id": dataset_id or None,
            "service_id": service_id or None,
            "policy_id": policy_id or None,
            "binding_kind": binding_kind or None,
            "permission_key": permission_key or None,
            "subject_type": subject_type or None,
            "issuer": issuer or None,
            "key_name": key_name or None,
            "purpose": purpose or None,
            "limit": limit,
            "offset": offset,
        },
        "count": len(rows),
        "pagination": build_pagination(
            limit=limit,
            offset=offset,
            returned_count=len(rows),
            total_matching_count=total_matching_count,
        ),
        "items": rows,
        "permission_summary": build_permission_summary(permission_summary_rows or rows) if entity == "caller-permissions" else None,
    }


def validate_list_entity_args(args: argparse.Namespace) -> None:
    if args.job_id:
        raise SystemExit("[ERROR] --job-id cannot be combined with --list-entity")
    if args.group_by:
        raise SystemExit("[ERROR] --group-by cannot be combined with --list-entity")
    if args.stage:
        raise SystemExit("[ERROR] --stage cannot be combined with --list-entity")
    if args.stage_status:
        raise SystemExit("[ERROR] --stage-status cannot be combined with --list-entity")
    if args.stage_sort != "recent":
        raise SystemExit("[ERROR] --stage-sort cannot be combined with --list-entity")

    allowed_filters = {
        "tenants": {"tenant_id"},
        "datasets": {"tenant_id", "dataset_id"},
        "services": {"tenant_id", "dataset_id", "service_id"},
        "callers": {"caller", "tenant_id"},
        "caller-identities": {"caller", "service_id", "subject_type", "issuer"},
        "key-refs": {"service_id", "key_name", "purpose"},
        "key-versions": {"service_id", "key_name", "purpose"},
        "policies": {"policy_id"},
        "policy-bindings": {"policy_id", "binding_kind", "caller", "tenant_id", "dataset_id", "service_id"},
        "caller-permissions": {"policy_id", "caller", "permission_key"},
        "job-state-transitions": set(),
        "policy-versions": {"policy_id"},
        "service-versions": {"tenant_id", "dataset_id", "service_id"},
        "catalog-lineage-read-model": {"caller", "tenant_id", "dataset_id", "service_id"},
        "retention-reconcile-plan": set(),
    }
    provided_filters = {
        "caller": args.caller,
        "tenant_id": args.tenant_id,
        "dataset_id": args.dataset_id,
        "service_id": args.service_id,
        "policy_id": args.policy_id,
        "binding_kind": args.binding_kind,
        "permission_key": args.permission_key,
        "subject_type": args.subject_type,
        "issuer": args.issuer,
        "key_name": args.key_name,
        "purpose": args.purpose,
    }
    unsupported = [
        name
        for name, value in provided_filters.items()
        if value and name not in allowed_filters[args.list_entity]
    ]
    if unsupported:
        raise SystemExit(
            f"[ERROR] unsupported filters for --list-entity {args.list_entity}: {', '.join(sorted(unsupported))}"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="Query the sidecar metadata database by job, scope, registry, or policy tables.")
    ap.add_argument("--db-path", required=True)
    ap.add_argument("--job-id", default="")
    ap.add_argument("--list-entity", choices=LIST_ENTITY_CHOICES, default="")
    ap.add_argument("--caller", default="")
    ap.add_argument("--tenant-id", default="")
    ap.add_argument("--dataset-id", default="")
    ap.add_argument("--service-id", default="")
    ap.add_argument("--policy-id", default="")
    ap.add_argument("--binding-kind", default="")
    ap.add_argument("--permission-key", default="")
    ap.add_argument("--subject-type", default="")
    ap.add_argument("--issuer", default="")
    ap.add_argument("--key-name", default="")
    ap.add_argument("--purpose", default="")
    ap.add_argument("--stage", default="")
    ap.add_argument("--stage-status", default="")
    ap.add_argument("--stage-sort", choices=("recent", "duration_desc", "duration_asc"), default="recent")
    ap.add_argument("--group-by", choices=("stage", "status"), default="")
    ap.add_argument("--output-format", choices=("json", "csv", "tsv"), default="json")
    ap.add_argument("--columns", default="")
    ap.add_argument("--output-file", default="")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--offset", type=int, default=0)
    args = ap.parse_args()

    conn = connect_db(args.db_path)
    try:
        if args.list_entity:
            validate_list_entity_args(args)
            result = query_entities(
                conn,
                entity=args.list_entity,
                caller=args.caller,
                tenant_id=args.tenant_id,
                dataset_id=args.dataset_id,
                service_id=args.service_id,
                policy_id=args.policy_id,
                binding_kind=args.binding_kind,
            permission_key=args.permission_key,
            subject_type=args.subject_type,
            issuer=args.issuer,
            key_name=args.key_name,
            purpose=args.purpose,
            limit=args.limit,
            offset=args.offset,
        )
        elif args.job_id:
            result = query_job_detail(conn, args.job_id)
        else:
            result = query_jobs(
                conn,
                caller=args.caller,
                tenant_id=args.tenant_id,
                dataset_id=args.dataset_id,
                service_id=args.service_id,
                stage=args.stage,
                stage_status=args.stage_status,
                stage_sort=args.stage_sort,
                group_by=args.group_by,
                limit=args.limit,
                offset=args.offset,
            )
    finally:
        conn.close()

    if args.columns and args.output_format == "json":
        raise SystemExit("[ERROR] --columns currently requires --output-format csv|tsv")
    if args.output_format == "json":
        rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    elif args.list_entity:
        rendered = render_entity_delimited(
            result,
            output_format=args.output_format,
            columns_arg=args.columns,
        )
    else:
        rendered = render_delimited(
            result,
            group_by=args.group_by,
            output_format=args.output_format,
            columns_arg=args.columns,
        )
    if args.output_file:
        output_path = Path(args.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
