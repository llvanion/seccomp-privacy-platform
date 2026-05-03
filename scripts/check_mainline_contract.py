#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_RECORD_RECOVERY_BOUNDARIES = {"worker_subprocess", "service_socket", "service_http"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError(f"{path}:{line_no} must contain a JSON object")
            records.append(data)
    return records


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", []):
            return value
    return None


def stringify(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def role_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        role = stringify(record.get("role"))
        if role:
            result[role] = record
    return result


def add_finding(
    findings: list[dict[str, Any]],
    *,
    kind: str,
    message: str,
    path: str,
    expected: Any = None,
    actual: Any = None,
) -> None:
    findings.append(
        {
            "severity": "error",
            "kind": kind,
            "path": path,
            "message": message,
            "expected": expected,
            "actual": actual,
        }
    )


def check_equal(
    findings: list[dict[str, Any]],
    *,
    label: str,
    expected: Any,
    actual: Any,
    path: str,
) -> None:
    if expected in (None, "") or actual in (None, ""):
        return
    if str(expected) != str(actual):
        add_finding(
            findings,
            kind=f"{label}_mismatch",
            message=f"{label} does not match canonical value",
            path=path,
            expected=expected,
            actual=actual,
        )


def check_exact_equal(
    findings: list[dict[str, Any]],
    *,
    label: str,
    expected: Any,
    actual: Any,
    path: str,
) -> None:
    if expected in (None, "", []) or actual in (None, "", []):
        return
    if expected != actual:
        add_finding(
            findings,
            kind=f"{label}_mismatch",
            message=f"{label} does not match canonical value",
            path=path,
            expected=expected,
            actual=actual,
        )


def check_required_non_empty(
    findings: list[dict[str, Any]],
    *,
    label: str,
    value: Any,
    path: str,
) -> None:
    if value in (None, ""):
        add_finding(
            findings,
            kind=f"missing_{label}",
            message=f"required field {label} is missing",
            path=path,
        )


def role_exposure_risk(*, output_file_type: str | None, cleanup_status: str | None) -> str:
    if output_file_type == "fifo" and cleanup_status == "removed":
        return "none"
    if output_file_type == "file" and cleanup_status == "cleaned":
        return "low"
    if output_file_type == "file" and cleanup_status == "retained":
        return "elevated"
    return "unknown"


def build_exposure_assessment(
    *,
    handoff_mode: str | None,
    server_cleanup: dict[str, Any],
    client_cleanup: dict[str, Any],
) -> dict[str, Any]:
    server_type = stringify(server_cleanup.get("output_file_type"))
    server_status = stringify(server_cleanup.get("status"))
    client_type = stringify(client_cleanup.get("output_file_type"))
    client_status = stringify(client_cleanup.get("status"))

    server_risk = role_exposure_risk(output_file_type=server_type, cleanup_status=server_status)
    client_risk = role_exposure_risk(output_file_type=client_type, cleanup_status=client_status)

    role_risks = {server_risk, client_risk}
    if "elevated" in role_risks:
        overall_risk = "elevated"
    elif role_risks <= {"none", "low"}:
        overall_risk = "low" if "low" in role_risks else "none"
    else:
        overall_risk = "unknown"

    return {
        "handoff_mode": handoff_mode,
        "plaintext_exposure_risk": overall_risk,
        "server_exposure": {
            "output_file_type": server_type,
            "cleanup_status": server_status,
            "exposure_risk": server_risk,
        },
        "client_exposure": {
            "output_file_type": client_type,
            "cleanup_status": client_status,
            "exposure_risk": client_risk,
        },
    }


def build_result(
    *,
    out_base: Path,
    job_id: str,
    canonical_scope: dict[str, Any],
    handoff_mode: str | None,
    handoff_cleanup: dict[str, Any],
    handoff_exposure_assessment: dict[str, Any],
    findings: list[dict[str, Any]],
    checks_run: int,
) -> dict[str, Any]:
    return {
        "schema": "mainline_contract_check/v1",
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "out_base": str(out_base),
        "job_id": job_id,
        "status": "ok" if not findings else "fail",
        "canonical_scope": canonical_scope,
        "handoff_mode": handoff_mode,
        "handoff_exposure_assessment": handoff_exposure_assessment,
        "handoff_cleanup": handoff_cleanup,
        "summary": {
            "checks_run": checks_run,
            "error_count": len(findings),
        },
        "findings": findings,
    }


def is_managed_sse_handoff_path(*, out_base: Path, output_file: str | None) -> bool:
    if not output_file:
        return False
    try:
        Path(output_file).resolve().relative_to((out_base / "sse_exports").resolve())
    except ValueError:
        return False
    return True


def summarize_handoff_cleanup(
    *,
    out_base: Path,
    role_name: str,
    export_record: dict[str, Any],
    findings: list[dict[str, Any]],
    allow_retained_managed_handoff: bool,
    retained_managed_handoff_reason: str | None,
) -> tuple[dict[str, Any], int]:
    if not export_record:
        return {
            "role": role_name,
            "output_file": None,
            "output_file_type": None,
            "managed_by_out_base": False,
            "exists_after_run": None,
            "status": "not_applicable",
        }, 0

    checks_run = 0
    output_file = stringify(export_record.get("output_file"))
    output_file_type = stringify(export_record.get("output_file_type"))
    managed_by_out_base = is_managed_sse_handoff_path(out_base=out_base, output_file=output_file)
    exists_after_run = None
    if output_file:
        exists_after_run = Path(output_file).exists()

    if output_file_type not in {"file", "fifo"}:
        status = "not_applicable"
    elif not output_file:
        status = "missing_output_file"
    elif not managed_by_out_base:
        status = "not_managed"
    elif exists_after_run:
        status = "retained"
    elif output_file_type == "file":
        status = "cleaned"
    else:
        status = "removed"

    retained_is_allowed = (
        allow_retained_managed_handoff
        and output_file_type == "file"
        and managed_by_out_base
        and exists_after_run is True
    )
    retention_reason = retained_managed_handoff_reason if status == "retained" else None

    if managed_by_out_base and output_file_type in {"file", "fifo"}:
        checks_run += 1
        if exists_after_run and not retained_is_allowed:
            kind = f"{role_name}_handoff_artifact_persisted"
            message = "managed SSE handoff artifact still exists after bridge run"
            if output_file_type == "file":
                message = "managed plaintext SSE handoff file still exists after bridge run"
            add_finding(
                findings,
                kind=kind,
                message=message,
                path=f"sse_exports/export_audit.jsonl:{role_name}",
                expected="absent",
                actual=output_file,
            )
        elif retained_is_allowed and not retention_reason:
            add_finding(
                findings,
                kind=f"{role_name}_handoff_retention_reason_missing",
                message="retained managed plaintext SSE handoff file is missing an explicit retention reason",
                path=f"sse_exports/export_audit.jsonl:{role_name}",
                expected="non-empty retained handoff reason",
                actual=retention_reason,
            )

    return {
        "role": role_name,
        "output_file": output_file,
        "output_file_type": output_file_type,
        "managed_by_out_base": managed_by_out_base,
        "exists_after_run": exists_after_run,
        "status": status,
        "retention_reason": retention_reason,
    }, checks_run


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Check owner-frozen mainline contract consistency across a completed run directory."
    )
    ap.add_argument("--out-base", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-findings", action="store_true")
    ap.add_argument(
        "--allow-retained-managed-handoff",
        action="store_true",
        help="Treat retained managed file-mode SSE handoff artifacts as an allowed compatibility mode.",
    )
    ap.add_argument(
        "--retained-managed-handoff-reason",
        default="",
        help="Explicit justification recorded when retained managed file-mode SSE handoff artifacts are allowed.",
    )
    args = ap.parse_args()

    out_base = Path(args.out_base).resolve()
    job_id = str(args.job_id)
    retained_managed_handoff_reason = str(args.retained_managed_handoff_reason or "").strip() or None
    findings: list[dict[str, Any]] = []
    checks_run = 0

    audit_chain = load_json(out_base / "audit_chain.json") or {}
    public_report = load_json(out_base / "a_psi_run" / "public_report.json") or {}
    policy_records = load_jsonl(out_base / "a_psi_run" / "audit_log.jsonl")
    policy_record = policy_records[-1] if policy_records else {}
    bridge_meta = load_json(out_base / "bridge_job" / "job_meta.json") or {}
    bridge_records = load_jsonl(out_base / "bridge_job" / "bridge_audit.jsonl")
    bridge_record = bridge_records[-1] if bridge_records else {}
    sse_records = load_jsonl(out_base / "sse_exports" / "export_audit.jsonl")
    sse_by_role = role_records(sse_records)
    service_config = load_json(out_base / "sse_exports" / "record_recovery_service_config.json") or {}
    service_health = load_json(out_base / "sse_exports" / "record_recovery_service_health.json") or {}
    default_service_audit_path = out_base / "sse_exports" / "record_recovery_service_audit.jsonl"
    configured_service_audit_path = Path(stringify(service_config.get("audit_log")) or "")
    if configured_service_audit_path and configured_service_audit_path.is_file():
        service_audit_path = configured_service_audit_path
    elif default_service_audit_path.is_file():
        service_audit_path = default_service_audit_path
    elif configured_service_audit_path:
        service_audit_path = configured_service_audit_path
    else:
        service_audit_path = default_service_audit_path
    service_audit_path_label = str(service_audit_path)
    service_audits = load_jsonl(service_audit_path)
    service_by_role = role_records(service_audits)
    service_audit = service_audits[-1] if service_audits else {}

    canonical_correlation_id = stringify(
        first_non_empty(
            audit_chain.get("correlation_id"),
            public_report.get("correlation_id"),
            policy_record.get("correlation_id"),
            bridge_record.get("correlation_id"),
            job_id,
        )
    )
    canonical_caller = stringify(
        first_non_empty(
            public_report.get("caller"),
            policy_record.get("caller"),
            sse_by_role.get("client", {}).get("caller"),
            sse_by_role.get("server", {}).get("caller"),
            service_by_role.get("client", {}).get("caller"),
            service_by_role.get("server", {}).get("caller"),
            service_audit.get("caller"),
        )
    )
    canonical_tenant_id = stringify(
        first_non_empty(
            service_config.get("tenant_id"),
            service_health.get("tenant_id"),
            service_by_role.get("client", {}).get("tenant_id"),
            service_by_role.get("server", {}).get("tenant_id"),
            service_audit.get("tenant_id"),
            sse_by_role.get("client", {}).get("tenant_id"),
            sse_by_role.get("server", {}).get("tenant_id"),
        )
    )
    canonical_dataset_id = stringify(
        first_non_empty(
            service_config.get("dataset_id"),
            service_health.get("dataset_id"),
            service_by_role.get("client", {}).get("dataset_id"),
            service_by_role.get("server", {}).get("dataset_id"),
            service_audit.get("dataset_id"),
            sse_by_role.get("client", {}).get("dataset_id"),
            sse_by_role.get("server", {}).get("dataset_id"),
        )
    )
    canonical_service_id = stringify(
        first_non_empty(
            service_config.get("service_id"),
            service_health.get("service_id"),
            service_by_role.get("client", {}).get("service_id"),
            service_by_role.get("server", {}).get("service_id"),
            service_audit.get("service_id"),
            sse_by_role.get("client", {}).get("service_id"),
            sse_by_role.get("server", {}).get("service_id"),
        )
    )

    canonical_scope = {
        "job_id": job_id,
        "correlation_id": canonical_correlation_id,
        "caller": canonical_caller,
        "tenant_id": canonical_tenant_id,
        "dataset_id": canonical_dataset_id,
        "service_id": canonical_service_id,
        "token_scope": stringify((((bridge_meta.get("bridge") or {}) if isinstance(bridge_meta.get("bridge"), dict) else {}).get("token_scope"))),
        "token_key_version": stringify((((bridge_meta.get("bridge") or {}) if isinstance(bridge_meta.get("bridge"), dict) else {}).get("token_key_version"))),
        "policy_version": stringify(first_non_empty(public_report.get("policy_version"), policy_record.get("policy_version"))),
    }

    checks_run += 1
    check_equal(findings, label="job_id", expected=job_id, actual=audit_chain.get("job_id"), path="audit_chain.json")
    checks_run += 1
    check_equal(
        findings,
        label="correlation_id",
        expected=canonical_correlation_id,
        actual=audit_chain.get("correlation_id"),
        path="audit_chain.json",
    )

    for path_label, record in (
        ("a_psi_run/public_report.json", public_report),
        ("a_psi_run/audit_log.jsonl", policy_record),
        ("bridge_job/bridge_audit.jsonl", bridge_record),
    ):
        if not record:
            continue
        checks_run += 1
        check_equal(findings, label="job_id", expected=job_id, actual=record.get("job_id"), path=path_label)
        checks_run += 1
        check_equal(
            findings,
            label="correlation_id",
            expected=canonical_correlation_id,
            actual=record.get("correlation_id"),
            path=path_label,
        )

    for path_label, record in (
        ("a_psi_run/public_report.json", public_report),
        ("a_psi_run/audit_log.jsonl", policy_record),
        ("sse_exports/export_audit.jsonl:client", sse_by_role.get("client", {})),
        ("sse_exports/export_audit.jsonl:server", sse_by_role.get("server", {})),
        ("sse_exports/record_recovery_service_audit.jsonl:client", service_by_role.get("client", {})),
        ("sse_exports/record_recovery_service_audit.jsonl:server", service_by_role.get("server", {})),
        ("sse_exports/record_recovery_service_audit.jsonl", service_audit),
    ):
        if not record:
            continue
        checks_run += 1
        check_equal(findings, label="caller", expected=canonical_caller, actual=record.get("caller"), path=path_label)

    for label, expected, records in (
        (
            "tenant_id",
            canonical_tenant_id,
            [
                ("sse_exports/export_audit.jsonl:client", sse_by_role.get("client", {})),
                ("sse_exports/export_audit.jsonl:server", sse_by_role.get("server", {})),
                ("sse_exports/record_recovery_service_audit.jsonl:client", service_by_role.get("client", {})),
                ("sse_exports/record_recovery_service_audit.jsonl:server", service_by_role.get("server", {})),
                ("sse_exports/record_recovery_service_audit.jsonl", service_audit),
                ("sse_exports/record_recovery_service_health.json", service_health),
                ("sse_exports/record_recovery_service_config.json", service_config),
            ],
        ),
        (
            "dataset_id",
            canonical_dataset_id,
            [
                ("sse_exports/export_audit.jsonl:client", sse_by_role.get("client", {})),
                ("sse_exports/export_audit.jsonl:server", sse_by_role.get("server", {})),
                ("sse_exports/record_recovery_service_audit.jsonl:client", service_by_role.get("client", {})),
                ("sse_exports/record_recovery_service_audit.jsonl:server", service_by_role.get("server", {})),
                ("sse_exports/record_recovery_service_audit.jsonl", service_audit),
                ("sse_exports/record_recovery_service_health.json", service_health),
                ("sse_exports/record_recovery_service_config.json", service_config),
            ],
        ),
        (
            "service_id",
            canonical_service_id,
            [
                ("sse_exports/export_audit.jsonl:client", sse_by_role.get("client", {})),
                ("sse_exports/export_audit.jsonl:server", sse_by_role.get("server", {})),
                ("sse_exports/record_recovery_service_audit.jsonl:client", service_by_role.get("client", {})),
                ("sse_exports/record_recovery_service_audit.jsonl:server", service_by_role.get("server", {})),
                ("sse_exports/record_recovery_service_audit.jsonl", service_audit),
                ("sse_exports/record_recovery_service_health.json", service_health),
                ("sse_exports/record_recovery_service_config.json", service_config),
            ],
        ),
    ):
        for path_label, record in records:
            if not record:
                continue
            checks_run += 1
            check_equal(findings, label=label, expected=expected, actual=record.get(label), path=path_label)

    bridge_block = bridge_meta.get("bridge") if isinstance(bridge_meta.get("bridge"), dict) else {}
    checks_run += 1
    check_required_non_empty(findings, label="token_scope", value=bridge_block.get("token_scope"), path="bridge_job/job_meta.json")
    checks_run += 1
    check_required_non_empty(
        findings,
        label="token_key_version",
        value=bridge_block.get("token_key_version"),
        path="bridge_job/job_meta.json",
    )

    for path_label, record in (
        ("a_psi_run/audit_log.jsonl", policy_record.get("bridge") if isinstance(policy_record.get("bridge"), dict) else {}),
        ("a_psi_run/public_report.json", public_report.get("bridge") if isinstance(public_report.get("bridge"), dict) else {}),
    ):
        if not record:
            continue
        if "token_scope" in record:
            checks_run += 1
            check_equal(
                findings,
                label="token_scope",
                expected=bridge_block.get("token_scope"),
                actual=record.get("token_scope"),
                path=path_label,
            )
        if "token_key_version" in record:
            checks_run += 1
            check_equal(
                findings,
                label="token_key_version",
                expected=bridge_block.get("token_key_version"),
                actual=record.get("token_key_version"),
                path=path_label,
            )

    if public_report and policy_record:
        checks_run += 1
        check_equal(
            findings,
            label="policy_version",
            expected=policy_record.get("policy_version"),
            actual=public_report.get("policy_version"),
            path="a_psi_run/public_report.json",
        )
        checks_run += 1
        check_equal(
            findings,
            label="k_threshold",
            expected=policy_record.get("threshold_k"),
            actual=public_report.get("k_threshold"),
            path="a_psi_run/public_report.json",
        )
        checks_run += 1
        check_equal(
            findings,
            label="reason_code",
            expected=policy_record.get("reason_code"),
            actual=public_report.get("reason_code"),
            path="a_psi_run/public_report.json",
        )
        expected_decision = "allow" if public_report.get("released") is True else "deny"
        checks_run += 1
        check_equal(
            findings,
            label="release_decision",
            expected=expected_decision,
            actual=policy_record.get("decision"),
            path="a_psi_run/audit_log.jsonl",
        )

    client_export = sse_by_role.get("client", {})
    server_export = sse_by_role.get("server", {})
    boundaries = {
        stringify(record.get("record_recovery_boundary"))
        for record in sse_records
        if stringify(record.get("record_recovery_boundary")) is not None
    }
    for boundary in sorted(boundaries):
        checks_run += 1
        if boundary not in ALLOWED_RECORD_RECOVERY_BOUNDARIES:
            add_finding(
                findings,
                kind="invalid_record_recovery_boundary",
                message="record_recovery_boundary is not an allowed value",
                path="sse_exports/export_audit.jsonl",
                expected=sorted(ALLOWED_RECORD_RECOVERY_BOUNDARIES),
                actual=boundary,
            )

    if client_export.get("record_store_file"):
        checks_run += 1
        check_required_non_empty(
            findings,
            label="record_recovery_boundary",
            value=client_export.get("record_recovery_boundary"),
            path="sse_exports/export_audit.jsonl:client",
        )

    if boundaries & {"service_socket", "service_http"}:
        checks_run += 1
        if not service_audit:
            add_finding(
                findings,
                kind="missing_service_audit",
                message="service recovery boundary requires record recovery service audit output",
                path=service_audit_path_label,
            )
        for field_name in ("tenant_id", "dataset_id", "service_id"):
            for role_name, export_record in (("server", server_export), ("client", client_export)):
                if stringify(export_record.get("record_recovery_boundary")) not in {"service_socket", "service_http"}:
                    continue
                checks_run += 1
                check_required_non_empty(
                    findings,
                    label=field_name,
                    value=export_record.get(field_name),
                    path=f"sse_exports/export_audit.jsonl:{role_name}",
                )

    for role_name, export_record in (("server", server_export), ("client", client_export)):
        boundary = stringify(export_record.get("record_recovery_boundary"))
        if boundary not in {"service_socket", "service_http"}:
            continue
        expected_transport = "unix_socket" if boundary == "service_socket" else "http"
        service_record = service_by_role.get(role_name, {})
        checks_run += 1
        if not service_record:
            add_finding(
                findings,
                kind=f"missing_{role_name}_service_audit",
                message="service recovery boundary requires a matching per-role service audit record",
                path=f"{service_audit_path_label}:{role_name}",
            )
            continue

        for label in ("job_id", "correlation_id", "caller", "tenant_id", "dataset_id", "service_id"):
            checks_run += 1
            check_equal(
                findings,
                label=f"{role_name}_service_{label}",
                expected=export_record.get(label),
                actual=service_record.get(label),
                path=f"{service_audit_path_label}:{role_name}",
            )

        for label in (
            "role",
            "join_key_field",
            "value_field",
            "candidate_count",
            "record_store_file",
            "record_store_sha256",
            "output_file",
            "input_rows",
            "output_rows",
            "output_file_type",
            "output_sha256",
        ):
            checks_run += 1
            check_equal(
                findings,
                label=f"{role_name}_service_{label}",
                expected=export_record.get(label),
                actual=service_record.get(label),
                path=f"{service_audit_path_label}:{role_name}",
            )

        checks_run += 1
        check_exact_equal(
            findings,
            label=f"{role_name}_service_filters",
            expected=export_record.get("filters"),
            actual=service_record.get("filters"),
            path=f"{service_audit_path_label}:{role_name}",
        )

        checks_run += 1
        check_equal(
            findings,
            label=f"{role_name}_service_transport",
            expected=expected_transport,
            actual=service_record.get("transport"),
            path=f"{service_audit_path_label}:{role_name}",
        )

    if "service_http" in boundaries:
        checks_run += 1
        check_equal(
            findings,
            label="service_transport",
            expected="http",
            actual=first_non_empty(service_health.get("transport"), service_audit.get("transport")),
            path="sse_exports/record_recovery_service_health.json",
        )
    if "service_socket" in boundaries:
        checks_run += 1
        check_equal(
            findings,
            label="service_transport",
            expected="unix_socket",
            actual=first_non_empty(service_health.get("transport"), service_audit.get("transport")),
            path="sse_exports/record_recovery_service_health.json",
        )

    if bridge_record:
        for role_name, export_record, bridge_type_key, bridge_sha_key in (
            ("server", server_export, "server_input_file_type", "server_input_sha256"),
            ("client", client_export, "client_input_file_type", "client_input_sha256"),
        ):
            if not export_record:
                continue
            output_type = stringify(export_record.get("output_file_type"))
            if output_type:
                checks_run += 1
                check_equal(
                    findings,
                    label=f"{role_name}_handoff_type",
                    expected=output_type,
                    actual=bridge_record.get(bridge_type_key),
                    path="bridge_job/bridge_audit.jsonl",
                )
                if output_type == "file":
                    checks_run += 1
                    check_equal(
                        findings,
                        label=f"{role_name}_handoff_sha256",
                        expected=export_record.get("output_sha256"),
                        actual=bridge_record.get(bridge_sha_key),
                        path="bridge_job/bridge_audit.jsonl",
                    )
                if output_type == "fifo" and bridge_record.get(bridge_sha_key) not in (None, ""):
                    add_finding(
                        findings,
                        kind=f"{role_name}_fifo_sha_should_be_null",
                        message="bridge fifo input should not reopen the pipe to compute input sha256",
                        path="bridge_job/bridge_audit.jsonl",
                        expected=None,
                        actual=bridge_record.get(bridge_sha_key),
                    )

    server_handoff_cleanup, cleanup_checks = summarize_handoff_cleanup(
        out_base=out_base,
        role_name="server",
        export_record=server_export,
        findings=findings,
        allow_retained_managed_handoff=args.allow_retained_managed_handoff,
        retained_managed_handoff_reason=retained_managed_handoff_reason,
    )
    checks_run += cleanup_checks
    client_handoff_cleanup, cleanup_checks = summarize_handoff_cleanup(
        out_base=out_base,
        role_name="client",
        export_record=client_export,
        findings=findings,
        allow_retained_managed_handoff=args.allow_retained_managed_handoff,
        retained_managed_handoff_reason=retained_managed_handoff_reason,
    )
    checks_run += cleanup_checks
    handoff_cleanup = {
        "server": server_handoff_cleanup,
        "client": client_handoff_cleanup,
    }

    server_output_file_type = stringify(server_export.get("output_file_type"))
    client_output_file_type = stringify(client_export.get("output_file_type"))
    handoff_mode_values = {x for x in [server_output_file_type, client_output_file_type] if x}
    handoff_mode: str | None = "fifo" if "fifo" in handoff_mode_values else ("file" if handoff_mode_values else None)

    handoff_exposure_assessment = build_exposure_assessment(
        handoff_mode=handoff_mode,
        server_cleanup=server_handoff_cleanup,
        client_cleanup=client_handoff_cleanup,
    )

    result = build_result(
        out_base=out_base,
        job_id=job_id,
        canonical_scope=canonical_scope,
        handoff_mode=handoff_mode,
        handoff_cleanup=handoff_cleanup,
        handoff_exposure_assessment=handoff_exposure_assessment,
        findings=findings,
        checks_run=checks_run,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)

    if findings and not args.allow_findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
