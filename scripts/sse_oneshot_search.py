#!/usr/bin/env python3
"""End-to-end SSE keyword search helper.

Spins up a temporary SSE server on a free TCP port, creates a service,
encrypts the supplied inverted-index database, runs a keyword search, then
tears the server down and emits a single JSON document to stdout.

Used by the operator-dashboard endpoint POST /v1/sse/search so the SPA can
trigger an SSE query without the caller orchestrating the multi-step CLI flow
by hand. Output schema is sse_oneshot_search/v1.

Usage:
    scripts/sse_oneshot_search.py --request-file /tmp/req.json

Request JSON shape:
    {
      "keyword": "China",
      "output_format": "hex",                  # int|hex|raw|utf8
      "scheme": "CJJ14.PiBas",                 # optional
      "service_name": "demo-service",          # optional
      "db": { "China": ["A", "B"], ... },      # optional inline DB
      "db_path": "/abs/path/example_db.json"   # alternative to db
    }

Exit code 0 on success; non-zero on error. On error, still emits a JSON
document with `status: "error"` and a `message`/`stage`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SSE_DIR = REPO_ROOT / "sse"
DEFAULT_PYTHON = SSE_DIR / ".venv" / "bin" / "python"

VALID_OUTPUT_FORMATS = {"int", "hex", "raw", "utf8"}
DEFAULT_SCHEME = "CJJ14.PiBas"
RESULT_RE = re.compile(r">>> The result is (\[.*?\])\.\s*$", re.MULTILINE | re.DOTALL)


def _pick_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, *, timeout_sec: float = 8.0) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"SSE server did not start on {host}:{port} within {timeout_sec}s")


def _resolve_python(python_arg: str) -> str:
    if python_arg:
        return python_arg
    if DEFAULT_PYTHON.is_file():
        return str(DEFAULT_PYTHON)
    return sys.executable


def _run_client(python: str, env: dict[str, str], args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = [python, "run_client.py", *args]
    return subprocess.run(
        cmd,
        cwd=str(SSE_DIR),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _parse_match_list(stdout: str) -> list[str]:
    match = RESULT_RE.search(stdout)
    if not match:
        # The client falls back to a different format when there are zero hits;
        # try a permissive fallback.
        if ">>> The result is []" in stdout:
            return []
        raise RuntimeError(f"could not parse search output: {stdout!r}")
    raw = match.group(1)
    parsed = json.loads(raw.replace("'", '"')) if "'" in raw and '"' not in raw else json.loads(raw)
    return [str(item) for item in parsed]


def _emit_error(stage: str, message: str, **extra: Any) -> None:
    payload = {
        "schema": "sse_oneshot_search/v1",
        "status": "error",
        "stage": stage,
        "message": message,
    }
    payload.update(extra)
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a one-shot SSE keyword search.")
    ap.add_argument("--request-file", required=True, help="Path to JSON request body")
    ap.add_argument("--python", default="", help="Python interpreter to use (default: sse/.venv/bin/python if present)")
    ap.add_argument("--workdir", default="", help="Working directory for transient artifacts (default: mkdtemp)")
    ap.add_argument("--keep-workdir", action="store_true", help="Do not delete workdir on exit (for debugging)")
    args = ap.parse_args()

    try:
        request = json.loads(Path(args.request_file).read_text())
    except Exception as exc:  # noqa: BLE001
        _emit_error("read_request", f"failed to read request file: {exc}")
        return 2

    keyword = str(request.get("keyword") or "").strip()
    if not keyword:
        _emit_error("validate", "missing keyword")
        return 2

    output_format = str(request.get("output_format") or "hex")
    if output_format not in VALID_OUTPUT_FORMATS:
        _emit_error("validate", f"invalid output_format: {output_format!r}")
        return 2

    scheme = str(request.get("scheme") or DEFAULT_SCHEME)
    service_name = str(request.get("service_name") or f"sse-oneshot-{int(time.time() * 1000)}")

    db_inline = request.get("db")
    db_path = request.get("db_path")
    if db_inline is None and not db_path:
        _emit_error("validate", "must provide either db or db_path")
        return 2

    python = _resolve_python(args.python)
    workdir = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="sse_oneshot_"))
    workdir.mkdir(parents=True, exist_ok=True)

    config_path = workdir / "sse-config.json"

    # Materialize the DB file
    if db_inline is not None:
        db_file = workdir / "db.json"
        db_file.write_text(json.dumps(db_inline))
    else:
        db_file = Path(str(db_path)).expanduser().resolve()
        if not db_file.is_file():
            _emit_error("validate", f"db_path not a file: {db_file}")
            return 2

    port = _pick_free_port()
    host = "127.0.0.1"
    env = dict(os.environ)
    env["SSE_SERVER_HOST"] = host
    env["SSE_SERVER_PORT"] = str(port)
    env["SSE_SERVER_URI"] = f"ws://{host}:{port}"
    # Don't let user proxies break the loopback websocket
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    env["NO_PROXY"] = f"{host},localhost"

    server_log = (workdir / "server.log").open("w")
    server_proc = subprocess.Popen(
        [python, "run_server.py", "start"],
        cwd=str(SSE_DIR),
        env=env,
        stdout=server_log,
        stderr=subprocess.STDOUT,
    )

    started_at = time.monotonic()
    try:
        try:
            _wait_for_port(host, port, timeout_sec=10.0)
        except TimeoutError as exc:
            _emit_error("server_start", str(exc))
            return 3

        try:
            _run_client(python, env, ["generate-config", "--scheme", scheme, "--save-path", str(config_path)])
            _run_client(python, env, ["create-service", "--config", str(config_path), "--sname", service_name])
            _run_client(python, env, ["generate-key", "--sname", service_name])
            _run_client(python, env, ["encrypt-database", "--sname", service_name, "--db-path", str(db_file)])
            _run_client(python, env, ["upload-config", "--sname", service_name])
            _run_client(python, env, ["upload-encrypted-database", "--sname", service_name])
            search_proc = _run_client(
                python,
                env,
                ["search", "--sname", service_name, "--keyword", keyword, "--output-format", output_format],
            )
        except subprocess.CalledProcessError as exc:
            _emit_error(
                "client_step",
                f"client step failed (exit {exc.returncode}): {exc.cmd[2] if len(exc.cmd) > 2 else 'unknown'}",
                stdout=exc.stdout,
                stderr=exc.stderr,
            )
            return 4

        try:
            matches = _parse_match_list(search_proc.stdout)
        except RuntimeError as exc:
            _emit_error("parse_result", str(exc), raw_stdout=search_proc.stdout)
            return 5

        duration_ms = int((time.monotonic() - started_at) * 1000)
        payload = {
            "schema": "sse_oneshot_search/v1",
            "status": "ok",
            "service_name": service_name,
            "scheme": scheme,
            "keyword": keyword,
            "output_format": output_format,
            "match_count": len(matches),
            "matches": matches,
            "duration_ms": duration_ms,
            "server_endpoint": f"ws://{host}:{port}",
            "db_source": "inline" if db_inline is not None else str(db_file),
            "workdir": str(workdir) if args.keep_workdir else None,
            "raw_stdout": search_proc.stdout,
        }
        json.dump(payload, sys.stdout)
        sys.stdout.write("\n")
        return 0
    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
            server_proc.wait(timeout=5)
        server_log.close()
        if not args.keep_workdir:
            # Best-effort cleanup
            for p in sorted(workdir.rglob("*"), reverse=True):
                try:
                    p.unlink() if p.is_file() else p.rmdir()
                except OSError:
                    pass
            try:
                workdir.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
