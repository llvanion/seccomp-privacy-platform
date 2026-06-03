#!/usr/bin/env python3
"""Regression gate for transactional privacy-budget consumption.

Two concurrent policy_release invocations race for a scope with budget for one
release. Exactly one must consume budget and release; the other must deny after
observing the transactional store.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_RELEASE = REPO_ROOT / "a-psi" / "moduleA_psi" / "scripts" / "policy_release.py"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def run_release(work_dir: Path, *, job_id: str, start: str, end: str) -> subprocess.Popen:
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
    out = work_dir / f"{job_id}.report.json"
    log = work_dir / f"{job_id}.stdout.txt"
    err = work_dir / f"{job_id}.stderr.txt"
    cmd = [
        sys.executable,
        str(POLICY_RELEASE),
        "--input", str(work_dir / "result.json"),
        "--job-meta", str(meta),
        "--out", str(out),
        "--audit-log", str(work_dir / "audit.jsonl"),
        "--caller", "privacy_budget_concurrency",
        "--threshold-k", "1",
        "--max-queries", "10",
        "--privacy-budget-ledger", str(work_dir / "ledger.jsonl"),
        "--privacy-budget-store", str(work_dir / "budget.sqlite"),
        "--privacy-budget-limit", "1",
        "--privacy-budget-cost", "1",
    ]
    return subprocess.Popen(
        cmd,
        cwd=REPO_ROOT,
        stdout=log.open("w", encoding="utf-8"),
        stderr=err.open("w", encoding="utf-8"),
    )


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check transactional privacy-budget concurrency behavior")
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
            work_dir = Path(tempfile.mkdtemp(prefix="privacy_budget_concurrency."))
        else:
            temp_dir = tempfile.TemporaryDirectory(prefix="privacy_budget_concurrency.")
            work_dir = Path(temp_dir.name)

    try:
        write_json(work_dir / "result.json", {"intersection_size": 2, "intersection_sum": 425})

        proc_a = run_release(
            work_dir,
            job_id="privacy-budget-race-a",
            start="2026-01-01T00:00:00Z",
            end="2026-01-31T00:00:00Z",
        )
        proc_b = run_release(
            work_dir,
            job_id="privacy-budget-race-b",
            start="2026-02-01T00:00:00Z",
            end="2026-02-28T00:00:00Z",
        )
        rc_a = proc_a.wait(timeout=60)
        rc_b = proc_b.wait(timeout=60)
        errors: list[str] = []
        if rc_a != 0:
            errors.append(f"release A exited {rc_a}")
        if rc_b != 0:
            errors.append(f"release B exited {rc_b}")

        reports = [
            load_json(work_dir / "privacy-budget-race-a.report.json"),
            load_json(work_dir / "privacy-budget-race-b.report.json"),
        ]
        released = [report for report in reports if report.get("released") is True]
        denied = [report for report in reports if report.get("released") is False]
        if len(released) != 1 or len(denied) != 1:
            errors.append(f"expected exactly one allow and one deny, got reports={reports}")
        if denied and denied[0].get("reason_code") != "privacy_budget_exhausted":
            errors.append(f"expected denied release to be privacy_budget_exhausted, got {denied[0].get('reason_code')}")

        ledger_rows = load_jsonl(work_dir / "ledger.jsonl")
        if len(ledger_rows) != 2:
            errors.append(f"expected 2 ledger rows, got {len(ledger_rows)}")
        if sum(1 for row in ledger_rows if row.get("budget", {}).get("consumed") is True) != 1:
            errors.append(f"expected exactly one consumed ledger row, got {ledger_rows}")
        if sum(1 for row in ledger_rows if row.get("reason_code") == "privacy_budget_exhausted") != 1:
            errors.append(f"expected one exhausted ledger row, got {ledger_rows}")

        with sqlite3.connect(work_dir / "budget.sqlite") as conn:
            rows = conn.execute(
                """
                SELECT decision, reason_code, budget_consumed, status
                FROM privacy_budget_consumption_events
                WHERE caller = 'privacy_budget_concurrency'
                ORDER BY id
                """
            ).fetchall()
        if len(rows) != 2:
            errors.append(f"expected 2 store rows, got {rows}")
        if sum(1 for row in rows if row[0] == "allow" and int(row[2]) == 1 and row[3] == "committed") != 1:
            errors.append(f"expected one committed allow consume row, got {rows}")
        if sum(1 for row in rows if row[1] == "privacy_budget_exhausted" and int(row[2]) == 0) != 1:
            errors.append(f"expected one exhausted non-consume row, got {rows}")

        report = {
            "schema": "privacy_budget_concurrency_check/v1",
            "status": "fail" if errors else "ok",
            "work_dir": str(work_dir),
            "reports": reports,
            "ledger_records": len(ledger_rows),
            "store_records": [
                {
                    "decision": row[0],
                    "reason_code": row[1],
                    "budget_consumed": bool(row[2]),
                    "status": row[3],
                }
                for row in rows
            ],
            "errors": errors,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if errors else 0
    finally:
        if temp_dir is not None and not args.keep:
            temp_dir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
