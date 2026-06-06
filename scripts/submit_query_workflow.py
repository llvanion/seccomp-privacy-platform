#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from metadata_db import connect_db, apply_migrations
from query_workflow_execution_store import (
    DEFAULT_LEASE_SECONDS,
    claim_execution,
    enqueue_execution,
    finish_execution,
    heartbeat_execution,
    lease_owner,
)


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
    "privacy_budget_config",
    "privacy_budget_ledger",
    "privacy_budget_approval_queue",
    "release_policy_gate_config",
    "release_policy_gate_report",
    "pjc_evidence_merge",
    "external_anchor_report",
    "operator_report_path",
    "out_base",
    "key_access_audit_log",
    "audit_archive_dir",
    "pjc_audit_log",
    "pjc_resource_limits",
    "source_attestation_signing_key_path",
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


def normalized_identity(value: Any) -> str:
    text = str(value or "").strip()
    return text.casefold() if text else ""


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


def optional_number(payload: dict[str, Any], field: str, *, default: float | None = None) -> float | None:
    if field not in payload:
        return default
    value = payload[field]
    if isinstance(value, bool):
        raise SystemExit(f"[ERROR] {field} must be a number when provided")
    if isinstance(value, (int, float)):
        return float(value)
    raise SystemExit(f"[ERROR] {field} must be a number when provided")


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
    client_value_min = optional_int(payload, "client_value_min")
    client_value_max = optional_int(payload, "client_value_max")
    if client_value_min is not None and client_value_max is not None and client_value_min > client_value_max:
        raise SystemExit("[ERROR] client_value_min cannot be greater than client_value_max")
    client_allowed_value_fields = optional_str_list(payload, "client_allowed_value_fields")
    client_value_unit = payload.get("client_value_unit")
    if client_value_unit not in (None, ""):
        require_nonempty_str(payload, "client_value_unit")
    client_value_currency = payload.get("client_value_currency")
    if client_value_currency not in (None, ""):
        require_nonempty_str(payload, "client_value_currency")

    for bool_field in (
        "deny_duplicate_query",
        "production_mode",
        "unsafe_allow_no_sse_export_policy",
        "cleanup_sse_export_handoff_files_after_bridge",
        "privacy_budget_required",
        "policy_require_dp",
        "public_report_redact_operator_fields",
        "client_value_allow_negative",
    ):
        optional_bool(payload, bool_field)
    if payload.get("source_system") not in (None, ""):
        require_nonempty_str(payload, "source_system")
    if payload.get("source_attestation_mode") not in (None, ""):
        mode = require_nonempty_str(payload, "source_attestation_mode")
        if mode not in {"planned", "local", "manual", "operator", "external"}:
            raise SystemExit("[ERROR] source_attestation_mode must be planned, local, manual, operator, or external")
    if payload.get("source_attestation_approval_id") not in (None, ""):
        require_nonempty_str(payload, "source_attestation_approval_id")
    if payload.get("source_attestation_operator_identity") not in (None, ""):
        require_nonempty_str(payload, "source_attestation_operator_identity")
    if payload.get("source_attestation_reviewer_identity") not in (None, ""):
        require_nonempty_str(payload, "source_attestation_reviewer_identity")
    if payload.get("source_attestation_signoff_status") not in (None, ""):
        signoff_status = require_nonempty_str(payload, "source_attestation_signoff_status")
        if signoff_status not in {"planned", "pending", "approved", "approved_dual", "rejected"}:
            raise SystemExit("[ERROR] source_attestation_signoff_status must be planned, pending, approved, approved_dual, or rejected")
        if signoff_status == "approved_dual" and not payload.get("source_attestation_reviewer_identity"):
            raise SystemExit("[ERROR] source_attestation_reviewer_identity is required when source_attestation_signoff_status=approved_dual")
        if (
            signoff_status == "approved_dual"
            and normalized_identity(payload.get("source_attestation_operator_identity"))
            and normalized_identity(payload.get("source_attestation_operator_identity"))
            == normalized_identity(payload.get("source_attestation_reviewer_identity"))
        ):
            raise SystemExit("[ERROR] source_attestation_reviewer_identity must differ from source_attestation_operator_identity")
    if payload.get("source_attestation_signing_key_path") not in (None, ""):
        require_nonempty_str(payload, "source_attestation_signing_key_path")
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

    privacy_budget_required = optional_bool(payload, "privacy_budget_required")
    privacy_budget_config = payload.get("privacy_budget_config")
    privacy_budget_ledger = payload.get("privacy_budget_ledger")
    privacy_budget_approval_queue = payload.get("privacy_budget_approval_queue")
    if privacy_budget_config not in (None, ""):
        privacy_budget_config = require_nonempty_str(payload, "privacy_budget_config")
    if privacy_budget_ledger not in (None, ""):
        privacy_budget_ledger = require_nonempty_str(payload, "privacy_budget_ledger")
    if privacy_budget_approval_queue not in (None, ""):
        privacy_budget_approval_queue = require_nonempty_str(payload, "privacy_budget_approval_queue")
    if privacy_budget_required:
        if not privacy_budget_config:
            raise SystemExit("[ERROR] privacy_budget_required=true requires privacy_budget_config")
        if not privacy_budget_ledger:
            raise SystemExit("[ERROR] privacy_budget_required=true requires privacy_budget_ledger")
    if privacy_budget_config and not privacy_budget_ledger:
        raise SystemExit("[ERROR] privacy_budget_config requires privacy_budget_ledger")
    if privacy_budget_approval_queue and not privacy_budget_ledger:
        raise SystemExit("[ERROR] privacy_budget_approval_queue requires privacy_budget_ledger")
    if payload.get("privacy_budget_purpose") not in (None, ""):
        require_nonempty_str(payload, "privacy_budget_purpose")
    privacy_budget_limit = optional_number(payload, "privacy_budget_limit")
    if privacy_budget_limit is not None and privacy_budget_limit < 0:
        raise SystemExit("[ERROR] privacy_budget_limit must be >= 0")
    privacy_budget_cost = optional_number(payload, "privacy_budget_cost")
    if privacy_budget_cost is not None and privacy_budget_cost <= 0:
        raise SystemExit("[ERROR] privacy_budget_cost must be > 0")
    if payload.get("release_policy_gate_config") not in (None, ""):
        require_nonempty_str(payload, "release_policy_gate_config")
    if payload.get("release_policy_gate_report") not in (None, ""):
        require_nonempty_str(payload, "release_policy_gate_report")
    if payload.get("pjc_evidence_merge") not in (None, ""):
        require_nonempty_str(payload, "pjc_evidence_merge")
    if payload.get("external_anchor_report") not in (None, ""):
        require_nonempty_str(payload, "external_anchor_report")
    if payload.get("operator_report_path") not in (None, ""):
        require_nonempty_str(payload, "operator_report_path")
    dp_epsilon = optional_number(payload, "dp_epsilon")
    if dp_epsilon is not None and dp_epsilon <= 0:
        raise SystemExit("[ERROR] dp_epsilon must be > 0")
    dp_sensitivity = optional_int(payload, "dp_sensitivity")
    if dp_sensitivity is not None and dp_sensitivity <= 0:
        raise SystemExit("[ERROR] dp_sensitivity must be > 0")
    if optional_bool(payload, "policy_require_dp"):
        if dp_epsilon is None:
            raise SystemExit("[ERROR] policy_require_dp=true requires dp_epsilon")
        if dp_sensitivity is None:
            raise SystemExit("[ERROR] policy_require_dp=true requires dp_sensitivity")
    if optional_bool(payload, "production_mode") and not payload.get("pjc_resource_limits"):
        raise SystemExit("[ERROR] production_mode requires pjc_resource_limits")
    if optional_bool(payload, "production_mode") and not payload.get("release_policy_gate_config"):
        raise SystemExit("[ERROR] production_mode requires release_policy_gate_config")
    if (
        optional_bool(payload, "production_mode")
        and release_gate_requires_external_anchor(str(payload.get("release_policy_gate_config") or ""))
        and not payload.get("external_anchor_report")
    ):
        raise SystemExit("[ERROR] production_mode release gate requires external_anchor_report")
    if (
        optional_bool(payload, "production_mode")
        and payload.get("client_value_mode", "count") == "raw-int"
        and client_value_max is None
    ):
        raise SystemExit("[ERROR] production_mode raw-int requires client_value_max")
    release_gate_config = str(payload.get("release_policy_gate_config") or "")
    release_gate_requirements = load_release_gate_requirements(release_gate_config) if release_gate_config else {}
    require_source_attestation = bool(release_gate_requirements.get("require_source_attestation"))
    require_signed_signoff = bool(release_gate_requirements.get("require_signed_signoff"))
    require_dual_signoff = bool(release_gate_requirements.get("require_dual_signoff"))
    require_bound_input_commitment = bool(release_gate_requirements.get("require_bound_input_commitment"))
    if optional_bool(payload, "production_mode") and (require_source_attestation or require_signed_signoff or require_dual_signoff or require_bound_input_commitment):
        required_source_fields = [
            "source_system",
            "source_attestation_mode",
            "source_attestation_approval_id",
            "source_attestation_operator_identity",
            "source_attestation_signoff_status",
        ]
        missing_source_fields = [field for field in required_source_fields if not payload.get(field)]
        if missing_source_fields:
            raise SystemExit(
                "[ERROR] release policy gate requires source attestation fields: "
                + ", ".join(missing_source_fields)
            )
        if require_signed_signoff and not payload.get("source_attestation_signing_key_path"):
            raise SystemExit("[ERROR] release policy gate requires source_attestation_signing_key_path for signed signoff")
        if require_dual_signoff and payload.get("source_attestation_signoff_status") != "approved_dual":
            raise SystemExit("[ERROR] release policy gate requires source_attestation_signoff_status=approved_dual")
        if require_dual_signoff and not payload.get("source_attestation_reviewer_identity"):
            raise SystemExit("[ERROR] release policy gate requires source_attestation_reviewer_identity for dual signoff")
    if optional_bool(payload, "production_mode") and payload.get("client_value_mode", "count") == "raw-int":
        client_value_field = payload.get("client_value_field")
        if not client_allowed_value_fields:
            raise SystemExit("[ERROR] production_mode raw-int requires client_allowed_value_fields")
        if client_value_field not in client_allowed_value_fields:
            raise SystemExit("[ERROR] client_value_field must be listed in client_allowed_value_fields")
        if not client_value_unit:
            raise SystemExit("[ERROR] production_mode raw-int requires client_value_unit")
        if client_value_unit == "minor_currency_unit":
            if not isinstance(client_value_currency, str) or not client_value_currency.strip():
                raise SystemExit("[ERROR] client_value_unit=minor_currency_unit requires client_value_currency")
            currency = client_value_currency.strip().upper()
            if len(currency) != 3 or not currency.isalpha():
                raise SystemExit("[ERROR] client_value_currency must be a 3-letter ISO 4217 code")


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
    add_arg("client-value-min", payload.get("client_value_min"))
    add_arg("client-value-max", payload.get("client_value_max"))
    add_flag("client-value-allow-negative", optional_bool(payload, "client_value_allow_negative") is True)
    for field in optional_str_list(payload, "client_allowed_value_fields"):
        add_arg("client-allowed-value-field", field)
    add_arg("client-value-unit", payload.get("client_value_unit"))
    add_arg("client-value-currency", payload.get("client_value_currency"))
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
    add_arg("pjc-resource-limits", payload.get("pjc_resource_limits"))
    add_arg("sse-export-policy-config", payload.get("sse_export_policy_config"))
    add_arg("sse-export-audit-log", payload.get("sse_export_audit_log"))
    add_arg("sse-export-handoff-mode", payload.get("sse_export_handoff_mode", "file"))
    add_arg("handoff-retention-reason", payload.get("handoff_retention_reason"))
    add_arg("job-id", payload.get("job_id"))
    add_arg("out-base", payload.get("out_base"))
    add_arg("caller", payload.get("caller"))
    add_arg("tenant-id", payload.get("tenant_id"))
    add_arg("dataset-id", payload.get("dataset_id"))
    add_arg("source-system", payload.get("source_system"))
    add_arg("source-attestation-mode", payload.get("source_attestation_mode"))
    add_arg("source-attestation-approval-id", payload.get("source_attestation_approval_id"))
    add_arg("source-attestation-operator-identity", payload.get("source_attestation_operator_identity"))
    add_arg("source-attestation-reviewer-identity", payload.get("source_attestation_reviewer_identity"))
    add_arg("source-attestation-signoff-status", payload.get("source_attestation_signoff_status"))
    add_arg("source-attestation-signing-key-path", payload.get("source_attestation_signing_key_path"))
    add_arg("privacy-budget-config", payload.get("privacy_budget_config"))
    add_arg("privacy-budget-ledger", payload.get("privacy_budget_ledger"))
    add_arg("privacy-budget-approval-queue", payload.get("privacy_budget_approval_queue"))
    add_arg("privacy-budget-purpose", payload.get("privacy_budget_purpose"))
    add_arg("privacy-budget-limit", payload.get("privacy_budget_limit"))
    add_arg("privacy-budget-cost", payload.get("privacy_budget_cost"))
    add_arg("release-policy-gate-config", payload.get("release_policy_gate_config"))
    add_arg("release-policy-gate-report", payload.get("release_policy_gate_report"))
    add_arg("pjc-evidence-merge", payload.get("pjc_evidence_merge"))
    add_arg("external-anchor-report", payload.get("external_anchor_report"))
    add_arg("dp-epsilon", payload.get("dp_epsilon"))
    add_arg("dp-sensitivity", payload.get("dp_sensitivity"))
    add_arg("operator-report-path", payload.get("operator_report_path"))
    add_arg("k", payload.get("k", 20))
    add_arg("n", payload.get("n", 5))
    for item in optional_str_list(payload, "server_filters"):
        add_arg("server-filter", item)
    for item in optional_str_list(payload, "client_filters"):
        add_arg("client-filter", item)
    add_flag("deny-duplicate-query", optional_bool(payload, "deny_duplicate_query"))
    add_flag("privacy-budget-required", optional_bool(payload, "privacy_budget_required"))
    add_flag("require-dp", optional_bool(payload, "policy_require_dp"))
    add_flag("public-report-redact-operator-fields", optional_bool(payload, "public_report_redact_operator_fields"))
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


def release_gate_requires_external_anchor(path: str) -> bool:
    return bool(load_release_gate_requirements(path).get("require_external_anchor"))


def load_release_gate_requirements(path: str) -> dict[str, Any]:
    if not path:
        return {}
    config_path = Path(path)
    if not config_path.is_file():
        raise SystemExit(f"[ERROR] release_policy_gate_config does not exist: {config_path}")
    try:
        payload = load_json_object(config_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"[ERROR] release_policy_gate_config is not valid JSON: {config_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"[ERROR] release_policy_gate_config must be a JSON object: {config_path}")
    return payload


def load_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not path.is_file():
        return result
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL receipt at {path}:{line_no}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"query workflow receipt at {path}:{line_no} must be an object")
        result.append(payload)
    return result


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
    error_class: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    event_at_utc = utc_now()
    out_base = str(payload.get("out_base") or "")
    receipt = {
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
    if error_class:
        receipt["error_class"] = error_class
    if error_message:
        receipt["error"] = error_message
    return receipt


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


def assert_workflow_sidecar_start_allowed(
    *,
    payload: dict[str, Any],
    sidecar_paths: dict[str, Path],
    request_digest: str,
    execute: bool,
) -> tuple[int, dict[str, Any] | None]:
    """Fail closed when a workflow sidecar already represents a live/terminal run.

    A dry-run creates an ``accepted`` terminal sidecar that an execute call may
    later claim only if the request digest matches. All other states require a
    new out_base/job_id so an accidental retry cannot overwrite evidence.
    """
    status_path = sidecar_paths.get("status")
    receipts_path = sidecar_paths.get("execution_receipts")
    if status_path is None or not status_path.is_file():
        return 0, None
    status = load_json_object(status_path)
    if status.get("schema") != STATUS_SCHEMA:
        raise RuntimeError(f"existing workflow status has unexpected schema: {status_path}")
    receipts = load_jsonl_objects(receipts_path) if receipts_path is not None else []
    last_receipt = receipts[-1] if receipts else None
    existing_digest = last_receipt.get("request_digest") if isinstance(last_receipt, dict) else None
    existing_state = str(status.get("state") or "")
    existing_job_id = status.get("job_id")
    requested_job_id = str(payload.get("job_id") or "")

    if (
        execute
        and existing_state == "accepted"
        and status.get("terminal") is True
        and existing_digest == request_digest
        and existing_job_id == requested_job_id
    ):
        return len(receipts), status

    raise RuntimeError(
        "query workflow sidecar already exists for "
        f"out_base={payload.get('out_base')!r} state={existing_state!r} "
        f"job_id={existing_job_id!r}; use a new out_base/job_id or resume via the "
        "approved relaunch path"
    )


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
    mode.add_argument("--enqueue", action="store_true", help="Queue the request in metadata DB for a worker instead of running it inline")
    ap.add_argument("--manifest-out", default="", help="Optional path to write the submission manifest JSON")
    ap.add_argument("--metadata-db-path", default="", help="Optional metadata DB path for DB-backed execution lifecycle state")
    ap.add_argument("--metadata-db-dsn", default="", help="Optional PostgreSQL DSN for DB-backed execution lifecycle state")
    ap.add_argument("--workflow-lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS)
    ap.add_argument("--workflow-steal-expired", action="store_true", default=False)
    return ap


def write_manifest(manifest: dict[str, Any], *, manifest_out: str) -> None:
    if not manifest_out:
        return
    out_path = Path(manifest_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sidecar_paths_for_payload(payload: dict[str, Any]) -> dict[str, Path]:
    out_base = payload.get("out_base")
    if not isinstance(out_base, str) or not out_base:
        return {}
    return query_workflow_sidecar_paths(out_base)


def submit_request_payload(
    *,
    raw_payload: dict[str, Any],
    request_source: str,
    request_dir: Path,
    execute: bool,
    enqueue: bool = False,
    manifest_out: str = "",
    metadata_db_path: str = "",
    metadata_db_dsn: str = "",
    workflow_lease_seconds: int = DEFAULT_LEASE_SECONDS,
    workflow_steal_expired: bool = False,
) -> tuple[dict[str, Any], int | None, dict[str, Any] | None, dict[str, Any] | None]:
    payload = normalize_request_paths(raw_payload, request_dir=request_dir)
    if execute and enqueue:
        raise SystemExit("[ERROR] execute and enqueue are mutually exclusive")
    mode = "execute" if (execute or enqueue) else "dry_run"
    request_digest = json_sha256(payload)
    sidecar_paths = sidecar_paths_for_payload(payload)
    receipt: dict[str, Any] | None = None
    status: dict[str, Any] | None = None
    receipt_count = 0
    exit_code: int | None = None
    command: list[str] = []
    db_conn = None
    execution_owner = ""
    job_id = ""

    try:
        validate_request(payload)
        command = build_command(payload)
    except SystemExit:
        manifest = render_manifest(
            request_source=request_source,
            payload=payload,
            command=command,
            mode=mode,
            exit_code=None,
        )
        write_manifest(manifest, manifest_out=manifest_out)
        raise

    if sidecar_paths:
        try:
            receipt_count, _existing_status = assert_workflow_sidecar_start_allowed(
                payload=payload,
                sidecar_paths=sidecar_paths,
                request_digest=request_digest,
                execute=execute or enqueue,
            )
        except RuntimeError as exc:
            raise SystemExit(f"[ERROR] {exc}") from exc

    if enqueue and not (metadata_db_path or metadata_db_dsn):
        raise SystemExit("[ERROR] --enqueue requires --metadata-db-path or --metadata-db-dsn")

    if enqueue:
        job_id = str(payload.get("job_id") or "")
        execution_owner = lease_owner("submit-query-workflow-enqueue")
        db_conn = connect_db(metadata_db_path, dsn=metadata_db_dsn)
        apply_migrations(db_conn)
        artifact_paths = {
            "status_path": str(sidecar_paths["status"]) if sidecar_paths else "",
            "receipts_path": str(sidecar_paths["execution_receipts"]) if sidecar_paths else "",
            "submission_manifest_path": str(sidecar_paths["submission_manifest"]) if sidecar_paths else "",
        }
        try:
            enqueue_execution(
                db_conn,
                job_id=job_id,
                out_base=str(payload.get("out_base") or ""),
                request_digest=request_digest,
                request_source=request_source,
                caller=str(payload.get("caller") or ""),
                tenant_id=str(payload.get("tenant_id") or ""),
                dataset_id=str(payload.get("dataset_id") or ""),
                mode=mode,
                owner=execution_owner,
                artifact_paths=artifact_paths,
                metadata={
                    "entrypoint": "submit_query_workflow",
                    "raw_payload": payload,
                    "request_dir": str(request_dir),
                    "command": redact_command(command),
                },
            )
        except RuntimeError as exc:
            db_conn.close()
            raise SystemExit(f"[ERROR] {exc}") from exc

    if execute and (metadata_db_path or metadata_db_dsn):
        job_id = str(payload.get("job_id") or "")
        execution_owner = lease_owner("submit-query-workflow")
        db_conn = connect_db(metadata_db_path, dsn=metadata_db_dsn)
        apply_migrations(db_conn)
        artifact_paths = {
            "status_path": str(sidecar_paths["status"]) if sidecar_paths else "",
            "receipts_path": str(sidecar_paths["execution_receipts"]) if sidecar_paths else "",
            "submission_manifest_path": str(sidecar_paths["submission_manifest"]) if sidecar_paths else "",
        }
        try:
            claim_execution(
                db_conn,
                job_id=job_id,
                out_base=str(payload.get("out_base") or ""),
                request_digest=request_digest,
                request_source=request_source,
                caller=str(payload.get("caller") or ""),
                tenant_id=str(payload.get("tenant_id") or ""),
                dataset_id=str(payload.get("dataset_id") or ""),
                mode=mode,
                owner=execution_owner,
                lease_seconds=workflow_lease_seconds,
                steal_expired=workflow_steal_expired,
                artifact_paths=artifact_paths,
                metadata={"entrypoint": "submit_query_workflow"},
            )
        except RuntimeError as exc:
            db_conn.close()
            raise SystemExit(f"[ERROR] {exc}") from exc

    if sidecar_paths:
        try:
            receipt = build_receipt(
                payload=payload,
                mode=mode,
                event="started" if execute else "queued" if enqueue else "accepted",
                request_digest=request_digest,
                command=command,
                exit_code=None,
            )
            append_jsonl(sidecar_paths["execution_receipts"], receipt)
            receipt_count += 1
            status = build_status(
                payload=payload,
                mode=mode,
                state="running" if execute else "queued" if enqueue else "accepted",
                terminal=not execute and not enqueue,
                latest_receipt=receipt,
                receipt_count=receipt_count,
                exit_code=None,
            )
            write_json(sidecar_paths["status"], status)
        except BaseException as exc:
            if db_conn is not None:
                if execute:
                    finish_execution(
                        db_conn,
                        job_id=job_id,
                        owner=execution_owner,
                        exit_code=127,
                        state="failed",
                        metadata={"error_class": "sidecar_write_failed", "error": str(exc)},
                    )
                elif enqueue:
                    finish_execution(
                        db_conn,
                        job_id=job_id,
                        owner=execution_owner,
                        exit_code=127,
                        state="failed",
                        metadata={"error_class": "sidecar_write_failed", "error": str(exc)},
                    )
                db_conn.close()
            raise

    if execute:
        try:
            if db_conn is not None:
                heartbeat_execution(
                    db_conn,
                    job_id=job_id,
                    owner=execution_owner,
                    lease_seconds=workflow_lease_seconds,
                )
            completed = subprocess.run(command, check=False)
            exit_code = completed.returncode
        except OSError as exc:
            exit_code = 127
            failure_message = str(exc)
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
                receipt = build_receipt(
                    payload=payload,
                    mode=mode,
                    event="failed",
                    request_digest=request_digest,
                    command=command,
                    exit_code=exit_code,
                    error_class="launch_failed",
                    error_message=failure_message,
                )
                append_jsonl(sidecar_paths["execution_receipts"], receipt)
                receipt_count += 1
                status = build_status(
                    payload=payload,
                    mode=mode,
                    state="failed",
                    terminal=True,
                    latest_receipt=receipt,
                    receipt_count=receipt_count,
                    exit_code=exit_code,
                )
                write_json(sidecar_paths["status"], status)
            if db_conn is not None:
                finish_execution(
                    db_conn,
                    job_id=job_id,
                    owner=execution_owner,
                    exit_code=exit_code,
                    state="failed",
                    metadata={"error_class": "launch_failed", "error": failure_message},
                )
                db_conn.close()
            return manifest, exit_code, receipt, status
        except BaseException as exc:
            if db_conn is not None:
                finish_execution(
                    db_conn,
                    job_id=job_id,
                    owner=execution_owner,
                    exit_code=127,
                    state="failed",
                    metadata={"error_class": "run_exception", "error": str(exc)},
                )
                db_conn.close()
            raise

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
            error_class = "run_failed" if exit_code not in (None, 0) else None
            receipt = build_receipt(
                payload=payload,
                mode=mode,
                event="completed" if exit_code in (None, 0) else "failed",
                request_digest=request_digest,
                command=command,
                exit_code=exit_code,
                error_class=error_class,
            )
            append_jsonl(sidecar_paths["execution_receipts"], receipt)
            receipt_count += 1
        elif receipt is None:
            raise SystemExit("[ERROR] dry-run receipt generation failed")
        status = build_status(
            payload=payload,
            mode=mode,
            state="completed" if exit_code in (None, 0) and execute else "failed" if execute else "queued" if enqueue else "accepted",
            terminal=False if enqueue else True,
            latest_receipt=receipt,
            receipt_count=receipt_count,
            exit_code=exit_code,
        )
        write_json(sidecar_paths["status"], status)
    if execute and db_conn is not None:
        finish_execution(
            db_conn,
            job_id=job_id,
            owner=execution_owner,
            exit_code=exit_code,
            metadata={"entrypoint": "submit_query_workflow"},
        )
        db_conn.close()
    elif enqueue and db_conn is not None:
        db_conn.close()
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
        enqueue=args.enqueue,
        manifest_out=args.manifest_out,
        metadata_db_path=args.metadata_db_path,
        metadata_db_dsn=args.metadata_db_dsn,
        workflow_lease_seconds=args.workflow_lease_seconds,
        workflow_steal_expired=args.workflow_steal_expired,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if exit_code not in (None, 0):
        raise SystemExit(exit_code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
