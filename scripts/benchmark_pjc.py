#!/usr/bin/env python3
import argparse
import json
import statistics
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime_service_helpers import available_port


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_PJC_SH = REPO_ROOT / "a-psi" / "moduleA_psi" / "scripts" / "run_pjc.sh"
DEFAULT_PJC_BIN_DIR = REPO_ROOT / "a-psi" / "private-join-and-compute" / "bazel-bin"
MODES = ("checked_in_sse_demo_job",)
EXPECTED_INTERSECTION_SIZE = 2
EXPECTED_INTERSECTION_SUM = 425


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


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def fixture_paths(mode: str) -> tuple[Path, Path]:
    if mode == "checked_in_sse_demo_job":
        base = REPO_ROOT / "bridge" / "out" / "sse_demo_job"
        return base / "server.csv", base / "client.csv"
    raise RuntimeError(f"unsupported PJC benchmark mode: {mode}")


def run_pjc_once(
    *,
    mode: str,
    iteration: int,
    pjc_bin_dir: Path,
    timeout_sec: float,
    server_csv: Path,
    client_csv: Path,
    expected_intersection_size: int,
    expected_intersection_sum: int,
) -> dict[str, Any]:
    if not server_csv.is_file() or not client_csv.is_file():
        raise RuntimeError(f"missing PJC benchmark fixture files for {mode}")

    with tempfile.TemporaryDirectory(prefix=f"seccomp_pjc_bench.{mode}.{iteration}.") as tmp_dir:
        out_dir = Path(tmp_dir) / "pjc_run"
        job_id = f"benchmark_pjc_{mode}_{iteration}"
        server_addr = f"127.0.0.1:{available_port()}"
        env = {
            **dict(subprocess.os.environ),
            "JOB_ID": job_id,
            "OUT_DIR": str(out_dir),
            "SERVER_CSV": str(server_csv),
            "CLIENT_CSV": str(client_csv),
            "PJC_BIN_DIR": str(pjc_bin_dir),
            "SERVER_ADDR": server_addr,
        }
        command = ["bash", str(RUN_PJC_SH)]
        started = time.perf_counter()
        try:
            result = subprocess.run(
                command,
                cwd=str(REPO_ROOT / "a-psi"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_sec,
                env=env,
            )
            timed_out = False
            exit_code = result.returncode
            stderr_tail = "\n".join(result.stderr.splitlines()[-20:]) if result.stderr else ""
            stdout_tail = "\n".join(result.stdout.splitlines()[-20:]) if result.stdout else ""
        except subprocess.TimeoutExpired as exc:
            duration_ms = (time.perf_counter() - started) * 1000
            return {
                "duration_ms": round(duration_ms, 3),
                "exit_code": 124,
                "timed_out": True,
                "stderr_tail": str(exc),
                "stdout_tail": "",
                "intersection_size": None,
                "intersection_sum": None,
                "result_file": None,
            }

        duration_ms = (time.perf_counter() - started) * 1000
        if exit_code != 0:
            return {
                "duration_ms": round(duration_ms, 3),
                "exit_code": exit_code,
                "timed_out": timed_out,
                "stderr_tail": stderr_tail,
                "stdout_tail": stdout_tail,
                "intersection_size": None,
                "intersection_sum": None,
                "result_file": None,
            }

        result_path = out_dir / "attribution_result.json"
        if not result_path.is_file():
            return {
                "duration_ms": round(duration_ms, 3),
                "exit_code": 1,
                "timed_out": False,
                "stderr_tail": f"missing PJC result file: {result_path}",
                "stdout_tail": stdout_tail,
                "intersection_size": None,
                "intersection_sum": None,
                "result_file": None,
            }

        metrics = read_json(result_path)
        intersection_size = int(metrics.get("intersection_size"))
        intersection_sum = int(metrics.get("intersection_sum"))
        if intersection_size != expected_intersection_size or intersection_sum != expected_intersection_sum:
            return {
                "duration_ms": round(duration_ms, 3),
                "exit_code": 1,
                "timed_out": False,
                "stderr_tail": (
                    f"unexpected PJC result: intersection_size={intersection_size}, "
                    f"intersection_sum={intersection_sum}"
                ),
                "stdout_tail": stdout_tail,
                "intersection_size": intersection_size,
                "intersection_sum": intersection_sum,
                "result_file": str(result_path),
            }

        return {
            "duration_ms": round(duration_ms, 3),
            "exit_code": 0,
            "timed_out": False,
            "stderr_tail": stderr_tail,
            "stdout_tail": stdout_tail,
            "intersection_size": intersection_size,
            "intersection_sum": intersection_sum,
            "result_file": str(result_path),
        }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Benchmark the existing PJC runner against prepared bridge job inputs.")
    ap.add_argument("--iterations", type=int, default=1)
    ap.add_argument("--mode", choices=("all",) + MODES, default="all")
    ap.add_argument("--timeout-sec", type=float, default=180.0)
    ap.add_argument("--server-csv", default="")
    ap.add_argument("--client-csv", default="")
    ap.add_argument("--expected-intersection-size", type=int, default=EXPECTED_INTERSECTION_SIZE)
    ap.add_argument("--expected-intersection-sum", type=int, default=EXPECTED_INTERSECTION_SUM)
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-failures", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.iterations <= 0:
        raise SystemExit("[ERROR] --iterations must be positive")
    if args.timeout_sec <= 0:
        raise SystemExit("[ERROR] --timeout-sec must be positive")
    if args.expected_intersection_size < 0 or args.expected_intersection_sum < 0:
        raise SystemExit("[ERROR] expected intersection metrics must be non-negative")

    pjc_bin_dir = Path(subprocess.os.environ.get("PJC_BIN_DIR", str(DEFAULT_PJC_BIN_DIR)))
    if not pjc_bin_dir.is_dir():
        raise SystemExit(f"[ERROR] PJC_BIN_DIR does not exist: {pjc_bin_dir}")
    if not RUN_PJC_SH.is_file():
        raise SystemExit(f"[ERROR] missing PJC runner script: {RUN_PJC_SH}")

    selected_modes = list(MODES) if args.mode == "all" else [args.mode]
    mode_entries: list[dict[str, Any]] = []
    for mode in selected_modes:
        default_server_csv, default_client_csv = fixture_paths(mode)
        server_csv = Path(args.server_csv).expanduser() if args.server_csv else default_server_csv
        client_csv = Path(args.client_csv).expanduser() if args.client_csv else default_client_csv
        mode_results = [
            run_pjc_once(
                mode=mode,
                iteration=iteration,
                pjc_bin_dir=pjc_bin_dir,
                timeout_sec=args.timeout_sec,
                server_csv=server_csv,
                client_csv=client_csv,
                expected_intersection_size=args.expected_intersection_size,
                expected_intersection_sum=args.expected_intersection_sum,
            )
            for iteration in range(args.iterations)
        ]
        mode_entries.append(
            {
                "mode": mode,
                "command": ["bash", str(RUN_PJC_SH)],
                "input_fixture": {
                    "server_csv": str(server_csv),
                    "client_csv": str(client_csv),
                },
                "summary": summarize(mode_results),
                "results": mode_results,
            }
        )

    report = {
        "schema": "pjc_benchmark/v1",
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "pjc_bin_dir": str(pjc_bin_dir),
        "expected_result": {
            "intersection_size": args.expected_intersection_size,
            "intersection_sum": args.expected_intersection_sum,
        },
        "iterations": args.iterations,
        "modes": mode_entries,
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
    failures = sum(item["summary"]["failed_iterations"] for item in mode_entries)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
