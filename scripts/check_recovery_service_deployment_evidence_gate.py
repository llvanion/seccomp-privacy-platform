#!/usr/bin/env python3
"""Verifier-facing gate for recovery-service deployment evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "recovery_service_deployment_evidence_gate/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact(path: Path, *, schema: str | None = None, note: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"path": str(path)}
    if schema:
        item["schema"] = schema
    if note:
        item["note"] = note
    return item


def parse_check(
    *,
    name: str,
    status: str,
    expected: Any,
    actual: Any,
    missing_prerequisites: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "name": name,
        "status": status,
        "expected": expected,
        "actual": actual,
    }
    if missing_prerequisites is not None:
        payload["missing_prerequisites"] = missing_prerequisites
    return payload


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def require_ok(res: subprocess.CompletedProcess[str], *, label: str) -> None:
    if res.returncode != 0:
        raise RuntimeError(f"{label} failed ({res.returncode})\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--live-evidence-archive", default="")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    repo_side_checks: list[dict[str, Any]] = []
    live_checks: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    production_gate_path = out_dir / "record_recovery_production_gate_check.json"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "check_record_recovery_production_gate.py"),
        "--out", str(production_gate_path),
    ])
    require_ok(res, label="check_record_recovery_production_gate")
    production_gate = load_json(production_gate_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_record_recovery_production_gate",
            status="ok" if (production_gate.get("summary") or {}).get("status") == "ok" else "fail",
            expected="recovery-service production gate rejects unsafe HTTP deployment configs before launch/render",
            actual=production_gate,
        )
    )
    artifacts.append(artifact(production_gate_path, schema="record_recovery_production_gate_check/v1"))

    failover_path = out_dir / "recovery_service_failover_test.json"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "test_failover_recovery_service.py"),
        "--output", str(failover_path),
        "--assert-ok",
    ])
    if res.returncode == 0:
        failover = load_json(failover_path)
        repo_side_checks.append(
            parse_check(
                name="repo_side_recovery_service_failover",
                status="ok" if failover.get("status") == "ok" else "fail",
                expected="recovery-service retry/failover path preserves successful service and audit continuity",
                actual=failover,
            )
        )
        artifacts.append(artifact(failover_path, schema="recovery_service_failover_test/v1"))
    else:
        stderr = res.stderr.strip()
        if "PermissionError" in stderr and ("socket" in stderr or "Operation not permitted" in stderr):
            repo_side_checks.append(
                parse_check(
                    name="repo_side_recovery_service_failover",
                    status="skipped",
                    expected="recovery-service retry/failover path preserves successful service and audit continuity",
                    actual={"stderr": stderr},
                    missing_prerequisites=["environment permits loopback listener sockets for recovery-service failover smoke"],
                )
            )
        else:
            require_ok(res, label="test_failover_recovery_service")

    k8s_topology_path = out_dir / "k8s_recovery_service_topology_report.json"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "render_recovery_service_k8s.py"),
        "--tenant-id", "contract-tenant",
        "--namespace", "seccomp-privacy",
        "--replicas", "2",
        "--min-replicas", "2",
        "--max-replicas", "6",
        "--target-cpu-utilization", "70",
        "--container-port", "18443",
        "--service-port", "443",
        "--image", "ghcr.io/seccomp-privacy/recovery-service:0.1.0",
        "--out-dir", str(out_dir / "k8s_recovery"),
        "--output", str(k8s_topology_path),
        "--assert-ok",
    ])
    require_ok(res, label="render_recovery_service_k8s")
    k8s_topology = load_json(k8s_topology_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_recovery_service_k8s_topology",
            status="ok" if k8s_topology.get("status") == "ok" else "fail",
            expected="recovery-service Deployment/Service/HPA topology remains structurally coherent",
            actual=k8s_topology,
        )
    )
    artifacts.append(artifact(k8s_topology_path, schema="k8s_recovery_service_topology_report/v1"))

    netpol_path = out_dir / "k8s_network_policy_report.json"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "render_k8s_network_policies.py"),
        "--tenant-id", "contract-tenant",
        "--tenant-id", "tenant-demo-2",
        "--namespace", "seccomp-privacy",
        "--out-dir", str(out_dir / "k8s_netpol"),
        "--output", str(netpol_path),
        "--assert-ok",
    ])
    require_ok(res, label="render_k8s_network_policies")
    netpol = load_json(netpol_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_recovery_service_network_policy",
            status="ok" if netpol.get("status") == "ok" else "fail",
            expected="tenant-scoped recovery-service NetworkPolicy render remains structurally coherent",
            actual=netpol,
        )
    )
    artifacts.append(artifact(netpol_path, schema="k8s_network_policy_report/v1"))

    archive_path = Path(args.live_evidence_archive).resolve() if args.live_evidence_archive else None
    if archive_path is None:
        archive_path = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname="recovery_service_live_archive",
            archive_filename="recovery_service_live_evidence_archive.json",
            expected_schema="recovery_service_live_evidence_archive/v1",
        )
    if archive_path is None:
        live_checks.append(
            parse_check(
                name="live_recovery_service_evidence_archive",
                status="skipped",
                expected="operator provides a unified live recovery-service deployment evidence archive",
                actual=None,
                missing_prerequisites=["--live-evidence-archive"],
            )
        )
    elif not archive_path.is_file():
        live_checks.append(
            parse_check(
                name="live_recovery_service_evidence_archive",
                status="fail",
                expected="operator provides a unified live recovery-service deployment evidence archive",
                actual={"path": str(archive_path), "exists": False},
            )
        )
    else:
        archive = load_json(archive_path)
        artifacts.append(artifact(archive_path, schema="recovery_service_live_evidence_archive/v1"))
        live_artifact_count = int(archive.get("live_artifact_count") or 0)
        live_checks.append(
            parse_check(
                name="live_recovery_service_evidence_archive",
                status="ok" if archive.get("status") == "ok" and live_artifact_count > 0 else "skipped" if archive.get("status") == "ok" else "fail",
                expected="operator provides a unified live recovery-service deployment evidence archive",
                actual=archive,
                missing_prerequisites=["archive contains no live recovery-service deployment artifacts"] if archive.get("status") == "ok" and live_artifact_count == 0 else None,
            )
        )

    repo_side_status = "ok" if all(item["status"] in {"ok", "skipped"} for item in repo_side_checks) else "fail"
    concrete_live = [item for item in live_checks if item["name"] == "live_recovery_service_evidence_archive"]
    live_status = (
        "fail" if any(item["status"] == "fail" for item in concrete_live)
        else "ok" if concrete_live and all(item["status"] == "ok" for item in concrete_live)
        else "skipped"
    )

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if repo_side_status == "ok" and live_status != "fail" else "fail",
        "repo_side_status": repo_side_status,
        "live_status": live_status,
        "repo_side_checks": repo_side_checks,
        "live_checks": live_checks,
        "repo_side_boundary": [
            "Repo-side checks prove production HTTP gate semantics, loopback failover continuity, and committed K8s/network-policy deployment topology coherence.",
            "They do not prove a real service user/systemd sandbox, host firewall or Kubernetes NetworkPolicy enforcement, or deployed public-network mTLS traffic on target hosts.",
        ],
        "live_boundary": [
            "Live recovery-service readiness requires operator-provided systemd/service-user, firewall/network-policy, public mTLS, and target-host failover artifacts.",
            "When no live archive is supplied, this gate stays at live_status=skipped rather than claiming production-complete recovery-service deployment hardening.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "recovery_service_deployment_evidence_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
