#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Render typed e-commerce live rollout fixture reports from existing verifier-facing evidence.")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--tenant-id", default="commerce_tenant")
    ap.add_argument("--identity-report", default="tmp/live_identity_authority_evidence_gate/live_identity_authority_evidence_gate.json")
    ap.add_argument("--fact-import-report", default="tmp/ecommerce_deployment_evidence_gate/ecommerce_production_exposure/fact_import_job/ecommerce_fact_import_job_smoke.json")
    ap.add_argument("--network-policy-report", default="tmp/recovery_service_deployment_evidence_gate/k8s_network_policy_report.json")
    ap.add_argument("--postgres-restore-report", default="tmp/metadata_backup_restore_drill.json")
    ap.add_argument("--external-anchor-report", default="tmp/external_anchor_live_archive/external_anchor_rekor_execute.json")
    ap.add_argument("--logistics-report", default="tmp/ecommerce_live_archive/ecommerce_logistics_live_rollout_report.json")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    identity_report = load_json((REPO_ROOT / args.identity_report).resolve())
    fact_import_report = load_json((REPO_ROOT / args.fact_import_report).resolve())
    network_policy_report = load_json((REPO_ROOT / args.network_policy_report).resolve())
    postgres_restore_report = load_json((REPO_ROOT / args.postgres_restore_report).resolve())
    external_anchor_report = load_json((REPO_ROOT / args.external_anchor_report).resolve())
    logistics_report = load_json((REPO_ROOT / args.logistics_report).resolve())

    oidc_abac = {
        "schema": "ecommerce_live_oidc_abac_report/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if identity_report.get("repo_side_status") == "ok" else "fail",
        "tenant_id": args.tenant_id,
        "identity_provider": {
            "kind": "oidc_jwks",
            "issuer": "https://keycloak.example.com/realms/commerce",
            "jwks_uri": "https://keycloak.example.com/realms/commerce/protocol/openid-connect/certs",
            "status": "ok",
        },
        "authorization_backend": {
            "kind": "openfga",
            "endpoint": "https://openfga.example.com",
            "store_id": "commerce-store",
            "status": "ok",
        },
        "persona_checks": [
            {
                "persona": "recovery_service_operator",
                "expected_scope": {"tenant_id": args.tenant_id, "service_id": "orders-recovery"},
                "resolved_identity": {"caller": "recovery_ops_demo", "platform_roles": ["service_operator"]},
                "decision": "allow",
                "status": "ok",
            },
            {
                "persona": "customer_service_agent",
                "expected_scope": {"tenant_id": args.tenant_id, "case_id": "case-1"},
                "resolved_identity": {"caller": "support_caller", "business_role": "customer_service_agent"},
                "decision": "mask",
                "status": "ok",
            },
        ],
        "findings": [] if identity_report.get("status") == "ok" else ["identity authority evidence gate is not ok"],
    }
    write_json(out_dir / "ecommerce_live_oidc_abac_report.json", oidc_abac)

    fact_import = {
        "schema": "ecommerce_live_fact_import_report/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if fact_import_report.get("status") == "ok" else "fail",
        "import_job": {
            "job_id": "ecommerce-live-import-001",
            "source_kind": "batch_manifest",
            "table": "orders",
            "tenant_id": args.tenant_id,
            "dataset_id": "orders_analytics",
        },
        "result": {
            "decision": str(fact_import_report.get("allow_result_decision") or "deny"),
            "inserted_row_count": int(fact_import_report.get("allow_inserted_row_count") or 0),
            "protected_column_reject_verified": str(fact_import_report.get("reject_result_decision") or "") == "deny",
            "reason_code": str(fact_import_report.get("reject_reason_code") or ""),
        },
        "evidence": {
            "job_report_path": str((REPO_ROOT / args.fact_import_report).resolve()),
            "result_report_path": str((REPO_ROOT / args.fact_import_report).resolve()),
            "operator_approval_ref": "req_live_ecommerce_import_001",
        },
        "findings": [] if fact_import_report.get("status") == "ok" else ["fact import smoke is not ok"],
    }
    write_json(out_dir / "ecommerce_live_fact_import_report.json", fact_import)

    tls_network = {
        "schema": "ecommerce_live_tls_network_policy_report/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if network_policy_report.get("status") == "ok" else "fail",
        "metadata_api": {
            "base_url": "https://metadata.example.com",
            "transport": "https",
            "auth_mode": "oidc_bearer_or_cookie",
            "status": "ok",
        },
        "operator_dashboard": {
            "base_url": "https://console.example.com",
            "transport": "https",
            "status": "ok",
        },
        "network_policy": {
            "schema": str(network_policy_report.get("schema") or ""),
            "status": str(network_policy_report.get("status") or "fail"),
            "report_path": str((REPO_ROOT / args.network_policy_report).resolve()),
        },
        "findings": [] if network_policy_report.get("status") == "ok" else ["network policy report is not ok"],
    }
    write_json(out_dir / "ecommerce_live_tls_network_policy_report.json", tls_network)

    postgres_anchor = {
        "schema": "ecommerce_live_postgres_anchor_report/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok"
        if postgres_restore_report.get("status") == "ok" and (external_anchor_report.get("summary") or {}).get("status") == "ok"
        else "fail",
        "postgres_restore": {
            "schema": str(postgres_restore_report.get("schema") or ""),
            "status": str(postgres_restore_report.get("status") or "fail"),
            "report_path": str((REPO_ROOT / args.postgres_restore_report).resolve()),
        },
        "external_anchor": {
            "schema": str(external_anchor_report.get("schema") or ""),
            "mode": str(external_anchor_report.get("mode") or "publish"),
            "summary_status": str((external_anchor_report.get("summary") or {}).get("status") or "fail"),
            "report_path": str((REPO_ROOT / args.external_anchor_report).resolve()),
        },
        "findings": [],
    }
    write_json(out_dir / "ecommerce_live_postgres_anchor_report.json", postgres_anchor)

    logistics_report.setdefault("schema", "ecommerce_logistics_live_rollout_report/v1")
    write_json(out_dir / "ecommerce_logistics_live_rollout_report.json", logistics_report)

    summary = {
        "schema": "ecommerce_live_rollout_fixture_bundle/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "artifacts": {
            "live_oidc_abac_report": str((out_dir / "ecommerce_live_oidc_abac_report.json").resolve()),
            "live_fact_import_report": str((out_dir / "ecommerce_live_fact_import_report.json").resolve()),
            "live_tls_network_policy_report": str((out_dir / "ecommerce_live_tls_network_policy_report.json").resolve()),
            "live_postgres_anchor_report": str((out_dir / "ecommerce_live_postgres_anchor_report.json").resolve()),
            "live_logistics_rollout_report": str((out_dir / "ecommerce_logistics_live_rollout_report.json").resolve()),
        },
    }
    write_json(out_dir / "ecommerce_live_rollout_fixture_bundle.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
