#!/usr/bin/env python3
"""Build final top-level live status summaries from existing module gate reports."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_SCHEMA = "production_security_closure_gate/v1"
BLOCKERS_SCHEMA = "final_live_blockers_report/v1"

MODULES = [
    ("public_two_host", "public_two_host_production_readiness_gate", "public_two_host_production_readiness_gate.json", "public_two_host_production_readiness_gate/v1"),
    ("spiffe_envoy", "spiffe_envoy_identity_gate", "spiffe_envoy_identity_gate.json", "spiffe_envoy_identity_gate/v1"),
    ("external_anchor", "external_anchor_evidence_gate", "external_anchor_evidence_gate.json", "external_anchor_evidence_gate/v1"),
    ("postgres_ha", "postgres_ha_evidence_gate", "postgres_ha_evidence_gate.json", "postgres_ha_evidence_gate/v1"),
    ("supply_chain", "supply_chain_evidence_gate", "supply_chain_evidence_gate.json", "supply_chain_evidence_gate/v1"),
    ("authority", "authority_evidence_gate", "authority_evidence_gate.json", "authority_evidence_gate/v1"),
    ("observability", "observability_evidence_gate", "observability_evidence_gate.json", "observability_evidence_gate/v1"),
    ("recovery_service", "recovery_service_deployment_evidence_gate", "recovery_service_deployment_evidence_gate.json", "recovery_service_deployment_evidence_gate/v1"),
    ("privacy_budget", "privacy_budget_deployment_evidence_gate", "privacy_budget_deployment_evidence_gate.json", "privacy_budget_deployment_evidence_gate/v1"),
    ("legacy_sse", "legacy_sse_query_surface_evidence_gate", "legacy_sse_query_surface_evidence_gate.json", "legacy_sse_query_surface_evidence_gate/v1"),
    ("pjc_resource_isolation", "pjc_resource_isolation_evidence_gate", "pjc_resource_isolation_evidence_gate.json", "pjc_resource_isolation_evidence_gate/v1"),
    ("query_workflow", "query_workflow_deployment_evidence_gate", "query_workflow_deployment_evidence_gate.json", "query_workflow_deployment_evidence_gate/v1"),
    ("ecommerce", "ecommerce_deployment_evidence_gate", "ecommerce_deployment_evidence_gate.json", "ecommerce_deployment_evidence_gate/v1"),
    ("console", "console_deployment_evidence_gate", "console_deployment_evidence_gate.json", "console_deployment_evidence_gate/v1"),
    ("control_plane", "control_plane_deployment_evidence_gate", "control_plane_deployment_evidence_gate.json", "control_plane_deployment_evidence_gate/v1"),
    ("pjc_protocol", "pjc_protocol_security_evidence_gate", "pjc_protocol_security_evidence_gate.json", "pjc_protocol_security_evidence_gate/v1"),
]


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
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reports-root", required=True)
    ap.add_argument("--closure-output", required=True)
    ap.add_argument("--blockers-output", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    reports_root = Path(args.reports_root).resolve()

    modules: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    remaining_modules: list[str] = []
    remaining_details: dict[str, Any] = {}

    for name, subdir, filename, schema in MODULES:
        path = reports_root / subdir / filename
        if not path.is_file():
            remaining_modules.append(name)
            modules.append(
                {
                    "name": name,
                    "schema": schema,
                    "path": str(path),
                    "status": "fail",
                    "repo_side_status": "fail",
                    "live_status": "fail",
                    "live_foundation_status": "skipped",
                }
            )
            continue

        payload = load_json(path)
        module = {
            "name": name,
            "schema": schema,
            "path": str(path),
            "status": str(payload.get("status") or "fail"),
            "repo_side_status": str(payload.get("repo_side_status") or ("ok" if payload.get("status") == "ok" else "fail")),
            "live_status": str(payload.get("live_status") or "skipped"),
            "live_foundation_status": "ok" if any(
                isinstance(item, dict) and item.get("name", "").endswith("_foundation") and item.get("status") == "ok"
                for item in (payload.get("live_checks") or [])
            ) else "skipped",
        }
        modules.append(module)
        artifacts.append({"path": str(path), "schema": schema})
        if module["live_status"] != "ok":
            remaining_modules.append(name)
            remaining_details[name] = {
                "status": module["live_status"],
                "required_artifacts": [
                    item.get("name")
                    for item in (payload.get("live_checks") or [])
                    if isinstance(item, dict) and item.get("status") != "ok"
                ],
                "collection_report": payload,
            }

    repo_side_ok_count = sum(1 for module in modules if module["repo_side_status"] == "ok")
    repo_side_fail_count = sum(1 for module in modules if module["repo_side_status"] != "ok")
    live_ok_count = sum(1 for module in modules if module["live_status"] == "ok")
    live_fail_count = sum(1 for module in modules if module["live_status"] == "fail")
    live_skipped_count = sum(1 for module in modules if module["live_status"] == "skipped")
    live_foundation_ok_count = sum(1 for module in modules if module["live_foundation_status"] == "ok")
    live_foundation_fail_count = sum(1 for module in modules if module["live_foundation_status"] == "fail")
    live_foundation_skipped_count = sum(1 for module in modules if module["live_foundation_status"] == "skipped")

    blockers = {
        "schema": BLOCKERS_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "remaining_live_module_count": len(remaining_modules),
        "remaining_modules": remaining_modules,
        "spiffe_envoy": remaining_details.get("spiffe_envoy", {"status": "ok", "required_artifacts": [], "collection_report": None}),
        "authority": remaining_details.get("authority", {"status": "ok", "required_artifacts": [], "collection_report": None}),
    }

    closure = {
        "schema": PRODUCTION_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if live_fail_count == 0 and repo_side_fail_count == 0 else "fail",
        "repo_side_status": "ok" if repo_side_fail_count == 0 else "fail",
        "live_status": "ok" if live_fail_count == 0 and live_skipped_count == 0 else "fail" if live_fail_count else "skipped",
        "summary": {
            "module_count": len(modules),
            "repo_side_ok_count": repo_side_ok_count,
            "repo_side_fail_count": repo_side_fail_count,
            "live_ok_count": live_ok_count,
            "live_fail_count": live_fail_count,
            "live_skipped_count": live_skipped_count,
            "live_foundation_ok_count": live_foundation_ok_count,
            "live_foundation_fail_count": live_foundation_fail_count,
            "live_foundation_skipped_count": live_foundation_skipped_count,
        },
        "modules": modules,
        "repo_side_boundary": [
            "This aggregate summary is built from already-generated module gates.",
            "It does not rerun module checks; it reflects the current authoritative gate files under reports_root.",
        ],
        "live_boundary": [
            "A module counts as live ok only when its gate file currently records live_status=ok.",
            "Remaining skipped or failed live modules remain visible here instead of being hidden behind repo-side green checks.",
        ],
        "remaining_live_blockers_report": blockers,
        "artifacts": artifacts + [{"path": str(Path(args.blockers_output).resolve()), "schema": BLOCKERS_SCHEMA}],
    }

    write_json(Path(args.blockers_output), blockers)
    write_json(Path(args.closure_output), closure)
    print(json.dumps({"closure": closure["summary"], "remaining_live_module_count": blockers["remaining_live_module_count"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
