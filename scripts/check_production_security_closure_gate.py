#!/usr/bin/env python3
"""Aggregate verifier-facing production-security modules into one closure report."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "production_security_closure_gate/v1"
FINAL_BLOCKERS_REPORT = REPO_ROOT / "tmp" / "final_live_blockers_report.json"

MODULES = [
    {
        "name": "public_two_host",
        "subdir": "public_two_host_production_readiness_gate",
        "filename": "public_two_host_production_readiness_gate.json",
        "schema": "public_two_host_production_readiness_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_public_two_host_production_readiness_gate.py")],
    },
    {
        "name": "spiffe_envoy",
        "subdir": "spiffe_envoy_identity_gate",
        "filename": "spiffe_envoy_identity_gate.json",
        "schema": "spiffe_envoy_identity_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_spiffe_envoy_identity_gate.py")],
    },
    {
        "name": "external_anchor",
        "subdir": "external_anchor_evidence_gate",
        "filename": "external_anchor_evidence_gate.json",
        "schema": "external_anchor_evidence_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_external_anchor_evidence_gate.py")],
    },
    {
        "name": "postgres_ha",
        "subdir": "postgres_ha_evidence_gate",
        "filename": "postgres_ha_evidence_gate.json",
        "schema": "postgres_ha_evidence_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_postgres_ha_evidence_gate.py")],
    },
    {
        "name": "supply_chain",
        "subdir": "supply_chain_evidence_gate",
        "filename": "supply_chain_evidence_gate.json",
        "schema": "supply_chain_evidence_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_supply_chain_evidence_gate.py")],
    },
    {
        "name": "authority",
        "subdir": "authority_evidence_gate",
        "filename": "authority_evidence_gate.json",
        "schema": "authority_evidence_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_authority_evidence_gate.py")],
    },
    {
        "name": "observability",
        "subdir": "observability_evidence_gate",
        "filename": "observability_evidence_gate.json",
        "schema": "observability_evidence_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_observability_evidence_gate.py")],
    },
    {
        "name": "recovery_service",
        "subdir": "recovery_service_deployment_evidence_gate",
        "filename": "recovery_service_deployment_evidence_gate.json",
        "schema": "recovery_service_deployment_evidence_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_recovery_service_deployment_evidence_gate.py")],
    },
    {
        "name": "privacy_budget",
        "subdir": "privacy_budget_deployment_evidence_gate",
        "filename": "privacy_budget_deployment_evidence_gate.json",
        "schema": "privacy_budget_deployment_evidence_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_privacy_budget_deployment_evidence_gate.py")],
    },
    {
        "name": "legacy_sse",
        "subdir": "legacy_sse_query_surface_evidence_gate",
        "filename": "legacy_sse_query_surface_evidence_gate.json",
        "schema": "legacy_sse_query_surface_evidence_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_legacy_sse_query_surface_evidence_gate.py")],
    },
    {
        "name": "pjc_resource_isolation",
        "subdir": "pjc_resource_isolation_evidence_gate",
        "filename": "pjc_resource_isolation_evidence_gate.json",
        "schema": "pjc_resource_isolation_evidence_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_pjc_resource_isolation_evidence_gate.py")],
    },
    {
        "name": "query_workflow",
        "subdir": "query_workflow_deployment_evidence_gate",
        "filename": "query_workflow_deployment_evidence_gate.json",
        "schema": "query_workflow_deployment_evidence_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_query_workflow_deployment_evidence_gate.py")],
    },
    {
        "name": "ecommerce",
        "subdir": "ecommerce_deployment_evidence_gate",
        "filename": "ecommerce_deployment_evidence_gate.json",
        "schema": "ecommerce_deployment_evidence_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_ecommerce_deployment_evidence_gate.py")],
    },
    {
        "name": "console",
        "subdir": "console_deployment_evidence_gate",
        "filename": "console_deployment_evidence_gate.json",
        "schema": "console_deployment_evidence_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_console_deployment_evidence_gate.py")],
    },
    {
        "name": "control_plane",
        "subdir": "control_plane_deployment_evidence_gate",
        "filename": "control_plane_deployment_evidence_gate.json",
        "schema": "control_plane_deployment_evidence_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_control_plane_deployment_evidence_gate.py")],
    },
    {
        "name": "pjc_protocol",
        "subdir": "pjc_protocol_security_evidence_gate",
        "filename": "pjc_protocol_security_evidence_gate.json",
        "schema": "pjc_protocol_security_evidence_gate/v1",
        "cmd": ["python3", str(REPO_ROOT / "scripts" / "check_pjc_protocol_security_evidence_gate.py")],
    },
]

DEFAULT_LIVE_ARCHIVES = {
    "postgres_ha": ("postgres_ha_live_archive", "postgres_ha_live_evidence_archive.json", "postgres_ha_live_evidence_archive/v1"),
    "supply_chain": ("supply_chain_live_archive", "supply_chain_live_evidence_archive.json", "supply_chain_live_evidence_archive/v1"),
    "authority": ("authority_live_archive", "authority_live_evidence_archive.json", "authority_live_evidence_archive/v1"),
    "observability": ("observability_live_archive", "observability_live_evidence_archive.json", "observability_live_evidence_archive/v1"),
    "query_workflow": ("query_workflow_live_archive", "query_workflow_live_evidence_archive.json", "query_workflow_live_evidence_archive/v1"),
    "ecommerce": ("ecommerce_live_archive", "ecommerce_live_evidence_archive.json", "ecommerce_live_evidence_archive/v1"),
    "console": ("console_live_archive", "console_live_evidence_archive.json", "console_live_evidence_archive/v1"),
    "control_plane": ("control_plane_live_archive", "control_plane_live_evidence_archive.json", "control_plane_live_evidence_archive/v1"),
    "pjc_protocol": ("pjc_protocol_live_archive", "pjc_protocol_live_evidence_archive.json", "pjc_protocol_live_evidence_archive/v1"),
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def foundation_status_for(module_name: str, payload: dict[str, Any]) -> str:
    checks = payload.get("live_checks")
    if not isinstance(checks, list):
        return "skipped"
    by_module = {
        "authority": ["live_authority_foundation"],
        "pjc_protocol": ["live_public_two_host_protocol_foundation"],
        "ecommerce": ["live_ecommerce_foundation"],
        "console": ["live_console_foundation"],
        "control_plane": ["live_control_plane_foundation"],
        "query_workflow": ["live_query_workflow_foundation"],
        "observability": ["live_observability_foundation"],
        "postgres_ha": ["live_postgres_ha_foundation"],
        "supply_chain": ["live_supply_chain_foundation"],
    }
    preferred = by_module.get(module_name, [])
    fallback = [
        "live_authority_foundation",
        "live_public_two_host_protocol_foundation",
        "live_ecommerce_foundation",
        "live_console_foundation",
        "live_control_plane_foundation",
        "live_query_workflow_foundation",
        "live_observability_foundation",
        "live_postgres_ha_foundation",
        "live_supply_chain_foundation",
    ]
    ordered_names = preferred + [name for name in fallback if name not in preferred]
    for check_name in ordered_names:
        for item in checks:
            if isinstance(item, dict) and item.get("name") == check_name:
                return str(item.get("status") or "skipped")
    return "skipped"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def ensure_module_report(spec: dict[str, Any], *, reports_root: Path | None, out_dir: Path) -> tuple[Path | None, dict[str, Any] | None]:
    default_tmp_candidate = REPO_ROOT / "tmp" / spec["subdir"] / spec["filename"]
    if reports_root is None and default_tmp_candidate.is_file():
        return default_tmp_candidate, None
    if reports_root is not None:
        candidate = reports_root / spec["subdir"] / spec["filename"]
        if candidate.is_file():
            return candidate, None
        flat_candidate = reports_root / spec["filename"]
        if flat_candidate.is_file():
            return flat_candidate, None
        matches = sorted(
            reports_root.rglob(spec["filename"]),
            key=lambda path: (path.stat().st_mtime, str(path)),
        )
        if matches:
            return matches[-1], None
    module_out = out_dir / spec["subdir"]
    module_out.mkdir(parents=True, exist_ok=True)
    cmd = list(spec["cmd"]) + ["--out-dir", str(module_out)]
    live_archive_spec = DEFAULT_LIVE_ARCHIVES.get(spec["name"])
    if live_archive_spec is not None:
        dirname, filename, expected_schema = live_archive_spec
        live_archive = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname=dirname,
            archive_filename=filename,
            expected_schema=expected_schema,
        )
        if live_archive is not None and live_archive.is_file():
            cmd.extend(["--live-evidence-archive", str(live_archive)])
    res = run(cmd)
    if res.returncode != 0:
        return None, {
            "name": spec["name"],
            "schema": spec["schema"],
            "path": str(module_out / spec["filename"]),
            "status": "fail",
            "repo_side_status": "fail",
            "live_status": "fail",
            "error": f"gate failed ({res.returncode})",
            "stdout": res.stdout,
            "stderr": res.stderr,
        }
    report_path = module_out / spec["filename"]
    if not report_path.is_file():
        return None, {
            "name": spec["name"],
            "schema": spec["schema"],
            "path": str(report_path),
            "status": "fail",
            "repo_side_status": "fail",
            "live_status": "fail",
            "error": "gate did not produce report",
            "stdout": res.stdout,
            "stderr": res.stderr,
        }
    return report_path, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--reports-root", default="")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    reports_root = Path(args.reports_root).resolve() if args.reports_root else None

    modules: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    for spec in MODULES:
        report_path, failure = ensure_module_report(spec, reports_root=reports_root, out_dir=out_dir / "modules")
        if failure is not None:
            modules.append(
                {
                    "name": failure["name"],
                    "schema": failure["schema"],
                    "path": failure["path"],
                    "status": "fail",
                    "repo_side_status": "fail",
                    "live_status": "fail",
                }
            )
            continue
        assert report_path is not None
        payload = load_json(report_path)
        repo_side_status = str(payload.get("repo_side_status") or ("ok" if payload.get("status") == "ok" else "fail"))
        live_status = str(payload.get("live_status") or "skipped")
        live_foundation_status = foundation_status_for(spec["name"], payload)
        modules.append(
            {
                "name": spec["name"],
                "schema": spec["schema"],
                "path": str(report_path),
                "status": str(payload.get("status") or "fail"),
                "repo_side_status": repo_side_status,
                "live_status": live_status,
                "live_foundation_status": live_foundation_status,
            }
        )
        artifacts.append({"path": str(report_path), "schema": spec["schema"]})

    repo_side_fail_count = sum(1 for module in modules if module["repo_side_status"] != "ok")
    repo_side_ok_count = sum(1 for module in modules if module["repo_side_status"] == "ok")
    live_ok_count = sum(1 for module in modules if module["live_status"] == "ok")
    live_fail_count = sum(1 for module in modules if module["live_status"] == "fail")
    live_skipped_count = sum(1 for module in modules if module["live_status"] == "skipped")
    live_foundation_ok_count = sum(1 for module in modules if module["live_foundation_status"] == "ok")
    live_foundation_fail_count = sum(1 for module in modules if module["live_foundation_status"] == "fail")
    live_foundation_skipped_count = sum(1 for module in modules if module["live_foundation_status"] == "skipped")

    repo_side_status = "ok" if repo_side_fail_count == 0 else "fail"
    live_status = "fail" if live_fail_count > 0 else "ok" if live_ok_count == len(modules) else "skipped"

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if repo_side_status == "ok" and live_status != "fail" else "fail",
        "repo_side_status": repo_side_status,
        "live_status": live_status,
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
            "This aggregate gate proves the current worktree has verifier-facing repo-side modules across the major production-security boundaries.",
            "It does not prove operator-managed live deployment artifacts exist for every module; consult each module's own live boundary and archive requirements.",
        ],
        "live_boundary": [
            "Some modules now carry live_foundation_status=ok, which means the current worktree has been frozen into a verifier-facing live archive shape without claiming operator rollout completion.",
            "Any module with live_status=skipped still requires operator-provided deployment evidence before the platform can be claimed production-complete.",
            "This top-level gate intentionally summarizes those gaps rather than hiding them behind repo-side green checks.",
        ],
        "artifacts": artifacts,
    }
    if FINAL_BLOCKERS_REPORT.is_file():
        final_blockers = load_json(FINAL_BLOCKERS_REPORT)
        report["remaining_live_blockers_report"] = final_blockers
        artifacts.append({"path": str(FINAL_BLOCKERS_REPORT), "schema": "final_live_blockers_report/v1"})
    write_json(out_dir / "production_security_closure_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
