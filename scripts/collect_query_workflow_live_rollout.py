#!/usr/bin/env python3
"""Collect live query-workflow rollout evidence from a running operator host."""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"

import sys

sys.path.insert(0, str(SCRIPTS))

from metadata_db import apply_migrations, connect_db  # noqa: E402
from query_workflow_execution_store import lease_owner, load_execution  # noqa: E402
import run_query_workflow_worker as qw_worker  # noqa: E402


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_checked(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"command failed ({res.returncode}): {' '.join(cmd)}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
        )
    return res


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--metadata-db-path", default="query_workflow_live.db")
    ap.add_argument("--job-id", default="query-workflow-live-rollout")
    return ap


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_db_path = Path(args.metadata_db_path)
    db_path = raw_db_path.resolve() if raw_db_path.is_absolute() else (out_dir / raw_db_path).resolve()

    run_checked(["python3", str(SCRIPTS / "init_metadata_db.py"), "--db-path", str(db_path)])

    fixture_dir = out_dir / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    default_request = fixture_dir / "cross_party_match_worker.json"
    keep_request = fixture_dir / "cross_party_match_keep.json"
    run_checked(
        [
            "python3",
            str(SCRIPTS / "build_query_workflow_request_fixtures.py"),
            "--default-out",
            str(default_request),
            "--keep-out",
            str(keep_request),
        ]
    )

    restart_request = default_request
    timeout_request = keep_request
    suffix = uuid.uuid4().hex[:8]
    restart_payload = json.loads(restart_request.read_text(encoding="utf-8"))
    restart_payload["job_id"] = f"contract-query-workflow-live-{suffix}"
    restart_payload["out_base"] = str(out_dir / f"query_workflow_live_out_{suffix}")
    write_json(restart_request, restart_payload)
    timeout_payload = json.loads(timeout_request.read_text(encoding="utf-8"))
    timeout_payload["job_id"] = f"contract-query-workflow-live-timeout-{suffix}"
    timeout_payload["out_base"] = str(out_dir / f"query_workflow_live_timeout_out_{suffix}")
    write_json(timeout_request, timeout_payload)
    restart_job_id = restart_payload["job_id"]
    timeout_job_id = timeout_payload["job_id"]

    restart_manifest = out_dir / "restart_enqueue_manifest.json"
    run_checked(
        [
            "python3",
            str(SCRIPTS / "submit_query_workflow.py"),
            "--request-file",
            str(restart_request),
            "--enqueue",
            "--metadata-db-path",
            str(db_path),
            "--manifest-out",
            str(restart_manifest),
        ]
    )

    with connect_db(str(db_path)) as conn:
        apply_migrations(conn)
        row = conn.execute("SELECT id, job_id FROM query_workflow_executions WHERE job_id = ?", (restart_job_id,)).fetchone()
        if row is None:
            raise RuntimeError("restart worker seed job was not enqueued")
        conn.execute(
            "UPDATE query_workflow_executions SET state = 'running', lease_owner = 'dead-worker', lease_expires_at_utc = '2000-01-01T00:00:00Z' WHERE id = ?",
            (row["id"],),
        )
        conn.commit()
        original_popen = qw_worker.subprocess.Popen
        qw_worker.subprocess.Popen = lambda *_args, **_kwargs: original_popen(["true"])
        try:
            restart_result = qw_worker.run_one(
                conn=conn,
                owner=lease_owner("live-query-workflow-restart"),
                lease_seconds=60,
                steal_expired=True,
                timeout_seconds=10,
                poll_seconds=0.05,
                worker_receipts_path=str(out_dir / "query_workflow_restart_worker_receipts.jsonl"),
                dry_run_command=False,
            )
        finally:
            qw_worker.subprocess.Popen = original_popen
        final_row = load_execution(conn, job_id=restart_job_id)
    if final_row is None:
        raise RuntimeError("restart worker final row missing")
    if restart_result.get("event") != "completed" or final_row["state"] != "completed" or not bool(final_row["terminal"]):
        raise RuntimeError(f"restart drill did not reach completed terminal state: {final_row}")
    restart_report = {
        "schema": "query_workflow_live_restart_drill_report/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "job_id": final_row["job_id"],
        "worker_event": restart_result.get("event"),
        "db_state": final_row["state"],
        "terminal": bool(final_row["terminal"]),
        "last_exit_code": final_row["last_exit_code"],
        "lease_owner": final_row["lease_owner"],
        "evidence": {
            "enqueue_manifest": str(restart_manifest),
            "worker_receipts": str(out_dir / "query_workflow_restart_worker_receipts.jsonl"),
        },
    }
    write_json(out_dir / "query_workflow_live_restart_drill_report.json", restart_report)

    timeout_db_path = (out_dir / "query_workflow_live_timeout.db").resolve()
    run_checked(["python3", str(SCRIPTS / "init_metadata_db.py"), "--db-path", str(timeout_db_path)])
    timeout_manifest = out_dir / "timeout_enqueue_manifest.json"
    run_checked(
        [
            "python3",
            str(SCRIPTS / "submit_query_workflow.py"),
            "--request-file",
            str(timeout_request),
            "--enqueue",
            "--metadata-db-path",
            str(timeout_db_path),
            "--manifest-out",
            str(timeout_manifest),
        ]
    )
    with connect_db(str(timeout_db_path)) as conn:
        apply_migrations(conn)
        original_popen = qw_worker.subprocess.Popen
        qw_worker.subprocess.Popen = lambda *_args, **_kwargs: original_popen(["sleep", "5"])
        try:
            timeout_result = qw_worker.run_one(
                conn=conn,
                owner=lease_owner("live-query-workflow-timeout"),
                lease_seconds=60,
                steal_expired=False,
                timeout_seconds=1,
                poll_seconds=0.05,
                worker_receipts_path=str(out_dir / "query_workflow_timeout_worker_receipts.jsonl"),
                dry_run_command=False,
            )
        finally:
            qw_worker.subprocess.Popen = original_popen
        timeout_row = load_execution(conn, job_id=timeout_job_id)
    if timeout_row is None:
        raise RuntimeError("timeout worker final row missing")
    if timeout_result.get("event") != "timed_out" or timeout_row["state"] != "timed_out" or not bool(timeout_row["terminal"]) or timeout_row["last_exit_code"] != 124:
        raise RuntimeError(f"timeout drill did not reach timed_out terminal state: {timeout_row}")
    timeout_report = {
        "schema": "query_workflow_live_timeout_report/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "job_id": timeout_job_id,
        "worker_event": timeout_result.get("event"),
        "db_state": timeout_row["state"],
        "terminal": bool(timeout_row["terminal"]),
        "last_exit_code": timeout_row["last_exit_code"],
        "evidence": {
            "enqueue_manifest": str(timeout_manifest),
            "worker_receipts": str(out_dir / "query_workflow_timeout_worker_receipts.jsonl"),
        },
    }
    write_json(out_dir / "query_workflow_live_timeout_report.json", timeout_report)

    summary = {
        "schema": "query_workflow_live_rollout_collection/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "job_id": args.job_id,
        "live_restart_drill_report": str(out_dir / "query_workflow_live_restart_drill_report.json"),
        "live_timeout_report": str(out_dir / "query_workflow_live_timeout_report.json"),
    }
    write_json(out_dir / "query_workflow_live_rollout_collection.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
