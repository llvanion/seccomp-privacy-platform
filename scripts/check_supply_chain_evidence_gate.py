#!/usr/bin/env python3
"""Verifier-facing gate for supply-chain / provenance evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "supply_chain_evidence_gate/v1"
DEFAULT_LIVE_ARCHIVE = REPO_ROOT / "tmp" / "supply_chain_live_archive" / "supply_chain_live_evidence_archive.json"


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

    supply_report_path = out_dir / "supply_chain_evidence.json"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "check_supply_chain_gate.py"),
        "--out", str(supply_report_path),
    ])
    require_ok(res, label="check_supply_chain_gate")
    supply_report = load_json(supply_report_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_supply_chain_report",
            status="ok" if supply_report.get("status") == "ok" else "fail",
            expected="repo-side supply-chain/test/provenance report is coherent",
            actual=supply_report,
        )
    )
    artifacts.append(artifact(supply_report_path, schema="supply_chain_evidence/v1"))

    archive_path = Path(args.live_evidence_archive).resolve() if args.live_evidence_archive else None
    if archive_path is None:
        archive_path = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname="supply_chain_live_archive",
            archive_filename="supply_chain_live_evidence_archive.json",
            expected_schema="supply_chain_live_evidence_archive/v1",
        )
        if archive_path is None and DEFAULT_LIVE_ARCHIVE.is_file():
            archive_path = DEFAULT_LIVE_ARCHIVE.resolve()
    if archive_path is None:
        live_checks.append(
            parse_check(
                name="live_supply_chain_archive",
                status="skipped",
                expected="operator provides a unified live supply-chain evidence archive",
                actual=None,
                missing_prerequisites=["--live-evidence-archive or tmp/supply_chain_live_archive/supply_chain_live_evidence_archive.json"],
            )
        )
    elif not archive_path.is_file():
        live_checks.append(
            parse_check(
                name="live_supply_chain_archive",
                status="fail",
                expected="operator provides a unified live supply-chain evidence archive",
                actual={"path": str(archive_path), "exists": False},
            )
        )
    else:
        archive = load_json(archive_path)
        artifacts.append(artifact(archive_path, schema="supply_chain_live_evidence_archive/v1"))
        live_artifact_count = int(archive.get("live_artifact_count") or 0)
        live_checks.append(
            parse_check(
                name="live_supply_chain_archive",
                status="ok" if archive.get("status") == "ok" and live_artifact_count > 0 else "skipped" if archive.get("status") == "ok" else "fail",
                expected="operator provides a unified live supply-chain evidence archive",
                actual=archive,
                missing_prerequisites=["archive contains no live supply-chain artifacts"] if archive.get("status") == "ok" and live_artifact_count == 0 else None,
            )
        )
        foundation_present = isinstance((archive.get("live_artifacts") or {}).get("live_repo_side_supply_chain_foundation"), dict)
        live_checks.append(
            parse_check(
                name="live_supply_chain_foundation",
                status="ok" if foundation_present else "skipped",
                expected="current-worktree supply-chain gate is frozen into the live supply-chain archive",
                actual=(archive.get("live_artifacts") or {}).get("live_repo_side_supply_chain_foundation"),
                missing_prerequisites=["live_repo_side_supply_chain_foundation not present in supply-chain live archive"] if not foundation_present else None,
            )
        )
        rollout_present = any(
            isinstance((archive.get("live_artifacts") or {}).get(name), dict)
            for name in (
                "live_release_checksums",
                "live_provenance_report",
                "live_advisory_report",
            )
        )
        live_checks.append(
            parse_check(
                name="live_real_supply_chain_rollout",
                status="ok" if rollout_present else "skipped",
                expected="real release checksums, provenance, or advisory artifacts are archived",
                actual={
                    key: (archive.get("live_artifacts") or {}).get(key)
                    for key in (
                        "live_release_checksums",
                        "live_provenance_report",
                        "live_advisory_report",
                    )
                },
                missing_prerequisites=["real supply-chain rollout artifacts are still missing"] if not rollout_present else None,
            )
        )

    repo_side_status = "ok" if all(item["status"] == "ok" for item in repo_side_checks) else "fail"
    concrete_live = [item for item in live_checks if item["name"] == "live_supply_chain_archive"]
    rollout_live = [item for item in live_checks if item["name"] == "live_real_supply_chain_rollout"]
    live_status = (
        "fail" if any(item["status"] == "fail" for item in concrete_live)
        else "ok" if rollout_live and all(item["status"] == "ok" for item in rollout_live)
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
            "Repo-side checks prove local CI/release workflow coverage, local component inventory, and workflow-material provenance interfaces remain coherent.",
            "They do not prove a real GitHub Actions run, signed provenance/attestation, or live advisory scanner results on released artifacts.",
        ],
        "live_boundary": [
            "Live supply-chain readiness requires operator-provided GitHub Actions run evidence, release artifact checksums, provenance/attestation, and advisory/scanner outputs.",
            "When no live archive is supplied, this gate stays at live_status=skipped rather than claiming production-complete supply-chain evidence.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "supply_chain_evidence_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
