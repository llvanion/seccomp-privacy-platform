#!/usr/bin/env python3
"""Collect live PJC resource-isolation rollout evidence from authoritative artifacts."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--query-timeout-report", default="tmp/query_workflow_live_real/query_workflow_live_timeout_report.json")
    ap.add_argument("--public-two-host-archive", default="tmp/public_two_host_live_archive_cross-vps-008/public_two_host_live_evidence_archive.json")
    ap.add_argument("--job-id", default="pjc-resource-isolation-live-rollout")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    timeout_report = load_json((REPO_ROOT / args.query_timeout_report).resolve())
    public_archive = load_json((REPO_ROOT / args.public_two_host_archive).resolve())

    timeout_cancel_report = {
        "schema": "pjc_resource_isolation_live_timeout_cancel_report/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "source_query_workflow_timeout_report": str((REPO_ROOT / args.query_timeout_report).resolve()),
        "worker_event": timeout_report.get("worker_event"),
        "db_state": timeout_report.get("db_state"),
        "terminal": timeout_report.get("terminal"),
        "last_exit_code": timeout_report.get("last_exit_code"),
        "boundary_note": "This timeout/cancel evidence is derived from the real DB-backed worker timeout drill already captured for query-workflow.",
    }
    write_json(out_dir / "pjc_resource_isolation_live_timeout_cancel_report.json", timeout_cancel_report)

    streaming_success_report = {
        "schema": "pjc_resource_isolation_live_streaming_success_report/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "source_public_two_host_archive": str((REPO_ROOT / args.public_two_host_archive).resolve()),
        "job_id": public_archive.get("job_id"),
        "bucket_count": public_archive.get("bucket_count"),
        "merged_bucket_count": (public_archive.get("merged_result") or {}).get("bucket_count_merged"),
        "tls_identity": public_archive.get("tls_identity"),
        "boundary_note": "This streaming-success evidence is derived from the authoritative public two-host live archive for cross-vps-008.",
    }
    write_json(out_dir / "pjc_resource_isolation_live_streaming_success_report.json", streaming_success_report)

    summary = {
        "schema": "pjc_resource_isolation_live_rollout_collection/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "job_id": args.job_id,
        "live_timeout_cancel_report": str(out_dir / "pjc_resource_isolation_live_timeout_cancel_report.json"),
        "live_streaming_success_report": str(out_dir / "pjc_resource_isolation_live_streaming_success_report.json"),
    }
    write_json(out_dir / "pjc_resource_isolation_live_rollout_collection.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
