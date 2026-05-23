#!/usr/bin/env python3
"""Focused smoke for the server-side release policy gate.

Covers the bypass cases the gate is meant to close:

1. Missing budget ledger → deny ``privacy_budget_missing_config``.
2. Low-k released report → deny ``min_k_violation``.
3. Released report without DP metadata → deny ``dp_required``.
4. Released report with proper DP + ledger entry → allow.
5. Released report whose ledger record records a duplicate-query deny → deny.

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
        config_path = _write_config(tmp)
        public_path = _write_public_report(tmp, name="public_ok", payload={
            "schema": "public_report/v2", "job_id": "smoke-4", "released": True,
            "reason_code": "threshold_passed", "k_threshold": 20,
            "dp_noise_applied": True, "dp_epsilon": 1.0,
        })
        report = run_gate(public_report_path=public_path, policy_config_path=config_path,
                          operator_report_path=None, budget_ledger_path=ledger)
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


def main() -> int:
    test_missing_budget_ledger()
    test_low_k_denial()
    test_missing_dp_denial()
    test_allowed_release()
    test_duplicate_query_denied()
    print("[ok] release policy gate smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
