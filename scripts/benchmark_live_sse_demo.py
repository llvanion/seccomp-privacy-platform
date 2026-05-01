#!/usr/bin/env python3
import argparse
import json
import statistics
import subprocess
import tempfile
import time
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_DEMO_SH = REPO_ROOT / "scripts" / "run_live_sse_bridge_demo.sh"
MODES = ("file_handoff", "file_handoff_retained", "fifo_handoff")
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


def normalize_sum_cents(*values: Any) -> int:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
        if parsed == parsed.to_integral_value():
            return int(parsed)
        cents = parsed * Decimal("100")
        if cents == cents.to_integral_value():
            return int(cents)
    raise RuntimeError(f"unable to normalize intersection_sum from values={values!r}")


def validate_manifest(out_base: Path, *, mode: str) -> dict[str, Any]:
    manifest_path = out_base / "live_demo_manifest.json"
    public_report_path = out_base / "a_psi_run" / "public_report.json"
    audit_chain_path = out_base / "audit_chain.json"
    mainline_contract_check_path = out_base / "mainline_contract_check.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"missing live demo manifest: {manifest_path}")
    if not public_report_path.is_file():
        raise RuntimeError(f"missing live demo public report: {public_report_path}")
    if not audit_chain_path.is_file():
        raise RuntimeError(f"missing live demo audit chain: {audit_chain_path}")
    if not mainline_contract_check_path.is_file():
        raise RuntimeError(f"missing live demo mainline contract check: {mainline_contract_check_path}")

    manifest = read_json(manifest_path)
    public_report = read_json(public_report_path)
    audit_chain = read_json(audit_chain_path)
    mainline_contract_check = read_json(mainline_contract_check_path)
    embedded_mainline_contract_check = (
        audit_chain.get("mainline_contract_check")
        if isinstance(audit_chain.get("mainline_contract_check"), dict)
        else {}
    )
    if embedded_mainline_contract_check.get("schema") != "mainline_contract_check/v1":
        raise RuntimeError(f"audit_chain missing embedded mainline contract check: {audit_chain_path}")
    if embedded_mainline_contract_check != mainline_contract_check:
        raise RuntimeError(
            f"audit_chain embedded mainline contract check diverges from sidecar: {audit_chain_path}"
        )
    public_details = public_report.get("details") if isinstance(public_report.get("details"), dict) else {}
    result = manifest.get("result") or {}
    intersection_size = int(result.get("intersection_size"))
    intersection_sum = normalize_sum_cents(
        result.get("intersection_sum_raw"),
        result.get("intersection_sum_cents"),
        public_report.get("intersection_sum_raw"),
        public_details.get("intersection_sum_raw"),
        public_report.get("intersection_sum_cents"),
        public_details.get("intersection_sum_cents"),
        result.get("intersection_sum"),
        result.get("intersection_sum_eur"),
        public_report.get("intersection_sum"),
        public_details.get("intersection_sum"),
        public_report.get("intersection_sum_eur"),
        public_details.get("intersection_sum_eur"),
    )
    if intersection_size != EXPECTED_INTERSECTION_SIZE:
        raise RuntimeError(
            f"unexpected live demo intersection_size: {intersection_size} != {EXPECTED_INTERSECTION_SIZE}"
        )
    if intersection_sum != EXPECTED_INTERSECTION_SUM:
        raise RuntimeError(
            "unexpected live demo intersection_sum: "
            f"{result.get('intersection_sum')} -> {intersection_sum} != {EXPECTED_INTERSECTION_SUM}"
        )
    if mainline_contract_check.get("status") != "ok":
        raise RuntimeError(f"live demo mainline contract check failed: {mainline_contract_check_path}")
    handoff_cleanup = mainline_contract_check.get("handoff_cleanup") or {}
    expected_status = (
        "cleaned"
        if mode == "file_handoff"
        else "retained"
        if mode == "file_handoff_retained"
        else "removed"
    )
    for role_name in ("server", "client"):
        entry = handoff_cleanup.get(role_name) or {}
        if entry.get("status") != expected_status:
            raise RuntimeError(
                f"unexpected {mode} handoff cleanup status for {role_name}: "
                f"{entry.get('status')} != {expected_status}"
            )
        if entry.get("managed_by_out_base") is not True:
            raise RuntimeError(f"expected managed handoff path for {role_name}: {entry}")
        expected_exists_after_run = mode == "file_handoff_retained"
        if entry.get("exists_after_run") is not expected_exists_after_run:
            raise RuntimeError(
                f"unexpected handoff artifact existence for {role_name}: "
                f"{entry.get('exists_after_run')} != {expected_exists_after_run}"
            )
    return {
        "intersection_size": intersection_size,
        "intersection_sum": intersection_sum,
        "released": result.get("released"),
        "reason_code": result.get("reason_code"),
        "manifest_path": str(manifest_path),
        "mainline_contract_check_embedded": True,
        "handoff_cleanup_server_status": (handoff_cleanup.get("server") or {}).get("status"),
        "handoff_cleanup_client_status": (handoff_cleanup.get("client") or {}).get("status"),
        "handoff_cleanup_server_exists_after_run": (handoff_cleanup.get("server") or {}).get("exists_after_run"),
        "handoff_cleanup_client_exists_after_run": (handoff_cleanup.get("client") or {}).get("exists_after_run"),
    }


def build_live_demo_command(*, mode: str, run_root: Path, run_id: str) -> list[str]:
    command = [
        "bash",
        str(LIVE_DEMO_SH),
        "--run-id",
        run_id,
        "--run-root",
        str(run_root),
        "--caller",
        "auto_demo",
        "--token-scope",
        f"benchmark-live-sse-{mode}",
        "--token-secret",
        "benchmark-live-sse-secret",
        "--k",
        "1",
        "--n",
        "5",
    ]
    if mode == "file_handoff_retained":
        command.append("--keep-sse-export-handoff-files")
    elif mode == "fifo_handoff":
        command.extend(["--sse-export-handoff-mode", "fifo"])
    return command


def run_live_demo_once(*, mode: str, iteration: int, timeout_sec: float) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"seccomp_live_sse_bench.{mode}.{iteration}.") as tmp_dir:
        run_root = Path(tmp_dir) / "live"
        benchmark_home = Path(tmp_dir) / "home"
        benchmark_home.mkdir(parents=True, exist_ok=True)
        run_id = f"benchmark_live_sse_{mode}_{iteration}"
        out_base = run_root / f"run-{run_id}"
        command = build_live_demo_command(mode=mode, run_root=run_root, run_id=run_id)
        env = dict(subprocess.os.environ)
        env["HOME"] = str(benchmark_home)
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
                "released": None,
                "reason_code": None,
                "manifest_path": None,
                "mainline_contract_check_embedded": None,
                "handoff_cleanup_server_status": None,
                "handoff_cleanup_client_status": None,
                "handoff_cleanup_server_exists_after_run": None,
                "handoff_cleanup_client_exists_after_run": None,
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
                "released": None,
                "reason_code": None,
                "manifest_path": None,
                "mainline_contract_check_embedded": None,
                "handoff_cleanup_server_status": None,
                "handoff_cleanup_client_status": None,
                "handoff_cleanup_server_exists_after_run": None,
                "handoff_cleanup_client_exists_after_run": None,
            }

        try:
            metrics = validate_manifest(out_base, mode=mode)
        except Exception as exc:
            return {
                "duration_ms": round(duration_ms, 3),
                "exit_code": 1,
                "timed_out": False,
                "stderr_tail": str(exc),
                "stdout_tail": stdout_tail,
                "intersection_size": None,
                "intersection_sum": None,
                "released": None,
                "reason_code": None,
                "manifest_path": None,
                "mainline_contract_check_embedded": None,
                "handoff_cleanup_server_status": None,
                "handoff_cleanup_client_status": None,
                "handoff_cleanup_server_exists_after_run": None,
                "handoff_cleanup_client_exists_after_run": None,
            }

        return {
            "duration_ms": round(duration_ms, 3),
            "exit_code": 0,
            "timed_out": False,
            "stderr_tail": stderr_tail,
            "stdout_tail": stdout_tail,
            "intersection_size": metrics["intersection_size"],
            "intersection_sum": metrics["intersection_sum"],
            "released": metrics["released"],
            "reason_code": metrics["reason_code"],
            "manifest_path": metrics["manifest_path"],
            "mainline_contract_check_embedded": metrics["mainline_contract_check_embedded"],
            "handoff_cleanup_server_status": metrics["handoff_cleanup_server_status"],
            "handoff_cleanup_client_status": metrics["handoff_cleanup_client_status"],
            "handoff_cleanup_server_exists_after_run": metrics["handoff_cleanup_server_exists_after_run"],
            "handoff_cleanup_client_exists_after_run": metrics["handoff_cleanup_client_exists_after_run"],
        }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Benchmark the live SSE-backed demo wrapper over the existing demo entrypoint.")
    ap.add_argument("--iterations", type=int, default=1)
    ap.add_argument("--mode", choices=("all",) + MODES, default="all")
    ap.add_argument("--timeout-sec", type=float, default=600.0)
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-failures", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.iterations <= 0:
        raise SystemExit("[ERROR] --iterations must be positive")
    if args.timeout_sec <= 0:
        raise SystemExit("[ERROR] --timeout-sec must be positive")
    if not LIVE_DEMO_SH.is_file():
        raise SystemExit(f"[ERROR] missing live demo script: {LIVE_DEMO_SH}")

    selected_modes = list(MODES) if args.mode == "all" else [args.mode]
    mode_entries: list[dict[str, Any]] = []
    for mode in selected_modes:
        mode_results = [
            run_live_demo_once(mode=mode, iteration=iteration, timeout_sec=args.timeout_sec)
            for iteration in range(args.iterations)
        ]
        mode_entries.append(
            {
                "mode": mode,
                "command": build_live_demo_command(
                    mode=mode,
                    run_root=Path("/tmp/seccomp_live_sse_benchmark_example"),
                    run_id=f"benchmark_live_sse_{mode}_example",
                ),
                "summary": summarize(mode_results),
                "results": mode_results,
            }
        )

    report = {
        "schema": "live_sse_benchmark/v1",
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "expected_result": {
            "intersection_size": EXPECTED_INTERSECTION_SIZE,
            "intersection_sum": EXPECTED_INTERSECTION_SUM,
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
