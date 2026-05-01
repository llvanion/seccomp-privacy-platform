#!/usr/bin/env python3
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import apply_migrations, connect_db, file_format, sha256_file, utc_now  # noqa: E402


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
        "key_access_audit": optional_jsonl(out_base / "key_access_audit.jsonl"),
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
    for table in (
        "job_artifacts",
        "job_stage_status",
        "audit_events",
        "audit_chains",
        "audit_seals",
        "key_access_events",
    ):
        conn.execute(f"DELETE FROM {table} WHERE job_id = ?", (job_id,))


def insert_job_artifacts(conn: sqlite3.Connection, *, bundle: dict, job_id: str) -> None:
    artifact_map = {
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
    for artifact_type, path in artifact_map.items():
        exists = path.exists()
        stage = (
            "sse_export" if artifact_type == "sse_export_audit" else
            "record_recovery_service" if artifact_type.startswith("record_recovery_service_") else
            "bridge" if artifact_type.startswith("bridge_") else
            "pjc" if artifact_type == "pjc_audit" else
            "policy_release" if artifact_type in {"public_report", "policy_audit"} else
            "audit" if artifact_type in {"audit_chain", "audit_seal"} else
            "key_access"
        )
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


def import_policy(conn: sqlite3.Connection, *, policy_path: str, imported_at: str) -> None:
    path = Path(policy_path)
    if not path.is_file():
        return
    payload = load_json(path)
    schema_name = str(payload.get("schema", "") or "")
    policy_id = sha256_file(path) or str(path.resolve())
    conn.execute(
        """
        INSERT INTO policies(policy_id, policy_kind, path, sha256, schema_name, imported_at_utc, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(policy_id) DO UPDATE SET
          policy_kind=excluded.policy_kind,
          path=excluded.path,
          sha256=excluded.sha256,
          schema_name=excluded.schema_name,
          imported_at_utc=excluded.imported_at_utc,
          payload_json=excluded.payload_json
        """,
        (
            policy_id,
            schema_name or "unknown_policy",
            str(path.resolve()),
            sha256_file(path),
            schema_name or None,
            imported_at,
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    callers = payload.get("callers")
    if not isinstance(callers, dict):
        return
    for caller, caller_policy in callers.items():
        if not isinstance(caller_policy, dict):
            continue
        tenant_id = caller_policy.get("tenant_id")
        datasets = caller_policy.get("allowed_dataset_ids")
        services = caller_policy.get("allowed_service_ids")
        conn.execute(
            """
            INSERT INTO policy_bindings(
              policy_id, binding_kind, caller, tenant_id, dataset_id, service_id,
              source_file, binding_json, imported_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(policy_id, binding_kind, caller) DO UPDATE SET
              tenant_id=excluded.tenant_id,
              dataset_id=excluded.dataset_id,
              service_id=excluded.service_id,
              source_file=excluded.source_file,
              binding_json=excluded.binding_json,
              imported_at_utc=excluded.imported_at_utc
            """,
            (
                policy_id,
                "caller_policy",
                caller,
                str(tenant_id) if tenant_id else None,
                datasets[0] if isinstance(datasets, list) and len(datasets) == 1 else None,
                services[0] if isinstance(services, list) and len(services) == 1 else None,
                str(path.resolve()),
                json.dumps(caller_policy, ensure_ascii=False),
                imported_at,
            ),
        )
        for key, value in caller_policy.items():
            conn.execute(
                """
                INSERT INTO caller_permissions(policy_id, caller, permission_key, permission_value, source_file, imported_at_utc)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(policy_id, caller, permission_key) DO UPDATE SET
                  permission_value=excluded.permission_value,
                  source_file=excluded.source_file,
                  imported_at_utc=excluded.imported_at_utc
                """,
                (
                    policy_id,
                    caller,
                    str(key),
                    json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, bool, int, float)) else str(value),
                    str(path.resolve()),
                    imported_at,
                ),
            )


def import_referenced_policies(conn: sqlite3.Connection, *, bundle: dict, imported_at: str) -> None:
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
    for path in sorted(paths):
        import_policy(conn, policy_path=path, imported_at=imported_at)


def import_run(conn: sqlite3.Connection, out_base: Path) -> dict:
    imported_at = utc_now()
    bundle = read_bundle(out_base)
    job_id = infer_job_id(bundle)
    correlation_id = infer_correlation_id(bundle, job_id)
    caller, tenant_id, dataset_id, service_id = infer_scope(bundle)

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
    insert_audit_chain(conn, bundle=bundle, job_id=job_id)
    import_referenced_policies(conn, bundle=bundle, imported_at=imported_at)
    conn.commit()
    return {
        "job_id": job_id,
        "correlation_id": correlation_id,
        "caller": caller,
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "service_id": service_id,
        "out_base": str(out_base.resolve()),
        "imported_at_utc": imported_at,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Import one existing pipeline run directory into the sidecar metadata database.")
    ap.add_argument("--out-base", required=True)
    ap.add_argument("--db-path", required=True)
    args = ap.parse_args()

    conn = connect_db(args.db_path)
    try:
        applied = apply_migrations(conn)
        result = import_run(conn, Path(args.out_base))
    finally:
        conn.close()
    print(json.dumps({"db_path": str(Path(args.db_path).resolve()), "applied_migrations": applied, "imported": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
