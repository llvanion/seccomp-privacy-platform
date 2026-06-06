#!/usr/bin/env python3
"""Verifier-facing gate for e-commerce deployment evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ecommerce_deployment_evidence_gate/v1"
DEFAULT_LIVE_ARCHIVE = REPO_ROOT / "tmp" / "ecommerce_live_archive" / "ecommerce_live_evidence_archive.json"


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

    exposure_dir = out_dir / "ecommerce_production_exposure"
    res = run(["python3", str(REPO_ROOT / "scripts" / "check_ecommerce_production_exposure_gate.py"), "--out-dir", str(exposure_dir)])
    if res.returncode == 0:
        exposure = load_json(exposure_dir / "ecommerce_production_exposure_gate.json")
        repo_side_checks.append(
            parse_check(
                name="repo_side_ecommerce_production_exposure",
                status="ok" if exposure.get("status") == "ok" else "fail",
                expected="e-commerce fact layer, business personas, direct query scope, approval workflow, and console contact surface remain aligned",
                actual=exposure,
            )
        )
        artifacts.append(artifact(exposure_dir / "ecommerce_production_exposure_gate.json", schema="ecommerce_production_exposure_gate/v1"))
    else:
        stderr = res.stderr.strip()
        stdout = res.stdout.strip()
        combined = "\n".join(part for part in (stdout, stderr) if part)
        if "PermissionError" in combined and ("socket" in combined or "Operation not permitted" in combined):
            repo_side_checks.append(
                parse_check(
                    name="repo_side_ecommerce_production_exposure",
                    status="skipped",
                    expected="e-commerce fact layer, business personas, direct query scope, approval workflow, and console contact surface remain aligned",
                    actual={"stdout": stdout, "stderr": stderr},
                    missing_prerequisites=["environment permits loopback listener sockets for e-commerce API/request-workflow smoke"],
                )
            )
        else:
            require_ok(res, label="check_ecommerce_production_exposure_gate")

    archive_path = Path(args.live_evidence_archive).resolve() if args.live_evidence_archive else None
    if archive_path is None:
        archive_path = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname="ecommerce_live_archive",
            archive_filename="ecommerce_live_evidence_archive.json",
            expected_schema="ecommerce_live_evidence_archive/v1",
        )
        if archive_path is None and DEFAULT_LIVE_ARCHIVE.is_file():
            archive_path = DEFAULT_LIVE_ARCHIVE.resolve()
    if archive_path is None:
        live_checks.append(
            parse_check(
                name="live_ecommerce_evidence_archive",
                status="skipped",
                expected="operator provides a unified live e-commerce deployment evidence archive",
                actual=None,
                missing_prerequisites=["--live-evidence-archive or tmp/ecommerce_live_archive/ecommerce_live_evidence_archive.json"],
            )
        )
    elif not archive_path.is_file():
        live_checks.append(
            parse_check(
                name="live_ecommerce_evidence_archive",
                status="fail",
                expected="operator provides a unified live e-commerce deployment evidence archive",
                actual={"path": str(archive_path), "exists": False},
            )
        )
    else:
        archive = load_json(archive_path)
        artifacts.append(artifact(archive_path, schema="ecommerce_live_evidence_archive/v1"))
        live_artifact_count = int(archive.get("live_artifact_count") or 0)
        live_checks.append(
            parse_check(
                name="live_ecommerce_evidence_archive",
                status="ok" if archive.get("status") == "ok" and live_artifact_count > 0 else "skipped" if archive.get("status") == "ok" else "fail",
                expected="operator provides a unified live e-commerce deployment evidence archive",
                actual=archive,
                missing_prerequisites=["archive contains no live e-commerce deployment artifacts"] if archive.get("status") == "ok" and live_artifact_count == 0 else None,
            )
        )
        foundation_present = isinstance((archive.get("live_artifacts") or {}).get("live_repo_side_ecommerce_foundation"), dict)
        live_checks.append(
            parse_check(
                name="live_ecommerce_foundation",
                status="ok" if foundation_present else "skipped",
                expected="current-worktree e-commerce exposure baseline is frozen into the live e-commerce archive",
                actual=(archive.get("live_artifacts") or {}).get("live_repo_side_ecommerce_foundation"),
                missing_prerequisites=["live_repo_side_ecommerce_foundation not present in e-commerce live archive"] if not foundation_present else None,
            )
        )
        rollout_present = any(
            isinstance((archive.get("live_artifacts") or {}).get(name), dict)
            for name in (
                "live_oidc_abac_report",
                "live_fact_import_report",
                "live_tls_network_policy_report",
                "live_postgres_anchor_report",
                "live_logistics_rollout_report",
            )
        )
        live_checks.append(
            parse_check(
                name="live_real_ecommerce_rollout",
                status="ok" if rollout_present else "skipped",
                expected="real identity/ABAC, approved fact import, TLS/NetworkPolicy, Postgres/anchor, or logistics rollout artifacts are archived as typed verifier-facing reports",
                actual={
                    key: (archive.get("live_artifacts") or {}).get(key)
                    for key in (
                        "live_oidc_abac_report",
                        "live_fact_import_report",
                        "live_tls_network_policy_report",
                        "live_postgres_anchor_report",
                        "live_logistics_rollout_report",
                    )
                },
                missing_prerequisites=["real e-commerce rollout artifacts are still missing"] if not rollout_present else None,
            )
        )

    repo_side_status = "ok" if all(item["status"] in {"ok", "skipped"} for item in repo_side_checks) else "fail"
    concrete_live = [item for item in live_checks if item["name"] == "live_ecommerce_evidence_archive"]
    rollout_live = [item for item in live_checks if item["name"] == "live_real_ecommerce_rollout"]
    if any(item["status"] == "fail" for item in concrete_live):
        live_status = "fail"
    elif rollout_live and all(item["status"] == "ok" for item in rollout_live):
        live_status = "ok"
    else:
        live_status = "skipped"

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if repo_side_status == "ok" and live_status != "fail" else "fail",
        "repo_side_status": repo_side_status,
        "live_status": live_status,
        "repo_side_checks": repo_side_checks,
        "live_checks": live_checks,
        "repo_side_boundary": [
            "Repo-side checks prove the fact schema, business persona field guards, identity-bound query/request scopes, and console contact surface remain coherent.",
            "They do not prove live OIDC/ABAC, approved fact imports, production TLS/NetworkPolicy, PostgreSQL drills, or external immutable audit anchoring.",
        ],
        "live_boundary": [
            "Live e-commerce readiness requires operator-provided identity/ABAC, fact import, TLS/network policy, Postgres/anchor, or equivalent verifier-facing rollout artifacts such as logistics rollout evidence.",
            "When no live archive is supplied, or when the archive contains only frozen foundation evidence, this gate stays at live_status=skipped rather than claiming production-complete e-commerce deployment.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "ecommerce_deployment_evidence_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
