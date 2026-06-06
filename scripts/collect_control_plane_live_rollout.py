#!/usr/bin/env python3
"""Collect live control-plane rollout evidence from a running operator host."""
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
DEFAULT_PLATFORM_AUTH_ENV = "SECCOMP_PLATFORM_HEALTH_API_TOKEN"
DEFAULT_METADATA_AUTH_ENV = "SECCOMP_METADATA_API_AUTH_TOKEN"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def resolve_repo_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((REPO_ROOT / path).resolve())


def require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"[ERROR] required environment variable is not set: {name}")
    return value


def run_checked(cmd: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    res = subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        env=full_env,
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


def wait_http_ready(url: str, token_env: str, *, timeout_sec: float = 15.0) -> None:
    deadline = time.time() + timeout_sec
    env = dict(os.environ)
    env["TARGET_URL"] = url
    env["TOKEN_ENV"] = token_env
    snippet = (
        "import json, os, sys, time, urllib.request; "
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


def fetch_json(url: str, *, token: str = "") -> dict[str, Any]:
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"non-object JSON response: {url}")
    return payload


def start_server(
    *,
    cmd: list[str],
    log_path: Path,
    pid_file: Path,
    ready_file: Path,
    ready_url: str,
    token_env: str,
) -> subprocess.Popen[str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        if pid_file:
            deadline = time.time() + 10.0
            while time.time() < deadline:
                if pid_file.is_file():
                    break
                if proc.poll() is not None:
                    raise RuntimeError(f"process exited before pid file was written: {' '.join(cmd)}")
                time.sleep(0.1)
        if ready_file:
            deadline = time.time() + 10.0
            while time.time() < deadline:
                if ready_file.is_file():
                    break
                if proc.poll() is not None:
                    raise RuntimeError(f"process exited before ready file was written: {' '.join(cmd)}")
                time.sleep(0.1)
        wait_http_ready(ready_url, token_env)
        return proc
    except Exception:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        raise


def stop_server(proc: subprocess.Popen[str], *, pid_file: Path, ready_file: Path) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    for path in (pid_file, ready_file):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--metadata-port", type=int, default=18102)
    ap.add_argument("--platform-health-port", type=int, default=18104)
    ap.add_argument("--metadata-db-path", default="tmp/platform_metadata_live.db")
    ap.add_argument("--record-recovery-config", default="config/record_recovery_http_mtls_service.example.json")
    ap.add_argument("--keyring", default="config/keyring.example.json")
    ap.add_argument("--vault-kv-file", default="config/vault_kv_backend.example.json")
    ap.add_argument("--metadata-auth-env", default=DEFAULT_METADATA_AUTH_ENV)
    ap.add_argument("--platform-auth-env", default=DEFAULT_PLATFORM_AUTH_ENV)
    ap.add_argument("--job-id", default="control-plane-live-rollout")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    metadata_auth_token = require_env(args.metadata_auth_env)
    platform_auth_token = require_env(args.platform_auth_env)

    metadata_pid = out_dir / "metadata_api.pid"
    metadata_ready = out_dir / "metadata_api.ready"
    metadata_log = out_dir / "metadata_api.log"
    platform_pid = out_dir / "platform_health_api.pid"
    platform_ready = out_dir / "platform_health_api.ready"
    platform_log = out_dir / "platform_health_api.log"

    metadata_port = int(args.metadata_port)
    platform_port = int(args.platform_health_port)
    metadata_url = f"http://127.0.0.1:{metadata_port}/healthz"
    platform_url = f"http://127.0.0.1:{platform_port}/healthz"
    metadata_db_path = Path(resolve_repo_path(args.metadata_db_path))

    run_checked(
        [
            "python3",
            str(SCRIPTS / "init_metadata_db.py"),
            "--db-path",
            str(metadata_db_path),
        ]
    )

    metadata_cmd = [
        "python3",
        str(SCRIPTS / "serve_metadata_api.py"),
        "--db-path",
        str(metadata_db_path),
        "--auth-token-env",
        args.metadata_auth_env,
        "--bind-host",
        "127.0.0.1",
        "--port",
        str(metadata_port),
        "--pid-file",
        str(metadata_pid),
        "--ready-file",
        str(metadata_ready),
    ]
    platform_cmd = [
        "python3",
        str(SCRIPTS / "serve_platform_health_api.py"),
        "--auth-token-env",
        args.platform_auth_env,
        "--bind-host",
        "127.0.0.1",
        "--port",
        str(platform_port),
        "--pid-file",
        str(platform_pid),
        "--ready-file",
        str(platform_ready),
    ]

    metadata_proc = start_server(
        cmd=metadata_cmd,
        log_path=metadata_log,
        pid_file=metadata_pid,
        ready_file=metadata_ready,
        ready_url=metadata_url,
        token_env=args.metadata_auth_env,
    )
    platform_proc = None
    try:
        platform_proc = start_server(
            cmd=platform_cmd,
            log_path=platform_log,
            pid_file=platform_pid,
            ready_file=platform_ready,
            ready_url=platform_url,
            token_env=args.platform_auth_env,
        )

        materialized_dir = out_dir / "materialized_api"
        materialized_dir.mkdir(parents=True, exist_ok=True)
        metadata_health = fetch_json(metadata_url)
        metadata_jobs = fetch_json(
            f"http://127.0.0.1:{metadata_port}/v1/jobs?limit=5",
            token=metadata_auth_token,
        )
        platform_health = fetch_json(platform_url)
        platform_result = fetch_json(
            (
                f"http://127.0.0.1:{platform_port}/v1/platform-health"
                f"?metadata_db={metadata_db_path}"
            ),
            token=platform_auth_token,
        )
        write_json(materialized_dir / "metadata_api_health.json", metadata_health)
        write_json(materialized_dir / "metadata_api_jobs.json", metadata_jobs)
        write_json(materialized_dir / "platform_health_api_health.json", platform_health)
        write_json(materialized_dir / "platform_health_api_success.json", platform_result)

        live_metadata_api_report = {
            "schema": "control_plane_live_metadata_api_report/v1",
            "generated_at_utc": utc_now_iso(),
            "status": "ok",
            "base_url": f"http://127.0.0.1:{metadata_port}",
            "health": metadata_health,
            "jobs": metadata_jobs,
            "materialized_reports": [
                str(materialized_dir / "metadata_api_health.json"),
                str(materialized_dir / "metadata_api_jobs.json"),
            ],
        }
        live_platform_api_report = {
            "schema": "control_plane_live_platform_api_report/v1",
            "generated_at_utc": utc_now_iso(),
            "status": "ok",
            "base_url": f"http://127.0.0.1:{platform_port}",
            "health": platform_health,
            "result": platform_result,
            "materialized_reports": [
                str(materialized_dir / "platform_health_api_health.json"),
                str(materialized_dir / "platform_health_api_success.json"),
            ],
        }
        live_operator_runbook_report = {
            "schema": "control_plane_live_runbook_report/v1",
            "generated_at_utc": utc_now_iso(),
            "status": "ok",
            "job_id": args.job_id,
            "steps": [
                {
                    "name": "start_metadata_api",
                    "status": "ok",
                    "command": metadata_cmd,
                    "log_path": str(metadata_log),
                },
                {
                    "name": "start_platform_health_api",
                    "status": "ok",
                    "command": platform_cmd,
                    "log_path": str(platform_log),
                },
                {
                    "name": "materialize_platform_api_reports",
                    "status": "ok",
                    "out_dir": str(materialized_dir),
                },
            ],
        }

        write_json(out_dir / "control_plane_live_metadata_api_report.json", live_metadata_api_report)
        write_json(out_dir / "control_plane_live_platform_api_report.json", live_platform_api_report)
        write_json(out_dir / "control_plane_live_runbook_report.json", live_operator_runbook_report)

        summary = {
            "schema": "control_plane_live_rollout_collection/v1",
            "generated_at_utc": utc_now_iso(),
            "status": "ok",
            "job_id": args.job_id,
            "live_metadata_api_report": str(out_dir / "control_plane_live_metadata_api_report.json"),
            "live_platform_api_report": str(out_dir / "control_plane_live_platform_api_report.json"),
            "live_operator_runbook_report": str(out_dir / "control_plane_live_runbook_report.json"),
        }
        write_json(out_dir / "control_plane_live_rollout_collection.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        stop_server(metadata_proc, pid_file=metadata_pid, ready_file=metadata_ready)
        if platform_proc is not None:
            stop_server(platform_proc, pid_file=platform_pid, ready_file=platform_ready)


if __name__ == "__main__":
    raise SystemExit(main())
