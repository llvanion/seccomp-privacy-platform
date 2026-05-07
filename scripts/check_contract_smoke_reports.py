#!/usr/bin/env python3
import argparse
import csv
import io
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.load(path.open("r", encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    records.append(payload)
    return records


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


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


def require_mainline_summary_counts(payload: dict[str, Any], *, label: str, expected_job_count: int) -> None:
    counts = payload.get("mainline_contract_summary_counts") or {}
    require(counts.get("job_count") == expected_job_count, f"{label} returned wrong mainline summary job_count: {payload}")
    embedded = counts.get("embedded_in_audit_chain") or {}
    require(
        embedded.get("true") == expected_job_count and embedded.get("false") == 0 and embedded.get("unknown") == 0,
        f"{label} returned invalid embedded mainline summary counts: {payload}",
    )
    handoff = counts.get("handoff_cleanup") or {}
    require(
        ((handoff.get("server") or {}).get("removed") == expected_job_count)
        and ((handoff.get("client") or {}).get("cleaned") == expected_job_count),
        f"{label} returned invalid handoff cleanup counts: {payload}",
    )
    service_consistency = counts.get("service_audit_consistency") or {}
    require(
        ((service_consistency.get("server") or {}).get("not_applicable") == expected_job_count)
        and ((service_consistency.get("client") or {}).get("ok") == expected_job_count)
        and service_consistency.get("error_count_total") == 0,
        f"{label} returned invalid service audit consistency counts: {payload}",
    )


def validate_audit_bundle(tmp_dir: Path) -> None:
    direct = load(tmp_dir / "audit_bundle_verify_direct.json")
    archive = load(tmp_dir / "audit_bundle_verify_archive.json")

    require(
        direct.get("schema") == "audit_bundle_verification/v1" and direct.get("verified") is True,
        f"direct audit bundle verification failed: {direct}",
    )
    require(
        archive.get("schema") == "audit_bundle_verification/v1" and archive.get("verified") is True,
        f"archived audit bundle verification failed: {archive}",
    )
    require(archive.get("archive_index_verified") is True, f"archive index was not verified: {archive}")
    require(archive.get("anchor_log_verified") is True, f"archive anchor log was not verified: {archive}")
    require(archive.get("anchor_signature_verified") is None or archive.get("anchor_signature_verified") is True,
            f"archive anchor signature status is invalid: {archive}")

    for payload in (direct, archive):
        mainline = payload.get("mainline_contract_summary") or {}
        require(
            mainline.get("schema") == "mainline_contract_check/v1",
            f"audit bundle verification missing mainline contract summary: {payload}",
        )
        require(
            mainline.get("status") == "ok" and mainline.get("embedded_in_audit_chain") is True,
            f"audit bundle verification returned invalid mainline summary: {payload}",
        )
        handoff = mainline.get("handoff_cleanup") or {}
        require(
            handoff.get("server") == "removed" and handoff.get("client") == "cleaned",
            f"audit bundle verification returned invalid handoff cleanup summary: {payload}",
        )
        service_consistency = mainline.get("service_audit_consistency") or {}
        require(
            service_consistency.get("server") == "not_applicable"
            and service_consistency.get("client") == "ok"
            and service_consistency.get("error_count") == 0,
            f"audit bundle verification returned invalid service audit consistency summary: {payload}",
        )
    require(direct.get("anchor_log_verified") is False, f"direct audit bundle verification unexpectedly reported anchor log verification: {direct}")
    require(direct.get("anchor_file") is None and direct.get("anchor_entry_sha256") is None,
            f"direct audit bundle verification unexpectedly exposed anchor fields: {direct}")
    require(
        isinstance(archive.get("anchor_file"), str) and archive.get("anchor_file"),
        f"archived audit bundle verification missing anchor_file: {archive}",
    )
    require(
        isinstance(archive.get("anchor_entry_sha256"), str) and len(archive.get("anchor_entry_sha256")) >= 64,
        f"archived audit bundle verification missing anchor_entry_sha256: {archive}",
    )
    archive_tenant_dir = tmp_dir / "audit_archive" / "contract-tenant"
    anchor_log = archive_tenant_dir / "audit_chain_anchor.jsonl"
    index_log = archive_tenant_dir / "audit_chain_index.jsonl"
    require(anchor_log.is_file(), f"audit archive anchor log missing: {anchor_log}")
    require(index_log.is_file(), f"audit archive index log missing: {index_log}")
    anchor_records = load_jsonl(anchor_log)
    index_records = load_jsonl(index_log)
    require(anchor_records and anchor_records[-1].get("tenant_id") == "contract-tenant",
            f"audit archive anchor tenant_id mismatch: {anchor_records[-1] if anchor_records else None}")
    require(index_records and index_records[-1].get("tenant_id") == "contract-tenant",
            f"audit archive index tenant_id mismatch: {index_records[-1] if index_records else None}")

    for name in ("audit_restore/audit_chain.json", "audit_restore/audit_chain.seal.json"):
        require((tmp_dir / name).is_file(), f"restored audit bundle file missing: {tmp_dir / name}")


def validate_metadata_cli(tmp_dir: Path) -> None:
    init_data = load(tmp_dir / "platform_metadata_init.json")
    import_data = load(tmp_dir / "platform_metadata_import.json")
    import_dry_run_data = load(tmp_dir / "platform_metadata_import_dry_run.json")
    import_replay_data = load(tmp_dir / "platform_metadata_import_replay.json")
    import_batch_data = load(tmp_dir / "platform_metadata_import_batch.json")
    portability_data = load(tmp_dir / "platform_metadata_schema_portability.json")
    job_data = load(tmp_dir / "platform_metadata_job.json")
    caller_data = load(tmp_dir / "platform_metadata_caller.json")
    scope_data = load(tmp_dir / "platform_metadata_scope.json")
    stage_data = load(tmp_dir / "platform_metadata_stage.json")
    stage_filtered_data = load(tmp_dir / "platform_metadata_stage_filtered.json")
    group_stage_data = load(tmp_dir / "platform_metadata_group_stage.json")
    group_status_data = load(tmp_dir / "platform_metadata_group_status.json")
    tenants_data = load(tmp_dir / "platform_metadata_tenants.json")
    services_data = load(tmp_dir / "platform_metadata_services.json")
    policies_data = load(tmp_dir / "platform_metadata_policies.json")
    policy_bindings_data = load(tmp_dir / "platform_metadata_policy_bindings.json")
    caller_permissions_data = load(tmp_dir / "platform_metadata_caller_permissions.json")
    restore_data = load(tmp_dir / "platform_metadata_restore.json")
    registry_apply_dry_run_data = load(tmp_dir / "platform_registry_apply_dry_run.json")
    registry_apply_data = load(tmp_dir / "platform_registry_apply.json")
    registry_apply_reconcile_data = load(tmp_dir / "platform_registry_apply_reconcile.json")
    registry_policies_data = load(tmp_dir / "platform_registry_policies.json")
    registry_caller_permissions_data = load(tmp_dir / "platform_registry_caller_permissions.json")
    registry_key_refs_data = load(tmp_dir / "platform_registry_key_refs.json")
    registry_key_versions_data = load(tmp_dir / "platform_registry_key_versions.json")
    registry_authz_tuples_data = load(tmp_dir / "platform_registry_authz_tuples.json")

    imported = import_data.get("imported") or {}
    for required_migration in {"001_init.sql", "002_add_stage_duration_columns.sql", "003_add_caller_identities.sql", "004_add_key_registry.sql"}:
        require(
            required_migration in init_data.get("applied_migrations", []),
            f"metadata init did not apply {required_migration}: {init_data}",
        )
    require(import_data.get("schema") == "metadata_import_report/v1", f"unexpected metadata import report schema: {import_data}")
    require(import_data.get("mode") == "apply", f"unexpected metadata import mode: {import_data}")
    require((import_data.get("summary") or {}).get("inserted_job_count") == 1, f"unexpected metadata import summary: {import_data}")
    require(imported.get("job_id") == "contract-check", f"unexpected imported job metadata: {import_data}")
    initial_import_entry = (import_data.get("imports") or [{}])[0]
    require(initial_import_entry.get("action") == "insert", f"unexpected metadata initial import action: {import_data}")
    require((initial_import_entry.get("existing_job") or {}).get("exists") is False, f"unexpected metadata existing-job snapshot on initial import: {import_data}")
    require((initial_import_entry.get("job_state_after") or {}).get("exists") is True, f"unexpected metadata post-import snapshot: {import_data}")

    require(import_dry_run_data.get("schema") == "metadata_import_report/v1", f"unexpected metadata dry-run report schema: {import_dry_run_data}")
    require(import_dry_run_data.get("mode") == "dry_run", f"unexpected metadata dry-run mode: {import_dry_run_data}")
    require((import_dry_run_data.get("summary") or {}).get("replaced_job_count") == 1, f"unexpected metadata dry-run summary: {import_dry_run_data}")
    dry_run_entry = (import_dry_run_data.get("imports") or [{}])[0]
    require(dry_run_entry.get("action") == "replace", f"unexpected metadata dry-run action: {import_dry_run_data}")
    require((dry_run_entry.get("existing_job") or {}).get("exists") is True, f"unexpected metadata dry-run existing-job snapshot: {import_dry_run_data}")
    require(dry_run_entry.get("result") is None and dry_run_entry.get("imported_at_utc") is None, f"metadata dry-run unexpectedly mutated state: {import_dry_run_data}")

    require(import_replay_data.get("schema") == "metadata_import_report/v1", f"unexpected metadata replay report schema: {import_replay_data}")
    require(import_replay_data.get("mode") == "apply", f"unexpected metadata replay mode: {import_replay_data}")
    require((import_replay_data.get("summary") or {}).get("replaced_job_count") == 1, f"unexpected metadata replay summary: {import_replay_data}")
    replay_entry = (import_replay_data.get("imports") or [{}])[0]
    require(replay_entry.get("action") == "replace", f"unexpected metadata replay action: {import_replay_data}")
    require((replay_entry.get("existing_job") or {}).get("exists") is True, f"unexpected metadata replay existing-job snapshot: {import_replay_data}")
    require((replay_entry.get("job_state_after") or {}).get("exists") is True, f"unexpected metadata replay post-import snapshot: {import_replay_data}")

    require(import_batch_data.get("schema") == "metadata_import_report/v1", f"unexpected metadata batch report schema: {import_batch_data}")
    require(import_batch_data.get("mode") == "dry_run", f"unexpected metadata batch report mode: {import_batch_data}")
    require((import_batch_data.get("summary") or {}).get("processed_run_count") == 1, f"unexpected metadata batch report summary: {import_batch_data}")
    batch_entry = (import_batch_data.get("imports") or [{}])[0]
    require(batch_entry.get("action") == "replace", f"unexpected metadata batch import action: {import_batch_data}")
    require(isinstance(batch_entry.get("out_base"), str) and batch_entry.get("out_base"), f"unexpected metadata batch import out_base: {import_batch_data}")

    require(portability_data.get("schema") == "metadata_schema_portability/v1", f"unexpected metadata portability schema: {portability_data}")
    require(portability_data.get("status") == "ok", f"metadata portability check failed: {portability_data}")
    portability_summary = portability_data.get("summary") or {}
    require(portability_summary.get("sqlite_only_construct_count") == 0, f"metadata portability check found SQLite-only constructs: {portability_data}")
    portability_checks = {item.get("name"): item for item in portability_data.get("checks", [])}
    for required_check in ("sqlite_only_constructs", "expected_indexes_present", "foreign_key_targets_present"):
        require((portability_checks.get(required_check) or {}).get("status") == "ok", f"metadata portability check {required_check} failed: {portability_data}")
    require(
        restore_data.get("schema") == "metadata_db_restore/v1" and restore_data.get("status") == "ok",
        f"unexpected metadata restore report schema/status: {restore_data}",
    )
    require(
        restore_data.get("used_sqlite_backup_api") is True,
        f"metadata restore did not report SQLite backup API usage: {restore_data}",
    )
    restored_status = restore_data.get("restored_status") or {}
    require(
        restored_status.get("schema") == "metadata_db_status/v1",
        f"metadata restore missing restored_status payload: {restore_data}",
    )
    require(
        ((restored_status.get("summary") or {}).get("job_count")) == 1,
        f"metadata restore returned wrong restored job_count: {restore_data}",
    )

    job = job_data.get("job") or {}
    require(job.get("job_id") == "contract-check", f"job lookup returned wrong job: {job_data}")
    require(job.get("caller") == "auto_demo", f"job lookup returned wrong caller: {job_data}")
    require(
        job.get("tenant_id") == "contract-tenant" and job.get("dataset_id") == "contract-dataset",
        f"job lookup returned wrong scope: {job_data}",
    )
    require(job.get("service_id") == "contract-recovery-service", f"job lookup returned wrong service_id: {job_data}")
    require(
        job.get("status") == "denied" and job.get("release_reason_code") == "below_k",
        f"job lookup returned wrong release summary: {job_data}",
    )
    require(len(job_data.get("artifacts", [])) >= 8, f"job lookup returned too few artifacts: {job_data}")
    require(
        any(item.get("stage") == "record_recovery_service" for item in job_data.get("stage_status", [])),
        f"job lookup missing record_recovery_service stage: {job_data}",
    )
    stage_status = {item.get("stage"): item for item in job_data.get("stage_status", [])}
    stage_duration_summary = ((job_data.get("timing_summary") or {}).get("stage_duration_summary") or {})
    require(
        (job_data.get("timing_summary") or {}).get("total_stage_duration_ms") not in (None, ""),
        f"job lookup missing total stage duration: {job_data}",
    )
    for expected_stage in {"sse_export", "record_recovery_service", "bridge", "pjc", "policy_release"}:
        require(
            (stage_status.get(expected_stage) or {}).get("duration_ms") not in (None, ""),
            f"job lookup missing stage duration for {expected_stage}: {job_data}",
        )
        require(
            stage_duration_summary.get(expected_stage) not in (None, ""),
            f"job lookup missing timing summary for {expected_stage}: {job_data}",
        )
    require(
        any(item.get("event_type") == "record_recovery_service_request" for item in job_data.get("audit_events", [])),
        f"job lookup missing recovery audit event: {job_data}",
    )
    require(
        any(item.get("stage") == "bridge" and item.get("duration_ms") not in (None, "") for item in job_data.get("audit_events", [])),
        f"job lookup missing bridge audit duration: {job_data}",
    )
    require((job_data.get("audit_chain") or {}).get("path") is not None, f"job lookup missing audit chain: {job_data}")
    require((job_data.get("audit_seal") or {}).get("path") is not None, f"job lookup missing audit seal: {job_data}")
    require_mainline_summary(job_data.get("mainline_contract_summary") or {}, label="metadata job lookup")

    caller_jobs = caller_data.get("jobs") or []
    require(len(caller_jobs) == 1 and caller_jobs[0].get("job_id") == "contract-check", f"caller query returned unexpected jobs: {caller_data}")
    require(caller_jobs[0].get("total_stage_duration_ms") not in (None, ""), f"caller query missing total stage duration: {caller_data}")
    require_mainline_summary(caller_jobs[0].get("mainline_contract_summary") or {}, label="metadata caller query")
    require_mainline_summary_counts(caller_data, label="metadata caller query", expected_job_count=1)
    for expected_stage in {"sse_export", "record_recovery_service", "bridge", "pjc", "policy_release"}:
        require(
            (caller_jobs[0].get("stage_duration_summary") or {}).get(expected_stage) not in (None, ""),
            f"caller query missing stage duration summary for {expected_stage}: {caller_data}",
        )

    scope_jobs = scope_data.get("jobs") or []
    require(
        len(scope_jobs) == 1 and scope_jobs[0].get("service_id") == "contract-recovery-service",
        f"scope query returned unexpected jobs: {scope_data}",
    )
    require(scope_jobs[0].get("total_stage_duration_ms") not in (None, ""), f"scope query missing total stage duration: {scope_data}")
    require_mainline_summary(scope_jobs[0].get("mainline_contract_summary") or {}, label="metadata scope query")
    require_mainline_summary_counts(scope_data, label="metadata scope query", expected_job_count=1)

    stage_jobs = stage_data.get("jobs") or []
    require((stage_data.get("filters") or {}).get("stage") == "bridge", f"stage query did not preserve stage filter: {stage_data}")
    require(len(stage_jobs) == 1 and stage_jobs[0].get("job_id") == "contract-check", f"stage query returned unexpected jobs: {stage_data}")
    require_mainline_summary(stage_jobs[0].get("mainline_contract_summary") or {}, label="metadata stage query")
    require_mainline_summary_counts(stage_data, label="metadata stage query", expected_job_count=1)
    matched_stage = stage_jobs[0].get("matched_stage") or {}
    require(
        matched_stage.get("stage") == "bridge" and matched_stage.get("duration_ms") not in (None, ""),
        f"stage query missing matched_stage bridge duration: {stage_data}",
    )
    stage_summary = stage_data.get("stage_summary") or {}
    require(
        stage_summary.get("stage") == "bridge" and stage_summary.get("matched_job_count") == 1,
        f"stage query returned wrong stage summary identity: {stage_data}",
    )
    duration_summary = stage_summary.get("duration_ms") or {}
    require(
        duration_summary.get("count") == 1 and duration_summary.get("total") not in (None, ""),
        f"stage query missing duration summary stats: {stage_data}",
    )
    require(stage_summary.get("status_counts"), f"stage query missing status counts: {stage_data}")

    stage_filtered_jobs = stage_filtered_data.get("jobs") or []
    stage_filtered_filters = stage_filtered_data.get("filters") or {}
    require(
        stage_filtered_filters.get("stage") == "bridge" and stage_filtered_filters.get("stage_status") == "allow",
        f"stage filtered query did not preserve filters: {stage_filtered_data}",
    )
    require(
        stage_filtered_filters.get("stage_sort") == "duration_desc",
        f"stage filtered query did not preserve sort: {stage_filtered_data}",
    )
    require(
        len(stage_filtered_jobs) == 1 and stage_filtered_jobs[0].get("job_id") == "contract-check",
        f"stage filtered query returned unexpected jobs: {stage_filtered_data}",
    )
    require_mainline_summary(stage_filtered_jobs[0].get("mainline_contract_summary") or {}, label="metadata stage filtered query")
    require_mainline_summary_counts(stage_filtered_data, label="metadata stage filtered query", expected_job_count=1)
    matched_stage = stage_filtered_jobs[0].get("matched_stage") or {}
    require(
        matched_stage.get("stage") == "bridge" and matched_stage.get("status") == "allow",
        f"stage filtered query returned wrong matched stage: {stage_filtered_data}",
    )
    require(
        matched_stage.get("duration_ms") not in (None, ""),
        f"stage filtered query missing matched stage duration: {stage_filtered_data}",
    )
    require(
        ((stage_filtered_data.get("stage_summary") or {}).get("status_counts") or {}).get("allow") == 1,
        f"stage filtered query missing allow status count: {stage_filtered_data}",
    )

    group_stage_filters = group_stage_data.get("filters") or {}
    require(group_stage_filters.get("group_by") == "stage", f"group-by stage query did not preserve group_by: {group_stage_data}")
    require_mainline_summary_counts(group_stage_data, label="metadata grouped-stage query", expected_job_count=1)
    group_stage_rows = group_stage_data.get("grouped_stage_summary") or []
    require(len(group_stage_rows) >= 5, f"group-by stage query returned too few stage summaries: {group_stage_data}")
    group_stage_by_name = {item.get("stage"): item for item in group_stage_rows}
    bridge_group = group_stage_by_name.get("bridge") or {}
    require(bridge_group.get("matched_job_count") == 1, f"group-by stage query missing bridge matched job count: {group_stage_data}")
    require((bridge_group.get("status_counts") or {}).get("allow") == 1, f"group-by stage query missing bridge allow count: {group_stage_data}")
    require_mainline_summary_counts(bridge_group, label="metadata grouped-stage bridge bucket", expected_job_count=1)
    require(((bridge_group.get("duration_ms") or {}).get("total")) not in (None, ""), f"group-by stage query missing bridge duration total: {group_stage_data}")
    policy_group = group_stage_by_name.get("policy_release") or {}
    require((policy_group.get("status_counts") or {}).get("deny") == 1, f"group-by stage query missing policy_release deny count: {group_stage_data}")
    require_mainline_summary_counts(policy_group, label="metadata grouped-stage policy bucket", expected_job_count=1)

    group_status_filters = group_status_data.get("filters") or {}
    require(group_status_filters.get("group_by") == "status", f"group-by status query did not preserve group_by: {group_status_data}")
    require_mainline_summary_counts(group_status_data, label="metadata grouped-status query", expected_job_count=1)
    group_status_rows = group_status_data.get("grouped_status_summary") or []
    require(len(group_status_rows) == 1, f"group-by status query returned unexpected status groups: {group_status_data}")
    status_row = group_status_rows[0]
    require(
        status_row.get("status") == "denied" and status_row.get("matched_job_count") == 1,
        f"group-by status query returned wrong denied summary: {group_status_data}",
    )
    require((status_row.get("release_reason_counts") or {}).get("below_k") == 1, f"group-by status query missing below_k release reason count: {group_status_data}")
    require_mainline_summary_counts(status_row, label="metadata grouped-status bucket", expected_job_count=1)
    require(((status_row.get("total_stage_duration_ms") or {}).get("total")) not in (None, ""), f"group-by status query missing total stage duration stats: {group_status_data}")

    tenant_rows = tenants_data.get("items") or []
    require(
        tenants_data.get("entity") == "tenants" and tenants_data.get("count") == 1,
        f"tenant entity query returned unexpected envelope: {tenants_data}",
    )
    require(len(tenant_rows) == 1 and tenant_rows[0].get("tenant_id") == "contract-tenant", f"tenant entity query returned unexpected rows: {tenants_data}")
    require(tenant_rows[0].get("job_count") == 1, f"tenant entity query missing job count: {tenants_data}")

    service_rows = services_data.get("items") or []
    require(
        services_data.get("entity") == "services" and services_data.get("count") == 1,
        f"service entity query returned unexpected envelope: {services_data}",
    )
    require(
        len(service_rows) == 1 and service_rows[0].get("service_id") == "contract-recovery-service",
        f"service entity query returned unexpected rows: {services_data}",
    )
    require(service_rows[0].get("job_count") == 1, f"service entity query missing job count: {services_data}")

    policy_rows = policies_data.get("items") or []
    require(
        policies_data.get("entity") == "policies" and bool(policy_rows),
        f"policy entity query returned no rows: {policies_data}",
    )
    export_policy = next((row for row in policy_rows if row.get("schema_name") == "sse_export_policy/v1"), None)
    require(export_policy is not None, f"policy entity query missing imported export policy: {policies_data}")
    require(
        export_policy.get("binding_count") not in (None, "") and export_policy.get("permission_count") not in (None, ""),
        f"policy entity query missing binding/permission counts: {policies_data}",
    )

    policy_binding_rows = policy_bindings_data.get("items") or []
    require(
        policy_bindings_data.get("entity") == "policy-bindings" and bool(policy_binding_rows),
        f"policy binding query returned no rows: {policy_bindings_data}",
    )
    require(
        any(row.get("caller") == "auto_demo" and row.get("binding_kind") == "caller_policy" for row in policy_binding_rows),
        f"policy binding query missing auto_demo binding: {policy_bindings_data}",
    )

    caller_permission_rows = caller_permissions_data.get("items") or []
    require(
        caller_permissions_data.get("entity") == "caller-permissions" and len(caller_permission_rows) >= 5,
        f"caller permission query returned too few rows: {caller_permissions_data}",
    )
    permission_keys = {row.get("permission_key") for row in caller_permission_rows}
    for required_permission in {"tenant_id", "allowed_dataset_ids", "allowed_service_ids", "can_run_bridge", "can_release"}:
        require(required_permission in permission_keys, f"caller permission query missing {required_permission}: {caller_permissions_data}")
    permission_summary = caller_permissions_data.get("permission_summary") or {}
    require(permission_summary.get("caller_count") == 1, f"caller permission query returned wrong caller_count summary: {caller_permissions_data}")
    require(permission_summary.get("callers") == ["auto_demo"], f"caller permission query returned wrong caller summary: {caller_permissions_data}")
    require(permission_summary.get("tenant_ids") == ["contract-tenant"], f"caller permission query returned wrong tenant summary: {caller_permissions_data}")
    require(permission_summary.get("allowed_dataset_ids") == ["contract-dataset"], f"caller permission query returned wrong dataset summary: {caller_permissions_data}")
    require(permission_summary.get("allowed_service_ids") == ["contract-recovery-service"], f"caller permission query returned wrong service summary: {caller_permissions_data}")
    require(((permission_summary.get("enabled_counts") or {}).get("true")) == 1, f"caller permission query returned wrong enabled summary: {caller_permissions_data}")
    platform_role_counts = permission_summary.get("platform_role_counts") or {}
    require(platform_role_counts.get("query_submitter") == 1, f"caller permission query missing query_submitter role: {caller_permissions_data}")
    require(platform_role_counts.get("privacy_operator") == 1, f"caller permission query missing privacy_operator role: {caller_permissions_data}")
    callers_by_platform_role = permission_summary.get("callers_by_platform_role") or {}
    require((callers_by_platform_role.get("query_submitter") or []) == ["auto_demo"], f"caller permission query returned wrong role caller map: {caller_permissions_data}")
    access_profiles = permission_summary.get("access_profiles") or []
    require(len(access_profiles) == 1 and access_profiles[0].get("caller") == "auto_demo", f"caller permission query returned wrong access profiles: {caller_permissions_data}")
    require(access_profiles[0].get("access_profile") == "commerce_ops_owner", f"caller permission query returned wrong access profile: {caller_permissions_data}")
    permission_flags = permission_summary.get("permissions") or {}
    for required_true in {"can_run_bridge", "can_run_pjc", "can_release", "can_use_record_recovery_service"}:
        require(
            ((permission_flags.get(required_true) or {}).get("true")) == 1,
            f"caller permission query returned wrong {required_true} summary: {caller_permissions_data}",
        )

    require(
        registry_apply_dry_run_data.get("schema") == "metadata_registry_apply_report/v1",
        f"unexpected registry apply dry-run schema: {registry_apply_dry_run_data}",
    )
    require(
        registry_apply_dry_run_data.get("mode") == "dry_run" and (registry_apply_dry_run_data.get("validation") or {}).get("status") == "ok",
        f"unexpected registry apply dry-run envelope: {registry_apply_dry_run_data}",
    )
    dry_run_summary = registry_apply_dry_run_data.get("summary") or {}
    require(
        (dry_run_summary.get("requested_counts") or {}).get("policies") == 1,
        f"registry apply dry-run returned wrong requested policy count: {registry_apply_dry_run_data}",
    )
    require(
        (dry_run_summary.get("requested_counts") or {}).get("key_refs") == 2
        and (dry_run_summary.get("requested_counts") or {}).get("key_versions") == 2
        and (dry_run_summary.get("requested_counts") or {}).get("issuer_registry") == 2,
        f"registry apply dry-run returned wrong key registry requested counts: {registry_apply_dry_run_data}",
    )
    require(
        ((dry_run_summary.get("entity_action_counts") or {}).get("insert")) == 21,
        f"registry apply dry-run returned wrong insert count: {registry_apply_dry_run_data}",
    )
    require(
        ((dry_run_summary.get("policy_action_counts") or {}).get("insert")) == 1,
        f"registry apply dry-run returned wrong policy insert count: {registry_apply_dry_run_data}",
    )
    require(
        all(item.get("state_after") is None for rows in (registry_apply_dry_run_data.get("entities") or {}).values() for item in rows),
        f"registry apply dry-run unexpectedly returned state_after rows: {registry_apply_dry_run_data}",
    )

    require(
        registry_apply_data.get("schema") == "metadata_registry_apply_report/v1",
        f"unexpected registry apply schema: {registry_apply_data}",
    )
    require(
        registry_apply_data.get("mode") == "apply",
        f"unexpected registry apply mode: {registry_apply_data}",
    )
    apply_summary = registry_apply_data.get("summary") or {}
    require(
        ((apply_summary.get("entity_action_counts") or {}).get("insert")) == 21,
        f"registry apply returned wrong entity insert count: {registry_apply_data}",
    )
    require(
        ((apply_summary.get("policy_action_counts") or {}).get("insert")) == 1,
        f"registry apply returned wrong policy insert count: {registry_apply_data}",
    )
    apply_policy = (registry_apply_data.get("policies") or [{}])[0]
    require(
        (apply_policy.get("state_after") or {}).get("binding_count") == 5,
        f"registry apply returned wrong policy binding count: {registry_apply_data}",
    )
    require(
        (apply_policy.get("state_after") or {}).get("permission_count", 0) >= 5,
        f"registry apply returned wrong policy permission count: {registry_apply_data}",
    )
    apply_key_refs = (registry_apply_data.get("entities") or {}).get("key_refs") or []
    require(
        len(apply_key_refs) == 2,
        f"registry apply returned wrong key_ref count: {registry_apply_data}",
    )
    apply_issuer_registry = (registry_apply_data.get("entities") or {}).get("issuer_registry") or []
    require(
        len(apply_issuer_registry) == 2,
        f"registry apply returned wrong issuer_registry count: {registry_apply_data}",
    )
    require(
        any(
            (item.get("state_after") or {}).get("backend_kind") == "local_keyring"
            and (item.get("state_after") or {}).get("active_version") == "demo-v1"
            for item in apply_key_refs
        ),
        f"registry apply returned wrong key_ref state: {registry_apply_data}",
    )

    require(
        registry_apply_reconcile_data.get("schema") == "metadata_registry_apply_report/v1",
        f"unexpected registry reconcile schema: {registry_apply_reconcile_data}",
    )
    require(
        registry_apply_reconcile_data.get("mode") == "dry_run",
        f"unexpected registry reconcile mode: {registry_apply_reconcile_data}",
    )
    reconcile_summary = registry_apply_reconcile_data.get("summary") or {}
    require(
        ((reconcile_summary.get("entity_action_counts") or {}).get("noop")) == 21,
        f"registry reconcile returned wrong entity noop count: {registry_apply_reconcile_data}",
    )
    require(
        ((reconcile_summary.get("policy_action_counts") or {}).get("noop")) == 1,
        f"registry reconcile returned wrong policy noop count: {registry_apply_reconcile_data}",
    )

    registry_policy_rows = registry_policies_data.get("items") or []
    require(
        registry_policies_data.get("entity") == "policies" and len(registry_policy_rows) == 1,
        f"registry policy query returned unexpected envelope: {registry_policies_data}",
    )
    require(
        registry_policy_rows[0].get("schema_name") == "sse_export_policy/v1",
        f"registry policy query returned wrong schema: {registry_policies_data}",
    )
    require(
        registry_policy_rows[0].get("binding_count") == 5,
        f"registry policy query returned wrong binding count: {registry_policies_data}",
    )

    registry_permission_rows = registry_caller_permissions_data.get("items") or []
    require(
        registry_caller_permissions_data.get("entity") == "caller-permissions" and len(registry_permission_rows) >= 5,
        f"registry caller-permissions query returned too few rows: {registry_caller_permissions_data}",
    )
    registry_permission_summary = registry_caller_permissions_data.get("permission_summary") or {}
    require(
        registry_permission_summary.get("callers") == ["commerce_ops_demo"],
        f"registry caller-permissions query returned wrong caller summary: {registry_caller_permissions_data}",
    )
    require(
        registry_permission_summary.get("allowed_service_ids") == ["orders-recovery"],
        f"registry caller-permissions query returned wrong service summary: {registry_caller_permissions_data}",
    )
    registry_key_ref_rows = registry_key_refs_data.get("items") or []
    require(
        registry_key_refs_data.get("entity") == "key-refs" and len(registry_key_ref_rows) == 2,
        f"registry key-refs query returned unexpected envelope: {registry_key_refs_data}",
    )
    key_ref_names = {item.get("key_name") for item in registry_key_ref_rows}
    require(
        key_ref_names == {"bridge-token", "audit-integrity"},
        f"registry key-refs query returned wrong key names: {registry_key_refs_data}",
    )
    bridge_key_ref = next((item for item in registry_key_ref_rows if item.get("key_name") == "bridge-token"), None)
    require(
        bridge_key_ref is not None
        and bridge_key_ref.get("backend_kind") == "local_keyring"
        and sorted(bridge_key_ref.get("allowed_callers") or []) == ["commerce_ops_demo", "recovery_ops_demo"],
        f"registry key-refs query returned wrong bridge-token row: {registry_key_refs_data}",
    )
    registry_key_version_rows = registry_key_versions_data.get("items") or []
    require(
        registry_key_versions_data.get("entity") == "key-versions" and len(registry_key_version_rows) == 1,
        f"registry key-versions query returned unexpected envelope: {registry_key_versions_data}",
    )
    bridge_key_version = registry_key_version_rows[0]
    require(
        bridge_key_version.get("key_name") == "bridge-token"
        and bridge_key_version.get("version") == "demo-v1"
        and bridge_key_version.get("enabled") is True
        and bridge_key_version.get("status") == "active"
        and bridge_key_version.get("secret_ref_kind") == "env"
        and bridge_key_version.get("secret_ref_name") == "BRIDGE_TOKEN_SECRET",
        f"registry key-versions query returned wrong bridge-token version row: {registry_key_versions_data}",
    )

    registry_authz_summary = registry_authz_tuples_data.get("summary") or {}
    require(
        registry_authz_tuples_data.get("schema") == "authz_tuple_export/v1",
        f"unexpected registry authz tuple schema: {registry_authz_tuples_data}",
    )
    require(
        registry_authz_summary.get("subject_count") == 5
        and registry_authz_summary.get("active_subject_count") == 3
        and registry_authz_summary.get("disabled_subject_count") == 2,
        f"registry authz tuple export returned wrong subject counts: {registry_authz_tuples_data}",
    )
    require(
        ((registry_authz_summary.get("subject_type_counts") or {}).get("service_account")) == 1,
        f"registry authz tuple export returned wrong service_account count: {registry_authz_tuples_data}",
    )
    require(
        any(item.get("subject") == "service_account:recovery_ops_demo" for item in registry_authz_tuples_data.get("subjects", [])),
        f"registry authz tuple export missing recovery_ops_demo subject: {registry_authz_tuples_data}",
    )


def validate_metadata_tabular_exports(tmp_dir: Path) -> None:
    stage_text = (tmp_dir / "platform_metadata_group_stage.tsv").read_text(encoding="utf-8")
    status_text = (tmp_dir / "platform_metadata_group_status.csv").read_text(encoding="utf-8")
    stage_columns_text = (tmp_dir / "platform_metadata_group_stage_columns.tsv").read_text(encoding="utf-8")
    status_file_text = (tmp_dir / "platform_metadata_group_status.out.csv").read_text(encoding="utf-8")
    status_stdout_text = (tmp_dir / "platform_metadata_group_status.stdout").read_text(encoding="utf-8")

    stage_rows = list(csv.DictReader(io.StringIO(stage_text), delimiter="\t"))
    require(len(stage_rows) >= 5, f"stage TSV export returned too few rows: {stage_text}")
    bridge_row = next((row for row in stage_rows if row.get("stage") == "bridge"), None)
    require(bridge_row is not None and bridge_row.get("duration_total") not in ("", None), f"stage TSV export missing bridge duration_total: {stage_text}")
    require(bool(bridge_row.get("status_counts")), f"stage TSV export missing bridge status_counts: {stage_text}")
    require(bridge_row.get("handoff_cleanup_server_removed") == "1", f"stage TSV export missing server removed count: {stage_text}")
    require(bridge_row.get("service_audit_consistency_client_ok") == "1", f"stage TSV export missing client ok count: {stage_text}")

    status_rows = list(csv.DictReader(io.StringIO(status_text)))
    require(len(status_rows) == 1, f"status CSV export returned unexpected rows: {status_text}")
    status_row = status_rows[0]
    require(status_row.get("status") == "denied", f"status CSV export returned wrong status: {status_text}")
    require(status_row.get("duration_total") not in ("", None), f"status CSV export missing duration_total: {status_text}")
    require("below_k" in (status_row.get("release_reason_counts") or ""), f"status CSV export missing below_k release reason: {status_text}")
    require(status_row.get("handoff_cleanup_server_removed") == "1", f"status CSV export missing server removed count: {status_text}")
    require(status_row.get("service_audit_consistency_client_ok") == "1", f"status CSV export missing client ok count: {status_text}")

    stage_column_rows = list(csv.DictReader(io.StringIO(stage_columns_text), delimiter="\t"))
    require(bool(stage_column_rows), f"stage TSV column export returned no rows: {stage_columns_text}")
    require(set(stage_column_rows[0].keys()) == {"stage", "duration_total"}, f"stage TSV column export returned wrong columns: {stage_columns_text}")

    status_file_rows = list(csv.DictReader(io.StringIO(status_file_text)))
    require(len(status_file_rows) == 1, f"status CSV output-file export returned unexpected rows: {status_file_text}")
    require(set(status_file_rows[0].keys()) == {"status", "duration_total"}, f"status CSV output-file export returned wrong columns: {status_file_text}")
    require(status_stdout_text == "", f"status CSV output-file export unexpectedly wrote stdout: {status_stdout_text!r}")


def validate_repo_hygiene(tmp_dir: Path) -> None:
    scan = load(tmp_dir / "repo_hygiene_scan.json")
    require(scan.get("schema") == "repo_hygiene_scan/v1", f"unexpected repo hygiene scan schema: {scan}")
    require((scan.get("summary") or {}).get("error", 0) == 0, f"repo hygiene scan found high-confidence secret errors: {scan}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Validate non-benchmark contract smoke reports materialized by check_json_contracts.sh.")
    ap.add_argument("--tmp-dir", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    tmp_dir = Path(args.tmp_dir).resolve()
    require(tmp_dir.is_dir(), f"tmp dir does not exist: {tmp_dir}")
    validate_audit_bundle(tmp_dir)
    validate_metadata_cli(tmp_dir)
    validate_metadata_tabular_exports(tmp_dir)
    validate_repo_hygiene(tmp_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
