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
EXPECTED_PIPELINE_MODES = ("file_handoff", "file_handoff_retained", "fifo_handoff")
EXPECTED_LIVE_MODES = ("file_handoff", "file_handoff_retained", "fifo_handoff")
EXPECTED_PJC_MODES = ("checked_in_sse_demo_job",)


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
    for mode in pipeline_module.MODES:
        command = pipeline_module.build_pipeline_command(
            mode=mode,
            out_base=Path("/tmp/seccomp_pipeline_benchmark_example"),
            job_id=f"contract_{mode}",
        )
        if mode == "file_handoff_retained":
            if "--keep-sse-export-handoff-files" not in command or "--sse-export-handoff-mode" in command:
                raise SystemExit(f"pipeline retained benchmark command mismatch: {command}")
        elif mode == "fifo_handoff":
            if "--sse-export-handoff-mode" not in command or "fifo" not in command:
                raise SystemExit(f"pipeline fifo benchmark command mismatch: {command}")
        else:
            if "--keep-sse-export-handoff-files" in command or "--sse-export-handoff-mode" in command:
                raise SystemExit(f"pipeline default file benchmark command mismatch: {command}")


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
            if "--keep-sse-export-handoff-files" not in command or "--sse-export-handoff-mode" in command:
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


def build_pipeline_fixture(pipeline_module: Any) -> dict[str, Any]:
    return {
        "schema": PIPELINE_BENCHMARK_SCHEMA,
        "generated_at_utc": "2026-04-29T00:00:00Z",
        "repo_root": str(REPO_ROOT),
        "bridge_bin": "cargo run --",
        "pjc_bin_dir": str(REPO_ROOT / "a-psi" / "private-join-and-compute" / "bazel-bin"),
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
            {
                "mode": mode,
                "command": ["bash", str(pjc_module.RUN_PJC_SH)],
                "input_fixture": {
                    "server_csv": str(pjc_module.fixture_paths(mode)[0]),
                    "client_csv": str(pjc_module.fixture_paths(mode)[1]),
                },
                "summary": build_summary(),
                "results": [
                    {
                        "duration_ms": 1.0,
                        "exit_code": 0,
                        "timed_out": False,
                        "stderr_tail": "",
                        "stdout_tail": "",
                        "intersection_size": pjc_module.EXPECTED_INTERSECTION_SIZE,
                        "intersection_sum": pjc_module.EXPECTED_INTERSECTION_SUM,
                        "result_file": "/tmp/seccomp_pjc_benchmark_example/attribution_result.json",
                    }
                ],
            }
            for mode in pjc_module.MODES
        ],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Build synthetic benchmark fixtures used by contract smoke.")
    ap.add_argument("--pipeline-out", required=True)
    ap.add_argument("--live-out", required=True)
    ap.add_argument("--pjc-out", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    pipeline_module = load_module(REPO_ROOT / "scripts" / "benchmark_pipeline.py", "benchmark_pipeline_contract")
    live_module = load_module(REPO_ROOT / "scripts" / "benchmark_live_sse_demo.py", "benchmark_live_sse_contract")
    pjc_module = load_module(REPO_ROOT / "scripts" / "benchmark_pjc.py", "benchmark_pjc_contract")

    validate_pipeline_surface(pipeline_module)
    validate_live_surface(live_module)
    validate_pjc_surface(pjc_module)

    write_json(Path(args.pipeline_out), build_pipeline_fixture(pipeline_module))
    write_json(Path(args.live_out), build_live_fixture(live_module))
    write_json(Path(args.pjc_out), build_pjc_fixture(pjc_module))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
