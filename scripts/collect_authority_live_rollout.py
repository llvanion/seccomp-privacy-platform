#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "live_rollout_collection_report/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
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
    ap = argparse.ArgumentParser(description="Collect authority live rollout evidence or emit a typed blocker report.")
    ap.add_argument("--output", required=True)
    ap.add_argument("--archive-output-dir", default="")
    ap.add_argument("--gate-output-dir", default="")
    ap.add_argument("--compose-file", default=str(REPO_ROOT / "docker-compose.authority.yml"))
    ap.add_argument("--live-keycloak-report", default="")
    ap.add_argument("--live-openfga-report", default="")
    ap.add_argument("--live-vault-report", default="")
    ap.add_argument("--live-cloud-kms-report", default="")
    ap.add_argument("--live-rotation-report", default="")
    args = ap.parse_args()

    output_path = Path(args.output).resolve()
    archive_dir = Path(args.archive_output_dir).resolve() if args.archive_output_dir else (output_path.parent / "authority_live_archive")
    gate_dir = Path(args.gate_output_dir).resolve() if args.gate_output_dir else (output_path.parent / "authority_evidence_gate")

    required_artifacts = [
        "live_keycloak_report",
        "live_openfga_report",
        "live_vault_report",
        "live_cloud_kms_report",
        "live_rotation_report",
    ]
    provided = {
        "live_keycloak_report": args.live_keycloak_report or None,
        "live_openfga_report": args.live_openfga_report or None,
        "live_vault_report": args.live_vault_report or None,
        "live_cloud_kms_report": args.live_cloud_kms_report or None,
        "live_rotation_report": args.live_rotation_report or None,
    }

    checks: list[dict[str, Any]] = []
    findings: list[str] = []

    compose_file = Path(args.compose_file).resolve()
    checks.append({
        "name": "compose_file_present",
        "status": "ok" if compose_file.is_file() else "error",
        "detail": str(compose_file),
    })
    docker_present = shutil.which("docker") is not None
    checks.append({
        "name": "docker_present",
        "status": "ok" if docker_present else "blocked",
        "detail": docker_present,
    })
    if not docker_present:
        findings.append("docker is not installed in the current environment")

    missing = [name for name, path in provided.items() if not path]
    if missing:
        findings.append(f"missing live artifact inputs: {', '.join(missing)}")
    provided_count = sum(1 for path in provided.values() if path)

    status = "blocked"
    archive_path: str | None = None
    gate_path: str | None = None
    gate_live_status: str | None = None

    if provided_count > 0:
        archive_cmd = [
            "python3",
            str(REPO_ROOT / "scripts" / "archive_authority_live_evidence.py"),
            "--job-id",
            "authority-live",
            "--live-keycloak-report",
            args.live_keycloak_report,
            "--live-openfga-report",
            args.live_openfga_report,
            "--live-vault-report",
            args.live_vault_report,
            "--live-cloud-kms-report",
            args.live_cloud_kms_report,
            "--live-rotation-report",
            args.live_rotation_report,
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
            archive_path = str((archive_dir / "authority_live_evidence_archive.json").resolve())
            gate_cmd = [
                "python3",
                str(REPO_ROOT / "scripts" / "check_authority_evidence_gate.py"),
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
                gate_json = json.loads((gate_dir / "authority_evidence_gate.json").read_text(encoding="utf-8"))
                gate_path = str((gate_dir / "authority_evidence_gate.json").resolve())
                gate_live_status = str(gate_json.get("live_status") or "")
                status = "ok" if gate_live_status == "ok" else "blocked"
                if status != "ok":
                    findings.append(f"verifier gate live_status={gate_live_status}")
        else:
            findings.append("archive_authority_live_evidence.py failed")
    else:
        status = "blocked"

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "module_name": "authority",
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
