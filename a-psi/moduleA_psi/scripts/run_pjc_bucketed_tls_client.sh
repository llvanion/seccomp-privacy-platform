#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Party B public bucketed mTLS wrapper. By default it expects one shared public
# TLS port across buckets and increments only the local loopback proxy port per
# bucket. Before each bucket it waits for the remote TLS port to accept TCP so
# the client does not race the next-bucket Party A restart window.

export RUN_PJC_CLIENT_SH="${RUN_PJC_CLIENT_SH:-$SCRIPT_DIR/run_pjc_client_tls.sh}"
export TLS_PORT_BASE="${TLS_PORT_BASE:-${TLS_PORT:-10502}}"
export LOCAL_PROXY_PORT_BASE="${LOCAL_PROXY_PORT_BASE:-${LOCAL_PROXY_PORT:-10503}}"
export TLS_PORT_MODE="${TLS_PORT_MODE:-shared}"
export LOCAL_PROXY_PORT_MODE="${LOCAL_PROXY_PORT_MODE:-increment}"
export WAIT_FOR_REMOTE_TLS_READY_TIMEOUT_SEC="${WAIT_FOR_REMOTE_TLS_READY_TIMEOUT_SEC:-120}"
export WAIT_FOR_REMOTE_TLS_READY_POLL_SEC="${WAIT_FOR_REMOTE_TLS_READY_POLL_SEC:-1}"

python3 - "$SCRIPT_DIR/run_pjc_bucketed_client.sh" <<'PY'
import os
import subprocess
import sys
import time

script = sys.argv[1]
base_tls = int(os.environ.get("TLS_PORT_BASE", "10502"))
base_local = int(os.environ.get("LOCAL_PROXY_PORT_BASE", "10503"))
job_dir = os.environ.get("JOB_DIR", "")
if not job_dir:
    raise SystemExit("JOB_DIR is required")

import json
from pathlib import Path

meta = json.loads((Path(job_dir) / "job_meta.json").read_text(encoding="utf-8"))
outputs = ((meta.get("bucket") or {}).get("outputs") or [])
tls_mode = os.environ.get("TLS_PORT_MODE", "shared").strip().lower() or "shared"
local_mode = os.environ.get("LOCAL_PROXY_PORT_MODE", "increment").strip().lower() or "increment"
timeout_sec = float(os.environ.get("WAIT_FOR_REMOTE_TLS_READY_TIMEOUT_SEC", "120") or "120")
poll_sec = float(os.environ.get("WAIT_FOR_REMOTE_TLS_READY_POLL_SEC", "1") or "1")
server_host = os.environ.get("SERVER_HOST", "").strip()

def wait_for_remote_tls(host: str, port: int) -> None:
    deadline = time.time() + timeout_sec
    last_error = ""
    while time.time() < deadline:
        out_dir = Path(job_dir) / ".tls_readiness"
        out_dir.mkdir(parents=True, exist_ok=True)
        report_path = out_dir / f"{host}_{port}.json"
        cmd = [
            "python3",
            str((Path(script).resolve().parents[2] / "scripts" / "check_pjc_tls_readiness.py")),
            "--job-id", os.environ.get("JOB_ID", "pjc-bucketed"),
            "--role", "client",
            "--peer-host", host,
            "--peer-port", str(port),
            "--server-hostname", os.environ.get("TLS_SERVER_COMMON_NAME", "pjc-server"),
            "--cert-dir", os.environ.get("CERT_DIR", ""),
            "--tcp-timeout-sec", "2.0",
            "--tls-timeout-sec", "2.0",
            "--output", str(report_path),
        ]
        probe = subprocess.run(cmd, env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                last_error = f"readiness report unreadable: {exc}"
                time.sleep(poll_sec)
                continue
            if report.get("ready") is True:
                return
            diag = report.get("diagnostic") or {}
            last_error = str(diag.get("reason_code") or diag.get("category") or probe.stderr.strip() or probe.stdout.strip() or "not ready")
        else:
            last_error = probe.stderr.strip() or probe.stdout.strip() or "readiness probe failed"
        time.sleep(poll_sec)
    raise SystemExit(
        f"remote TLS listener not ready on {host}:{port} after {timeout_sec}s: {last_error or 'no response'}"
    )

for idx, item in enumerate(outputs):
    env = os.environ.copy()
    env["JOB_DIR"] = job_dir
    tls_port = base_tls if tls_mode == "shared" else base_tls + idx
    local_proxy_port = base_local if local_mode == "shared" else base_local + idx
    env["TLS_PORT"] = str(tls_port)
    env["LOCAL_PROXY_PORT"] = str(local_proxy_port)
    env["BUCKET_ONLY"] = str(item.get("bucket") or "")
    if server_host:
        wait_for_remote_tls(server_host, tls_port)
    result = subprocess.run(["bash", script], env=env, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
PY
