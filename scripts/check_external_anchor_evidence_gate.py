#!/usr/bin/env python3
"""Verifier-facing gate for external immutable audit anchor evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "external_anchor_evidence_gate/v1"


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

    report_path = out_dir / "external_audit_anchor_report_rekor_planned.json"
    cmd = [
        "python3",
        str(REPO_ROOT / "scripts" / "publish_external_audit_anchor.py"),
        "--anchor-file", str(REPO_ROOT / "tmp" / "external_audit_anchor_evidence" / "archive" / "audit_chain_anchor.jsonl"),
        "--external-ledger", "https://rekor.sigstore.dev",
        "--sink-kind", "rekor",
        "--output", str(report_path),
    ]
    res = run(cmd)
    if res.returncode == 0 and report_path.is_file():
        planned_rekor = load_json(report_path)
        repo_side_checks.append(
            parse_check(
                name="repo_side_rekor_planned_report",
                status="ok" if planned_rekor.get("schema") == "external_audit_anchor_report/v1" else "fail",
                expected="publisher emits a schema-valid planned Rekor report without live credentials",
                actual=planned_rekor,
            )
        )
        artifacts.append(artifact(report_path, schema="external_audit_anchor_report/v1"))
    else:
        repo_side_checks.append(
            parse_check(
                name="repo_side_rekor_planned_report",
                status="fail",
                expected="publisher emits a schema-valid planned Rekor report without live credentials",
                actual={"stdout": res.stdout, "stderr": res.stderr, "exit_code": res.returncode},
            )
        )

    verify_script = REPO_ROOT / "scripts" / "verify_external_audit_anchor_gate.sh"
    verify_res = run(["bash", str(verify_script), "--keep-out-dir"])
    repo_side_checks.append(
        parse_check(
            name="repo_side_anchor_gate_verify_script",
            status="ok" if verify_res.returncode == 0 else "fail",
            expected="repo-side external anchor gate negatives and schema checks pass",
            actual={"stdout_tail": verify_res.stdout.strip().splitlines()[-1] if verify_res.stdout.strip() else "", "stderr": verify_res.stderr.strip()},
        )
    )

    archive_path = Path(args.live_evidence_archive).resolve() if args.live_evidence_archive else None
    if archive_path is None:
        archive_path = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname="external_anchor_live_archive",
            archive_filename="external_anchor_live_evidence_archive.json",
            expected_schema="external_anchor_live_evidence_archive/v1",
        )
    if archive_path is None:
        live_checks.append(
            parse_check(
                name="live_external_anchor_archive",
                status="skipped",
                expected="operator provides a live external-anchor evidence archive",
                actual=None,
                missing_prerequisites=["--live-evidence-archive"],
            )
        )
    elif not archive_path.is_file():
        live_checks.append(
            parse_check(
                name="live_external_anchor_archive",
                status="fail",
                expected="operator provides a live external-anchor evidence archive",
                actual={"path": str(archive_path), "exists": False},
            )
        )
    else:
        archive = load_json(archive_path)
        artifacts.append(artifact(archive_path, schema="external_anchor_live_evidence_archive/v1"))
        live_artifact_count = int(archive.get("live_artifact_count") or 0)
        live_checks.append(
            parse_check(
                name="live_external_anchor_archive",
                status="ok" if archive.get("status") == "ok" and live_artifact_count > 0 else "skipped" if archive.get("status") == "ok" else "fail",
                expected="operator provides a live external-anchor evidence archive",
                actual=archive,
                missing_prerequisites=["archive contains no live anchor execution artifacts"] if archive.get("status") == "ok" and live_artifact_count == 0 else None,
            )
        )

    repo_side_status = "ok" if all(item["status"] == "ok" for item in repo_side_checks) else "fail"
    concrete_live = [item for item in live_checks if item["name"] == "live_external_anchor_archive"]
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
            "Repo-side checks prove the publisher, strict release-gate semantics, planned-mode reports, and negative anchor paths remain coherent.",
            "They do not prove a real immutable external sink accepted and retained the anchor records.",
        ],
        "live_boundary": [
            "Live external-anchor readiness requires operator-provided uploaded/verified evidence from S3 Object Lock, Rekor, or another immutable sink.",
            "When no live archive is supplied, this gate stays at live_status=skipped rather than claiming immutable external anchoring is complete.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "external_anchor_evidence_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
