#!/usr/bin/env python3
"""Collect live PostgreSQL/HA rollout evidence from a running operator host."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
DEFAULT_METADATA_AUTH_ENV = "SECCOMP_METADATA_API_AUTH_TOKEN"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"[ERROR] required environment variable is not set: {name}")
    return value


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


def fetch_json(url: str, *, token: str = "") -> dict[str, Any]:
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"non-object JSON response: {url}")
    return payload


def wait_http_ready(url: str, token_env: str, *, timeout_sec: float = 15.0) -> None:
    deadline = time.time() + timeout_sec
    env = dict(os.environ)
    env["TARGET_URL"] = url
    env["TOKEN_ENV"] = token_env
    snippet = (
        "import json, os, urllib.request; "
        "req=urllib.request.Request(os.environ['TARGET_URL']); "
        "tok=os.environ.get(os.environ['TOKEN_ENV'], ''); "
        "req.add_header('Authorization', f'Bearer {tok}'); "
        "resp=urllib.request.urlopen(req, timeout=3); "
        "payload=json.loads(resp.read().decode('utf-8')); "
        "assert isinstance(payload, dict)"
    )
    while time.time() < deadline:
        res = subprocess.run(
            ["python3", "-c", snippet],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if res.returncode == 0:
            return
        time.sleep(0.25)
    raise RuntimeError(f"timeout waiting for HTTP readiness: {url}")


def start_metadata_api(
    *,
    db_path: Path,
    port: int,
    auth_env: str,
    out_dir: Path,
) -> subprocess.Popen[str]:
    pid_file = out_dir / "restored_metadata_api.pid"
    ready_file = out_dir / "restored_metadata_api.ready"
    log_path = out_dir / "restored_metadata_api.log"
    handle = log_path.open("w", encoding="utf-8")
    cmd = [
        "python3",
        str(SCRIPTS / "serve_metadata_api.py"),
        "--db-path",
        str(db_path),
        "--auth-token-env",
        auth_env,
        "--bind-host",
        "127.0.0.1",
        "--port",
        str(port),
        "--pid-file",
        str(pid_file),
        "--ready-file",
        str(ready_file),
    ]
    proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT), stdout=handle, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + 15.0
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"restored metadata API exited early: {' '.join(cmd)}")
        if ready_file.is_file():
            break
        time.sleep(0.1)
    wait_http_ready(f"http://127.0.0.1:{port}/healthz", auth_env)
    return proc


def stop_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--metadata-db-path", default="tmp/postgres_ha_live_metadata.db")
    ap.add_argument("--metadata-auth-env", default=DEFAULT_METADATA_AUTH_ENV)
    ap.add_argument("--restored-metadata-port", type=int, default=18112)
    ap.add_argument("--job-id", default="postgres-ha-live-rollout")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata_db_path = (REPO_ROOT / args.metadata_db_path).resolve()
    auth_token = require_env(args.metadata_auth_env)

    run_checked(["python3", str(SCRIPTS / "init_metadata_db.py"), "--db-path", str(metadata_db_path)])

    backup_report = out_dir / "live_metadata_backup_report.json"
    run_checked(
        [
            "python3",
            str(SCRIPTS / "backup_metadata_db.py"),
            "--db-path",
            str(metadata_db_path),
            "--out-path",
            str(out_dir / "live_metadata.backup.db"),
            "--verify",
            "--overwrite",
            "--output",
            str(backup_report),
            "--assert-ok",
        ]
    )
    restore_report = out_dir / "live_metadata_restore_report.json"
    restored_db = out_dir / "live_metadata.restored.db"
    run_checked(
        [
            "python3",
            str(SCRIPTS / "restore_metadata_db.py"),
            "--backup-path",
            str(out_dir / "live_metadata.backup.db"),
            "--backup-report",
            str(backup_report),
            "--out-db-path",
            str(restored_db),
            "--verify-portability",
            "--overwrite",
            "--output",
            str(restore_report),
            "--assert-ok",
        ]
    )

    proc = start_metadata_api(
        db_path=restored_db,
        port=int(args.restored_metadata_port),
        auth_env=args.metadata_auth_env,
        out_dir=out_dir,
    )
    try:
        health = fetch_json(f"http://127.0.0.1:{args.restored_metadata_port}/healthz")
        jobs = fetch_json(
            f"http://127.0.0.1:{args.restored_metadata_port}/v1/jobs?limit=5",
            token=auth_token,
        )
    finally:
        stop_process(proc)

    restored_api_smoke = {
        "schema": "postgres_ha_live_restored_api_smoke/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "base_url": f"http://127.0.0.1:{args.restored_metadata_port}",
        "health": health,
        "jobs": jobs,
        "restored_db_path": str(restored_db),
    }
    write_json(out_dir / "postgres_ha_live_restored_api_smoke.json", restored_api_smoke)

    summary = {
        "schema": "postgres_ha_live_rollout_collection/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "job_id": args.job_id,
        "live_backup_restore_report": str(restore_report),
        "live_restored_api_smoke": str(out_dir / "postgres_ha_live_restored_api_smoke.json"),
    }
    write_json(out_dir / "postgres_ha_live_rollout_collection.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
