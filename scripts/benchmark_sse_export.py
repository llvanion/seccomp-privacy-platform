#!/usr/bin/env python3
import argparse
import csv
import json
import os
import resource
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SSE_DIR = REPO_ROOT / "sse"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SSE_DIR) not in sys.path:
    sys.path.insert(0, str(SSE_DIR))

# The SSE client module initializes a per-user config directory at import
# time. Keep benchmark imports self-contained in restricted CI/sandbox users.
BENCHMARK_HOME = Path(os.environ.get("SECCOMP_BENCHMARK_HOME", "/tmp/seccomp_benchmark_home")).resolve()
BENCHMARK_HOME.mkdir(parents=True, exist_ok=True)
os.environ["HOME"] = str(BENCHMARK_HOME)

from services.record_recovery.encrypted_record_store import build_record_store  # noqa: E402
from frontend.client.commands import export_bridge_records  # noqa: E402
from scripts.generate_benchmark_dataset import generate_order_record  # noqa: E402


SCHEMA_ID = "sse_export_benchmark/v1"
FIXTURE_PROFILE = "synthetic_ecommerce_orders_v1"
KEY_ENV = "SSE_RECORD_STORE_PASSPHRASE"


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
    throughputs = [
        float(item["throughput_records_per_sec"])
        for item in results
        if item.get("exit_code") == 0 and isinstance(item.get("throughput_records_per_sec"), (int, float))
    ]
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
        "throughput_records_per_sec": {
            "mean": round(statistics.fmean(throughputs), 3) if throughputs else None,
            "p50": round(percentile(throughputs, 0.50), 3) if throughputs else None,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_policy(path: Path, *, max_export_rows: int) -> None:
    payload = {
        "schema": "sse_export_policy/v1",
        "callers": {
            "auto_demo": {
                "enabled": True,
                "tenant_id": "demo_tenant",
                "allowed_dataset_ids": ["bridge_demo_dataset"],
                "allowed_service_ids": ["bridge-demo-recovery"],
                "allowed_roles": ["server", "client"],
                "allowed_fields": ["email", "amount"],
                "allowed_join_key_fields": ["email"],
                "allowed_value_fields": ["amount"],
                "allowed_filter_fields": ["campaign"],
                "required_filters": ["campaign"],
                "allowed_filter_values": {"campaign": ["demo"]},
                "max_export_rows": max_export_rows,
                "min_export_rows": 1,
                "can_use_record_recovery_service": True,
                "can_run_bridge": True,
                "can_run_pjc": True,
                "can_release": True,
            }
        },
    }
    write_json(path, payload)


def generate_orders(path: Path, *, count: int, seed: int) -> float:
    import random

    rng = random.Random(seed)
    started = time.perf_counter()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for index in range(count):
            handle.write(json.dumps(generate_order_record(index, rng=rng, campaign="demo"), separators=(",", ":")) + "\n")
    return round((time.perf_counter() - started) * 1000, 3)


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def build_store(source_path: Path, store_path: Path, *, key_env: str) -> tuple[int, float]:
    started = time.perf_counter()
    count = build_record_store(
        rows=iter_jsonl(source_path),
        out_path=store_path,
        record_id_field="record_id",
        key_env=key_env,
    )
    return count, round((time.perf_counter() - started) * 1000, 3)


def read_audit_last(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    last: dict[str, Any] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    last = payload
    return last


def count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def current_peak_rss_kb() -> int:
    return max(
        int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss),
    )


def run_export_once(
    *,
    iteration: int,
    run_root: Path,
    store_path: Path,
    policy_path: Path,
    env: dict[str, str],
    candidate_count: int,
    timeout_sec: float,
) -> dict[str, Any]:
    out_path = run_root / f"export_{iteration}.csv"
    audit_path = run_root / f"export_{iteration}.audit.jsonl"
    candidate_ids = {f"ORD-{index:08d}" for index in range(candidate_count)}
    started = time.perf_counter()
    try:
        original = os.environ.get(KEY_ENV)
        os.environ[KEY_ENV] = env[KEY_ENV]
        try:
            export_bridge_records(
                source_path="",
                out_path=str(out_path),
                role="client",
                source_format="jsonl",
                out_format="csv",
                join_key_field="email",
                value_field="amount",
                filters=["campaign=demo"],
                caller="auto_demo",
                policy_config=str(policy_path),
                audit_log=str(audit_path),
                job_id=f"benchmark-sse-export-{iteration}",
                unsafe_allow_no_policy=False,
                candidate_ids=candidate_ids,
                record_id_field="record_id",
                candidate_source="benchmark_candidate_set",
                tenant_id="demo_tenant",
                dataset_id="bridge_demo_dataset",
                record_store_path=str(store_path),
                record_store_key_env=KEY_ENV,
            )
        finally:
            if original is None:
                os.environ.pop(KEY_ENV, None)
            else:
                os.environ[KEY_ENV] = original
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        if duration_ms > timeout_sec * 1000:
            raise TimeoutError(f"export exceeded timeout: {duration_ms}ms > {timeout_sec * 1000}ms")
        output_rows = count_csv_rows(out_path)
        audit = read_audit_last(audit_path)
        exit_code = 0
        timed_out = False
        stderr_tail = ""
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        output_rows = None
        audit = read_audit_last(audit_path)
        exit_code = 124 if isinstance(exc, TimeoutError) else 1
        timed_out = isinstance(exc, TimeoutError)
        stderr_tail = str(exc)
    throughput = None
    if output_rows is not None and duration_ms > 0:
        throughput = round(output_rows / (duration_ms / 1000.0), 3)
    return {
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stderr_tail": stderr_tail,
        "input_rows": audit.get("input_rows"),
        "output_rows": output_rows,
        "candidate_count": audit.get("candidate_count"),
        "audit_decision": audit.get("decision"),
        "audit_duration_ms": audit.get("duration_ms"),
        "record_recovery_boundary": audit.get("record_recovery_boundary"),
        "throughput_records_per_sec": throughput,
        "peak_rss_kb": current_peak_rss_kb(),
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Benchmark SSE export throughput over an encrypted synthetic order record store.")
    ap.add_argument("--record-count", type=int, default=1000)
    ap.add_argument("--candidate-count", type=int, default=0, help="Defaults to --record-count")
    ap.add_argument("--iterations", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--timeout-sec", type=float, default=120.0)
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-failures", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.record_count <= 0:
        raise SystemExit("[ERROR] --record-count must be positive")
    candidate_count = args.candidate_count or args.record_count
    if candidate_count <= 0:
        raise SystemExit("[ERROR] --candidate-count must be positive")
    if candidate_count > args.record_count:
        raise SystemExit("[ERROR] --candidate-count cannot exceed --record-count")
    if args.iterations <= 0:
        raise SystemExit("[ERROR] --iterations must be positive")
    if args.timeout_sec <= 0:
        raise SystemExit("[ERROR] --timeout-sec must be positive")

    env = dict(os.environ)
    env.setdefault(KEY_ENV, "benchmark-sse-export-passphrase")
    original = os.environ.get(KEY_ENV)
    os.environ[KEY_ENV] = env[KEY_ENV]
    try:
        with tempfile.TemporaryDirectory(prefix="seccomp_sse_export_bench.") as tmp_dir:
            run_root = Path(tmp_dir)
            source_path = run_root / "orders.jsonl"
            store_path = run_root / "orders.enc.jsonl"
            policy_path = run_root / "export_policy.json"
            generation_ms = generate_orders(source_path, count=args.record_count, seed=args.seed)
            store_count, store_build_ms = build_store(source_path, store_path, key_env=KEY_ENV)
            write_policy(policy_path, max_export_rows=max(candidate_count, 1))
            results = [
                run_export_once(
                    iteration=iteration,
                    run_root=run_root,
                    store_path=store_path,
                    policy_path=policy_path,
                    env=env,
                    candidate_count=candidate_count,
                    timeout_sec=args.timeout_sec,
                )
                for iteration in range(args.iterations)
            ]
            report = {
                "schema": SCHEMA_ID,
                "generated_at_utc": utc_now_iso(),
                "repo_root": str(REPO_ROOT),
                "fixture_profile": FIXTURE_PROFILE,
                "scale": {
                    "record_count": args.record_count,
                    "candidate_count": candidate_count,
                    "store_record_count": store_count,
                },
                "setup": {
                    "generation_ms": generation_ms,
                    "store_build_ms": store_build_ms,
                    "source_path": str(source_path),
                    "store_path": str(store_path),
                },
                "mode": "encrypted_record_store_worker",
                "iterations": args.iterations,
                "summary": summarize(results),
                "results": results,
            }
    finally:
        if original is None:
            os.environ.pop(KEY_ENV, None)
        else:
            os.environ[KEY_ENV] = original

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
    return 1 if report["summary"]["failed_iterations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
