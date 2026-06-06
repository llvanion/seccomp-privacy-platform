#!/usr/bin/env python3
import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_BENCHMARK_SCHEMA = "pipeline_benchmark/v1"
LIVE_SSE_BENCHMARK_SCHEMA = "live_sse_benchmark/v1"
PJC_BENCHMARK_SCHEMA = "pjc_benchmark/v1"
BRIDGE_BENCHMARK_SCHEMA = "bridge_benchmark/v1"
DASHBOARD_JOBS_BENCHMARK_SCHEMA = "dashboard_jobs_benchmark/v1"
EXPECTED_PIPELINE_MODES = ("file_handoff", "file_handoff_retained", "fifo_handoff")
EXPECTED_LIVE_MODES = ("file_handoff", "file_handoff_retained", "fifo_handoff")
EXPECTED_PJC_MODES = ("checked_in_sse_demo_job",)
EXPECTED_PJC_SCALE_MODES = ("generated_scale_csv",)
EXPECTED_BRIDGE_MODES = ("prepare_job_jsonl",)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def build_summary() -> dict[str, Any]:
    return {
        "iterations": 1,
        "successful_iterations": 1,
        "failed_iterations": 0,
        "duration_ms": {
            "min": 1.0,
            "mean": 1.0,
            "p50": 1.0,
            "p95": 1.0,
            "max": 1.0,
        },
    }


def validate_pipeline_surface(pipeline_module: Any) -> None:
    if tuple(pipeline_module.MODES) != EXPECTED_PIPELINE_MODES:
        raise SystemExit(
            f"pipeline benchmark mode set mismatch: expected {EXPECTED_PIPELINE_MODES}, got {tuple(pipeline_module.MODES)}"
        )
    production_limits = REPO_ROOT / "config" / "pjc_resource_limits.example.json"
    release_policy_gate_config = REPO_ROOT / "config" / "release_policy_gate.example.json"
    external_anchor_report = Path("/tmp/seccomp_pipeline_benchmark_example/external_anchor_report.json")
    for mode in pipeline_module.MODES:
        command = pipeline_module.build_pipeline_command(
            mode=mode,
            out_base=Path("/tmp/seccomp_pipeline_benchmark_example"),
            job_id=f"contract_{mode}",
            server_source=Path("/tmp/seccomp_pipeline_benchmark_example/server.csv"),
            client_source=Path("/tmp/seccomp_pipeline_benchmark_example/client.csv"),
        )
        if "--production-mode" in command or "--pjc-resource-limits" in command:
            raise SystemExit(f"pipeline default benchmark should not use production flags: {command}")
        if mode == "file_handoff_retained":
            if (
                "--keep-sse-export-handoff-files" not in command
                or "--sse-export-handoff-mode" in command
                or "--handoff-retention-reason" not in command
            ):
                raise SystemExit(f"pipeline retained benchmark command mismatch: {command}")
        elif mode == "fifo_handoff":
            if "--sse-export-handoff-mode" not in command or "fifo" not in command:
                raise SystemExit(f"pipeline fifo benchmark command mismatch: {command}")
        else:
            if "--keep-sse-export-handoff-files" in command or "--sse-export-handoff-mode" in command:
                raise SystemExit(f"pipeline default file benchmark command mismatch: {command}")
        if mode != "file_handoff_retained":
            production_command = pipeline_module.build_pipeline_command(
                mode=mode,
                out_base=Path("/tmp/seccomp_pipeline_benchmark_example"),
                job_id=f"contract_prod_{mode}",
                server_source=Path("/tmp/seccomp_pipeline_benchmark_example/server.csv"),
                client_source=Path("/tmp/seccomp_pipeline_benchmark_example/client.csv"),
                production_mode=True,
                pjc_resource_limits=production_limits,
                release_policy_gate_config=release_policy_gate_config,
                external_anchor_report=external_anchor_report,
            )
            required_prod_flags = {
                "--production-mode",
                "--pjc-resource-limits",
                "--release-policy-gate-config",
                "--external-anchor-report",
                "--privacy-budget-required",
                "--privacy-budget-config",
                "--privacy-budget-ledger",
                "--require-dp",
                "--dp-epsilon",
                "--dp-sensitivity",
                "--public-report-redact-operator-fields",
            }
            missing_prod_flags = sorted(required_prod_flags - set(production_command))
            if missing_prod_flags:
                raise SystemExit(f"pipeline production benchmark command missing production flags: {production_command}")
            if str(production_limits) not in production_command:
                raise SystemExit(f"pipeline production benchmark command missing limits path: {production_command}")
            if str(release_policy_gate_config) not in production_command:
                raise SystemExit(f"pipeline production benchmark command missing release gate config path: {production_command}")
            if str(external_anchor_report) not in production_command:
                raise SystemExit(f"pipeline production benchmark command missing external anchor report path: {production_command}")
    try:
        pipeline_module.build_pipeline_command(
            mode="file_handoff_retained",
            out_base=Path("/tmp/seccomp_pipeline_benchmark_example"),
            job_id="contract_prod_file_handoff_retained",
            server_source=Path("/tmp/seccomp_pipeline_benchmark_example/server.csv"),
            client_source=Path("/tmp/seccomp_pipeline_benchmark_example/client.csv"),
            production_mode=True,
            pjc_resource_limits=production_limits,
            release_policy_gate_config=release_policy_gate_config,
            external_anchor_report=external_anchor_report,
        )
    except ValueError:
        pass
    else:
        raise SystemExit("pipeline retained benchmark unexpectedly accepted production_mode")


def validate_live_surface(live_module: Any) -> None:
    if tuple(live_module.MODES) != EXPECTED_LIVE_MODES:
        raise SystemExit(
            f"live SSE benchmark mode set mismatch: expected {EXPECTED_LIVE_MODES}, got {tuple(live_module.MODES)}"
        )
    for mode in live_module.MODES:
        command = live_module.build_live_demo_command(
            mode=mode,
            run_root=Path("/tmp/seccomp_live_sse_benchmark_example"),
            run_id=f"contract_{mode}",
        )
        if mode == "file_handoff_retained":
            if (
                "--keep-sse-export-handoff-files" not in command
                or "--sse-export-handoff-mode" in command
                or "--handoff-retention-reason" not in command
            ):
                raise SystemExit(f"live retained benchmark command mismatch: {command}")
        elif mode == "fifo_handoff":
            if "--sse-export-handoff-mode" not in command or "fifo" not in command:
                raise SystemExit(f"live fifo benchmark command mismatch: {command}")
        else:
            if "--keep-sse-export-handoff-files" in command or "--sse-export-handoff-mode" in command:
                raise SystemExit(f"live default file benchmark command mismatch: {command}")


def validate_pjc_surface(pjc_module: Any) -> None:
    if tuple(pjc_module.MODES) != EXPECTED_PJC_MODES:
        raise SystemExit(
            f"PJC benchmark mode set mismatch: expected {EXPECTED_PJC_MODES}, got {tuple(pjc_module.MODES)}"
        )
    if tuple(pjc_module.SCALE_MODES) != EXPECTED_PJC_SCALE_MODES:
        raise SystemExit(
            f"PJC benchmark scale mode set mismatch: expected {EXPECTED_PJC_SCALE_MODES}, got {tuple(pjc_module.SCALE_MODES)}"
        )
    for mode in pjc_module.MODES:
        command = ["bash", str(pjc_module.RUN_PJC_SH)]
        if command != ["bash", str(REPO_ROOT / "a-psi" / "moduleA_psi" / "scripts" / "run_pjc.sh")]:
            raise SystemExit(f"PJC benchmark command surface mismatch: {command}")
        server_csv, client_csv = pjc_module.fixture_paths(mode)
        expected_server = REPO_ROOT / "bridge" / "out" / "sse_demo_job" / "server.csv"
        expected_client = REPO_ROOT / "bridge" / "out" / "sse_demo_job" / "client.csv"
        if server_csv != expected_server or client_csv != expected_client:
            raise SystemExit(
                f"PJC benchmark fixture path mismatch: expected {(expected_server, expected_client)}, "
                f"got {(server_csv, client_csv)}"
            )


def pjc_fixture_entry(
    *,
    mode: str,
    command: list[str],
    server_csv: str,
    client_csv: str,
    scale: dict[str, Any],
    result_file: str,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "command": command,
        "input_fixture": {
            "server_csv": server_csv,
            "client_csv": client_csv,
        },
        "scale": scale,
        "summary": build_summary(),
        "results": [
            {
                "duration_ms": 1.0,
                "exit_code": 0,
                "timed_out": False,
                "stderr_tail": "",
                "stdout_tail": "",
                "intersection_size": scale["expected_intersection_size"],
                "intersection_sum": scale["expected_intersection_sum"],
                "result_file": result_file,
                "peak_rss_kb": 1,
            }
        ],
    }


def validate_bridge_surface(bridge_module: Any) -> None:
    if tuple(bridge_module.MODES) != EXPECTED_BRIDGE_MODES:
        raise SystemExit(
            f"bridge benchmark mode set mismatch: expected {EXPECTED_BRIDGE_MODES}, got {tuple(bridge_module.MODES)}"
        )
    command = bridge_module.build_prepare_job_command(
        bridge_cmd=["cargo", "run", "--quiet", "--"],
        server_jsonl=Path("/tmp/seccomp_bridge_benchmark_example/server.jsonl"),
        client_jsonl=Path("/tmp/seccomp_bridge_benchmark_example/client.jsonl"),
        out_dir=Path("/tmp/seccomp_bridge_benchmark_example/out"),
        audit_log=Path("/tmp/seccomp_bridge_benchmark_example/bridge_audit.jsonl"),
        job_id="contract_bridge_prepare_job",
        token_scope="contract_bridge_prepare_job",
    )
    expected_flags = {
        "prepare-job",
        "--server-input-format",
        "jsonl",
        "--client-input-format",
        "jsonl",
        "--server-normalizer",
        "email",
        "--client-normalizer",
        "email",
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
        "--token-secret-env",
        bridge_module.TOKEN_SECRET_ENV,
        "--audit-log",
        "--production-mode",
    }
    if not expected_flags.issubset(set(command)):
        raise SystemExit(f"bridge benchmark command surface mismatch: {command}")


def build_pipeline_fixture(pipeline_module: Any) -> dict[str, Any]:
    return {
        "schema": PIPELINE_BENCHMARK_SCHEMA,
        "generated_at_utc": "2026-04-29T00:00:00Z",
        "repo_root": str(REPO_ROOT),
        "bridge_bin": "cargo run --",
        "pjc_bin_dir": str(REPO_ROOT / "a-psi" / "private-join-and-compute" / "bazel-bin"),
        "production_mode": False,
        "pjc_resource_limits": None,
        "expected_result": {
            "intersection_size": pipeline_module.EXPECTED_INTERSECTION_SIZE,
            "intersection_sum": pipeline_module.EXPECTED_INTERSECTION_SUM,
        },
        "iterations": 1,
        "modes": [
            {
                "mode": mode,
                "command": pipeline_module.build_pipeline_command(
                    mode=mode,
                    out_base=Path("/tmp/seccomp_pipeline_benchmark_example"),
                    job_id=f"fixture_{mode}",
                    server_source=Path("/tmp/seccomp_pipeline_benchmark_example/server.csv"),
                    client_source=Path("/tmp/seccomp_pipeline_benchmark_example/client.csv"),
                ),
                "summary": build_summary(),
                "results": [
                    {
                        "duration_ms": 1.0,
                        "exit_code": 0,
                        "timed_out": False,
                        "stderr_tail": "",
                        "stdout_tail": "",
                        "intersection_size": pipeline_module.EXPECTED_INTERSECTION_SIZE,
                        "intersection_sum": pipeline_module.EXPECTED_INTERSECTION_SUM,
                        "public_report_released": True,
                        "public_report_reason_code": "ok",
                        "mainline_contract_check_embedded": True,
                        "handoff_cleanup_server_status": (
                            "cleaned"
                            if mode == "file_handoff"
                            else "retained"
                            if mode == "file_handoff_retained"
                            else "removed"
                        ),
                        "handoff_cleanup_client_status": (
                            "cleaned"
                            if mode == "file_handoff"
                            else "retained"
                            if mode == "file_handoff_retained"
                            else "removed"
                        ),
                        "handoff_cleanup_server_exists_after_run": mode == "file_handoff_retained",
                        "handoff_cleanup_client_exists_after_run": mode == "file_handoff_retained",
                    }
                ],
            }
            for mode in pipeline_module.MODES
        ],
    }


def build_live_fixture(live_module: Any) -> dict[str, Any]:
    return {
        "schema": LIVE_SSE_BENCHMARK_SCHEMA,
        "generated_at_utc": "2026-04-29T00:00:00Z",
        "repo_root": str(REPO_ROOT),
        "expected_result": {
            "intersection_size": live_module.EXPECTED_INTERSECTION_SIZE,
            "intersection_sum": live_module.EXPECTED_INTERSECTION_SUM,
        },
        "iterations": 1,
        "modes": [
            {
                "mode": mode,
                "command": live_module.build_live_demo_command(
                    mode=mode,
                    run_root=Path("/tmp/seccomp_live_sse_benchmark_example"),
                    run_id=f"fixture_{mode}",
                ),
                "summary": build_summary(),
                "results": [
                    {
                        "duration_ms": 1.0,
                        "exit_code": 0,
                        "timed_out": False,
                        "stderr_tail": "",
                        "stdout_tail": "",
                        "intersection_size": live_module.EXPECTED_INTERSECTION_SIZE,
                        "intersection_sum": live_module.EXPECTED_INTERSECTION_SUM,
                        "released": True,
                        "reason_code": "ok",
                        "manifest_path": "/tmp/seccomp_live_sse_benchmark_example/live_demo_manifest.json",
                        "mainline_contract_check_embedded": True,
                        "handoff_cleanup_server_status": (
                            "cleaned"
                            if mode == "file_handoff"
                            else "retained"
                            if mode == "file_handoff_retained"
                            else "removed"
                        ),
                        "handoff_cleanup_client_status": (
                            "cleaned"
                            if mode == "file_handoff"
                            else "retained"
                            if mode == "file_handoff_retained"
                            else "removed"
                        ),
                        "handoff_cleanup_server_exists_after_run": mode == "file_handoff_retained",
                        "handoff_cleanup_client_exists_after_run": mode == "file_handoff_retained",
                    }
                ],
            }
            for mode in live_module.MODES
        ],
    }


def build_pjc_fixture(pjc_module: Any) -> dict[str, Any]:
    command = ["bash", str(pjc_module.RUN_PJC_SH)]
    checked_server, checked_client = pjc_module.fixture_paths("checked_in_sse_demo_job")
    generated_overlap = 0.2
    generated_server_items = 100000
    generated_client_items = 50000
    generated_overlap_count = pjc_module.overlap_count_for_scale(
        generated_server_items,
        generated_client_items,
        generated_overlap,
    )
    generated_sum = pjc_module.expected_sum_for_overlap(generated_overlap_count)
    return {
        "schema": PJC_BENCHMARK_SCHEMA,
        "generated_at_utc": "2026-04-29T00:00:00Z",
        "repo_root": str(REPO_ROOT),
        "pjc_bin_dir": str(REPO_ROOT / "a-psi" / "private-join-and-compute" / "bazel-bin"),
        "expected_result": {
            "intersection_size": pjc_module.EXPECTED_INTERSECTION_SIZE,
            "intersection_sum": pjc_module.EXPECTED_INTERSECTION_SUM,
        },
        "iterations": 1,
        "modes": [
            pjc_fixture_entry(
                mode="checked_in_sse_demo_job",
                command=command,
                server_csv=str(checked_server),
                client_csv=str(checked_client),
                scale={
                    "source": "checked_in_fixture",
                    "server_items": 2,
                    "client_items": 2,
                    "overlap_count": pjc_module.EXPECTED_INTERSECTION_SIZE,
                    "overlap_ratio": None,
                    "expected_intersection_size": pjc_module.EXPECTED_INTERSECTION_SIZE,
                    "expected_intersection_sum": pjc_module.EXPECTED_INTERSECTION_SUM,
                },
                result_file="/tmp/seccomp_pjc_benchmark_example/attribution_result.json",
            ),
            pjc_fixture_entry(
                mode="generated_scale_csv",
                command=command,
                server_csv="/tmp/seccomp_pjc_scale_server_100000.csv",
                client_csv="/tmp/seccomp_pjc_scale_client_50000.csv",
                scale={
                    "source": "generated_csv",
                    "server_items": generated_server_items,
                    "client_items": generated_client_items,
                    "overlap_count": generated_overlap_count,
                    "overlap_ratio": generated_overlap,
                    "expected_intersection_size": generated_overlap_count,
                    "expected_intersection_sum": generated_sum,
                },
                result_file="/tmp/seccomp_pjc_benchmark_example/generated_scale_csv/attribution_result.json",
            ),
        ],
    }


def build_bridge_fixture(bridge_module: Any) -> dict[str, Any]:
    command = bridge_module.build_prepare_job_command(
        bridge_cmd=["cargo", "run", "--quiet", "--"],
        server_jsonl=Path("/tmp/seccomp_bridge_benchmark_example/server.jsonl"),
        client_jsonl=Path("/tmp/seccomp_bridge_benchmark_example/client.jsonl"),
        out_dir=Path("/tmp/seccomp_bridge_benchmark_example/out"),
        audit_log=Path("/tmp/seccomp_bridge_benchmark_example/bridge_audit.jsonl"),
        job_id="fixture_bridge_prepare_job",
        token_scope="fixture_bridge_prepare_job",
    )
    return {
        "schema": BRIDGE_BENCHMARK_SCHEMA,
        "generated_at_utc": "2026-05-08T00:00:00Z",
        "repo_root": str(REPO_ROOT),
        "bridge_cwd": str(REPO_ROOT / "bridge"),
        "fixture_profile": bridge_module.FIXTURE_PROFILE,
        "scale": {
            "server_rows": 5,
            "client_rows": 5,
        },
        "setup": {
            "server_generation_ms": 1.0,
            "client_generation_ms": 1.0,
            "server_jsonl": "/tmp/seccomp_bridge_benchmark_example/server.jsonl",
            "client_jsonl": "/tmp/seccomp_bridge_benchmark_example/client.jsonl",
        },
        "profile": {
            "method": "bridge_internal_phase_timing",
            "top_hotspots": [
                {"rank": 1, "symbol": "build_client_values", "percent": 35.0},
                {"rank": 2, "symbol": "build_server_tokens", "percent": 30.0},
                {"rank": 3, "symbol": "load_client_rows", "percent": 20.0},
            ],
            "notes": "Contract fixture; run the benchmark script for measured phase timing, throughput, and RSS.",
        },
        "iterations": 1,
        "modes": [
            {
                "mode": mode,
                "command": command,
                "input_fixture": {
                    "server_jsonl": "/tmp/seccomp_bridge_benchmark_example/server.jsonl",
                    "client_jsonl": "/tmp/seccomp_bridge_benchmark_example/client.jsonl",
                },
                "summary": {
                    **build_summary(),
                    "throughput_rows_per_sec": {
                        "mean": 1000.0,
                        "p50": 1000.0,
                    },
                },
                "results": [
                    {
                        "duration_ms": 1.0,
                        "exit_code": 0,
                        "timed_out": False,
                        "stderr_tail": "",
                        "stdout_tail": "",
                        "server_input_rows": 5,
                        "client_input_rows": 5,
                        "server_unique_join_tokens": 5,
                        "client_unique_join_tokens": 5,
                        "server_output_rows": 5,
                        "client_output_rows": 5,
                        "audit_decision": "allow",
                        "audit_duration_ms": 1,
                        "phase_timings_ms": {
                            "build_client_values": 35.0,
                            "build_server_tokens": 30.0,
                            "load_client_rows": 20.0,
                            "load_server_rows": 15.0,
                        },
                        "production_mode": True,
                        "token_secret_source_kind": "env",
                        "throughput_rows_per_sec": 1000.0,
                        "peak_rss_kb": 1,
                        "job_meta_file": "/tmp/seccomp_bridge_benchmark_example/out/job_meta.json",
                        "audit_log": "/tmp/seccomp_bridge_benchmark_example/bridge_audit.jsonl",
                    }
                ],
            }
            for mode in bridge_module.MODES
        ],
    }


def build_dashboard_jobs_fixture() -> dict[str, Any]:
    results = [
        {
            "duration_ms": 10.0 + index,
            "status_code": 202,
            "job_id": f"dashboard_benchmark_job_{index}",
            "state": "running",
        }
        for index in range(5)
    ]
    dashboard_results = [
        {
            "duration_ms": 8.0 + index,
            "status_code": 200,
            "overall_status": "warn",
            "job_control_state": "running",
        }
        for index in range(5)
    ]
    return {
        "schema": DASHBOARD_JOBS_BENCHMARK_SCHEMA,
        "generated_at_utc": "2026-05-08T00:00:00Z",
        "repo_root": str(REPO_ROOT),
        "mode": "inprocess_http_fake_runner",
        "configuration": {
            "concurrency": 5,
            "dashboard_reads": 5,
            "job_runtime_sec": 0.2,
            "dashboard_p95_threshold_ms": 2000.0,
            "max_memory_growth_kb_per_job": 1024.0,
        },
        "summary": {
            "status": "ok",
            "accepted_jobs": 5,
            "rejected_jobs": 0,
            "dashboard_ok_reads": 5,
            "dashboard_p95_ms": 12.0,
            "dashboard_p95_passed": True,
            "memory_growth_current_kb": 128.0,
            "memory_growth_peak_kb": 256.0,
            "memory_growth_per_job_kb": 25.6,
            "memory_leak_check_passed": True,
        },
        "start_requests": {
            "duration_ms": {
                "min": 10.0,
                "mean": 12.0,
                "p50": 12.0,
                "p95": 13.8,
                "max": 14.0,
            },
            "results": results,
        },
        "dashboard_reads": {
            "duration_ms": {
                "min": 8.0,
                "mean": 10.0,
                "p50": 10.0,
                "p95": 11.8,
                "max": 12.0,
            },
            "results": dashboard_results,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Build synthetic benchmark fixtures used by contract smoke.")
    ap.add_argument("--pipeline-out", required=True)
    ap.add_argument("--live-out", required=True)
    ap.add_argument("--pjc-out", required=True)
    ap.add_argument("--bridge-out", required=True)
    ap.add_argument("--dashboard-jobs-out", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    pipeline_module = load_module(REPO_ROOT / "scripts" / "benchmark_pipeline.py", "benchmark_pipeline_contract")
    live_module = load_module(REPO_ROOT / "scripts" / "benchmark_live_sse_demo.py", "benchmark_live_sse_contract")
    pjc_module = load_module(REPO_ROOT / "scripts" / "benchmark_pjc.py", "benchmark_pjc_contract")
    bridge_module = load_module(REPO_ROOT / "scripts" / "benchmark_bridge.py", "benchmark_bridge_contract")

    validate_pipeline_surface(pipeline_module)
    validate_live_surface(live_module)
    validate_pjc_surface(pjc_module)
    validate_bridge_surface(bridge_module)

    write_json(Path(args.pipeline_out), build_pipeline_fixture(pipeline_module))
    write_json(Path(args.live_out), build_live_fixture(live_module))
    write_json(Path(args.pjc_out), build_pjc_fixture(pjc_module))
    write_json(Path(args.bridge_out), build_bridge_fixture(bridge_module))
    write_json(Path(args.dashboard_jobs_out), build_dashboard_jobs_fixture())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
