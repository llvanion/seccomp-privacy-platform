#!/usr/bin/env python3
"""DB-backed local worker for query workflow executions.

This is repo-side durable-worker evidence, not a claim of a managed production
queue. It proves the execution path can be moved out of HTTP request threads and
owned by a lease/heartbeat worker with cancellation, timeout, and restart-steal
semantics.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from query_workflow_execution_store import (
    DEFAULT_LEASE_SECONDS,
    claim_next_execution,
    connect_execution_db,
    finish_execution,
    heartbeat_execution,
    lease_owner,
    load_execution,
    metadata_json,
)
from submit_query_workflow import (
    REPO_ROOT,
    append_jsonl,
    build_command,
    build_receipt,
    build_status,
    json_sha256,
    load_jsonl_objects,
    query_workflow_sidecar_paths,
    render_manifest,
    validate_request,
    write_json,
)


WORKER_SCHEMA = "query_workflow_worker_run/v1"


def _write_worker_receipt(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _load_payload(row: dict[str, Any]) -> dict[str, Any]:
    meta = metadata_json(row)
    payload = meta.get("raw_payload")
    if not isinstance(payload, dict):
        raise RuntimeError(f"queued execution is missing raw_payload metadata: {row.get('job_id')}")
    return payload


def _receipt_count(path: Path) -> int:
    return len(load_jsonl_objects(path))


def _mark_terminal(
    conn: Any,
    *,
    row: dict[str, Any],
    owner: str,
    payload: dict[str, Any],
    command: list[str],
    request_source: str,
    request_digest: str,
    exit_code: int,
    state: str,
    event: str,
    error_class: str | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sidecar_paths = query_workflow_sidecar_paths(str(payload.get("out_base") or row.get("out_base") or ""))
    manifest = render_manifest(
        request_source=request_source,
        payload=payload,
        command=command,
        mode="execute",
        exit_code=exit_code,
    )
    write_json(sidecar_paths["submission_manifest"], manifest)
    receipt = build_receipt(
        payload=payload,
        mode="execute",
        event=event,
        request_digest=request_digest,
        command=command,
        exit_code=exit_code,
        error_class=error_class,
        error_message=error_message,
    )
    append_jsonl(sidecar_paths["execution_receipts"], receipt)
    final_receipt_count = _receipt_count(sidecar_paths["execution_receipts"])
    status = build_status(
        payload=payload,
        mode="execute",
        state=state,
        terminal=True,
        latest_receipt=receipt,
        receipt_count=final_receipt_count,
        exit_code=exit_code,
    )
    write_json(sidecar_paths["status"], status)
    return finish_execution(
        conn,
        job_id=str(row["job_id"]),
        owner=owner,
        exit_code=exit_code,
        state=state,
        metadata=metadata or {"entrypoint": "run_query_workflow_worker"},
    )


def run_one(
    *,
    conn: Any,
    owner: str,
    lease_seconds: int,
    steal_expired: bool,
    timeout_seconds: int,
    poll_seconds: float,
    worker_receipts_path: str = "",
    dry_run_command: bool = False,
) -> dict[str, Any]:
    row = claim_next_execution(
        conn,
        owner=owner,
        lease_seconds=lease_seconds,
        steal_expired=steal_expired,
    )
    if row is None:
        result = {
            "schema": WORKER_SCHEMA,
            "event": "idle",
            "owner": owner,
            "job_id": None,
            "state": "idle",
        }
        _write_worker_receipt(worker_receipts_path, result)
        return result

    payload = _load_payload(row)
    request_digest = json_sha256(payload)
    try:
        validate_request(payload)
        command = build_command(payload)
    except BaseException as exc:
        finished = _mark_terminal(
            conn,
            row=row,
            owner=owner,
            payload=payload,
            command=[],
            request_source=str(row.get("request_source") or ""),
            request_digest=request_digest,
            exit_code=126,
            state="failed",
            event="failed",
            error_class="validation_failed",
            error_message=str(exc),
            metadata={"entrypoint": "run_query_workflow_worker", "error_class": "validation_failed", "error": str(exc)},
        )
        result = {
            "schema": WORKER_SCHEMA,
            "event": "failed",
            "owner": owner,
            "job_id": row["job_id"],
            "state": finished["state"],
            "exit_code": 126,
        }
        _write_worker_receipt(worker_receipts_path, result)
        return result
    if str(row.get("request_digest") or "") != request_digest:
        finished = _mark_terminal(
            conn,
            row=row,
            owner=owner,
            payload=payload,
            command=command,
            request_source=str(row.get("request_source") or ""),
            request_digest=request_digest,
            exit_code=126,
            state="failed",
            event="failed",
            error_class="request_digest_mismatch",
            error_message="queued execution request_digest does not match raw_payload metadata",
            metadata={"entrypoint": "run_query_workflow_worker", "error_class": "request_digest_mismatch"},
        )
        result = {"schema": WORKER_SCHEMA, "event": "failed", "owner": owner, "job_id": row["job_id"], "state": finished["state"]}
        _write_worker_receipt(worker_receipts_path, result)
        return result

    sidecar_paths = query_workflow_sidecar_paths(str(payload.get("out_base") or ""))
    if str(row.get("state") or "") == "cancel_requested":
        finished = _mark_terminal(
            conn,
            row=row,
            owner=owner,
            payload=payload,
            command=command,
            request_source=str(row.get("request_source") or ""),
            request_digest=request_digest,
            exit_code=130,
            state="cancelled",
            event="cancelled",
            error_class="cancel_requested",
            error_message="execution was already cancel_requested when worker claimed it",
            metadata={
                "entrypoint": "run_query_workflow_worker",
                "worker_owner": owner,
                "error_class": "cancel_requested",
            },
        )
        result = {
            "schema": WORKER_SCHEMA,
            "event": "cancelled",
            "owner": owner,
            "job_id": row["job_id"],
            "state": finished["state"],
            "exit_code": 130,
        }
        _write_worker_receipt(worker_receipts_path, result)
        return result
    started_receipt = build_receipt(
        payload=payload,
        mode="execute",
        event="started",
        request_digest=request_digest,
        command=command,
        exit_code=None,
    )
    append_jsonl(sidecar_paths["execution_receipts"], started_receipt)
    started_status = build_status(
        payload=payload,
        mode="execute",
        state="running",
        terminal=False,
        latest_receipt=started_receipt,
        receipt_count=_receipt_count(sidecar_paths["execution_receipts"]),
        exit_code=None,
    )
    write_json(sidecar_paths["status"], started_status)

    exit_code = 0
    final_state = "completed"
    final_event = "completed"
    error_class = None
    error_message = None
    process: subprocess.Popen[Any] | None = None
    try:
        heartbeat_execution(conn, job_id=str(row["job_id"]), owner=owner, lease_seconds=lease_seconds)
        if dry_run_command:
            process = subprocess.Popen(["true"], cwd=str(REPO_ROOT))
        else:
            process = subprocess.Popen(command, cwd=str(REPO_ROOT))
        started_at = time.monotonic()
        while True:
            current = load_execution(conn, job_id=str(row["job_id"]))
            if current is not None and str(current.get("state") or "") == "cancel_requested":
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                exit_code = 130
                final_state = "cancelled"
                final_event = "cancelled"
                error_class = "cancel_requested"
                error_message = "execution cancelled by operator request"
                break
            if process.poll() is not None:
                exit_code = int(process.returncode or 0)
                if exit_code != 0:
                    final_state = "failed"
                    final_event = "failed"
                    error_class = "run_failed"
                break
            if timeout_seconds > 0 and time.monotonic() - started_at > timeout_seconds:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                exit_code = 124
                final_state = "timed_out"
                final_event = "timed_out"
                error_class = "timeout"
                error_message = f"execution exceeded timeout_seconds={timeout_seconds}"
                break
            heartbeat_execution(conn, job_id=str(row["job_id"]), owner=owner, lease_seconds=lease_seconds)
            time.sleep(max(0.05, poll_seconds))
    except OSError as exc:
        exit_code = 127
        final_state = "failed"
        final_event = "failed"
        error_class = "launch_failed"
        error_message = str(exc)

    finished = _mark_terminal(
        conn,
        row=row,
        owner=owner,
        payload=payload,
        command=command,
        request_source=str(row.get("request_source") or ""),
        request_digest=request_digest,
        exit_code=exit_code,
        state=final_state,
        event=final_event,
        error_class=error_class,
        error_message=error_message,
        metadata={
            "entrypoint": "run_query_workflow_worker",
            "worker_owner": owner,
            "error_class": error_class,
            "error": error_message,
        },
    )
    result = {
        "schema": WORKER_SCHEMA,
        "event": final_event,
        "owner": owner,
        "job_id": row["job_id"],
        "state": finished["state"],
        "exit_code": exit_code,
    }
    _write_worker_receipt(worker_receipts_path, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Run DB-backed query workflow worker.")
    ap.add_argument("--metadata-db-path", default="")
    ap.add_argument("--metadata-db-dsn", default="")
    ap.add_argument("--owner", default="")
    ap.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS)
    ap.add_argument("--steal-expired", action="store_true", default=False)
    ap.add_argument("--timeout-seconds", type=int, default=0)
    ap.add_argument("--poll-seconds", type=float, default=1.0)
    ap.add_argument("--once", action="store_true", default=False)
    ap.add_argument("--idle-exit", action="store_true", default=False)
    ap.add_argument("--worker-receipts", default="")
    ap.add_argument("--dry-run-command", action="store_true", default=False)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    owner = args.owner or lease_owner("query-workflow-worker")
    conn = connect_execution_db(args.metadata_db_path, args.metadata_db_dsn)
    try:
        while True:
            result = run_one(
                conn=conn,
                owner=owner,
                lease_seconds=args.lease_seconds,
                steal_expired=bool(args.steal_expired),
                timeout_seconds=max(0, int(args.timeout_seconds)),
                poll_seconds=max(0.05, float(args.poll_seconds)),
                worker_receipts_path=args.worker_receipts,
                dry_run_command=bool(args.dry_run_command),
            )
            if args.once or (args.idle_exit and result.get("event") == "idle"):
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
