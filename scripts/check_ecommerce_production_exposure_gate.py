#!/usr/bin/env python3
"""Production exposure gate for the e-commerce data/persona surface.

This gate intentionally aggregates existing repo-side evidence instead of
creating a new privileged read path. It checks that the supported commerce
facts, business personas, API field guard, operator request approval flow, and
console contact surface remain aligned.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ecommerce_production_exposure_gate/v1"
REQUIRED_FACT_TABLES = {
    "orders",
    "order_items",
    "order_attribution",
    "order_payment",
    "order_fulfillment",
    "customer_service_interactions",
}
REQUIRED_BUSINESS_ROLES = {
    "buyer",
    "merchant_staff",
    "customer_service_agent",
    "courier",
    "station_operator",
    "last_mile_courier",
    "field_marketer",
    "fraud_analyst",
    "compliance_auditor",
}
REQUIRED_PROTECTED_FIELDS = {
    "orders.buyer_email",
    "order_fulfillment.delivery_address",
    "support_case.raw_transcript",
}
FORBIDDEN_ANALYST_ENDPOINTS = {
    "/v1/jobs/start",
    "/v1/jobs/{job_id}/relaunch",
    "/v1/pjc-mtls/preflight",
    "/v1/pjc/run-manifest/sign",
    "/v1/pjc/evidence/verify-merge",
}
ANALYST_ROLES = {"campaign_analyst", "fraud_analyst"}
PRIVILEGED_MUTATION_ROLES = {"privacy_operator", "platform_admin"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def run_json(cmd: list[str], *, output_path: Path | None = None) -> dict[str, Any]:
    res = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"command failed ({res.returncode}): {' '.join(cmd)}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
        )
    if output_path is not None and output_path.is_file():
        return load_json(output_path)
    return json.loads(res.stdout)


def latest_tmp_report(filename: str) -> Path | None:
    matches = list((REPO_ROOT / "tmp").rglob(filename))
    if not matches:
        return None
    return max(matches, key=lambda path: (path.stat().st_mtime, str(path)))


def copy_tree_contents(src_dir: Path, dst_dir: Path) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(src_dir.rglob("*")):
        rel = src.relative_to(src_dir)
        dst = dst_dir / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.resolve() == dst.resolve():
                continue
            shutil.copy2(src, dst)


def copy_matching_siblings(src_file: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    stem = src_file.stem
    suffix = src_file.suffix
    for sibling in sorted(src_file.parent.glob(f"{stem}*{suffix}")):
        dst = dst_dir / sibling.name
        if sibling.resolve() == dst.resolve():
            continue
        shutil.copy2(sibling, dst)
    return dst_dir / src_file.name


def is_loopback_socket_permission_error(exc: BaseException) -> bool:
    text = str(exc)
    return "PermissionError" in text and ("socket" in text or "Operation not permitted" in text)


def skip_check(name: str, message: str, *, expected: Any, actual: Any, missing_prerequisites: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "status": "skipped",
        "message": message,
        "expected": expected,
        "actual": actual,
        "missing_prerequisites": missing_prerequisites,
    }


def artifact(path: Path, *, schema: str | None = None, note: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"path": str(path)}
    if schema:
        item["schema"] = schema
    if note:
        item["note"] = note
    return item


def api_report_meets_current_contract(api_report: dict[str, Any]) -> bool:
    return (
        api_report.get("status") == "ok"
        and api_report.get("business_identity_spoof_status") == 403
        and api_report.get("business_identity_cross_tenant_status") == 403
        and api_report.get("merchant_read_preview_denied_status") == 403
        and api_report.get("merchant_relationship_spoof_status") == 403
        and api_report.get("support_masked_preview_decision") == "mask"
        and api_report.get("support_relationship_binding_status") == "ok"
        and api_report.get("support_relationship_spoof_status") == 403
        and api_report.get("sensitive_filter_status") == 400
        and api_report.get("role_spoof_status") == 403
        and api_report.get("buyer_self_preview_decision") == "allow"
        and api_report.get("buyer_relationship_spoof_status") == 403
        and api_report.get("courier_leg_preview_decision") == "allow"
        and api_report.get("courier_final_address_denied_status") == 403
        and api_report.get("courier_relationship_spoof_status") == 403
        and api_report.get("station_leg_preview_decision") == "allow"
        and api_report.get("station_final_address_denied_status") == 403
        and api_report.get("last_mile_preview_decision") == "mask"
        and api_report.get("fraud_payment_preview_decision") == "allow"
        and api_report.get("fraud_relationship_spoof_status") == 403
        and api_report.get("fraud_contact_decision") == "deny"
        and api_report.get("field_marketer_attribution_preview_decision") == "allow"
        and api_report.get("field_marketer_relationship_spoof_status") == 403
        and api_report.get("field_marketer_contact_decision") == "deny"
    )


def check_console_manifest(manifest: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sections = manifest.get("sections") if isinstance(manifest.get("sections"), list) else []
    exposed_bad: list[dict[str, Any]] = []
    request_section_ok = False
    pjc_section_ok = False
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_name = str(section.get("section") or "")
        roles = {str(item) for item in section.get("roles_allowed") or []}
        endpoints = section.get("endpoints") if isinstance(section.get("endpoints"), list) else []
        if section_name == "requests":
            paths = {str(item.get("path") or "") for item in endpoints if isinstance(item, dict)}
            request_section_ok = {"/v1/request/submit", "/v1/request/{submission_id}/approve"}.issubset(paths)
        if section_name == "pjc_two_party":
            pjc_section_ok = "privacy_operator" in roles and not bool(roles & ANALYST_ROLES)
        for endpoint in endpoints:
            if not isinstance(endpoint, dict):
                continue
            path = str(endpoint.get("path") or "")
            endpoint_role = str(endpoint.get("role") or "")
            if (
                path in FORBIDDEN_ANALYST_ENDPOINTS
                and roles & ANALYST_ROLES
                and endpoint_role not in PRIVILEGED_MUTATION_ROLES
            ):
                exposed_bad.append({
                    "section": section_name,
                    "path": path,
                    "endpoint_role": endpoint_role,
                    "section_roles_allowed": sorted(roles & ANALYST_ROLES),
                })
    summary = {
        "section_count": len(sections),
        "request_section_has_submit_and_approve": request_section_ok,
        "pjc_section_privileged_only": pjc_section_ok,
        "business_access_section_has_check_and_preview": any(
            isinstance(section, dict)
            and str(section.get("section") or "") == "business_access"
            and {str(item.get("path") or "") for item in (section.get("endpoints") or []) if isinstance(item, dict)} >= {
                "/v1/business-access/check",
                "/v1/business-data/read-preview",
            }
            for section in sections
        ),
        "analyst_forbidden_endpoint_exposures": exposed_bad,
    }
    findings = []
    if not request_section_ok:
        findings.append({
            "kind": "console_request_workflow_missing",
            "message": "console manifest must expose both request submission and approval endpoints",
            "expected": ["/v1/request/submit", "/v1/request/{submission_id}/approve"],
            "actual": manifest,
        })
    if not pjc_section_ok:
        findings.append({
            "kind": "console_pjc_roles_too_broad",
            "message": "PJC evidence section must remain restricted to privileged operator/auditor roles",
            "expected": "privacy_operator without campaign_analyst/fraud_analyst",
            "actual": summary,
        })
    if not summary["business_access_section_has_check_and_preview"]:
        findings.append({
            "kind": "console_business_access_workbench_missing",
            "message": "console manifest must expose business-access/check and business-data/read-preview through a business-access section",
            "expected": ["/v1/business-access/check", "/v1/business-data/read-preview"],
            "actual": summary,
        })
    if exposed_bad:
        findings.append({
            "kind": "console_analyst_mutation_exposure",
            "message": "analyst roles must not receive direct job/PJC mutation endpoints",
            "expected": "no analyst role on mutation/PJC endpoints",
            "actual": exposed_bad,
        })
    return summary, findings


def build_exposure_matrix(
    *,
    out_dir: Path,
    api_report: dict[str, Any],
    query_scope_report: dict[str, Any],
    request_report: dict[str, Any],
    request_list: dict[str, Any],
    request_detail: dict[str, Any],
    request_spoof_caller_reject: dict[str, Any],
    request_spoof_tenant_reject: dict[str, Any],
    request_spoof_dataset_reject: dict[str, Any],
    request_recovery_without_permission_reject: dict[str, Any],
    request_recovery_allowed_submit: dict[str, Any],
    request_recovery_service_spoof_reject: dict[str, Any],
    request_analyst_list: dict[str, Any],
    request_analyst_detail_reject: dict[str, Any],
    request_analyst_approve_reject: dict[str, Any],
    request_analyst_reject_reject: dict[str, Any],
    request_self_reject: dict[str, Any],
    request_approve: dict[str, Any],
    request_auditor_list: dict[str, Any],
    request_auditor_detail: dict[str, Any],
    request_auditor_approve_reject: dict[str, Any],
    request_reject: dict[str, Any],
    request_auditor_reject: dict[str, Any],
    console_summary: dict[str, Any],
    policy_roles: set[str],
    protected_fields: set[str],
    support_relation_binding_artifact: Path | None,
) -> dict[str, Any]:
    business_access_dir = out_dir / "business_access_api"
    request_output = out_dir / "operator_request_submission.json"
    return {
        "attacker_view": [
            {
                "surface": "metadata_api_business_identity_directory",
                "actor": "tenant-scoped business caller",
                "risk": "enumerates another caller's business-identity rows or crosses tenant boundary through the identity directory",
                "expected_control": "business-identities metadata is caller-scoped for non-privileged identities and rejects caller/tenant spoofing",
                "status": "ok"
                if (
                    api_report.get("business_identity_spoof_status") == 403
                    and api_report.get("business_identity_cross_tenant_status") == 403
                )
                else "fail",
                "evidence": [
                    artifact(out_dir / "business_access_api" / "business_access_api_smoke.json", schema="business_access_api_smoke/v1", note="business identity spoof and cross-tenant denial summary"),
                ],
            },
            {
                "surface": "query_workflow_api",
                "actor": "identity-bound direct query caller",
                "risk": "bypasses request workflow and drifts caller/dataset/tenant/recovery-service scope through the direct query API",
                "expected_control": "direct query/workflow API keeps the same caller/dataset/tenant/recovery-service bindings and execute privilege split",
                "status": "ok"
                if (
                    query_scope_report.get("caller_spoof_status") == 403
                    and query_scope_report.get("dataset_spoof_status") == 403
                    and query_scope_report.get("tenant_spoof_status") == 403
                    and query_scope_report.get("recovery_allowed_service_id") == "orders-recovery"
                    and query_scope_report.get("recovery_spoof_status") == 403
                    and query_scope_report.get("execute_forbidden_status") == 403
                    and query_scope_report.get("status_cross_caller_forbidden_status") == 403
                )
                else "fail",
                "evidence": [
                    artifact(out_dir / "query_workflow_identity_scope" / "query_workflow_identity_scope_smoke.json", schema="query_workflow_identity_scope_smoke/v1"),
                ],
            },
            {
                "surface": "metadata_api_business_read_preview",
                "actor": "merchant_staff attacker",
                "risk": "reads buyer contact or delivery address outside allowed scope",
                "expected_control": "deny or scope-conflict refusal before sensitive row data is returned",
                "status": "ok"
                if (
                    api_report.get("merchant_read_preview_denied_status") == 403
                    and api_report.get("merchant_filter_conflict_status") == 403
                    and api_report.get("merchant_tenant_filter_conflict_status") == 403
                    and api_report.get("merchant_relationship_spoof_status") == 403
                )
                else "fail",
                "evidence": [
                    artifact(business_access_dir / "merchant_contact_deny_check.json", schema="business_access_check_report/v1"),
                    artifact(business_access_dir / "merchant_address_deny_check.json", schema="business_access_check_report/v1"),
                    artifact(business_access_dir / "business_read_preview_allow.json", schema="business_data_read_preview/v1", note="authorized positive control"),
                ],
            },
            {
                "surface": "metadata_api_business_read_preview",
                "actor": "customer_service_agent attacker",
                "risk": "uses support-case access to pivot into another case or expose raw buyer contact instead of masked contact hints",
                "expected_control": "assigned support case stays bound to the authenticated support identity, buyer contact remains masked, and case spoofing is rejected",
                "status": "ok"
                if (
                    api_report.get("support_masked_preview_decision") == "mask"
                    and api_report.get("support_relationship_binding_status") == "ok"
                    and api_report.get("support_relationship_spoof_status") == 403
                )
                else "fail",
                "evidence": [
                    artifact(business_access_dir / "support_masked_check.json", schema="business_data_read_preview/v1"),
                    artifact(support_relation_binding_artifact, schema="business_access_check_report/v1", note="support relation binding baseline")
                    if support_relation_binding_artifact is not None
                    else artifact(business_access_dir / "business_access_api_smoke.json", schema="business_access_api_smoke/v1", note="support binding fallback summary"),
                ],
            },
            {
                "surface": "metadata_api_business_read_preview",
                "actor": "field_marketer attacker",
                "risk": "uses campaign role to pivot into buyer contact or non-attribution fields",
                "expected_control": "campaign attribution stays allowed; buyer contact remains denied",
                "status": "ok"
                if (
                    api_report.get("field_marketer_attribution_preview_decision") == "allow"
                    and api_report.get("field_marketer_relationship_spoof_status") == 403
                    and api_report.get("field_marketer_contact_decision") == "deny"
                )
                else "fail",
                "evidence": [
                    artifact(business_access_dir / "field_marketer_attribution_preview.json", schema="business_data_read_preview/v1"),
                    artifact(business_access_dir / "field_marketer_contact_deny_check.json", schema="business_access_check_report/v1"),
                ],
            },
            {
                "surface": "metadata_api_business_read_preview",
                "actor": "courier on upstream leg",
                "risk": "a courier or station operator learns final-recipient address details for a leg they have not reached yet",
                "expected_control": "assigned delivery leg exposes only next-stop / handoff fields, while final address stays denied until the correct terminal leg",
                "status": "ok"
                if (
                    api_report.get("courier_leg_preview_decision") == "allow"
                    and api_report.get("courier_final_address_denied_status") == 403
                    and api_report.get("courier_relationship_spoof_status") == 403
                    and api_report.get("station_leg_preview_decision") == "allow"
                    and api_report.get("station_final_address_denied_status") == 403
                )
                else "fail",
                "evidence": [
                    artifact(business_access_dir / "courier_leg_preview.json", schema="business_data_read_preview/v1"),
                    artifact(business_access_dir / "station_leg_preview.json", schema="business_data_read_preview/v1"),
                ],
            },
            {
                "surface": "metadata_api_business_read_preview",
                "actor": "last-mile courier",
                "risk": "last-mile delivery cannot complete because final dropoff fields are unavailable, or recipient contact is over-exposed instead of masked",
                "expected_control": "the terminal assigned last-mile leg may read the exact dropoff address, while recipient phone stays masked by default",
                "status": "ok"
                if api_report.get("last_mile_preview_decision") == "mask"
                else "fail",
                "evidence": [
                    artifact(business_access_dir / "last_mile_leg_preview.json", schema="business_data_read_preview/v1"),
                ],
            },
            {
                "surface": "metadata_api_business_read_preview",
                "actor": "fraud_analyst attacker",
                "risk": "uses fraud queue access to pull buyer contact instead of payment-risk signals",
                "expected_control": "payment-risk preview allowed; buyer contact denied",
                "status": "ok"
                if (
                    api_report.get("fraud_payment_preview_decision") == "allow"
                    and api_report.get("fraud_relationship_spoof_status") == 403
                    and api_report.get("fraud_contact_decision") == "deny"
                )
                else "fail",
                "evidence": [
                    artifact(business_access_dir / "fraud_payment_preview.json", schema="business_data_read_preview/v1"),
                    artifact(business_access_dir / "fraud_contact_deny_check.json", schema="business_access_check_report/v1"),
                ],
            },
        ],
        "internal_adversary_view": [
            {
                "surface": "request_workflow",
                "actor": "submitter spoofing caller/tenant/dataset",
                "risk": "authenticated submitter impersonates another caller or submits outside its authorized tenant/dataset scope",
                "expected_control": "submit path binds identity and rejects caller, tenant_id, or dataset_id drift with authz_rejected",
                "status": "ok"
                if (
                    request_spoof_caller_reject.get("status") == 403
                    and (request_spoof_caller_reject.get("response") or {}).get("error") == "authz_rejected"
                    and request_spoof_tenant_reject.get("status") == 403
                    and (request_spoof_tenant_reject.get("response") or {}).get("error") == "authz_rejected"
                    and request_spoof_dataset_reject.get("status") == 403
                    and (request_spoof_dataset_reject.get("response") or {}).get("error") == "authz_rejected"
                )
                else "fail",
                "evidence": [
                    artifact(request_output.with_name(f"{request_output.stem}_spoof_caller_reject{request_output.suffix}"), note="HTTP status envelope with denial"),
                    artifact(request_output.with_name(f"{request_output.stem}_spoof_tenant_reject{request_output.suffix}"), note="HTTP status envelope with denial"),
                    artifact(request_output.with_name(f"{request_output.stem}_spoof_dataset_reject{request_output.suffix}"), note="HTTP status envelope with denial"),
                ],
            },
            {
                "surface": "request_workflow",
                "actor": "submitter spoofing recovery service scope",
                "risk": "submitter enables record recovery without permission or binds a recovery service outside allowed_service_ids",
                "expected_control": "recovery use requires can_use_record_recovery_service and record_recovery_service_id stays within allowed service scope",
                "status": "ok"
                if (
                    request_recovery_without_permission_reject.get("status") == 403
                    and (request_recovery_without_permission_reject.get("response") or {}).get("error") == "authz_rejected"
                    and request_recovery_allowed_submit.get("service_id") == "bridge-demo-recovery"
                    and request_recovery_service_spoof_reject.get("status") == 403
                    and (request_recovery_service_spoof_reject.get("response") or {}).get("error") == "authz_rejected"
                )
                else "fail",
                "evidence": [
                    artifact(request_output.with_name(f"{request_output.stem}_recovery_without_permission_reject{request_output.suffix}"), note="HTTP status envelope with denial"),
                    artifact(request_output.with_name(f"{request_output.stem}_recovery_allowed_submit{request_output.suffix}"), schema="operator_request_submission/v1"),
                    artifact(request_output.with_name(f"{request_output.stem}_recovery_service_spoof_reject{request_output.suffix}"), note="HTTP status envelope with denial"),
                ],
            },
            {
                "surface": "request_workflow",
                "actor": "same_identity submitter/approver",
                "risk": "self-approves a request and launches work without separation of duties",
                "expected_control": "HTTP 403 same_identity_self_approval before approval state transition",
                "status": "ok"
                if (
                    request_self_reject.get("status") == 403
                    and (request_self_reject.get("response") or {}).get("error") == "same_identity_self_approval"
                    and request_approve.get("status") == "approved"
                    and request_reject.get("status") == "rejected"
                )
                else "fail",
                "evidence": [
                    artifact(request_output.with_name(f"{request_output.stem}_self_approve_reject{request_output.suffix}"), note="HTTP status envelope with denial"),
                    artifact(request_output.with_name(f"{request_output.stem}_approve{request_output.suffix}"), schema="operator_request_submission/v1"),
                    artifact(request_output.with_name(f"{request_output.stem}_reject{request_output.suffix}"), schema="operator_request_submission/v1"),
                ],
            },
            {
                "surface": "request_workflow",
                "actor": "non-review analyst",
                "risk": "campaign/fraud-style analyst reads or mutates another caller's pending request directly",
                "expected_control": "list result is empty and detail/approve/reject return authz_rejected",
                "status": "ok"
                if (
                    request_analyst_list.get("returned_count") == 0
                    and request_analyst_detail_reject.get("status") == 403
                    and (request_analyst_detail_reject.get("response") or {}).get("error") == "authz_rejected"
                    and request_analyst_approve_reject.get("status") == 403
                    and (request_analyst_approve_reject.get("response") or {}).get("error") == "authz_rejected"
                    and request_analyst_reject_reject.get("status") == 403
                    and (request_analyst_reject_reject.get("response") or {}).get("error") == "authz_rejected"
                )
                else "fail",
                "evidence": [
                    artifact(request_output.with_name(f"{request_output.stem}_analyst_list{request_output.suffix}")),
                    artifact(request_output.with_name(f"{request_output.stem}_analyst_detail_reject{request_output.suffix}"), note="HTTP status envelope with denial"),
                    artifact(request_output.with_name(f"{request_output.stem}_analyst_approve_reject{request_output.suffix}"), note="HTTP status envelope with denial"),
                    artifact(request_output.with_name(f"{request_output.stem}_analyst_reject_reject{request_output.suffix}"), note="HTTP status envelope with denial"),
                ],
            },
            {
                "surface": "request_workflow",
                "actor": "compliance auditor",
                "risk": "audit reviewer silently escalates into request approval rather than read/reject-only workflow control",
                "expected_control": "auditor can list/detail/reject but approve returns authz_rejected",
                "status": "ok"
                if (
                    request_auditor_list.get("returned_count", 0) >= 1
                    and request_auditor_detail.get("submission_id")
                    and request_auditor_approve_reject.get("status") == 403
                    and (request_auditor_approve_reject.get("response") or {}).get("error") == "authz_rejected"
                    and request_auditor_reject.get("status") == "rejected"
                    and request_auditor_reject.get("rejected_by") == "compliance_auditor_demo"
                )
                else "fail",
                "evidence": [
                    artifact(request_output.with_name(f"{request_output.stem}_auditor_list{request_output.suffix}"), schema="operator_request_submission_list/v1"),
                    artifact(request_output.with_name(f"{request_output.stem}_auditor_detail{request_output.suffix}"), schema="operator_request_submission/v1"),
                    artifact(request_output.with_name(f"{request_output.stem}_auditor_approve_reject{request_output.suffix}"), note="HTTP status envelope with denial"),
                    artifact(request_output.with_name(f"{request_output.stem}_auditor_reject{request_output.suffix}"), schema="operator_request_submission/v1"),
                ],
            },
            {
                "surface": "operator_console_manifest",
                "actor": "campaign/fraud analyst with console access",
                "risk": "directly reaches job start or PJC mutation endpoints instead of going through request workflow",
                "expected_control": "analysts may submit requests but do not receive direct job/PJC mutation endpoints",
                "status": "ok"
                if not console_summary.get("analyst_forbidden_endpoint_exposures")
                else "fail",
                "evidence": [
                    artifact(REPO_ROOT / "config" / "operator_console" / "console_manifest.json", schema="console_manifest/v1"),
                ],
            },
        ],
        "verifier_view": {
            "claim": "Repo-side evidence covers data surface, field policy, runtime API behavior, approval workflow, and console contact surface without claiming live production deployment.",
            "frozen_roles": sorted(policy_roles),
            "protected_fields": sorted(protected_fields),
            "artifacts": [
                artifact(out_dir / "ecommerce_fact_layer_report.json", schema="ecommerce_fact_layer_report/v1"),
                artifact(out_dir / "business_access_policy_smoke.json", schema="business_access_policy_smoke/v1"),
                artifact(business_access_dir / "business_access_api_smoke.json", schema="business_access_api_smoke/v1"),
                artifact(out_dir / "query_workflow_identity_scope" / "query_workflow_identity_scope_smoke.json", schema="query_workflow_identity_scope_smoke/v1"),
                artifact(business_access_dir / "business_read_preview_allow.json", schema="business_data_read_preview/v1"),
                artifact(business_access_dir / "business_read_preview_masked.json", schema="business_data_read_preview/v1"),
                artifact(business_access_dir / "support_masked_check.json", schema="business_data_read_preview/v1"),
                *(
                    [artifact(support_relation_binding_artifact, schema="business_access_check_report/v1", note="direct repo-side support relation binding evidence")]
                    if support_relation_binding_artifact is not None
                    else []
                ),
                artifact(request_output, schema="operator_request_submission/v1"),
                artifact(request_output.with_name(f"{request_output.stem}_list{request_output.suffix}"), schema="operator_request_submission_list/v1"),
                artifact(request_output.with_name(f"{request_output.stem}_detail{request_output.suffix}"), schema="operator_request_submission/v1"),
                artifact(request_output.with_name(f"{request_output.stem}_spoof_caller_reject{request_output.suffix}"), note="caller spoof submit denied"),
                artifact(request_output.with_name(f"{request_output.stem}_spoof_tenant_reject{request_output.suffix}"), note="tenant spoof submit denied"),
                artifact(request_output.with_name(f"{request_output.stem}_spoof_dataset_reject{request_output.suffix}"), note="dataset spoof submit denied"),
                artifact(request_output.with_name(f"{request_output.stem}_recovery_without_permission_reject{request_output.suffix}"), note="recovery submit denied without permission"),
                artifact(request_output.with_name(f"{request_output.stem}_recovery_allowed_submit{request_output.suffix}"), schema="operator_request_submission/v1"),
                artifact(request_output.with_name(f"{request_output.stem}_recovery_service_spoof_reject{request_output.suffix}"), note="recovery service spoof denied"),
                artifact(request_output.with_name(f"{request_output.stem}_approve{request_output.suffix}"), schema="operator_request_submission/v1"),
                artifact(request_output.with_name(f"{request_output.stem}_reject{request_output.suffix}"), schema="operator_request_submission/v1"),
                artifact(request_output.with_name(f"{request_output.stem}_analyst_approve_reject{request_output.suffix}"), note="non-review analyst cannot approve"),
                artifact(request_output.with_name(f"{request_output.stem}_auditor_approve_reject{request_output.suffix}"), note="auditor cannot approve"),
                artifact(request_output.with_name(f"{request_output.stem}_auditor_reject{request_output.suffix}"), schema="operator_request_submission/v1"),
                artifact(REPO_ROOT / "config" / "operator_console" / "console_manifest.json", schema="console_manifest/v1"),
            ],
            "repo_side_boundary": [
                "Loopback API and local token fixtures prove fail-closed behavior only; they are not deployment evidence.",
                "This gate does not prove live OIDC/JWKS, external ABAC/OpenFGA, production TLS/mTLS, NetworkPolicy, Postgres HA, or immutable external audit anchoring.",
            ],
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Aggregate e-commerce production exposure repo-side evidence.")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    support_relation_binding_artifact: Path | None = None

    fact_report = run_json([
        sys.executable,
        str(REPO_ROOT / "scripts" / "render_ecommerce_fact_layer.py"),
        "--output", str(out_dir / "ecommerce_fact_layer_report.json"),
    ], output_path=out_dir / "ecommerce_fact_layer_report.json")
    present_tables = set(fact_report.get("summary", {}).get("tables_present") or [])
    fact_ok = fact_report.get("summary", {}).get("status") == "ok" and REQUIRED_FACT_TABLES <= present_tables
    checks.append({
        "name": "fact_layer_schema",
        "status": "ok" if fact_ok else "fail",
        "message": None if fact_ok else "e-commerce fact-layer baseline is incomplete",
        "expected": sorted(REQUIRED_FACT_TABLES),
        "actual": sorted(present_tables),
    })
    if not fact_ok:
        findings.append({
            "kind": "fact_layer_incomplete",
            "message": "e-commerce fact-layer baseline is incomplete",
            "expected": sorted(REQUIRED_FACT_TABLES),
            "actual": sorted(present_tables),
        })

    policy_smoke = run_json([
        sys.executable,
        str(REPO_ROOT / "scripts" / "check_business_access_policy_smoke.py"),
        "--output", str(out_dir / "business_access_policy_smoke.json"),
    ], output_path=out_dir / "business_access_policy_smoke.json")
    policy = load_json(REPO_ROOT / "config" / "business_access_policy.ecommerce.example.json")
    roles = set(policy.get("roles") or {})
    protected_fields = set(policy.get("protected_fields") or {})
    policy_ok = REQUIRED_BUSINESS_ROLES <= roles and REQUIRED_PROTECTED_FIELDS <= protected_fields
    checks.append({
        "name": "business_access_policy",
        "status": "ok" if policy_ok else "fail",
        "message": None if policy_ok else "business access policy is missing required e-commerce roles or protected fields",
        "expected": {"roles": sorted(REQUIRED_BUSINESS_ROLES), "protected_fields": sorted(REQUIRED_PROTECTED_FIELDS)},
        "actual": {"roles": sorted(roles), "protected_fields": sorted(protected_fields)},
    })
    if not policy_ok:
        findings.append({
            "kind": "business_policy_incomplete",
            "message": "business access policy is missing required e-commerce roles or protected fields",
            "expected": {"roles": sorted(REQUIRED_BUSINESS_ROLES), "protected_fields": sorted(REQUIRED_PROTECTED_FIELDS)},
            "actual": {"roles": sorted(roles), "protected_fields": sorted(protected_fields)},
        })

    business_access_dir = out_dir / "business_access_api"
    api_report: dict[str, Any] = {}
    business_access_runtime_available = True
    try:
        latest_api_report = latest_tmp_report("business_access_api_smoke.json")
        if latest_api_report is not None:
            copy_tree_contents(latest_api_report.parent, business_access_dir)
            api_report = load_json(business_access_dir / "business_access_api_smoke.json")
            if not api_report_meets_current_contract(api_report):
                api_report = run_json([
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "check_business_access_api_smoke.py"),
                    "--out-dir", str(business_access_dir),
                ])
        else:
            api_report = run_json([
                sys.executable,
                str(REPO_ROOT / "scripts" / "check_business_access_api_smoke.py"),
                "--out-dir", str(business_access_dir),
            ])
        api_ok = api_report_meets_current_contract(api_report)
        checks.append({
            "name": "business_access_api",
            "status": "ok" if api_ok else "fail",
            "message": None if api_ok else "business access API smoke did not prove allow/deny/mask/spoof coverage",
            "expected": "allow/deny/mask/sensitive-filter/spoof/fraud checks",
            "actual": api_report,
        })
        if not api_ok:
            findings.append({
                "kind": "business_access_api_incomplete",
                "message": "business access API smoke did not prove allow/deny/mask/spoof coverage",
                "expected": "allow/deny/mask/sensitive-filter/spoof/fraud checks",
                "actual": api_report,
            })
    except RuntimeError as exc:
        if not is_loopback_socket_permission_error(exc):
            raise
        business_access_runtime_available = False
        checks.append(
            skip_check(
                "business_access_api",
                "business access API smoke requires loopback listener sockets in the current runtime",
                expected="allow/deny/mask/sensitive-filter/spoof/fraud checks",
                actual={"error": str(exc)},
                missing_prerequisites=["environment permits loopback listener sockets for business-access API smoke"],
            )
        )

    try:
        support_relation_binding_artifact = out_dir / "support_relation_binding_report.json"
        run_json([
            sys.executable,
            str(REPO_ROOT / "scripts" / "check_business_access_support_relation_binding.py"),
            "--output",
            str(support_relation_binding_artifact),
        ], output_path=support_relation_binding_artifact)
    except Exception:
        support_relation_binding_artifact = None

    query_scope_dir = out_dir / "query_workflow_identity_scope"
    query_scope_report: dict[str, Any] = {}
    query_scope_runtime_available = True
    try:
        latest_query_scope = latest_tmp_report("query_workflow_identity_scope_smoke.json")
        if latest_query_scope is not None:
            copy_tree_contents(latest_query_scope.parent, query_scope_dir)
            query_scope_report = load_json(query_scope_dir / "query_workflow_identity_scope_smoke.json")
        else:
            query_scope_report = run_json([
                sys.executable,
                str(REPO_ROOT / "scripts" / "check_query_workflow_identity_scope_smoke.py"),
                "--out-dir", str(query_scope_dir),
            ], output_path=query_scope_dir / "query_workflow_identity_scope_smoke.json")
        query_scope_ok = (
            query_scope_report.get("status") == "ok"
            and query_scope_report.get("dry_run_identity_caller") == "marketing_analyst_demo"
            and query_scope_report.get("caller_spoof_status") == 403
            and query_scope_report.get("dataset_spoof_status") == 403
            and query_scope_report.get("tenant_spoof_status") == 403
            and query_scope_report.get("recovery_allowed_service_id") == "orders-recovery"
            and query_scope_report.get("recovery_spoof_status") == 403
            and query_scope_report.get("execute_forbidden_status") == 403
            and query_scope_report.get("execute_allowed_identity_caller") == "commerce_ops_demo"
            and query_scope_report.get("status_caller") == "marketing_analyst_demo"
            and query_scope_report.get("status_cross_caller_forbidden_status") == 403
        )
        checks.append({
            "name": "direct_query_workflow_identity_scope",
            "status": "ok" if query_scope_ok else "fail",
            "message": None if query_scope_ok else "direct query/workflow API smoke did not prove identity-bound scope enforcement",
            "expected": "caller/dataset/tenant/recovery-service binding plus execute privilege split",
            "actual": query_scope_report,
        })
        if not query_scope_ok:
            findings.append({
                "kind": "direct_query_workflow_scope_incomplete",
                "message": "direct query/workflow API smoke did not prove identity-bound scope enforcement",
                "expected": "caller/dataset/tenant/recovery-service binding plus execute privilege split",
                "actual": query_scope_report,
            })
    except RuntimeError as exc:
        if not is_loopback_socket_permission_error(exc):
            raise
        query_scope_runtime_available = False
        checks.append(
            skip_check(
                "direct_query_workflow_identity_scope",
                "direct query/workflow identity scope smoke requires loopback listener sockets in the current runtime",
                expected="caller/dataset/tenant/recovery-service binding plus execute privilege split",
                actual={"error": str(exc)},
                missing_prerequisites=["environment permits loopback listener sockets for query-workflow identity scope smoke"],
            )
        )

    request_output = out_dir / "operator_request_submission.json"
    request_report: dict[str, Any] = {}
    request_list: dict[str, Any] = {}
    request_detail: dict[str, Any] = {}
    request_spoof_caller_reject: dict[str, Any] = {}
    request_spoof_tenant_reject: dict[str, Any] = {}
    request_spoof_dataset_reject: dict[str, Any] = {}
    request_recovery_without_permission_reject: dict[str, Any] = {}
    request_recovery_allowed_submit: dict[str, Any] = {}
    request_recovery_service_spoof_reject: dict[str, Any] = {}
    request_analyst_list: dict[str, Any] = {}
    request_analyst_detail_reject: dict[str, Any] = {}
    request_analyst_approve_reject: dict[str, Any] = {}
    request_analyst_reject_reject: dict[str, Any] = {}
    request_self_reject: dict[str, Any] = {}
    request_approve: dict[str, Any] = {}
    request_auditor_list: dict[str, Any] = {}
    request_auditor_detail: dict[str, Any] = {}
    request_auditor_approve_reject: dict[str, Any] = {}
    request_reject: dict[str, Any] = {}
    request_auditor_reject: dict[str, Any] = {}
    request_runtime_available = True
    try:
        latest_request_report = latest_tmp_report("operator_request_submission.json")
        if latest_request_report is not None:
            request_output = copy_matching_siblings(latest_request_report, out_dir)
            request_report = load_json(request_output)
        else:
            request_report = run_json([
                sys.executable,
                str(REPO_ROOT / "scripts" / "check_operator_request_submission_smoke.py"),
                "--output", str(request_output),
            ], output_path=request_output)
        request_list = load_json(request_output.with_name(f"{request_output.stem}_list{request_output.suffix}"))
        request_detail = load_json(request_output.with_name(f"{request_output.stem}_detail{request_output.suffix}"))
        request_spoof_caller_reject = load_json(request_output.with_name(f"{request_output.stem}_spoof_caller_reject{request_output.suffix}"))
        request_spoof_tenant_reject = load_json(request_output.with_name(f"{request_output.stem}_spoof_tenant_reject{request_output.suffix}"))
        request_spoof_dataset_reject = load_json(request_output.with_name(f"{request_output.stem}_spoof_dataset_reject{request_output.suffix}"))
        request_recovery_without_permission_reject = load_json(request_output.with_name(f"{request_output.stem}_recovery_without_permission_reject{request_output.suffix}"))
        request_recovery_allowed_submit = load_json(request_output.with_name(f"{request_output.stem}_recovery_allowed_submit{request_output.suffix}"))
        request_recovery_service_spoof_reject = load_json(request_output.with_name(f"{request_output.stem}_recovery_service_spoof_reject{request_output.suffix}"))
        request_analyst_list = load_json(request_output.with_name(f"{request_output.stem}_analyst_list{request_output.suffix}"))
        request_analyst_detail_reject = load_json(request_output.with_name(f"{request_output.stem}_analyst_detail_reject{request_output.suffix}"))
        request_analyst_approve_reject = load_json(request_output.with_name(f"{request_output.stem}_analyst_approve_reject{request_output.suffix}"))
        request_analyst_reject_reject = load_json(request_output.with_name(f"{request_output.stem}_analyst_reject_reject{request_output.suffix}"))
        request_self_reject = load_json(request_output.with_name(f"{request_output.stem}_self_approve_reject{request_output.suffix}"))
        request_approve = load_json(request_output.with_name(f"{request_output.stem}_approve{request_output.suffix}"))
        request_auditor_list = load_json(request_output.with_name(f"{request_output.stem}_auditor_list{request_output.suffix}"))
        request_auditor_detail = load_json(request_output.with_name(f"{request_output.stem}_auditor_detail{request_output.suffix}"))
        request_auditor_approve_reject = load_json(request_output.with_name(f"{request_output.stem}_auditor_approve_reject{request_output.suffix}"))
        request_reject = load_json(request_output.with_name(f"{request_output.stem}_reject{request_output.suffix}"))
        request_auditor_reject = load_json(request_output.with_name(f"{request_output.stem}_auditor_reject{request_output.suffix}"))
        request_ok = (
            request_report.get("schema") == "operator_request_submission/v1"
            and request_list.get("schema") == "operator_request_submission_list/v1"
            and request_list.get("returned_count", 0) >= 1
            and isinstance(request_detail.get("request"), dict)
            and request_spoof_caller_reject.get("status") == 403
            and (request_spoof_caller_reject.get("response") or {}).get("error") == "authz_rejected"
            and request_spoof_tenant_reject.get("status") == 403
            and (request_spoof_tenant_reject.get("response") or {}).get("error") == "authz_rejected"
            and request_spoof_dataset_reject.get("status") == 403
            and (request_spoof_dataset_reject.get("response") or {}).get("error") == "authz_rejected"
            and request_recovery_without_permission_reject.get("status") == 403
            and (request_recovery_without_permission_reject.get("response") or {}).get("error") == "authz_rejected"
            and request_recovery_allowed_submit.get("service_id") == "bridge-demo-recovery"
            and request_recovery_service_spoof_reject.get("status") == 403
            and (request_recovery_service_spoof_reject.get("response") or {}).get("error") == "authz_rejected"
            and request_analyst_list.get("returned_count") == 0
            and request_analyst_detail_reject.get("status") == 403
            and (request_analyst_detail_reject.get("response") or {}).get("error") == "authz_rejected"
            and request_analyst_approve_reject.get("status") == 403
            and (request_analyst_approve_reject.get("response") or {}).get("error") == "authz_rejected"
            and request_analyst_reject_reject.get("status") == 403
            and (request_analyst_reject_reject.get("response") or {}).get("error") == "authz_rejected"
            and request_self_reject.get("status") == 403
            and (request_self_reject.get("response") or {}).get("error") == "same_identity_self_approval"
            and request_approve.get("status") == "approved"
            and request_approve.get("approved_by") == "privacy_operator_demo"
            and isinstance(request_approve.get("job_control"), dict)
            and request_approve["job_control"].get("state") == "running"
            and request_auditor_list.get("schema") == "operator_request_submission_list/v1"
            and request_auditor_list.get("returned_count", 0) >= 1
            and request_auditor_detail.get("schema") == "operator_request_submission/v1"
            and request_auditor_approve_reject.get("status") == 403
            and (request_auditor_approve_reject.get("response") or {}).get("error") == "authz_rejected"
            and request_reject.get("status") == "rejected"
            and request_reject.get("rejection_reason") == "smoke rejection"
            and request_auditor_reject.get("status") == "rejected"
            and request_auditor_reject.get("rejected_by") == "compliance_auditor_demo"
        )
        request_actual = {
            "submission": request_report,
            "list": request_list,
            "detail": request_detail,
            "spoof_caller_reject": request_spoof_caller_reject,
            "spoof_tenant_reject": request_spoof_tenant_reject,
            "spoof_dataset_reject": request_spoof_dataset_reject,
            "recovery_without_permission_reject": request_recovery_without_permission_reject,
            "recovery_allowed_submit": request_recovery_allowed_submit,
            "recovery_service_spoof_reject": request_recovery_service_spoof_reject,
            "analyst_list": request_analyst_list,
            "analyst_detail_reject": request_analyst_detail_reject,
            "analyst_approve_reject": request_analyst_approve_reject,
            "analyst_reject_reject": request_analyst_reject_reject,
            "self_approve_reject": request_self_reject,
            "approve": request_approve,
            "auditor_list": request_auditor_list,
            "auditor_detail": request_auditor_detail,
            "auditor_approve_reject": request_auditor_approve_reject,
            "reject": request_reject,
            "auditor_reject": request_auditor_reject,
        }
        checks.append({
            "name": "operator_request_workflow",
            "status": "ok" if request_ok else "fail",
            "message": None if request_ok else "operator request workflow did not prove submit/approve/reject/self-approval denial",
            "expected": "request submission smoke with approval evidence",
            "actual": request_actual,
        })
        if not request_ok:
            findings.append({
                "kind": "request_workflow_incomplete",
                "message": "operator request workflow did not prove submit/approve/reject/self-approval denial",
                "expected": "request submission smoke with approval evidence",
                "actual": request_actual,
            })
    except RuntimeError as exc:
        if not is_loopback_socket_permission_error(exc):
            raise
        request_runtime_available = False
        checks.append(
            skip_check(
                "operator_request_workflow",
                "operator request workflow smoke requires loopback listener sockets in the current runtime",
                expected="request submission smoke with approval evidence",
                actual={"error": str(exc)},
                missing_prerequisites=["environment permits loopback listener sockets for operator request workflow smoke"],
            )
        )

    console_manifest = load_json(REPO_ROOT / "config" / "operator_console" / "console_manifest.json")
    console_summary, console_findings = check_console_manifest(console_manifest)
    console_ok = not console_findings
    checks.append({
        "name": "console_manifest",
        "status": "ok" if console_ok else "fail",
        "message": None if console_ok else "console manifest exposes unsupported e-commerce production contact surface",
        "expected": "analysts submit requests but do not directly start jobs or PJC roles",
        "actual": console_summary,
    })
    findings.extend(console_findings)

    business_access_workbench_report = run_json([sys.executable, str(REPO_ROOT / "scripts" / "check_console_business_access_workbench.py")])
    workbench_ok = business_access_workbench_report.get("status") == "ok"
    checks.append({
        "name": "console_business_access_workbench",
        "status": "ok" if workbench_ok else "fail",
        "message": None if workbench_ok else "console business access workbench route/client wiring is incomplete",
        "expected": "console route + metadata sidecar client for business-access/check and business-data/read-preview",
        "actual": business_access_workbench_report,
    })
    if not workbench_ok:
        findings.append({
            "kind": "console_business_access_workbench_incomplete",
            "message": "console business access workbench route/client wiring is incomplete",
            "expected": "console route + metadata sidecar client for business-access/check and business-data/read-preview",
            "actual": business_access_workbench_report,
        })

    fact_import_job_dir = out_dir / "fact_import_job"
    fact_import_job_dir.mkdir(parents=True, exist_ok=True)
    fact_import_job_report = run_json(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_ecommerce_fact_import_job_smoke.py"), "--out-dir", str(fact_import_job_dir)],
        output_path=fact_import_job_dir / "ecommerce_fact_import_job_smoke.json",
    )
    fact_import_job_ok = fact_import_job_report.get("status") == "ok"
    checks.append({
        "name": "ecommerce_fact_import_job",
        "status": "ok" if fact_import_job_ok else "fail",
        "message": None if fact_import_job_ok else "validator-first e-commerce ETL import job wrapper did not prove allow/reject fail-closed behavior",
        "expected": "manifest-driven import wrapper commits allowed rows and rejects protected-column batches without side effects",
        "actual": fact_import_job_report,
    })
    if not fact_import_job_ok:
        findings.append({
            "kind": "ecommerce_fact_import_job_incomplete",
            "message": "validator-first e-commerce ETL import job wrapper did not prove allow/reject fail-closed behavior",
            "expected": "manifest-driven import wrapper commits allowed rows and rejects protected-column batches without side effects",
            "actual": fact_import_job_report,
        })

    status = "ok" if all(item["status"] in {"ok", "skipped"} for item in checks) else "fail"
    if business_access_runtime_available and query_scope_runtime_available and request_runtime_available:
        exposure_matrix = build_exposure_matrix(
            out_dir=out_dir,
            api_report=api_report,
            query_scope_report=query_scope_report,
            request_report=request_report,
            request_list=request_list,
            request_detail=request_detail,
            request_spoof_caller_reject=request_spoof_caller_reject,
            request_spoof_tenant_reject=request_spoof_tenant_reject,
            request_spoof_dataset_reject=request_spoof_dataset_reject,
            request_recovery_without_permission_reject=request_recovery_without_permission_reject,
            request_recovery_allowed_submit=request_recovery_allowed_submit,
            request_recovery_service_spoof_reject=request_recovery_service_spoof_reject,
            request_analyst_list=request_analyst_list,
            request_analyst_detail_reject=request_analyst_detail_reject,
            request_analyst_approve_reject=request_analyst_approve_reject,
            request_analyst_reject_reject=request_analyst_reject_reject,
            request_self_reject=request_self_reject,
            request_approve=request_approve,
            request_auditor_list=request_auditor_list,
            request_auditor_detail=request_auditor_detail,
            request_auditor_approve_reject=request_auditor_approve_reject,
            request_reject=request_reject,
            request_auditor_reject=request_auditor_reject,
            console_summary=console_summary,
            policy_roles=roles,
            protected_fields=protected_fields,
            support_relation_binding_artifact=support_relation_binding_artifact,
        )
    else:
        exposure_matrix = {
            "attacker_view": [],
            "internal_adversary_view": [],
            "verifier_view": {
                "claim": "Repo-side facts, policies, and console surface remain frozen, but loopback runtime smokes were skipped in the current sandbox.",
                "frozen_roles": sorted(roles),
                "protected_fields": sorted(protected_fields),
                "artifacts": [
                    artifact(out_dir / "ecommerce_fact_layer_report.json", schema="ecommerce_fact_layer_report/v1"),
                    artifact(out_dir / "business_access_policy_smoke.json", schema="business_access_policy_smoke/v1"),
                    artifact(REPO_ROOT / "config" / "operator_console" / "console_manifest.json", schema="console_manifest/v1"),
                    artifact(out_dir / "console_business_access_workbench_check.json", schema="console_business_access_workbench_check/v1"),
                    artifact(out_dir / "fact_import_job" / "ecommerce_fact_import_job_smoke.json", schema="ecommerce_fact_import_job_smoke/v1"),
                    *(
                        [artifact(support_relation_binding_artifact, schema="business_access_check_report/v1", note="direct repo-side support relation binding evidence")]
                        if support_relation_binding_artifact is not None
                        else []
                    ),
                ],
                "repo_side_boundary": [
                    "Loopback API and local token fixtures prove fail-closed behavior only; they are not deployment evidence.",
                    "Current sandbox restrictions prevented the business-access API, query-workflow, or operator request runtime smokes from running to completion.",
                ],
            },
        }
    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": status,
        "repo_side_evidence": {
            "fact_layer_schema": {
                "path": str(out_dir / "ecommerce_fact_layer_report.json"),
                "table_count": fact_report.get("summary", {}).get("table_count"),
                "total_index_count": fact_report.get("summary", {}).get("total_index_count"),
            },
            "business_access_policy": {
                "path": str(REPO_ROOT / "config" / "business_access_policy.ecommerce.example.json"),
                "roles": sorted(roles),
                "policy_smoke_path": str(out_dir / "business_access_policy_smoke.json"),
                "policy_smoke_case_count": policy_smoke.get("case_count"),
            },
            "business_access_api": {
                "path": str(out_dir / "business_access_api" / "business_access_api_smoke.json"),
                "summary": api_report,
                "artifacts": [
                    artifact(out_dir / "business_access_api" / "business_read_preview_allow.json", schema="business_data_read_preview/v1"),
                    artifact(out_dir / "business_access_api" / "business_read_preview_masked.json", schema="business_data_read_preview/v1"),
                    artifact(out_dir / "business_access_api" / "merchant_contact_deny_check.json", schema="business_access_check_report/v1"),
                    artifact(out_dir / "business_access_api" / "fraud_payment_preview.json", schema="business_data_read_preview/v1"),
                    artifact(out_dir / "business_access_api" / "fraud_contact_deny_check.json", schema="business_access_check_report/v1"),
                    artifact(out_dir / "business_access_api" / "field_marketer_attribution_preview.json", schema="business_data_read_preview/v1"),
                    artifact(out_dir / "business_access_api" / "field_marketer_contact_deny_check.json", schema="business_access_check_report/v1"),
                ],
            },
            "direct_query_workflow_identity_scope": {
                "path": str(out_dir / "query_workflow_identity_scope" / "query_workflow_identity_scope_smoke.json"),
                "summary": query_scope_report,
            },
            "operator_request_workflow": {
                "submission_path": str(request_output),
                "list_path": str(request_output.with_name(f"{request_output.stem}_list{request_output.suffix}")),
                "detail_path": str(request_output.with_name(f"{request_output.stem}_detail{request_output.suffix}")),
                "spoof_caller_reject_path": str(request_output.with_name(f"{request_output.stem}_spoof_caller_reject{request_output.suffix}")),
                "spoof_tenant_reject_path": str(request_output.with_name(f"{request_output.stem}_spoof_tenant_reject{request_output.suffix}")),
                "spoof_dataset_reject_path": str(request_output.with_name(f"{request_output.stem}_spoof_dataset_reject{request_output.suffix}")),
                "recovery_without_permission_reject_path": str(request_output.with_name(f"{request_output.stem}_recovery_without_permission_reject{request_output.suffix}")),
                "recovery_allowed_submit_path": str(request_output.with_name(f"{request_output.stem}_recovery_allowed_submit{request_output.suffix}")),
                "recovery_service_spoof_reject_path": str(request_output.with_name(f"{request_output.stem}_recovery_service_spoof_reject{request_output.suffix}")),
                "analyst_list_path": str(request_output.with_name(f"{request_output.stem}_analyst_list{request_output.suffix}")),
                "analyst_detail_reject_path": str(request_output.with_name(f"{request_output.stem}_analyst_detail_reject{request_output.suffix}")),
                "analyst_approve_reject_path": str(request_output.with_name(f"{request_output.stem}_analyst_approve_reject{request_output.suffix}")),
                "analyst_reject_reject_path": str(request_output.with_name(f"{request_output.stem}_analyst_reject_reject{request_output.suffix}")),
                "self_approve_reject_path": str(request_output.with_name(f"{request_output.stem}_self_approve_reject{request_output.suffix}")),
                "approve_path": str(request_output.with_name(f"{request_output.stem}_approve{request_output.suffix}")),
                "auditor_list_path": str(request_output.with_name(f"{request_output.stem}_auditor_list{request_output.suffix}")),
                "auditor_detail_path": str(request_output.with_name(f"{request_output.stem}_auditor_detail{request_output.suffix}")),
                "auditor_approve_reject_path": str(request_output.with_name(f"{request_output.stem}_auditor_approve_reject{request_output.suffix}")),
                "reject_path": str(request_output.with_name(f"{request_output.stem}_reject{request_output.suffix}")),
                "auditor_reject_path": str(request_output.with_name(f"{request_output.stem}_auditor_reject{request_output.suffix}")),
            },
            "console_manifest": {
                "path": str(REPO_ROOT / "config" / "operator_console" / "console_manifest.json"),
                "summary": console_summary,
            },
            "console_business_access_workbench": {
                "path": str(REPO_ROOT / "console" / "src" / "routes" / "business-access.tsx"),
                "summary": business_access_workbench_report,
            },
            "ecommerce_fact_import_job": {
                "path": str(REPO_ROOT / "scripts" / "run_ecommerce_fact_import_job.py"),
                "summary": fact_import_job_report,
            },
        },
        "exposure_matrix": exposure_matrix,
        "real_production_remaining": [
            "Replace local token-map identity fixtures with real OIDC/JWKS resolution and mapped business_identity rows for buyer, merchant, support, courier, field marketing, fraud, operator, and auditor personas.",
            "Load real or approved synthetic e-commerce fact rows through the importer and archive the validation/import reports; this repo-side gate only proves schema and policy behavior.",
            "Run the metadata API, operator dashboard, and query workflow behind production TLS/mTLS and network policy; local loopback smokes are not deployment evidence.",
            "Bind request approvals to real separation-of-duties identities and retention/audit storage; local smoke proves self-approval denial only.",
            "Exercise live Postgres/backup/restore/failover and external immutable audit anchoring for these e-commerce workflows.",
            "Run the console business-access workbench and validator-first ETL wrapper against live OIDC/ABAC and production ETL/event-stream runtimes; current evidence is still repo-side.",
        ],
        "checks": checks,
        "findings": findings,
    }
    out_path = out_dir / "ecommerce_production_exposure_gate.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
