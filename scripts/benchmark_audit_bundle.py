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


REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_BUNDLE_PY = REPO_ROOT / "scripts" / "archive_audit_bundle.py"
SEAL_AUDIT_PY = REPO_ROOT / "scripts" / "seal_audit_artifact.py"
VALIDATE_JSON_PY = REPO_ROOT / "scripts" / "validate_json_contract.py"
VERIFY_BUNDLE_PY = REPO_ROOT / "scripts" / "verify_audit_bundle.py"
AUDIT_CHAIN_SCHEMA = REPO_ROOT / "schemas" / "audit_chain.schema.json"
AUDIT_SEAL_SCHEMA = REPO_ROOT / "schemas" / "audit_seal.schema.json"
MODES = (
    "archive_cli",
    "verify_direct_cli",
    "verify_archive_index_cli",
    "verify_archive_index_restore_cli",
)
FIXTURE_PROFILE = "synthetic_audit_bundle_v1"
FIXTURE_JOB_ID = "benchmark-audit-bundle"
FIXTURE_CORRELATION_ID = "benchmark-audit-bundle"
HMAC_KEY_ENV = "BENCHMARK_AUDIT_BUNDLE_HMAC_KEY"
ANCHOR_KEY_ENV = "BENCHMARK_AUDIT_BUNDLE_ANCHOR_KEY"


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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_ok(result: subprocess.CompletedProcess[str], *, label: str) -> None:
    if result.returncode != 0:
        raise SystemExit(f"[ERROR] {label} failed:\n{result.stderr}")


def run_checked(command: list[str], *, env: dict[str, str], label: str) -> None:
    result = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    ensure_ok(result, label=label)


def materialize_fixture(run_root: Path, *, env: dict[str, str]) -> tuple[Path, Path]:
    out_base = run_root / "fixture"
    audit_chain_path = out_base / "audit_chain.json"
    audit_seal_path = out_base / "audit_chain.seal.json"
    write_json(
        audit_chain_path,
        {
            "schema": "audit_chain/v1",
            "generated_at_utc": utc_now_iso(),
            "job_id": FIXTURE_JOB_ID,
            "correlation_id": FIXTURE_CORRELATION_ID,
            "paths": {
                "out_base": str(out_base.resolve()),
            },
            "artifacts": {
                "bridge_job_meta_sha256": None,
                "pjc_result_sha256": None,
                "public_report_sha256": None,
            },
            "counts": {
                "sse_export_audit_records": 0,
                "record_recovery_service_audit_records": 0,
                "bridge_audit_records": 0,
                "pjc_audit_records": 0,
                "policy_audit_records": 0,
                "key_access_audit_records": 0,
            },
            "key_access_audit": [],
            "sse_export_audit": [],
            "record_recovery_service_audit": [],
            "bridge_audit": [],
            "bridge_job_meta": None,
            "pjc_audit": [],
            "pjc_result": None,
            "public_report": None,
            "policy_audit": [],
            "mainline_contract_check": {
                "schema": "mainline_contract_check/v1",
                "generated_at_utc": utc_now_iso(),
                "repo_root": str(REPO_ROOT),
                "out_base": str(out_base.resolve()),
                "job_id": FIXTURE_JOB_ID,
                "status": "ok",
                "canonical_scope": {
                    "job_id": FIXTURE_JOB_ID,
                    "correlation_id": FIXTURE_CORRELATION_ID,
                    "caller": "benchmark_audit_bundle",
                    "tenant_id": "tenant-benchmark",
                    "dataset_id": "dataset-benchmark",
                    "service_id": "service-benchmark",
                    "record_recovery_boundary": "local_controlled_service",
                    "token_scope": "benchmark-audit-bundle",
                    "token_key_version": "v1",
                    "policy_version": "v1",
                    "release_policy": "threshold_release",
                    "k_threshold": 1,
                    "reason_code": "k_threshold_passed",
                },
                "handoff_cleanup": {
                    "server": {
                        "role": "server",
                        "output_file": str((out_base / "sse_exports" / "server.pipe").resolve()),
                        "output_file_type": "fifo",
                        "managed_by_out_base": True,
                        "exists_after_run": False,
                        "status": "removed",
                    },
                    "client": {
                        "role": "client",
                        "output_file": str((out_base / "sse_exports" / "client.csv").resolve()),
                        "output_file_type": "file",
                        "managed_by_out_base": True,
                        "exists_after_run": False,
                        "status": "cleaned",
                    },
                },
                "summary": {
                    "checks_run": 2,
                    "error_count": 0,
                },
                "findings": [],
            },
        },
    )
    run_checked(
        [
            sys.executable,
            str(VALIDATE_JSON_PY),
            "--schema",
            str(AUDIT_CHAIN_SCHEMA),
            "--json",
            str(audit_chain_path),
        ],
        env=env,
        label="validate audit_chain fixture",
    )
    run_checked(
        [
            sys.executable,
            str(SEAL_AUDIT_PY),
            "--input",
            str(audit_chain_path),
            "--out",
            str(audit_seal_path),
            "--job-id",
            FIXTURE_JOB_ID,
            "--hmac-key-env",
            HMAC_KEY_ENV,
        ],
        env=env,
        label="seal audit fixture",
    )
    run_checked(
        [
            sys.executable,
            str(VALIDATE_JSON_PY),
            "--schema",
            str(AUDIT_SEAL_SCHEMA),
            "--json",
            str(audit_seal_path),
        ],
        env=env,
        label="validate audit_seal fixture",
    )
    return audit_chain_path, audit_seal_path


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def read_last_jsonl_record(path: Path) -> dict[str, Any]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"empty JSONL file: {path}")
    payload = json.loads(lines[-1])
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object in JSONL file: {path}")
    return payload


def validate_archive_index(index_path: Path) -> dict[str, Any]:
    if not index_path.is_file():
        raise RuntimeError(f"missing archive index: {index_path}")
    record = read_last_jsonl_record(index_path)
    if record.get("schema") != "audit_archive_index/v1":
        raise RuntimeError(f"unexpected archive index schema: {record}")
    if record.get("job_id") != FIXTURE_JOB_ID:
        raise RuntimeError(f"unexpected archive index job_id: {record.get('job_id')}")
    archived_chain = Path(str(record.get("archived_audit_chain_file", "")))
    archived_seal = Path(str(record.get("archived_audit_seal_file", "")))
    if not archived_chain.is_file() or not archived_seal.is_file():
        raise RuntimeError("archived audit files are missing")
    mainline = record.get("mainline_contract_summary") if isinstance(record.get("mainline_contract_summary"), dict) else {}
    if mainline.get("schema") != "mainline_contract_check/v1":
        raise RuntimeError(f"archive index missing mainline contract summary schema: {record}")
    if mainline.get("status") != "ok" or mainline.get("embedded_in_audit_chain") is not True:
        raise RuntimeError(f"archive index mainline contract summary invalid: {record}")
    handoff = mainline.get("handoff_cleanup") if isinstance(mainline.get("handoff_cleanup"), dict) else {}
    if handoff.get("server") != "removed" or handoff.get("client") != "cleaned":
        raise RuntimeError(f"archive index handoff cleanup summary invalid: {record}")
    service_consistency = (
        mainline.get("service_audit_consistency")
        if isinstance(mainline.get("service_audit_consistency"), dict)
        else {}
    )
    if (
        service_consistency.get("server") != "not_applicable"
        or service_consistency.get("client") != "not_applicable"
        or service_consistency.get("error_count") != 0
    ):
        raise RuntimeError(f"archive index service audit consistency summary invalid: {record}")
    anchor_path = Path(str(record.get("anchor_file", "")))
    if not anchor_path.is_file():
        raise RuntimeError(f"archive index is missing anchor file: {record}")
    return {
        "archive_index_path": str(index_path),
        "anchor_log_path": str(anchor_path),
        "archived_audit_chain_file": str(archived_chain),
        "archived_audit_seal_file": str(archived_seal),
    }


def validate_verify_report(
    payload: dict[str, Any],
    *,
    expect_archive_index: bool,
    expect_restore: bool,
) -> dict[str, Any]:
    if payload.get("schema") != "audit_bundle_verification/v1":
        raise RuntimeError(f"unexpected verify schema: {payload}")
    if payload.get("verified") is not True:
        raise RuntimeError(f"audit bundle was not verified: {payload}")
    if payload.get("job_id") != FIXTURE_JOB_ID:
        raise RuntimeError(f"unexpected verify job_id: {payload.get('job_id')}")
    if bool(payload.get("archive_index_verified")) != expect_archive_index:
        raise RuntimeError(f"unexpected archive_index_verified flag: {payload}")
    if bool(payload.get("anchor_log_verified")) != expect_archive_index:
        raise RuntimeError(f"unexpected anchor_log_verified flag: {payload}")
    mainline = payload.get("mainline_contract_summary") if isinstance(payload.get("mainline_contract_summary"), dict) else {}
    if mainline.get("schema") != "mainline_contract_check/v1":
        raise RuntimeError(f"verify report missing mainline contract summary schema: {payload}")
    if mainline.get("status") != "ok" or mainline.get("embedded_in_audit_chain") is not True:
        raise RuntimeError(f"verify report mainline contract summary invalid: {payload}")
    handoff = mainline.get("handoff_cleanup") if isinstance(mainline.get("handoff_cleanup"), dict) else {}
    if handoff.get("server") != "removed" or handoff.get("client") != "cleaned":
        raise RuntimeError(f"verify report handoff cleanup summary invalid: {payload}")
    service_consistency = (
        mainline.get("service_audit_consistency")
        if isinstance(mainline.get("service_audit_consistency"), dict)
        else {}
    )
    if (
        service_consistency.get("server") != "not_applicable"
        or service_consistency.get("client") != "not_applicable"
        or service_consistency.get("error_count") != 0
    ):
        raise RuntimeError(f"verify report service audit consistency summary invalid: {payload}")
    restored = payload.get("restored")
    if expect_restore:
        if not isinstance(restored, dict):
            raise RuntimeError(f"missing restored payload: {payload}")
        restored_chain = Path(str(restored.get("restored_audit_chain_file", "")))
        restored_seal = Path(str(restored.get("restored_audit_seal_file", "")))
        if not restored_chain.is_file() or not restored_seal.is_file():
            raise RuntimeError(f"restored bundle files are missing: {payload}")
    elif restored is not None:
        raise RuntimeError(f"unexpected restore payload: {payload}")
    return {
        "verified": True,
        "signature_verified": payload.get("signature_verified"),
        "archive_index_verified": bool(payload.get("archive_index_verified")),
        "anchor_log_verified": bool(payload.get("anchor_log_verified")),
        "anchor_signature_verified": payload.get("anchor_signature_verified"),
        "anchor_log_path": payload.get("anchor_file"),
        "restored": expect_restore,
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


def bootstrap_archive_fixture(
    *,
    env: dict[str, str],
    audit_chain_path: Path,
    audit_seal_path: Path,
    archive_dir: Path,
) -> Path:
    run_checked(
        [
            sys.executable,
            str(ARCHIVE_BUNDLE_PY),
            "--audit-chain",
            str(audit_chain_path),
            "--audit-seal",
            str(audit_seal_path),
            "--archive-dir",
            str(archive_dir),
            "--job-id",
            FIXTURE_JOB_ID,
            "--hmac-key-env",
            HMAC_KEY_ENV,
            "--anchor-key-env",
            ANCHOR_KEY_ENV,
        ],
        env=env,
        label="bootstrap archive fixture",
    )
    index_path = archive_dir / "audit_chain_index.jsonl"
    validate_archive_index(index_path)
    return index_path


def run_mode_once(*, mode: str, iteration: int, timeout_sec: float, common_env: dict[str, str]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"seccomp_audit_bundle_bench.{mode}.{iteration}.") as tmp_dir:
        run_root = Path(tmp_dir)
        env = dict(common_env)
        audit_chain_path, audit_seal_path = materialize_fixture(run_root, env=env)
        archive_index_path: str | None = None
        restored = False
        signature_verified: bool | None = None
        anchor_signature_verified: bool | None = None

        if mode == "archive_cli":
            archive_dir = run_root / "archive"
            command = [
                sys.executable,
                str(ARCHIVE_BUNDLE_PY),
                "--audit-chain",
                str(audit_chain_path),
                "--audit-seal",
                str(audit_seal_path),
                "--archive-dir",
                str(archive_dir),
                "--job-id",
                FIXTURE_JOB_ID,
                "--hmac-key-env",
                HMAC_KEY_ENV,
                "--anchor-key-env",
                ANCHOR_KEY_ENV,
            ]
            result, stdout = run_command(command, env=env, timeout_sec=timeout_sec)
            stdout_tail = "\n".join(stdout.splitlines()[-20:]) if stdout else ""
            if result["exit_code"] == 0:
                archive_metrics = validate_archive_index(archive_dir / "audit_chain_index.jsonl")
                archive_index_path = archive_metrics["archive_index_path"]
                anchor_signature_verified = True
                signature_verified = True
            return {
                **result,
                "stdout_tail": stdout_tail,
                "verified": result["exit_code"] == 0,
                "signature_verified": signature_verified,
                "archive_index_verified": result["exit_code"] == 0,
                "anchor_log_verified": result["exit_code"] == 0,
                "anchor_signature_verified": anchor_signature_verified,
                "anchor_log_path": archive_metrics["anchor_log_path"] if result["exit_code"] == 0 else None,
                "restored": False,
                "archive_index_path": archive_index_path,
            }

        if mode == "verify_direct_cli":
            command = [
                sys.executable,
                str(VERIFY_BUNDLE_PY),
                "--audit-chain",
                str(audit_chain_path),
                "--audit-seal",
                str(audit_seal_path),
                "--job-id",
                FIXTURE_JOB_ID,
                "--hmac-key-env",
                HMAC_KEY_ENV,
                "--anchor-key-env",
                ANCHOR_KEY_ENV,
            ]
            expect_archive_index = False
            expect_restore = False
        else:
            bootstrap_archive_dir = run_root / "archive_bootstrap"
            bootstrap_index_path = bootstrap_archive_fixture(
                env=env,
                audit_chain_path=audit_chain_path,
                audit_seal_path=audit_seal_path,
                archive_dir=bootstrap_archive_dir,
            )
            archive_index_path = str(bootstrap_index_path)
            command = [
                sys.executable,
                str(VERIFY_BUNDLE_PY),
                "--archive-index",
                str(bootstrap_index_path),
                "--job-id",
                FIXTURE_JOB_ID,
                "--hmac-key-env",
                HMAC_KEY_ENV,
                "--anchor-key-env",
                ANCHOR_KEY_ENV,
            ]
            expect_archive_index = True
            expect_restore = mode == "verify_archive_index_restore_cli"
            if expect_restore:
                command.extend(["--restore-dir", str(run_root / "restored_bundle")])

        result, stdout = run_command(command, env=env, timeout_sec=timeout_sec)
        stdout_tail = "\n".join(stdout.splitlines()[-20:]) if stdout else ""
        if result["exit_code"] != 0:
            return {
                **result,
                "stdout_tail": stdout_tail,
                "verified": False,
                "signature_verified": None,
                "archive_index_verified": expect_archive_index,
                "anchor_log_verified": expect_archive_index,
                "anchor_signature_verified": None,
                "anchor_log_path": None,
                "restored": expect_restore,
                "archive_index_path": archive_index_path,
            }
        payload = json.loads(stdout)
        if not isinstance(payload, dict):
            raise RuntimeError(f"expected JSON verify output: {payload!r}")
        verify_metrics = validate_verify_report(
            payload,
            expect_archive_index=expect_archive_index,
            expect_restore=expect_restore,
        )
        restored = verify_metrics["restored"]
        signature_verified = verify_metrics["signature_verified"]
        return {
            **result,
            "stdout_tail": stdout_tail,
            "verified": verify_metrics["verified"],
            "signature_verified": signature_verified,
            "archive_index_verified": verify_metrics["archive_index_verified"],
            "anchor_log_verified": verify_metrics["anchor_log_verified"],
            "anchor_signature_verified": verify_metrics["anchor_signature_verified"],
            "anchor_log_path": verify_metrics["anchor_log_path"],
            "restored": restored,
            "archive_index_path": archive_index_path,
        }


def example_command_for_mode(mode: str) -> list[str]:
    base = [sys.executable]
    if mode == "archive_cli":
        return base + [
            str(ARCHIVE_BUNDLE_PY),
            "--audit-chain",
            "/tmp/audit_chain.json",
            "--audit-seal",
            "/tmp/audit_chain.seal.json",
            "--archive-dir",
            "/tmp/audit_archive",
            "--job-id",
            FIXTURE_JOB_ID,
            "--hmac-key-env",
            HMAC_KEY_ENV,
            "--anchor-key-env",
            ANCHOR_KEY_ENV,
        ]
    command = base + [
        str(VERIFY_BUNDLE_PY),
        "--job-id",
        FIXTURE_JOB_ID,
        "--hmac-key-env",
        HMAC_KEY_ENV,
    ]
    if mode == "verify_direct_cli":
        return command + [
            "--audit-chain",
            "/tmp/audit_chain.json",
            "--audit-seal",
            "/tmp/audit_chain.seal.json",
        ]
    if mode == "verify_archive_index_cli":
        return command + [
            "--archive-index",
            "/tmp/audit_archive/audit_chain_index.jsonl",
        ]
    return command + [
        "--archive-index",
        "/tmp/audit_archive/audit_chain_index.jsonl",
        "--restore-dir",
        "/tmp/restored_audit_bundle",
    ]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Benchmark archive/verify audit bundle entrypoints over a synthetic sealed audit_chain fixture.",
    )
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

    common_env = dict(os.environ)
    common_env[HMAC_KEY_ENV] = "benchmark-audit-bundle-secret"
    common_env[ANCHOR_KEY_ENV] = "benchmark-audit-bundle-anchor-secret"
    selected_modes = list(MODES) if args.mode == "all" else [args.mode]
    mode_entries: list[dict[str, Any]] = []

    for mode in selected_modes:
        mode_results = [
            run_mode_once(mode=mode, iteration=iteration, timeout_sec=args.timeout_sec, common_env=common_env)
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
        "schema": "audit_bundle_benchmark/v1",
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "fixture_profile": FIXTURE_PROFILE,
        "job_id": FIXTURE_JOB_ID,
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
