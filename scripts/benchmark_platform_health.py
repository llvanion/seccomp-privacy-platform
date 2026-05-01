#!/usr/bin/env python3
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from benchmark_read_adapters import FIXTURE_PROFILE, materialize_fixture
from runtime_service_helpers import available_port, wait_for_json_health


REPO_ROOT = Path(__file__).resolve().parents[1]
SEAL_AUDIT_PY = REPO_ROOT / "scripts" / "seal_audit_artifact.py"
SERVE_PLATFORM_HEALTH_API_PY = REPO_ROOT / "scripts" / "serve_platform_health_api.py"
PLATFORM_API_CLIENT_PY = REPO_ROOT / "scripts" / "platform_api_client.py"
MODES = (
    "pipeline_run_cli",
    "metadata_db_cli",
    "combined_cli",
    "pipeline_run_http",
    "metadata_db_http",
    "combined_http",
    "combined_client",
)


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


def run_command(command: list[str], *, env: dict[str, str], timeout_sec: float) -> tuple[dict[str, Any], str]:
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
        stdout = result.stdout
        stderr_tail = "\n".join(result.stderr.splitlines()[-20:]) if result.stderr else ""
    except subprocess.TimeoutExpired as exc:
        duration_ms = (time.perf_counter() - started) * 1000
        return (
            {
                "duration_ms": round(duration_ms, 3),
                "exit_code": 124,
                "timed_out": True,
                "stderr_tail": str(exc),
            },
            "",
        )
    duration_ms = (time.perf_counter() - started) * 1000
    return (
        {
            "duration_ms": round(duration_ms, 3),
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stderr_tail": stderr_tail,
        },
        stdout,
    )


def ensure_ok(result: subprocess.CompletedProcess[str], *, label: str) -> None:
    if result.returncode != 0:
        raise SystemExit(f"[ERROR] {label} failed:\n{result.stderr}")


def run_checked(command: list[str], *, env: dict[str, str], label: str) -> None:
    result = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    ensure_ok(result, label=label)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def validate_health_payload(payload: dict[str, Any], *, expected_components: set[str]) -> dict[str, Any]:
    if payload.get("schema") != "platform_health/v1":
        raise RuntimeError(f"unexpected platform health schema: {payload}")
    summary = payload.get("summary")
    if not isinstance(summary, dict) or summary.get("status") != "ok":
        raise RuntimeError(f"platform health did not pass: {payload}")
    checks = payload.get("checks")
    if not isinstance(checks, list):
        raise RuntimeError(f"platform health checks must be a list: {payload}")
    components = {item.get("component") for item in checks if isinstance(item, dict)}
    statuses = {item.get("status") for item in checks if isinstance(item, dict)}
    if components != expected_components:
        raise RuntimeError(f"unexpected platform health components: expected={expected_components} actual={components}")
    if statuses != {"ok"}:
        raise RuntimeError(f"unexpected platform health statuses: {statuses}")
    for item in checks:
        if not isinstance(item, dict) or item.get("component") != "pipeline_run":
            continue
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        audit_chain = details.get("audit_chain") if isinstance(details.get("audit_chain"), dict) else {}
        if audit_chain.get("mainline_contract_check_embedded") is not True:
            raise RuntimeError(f"platform health pipeline_run missing embedded mainline contract check: {item}")
        mainline = (
            details.get("mainline_contract_check")
            if isinstance(details.get("mainline_contract_check"), dict)
            else {}
        )
        if mainline.get("schema") != "mainline_contract_check/v1":
            raise RuntimeError(f"platform health pipeline_run returned wrong mainline schema: {item}")
        if mainline.get("status") != "ok":
            raise RuntimeError(f"platform health pipeline_run returned non-ok mainline status: {item}")
        handoff_cleanup = (
            mainline.get("handoff_cleanup")
            if isinstance(mainline.get("handoff_cleanup"), dict)
            else {}
        )
        for role_name in ("server", "client"):
            entry = handoff_cleanup.get(role_name) if isinstance(handoff_cleanup.get(role_name), dict) else {}
            if entry.get("status") not in {"cleaned", "removed"}:
                raise RuntimeError(f"platform health pipeline_run returned bad handoff cleanup state: {item}")
        service_consistency = (
            mainline.get("service_audit_consistency")
            if isinstance(mainline.get("service_audit_consistency"), dict)
            else {}
        )
        if (
            service_consistency.get("server") != "not_applicable"
            or service_consistency.get("client") != "ok"
            or service_consistency.get("error_count") != 0
        ):
            raise RuntimeError(f"platform health pipeline_run returned bad service audit consistency summary: {item}")
    return {
        "summary_status": str(summary.get("status")),
        "check_count": len(checks),
        "components": sorted(str(component) for component in components),
    }


def validate_health_report(path: Path, *, expected_components: set[str]) -> dict[str, Any]:
    payload = read_json(path)
    return validate_health_payload(payload, expected_components=expected_components)


def get_http_json(
    *,
    url: str,
    auth_token: str,
    timeout_sec: float,
    expected_components: set[str],
) -> dict[str, Any]:
    started = time.perf_counter()
    opener = build_opener(ProxyHandler({}))
    request = Request(url, method="GET")
    if auth_token:
        request.add_header("Authorization", f"Bearer {auth_token}")
    try:
        with opener.open(request, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("schema") != "platform_health_api_response/v1":
            raise RuntimeError(f"unexpected response schema: {payload}")
        if payload.get("result_schema") != "platform_health/v1":
            raise RuntimeError(f"unexpected result schema: {payload}")
        metrics = validate_health_payload(payload.get("result") or {}, expected_components=expected_components)
        timed_out = False
        exit_code = 0
        stderr_tail = ""
    except HTTPError as exc:
        metrics = {"summary_status": None, "check_count": None, "components": []}
        timed_out = False
        exit_code = exc.code
        stderr_tail = exc.read().decode("utf-8", errors="replace")
    except URLError as exc:
        metrics = {"summary_status": None, "check_count": None, "components": []}
        timed_out = False
        exit_code = 1
        stderr_tail = str(exc)
    except Exception as exc:
        metrics = {"summary_status": None, "check_count": None, "components": []}
        timed_out = False
        exit_code = 1
        stderr_tail = str(exc)
    duration_ms = (time.perf_counter() - started) * 1000
    return {
        "duration_ms": round(duration_ms, 3),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stderr_tail": stderr_tail,
        "stdout_tail": "",
        "summary_status": metrics["summary_status"],
        "check_count": metrics["check_count"],
        "components": metrics["components"],
    }


def run_platform_client(
    *,
    command: list[str],
    env: dict[str, str],
    timeout_sec: float,
    expected_components: set[str],
) -> dict[str, Any]:
    result, stdout = run_command(command, env=env, timeout_sec=timeout_sec)
    stdout_tail = "\n".join(stdout.splitlines()[-20:]) if stdout else ""
    if result["exit_code"] != 0:
        return {
            **result,
            "stdout_tail": stdout_tail,
            "summary_status": None,
            "check_count": None,
            "components": [],
        }
    try:
        payload = json.loads(stdout or "{}")
        if payload.get("schema") != "platform_health_api_response/v1":
            raise RuntimeError(f"unexpected response schema: {payload}")
        if payload.get("result_schema") != "platform_health/v1":
            raise RuntimeError(f"unexpected result schema: {payload}")
        metrics = validate_health_payload(payload.get("result") or {}, expected_components=expected_components)
    except Exception as exc:
        return {
            **result,
            "exit_code": 1,
            "stderr_tail": str(exc),
            "stdout_tail": stdout_tail,
            "summary_status": None,
            "check_count": None,
            "components": [],
        }
    return {
        **result,
        "stdout_tail": stdout_tail,
        "summary_status": metrics["summary_status"],
        "check_count": metrics["check_count"],
        "components": metrics["components"],
    }


def example_command_for_mode(mode: str) -> list[str]:
    cli_prefix = [sys.executable, str(REPO_ROOT / "scripts" / "check_platform_health.py")]
    if mode == "pipeline_run_cli":
        return cli_prefix + ["--out-base", "/tmp/completed_run"]
    if mode == "metadata_db_cli":
        return cli_prefix + ["--metadata-db", "/tmp/platform_metadata.db"]
    if mode == "combined_cli":
        return cli_prefix + ["--out-base", "/tmp/completed_run", "--metadata-db", "/tmp/platform_metadata.db"]
    if mode == "pipeline_run_http":
        return ["GET", "http://127.0.0.1:18093/v1/platform-health?out_base=/tmp/completed_run"]
    if mode == "metadata_db_http":
        return ["GET", "http://127.0.0.1:18093/v1/platform-health?metadata_db=/tmp/platform_metadata.db"]
    if mode == "combined_http":
        return ["GET", "http://127.0.0.1:18093/v1/platform-health?out_base=/tmp/completed_run&metadata_db=/tmp/platform_metadata.db"]
    return [
        sys.executable,
        str(PLATFORM_API_CLIENT_PY),
        "platform-health",
        "--base-url",
        "http://127.0.0.1:18093",
        "--auth-token-env",
        "SECCOMP_PLATFORM_HEALTH_API_TOKEN",
        "--param",
        "out_base=/tmp/completed_run",
        "--param",
        "metadata_db=/tmp/platform_metadata.db",
    ]


def run_mode_once(
    *,
    mode: str,
    iteration: int,
    timeout_sec: float,
    common_env: dict[str, str],
    out_base: Path,
    db_path: Path,
    api_base_url: str,
    api_env: dict[str, str],
) -> dict[str, Any]:
    output_path = Path(tempfile.gettempdir()) / f"platform_health_bench_{mode}_{iteration}.json"
    if output_path.exists():
        output_path.unlink()

    command = [sys.executable, str(REPO_ROOT / "scripts" / "check_platform_health.py"), "--output", str(output_path)]

    if mode == "pipeline_run_cli":
        command.extend(["--out-base", str(out_base)])
        expected_components = {"pipeline_run"}
        result, stdout = run_command(command, env=common_env, timeout_sec=timeout_sec)
    elif mode == "metadata_db_cli":
        command.extend(["--metadata-db", str(db_path)])
        expected_components = {"metadata_db"}
        result, stdout = run_command(command, env=common_env, timeout_sec=timeout_sec)
    elif mode == "combined_cli":
        command.extend(["--out-base", str(out_base), "--metadata-db", str(db_path)])
        expected_components = {"pipeline_run", "metadata_db"}
        result, stdout = run_command(command, env=common_env, timeout_sec=timeout_sec)
    elif mode == "pipeline_run_http":
        return get_http_json(
            url=f"{api_base_url}/v1/platform-health?out_base={out_base}",
            auth_token=api_env["SECCOMP_PLATFORM_HEALTH_API_TOKEN"],
            timeout_sec=timeout_sec,
            expected_components={"pipeline_run"},
        )
    elif mode == "metadata_db_http":
        return get_http_json(
            url=f"{api_base_url}/v1/platform-health?metadata_db={db_path}",
            auth_token=api_env["SECCOMP_PLATFORM_HEALTH_API_TOKEN"],
            timeout_sec=timeout_sec,
            expected_components={"metadata_db"},
        )
    elif mode == "combined_http":
        return get_http_json(
            url=f"{api_base_url}/v1/platform-health?out_base={out_base}&metadata_db={db_path}",
            auth_token=api_env["SECCOMP_PLATFORM_HEALTH_API_TOKEN"],
            timeout_sec=timeout_sec,
            expected_components={"pipeline_run", "metadata_db"},
        )
    elif mode == "combined_client":
        return run_platform_client(
            command=[
                sys.executable,
                str(PLATFORM_API_CLIENT_PY),
                "platform-health",
                "--base-url",
                api_base_url,
                "--auth-token-env",
                "SECCOMP_PLATFORM_HEALTH_API_TOKEN",
                "--param",
                f"out_base={out_base}",
                "--param",
                f"metadata_db={db_path}",
            ],
            env=api_env,
            timeout_sec=timeout_sec,
            expected_components={"pipeline_run", "metadata_db"},
        )
    else:
        raise SystemExit(f"[ERROR] unsupported mode: {mode}")

    stdout_tail = "\n".join(stdout.splitlines()[-20:]) if stdout else ""
    if result["exit_code"] != 0:
        return {
            **result,
            "stdout_tail": stdout_tail,
            "summary_status": None,
            "check_count": None,
            "components": [],
        }

    metrics = validate_health_report(output_path, expected_components=expected_components)
    return {
        **result,
        "stdout_tail": stdout_tail,
        "summary_status": metrics["summary_status"],
        "check_count": metrics["check_count"],
        "components": metrics["components"],
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Benchmark the read-only platform health sidecar over synthetic pipeline and metadata fixtures.")
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

    selected_modes = list(MODES) if args.mode == "all" else [args.mode]
    common_env = dict(os.environ)
    common_env.setdefault("SSE_RECORD_RECOVERY_TOKEN", "benchmark-record-recovery-token")
    mode_entries: list[dict[str, Any]] = []
    platform_health_api_process: subprocess.Popen[str] | None = None
    platform_health_api_base_url = ""

    with tempfile.TemporaryDirectory(prefix="seccomp_platform_health_bench.") as tmp_dir:
        run_root = Path(tmp_dir)
        out_base, db_path = materialize_fixture(run_root, env=common_env)
        run_checked(
            [
                sys.executable,
                str(SEAL_AUDIT_PY),
                "--input",
                str(out_base / "audit_chain.json"),
                "--out",
                str(out_base / "audit_chain.seal.json"),
                "--job-id",
                "benchmark-read-adapters",
            ],
            env=common_env,
            label="seal platform health fixture",
        )

        platform_health_api_env = dict(common_env)
        platform_health_api_env["SECCOMP_PLATFORM_HEALTH_API_TOKEN"] = "benchmark-platform-health-token"

        try:
            requested_api_modes = [mode for mode in selected_modes if mode.endswith("_http") or mode.endswith("_client")]
            if requested_api_modes:
                try:
                    platform_health_port = available_port()
                    platform_health_api_base_url = f"http://127.0.0.1:{platform_health_port}"
                    platform_health_api_process = subprocess.Popen(
                        [
                            sys.executable,
                            str(SERVE_PLATFORM_HEALTH_API_PY),
                            "--bind-host",
                            "127.0.0.1",
                            "--port",
                            str(platform_health_port),
                            "--auth-token-env",
                            "SECCOMP_PLATFORM_HEALTH_API_TOKEN",
                        ],
                        cwd=str(REPO_ROOT),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        env=platform_health_api_env,
                        text=True,
                    )
                    wait_for_json_health(
                        url=f"{platform_health_api_base_url}/healthz",
                        timeout_sec=min(args.timeout_sec, 3.0),
                        interval_sec=0.05,
                    )
                except (Exception, SystemExit) as exc:
                    if args.mode != "all":
                        raise SystemExit(f"[ERROR] failed to start platform health API for mode {args.mode}: {exc}") from exc
                    selected_modes = [mode for mode in selected_modes if mode not in requested_api_modes]
                    print(
                        f"[WARN] skipping platform health HTTP/client benchmark modes in this environment: {exc}",
                        file=sys.stderr,
                    )
                    if platform_health_api_process is not None:
                        platform_health_api_process.terminate()
                        try:
                            platform_health_api_process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            platform_health_api_process.kill()
                            platform_health_api_process.wait(timeout=5)
                        platform_health_api_process = None
                    platform_health_api_base_url = ""

            for mode in selected_modes:
                mode_results = [
                    run_mode_once(
                        mode=mode,
                        iteration=iteration,
                        timeout_sec=args.timeout_sec,
                        common_env=common_env,
                        out_base=out_base,
                        db_path=db_path,
                        api_base_url=platform_health_api_base_url,
                        api_env=platform_health_api_env,
                    )
                    for iteration in range(args.iterations)
                ]
                mode_entries.append(
                    {
                        "mode": mode,
                        "command": example_command_for_mode(mode),
                        "summary": summarize(mode_results),
                        "results": mode_results,
                    }
                )
        finally:
            if platform_health_api_process is not None:
                platform_health_api_process.terminate()
                try:
                    platform_health_api_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    platform_health_api_process.kill()
                    platform_health_api_process.wait(timeout=5)

    report = {
        "schema": "platform_health_benchmark/v1",
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "fixture_profile": FIXTURE_PROFILE,
        "iterations": args.iterations,
        "modes": mode_entries,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = (REPO_ROOT / args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)

    if args.allow_failures:
        return 0
    failures = sum(item["summary"]["failed_iterations"] for item in mode_entries)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
