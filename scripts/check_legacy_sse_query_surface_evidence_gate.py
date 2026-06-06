#!/usr/bin/env python3
"""Verifier-facing gate for legacy-SSE retired query-surface evidence."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "legacy_sse_query_surface_evidence_gate/v1"


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

    legacy_path = out_dir / "legacy_sse_production_gate.json"
    from subprocess import run, PIPE
    res = run(
        ["python3", str(REPO_ROOT / "scripts" / "check_legacy_sse_production_gate.py"), "--out", str(legacy_path)],
        cwd=str(REPO_ROOT),
        text=True,
        stdout=PIPE,
        stderr=PIPE,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"check_legacy_sse_production_gate failed ({res.returncode})\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")
    legacy = load_json(legacy_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_legacy_sse_retirement_gate",
            status="ok" if legacy.get("status") == "ok" else "fail",
            expected="legacy SSE WebSocket is retired under production mode and wide bind remains demo-only",
            actual=legacy,
        )
    )
    artifacts.append(artifact(legacy_path, schema="legacy_sse_production_gate/v1"))

    archive_path = Path(args.live_evidence_archive).resolve() if args.live_evidence_archive else None
    if archive_path is None:
        archive_path = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname="legacy_sse_live_archive",
            archive_filename="legacy_sse_live_evidence_archive.json",
            expected_schema="legacy_sse_live_evidence_archive/v1",
        )
    if archive_path is None:
        live_checks.append(
            parse_check(
                name="live_legacy_sse_evidence_archive",
                status="skipped",
                expected="operator provides a unified live legacy-SSE query-surface evidence archive",
                actual=None,
                missing_prerequisites=["--live-evidence-archive"],
            )
        )
    elif not archive_path.is_file():
        live_checks.append(
            parse_check(
                name="live_legacy_sse_evidence_archive",
                status="fail",
                expected="operator provides a unified live legacy-SSE query-surface evidence archive",
                actual={"path": str(archive_path), "exists": False},
            )
        )
    else:
        archive = load_json(archive_path)
        artifacts.append(artifact(archive_path, schema="legacy_sse_live_evidence_archive/v1"))
        live_artifact_count = int(archive.get("live_artifact_count") or 0)
        live_checks.append(
            parse_check(
                name="live_legacy_sse_evidence_archive",
                status="ok" if archive.get("status") == "ok" and live_artifact_count > 0 else "skipped" if archive.get("status") == "ok" else "fail",
                expected="operator provides a unified live legacy-SSE query-surface evidence archive",
                actual=archive,
                missing_prerequisites=["archive contains no live legacy-SSE deployment artifacts"] if archive.get("status") == "ok" and live_artifact_count == 0 else None,
            )
        )

    repo_side_status = "ok" if all(item["status"] == "ok" for item in repo_side_checks) else "fail"
    concrete_live = [item for item in live_checks if item["name"] == "live_legacy_sse_evidence_archive"]
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
            "Repo-side checks prove the historical SSE WebSocket is retired under production mode and cannot be reintroduced as a broad-bind query surface by accident.",
            "They do not prove deployed hosts, ingress, or socket inventory actually exclude that legacy listener from production traffic paths.",
        ],
        "live_boundary": [
            "Live legacy-SSE closure requires operator-provided route, socket, and ingress evidence that production traffic uses the query workflow and bridge APIs instead of the retired WebSocket.",
            "When no live archive is supplied, this gate stays at live_status=skipped rather than claiming the retired legacy SSE surface is absent from production deployment.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "legacy_sse_query_surface_evidence_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
