#!/usr/bin/env python3
import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from runtime_service_helpers import available_port


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SSE_DIR = REPO_ROOT / "sse"
if str(SSE_DIR) not in sys.path:
    sys.path.insert(0, str(SSE_DIR))

from services.record_recovery.client import request_record_recovery, request_record_recovery_health  # noqa: E402
from services.record_recovery.encrypted_record_store import build_record_store  # noqa: E402


MODES = (
    "unix_socket_health_cli",
    "unix_socket_health_direct",
    "unix_socket_recover_direct",
    "http_health_cli",
    "http_health_direct",
    "http_recover_direct",
)
FIXTURE_PROFILE = "synthetic_record_recovery_store_v1"
FIXTURE_SERVICE_ID = "benchmark-record-recovery"
FIXTURE_TENANT_ID = "benchmark-tenant"
FIXTURE_DATASET_ID = "benchmark-dataset"
FIXTURE_CALLER = "auto_demo"
FIXTURE_JOB_ID = "benchmark-record-recovery-job"
KEY_ENV = "SSE_RECORD_STORE_PASSPHRASE"
AUTH_ENV = "SSE_RECORD_RECOVERY_TOKEN"
EXPECTED_OUTPUT_ROWS = 2


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


def run_callable(func: Callable[[], dict[str, Any]], *, timeout_sec: float) -> dict[str, Any]:
    started = time.perf_counter()
    timed_out = False
    try:
        result = func()
        elapsed_sec = time.perf_counter() - started
        if elapsed_sec > timeout_sec:
            raise TimeoutError(f"call exceeded timeout: {elapsed_sec:.3f}s > {timeout_sec:.3f}s")
        exit_code = 0
        stderr_tail = ""
        extra: dict[str, Any] = {}
        if "output_rows" in result:
            extra["output_rows"] = result.get("output_rows")
        if "transport" in result:
            extra["transport"] = result.get("transport")
    except Exception as exc:
        exit_code = 1
        stderr_tail = str(exc)
        extra = {}
    duration_ms = (time.perf_counter() - started) * 1000
    payload = {
        "duration_ms": round(duration_ms, 3),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stderr_tail": stderr_tail,
    }
    payload.update(extra)
    return payload


def parse_json_stdout(stdout: str, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[ERROR] {label} returned invalid JSON: {exc}\n{stdout}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"[ERROR] {label} returned a non-object JSON payload")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_service_config(
    *,
    config_path: Path,
    run_root: Path,
    transport: str,
    socket_path: Path | None = None,
    endpoint_url: str = "",
    bind_host: str = "",
    port: int | None = None,
) -> None:
    payload: dict[str, Any] = {
        "schema": "record_recovery_service_config/v1",
        "transport": transport,
        "service_id": FIXTURE_SERVICE_ID,
        "tenant_id": FIXTURE_TENANT_ID,
        "dataset_id": FIXTURE_DATASET_ID,
        "auth_token_env": AUTH_ENV,
        "allowed_callers": [FIXTURE_CALLER],
        "allowed_output_roots": [str((run_root / "outputs").resolve())],
        "allowed_record_store_roots": [str(run_root.resolve())],
        "audit_log": str((run_root / f"{transport}_service_audit.jsonl").resolve()),
        "lifecycle": {
            "pid_file": str((run_root / f"{transport}.pid").resolve()),
            "ready_file": str((run_root / f"{transport}.ready").resolve()),
            "log_file": str((run_root / f"{transport}.log").resolve()),
        },
    }
    if transport == "unix_socket":
        if socket_path is None:
            raise SystemExit("[ERROR] unix_socket benchmark config requires socket_path")
        payload["socket_path"] = str(socket_path.resolve())
        payload["socket_mode"] = "600"
    else:
        if not endpoint_url or not bind_host or port is None:
            raise SystemExit("[ERROR] http benchmark config requires endpoint_url, bind_host, and port")
        payload["endpoint_url"] = endpoint_url
        payload["http_listener"] = {"bind_host": bind_host, "port": port}
    write_json(config_path, payload)


def synthetic_candidate_email(index: int) -> str:
    return f"candidate-{index:06d}@example.com"


def create_record_store(*, store_path: Path, env: dict[str, str], candidate_count: int) -> None:
    rows = [
        {
            "email": synthetic_candidate_email(index),
            "campaign": "demo",
            "amount": str(100 + index),
        }
        for index in range(candidate_count)
    ]
    rows.append({"email": "nonmatch@example.com", "campaign": "other", "amount": "50"})
    original = os.environ.get(KEY_ENV)
    os.environ[KEY_ENV] = env[KEY_ENV]
    try:
        count = build_record_store(
            rows=rows,
            out_path=store_path,
            record_id_field="email",
            key_env=KEY_ENV,
        )
    finally:
        if original is None:
            os.environ.pop(KEY_ENV, None)
        else:
            os.environ[KEY_ENV] = original
    if count != candidate_count + 1:
        raise SystemExit(f"[ERROR] unexpected synthetic record-store row count: {count}")


def verify_recovered_csv(path: Path, *, expected_output_rows: int) -> None:
    if not path.is_file():
        raise RuntimeError(f"record recovery output file missing: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != expected_output_rows:
        raise RuntimeError(f"unexpected recovered row count: {len(rows)} != {expected_output_rows}")
    emails = {str(row.get("email") or "") for row in rows}
    expected_emails = {synthetic_candidate_email(index) for index in range(expected_output_rows)}
    if emails != expected_emails:
        raise RuntimeError(f"unexpected recovered email set: {sorted(emails)}")


def run_checked(command: list[str], *, env: dict[str, str], timeout_sec: float, label: str) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_sec,
        env=env,
    )
    duration_ms = round((time.perf_counter() - started) * 1000, 3)
    if result.returncode != 0:
        raise SystemExit(f"[ERROR] {label} failed:\n{result.stderr}")
    return parse_json_stdout(result.stdout, label=label), duration_ms


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Benchmark standalone record recovery service health and recover operations over Unix-socket and HTTP transports.")
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--candidate-count", type=int, default=EXPECTED_OUTPUT_ROWS)
    ap.add_argument("--mode", choices=("all",) + MODES, default="all")
    ap.add_argument("--timeout-sec", type=float, default=30.0)
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-failures", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.candidate_count <= 0:
        raise SystemExit("[ERROR] --candidate-count must be positive")
    if args.iterations <= 0:
        raise SystemExit("[ERROR] --iterations must be positive")
    if args.timeout_sec <= 0:
        raise SystemExit("[ERROR] --timeout-sec must be positive")

    selected_modes = list(MODES) if args.mode == "all" else [args.mode]
    common_env = dict(os.environ)
    common_env.setdefault(KEY_ENV, "benchmark-record-store-passphrase")
    common_env.setdefault(AUTH_ENV, "benchmark-record-recovery-token")
    original_key_env = os.environ.get(KEY_ENV)
    original_auth_env = os.environ.get(AUTH_ENV)
    os.environ[KEY_ENV] = common_env[KEY_ENV]
    os.environ[AUTH_ENV] = common_env[AUTH_ENV]

    try:
        with tempfile.TemporaryDirectory(prefix="seccomp_record_recovery_bench.") as tmp_dir:
            run_root = Path(tmp_dir)
            (run_root / "outputs").mkdir(parents=True, exist_ok=True)
            store_path = run_root / "records.enc.jsonl"
            create_record_store(store_path=store_path, env=common_env, candidate_count=args.candidate_count)

            transport_set = []
            if any(mode.startswith("unix_socket_") for mode in selected_modes):
                transport_set.append("unix_socket")
            if any(mode.startswith("http_") for mode in selected_modes):
                transport_set.append("http")

            results: list[dict[str, Any]] = []
            startup_by_transport: dict[str, float] = {}

            for transport in transport_set:
                if transport == "unix_socket":
                    socket_path = run_root / "record_recovery.sock"
                    endpoint_url = ""
                    bind_host = ""
                    port = None
                else:
                    socket_path = None
                    bind_host = "127.0.0.1"
                    port = available_port()
                    endpoint_url = f"http://127.0.0.1:{port}"

                config_path = run_root / f"{transport}.config.json"
                make_service_config(
                    config_path=config_path,
                    run_root=run_root,
                    transport=transport,
                    socket_path=socket_path,
                    endpoint_url=endpoint_url,
                    bind_host=bind_host,
                    port=port,
                )

                start_command = [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "manage_record_recovery_service.py"),
                    "start",
                    "--config",
                    str(config_path),
                    "--timeout-sec",
                    str(args.timeout_sec),
                ]
                _, startup_ms = run_checked(
                    start_command,
                    env=common_env,
                    timeout_sec=args.timeout_sec,
                    label=f"{transport} start",
                )
                startup_by_transport[transport] = startup_ms

                try:
                    for mode in selected_modes:
                        if transport == "unix_socket" and not mode.startswith("unix_socket_"):
                            continue
                        if transport == "http" and not mode.startswith("http_"):
                            continue

                        mode_results: list[dict[str, Any]] = []
                        operation = "health" if "_health_" in mode else "recover"
                        if mode.endswith("_health_cli"):
                            mode_command = [
                                sys.executable,
                                str(REPO_ROOT / "scripts" / "request_record_recovery_service.py"),
                                "--config",
                                str(config_path),
                            ]
                            for _ in range(args.iterations):
                                mode_results.append(run_command(mode_command, env=common_env, timeout_sec=args.timeout_sec))
                        elif mode.endswith("_health_direct"):
                            mode_command = ["python-api", "services.record_recovery.client.request_record_recovery_health"]

                            def health_call() -> dict[str, Any]:
                                result = request_record_recovery_health(
                                    socket_path=socket_path,
                                    endpoint_url=endpoint_url,
                                    auth_env=AUTH_ENV,
                                )
                                if result.get("transport") != transport:
                                    raise RuntimeError(f"unexpected health transport: {result}")
                                return result

                            for _ in range(args.iterations):
                                mode_results.append(run_callable(health_call, timeout_sec=args.timeout_sec))
                        elif mode.endswith("_recover_direct"):
                            mode_command = ["python-api", "services.record_recovery.client.request_record_recovery"]
                            for iteration in range(args.iterations):
                                out_path = run_root / "outputs" / f"{mode}_{iteration}.csv"
                                if out_path.exists():
                                    out_path.unlink()

                                def recover_call(out_path: Path = out_path) -> dict[str, Any]:
                                    result = request_record_recovery(
                                        socket_path=socket_path,
                                        endpoint_url=endpoint_url,
                                        auth_env=AUTH_ENV,
                                        caller=FIXTURE_CALLER,
                                        job_id=FIXTURE_JOB_ID,
                                        tenant_id=FIXTURE_TENANT_ID,
                                        dataset_id=FIXTURE_DATASET_ID,
                                        service_id=FIXTURE_SERVICE_ID,
                                        record_store_path=store_path,
                                        record_store_key_env=KEY_ENV,
                                        out_path=out_path,
                                        out_format="csv",
                                        role="client",
                                        join_key_field="email",
                                        value_field="amount",
                                        filter_pairs=[("campaign", "demo")],
                                        candidate_ids={synthetic_candidate_email(index) for index in range(args.candidate_count)},
                                        min_output_rows=1,
                                        max_output_rows=max(args.candidate_count, 5),
                                    )
                                    if int(result.get("output_rows", -1)) != args.candidate_count:
                                        raise RuntimeError(f"unexpected recover output_rows: {result}")
                                    verify_recovered_csv(out_path, expected_output_rows=args.candidate_count)
                                    return result

                                mode_results.append(run_callable(recover_call, timeout_sec=args.timeout_sec))
                        else:
                            raise SystemExit(f"[ERROR] unsupported benchmark mode: {mode}")

                        results.append(
                            {
                                "mode": mode,
                                "transport": transport,
                                "operation": operation,
                                "command": mode_command,
                                "summary": summarize(mode_results),
                                "results": mode_results,
                                "service_startup_ms": startup_by_transport[transport],
                            }
                        )
                finally:
                    stop_command = [
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "manage_record_recovery_service.py"),
                        "stop",
                        "--config",
                        str(config_path),
                        "--timeout-sec",
                        str(args.timeout_sec),
                    ]
                    stop_result = subprocess.run(
                        stop_command,
                        cwd=str(REPO_ROOT),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=args.timeout_sec,
                        env=common_env,
                    )
                    if stop_result.returncode != 0:
                        raise SystemExit(f"[ERROR] {transport} stop failed:\n{stop_result.stderr}")

        report = {
            "schema": "record_recovery_benchmark/v1",
            "generated_at_utc": utc_now_iso(),
            "repo_root": str(REPO_ROOT),
            "fixture_profile": FIXTURE_PROFILE,
            "service_id": FIXTURE_SERVICE_ID,
            "transports": transport_set,
            "iterations": args.iterations,
            "candidate_count": args.candidate_count,
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
    finally:
        if original_key_env is None:
            os.environ.pop(KEY_ENV, None)
        else:
            os.environ[KEY_ENV] = original_key_env
        if original_auth_env is None:
            os.environ.pop(AUTH_ENV, None)
        else:
            os.environ[AUTH_ENV] = original_auth_env


if __name__ == "__main__":
    raise SystemExit(main())
