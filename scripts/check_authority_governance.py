#!/usr/bin/env python3
"""
A5-A6: aggregate authority-source governance and smoke reports.

This is an operator-facing read adapter. It consumes existing contract reports
from policy drift, key drift, identity resolution, OpenFGA-style checks, KMS
reachability, service-token lifecycle, and issuer rotation. It does not change
the main privacy pipeline or replace the underlying authority checks.
"""
import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_SCHEMA = "authority_governance_report/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json_object(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise SystemExit(f"[ERROR] JSON object expected: {path}")
    return payload


def source_schema(payload: dict[str, Any]) -> str:
    return str(payload.get("schema") or payload.get("$id") or "")


def check(
    *,
    category: str,
    name: str,
    status: str,
    source_schema_name: str,
    source_path: str,
    detail: str,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "category": category,
        "name": name,
        "status": status,
        "source_schema": source_schema_name,
        "source_path": str(Path(source_path).resolve()),
        "detail": detail,
        "metrics": metrics or {},
    }


def policy_check(path: str) -> dict[str, Any]:
    payload = load_json_object(path)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    findings = int(summary.get("total_findings") or 0)
    status = "ok" if summary.get("status") == "clean" and findings == 0 else "error"
    return check(
        category="policy",
        name="policy_drift",
        status=status,
        source_schema_name=source_schema(payload),
        source_path=path,
        detail=f"policy drift status={summary.get('status')} findings={findings}",
        metrics={
            "registered_policy_count": summary.get("registered_policy_count"),
            "total_findings": findings,
        },
    )


def key_check(path: str) -> dict[str, Any]:
    payload = load_json_object(path)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    actionable = int(summary.get("actionable_findings") or 0)
    informational = int(summary.get("informational_findings") or 0)
    status = "error" if actionable else "warn" if informational else "ok"
    return check(
        category="key",
        name="key_backend_drift",
        status=status,
        source_schema_name=source_schema(payload),
        source_path=path,
        detail=(
            f"key drift status={summary.get('status')} "
            f"actionable={actionable} informational={informational}"
        ),
        metrics={
            "ref_key_count": summary.get("ref_key_count"),
            "db_key_count": summary.get("db_key_count"),
            "actionable_findings": actionable,
            "informational_findings": informational,
        },
    )


def identity_check(path: str) -> dict[str, Any]:
    payload = load_json_object(path)
    identity = payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
    access = payload.get("access_summary") if isinstance(payload.get("access_summary"), dict) else {}
    caller = str(identity.get("caller") or "")
    roles = identity.get("platform_roles") if isinstance(identity.get("platform_roles"), list) else []
    status = "ok" if caller and payload.get("resolution_mode") in {"bearer_token", "subject_lookup"} else "error"
    return check(
        category="identity",
        name="api_identity_resolution",
        status=status,
        source_schema_name=source_schema(payload),
        source_path=path,
        detail=f"resolved caller={caller or '<missing>'} roles={','.join(map(str, roles))}",
        metrics={
            "resolution_mode": payload.get("resolution_mode"),
            "caller": caller,
            "query_submit_allowed": access.get("query_submit_allowed"),
            "query_execute_allowed": access.get("query_execute_allowed"),
        },
    )


def authz_check(path: str) -> dict[str, Any]:
    payload = load_json_object(path)
    allowed = bool(payload.get("allowed"))
    status = "ok" if allowed else "error"
    return check(
        category="authz",
        name="openfga_check",
        status=status,
        source_schema_name=source_schema(payload),
        source_path=path,
        detail=(
            f"{payload.get('user')} {payload.get('relation')} "
            f"{payload.get('object')} allowed={allowed}"
        ),
        metrics={"allowed": allowed},
    )


def kms_check(path: str) -> dict[str, Any]:
    payload = load_json_object(path)
    overall = str(payload.get("overall_status") or "")
    status = "ok" if overall == "ok" else "warn" if overall == "degraded" else "error"
    return check(
        category="kms",
        name="kms_reachability",
        status=status,
        source_schema_name=source_schema(payload),
        source_path=path,
        detail=(
            f"kms overall_status={overall} reachable={payload.get('reachable_count')} "
            f"unreachable={payload.get('unreachable_count')}"
        ),
        metrics={
            "checked_count": payload.get("checked_count"),
            "reachable_count": payload.get("reachable_count"),
            "unreachable_count": payload.get("unreachable_count"),
        },
    )


def service_token_check(path: str) -> dict[str, Any]:
    payload = load_json_object(path)
    status_value = str(payload.get("status") or "")
    operation = str(payload.get("operation") or "")
    status = "ok" if status_value == "ok" else "warn" if status_value in {"revoked", "expired"} else "error"
    return check(
        category="service_token",
        name=f"service_token_{operation or 'unknown'}",
        status=status,
        source_schema_name=source_schema(payload),
        source_path=path,
        detail=f"service_id={payload.get('service_id')} operation={operation} status={status_value}",
        metrics={
            "operation": operation,
            "service_id": payload.get("service_id"),
            "status": status_value,
        },
    )


def issuer_check(path: str) -> dict[str, Any]:
    payload = load_json_object(path)
    ok = bool(payload.get("ok"))
    return check(
        category="issuer",
        name="issuer_credential_rotation",
        status="ok" if ok else "error",
        source_schema_name=source_schema(payload),
        source_path=path,
        detail=f"issuer={payload.get('issuer')} mode={payload.get('mode')} ok={ok}",
        metrics={
            "issuer": payload.get("issuer"),
            "issuer_type": payload.get("issuer_type"),
            "mode": payload.get("mode"),
            "key_rotation_count": payload.get("key_rotation_count"),
        },
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Aggregate authority governance and smoke reports.")
    ap.add_argument("--policy-drift", action="append", default=[])
    ap.add_argument("--key-drift", action="append", default=[])
    ap.add_argument("--identity-resolution", action="append", default=[])
    ap.add_argument("--openfga-check", action="append", default=[])
    ap.add_argument("--kms-reachability", action="append", default=[])
    ap.add_argument("--service-token-report", action="append", default=[])
    ap.add_argument("--issuer-rotation", action="append", default=[])
    ap.add_argument("--output", default="")
    ap.add_argument("--assert-ok", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    checks: list[dict[str, Any]] = []
    for path in args.policy_drift:
        checks.append(policy_check(path))
    for path in args.key_drift:
        checks.append(key_check(path))
    for path in args.identity_resolution:
        checks.append(identity_check(path))
    for path in args.openfga_check:
        checks.append(authz_check(path))
    for path in args.kms_reachability:
        checks.append(kms_check(path))
    for path in args.service_token_report:
        checks.append(service_token_check(path))
    for path in args.issuer_rotation:
        checks.append(issuer_check(path))

    categories: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "warn": 0, "error": 0})
    ok_count = warn_count = error_count = 0
    for item in checks:
        status = str(item["status"])
        categories[str(item["category"])][status] += 1
        if status == "ok":
            ok_count += 1
        elif status == "warn":
            warn_count += 1
        else:
            error_count += 1

    overall = "error" if error_count else "degraded" if warn_count else "ok"
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "overall_status": overall,
        "summary": {
            "check_count": len(checks),
            "ok_count": ok_count,
            "warn_count": warn_count,
            "error_count": error_count,
            "categories": dict(sorted(categories.items())),
        },
        "checks": checks,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.assert_ok and overall != "ok":
        print(f"[error] authority governance status is {overall}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
