#!/usr/bin/env python3
"""Collect live privacy-budget rollout evidence from a running operator host."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_checked(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
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
    ap.add_argument("--job-id", default="privacy-budget-live-rollout")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    approval_api_dir = out_dir / "privacy_budget_approval_api_smoke"
    run_checked(
        [
            "python3",
            str(SCRIPTS / "check_privacy_budget_approval_api_smoke.py"),
            "--out-dir",
            str(approval_api_dir),
        ]
    )
    approval_api_report = approval_api_dir / "privacy_budget_approval_api_smoke.json"

    concurrency_work_dir = out_dir / "privacy_budget_concurrency"
    res = run_checked(
        [
            "python3",
            str(SCRIPTS / "check_privacy_budget_concurrency.py"),
            "--work-dir",
            str(concurrency_work_dir),
        ]
    )
    duplicate_denial_report = out_dir / "privacy_budget_concurrency_check.json"
    duplicate_denial_report.write_text(res.stdout, encoding="utf-8")

    summary = {
        "schema": "privacy_budget_live_rollout_collection/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "job_id": args.job_id,
        "live_approval_api_report": str(approval_api_report),
        "live_duplicate_denial_report": str(duplicate_denial_report),
    }
    write_json(out_dir / "privacy_budget_live_rollout_collection.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
