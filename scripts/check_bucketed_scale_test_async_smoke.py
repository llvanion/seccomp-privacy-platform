#!/usr/bin/env python3
"""Regression smoke for A.14: async bucketed scale-test job model.

Spins up ``serve_operator_dashboard.py`` on a loopback port with
``PJC_MTLS_SCRIPT_DIR`` redirected to a temp dir containing a fast fake
``run_bucketed_scale_test.sh``. Then:

1. ``POST /v1/bucketed-scale-test/run`` returns ``HTTP 202`` with
   ``{job_id, state: "running"}``.
2. Polling ``GET /v1/bucketed-scale-test/{job_id}`` flips to
   ``state="succeeded"`` within a few seconds and includes the result payload.
3. ``GET /v1/bucketed-scale-test`` returns the same job in the list.
4. ``POST /v1/bucketed-scale-test/run`` with ``{"sync": true}`` runs through
   the legacy blocking path and returns ``HTTP 200`` with a non-empty result.

The fake helper finishes in ~300 ms so the whole smoke takes < 5 s.
Default ``scripts/check_json_contracts.sh`` invokes this script.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

FAKE_HELPER_SH = r"""#!/usr/bin/env bash
set -euo pipefail
sleep 0.3
mkdir -p "$OUT_DIR"
cat > "$OUT_DIR/attribution_result.json" <<'JSON'
{"intersection_size": 7, "intersection_sum": 42, "buckets": []}
JSON
cat > "$OUT_DIR/expected_result.json" <<'JSON'
{"intersection_size": 7, "intersection_sum": 42}
JSON
exit 0
"""


def _free_port() -> int:
    sock = socket.socket()
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _request(method: str, url: str, *, body: dict | None = None, timeout: float = 5.0):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _wait_ready(url: str, *, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    last: str | None = None
    while time.time() < deadline:
        try:
            status, body = _request("GET", url, timeout=0.5)
            if status == 200:
                return
            last = f"status={status} body={body[:120]!r}"
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last = repr(exc)
        time.sleep(0.1)
    raise SystemExit(f"server did not become ready at {url}: {last}")


def _poll_until_terminal(url: str, *, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        status, body = _request("GET", url, timeout=2.0)
        if status != 200:
            raise SystemExit(f"poll {url}: expected 200, got {status} {body}")
        last = json.loads(body)
        if last.get("state") in ("succeeded", "failed"):
            return last
        time.sleep(0.1)
    raise SystemExit(f"job did not reach terminal state in {timeout}s; last: {last}")


def main() -> int:
    ap = argparse.ArgumentParser(description="A.14 async bucketed scale-test smoke.")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    scratch = Path(args.out_dir).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    out_base = scratch / "out_base"
    out_base.mkdir(parents=True, exist_ok=True)
    history_root = scratch
    fake_pjc_script_dir = scratch / "fake_pjc"
    fake_pjc_script_dir.mkdir(parents=True, exist_ok=True)
    fake_helper = fake_pjc_script_dir / "run_bucketed_scale_test.sh"
    fake_helper.write_text(FAKE_HELPER_SH, encoding="utf-8")
    fake_helper.chmod(0o755)

    # Stub the helpers that are looked up next to run_bucketed_scale_test.sh.
    # The dashboard uses PJC_MTLS_SCRIPT_DIR = REPO_ROOT/a-psi/moduleA_psi/scripts
    # which is hard-coded at module load. We can't redirect it via env, so the
    # smoke just shells out via the legitimate script dir and overrides the
    # helper path it tries to resolve. To keep the smoke self-contained, we
    # instead patch the script via a wrapper module that imports the dashboard
    # then overrides PJC_MTLS_SCRIPT_DIR before main().
    wrapper_path = scratch / "dashboard_with_fake_script_dir.py"
    wrapper_path.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT / 'scripts')!r})\n"
        "import serve_operator_dashboard as mod\n"
        "from pathlib import Path\n"
        f"mod.PJC_MTLS_SCRIPT_DIR = Path({str(fake_pjc_script_dir)!r})\n"
        "raise SystemExit(mod.main())\n",
        encoding="utf-8",
    )

    port = _free_port()
    base = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env.pop("HTTP_PROXY", None)
    env.pop("http_proxy", None)

    proc = subprocess.Popen(
        [
            sys.executable,
            str(wrapper_path),
            "--out-base", str(out_base),
            "--history-root", str(history_root),
            "--bind-host", "127.0.0.1",
            "--port", str(port),
        ],
        env=env,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_ready(f"{base}/healthz")

        # Invariant 1: async POST returns 202 + running.
        status, body = _request(
            "POST",
            f"{base}/v1/bucketed-scale-test/run",
            body={
                "job_id": "async-smoke",
                "out_dir": str(scratch / "async_run"),
            },
        )
        if status != 202:
            sys.stderr.write(f"[ERROR] async POST expected 202, got {status}: {body}\n")
            return 1
        snap = json.loads(body)
        job_id = snap.get("job_id")
        if not job_id or snap.get("state") != "running":
            sys.stderr.write(f"[ERROR] async POST snapshot invalid: {snap}\n")
            return 1

        # Invariant 2: polling flips to succeeded with result included.
        terminal = _poll_until_terminal(f"{base}/v1/bucketed-scale-test/{job_id}", timeout=8.0)
        if terminal.get("state") != "succeeded":
            sys.stderr.write(f"[ERROR] async job did not succeed: {terminal}\n")
            return 1
        result = terminal.get("result") or {}
        summary = result.get("summary") or {}
        if summary.get("matches_expected") is not True:
            sys.stderr.write(f"[ERROR] async job result summary unexpected: {summary}\n")
            return 1

        # Invariant 3: list endpoint includes the job.
        status, body = _request("GET", f"{base}/v1/bucketed-scale-test")
        if status != 200:
            sys.stderr.write(f"[ERROR] list expected 200, got {status}: {body}\n")
            return 1
        listing = json.loads(body)
        jobs = listing.get("jobs") or []
        if not any(j.get("job_id") == job_id for j in jobs):
            sys.stderr.write(f"[ERROR] list did not include {job_id}: {listing}\n")
            return 1

        # Invariant 4: ?sync=1 returns 200 directly.
        status, body = _request(
            "POST",
            f"{base}/v1/bucketed-scale-test/run?sync=1",
            body={
                "job_id": "sync-smoke",
                "out_dir": str(scratch / "sync_run"),
            },
            timeout=10.0,
        )
        if status != 200:
            sys.stderr.write(f"[ERROR] sync POST expected 200, got {status}: {body}\n")
            return 1
        sync_payload = json.loads(body)
        if sync_payload.get("status") != "ok":
            sys.stderr.write(f"[ERROR] sync POST payload not ok: {sync_payload}\n")
            return 1
        if (sync_payload.get("summary") or {}).get("matches_expected") is not True:
            sys.stderr.write(f"[ERROR] sync POST summary unexpected: {sync_payload}\n")
            return 1

        report = {
            "status": "ok",
            "schema": "bucketed_scale_test_async_smoke_report/v1",
            "port": port,
            "async_job_id": job_id,
            "async_duration_sec": terminal.get("duration_sec"),
            "list_contains_async_job": True,
            "sync_path_ok": True,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
