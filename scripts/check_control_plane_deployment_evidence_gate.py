#!/usr/bin/env python3
"""Verifier-facing gate for control-plane/operator-readiness deployment evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "control_plane_deployment_evidence_gate/v1"
DEFAULT_LIVE_ARCHIVE = REPO_ROOT / "tmp" / "control_plane_live_archive" / "control_plane_live_evidence_archive.json"


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


def latest_tmp_report(filename: str) -> Path | None:
    matches = sorted((REPO_ROOT / "tmp").rglob(filename))
    return matches[-1] if matches else None


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

    operator_readiness_path = latest_tmp_report("operator_readiness.json") or (out_dir / "operator_readiness.json")
    if operator_readiness_path.is_file():
        operator_readiness = load_json(operator_readiness_path)
    else:
        res = run(["python3", str(REPO_ROOT / "scripts" / "check_operator_readiness.py"), "--out", str(operator_readiness_path)])
        require_ok(res, label="check_operator_readiness")
        operator_readiness = load_json(operator_readiness_path)
    readiness_checks = {
        str(item.get("name") or ""): str(item.get("status") or "")
        for item in (operator_readiness.get("checks") or [])
        if isinstance(item, dict)
    }
    operator_readiness_ok = (
        readiness_checks.get("config_example_files") == "pass"
        and readiness_checks.get("bridge_example_data") == "pass"
    )
    repo_side_checks.append(
        parse_check(
            name="repo_side_operator_readiness",
            status="ok" if operator_readiness_ok else "fail",
            expected="deployment examples and bridge fixtures remain operator-ready; broad pre_release coverage is reported as context, not as the sole control-plane blocker",
            actual=operator_readiness,
        )
    )
    artifacts.append(artifact(operator_readiness_path, schema="operator_readiness/v1"))

    malformed_path = latest_tmp_report("http_malformed_input_gate.json") or (out_dir / "http_malformed_input_gate.json")
    if malformed_path.is_file():
        malformed = load_json(malformed_path)
    else:
        res = run(["python3", str(REPO_ROOT / "scripts" / "check_http_malformed_input_gate.py"), "--output", str(malformed_path)])
        require_ok(res, label="check_http_malformed_input_gate")
        malformed = load_json(malformed_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_http_malformed_input_gate",
            status="ok" if (malformed.get("summary") or {}).get("status") == "ok" else "fail",
            expected="record-recovery HTTP boundary rejects malformed, spoofed, and tampered inputs",
            actual=malformed,
        )
    )
    artifacts.append(artifact(malformed_path, schema="http_malformed_input_gate/v1"))

    deepening_path = latest_tmp_report("control_plane_deepening.json") or (out_dir / "control_plane_deepening_report.json")
    if deepening_path.is_file():
        deepening = load_json(deepening_path)
    else:
        res = run(["python3", str(REPO_ROOT / "scripts" / "materialize_control_plane_deepening.py"), "--db-path", str(out_dir / "control_plane.db"), "--output", str(deepening_path)])
        require_ok(res, label="materialize_control_plane_deepening")
        deepening = load_json(deepening_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_control_plane_deepening",
            status="ok" if (deepening.get("summary") or {}).get("status") == "ok" else "fail",
            expected="control-plane derived read models can be materialized and stay structurally coherent",
            actual=deepening,
        )
    )
    artifacts.append(artifact(deepening_path, schema="control_plane_deepening_report/v1"))

    # Minimal metadata API caller-safe redaction proof via the existing contract smoke output if available.
    contract_redaction = latest_tmp_report("metadata_api_public_redaction_check.json")
    if contract_redaction is not None and contract_redaction.is_file():
        redaction = load_json(contract_redaction)
        repo_side_checks.append(
            parse_check(
                name="repo_side_metadata_api_redaction",
                status="ok" if redaction.get("status") == "ok" else "fail",
                expected="caller-safe metadata API responses remain redacted for normal callers",
                actual=redaction,
            )
        )
        artifacts.append(artifact(contract_redaction, schema="metadata_api_public_redaction_check/v1"))
    else:
        repo_side_checks.append(
            parse_check(
                name="repo_side_metadata_api_redaction",
                status="skipped",
                expected="caller-safe metadata API responses remain redacted for normal callers",
                actual=None,
                missing_prerequisites=["tmp/metadata_api_public_redaction_check.json from contract smoke"],
            )
        )

    archive_path = Path(args.live_evidence_archive).resolve() if args.live_evidence_archive else None
    if archive_path is None:
        archive_path = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname="control_plane_live_archive",
            archive_filename="control_plane_live_evidence_archive.json",
            expected_schema="control_plane_live_evidence_archive/v1",
        )
        if archive_path is None and DEFAULT_LIVE_ARCHIVE.is_file():
            archive_path = DEFAULT_LIVE_ARCHIVE.resolve()
    if archive_path is None:
        live_checks.append(
            parse_check(
                name="live_control_plane_evidence_archive",
                status="skipped",
                expected="operator provides a unified live control-plane deployment evidence archive",
                actual=None,
                missing_prerequisites=["--live-evidence-archive or tmp/control_plane_live_archive/control_plane_live_evidence_archive.json"],
            )
        )
    elif not archive_path.is_file():
        live_checks.append(
            parse_check(
                name="live_control_plane_evidence_archive",
                status="fail",
                expected="operator provides a unified live control-plane deployment evidence archive",
                actual={"path": str(archive_path), "exists": False},
            )
        )
    else:
        archive = load_json(archive_path)
        artifacts.append(artifact(archive_path, schema="control_plane_live_evidence_archive/v1"))
        live_artifact_count = int(archive.get("live_artifact_count") or 0)
        live_checks.append(
            parse_check(
                name="live_control_plane_evidence_archive",
                status="ok" if archive.get("status") == "ok" and live_artifact_count > 0 else "skipped" if archive.get("status") == "ok" else "fail",
                expected="operator provides a unified live control-plane deployment evidence archive",
                actual=archive,
                missing_prerequisites=["archive contains no live control-plane deployment artifacts"] if archive.get("status") == "ok" and live_artifact_count == 0 else None,
            )
        )
        foundation_present = isinstance((archive.get("live_artifacts") or {}).get("live_repo_side_control_plane_foundation"), dict)
        live_checks.append(
            parse_check(
                name="live_control_plane_foundation",
                status="ok" if foundation_present else "skipped",
                expected="current-worktree control-plane readiness/malformed-input/read-model foundation is frozen into the live control-plane archive",
                actual=(archive.get("live_artifacts") or {}).get("live_repo_side_control_plane_foundation"),
                missing_prerequisites=["live_repo_side_control_plane_foundation not present in control-plane live archive"] if not foundation_present else None,
            )
        )
        rollout_present = any(
            isinstance((archive.get("live_artifacts") or {}).get(name), dict)
            for name in (
                "live_operator_runbook_report",
                "live_metadata_api_report",
                "live_platform_api_report",
                "live_reverse_proxy_report",
            )
        )
        live_checks.append(
            parse_check(
                name="live_real_control_plane_rollout",
                status="ok" if rollout_present else "skipped",
                expected="real runbook exercise, metadata/platform API, or reverse-proxy artifacts are archived",
                actual={
                    key: (archive.get("live_artifacts") or {}).get(key)
                    for key in (
                        "live_operator_runbook_report",
                        "live_metadata_api_report",
                        "live_platform_api_report",
                        "live_reverse_proxy_report",
                    )
                },
                missing_prerequisites=["real control-plane rollout artifacts are still missing"] if not rollout_present else None,
            )
        )

    repo_side_status = "ok" if all(item["status"] in {"ok", "skipped"} for item in repo_side_checks) else "fail"
    concrete_live = [item for item in live_checks if item["name"] == "live_control_plane_evidence_archive"]
    rollout_live = [item for item in live_checks if item["name"] == "live_real_control_plane_rollout"]
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
            "Repo-side checks prove deployment examples, malformed-input rejection, control-plane read models, and metadata API redaction remain coherent.",
            "They do not prove live reverse proxying, live metadata/platform APIs, or operator-run deployment exercises on target hosts.",
        ],
        "live_boundary": [
            "Live control-plane readiness requires operator-provided metadata/platform API, reverse proxy, and runbook exercise artifacts.",
            "When no live archive is supplied, this gate stays at live_status=skipped rather than claiming production-complete control-plane deployment.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "control_plane_deployment_evidence_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
