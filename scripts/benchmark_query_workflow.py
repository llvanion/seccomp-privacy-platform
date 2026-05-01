#!/usr/bin/env python3
import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from runtime_service_helpers import available_port, wait_for_json_health


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUEST_FILE = REPO_ROOT / "docs" / "examples" / "query_request.json"
MODES = ("cli_dry_run", "http_dry_run", "client_dry_run")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * pct
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    weight = pos - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [float(item["duration_ms"]) for item in results if item.get("exit_code") == 0]
    failures = sum(1 for item in results if item.get("exit_code") != 0)
    return {
        "iterations": len(results),
        "successful_iterations": len(durations),
        "failed_iterations": failures,
        "duration_ms": {
            "min": round(min(durations), 3) if durations else None,
            "mean": round(statistics.fmean(durations), 3) if durations else None,
            "p50": round(percentile(durations, 0.50), 3) if durations else None,
            "p95": round(percentile(durations, 0.95), 3) if durations else None,
            "max": round(max(durations), 3) if durations else None,
        },
    }


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"[ERROR] JSON object expected: {path}")
    return payload


def run_command(command: list[str], *, env: dict[str, str], timeout_sec: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_sec,
            env=env,
        )
        timed_out = False
        exit_code = result.returncode
        stderr_tail = "\n".join(result.stderr.splitlines()[-20:]) if result.stderr else ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        stderr_tail = str(exc)
    duration_ms = (time.perf_counter() - started) * 1000
    return {
        "duration_ms": round(duration_ms, 3),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stderr_tail": stderr_tail,
    }


def post_http_dry_run(
    *,
    base_url: str,
    request_payload: dict[str, Any],
    request_base_dir: str,
    auth_token: str,
    timeout_sec: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    opener = build_opener(ProxyHandler({}))
    request = Request(
        f"{base_url}/v1/query-workflows/dry-run",
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}",
            "X-Request-Base-Dir": request_base_dir,
        },
        method="POST",
    )
    try:
        with opener.open(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8")
        payload = json.loads(raw)
        if payload.get("schema") != "query_workflow_api_response/v1":
            raise RuntimeError(f"unexpected response schema: {payload}")
        timed_out = False
        exit_code = 0
        stderr_tail = ""
    except HTTPError as exc:
        timed_out = False
        exit_code = exc.code
        stderr_tail = exc.read().decode("utf-8", errors="replace")
    except URLError as exc:
        timed_out = False
        exit_code = 1
        stderr_tail = str(exc)
    duration_ms = (time.perf_counter() - started) * 1000
    return {
        "duration_ms": round(duration_ms, 3),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stderr_tail": stderr_tail,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Benchmark dry-run query-workflow entrypoints without executing the privacy pipeline.")
    ap.add_argument("--request-file", default=str(DEFAULT_REQUEST_FILE))
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--mode", choices=("all",) + MODES, default="all")
    ap.add_argument("--timeout-sec", type=float, default=30.0)
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-failures", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.iterations <= 0:
        raise SystemExit("[ERROR] --iterations must be positive")
    if args.timeout_sec <= 0:
        raise SystemExit("[ERROR] --timeout-sec must be positive")

    request_file = Path(args.request_file)
    if not request_file.is_absolute():
        request_file = (REPO_ROOT / request_file).resolve()
    if not request_file.is_file():
        raise SystemExit(f"[ERROR] request file does not exist: {request_file}")

    request_payload = load_json_object(request_file)
    request_base_dir = str(request_file.parent)
    selected_modes = list(MODES) if args.mode == "all" else [args.mode]

    common_env = dict(os.environ)
    common_env.setdefault("BRIDGE_TOKEN_SECRET", "benchmark-local-secret")
    results: list[dict[str, Any]] = []

    query_api_process: subprocess.Popen[str] | None = None
    query_api_env = dict(common_env)
    query_api_env["SECCOMP_QUERY_WORKFLOW_API_TOKEN"] = "benchmark-query-api-token"
    query_api_port: int | None = None
    query_api_base_url = ""
    startup_ms: float | None = None

    try:
        if any(mode in {"http_dry_run", "client_dry_run"} for mode in selected_modes):
            query_api_port = available_port()
            query_api_base_url = f"http://127.0.0.1:{query_api_port}"
            server_command = [
                sys.executable,
                str(REPO_ROOT / "scripts" / "serve_query_workflow_api.py"),
                "--bind-host",
                "127.0.0.1",
                "--port",
                str(query_api_port),
                "--auth-token-env",
                "SECCOMP_QUERY_WORKFLOW_API_TOKEN",
            ]
            started = time.perf_counter()
            query_api_process = subprocess.Popen(
                server_command,
                cwd=str(REPO_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=query_api_env,
                text=True,
            )
            wait_for_json_health(url=f"{query_api_base_url}/healthz", timeout_sec=args.timeout_sec, interval_sec=0.05)
            startup_ms = round((time.perf_counter() - started) * 1000, 3)

        for mode in selected_modes:
            mode_command: list[str]
            mode_results: list[dict[str, Any]] = []
            if mode == "cli_dry_run":
                mode_command = [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "submit_query_workflow.py"),
                    "--request-file",
                    str(request_file),
                    "--dry-run",
                ]
                for _ in range(args.iterations):
                    mode_results.append(run_command(mode_command, env=common_env, timeout_sec=args.timeout_sec))
            elif mode == "http_dry_run":
                mode_command = [
                    "POST",
                    f"{query_api_base_url}/v1/query-workflows/dry-run",
                ]
                for _ in range(args.iterations):
                    mode_results.append(
                        post_http_dry_run(
                            base_url=query_api_base_url,
                            request_payload=request_payload,
                            request_base_dir=request_base_dir,
                            auth_token=query_api_env["SECCOMP_QUERY_WORKFLOW_API_TOKEN"],
                            timeout_sec=args.timeout_sec,
                        )
                    )
            elif mode == "client_dry_run":
                mode_command = [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "platform_api_client.py"),
                    "query-submit",
                    "--base-url",
                    query_api_base_url,
                    "--auth-token-env",
                    "SECCOMP_QUERY_WORKFLOW_API_TOKEN",
                    "--request-file",
                    str(request_file),
                ]
                for _ in range(args.iterations):
                    mode_results.append(run_command(mode_command, env=query_api_env, timeout_sec=args.timeout_sec))
            else:
                raise SystemExit(f"[ERROR] unsupported mode: {mode}")

            entry: dict[str, Any] = {
                "mode": mode,
                "command": mode_command,
                "summary": summarize(mode_results),
                "results": mode_results,
            }
            if mode in {"http_dry_run", "client_dry_run"}:
                entry["server_startup_ms"] = startup_ms
            results.append(entry)
    finally:
        if query_api_process is not None:
            query_api_process.terminate()
            try:
                query_api_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                query_api_process.kill()
                query_api_process.wait(timeout=5)

    report = {
        "schema": "query_workflow_benchmark/v1",
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "request_file": str(request_file),
        "iterations": args.iterations,
        "modes": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = (REPO_ROOT / output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)

    if args.allow_failures:
        return 0
    failures = sum(item["summary"]["failed_iterations"] for item in results)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
