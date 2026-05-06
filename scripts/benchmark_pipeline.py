#!/usr/bin/env python3
import argparse
import json
import os
import statistics
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
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


def validate_completed_run(
    out_base: Path,
    *,
    mode: str,
    expected_intersection_size: int,
    expected_intersection_sum: int,
) -> dict[str, Any]:
    result_path = out_base / "a_psi_run" / "attribution_result.json"
    report_path = out_base / "a_psi_run" / "public_report.json"
    audit_chain_path = out_base / "audit_chain.json"
    mainline_contract_check_path = out_base / "mainline_contract_check.json"
    if not result_path.is_file():
        raise RuntimeError(f"missing attribution result: {result_path}")
    if not report_path.is_file():
        raise RuntimeError(f"missing public report: {report_path}")
    if not audit_chain_path.is_file():
        raise RuntimeError(f"missing audit chain: {audit_chain_path}")
    if not mainline_contract_check_path.is_file():
        raise RuntimeError(f"missing mainline contract check: {mainline_contract_check_path}")

    result = read_json(result_path)
    report = read_json(report_path)
    audit_chain = read_json(audit_chain_path)
    mainline_contract_check = read_json(mainline_contract_check_path)
    intersection_size = int(result.get("intersection_size"))
    intersection_sum = int(result.get("intersection_sum"))
    if intersection_size != expected_intersection_size:
        raise RuntimeError(
            f"unexpected intersection_size: {intersection_size} != {expected_intersection_size}"
        )
    if intersection_sum != expected_intersection_sum:
        raise RuntimeError(
            f"unexpected intersection_sum: {intersection_sum} != {expected_intersection_sum}"
        )
    embedded_mainline_contract_check = (
        audit_chain.get("mainline_contract_check")
        if isinstance(audit_chain.get("mainline_contract_check"), dict)
        else {}
    )
    if embedded_mainline_contract_check.get("schema") != "mainline_contract_check/v1":
        raise RuntimeError(f"audit chain missing embedded mainline contract check: {audit_chain_path}")
    if embedded_mainline_contract_check != mainline_contract_check:
        raise RuntimeError(
            f"audit chain embedded mainline contract check diverges from sidecar: {audit_chain_path}"
        )
    if mainline_contract_check.get("status") != "ok":
        raise RuntimeError(f"pipeline mainline contract check failed: {mainline_contract_check_path}")
    handoff_cleanup = mainline_contract_check.get("handoff_cleanup") or {}
    expected_status = (
        "cleaned"
        if mode == "file_handoff"
        else "retained"
        if mode == "file_handoff_retained"
        else "removed"
    )
    expected_exists_after_run = mode == "file_handoff_retained"
    for role_name in ("server", "client"):
        entry = handoff_cleanup.get(role_name) or {}
        if entry.get("status") != expected_status:
            raise RuntimeError(
                f"unexpected {mode} handoff cleanup status for {role_name}: "
                f"{entry.get('status')} != {expected_status}"
            )
        if entry.get("managed_by_out_base") is not True:
            raise RuntimeError(f"expected managed handoff path for {role_name}: {entry}")
        if entry.get("exists_after_run") is not expected_exists_after_run:
            raise RuntimeError(
                f"unexpected handoff artifact existence for {role_name}: "
                f"{entry.get('exists_after_run')} != {expected_exists_after_run}"
            )
        expected_reason = "benchmark_file_handoff_retained" if mode == "file_handoff_retained" else None
        if entry.get("retention_reason") != expected_reason:
            raise RuntimeError(
                f"unexpected handoff retention reason for {role_name}: "
                f"{entry.get('retention_reason')} != {expected_reason}"
            )
    return {
        "intersection_size": intersection_size,
        "intersection_sum": intersection_sum,
        "public_report_released": report.get("released"),
        "public_report_reason_code": report.get("reason_code"),
        "mainline_contract_check_embedded": True,
        "handoff_cleanup_server_status": (handoff_cleanup.get("server") or {}).get("status"),
        "handoff_cleanup_client_status": (handoff_cleanup.get("client") or {}).get("status"),
        "handoff_cleanup_server_exists_after_run": (handoff_cleanup.get("server") or {}).get("exists_after_run"),
        "handoff_cleanup_client_exists_after_run": (handoff_cleanup.get("client") or {}).get("exists_after_run"),
    }


def build_pipeline_command(
    *,
    mode: str,
    out_base: Path,
    job_id: str,
    server_source: Path,
    client_source: Path,
) -> list[str]:
    command = [
        "bash",
        str(REPO_ROOT / "scripts" / "run_sse_bridge_pipeline.sh"),
        "--server-source",
        str(server_source.resolve()),
        "--client-source",
        str(client_source.resolve()),
        "--server-join-key-field",
        "email",
        "--client-join-key-field",
        "email",
        "--client-value-field",
        "amount",
        "--server-normalizer",
        "email",
        "--client-normalizer",
        "email",
        "--client-value-mode",
        "raw-int",
        "--server-filter",
        "campaign=demo",
        "--client-filter",
        "campaign=demo",
        "--token-scope",
        f"benchmark-pipeline-{mode}",
        "--token-secret-env",
        "BRIDGE_TOKEN_SECRET",
        "--production-mode",
        "--job-id",
        job_id,
        "--out-base",
        str(out_base),
        "--caller",
        "auto_demo",
        "--tenant-id",
        "demo_tenant",
        "--dataset-id",
        "bridge_demo_dataset",
        "--sse-export-policy-config",
        str((REPO_ROOT / "sse" / "config" / "export_policy.example.json").resolve()),
        "--k",
        "1",
        "--n",
        "5",
    ]
    if mode == "file_handoff_retained":
        command.extend(["--keep-sse-export-handoff-files", "--handoff-retention-reason", "benchmark_file_handoff_retained"])
    elif mode == "fifo_handoff":
        command.extend(["--sse-export-handoff-mode", "fifo"])
    return command


def run_pipeline_once(
    *,
    mode: str,
    iteration: int,
    env: dict[str, str],
    timeout_sec: float,
    server_source: Path,
    client_source: Path,
    expected_intersection_size: int,
    expected_intersection_sum: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"seccomp_pipeline_bench.{mode}.{iteration}.") as tmp_dir:
        out_base = Path(tmp_dir) / "run"
        benchmark_home = Path(tmp_dir) / "home"
        benchmark_home.mkdir(parents=True, exist_ok=True)
        job_id = f"benchmark_pipeline_{mode}_{iteration}"
        command = build_pipeline_command(
            mode=mode,
            out_base=out_base,
            job_id=job_id,
            server_source=server_source,
            client_source=client_source,
        )
        run_env = dict(env)
        run_env["HOME"] = str(benchmark_home)
        started = time.perf_counter()
        try:
            result = subprocess.run(
                command,
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_sec,
                env=run_env,
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
                "public_report_released": None,
                "public_report_reason_code": None,
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
                "public_report_released": None,
                "public_report_reason_code": None,
                "mainline_contract_check_embedded": None,
                "handoff_cleanup_server_status": None,
                "handoff_cleanup_client_status": None,
                "handoff_cleanup_server_exists_after_run": None,
                "handoff_cleanup_client_exists_after_run": None,
            }

        try:
            metrics = validate_completed_run(
                out_base,
                mode=mode,
                expected_intersection_size=expected_intersection_size,
                expected_intersection_sum=expected_intersection_sum,
            )
        except Exception as exc:
            return {
                "duration_ms": round(duration_ms, 3),
                "exit_code": 1,
                "timed_out": False,
                "stderr_tail": str(exc),
                "stdout_tail": stdout_tail,
                "intersection_size": None,
                "intersection_sum": None,
                "public_report_released": None,
                "public_report_reason_code": None,
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
            "public_report_released": metrics["public_report_released"],
            "public_report_reason_code": metrics["public_report_reason_code"],
            "mainline_contract_check_embedded": metrics["mainline_contract_check_embedded"],
            "handoff_cleanup_server_status": metrics["handoff_cleanup_server_status"],
            "handoff_cleanup_client_status": metrics["handoff_cleanup_client_status"],
            "handoff_cleanup_server_exists_after_run": metrics["handoff_cleanup_server_exists_after_run"],
            "handoff_cleanup_client_exists_after_run": metrics["handoff_cleanup_client_exists_after_run"],
        }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Benchmark the existing file-mode SSE -> bridge -> PJC -> policy pipeline entrypoint.")
    ap.add_argument("--iterations", type=int, default=1)
    ap.add_argument("--mode", choices=("all",) + MODES, default="all")
    ap.add_argument("--timeout-sec", type=float, default=300.0)
    ap.add_argument("--server-source", default=str((REPO_ROOT / "sse" / "examples" / "bridge_server_records.jsonl").resolve()))
    ap.add_argument("--client-source", default=str((REPO_ROOT / "sse" / "examples" / "bridge_client_records.jsonl").resolve()))
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

    server_source = Path(args.server_source).expanduser()
    client_source = Path(args.client_source).expanduser()
    if not server_source.is_file():
        raise SystemExit(f"[ERROR] server source does not exist: {server_source}")
    if not client_source.is_file():
        raise SystemExit(f"[ERROR] client source does not exist: {client_source}")

    pjc_bin_dir = Path(os.environ.get("PJC_BIN_DIR", str(REPO_ROOT / "a-psi" / "private-join-and-compute" / "bazel-bin")))
    if not pjc_bin_dir.is_dir():
        raise SystemExit(f"[ERROR] PJC_BIN_DIR does not exist: {pjc_bin_dir}")

    selected_modes = list(MODES) if args.mode == "all" else [args.mode]
    env = dict(os.environ)
    env.setdefault("BRIDGE_TOKEN_SECRET", "benchmark-pipeline-secret")

    results: list[dict[str, Any]] = []
    for mode in selected_modes:
        mode_results = [
            run_pipeline_once(
                mode=mode,
                iteration=iteration,
                env=env,
                timeout_sec=args.timeout_sec,
                server_source=server_source,
                client_source=client_source,
                expected_intersection_size=args.expected_intersection_size,
                expected_intersection_sum=args.expected_intersection_sum,
            )
            for iteration in range(args.iterations)
        ]
        results.append(
            {
                "mode": mode,
                "command": build_pipeline_command(
                    mode=mode,
                    out_base=Path("/tmp/seccomp_pipeline_benchmark_example"),
                    job_id=f"benchmark_pipeline_{mode}_example",
                    server_source=server_source,
                    client_source=client_source,
                ),
                "summary": summarize(mode_results),
                "results": mode_results,
            }
        )

    report = {
        "schema": "pipeline_benchmark/v1",
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "bridge_bin": env.get("BRIDGE_BIN", "cargo run --"),
        "pjc_bin_dir": str(pjc_bin_dir),
        "expected_result": {
            "intersection_size": args.expected_intersection_size,
            "intersection_sum": args.expected_intersection_sum,
        },
        "server_source": str(server_source.resolve()),
        "client_source": str(client_source.resolve()),
        "iterations": args.iterations,
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


if __name__ == "__main__":
    raise SystemExit(main())
