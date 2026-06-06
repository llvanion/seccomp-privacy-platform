#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive


REPO_ROOT = Path(__file__).resolve().parents[1]

MODULES = [
    ("spiffe_envoy", "scripts/check_spiffe_envoy_identity_gate.py", "tmp/spiffe_envoy_identity_gate", "spiffe_envoy_live_archive", "spiffe_envoy_live_evidence_archive.json", "spiffe_envoy_live_evidence_archive/v1"),
    ("external_anchor", "scripts/check_external_anchor_evidence_gate.py", "tmp/external_anchor_evidence_gate", "external_anchor_live_archive", "external_anchor_live_evidence_archive.json", "external_anchor_live_evidence_archive/v1"),
    ("postgres_ha", "scripts/check_postgres_ha_evidence_gate.py", "tmp/postgres_ha_evidence_gate", "postgres_ha_live_archive", "postgres_ha_live_evidence_archive.json", "postgres_ha_live_evidence_archive/v1"),
    ("supply_chain", "scripts/check_supply_chain_evidence_gate.py", "tmp/supply_chain_evidence_gate", "supply_chain_live_archive", "supply_chain_live_evidence_archive.json", "supply_chain_live_evidence_archive/v1"),
    ("authority", "scripts/check_authority_evidence_gate.py", "tmp/authority_evidence_gate", "authority_live_archive", "authority_live_evidence_archive.json", "authority_live_evidence_archive/v1"),
    ("observability", "scripts/check_observability_evidence_gate.py", "tmp/observability_evidence_gate", "observability_live_archive", "observability_live_evidence_archive.json", "observability_live_evidence_archive/v1"),
    ("recovery_service", "scripts/check_recovery_service_deployment_evidence_gate.py", "tmp/recovery_service_deployment_evidence_gate", "recovery_service_live_archive", "recovery_service_live_evidence_archive.json", "recovery_service_live_evidence_archive/v1"),
    ("privacy_budget", "scripts/check_privacy_budget_deployment_evidence_gate.py", "tmp/privacy_budget_deployment_evidence_gate", "privacy_budget_live_archive", "privacy_budget_live_evidence_archive.json", "privacy_budget_live_evidence_archive/v1"),
    ("legacy_sse", "scripts/check_legacy_sse_query_surface_evidence_gate.py", "tmp/legacy_sse_query_surface_evidence_gate", "legacy_sse_live_archive", "legacy_sse_live_evidence_archive.json", "legacy_sse_live_evidence_archive/v1"),
    ("pjc_resource_isolation", "scripts/check_pjc_resource_isolation_evidence_gate.py", "tmp/pjc_resource_isolation_evidence_gate", "pjc_resource_isolation_live_archive", "pjc_resource_isolation_live_evidence_archive.json", "pjc_resource_isolation_live_evidence_archive/v1"),
    ("query_workflow", "scripts/check_query_workflow_deployment_evidence_gate.py", "tmp/query_workflow_deployment_evidence_gate", "query_workflow_live_archive", "query_workflow_live_evidence_archive.json", "query_workflow_live_evidence_archive/v1"),
    ("ecommerce", "scripts/check_ecommerce_deployment_evidence_gate.py", "tmp/ecommerce_deployment_evidence_gate", "ecommerce_live_archive", "ecommerce_live_evidence_archive.json", "ecommerce_live_evidence_archive/v1"),
    ("console", "scripts/check_console_deployment_evidence_gate.py", "tmp/console_deployment_evidence_gate", "console_live_archive", "console_live_evidence_archive.json", "console_live_evidence_archive/v1"),
    ("control_plane", "scripts/check_control_plane_deployment_evidence_gate.py", "tmp/control_plane_deployment_evidence_gate", "control_plane_live_archive", "control_plane_live_evidence_archive.json", "control_plane_live_evidence_archive/v1"),
    ("pjc_protocol", "scripts/check_pjc_protocol_security_evidence_gate.py", "tmp/pjc_protocol_security_evidence_gate", "pjc_protocol_live_archive", "pjc_protocol_live_evidence_archive.json", "pjc_protocol_live_evidence_archive/v1"),
]


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def main() -> int:
    results: list[dict[str, Any]] = []
    failures = 0
    for name, script_rel, out_dir_rel, archive_dirname, archive_filename, schema_id in MODULES:
        archive_path = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname=archive_dirname,
            archive_filename=archive_filename,
            expected_schema=schema_id,
        )
        cmd = ["python3", str(REPO_ROOT / script_rel), "--out-dir", str(REPO_ROOT / out_dir_rel)]
        if archive_path is not None:
            cmd.extend(["--live-evidence-archive", str(archive_path)])
        res = run(cmd)
        ok = res.returncode == 0
        if not ok:
            failures += 1
        results.append(
            {
                "module": name,
                "status": "ok" if ok else "fail",
                "archive_path": str(archive_path) if archive_path is not None else None,
                "returncode": res.returncode,
                "stderr": res.stderr.strip(),
            }
        )
    report = {
        "schema": "authoritative_live_gate_refresh/v1",
        "status": "ok" if failures == 0 else "fail",
        "failures": failures,
        "results": results,
    }
    out_path = REPO_ROOT / "tmp" / "authoritative_live_gate_refresh.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
