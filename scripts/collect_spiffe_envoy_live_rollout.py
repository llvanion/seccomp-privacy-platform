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
    ap = argparse.ArgumentParser(description="Collect SPIFFE/Envoy live rollout evidence or emit a typed blocker report.")
    ap.add_argument("--output", required=True)
    ap.add_argument("--archive-output-dir", default="")
    ap.add_argument("--gate-output-dir", default="")
    ap.add_argument("--templates-dir", default=str(REPO_ROOT / "deploy" / "spiffe_envoy"))
    ap.add_argument("--live-positive-report", default="")
    ap.add_argument("--live-wrong-peer-report", default="")
    ap.add_argument("--live-expired-svid-report", default="")
    ap.add_argument("--live-trust-bundle-reject-report", default="")
    ap.add_argument("--live-envoy-access-log", default="")
    args = ap.parse_args()

    output_path = Path(args.output).resolve()
    archive_dir = Path(args.archive_output_dir).resolve() if args.archive_output_dir else (output_path.parent / "spiffe_envoy_live_archive")
    gate_dir = Path(args.gate_output_dir).resolve() if args.gate_output_dir else (output_path.parent / "spiffe_envoy_identity_gate")

    required_artifacts = [
        "live_positive_run",
        "live_wrong_peer_reject",
        "live_expired_svid_reject",
        "live_trust_bundle_reject",
        "live_envoy_access_log",
    ]
    provided = {
        "live_positive_run": args.live_positive_report or None,
        "live_wrong_peer_reject": args.live_wrong_peer_report or None,
        "live_expired_svid_reject": args.live_expired_svid_report or None,
        "live_trust_bundle_reject": args.live_trust_bundle_reject_report or None,
        "live_envoy_access_log": args.live_envoy_access_log or None,
    }

    checks: list[dict[str, Any]] = []
    findings: list[str] = []

    templates_dir = Path(args.templates_dir).resolve()
    checks.append({
        "name": "templates_dir_present",
        "status": "ok" if templates_dir.is_dir() else "error",
        "detail": str(templates_dir),
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

    status = "blocked"
    archive_path: str | None = None
    gate_path: str | None = None
    gate_live_status: str | None = None

    if not missing:
        archive_cmd = [
            "python3",
            str(REPO_ROOT / "scripts" / "archive_spiffe_envoy_live_evidence.py"),
            "--job-id",
            "spiffe-envoy-live",
            "--templates-dir",
            str(templates_dir),
            "--live-positive-report",
            args.live_positive_report,
            "--live-wrong-peer-report",
            args.live_wrong_peer_report,
            "--live-expired-svid-report",
            args.live_expired_svid_report,
            "--live-trust-bundle-reject-report",
            args.live_trust_bundle_reject_report,
            "--live-envoy-access-log",
            args.live_envoy_access_log,
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
            archive_path = str((archive_dir / "spiffe_envoy_live_evidence_archive.json").resolve())
            gate_cmd = [
                "python3",
                str(REPO_ROOT / "scripts" / "check_spiffe_envoy_identity_gate.py"),
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
                gate_json = json.loads((gate_dir / "spiffe_envoy_identity_gate.json").read_text(encoding="utf-8"))
                gate_path = str((gate_dir / "spiffe_envoy_identity_gate.json").resolve())
                gate_live_status = str(gate_json.get("live_status") or "")
                status = "ok" if gate_live_status == "ok" else "blocked"
                if status != "ok":
                    findings.append(f"verifier gate live_status={gate_live_status}")
        else:
            findings.append("archive_spiffe_envoy_live_evidence.py failed")

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "module_name": "spiffe_envoy",
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
