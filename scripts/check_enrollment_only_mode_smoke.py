#!/usr/bin/env python3
"""Regression smoke for A.13: enrollment-only HTTP mode.

Stands up ``scripts/serve_operator_dashboard.py --mtls-enrollment-only-mode``
as a subprocess on a loopback port, then asserts:

1. ``GET /healthz`` returns 200 and ``ok``.
2. ``GET /`` (dashboard HTML), ``GET /v1/dashboard``, ``GET /v1/runs``, and
   ``POST /v1/runs/select`` all return 404 with ``error=enrollment_only_mode``.
3. ``POST /v1/pjc-mtls/enroll`` reaches the handler (does *not* hit the
   enrollment-only guard) — bad pairing token is rejected as 403, which proves
   the request reached ``_enroll_pjc_mtls_csr`` rather than the early 404.

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


def _request(method: str, url: str, *, body: dict | None = None, timeout: float = 3.0):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    # Bypass any system HTTP proxy so loopback always goes direct.
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
    ap = argparse.ArgumentParser(description="A.13 enrollment-only mode regression smoke.")
    ap.add_argument("--out-dir", required=True, help="Scratch directory for out-base + history-root")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    history_root = out_dir.parent

    port = _free_port()
    base = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env.pop("HTTP_PROXY", None)
    env.pop("http_proxy", None)

    proc = subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "serve_operator_dashboard.py"),
            "--out-base", str(out_dir),
            "--history-root", str(history_root),
            "--bind-host", "127.0.0.1",
            "--port", str(port),
            "--mtls-enrollment-only-mode",
        ],
        env=env,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_ready(f"{base}/healthz")

        # Invariant 1: /healthz is reachable and ok.
        status, body = _request("GET", f"{base}/healthz")
        if status != 200:
            sys.stderr.write(f"[ERROR] /healthz expected 200, got {status}: {body}\n")
            return 1
        payload = json.loads(body)
        if payload.get("status") != "ok":
            sys.stderr.write(f"[ERROR] /healthz payload not ok: {payload}\n")
            return 1

        # Invariant 2: every other surface returns 404 enrollment_only_mode.
        blocked_calls = [
            ("GET", "/", None),
            ("GET", "/v1/dashboard", None),
            ("GET", "/v1/runs", None),
            ("POST", "/v1/runs/select", {"out_base": str(out_dir)}),
            ("POST", "/v1/request/submit", {"request": {}}),
        ]
        for method, path, body_in in blocked_calls:
            status, body = _request(method, f"{base}{path}", body=body_in)
            if status != 404:
                sys.stderr.write(
                    f"[ERROR] {method} {path}: expected 404 enrollment_only_mode, got {status}: {body}\n"
                )
                return 1
            try:
                envelope = json.loads(body)
            except json.JSONDecodeError:
                sys.stderr.write(f"[ERROR] {method} {path}: body was not JSON: {body!r}\n")
                return 1
            if envelope.get("error") != "enrollment_only_mode":
                sys.stderr.write(
                    f"[ERROR] {method} {path}: expected error=enrollment_only_mode, got {envelope}\n"
                )
                return 1

        # Invariant 3: enrollment endpoint reaches the handler. A bad pairing
        # token must return 403 pairing_rejected — that proves we got past
        # the enrollment-only guard (which would have returned 404).
        status, body = _request(
            "POST",
            f"{base}/v1/pjc-mtls/enroll",
            body={"pairing_token": "wrong-token", "csr_pem": ""},
        )
        if status != 403:
            sys.stderr.write(
                f"[ERROR] POST /v1/pjc-mtls/enroll expected 403, got {status}: {body}\n"
            )
            return 1
        envelope = json.loads(body)
        if envelope.get("error") != "pairing_rejected":
            sys.stderr.write(
                f"[ERROR] POST /v1/pjc-mtls/enroll expected pairing_rejected, got {envelope}\n"
            )
            return 1

        summary = {
            "status": "ok",
            "schema": "enrollment_only_mode_smoke_report/v1",
            "port": port,
            "blocked_paths_count": len(blocked_calls),
            "healthz_ok": True,
            "enrollment_handler_reachable": True,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
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
