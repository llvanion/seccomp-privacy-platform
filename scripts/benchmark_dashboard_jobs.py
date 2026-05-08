#!/usr/bin/env python3
import argparse
import gc
import json
import statistics
import sys
import threading
import time
import tracemalloc
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime_service_helpers import available_port  # noqa: E402
import serve_operator_dashboard as dashboard  # noqa: E402


SCHEMA_ID = "dashboard_jobs_benchmark/v1"
NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


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


def duration_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "min": round(min(values), 3) if values else None,
        "mean": round(statistics.fmean(values), 3) if values else None,
        "p50": round(percentile(values, 0.50), 3) if values else None,
        "p95": round(percentile(values, 0.95), 3) if values else None,
        "max": round(max(values), 3) if values else None,
    }


def post_json(url: str, payload: dict[str, Any], *, timeout_sec: float) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with NO_PROXY_OPENER.open(request, timeout=timeout_sec) as response:
            raw = response.read()
            status = int(response.status)
            response_payload = json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = int(exc.code)
        response_payload = json.loads(raw.decode("utf-8")) if raw else {}
    return {
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "status_code": status,
        "response": response_payload if isinstance(response_payload, dict) else {},
    }


def get_json(url: str, *, timeout_sec: float) -> dict[str, Any]:
    started = time.perf_counter()
    with NO_PROXY_OPENER.open(url, timeout=timeout_sec) as response:
        raw = response.read()
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    return {
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "status_code": int(response.status),
        "response": payload if isinstance(payload, dict) else {},
    }


def build_request(*, index: int, out_base: Path, tenant_id: str) -> dict[str, Any]:
    return {
        "schema": "query_workflow_request/v1",
        "query_type": "cross_party_match",
        "server_source": str(REPO_ROOT / "sse/examples/bridge_server_records.jsonl"),
        "client_source": str(REPO_ROOT / "sse/examples/bridge_client_records.jsonl"),
        "server_join_key_field": "email",
        "client_join_key_field": "email",
        "client_value_field": "amount",
        "server_normalizer": "email",
        "client_normalizer": "email",
        "client_value_mode": "raw-int",
        "server_filters": ["campaign=demo"],
        "client_filters": ["campaign=demo"],
        "token_scope": f"dashboard-benchmark-{index}",
        "token_secret_env": "BRIDGE_TOKEN_SECRET",
        "job_id": f"dashboard_benchmark_job_{index}",
        "out_base": str(out_base),
        "caller": "auto_demo",
        "tenant_id": tenant_id,
        "dataset_id": "bridge_demo_dataset",
        "k": 1,
        "n": 5,
        "sse_export_policy_config": str(REPO_ROOT / "sse/config/export_policy.example.json"),
        "deny_duplicate_query": False,
        "sse_export_handoff_mode": "fifo",
        "cleanup_sse_export_handoff_files_after_bridge": True,
    }


def install_fake_runner(*, runtime_sec: float) -> Any:
    original = dashboard._start_job_thread

    def fake_start_job_thread(server: dashboard.DashboardServer, *, payload: dict[str, Any], request_source: str, request_dir: Path) -> None:
        normalized = dashboard.normalize_request_paths(payload, request_dir=request_dir)
        dashboard.validate_request(normalized)
        now = dashboard._utc_now()
        out_base = Path(str(normalized["out_base"])).resolve()
        job_id = str(normalized.get("job_id") or "")
        job_record = {
            "job_id": job_id,
            "tenant_id": dashboard._normalized_tenant_id(normalized),
            "state": "running",
            "terminal": False,
            "started_at_utc": now,
            "finished_at_utc": None,
            "last_updated_at_utc": now,
            "last_exit_code": None,
            "out_base": str(out_base),
            "request_source": request_source,
        }
        out_base.mkdir(parents=True, exist_ok=True)
        server.out_base = out_base
        server.set_job(job_record)

        def runner() -> None:
            time.sleep(runtime_sec)
            finished_at = dashboard._utc_now()
            server.set_job(
                {
                    **job_record,
                    "state": "completed",
                    "terminal": True,
                    "finished_at_utc": finished_at,
                    "last_updated_at_utc": finished_at,
                    "last_exit_code": 0,
                }
            )

        threading.Thread(target=runner, daemon=True).start()

    dashboard._start_job_thread = fake_start_job_thread
    return original


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="seccomp_dashboard_jobs_bench.") as tmp_dir:
        root = Path(tmp_dir)
        out_base = root / "selected"
        out_base.mkdir(parents=True, exist_ok=True)
        tenant_id = "dashboard_benchmark_tenant"
        port = available_port()
        server = dashboard.DashboardServer(
            ("127.0.0.1", port),
            dashboard.DashboardHandler,
            out_base=out_base,
            history_root=root,
            history_limit=max(args.concurrency, 1),
            pid_file="",
            ready_file="",
            max_concurrent_jobs_per_tenant=args.concurrency,
        )
        original_runner = install_fake_runner(runtime_sec=args.job_runtime_sec)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{port}"
        try:
            get_json(f"{base_url}/healthz", timeout_sec=args.timeout_sec)
            gc.collect()
            tracemalloc.start()
            before_current, before_peak = tracemalloc.get_traced_memory()
            start_payloads = [
                {"request": build_request(index=index, out_base=root / f"job_{index}", tenant_id=tenant_id)}
                for index in range(args.concurrency)
            ]
            with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                futures = [
                    executor.submit(post_json, f"{base_url}/v1/jobs/start", payload, timeout_sec=args.timeout_sec)
                    for payload in start_payloads
                ]
                start_results = [future.result() for future in as_completed(futures)]

            dashboard_results = [
                get_json(f"{base_url}/v1/dashboard", timeout_sec=args.timeout_sec)
                for _ in range(args.dashboard_reads)
            ]

            deadline = time.monotonic() + args.timeout_sec
            while time.monotonic() < deadline:
                active = server.active_jobs_for_tenant(tenant_id)
                if active == 0:
                    break
                time.sleep(0.05)
            gc.collect()
            after_current, after_peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        finally:
            dashboard._start_job_thread = original_runner
            server.shutdown()
            server.server_close()
            thread.join(timeout=2.0)

    start_latencies = [float(item["duration_ms"]) for item in start_results]
    dashboard_latencies = [float(item["duration_ms"]) for item in dashboard_results]
    accepted = sum(1 for item in start_results if item.get("status_code") == 202)
    rejected = len(start_results) - accepted
    dashboard_ok = sum(1 for item in dashboard_results if item.get("status_code") == 200)
    current_growth_kb = max(0.0, (after_current - before_current) / 1024.0)
    peak_growth_kb = max(0.0, (after_peak - before_peak) / 1024.0)
    current_growth_per_job_kb = current_growth_kb / max(args.concurrency, 1)
    dashboard_p95 = percentile(dashboard_latencies, 0.95)
    memory_passed = current_growth_per_job_kb <= args.max_memory_growth_kb_per_job
    dashboard_passed = dashboard_p95 is not None and dashboard_p95 < args.dashboard_p95_threshold_ms
    return {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "mode": "inprocess_http_fake_runner",
        "configuration": {
            "concurrency": args.concurrency,
            "dashboard_reads": args.dashboard_reads,
            "job_runtime_sec": args.job_runtime_sec,
            "dashboard_p95_threshold_ms": args.dashboard_p95_threshold_ms,
            "max_memory_growth_kb_per_job": args.max_memory_growth_kb_per_job,
        },
        "summary": {
            "status": "ok" if accepted == args.concurrency and rejected == 0 and dashboard_ok == args.dashboard_reads and dashboard_passed and memory_passed else "fail",
            "accepted_jobs": accepted,
            "rejected_jobs": rejected,
            "dashboard_ok_reads": dashboard_ok,
            "dashboard_p95_ms": round(dashboard_p95, 3) if dashboard_p95 is not None else None,
            "dashboard_p95_passed": dashboard_passed,
            "memory_growth_current_kb": round(current_growth_kb, 3),
            "memory_growth_peak_kb": round(peak_growth_kb, 3),
            "memory_growth_per_job_kb": round(current_growth_per_job_kb, 3),
            "memory_leak_check_passed": memory_passed,
        },
        "start_requests": {
            "duration_ms": duration_summary(start_latencies),
            "results": [
                {
                    "duration_ms": item["duration_ms"],
                    "status_code": item["status_code"],
                    "job_id": item.get("response", {}).get("job_id"),
                    "state": item.get("response", {}).get("state"),
                }
                for item in sorted(start_results, key=lambda row: str(row.get("response", {}).get("job_id") or ""))
            ],
        },
        "dashboard_reads": {
            "duration_ms": duration_summary(dashboard_latencies),
            "results": [
                {
                    "duration_ms": item["duration_ms"],
                    "status_code": item["status_code"],
                    "overall_status": item.get("response", {}).get("overall_status"),
                    "job_control_state": (item.get("response", {}).get("job_control") or {}).get("state"),
                }
                for item in dashboard_results
            ],
        },
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Benchmark concurrent operator-dashboard job starts and dashboard reads.")
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--dashboard-reads", type=int, default=10)
    ap.add_argument("--job-runtime-sec", type=float, default=0.5)
    ap.add_argument("--timeout-sec", type=float, default=10.0)
    ap.add_argument("--dashboard-p95-threshold-ms", type=float, default=2000.0)
    ap.add_argument("--max-memory-growth-kb-per-job", type=float, default=1024.0)
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-failures", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.concurrency <= 0:
        raise SystemExit("[ERROR] --concurrency must be positive")
    if args.dashboard_reads <= 0:
        raise SystemExit("[ERROR] --dashboard-reads must be positive")
    if args.job_runtime_sec < 0:
        raise SystemExit("[ERROR] --job-runtime-sec must be non-negative")
    report = run_benchmark(args)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = REPO_ROOT / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.allow_failures:
        return 0
    return 0 if report.get("summary", {}).get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
