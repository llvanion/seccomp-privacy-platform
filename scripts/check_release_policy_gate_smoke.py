#!/usr/bin/env python3
"""Focused smoke for the server-side release policy gate.

Covers the bypass cases the gate is meant to close:

1. Missing budget ledger -> deny ``privacy_budget_missing_config``.
2. Low-k released report -> deny ``min_k_violation``.
3. Released report without DP metadata -> deny ``dp_required``.
4. Released report with proper DP + ledger entry + redaction -> allow.
5. Released report whose ledger record records a duplicate-query deny -> deny.
6. Released report that leaks operator-only fields -> deny.
7. Released report with required PJC evidence bound to policy audit -> allow.
8. Mismatched PJC evidence result hash -> deny.
9. Missing required external immutable anchor -> deny.
10. Local/planned anchor report -> deny.
11. Uploaded S3 Object Lock anchor report -> allow.
12. Missing required source attestation -> deny.
13. Bound source attestation + signed signoff + input commitment -> allow.
14. Input commitment binding mismatch -> deny.
15. Source truthfulness / scope mismatch -> deny.
16. Signed signoff missing -> deny.
17. Strict source-attestation mode / staleness -> deny.

Every emitted report is validated against
``schemas/release_policy_gate.schema.json``.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_release_policy_gate import run_gate  # noqa: E402
from source_attestation_lib import attach_ed25519_signature, write_json  # noqa: E402
from validate_json_contract import load_json, validate_value  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402


SCHEMA = load_json(str(REPO_ROOT / "schemas" / "release_policy_gate.schema.json"))
TOTAL_TESTS = 19


def _validate(report: dict) -> None:
    validate_value(report, SCHEMA)


def utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_config(tmp: Path, overrides: dict | None = None) -> Path:
    config = {
        "schema": "release_policy_gate_config/v1",
        "require_dp": True,
        "min_dp_epsilon": 0.1,
        "max_dp_epsilon": 5.0,
        "min_k": 20,
        "require_privacy_budget": True,
        "budget_ledger_path": str(tmp / "ledger.jsonl"),
        "duplicate_query_denied": True,
        "require_public_report_redaction": False,
        "require_dual_signoff": False,
        "allowed_deny_reason_codes": [
            "below_k", "privacy_budget_exhausted",
            "privacy_budget_duplicate_query", "privacy_budget_near_duplicate",
            "privacy_budget_bucket_probe",
            "rate_limit_exceeded",
        ],
    }
    if overrides:
        config.update(overrides)
    path = tmp / "policy.json"
    path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
    return path


def _write_public_report(tmp: Path, *, name: str, payload: dict) -> Path:
    path = tmp / f"{name}.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _write_pjc_binding_artifacts(tmp: Path, *, job_id: str, public_report: Path, result_sha: str, party_result_sha: str | None = None) -> tuple[Path, Path]:
    audit_log = tmp / "policy_audit.jsonl"
    audit_log.write_text(json.dumps({
        "event": "policy_release",
        "job_id": job_id,
        "pjc_result_sha256": result_sha,
    }, sort_keys=True) + "\n", encoding="utf-8")
    public_sha = _sha256(public_report)
    party_sha = party_result_sha or result_sha
    merge = {
        "schema": "pjc_two_party_evidence_merge/v1",
        "generated_at_utc": "2026-06-01T00:00:00Z",
        "job_id": job_id,
        "decision": "allow",
        "reason_code": "ok",
        "party_a": {
            "source": str(tmp / "party_a"),
            "job_id": job_id,
            "result_sha256": party_sha,
            "public_report_sha256": public_sha,
            "missing_files": [],
        },
        "party_b": {
            "source": str(tmp / "party_b"),
            "job_id": job_id,
            "result_sha256": party_sha,
            "public_report_sha256": public_sha,
            "missing_files": [],
        },
        "checks": {
            "manifest_signature_valid": "match",
            "job_id_match": "match",
            "commit_match": "match",
            "input_commitment_match": "match",
            "commitment_exchange_match": "match",
            "bucket_policy_match": "match",
            "shard_manifest_match": "match",
            "tls_identity_match": "match",
            "ca_fingerprint_match": "match",
            "result_hash_match": "match",
            "policy_decision_match": "match",
            "audit_chain_match": "match",
        },
        "findings": [],
    }
    merge_path = tmp / "pjc_evidence_merge.json"
    merge_path.write_text(json.dumps(merge, sort_keys=True), encoding="utf-8")
    return merge_path, audit_log


def _write_external_anchor_report(
    tmp: Path,
    *,
    job_id: str,
    uploaded: bool,
    kind: str = "s3_worm",
) -> Path:
    entry_sha = "d" * 64
    payload_sha = "e" * 64
    index_sha = "f" * 64
    if kind == "s3_worm":
        sink = {
            "kind": "s3_worm",
            "path": "s3://audit-bucket/tenant/audit_anchor.jsonl",
            "tenant_id": None,
            "s3_object_lock": {
                "bucket": "audit-bucket",
                "key": "tenant/audit_anchor.jsonl",
                "object_lock_mode": "COMPLIANCE",
                "retain_until_utc": "2036-01-01T00:00:00Z",
                "retain_days": 3650,
                "executed": uploaded,
                "status": "uploaded" if uploaded else "planned",
                "details": "synthetic smoke fixture",
                "etag": "etag-1" if uploaded else None,
                "version_id": "version-1" if uploaded else None,
                "previous_object_etag": None,
            },
        }
    elif kind == "file_ledger":
        sink = {
            "kind": "file_ledger",
            "path": str(tmp / "external_anchor_ledger.jsonl"),
            "tenant_id": None,
        }
    else:
        raise ValueError(f"unsupported external anchor fixture kind: {kind}")
    report = {
        "schema": "external_audit_anchor_report/v1",
        "generated_at_utc": "2026-06-03T00:00:00Z",
        "source_anchor_file": str(tmp / "audit_chain_anchor.jsonl"),
        "tenant_id": None,
        "production_mode": True,
        "production_findings": [] if uploaded and kind == "s3_worm" else [{
            "kind": "production_external_anchor_not_uploaded",
            "message": "synthetic planned/local anchor",
            "ref": None,
        }],
        "external_sink": sink,
        "mode": "publish" if uploaded else "dry_run",
        "summary": {
            "status": "ok",
            "anchor_record_count": 1,
            "published_count": 1 if uploaded else 0,
            "verified_chain": True,
            "signed_count": 1,
            "last_entry_sha256": entry_sha,
            "tenant_id": None,
        },
        "records": [{
            "job_id": job_id,
            "chain_position": 1,
            "entry_sha256": entry_sha,
            "payload_sha256": payload_sha,
            "index_record_sha256": index_sha,
            "signature_algorithm": "hmac-sha256",
            "signature_verified": True,
            "tenant_id": None,
            "published": uploaded,
        }],
    }
    path = tmp / f"external_anchor_{kind}_{'uploaded' if uploaded else 'planned'}.json"
    path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    return path


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_ed25519_key(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def _write_source_attestation_bundle(
    tmp: Path,
    *,
    job_id: str,
    caller: str = "attestation_caller",
    dataset: str = "orders_analytics",
    sign_attestation: bool = True,
    signoff_status: str = "approved_dual",
    attestation_mode: str = "operator",
    max_age_hours: float = 0.0,
    stale: bool = False,
    truthfulness_decision: str = "allow",
    require_dual_signoff: bool = False,
    reviewer_identity: str = "compliance_auditor_demo",
) -> tuple[Path, Path, Path, Path | None]:
    source_attestation_path = tmp / "source_attestation.json"
    source_truthfulness_report_path = tmp / "source_truthfulness_report.json"
    operator_report_path = tmp / "operator.json"
    signing_key = tmp / "source_attestation_ed25519.pem"
    if sign_attestation:
        _write_ed25519_key(signing_key)

    created_at = "2025-01-01T00:00:00Z" if stale else utc_now_iso()
    attestation = {
        "schema": "source_attestation/v1",
        "generated_at_utc": created_at,
        "tenant": "commerce_tenant",
        "dataset": dataset,
        "purpose": "campaign_measurement",
        "job_id": job_id,
        "caller": caller,
        "source_system": "ecommerce_fact_import",
        "source_snapshot_sha256": "1" * 64,
        "bridge_input_sha256": "2" * 64,
        "input_commitment_sha256": "3" * 64,
        "sealed_export_manifest_sha256": "4" * 64,
        "approval_id": "approval-source-smoke",
        "operator_identity": "privacy_operator_demo",
        "operator_signed_at_utc": created_at,
        "reviewer_identity": reviewer_identity,
        "reviewer_signed_at_utc": created_at,
        "signoff_status": signoff_status,
        "attestation_mode": attestation_mode,
        "created_at_utc": created_at,
        "signed_at_utc": None,
        "signature_algorithm": None,
        "canonicalization": None,
        "payload_sha256": None,
        "signature": None,
        "public_key_pem": None,
        "public_key_fingerprint_sha256": None,
    }
    if sign_attestation:
        attestation = attach_ed25519_signature(attestation=attestation, signing_key_path=signing_key, signed_at_utc=created_at)
    write_json(source_attestation_path, attestation)
    attestation_sha = _sha256(source_attestation_path)
    truthfulness_report = {
        "schema": "source_truthfulness_report/v1",
        "generated_at_utc": created_at,
        "decision": truthfulness_decision,
        "reason_code": "ok" if truthfulness_decision == "allow" else "source_truthfulness_denied",
        "reason": None if truthfulness_decision == "allow" else "synthetic deny",
        "strict_mode": True,
        "max_age_hours": max_age_hours,
        "require_signed_signoff": True,
        "require_dual_signoff": require_dual_signoff,
        "job_id": job_id,
        "caller": caller,
        "tenant": "commerce_tenant",
        "dataset": dataset,
        "purpose": "campaign_measurement",
        "attestation_path": str(source_attestation_path),
        "attestation_sha256": attestation_sha,
        "source_export_manifest_path": None,
        "source_export_manifest_sha256": None,
        "summary": {
            "source_attestation_mode": attestation_mode,
            "signoff_status": signoff_status,
            "input_commitment_sha256": attestation["input_commitment_sha256"],
        },
        "checks": [],
        "findings": [],
    }
    write_json(source_truthfulness_report_path, truthfulness_report)
    operator_report_path.write_text(
        json.dumps(
            {
                "schema": "operator_release_report/v1",
            "governance": {
                "source_attestation_sha256": attestation_sha,
                "source_truthfulness_report_sha256": _sha256(source_truthfulness_report_path),
                "source_attestation_signoff_status": signoff_status,
                "input_commitment_sha256": attestation["input_commitment_sha256"],
            },
        },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return source_attestation_path, source_truthfulness_report_path, operator_report_path, signing_key if sign_attestation else None


def test_missing_budget_ledger() -> None:
    print(f"[1/{TOTAL_TESTS}] missing budget ledger -> deny ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        config_path = _write_config(tmp, overrides={"budget_ledger_path": str(tmp / "does_not_exist.jsonl")})
        public_path = _write_public_report(tmp, name="public_allow", payload={
            "schema": "public_report/v2", "job_id": "smoke-1", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
        })
        report = run_gate(
            public_report_path=public_path,
            policy_config_path=config_path,
            operator_report_path=None,
            budget_ledger_path=None,
            pjc_evidence_merge_path=None,
            policy_audit_log_path=None,
        )
        _validate(report)
        assert report["decision"] == "deny", report
        assert report["reason_code"] == "privacy_budget_missing_config", report
    print("       OK")


def test_low_k_denial() -> None:
    print(f"[2/{TOTAL_TESTS}] low-k released report -> deny ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-2", "decision": "allow"}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp)
        public_path = _write_public_report(tmp, name="public_lowk", payload={
            "schema": "public_report/v2", "job_id": "smoke-2", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 5,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
        })
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=None, budget_ledger_path=ledger)
        _validate(report)
        assert report["decision"] == "deny", report
        # The first failing check in our order is dp_enforced -> ok, min_k -> deny
        assert report["reason_code"] == "min_k_violation", report
    print("       OK")


def test_missing_dp_denial() -> None:
    print(f"[3/{TOTAL_TESTS}] released report without DP metadata -> deny ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-3", "decision": "allow"}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp)
        public_path = _write_public_report(tmp, name="public_no_dp", payload={
            "schema": "public_report/v2", "job_id": "smoke-3", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": False, "dp_epsilon": None,
        })
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=None, budget_ledger_path=ledger)
        _validate(report)
        assert report["decision"] == "deny", report
        assert report["reason_code"] == "dp_required", report
    print("       OK")


def test_allowed_release() -> None:
    print(f"[4/{TOTAL_TESTS}] proper release -> allow ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-4", "decision": "allow",
                                       "privacy_budget": {"decision": "allow"}}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp, overrides={"require_public_report_redaction": True})
        op_path = tmp / "operator.json"
        op_path.write_text(json.dumps({"schema": "operator_release_report/v1"}), encoding="utf-8")
        public_path = _write_public_report(tmp, name="public_ok", payload={
            "schema": "public_report/v2", "job_id": "smoke-4", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
            "operator_fields_redacted": True,
        })
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=op_path, budget_ledger_path=ledger)
        _validate(report)
        assert report["decision"] == "allow", report
        assert report["reason_code"] == "ok", report
    print("       OK")


def test_duplicate_query_denied() -> None:
    print(f"[5/{TOTAL_TESTS}] duplicate-query budget decision leaked -> deny ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-5", "decision": "allow"}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp)
        public_path = _write_public_report(tmp, name="public_dup", payload={
            "schema": "public_report/v2", "job_id": "smoke-5", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
        })
        op_path = tmp / "operator.json"
        op_path.write_text(json.dumps({
            "privacy_budget": {"decision": "deny", "reason_code": "privacy_budget_duplicate_query"}
        }), encoding="utf-8")
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=op_path, budget_ledger_path=ledger)
        _validate(report)
        assert report["decision"] == "deny", report
        assert report["reason_code"] == "duplicate_query_leaked", report
    print("       OK")


def test_operator_fields_leaked() -> None:
    print(f"[6/{TOTAL_TESTS}] released report leaking operator-only fields -> deny ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-6", "decision": "allow",
                                       "privacy_budget": {"decision": "allow"}}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp, overrides={"require_public_report_redaction": True})
        public_path = _write_public_report(tmp, name="public_leaky", payload={
            "schema": "public_report/v2", "job_id": "smoke-6", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
            "operator_fields_redacted": False,
            "input_sizes": {"server": 10, "client": 10},
        })
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=None, budget_ledger_path=ledger)
        _validate(report)
        assert report["decision"] == "deny", report
        assert report["reason_code"] == "public_report_operator_fields_leaked", report
    print("       OK")


def test_pjc_evidence_binding_allow() -> None:
    print(f"[7/{TOTAL_TESTS}] required PJC evidence binding -> allow ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-7", "decision": "allow",
                                       "privacy_budget": {"decision": "allow"}}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp, overrides={"require_pjc_evidence_merge": True})
        public_path = _write_public_report(tmp, name="public_pjc_bound", payload={
            "schema": "public_report/v2", "job_id": "smoke-7", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
        })
        result_sha = "a" * 64
        merge_path, audit_log = _write_pjc_binding_artifacts(tmp, job_id="smoke-7", public_report=public_path, result_sha=result_sha)
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=None, budget_ledger_path=ledger,
                          pjc_evidence_merge_path=merge_path, policy_audit_log_path=audit_log)
        _validate(report)
        assert report["decision"] == "allow", report
        assert next(check for check in report["checks"] if check["name"] == "pjc_evidence_merge")["status"] == "ok", report
    print("       OK")


def test_pjc_evidence_binding_result_mismatch() -> None:
    print(f"[8/{TOTAL_TESTS}] PJC evidence result replacement -> deny ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-8", "decision": "allow",
                                       "privacy_budget": {"decision": "allow"}}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp, overrides={"require_pjc_evidence_merge": True})
        public_path = _write_public_report(tmp, name="public_pjc_bad", payload={
            "schema": "public_report/v2", "job_id": "smoke-8", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
        })
        merge_path, audit_log = _write_pjc_binding_artifacts(
            tmp,
            job_id="smoke-8",
            public_report=public_path,
            result_sha="b" * 64,
            party_result_sha="c" * 64,
        )
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=None, budget_ledger_path=ledger,
                          pjc_evidence_merge_path=merge_path, policy_audit_log_path=audit_log)
        _validate(report)
        assert report["decision"] == "deny", report
        assert report["reason_code"] == "pjc_evidence_merge_unbound", report
    print("       OK")


def test_external_anchor_missing() -> None:
    print(f"[9/{TOTAL_TESTS}] missing external immutable anchor -> deny ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-9", "decision": "allow",
                                       "privacy_budget": {"decision": "allow"}}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp, overrides={"require_external_anchor": True})
        public_path = _write_public_report(tmp, name="public_anchor_missing", payload={
            "schema": "public_report/v2", "job_id": "smoke-9", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
        })
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=None, budget_ledger_path=ledger)
        _validate(report)
        assert report["decision"] == "deny", report
        assert report["reason_code"] == "external_anchor_missing", report
    print("       OK")


def test_external_anchor_planned_denied() -> None:
    print(f"[10/{TOTAL_TESTS}] local/planned external anchor -> deny ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-10", "decision": "allow",
                                       "privacy_budget": {"decision": "allow"}}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp, overrides={"require_external_anchor": True})
        public_path = _write_public_report(tmp, name="public_anchor_planned", payload={
            "schema": "public_report/v2", "job_id": "smoke-10", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
        })
        anchor_path = _write_external_anchor_report(tmp, job_id="smoke-10", uploaded=False)
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=None, budget_ledger_path=ledger,
                          external_anchor_report_path=anchor_path)
        _validate(report)
        assert report["decision"] == "deny", report
        assert report["reason_code"] == "external_anchor_unuploaded", report
    print("       OK")


def test_external_anchor_uploaded_allow() -> None:
    print(f"[11/{TOTAL_TESTS}] uploaded external immutable anchor -> allow ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-11", "decision": "allow",
                                       "privacy_budget": {"decision": "allow"}}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp, overrides={"require_external_anchor": True})
        public_path = _write_public_report(tmp, name="public_anchor_uploaded", payload={
            "schema": "public_report/v2", "job_id": "smoke-11", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
        })
        anchor_path = _write_external_anchor_report(tmp, job_id="smoke-11", uploaded=True)
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=None, budget_ledger_path=ledger,
                          external_anchor_report_path=anchor_path)
        _validate(report)
        assert report["decision"] == "allow", report
        assert next(check for check in report["checks"] if check["name"] == "external_anchor")["status"] == "ok", report
    print("       OK")


def test_source_attestation_missing() -> None:
    print(f"[12/{TOTAL_TESTS}] missing required source attestation -> deny ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-12", "decision": "allow", "privacy_budget": {"decision": "allow"}}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp, overrides={
            "require_privacy_budget": False,
            "require_source_attestation": True,
            "require_signed_signoff": True,
            "require_dual_signoff": True,
            "require_bound_input_commitment": True,
            "strict_source_attestation": True,
            "max_source_attestation_age_hours": 24,
        })
        public_path = _write_public_report(tmp, name="public_attestation_missing", payload={
            "schema": "public_report/v2", "job_id": "smoke-12", "caller": "attestation_caller", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
        })
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=None, budget_ledger_path=ledger)
        _validate(report)
        assert report["decision"] == "deny", report
        assert report["reason_code"] == "source_attestation_missing", report
    print("       OK")


def test_source_attestation_binding_allow() -> None:
    print(f"[13/{TOTAL_TESTS}] bound source attestation -> allow ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-13", "decision": "allow", "privacy_budget": {"decision": "allow"}}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp, overrides={
            "require_privacy_budget": False,
            "require_source_attestation": True,
            "require_signed_signoff": True,
            "require_dual_signoff": True,
            "require_bound_input_commitment": True,
            "strict_source_attestation": True,
            "max_source_attestation_age_hours": 168,
        })
        attestation_path, truthfulness_path, operator_path, _signing_key = _write_source_attestation_bundle(tmp, job_id="smoke-13", max_age_hours=168, require_dual_signoff=True)
        attestation_sha = _sha256(attestation_path)
        truthfulness_sha = _sha256(truthfulness_path)
        public_path = _write_public_report(tmp, name="public_attestation_allow", payload={
            "schema": "public_report/v2", "job_id": "smoke-13", "caller": "attestation_caller", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
            "governance": {
                "source_attestation_sha256": attestation_sha,
                "source_truthfulness_report_sha256": truthfulness_sha,
                "source_attestation_signoff_status": "approved_dual",
                "input_commitment_sha256": "3" * 64,
            },
        })
        audit_log = tmp / "policy_audit.jsonl"
        audit_log.write_text(json.dumps({
            "event": "policy_release",
            "job_id": "smoke-13",
            "caller": "attestation_caller",
            "governance": {
                "source_attestation_sha256": attestation_sha,
                "source_truthfulness_report_sha256": truthfulness_sha,
                "source_attestation_signoff_status": "approved_dual",
                "input_commitment_sha256": "3" * 64,
            },
        }, sort_keys=True) + "\n", encoding="utf-8")
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=operator_path, budget_ledger_path=ledger,
                          policy_audit_log_path=audit_log,
                          source_attestation_path=attestation_path,
                          source_truthfulness_report_path=truthfulness_path)
        _validate(report)
        assert report["decision"] == "allow", report
        assert next(check for check in report["checks"] if check["name"] == "source_attestation")["status"] == "ok", report
        assert next(check for check in report["checks"] if check["name"] == "signed_signoff")["status"] == "ok", report
        assert next(check for check in report["checks"] if check["name"] == "bound_input_commitment")["status"] == "ok", report
    print("       OK")


def test_source_attestation_input_commitment_mismatch() -> None:
    print(f"[14/{TOTAL_TESTS}] bound input commitment mismatch -> deny ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-14", "decision": "allow", "privacy_budget": {"decision": "allow"}}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp, overrides={
            "require_privacy_budget": False,
            "require_source_attestation": True,
            "require_signed_signoff": True,
            "require_dual_signoff": True,
            "require_bound_input_commitment": True,
            "strict_source_attestation": True,
            "max_source_attestation_age_hours": 168,
        })
        attestation_path, truthfulness_path, operator_path, _signing_key = _write_source_attestation_bundle(tmp, job_id="smoke-14", max_age_hours=168, require_dual_signoff=True)
        attestation_sha = _sha256(attestation_path)
        truthfulness_sha = _sha256(truthfulness_path)
        public_path = _write_public_report(tmp, name="public_attestation_commit_bad", payload={
            "schema": "public_report/v2", "job_id": "smoke-14", "caller": "attestation_caller", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
            "governance": {
                "source_attestation_sha256": attestation_sha,
                "source_truthfulness_report_sha256": truthfulness_sha,
                "source_attestation_signoff_status": "approved_dual",
                "input_commitment_sha256": "3" * 64,
            },
        })
        audit_log = tmp / "policy_audit.jsonl"
        audit_log.write_text(json.dumps({
            "event": "policy_release",
            "job_id": "smoke-14",
            "caller": "attestation_caller",
            "governance": {
                "source_attestation_sha256": attestation_sha,
                "source_truthfulness_report_sha256": truthfulness_sha,
                "source_attestation_signoff_status": "approved_dual",
                "input_commitment_sha256": "9" * 64,
            },
        }, sort_keys=True) + "\n", encoding="utf-8")
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=operator_path, budget_ledger_path=ledger,
                          policy_audit_log_path=audit_log,
                          source_attestation_path=attestation_path,
                          source_truthfulness_report_path=truthfulness_path)
        _validate(report)
        assert report["decision"] == "deny", report
        assert report["reason_code"] == "bound_input_commitment_mismatch", report
    print("       OK")


def test_source_attestation_scope_mismatch() -> None:
    print(f"[15/{TOTAL_TESTS}] source attestation scope mismatch -> deny ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-15", "decision": "allow", "privacy_budget": {"decision": "allow"}}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp, overrides={
            "require_privacy_budget": False,
            "require_source_attestation": True,
            "require_signed_signoff": True,
            "require_dual_signoff": True,
            "require_bound_input_commitment": False,
            "strict_source_attestation": True,
            "max_source_attestation_age_hours": 168,
        })
        attestation_path, truthfulness_path, operator_path, _signing_key = _write_source_attestation_bundle(tmp, job_id="smoke-15", dataset="wrong_dataset", max_age_hours=168, truthfulness_decision="deny", require_dual_signoff=True)
        attestation_sha = _sha256(attestation_path)
        truthfulness_sha = _sha256(truthfulness_path)
        public_path = _write_public_report(tmp, name="public_attestation_scope_bad", payload={
            "schema": "public_report/v2", "job_id": "smoke-15", "caller": "attestation_caller", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
            "governance": {
                "source_attestation_sha256": attestation_sha,
                "source_truthfulness_report_sha256": truthfulness_sha,
                "source_attestation_signoff_status": "approved_dual",
                "input_commitment_sha256": "3" * 64,
            },
        })
        audit_log = tmp / "policy_audit.jsonl"
        audit_log.write_text(json.dumps({
            "event": "policy_release",
            "job_id": "smoke-15",
            "caller": "attestation_caller",
            "governance": {
                "source_attestation_sha256": attestation_sha,
                "source_truthfulness_report_sha256": truthfulness_sha,
                "source_attestation_signoff_status": "approved_dual",
                "input_commitment_sha256": "3" * 64,
            },
        }, sort_keys=True) + "\n", encoding="utf-8")
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=operator_path, budget_ledger_path=ledger,
                          policy_audit_log_path=audit_log,
                          source_attestation_path=attestation_path,
                          source_truthfulness_report_path=truthfulness_path)
        _validate(report)
        assert report["decision"] == "deny", report
        assert report["reason_code"] == "source_attestation_unbound", report
    print("       OK")


def test_signed_signoff_missing() -> None:
    print(f"[16/{TOTAL_TESTS}] signed signoff missing -> deny ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-16", "decision": "allow", "privacy_budget": {"decision": "allow"}}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp, overrides={
            "require_privacy_budget": False,
            "require_source_attestation": True,
            "require_signed_signoff": True,
            "require_dual_signoff": True,
            "require_bound_input_commitment": False,
            "strict_source_attestation": False,
            "max_source_attestation_age_hours": 168,
        })
        attestation_path, truthfulness_path, operator_path, _signing_key = _write_source_attestation_bundle(tmp, job_id="smoke-16", sign_attestation=False, max_age_hours=168, require_dual_signoff=True)
        attestation_sha = _sha256(attestation_path)
        truthfulness_sha = _sha256(truthfulness_path)
        public_path = _write_public_report(tmp, name="public_attestation_unsigned", payload={
            "schema": "public_report/v2", "job_id": "smoke-16", "caller": "attestation_caller", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
            "governance": {
                "source_attestation_sha256": attestation_sha,
                "source_truthfulness_report_sha256": truthfulness_sha,
                "source_attestation_signoff_status": "approved_dual",
                "input_commitment_sha256": "3" * 64,
            },
        })
        audit_log = tmp / "policy_audit.jsonl"
        audit_log.write_text(json.dumps({
            "event": "policy_release",
            "job_id": "smoke-16",
            "caller": "attestation_caller",
            "governance": {
                "source_attestation_sha256": attestation_sha,
                "source_truthfulness_report_sha256": truthfulness_sha,
                "source_attestation_signoff_status": "approved_dual",
                "input_commitment_sha256": "3" * 64,
            },
        }, sort_keys=True) + "\n", encoding="utf-8")
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=operator_path, budget_ledger_path=ledger,
                          policy_audit_log_path=audit_log,
                          source_attestation_path=attestation_path,
                          source_truthfulness_report_path=truthfulness_path)
        _validate(report)
        assert report["decision"] == "deny", report
        assert report["reason_code"] == "signed_signoff_invalid", report
    print("       OK")


def test_strict_source_attestation_modes_and_stale() -> None:
    print(f"[17/{TOTAL_TESTS}] strict planned/local/manual/stale source attestation -> deny ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-17", "decision": "allow", "privacy_budget": {"decision": "allow"}}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp, overrides={
            "require_privacy_budget": False,
            "require_source_attestation": True,
            "require_signed_signoff": True,
            "require_dual_signoff": True,
            "require_bound_input_commitment": False,
            "strict_source_attestation": True,
            "max_source_attestation_age_hours": 24,
        })

        for idx, mode in enumerate(("planned", "local", "manual"), start=1):
            case_dir = tmp / f"mode_{mode}"
            attestation_path, truthfulness_path, operator_path, _signing_key = _write_source_attestation_bundle(case_dir, job_id=f"smoke-17-{idx}", attestation_mode=mode, max_age_hours=24, require_dual_signoff=True)
            attestation_sha = _sha256(attestation_path)
            truthfulness_sha = _sha256(truthfulness_path)
            public_path = _write_public_report(case_dir, name=f"public_{mode}", payload={
                "schema": "public_report/v2", "job_id": f"smoke-17-{idx}", "caller": "attestation_caller", "released": True,
                "reason_code": "threshold_passed", "k_threshold": 20,
                "dp_noise_applied": True, "dp_epsilon": 1.0,
                "governance": {
                    "source_attestation_sha256": attestation_sha,
                    "source_truthfulness_report_sha256": truthfulness_sha,
                    "source_attestation_signoff_status": "approved_dual",
                    "input_commitment_sha256": "3" * 64,
                },
            })
            audit_log = case_dir / "policy_audit.jsonl"
            audit_log.write_text(json.dumps({
                "event": "policy_release",
                "job_id": f"smoke-17-{idx}",
                "caller": "attestation_caller",
                "governance": {
                    "source_attestation_sha256": attestation_sha,
                    "source_truthfulness_report_sha256": truthfulness_sha,
                    "source_attestation_signoff_status": "approved_dual",
                    "input_commitment_sha256": "3" * 64,
                },
            }, sort_keys=True) + "\n", encoding="utf-8")
            report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                              operator_report_path=operator_path, budget_ledger_path=ledger,
                              policy_audit_log_path=audit_log,
                              source_attestation_path=attestation_path,
                              source_truthfulness_report_path=truthfulness_path)
            _validate(report)
            assert report["decision"] == "deny", report
            assert report["reason_code"] == "signed_signoff_invalid", report

        stale_dir = tmp / "stale"
        attestation_path, truthfulness_path, operator_path, _signing_key = _write_source_attestation_bundle(stale_dir, job_id="smoke-17-stale", max_age_hours=24, stale=True, truthfulness_decision="deny", require_dual_signoff=True)
        attestation_sha = _sha256(attestation_path)
        truthfulness_sha = _sha256(truthfulness_path)
        public_path = _write_public_report(stale_dir, name="public_stale", payload={
            "schema": "public_report/v2", "job_id": "smoke-17-stale", "caller": "attestation_caller", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
            "governance": {
                "source_attestation_sha256": attestation_sha,
                "source_truthfulness_report_sha256": truthfulness_sha,
                "source_attestation_signoff_status": "approved_dual",
                "input_commitment_sha256": "3" * 64,
            },
        })
        audit_log = stale_dir / "policy_audit.jsonl"
        audit_log.write_text(json.dumps({
            "event": "policy_release",
            "job_id": "smoke-17-stale",
            "caller": "attestation_caller",
            "governance": {
                "source_attestation_sha256": attestation_sha,
                "source_truthfulness_report_sha256": truthfulness_sha,
                "source_attestation_signoff_status": "approved_dual",
                "input_commitment_sha256": "3" * 64,
            },
        }, sort_keys=True) + "\n", encoding="utf-8")
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=operator_path, budget_ledger_path=ledger,
                          policy_audit_log_path=audit_log,
                          source_attestation_path=attestation_path,
                          source_truthfulness_report_path=truthfulness_path)
        _validate(report)
        assert report["decision"] == "deny", report
        assert report["reason_code"] == "source_attestation_unbound", report
    print("       OK")


def test_dual_signoff_single_approved_rejected() -> None:
    print(f"[18/{TOTAL_TESTS}] dual signoff required but attestation is single-approved -> deny ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-18", "decision": "allow", "privacy_budget": {"decision": "allow"}}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp, overrides={
            "require_privacy_budget": False,
            "require_source_attestation": True,
            "require_signed_signoff": True,
            "require_dual_signoff": True,
            "require_bound_input_commitment": False,
            "strict_source_attestation": True,
            "max_source_attestation_age_hours": 168,
        })
        attestation_path, truthfulness_path, operator_path, _signing_key = _write_source_attestation_bundle(
            tmp,
            job_id="smoke-18",
            signoff_status="approved",
            require_dual_signoff=False,
        )
        attestation_sha = _sha256(attestation_path)
        truthfulness_sha = _sha256(truthfulness_path)
        public_path = _write_public_report(tmp, name="public_dual_required_single", payload={
            "schema": "public_report/v2", "job_id": "smoke-18", "caller": "attestation_caller", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
            "governance": {
                "source_attestation_sha256": attestation_sha,
                "source_truthfulness_report_sha256": truthfulness_sha,
                "source_attestation_signoff_status": "approved",
                "input_commitment_sha256": "3" * 64,
            },
        })
        audit_log = tmp / "policy_audit.jsonl"
        audit_log.write_text(json.dumps({
            "event": "policy_release",
            "job_id": "smoke-18",
            "caller": "attestation_caller",
            "governance": {
                "source_attestation_sha256": attestation_sha,
                "source_truthfulness_report_sha256": truthfulness_sha,
                "source_attestation_signoff_status": "approved",
                "input_commitment_sha256": "3" * 64,
            },
        }, sort_keys=True) + "\n", encoding="utf-8")
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=operator_path, budget_ledger_path=ledger,
                          policy_audit_log_path=audit_log,
                          source_attestation_path=attestation_path,
                          source_truthfulness_report_path=truthfulness_path)
        _validate(report)
        assert report["decision"] == "deny", report
        assert report["reason_code"] == "source_attestation_unbound", report
    print("       OK")


def test_external_anchor_wrong_job_rejected() -> None:
    print(f"[19/{TOTAL_TESTS}] external anchor report for different job -> deny ...")
    with tempfile.TemporaryDirectory(prefix="rpg_smoke_") as tmp_str:
        tmp = Path(tmp_str)
        ledger = tmp / "ledger.jsonl"
        ledger.write_text(json.dumps({"job_id": "smoke-19", "decision": "allow",
                                       "privacy_budget": {"decision": "allow"}}) + "\n", encoding="utf-8")
        config_path = _write_config(tmp, overrides={"require_external_anchor": True})
        public_path = _write_public_report(tmp, name="public_anchor_wrong_job", payload={
            "schema": "public_report/v2", "job_id": "smoke-19", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
        })
        anchor_path = _write_external_anchor_report(tmp, job_id="different-job", uploaded=True)
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=None, budget_ledger_path=ledger,
                          external_anchor_report_path=anchor_path)
        _validate(report)
        assert report["decision"] == "deny", report
        assert report["reason_code"] == "external_anchor_unuploaded", report
    print("       OK")


def main() -> int:
    test_missing_budget_ledger()
    test_low_k_denial()
    test_missing_dp_denial()
    test_allowed_release()
    test_duplicate_query_denied()
    test_operator_fields_leaked()
    test_pjc_evidence_binding_allow()
    test_pjc_evidence_binding_result_mismatch()
    test_external_anchor_missing()
    test_external_anchor_planned_denied()
    test_external_anchor_uploaded_allow()
    test_source_attestation_missing()
    test_source_attestation_binding_allow()
    test_source_attestation_input_commitment_mismatch()
    test_source_attestation_scope_mismatch()
    test_signed_signoff_missing()
    test_strict_source_attestation_modes_and_stale()
    test_dual_signoff_single_approved_rejected()
    test_external_anchor_wrong_job_rejected()
    print("[ok] release policy gate smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
