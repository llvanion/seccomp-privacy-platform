#!/usr/bin/env python3
"""Server-side release policy gate.

A public PJC release is only allowed when the configured policy
(``release_policy_gate_config/v1``) is satisfied by the artifacts emitted by
``a-psi/moduleA_psi/scripts/policy_release.py`` and
``policy_postprocess_buckets.py``. The gate is the canonical "should this
release become public?" check and runs server-side so that an operator who
forgets ``--require-dp`` on a one-shot CLI cannot widen the public surface.

Output: ``release_policy_gate/v1`` JSON with per-check status + first failing
finding. Returns non-zero when ``--assert-allow`` is passed and decision != allow.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from source_attestation_lib import (  # noqa: E402
    SOURCE_ATTESTATION_APPROVED_STATUSES,
    SOURCE_ATTESTATION_STRICT_FAIL_MODES,
    same_identity,
    verify_ed25519_signature,
)
from validate_json_contract import load_json, validate_value  # noqa: E402

SCHEMA = "release_policy_gate/v1"
OPERATOR_ONLY_PUBLIC_FIELDS = ("input_sizes", "rate_limit_used", "rate_limit_max", "bridge", "details")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_config(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    schema = load_json(str(REPO_ROOT / "schemas" / "release_policy_gate_config.schema.json"))
    validate_value(data, schema)
    return data


def _load_public_report(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"public_report must be a JSON object: {path}")
    return data


def _read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return out


def _load_json_object(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON object expected: {path}")
    return data


def _latest_policy_audit_record(path: Path, *, job_id: str | None) -> dict | None:
    if not path.is_file():
        return None
    records = [
        item
        for item in _read_jsonl(path)
        if item.get("event") == "policy_release" and (job_id is None or item.get("job_id") == job_id)
    ]
    return records[-1] if records else None


def _external_anchor_status(report: dict) -> dict:
    sink = report.get("external_sink") if isinstance(report.get("external_sink"), dict) else {}
    kind = str(sink.get("kind") or "")
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    sink_status = None
    executed = None
    immutable_ref = None
    if kind == "s3_worm":
        block = sink.get("s3_object_lock") if isinstance(sink.get("s3_object_lock"), dict) else {}
        sink_status = block.get("status")
        executed = block.get("executed")
        bucket = block.get("bucket")
        key = block.get("key")
        version_id = block.get("version_id")
        immutable_ref = {
            "kind": kind,
            "uri": f"s3://{bucket}/{key}" if bucket and key else sink.get("path"),
            "version_id": version_id,
            "etag": block.get("etag"),
            "retain_until_utc": block.get("retain_until_utc"),
        }
    elif kind == "rekor":
        block = sink.get("rekor_transparency_log") if isinstance(sink.get("rekor_transparency_log"), dict) else {}
        sink_status = block.get("status")
        executed = block.get("executed")
        immutable_ref = {
            "kind": kind,
            "endpoint_url": block.get("endpoint_url"),
            "uploaded_count": block.get("uploaded_count"),
            "entries": block.get("entries") or [],
        }
    else:
        sink_status = "local" if kind == "file_ledger" else None
        executed = kind == "file_ledger" and int(summary.get("published_count") or 0) > 0
        immutable_ref = {"kind": kind, "path": sink.get("path")}
    return {
        "kind": kind,
        "summary_status": summary.get("status"),
        "published_count": summary.get("published_count"),
        "anchor_record_count": summary.get("anchor_record_count"),
        "verified_chain": summary.get("verified_chain"),
        "last_entry_sha256": summary.get("last_entry_sha256"),
        "mode": report.get("mode"),
        "production_mode": report.get("production_mode"),
        "production_findings": report.get("production_findings") if isinstance(report.get("production_findings"), list) else [],
        "sink_status": sink_status,
        "executed": executed,
        "immutable_ref": immutable_ref,
    }


def run_gate(
    *,
    public_report_path: Path,
    policy_config_path: Path,
    operator_report_path: Path | None,
    budget_ledger_path: Path | None,
    pjc_evidence_merge_path: Path | None = None,
    policy_audit_log_path: Path | None = None,
    external_anchor_report_path: Path | None = None,
    source_attestation_path: Path | None = None,
    source_truthfulness_report_path: Path | None = None,
) -> dict:
    checks: list[dict] = []
    findings: list[dict] = []
    config = _load_config(policy_config_path)
    public_report = _load_public_report(public_report_path)
    operator_report: dict | None = None
    if operator_report_path is not None:
        if operator_report_path.is_file():
            operator_report = json.loads(operator_report_path.read_text(encoding="utf-8"))

    released = bool(public_report.get("released"))
    reason_code = str(public_report.get("reason_code") or "")
    job_id = str(public_report.get("job_id") or "") or None
    caller = str(public_report.get("caller") or "") or None
    public_governance = public_report.get("governance") if isinstance(public_report.get("governance"), dict) else {}
    operator_governance = operator_report.get("governance") if isinstance(operator_report, dict) and isinstance(operator_report.get("governance"), dict) else {}
    source_attestation: dict | None = None
    source_truthfulness_report: dict | None = None
    source_attestation_sha256: str | None = None
    source_truthfulness_report_sha256: str | None = None
    source_attestation_load_error: str | None = None
    source_truthfulness_report_load_error: str | None = None
    source_governance_needed = released and any(
        bool(config.get(name))
        for name in ("require_source_attestation", "require_signed_signoff", "require_dual_signoff", "require_bound_input_commitment")
    )
    if source_governance_needed:
        if source_attestation_path is None or not source_attestation_path.is_file():
            source_attestation_load_error = "source attestation file is required"
        else:
            try:
                source_attestation = _load_json_object(source_attestation_path)
                source_attestation_schema = load_json(str(REPO_ROOT / "schemas" / "source_attestation.schema.json"))
                validate_value(source_attestation, source_attestation_schema)
                source_attestation_sha256 = _sha256(source_attestation_path)
            except Exception as exc:
                source_attestation = None
                source_attestation_load_error = str(exc)
        if source_truthfulness_report_path is None or not source_truthfulness_report_path.is_file():
            source_truthfulness_report_load_error = "source truthfulness report is required"
        else:
            try:
                source_truthfulness_report = _load_json_object(source_truthfulness_report_path)
                source_truthfulness_schema = load_json(str(REPO_ROOT / "schemas" / "source_truthfulness_report.schema.json"))
                validate_value(source_truthfulness_report, source_truthfulness_schema)
                source_truthfulness_report_sha256 = _sha256(source_truthfulness_report_path)
            except Exception as exc:
                source_truthfulness_report = None
                source_truthfulness_report_load_error = str(exc)

    # 1. DP enforcement
    if config["require_dp"] and released:
        dp_applied = bool(public_report.get("dp_noise_applied"))
        dp_eps = public_report.get("dp_epsilon")
        min_eps = config.get("min_dp_epsilon")
        max_eps = config.get("max_dp_epsilon")
        if not dp_applied:
            checks.append({"name": "dp_enforced", "status": "deny", "expected": True, "actual": False, "message": "released report missing dp_noise_applied"})
            findings.append({"kind": "dp_required", "message": "released without DP noise", "expected": True, "actual": False})
        elif dp_eps is None or float(dp_eps) <= 0:
            checks.append({"name": "dp_enforced", "status": "deny", "expected": "> 0", "actual": dp_eps, "message": "dp_epsilon missing or non-positive"})
            findings.append({"kind": "dp_required", "message": "dp_epsilon missing/non-positive", "expected": "> 0", "actual": dp_eps})
        elif min_eps is not None and float(dp_eps) < float(min_eps):
            checks.append({"name": "dp_enforced", "status": "deny", "expected": f">= {min_eps}", "actual": dp_eps, "message": "dp_epsilon below policy minimum"})
            findings.append({"kind": "dp_epsilon_too_small", "message": "dp_epsilon below policy minimum", "expected": min_eps, "actual": dp_eps})
        elif max_eps is not None and float(dp_eps) > float(max_eps):
            checks.append({"name": "dp_enforced", "status": "deny", "expected": f"<= {max_eps}", "actual": dp_eps, "message": "dp_epsilon above policy maximum"})
            findings.append({"kind": "dp_epsilon_too_large", "message": "dp_epsilon above policy maximum", "expected": max_eps, "actual": dp_eps})
        else:
            checks.append({"name": "dp_enforced", "status": "ok", "expected": "dp applied", "actual": dp_eps, "message": None})
    else:
        checks.append({"name": "dp_enforced", "status": "skip", "expected": None, "actual": None, "message": "skipped (require_dp false or release denied)"})

    # 2. k threshold
    if released:
        report_k = public_report.get("k_threshold")
        min_k = int(config.get("min_k") or 0)
        if report_k is None or int(report_k) < min_k:
            checks.append({"name": "min_k", "status": "deny", "expected": f">= {min_k}", "actual": report_k, "message": "k_threshold below policy minimum"})
            findings.append({"kind": "min_k_violation", "message": "k_threshold below policy minimum", "expected": min_k, "actual": report_k})
        else:
            checks.append({"name": "min_k", "status": "ok", "expected": f">= {min_k}", "actual": report_k, "message": None})
    else:
        checks.append({"name": "min_k", "status": "skip", "expected": None, "actual": None, "message": "release denied"})

    # 3. privacy budget
    if config["require_privacy_budget"]:
        ledger_path = budget_ledger_path or (Path(config["budget_ledger_path"]) if config.get("budget_ledger_path") else None)
        if ledger_path is None or not ledger_path.exists():
            checks.append({"name": "privacy_budget_ledger", "status": "deny", "expected": "configured", "actual": str(ledger_path) if ledger_path else None, "message": "privacy budget required but ledger not configured / not found"})
            findings.append({"kind": "privacy_budget_missing_config", "message": "privacy budget ledger not configured", "expected": "configured", "actual": str(ledger_path) if ledger_path else None})
        elif released:
            records = _read_jsonl(ledger_path)
            match = next((r for r in records if r.get("job_id") == job_id), None)
            if match is None:
                checks.append({"name": "privacy_budget_ledger", "status": "deny", "expected": f"record for {job_id}", "actual": None, "message": "no ledger record for released job"})
                findings.append({"kind": "budget_ledger_missing_record", "message": "no ledger record for released job", "expected": job_id, "actual": None})
            else:
                decision = str(match.get("decision") or "").lower()
                budget = match.get("privacy_budget") or {}
                budget_decision = str(budget.get("decision") or "").lower() if isinstance(budget, dict) else ""
                if decision in {"allow"} and budget_decision in {"allow", ""}:
                    checks.append({"name": "privacy_budget_ledger", "status": "ok", "expected": "allow", "actual": decision, "message": None})
                else:
                    checks.append({"name": "privacy_budget_ledger", "status": "deny", "expected": "allow", "actual": decision, "message": "ledger record does not record an allowed release"})
                    findings.append({"kind": "budget_ledger_denied", "message": "ledger record does not record an allowed release", "expected": "allow", "actual": decision})
        else:
            checks.append({"name": "privacy_budget_ledger", "status": "skip", "expected": None, "actual": None, "message": "release denied (no ledger entry needed)"})
    else:
        checks.append({"name": "privacy_budget_ledger", "status": "skip", "expected": None, "actual": None, "message": "skipped (require_privacy_budget false)"})

    # 4. denial reason code allow-list (defense in depth)
    if not released:
        allowed = set(config["allowed_deny_reason_codes"])
        if reason_code not in allowed:
            checks.append({"name": "deny_reason_code", "status": "deny", "expected": sorted(allowed), "actual": reason_code, "message": "release denied with an out-of-policy reason code"})
            findings.append({"kind": "deny_reason_not_allowed", "message": "release denied with an out-of-policy reason code", "expected": sorted(allowed), "actual": reason_code})
        else:
            checks.append({"name": "deny_reason_code", "status": "ok", "expected": sorted(allowed), "actual": reason_code, "message": None})
    else:
        checks.append({"name": "deny_reason_code", "status": "skip", "expected": None, "actual": None, "message": "release allowed"})

    # 5. duplicate-query enforcement (operator report may carry the budget decision)
    if config.get("duplicate_query_denied") and released and operator_report is not None:
        pb = operator_report.get("privacy_budget") if isinstance(operator_report, dict) else None
        if isinstance(pb, dict) and pb.get("decision") == "deny" and "duplicate" in str(pb.get("reason_code") or ""):
            checks.append({"name": "duplicate_query", "status": "deny", "expected": "no duplicate", "actual": pb.get("reason_code"), "message": "duplicate-query budget decision was deny but release went public"})
            findings.append({"kind": "duplicate_query_leaked", "message": "duplicate query slipped past CLI gate", "expected": "no duplicate", "actual": pb.get("reason_code")})
        else:
            checks.append({"name": "duplicate_query", "status": "ok", "expected": "no duplicate", "actual": None, "message": None})
    else:
        checks.append({"name": "duplicate_query", "status": "skip", "expected": None, "actual": None, "message": "skipped"})

    # 6. public report redaction for released reports
    if config.get("require_public_report_redaction") and released:
        leaked = [field for field in OPERATOR_ONLY_PUBLIC_FIELDS if field in public_report]
        redaction_marker = bool(public_report.get("operator_fields_redacted"))
        if leaked:
            checks.append({"name": "public_report_redaction", "status": "deny", "expected": "no operator-only public fields", "actual": leaked, "message": "released public report contains operator-only fields"})
            findings.append({"kind": "public_report_operator_fields_leaked", "message": "released public report contains operator-only fields", "expected": "redacted", "actual": leaked})
        elif not redaction_marker:
            checks.append({"name": "public_report_redaction", "status": "deny", "expected": "operator_fields_redacted=true", "actual": public_report.get("operator_fields_redacted"), "message": "released public report lacks redaction marker"})
            findings.append({"kind": "public_report_redaction_missing", "message": "released public report lacks redaction marker", "expected": True, "actual": public_report.get("operator_fields_redacted")})
        elif operator_report_path is not None and not operator_report_path.is_file():
            checks.append({"name": "public_report_redaction", "status": "deny", "expected": "operator report exists", "actual": str(operator_report_path), "message": "redacted release did not preserve an operator report"})
            findings.append({"kind": "operator_report_missing", "message": "redacted release did not preserve an operator report", "expected": "file", "actual": str(operator_report_path)})
        else:
            checks.append({"name": "public_report_redaction", "status": "ok", "expected": "redacted", "actual": True, "message": None})
    else:
        checks.append({"name": "public_report_redaction", "status": "skip", "expected": None, "actual": None, "message": "skipped (require_public_report_redaction false or release denied)"})

    # 7. Source truthfulness and source-attestation binding.
    if config.get("require_source_attestation") and released:
        if source_attestation_load_error is not None:
            checks.append({"name": "source_attestation", "status": "deny", "expected": "valid source_attestation/v1", "actual": source_attestation_load_error, "message": "source attestation file is required and must validate"})
            findings.append({"kind": "source_attestation_missing", "message": "source attestation file is required and must validate", "expected": "valid source_attestation/v1", "actual": source_attestation_load_error})
        elif source_truthfulness_report_load_error is not None:
            checks.append({"name": "source_attestation", "status": "deny", "expected": "valid source_truthfulness_report/v1", "actual": source_truthfulness_report_load_error, "message": "source truthfulness verifier report is required and must validate"})
            findings.append({"kind": "source_truthfulness_report_missing", "message": "source truthfulness verifier report is required and must validate", "expected": "valid source_truthfulness_report/v1", "actual": source_truthfulness_report_load_error})
        else:
            assert source_attestation is not None
            assert source_truthfulness_report is not None
            policy_audit = _latest_policy_audit_record(policy_audit_log_path, job_id=job_id) if policy_audit_log_path is not None else None
            policy_governance = policy_audit.get("governance") if isinstance(policy_audit, dict) and isinstance(policy_audit.get("governance"), dict) else {}
            mismatches: list[dict] = []
            if source_truthfulness_report.get("decision") != "allow":
                mismatches.append({"field": "source_truthfulness_report.decision", "expected": "allow", "actual": source_truthfulness_report.get("decision")})
            if config.get("strict_source_attestation") and source_truthfulness_report.get("strict_mode") is not True:
                mismatches.append({"field": "source_truthfulness_report.strict_mode", "expected": True, "actual": source_truthfulness_report.get("strict_mode")})
            expected_max_age = float(config.get("max_source_attestation_age_hours") or 0)
            if expected_max_age > 0 and float(source_truthfulness_report.get("max_age_hours") or 0) != expected_max_age:
                mismatches.append({"field": "source_truthfulness_report.max_age_hours", "expected": expected_max_age, "actual": source_truthfulness_report.get("max_age_hours")})
            if config.get("require_signed_signoff") and source_truthfulness_report.get("require_signed_signoff") is not True:
                mismatches.append({"field": "source_truthfulness_report.require_signed_signoff", "expected": True, "actual": source_truthfulness_report.get("require_signed_signoff")})
            if config.get("require_dual_signoff") and source_truthfulness_report.get("require_dual_signoff") is not True:
                mismatches.append({"field": "source_truthfulness_report.require_dual_signoff", "expected": True, "actual": source_truthfulness_report.get("require_dual_signoff")})
            if source_attestation.get("job_id") != job_id:
                mismatches.append({"field": "source_attestation.job_id", "expected": job_id, "actual": source_attestation.get("job_id")})
            if caller and source_attestation.get("caller") != caller:
                mismatches.append({"field": "source_attestation.caller", "expected": caller, "actual": source_attestation.get("caller")})
            if source_attestation_sha256 and public_governance.get("source_attestation_sha256") != source_attestation_sha256:
                mismatches.append({"field": "public_report.governance.source_attestation_sha256", "expected": source_attestation_sha256, "actual": public_governance.get("source_attestation_sha256")})
            if source_truthfulness_report_sha256 and public_governance.get("source_truthfulness_report_sha256") != source_truthfulness_report_sha256:
                mismatches.append({"field": "public_report.governance.source_truthfulness_report_sha256", "expected": source_truthfulness_report_sha256, "actual": public_governance.get("source_truthfulness_report_sha256")})
            if public_governance.get("source_attestation_signoff_status") != source_attestation.get("signoff_status"):
                mismatches.append({"field": "public_report.governance.source_attestation_signoff_status", "expected": source_attestation.get("signoff_status"), "actual": public_governance.get("source_attestation_signoff_status")})
            if operator_report is not None and source_attestation_sha256 and operator_governance.get("source_attestation_sha256") != source_attestation_sha256:
                mismatches.append({"field": "operator_report.governance.source_attestation_sha256", "expected": source_attestation_sha256, "actual": operator_governance.get("source_attestation_sha256")})
            if operator_report is not None and source_truthfulness_report_sha256 and operator_governance.get("source_truthfulness_report_sha256") != source_truthfulness_report_sha256:
                mismatches.append({"field": "operator_report.governance.source_truthfulness_report_sha256", "expected": source_truthfulness_report_sha256, "actual": operator_governance.get("source_truthfulness_report_sha256")})
            if policy_audit is None:
                mismatches.append({"field": "policy_audit", "expected": f"record for {job_id}", "actual": None})
            else:
                if policy_governance.get("source_attestation_sha256") != source_attestation_sha256:
                    mismatches.append({"field": "policy_audit.governance.source_attestation_sha256", "expected": source_attestation_sha256, "actual": policy_governance.get("source_attestation_sha256")})
                if source_truthfulness_report_sha256 and policy_governance.get("source_truthfulness_report_sha256") != source_truthfulness_report_sha256:
                    mismatches.append({"field": "policy_audit.governance.source_truthfulness_report_sha256", "expected": source_truthfulness_report_sha256, "actual": policy_governance.get("source_truthfulness_report_sha256")})
                if policy_governance.get("source_attestation_signoff_status") != source_attestation.get("signoff_status"):
                    mismatches.append({"field": "policy_audit.governance.source_attestation_signoff_status", "expected": source_attestation.get("signoff_status"), "actual": policy_governance.get("source_attestation_signoff_status")})
                if policy_audit.get("job_id") != job_id:
                    mismatches.append({"field": "policy_audit.job_id", "expected": job_id, "actual": policy_audit.get("job_id")})
                if caller and policy_audit.get("caller") != caller:
                    mismatches.append({"field": "policy_audit.caller", "expected": caller, "actual": policy_audit.get("caller")})
            if source_truthfulness_report.get("attestation_sha256") not in {None, source_attestation_sha256}:
                mismatches.append({"field": "source_truthfulness_report.attestation_sha256", "expected": source_attestation_sha256, "actual": source_truthfulness_report.get("attestation_sha256")})
            if mismatches:
                checks.append({"name": "source_attestation", "status": "deny", "expected": "attestation and truthfulness report bound to public/operator/policy evidence", "actual": mismatches, "message": "source attestation is not bound to this release"})
                findings.append({"kind": "source_attestation_unbound", "message": "source attestation is not bound to this release", "expected": "matching attestation/report hashes", "actual": mismatches})
            else:
                checks.append({"name": "source_attestation", "status": "ok", "expected": "bound attestation", "actual": {"source_attestation_sha256": source_attestation_sha256, "source_truthfulness_report_sha256": source_truthfulness_report_sha256}, "message": None})
    elif config.get("require_source_attestation"):
        checks.append({"name": "source_attestation", "status": "skip", "expected": None, "actual": None, "message": "release denied (no public source-attestation binding needed)"})
    else:
        checks.append({"name": "source_attestation", "status": "skip", "expected": None, "actual": None, "message": "skipped (require_source_attestation false)"})

    # 8. Signed signoff enforcement.
    if config.get("require_signed_signoff") and released:
        if source_attestation_load_error is not None or source_truthfulness_report_load_error is not None or source_attestation is None:
            checks.append({"name": "signed_signoff", "status": "deny", "expected": "valid signed source attestation", "actual": source_attestation_load_error or source_truthfulness_report_load_error, "message": "signed signoff requires a valid source attestation and verifier report"})
            findings.append({"kind": "signed_signoff_missing", "message": "signed signoff requires a valid source attestation and verifier report", "expected": "valid signed source attestation", "actual": source_attestation_load_error or source_truthfulness_report_load_error})
        else:
            signature_valid, signature_reason = verify_ed25519_signature(source_attestation)
            strict_source = bool(config.get("strict_source_attestation"))
            bad: list[dict] = []
            if source_attestation.get("signoff_status") not in SOURCE_ATTESTATION_APPROVED_STATUSES:
                bad.append({"field": "source_attestation.signoff_status", "expected": sorted(SOURCE_ATTESTATION_APPROVED_STATUSES), "actual": source_attestation.get("signoff_status")})
            if not signature_valid:
                bad.append({"field": "source_attestation.signature", "expected": "valid ed25519 signature", "actual": signature_reason})
            if strict_source and source_attestation.get("attestation_mode") in SOURCE_ATTESTATION_STRICT_FAIL_MODES:
                bad.append({"field": "source_attestation.attestation_mode", "expected": "operator|external", "actual": source_attestation.get("attestation_mode")})
            if config.get("require_dual_signoff") and source_attestation.get("signoff_status") != "approved_dual":
                bad.append({"field": "source_attestation.signoff_status", "expected": "approved_dual", "actual": source_attestation.get("signoff_status")})
            if config.get("require_dual_signoff") and same_identity(source_attestation.get("operator_identity"), source_attestation.get("reviewer_identity")):
                bad.append({"field": "source_attestation.reviewer_identity", "expected": "distinct from operator_identity", "actual": source_attestation.get("reviewer_identity")})
            if bad:
                checks.append({"name": "signed_signoff", "status": "deny", "expected": "approved signed source attestation", "actual": bad, "message": "signed signoff requirements are not satisfied"})
                findings.append({"kind": "signed_signoff_invalid", "message": "signed signoff requirements are not satisfied", "expected": "approved signed source attestation", "actual": bad})
            else:
                checks.append({"name": "signed_signoff", "status": "ok", "expected": "approved signed source attestation", "actual": {"signoff_status": source_attestation.get("signoff_status"), "attestation_mode": source_attestation.get("attestation_mode")}, "message": None})
    elif config.get("require_signed_signoff"):
        checks.append({"name": "signed_signoff", "status": "skip", "expected": None, "actual": None, "message": "release denied (no signed signoff needed)"})
    else:
        checks.append({"name": "signed_signoff", "status": "skip", "expected": None, "actual": None, "message": "skipped (require_signed_signoff false)"})

    # 9. Input-commitment binding enforcement.
    if config.get("require_bound_input_commitment") and released:
        if source_attestation_load_error is not None or source_attestation is None:
            checks.append({"name": "bound_input_commitment", "status": "deny", "expected": "source attestation with bound input commitment", "actual": source_attestation_load_error, "message": "input commitment binding requires a valid source attestation"})
            findings.append({"kind": "bound_input_commitment_missing", "message": "input commitment binding requires a valid source attestation", "expected": "valid source attestation", "actual": source_attestation_load_error})
        else:
            policy_audit = _latest_policy_audit_record(policy_audit_log_path, job_id=job_id) if policy_audit_log_path is not None else None
            policy_governance = policy_audit.get("governance") if isinstance(policy_audit, dict) and isinstance(policy_audit.get("governance"), dict) else {}
            expected_commitment = source_attestation.get("input_commitment_sha256")
            actual_commitment = policy_governance.get("input_commitment_sha256")
            if expected_commitment != actual_commitment:
                checks.append({"name": "bound_input_commitment", "status": "deny", "expected": expected_commitment, "actual": actual_commitment, "message": "policy audit input commitment binding does not match source attestation"})
                findings.append({"kind": "bound_input_commitment_mismatch", "message": "policy audit input commitment binding does not match source attestation", "expected": expected_commitment, "actual": actual_commitment})
            else:
                checks.append({"name": "bound_input_commitment", "status": "ok", "expected": expected_commitment, "actual": actual_commitment, "message": None})
    elif config.get("require_bound_input_commitment"):
        checks.append({"name": "bound_input_commitment", "status": "skip", "expected": None, "actual": None, "message": "release denied (no bound input commitment needed)"})
    else:
        checks.append({"name": "bound_input_commitment", "status": "skip", "expected": None, "actual": None, "message": "skipped (require_bound_input_commitment false)"})

    # 10. PJC two-party evidence merge binding. This is optional by config so
    # existing local demos stay compatible, but production release configs can
    # require that both parties signed the same result/commitment evidence.
    if config.get("require_pjc_evidence_merge") and released:
        if pjc_evidence_merge_path is None or not pjc_evidence_merge_path.is_file():
            checks.append({"name": "pjc_evidence_merge", "status": "deny", "expected": "pjc_two_party_evidence_merge/v1", "actual": str(pjc_evidence_merge_path) if pjc_evidence_merge_path else None, "message": "PJC evidence merge report is required"})
            findings.append({"kind": "pjc_evidence_merge_missing", "message": "PJC evidence merge report is required for release", "expected": "file", "actual": str(pjc_evidence_merge_path) if pjc_evidence_merge_path else None})
        else:
            try:
                merge = _load_json_object(pjc_evidence_merge_path)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                merge = {}
                checks.append({"name": "pjc_evidence_merge", "status": "deny", "expected": "valid JSON report", "actual": str(exc), "message": "PJC evidence merge report is invalid"})
                findings.append({"kind": "pjc_evidence_merge_invalid", "message": "PJC evidence merge report is invalid", "expected": "valid JSON", "actual": str(exc)})
            if merge:
                merge_decision = str(merge.get("decision") or "")
                merge_job_id = str(merge.get("job_id") or "") or None
                party_a = merge.get("party_a") if isinstance(merge.get("party_a"), dict) else {}
                party_b = merge.get("party_b") if isinstance(merge.get("party_b"), dict) else {}
                public_sha = _sha256(public_report_path) if public_report_path.is_file() else None
                policy_audit = _latest_policy_audit_record(policy_audit_log_path, job_id=job_id) if policy_audit_log_path is not None else None
                pjc_result_sha = policy_audit.get("pjc_result_sha256") if isinstance(policy_audit, dict) else None
                mismatches: list[dict] = []
                if merge_decision != "allow":
                    mismatches.append({"field": "decision", "expected": "allow", "actual": merge_decision})
                if merge_job_id != job_id:
                    mismatches.append({"field": "job_id", "expected": job_id, "actual": merge_job_id})
                if policy_audit_log_path is None:
                    mismatches.append({"field": "policy_audit_log", "expected": "configured", "actual": None})
                elif policy_audit is None:
                    mismatches.append({"field": "policy_audit_record", "expected": f"record for {job_id}", "actual": None})
                if pjc_result_sha:
                    for party_label, party in (("party_a", party_a), ("party_b", party_b)):
                        if party.get("result_sha256") != pjc_result_sha:
                            mismatches.append({"field": f"{party_label}.result_sha256", "expected": pjc_result_sha, "actual": party.get("result_sha256")})
                for party_label, party in (("party_a", party_a), ("party_b", party_b)):
                    party_public_sha = party.get("public_report_sha256")
                    if party_public_sha and party_public_sha != public_sha:
                        mismatches.append({"field": f"{party_label}.public_report_sha256", "expected": public_sha, "actual": party_public_sha})
                if mismatches:
                    checks.append({"name": "pjc_evidence_merge", "status": "deny", "expected": "merge allow and result/report hashes bound", "actual": mismatches, "message": "PJC evidence merge is not bound to this release"})
                    findings.append({"kind": "pjc_evidence_merge_unbound", "message": "PJC evidence merge is not bound to this release", "expected": "matching job/result/report hashes", "actual": mismatches})
                else:
                    checks.append({"name": "pjc_evidence_merge", "status": "ok", "expected": "bound evidence merge", "actual": str(pjc_evidence_merge_path), "message": None})
    elif config.get("require_pjc_evidence_merge"):
        checks.append({"name": "pjc_evidence_merge", "status": "skip", "expected": None, "actual": None, "message": "release denied (no public evidence binding needed)"})
    else:
        checks.append({"name": "pjc_evidence_merge", "status": "skip", "expected": None, "actual": None, "message": "skipped (require_pjc_evidence_merge false)"})

    # 11. External immutable anchor binding. This deliberately allows local
    # contract configs to skip the check, while strict production configs can
    # require a real uploaded s3_worm/Rekor anchor report before release is
    # considered public.
    if config.get("require_external_anchor") and released:
        if external_anchor_report_path is None or not external_anchor_report_path.is_file():
            checks.append({"name": "external_anchor", "status": "deny", "expected": "external_audit_anchor_report/v1", "actual": str(external_anchor_report_path) if external_anchor_report_path else None, "message": "external immutable anchor report is required"})
            findings.append({"kind": "external_anchor_missing", "message": "external immutable anchor report is required for release", "expected": "file", "actual": str(external_anchor_report_path) if external_anchor_report_path else None})
        else:
            try:
                anchor = _load_json_object(external_anchor_report_path)
                anchor_schema = load_json(str(REPO_ROOT / "schemas" / "external_audit_anchor_report.schema.json"))
                validate_value(anchor, anchor_schema)
            except Exception as exc:
                anchor = {}
                checks.append({"name": "external_anchor", "status": "deny", "expected": "valid JSON report", "actual": str(exc), "message": "external anchor report is invalid"})
                findings.append({"kind": "external_anchor_invalid", "message": "external anchor report is invalid", "expected": "valid JSON", "actual": str(exc)})
            if anchor:
                status = _external_anchor_status(anchor)
                bad: list[dict] = []
                if anchor.get("schema") != "external_audit_anchor_report/v1":
                    bad.append({"field": "schema", "expected": "external_audit_anchor_report/v1", "actual": anchor.get("schema")})
                if status["kind"] not in {"s3_worm", "rekor"}:
                    bad.append({"field": "external_sink.kind", "expected": "s3_worm|rekor", "actual": status["kind"]})
                if status["summary_status"] != "ok":
                    bad.append({"field": "summary.status", "expected": "ok", "actual": status["summary_status"]})
                if status["sink_status"] != "uploaded":
                    bad.append({"field": "sink.status", "expected": "uploaded", "actual": status["sink_status"]})
                if status["executed"] is not True:
                    bad.append({"field": "sink.executed", "expected": True, "actual": status["executed"]})
                if status["verified_chain"] is not True:
                    bad.append({"field": "summary.verified_chain", "expected": True, "actual": status["verified_chain"]})
                if int(status["published_count"] or 0) < 1:
                    bad.append({"field": "summary.published_count", "expected": ">= 1", "actual": status["published_count"]})
                if int(status["anchor_record_count"] or 0) < 1:
                    bad.append({"field": "summary.anchor_record_count", "expected": ">= 1", "actual": status["anchor_record_count"]})
                if not status["last_entry_sha256"]:
                    bad.append({"field": "summary.last_entry_sha256", "expected": "present", "actual": status["last_entry_sha256"]})
                if status["production_findings"]:
                    bad.append({"field": "production_findings", "expected": [], "actual": status["production_findings"]})
                records = anchor.get("records") if isinstance(anchor.get("records"), list) else []
                matching_job_records = [item for item in records if isinstance(item, dict) and str(item.get("job_id") or "") == str(job_id or "")]
                if not matching_job_records:
                    bad.append({"field": "records.job_id", "expected": job_id, "actual": [item.get("job_id") for item in records if isinstance(item, dict)]})
                if bad:
                    checks.append({"name": "external_anchor", "status": "deny", "expected": "uploaded external immutable anchor", "actual": bad, "message": "external anchor report does not prove uploaded immutable anchoring"})
                    findings.append({"kind": "external_anchor_unuploaded", "message": "external anchor report does not prove uploaded immutable anchoring", "expected": "uploaded s3_worm/Rekor report", "actual": bad})
                else:
                    checks.append({"name": "external_anchor", "status": "ok", "expected": "uploaded external immutable anchor", "actual": status, "message": None})
    elif config.get("require_external_anchor"):
        checks.append({"name": "external_anchor", "status": "skip", "expected": None, "actual": None, "message": "release denied (no external anchor needed for denied report)"})
    else:
        checks.append({"name": "external_anchor", "status": "skip", "expected": None, "actual": None, "message": "skipped (require_external_anchor false)"})

    decision = "allow"
    chosen_reason_code = "ok"
    chosen_reason: str | None = None
    for chk in checks:
        if chk["status"] == "deny":
            decision = "deny"
            chosen_reason = chk.get("message")
            first_finding_kind = next(
                (
                    str(item.get("kind"))
                    for item in findings
                    if str(item.get("kind") or "").startswith(str(chk["name"]).replace("_", "-"))
                ),
                None,
            )
            # Most finding kinds predate check-name prefixes, so keep an
            # explicit mapping but avoid using findings[0] from an earlier
            # failed check.
            finding_by_check = {
                "dp_enforced": next((item["kind"] for item in findings if item.get("kind") in {"dp_required", "dp_epsilon_too_small", "dp_epsilon_too_large"}), None),
                "privacy_budget_ledger": next((item["kind"] for item in findings if str(item.get("kind", "")).startswith(("privacy_budget_", "budget_ledger_"))), None),
                "public_report_redaction": next((item["kind"] for item in findings if str(item.get("kind", "")).startswith(("public_report_", "operator_report_"))), None),
                "source_attestation": next((item["kind"] for item in findings if str(item.get("kind", "")).startswith(("source_attestation_", "source_truthfulness_"))), None),
                "signed_signoff": next((item["kind"] for item in findings if str(item.get("kind", "")).startswith("signed_signoff_")), None),
                "bound_input_commitment": next((item["kind"] for item in findings if str(item.get("kind", "")).startswith("bound_input_commitment_")), None),
                "pjc_evidence_merge": next((item["kind"] for item in findings if str(item.get("kind", "")).startswith("pjc_evidence_merge_")), None),
                "external_anchor": next((item["kind"] for item in findings if str(item.get("kind", "")).startswith("external_anchor_")), None),
            }
            # Map the first failing check name to a reason code
            chosen_reason_code = {
                "dp_enforced": finding_by_check.get("dp_enforced") or first_finding_kind or "dp_required",
                "min_k": "min_k_violation",
                "privacy_budget_ledger": finding_by_check.get("privacy_budget_ledger") or first_finding_kind or "privacy_budget_required",
                "deny_reason_code": "deny_reason_not_allowed",
                "duplicate_query": "duplicate_query_leaked",
                "public_report_redaction": finding_by_check.get("public_report_redaction") or first_finding_kind or "public_report_redaction_required",
                "source_attestation": finding_by_check.get("source_attestation") or first_finding_kind or "source_attestation_required",
                "signed_signoff": finding_by_check.get("signed_signoff") or first_finding_kind or "signed_signoff_required",
                "bound_input_commitment": finding_by_check.get("bound_input_commitment") or first_finding_kind or "bound_input_commitment_required",
                "pjc_evidence_merge": finding_by_check.get("pjc_evidence_merge") or first_finding_kind or "pjc_evidence_merge_required",
                "external_anchor": finding_by_check.get("external_anchor") or first_finding_kind or "external_anchor_required",
            }.get(chk["name"], "policy_gate_denied")
            break

    return {
        "schema": SCHEMA,
        "generated_at_utc": _utc_now(),
        "decision": decision,
        "reason_code": chosen_reason_code,
        "reason": chosen_reason,
        "public_report_path": str(public_report_path),
        "public_report_sha256": _sha256(public_report_path) if public_report_path.is_file() else None,
        "operator_report_path": str(operator_report_path) if operator_report_path else None,
        "policy_config_path": str(policy_config_path),
        "pjc_evidence_merge_path": str(pjc_evidence_merge_path) if pjc_evidence_merge_path else None,
        "policy_audit_log_path": str(policy_audit_log_path) if policy_audit_log_path else None,
        "external_anchor_report_path": str(external_anchor_report_path) if external_anchor_report_path else None,
        "source_attestation_path": str(source_attestation_path) if source_attestation_path else None,
        "source_truthfulness_report_path": str(source_truthfulness_report_path) if source_truthfulness_report_path else None,
        "job_id": job_id,
        "caller": caller,
        "checks": checks,
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Server-side release policy gate")
    parser.add_argument("--public-report", required=True)
    parser.add_argument("--policy-config", required=True)
    parser.add_argument("--operator-report", default=None)
    parser.add_argument("--privacy-budget-ledger", default=None)
    parser.add_argument("--pjc-evidence-merge", default=None)
    parser.add_argument("--policy-audit-log", default=None)
    parser.add_argument("--external-anchor-report", default=None)
    parser.add_argument("--source-attestation", default=None)
    parser.add_argument("--source-truthfulness-report", default=None)
    parser.add_argument("--output", required=True)
    parser.add_argument("--assert-allow", action="store_true")
    args = parser.parse_args(argv)

    public_report = Path(args.public_report).resolve()
    config_path = Path(args.policy_config).resolve()
    operator_report = Path(args.operator_report).resolve() if args.operator_report else None
    budget_ledger = Path(args.privacy_budget_ledger).resolve() if args.privacy_budget_ledger else None
    pjc_evidence_merge = Path(args.pjc_evidence_merge).resolve() if args.pjc_evidence_merge else None
    policy_audit_log = Path(args.policy_audit_log).resolve() if args.policy_audit_log else None
    external_anchor_report = Path(args.external_anchor_report).resolve() if args.external_anchor_report else None
    source_attestation = Path(args.source_attestation).resolve() if args.source_attestation else None
    source_truthfulness_report = Path(args.source_truthfulness_report).resolve() if args.source_truthfulness_report else None
    out_path = Path(args.output).resolve()

    report = run_gate(
        public_report_path=public_report,
        policy_config_path=config_path,
        operator_report_path=operator_report,
        budget_ledger_path=budget_ledger,
        pjc_evidence_merge_path=pjc_evidence_merge,
        policy_audit_log_path=policy_audit_log,
        external_anchor_report_path=external_anchor_report,
        source_attestation_path=source_attestation,
        source_truthfulness_report_path=source_truthfulness_report,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if args.assert_allow and report["decision"] != "allow":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
