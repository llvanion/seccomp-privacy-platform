#!/usr/bin/env python3
import argparse
import os
import sqlite3
from pathlib import Path
from typing import Any, NoReturn

from platform_metadata_lib import (
    connect_sqlite,
    file_exists,
    first_non_empty,
    json_dumps,
    load_json_if_exists,
    load_json_object,
    load_jsonl,
    normalize_text,
    sha256_file,
    upsert_registry_row,
    utc_now_iso,
)


def die(msg: str) -> NoReturn:
    raise SystemExit(f"[ERROR] {msg}")


def resolve_paths(out_base: str) -> dict[str, str]:
    root = os.path.abspath(out_base)
    return {
        "out_base": root,
        "sse_audit": os.path.join(root, "sse_exports", "export_audit.jsonl"),
        "record_recovery_service_audit": os.path.join(root, "sse_exports", "record_recovery_service_audit.jsonl"),
        "record_recovery_service_health": os.path.join(root, "sse_exports", "record_recovery_service_health.json"),
        "record_recovery_service_config": os.path.join(root, "sse_exports", "record_recovery_service_config.json"),
        "bridge_job_meta": os.path.join(root, "bridge_job", "job_meta.json"),
        "bridge_audit": os.path.join(root, "bridge_job", "bridge_audit.jsonl"),
        "pjc_audit": os.path.join(root, "a_psi_run", "pjc_audit.jsonl"),
        "pjc_result": os.path.join(root, "a_psi_run", "attribution_result.json"),
        "public_report": os.path.join(root, "a_psi_run", "public_report.json"),
        "policy_audit": os.path.join(root, "a_psi_run", "audit_log.jsonl"),
        "key_access_audit": os.path.join(root, "key_access_audit.jsonl"),
        "audit_chain": os.path.join(root, "audit_chain.json"),
        "audit_seal": os.path.join(root, "audit_chain.seal.json"),
    }


def ensure_db_initialized(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'jobs'
        """
    ).fetchone()
    if row is None:
        die("metadata DB is not initialized; run scripts/init_metadata_db.py first")


def detect_job_id(paths: dict[str, str]) -> str:
    bridge_job_meta = load_json_if_exists(paths["bridge_job_meta"])
    if bridge_job_meta and normalize_text(bridge_job_meta.get("job_id")):
        return str(bridge_job_meta["job_id"])

    for key in ("public_report", "audit_chain", "pjc_result"):
        payload = load_json_if_exists(paths[key])
        if payload and normalize_text(payload.get("job_id")):
            return str(payload["job_id"])
        if payload and normalize_text(payload.get("correlation_id")):
            return str(payload["correlation_id"])

    for key in ("sse_audit", "record_recovery_service_audit", "bridge_audit", "policy_audit", "key_access_audit"):
        records = load_jsonl(paths[key])
        for record in records:
            candidate = first_non_empty(record.get("job_id"), record.get("correlation_id"))
            if candidate:
                return str(candidate)

    die(f"unable to detect job_id from out-base: {paths['out_base']}")


def filter_job_records(records: list[dict[str, Any]], job_id: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for record in records:
        record_job_id = first_non_empty(record.get("job_id"), record.get("correlation_id"))
        if record_job_id is None or str(record_job_id) == job_id:
            output.append(record)
    return output


def collect_artifacts(paths: dict[str, str], job_id: str) -> dict[str, Any]:
    bridge_job_meta = load_json_if_exists(paths["bridge_job_meta"])
    public_report = load_json_if_exists(paths["public_report"])
    pjc_result = load_json_if_exists(paths["pjc_result"])
    audit_chain = load_json_if_exists(paths["audit_chain"])
    audit_seal = load_json_if_exists(paths["audit_seal"])
    service_health = load_json_if_exists(paths["record_recovery_service_health"])
    service_config = load_json_if_exists(paths["record_recovery_service_config"])

    return {
        "job_id": job_id,
        "bridge_job_meta": bridge_job_meta,
        "public_report": public_report,
        "pjc_result": pjc_result,
        "audit_chain": audit_chain,
        "audit_seal": audit_seal,
        "service_health": service_health,
        "service_config": service_config,
        "sse_audit": filter_job_records(load_jsonl(paths["sse_audit"]), job_id),
        "record_recovery_service_audit": filter_job_records(load_jsonl(paths["record_recovery_service_audit"]), job_id),
        "bridge_audit": filter_job_records(load_jsonl(paths["bridge_audit"]), job_id),
        "pjc_audit": filter_job_records(load_jsonl(paths["pjc_audit"]), job_id),
        "policy_audit": filter_job_records(load_jsonl(paths["policy_audit"]), job_id),
        "key_access_audit": filter_job_records(load_jsonl(paths["key_access_audit"]), job_id),
    }


def infer_policy_id(args: argparse.Namespace, payload: dict[str, Any]) -> str | None:
    return normalize_text(
        first_non_empty(
            args.policy_id,
            payload.get("public_report", {}).get("policy_id") if payload.get("public_report") else None,
            payload.get("public_report", {}).get("policy_version") if payload.get("public_report") else None,
            payload.get("audit_chain", {}).get("policy_id") if payload.get("audit_chain") else None,
            payload.get("policy_audit", [{}])[0].get("policy_id") if payload.get("policy_audit") else None,
            payload.get("policy_audit", [{}])[0].get("policy_version") if payload.get("policy_audit") else None,
        )
    )


def infer_dataset_id(args: argparse.Namespace, payload: dict[str, Any]) -> str | None:
    return normalize_text(first_non_empty(args.dataset_id))


def infer_service_id(args: argparse.Namespace, payload: dict[str, Any]) -> str | None:
    return normalize_text(
        first_non_empty(
            args.service_id,
            payload.get("service_config", {}).get("service_id") if payload.get("service_config") else None,
            payload.get("service_config", {}).get("sid") if payload.get("service_config") else None,
            payload.get("service_config", {}).get("service_name") if payload.get("service_config") else None,
        )
    )


def infer_tenant_id(args: argparse.Namespace, payload: dict[str, Any]) -> str | None:
    return normalize_text(first_non_empty(args.tenant_id))


def infer_caller(payload: dict[str, Any]) -> str | None:
    sources = [
        payload.get("public_report", {}).get("caller") if payload.get("public_report") else None,
        payload.get("policy_audit", [{}])[0].get("caller") if payload.get("policy_audit") else None,
        payload.get("sse_audit", [{}])[0].get("caller") if payload.get("sse_audit") else None,
        payload.get("record_recovery_service_audit", [{}])[0].get("caller") if payload.get("record_recovery_service_audit") else None,
        payload.get("key_access_audit", [{}])[0].get("caller") if payload.get("key_access_audit") else None,
    ]
    return normalize_text(first_non_empty(*sources))


def infer_record_recovery_boundary(payload: dict[str, Any]) -> str | None:
    for record in payload.get("sse_audit", []):
        boundary = normalize_text(record.get("record_recovery_boundary"))
        if boundary:
            return boundary
    return None


def infer_token_scope(payload: dict[str, Any]) -> str | None:
    bridge_job_meta = payload.get("bridge_job_meta") or {}
    bridge = bridge_job_meta.get("bridge", {}) if isinstance(bridge_job_meta.get("bridge"), dict) else {}
    return normalize_text(bridge.get("token_scope"))


def infer_token_key_version(payload: dict[str, Any]) -> str | None:
    bridge_job_meta = payload.get("bridge_job_meta") or {}
    bridge = bridge_job_meta.get("bridge", {}) if isinstance(bridge_job_meta.get("bridge"), dict) else {}
    return normalize_text(bridge.get("token_key_version"))


def upsert_job(conn: sqlite3.Connection, args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    bridge_job_meta = payload.get("bridge_job_meta") or {}
    public_report = payload.get("public_report") or {}

    job_row = {
        "job_id": payload["job_id"],
        "correlation_id": normalize_text(first_non_empty(public_report.get("correlation_id"), payload["job_id"])),
        "caller": infer_caller(payload),
        "tenant_id": infer_tenant_id(args, payload),
        "dataset_id": infer_dataset_id(args, payload),
        "service_id": infer_service_id(args, payload),
        "policy_id": infer_policy_id(args, payload),
        "token_scope": infer_token_scope(payload),
        "token_key_version": infer_token_key_version(payload),
        "record_recovery_boundary": infer_record_recovery_boundary(payload),
        "job_type": normalize_text(bridge_job_meta.get("job_type")),
        "job_state": "imported",
        "source_out_base": args.out_base,
        "bridge_generator": normalize_text(bridge_job_meta.get("generator")),
        "raw_metadata_json": json_dumps(bridge_job_meta) if bridge_job_meta else None,
        "created_at": now,
        "updated_at": now,
    }

    upsert_registry_row(
        conn,
        "tenants",
        "tenant_id",
        job_row["tenant_id"],
        {
            "display_name": job_row["tenant_id"],
            "metadata_json": json_dumps({"source": "importer_override"}),
        },
    )
    upsert_registry_row(
        conn,
        "datasets",
        "dataset_id",
        job_row["dataset_id"],
        {
            "tenant_id": job_row["tenant_id"],
            "display_name": job_row["dataset_id"],
            "metadata_json": json_dumps({"source": "importer_override"}),
        },
    )
    upsert_registry_row(
        conn,
        "services",
        "service_id",
        job_row["service_id"],
        {
            "tenant_id": job_row["tenant_id"],
            "service_type": "pipeline_component",
            "display_name": job_row["service_id"],
            "metadata_json": json_dumps({"source": "importer_inferred_or_override"}),
        },
    )
    upsert_registry_row(
        conn,
        "callers",
        "caller",
        job_row["caller"],
        {
            "tenant_id": job_row["tenant_id"],
            "caller_type": "human_user",
            "display_name": job_row["caller"],
            "metadata_json": json_dumps({"source": "artifact_observed"}),
        },
    )
    upsert_registry_row(
        conn,
        "policies",
        "policy_id",
        job_row["policy_id"],
        {
            "tenant_id": job_row["tenant_id"],
            "policy_kind": "release_policy",
            "policy_version": job_row["policy_id"],
            "source_path": pathsafe(first_non_empty(args.policy_source, public_report.get("policy_config"))),
            "metadata_json": json_dumps({"source": "artifact_inferred_or_override"}),
        },
    )

    conn.execute(
        """
        INSERT INTO jobs (
            job_id, correlation_id, caller, tenant_id, dataset_id, service_id, policy_id,
            token_scope, token_key_version, record_recovery_boundary, job_type, job_state,
            source_out_base, bridge_generator, raw_metadata_json, created_at, updated_at
        ) VALUES (
            :job_id, :correlation_id, :caller, :tenant_id, :dataset_id, :service_id, :policy_id,
            :token_scope, :token_key_version, :record_recovery_boundary, :job_type, :job_state,
            :source_out_base, :bridge_generator, :raw_metadata_json, :created_at, :updated_at
        )
        ON CONFLICT(job_id) DO UPDATE SET
            correlation_id = excluded.correlation_id,
            caller = excluded.caller,
            tenant_id = excluded.tenant_id,
            dataset_id = excluded.dataset_id,
            service_id = excluded.service_id,
            policy_id = excluded.policy_id,
            token_scope = excluded.token_scope,
            token_key_version = excluded.token_key_version,
            record_recovery_boundary = excluded.record_recovery_boundary,
            job_type = excluded.job_type,
            job_state = excluded.job_state,
            source_out_base = excluded.source_out_base,
            bridge_generator = excluded.bridge_generator,
            raw_metadata_json = excluded.raw_metadata_json,
            updated_at = excluded.updated_at
        """,
        job_row,
    )
    return job_row


def pathsafe(value: Any) -> str | None:
    return normalize_text(value)


def clear_job_derived_rows(conn: sqlite3.Connection, job_id: str) -> None:
    for table in (
        "job_stage_status",
        "job_artifacts",
        "job_state_transitions",
        "audit_events",
        "audit_chains",
        "audit_seals",
        "key_access_events",
    ):
        conn.execute(f"DELETE FROM {table} WHERE job_id = ?", (job_id,))


def insert_job_stage_status(conn: sqlite3.Connection, job_row: dict[str, Any], stage_name: str, status: str, details: dict[str, Any]) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO job_stage_status (
            job_id, stage_name, status, decision, reason_code, stage_ts,
            details_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_row["job_id"],
            stage_name,
            status,
            normalize_text(details.get("decision")),
            normalize_text(details.get("reason_code")),
            normalize_text(first_non_empty(details.get("ts_utc"), details.get("generated_at_utc"))),
            json_dumps(details),
            now,
            now,
        ),
    )


def insert_job_artifact(conn: sqlite3.Connection, job_id: str, stage_name: str, artifact_type: str, file_path: str, metadata: dict[str, Any] | None = None) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO job_artifacts (
            job_id, stage_name, artifact_type, file_path, sha256, media_type,
            record_count, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            stage_name,
            artifact_type,
            file_path,
            sha256_file(file_path),
            infer_media_type(file_path),
            infer_record_count(metadata),
            json_dumps(metadata) if metadata is not None else None,
            now,
            now,
        ),
    )


def infer_media_type(file_path: str) -> str | None:
    if file_path.endswith(".jsonl"):
        return "application/jsonl"
    if file_path.endswith(".json"):
        return "application/json"
    if file_path.endswith(".csv"):
        return "text/csv"
    return None


def infer_record_count(metadata: dict[str, Any] | None) -> int | None:
    if not metadata:
        return None
    for key in ("record_count", "output_rows", "input_rows", "candidate_count"):
        value = metadata.get(key)
        if isinstance(value, int):
            return value
    return None


def insert_state_transition(conn: sqlite3.Connection, job_id: str, from_state: str | None, to_state: str, reason_code: str | None, details: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO job_state_transitions (
            job_id, from_state, to_state, reason_code, actor_type, actor_id,
            details_json, transitioned_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            from_state,
            to_state,
            reason_code,
            "importer",
            "scripts/import_run_metadata.py",
            json_dumps(details),
            utc_now_iso(),
        ),
    )


def insert_audit_event(conn: sqlite3.Connection, job_row: dict[str, Any], stage_name: str, event_source: str, record: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO audit_events (
            job_id, correlation_id, caller, tenant_id, dataset_id, service_id, policy_id,
            event_schema, event_source, event_name, stage_name, event_ts, decision,
            reason_code, record_recovery_boundary, raw_event_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_row["job_id"],
            normalize_text(first_non_empty(record.get("correlation_id"), job_row["correlation_id"])),
            normalize_text(first_non_empty(record.get("caller"), job_row["caller"])),
            job_row["tenant_id"],
            job_row["dataset_id"],
            job_row["service_id"],
            job_row["policy_id"],
            normalize_text(record.get("schema")),
            event_source,
            normalize_text(first_non_empty(record.get("event"), "unknown_event")) or "unknown_event",
            stage_name,
            normalize_text(first_non_empty(record.get("ts_utc"), record.get("generated_at_utc"), record.get("ts_unix_ms"))),
            normalize_text(record.get("decision")),
            normalize_text(record.get("reason_code")),
            normalize_text(first_non_empty(record.get("record_recovery_boundary"), job_row["record_recovery_boundary"])),
            json_dumps(record),
            utc_now_iso(),
        ),
    )


def insert_key_access_event(conn: sqlite3.Connection, job_row: dict[str, Any], record: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO key_access_events (
            job_id, correlation_id, caller, tenant_id, dataset_id, service_id, policy_id,
            key_id, key_version, purpose, decision, reason_code, manifest_file,
            manifest_sha256, secret_source_kind, secret_source_name, event_ts,
            raw_event_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_row["job_id"],
            normalize_text(first_non_empty(record.get("correlation_id"), job_row["correlation_id"])),
            normalize_text(first_non_empty(record.get("caller"), job_row["caller"])),
            job_row["tenant_id"],
            job_row["dataset_id"],
            job_row["service_id"],
            job_row["policy_id"],
            normalize_text(record.get("key_id")),
            normalize_text(record.get("key_version")),
            normalize_text(record.get("purpose")),
            normalize_text(record.get("decision")) or "unknown",
            normalize_text(record.get("reason_code")),
            normalize_text(record.get("manifest_file")),
            normalize_text(record.get("manifest_sha256")),
            normalize_text((record.get("secret_source") or {}).get("kind")),
            normalize_text((record.get("secret_source") or {}).get("name")),
            normalize_text(record.get("ts_utc")),
            json_dumps(record),
            utc_now_iso(),
        ),
    )


def insert_audit_chain(conn: sqlite3.Connection, job_row: dict[str, Any], path: str, payload: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO audit_chains (
            job_id, correlation_id, chain_schema, generated_at, chain_file, chain_sha256,
            raw_chain_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_row["job_id"],
            normalize_text(first_non_empty(payload.get("correlation_id"), job_row["correlation_id"])),
            normalize_text(payload.get("schema")),
            normalize_text(payload.get("generated_at_utc")),
            path,
            sha256_file(path),
            json_dumps(payload),
            utc_now_iso(),
        ),
    )


def insert_audit_seal(conn: sqlite3.Connection, job_row: dict[str, Any], payload: dict[str, Any]) -> None:
    secret_source = payload.get("secret_source") or {}
    conn.execute(
        """
        INSERT INTO audit_seals (
            job_id, correlation_id, artifact_file, artifact_sha256, signature_algorithm,
            signature, secret_source_kind, secret_source_name, sealed_at, raw_seal_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_row["job_id"],
            normalize_text(first_non_empty(payload.get("correlation_id"), job_row["correlation_id"])),
            normalize_text(payload.get("artifact_file")),
            normalize_text(payload.get("artifact_sha256")),
            normalize_text(payload.get("signature_algorithm")),
            normalize_text(payload.get("signature")),
            normalize_text(secret_source.get("kind")),
            normalize_text(secret_source.get("name")),
            normalize_text(payload.get("ts_utc")),
            json_dumps(payload),
            utc_now_iso(),
        ),
    )


def import_payload(conn: sqlite3.Connection, args: argparse.Namespace, paths: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    job_row = upsert_job(conn, args, payload)
    clear_job_derived_rows(conn, payload["job_id"])

    insert_state_transition(conn, payload["job_id"], None, "imported", "metadata_imported", {"out_base": args.out_base})

    bridge_job_meta = payload.get("bridge_job_meta")
    public_report = payload.get("public_report")
    pjc_result = payload.get("pjc_result")
    audit_chain = payload.get("audit_chain")
    audit_seal = payload.get("audit_seal")
    service_health = payload.get("service_health")
    service_config = payload.get("service_config")

    stage_rows = [
        ("sse_export", payload["sse_audit"]),
        ("record_recovery_service", payload["record_recovery_service_audit"]),
        ("bridge", payload["bridge_audit"]),
        ("pjc", payload["pjc_audit"]),
        ("policy_release", payload["policy_audit"]),
        ("key_access", payload["key_access_audit"]),
    ]
    for stage_name, records in stage_rows:
        if records:
            insert_job_stage_status(conn, job_row, stage_name, "observed", records[-1])
        else:
            fallback_details = {"stage": stage_name, "reason_code": "no_artifact"}
            if stage_name == "pjc" and pjc_result:
                fallback_details = {
                    "stage": stage_name,
                    "reason_code": "pjc_result_only",
                    "job_id": payload["job_id"],
                    "intersection_size": pjc_result.get("intersection_size"),
                    "intersection_sum": pjc_result.get("intersection_sum"),
                }
                insert_job_stage_status(conn, job_row, stage_name, "observed", fallback_details)
                continue
            insert_job_stage_status(conn, job_row, stage_name, "missing", fallback_details)

    if bridge_job_meta:
        insert_job_artifact(conn, payload["job_id"], "bridge", "bridge_job_meta", paths["bridge_job_meta"], bridge_job_meta)
    if public_report and file_exists(paths["public_report"]):
        insert_job_artifact(conn, payload["job_id"], "policy_release", "public_report", paths["public_report"], public_report)
    if pjc_result and file_exists(paths["pjc_result"]):
        insert_job_artifact(conn, payload["job_id"], "pjc", "attribution_result", paths["pjc_result"], pjc_result)
    if audit_chain and file_exists(paths["audit_chain"]):
        insert_job_artifact(conn, payload["job_id"], "audit", "audit_chain", paths["audit_chain"], audit_chain)
        insert_audit_chain(conn, job_row, paths["audit_chain"], audit_chain)
    if audit_seal and file_exists(paths["audit_seal"]):
        insert_job_artifact(conn, payload["job_id"], "audit", "audit_seal", paths["audit_seal"], audit_seal)
        insert_audit_seal(conn, job_row, audit_seal)
    if service_health and file_exists(paths["record_recovery_service_health"]):
        insert_job_artifact(conn, payload["job_id"], "record_recovery_service", "service_health", paths["record_recovery_service_health"], service_health)
    if service_config and file_exists(paths["record_recovery_service_config"]):
        insert_job_artifact(conn, payload["job_id"], "record_recovery_service", "service_config", paths["record_recovery_service_config"], service_config)

    if file_exists(paths["sse_audit"]):
        insert_job_artifact(conn, payload["job_id"], "sse_export", "sse_export_audit", paths["sse_audit"], {"record_count": len(payload["sse_audit"])})
    if file_exists(paths["record_recovery_service_audit"]):
        insert_job_artifact(conn, payload["job_id"], "record_recovery_service", "record_recovery_service_audit", paths["record_recovery_service_audit"], {"record_count": len(payload["record_recovery_service_audit"])})
    if file_exists(paths["bridge_audit"]):
        insert_job_artifact(conn, payload["job_id"], "bridge", "bridge_audit", paths["bridge_audit"], {"record_count": len(payload["bridge_audit"])})
    if file_exists(paths["policy_audit"]):
        insert_job_artifact(conn, payload["job_id"], "policy_release", "policy_audit", paths["policy_audit"], {"record_count": len(payload["policy_audit"])})
    if file_exists(paths["key_access_audit"]):
        insert_job_artifact(conn, payload["job_id"], "key_access", "key_access_audit", paths["key_access_audit"], {"record_count": len(payload["key_access_audit"])})
    if file_exists(paths["pjc_audit"]):
        insert_job_artifact(conn, payload["job_id"], "pjc", "pjc_audit", paths["pjc_audit"], {"record_count": len(payload["pjc_audit"])})

    for record in payload["sse_audit"]:
        insert_audit_event(conn, job_row, "sse_export", "sse_export_audit", record)
    for record in payload["record_recovery_service_audit"]:
        insert_audit_event(conn, job_row, "record_recovery_service", "record_recovery_service_audit", record)
    for record in payload["bridge_audit"]:
        insert_audit_event(conn, job_row, "bridge", "bridge_audit", record)
    for record in payload["pjc_audit"]:
        insert_audit_event(conn, job_row, "pjc", "pjc_audit", record)
    for record in payload["policy_audit"]:
        insert_audit_event(conn, job_row, "policy_release", "policy_audit", record)
    for record in payload["key_access_audit"]:
        insert_audit_event(conn, job_row, "key_access", "key_access_audit", record)
        insert_key_access_event(conn, job_row, record)

    return {
        "job_id": payload["job_id"],
        "caller": job_row["caller"],
        "tenant_id": job_row["tenant_id"],
        "dataset_id": job_row["dataset_id"],
        "service_id": job_row["service_id"],
        "policy_id": job_row["policy_id"],
        "record_counts": {
            "sse_export_audit": len(payload["sse_audit"]),
            "record_recovery_service_audit": len(payload["record_recovery_service_audit"]),
            "bridge_audit": len(payload["bridge_audit"]),
            "pjc_audit": len(payload["pjc_audit"]),
            "policy_audit": len(payload["policy_audit"]),
            "key_access_audit": len(payload["key_access_audit"]),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Import one out-base pipeline run into the platform metadata DB.")
    ap.add_argument("--out-base", required=True, help="Pipeline output directory")
    ap.add_argument("--db-path", required=True, help="SQLite metadata DB path")
    ap.add_argument("--tenant-id", default="", help="Optional override for frozen field tenant_id")
    ap.add_argument("--dataset-id", default="", help="Optional override for frozen field dataset_id")
    ap.add_argument("--service-id", default="", help="Optional override for frozen field service_id")
    ap.add_argument("--policy-id", default="", help="Optional override for frozen field policy_id")
    ap.add_argument("--policy-source", default="", help="Optional policy file path reference to persist with inferred/override policy")
    args = ap.parse_args()

    paths = resolve_paths(args.out_base)
    if not os.path.isdir(paths["out_base"]):
        die(f"missing out-base directory: {paths['out_base']}")

    job_id = detect_job_id(paths)
    payload = collect_artifacts(paths, job_id)

    with connect_sqlite(os.path.abspath(args.db_path)) as conn:
        ensure_db_initialized(conn)
        summary = import_payload(conn, args, paths, payload)
        conn.commit()

    print(json_dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
