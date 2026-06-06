#!/usr/bin/env python3
"""Collect live console rollout evidence from a running operator host."""
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


def run_checked(cmd: list[str]) -> None:
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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--job-id", default="console-live-rollout")
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

    browser_report = out_dir / "console_live_browser_session_report.json"
    headers_report = out_dir / "console_live_security_headers_report.json"
    release_report = out_dir / "console_live_release_run_report.json"

    run_checked(["python3", str(SCRIPTS / "check_console_browser_session.py"), "--out", str(browser_report)])
    run_checked(["python3", str(SCRIPTS / "check_console_security_headers.py"), "--out", str(headers_report)])
    run_checked(["python3", str(SCRIPTS / "check_console_release_gate.py"), "--out", str(release_report)])

    browser = load_json(browser_report)
    headers = load_json(headers_report)
    release = load_json(release_report)
    summary = {
        "schema": "console_live_rollout_collection/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "job_id": args.job_id,
        "live_browser_exercise_report": str(browser_report),
        "live_https_secure_cookie_report": str(browser_report),
        "live_release_run_report": str(release_report),
        "browser_status": browser.get("status"),
        "headers_status": headers.get("status"),
        "release_status": release.get("status"),
    }
    write_json(out_dir / "console_live_rollout_collection.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
