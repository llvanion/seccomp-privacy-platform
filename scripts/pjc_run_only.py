#!/usr/bin/env python3
"""PJC-only helper: run private join-and-compute against pre-built CSVs.

Skips the bridge step entirely. Assumes the caller already has tokenized
server.csv + client.csv on disk (typically produced by `bridge prepare-job`).
Runs PJC + the policy release gate and emits a single JSON document with the
attribution result + public report side-by-side.

Used by the operator-dashboard endpoint POST /v1/pjc/run-only so the SPA can
trigger a PJC computation without re-running the SSE / bridge stages.

Schema: pjc_run_only/v1.

Usage:
    scripts/pjc_run_only.py --request-file /tmp/pjc-req.json

Request JSON shape:
    {
      "server_csv": "/abs/path/server.csv",
      "client_csv": "/abs/path/client.csv",
      "job_meta": "/abs/path/job_meta.json",     # optional
      "out_dir":  "/abs/path/run",               # optional (default: mkdtemp)
      "job_id":   "demo",                        # optional
      "caller":   "console-operator",            # optional
      "threshold_k": 1,                          # optional, default 1
      "max_queries": 5,                          # optional, default 5
      "deny_duplicate_query": false,             # optional
      "dp_epsilon": null,                        # optional float
      "dp_sensitivity": null,                    # optional float
      "round_sum_to": null,                      # optional int
      "value_mode": "raw-int",                   # informational
      "pjc_build": true                          # set false to skip cargo/bazel rebuild
    }
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_ROOT = REPO_ROOT / "a-psi" / "moduleA_psi"
RUN_PJC_SH = MODULE_ROOT / "scripts" / "run_pjc.sh"
POLICY_RELEASE_PY = MODULE_ROOT / "scripts" / "policy_release.py"


def _emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def _emit_error(stage: str, message: str, **extra: Any) -> None:
    payload = {
        "schema": "pjc_run_only/v1",
        "status": "error",
        "stage": stage,
        "message": message,
    }
    payload.update(extra)
    _emit(payload)


def _require_file(path: str, label: str) -> Path | None:
    p = Path(path).expanduser()
    try:
        resolved = p.resolve(strict=True)
    except FileNotFoundError:
        _emit_error("validate", f"{label} not found: {path}")
        return None
    if not resolved.is_file():
        _emit_error("validate", f"{label} is not a regular file: {resolved}")
        return None
    return resolved


def main() -> int:
    ap = argparse.ArgumentParser(description="Run PJC on prepared bridge CSVs + policy release.")
    ap.add_argument("--request-file", required=True, help="Path to JSON request body")
    args = ap.parse_args()

    try:
        request = json.loads(Path(args.request_file).read_text())
    except Exception as exc:  # noqa: BLE001
        _emit_error("read_request", f"failed to read request file: {exc}")
        return 2

    server_csv_arg = request.get("server_csv")
    client_csv_arg = request.get("client_csv")
    if not server_csv_arg or not client_csv_arg:
        _emit_error("validate", "both server_csv and client_csv are required")
        return 2

    server_csv = _require_file(server_csv_arg, "server_csv")
    if server_csv is None:
        return 2
    client_csv = _require_file(client_csv_arg, "client_csv")
    if client_csv is None:
        return 2

    job_meta_arg = request.get("job_meta")
    job_meta: Path | None = None
    if job_meta_arg:
        job_meta = _require_file(job_meta_arg, "job_meta")
        if job_meta is None:
            return 2

    job_id = str(request.get("job_id") or f"pjc-only-{int(time.time())}")
    caller = str(request.get("caller") or "console-operator")
    threshold_k = int(request.get("threshold_k") or 1)
    max_queries = int(request.get("max_queries") or 5)
    deny_dup = bool(request.get("deny_duplicate_query") or False)
    dp_epsilon = request.get("dp_epsilon")
    dp_sensitivity = request.get("dp_sensitivity")
    round_sum_to = request.get("round_sum_to")
    pjc_build = bool(request.get("pjc_build") if "pjc_build" in request else True)
    tenant_id = request.get("tenant_id")
    dataset_id = request.get("dataset_id")
    purpose = request.get("purpose")

    out_dir_arg = request.get("out_dir")
    workdir_owned = False
    if out_dir_arg:
        out_dir = Path(out_dir_arg).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = Path(tempfile.mkdtemp(prefix="pjc_run_only_"))
        workdir_owned = True
    out_dir = out_dir.resolve()

    started_at = time.monotonic()

    env = dict(os.environ)
    # Localhost gRPC must not be proxied.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    env["no_proxy"] = "127.0.0.1,localhost,0.0.0.0"

    env["SERVER_CSV"] = str(server_csv)
    env["CLIENT_CSV"] = str(client_csv)
    env["OUT_DIR"] = str(out_dir)
    env["JOB_ID"] = job_id
    env["PJC_BUILD"] = "1" if pjc_build else "0"

    # When the caller opts out of rebuilding, point the script at the in-tree
    # `bazel-bin` symlink directly. `bazel info bazel-bin` returns a path under
    # ~/.cache that may not contain the artifacts even when the workspace
    # symlink does.
    if not pjc_build:
        bazel_bin = REPO_ROOT / "a-psi" / "private-join-and-compute" / "bazel-bin"
        server_binary = bazel_bin / "private_join_and_compute" / "server"
        if server_binary.is_file() and os.access(server_binary, os.X_OK):
            env["PJC_BIN_DIR"] = str(bazel_bin)

    if not RUN_PJC_SH.is_file():
        _emit_error("validate", f"run_pjc.sh missing: {RUN_PJC_SH}")
        return 2

    pjc_log = out_dir / "run_pjc.log"
    try:
        with pjc_log.open("w") as fh:
            subprocess.run(["bash", str(RUN_PJC_SH)], env=env, stdout=fh, stderr=subprocess.STDOUT, check=True)
    except subprocess.CalledProcessError as exc:
        _emit_error(
            "run_pjc",
            f"run_pjc.sh exited with {exc.returncode}",
            log_path=str(pjc_log),
        )
        if workdir_owned:
            shutil.rmtree(out_dir, ignore_errors=True)
        return 3
    except FileNotFoundError:
        _emit_error("run_pjc", "bash not available on PATH")
        if workdir_owned:
            shutil.rmtree(out_dir, ignore_errors=True)
        return 3

    attribution_path = out_dir / "attribution_result.json"
    if not attribution_path.is_file():
        _emit_error(
            "run_pjc",
            "attribution_result.json missing after run_pjc.sh",
            out_dir=str(out_dir),
            log_path=str(pjc_log),
        )
        if workdir_owned:
            shutil.rmtree(out_dir, ignore_errors=True)
        return 3

    try:
        attribution = json.loads(attribution_path.read_text())
    except Exception as exc:  # noqa: BLE001
        _emit_error("parse_attribution", f"failed to parse attribution_result.json: {exc}")
        if workdir_owned:
            shutil.rmtree(out_dir, ignore_errors=True)
        return 4

    public_report_path = out_dir / "public_report.json"
    audit_log_path = out_dir / "policy_audit.jsonl"

    policy_cmd: list[str] = [
        sys.executable,
        str(POLICY_RELEASE_PY),
        "--input", str(attribution_path),
        "--out", str(public_report_path),
        "--audit-log", str(audit_log_path),
        "--caller", caller,
        "--job-id", job_id,
        "--threshold-k", str(threshold_k),
        "--max-queries", str(max_queries),
    ]
    if job_meta is not None:
        policy_cmd += ["--job-meta", str(job_meta)]
    if deny_dup:
        policy_cmd += ["--deny-duplicate-query"]
    if dp_epsilon is not None:
        policy_cmd += ["--dp-epsilon", str(dp_epsilon)]
    if dp_sensitivity is not None:
        policy_cmd += ["--dp-sensitivity", str(dp_sensitivity)]
    if round_sum_to is not None:
        policy_cmd += ["--round-sum-to", str(round_sum_to)]
    if tenant_id:
        policy_cmd += ["--tenant-id", str(tenant_id)]
    if dataset_id:
        policy_cmd += ["--dataset-id", str(dataset_id)]
    if purpose:
        policy_cmd += ["--purpose", str(purpose)]

    policy_log = out_dir / "policy_release.log"
    try:
        with policy_log.open("w") as fh:
            subprocess.run(policy_cmd, stdout=fh, stderr=subprocess.STDOUT, check=True)
    except subprocess.CalledProcessError as exc:
        _emit_error(
            "policy_release",
            f"policy_release.py exited with {exc.returncode}",
            log_path=str(policy_log),
        )
        if workdir_owned:
            shutil.rmtree(out_dir, ignore_errors=True)
        return 5

    public_report: dict[str, Any] | None = None
    if public_report_path.is_file():
        try:
            public_report = json.loads(public_report_path.read_text())
        except Exception as exc:  # noqa: BLE001
            _emit_error("parse_public_report", f"failed to parse public_report.json: {exc}")
            if workdir_owned:
                shutil.rmtree(out_dir, ignore_errors=True)
            return 6

    duration_ms = int((time.monotonic() - started_at) * 1000)

    payload: dict[str, Any] = {
        "schema": "pjc_run_only/v1",
        "status": "ok",
        "job_id": job_id,
        "caller": caller,
        "out_dir": str(out_dir),
        "duration_ms": duration_ms,
        "inputs": {
            "server_csv": str(server_csv),
            "client_csv": str(client_csv),
            "job_meta": str(job_meta) if job_meta else None,
        },
        "policy": {
            "threshold_k": threshold_k,
            "max_queries": max_queries,
            "deny_duplicate_query": deny_dup,
            "dp_epsilon": dp_epsilon,
            "dp_sensitivity": dp_sensitivity,
            "round_sum_to": round_sum_to,
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "purpose": purpose,
        },
        "attribution": attribution,
        "public_report": public_report,
        "artifacts": {
            "attribution_path": str(attribution_path),
            "public_report_path": str(public_report_path) if public_report_path.is_file() else None,
            "policy_audit_path": str(audit_log_path) if audit_log_path.is_file() else None,
            "run_pjc_log": str(pjc_log),
            "policy_release_log": str(policy_log),
        },
        "workdir_owned": workdir_owned,
    }
    _emit(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
