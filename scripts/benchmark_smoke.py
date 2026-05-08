#!/usr/bin/env python3
import argparse
import json
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

TARGETS = {
    "dependency-hygiene": ["python3", "scripts/check_dependency_hygiene.py"],
    "hygiene": ["python3", "scripts/scan_repo_hygiene.py"],
    "schema-backcompat": ["python3", "scripts/check_schema_backcompat.py"],
    "contracts": ["bash", "scripts/check_json_contracts.sh"],
    "ci-smoke": ["bash", "scripts/check_ci_smoke.sh"],
    "sse-export-scale": ["python3", "scripts/benchmark_sse_export.py"],
}


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


def command_for_target(target: str, *, scale: int) -> list[str]:
    try:
        command = list(TARGETS[target])
    except KeyError as e:
        raise ValueError(f"unsupported benchmark target: {target}") from e
    if target == "sse-export-scale":
        command.extend(["--record-count", str(scale), "--candidate-count", str(scale), "--iterations", "1"])
    return command


def run_once(command: list[str], *, timeout_sec: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_sec,
        )
        timed_out = False
        return_code = result.returncode
        stderr_tail = "\n".join(result.stderr.splitlines()[-20:]) if result.stderr else ""
    except subprocess.TimeoutExpired as e:
        timed_out = True
        return_code = 124
        stderr_tail = str(e)
    duration_ms = (time.perf_counter() - started) * 1000
    return {
        "duration_ms": round(duration_ms, 3),
        "exit_code": return_code,
        "timed_out": timed_out,
        "stderr_tail": stderr_tail,
    }


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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Benchmark existing smoke-check entrypoints and emit JSON results.")
    ap.add_argument("--target", choices=sorted(TARGETS), default="hygiene")
    ap.add_argument("--scale", type=int, default=1000, help="Record scale for scale-aware targets")
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--timeout-sec", type=float, default=120.0)
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-failures", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.iterations <= 0:
        raise SystemExit("[ERROR] --iterations must be positive")
    if args.timeout_sec <= 0:
        raise SystemExit("[ERROR] --timeout-sec must be positive")
    if args.scale <= 0:
        raise SystemExit("[ERROR] --scale must be positive")

    command = command_for_target(args.target, scale=args.scale)
    results = [run_once(command, timeout_sec=args.timeout_sec) for _ in range(args.iterations)]
    report = {
        "schema": "smoke_benchmark/v1",
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "target": args.target,
        "scale": args.scale if args.target == "sse-export-scale" else None,
        "command": command,
        "summary": summarize(results),
        "results": results,
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
    return 1 if report["summary"]["failed_iterations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
