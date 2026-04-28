#!/usr/bin/env python3
"""Pipeline benchmark suite.

Measures:
  - Pipeline end-to-end latency
  - Record recovery latency
  - PJC execution latency
  - Stage-by-stage breakdown

All benchmarks call existing CLI scripts. No privacy-compute logic is rewritten.

Usage:
  python3 scripts/benchmark_pipeline.py run --iterations 3 --out-base tmp/benchmark
  python3 scripts/benchmark_pipeline.py report --benchmark-dir tmp/benchmark
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PIPELINE_SCRIPT = os.path.join(REPO_ROOT, "scripts", "run_sse_bridge_pipeline.sh")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_cmd(cmd: List[str], cwd: Optional[str] = None,
            env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    t0 = time.perf_counter()
    try:
        result = subprocess.run(
            cmd, cwd=cwd or REPO_ROOT, env=merged_env,
            capture_output=True, text=True, timeout=900,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
    except subprocess.TimeoutExpired:
        return {"success": False, "exit_code": -1, "stdout": "", "stderr": "timeout",
                "elapsed_ms": 900000}
    return {
        "success": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": result.stdout[:50000],
        "stderr": result.stderr[:50000],
        "elapsed_ms": elapsed_ms,
    }


def benchmark_pipeline(iteration: int, out_base: str, policy_config: str,
                       token_secret_env: str = "BRIDGE_TOKEN_SECRET") -> Dict[str, Any]:
    """Run a single iteration of the pipeline benchmark."""
    job_id = f"bench_{iteration}_{int(time.time())}"
    iter_out = os.path.join(out_base, f"iter_{iteration:03d}")
    os.makedirs(iter_out, exist_ok=True)

    server_source = os.path.join(REPO_ROOT, "sse", "examples", "bridge_server_records.jsonl")
    client_source = os.path.join(REPO_ROOT, "sse", "examples", "bridge_client_records.jsonl")

    cmd = [
        "bash", PIPELINE_SCRIPT,
        "--server-source", server_source,
        "--client-source", client_source,
        "--server-join-key-field", "email",
        "--client-join-key-field", "email",
        "--client-value-field", "amount",
        "--server-normalizer", "email",
        "--client-normalizer", "email",
        "--client-value-mode", "raw-int",
        "--server-filter", "campaign=demo",
        "--client-filter", "campaign=demo",
        "--token-scope", f"bench-scope-{job_id}",
        "--token-secret-env", token_secret_env,
        "--job-id", job_id,
        "--out-base", iter_out,
        "--caller", "benchmark",
        "--k", "1",
        "--n", "5",
    ]
    if policy_config and os.path.isfile(policy_config):
        cmd += ["--sse-export-policy-config", policy_config]

    t0 = time.perf_counter()
    result = run_cmd(cmd)
    total_ms = (time.perf_counter() - t0) * 1000

    manifest = {
        "schema": "benchmark_run/v1",
        "iteration": iteration,
        "job_id": job_id,
        "started_at_utc": utc_now_iso(),
        "total_elapsed_ms": total_ms,
        "success": result["success"],
        "exit_code": result["exit_code"],
        "out_dir": iter_out,
    }

    manifest_path = os.path.join(iter_out, "benchmark_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"  iter {iteration:03d}: {total_ms:.0f}ms {'OK' if result['success'] else 'FAIL'}")
    return manifest


def benchmark_record_recovery(out_base: str) -> Dict[str, Any]:
    """Benchmark encrypted record-store creation and recovery latency."""
    sse_py = os.path.join(REPO_ROOT, "sse", ".venv", "bin", "python")
    if not os.path.isfile(sse_py):
        return {"success": False, "reason": f"SSE python not found: {sse_py}"}

    sse_dir = os.path.join(REPO_ROOT, "sse")
    bench_dir = os.path.join(out_base, "record_recovery_bench")
    os.makedirs(bench_dir, exist_ok=True)

    results: Dict[str, Any] = {"stage": "record_recovery", "measurements": {}}

    # Create encrypted record store
    enc_path = os.path.join(bench_dir, "client_records.enc.jsonl")
    t0 = time.perf_counter()
    create_result = run_cmd([
        sse_py, "run_client.py", "create-encrypted-record-store",
        "--source-path", os.path.join(sse_dir, "examples", "bridge_client_records.jsonl"),
        "--out-path", enc_path,
        "--source-format", "jsonl",
        "--record-id-field", "email_hex",
        "--key-env", "SSE_RECORD_STORE_PASSPHRASE",
    ], cwd=sse_dir)
    create_ms = (time.perf_counter() - t0) * 1000
    results["measurements"]["create_encrypted_store_ms"] = create_ms
    results["create_ok"] = create_result["success"]

    # Export from encrypted store (subprocess recovery boundary)
    csv_path = os.path.join(bench_dir, "client_demo.csv")
    t0 = time.perf_counter()
    export_result = run_cmd([
        sse_py, "run_client.py", "export-bridge-records",
        "--out-path", csv_path,
        "--role", "client",
        "--source-format", "jsonl",
        "--out-format", "csv",
        "--join-key-field", "email",
        "--value-field", "amount",
        "--filter", "campaign=demo",
        "--caller", "benchmark",
        "--audit-log", os.path.join(bench_dir, "export_audit.jsonl"),
        "--job-id", f"recovery_bench_{int(time.time())}",
        "--sse-keyword", "demo",
        "--record-id-field", "email_hex",
        "--record-id-format", "hex",
        "--sname", "bridge_sse_demo",
        "--record-store-path", enc_path,
        "--record-store-key-env", "SSE_RECORD_STORE_PASSPHRASE",
        "--unsafe-allow-no-policy",
    ], cwd=sse_dir)
    export_ms = (time.perf_counter() - t0) * 1000
    results["measurements"]["recover_and_export_ms"] = export_ms
    results["export_ok"] = export_result["success"]

    results["success"] = create_result["success"] and export_result["success"]
    print(f"  record recovery: create={create_ms:.0f}ms export={export_ms:.0f}ms "
          f"{'OK' if results['success'] else 'FAIL'}")
    return results


def run_benchmarks(args: argparse.Namespace) -> int:
    out_base = os.path.abspath(args.out_base)
    os.makedirs(out_base, exist_ok=True)

    print(f"=== Pipeline Benchmark ({args.iterations} iterations) ===")
    print(f"Output: {out_base}")

    runs: List[Dict[str, Any]] = []
    for i in range(1, args.iterations + 1):
        run = benchmark_pipeline(
            i, out_base, args.policy_config, args.token_secret_env
        )
        runs.append(run)

    print(f"\n=== Record Recovery Benchmark ===")
    recovery = benchmark_record_recovery(out_base)

    # Aggregate
    successful = [r for r in runs if r.get("success")]
    elapsed = [r["total_elapsed_ms"] for r in successful]

    summary = {
        "schema": "benchmark_summary/v1",
        "generated_at_utc": utc_now_iso(),
        "iterations": args.iterations,
        "pipeline": {
            "success_count": len(successful),
            "fail_count": len(runs) - len(successful),
            "elapsed_ms": {
                "min": min(elapsed) if elapsed else None,
                "max": max(elapsed) if elapsed else None,
                "mean": statistics.mean(elapsed) if elapsed else None,
                "median": statistics.median(elapsed) if elapsed else None,
                "stdev": statistics.stdev(elapsed) if len(elapsed) > 1 else None,
                "p95": sorted(elapsed)[int(len(elapsed) * 0.95)] if len(elapsed) >= 20 else None,
            },
        },
        "record_recovery": recovery,
        "runs": runs,
    }

    summary_path = os.path.join(out_base, "benchmark_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\n=== Summary ===")
    pipe = summary["pipeline"]
    print(f"  Pipeline: {pipe['success_count']}/{args.iterations} successful")
    if elapsed:
        print(f"  Latency: min={pipe['elapsed_ms']['min']:.0f}ms "
              f"median={pipe['elapsed_ms']['median']:.0f}ms "
              f"max={pipe['elapsed_ms']['max']:.0f}ms")
        if pipe['elapsed_ms']['mean']:
            print(f"  Mean: {pipe['elapsed_ms']['mean']:.0f}ms "
                  f"Stdev: {pipe['elapsed_ms']['stdev']:.0f}ms")
    print(f"  Summary: {os.path.abspath(summary_path)}")
    return 0 if successful else 1


def generate_report(args: argparse.Namespace) -> int:
    summary_path = os.path.join(os.path.abspath(args.benchmark_dir), "benchmark_summary.json")
    if not os.path.isfile(summary_path):
        print(f"[ERROR] benchmark summary not found: {summary_path}", file=sys.stderr)
        return 1

    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    lines = [
        "# Pipeline Benchmark Report",
        "",
        f"**Generated**: {utc_now_iso()}  ",
        f"**Source**: `{summary_path}`  ",
        "",
        "## Pipeline Latency",
        "",
    ]

    pipe = summary.get("pipeline", {})
    e = pipe.get("elapsed_ms", {})
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Iterations | {summary.get('iterations', '?')} |")
    lines.append(f"| Successful | {pipe.get('success_count', '?')} |")
    lines.append(f"| Failed | {pipe.get('fail_count', '?')} |")
    lines.append(f"| Min | {e.get('min', 'N/A')} ms |")
    lines.append(f"| Max | {e.get('max', 'N/A')} ms |")
    lines.append(f"| Mean | {e.get('mean', 'N/A')} ms |")
    lines.append(f"| Median | {e.get('median', 'N/A')} ms |")
    lines.append(f"| Stdev | {e.get('stdev', 'N/A')} ms |")
    lines.append(f"| P95 | {e.get('p95', 'N/A')} ms |")
    lines.append("")

    recovery = summary.get("record_recovery", {})
    rec_m = recovery.get("measurements", {})
    if rec_m:
        lines.append("## Record Recovery Latency")
        lines.append("")
        lines.append(f"| Operation | Latency |")
        lines.append(f"|-----------|---------|")
        for name, ms in rec_m.items():
            lines.append(f"| {name} | {ms:.1f} ms |")
        lines.append("")

    lines.append("## Detailed Runs")
    lines.append("")
    lines.append(f"| Iter | Job ID | Latency | Status |")
    lines.append(f"|------|--------|---------|--------|")
    for run in summary.get("runs", []):
        status = "PASS" if run.get("success") else "FAIL"
        lines.append(f"| {run.get('iteration', '?')} | `{run.get('job_id', '?')}` | "
                     f"{run.get('total_elapsed_ms', 0):.0f}ms | {status} |")

    report = "\n".join(lines) + "\n"
    report_path = args.out or os.path.join(args.benchmark_dir, "BENCHMARK_REPORT.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[ok] benchmark report: {os.path.abspath(report_path)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Pipeline benchmark suite")
    sub = ap.add_subparsers(dest="command")

    run_ap = sub.add_parser("run", help="Run benchmarks")
    run_ap.add_argument("--iterations", type=int, default=3)
    run_ap.add_argument("--out-base", default="tmp/benchmark")
    run_ap.add_argument("--policy-config", default="")
    run_ap.add_argument("--token-secret-env", default="BRIDGE_TOKEN_SECRET")

    sub.add_parser("report", help="Generate benchmark report").add_argument(
        "--benchmark-dir", default="tmp/benchmark")
    sub.add_parser("report").add_argument("--out", default="")

    args = ap.parse_args()
    if args.command == "run":
        return run_benchmarks(args)
    elif args.command == "report":
        return generate_report(args)
    else:
        ap.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
