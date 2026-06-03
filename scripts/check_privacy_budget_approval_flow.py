#!/usr/bin/env python3
"""Regression gate for privacy-budget approval approve/reject/expire/consume."""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_RELEASE = REPO_ROOT / "a-psi" / "moduleA_psi" / "scripts" / "policy_release.py"
APPROVAL_MANAGER = REPO_ROOT / "scripts" / "manage_privacy_budget_approval.py"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run_cmd(cmd: list[str], *, expect_rc: int = 0) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)
    if proc.returncode != expect_rc:
        raise AssertionError(
            f"expected rc={expect_rc}, got {proc.returncode}\ncmd={cmd}\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )
    return proc.returncode, proc.stdout, proc.stderr


def release_cmd(
    work_dir: Path,
    *,
    job_id: str,
    start: str,
    end: str,
    extra: list[str] | None = None,
) -> list[str]:
    meta = work_dir / f"{job_id}.meta.json"
    write_json(meta, {
        "job_id": job_id,
        "window_start": start,
        "window_end": end,
        "bucket": "campaign-a",
        "tenant_id": "tenant-a",
        "dataset_id": "orders-2026",
        "purpose": "attribution-release",
    })
    cmd = [
        sys.executable,
        str(POLICY_RELEASE),
        "--input", str(work_dir / "result.json"),
        "--job-meta", str(meta),
        "--out", str(work_dir / f"{job_id}.report.json"),
        "--audit-log", str(work_dir / "audit.jsonl"),
        "--caller", "privacy_budget_requester",
        "--threshold-k", "1",
        "--max-queries", "10",
        "--privacy-budget-ledger", str(work_dir / "ledger.jsonl"),
        "--privacy-budget-store", str(work_dir / "budget.sqlite"),
        "--privacy-budget-limit", "3",
        "--privacy-budget-cost", "1",
        "--privacy-budget-approval-queue", str(work_dir / "approval_queue.jsonl"),
        "--privacy-budget-approval-decisions", str(work_dir / "approval_decisions.jsonl"),
    ]
    if extra:
        cmd.extend(extra)
    return cmd


def approval_cmd(work_dir: Path, action: str, request_id: str, *, actor: str = "privacy_operator", reason: str = "") -> list[str]:
    cmd = [
        sys.executable,
        str(APPROVAL_MANAGER),
        "--store", str(work_dir / "budget.sqlite"),
        "--approval-queue", str(work_dir / "approval_queue.jsonl"),
        "--decisions", str(work_dir / "approval_decisions.jsonl"),
        "--request-id", request_id,
        "--actor", actor,
    ]
    if reason:
        cmd.extend(["--reason", reason])
    cmd.append(action)
    return cmd


def fetch_statuses(db_path: Path) -> dict[str, int]:
    with sqlite3.connect(db_path) as conn:
        return {
            str(status): int(count)
            for status, count in conn.execute(
                "SELECT status, COUNT(*) FROM privacy_budget_approval_events GROUP BY status"
            ).fetchall()
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check privacy-budget approval close-loop behavior")
    parser.add_argument("--work-dir", help="Optional work directory to keep artifacts")
    parser.add_argument("--keep", action="store_true", help="Keep temporary work dir when --work-dir is not set")
    args = parser.parse_args()

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if args.work_dir:
        work_dir = Path(args.work_dir)
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True)
    else:
        if args.keep:
            work_dir = Path(tempfile.mkdtemp(prefix="privacy_budget_approval."))
        else:
            temp_dir = tempfile.TemporaryDirectory(prefix="privacy_budget_approval.")
            work_dir = Path(temp_dir.name)

    errors: list[str] = []
    try:
        write_json(work_dir / "result.json", {"intersection_size": 2, "intersection_sum": 425})

        run_cmd(release_cmd(
            work_dir,
            job_id="approval-baseline",
            start="2026-01-01T00:00:00Z",
            end="2026-01-31T00:00:00Z",
        ))
        run_cmd(release_cmd(
            work_dir,
            job_id="approval-near-duplicate",
            start="2026-01-15T00:00:00Z",
            end="2026-02-15T00:00:00Z",
        ))
        near_report = load_json(work_dir / "approval-near-duplicate.report.json")
        if near_report.get("reason_code") != "privacy_budget_near_duplicate":
            errors.append(f"near duplicate did not fail closed: {near_report}")
        queue_rows = load_jsonl(work_dir / "approval_queue.jsonl")
        if len(queue_rows) != 1:
            errors.append(f"expected one approval request, got {queue_rows}")
            request_id = ""
        else:
            request_id = str(queue_rows[0].get("request_id") or "")

        if request_id:
            _, self_stdout, self_stderr = run_cmd(
                approval_cmd(work_dir, "approve", request_id, actor="privacy_budget_requester"),
                expect_rc=1,
            )
            if "same_identity_self_approval" not in (self_stdout + self_stderr):
                errors.append("same-identity approval was not rejected with expected reason")

            run_cmd(approval_cmd(work_dir, "approve", request_id, reason="manual overlap review ok"))
            run_cmd(release_cmd(
                work_dir,
                job_id="approval-consumed-release",
                start="2026-01-15T00:00:00Z",
                end="2026-02-15T00:00:00Z",
                extra=[
                    "--privacy-budget-approval-id", request_id,
                    "--privacy-budget-approval-actor", "privacy_operator",
                ],
            ))
            consumed_report = load_json(work_dir / "approval-consumed-release.report.json")
            if consumed_report.get("released") is not True:
                errors.append(f"approved release was not released: {consumed_report}")

            repeat_rc, repeat_stdout, repeat_stderr = run_cmd(release_cmd(
                work_dir,
                job_id="approval-repeat-consume",
                start="2026-01-15T00:00:00Z",
                end="2026-02-15T00:00:00Z",
                extra=[
                    "--privacy-budget-approval-id", request_id,
                    "--privacy-budget-approval-actor", "privacy_operator",
                ],
            ), expect_rc=1)
            if repeat_rc != 1 or "not approved" not in (repeat_stdout + repeat_stderr):
                errors.append("consumed approval was reusable")

        run_cmd(release_cmd(
            work_dir,
            job_id="approval-near-duplicate-reject",
            start="2026-01-20T00:00:00Z",
            end="2026-02-20T00:00:00Z",
        ))
        reject_rows = load_jsonl(work_dir / "approval_queue.jsonl")
        reject_id = str(reject_rows[-1].get("request_id") or "")
        run_cmd(approval_cmd(work_dir, "reject", reject_id, reason="manual reject"))
        _, rejected_stdout, rejected_stderr = run_cmd(release_cmd(
            work_dir,
            job_id="approval-rejected-consume",
            start="2026-01-20T00:00:00Z",
            end="2026-02-20T00:00:00Z",
            extra=[
                "--privacy-budget-approval-id", reject_id,
                "--privacy-budget-approval-actor", "privacy_operator",
            ],
        ), expect_rc=1)
        if "not approved" not in (rejected_stdout + rejected_stderr):
            errors.append("rejected approval was consumable")

        run_cmd(release_cmd(
            work_dir,
            job_id="approval-near-duplicate-expire",
            start="2026-01-25T00:00:00Z",
            end="2026-02-25T00:00:00Z",
        ))
        expire_rows = load_jsonl(work_dir / "approval_queue.jsonl")
        expire_id = str(expire_rows[-1].get("request_id") or "")
        run_cmd(approval_cmd(work_dir, "expire", expire_id, reason="manual expiry"))
        _, expired_stdout, expired_stderr = run_cmd(release_cmd(
            work_dir,
            job_id="approval-expired-consume",
            start="2026-01-25T00:00:00Z",
            end="2026-02-25T00:00:00Z",
            extra=[
                "--privacy-budget-approval-id", expire_id,
                "--privacy-budget-approval-actor", "privacy_operator",
            ],
        ), expect_rc=1)
        if "not approved" not in (expired_stdout + expired_stderr):
            errors.append("expired approval was consumable")

        ledger_rows = load_jsonl(work_dir / "ledger.jsonl")
        decisions = load_jsonl(work_dir / "approval_decisions.jsonl")
        statuses = fetch_statuses(work_dir / "budget.sqlite")
        consumed_decisions = [row for row in decisions if row.get("action") == "consume"]
        if len(consumed_decisions) != 1:
            errors.append(f"expected one consume decision, got {decisions}")
        if statuses.get("consumed", 0) != 1 or statuses.get("rejected", 0) != 1 or statuses.get("expired", 0) != 1:
            errors.append(f"unexpected approval statuses: {statuses}")
        if sum(1 for row in ledger_rows if row.get("budget", {}).get("consumed") is True) != 2:
            errors.append(f"expected baseline + approved consume ledger rows, got {ledger_rows}")

        report = {
            "schema": "privacy_budget_approval_flow_check/v1",
            "status": "fail" if errors else "ok",
            "work_dir": str(work_dir),
            "approval_requests": len(load_jsonl(work_dir / "approval_queue.jsonl")),
            "approval_decisions": len(decisions),
            "approval_status_counts": statuses,
            "ledger_records": len(ledger_rows),
            "errors": errors,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if errors else 0
    finally:
        if temp_dir is not None and not args.keep:
            temp_dir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
