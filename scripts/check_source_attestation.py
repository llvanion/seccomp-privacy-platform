#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from source_attestation_lib import (
    SOURCE_ATTESTATION_APPROVED_STATUSES,
    SOURCE_ATTESTATION_SCHEMA,
    SOURCE_ATTESTATION_STRICT_FAIL_MODES,
    SOURCE_EXPORT_MANIFEST_SCHEMA,
    SOURCE_TRUTHFULNESS_REPORT_SCHEMA,
    combined_hash,
    file_descriptor,
    load_json_object,
    same_identity,
    sha256_file,
    utc_now_iso,
    validate_schema,
    verify_ed25519_signature,
    write_json,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _check(
    checks: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    *,
    name: str,
    ok: bool,
    expected: Any,
    actual: Any,
    message: str,
    finding_kind: str,
) -> None:
    checks.append(
        {
            "name": name,
            "status": "ok" if ok else "deny",
            "expected": expected,
            "actual": actual,
            "message": None if ok else message,
        }
    )
    if not ok:
        findings.append(
            {
                "kind": finding_kind,
                "message": message,
                "expected": expected,
                "actual": actual,
            }
        )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Verify typed source attestation and source-truthfulness bindings.")
    ap.add_argument("--attestation", required=True)
    ap.add_argument("--source-export-manifest", default="")
    ap.add_argument("--server-source", required=True)
    ap.add_argument("--client-source", required=True)
    ap.add_argument("--server-bridge-input", required=True)
    ap.add_argument("--client-bridge-input", required=True)
    ap.add_argument("--input-commitment", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--caller", required=True)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--purpose", required=True)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--max-age-hours", type=float, default=0.0)
    ap.add_argument("--require-signed-signoff", action="store_true")
    ap.add_argument("--require-dual-signoff", action="store_true")
    ap.add_argument("--output", required=True)
    ap.add_argument("--assert-allow", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    attestation_path = Path(args.attestation).resolve()
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    def write_terminal_report(*, reason_code: str, reason: str, expected: Any, actual: Any) -> int:
        report = {
            "schema": SOURCE_TRUTHFULNESS_REPORT_SCHEMA,
            "generated_at_utc": utc_now_iso(),
            "decision": "deny",
            "reason_code": reason_code,
            "reason": reason,
            "strict_mode": bool(args.strict),
            "max_age_hours": float(args.max_age_hours),
            "require_signed_signoff": bool(args.require_signed_signoff),
            "require_dual_signoff": bool(args.require_dual_signoff),
            "job_id": args.job_id,
            "caller": args.caller,
            "tenant": args.tenant,
            "dataset": args.dataset,
            "purpose": args.purpose,
            "attestation_path": str(attestation_path),
            "attestation_sha256": sha256_file(attestation_path) if attestation_path.is_file() else None,
            "source_export_manifest_path": None,
            "source_export_manifest_sha256": None,
            "summary": {},
            "checks": [
                {
                    "name": "attestation_present",
                    "status": "deny",
                    "expected": expected,
                    "actual": actual,
                    "message": reason,
                }
            ],
            "findings": [
                {
                    "kind": reason_code,
                    "message": reason,
                    "expected": expected,
                    "actual": actual,
                }
            ],
        }
        write_json(Path(args.output).resolve(), report)
        if args.assert_allow:
            return 2
        return 0

    if not attestation_path.is_file():
        return write_terminal_report(
            reason_code="source_attestation_missing",
            reason="source attestation file is required",
            expected="source_attestation/v1 file",
            actual=str(attestation_path),
        )

    try:
        attestation = load_json_object(attestation_path)
        validate_schema(attestation, repo_root=REPO_ROOT, schema_filename="source_attestation.schema.json")
    except Exception as exc:
        return write_terminal_report(
            reason_code="source_attestation_invalid",
            reason="source attestation file must validate against source_attestation/v1",
            expected="valid source_attestation/v1",
            actual=str(exc),
        )
    attestation_sha256 = sha256_file(attestation_path)

    source_export_manifest: dict[str, Any] | None = None
    source_export_manifest_path: Path | None = None
    source_export_manifest_sha256: str | None = None
    if args.source_export_manifest:
        source_export_manifest_path = Path(args.source_export_manifest).resolve()
        if source_export_manifest_path.is_file():
            try:
                source_export_manifest = load_json_object(source_export_manifest_path)
                validate_schema(source_export_manifest, repo_root=REPO_ROOT, schema_filename="source_export_manifest.schema.json")
                source_export_manifest_sha256 = sha256_file(source_export_manifest_path)
            except Exception as exc:
                return write_terminal_report(
                    reason_code="source_export_manifest_invalid",
                    reason="source export manifest must validate against source_export_manifest/v1",
                    expected="valid source_export_manifest/v1",
                    actual=str(exc),
                )

    require_export_manifest = bool(args.strict or attestation.get("sealed_export_manifest_sha256"))
    if require_export_manifest and source_export_manifest is None:
        _check(
            checks,
            findings,
            name="sealed_export_manifest",
            ok=False,
            expected="source_export_manifest/v1 supplied and verified",
            actual=None,
            message="strict source attestation verification requires the bound source export manifest",
            finding_kind="sealed_export_manifest_missing",
        )

    try:
        source_files = [
            file_descriptor(label="server_source", path=Path(args.server_source)),
            file_descriptor(label="client_source", path=Path(args.client_source)),
        ]
        bridge_input_files = [
            file_descriptor(label="server_bridge_input", path=Path(args.server_bridge_input)),
            file_descriptor(label="client_bridge_input", path=Path(args.client_bridge_input)),
        ]
        expected_input_commitment_sha256 = sha256_file(Path(args.input_commitment).resolve())
    except Exception as exc:
        return write_terminal_report(
            reason_code="source_input_evidence_missing",
            reason="source or bridge input evidence files are missing or unreadable",
            expected="readable source files, bridge input files, and input commitment",
            actual=str(exc),
        )
    expected_source_snapshot_sha256 = combined_hash(source_files)
    expected_bridge_input_sha256 = combined_hash(bridge_input_files)

    def parse_utc(value: str) -> datetime:
        text = str(value or "").strip()
        if not text:
            raise ValueError("empty timestamp")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    _check(
        checks,
        findings,
        name="scope_binding",
        ok=(
            attestation.get("job_id") == args.job_id
            and attestation.get("caller") == args.caller
            and attestation.get("tenant") == args.tenant
            and attestation.get("dataset") == args.dataset
            and attestation.get("purpose") == args.purpose
        ),
        expected={
            "job_id": args.job_id,
            "caller": args.caller,
            "tenant": args.tenant,
            "dataset": args.dataset,
            "purpose": args.purpose,
        },
        actual={
            "job_id": attestation.get("job_id"),
            "caller": attestation.get("caller"),
            "tenant": attestation.get("tenant"),
            "dataset": attestation.get("dataset"),
            "purpose": attestation.get("purpose"),
        },
        message="attestation scope does not match expected request/release scope",
        finding_kind="attestation_scope_mismatch",
    )
    _check(
        checks,
        findings,
        name="source_snapshot_hash",
        ok=attestation.get("source_snapshot_sha256") == expected_source_snapshot_sha256,
        expected=expected_source_snapshot_sha256,
        actual=attestation.get("source_snapshot_sha256"),
        message="attestation source_snapshot_sha256 does not match the bound source snapshot",
        finding_kind="source_snapshot_hash_mismatch",
    )
    _check(
        checks,
        findings,
        name="bridge_input_hash",
        ok=attestation.get("bridge_input_sha256") == expected_bridge_input_sha256,
        expected=expected_bridge_input_sha256,
        actual=attestation.get("bridge_input_sha256"),
        message="attestation bridge_input_sha256 does not match bridge inputs",
        finding_kind="bridge_input_hash_mismatch",
    )
    _check(
        checks,
        findings,
        name="input_commitment_hash",
        ok=attestation.get("input_commitment_sha256") == expected_input_commitment_sha256,
        expected=expected_input_commitment_sha256,
        actual=attestation.get("input_commitment_sha256"),
        message="attestation input_commitment_sha256 does not match input_commitments.json",
        finding_kind="input_commitment_hash_mismatch",
    )
    if source_export_manifest is not None:
        _check(
            checks,
            findings,
            name="sealed_export_manifest",
            ok=attestation.get("sealed_export_manifest_sha256") == source_export_manifest_sha256,
            expected=source_export_manifest_sha256,
            actual=attestation.get("sealed_export_manifest_sha256"),
            message="attestation sealed_export_manifest_sha256 does not match the bound source export manifest",
            finding_kind="sealed_export_manifest_mismatch",
        )
        _check(
            checks,
            findings,
            name="export_manifest_source_hash",
            ok=source_export_manifest.get("source_snapshot_sha256") == expected_source_snapshot_sha256,
            expected=expected_source_snapshot_sha256,
            actual=source_export_manifest.get("source_snapshot_sha256"),
            message="source export manifest source_snapshot_sha256 does not match source files",
            finding_kind="export_manifest_source_hash_mismatch",
        )
        _check(
            checks,
            findings,
            name="export_manifest_bridge_hash",
            ok=source_export_manifest.get("bridge_input_sha256") == expected_bridge_input_sha256,
            expected=expected_bridge_input_sha256,
            actual=source_export_manifest.get("bridge_input_sha256"),
            message="source export manifest bridge_input_sha256 does not match bridge inputs",
            finding_kind="export_manifest_bridge_hash_mismatch",
        )
        _check(
            checks,
            findings,
            name="export_manifest_scope_binding",
            ok=(
                source_export_manifest.get("job_id") == args.job_id
                and source_export_manifest.get("caller") == args.caller
                and source_export_manifest.get("tenant") == args.tenant
                and source_export_manifest.get("dataset") == args.dataset
                and source_export_manifest.get("purpose") == args.purpose
                and source_export_manifest.get("source_system") == attestation.get("source_system")
            ),
            expected={
                "job_id": args.job_id,
                "caller": args.caller,
                "tenant": args.tenant,
                "dataset": args.dataset,
                "purpose": args.purpose,
                "source_system": attestation.get("source_system"),
            },
            actual={
                "job_id": source_export_manifest.get("job_id"),
                "caller": source_export_manifest.get("caller"),
                "tenant": source_export_manifest.get("tenant"),
                "dataset": source_export_manifest.get("dataset"),
                "purpose": source_export_manifest.get("purpose"),
                "source_system": source_export_manifest.get("source_system"),
            },
            message="source export manifest scope does not match the bound attestation/request scope",
            finding_kind="export_manifest_scope_mismatch",
        )
    else:
        if not require_export_manifest:
            checks.append(
                {
                    "name": "sealed_export_manifest",
                    "status": "skip",
                    "expected": "source_export_manifest/v1",
                    "actual": None,
                    "message": "no source export manifest supplied",
                }
            )
        checks.append(
            {
                "name": "export_manifest_scope_binding",
                "status": "skip",
                "expected": "source_export_manifest/v1",
                "actual": None,
                "message": "no source export manifest supplied",
            }
        )

    approval_present = bool(str(attestation.get("approval_id") or "").strip())
    operator_identity_present = bool(str(attestation.get("operator_identity") or "").strip())
    signoff_status = str(attestation.get("signoff_status") or "")
    dual_reviewer_ok = signoff_status != "approved_dual" or bool(str(attestation.get("reviewer_identity") or "").strip())
    _check(
        checks,
        findings,
        name="signoff_fields",
        ok=approval_present and operator_identity_present and dual_reviewer_ok,
        expected={
            "approval_id": "non-empty",
            "operator_identity": "non-empty",
            "reviewer_identity": "present when signoff_status=approved_dual",
        },
        actual={
            "approval_id": attestation.get("approval_id"),
            "operator_identity": attestation.get("operator_identity"),
            "reviewer_identity": attestation.get("reviewer_identity"),
            "signoff_status": signoff_status,
        },
        message="attestation signoff fields are incomplete",
        finding_kind="signoff_missing",
    )

    dual_signoff_required = bool(args.require_dual_signoff)
    reviewer_identity = attestation.get("reviewer_identity")
    _check(
        checks,
        findings,
        name="signoff_identity_separation",
        ok=(
            (
                signoff_status != "approved_dual"
                and not dual_signoff_required
            )
            or (
                signoff_status == "approved_dual"
                and bool(str(reviewer_identity or "").strip())
                and not same_identity(attestation.get("operator_identity"), reviewer_identity)
            )
        ),
        expected={
            "require_dual_signoff": dual_signoff_required,
            "operator_identity": "distinct from reviewer_identity when dual signoff is required",
        },
        actual={
            "signoff_status": signoff_status,
            "operator_identity": attestation.get("operator_identity"),
            "reviewer_identity": reviewer_identity,
        },
        message="dual signoff requires distinct operator and reviewer identities",
        finding_kind="signoff_identity_separation_invalid",
    )

    created_at = None
    try:
        created_at = parse_utc(str(attestation.get("created_at_utc") or ""))
    except Exception:
        created_at = None
    timestamp_ok = False
    timestamp_actual: Any = {}
    try:
        operator_signed_at = parse_utc(str(attestation.get("operator_signed_at_utc") or "")) if signoff_status in SOURCE_ATTESTATION_APPROVED_STATUSES else None
        reviewer_signed_at = parse_utc(str(attestation.get("reviewer_signed_at_utc") or "")) if signoff_status == "approved_dual" else None
        timestamp_ok = True
        if signoff_status in SOURCE_ATTESTATION_APPROVED_STATUSES and operator_signed_at is None:
            timestamp_ok = False
        if signoff_status == "approved_dual" and reviewer_signed_at is None:
            timestamp_ok = False
        if timestamp_ok and created_at is not None and operator_signed_at is not None and operator_signed_at < created_at:
            timestamp_ok = False
        if timestamp_ok and created_at is not None and reviewer_signed_at is not None and reviewer_signed_at < created_at:
            timestamp_ok = False
        if timestamp_ok and operator_signed_at is not None and reviewer_signed_at is not None and reviewer_signed_at < operator_signed_at:
            timestamp_ok = False
        timestamp_actual = {
            "created_at_utc": attestation.get("created_at_utc"),
            "operator_signed_at_utc": attestation.get("operator_signed_at_utc"),
            "reviewer_signed_at_utc": attestation.get("reviewer_signed_at_utc"),
        }
    except Exception as exc:
        timestamp_actual = str(exc)
    _check(
        checks,
        findings,
        name="signoff_timestamps",
        ok=timestamp_ok,
        expected={
            "operator_signed_at_utc": "present and >= created_at_utc when approved",
            "reviewer_signed_at_utc": "present and >= operator_signed_at_utc when approved_dual",
        },
        actual=timestamp_actual,
        message="signoff timestamps are missing or inconsistent with approval chronology",
        finding_kind="signoff_timestamps_invalid",
    )

    signature_valid, signature_reason = verify_ed25519_signature(attestation)
    signature_required = bool(args.require_signed_signoff)
    _check(
        checks,
        findings,
        name="signoff_signature",
        ok=(signature_valid if signature_required else True),
        expected="valid ed25519 signature" if signature_required else "not required",
        actual=signature_reason if not signature_valid else "valid",
        message="attestation signoff signature is missing or invalid",
        finding_kind="signoff_signature_invalid",
    )

    if args.strict:
        strict_ok = (
            str(attestation.get("attestation_mode") or "") not in SOURCE_ATTESTATION_STRICT_FAIL_MODES
            and signoff_status in SOURCE_ATTESTATION_APPROVED_STATUSES
        )
        _check(
            checks,
            findings,
            name="strict_mode_governance",
            ok=strict_ok,
            expected={
                "attestation_mode": "operator|external",
                "signoff_status": sorted(SOURCE_ATTESTATION_APPROVED_STATUSES),
            },
            actual={
                "attestation_mode": attestation.get("attestation_mode"),
                "signoff_status": signoff_status,
            },
            message="strict mode rejects planned/local/manual evidence or unsigned signoff status",
            finding_kind="strict_mode_source_attestation_rejected",
        )
    else:
        checks.append(
            {
                "name": "strict_mode_governance",
                "status": "skip",
                "expected": None,
                "actual": None,
                "message": "strict mode disabled",
            }
        )

    if args.max_age_hours > 0:
        freshness_anchor = attestation.get("operator_signed_at_utc") or attestation.get("created_at_utc")
        freshness_ok = False
        freshness_actual: Any
        try:
            age_hours = (datetime.now(timezone.utc) - parse_utc(str(freshness_anchor or ""))).total_seconds() / 3600.0
            freshness_ok = age_hours <= float(args.max_age_hours)
            freshness_actual = round(age_hours, 3)
        except Exception as exc:
            freshness_actual = str(exc)
        _check(
            checks,
            findings,
            name="attestation_freshness",
            ok=freshness_ok,
            expected=f"<= {args.max_age_hours}h",
            actual=freshness_actual,
            message="attestation freshness exceeds the allowed strict-mode age bound",
            finding_kind="source_attestation_stale",
        )
    else:
        checks.append(
            {
                "name": "attestation_freshness",
                "status": "skip",
                "expected": None,
                "actual": None,
                "message": "freshness bound disabled",
            }
        )

    decision = "allow"
    reason_code = "ok"
    reason = None
    for check in checks:
        if check["status"] == "deny":
            decision = "deny"
            reason = check.get("message")
            reason_code = next(
                (
                    finding.get("kind")
                    for finding in findings
                    if finding.get("message") == check.get("message")
                ),
                "source_truthfulness_denied",
            )
            break

    report = {
        "schema": SOURCE_TRUTHFULNESS_REPORT_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason,
        "strict_mode": bool(args.strict),
        "max_age_hours": float(args.max_age_hours),
        "require_signed_signoff": bool(args.require_signed_signoff),
        "require_dual_signoff": bool(args.require_dual_signoff),
        "job_id": args.job_id,
        "caller": args.caller,
        "tenant": args.tenant,
        "dataset": args.dataset,
        "purpose": args.purpose,
        "attestation_path": str(attestation_path),
        "attestation_sha256": attestation_sha256,
        "source_export_manifest_path": str(source_export_manifest_path) if source_export_manifest_path else None,
        "source_export_manifest_sha256": source_export_manifest_sha256,
        "summary": {
            "source_attestation_mode": attestation.get("attestation_mode"),
            "signoff_status": signoff_status,
            "approval_id": attestation.get("approval_id"),
            "operator_identity": attestation.get("operator_identity"),
            "reviewer_identity": attestation.get("reviewer_identity"),
            "signature_present": attestation.get("signature_algorithm") not in (None, ""),
            "signature_valid": signature_valid,
            "dual_signoff_required": bool(args.require_dual_signoff),
            "source_snapshot_sha256": attestation.get("source_snapshot_sha256"),
            "bridge_input_sha256": attestation.get("bridge_input_sha256"),
            "input_commitment_sha256": attestation.get("input_commitment_sha256"),
        },
        "checks": checks,
        "findings": findings,
    }
    out_path = Path(args.output).resolve()
    write_json(out_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.assert_allow and decision != "allow":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
