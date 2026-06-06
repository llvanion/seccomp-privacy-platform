#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from source_attestation_lib import (
    RELEASE_GOVERNANCE_REPORT_SCHEMA,
    load_json_object,
    sha256_file,
    utc_now_iso,
    validate_schema,
    write_json,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.is_file():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _latest_policy_audit(path: Path, *, job_id: str) -> dict[str, Any] | None:
    records = [
        item
        for item in _read_jsonl(path)
        if item.get("event") == "policy_release" and str(item.get("job_id") or "") == job_id
    ]
    return records[-1] if records else None


def _record(
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
            "status": "ok" if ok else "fail",
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
    ap = argparse.ArgumentParser(description="Build a release governance report bound to source attestation and release evidence.")
    ap.add_argument("--source-attestation", required=True)
    ap.add_argument("--source-truthfulness-report", required=True)
    ap.add_argument("--public-report", required=True)
    ap.add_argument("--policy-audit-log", required=True)
    ap.add_argument("--release-policy-gate", default="")
    ap.add_argument("--operator-report", default="")
    ap.add_argument("--external-anchor-report", default="")
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--output", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    source_attestation_path = Path(args.source_attestation).resolve()
    truthfulness_report_path = Path(args.source_truthfulness_report).resolve()
    public_report_path = Path(args.public_report).resolve()
    policy_audit_log_path = Path(args.policy_audit_log).resolve()
    release_policy_gate_path = Path(args.release_policy_gate).resolve() if args.release_policy_gate else None
    operator_report_path = Path(args.operator_report).resolve() if args.operator_report else None
    external_anchor_report_path = Path(args.external_anchor_report).resolve() if args.external_anchor_report else None

    source_attestation = load_json_object(source_attestation_path)
    validate_schema(source_attestation, repo_root=REPO_ROOT, schema_filename="source_attestation.schema.json")
    truthfulness_report = load_json_object(truthfulness_report_path)
    validate_schema(truthfulness_report, repo_root=REPO_ROOT, schema_filename="source_truthfulness_report.schema.json")
    public_report = load_json_object(public_report_path)
    policy_audit = _latest_policy_audit(policy_audit_log_path, job_id=args.job_id)
    release_policy_gate = load_json_object(release_policy_gate_path) if release_policy_gate_path and release_policy_gate_path.is_file() else None
    operator_report = load_json_object(operator_report_path) if operator_report_path and operator_report_path.is_file() else None
    external_anchor_report = load_json_object(external_anchor_report_path) if external_anchor_report_path and external_anchor_report_path.is_file() else None

    source_attestation_sha256 = sha256_file(source_attestation_path)
    truthfulness_report_sha256 = sha256_file(truthfulness_report_path)
    public_report_sha256 = sha256_file(public_report_path)
    release_policy_gate_sha256 = sha256_file(release_policy_gate_path) if release_policy_gate_path and release_policy_gate_path.is_file() else None
    operator_report_sha256 = sha256_file(operator_report_path) if operator_report_path and operator_report_path.is_file() else None
    external_anchor_report_sha256 = sha256_file(external_anchor_report_path) if external_anchor_report_path and external_anchor_report_path.is_file() else None

    public_governance = public_report.get("governance") if isinstance(public_report.get("governance"), dict) else {}
    policy_governance = policy_audit.get("governance") if isinstance(policy_audit, dict) and isinstance(policy_audit.get("governance"), dict) else {}
    operator_governance = operator_report.get("governance") if isinstance(operator_report, dict) and isinstance(operator_report.get("governance"), dict) else {}

    _record(
        checks,
        findings,
        name="truthfulness_report_allow",
        ok=truthfulness_report.get("decision") == "allow",
        expected="allow",
        actual=truthfulness_report.get("decision"),
        message="source truthfulness report did not allow the bound attestation",
        finding_kind="source_truthfulness_report_denied",
    )
    _record(
        checks,
        findings,
        name="public_report_binding",
        ok=(
            public_governance.get("source_attestation_sha256") == source_attestation_sha256
            and public_governance.get("source_truthfulness_report_sha256") == truthfulness_report_sha256
            and public_governance.get("source_attestation_signoff_status") == source_attestation.get("signoff_status")
        ),
        expected={
            "source_attestation_sha256": source_attestation_sha256,
            "source_truthfulness_report_sha256": truthfulness_report_sha256,
            "source_attestation_signoff_status": source_attestation.get("signoff_status"),
        },
        actual={
            "source_attestation_sha256": public_governance.get("source_attestation_sha256"),
            "source_truthfulness_report_sha256": public_governance.get("source_truthfulness_report_sha256"),
            "source_attestation_signoff_status": public_governance.get("source_attestation_signoff_status"),
        },
        message="public report governance binding does not match source attestation/truthfulness evidence",
        finding_kind="public_report_source_attestation_unbound",
    )
    _record(
        checks,
        findings,
        name="policy_audit_binding",
        ok=(
            policy_governance.get("source_attestation_sha256") == source_attestation_sha256
            and policy_governance.get("source_truthfulness_report_sha256") == truthfulness_report_sha256
            and policy_governance.get("source_attestation_signoff_status") == source_attestation.get("signoff_status")
        ),
        expected={
            "source_attestation_sha256": source_attestation_sha256,
            "source_truthfulness_report_sha256": truthfulness_report_sha256,
            "source_attestation_signoff_status": source_attestation.get("signoff_status"),
        },
        actual={
            "source_attestation_sha256": policy_governance.get("source_attestation_sha256"),
            "source_truthfulness_report_sha256": policy_governance.get("source_truthfulness_report_sha256"),
            "source_attestation_signoff_status": policy_governance.get("source_attestation_signoff_status"),
        },
        message="policy audit governance binding does not match source attestation/truthfulness evidence",
        finding_kind="policy_audit_source_attestation_unbound",
    )
    _record(
        checks,
        findings,
        name="input_commitment_binding",
        ok=policy_governance.get("input_commitment_sha256") == source_attestation.get("input_commitment_sha256"),
        expected=source_attestation.get("input_commitment_sha256"),
        actual=policy_governance.get("input_commitment_sha256"),
        message="policy audit governance binding does not match source attestation input commitment",
        finding_kind="policy_audit_input_commitment_unbound",
    )
    if operator_report is not None:
        _record(
            checks,
            findings,
            name="operator_report_binding",
            ok=(
                operator_governance.get("source_attestation_sha256") == source_attestation_sha256
                and operator_governance.get("source_truthfulness_report_sha256") == truthfulness_report_sha256
            ),
            expected={
                "source_attestation_sha256": source_attestation_sha256,
                "source_truthfulness_report_sha256": truthfulness_report_sha256,
            },
            actual={
                "source_attestation_sha256": operator_governance.get("source_attestation_sha256"),
                "source_truthfulness_report_sha256": operator_governance.get("source_truthfulness_report_sha256"),
            },
            message="operator report governance binding does not match source attestation/truthfulness evidence",
            finding_kind="operator_report_source_attestation_unbound",
        )
    else:
        checks.append(
            {
                "name": "operator_report_binding",
                "status": "skip",
                "expected": None,
                "actual": None,
                "message": "operator report not supplied",
            }
        )
    if release_policy_gate is not None:
        _record(
            checks,
            findings,
            name="release_policy_gate_present",
            ok=release_policy_gate.get("schema") == "release_policy_gate/v1",
            expected="release_policy_gate/v1",
            actual=release_policy_gate.get("schema"),
            message="release policy gate report is missing or invalid",
            finding_kind="release_policy_gate_missing",
        )
        _record(
            checks,
            findings,
            name="release_policy_gate_binding",
            ok=(
                release_policy_gate.get("public_report_sha256") == public_report_sha256
                and release_policy_gate.get("job_id") == args.job_id
                and release_policy_gate.get("decision") == ("allow" if public_report.get("released") else "deny")
            ),
            expected={
                "public_report_sha256": public_report_sha256,
                "job_id": args.job_id,
                "decision": "allow" if public_report.get("released") else "deny",
            },
            actual={
                "public_report_sha256": release_policy_gate.get("public_report_sha256"),
                "job_id": release_policy_gate.get("job_id"),
                "decision": release_policy_gate.get("decision"),
            },
            message="release policy gate is not bound to this public report / release decision",
            finding_kind="release_policy_gate_unbound",
        )
    else:
        checks.append(
            {
                "name": "release_policy_gate_present",
                "status": "skip",
                "expected": None,
                "actual": None,
                "message": "release policy gate not supplied",
            }
        )
        checks.append(
            {
                "name": "release_policy_gate_binding",
                "status": "skip",
                "expected": None,
                "actual": None,
                "message": "release policy gate not supplied",
            }
        )

    if policy_audit is not None:
        _record(
            checks,
            findings,
            name="policy_audit_scope_binding",
            ok=(
                str(policy_audit.get("job_id") or "") == args.job_id
                and str(policy_audit.get("caller") or "") == str(public_report.get("caller") or "")
            ),
            expected={"job_id": args.job_id, "caller": public_report.get("caller")},
            actual={"job_id": policy_audit.get("job_id"), "caller": policy_audit.get("caller")},
            message="policy audit record is not bound to the released job/caller scope",
            finding_kind="policy_audit_scope_unbound",
        )
    else:
        _record(
            checks,
            findings,
            name="policy_audit_scope_binding",
            ok=False,
            expected=f"policy_release audit record for {args.job_id}",
            actual=None,
            message="policy audit record is missing for the released job",
            finding_kind="policy_audit_missing",
        )

    if external_anchor_report is not None:
        records = external_anchor_report.get("records") if isinstance(external_anchor_report.get("records"), list) else []
        matched_records = [
            item
            for item in records
            if isinstance(item, dict) and str(item.get("job_id") or "") == args.job_id
        ]
        _record(
            checks,
            findings,
            name="external_anchor_binding",
            ok=bool(matched_records),
            expected={"job_id": args.job_id, "record_present": True},
            actual={"matched_record_count": len(matched_records)},
            message="external anchor report does not include a record for the released job",
            finding_kind="external_anchor_unbound",
        )
    else:
        checks.append(
            {
                "name": "external_anchor_binding",
                "status": "skip",
                "expected": None,
                "actual": None,
                "message": "external anchor report not supplied",
            }
        )

    status = "ok" if all(item["status"] in {"ok", "skip"} for item in checks) else "fail"
    report = {
        "schema": RELEASE_GOVERNANCE_REPORT_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": status,
        "job_id": args.job_id,
        "release_decision": release_policy_gate.get("decision") if isinstance(release_policy_gate, dict) else public_report.get("released"),
        "source_attestation_path": str(source_attestation_path),
        "source_attestation_sha256": source_attestation_sha256,
        "source_truthfulness_report_path": str(truthfulness_report_path),
        "source_truthfulness_report_sha256": truthfulness_report_sha256,
        "public_report_path": str(public_report_path),
        "public_report_sha256": public_report_sha256,
        "operator_report_path": str(operator_report_path) if operator_report_path else None,
        "operator_report_sha256": operator_report_sha256,
        "policy_audit_log_path": str(policy_audit_log_path),
        "release_policy_gate_path": str(release_policy_gate_path) if release_policy_gate_path else None,
        "release_policy_gate_sha256": release_policy_gate_sha256,
        "external_anchor_report_path": str(external_anchor_report_path) if external_anchor_report_path else None,
        "external_anchor_report_sha256": external_anchor_report_sha256,
        "summary": {
            "source_attestation_mode": source_attestation.get("attestation_mode"),
            "source_attestation_signoff_status": source_attestation.get("signoff_status"),
            "approval_id": source_attestation.get("approval_id"),
            "operator_identity": source_attestation.get("operator_identity"),
            "reviewer_identity": source_attestation.get("reviewer_identity"),
            "truthfulness_decision": truthfulness_report.get("decision"),
            "release_gate_decision": release_policy_gate.get("decision") if isinstance(release_policy_gate, dict) else None,
            "external_anchor_schema": external_anchor_report.get("schema") if isinstance(external_anchor_report, dict) else None,
        },
        "checks": checks,
        "findings": findings,
    }
    write_json(Path(args.output).resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
