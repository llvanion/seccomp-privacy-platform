#!/usr/bin/env python3
"""Build a typed live e-commerce OIDC/ABAC report from verifier-facing evidence."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "ecommerce_live_oidc_abac_report/v1"
OIDC_CLAIM_MAP_SCHEMA = "oidc_claim_map/v1"
OPENFGA_CHECK_SCHEMA = "openfga_check_result/v1"
BUSINESS_ACCESS_SMOKE_SCHEMA = "business_access_api_smoke/v1"
BUSINESS_ACCESS_CHECK_SCHEMA = "business_access_check_report/v1"
BUSINESS_PREVIEW_SCHEMA = "business_data_read_preview/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path_value: str) -> dict[str, Any]:
    path = Path(path_value).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def write_json(path_value: str, payload: dict[str, Any]) -> None:
    path = Path(path_value).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_schema(payload: dict[str, Any], *, expected: str, label: str) -> None:
    actual = str(payload.get("schema") or "")
    if actual != expected:
        raise ValueError(f"{label} must use {expected}; got {actual!r}")


def load_optional_json(path_value: str) -> dict[str, Any] | None:
    if not path_value:
        return None
    return load_json(path_value)


def normalize_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def build_identity_provider(claim_map: dict[str, Any], findings: list[str]) -> dict[str, Any]:
    issuer = str(claim_map.get("issuer") or "")
    jwks_uri = str(claim_map.get("jwks_uri") or "")
    status = "ok"
    if claim_map.get("valid") is not True:
        status = "fail"
        findings.append("live oidc claim map is not valid")
    if claim_map.get("signature_verified") is not True:
        status = "fail"
        findings.append("live oidc token signature was not verified against JWKS")
    if not issuer:
        status = "fail"
        findings.append("live oidc claim map is missing issuer")
    if not jwks_uri:
        status = "fail"
        findings.append("live oidc claim map is missing jwks_uri")
    if claim_map.get("issuer_registered") is not True:
        findings.append("live oidc issuer is signature-verified but not registered in issuer_registry")
    if claim_map.get("audience_ok") is not True:
        findings.append("live oidc token audience did not pass an explicit trusted-audience check")
    return {
        "kind": "oidc_jwks",
        "issuer": issuer,
        "jwks_uri": jwks_uri,
        "status": status,
    }


def build_authorization_backend(openfga_check: dict[str, Any], findings: list[str]) -> dict[str, Any]:
    backend_kind = str(openfga_check.get("backend_kind") or "")
    endpoint = openfga_check.get("openfga_endpoint")
    store_id = openfga_check.get("openfga_store_id")
    status = "ok"
    if backend_kind != "openfga_http":
        status = "fail"
        findings.append("authorization backend evidence is not a live openfga_http check")
    if openfga_check.get("allowed") is not True:
        status = "fail"
        findings.append("live openfga check did not return allowed=true")
    if not endpoint:
        status = "fail"
        findings.append("live openfga check is missing endpoint metadata")
    if not store_id:
        status = "fail"
        findings.append("live openfga check is missing store_id metadata")
    return {
        "kind": "openfga",
        "endpoint": str(endpoint) if endpoint is not None else None,
        "store_id": str(store_id) if store_id is not None else None,
        "status": status,
    }


def build_allow_persona_check(
    *,
    tenant_id: str,
    persona: str,
    claim_map: dict[str, Any],
    openfga_check: dict[str, Any],
    findings: list[str],
) -> dict[str, Any]:
    mapped = normalize_object(claim_map.get("mapped_fields"))
    expected_scope: dict[str, Any] = {
        "tenant_id": tenant_id,
        "relation": str(openfga_check.get("relation") or ""),
        "object": str(openfga_check.get("object") or ""),
    }
    service_id = str(mapped.get("service_id") or "")
    if service_id:
        expected_scope["service_id"] = service_id

    raw_claims = normalize_object(claim_map.get("raw_claims"))
    if not raw_claims.get("tenant_id"):
        findings.append("live service-account token does not carry tenant_id; report tenant_id is sourced from e-commerce evidence scope")

    allowed = openfga_check.get("allowed") is True
    status = "ok" if claim_map.get("valid") is True and allowed and str(openfga_check.get("backend_kind") or "") == "openfga_http" else "fail"
    return {
        "persona": persona,
        "expected_scope": expected_scope,
        "resolved_identity": {
            "issuer": str(claim_map.get("issuer") or ""),
            "subject": str(claim_map.get("subject") or ""),
            "caller": mapped.get("caller"),
            "subject_type": mapped.get("subject_type"),
            "service_id": mapped.get("service_id"),
            "display_name": mapped.get("display_name"),
            "platform_roles": mapped.get("platform_roles"),
            "openfga_user": openfga_check.get("user"),
        },
        "decision": "allow" if allowed else "deny",
        "status": status,
    }


def build_support_persona_check(
    *,
    tenant_id: str,
    persona: str,
    api_smoke: dict[str, Any],
    support_binding: dict[str, Any] | None,
    support_preview: dict[str, Any] | None,
    findings: list[str],
) -> dict[str, Any]:
    preview = support_preview or {}
    binding = support_binding or {}
    binding_scope = normalize_object(normalize_object(binding.get("request")).get("scope"))
    preview_scope = normalize_object(preview.get("scope"))
    expected_scope = dict(binding_scope or preview_scope or {"tenant_id": tenant_id})

    preview_binding = normalize_object(preview.get("relationship_binding"))
    report_binding = normalize_object(binding.get("relationship_binding"))
    effective_binding = report_binding or preview_binding

    support_mask_ok = api_smoke.get("support_masked_preview_decision") == "mask"
    support_binding_ok = api_smoke.get("support_relationship_binding_status") == "ok"
    support_spoof_ok = api_smoke.get("support_relationship_spoof_status") == 403
    preview_ok = preview.get("decision") == "mask" if preview else True
    effective_binding_ok = str(effective_binding.get("status") or "") == "ok"

    status = "ok" if all((support_mask_ok, support_binding_ok, support_spoof_ok, preview_ok, effective_binding_ok)) else "fail"
    if not preview:
        findings.append("support masked preview detail was not provided; report falls back to business_access_api_smoke summary for the mask decision")
    if not binding:
        findings.append("support relation binding report was not provided")
    findings.append("support masked persona evidence is sourced from business-access runtime evidence, not from a live Keycloak user token")

    return {
        "persona": persona,
        "expected_scope": expected_scope,
        "resolved_identity": {
            "business_role": "customer_service_agent",
            "policy_id": preview.get("policy_id") or binding.get("policy_id"),
            "policy_version": preview.get("policy_version") or binding.get("policy_version"),
            "relationship_binding": effective_binding,
            "auth_source": "business_access_runtime_evidence",
        },
        "decision": "mask",
        "status": status,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tenant-id", default="commerce_tenant")
    ap.add_argument("--allow-persona", default="recovery_service_operator")
    ap.add_argument("--support-persona", default="customer_service_agent")
    ap.add_argument("--oidc-claim-map", required=True)
    ap.add_argument("--openfga-check", required=True)
    ap.add_argument("--business-access-api-smoke", required=True)
    ap.add_argument("--support-relation-binding-report", default="")
    ap.add_argument("--support-masked-preview", default="")
    ap.add_argument("--output", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()

    claim_map = load_json(args.oidc_claim_map)
    require_schema(claim_map, expected=OIDC_CLAIM_MAP_SCHEMA, label="--oidc-claim-map")

    openfga_check = load_json(args.openfga_check)
    require_schema(openfga_check, expected=OPENFGA_CHECK_SCHEMA, label="--openfga-check")

    api_smoke = load_json(args.business_access_api_smoke)
    require_schema(api_smoke, expected=BUSINESS_ACCESS_SMOKE_SCHEMA, label="--business-access-api-smoke")

    support_binding = load_optional_json(args.support_relation_binding_report)
    if support_binding is not None:
        require_schema(support_binding, expected=BUSINESS_ACCESS_CHECK_SCHEMA, label="--support-relation-binding-report")

    support_preview = load_optional_json(args.support_masked_preview)
    if support_preview is not None:
        require_schema(support_preview, expected=BUSINESS_PREVIEW_SCHEMA, label="--support-masked-preview")

    findings: list[str] = []
    identity_provider = build_identity_provider(claim_map, findings)
    authorization_backend = build_authorization_backend(openfga_check, findings)
    persona_checks = [
        build_allow_persona_check(
            tenant_id=args.tenant_id,
            persona=args.allow_persona,
            claim_map=claim_map,
            openfga_check=openfga_check,
            findings=findings,
        ),
        build_support_persona_check(
            tenant_id=args.tenant_id,
            persona=args.support_persona,
            api_smoke=api_smoke,
            support_binding=support_binding,
            support_preview=support_preview,
            findings=findings,
        ),
    ]

    status = "ok" if identity_provider["status"] == "ok" and authorization_backend["status"] == "ok" and all(item["status"] == "ok" for item in persona_checks) else "fail"
    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": status,
        "tenant_id": args.tenant_id,
        "identity_provider": identity_provider,
        "authorization_backend": authorization_backend,
        "persona_checks": persona_checks,
        "findings": findings,
    }
    write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
