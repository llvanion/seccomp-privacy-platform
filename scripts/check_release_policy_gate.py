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

from validate_json_contract import load_json, validate_value  # noqa: E402

SCHEMA = "release_policy_gate/v1"


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


def run_gate(
    *,
    public_report_path: Path,
    policy_config_path: Path,
    operator_report_path: Path | None,
    budget_ledger_path: Path | None,
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

    decision = "allow"
    chosen_reason_code = "ok"
    chosen_reason: str | None = None
    for chk in checks:
        if chk["status"] == "deny":
            decision = "deny"
            chosen_reason = chk.get("message")
            # Map the first failing check name to a reason code
            chosen_reason_code = {
                "dp_enforced": findings[0]["kind"] if findings else "dp_required",
                "min_k": "min_k_violation",
                "privacy_budget_ledger": findings[0]["kind"] if findings else "privacy_budget_required",
                "deny_reason_code": "deny_reason_not_allowed",
                "duplicate_query": "duplicate_query_leaked",
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
    parser.add_argument("--output", required=True)
    parser.add_argument("--assert-allow", action="store_true")
    args = parser.parse_args(argv)

    public_report = Path(args.public_report).resolve()
    config_path = Path(args.policy_config).resolve()
    operator_report = Path(args.operator_report).resolve() if args.operator_report else None
    budget_ledger = Path(args.privacy_budget_ledger).resolve() if args.privacy_budget_ledger else None
    out_path = Path(args.output).resolve()

    report = run_gate(
        public_report_path=public_report,
        policy_config_path=config_path,
        operator_report_path=operator_report,
        budget_ledger_path=budget_ledger,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if args.assert_allow and report["decision"] != "allow":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
