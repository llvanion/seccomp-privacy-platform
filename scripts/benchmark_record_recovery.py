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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
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
from scripts.issue_mtls_certs import build_report as issue_mtls_cert_report  # noqa: E402


MODES = (
    "unix_socket_health_cli",
    "unix_socket_health_direct",
    "unix_socket_recover_direct",
    "http_health_cli",
    "http_health_direct",
    "http_recover_direct",
    "http_recover_concurrent",
)
EXPLICIT_MODES = (
    "http_recover_mtls",
    "http_recover_concurrent_limited",
    "g2b_acceptance",
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


def run_concurrent_batch(
    funcs: list[Callable[[], dict[str, Any]]],
    *,
    timeout_sec: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    request_results: list[dict[str, Any]] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=len(funcs)) as executor:
        futures = [executor.submit(func) for func in funcs]
        try:
            completed = list(as_completed(futures, timeout=timeout_sec))
        except FuturesTimeoutError as exc:
            completed = [future for future in futures if future.done()]
            failures.append(str(exc))
            for future in futures:
                future.cancel()
        for future in completed:
            try:
                request_results.append(future.result(timeout=0))
            except Exception as exc:
                failures.append(str(exc))
    duration_sec = time.perf_counter() - started
    successful = len(request_results)
    failed = len(failures) + (len(funcs) - successful - len(failures))
    total_output_rows = sum(int(result.get("output_rows") or 0) for result in request_results)
    return {
        "duration_ms": round(duration_sec * 1000, 3),
        "exit_code": 0 if failed == 0 else 1,
        "timed_out": duration_sec > timeout_sec,
        "stderr_tail": "\n".join(failures[-5:]),
        "concurrent_requests": len(funcs),
        "successful_requests": successful,
        "failed_requests": failed,
        "total_output_rows": total_output_rows,
        "throughput_rps": round(successful / duration_sec, 3) if duration_sec > 0 else None,
    }


def run_concurrent_safety_valve_batch(
    funcs: list[Callable[[], dict[str, Any]]],
    *,
    timeout_sec: float,
    max_rows_per_request: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    request_results: list[dict[str, Any]] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=len(funcs)) as executor:
        futures = [executor.submit(func) for func in funcs]
        try:
            completed = list(as_completed(futures, timeout=timeout_sec))
        except FuturesTimeoutError as exc:
            completed = [future for future in futures if future.done()]
            failures.append(str(exc))
            for future in futures:
                future.cancel()
        for future in completed:
            try:
                request_results.append(future.result(timeout=0))
            except Exception as exc:
                failures.append(str(exc))
    duration_sec = time.perf_counter() - started
    rejected = sum(1 for result in request_results if result.get("rejected") is True)
    accepted = sum(1 for result in request_results if result.get("rejected") is False)
    incomplete = len(funcs) - len(request_results)
    failed = len(failures) + incomplete
    enforced = rejected == len(funcs) and accepted == 0 and failed == 0
    return {
        "duration_ms": round(duration_sec * 1000, 3),
        "exit_code": 0 if enforced else 1,
        "timed_out": duration_sec > timeout_sec,
        "stderr_tail": "\n".join(failures[-5:]),
        "concurrent_requests": len(funcs),
        "successful_requests": 0,
        "failed_requests": failed,
        "total_output_rows": sum(int(result.get("output_rows") or 0) for result in request_results),
        "throughput_rps": round(rejected / duration_sec, 3) if duration_sec > 0 else None,
        "accepted_requests": accepted,
        "rejected_requests": rejected,
        "safety_valve_max_rows": max_rows_per_request,
        "safety_valve_enforced": enforced,
    }


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


def read_process_rss_kb(pid: int | None) -> int | None:
    if not pid:
        return None
    status_path = Path("/proc") / str(pid) / "status"
    try:
        for line in status_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1])
    except FileNotFoundError:
        return None
    return None


def make_service_config(
    *,
    config_path: Path,
    run_root: Path,
    transport: str,
    socket_path: Path | None = None,
    endpoint_url: str = "",
    bind_host: str = "",
    port: int | None = None,
    tls_config: dict[str, Any] | None = None,
    max_rows_per_request: int = 0,
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
    if max_rows_per_request > 0:
        payload["max_rows_per_request"] = max_rows_per_request
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
        if tls_config:
            payload["tls"] = tls_config
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


def issue_mock_mtls_certs(out_dir: Path) -> dict[str, Any]:
    report = issue_mtls_cert_report(
        {
            "schema": "vault_pki_config/v1",
            "common_name": "127.0.0.1",
            "ip_sans": ["127.0.0.1"],
            "dns_sans": ["localhost"],
            "ttl_hours": 24,
            "issue_client_cert": True,
            "mock_mode": True,
        },
        out_dir=str(out_dir),
    )
    if not report.get("ok"):
        raise RuntimeError(f"mock mTLS cert issue failed: {report.get('error')}")
    issued = report.get("issued_files") if isinstance(report.get("issued_files"), dict) else {}
    return {
        "enabled": True,
        "server_cert": str(issued["server_cert"]),
        "server_key": str(issued["server_key"]),
        "ca_cert": str(issued["ca_cert"]),
        "require_client_cert": True,
        "client_cert": str(issued["client_cert"]),
        "client_key": str(issued["client_key"]),
        "verify_hostname": False,
    }


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


def summary_p95(entry: dict[str, Any]) -> float | None:
    duration = (entry.get("summary") or {}).get("duration_ms") or {}
    value = duration.get("p95")
    return float(value) if isinstance(value, (int, float)) else None


def mean_success_duration_ms(entry: dict[str, Any]) -> float | None:
    durations = [
        float(item["duration_ms"])
        for item in entry.get("results") or []
        if item.get("exit_code") == 0 and isinstance(item.get("duration_ms"), (int, float))
    ]
    return statistics.fmean(durations) if durations else None


def mean_throughput_rps(entry: dict[str, Any]) -> float | None:
    throughputs = [
        float(item["throughput_rps"])
        for item in entry.get("results") or []
        if item.get("exit_code") == 0 and isinstance(item.get("throughput_rps"), (int, float))
    ]
    return statistics.fmean(throughputs) if throughputs else None


def build_g2b_summary(*, results: list[dict[str, Any]], candidate_count: int, concurrency: int) -> dict[str, Any] | None:
    by_mode = {entry.get("mode"): entry for entry in results}
    required = {"http_recover_direct", "http_recover_concurrent", "http_recover_mtls"}
    if not required.issubset(by_mode):
        return None
    direct_entry = by_mode["http_recover_direct"]
    concurrent_entry = by_mode["http_recover_concurrent"]
    mtls_entry = by_mode["http_recover_mtls"]
    direct_p95 = summary_p95(direct_entry)
    concurrent_p95 = summary_p95(concurrent_entry)
    mtls_p95 = summary_p95(mtls_entry)
    direct_mean = mean_success_duration_ms(direct_entry)
    sequential_rps = 1000.0 / direct_mean if direct_mean and direct_mean > 0 else None
    concurrent_rps = mean_throughput_rps(concurrent_entry)
    limited_entry = by_mode.get("http_recover_concurrent_limited")
    safety_valve_enforced = None
    safety_valve_max_rows = None
    if limited_entry:
        limited_results = limited_entry.get("results") or []
        safety_valve_enforced = all(item.get("safety_valve_enforced") is True for item in limited_results)
        safety_valve_values = [
            int(item["safety_valve_max_rows"])
            for item in limited_results
            if isinstance(item.get("safety_valve_max_rows"), int)
        ]
        safety_valve_max_rows = safety_valve_values[0] if safety_valve_values else None
    mtls_overhead = None
    if direct_p95 is not None and mtls_p95 is not None:
        mtls_overhead = round(mtls_p95 - direct_p95, 3)
    efficiency = None
    if sequential_rps and concurrent_rps is not None and concurrency > 0:
        efficiency = round(concurrent_rps / (sequential_rps * concurrency), 3)
    return {
        "candidate_count": candidate_count,
        "concurrency": concurrency,
        "sequential_http_p95_ms": round(direct_p95, 3) if direct_p95 is not None else None,
        "concurrent_http_p95_ms": round(concurrent_p95, 3) if concurrent_p95 is not None else None,
        "concurrent_http_throughput_rps": round(concurrent_rps, 3) if concurrent_rps is not None else None,
        "concurrency_efficiency_ratio": efficiency,
        "mtls_p95_ms": round(mtls_p95, 3) if mtls_p95 is not None else None,
        "mtls_p95_overhead_ms": mtls_overhead,
        "safety_valve_max_rows": safety_valve_max_rows,
        "safety_valve_enforced": safety_valve_enforced,
        "acceptance": {
            "single_threaded_p95_under_500ms": direct_p95 is not None and direct_p95 < 500,
            "concurrent_throughput_over_5_rps": concurrent_rps is not None and concurrent_rps > 5,
            "mtls_overhead_under_20ms": mtls_overhead is not None and mtls_overhead < 20,
            "safety_valve_enforced": safety_valve_enforced,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Benchmark standalone record recovery service health and recover operations over Unix-socket and HTTP transports.")
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--candidate-count", type=int, default=EXPECTED_OUTPUT_ROWS)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--safety-valve-max-rows", type=int, default=0)
    ap.add_argument("--mode", choices=("all",) + MODES + EXPLICIT_MODES, default="all")
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
    if args.concurrency <= 0:
        raise SystemExit("[ERROR] --concurrency must be positive")
    if args.safety_valve_max_rows < 0:
        raise SystemExit("[ERROR] --safety-valve-max-rows must be non-negative")
    if args.timeout_sec <= 0:
        raise SystemExit("[ERROR] --timeout-sec must be positive")

    if args.mode == "all":
        selected_modes = list(MODES)
    elif args.mode == "g2b_acceptance":
        selected_modes = [
            "http_recover_direct",
            "http_recover_concurrent",
            "http_recover_mtls",
            "http_recover_concurrent_limited",
        ]
    else:
        selected_modes = [args.mode]
    if "http_recover_concurrent_limited" in selected_modes and args.safety_valve_max_rows <= 0:
        args.safety_valve_max_rows = max(1, args.candidate_count // 10)
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

            transport_plan: list[tuple[str, str, int]] = []
            if any(mode.startswith("unix_socket_") for mode in selected_modes):
                transport_plan.append(("unix_socket", "unix_socket", 0))
            if any(
                mode.startswith("http_")
                and mode not in {"http_recover_mtls", "http_recover_concurrent_limited"}
                for mode in selected_modes
            ):
                transport_plan.append(("http", "http", 0))
            if "http_recover_mtls" in selected_modes:
                transport_plan.append(("https_mtls", "https_mtls", 0))
            if "http_recover_concurrent_limited" in selected_modes:
                transport_plan.append(("http_limited", "http", args.safety_valve_max_rows))
            transport_set = sorted({public_transport for _, public_transport, _ in transport_plan})

            results: list[dict[str, Any]] = []
            startup_by_transport: dict[str, float] = {}
            service_pid_by_transport: dict[str, int | None] = {}

            for transport_profile, transport, max_rows_per_request in transport_plan:
                if transport_profile == "unix_socket":
                    socket_path = run_root / "record_recovery.sock"
                    endpoint_url = ""
                    bind_host = ""
                    port = None
                else:
                    socket_path = None
                    bind_host = "127.0.0.1"
                    port = available_port()
                    endpoint_url = f"https://127.0.0.1:{port}" if transport_profile == "https_mtls" else f"http://127.0.0.1:{port}"
                tls_config = issue_mock_mtls_certs(run_root / "mtls") if transport_profile == "https_mtls" else None

                config_path = run_root / f"{transport_profile}.config.json"
                make_service_config(
                    config_path=config_path,
                    run_root=run_root,
                    transport="http" if transport_profile in {"https_mtls", "http_limited"} else transport_profile,
                    socket_path=socket_path,
                    endpoint_url=endpoint_url,
                    bind_host=bind_host,
                    port=port,
                    tls_config=tls_config,
                    max_rows_per_request=max_rows_per_request,
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
                start_payload, startup_ms = run_checked(
                    start_command,
                    env=common_env,
                    timeout_sec=args.timeout_sec,
                    label=f"{transport_profile} start",
                )
                startup_by_transport[transport_profile] = startup_ms
                service_pid_by_transport[transport_profile] = start_payload.get("started_pid")

                try:
                    for mode in selected_modes:
                        if transport_profile == "unix_socket" and not mode.startswith("unix_socket_"):
                            continue
                        if transport_profile == "http" and (
                            not mode.startswith("http_")
                            or mode in {"http_recover_mtls", "http_recover_concurrent_limited"}
                        ):
                            continue
                        if transport_profile == "https_mtls" and mode != "http_recover_mtls":
                            continue
                        if transport_profile == "http_limited" and mode != "http_recover_concurrent_limited":
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
                        elif mode.endswith("_recover_direct") or mode == "http_recover_mtls":
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
                                        tls_config=tls_config,
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
                        elif mode == "http_recover_concurrent":
                            mode_command = [
                                "python-api",
                                "services.record_recovery.client.request_record_recovery",
                                f"--concurrency={args.concurrency}",
                            ]
                            for iteration in range(args.iterations):
                                funcs: list[Callable[[], dict[str, Any]]] = []
                                for request_index in range(args.concurrency):
                                    out_path = run_root / "outputs" / f"{mode}_{iteration}_{request_index}.csv"
                                    if out_path.exists():
                                        out_path.unlink()

                                    def recover_call(out_path: Path = out_path) -> dict[str, Any]:
                                        result = request_record_recovery(
                                            socket_path=None,
                                            endpoint_url=endpoint_url,
                                            auth_env=AUTH_ENV,
                                            tls_config=tls_config,
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
                                            candidate_ids={
                                                synthetic_candidate_email(index) for index in range(args.candidate_count)
                                            },
                                            min_output_rows=1,
                                            max_output_rows=max(args.candidate_count, 5),
                                        )
                                        if int(result.get("output_rows", -1)) != args.candidate_count:
                                            raise RuntimeError(f"unexpected recover output_rows: {result}")
                                        verify_recovered_csv(out_path, expected_output_rows=args.candidate_count)
                                        return result

                                    funcs.append(recover_call)
                                mode_results.append(run_concurrent_batch(funcs, timeout_sec=args.timeout_sec))
                        elif mode == "http_recover_concurrent_limited":
                            mode_command = [
                                "python-api",
                                "services.record_recovery.client.request_record_recovery",
                                f"--concurrency={args.concurrency}",
                                f"--max-rows-per-request={max_rows_per_request}",
                            ]
                            for iteration in range(args.iterations):
                                funcs = []
                                for request_index in range(args.concurrency):
                                    out_path = run_root / "outputs" / f"{mode}_{iteration}_{request_index}.csv"
                                    if out_path.exists():
                                        out_path.unlink()

                                    def recover_call(out_path: Path = out_path) -> dict[str, Any]:
                                        try:
                                            result = request_record_recovery(
                                                socket_path=None,
                                                endpoint_url=endpoint_url,
                                                auth_env=AUTH_ENV,
                                                tls_config=tls_config,
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
                                                candidate_ids={
                                                    synthetic_candidate_email(index) for index in range(args.candidate_count)
                                                },
                                                min_output_rows=1,
                                                max_output_rows=max(args.candidate_count, 5),
                                            )
                                        except Exception as exc:
                                            error = str(exc)
                                            if "exceeds max rows" not in error:
                                                raise
                                            return {"rejected": True, "error": error}
                                        return {
                                            "rejected": False,
                                            "output_rows": int(result.get("output_rows") or 0),
                                        }

                                    funcs.append(recover_call)
                                mode_results.append(
                                    run_concurrent_safety_valve_batch(
                                        funcs,
                                        timeout_sec=args.timeout_sec,
                                        max_rows_per_request=max_rows_per_request,
                                    )
                                )
                        else:
                            raise SystemExit(f"[ERROR] unsupported benchmark mode: {mode}")

                        service_pid = service_pid_by_transport.get(transport_profile)
                        service_rss_kb = read_process_rss_kb(service_pid)
                        for item in mode_results:
                            item["service_pid"] = service_pid
                            item["service_rss_kb"] = service_rss_kb

                        results.append(
                            {
                                "mode": mode,
                                "transport": transport,
                                "operation": operation,
                                "command": mode_command,
                                "summary": summarize(mode_results),
                                "results": mode_results,
                                "service_startup_ms": startup_by_transport[transport_profile],
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
        g2b_summary = build_g2b_summary(
            results=results,
            candidate_count=args.candidate_count,
            concurrency=args.concurrency,
        )
        if g2b_summary is not None:
            report["g2b_summary"] = g2b_summary
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
