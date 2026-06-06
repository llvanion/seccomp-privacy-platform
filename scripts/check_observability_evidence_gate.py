#!/usr/bin/env python3
"""Verifier-facing gate for observability / alerting evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "observability_evidence_gate/v1"
DEFAULT_LIVE_ARCHIVE = REPO_ROOT / "tmp" / "observability_live_archive" / "observability_live_evidence_archive.json"


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

    topology_path = out_dir / "observability_topology_report.json"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "render_observability_topology.py"),
        "--output", str(topology_path),
    ])
    require_ok(res, label="render_observability_topology")
    topology = load_json(topology_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_observability_topology",
            status="ok" if (topology.get("summary") or {}).get("status") == "ok" else "fail",
            expected="Grafana/Tempo/Prometheus topology stays structurally coherent",
            actual=topology,
        )
    )
    artifacts.append(artifact(topology_path, schema="observability_topology_report/v1"))

    smoke_dir = out_dir / "alert_webhook_smoke"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "check_alert_webhook_smoke.py"),
        "--out-dir", str(smoke_dir),
    ])
    if res.returncode == 0:
        heartbeat_log = smoke_dir / "alert_daemon_heartbeat.jsonl"
        repo_side_checks.append(
            parse_check(
                name="repo_side_alert_webhook_smoke",
                status="ok",
                expected="repo-side alert webhook + daemon transitions succeed for slack and alertmanager formats",
                actual={"out_dir": str(smoke_dir), "heartbeat_log": str(heartbeat_log)},
            )
        )
        artifacts.append(artifact(heartbeat_log, schema="alert_daemon_heartbeat/v1"))
    else:
        stderr = res.stderr.strip()
        if "PermissionError" in stderr and "socket" in stderr:
            repo_side_checks.append(
                parse_check(
                    name="repo_side_alert_webhook_smoke",
                    status="skipped",
                    expected="repo-side alert webhook + daemon transitions succeed for slack and alertmanager formats",
                    actual={"stderr": stderr},
                    missing_prerequisites=["environment permits loopback listener sockets for alert webhook smoke"],
                )
            )
        else:
            require_ok(res, label="check_alert_webhook_smoke")

    archive_path = Path(args.live_evidence_archive).resolve() if args.live_evidence_archive else None
    if archive_path is None:
        archive_path = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname="observability_live_archive",
            archive_filename="observability_live_evidence_archive.json",
            expected_schema="observability_live_evidence_archive/v1",
        )
        if archive_path is None and DEFAULT_LIVE_ARCHIVE.is_file():
            archive_path = DEFAULT_LIVE_ARCHIVE.resolve()
    if archive_path is None:
        live_checks.append(
            parse_check(
                name="live_observability_evidence_archive",
                status="skipped",
                expected="operator provides a unified observability live evidence archive",
                actual=None,
                missing_prerequisites=["--live-evidence-archive or tmp/observability_live_archive/observability_live_evidence_archive.json"],
            )
        )
    elif not archive_path.is_file():
        live_checks.append(
            parse_check(
                name="live_observability_evidence_archive",
                status="fail",
                expected="operator provides a unified observability live evidence archive",
                actual={"path": str(archive_path), "exists": False},
            )
        )
    else:
        archive = load_json(archive_path)
        artifacts.append(artifact(archive_path, schema="observability_live_evidence_archive/v1"))
        live_artifact_count = int(archive.get("live_artifact_count") or 0)
        live_checks.append(
            parse_check(
                name="live_observability_evidence_archive",
                status="ok" if archive.get("status") == "ok" and live_artifact_count > 0 else "skipped" if archive.get("status") == "ok" else "fail",
                expected="operator provides a unified observability live evidence archive",
                actual=archive,
                missing_prerequisites=["archive contains no live observability artifacts"] if archive.get("status") == "ok" and live_artifact_count == 0 else None,
            )
        )
        foundation_present = isinstance((archive.get("live_artifacts") or {}).get("live_repo_side_observability_foundation"), dict)
        live_checks.append(
            parse_check(
                name="live_observability_foundation",
                status="ok" if foundation_present else "skipped",
                expected="current-worktree observability topology/heartbeat baseline is frozen into the live observability archive",
                actual=(archive.get("live_artifacts") or {}).get("live_repo_side_observability_foundation"),
                missing_prerequisites=["live_repo_side_observability_foundation not present in observability live archive"] if not foundation_present else None,
            )
        )
        rollout_present = any(
            isinstance((archive.get("live_artifacts") or {}).get(name), dict)
            for name in (
                "live_tempo_push_report",
                "live_grafana_render_report",
                "live_webhook_report",
            )
        )
        live_checks.append(
            parse_check(
                name="live_real_observability_rollout",
                status="ok" if rollout_present else "skipped",
                expected="real Tempo/Grafana/webhook artifacts are archived",
                actual={
                    key: (archive.get("live_artifacts") or {}).get(key)
                    for key in (
                        "live_tempo_push_report",
                        "live_grafana_render_report",
                        "live_webhook_report",
                    )
                },
                missing_prerequisites=["real observability rollout artifacts are still missing"] if not rollout_present else None,
            )
        )

    repo_side_status = "ok" if all(item["status"] in {"ok", "skipped"} for item in repo_side_checks) else "fail"
    concrete_live = [item for item in live_checks if item["name"] == "live_observability_evidence_archive"]
    rollout_live = [item for item in live_checks if item["name"] == "live_real_observability_rollout"]
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
            "Repo-side checks prove the checked-in observability topology and alerting daemon/webhook behavior remain coherent.",
            "They do not prove a real Tempo/Grafana/Prometheus deployment, non-empty dashboards, or webhook delivery to operator endpoints.",
        ],
        "live_boundary": [
            "Live observability readiness requires operator-provided Tempo push, Grafana render, webhook, and heartbeat artifacts.",
            "When no live archive is supplied, this gate stays at live_status=skipped rather than claiming production-complete observability.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "observability_evidence_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
