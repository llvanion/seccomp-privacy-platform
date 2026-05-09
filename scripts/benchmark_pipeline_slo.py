#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import benchmark_pipeline


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "pipeline_slo_benchmark/v1"
CORE_STAGE_MAP = {
    "sse_export": "sse_export",
    "record_recovery_service": "record_recovery",
    "bridge": "bridge_prepare_job",
    "pjc": "pjc",
    "policy_release": "policy_release",
}
SLO_TARGETS_MS = {
    "sse_export": {"p50": 5000.0, "p95": 15000.0},
    "record_recovery": {"p50": 500.0, "p95": 2000.0},
    "bridge_prepare_job": {"p50": 10000.0, "p95": 30000.0},
    "pjc": {"p50": 60000.0, "p95": 120000.0},
    "policy_release": {"p50": 1000.0, "p95": 3000.0},
    "total_pipeline": {"p50": 90000.0, "p95": 180000.0},
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def build_fixture_rows(
    *,
    server_rows: int,
    client_rows: int,
    overlap_count: int,
    campaign: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    if server_rows <= 0 or client_rows <= 0:
        raise ValueError("server_rows and client_rows must be positive")
    if overlap_count < 0 or overlap_count > min(server_rows, client_rows):
        raise ValueError("overlap_count must be between 0 and min(server_rows, client_rows)")

    server: list[dict[str, Any]] = []
    client: list[dict[str, Any]] = []
    expected_sum = 0

    for index in range(overlap_count):
        email = f"shared-{index:08d}@example.com"
        amount = 100 + index
        server.append({"email": email, "campaign": campaign, "event": "exposure"})
        client.append({"email": email, "campaign": campaign, "amount": str(amount)})
        expected_sum += amount

    for index in range(server_rows - overlap_count):
        server.append({"email": f"server-only-{index:08d}@example.com", "campaign": campaign, "event": "exposure"})

    for index in range(client_rows - overlap_count):
        client.append({"email": f"client-only-{index:08d}@example.com", "campaign": campaign, "amount": str(1000000 + index)})

    return server, client, expected_sum


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


OPTIONAL_STAGES = frozenset({"record_recovery"})


def evaluate_stage(stage: str, duration_ms: float | None) -> dict[str, Any]:
    target = SLO_TARGETS_MS[stage]
    if duration_ms is None:
        # Stages like record_recovery only fire when the pipeline uses an
        # encrypted record store; with raw JSONL fixtures they are simply
        # absent and should not break the SLO summary.
        absence_status = "not_applicable" if stage in OPTIONAL_STAGES else "missing_duration"
        return {
            "stage": stage,
            "duration_ms": None,
            "p50_target_ms": target["p50"],
            "p95_target_ms": target["p95"],
            "within_p50_target": None,
            "within_p95_target": None,
            "within_3x_p95_target": None,
            "status": absence_status,
        }
    return {
        "stage": stage,
        "duration_ms": round(duration_ms, 3),
        "p50_target_ms": target["p50"],
        "p95_target_ms": target["p95"],
        "within_p50_target": duration_ms <= target["p50"],
        "within_p95_target": duration_ms <= target["p95"],
        "within_3x_p95_target": duration_ms <= target["p95"] * 3,
        "status": "ok" if duration_ms <= target["p95"] * 3 else "slo_breach",
    }


def stage_breakdown(observability: dict[str, Any]) -> list[dict[str, Any]]:
    by_stage: dict[str, list[float]] = {}
    for event in observability.get("events") or []:
        if not isinstance(event, dict):
            continue
        mapped = CORE_STAGE_MAP.get(str(event.get("stage") or ""))
        duration = event.get("duration_ms")
        if mapped and isinstance(duration, (int, float)):
            by_stage.setdefault(mapped, []).append(float(duration))

    rows: list[dict[str, Any]] = []
    for stage in ("sse_export", "record_recovery", "bridge_prepare_job", "pjc", "policy_release"):
        values = by_stage.get(stage) or []
        rows.append(evaluate_stage(stage, sum(values) if values else None))
    return rows


def build_summary(*, stages: list[dict[str, Any]], total_duration_ms: float, exit_code: int) -> dict[str, Any]:
    total = evaluate_stage("total_pipeline", total_duration_ms if exit_code == 0 else None)
    checked = [*stages, total]
    missing = [item["stage"] for item in checked if item["status"] == "missing_duration"]
    breaches = [item["stage"] for item in checked if item["status"] == "slo_breach"]
    not_applicable = [item["stage"] for item in checked if item["status"] == "not_applicable"]
    return {
        "status": "ok" if exit_code == 0 and not missing and not breaches else "fail",
        "exit_code": exit_code,
        "total_duration_ms": round(total_duration_ms, 3),
        "total_pipeline": total,
        "stage_count": len(stages),
        "missing_duration_stages": missing,
        "slo_breach_stages": breaches,
        "not_applicable_stages": not_applicable,
        "all_stages_within_3x_p95": not missing and not breaches,
    }


def run_pipeline_slo(args: argparse.Namespace) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="seccomp_pipeline_slo.") as tmp_name:
        tmp = Path(tmp_name)
        server_source = tmp / "server.jsonl"
        client_source = tmp / "client.jsonl"
        out_base = Path(args.out_base).expanduser() if args.out_base else tmp / "run"
        server_rows, client_rows, expected_sum = build_fixture_rows(
            server_rows=args.server_rows,
            client_rows=args.client_rows,
            overlap_count=args.overlap_count,
            campaign=args.campaign,
        )
        write_jsonl(server_source, server_rows)
        write_jsonl(client_source, client_rows)

        env = dict(os.environ)
        env.setdefault("BRIDGE_TOKEN_SECRET", "pipeline-slo-benchmark-secret")
        benchmark_home = tmp / "home"
        benchmark_home.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(benchmark_home)

        command = benchmark_pipeline.build_pipeline_command(
            mode="file_handoff",
            out_base=out_base,
            job_id=args.job_id,
            server_source=server_source,
            client_source=client_source,
        )
        started = time.perf_counter()
        timed_out = False
        try:
            result = subprocess.run(
                command,
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=args.timeout_sec,
                env=env,
            )
            exit_code = int(result.returncode)
            stderr_tail = "\n".join(result.stderr.splitlines()[-20:]) if result.stderr else ""
            stdout_tail = "\n".join(result.stdout.splitlines()[-20:]) if result.stdout else ""
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            timed_out = True
            stderr_tail = str(exc)
            stdout_tail = ""

        total_duration_ms = (time.perf_counter() - started) * 1000
        validation: dict[str, Any] = {
            "intersection_size": None,
            "intersection_sum": None,
            "public_report_released": None,
            "public_report_reason_code": None,
            "mainline_contract_check_embedded": None,
        }
        observability: dict[str, Any] = {}
        stages = [evaluate_stage(stage, None) for stage in ("sse_export", "record_recovery", "bridge_prepare_job", "pjc", "policy_release")]

        if exit_code == 0:
            try:
                validation = benchmark_pipeline.validate_completed_run(
                    out_base,
                    mode="file_handoff",
                    expected_intersection_size=args.overlap_count,
                    expected_intersection_sum=expected_sum,
                )
                # The pipeline writes audit_chain.json directly; pipeline_observability/v1
                # is the derived stage-event view. Render it here so per-stage
                # duration_ms can be evaluated against the SLO targets.
                obs_path = out_base / "pipeline_observability.json"
                if not obs_path.exists():
                    subprocess.run(
                        [
                            "python3",
                            str(REPO_ROOT / "scripts" / "export_observability_events.py"),
                            "--audit-chain",
                            str(out_base / "audit_chain.json"),
                            "--out",
                            str(obs_path),
                        ],
                        check=True,
                        cwd=str(REPO_ROOT),
                    )
                observability = read_json(obs_path)
                stages = stage_breakdown(observability)
            except Exception as exc:
                exit_code = 1
                stderr_tail = str(exc)

        return build_report(
            args=args,
            command=command,
            out_base=out_base,
            server_source=server_source,
            client_source=client_source,
            expected_sum=expected_sum,
            stages=stages,
            validation=validation,
            total_duration_ms=total_duration_ms,
            exit_code=exit_code,
            timed_out=timed_out,
            stderr_tail=stderr_tail,
            stdout_tail=stdout_tail,
            observability=observability,
        )


def build_report(
    *,
    args: argparse.Namespace,
    command: list[str],
    out_base: Path,
    server_source: Path,
    client_source: Path,
    expected_sum: int,
    stages: list[dict[str, Any]],
    validation: dict[str, Any],
    total_duration_ms: float,
    exit_code: int,
    timed_out: bool,
    stderr_tail: str,
    stdout_tail: str,
    observability: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "mode": "file_handoff",
        "configuration": {
            "server_rows": args.server_rows,
            "client_rows": args.client_rows,
            "overlap_count": args.overlap_count,
            "campaign": args.campaign,
            "timeout_sec": args.timeout_sec,
            "slo_targets_ms": SLO_TARGETS_MS,
        },
        "expected_result": {
            "intersection_size": args.overlap_count,
            "intersection_sum": expected_sum,
        },
        "command": command,
        "artifacts": {
            "out_base": str(out_base.resolve()),
            "server_source": str(server_source.resolve()),
            "client_source": str(client_source.resolve()),
            "pipeline_observability": str((out_base / "pipeline_observability.json").resolve()),
        },
        "summary": build_summary(stages=stages, total_duration_ms=total_duration_ms, exit_code=exit_code),
        "stages": stages,
        "validation": validation,
        "run": {
            "duration_ms": round(total_duration_ms, 3),
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stderr_tail": stderr_tail,
            "stdout_tail": stdout_tail,
            "observability_schema": observability.get("schema"),
            "observability_event_count": (observability.get("summary") or {}).get("event_count"),
        },
    }


def fixture_report(args: argparse.Namespace) -> dict[str, Any]:
    expected_sum = sum(100 + index for index in range(args.overlap_count))
    stages = [
        evaluate_stage("sse_export", 1000.0),
        evaluate_stage("record_recovery", 250.0),
        evaluate_stage("bridge_prepare_job", 2000.0),
        evaluate_stage("pjc", 10000.0),
        evaluate_stage("policy_release", 100.0),
    ]
    total_duration_ms = sum(float(item["duration_ms"] or 0) for item in stages)
    out_base = Path("/tmp/seccomp_pipeline_slo_example/run")
    server_source = Path("/tmp/seccomp_pipeline_slo_example/server.jsonl")
    client_source = Path("/tmp/seccomp_pipeline_slo_example/client.jsonl")
    return build_report(
        args=args,
        command=benchmark_pipeline.build_pipeline_command(
            mode="file_handoff",
            out_base=out_base,
            job_id=args.job_id,
            server_source=server_source,
            client_source=client_source,
        ),
        out_base=out_base,
        server_source=server_source,
        client_source=client_source,
        expected_sum=expected_sum,
        stages=stages,
        validation={
            "intersection_size": args.overlap_count,
            "intersection_sum": expected_sum,
            "public_report_released": True,
            "public_report_reason_code": "ok",
            "mainline_contract_check_embedded": True,
        },
        total_duration_ms=total_duration_ms,
        exit_code=0,
        timed_out=False,
        stderr_tail="",
        stdout_tail="",
        observability={"schema": "pipeline_observability/v1", "summary": {"event_count": 5}},
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="G5 end-to-end pipeline SLO benchmark.")
    ap.add_argument("--server-rows", type=int, default=10000)
    ap.add_argument("--client-rows", type=int, default=10000)
    ap.add_argument("--overlap-count", type=int, default=1000)
    ap.add_argument("--campaign", default="demo")
    ap.add_argument("--job-id", default="pipeline_slo_benchmark_job")
    ap.add_argument("--timeout-sec", type=float, default=600.0)
    ap.add_argument("--out-base", default="")
    ap.add_argument("--output", default="")
    ap.add_argument("--fixture-only", action="store_true", help="Emit a schema-valid report fixture without running the pipeline.")
    ap.add_argument("--assert-ok", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.server_rows <= 0 or args.client_rows <= 0:
        raise SystemExit("[ERROR] --server-rows and --client-rows must be positive")
    if args.overlap_count < 0 or args.overlap_count > min(args.server_rows, args.client_rows):
        raise SystemExit("[ERROR] --overlap-count must be between 0 and min(server_rows, client_rows)")
    if args.timeout_sec <= 0:
        raise SystemExit("[ERROR] --timeout-sec must be positive")

    report = fixture_report(args) if args.fixture_only else run_pipeline_slo(args)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        if not output.is_absolute():
            output = (REPO_ROOT / output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.assert_ok and report.get("summary", {}).get("status") != "ok":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
