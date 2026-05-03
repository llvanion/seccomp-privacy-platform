#!/usr/bin/env python3
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark_read_adapters import FIXTURE_PROFILE, materialize_fixture


REPO_ROOT = Path(__file__).resolve().parents[1]
MODES = (
    "observability_cli",
    "catalog_cli_default",
    "catalog_cli_include_paths",
)
EXPECTED_STAGES = {
    "sse_export",
    "record_recovery_service",
    "bridge",
    "pjc",
    "policy_release",
    "handoff_cleanup",
    "handoff_exposure_assessment",
    "service_audit_consistency",
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


def run_command(command: list[str], *, env: dict[str, str], timeout_sec: float) -> tuple[dict[str, Any], str]:
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
        stdout = result.stdout
        stderr_tail = "\n".join(result.stderr.splitlines()[-20:]) if result.stderr else ""
    except subprocess.TimeoutExpired as exc:
        duration_ms = (time.perf_counter() - started) * 1000
        return (
            {
                "duration_ms": round(duration_ms, 3),
                "exit_code": 124,
                "timed_out": True,
                "stderr_tail": str(exc),
            },
            "",
        )
    duration_ms = (time.perf_counter() - started) * 1000
    return (
        {
            "duration_ms": round(duration_ms, 3),
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stderr_tail": stderr_tail,
        },
        stdout,
    )


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def validate_observability(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if payload.get("schema") != "pipeline_observability/v1":
        raise RuntimeError(f"unexpected observability schema: {payload}")
    summary = payload.get("summary")
    events = payload.get("events")
    if not isinstance(summary, dict) or not isinstance(events, list):
        raise RuntimeError(f"malformed observability payload: {payload}")
    if summary.get("event_count") != len(events):
        raise RuntimeError(f"observability event_count mismatch: {payload}")
    stages = {item.get("stage") for item in events if isinstance(item, dict)}
    missing_stages = sorted(EXPECTED_STAGES - {str(stage) for stage in stages if stage is not None})
    if missing_stages:
        raise RuntimeError(f"observability missing stages: {missing_stages}")
    if not any(isinstance(item, dict) and item.get("duration_ms") not in (None, "") for item in events):
        raise RuntimeError(f"observability did not propagate duration_ms: {payload}")
    return {
        "result_schema": "pipeline_observability/v1",
        "event_count": len(events),
        "artifact_count": None,
        "lineage_edge_count": None,
        "paths_included": None,
        "mainline_contract_embedded": None,
        "service_audit_consistency_server": None,
        "service_audit_consistency_client": None,
        "service_audit_consistency_error_count": None,
    }


def validate_catalog(path: Path, *, expect_paths: bool) -> dict[str, Any]:
    payload = load_json(path)
    if payload.get("schema") != "catalog_lineage/v1":
        raise RuntimeError(f"unexpected catalog schema: {payload}")
    privacy = payload.get("privacy")
    summary = payload.get("summary")
    artifacts = payload.get("artifacts")
    edges = payload.get("lineage_edges")
    if not isinstance(privacy, dict) or not isinstance(summary, dict) or not isinstance(artifacts, list) or not isinstance(edges, list):
        raise RuntimeError(f"malformed catalog payload: {payload}")
    if bool(privacy.get("paths_included")) != expect_paths:
        raise RuntimeError(f"unexpected catalog paths_included flag: {payload}")
    if summary.get("artifact_count") != len(artifacts) or summary.get("lineage_edge_count") != len(edges):
        raise RuntimeError(f"catalog summary count mismatch: {payload}")
    if len(artifacts) == 0 or len(edges) == 0:
        raise RuntimeError(f"catalog output is unexpectedly empty: {payload}")
    mainline = payload.get("mainline_contract_summary")
    if not isinstance(mainline, dict):
        raise RuntimeError(f"catalog output missing mainline contract summary: {payload}")
    service_consistency = mainline.get("service_audit_consistency")
    if (
        mainline.get("schema") != "mainline_contract_check/v1"
        or mainline.get("status") != "ok"
        or mainline.get("embedded_in_audit_chain") is not True
        or not isinstance(service_consistency, dict)
        or service_consistency.get("server") != "not_applicable"
        or service_consistency.get("client") != "ok"
        or service_consistency.get("error_count") != 0
    ):
        raise RuntimeError(f"catalog output returned unexpected mainline contract summary: {payload}")
    if expect_paths:
        if not any(isinstance(item, dict) and item.get("path") for item in artifacts):
            raise RuntimeError(f"catalog include-paths output did not include paths: {payload}")
    else:
        if any(isinstance(item, dict) and "path" in item for item in artifacts):
            raise RuntimeError(f"catalog default output unexpectedly included paths: {payload}")
        if not all(isinstance(item, dict) and item.get("path_included") is False for item in artifacts):
            raise RuntimeError(f"catalog default output missing path_included=false markers: {payload}")
    return {
        "result_schema": "catalog_lineage/v1",
        "event_count": None,
        "artifact_count": len(artifacts),
        "lineage_edge_count": len(edges),
        "paths_included": expect_paths,
        "mainline_contract_embedded": True,
        "service_audit_consistency_server": service_consistency.get("server"),
        "service_audit_consistency_client": service_consistency.get("client"),
        "service_audit_consistency_error_count": service_consistency.get("error_count"),
    }


def example_command_for_mode(mode: str) -> list[str]:
    if mode == "observability_cli":
        return [
            sys.executable,
            str(REPO_ROOT / "scripts" / "export_observability_events.py"),
            "--audit-chain",
            "/tmp/audit_chain.json",
            "--out",
            "/tmp/pipeline_observability.json",
        ]
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "export_catalog_lineage.py"),
        "--audit-chain",
        "/tmp/audit_chain.json",
        "--out",
        "/tmp/catalog_lineage.json",
    ]
    if mode == "catalog_cli_include_paths":
        command.append("--include-paths")
    return command


def run_mode_once(
    *,
    mode: str,
    iteration: int,
    timeout_sec: float,
    common_env: dict[str, str],
    audit_chain_path: Path,
) -> dict[str, Any]:
    if mode == "observability_cli":
        output_path = Path(tempfile.gettempdir()) / f"derived_views_observability_{iteration}.json"
        command = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "export_observability_events.py"),
            "--audit-chain",
            str(audit_chain_path),
            "--out",
            str(output_path),
        ]
        validator = lambda path: validate_observability(path)
    else:
        suffix = "catalog_paths" if mode == "catalog_cli_include_paths" else "catalog_default"
        output_path = Path(tempfile.gettempdir()) / f"derived_views_{suffix}_{iteration}.json"
        command = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "export_catalog_lineage.py"),
            "--audit-chain",
            str(audit_chain_path),
            "--out",
            str(output_path),
        ]
        expect_paths = mode == "catalog_cli_include_paths"
        if expect_paths:
            command.append("--include-paths")
        validator = lambda path, expect_paths=expect_paths: validate_catalog(path, expect_paths=expect_paths)
    if output_path.exists():
        output_path.unlink()
    result, stdout = run_command(command, env=common_env, timeout_sec=timeout_sec)
    stdout_tail = "\n".join(stdout.splitlines()[-20:]) if stdout else ""
    if result["exit_code"] != 0:
        return {
            **result,
            "stdout_tail": stdout_tail,
            "result_schema": None,
            "event_count": None,
            "artifact_count": None,
            "lineage_edge_count": None,
            "paths_included": None,
        }
    metrics = validator(output_path)
    return {
        **result,
        "stdout_tail": stdout_tail,
        **metrics,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Benchmark derived observability and catalog/lineage exporters over a synthetic audit_chain fixture.")
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--mode", choices=("all",) + MODES, default="all")
    ap.add_argument("--timeout-sec", type=float, default=30.0)
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-failures", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.iterations <= 0:
        raise SystemExit("[ERROR] --iterations must be positive")
    if args.timeout_sec <= 0:
        raise SystemExit("[ERROR] --timeout-sec must be positive")

    selected_modes = list(MODES) if args.mode == "all" else [args.mode]
    common_env = dict(os.environ)
    common_env.setdefault("SSE_RECORD_RECOVERY_TOKEN", "benchmark-record-recovery-token")
    mode_entries: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="seccomp_derived_views_bench.") as tmp_dir:
        run_root = Path(tmp_dir)
        out_base, _db_path = materialize_fixture(run_root, env=common_env)
        audit_chain_path = out_base / "audit_chain.json"

        for mode in selected_modes:
            mode_results = [
                run_mode_once(
                    mode=mode,
                    iteration=iteration,
                    timeout_sec=args.timeout_sec,
                    common_env=common_env,
                    audit_chain_path=audit_chain_path,
                )
                for iteration in range(args.iterations)
            ]
            mode_entries.append(
                {
                    "mode": mode,
                    "command": example_command_for_mode(mode),
                    "summary": summarize(mode_results),
                    "results": mode_results,
                }
            )

    report = {
        "schema": "derived_views_benchmark/v1",
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "fixture_profile": FIXTURE_PROFILE,
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
