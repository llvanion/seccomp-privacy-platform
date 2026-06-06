#!/usr/bin/env python3
"""Verifier-facing gate for query-workflow deployment evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "query_workflow_deployment_evidence_gate/v1"


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

    durability_path = out_dir / "query_workflow_durability_check.json"
    res = run(["python3", str(REPO_ROOT / "scripts" / "check_query_workflow_durability.py"), "--out", str(durability_path)])
    require_ok(res, label="check_query_workflow_durability")
    durability = load_json(durability_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_query_workflow_durability",
            status="ok" if durability.get("status") == "ok" else "fail",
            expected="DB-backed query workflow ownership, cancel, timeout, restart-steal, and duplicate denial stay coherent",
            actual=durability,
        )
    )
    artifacts.append(artifact(durability_path, schema="query_workflow_durability_check/v1"))

    source_truthfulness_path = out_dir / "source_truthfulness_smoke.json"
    res = run(["python3", str(REPO_ROOT / "scripts" / "check_source_attestation_smoke.py"), "--output", str(source_truthfulness_path)])
    require_ok(res, label="check_source_attestation_smoke")
    source_truthfulness = load_json(source_truthfulness_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_source_truthfulness_gate",
            status="ok" if source_truthfulness.get("status") == "ok" else "fail",
            expected="typed source attestation, signoff, strict-mode, and hash-binding negative cases are enforced",
            actual=source_truthfulness,
        )
    )
    artifacts.append(artifact(source_truthfulness_path, schema="source_truthfulness_smoke/v1"))

    source_truthfulness_pipeline_path = out_dir / "source_attestation_pipeline_smoke.json"
    res = run(["python3", str(REPO_ROOT / "scripts" / "check_source_attestation_pipeline_smoke.py"), "--output", str(source_truthfulness_pipeline_path)])
    require_ok(res, label="check_source_attestation_pipeline_smoke")
    source_truthfulness_pipeline = load_json(source_truthfulness_pipeline_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_source_truthfulness_pipeline",
            status="ok" if source_truthfulness_pipeline.get("status") == "ok" else "fail",
            expected="source attestation is bound end-to-end through pipeline, release gate, audit, and release governance artifacts",
            actual=source_truthfulness_pipeline,
        )
    )
    artifacts.append(artifact(source_truthfulness_pipeline_path, schema="source_attestation_pipeline_smoke/v1"))

    worker_run_path = out_dir / "query_workflow_worker_run.json"
    res = run([
        "bash",
        "-lc",
        f"tmpdir={str(out_dir / 'worker_tmp')}; mkdir -p \"$tmpdir\"; "
        f"python3 {str(REPO_ROOT / 'scripts' / 'build_query_workflow_request_fixtures.py')} --tmp-root \"$tmpdir\" --default-out \"$tmpdir/query_requests/cross_party_match_worker.json\" --keep-out \"$tmpdir/query_requests/cross_party_match_keep.json\" >/dev/null; "
        f"python3 {str(REPO_ROOT / 'scripts' / 'submit_query_workflow.py')} --request-file \"$tmpdir/query_requests/cross_party_match_worker.json\" --enqueue --metadata-db-path \"$tmpdir/query_workflow_worker.db\" --manifest-out \"$tmpdir/query_workflow_worker_enqueue_manifest.json\" >/dev/null; "
        f"python3 {str(REPO_ROOT / 'scripts' / 'run_query_workflow_worker.py')} --metadata-db-path \"$tmpdir/query_workflow_worker.db\" --once --dry-run-command --worker-receipts \"$tmpdir/query_workflow_worker_receipts.jsonl\" > {str(worker_run_path)}"
    ])
    if res.returncode == 0:
        worker_run = load_json(worker_run_path)
        repo_side_checks.append(
            parse_check(
                name="repo_side_query_workflow_worker",
                status="ok" if worker_run.get("schema") == "query_workflow_worker_run/v1" else "fail",
                expected="local worker path can claim and emit worker-run evidence outside submit/API thread",
                actual=worker_run,
            )
        )
        artifacts.append(artifact(worker_run_path, schema="query_workflow_worker_run/v1"))
    else:
        repo_side_checks.append(
            parse_check(
                name="repo_side_query_workflow_worker",
                status="skipped",
                expected="local worker path can claim and emit worker-run evidence outside submit/API thread",
                actual={"stdout": res.stdout, "stderr": res.stderr},
                missing_prerequisites=["current sandbox/runtime permits local worker dry-run fixture path"],
            )
        )

    archive_path = Path(args.live_evidence_archive).resolve() if args.live_evidence_archive else None
    if archive_path is None:
        archive_path = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname="query_workflow_live_archive",
            archive_filename="query_workflow_live_evidence_archive.json",
            expected_schema="query_workflow_live_evidence_archive/v1",
        )
    if archive_path is None:
        live_checks.append(
            parse_check(
                name="live_query_workflow_evidence_archive",
                status="skipped",
                expected="operator provides a unified live query-workflow deployment evidence archive",
                actual=None,
                missing_prerequisites=["--live-evidence-archive"],
            )
        )
    elif not archive_path.is_file():
        live_checks.append(
            parse_check(
                name="live_query_workflow_evidence_archive",
                status="fail",
                expected="operator provides a unified live query-workflow deployment evidence archive",
                actual={"path": str(archive_path), "exists": False},
            )
        )
    else:
        archive = load_json(archive_path)
        artifacts.append(artifact(archive_path, schema="query_workflow_live_evidence_archive/v1"))
        live_artifact_count = int(archive.get("live_artifact_count") or 0)
        live_checks.append(
            parse_check(
                name="live_query_workflow_evidence_archive",
                status="ok" if archive.get("status") == "ok" and live_artifact_count > 0 else "skipped" if archive.get("status") == "ok" else "fail",
                expected="operator provides a unified live query-workflow deployment evidence archive",
                actual=archive,
                missing_prerequisites=["archive contains no live query-workflow deployment artifacts"] if archive.get("status") == "ok" and live_artifact_count == 0 else None,
            )
        )
        foundation_present = isinstance((archive.get("live_artifacts") or {}).get("live_repo_side_query_workflow_foundation"), dict)
        live_checks.append(
            parse_check(
                name="live_query_workflow_foundation",
                status="ok" if foundation_present else "skipped",
                expected="current-worktree query-workflow durability/worker baseline is frozen into the live query-workflow archive",
                actual=(archive.get("live_artifacts") or {}).get("live_repo_side_query_workflow_foundation"),
                missing_prerequisites=["live_repo_side_query_workflow_foundation not present in query-workflow live archive"] if not foundation_present else None,
            )
        )
        rollout_present = any(
            isinstance((archive.get("live_artifacts") or {}).get(name), dict)
            for name in (
                "live_multi_worker_retry_report",
                "live_restart_drill_report",
                "live_postgres_ha_report",
            )
        )
        live_checks.append(
            parse_check(
                name="live_real_query_workflow_rollout",
                status="ok" if rollout_present else "skipped",
                expected="real worker retry/restart/HA artifacts are archived",
                actual={
                    key: (archive.get("live_artifacts") or {}).get(key)
                    for key in (
                        "live_multi_worker_retry_report",
                        "live_restart_drill_report",
                        "live_postgres_ha_report",
                    )
                },
                missing_prerequisites=["real query-workflow rollout artifacts are still missing"] if not rollout_present else None,
            )
        )

    repo_side_status = "ok" if all(item["status"] in {"ok", "skipped"} for item in repo_side_checks) else "fail"
    concrete_live = [item for item in live_checks if item["name"] == "live_query_workflow_evidence_archive"]
    rollout_live = [item for item in live_checks if item["name"] == "live_real_query_workflow_rollout"]
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
            "Repo-side checks prove DB-backed execution ownership, cancellation, timeout, restart-steal semantics, and worker-run evidence for the local path.",
            "They do not prove supervised deployed workers, target-host restart drills, multi-worker retry policy, or the same behavior against live PostgreSQL/HA.",
        ],
        "live_boundary": [
            "Live query-workflow readiness requires operator-provided worker supervision, restart, retry, and PostgreSQL/HA artifacts.",
            "When no live archive is supplied, this gate stays at live_status=skipped rather than claiming production-complete query-workflow deployment durability.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "query_workflow_deployment_evidence_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
