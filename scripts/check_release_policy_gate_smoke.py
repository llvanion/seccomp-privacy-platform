#!/usr/bin/env python3
"""Focused smoke for the server-side release policy gate.

Covers the bypass cases the gate is meant to close:

1. Missing budget ledger → deny ``privacy_budget_missing_config``.
2. Low-k released report → deny ``min_k_violation``.
3. Released report without DP metadata → deny ``dp_required``.
4. Released report with proper DP + ledger entry + redaction → allow.
5. Released report whose ledger record records a duplicate-query deny → deny.
6. Released report that leaks operator-only fields → deny.
7. Released report with required PJC evidence bound to policy audit → allow.
8. Mismatched PJC evidence result hash → deny.

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
from validate_json_contract import load_json, validate_value  # noqa: E402


SCHEMA = load_json(str(REPO_ROOT / "schemas" / "release_policy_gate.schema.json"))


def _validate(report: dict) -> None:
    validate_value(report, SCHEMA)


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
        "allowed_deny_reason_codes": [
            "below_k", "privacy_budget_exhausted",
            "privacy_budget_duplicate_query", "privacy_budget_near_duplicate",
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


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def test_missing_budget_ledger() -> None:
    print("[1/5] missing budget ledger → deny ...")
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
    print("[2/5] low-k released report → deny ...")
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
    print("[3/5] released report without DP metadata → deny ...")
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
    print("[4/5] proper release → allow ...")
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
    print("[5/5] duplicate-query budget decision leaked → deny ...")
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
    print("[6/6] released report leaking operator-only fields → deny ...")
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
    print("[7/8] required PJC evidence binding → allow ...")
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
    print("[8/8] PJC evidence result replacement → deny ...")
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


def main() -> int:
    test_missing_budget_ledger()
    test_low_k_denial()
    test_missing_dp_denial()
    test_allowed_release()
    test_duplicate_query_denied()
    test_operator_fields_leaked()
    test_pjc_evidence_binding_allow()
    test_pjc_evidence_binding_result_mismatch()
    print("[ok] release policy gate smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
