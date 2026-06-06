#!/usr/bin/env python3
"""
Pre-release gate: runs all fast contract-check and benchmark gate scripts,
validates each output against its schema, and emits a consolidated
pre_release_gate/v1 JSON report.

Exits non-zero if any gate fails.

Usage:
    python3 scripts/check_pre_release_gate.py [--out report.json]
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent
SCRIPTS = REPO_ROOT / "scripts"
SCHEMAS = REPO_ROOT / "schemas"
VALIDATOR_PY = SCRIPTS / "validate_json_contract.py"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _schema_path(schema_id: str) -> Path | None:
    """Return schema file path for a given $id, or None if not found."""
    base = schema_id.split("/")[0]
    candidate = SCHEMAS / f"{base}.schema.json"
    if candidate.exists():
        return candidate
    return None


def run_gate(
    *,
    name: str,
    cmd: list[str],
    output_path: Path,
    output_schema_id: str | None,
) -> dict[str, Any]:
    """Run a single gate sub-check and return a result dict."""
    started = time.perf_counter()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    duration_ms = round((time.perf_counter() - started) * 1000, 1)

    exit_code = result.returncode
    stderr_tail = "\n".join(result.stderr.strip().splitlines()[-5:]) if result.stderr.strip() else ""

    output_schema_valid: bool | None = None
    schema_error: str | None = None

    if output_schema_id and output_path.exists() and exit_code == 0:
        schema_path = _schema_path(output_schema_id)
        if schema_path:
            val = subprocess.run(
                [sys.executable, str(VALIDATOR_PY), "--schema", str(schema_path), "--json", str(output_path)],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            output_schema_valid = val.returncode == 0
            if not output_schema_valid:
                schema_error = (val.stdout + val.stderr).strip()
        else:
            output_schema_valid = None

    status = "pass" if exit_code == 0 and (output_schema_valid is not False) else "fail"
    return {
        "name": name,
        "status": status,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "output_schema": output_schema_id,
        "output_schema_valid": output_schema_valid,
        "stderr_tail": stderr_tail or None,
        "schema_error": schema_error,
    }


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Pre-release gate: runs all fast contract and benchmark checks.")
    ap.add_argument("--out", default="", help="Path to write pre_release_gate/v1 JSON report (default: stdout)")
    ap.add_argument("--verbose", action="store_true", help="Print each gate result as it completes")
    args = ap.parse_args()

    generated_at = utc_now_iso()
    gate_results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="seccomp_gate_") as tmpdir:
        tmp = Path(tmpdir)

        gates: list[tuple[str, list[str], Path, str | None]] = [
            (
                "repo_hygiene",
                [sys.executable, str(SCRIPTS / "scan_repo_hygiene.py"), "--fail-on-warn", "--output", str(tmp / "repo_hygiene.json")],
                tmp / "repo_hygiene.json",
                "repo_hygiene_scan/v1",
            ),
            (
                "dependency_hygiene",
                [sys.executable, str(SCRIPTS / "check_dependency_hygiene.py"), "--fail-on-warn", "--output", str(tmp / "dep_hygiene.json")],
                tmp / "dep_hygiene.json",
                "dependency_hygiene/v1",
            ),
            (
                "supply_chain_evidence",
                [sys.executable, str(SCRIPTS / "check_supply_chain_gate.py"), "--out", str(tmp / "supply_chain.json")],
                tmp / "supply_chain.json",
                "supply_chain_evidence/v1",
            ),
            (
                "legacy_sse_production_gate",
                [
                    sys.executable,
                    str(SCRIPTS / "check_legacy_sse_production_gate.py"),
                    "--out",
                    str(tmp / "legacy_sse_production_gate.json"),
                ],
                tmp / "legacy_sse_production_gate.json",
                "legacy_sse_production_gate/v1",
            ),
            (
                "query_workflow_durability",
                [
                    sys.executable,
                    str(SCRIPTS / "check_query_workflow_durability.py"),
                    "--out",
                    str(tmp / "query_workflow_durability.json"),
                ],
                tmp / "query_workflow_durability.json",
                "query_workflow_durability_check/v1",
            ),
            (
                "schema_backcompat",
                [sys.executable, str(SCRIPTS / "check_schema_backcompat.py"), "--output", str(tmp / "backcompat.json")],
                tmp / "backcompat.json",
                "schema_backcompat_check/v1",
            ),
            (
                "metadata_backup_restore_drill",
                [
                    sys.executable,
                    str(SCRIPTS / "check_metadata_backup_restore_drill.py"),
                    "--out",
                    str(tmp / "metadata_backup_restore_drill.json"),
                ],
                tmp / "metadata_backup_restore_drill.json",
                "metadata_backup_restore_drill/v1",
            ),
            (
                "malformed_input",
                [sys.executable, str(SCRIPTS / "check_malformed_input_gate.py"), "--out", str(tmp / "malformed.json")],
                tmp / "malformed.json",
                "malformed_input_gate/v1",
            ),
            (
                "record_recovery_boundary",
                [sys.executable, str(SCRIPTS / "check_record_recovery_boundary.py"), "--output", str(tmp / "rr_boundary.json")],
                tmp / "rr_boundary.json",
                "record_recovery_boundary_check/v1",
            ),
            (
                "record_recovery_production_gate",
                [
                    sys.executable,
                    str(SCRIPTS / "check_record_recovery_production_gate.py"),
                    "--out",
                    str(tmp / "rr_production_gate.json"),
                ],
                tmp / "rr_production_gate.json",
                "record_recovery_production_gate_check/v1",
            ),
            (
                "query_workflow_benchmark",
                [
                    sys.executable, str(SCRIPTS / "benchmark_query_workflow.py"),
                    "--iterations", "1", "--output", str(tmp / "qw_bench.json"),
                ],
                tmp / "qw_bench.json",
                "query_workflow_benchmark/v1",
            ),
            (
                "read_adapter_benchmark",
                [
                    sys.executable, str(SCRIPTS / "benchmark_read_adapters.py"),
                    "--iterations", "1", "--output", str(tmp / "rad_bench.json"),
                ],
                tmp / "rad_bench.json",
                "read_adapter_benchmark/v1",
            ),
            (
                "record_recovery_benchmark",
                [
                    sys.executable, str(SCRIPTS / "benchmark_record_recovery.py"),
                    "--iterations", "1", "--output", str(tmp / "rr_bench.json"),
                ],
                tmp / "rr_bench.json",
                "record_recovery_benchmark/v1",
            ),
            (
                "audit_bundle_benchmark",
                [
                    sys.executable, str(SCRIPTS / "benchmark_audit_bundle.py"),
                    "--iterations", "1", "--output", str(tmp / "ab_bench.json"),
                ],
                tmp / "ab_bench.json",
                "audit_bundle_benchmark/v1",
            ),
            (
                "platform_health_benchmark",
                [
                    sys.executable, str(SCRIPTS / "benchmark_platform_health.py"),
                    "--iterations", "1", "--output", str(tmp / "ph_bench.json"),
                ],
                tmp / "ph_bench.json",
                "platform_health_benchmark/v1",
            ),
            (
                "derived_views_benchmark",
                [
                    sys.executable, str(SCRIPTS / "benchmark_derived_views.py"),
                    "--iterations", "1", "--output", str(tmp / "dv_bench.json"),
                ],
                tmp / "dv_bench.json",
                "derived_views_benchmark/v1",
            ),
        ]

        for name, cmd, output_path, schema_id in gates:
            r = run_gate(name=name, cmd=cmd, output_path=output_path, output_schema_id=schema_id)
            gate_results.append(r)
            if args.verbose or r["status"] == "fail":
                status_icon = "[ok]" if r["status"] == "pass" else "[FAIL]"
                schema_ok = "" if r["output_schema_valid"] is None else f" schema={r['output_schema_valid']}"
                print(f"{status_icon} {name}: exit={r['exit_code']} duration={r['duration_ms']}ms{schema_ok}")
                if r["status"] == "fail" and r.get("stderr_tail"):
                    print(f"  stderr: {r['stderr_tail']}", file=sys.stderr)
                if r.get("schema_error"):
                    print(f"  schema_error: {r['schema_error']}", file=sys.stderr)

    total = len(gate_results)
    passed = sum(1 for r in gate_results if r["status"] == "pass")
    failed = total - passed
    status = "ok" if failed == 0 else "fail"

    report: dict[str, Any] = {
        "schema": "pre_release_gate/v1",
        "generated_at_utc": generated_at,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "status": status,
        },
        "gates": gate_results,
    }

    report_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(report_text + "\n", encoding="utf-8")
        print(f"[ok] pre_release_gate: {total} gates, {passed} passed, {failed} failed → {status}")
    else:
        print(report_text)

    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
