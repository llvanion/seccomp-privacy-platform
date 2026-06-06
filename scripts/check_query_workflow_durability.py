#!/usr/bin/env python3
"""Repo-side durability gate for query workflow sidecars.

This gate does not claim to be a durable production queue. It verifies the
current file-sidecar workflow cannot silently overwrite accepted/running/
terminal state, and that stale/non-terminal runs are visible to operators
instead of being treated as retry-safe.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "query_workflow_durability_check/v1"

import sys

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import submit_query_workflow as submit_qw
from check_workflow_retry_eligibility import build_eligibility_report
from metadata_db import apply_migrations, connect_db
from query_workflow_execution_store import (
    claim_execution,
    finish_execution,
    lease_owner,
    load_execution,
    request_cancel_execution,
)
import run_query_workflow_worker as qw_worker
from submit_query_workflow import (
    build_command,
    build_receipt,
    build_status,
    json_sha256,
    query_workflow_sidecar_paths,
    submit_request_payload,
    validate_request,
    write_json,
)
from validate_json_contract import load_json as load_schema_json, validate_value


class _FakeCompletedProcess:
    returncode = 0


def run_submit_with_fake_pipeline(**kwargs: Any):
    original_run = submit_qw.subprocess.run
    submit_qw.subprocess.run = lambda *_args, **_kwargs: _FakeCompletedProcess()
    try:
        return submit_request_payload(**kwargs)
    finally:
        submit_qw.subprocess.run = original_run


def run_enqueue(**kwargs: Any):
    return submit_request_payload(enqueue=True, **kwargs)


def worker_run_once_with_command(conn: Any, *, command: list[str], **kwargs: Any) -> dict[str, Any]:
    original_popen = qw_worker.subprocess.Popen
    qw_worker.subprocess.Popen = lambda *_args, **_popen_kwargs: original_popen(command)
    try:
        return qw_worker.run_one(conn=conn, **kwargs)
    finally:
        qw_worker.subprocess.Popen = original_popen


def load_execution_row(db_path: Path, *, job_id: str) -> dict[str, Any] | None:
    with connect_db(str(db_path)) as conn:
        return load_execution(conn, job_id=job_id)


def execution_rows(db_path: Path) -> list[dict[str, Any]]:
    with connect_db(str(db_path)) as conn:
        rows = conn.execute("SELECT * FROM query_workflow_executions ORDER BY id").fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def add_finding(findings: list[dict[str, Any]], *, kind: str, message: str, expected: Any, actual: Any) -> None:
    findings.append({
        "kind": kind,
        "message": message,
        "expected": expected,
        "actual": actual,
    })


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def load_receipts(path: Path) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"receipt at line {line_no} must be an object")
        receipts.append(payload)
    return receipts


def validate_schema(schema_name: str, payload: dict[str, Any]) -> bool:
    schema = load_schema_json(REPO_ROOT / "schemas" / f"{schema_name}.schema.json")
    try:
        validate_value(schema, payload)
        return True
    except Exception:
        return False


def write_fixture_inputs(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    server = root / "server.jsonl"
    client = root / "client.jsonl"
    policy = root / "export_policy.json"
    server.write_text(
        "\n".join([
            json.dumps({"email": "a@example.com", "campaign": "demo"}),
            json.dumps({"email": "b@example.com", "campaign": "demo"}),
        ]) + "\n",
        encoding="utf-8",
    )
    client.write_text(
        "\n".join([
            json.dumps({"email": "a@example.com", "purchase": 100}),
            json.dumps({"email": "c@example.com", "purchase": 200}),
        ]) + "\n",
        encoding="utf-8",
    )
    policy.write_text(
        json.dumps({
            "schema": "sse_export_policy/v1",
            "callers": {
                "durability-caller": {
                    "enabled": True,
                    "tenant_id": "durability-tenant",
                    "allowed_dataset_ids": ["durability-dataset"],
                    "allowed_roles": ["server", "client"],
                    "allowed_fields": ["email", "campaign", "purchase"],
                    "allowed_join_key_fields": ["email"],
                    "allowed_value_fields": ["purchase"],
                    "allowed_filter_fields": ["campaign"],
                    "required_filters": ["campaign"],
                    "allowed_filter_values": {"campaign": ["demo"]},
                    "max_export_rows": 1000,
                    "min_export_rows": 1,
                    "can_use_record_recovery_service": True,
                    "can_run_bridge": True,
                    "can_run_pjc": True,
                    "can_release": True,
                }
            },
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"server": server, "client": client, "policy": policy}


def base_request(root: Path, out_base: Path, *, job_id: str = "durability-job") -> dict[str, Any]:
    inputs = write_fixture_inputs(root)
    return {
        "schema": "query_workflow_request/v1",
        "query_type": "cross_party_match",
        "server_source": str(inputs["server"]),
        "client_source": str(inputs["client"]),
        "server_source_format": "jsonl",
        "client_source_format": "jsonl",
        "server_join_key_field": "email",
        "client_join_key_field": "email",
        "client_value_field": "purchase",
        "client_value_mode": "raw-int",
        "client_value_min": 0,
        "client_value_max": 1000000,
        "client_allowed_value_fields": ["purchase"],
        "client_value_unit": "minor_currency_unit",
        "client_value_currency": "USD",
        "server_filters": ["campaign=demo"],
        "token_scope": "durability-scope",
        "token_secret": "example-durability-token-secret",
        "job_id": job_id,
        "out_base": str(out_base),
        "caller": "durability-caller",
        "tenant_id": "durability-tenant",
        "dataset_id": "durability-dataset",
        "sse_export_policy_config": str(inputs["policy"]),
        "cleanup_sse_export_handoff_files_after_bridge": True,
    }


def expect_system_exit(func, expected_text: str) -> dict[str, Any]:
    try:
        func()
    except SystemExit as exc:
        actual = str(exc)
        return {"ok": expected_text in actual, "exit": actual}
    except Exception as exc:
        actual = str(exc)
        return {"ok": expected_text in actual, "exit": actual}
    return {"ok": False, "exit": "command succeeded unexpectedly"}


def sidecar_consistency(out_base: Path) -> tuple[dict[str, Any], list[str]]:
    paths = query_workflow_sidecar_paths(str(out_base))
    status = load_json(paths["status"])
    receipts = load_receipts(paths["execution_receipts"])
    errors: list[str] = []
    if status.get("receipt_count") != len(receipts):
        errors.append(f"receipt_count {status.get('receipt_count')} != actual {len(receipts)}")
    if receipts and status.get("latest_receipt_id") != receipts[-1].get("receipt_id"):
        errors.append("latest_receipt_id does not point at the last receipt")
    if status.get("job_id") and any(receipt.get("job_id") != status.get("job_id") for receipt in receipts):
        errors.append("receipt job_id does not match status job_id")
    if status.get("state") in {"completed", "failed", "rejected", "accepted", "cancelled", "timed_out"} and status.get("terminal") is not True:
        errors.append("terminal state does not set terminal=true")
    if status.get("state") in {"queued", "running", "cancel_requested"} and status.get("terminal") is not False:
        errors.append("running state does not set terminal=false")
    return status, errors


def build_stale_running_fixture(root: Path) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    out_base = root / "stale-running"
    payload = base_request(root / "stale-inputs", out_base, job_id="stale-running-job")
    validate_request(payload)
    command = build_command(payload)
    digest = json_sha256(payload)
    paths = query_workflow_sidecar_paths(str(out_base))
    started = build_receipt(
        payload=payload,
        mode="execute",
        event="started",
        request_digest=digest,
        command=command,
        exit_code=None,
    )
    stale_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    status = build_status(
        payload=payload,
        mode="execute",
        state="running",
        terminal=False,
        latest_receipt=started,
        receipt_count=1,
        exit_code=None,
    )
    status["last_updated_at_utc"] = stale_at
    paths["sidecar_dir"].mkdir(parents=True, exist_ok=True)
    paths["execution_receipts"].write_text(json.dumps(started, ensure_ascii=False) + "\n", encoding="utf-8")
    write_json(paths["status"], status)
    return out_base, status, [started]


def main() -> int:
    ap = argparse.ArgumentParser(description="Check repo-side query workflow durability invariants.")
    ap.add_argument("--out", default="", help=f"Path to write {SCHEMA_ID} JSON report")
    args = ap.parse_args()

    findings: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="seccomp_qw_durability_") as tmpdir:
        root = Path(tmpdir)
        out_base = root / "workflow"
        payload = base_request(root / "inputs", out_base)
        manifest, exit_code, _receipt, status = run_submit_with_fake_pipeline(
            raw_payload=payload,
            request_source="durability-smoke:dry-run",
            request_dir=root,
            execute=False,
        )
        checks["dry_run_accepts"] = {
            "mode": manifest.get("mode"),
            "exit_code": exit_code,
            "state": status.get("state") if status else None,
            "terminal": status.get("terminal") if status else None,
        }
        if checks["dry_run_accepts"] != {"mode": "dry_run", "exit_code": None, "state": "accepted", "terminal": True}:
            add_finding(
                findings,
                kind="dry_run_sidecar_invalid",
                message="dry-run did not create accepted terminal sidecar",
                expected={"mode": "dry_run", "state": "accepted", "terminal": True},
                actual=checks["dry_run_accepts"],
            )

        duplicate_dry_run = expect_system_exit(
            lambda: run_submit_with_fake_pipeline(
                raw_payload=payload,
                request_source="durability-smoke:duplicate-dry-run",
                request_dir=root,
                execute=False,
            ),
            "query workflow sidecar already exists",
        )
        checks["duplicate_dry_run_denied"] = duplicate_dry_run
        if not duplicate_dry_run["ok"]:
            add_finding(
                findings,
                kind="duplicate_dry_run_allowed",
                message="duplicate dry-run overwrote existing accepted sidecar",
                expected="SystemExit containing query workflow sidecar already exists",
                actual=duplicate_dry_run,
            )

        manifest2, _exit2, _receipt2, status2 = run_submit_with_fake_pipeline(
            raw_payload=payload,
            request_source="durability-smoke:execute-from-accepted",
            request_dir=root,
            execute=True,
            metadata_db_path=str(root / "workflow_execution.db"),
            workflow_lease_seconds=60,
        )
        status_after, consistency_errors = sidecar_consistency(out_base)
        db_execution = load_execution_row(root / "workflow_execution.db", job_id=str(payload["job_id"]))
        checks["execute_claims_accepted"] = {
            "manifest_mode": manifest2.get("mode"),
            "state": status2.get("state") if status2 else None,
            "receipt_count": status_after.get("receipt_count"),
            "consistency_errors": consistency_errors,
            "db_state": db_execution.get("state") if db_execution else None,
            "db_terminal": bool(db_execution.get("terminal")) if db_execution else None,
            "db_last_exit_code": db_execution.get("last_exit_code") if db_execution else None,
        }
        if (
            status_after.get("receipt_count", 0) < 3
            or consistency_errors
            or not db_execution
            or db_execution.get("state") != "completed"
            or bool(db_execution.get("terminal")) is not True
        ):
            add_finding(
                findings,
                kind="execute_claim_consistency_failed",
                message="execute did not preserve dry-run receipts, sidecar consistency, and DB terminal state",
                expected="receipt_count>=3, no sidecar consistency errors, and DB state=completed terminal=true",
                actual=checks["execute_claims_accepted"],
            )

        duplicate_execute = expect_system_exit(
            lambda: run_submit_with_fake_pipeline(
                raw_payload=payload,
                request_source="durability-smoke:duplicate-execute",
                request_dir=root,
                execute=True,
            ),
            "query workflow sidecar already exists",
        )
        checks["duplicate_execute_denied"] = duplicate_execute
        if not duplicate_execute["ok"]:
            add_finding(
                findings,
                kind="duplicate_execute_allowed",
                message="duplicate execute overwrote terminal sidecar",
                expected="SystemExit containing query workflow sidecar already exists",
                actual=duplicate_execute,
            )

        stale_out_base, stale_status, stale_receipts = build_stale_running_fixture(root / "stale")
        stale_retry = build_eligibility_report(stale_status, stale_receipts)
        stale_duplicate = expect_system_exit(
            lambda: run_submit_with_fake_pipeline(
                raw_payload=base_request(root / "stale" / "inputs2", stale_out_base, job_id="stale-running-job"),
                request_source="durability-smoke:stale-running-duplicate",
                request_dir=root,
                execute=True,
            ),
            "query workflow sidecar already exists",
        )
        checks["stale_running_visible"] = {
            "retry_recommended_action": stale_retry.get("recommended_action"),
            "retryable": stale_retry.get("retryable"),
            "resubmit_required": stale_retry.get("resubmit_required"),
            "duplicate_start": stale_duplicate,
        }
        if stale_retry.get("recommended_action") != "wait" or stale_duplicate.get("ok") is not True:
            add_finding(
                findings,
                kind="stale_running_not_fail_closed",
                message="stale running sidecar was not kept visible or duplicate start was allowed",
                expected={"recommended_action": "wait", "duplicate_start_denied": True},
                actual=checks["stale_running_visible"],
            )

        db_path = root / "lease_semantics.db"
        with connect_db(str(db_path)) as conn:
            apply_migrations(conn)
            owner_a = lease_owner("durability-a")
            owner_b = lease_owner("durability-b")
            db_payload = base_request(root / "db-inputs", root / "db-run", job_id="db-lease-job")
            db_digest = json_sha256(db_payload)
            claimed = claim_execution(
                conn,
                job_id=str(db_payload["job_id"]),
                out_base=str(db_payload["out_base"]),
                request_digest=db_digest,
                request_source="durability-smoke:db-claim",
                caller=str(db_payload["caller"]),
                tenant_id=str(db_payload["tenant_id"]),
                dataset_id=str(db_payload["dataset_id"]),
                owner=owner_a,
                lease_seconds=60,
                metadata={"case": "initial_claim"},
            )
            duplicate_active = expect_system_exit(
                lambda: claim_execution(
                    conn,
                    job_id=str(db_payload["job_id"]),
                    out_base=str(db_payload["out_base"]),
                    request_digest=db_digest,
                    request_source="durability-smoke:duplicate-active",
                    caller=str(db_payload["caller"]),
                    tenant_id=str(db_payload["tenant_id"]),
                    dataset_id=str(db_payload["dataset_id"]),
                    owner=owner_b,
                    lease_seconds=60,
                    metadata={"case": "duplicate_active"},
                ),
                "lease is active",
            )
            finish_execution(
                conn,
                job_id=str(db_payload["job_id"]),
                owner=owner_a,
                exit_code=0,
                metadata={"case": "terminal"},
            )
            terminal_replay = expect_system_exit(
                lambda: claim_execution(
                    conn,
                    job_id=str(db_payload["job_id"]),
                    out_base=str(db_payload["out_base"]),
                    request_digest=db_digest,
                    request_source="durability-smoke:terminal-replay",
                    caller=str(db_payload["caller"]),
                    tenant_id=str(db_payload["tenant_id"]),
                    dataset_id=str(db_payload["dataset_id"]),
                    owner=owner_b,
                    lease_seconds=60,
                ),
                "execution is terminal",
            )
            expired_payload = base_request(root / "expired-inputs", root / "expired-run", job_id="expired-lease-job")
            expired_digest = json_sha256(expired_payload)
            expired = claim_execution(
                conn,
                job_id=str(expired_payload["job_id"]),
                out_base=str(expired_payload["out_base"]),
                request_digest=expired_digest,
                request_source="durability-smoke:expired-claim",
                caller=str(expired_payload["caller"]),
                tenant_id=str(expired_payload["tenant_id"]),
                dataset_id=str(expired_payload["dataset_id"]),
                owner=owner_a,
                lease_seconds=1,
            )
            conn.execute(
                "UPDATE query_workflow_executions SET lease_expires_at_utc = ? WHERE id = ?",
                ("2000-01-01T00:00:00Z", expired["id"]),
            )
            conn.commit()
            stolen = claim_execution(
                conn,
                job_id=str(expired_payload["job_id"]),
                out_base=str(expired_payload["out_base"]),
                request_digest=expired_digest,
                request_source="durability-smoke:expired-steal",
                caller=str(expired_payload["caller"]),
                tenant_id=str(expired_payload["tenant_id"]),
                dataset_id=str(expired_payload["dataset_id"]),
                owner=owner_b,
                lease_seconds=60,
                steal_expired=True,
                metadata={"case": "expired_steal"},
            )
            checks["db_execution_lifecycle"] = {
                "initial_state": claimed.get("state"),
                "duplicate_active": duplicate_active,
                "terminal_replay": terminal_replay,
                "stolen_owner_changed": stolen.get("lease_owner") == owner_b,
                "row_count": len(execution_rows(db_path)),
            }
            if (
                claimed.get("state") != "running"
                or duplicate_active.get("ok") is not True
                or terminal_replay.get("ok") is not True
                or stolen.get("lease_owner") != owner_b
            ):
                add_finding(
                    findings,
                    kind="db_execution_lifecycle_invalid",
                    message="DB-backed execution lifecycle did not enforce active duplicate, terminal replay, or expired lease semantics",
                    expected={
                        "initial_state": "running",
                        "duplicate_active_denied": True,
                        "terminal_replay_denied": True,
                        "expired_lease_stolen": True,
                    },
                    actual=checks["db_execution_lifecycle"],
                )

        worker_db_path = root / "worker_lifecycle.db"
        worker_out_base = root / "worker-run"
        worker_payload = base_request(root / "worker-inputs", worker_out_base, job_id="worker-success-job")
        enqueue_manifest, _enqueue_exit, _enqueue_receipt, enqueue_status = run_enqueue(
            raw_payload=worker_payload,
            request_source="durability-smoke:worker-enqueue",
            request_dir=root,
            execute=False,
            metadata_db_path=str(worker_db_path),
        )
        with connect_db(str(worker_db_path)) as conn:
            apply_migrations(conn)
            worker_success = worker_run_once_with_command(
                conn,
                command=["true"],
                owner=lease_owner("durability-worker-success"),
                lease_seconds=60,
                steal_expired=False,
                timeout_seconds=10,
                poll_seconds=0.05,
            )
            success_row = load_execution(conn, job_id=str(worker_payload["job_id"]))
        success_status, success_consistency = sidecar_consistency(worker_out_base)
        checks["worker_enqueue_and_complete"] = {
            "enqueue_mode": enqueue_manifest.get("mode"),
            "enqueue_state": enqueue_status.get("state") if enqueue_status else None,
            "worker_event": worker_success.get("event"),
            "db_state": success_row.get("state") if success_row else None,
            "db_terminal": bool(success_row.get("terminal")) if success_row else None,
            "sidecar_state": success_status.get("state"),
            "consistency_errors": success_consistency,
        }
        if (
            enqueue_status is None
            or enqueue_status.get("state") != "queued"
            or worker_success.get("event") != "completed"
            or not success_row
            or success_row.get("state") != "completed"
            or bool(success_row.get("terminal")) is not True
            or success_consistency
        ):
            add_finding(
                findings,
                kind="worker_enqueue_complete_invalid",
                message="worker did not move queued DB execution to completed terminal sidecar and DB state",
                expected={"enqueue_state": "queued", "worker_event": "completed", "db_state": "completed"},
                actual=checks["worker_enqueue_and_complete"],
            )

        queued_cancel_db_path = root / "queued_cancel.db"
        queued_cancel_out_base = root / "queued-cancel-run"
        queued_cancel_payload = base_request(
            root / "queued-cancel-inputs",
            queued_cancel_out_base,
            job_id="queued-cancel-job",
        )
        run_enqueue(
            raw_payload=queued_cancel_payload,
            request_source="durability-smoke:queued-cancel-enqueue",
            request_dir=root,
            execute=False,
            metadata_db_path=str(queued_cancel_db_path),
        )
        queued_cancel_report_path = root / "queued_cancel_report.json"
        queued_cancel_proc = subprocess.run(
            [
                "python3",
                str(REPO_ROOT / "scripts" / "cancel_query_workflow_execution.py"),
                "--metadata-db-path",
                str(queued_cancel_db_path),
                "--job-id",
                str(queued_cancel_payload["job_id"]),
                "--actor",
                "durability-operator",
                "--reason",
                "queued cancellation",
                "--out",
                str(queued_cancel_report_path),
            ],
            cwd=str(REPO_ROOT),
            check=False,
            capture_output=True,
            text=True,
        )
        queued_cancel_report = load_json(queued_cancel_report_path)
        queued_cancel_status, queued_cancel_consistency = sidecar_consistency(queued_cancel_out_base)
        with connect_db(str(queued_cancel_db_path)) as conn:
            queued_cancel_row = load_execution(conn, job_id=str(queued_cancel_payload["job_id"]))
        checks["queued_cancel_cli"] = {
            "exit_code": queued_cancel_proc.returncode,
            "report_state": queued_cancel_report.get("state"),
            "report_sidecar_written": queued_cancel_report.get("sidecar_written"),
            "db_state": queued_cancel_row.get("state") if queued_cancel_row else None,
            "db_terminal": bool(queued_cancel_row.get("terminal")) if queued_cancel_row else None,
            "sidecar_state": queued_cancel_status.get("state"),
            "sidecar_terminal": queued_cancel_status.get("terminal"),
            "consistency_errors": queued_cancel_consistency,
        }
        if (
            queued_cancel_proc.returncode != 0
            or queued_cancel_report.get("state") != "cancelled"
            or queued_cancel_report.get("sidecar_written") is not True
            or not queued_cancel_row
            or queued_cancel_row.get("state") != "cancelled"
            or bool(queued_cancel_row.get("terminal")) is not True
            or queued_cancel_status.get("state") != "cancelled"
            or queued_cancel_status.get("terminal") is not True
            or queued_cancel_consistency
        ):
            add_finding(
                findings,
                kind="queued_cancel_cli_invalid",
                message="queued cancellation CLI did not write terminal DB and sidecar evidence",
                expected={"state": "cancelled", "terminal": True, "sidecar_written": True},
                actual=checks["queued_cancel_cli"],
            )

        cancel_db_path = root / "worker_cancel.db"
        cancel_payload = base_request(root / "cancel-inputs", root / "cancel-run", job_id="worker-cancel-job")
        run_enqueue(
            raw_payload=cancel_payload,
            request_source="durability-smoke:worker-cancel-enqueue",
            request_dir=root,
            execute=False,
            metadata_db_path=str(cancel_db_path),
        )
        cancel_result_holder: dict[str, Any] = {}
        cancel_error_holder: dict[str, Any] = {}

        def _cancel_worker_thread() -> None:
            try:
                with connect_db(str(cancel_db_path)) as worker_conn:
                    apply_migrations(worker_conn)
                    cancel_result_holder["result"] = worker_run_once_with_command(
                        worker_conn,
                        command=["sleep", "5"],
                        owner=lease_owner("durability-worker-cancel"),
                        lease_seconds=60,
                        steal_expired=False,
                        timeout_seconds=30,
                        poll_seconds=0.05,
                    )
            except BaseException as exc:
                cancel_error_holder["error"] = repr(exc)

        cancel_thread = threading.Thread(target=_cancel_worker_thread)
        cancel_thread.start()
        with connect_db(str(cancel_db_path)) as conn:
            apply_migrations(conn)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                row = load_execution(conn, job_id=str(cancel_payload["job_id"]))
                if row and row.get("state") == "running":
                    break
                time.sleep(0.05)
            request_cancel_execution(
                conn,
                job_id=str(cancel_payload["job_id"]),
                actor="durability-operator",
                reason="smoke cancellation",
            )
        cancel_thread.join(timeout=10)
        if cancel_thread.is_alive():
            cancel_error_holder["error"] = "cancel worker thread did not exit"
        with connect_db(str(cancel_db_path)) as conn:
            cancel_row = load_execution(conn, job_id=str(cancel_payload["job_id"]))
        cancel_result = cancel_result_holder.get("result", {"event": None, "error": cancel_error_holder.get("error")})
        cancel_status, cancel_consistency = sidecar_consistency(root / "cancel-run")
        checks["worker_cancel"] = {
            "worker_event": cancel_result.get("event"),
            "db_state": cancel_row.get("state") if cancel_row else None,
            "db_terminal": bool(cancel_row.get("terminal")) if cancel_row else None,
            "sidecar_state": cancel_status.get("state"),
            "last_exit_code": cancel_status.get("last_exit_code"),
            "consistency_errors": cancel_consistency,
        }
        if (
            cancel_result.get("event") != "cancelled"
            or not cancel_row
            or cancel_row.get("state") != "cancelled"
            or bool(cancel_row.get("terminal")) is not True
            or cancel_status.get("state") != "cancelled"
            or cancel_status.get("last_exit_code") != 130
            or cancel_consistency
        ):
            add_finding(
                findings,
                kind="worker_cancel_invalid",
                message="worker did not honor DB cancellation request and write cancelled terminal evidence",
                expected={"event": "cancelled", "state": "cancelled", "exit_code": 130},
                actual=checks["worker_cancel"],
            )

        timeout_db_path = root / "worker_timeout.db"
        timeout_payload = base_request(root / "timeout-inputs", root / "timeout-run", job_id="worker-timeout-job")
        run_enqueue(
            raw_payload=timeout_payload,
            request_source="durability-smoke:worker-timeout-enqueue",
            request_dir=root,
            execute=False,
            metadata_db_path=str(timeout_db_path),
        )
        with connect_db(str(timeout_db_path)) as conn:
            apply_migrations(conn)
            timeout_result = worker_run_once_with_command(
                conn,
                command=["sleep", "5"],
                owner=lease_owner("durability-worker-timeout"),
                lease_seconds=60,
                steal_expired=False,
                timeout_seconds=1,
                poll_seconds=0.05,
            )
            timeout_row = load_execution(conn, job_id=str(timeout_payload["job_id"]))
        timeout_status, timeout_consistency = sidecar_consistency(root / "timeout-run")
        checks["worker_timeout"] = {
            "worker_event": timeout_result.get("event"),
            "db_state": timeout_row.get("state") if timeout_row else None,
            "db_terminal": bool(timeout_row.get("terminal")) if timeout_row else None,
            "sidecar_state": timeout_status.get("state"),
            "last_exit_code": timeout_status.get("last_exit_code"),
            "consistency_errors": timeout_consistency,
        }
        if (
            timeout_result.get("event") != "timed_out"
            or not timeout_row
            or timeout_row.get("state") != "timed_out"
            or bool(timeout_row.get("terminal")) is not True
            or timeout_status.get("state") != "timed_out"
            or timeout_status.get("last_exit_code") != 124
            or timeout_consistency
        ):
            add_finding(
                findings,
                kind="worker_timeout_invalid",
                message="worker did not terminate timed-out execution and write terminal timeout evidence",
                expected={"event": "timed_out", "state": "timed_out", "exit_code": 124},
                actual=checks["worker_timeout"],
            )

        restart_db_path = root / "worker_restart.db"
        restart_payload = base_request(root / "restart-inputs", root / "restart-run", job_id="worker-restart-job")
        run_enqueue(
            raw_payload=restart_payload,
            request_source="durability-smoke:worker-restart-enqueue",
            request_dir=root,
            execute=False,
            metadata_db_path=str(restart_db_path),
        )
        with connect_db(str(restart_db_path)) as conn:
            apply_migrations(conn)
            first_owner = lease_owner("durability-worker-dead")
            first_claim = qw_worker.claim_next_execution(
                conn,
                owner=first_owner,
                lease_seconds=1,
                steal_expired=False,
            )
            assert first_claim is not None
            conn.execute(
                "UPDATE query_workflow_executions SET lease_expires_at_utc = ? WHERE id = ?",
                ("2000-01-01T00:00:00Z", first_claim["id"]),
            )
            conn.commit()
            restart_result = worker_run_once_with_command(
                conn,
                command=["true"],
                owner=lease_owner("durability-worker-restart"),
                lease_seconds=60,
                steal_expired=True,
                timeout_seconds=10,
                poll_seconds=0.05,
            )
            restart_row = load_execution(conn, job_id=str(restart_payload["job_id"]))
        checks["worker_restart_steals_expired"] = {
            "first_owner": first_owner,
            "worker_event": restart_result.get("event"),
            "db_state": restart_row.get("state") if restart_row else None,
            "db_terminal": bool(restart_row.get("terminal")) if restart_row else None,
        }
        if (
            restart_result.get("event") != "completed"
            or not restart_row
            or restart_row.get("state") != "completed"
            or bool(restart_row.get("terminal")) is not True
        ):
            add_finding(
                findings,
                kind="worker_restart_steal_invalid",
                message="replacement worker did not steal expired lease and complete execution",
                expected={"event": "completed", "state": "completed"},
                actual=checks["worker_restart_steals_expired"],
            )

        cancel_takeover_db_path = root / "worker_cancel_takeover.db"
        cancel_takeover_payload = base_request(
            root / "cancel-takeover-inputs",
            root / "cancel-takeover-run",
            job_id="worker-cancel-takeover-job",
        )
        run_enqueue(
            raw_payload=cancel_takeover_payload,
            request_source="durability-smoke:worker-cancel-takeover-enqueue",
            request_dir=root,
            execute=False,
            metadata_db_path=str(cancel_takeover_db_path),
        )
        with connect_db(str(cancel_takeover_db_path)) as conn:
            apply_migrations(conn)
            dead_owner = lease_owner("durability-worker-cancel-dead")
            dead_claim = qw_worker.claim_next_execution(
                conn,
                owner=dead_owner,
                lease_seconds=1,
                steal_expired=False,
            )
            assert dead_claim is not None
            request_cancel_execution(
                conn,
                job_id=str(cancel_takeover_payload["job_id"]),
                actor="durability-operator",
                reason="cancel before restart takeover",
            )
            conn.execute(
                "UPDATE query_workflow_executions SET lease_expires_at_utc = ? WHERE id = ?",
                ("2000-01-01T00:00:00Z", dead_claim["id"]),
            )
            conn.commit()
            cancel_takeover_result = worker_run_once_with_command(
                conn,
                command=["true"],
                owner=lease_owner("durability-worker-cancel-takeover"),
                lease_seconds=60,
                steal_expired=True,
                timeout_seconds=10,
                poll_seconds=0.05,
            )
            cancel_takeover_row = load_execution(conn, job_id=str(cancel_takeover_payload["job_id"]))
        checks["worker_cancel_requested_takeover"] = {
            "worker_event": cancel_takeover_result.get("event"),
            "db_state": cancel_takeover_row.get("state") if cancel_takeover_row else None,
            "db_terminal": bool(cancel_takeover_row.get("terminal")) if cancel_takeover_row else None,
        }
        if (
            cancel_takeover_result.get("event") != "cancelled"
            or not cancel_takeover_row
            or cancel_takeover_row.get("state") != "cancelled"
            or bool(cancel_takeover_row.get("terminal")) is not True
        ):
            add_finding(
                findings,
                kind="worker_cancel_takeover_invalid",
                message="replacement worker did not preserve cancel_requested state during expired-lease takeover",
                expected={"event": "cancelled", "state": "cancelled"},
                actual=checks["worker_cancel_requested_takeover"],
            )

        schema_checks = {
            "status_schema_valid": validate_schema("query_workflow_status", status_after),
            "worker_status_schema_valid": validate_schema("query_workflow_status", success_status),
            "cancel_status_schema_valid": validate_schema("query_workflow_status", cancel_status),
            "timeout_status_schema_valid": validate_schema("query_workflow_status", timeout_status),
            "retry_schema_valid": validate_schema("workflow_retry_eligibility", stale_retry),
        }
        checks["schema_checks"] = schema_checks
        if not all(schema_checks.values()):
            add_finding(
                findings,
                kind="schema_validation_failed",
                message="durability evidence payload failed schema validation",
                expected={"status_schema_valid": True, "retry_schema_valid": True},
                actual=schema_checks,
            )

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "status": "fail" if findings else "ok",
        "summary": {
            "finding_count": len(findings),
            "repo_side_claim": "file-sidecar workflow rejects duplicate overwrite; metadata DB execution rows enforce claim, heartbeat/lease, terminal replay denial, expired-lease steal, queue, cancel, timeout, and worker-owned terminal semantics",
            "production_boundary": "local DB-backed worker evidence exists; production still needs deployed multi-worker process supervision, live PostgreSQL/HA, and restart/cancel/timeout drills on the target hosts",
        },
        "checks": checks,
        "findings": findings,
        "implementation": {
            "submitter": "scripts/submit_query_workflow.py",
            "dashboard": "scripts/serve_operator_dashboard.py",
            "execution_store": "scripts/query_workflow_execution_store.py",
            "worker": "scripts/run_query_workflow_worker.py",
            "status_schema": "schemas/query_workflow_status.schema.json",
            "receipt_schema": "schemas/query_workflow_receipt.schema.json",
        },
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
