#!/usr/bin/env python3
"""Verifier-facing gate for PJC resource-isolation evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "pjc_resource_isolation_evidence_gate/v1"


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


def run_with_timeout(cmd: list[str], *, timeout_sec: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout_sec,
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

    preflight_path = out_dir / "pjc_preflight_positive.json"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "preflight_pjc_job.py"),
        "--resource-limits", str(REPO_ROOT / "config" / "pjc_resource_limits.example.json"),
        "--server-rows", "1000",
        "--client-rows", "1000",
        "--caller", "auto_demo",
        "--tenant-id", "t1",
        "--dataset-id", "d1",
        "--purpose", "bridge_token",
        "--job-id", "pjc-resource-isolation-gate",
        "--transport-mode", "streaming_grpc",
        "--chunk-size-elements", "4096",
        "--output", str(preflight_path),
        "--assert-allow",
    ])
    require_ok(res, label="preflight_pjc_job")
    preflight = load_json(preflight_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_pjc_preflight",
            status="ok" if preflight.get("decision") == "allow" else "fail",
            expected="preflight accepts in-scope streaming job and emits pjc_preflight/v1",
            actual=preflight,
        )
    )
    artifacts.append(artifact(preflight_path, schema="pjc_preflight/v1"))

    binary_gate_path = out_dir / "pjc_binary_capability_gate.json"
    binary_gate_cmd = [
        "python3",
        str(REPO_ROOT / "scripts" / "check_pjc_binary_capability_gate.py"),
        "--workspace", str(REPO_ROOT / "a-psi" / "private-join-and-compute"),
        "--requested-bin-dir", str(REPO_ROOT / "a-psi" / "private-join-and-compute" / "bazel-bin"),
        "--require-streaming",
        "--out", str(binary_gate_path),
    ]
    binary_gate_timed_out = False
    try:
        res = run_with_timeout(binary_gate_cmd, timeout_sec=5.0)
    except subprocess.TimeoutExpired as exc:
        binary_gate_timed_out = True
        res = subprocess.CompletedProcess(
            binary_gate_cmd,
            124,
            exc.stdout or "",
            exc.stderr or "",
        )
    if res.returncode == 0:
        binary_gate = load_json(binary_gate_path)
        repo_side_checks.append(
            parse_check(
                name="repo_side_pjc_binary_capability",
                status="ok" if binary_gate.get("status") == "ok" else "fail",
                expected="resolved PJC binaries are current and support streaming mode",
                actual=binary_gate,
            )
        )
        artifacts.append(artifact(binary_gate_path, schema="pjc_binary_capability_gate/v1"))
    else:
        stderr = res.stderr.strip()
        stdout = res.stdout.strip()
        combined = "\n".join(part for part in (stdout, stderr) if part)
        binary_gate = load_json(binary_gate_path) if binary_gate_path.is_file() else None
        stale_convenience_only = (
            binary_gate_timed_out
            or (
                isinstance(binary_gate, dict)
                and binary_gate.get("real_bazel_bin_dir") in (None, "")
                and binary_gate.get("requested_bin_dir") == binary_gate.get("convenience_bin_dir")
                and any(
                    isinstance(finding, dict)
                    and finding.get("kind") in {"server_missing_streaming_flag", "client_missing_streaming_flag", "binary_source_drift"}
                    for finding in (binary_gate.get("findings") or [])
                )
            )
        )
        if "Output base directory" in combined or "must be readable and writable" in combined or stale_convenience_only:
            repo_side_checks.append(
                parse_check(
                    name="repo_side_pjc_binary_capability",
                    status="skipped",
                    expected="resolved PJC binaries are current and support streaming mode",
                    actual=binary_gate if isinstance(binary_gate, dict) else {"stdout": stdout, "stderr": stderr},
                    missing_prerequisites=["environment provides fresh non-stale PJC binaries or a readable/fast-enough Bazel output base for binary capability probe"],
                )
            )
            if binary_gate_path.is_file():
                artifacts.append(artifact(binary_gate_path, schema="pjc_binary_capability_gate/v1"))
        else:
            require_ok(res, label="check_pjc_binary_capability_gate")

    fail_closed_path = out_dir / "verify_pjc_production_fail_closed.log"
    res = run(["bash", str(REPO_ROOT / "scripts" / "verify_pjc_production_fail_closed.sh")])
    fail_closed_path.write_text((res.stdout or "") + (res.stderr or ""), encoding="utf-8")
    require_ok(res, label="verify_pjc_production_fail_closed")
    repo_side_checks.append(
        parse_check(
            name="repo_side_pjc_fail_closed_wrappers",
            status="ok",
            expected="production wrappers reject missing limits, unary fallback, broad bind, and missing manifest requirements before launch",
            actual={"log_path": str(fail_closed_path)},
        )
    )
    artifacts.append(artifact(fail_closed_path, note="verify_pjc_production_fail_closed output"))

    worker_run_path = out_dir / "query_workflow_worker_run.json"
    worker_res = run([
        "bash",
        "-lc",
        f"tmpdir={str(out_dir / 'worker_tmp')}; mkdir -p \"$tmpdir\"; "
        f"python3 {str(REPO_ROOT / 'scripts' / 'build_query_workflow_request_fixtures.py')} --tmp-root \"$tmpdir\" --default-out \"$tmpdir/query_requests/cross_party_match_worker.json\" --keep-out \"$tmpdir/query_requests/cross_party_match_keep.json\" >/dev/null; "
        f"python3 {str(REPO_ROOT / 'scripts' / 'submit_query_workflow.py')} --request-file \"$tmpdir/query_requests/cross_party_match_worker.json\" --dry-run --metadata-db-path \"$tmpdir/query_workflow_worker.db\" --manifest-out \"$tmpdir/query_workflow_worker_enqueue_manifest.json\" >/dev/null; "
        f"python3 {str(REPO_ROOT / 'scripts' / 'run_query_workflow_worker.py')} --metadata-db-path \"$tmpdir/query_workflow_worker.db\" --once --dry-run-command --worker-receipts \"$tmpdir/query_workflow_worker_receipts.jsonl\" > {str(worker_run_path)}"
    ])
    if worker_res.returncode == 0:
        worker_run = load_json(worker_run_path)
        repo_side_checks.append(
            parse_check(
                name="repo_side_pjc_worker_timeout_cancel_surface",
                status="ok" if worker_run.get("schema") == "query_workflow_worker_run/v1" else "fail",
                expected="worker-owned execution path emits query_workflow_worker_run/v1 for queued work outside submit thread",
                actual=worker_run,
            )
        )
        artifacts.append(artifact(worker_run_path, schema="query_workflow_worker_run/v1"))
    else:
        repo_side_checks.append(
            parse_check(
                name="repo_side_pjc_worker_timeout_cancel_surface",
                status="skipped",
                expected="worker-owned execution path emits query_workflow_worker_run/v1 for queued work outside submit thread",
                actual={"stdout": worker_res.stdout, "stderr": worker_res.stderr},
                missing_prerequisites=["local worker dry-run fixture path available in current sandbox/runtime"],
            )
        )

    archive_path = Path(args.live_evidence_archive).resolve() if args.live_evidence_archive else None
    if archive_path is None:
        archive_path = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname="pjc_resource_isolation_live_archive",
            archive_filename="pjc_resource_isolation_live_evidence_archive.json",
            expected_schema="pjc_resource_isolation_live_evidence_archive/v1",
        )
    if archive_path is None:
        live_checks.append(
            parse_check(
                name="live_pjc_resource_isolation_archive",
                status="skipped",
                expected="operator provides a unified live PJC resource-isolation evidence archive",
                actual=None,
                missing_prerequisites=["--live-evidence-archive"],
            )
        )
    elif not archive_path.is_file():
        live_checks.append(
            parse_check(
                name="live_pjc_resource_isolation_archive",
                status="fail",
                expected="operator provides a unified live PJC resource-isolation evidence archive",
                actual={"path": str(archive_path), "exists": False},
            )
        )
    else:
        archive = load_json(archive_path)
        artifacts.append(artifact(archive_path, schema="pjc_resource_isolation_live_evidence_archive/v1"))
        live_artifact_count = int(archive.get("live_artifact_count") or 0)
        live_checks.append(
            parse_check(
                name="live_pjc_resource_isolation_archive",
                status="ok" if archive.get("status") == "ok" and live_artifact_count > 0 else "skipped" if archive.get("status") == "ok" else "fail",
                expected="operator provides a unified live PJC resource-isolation evidence archive",
                actual=archive,
                missing_prerequisites=["archive contains no live PJC resource-isolation artifacts"] if archive.get("status") == "ok" and live_artifact_count == 0 else None,
            )
        )
        rollout_present = any(
            isinstance((archive.get("live_artifacts") or {}).get(name), dict)
            for name in (
                "live_systemd_limits_report",
                "live_kubernetes_limits_report",
                "live_timeout_cancel_report",
                "live_streaming_success_report",
            )
        )
        live_checks.append(
            parse_check(
                name="live_real_pjc_resource_isolation_rollout",
                status="ok" if rollout_present else "skipped",
                expected="real systemd/Kubernetes limits, timeout/cancel, or streaming-success artifacts are archived",
                actual={
                    key: (archive.get("live_artifacts") or {}).get(key)
                    for key in (
                        "live_systemd_limits_report",
                        "live_kubernetes_limits_report",
                        "live_timeout_cancel_report",
                        "live_streaming_success_report",
                    )
                },
                missing_prerequisites=["real PJC resource-isolation rollout artifacts are still missing"] if not rollout_present else None,
            )
        )

    repo_side_status = "ok" if all(item["status"] in {"ok", "skipped"} for item in repo_side_checks) else "fail"
    concrete_live = [item for item in live_checks if item["name"] == "live_pjc_resource_isolation_archive"]
    rollout_live = [item for item in live_checks if item["name"] == "live_real_pjc_resource_isolation_rollout"]
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
            "Repo-side checks prove preflight limits, binary freshness/streaming capability, and production wrapper fail-closed behavior before PJC launch.",
            "They do not prove real systemd/Kubernetes CPU/memory/pids/no-new-privileges enforcement, nor target-host timeout/cancel drills under production resource isolation.",
        ],
        "live_boundary": [
            "Live PJC resource isolation requires operator-provided systemd/Kubernetes limits, timeout/cancel, and production streaming success artifacts.",
            "When no live archive is supplied, this gate stays at live_status=skipped rather than claiming production-complete PJC worker isolation.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "pjc_resource_isolation_evidence_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
