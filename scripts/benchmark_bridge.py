#!/usr/bin/env python3
import argparse
import json
import os
import resource
import shlex
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_DIR = REPO_ROOT / "bridge"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_benchmark_dataset import generate_order_record  # noqa: E402

SCHEMA_ID = "bridge_benchmark/v1"
FIXTURE_PROFILE = "synthetic_ecommerce_orders_v1"
MODES = ("prepare_job_jsonl",)
TOKEN_SECRET_ENV = "BRIDGE_TOKEN_SECRET"


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
    throughputs = [
        float(item["throughput_rows_per_sec"])
        for item in results
        if item.get("exit_code") == 0 and isinstance(item.get("throughput_rows_per_sec"), (int, float))
    ]
    return {
        "iterations": len(results),
        "successful_iterations": len(durations),
        "failed_iterations": sum(1 for item in results if item.get("exit_code") != 0),
        "duration_ms": {
            "min": round(min(durations), 3) if durations else None,
            "mean": round(statistics.fmean(durations), 3) if durations else None,
            "p50": round(percentile(durations, 0.50), 3) if durations else None,
            "p95": round(percentile(durations, 0.95), 3) if durations else None,
            "max": round(max(durations), 3) if durations else None,
        },
        "throughput_rows_per_sec": {
            "mean": round(statistics.fmean(throughputs), 3) if throughputs else None,
            "p50": round(percentile(throughputs, 0.50), 3) if throughputs else None,
        },
    }


def derive_phase_hotspots(results: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    totals: dict[str, float] = {}
    for item in results:
        if item.get("exit_code") != 0:
            continue
        timings = item.get("phase_timings_ms")
        if not isinstance(timings, dict):
            continue
        for phase, value in timings.items():
            if isinstance(value, (int, float)):
                totals[str(phase)] = totals.get(str(phase), 0.0) + float(value)

    total_ms = sum(totals.values())
    if total_ms <= 0:
        return []
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    return [
        {
            "rank": index + 1,
            "symbol": phase,
            "percent": round((duration_ms / total_ms) * 100.0, 3),
        }
        for index, (phase, duration_ms) in enumerate(ranked[:limit])
    ]


def default_bridge_command() -> list[str]:
    override = os.environ.get("BRIDGE_BIN", "").strip()
    if override:
        return shlex.split(override)
    return ["cargo", "run", "--quiet", "--"]


def write_orders_jsonl(path: Path, *, count: int, seed: int, campaign: str) -> float:
    import random

    rng = random.Random(seed)
    started = time.perf_counter()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for index in range(count):
            handle.write(
                json.dumps(
                    generate_order_record(index, rng=rng, campaign=campaign),
                    separators=(",", ":"),
                )
                + "\n"
            )
    return round((time.perf_counter() - started) * 1000, 3)


def line_count(path: Path) -> int | None:
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


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


def current_peak_rss_kb() -> int:
    return max(
        int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss),
    )


def build_prepare_job_command(
    *,
    bridge_cmd: list[str],
    server_jsonl: Path,
    client_jsonl: Path,
    out_dir: Path,
    audit_log: Path,
    job_id: str,
    token_scope: str,
) -> list[str]:
    return [
        *bridge_cmd,
        "prepare-job",
        "--server-input",
        str(server_jsonl),
        "--server-input-format",
        "jsonl",
        "--server-join-key-column",
        "email",
        "--server-normalizer",
        "email",
        "--client-input",
        str(client_jsonl),
        "--client-input-format",
        "jsonl",
        "--client-join-key-column",
        "email",
        "--client-value-column",
        "amount",
        "--client-value-mode",
        "raw-int",
        "--client-value-max",
        "1000000",
        "--client-allowed-value-column",
        "amount",
        "--client-value-unit",
        "minor_currency_unit",
        "--client-value-currency",
        "USD",
        "--client-normalizer",
        "email",
        "--job-id",
        job_id,
        "--token-scope",
        token_scope,
        "--token-secret-env",
        TOKEN_SECRET_ENV,
        "--out-dir",
        str(out_dir),
        "--audit-log",
        str(audit_log),
        "--production-mode",
    ]


def run_prepare_job_once(
    *,
    iteration: int,
    bridge_cmd: list[str],
    server_jsonl: Path,
    client_jsonl: Path,
    run_root: Path,
    timeout_sec: float,
) -> dict[str, Any]:
    out_dir = run_root / f"bridge_job_{iteration}"
    audit_log = run_root / f"bridge_job_{iteration}.audit.jsonl"
    job_id = f"benchmark_bridge_prepare_job_{iteration}"
    command = build_prepare_job_command(
        bridge_cmd=bridge_cmd,
        server_jsonl=server_jsonl,
        client_jsonl=client_jsonl,
        out_dir=out_dir,
        audit_log=audit_log,
        job_id=job_id,
        token_scope=job_id,
    )
    env = dict(os.environ)
    env.setdefault(TOKEN_SECRET_ENV, "benchmark-bridge-token-secret")
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=str(BRIDGE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_sec,
            env=env,
        )
        exit_code = result.returncode
        timed_out = False
        stderr_tail = "\n".join(result.stderr.splitlines()[-20:]) if result.stderr else ""
        stdout_tail = "\n".join(result.stdout.splitlines()[-20:]) if result.stdout else ""
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        timed_out = True
        stderr_tail = str(exc)
        stdout_tail = ""
    duration_ms = round((time.perf_counter() - started) * 1000, 3)
    audit = read_audit_last(audit_log)
    meta = read_json(out_dir / "job_meta.json")
    counts = meta.get("counts") if isinstance(meta.get("counts"), dict) else {}
    input_rows = int(counts.get("server_input_rows") or 0) + int(counts.get("client_input_rows") or 0)
    throughput = round(input_rows / (duration_ms / 1000.0), 3) if exit_code == 0 and duration_ms > 0 else None
    return {
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stderr_tail": stderr_tail,
        "stdout_tail": stdout_tail,
        "server_input_rows": counts.get("server_input_rows"),
        "client_input_rows": counts.get("client_input_rows"),
        "server_unique_join_tokens": counts.get("server_unique_join_tokens"),
        "client_unique_join_tokens": counts.get("client_unique_join_tokens"),
        "server_output_rows": line_count(out_dir / "server.csv"),
        "client_output_rows": line_count(out_dir / "client.csv"),
        "audit_decision": audit.get("decision"),
        "audit_duration_ms": audit.get("duration_ms"),
        "phase_timings_ms": audit.get("phase_timings_ms") if isinstance(audit.get("phase_timings_ms"), dict) else {},
        "production_mode": audit.get("production_mode"),
        "token_secret_source_kind": (audit.get("token_secret_source") or {}).get("kind"),
        "throughput_rows_per_sec": throughput,
        "peak_rss_kb": current_peak_rss_kb(),
        "job_meta_file": str(out_dir / "job_meta.json") if (out_dir / "job_meta.json").is_file() else None,
        "audit_log": str(audit_log) if audit_log.is_file() else None,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Benchmark the Rust bridge prepare-job path over synthetic JSONL inputs.")
    ap.add_argument("--server-rows", type=int, default=1000)
    ap.add_argument("--client-rows", type=int, default=1000)
    ap.add_argument("--iterations", type=int, default=1)
    ap.add_argument("--mode", choices=("all",) + MODES, default="all")
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--timeout-sec", type=float, default=120.0)
    ap.add_argument("--bridge-bin", default="", help="Command prefix for the bridge binary; defaults to BRIDGE_BIN or cargo run.")
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-failures", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.server_rows <= 0 or args.client_rows <= 0:
        raise SystemExit("[ERROR] --server-rows and --client-rows must be positive")
    if args.iterations <= 0:
        raise SystemExit("[ERROR] --iterations must be positive")
    if args.timeout_sec <= 0:
        raise SystemExit("[ERROR] --timeout-sec must be positive")

    bridge_cmd = shlex.split(args.bridge_bin) if args.bridge_bin else default_bridge_command()
    selected_modes = list(MODES) if args.mode == "all" else [args.mode]
    with tempfile.TemporaryDirectory(prefix="seccomp_bridge_bench.") as tmp_dir:
        run_root = Path(tmp_dir)
        server_jsonl = run_root / "server_orders.jsonl"
        client_jsonl = run_root / "client_orders.jsonl"
        server_generation_ms = write_orders_jsonl(server_jsonl, count=args.server_rows, seed=args.seed, campaign="demo")
        client_generation_ms = write_orders_jsonl(
            client_jsonl,
            count=args.client_rows,
            seed=args.seed + 1,
            campaign="demo",
        )
        mode_entries: list[dict[str, Any]] = []
        for mode in selected_modes:
            results = [
                run_prepare_job_once(
                    iteration=iteration,
                    bridge_cmd=bridge_cmd,
                    server_jsonl=server_jsonl,
                    client_jsonl=client_jsonl,
                    run_root=run_root,
                    timeout_sec=args.timeout_sec,
                )
                for iteration in range(args.iterations)
            ]
            phase_hotspots = derive_phase_hotspots(results)
            mode_entries.append(
                {
                    "mode": mode,
                    "command": build_prepare_job_command(
                        bridge_cmd=bridge_cmd,
                        server_jsonl=server_jsonl,
                        client_jsonl=client_jsonl,
                        out_dir=Path("/tmp/seccomp_bridge_benchmark_example/out"),
                        audit_log=Path("/tmp/seccomp_bridge_benchmark_example/bridge_audit.jsonl"),
                        job_id="benchmark_bridge_prepare_job_example",
                        token_scope="benchmark_bridge_prepare_job_example",
                    ),
                    "input_fixture": {
                        "server_jsonl": str(server_jsonl),
                        "client_jsonl": str(client_jsonl),
                    },
                    "summary": summarize(results),
                    "results": results,
                    "profile_hotspots": phase_hotspots,
                }
            )
        report = {
            "schema": SCHEMA_ID,
            "generated_at_utc": utc_now_iso(),
            "repo_root": str(REPO_ROOT),
            "bridge_cwd": str(BRIDGE_DIR),
            "fixture_profile": FIXTURE_PROFILE,
            "scale": {
                "server_rows": args.server_rows,
                "client_rows": args.client_rows,
            },
            "setup": {
                "server_generation_ms": server_generation_ms,
                "client_generation_ms": client_generation_ms,
                "server_jsonl": str(server_jsonl),
                "client_jsonl": str(client_jsonl),
            },
            "profile": {
                "method": "bridge_internal_phase_timing" if any(
                    entry["profile_hotspots"] for entry in mode_entries
                ) else "external_flamegraph_optional",
                "top_hotspots": next(
                    (entry["profile_hotspots"] for entry in mode_entries if entry["profile_hotspots"]),
                    [],
                ),
                "notes": "Top hotspots are derived from bridge audit phase timings. Run cargo flamegraph/perf externally for symbol-level CPU stacks when the host allows it.",
            },
            "iterations": args.iterations,
            "modes": [
                {key: value for key, value in entry.items() if key != "profile_hotspots"}
                for entry in mode_entries
            ],
        }

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
    failures = sum(item["summary"]["failed_iterations"] for item in report["modes"])
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
