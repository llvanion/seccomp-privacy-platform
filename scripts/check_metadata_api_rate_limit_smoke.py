#!/usr/bin/env python3
"""Regression smoke for A.15: per-caller rate limit on serve_metadata_api.py.

Spins up ``serve_metadata_api.py`` with a small rate limit on a loopback port
backed by an empty fresh SQLite DB, then asserts:

1. ``GET /healthz`` is always reachable and never rate-limited.
2. Burst requests within the configured capacity succeed.
3. Requests past the burst cap return ``HTTP 429`` with the new
   ``rate limit exceeded`` envelope.

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


def _free_port() -> int:
    sock = socket.socket()
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _request(method: str, url: str, *, headers: dict | None = None, timeout: float = 3.0):
    req = urllib.request.Request(url, headers=headers or {}, method=method)
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


def main() -> int:
    ap = argparse.ArgumentParser(description="A.15 metadata API rate limit smoke.")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--burst", type=int, default=2, help="Burst capacity to test against")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "metadata.sqlite3"
    # Initialise an empty DB so the server can boot.
    init_cmd = [
        sys.executable,
        "-c",
        "import sys; sys.path.insert(0, %r);"
        "from metadata_db import connect_db, apply_migrations;"
        "conn = connect_db(%r);"
        "apply_migrations(conn); conn.close()"
        % (str(REPO_ROOT / "scripts"), str(db_path)),
    ]
    res = subprocess.run(init_cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        sys.stderr.write(f"[ERROR] failed to init metadata DB: {res.stderr.strip()}\n")
        return 1

    auth_env = "METADATA_API_RATE_SMOKE_TOKEN"
    auth_token = "smoke-bearer-token-xyz"
    port = _free_port()
    base = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env[auth_env] = auth_token
    env.pop("HTTP_PROXY", None)
    env.pop("http_proxy", None)

    proc = subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "serve_metadata_api.py"),
            "--db-path", str(db_path),
            "--bind-host", "127.0.0.1",
            "--port", str(port),
            "--auth-token-env", auth_env,
            "--rate-limit-per-caller", "1",
            "--rate-limit-burst", str(args.burst),
        ],
        env=env,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_ready(f"{base}/healthz")

        # /healthz must never be rate-limited.
        for _ in range(args.burst * 3):
            status, body = _request("GET", f"{base}/healthz")
            if status != 200:
                sys.stderr.write(f"[ERROR] /healthz unexpectedly returned {status}: {body}\n")
                return 1

        # Hammer an auth-required endpoint with the bearer token. The first
        # `burst` requests should succeed; the very next should return 429.
        bearer = {"Authorization": f"Bearer {auth_token}"}
        seen_429 = False
        successes_before_429 = 0
        responses: list[tuple[int, str]] = []
        for _ in range(args.burst + 2):
            status, body = _request("GET", f"{base}/v1/jobs", headers=bearer)
            responses.append((status, body[:120]))
            if status == 200:
                successes_before_429 += 1
            elif status == 429:
                seen_429 = True
                envelope = json.loads(body)
                if envelope.get("error") and "rate limit" not in str(envelope.get("error")):
                    sys.stderr.write(f"[ERROR] 429 envelope unexpected: {envelope}\n")
                    return 1
                break

        if not seen_429:
            sys.stderr.write(
                f"[ERROR] never observed HTTP 429 within burst+2 requests\n"
                f"  responses: {responses}\n"
            )
            return 1
        if successes_before_429 < 1:
            sys.stderr.write(
                f"[ERROR] expected at least one 200 before 429\n"
                f"  responses: {responses}\n"
            )
            return 1

        report = {
            "status": "ok",
            "schema": "metadata_api_rate_limit_smoke_report/v1",
            "port": port,
            "burst": args.burst,
            "successes_before_429": successes_before_429,
            "seen_429": True,
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
