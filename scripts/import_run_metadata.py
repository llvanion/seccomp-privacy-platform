#!/usr/bin/env python3
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import apply_migrations, connect_db, file_format, row_to_dict, sha256_file, utc_now  # noqa: E402
from scripts.metadata_registry import apply_policy_plan, plan_policy_file  # noqa: E402


IMPORT_SCHEMA = "metadata_import_report/v1"
ARTIFACT_TYPE_STAGE_MAP = {
    "sse_export_audit": "sse_export",
    "record_recovery_service_audit": "record_recovery_service",
    "record_recovery_service_health": "record_recovery_service",
    "record_recovery_service_config": "record_recovery_service",
    "bridge_job_meta": "bridge",
    "bridge_audit": "bridge",
    "pjc_audit": "pjc",
    "public_report": "policy_release",
    "policy_audit": "policy_release",
    "privacy_budget_ledger": "policy_release",
    "audit_chain": "audit",
    "audit_seal": "audit",
    "key_access_audit": "key_access",
}
JOB_DEPENDENT_TABLES = (
    "job_artifacts",
    "job_stage_status",
    "audit_events",
    "audit_chains",
    "audit_seals",
    "privacy_budget_ledger_events",
    "key_access_events",
)


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError(f"{path} contains a non-object JSONL record")
            records.append(data)
    return records


def optional_json(path: Path) -> dict | None:
    return load_json(path) if path.is_file() else None


def optional_jsonl(path: Path) -> list[dict]:
    return load_jsonl(path) if path.is_file() else []


def first_existing_path(*paths: Path) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def first_nonempty(*values):
    for value in values:
        if value not in (None, "", []):
            return value
    return None


def optional_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def optional_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def record_ts_utc_string(record: dict) -> str | None:
    ts_utc = first_nonempty(record.get("ts_utc"), record.get("generated_at_utc"))
    if ts_utc:
        return str(ts_utc)
    unix_ms = optional_int(record.get("ts_unix_ms"))
    if unix_ms is None:
        return None
    return datetime.fromtimestamp(unix_ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def infer_job_id(bundle: dict) -> str:
    candidates = [
        bundle["audit_chain"].get("job_id") if bundle["audit_chain"] else None,
        bundle["public_report"].get("job_id") if bundle["public_report"] else None,
        bundle["bridge_job_meta"].get("job_id") if bundle["bridge_job_meta"] else None,
        bundle["policy_audit"][0].get("job_id") if bundle["policy_audit"] else None,
        bundle["sse_export_audit"][0].get("job_id") if bundle["sse_export_audit"] else None,
    ]
    job_id = first_nonempty(*candidates)
    if not job_id:
        raise ValueError(f"could not infer job_id from {bundle['out_base']}")
    return str(job_id)


def infer_correlation_id(bundle: dict, job_id: str) -> str:
    correlation_id = first_nonempty(
        bundle["audit_chain"].get("correlation_id") if bundle["audit_chain"] else None,
        bundle["public_report"].get("correlation_id") if bundle["public_report"] else None,
        bundle["policy_audit"][0].get("correlation_id") if bundle["policy_audit"] else None,
        bundle["sse_export_audit"][0].get("correlation_id") if bundle["sse_export_audit"] else None,
        job_id,
    )
    return str(correlation_id)


def infer_scope(bundle: dict) -> tuple[str | None, str | None, str | None, str | None]:
    service_config = bundle["record_recovery_service_config"] or {}
    health = bundle["record_recovery_service_health"] or {}
    service_audit = bundle["record_recovery_service_audit"]
    policy_audit = bundle["policy_audit"]
    public_report = bundle["public_report"] or {}
    sse_export = bundle["sse_export_audit"]

    caller = first_nonempty(
        public_report.get("caller"),
        policy_audit[0].get("caller") if policy_audit else None,
        sse_export[0].get("caller") if sse_export else None,
        service_audit[0].get("caller") if service_audit else None,
    )
    tenant_id = first_nonempty(
        service_config.get("tenant_id"),
        health.get("tenant_id"),
        service_audit[0].get("tenant_id") if service_audit else None,
        sse_export[0].get("tenant_id") if sse_export else None,
    )
    dataset_id = first_nonempty(
        service_config.get("dataset_id"),
        health.get("dataset_id"),
        service_audit[0].get("dataset_id") if service_audit else None,
        sse_export[0].get("dataset_id") if sse_export else None,
    )
    service_id = first_nonempty(
        service_config.get("service_id"),
        health.get("service_id"),
        service_audit[0].get("service_id") if service_audit else None,
        sse_export[0].get("service_id") if sse_export else None,
    )
    return (
        str(caller) if caller else None,
        str(tenant_id) if tenant_id else None,
        str(dataset_id) if dataset_id else None,
        str(service_id) if service_id else None,
    )


def read_bundle(out_base: Path) -> dict:
    privacy_budget_ledger_path = first_existing_path(
        out_base / "a_psi_run" / "privacy_budget_ledger.jsonl",
        out_base / "privacy_budget_ledger.jsonl",
    )
    return {
        "out_base": out_base.resolve(),
        "audit_chain": optional_json(out_base / "audit_chain.json"),
        "audit_seal": optional_json(out_base / "audit_chain.seal.json"),
        "public_report": optional_json(out_base / "a_psi_run" / "public_report.json"),
        "bridge_job_meta": optional_json(out_base / "bridge_job" / "job_meta.json"),
        "record_recovery_service_config": optional_json(out_base / "sse_exports" / "record_recovery_service_config.json"),
        "record_recovery_service_health": optional_json(out_base / "sse_exports" / "record_recovery_service_health.json"),
        "sse_export_audit": optional_jsonl(out_base / "sse_exports" / "export_audit.jsonl"),
        "record_recovery_service_audit": optional_jsonl(out_base / "sse_exports" / "record_recovery_service_audit.jsonl"),
        "bridge_audit": optional_jsonl(out_base / "bridge_job" / "bridge_audit.jsonl"),
        "pjc_audit": optional_jsonl(out_base / "a_psi_run" / "pjc_audit.jsonl"),
        "policy_audit": optional_jsonl(out_base / "a_psi_run" / "audit_log.jsonl"),
        "privacy_budget_ledger_path": privacy_budget_ledger_path,
        "privacy_budget_ledger": optional_jsonl(privacy_budget_ledger_path) if privacy_budget_ledger_path else [],
        "key_access_audit": optional_jsonl(out_base / "key_access_audit.jsonl"),
    }


def referenced_policy_paths(bundle: dict) -> list[str]:
    paths: set[str] = set()
    for record in bundle["sse_export_audit"]:
        policy_path = record.get("policy_config")
        if isinstance(policy_path, str) and policy_path:
            paths.add(policy_path)
    for record in bundle["record_recovery_service_audit"]:
        policy_path = record.get("authz_policy_config")
        if isinstance(policy_path, str) and policy_path:
            paths.add(policy_path)
    config = bundle["record_recovery_service_config"] or {}
    if isinstance(config.get("authz_config"), str) and config.get("authz_config"):
        paths.add(str(config["authz_config"]))
    return sorted(paths)


def import_artifact_map(bundle: dict) -> dict[str, Path]:
    artifacts = {
        "sse_export_audit": bundle["out_base"] / "sse_exports" / "export_audit.jsonl",
        "record_recovery_service_audit": bundle["out_base"] / "sse_exports" / "record_recovery_service_audit.jsonl",
        "record_recovery_service_health": bundle["out_base"] / "sse_exports" / "record_recovery_service_health.json",
        "record_recovery_service_config": bundle["out_base"] / "sse_exports" / "record_recovery_service_config.json",
        "bridge_job_meta": bundle["out_base"] / "bridge_job" / "job_meta.json",
        "bridge_audit": bundle["out_base"] / "bridge_job" / "bridge_audit.jsonl",
        "pjc_audit": bundle["out_base"] / "a_psi_run" / "pjc_audit.jsonl",
        "public_report": bundle["out_base"] / "a_psi_run" / "public_report.json",
        "policy_audit": bundle["out_base"] / "a_psi_run" / "audit_log.jsonl",
        "audit_chain": bundle["out_base"] / "audit_chain.json",
        "audit_seal": bundle["out_base"] / "audit_chain.seal.json",
        "key_access_audit": bundle["out_base"] / "key_access_audit.jsonl",
    }
    if bundle.get("privacy_budget_ledger_path"):
        artifacts["privacy_budget_ledger"] = bundle["privacy_budget_ledger_path"]
    return artifacts


def incoming_summary(bundle: dict) -> dict[str, Any]:
    artifact_map = import_artifact_map(bundle)
    stage_record_counts = {
        "sse_export": len(bundle["sse_export_audit"]),
        "record_recovery_service": len(bundle["record_recovery_service_audit"]),
        "bridge": len(bundle["bridge_audit"]),
        "pjc": len(bundle["pjc_audit"]),
        "policy_release": len(bundle["policy_audit"]),
        "privacy_budget_ledger": len(bundle["privacy_budget_ledger"]),
        "key_access": len(bundle["key_access_audit"]),
    }
    policy_paths = referenced_policy_paths(bundle)
    return {
        "artifact_count_expected": len(artifact_map),
        "artifact_count_existing_on_disk": sum(1 for path in artifact_map.values() if path.exists()),
        "artifact_types": sorted(artifact_map),
        "stage_status_count_expected": len(stage_record_counts),
        "stage_record_counts": stage_record_counts,
        "audit_event_count_expected": sum(stage_record_counts[stage] for stage in ("sse_export", "record_recovery_service", "bridge", "pjc", "policy_release")),
        "key_access_event_count_expected": stage_record_counts["key_access"],
        "policy_reference_count": len(policy_paths),
        "policy_paths": policy_paths,
    }


def upsert_scope_entities(
    conn: sqlite3.Connection,
    *,
    imported_at: str,
    job_id: str,
    caller: str | None,
    tenant_id: str | None,
    dataset_id: str | None,
    service_id: str | None,
    service_config: dict | None,
) -> None:
    if tenant_id:
        conn.execute(
            """
            INSERT INTO tenants(tenant_id, created_at_utc, source, last_seen_job_id)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(tenant_id) DO UPDATE SET
              source=excluded.source,
              last_seen_job_id=excluded.last_seen_job_id
            """,
            (tenant_id, imported_at, "import_run_metadata", job_id),
        )
    if dataset_id:
        conn.execute(
            """
            INSERT INTO datasets(dataset_id, tenant_id, created_at_utc, source, last_seen_job_id)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(dataset_id) DO UPDATE SET
              tenant_id=excluded.tenant_id,
              source=excluded.source,
              last_seen_job_id=excluded.last_seen_job_id
            """,
            (dataset_id, tenant_id, imported_at, "import_run_metadata", job_id),
        )
    if caller:
        conn.execute(
            """
            INSERT INTO callers(caller, tenant_id, created_at_utc, source, last_seen_job_id)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(caller) DO UPDATE SET
              tenant_id=excluded.tenant_id,
              source=excluded.source,
              last_seen_job_id=excluded.last_seen_job_id
            """,
            (caller, tenant_id, imported_at, "import_run_metadata", job_id),
        )
    if service_id:
        transport = first_nonempty(
            service_config.get("transport") if service_config else None,
            "unix_socket" if service_config and service_config.get("socket_path") else None,
            "http" if service_config and service_config.get("endpoint_url") else None,
        )
        config_path = None
        conn.execute(
            """
            INSERT INTO services(service_id, tenant_id, dataset_id, service_type, transport, config_path, created_at_utc, last_seen_job_id)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(service_id) DO UPDATE SET
              tenant_id=excluded.tenant_id,
              dataset_id=excluded.dataset_id,
              service_type=excluded.service_type,
              transport=excluded.transport,
              config_path=excluded.config_path,
              last_seen_job_id=excluded.last_seen_job_id
            """,
            (service_id, tenant_id, dataset_id, "record_recovery", transport, config_path, imported_at, job_id),
        )


def job_summary(bundle: dict) -> tuple[str | None, int | None, int | None, str | None, str | None]:
    public_report = bundle["public_report"] or {}
    policy_audit = bundle["policy_audit"]
    released_payload = public_report.get("released")
    released_metrics = released_payload if isinstance(released_payload, dict) else {}
    released = public_report.get("released")
    if released is True:
        status = "released"
    elif released is False:
        status = "denied"
    else:
        status = first_nonempty(policy_audit[-1].get("decision") if policy_audit else None, "imported")
    reason_code = first_nonempty(
        public_report.get("reason_code"),
        policy_audit[-1].get("reason_code") if policy_audit else None,
    )
    intersection_size = first_nonempty(
        public_report.get("details", {}).get("intersection_size"),
        released_metrics.get("intersection_size"),
        policy_audit[-1].get("parsed_metrics", {}).get("intersection_size") if policy_audit else None,
    )
    intersection_sum = first_nonempty(
        public_report.get("details", {}).get("intersection_sum"),
        released_metrics.get("intersection_sum"),
        policy_audit[-1].get("parsed_metrics", {}).get("intersection_sum") if policy_audit else None,
    )
    created_at = first_nonempty(
        public_report.get("generated_at_utc"),
        bundle["audit_chain"].get("generated_at_utc") if bundle["audit_chain"] else None,
        policy_audit[-1].get("ts_utc") if policy_audit else None,
    )
    return (
        str(status) if status else None,
        int(intersection_size) if intersection_size is not None else None,
        int(intersection_sum) if intersection_sum is not None else None,
        str(reason_code) if reason_code else None,
        str(created_at) if created_at else None,
    )


def replace_job_core(
    conn: sqlite3.Connection,
    *,
    imported_at: str,
    bundle: dict,
    job_id: str,
    correlation_id: str,
    caller: str | None,
    tenant_id: str | None,
    dataset_id: str | None,
    service_id: str | None,
) -> None:
    status, intersection_size, intersection_sum, reason_code, created_at = job_summary(bundle)
    public_report = bundle["public_report"] or {}
    conn.execute(
        """
        INSERT INTO jobs(
          job_id, correlation_id, caller, tenant_id, dataset_id, service_id,
          out_base, public_report_path, audit_chain_path, status, release_reason_code,
          public_report_released, intersection_size, intersection_sum, created_at_utc, imported_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
          correlation_id=excluded.correlation_id,
          caller=excluded.caller,
          tenant_id=excluded.tenant_id,
          dataset_id=excluded.dataset_id,
          service_id=excluded.service_id,
          out_base=excluded.out_base,
          public_report_path=excluded.public_report_path,
          audit_chain_path=excluded.audit_chain_path,
          status=excluded.status,
          release_reason_code=excluded.release_reason_code,
          public_report_released=excluded.public_report_released,
          intersection_size=excluded.intersection_size,
          intersection_sum=excluded.intersection_sum,
          created_at_utc=excluded.created_at_utc,
          imported_at_utc=excluded.imported_at_utc
        """,
        (
            job_id,
            correlation_id,
            caller,
            tenant_id,
            dataset_id,
            service_id,
            str(bundle["out_base"]),
            str((bundle["out_base"] / "a_psi_run" / "public_report.json").resolve()) if (bundle["out_base"] / "a_psi_run" / "public_report.json").is_file() else None,
            str((bundle["out_base"] / "audit_chain.json").resolve()) if (bundle["out_base"] / "audit_chain.json").is_file() else None,
            status,
            reason_code,
            1 if public_report.get("released") is True else 0 if public_report.get("released") is False else None,
            intersection_size,
            intersection_sum,
            created_at,
            imported_at,
        ),
    )


def clear_job_dependent_rows(conn: sqlite3.Connection, job_id: str) -> None:
    for table in JOB_DEPENDENT_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE job_id = ?", (job_id,))


def insert_job_artifacts(conn: sqlite3.Connection, *, bundle: dict, job_id: str) -> None:
    artifact_map = import_artifact_map(bundle)
    for artifact_type, path in artifact_map.items():
        exists = path.exists()
        stage = ARTIFACT_TYPE_STAGE_MAP[artifact_type]
        conn.execute(
            """
            INSERT INTO job_artifacts(job_id, stage, artifact_type, path, sha256, file_format, exists_on_disk, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                stage,
                artifact_type,
                str(path.resolve()),
                sha256_file(path),
                file_format(path),
                1 if exists else 0,
                json.dumps({"exists": exists}, ensure_ascii=False),
            ),
        )


def stage_status_from_records(records: list[dict]) -> tuple[str, str | None, int | None, dict]:
    if not records:
        return "missing", None, None, {}
    decision = str(records[-1].get("decision", "") or "").lower()
    if decision == "allow":
        status = "allow"
    elif decision == "deny":
        status = "deny"
    else:
        status = "observed"
    ts_utc = record_ts_utc_string(records[-1])
    durations = [duration for duration in (optional_int(record.get("duration_ms")) for record in records) if duration is not None]
    stage_duration_ms = sum(durations) if durations else None
    return (
        status,
        str(ts_utc) if ts_utc else None,
        stage_duration_ms,
        {
            "record_count": len(records),
            "duration_record_count": len(durations),
            "duration_ms_total": stage_duration_ms,
            "duration_ms_max": max(durations) if durations else None,
            "duration_ms_latest": optional_int(records[-1].get("duration_ms")),
        },
    )


def insert_stage_statuses(conn: sqlite3.Connection, *, bundle: dict, job_id: str) -> None:
    stage_map = {
        "sse_export": bundle["sse_export_audit"],
        "record_recovery_service": bundle["record_recovery_service_audit"],
        "bridge": bundle["bridge_audit"],
        "pjc": bundle["pjc_audit"],
        "policy_release": bundle["policy_audit"],
        "key_access": bundle["key_access_audit"],
    }
    for stage, records in stage_map.items():
        status, ts_utc, duration_ms, details = stage_status_from_records(records)
        conn.execute(
            """
            INSERT INTO job_stage_status(job_id, stage, status, ts_utc, duration_ms, details_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_id, stage, status, ts_utc, duration_ms, json.dumps(details, ensure_ascii=False)),
        )


def artifact_hint(record: dict) -> str | None:
    return first_nonempty(
        record.get("output_file"),
        record.get("release_file"),
        record.get("result_file"),
        record.get("input_file"),
        record.get("record_store_file"),
    )


def insert_audit_events(
    conn: sqlite3.Connection,
    *,
    bundle: dict,
    job_id: str,
    correlation_id: str,
    tenant_id: str | None,
    dataset_id: str | None,
    service_id: str | None,
) -> None:
    sources = (
        ("sse_export", bundle["sse_export_audit"]),
        ("record_recovery_service", bundle["record_recovery_service_audit"]),
        ("bridge", bundle["bridge_audit"]),
        ("pjc", bundle["pjc_audit"]),
        ("policy_release", bundle["policy_audit"]),
    )
    for stage, records in sources:
        for record in records:
            conn.execute(
                """
                INSERT INTO audit_events(
                  job_id, correlation_id, stage, event_type, ts_utc, caller,
                  tenant_id, dataset_id, service_id, decision, reason_code, artifact_path, duration_ms, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    str(first_nonempty(record.get("correlation_id"), correlation_id)),
                    stage,
                    str(first_nonempty(record.get("event"), stage)),
                    record_ts_utc_string(record),
                    record.get("caller"),
                    first_nonempty(record.get("tenant_id"), tenant_id),
                    first_nonempty(record.get("dataset_id"), dataset_id),
                    first_nonempty(record.get("service_id"), service_id),
                    record.get("decision"),
                    record.get("reason_code"),
                    artifact_hint(record),
                    optional_int(record.get("duration_ms")),
                    json.dumps(record, ensure_ascii=False),
                ),
            )


def insert_key_access_events(
    conn: sqlite3.Connection,
    *,
    bundle: dict,
    job_id: str,
    correlation_id: str,
    tenant_id: str | None,
    dataset_id: str | None,
    service_id: str | None,
) -> None:
    for record in bundle["key_access_audit"]:
        conn.execute(
            """
            INSERT INTO key_access_events(
              job_id, correlation_id, caller, tenant_id, dataset_id, service_id,
              key_id, key_version, purpose, decision, reason_code, ts_utc, source_file, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                str(first_nonempty(record.get("correlation_id"), correlation_id)),
                record.get("caller"),
                tenant_id,
                dataset_id,
                service_id,
                record.get("key_id"),
                record.get("key_version"),
                record.get("purpose"),
                record.get("decision"),
                record.get("reason_code"),
                record.get("ts_utc"),
                record.get("manifest_file"),
                json.dumps(record, ensure_ascii=False),
            ),
        )


def insert_privacy_budget_ledger_events(
    conn: sqlite3.Connection,
    *,
    bundle: dict,
    source_job_id: str,
) -> None:
    ledger_path = bundle.get("privacy_budget_ledger_path")
    if not ledger_path:
        return
    for record in bundle["privacy_budget_ledger"]:
        budget = record.get("budget") if isinstance(record.get("budget"), dict) else {}
        conn.execute(
            """
            INSERT INTO privacy_budget_ledger_events(
              job_id, ledger_job_id, correlation_id, policy_version, ts_utc,
              caller, tenant_id, dataset_id, purpose, decision, reason_code,
              abuse_signal, matched_prior_job_id, matched_prior_relation,
              budget_limit, budget_cost, budget_used_before, budget_used_after,
              budget_consumed, query_fingerprint, query_payload_sha256,
              window_json, bucket_json, parsed_metrics_json, public_report_sha256,
              ledger_path, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_job_id,
                record.get("job_id"),
                record.get("correlation_id"),
                record.get("policy_version"),
                record.get("ts_utc"),
                record.get("caller"),
                record.get("tenant_id"),
                record.get("dataset_id"),
                record.get("purpose"),
                record.get("decision"),
                record.get("reason_code"),
                record.get("abuse_signal"),
                record.get("matched_prior_job_id"),
                record.get("matched_prior_relation"),
                optional_float(budget.get("limit")),
                optional_float(budget.get("cost")),
                optional_float(budget.get("used_before")),
                optional_float(budget.get("used_after")),
                bool(budget.get("consumed")) if budget.get("consumed") is not None else None,
                record.get("query_fingerprint"),
                record.get("query_payload_sha256"),
                json.dumps(record.get("window"), ensure_ascii=False),
                json.dumps(record.get("bucket"), ensure_ascii=False),
                json.dumps(record.get("parsed_metrics"), ensure_ascii=False),
                record.get("public_report_sha256"),
                str(Path(ledger_path).resolve()),
                json.dumps(record, ensure_ascii=False),
            ),
        )


def insert_audit_chain(conn: sqlite3.Connection, *, bundle: dict, job_id: str) -> None:
    if bundle["audit_chain"]:
        path = bundle["out_base"] / "audit_chain.json"
        counts = bundle["audit_chain"].get("counts")
        conn.execute(
            """
            INSERT INTO audit_chains(job_id, path, sha256, generated_at_utc, counts_json, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                str(path.resolve()),
                sha256_file(path),
                bundle["audit_chain"].get("generated_at_utc"),
                json.dumps(counts, ensure_ascii=False) if counts is not None else None,
                json.dumps(bundle["audit_chain"], ensure_ascii=False),
            ),
        )
    if bundle["audit_seal"]:
        path = bundle["out_base"] / "audit_chain.seal.json"
        signature_payload = bundle["audit_seal"].get("signature")
        signature_algorithm = first_nonempty(
            bundle["audit_seal"].get("signature_algorithm"),
            signature_payload.get("algorithm") if isinstance(signature_payload, dict) else None,
            bundle["audit_seal"].get("hash", {}).get("algorithm") if isinstance(bundle["audit_seal"].get("hash"), dict) else None,
        )
        conn.execute(
            """
            INSERT INTO audit_seals(job_id, path, sha256, algorithm, signed, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                str(path.resolve()),
                sha256_file(path),
                signature_algorithm,
                1 if bundle["audit_seal"].get("signature") else 0,
                json.dumps(bundle["audit_seal"], ensure_ascii=False),
            ),
        )


def existing_job_row_counts(conn: sqlite3.Connection, job_id: str) -> dict[str, int]:
    return {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE job_id = ?", (job_id,)).fetchone()[0])
        for table in JOB_DEPENDENT_TABLES
    }


def existing_job_summary(conn: sqlite3.Connection, job_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT job_id, correlation_id, caller, tenant_id, dataset_id, service_id,
               status, release_reason_code, public_report_released, imported_at_utc, out_base
        FROM jobs
        WHERE job_id = ?
        """,
        (job_id,),
    ).fetchone()
    if row is None:
        return {
            "exists": False,
            "job_id": job_id,
            "row_counts": {table: 0 for table in JOB_DEPENDENT_TABLES},
        }
    data = row_to_dict(row) or {}
    data["exists"] = True
    data["row_counts"] = existing_job_row_counts(conn, job_id)
    return data


def build_import_plan(conn: sqlite3.Connection, out_base: Path) -> dict[str, Any]:
    bundle = read_bundle(out_base)
    job_id = infer_job_id(bundle)
    correlation_id = infer_correlation_id(bundle, job_id)
    caller, tenant_id, dataset_id, service_id = infer_scope(bundle)
    existing = existing_job_summary(conn, job_id)
    return {
        "bundle": bundle,
        "job_id": job_id,
        "correlation_id": correlation_id,
        "caller": caller,
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "service_id": service_id,
        "action": "replace" if existing["exists"] else "insert",
        "incoming": incoming_summary(bundle),
        "existing_job": existing,
    }


def import_policy(conn: sqlite3.Connection, *, policy_path: str, imported_at: str) -> None:
    path = Path(policy_path)
    if not path.is_file():
        return
    plan = plan_policy_file(conn, policy_path=path)
    apply_policy_plan(conn, plan, imported_at=imported_at)


def import_referenced_policies(conn: sqlite3.Connection, *, bundle: dict, imported_at: str) -> None:
    for path in referenced_policy_paths(bundle):
        import_policy(conn, policy_path=path, imported_at=imported_at)


def apply_import_plan(conn: sqlite3.Connection, plan: dict[str, Any], *, imported_at: str) -> dict[str, Any]:
    bundle = plan["bundle"]
    job_id = str(plan["job_id"])
    correlation_id = str(plan["correlation_id"])
    caller = plan["caller"]
    tenant_id = plan["tenant_id"]
    dataset_id = plan["dataset_id"]
    service_id = plan["service_id"]
    clear_job_dependent_rows(conn, job_id)
    upsert_scope_entities(
        conn,
        imported_at=imported_at,
        job_id=job_id,
        caller=caller,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        service_id=service_id,
        service_config=bundle["record_recovery_service_config"],
    )
    replace_job_core(
        conn,
        imported_at=imported_at,
        bundle=bundle,
        job_id=job_id,
        correlation_id=correlation_id,
        caller=caller,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        service_id=service_id,
    )
    insert_job_artifacts(conn, bundle=bundle, job_id=job_id)
    insert_stage_statuses(conn, bundle=bundle, job_id=job_id)
    insert_audit_events(
        conn,
        bundle=bundle,
        job_id=job_id,
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        service_id=service_id,
    )
    insert_key_access_events(
        conn,
        bundle=bundle,
        job_id=job_id,
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        service_id=service_id,
    )
    insert_privacy_budget_ledger_events(conn, bundle=bundle, source_job_id=job_id)
    insert_audit_chain(conn, bundle=bundle, job_id=job_id)
    import_referenced_policies(conn, bundle=bundle, imported_at=imported_at)
    return {
        "job_id": job_id,
        "correlation_id": correlation_id,
        "caller": caller,
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "service_id": service_id,
        "out_base": str(bundle["out_base"]),
        "imported_at_utc": imported_at,
    }


def summarize_report(imports: list[dict[str, Any]]) -> dict[str, Any]:
    action_counts = {"insert": 0, "replace": 0}
    for item in imports:
        action = item.get("action")
        if action in action_counts:
            action_counts[str(action)] += 1
    return {
        "requested_run_count": len(imports),
        "processed_run_count": len(imports),
        "inserted_job_count": action_counts["insert"],
        "replaced_job_count": action_counts["replace"],
    }


def parse_out_base_file(path_value: str) -> list[Path]:
    path = Path(path_value).resolve()
    if not path.is_file():
        raise SystemExit(f"[ERROR] out-base file does not exist: {path}")
    values: list[Path] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        values.append(Path(candidate).resolve())
    return values


def collect_out_bases(args: argparse.Namespace) -> list[Path]:
    values = [Path(item).resolve() for item in args.out_base]
    if args.out_base_file:
        values.extend(parse_out_base_file(args.out_base_file))
    if not values:
        raise SystemExit("[ERROR] at least one --out-base or --out-base-file entry is required")
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in values:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def import_runs(conn: sqlite3.Connection, out_bases: list[Path], *, dry_run: bool) -> dict[str, Any]:
    generated_at = utc_now()
    plans = [build_import_plan(conn, out_base) for out_base in out_bases]
    job_ids = [str(plan["job_id"]) for plan in plans]
    duplicate_job_ids = sorted({job_id for job_id in job_ids if job_ids.count(job_id) > 1})
    if duplicate_job_ids:
        raise SystemExit(
            f"[ERROR] duplicate inferred job_id values in one import batch are not allowed: {', '.join(duplicate_job_ids)}"
        )
    imports: list[dict[str, Any]] = []
    # All-or-nothing: every plan in the batch must apply, or none of them.
    # On any Python exception below we roll back so the caller never observes
    # a half-imported batch (e.g. plan #2 of 3 succeeded, plan #3 raised).
    try:
        for plan in plans:
            imported = None
            imported_at = None
            if not dry_run:
                imported_at = utc_now()
                imported = apply_import_plan(conn, plan, imported_at=imported_at)
            entry = {
                "out_base": str(plan["bundle"]["out_base"]),
                "job_id": plan["job_id"],
                "correlation_id": plan["correlation_id"],
                "caller": plan["caller"],
                "tenant_id": plan["tenant_id"],
                "dataset_id": plan["dataset_id"],
                "service_id": plan["service_id"],
                "action": plan["action"],
                "existing_job": plan["existing_job"],
                "incoming": plan["incoming"],
                "imported_at_utc": imported_at,
                "result": imported,
            }
            if not dry_run:
                entry["job_state_after"] = existing_job_summary(conn, str(plan["job_id"]))
            imports.append(entry)
        if not dry_run:
            conn.commit()
    except BaseException:
        if not dry_run:
            try:
                conn.rollback()
            except Exception:
                # If rollback itself fails we still want the original error to surface.
                pass
        raise
    return {
        "schema": IMPORT_SCHEMA,
        "generated_at_utc": generated_at,
        "db_path": None,
        "mode": "dry_run" if dry_run else "apply",
        "applied_migrations": [],
        "summary": summarize_report(imports),
        "imports": imports,
        "imported": imports[0]["result"] if len(imports) == 1 else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Import one or more existing pipeline run directories into the sidecar metadata database.")
    ap.add_argument("--out-base", action="append", default=[], help="Run directory to import; may be provided multiple times")
    ap.add_argument("--out-base-file", default="", help="Optional newline-delimited file of run directories to import")
    ap.add_argument("--db-path", default="")
    ap.add_argument("--db-dsn", default="")
    ap.add_argument("--dry-run", action="store_true", help="Read and reconcile runs without writing to the DB")
    args = ap.parse_args()
    if not args.db_path and not args.db_dsn:
        raise SystemExit("[ERROR] one of --db-path or --db-dsn is required")

    out_bases = collect_out_bases(args)
    conn = connect_db(args.db_path, dsn=args.db_dsn)
    try:
        applied = apply_migrations(conn)
        try:
            report = import_runs(conn, out_bases, dry_run=args.dry_run)
        except BaseException:
            # Defence in depth — import_runs already rolls back, but if anything
            # raised between import_runs returning and conn.close() landing,
            # explicitly drop the in-flight transaction so we never leak it.
            try:
                conn.rollback()
            except Exception:
                pass
            raise
    finally:
        conn.close()
    report["db_path"] = str(Path(args.db_path).resolve()) if args.db_path else None
    report["db_dsn"] = args.db_dsn or None
    report["applied_migrations"] = applied
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
