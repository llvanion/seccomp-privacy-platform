#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SCRIPT = REPO_ROOT / "scripts" / "run_sse_bridge_pipeline.sh"
REQUEST_SCHEMA = "query_workflow_request/v1"
MANIFEST_SCHEMA = "query_workflow_submission/v1"
RECEIPT_SCHEMA = "query_workflow_receipt/v1"
STATUS_SCHEMA = "query_workflow_status/v1"
SUPPORTED_QUERY_TYPES = {"cross_party_match"}
QUERY_WORKFLOW_DIRNAME = "query_workflow"
SUBMISSION_MANIFEST_FILENAME = "submission_manifest.json"
EXECUTION_RECEIPTS_FILENAME = "execution_receipts.jsonl"
STATUS_FILENAME = "status.json"
PATH_FIELDS = {
    "server_source",
    "client_source",
    "server_record_store_path",
    "client_record_store_path",
    "record_recovery_socket",
    "record_recovery_service_config",
    "record_recovery_authz_config",
    "key_manifest",
    "keyring",
    "external_kms_config",
    "sse_export_policy_config",
    "out_base",
    "key_access_audit_log",
    "audit_archive_dir",
    "pjc_audit_log",
    "sse_export_audit_log",
    "record_recovery_service_audit_log",
    "record_recovery_service_log",
    "record_recovery_service_health_json",
}
SECRET_FIELDS = {"token_secret"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def json_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_request(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("[ERROR] workflow request must be a JSON object")
    return payload


def resolve_request_path(request_dir: Path, value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((request_dir / path).resolve())


def normalize_request_paths(payload: dict[str, Any], *, request_dir: Path) -> dict[str, Any]:
    normalized = dict(payload)
    for field in PATH_FIELDS:
        value = normalized.get(field)
        if isinstance(value, str) and value:
            normalized[field] = resolve_request_path(request_dir, value)
    return normalized


def require_nonempty_str(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"[ERROR] {field} is required")
    return value


def optional_str_list(payload: dict[str, Any], field: str) -> list[str]:
    value = payload.get(field)
    if value in (None, ""):
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise SystemExit(f"[ERROR] {field} must be a list of non-empty strings")
    return list(value)


def optional_bool(payload: dict[str, Any], field: str) -> bool:
    value = payload.get(field, False)
    if isinstance(value, bool):
        return value
    raise SystemExit(f"[ERROR] {field} must be a boolean when provided")


def optional_int(payload: dict[str, Any], field: str, *, default: int | None = None) -> int | None:
    if field not in payload:
        return default
    value = payload[field]
    if isinstance(value, int):
        return value
    raise SystemExit(f"[ERROR] {field} must be an integer when provided")


def validate_request(payload: dict[str, Any]) -> None:
    schema = payload.get("schema")
    if schema not in (None, REQUEST_SCHEMA):
        raise SystemExit(f"[ERROR] unsupported request schema: {schema}")
    query_type = require_nonempty_str(payload, "query_type")
    if query_type not in SUPPORTED_QUERY_TYPES:
        raise SystemExit(f"[ERROR] unsupported query_type: {query_type}")

    required_fields = [
        "server_source",
        "client_source",
        "server_join_key_field",
        "client_join_key_field",
        "client_value_field",
        "token_scope",
        "job_id",
        "out_base",
        "caller",
        "sse_export_policy_config",
    ]
    for field in required_fields:
        require_nonempty_str(payload, field)

    for list_field in ("server_filters", "client_filters"):
        optional_str_list(payload, list_field)

    for int_field, default in (("k", 20), ("n", 5)):
        value = optional_int(payload, int_field, default=default)
        if value is not None and value <= 0:
            raise SystemExit(f"[ERROR] {int_field} must be > 0")

    for bool_field in (
        "deny_duplicate_query",
        "production_mode",
        "unsafe_allow_no_sse_export_policy",
        "cleanup_sse_export_handoff_files_after_bridge",
    ):
        optional_bool(payload, bool_field)
    handoff_retention_reason = payload.get("handoff_retention_reason")
    if handoff_retention_reason not in (None, ""):
        require_nonempty_str(payload, "handoff_retention_reason")

    secret_method_count = sum(
        1
        for field in ("token_secret", "token_secret_env", "token_secret_key_id", "token_secret_key_name")
        if isinstance(payload.get(field), str) and payload.get(field)
    )
    if secret_method_count != 1:
        raise SystemExit(
            "[ERROR] exactly one of token_secret, token_secret_env, token_secret_key_id, or token_secret_key_name is required"
        )

    token_secret_key_name = payload.get("token_secret_key_name")
    keyring = payload.get("keyring")
    external_kms_config = payload.get("external_kms_config")
    if token_secret_key_name:
        if not keyring and not external_kms_config:
            raise SystemExit("[ERROR] token_secret_key_name requires keyring or external_kms_config")
        if keyring and external_kms_config:
            raise SystemExit("[ERROR] use only one of keyring or external_kms_config with token_secret_key_name")

    if payload.get("token_secret_key_id") and not payload.get("key_manifest"):
        raise SystemExit("[ERROR] token_secret_key_id requires key_manifest")

    if optional_bool(payload, "production_mode") and payload.get("token_secret"):
        raise SystemExit("[ERROR] production_mode forbids token_secret; use token_secret_env or KMS-backed resolution")

    handoff_mode = payload.get("sse_export_handoff_mode", "file")
    if handoff_mode not in {"file", "fifo"}:
        raise SystemExit("[ERROR] sse_export_handoff_mode must be file or fifo")
    cleanup_handoff = optional_bool(payload, "cleanup_sse_export_handoff_files_after_bridge")
    if cleanup_handoff is False:
        if handoff_mode != "file":
            raise SystemExit("[ERROR] cleanup_sse_export_handoff_files_after_bridge=false requires sse_export_handoff_mode=file")
        if not handoff_retention_reason:
            raise SystemExit("[ERROR] handoff_retention_reason is required when cleanup_sse_export_handoff_files_after_bridge=false")
    elif handoff_retention_reason:
        raise SystemExit("[ERROR] handoff_retention_reason is only valid when cleanup_sse_export_handoff_files_after_bridge=false")

    recovery_mode = payload.get("record_recovery_service_mode", "auto")
    if recovery_mode not in {"auto", "manual", "subprocess"}:
        raise SystemExit("[ERROR] record_recovery_service_mode must be auto, manual, or subprocess")


def build_command(payload: dict[str, Any]) -> list[str]:
    cmd = ["bash", str(PIPELINE_SCRIPT)]

    def add_arg(name: str, value: Any) -> None:
        if value in (None, "", []):
            return
        cmd.extend([f"--{name}", str(value)])

    def add_flag(name: str, enabled: bool) -> None:
        if enabled:
            cmd.append(f"--{name}")

    add_arg("server-source", payload.get("server_source"))
    add_arg("client-source", payload.get("client_source"))
    add_arg("server-source-format", payload.get("server_source_format", "jsonl"))
    add_arg("client-source-format", payload.get("client_source_format", "jsonl"))
    add_arg("server-join-key-field", payload.get("server_join_key_field"))
    add_arg("client-join-key-field", payload.get("client_join_key_field"))
    add_arg("client-value-field", payload.get("client_value_field"))
    add_arg("server-normalizer", payload.get("server_normalizer", "identity"))
    add_arg("client-normalizer", payload.get("client_normalizer", "identity"))
    add_arg("client-value-mode", payload.get("client_value_mode", "count"))
    add_arg("server-sse-keyword", payload.get("server_sse_keyword"))
    add_arg("client-sse-keyword", payload.get("client_sse_keyword"))
    add_arg("server-record-id-field", payload.get("server_record_id_field"))
    add_arg("client-record-id-field", payload.get("client_record_id_field"))
    add_arg("server-record-id-format", payload.get("server_record_id_format", "utf8"))
    add_arg("client-record-id-format", payload.get("client_record_id_format", "utf8"))
    add_arg("server-sse-sid", payload.get("server_sse_sid"))
    add_arg("client-sse-sid", payload.get("client_sse_sid"))
    add_arg("server-sse-sname", payload.get("server_sse_sname"))
    add_arg("client-sse-sname", payload.get("client_sse_sname"))
    add_arg("server-record-store-path", payload.get("server_record_store_path"))
    add_arg("client-record-store-path", payload.get("client_record_store_path"))
    add_arg("server-record-store-key-env", payload.get("server_record_store_key_env"))
    add_arg("client-record-store-key-env", payload.get("client_record_store_key_env"))
    add_arg("record-recovery-socket", payload.get("record_recovery_socket"))
    add_arg("record-recovery-endpoint-url", payload.get("record_recovery_endpoint_url"))
    add_arg("record-recovery-auth-env", payload.get("record_recovery_auth_env"))
    add_arg("record-recovery-service-config", payload.get("record_recovery_service_config"))
    add_arg("record-recovery-authz-config", payload.get("record_recovery_authz_config"))
    add_arg("record-recovery-service-id", payload.get("record_recovery_service_id"))
    add_arg("record-recovery-service-audit-log", payload.get("record_recovery_service_audit_log"))
    add_arg("record-recovery-service-log", payload.get("record_recovery_service_log"))
    add_arg("record-recovery-service-health-json", payload.get("record_recovery_service_health_json"))
    add_arg("record-recovery-service-mode", payload.get("record_recovery_service_mode", "auto"))
    add_arg("token-scope", payload.get("token_scope"))
    add_arg("token-secret", payload.get("token_secret"))
    add_arg("token-secret-env", payload.get("token_secret_env"))
    add_arg("token-secret-key-id", payload.get("token_secret_key_id"))
    add_arg("token-secret-key-name", payload.get("token_secret_key_name"))
    add_arg("token-key-version", payload.get("token_key_version"))
    add_arg("key-manifest", payload.get("key_manifest"))
    add_arg("keyring", payload.get("keyring"))
    add_arg("external-kms-config", payload.get("external_kms_config"))
    add_arg("key-access-audit-log", payload.get("key_access_audit_log"))
    add_arg("audit-archive-dir", payload.get("audit_archive_dir"))
    add_arg("pjc-audit-log", payload.get("pjc_audit_log"))
    add_arg("sse-export-policy-config", payload.get("sse_export_policy_config"))
    add_arg("sse-export-audit-log", payload.get("sse_export_audit_log"))
    add_arg("sse-export-handoff-mode", payload.get("sse_export_handoff_mode", "file"))
    add_arg("handoff-retention-reason", payload.get("handoff_retention_reason"))
    add_arg("job-id", payload.get("job_id"))
    add_arg("out-base", payload.get("out_base"))
    add_arg("caller", payload.get("caller"))
    add_arg("tenant-id", payload.get("tenant_id"))
    add_arg("dataset-id", payload.get("dataset_id"))
    add_arg("k", payload.get("k", 20))
    add_arg("n", payload.get("n", 5))
    for item in optional_str_list(payload, "server_filters"):
        add_arg("server-filter", item)
    for item in optional_str_list(payload, "client_filters"):
        add_arg("client-filter", item)
    add_flag("deny-duplicate-query", optional_bool(payload, "deny_duplicate_query"))
    add_flag("production-mode", optional_bool(payload, "production_mode"))
    add_flag("unsafe-allow-no-sse-export-policy", optional_bool(payload, "unsafe_allow_no_sse_export_policy"))
    cleanup_handoff = optional_bool(payload, "cleanup_sse_export_handoff_files_after_bridge")
    if cleanup_handoff is False:
        add_flag("keep-sse-export-handoff-files", True)
    else:
        add_flag("cleanup-sse-export-handoff-files-after-bridge", cleanup_handoff)
    return cmd


def redact_command(cmd: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for item in cmd:
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        redacted.append(item)
        if item == "--token-secret":
            redact_next = True
    return redacted


def summarize_request(payload: dict[str, Any]) -> dict[str, Any]:
    summary = {}
    for key, value in payload.items():
        if key in SECRET_FIELDS and value:
            summary[key] = "<redacted>"
        else:
            summary[key] = value
    return summary


def query_workflow_sidecar_dir(out_base: str) -> Path:
    return Path(out_base) / QUERY_WORKFLOW_DIRNAME


def query_workflow_sidecar_paths(out_base: str) -> dict[str, Path]:
    sidecar_dir = query_workflow_sidecar_dir(out_base)
    return {
        "sidecar_dir": sidecar_dir,
        "submission_manifest": sidecar_dir / SUBMISSION_MANIFEST_FILENAME,
        "execution_receipts": sidecar_dir / EXECUTION_RECEIPTS_FILENAME,
        "status": sidecar_dir / STATUS_FILENAME,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"[ERROR] JSON object expected: {path}")
    return payload


def load_query_workflow_status(out_base: str) -> dict[str, Any]:
    status_path = query_workflow_sidecar_paths(out_base)["status"]
    if not status_path.is_file():
        raise FileNotFoundError(f"query workflow status file does not exist: {status_path}")
    payload = load_json_object(status_path)
    if payload.get("schema") != STATUS_SCHEMA:
        raise ValueError(f"unexpected query workflow status schema: {payload}")
    return payload


def build_artifact_summary(out_base: str) -> dict[str, Any]:
    out_root = Path(out_base)
    sidecar_paths = query_workflow_sidecar_paths(out_base)
    public_report_path = out_root / "a_psi_run" / "public_report.json"
    audit_chain_path = out_root / "audit_chain.json"
    mainline_contract_path = out_root / "mainline_contract_check.json"
    return {
        "submission_manifest_available": sidecar_paths["submission_manifest"].is_file(),
        "execution_receipts_available": sidecar_paths["execution_receipts"].is_file(),
        "status_available": sidecar_paths["status"].is_file(),
        "public_report_available": public_report_path.is_file(),
        "audit_chain_available": audit_chain_path.is_file(),
        "mainline_contract_available": mainline_contract_path.is_file(),
    }


def build_receipt(
    *,
    payload: dict[str, Any],
    mode: str,
    event: str,
    request_digest: str,
    command: list[str],
    exit_code: int | None,
) -> dict[str, Any]:
    event_at_utc = utc_now()
    out_base = str(payload.get("out_base") or "")
    return {
        "schema": RECEIPT_SCHEMA,
        "receipt_id": f"{payload.get('job_id')}-{event}-{event_at_utc}",
        "event": event,
        "event_at_utc": event_at_utc,
        "workflow": "sse_bridge_pipeline",
        "mode": mode,
        "job_id": str(payload.get("job_id") or ""),
        "correlation_id": payload.get("correlation_id"),
        "caller": str(payload.get("caller") or ""),
        "tenant_id": str(payload.get("tenant_id") or ""),
        "dataset_id": str(payload.get("dataset_id") or ""),
        "query_type": payload.get("query_type"),
        "out_base": out_base,
        "request_digest": request_digest,
        "request_summary": summarize_request(payload),
        "command": redact_command(command),
        "exit_code": exit_code,
        "artifacts": build_artifact_summary(out_base),
    }


def build_status(
    *,
    payload: dict[str, Any],
    mode: str,
    state: str,
    terminal: bool,
    latest_receipt: dict[str, Any],
    receipt_count: int,
    exit_code: int | None,
) -> dict[str, Any]:
    out_base = str(payload.get("out_base") or "")
    artifacts = build_artifact_summary(out_base)
    return {
        "schema": STATUS_SCHEMA,
        "workflow": "sse_bridge_pipeline",
        "mode": mode,
        "job_id": str(payload.get("job_id") or ""),
        "correlation_id": payload.get("correlation_id"),
        "caller": str(payload.get("caller") or ""),
        "tenant_id": str(payload.get("tenant_id") or ""),
        "dataset_id": str(payload.get("dataset_id") or ""),
        "query_type": payload.get("query_type"),
        "out_base": out_base,
        "state": state,
        "terminal": terminal,
        "last_updated_at_utc": utc_now(),
        "latest_receipt_id": latest_receipt.get("receipt_id"),
        "receipt_count": receipt_count,
        "last_exit_code": exit_code,
        "artifact_summary": artifacts,
        "public_report_available": artifacts["public_report_available"],
        "audit_chain_available": artifacts["audit_chain_available"],
    }


def render_manifest(
    *,
    request_source: str,
    payload: dict[str, Any],
    command: list[str],
    mode: str,
    exit_code: int | None,
) -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "submitted_at_utc": utc_now(),
        "request_file": request_source,
        "query_type": payload.get("query_type"),
        "workflow": "sse_bridge_pipeline",
        "mode": mode,
        "pipeline_script": str(PIPELINE_SCRIPT),
        "request_summary": summarize_request(payload),
        "command": redact_command(command),
        "exit_code": exit_code,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Submit a limited query workflow request through the existing pipeline adapter.")
    ap.add_argument("--request-file", required=True, help="JSON workflow request file")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Validate the request and emit the planned command without executing it")
    mode.add_argument("--execute", action="store_true", help="Execute the pipeline command after validation")
    ap.add_argument("--manifest-out", default="", help="Optional path to write the submission manifest JSON")
    return ap


def write_manifest(manifest: dict[str, Any], *, manifest_out: str) -> None:
    if not manifest_out:
        return
    out_path = Path(manifest_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def submit_request_payload(
    *,
    raw_payload: dict[str, Any],
    request_source: str,
    request_dir: Path,
    execute: bool,
    manifest_out: str = "",
) -> tuple[dict[str, Any], int | None, dict[str, Any] | None, dict[str, Any] | None]:
    payload = normalize_request_paths(raw_payload, request_dir=request_dir)
    validate_request(payload)
    command = build_command(payload)
    mode = "execute" if execute else "dry_run"
    request_digest = json_sha256(payload)
    out_base = str(payload.get("out_base") or "")
    sidecar_paths = query_workflow_sidecar_paths(out_base) if out_base else {}
    receipt: dict[str, Any] | None = None
    status: dict[str, Any] | None = None
    receipt_count = 0
    exit_code: int | None = None

    if sidecar_paths:
        receipt = build_receipt(
            payload=payload,
            mode=mode,
            event="started" if execute else "accepted",
            request_digest=request_digest,
            command=command,
            exit_code=None,
        )
        append_jsonl(sidecar_paths["execution_receipts"], receipt)
        receipt_count = 1
        status = build_status(
            payload=payload,
            mode=mode,
            state="running" if execute else "accepted",
            terminal=not execute,
            latest_receipt=receipt,
            receipt_count=receipt_count,
            exit_code=None,
        )
        write_json(sidecar_paths["status"], status)

    if execute:
        completed = subprocess.run(command, check=False)
        exit_code = completed.returncode

    manifest = render_manifest(
        request_source=request_source,
        payload=payload,
        command=command,
        mode=mode,
        exit_code=exit_code,
    )
    write_manifest(manifest, manifest_out=manifest_out)
    if sidecar_paths:
        write_json(sidecar_paths["submission_manifest"], manifest)
        if execute:
            receipt = build_receipt(
                payload=payload,
                mode=mode,
                event="completed" if exit_code in (None, 0) else "failed",
                request_digest=request_digest,
                command=command,
                exit_code=exit_code,
            )
            append_jsonl(sidecar_paths["execution_receipts"], receipt)
            receipt_count += 1
        elif receipt is None:
            raise SystemExit("[ERROR] dry-run receipt generation failed")
        status = build_status(
            payload=payload,
            mode=mode,
            state="completed" if exit_code in (None, 0) and execute else "failed" if execute else "accepted",
            terminal=True,
            latest_receipt=receipt,
            receipt_count=receipt_count,
            exit_code=exit_code,
        )
        write_json(sidecar_paths["status"], status)
    return manifest, exit_code, receipt, status


def main() -> int:
    args = build_parser().parse_args()
    request_file = Path(args.request_file)
    if not request_file.is_file():
        raise SystemExit(f"[ERROR] request file does not exist: {request_file}")

    manifest, exit_code, _receipt, _status = submit_request_payload(
        raw_payload=load_request(request_file),
        request_source=str(request_file.resolve()),
        request_dir=request_file.resolve().parent,
        execute=args.execute,
        manifest_out=args.manifest_out,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if exit_code not in (None, 0):
        raise SystemExit(exit_code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
