#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "live_rollout_collection_report/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect e-commerce live rollout evidence or emit a typed blocker report.")
    ap.add_argument("--output", required=True)
    ap.add_argument("--archive-output-dir", default="")
    ap.add_argument("--gate-output-dir", default="")
    ap.add_argument("--foundation-report", default=str(REPO_ROOT / "tmp" / "ecommerce_production_exposure_gate" / "ecommerce_production_exposure_gate.json"))
    ap.add_argument("--live-oidc-abac-report", default="")
    ap.add_argument("--live-fact-import-report", default="")
    ap.add_argument("--live-tls-network-policy-report", default="")
    ap.add_argument("--live-postgres-anchor-report", default="")
    ap.add_argument("--live-logistics-rollout-report", default="")
    args = ap.parse_args()

    output_path = Path(args.output).resolve()
    archive_dir = Path(args.archive_output_dir).resolve() if args.archive_output_dir else (output_path.parent / "ecommerce_live_archive")
    gate_dir = Path(args.gate_output_dir).resolve() if args.gate_output_dir else (output_path.parent / "ecommerce_deployment_evidence_gate")

    if not args.live_logistics_rollout_report:
        for candidate in (
            REPO_ROOT / "tmp" / "ecommerce_live_archive" / "ecommerce_logistics_live_rollout_report.json",
            REPO_ROOT / "tmp" / "logistics_live_synthetic" / "ecommerce_logistics_live_rollout_report.json",
        ):
            if candidate.is_file():
                args.live_logistics_rollout_report = str(candidate)
                break

    required_artifacts = [
        "live_repo_side_ecommerce_foundation",
        "live_oidc_abac_report",
        "live_fact_import_report",
        "live_tls_network_policy_report",
        "live_postgres_anchor_report",
        "live_logistics_rollout_report",
    ]
    provided = {
        "live_repo_side_ecommerce_foundation": args.foundation_report or None,
        "live_oidc_abac_report": args.live_oidc_abac_report or None,
        "live_fact_import_report": args.live_fact_import_report or None,
        "live_tls_network_policy_report": args.live_tls_network_policy_report or None,
        "live_postgres_anchor_report": args.live_postgres_anchor_report or None,
        "live_logistics_rollout_report": args.live_logistics_rollout_report or None,
    }

    checks: list[dict] = []
    findings: list[str] = []

    archive_script = REPO_ROOT / "scripts" / "archive_ecommerce_live_evidence.py"
    gate_script = REPO_ROOT / "scripts" / "check_ecommerce_deployment_evidence_gate.py"
    checks.append({
        "name": "archive_script_present",
        "status": "ok" if archive_script.is_file() else "error",
        "detail": str(archive_script),
    })
    checks.append({
        "name": "gate_script_present",
        "status": "ok" if gate_script.is_file() else "error",
        "detail": str(gate_script),
    })
    python_present = shutil.which("python3") is not None
    checks.append({
        "name": "python_present",
        "status": "ok" if python_present else "blocked",
        "detail": python_present,
    })
    if not python_present:
        findings.append("python3 is not installed in the current environment")

    missing = [name for name, path in provided.items() if not path]
    if missing:
        findings.append(f"missing live artifact inputs: {', '.join(missing)}")

    status = "blocked"
    archive_path: str | None = None
    gate_path: str | None = None
    gate_live_status: str | None = None

    if provided["live_logistics_rollout_report"] or (
        provided["live_oidc_abac_report"]
        and provided["live_fact_import_report"]
        and provided["live_tls_network_policy_report"]
        and provided["live_postgres_anchor_report"]
    ):
        archive_cmd = [
            "python3",
            str(archive_script),
            "--job-id",
            "ecommerce-live",
            "--live-repo-side-ecommerce-foundation",
            args.foundation_report,
            "--live-oidc-abac-report",
            args.live_oidc_abac_report,
            "--live-fact-import-report",
            args.live_fact_import_report,
            "--live-tls-network-policy-report",
            args.live_tls_network_policy_report,
            "--live-postgres-anchor-report",
            args.live_postgres_anchor_report,
            "--live-logistics-rollout-report",
            args.live_logistics_rollout_report,
            "--output-dir",
            str(archive_dir),
        ]
        archive_res = run(archive_cmd)
        checks.append({
            "name": "archive_live_evidence",
            "status": "ok" if archive_res.returncode == 0 else "error",
            "detail": {"returncode": archive_res.returncode, "stderr": archive_res.stderr.strip()},
        })
        if archive_res.returncode == 0:
            archive_path = str((archive_dir / "ecommerce_live_evidence_archive.json").resolve())
            gate_cmd = [
                "python3",
                str(gate_script),
                "--out-dir",
                str(gate_dir),
                "--live-evidence-archive",
                archive_path,
            ]
            gate_res = run(gate_cmd)
            checks.append({
                "name": "build_verifier_gate",
                "status": "ok" if gate_res.returncode == 0 else "error",
                "detail": {"returncode": gate_res.returncode, "stderr": gate_res.stderr.strip()},
            })
            if gate_res.returncode == 0:
                gate_json = json.loads((gate_dir / "ecommerce_deployment_evidence_gate.json").read_text(encoding="utf-8"))
                gate_path = str((gate_dir / "ecommerce_deployment_evidence_gate.json").resolve())
                gate_live_status = str(gate_json.get("live_status") or "")
                status = "ok" if gate_live_status == "ok" else "blocked"
                if status != "ok":
                    findings.append(f"verifier gate live_status={gate_live_status}")
            else:
                findings.append("check_ecommerce_deployment_evidence_gate.py failed")
        else:
            findings.append("archive_ecommerce_live_evidence.py failed")
    else:
        status = "blocked"
        findings.append(
            "at least one real e-commerce rollout path is required: either live_logistics_rollout_report or the full oidc/import/tls/postgres set"
        )

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "module_name": "ecommerce",
        "status": status,
        "checks": checks,
        "required_artifacts": required_artifacts,
        "provided_artifacts": provided,
        "outputs": {
            "archive_path": archive_path,
            "gate_path": gate_path,
            "gate_live_status": gate_live_status,
        },
        "findings": findings,
    }
    write_json(output_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
