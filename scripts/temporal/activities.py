"""Temporal Activities for the SSE-Bridge-A-PSI pipeline.

Each activity wraps an existing CLI call. No privacy-compute logic is rewritten here.
Activities return structured results; failures surface as application errors.

Requirements: pip install temporalio
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from temporalio import activity


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _repo_path(rel: str) -> str:
    return os.path.join(REPO_ROOT, rel)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


@dataclass
class PipelineContext:
    """Shared context passed through the workflow."""
    job_id: str = ""
    correlation_id: str = ""
    caller: str = "temporal_workflow"
    tenant_id: str = "default_tenant"
    out_base: str = ""
    sse_export_dir: str = ""
    bridge_job_dir: str = ""
    apsi_job_dir: str = ""
    token_scope: str = ""
    token_secret_env: str = "BRIDGE_TOKEN_SECRET"
    token_key_version: str = "1"
    production_mode: bool = False
    sse_export_policy_config: str = ""
    server_source: str = ""
    client_source: str = ""
    server_join_key_field: str = "email"
    client_join_key_field: str = "email"
    client_value_field: str = "amount"
    server_normalizer: str = "email"
    client_normalizer: str = "email"
    client_value_mode: str = "raw-int"
    server_filter: str = ""
    client_filter: str = ""
    k_threshold: int = 20
    rate_n: int = 5
    deny_duplicate_query: bool = False
    audit_seal_key_env: str = ""
    server_sse_keyword: str = ""
    client_sse_keyword: str = ""
    server_record_id_field: str = ""
    client_record_id_field: str = ""
    sse_export_handoff_mode: str = "file"

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PipelineContext":
        ctx = cls()
        for k, v in d.items():
            if hasattr(ctx, k):
                setattr(ctx, k, v)
        return ctx


def _run_cmd(cmd: List[str], cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Run a command and return structured result. Never logs token values."""
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    activity.logger.info(f"Running: {' '.join(c for c in cmd if not c.startswith('--token-secret'))}")

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or REPO_ROOT,
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired as e:
        return {
            "success": False,
            "exit_code": -1,
            "stdout": e.stdout or "",
            "stderr": f"Command timed out after 600s: {e}",
            "error": "timeout",
        }

    return {
        "success": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": result.stdout[:100000],
        "stderr": result.stderr[:100000],
        "error": "" if result.returncode == 0 else f"exit_code={result.returncode}",
    }


@activity.defn
async def validate_policy_activity(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Validate pipeline policy before proceeding."""
    c = PipelineContext.from_dict(ctx)

    if not c.sse_export_policy_config or not os.path.isfile(c.sse_export_policy_config):
        activity.logger.warning("No SSE export policy config; skipping policy validation")
        return {"decision": "allow", "reason_code": "no_policy_config", "stage": "validate_policy"}

    cmd = [
        sys.executable,
        _repo_path("scripts/validate_pipeline_policy.py"),
        "--policy-config", c.sse_export_policy_config,
        "--caller", c.caller,
        "--require-bridge",
        "--require-pjc",
        "--require-release",
    ]
    result = _run_cmd(cmd)
    result["stage"] = "validate_policy"
    result["decision"] = "allow" if result["success"] else "deny"
    result["reason_code"] = "ok" if result["success"] else "policy_validation_failed"
    activity.logger.info(f"validate_policy: decision={result['decision']}")
    return result


@activity.defn
async def run_sse_export_activity(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Run SSE export by calling run_client.py export-bridge-records for server and client."""
    c = PipelineContext.from_dict(ctx)

    sse_py = _repo_path("sse/.venv/bin/python")
    if not os.path.isfile(sse_py):
        return {"success": False, "decision": "deny", "reason_code": "sse_py_missing", "stage": "sse_export"}

    sse_dir = _repo_path("sse")
    export_audit_log = os.path.join(c.sse_export_dir, "export_audit.jsonl")

    # Server export
    server_cmd = [
        sse_py, "run_client.py", "export-bridge-records",
        "--out-path", os.path.join(c.sse_export_dir, "server.csv"),
        "--role", "server",
        "--source-format", "jsonl",
        "--out-format", "csv",
        "--join-key-field", c.server_join_key_field,
        "--caller", c.caller,
        "--audit-log", export_audit_log,
        "--job-id", c.job_id,
    ]
    if c.server_source:
        server_cmd += ["--source-path", c.server_source]
    if c.server_filter:
        server_cmd += ["--filter", c.server_filter]
    if c.sse_export_policy_config and os.path.isfile(c.sse_export_policy_config):
        server_cmd += ["--policy-config", c.sse_export_policy_config]
    if c.server_sse_keyword:
        server_cmd += ["--sse-keyword", c.server_sse_keyword,
                       "--record-id-field", c.server_record_id_field]

    server_result = _run_cmd(server_cmd, cwd=sse_dir)

    # Client export
    client_cmd = [
        sse_py, "run_client.py", "export-bridge-records",
        "--out-path", os.path.join(c.sse_export_dir, "client.csv"),
        "--role", "client",
        "--source-format", "jsonl",
        "--out-format", "csv",
        "--join-key-field", c.client_join_key_field,
        "--value-field", c.client_value_field,
        "--caller", c.caller,
        "--audit-log", export_audit_log,
        "--job-id", c.job_id,
    ]
    if c.client_source:
        client_cmd += ["--source-path", c.client_source]
    if c.client_filter:
        client_cmd += ["--filter", c.client_filter]
    if c.sse_export_policy_config and os.path.isfile(c.sse_export_policy_config):
        client_cmd += ["--policy-config", c.sse_export_policy_config]
    if c.client_sse_keyword:
        client_cmd += ["--sse-keyword", c.client_sse_keyword,
                       "--record-id-field", c.client_record_id_field]

    client_result = _run_cmd(client_cmd, cwd=sse_dir)

    all_ok = server_result["success"] and client_result["success"]
    return {
        "success": all_ok,
        "decision": "allow" if all_ok else "deny",
        "reason_code": "ok" if all_ok else "sse_export_failed",
        "stage": "sse_export",
        "server_ok": server_result["success"],
        "client_ok": client_result["success"],
        "export_audit_log": export_audit_log,
    }


@activity.defn
async def run_record_recovery_health_check_activity(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Validate that record recovery service audit logs exist and are valid, if applicable."""
    c = PipelineContext.from_dict(ctx)
    recovery_audit = os.path.join(c.sse_export_dir, "record_recovery_service_audit.jsonl")

    if not os.path.isfile(recovery_audit):
        activity.logger.info("No record recovery service audit log; skipping health check")
        return {"success": True, "decision": "allow", "reason_code": "no_recovery_used", "stage": "record_recovery_health_check"}

    cmd = [
        sys.executable,
        _repo_path("scripts/validate_json_contract.py"),
        "--schema", _repo_path("schemas/sse_record_recovery_service_audit.schema.json"),
        "--jsonl", recovery_audit,
    ]
    result = _run_cmd(cmd)
    result["stage"] = "record_recovery_health_check"
    result["decision"] = "allow" if result["success"] else "deny"
    result["reason_code"] = "ok" if result["success"] else "recovery_audit_invalid"
    return result


@activity.defn
async def run_bridge_prepare_job_activity(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Run bridge prepare-job by calling the Rust bridge binary or cargo run."""
    c = PipelineContext.from_dict(ctx)
    bridge_bin = os.environ.get("BRIDGE_BIN", "cargo run --")
    bridge_dir = _repo_path("bridge")

    server_csv = os.path.join(c.sse_export_dir, "server.csv")
    client_csv = os.path.join(c.sse_export_dir, "client.csv")

    if not os.path.isfile(server_csv):
        return {"success": False, "decision": "deny", "reason_code": "server_csv_missing", "stage": "bridge"}
    if not os.path.isfile(client_csv):
        return {"success": False, "decision": "deny", "reason_code": "client_csv_missing", "stage": "bridge"}

    cmd = bridge_bin.split() + [
        "prepare-job",
        "--server-input", server_csv,
        "--server-input-format", "csv",
        "--server-join-key-column", c.server_join_key_field,
        "--server-normalizer", c.server_normalizer,
        "--client-input", client_csv,
        "--client-input-format", "csv",
        "--client-join-key-column", c.client_join_key_field,
        "--client-value-mode", c.client_value_mode,
        "--client-normalizer", c.client_normalizer,
        "--out-dir", c.bridge_job_dir,
        "--job-id", c.job_id,
        "--token-scope", c.token_scope,
        "--token-key-version", c.token_key_version,
        "--audit-log", os.path.join(c.bridge_job_dir, "bridge_audit.jsonl"),
    ]
    if c.client_value_mode == "raw-int" and c.client_value_field:
        cmd += ["--client-value-column", c.client_value_field]
    if c.production_mode:
        cmd += ["--production-mode"]
    cmd += ["--token-secret-env", c.token_secret_env]

    result = _run_cmd(cmd, cwd=bridge_dir)
    result["stage"] = "bridge"
    result["decision"] = "allow" if result["success"] else "deny"
    result["reason_code"] = "ok" if result["success"] else "bridge_failed"
    return result


@activity.defn
async def run_pjc_activity(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Run A-PSI PJC execution by calling run_pjc.sh with bridge outputs."""
    c = PipelineContext.from_dict(ctx)

    bridge_job_meta = os.path.join(c.bridge_job_dir, "job_meta.json")
    if os.path.isfile(bridge_job_meta):
        import shutil
        shutil.copy2(bridge_job_meta, os.path.join(c.apsi_job_dir, "job_meta.json"))

    cmd = [
        "bash",
        _repo_path("a-psi/moduleA_psi/scripts/run_pjc.sh"),
    ]
    env = {
        "JOB_ID": c.job_id,
        "OUT_DIR": c.apsi_job_dir,
        "SERVER_CSV": os.path.join(c.bridge_job_dir, "server.csv"),
        "CLIENT_CSV": os.path.join(c.bridge_job_dir, "client.csv"),
        "PJC_BIN_DIR": os.environ.get("PJC_BIN_DIR", _repo_path("a-psi/private-join-and-compute/bazel-bin")),
    }
    result = _run_cmd(cmd, cwd=_repo_path("a-psi"), env=env)
    result["stage"] = "pjc"
    result["decision"] = "allow" if result["success"] else "deny"
    result["reason_code"] = "ok" if result["success"] else "pjc_failed"
    return result


@activity.defn
async def run_policy_release_activity(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Run policy release by calling policy_release.py."""
    c = PipelineContext.from_dict(ctx)

    cmd = [
        sys.executable,
        _repo_path("a-psi/moduleA_psi/scripts/policy_release.py"),
        "--job-dir", c.apsi_job_dir,
        "--caller", c.caller,
        "--k", str(c.k_threshold),
        "--n", str(c.rate_n),
    ]
    if c.deny_duplicate_query:
        cmd.append("--deny-duplicate-query")

    result = _run_cmd(cmd, cwd=_repo_path("a-psi"))
    result["stage"] = "policy_release"

    public_report_path = os.path.join(c.apsi_job_dir, "public_report.json")
    if os.path.isfile(public_report_path):
        with open(public_report_path, "r") as f:
            report = json.load(f)
        result["released"] = report.get("released", False)
        result["reason_code"] = report.get("reason_code", "unknown")
        result["intersection_size"] = report.get("conversions", 0)
        result["intersection_sum"] = report.get("value_sum", 0)

    result["decision"] = "allow" if result["success"] else "deny"
    return result


@activity.defn
async def build_audit_chain_activity(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Build the cross-stage audit chain and seal."""
    c = PipelineContext.from_dict(ctx)

    cmd = [
        sys.executable,
        _repo_path("scripts/build_audit_chain.py"),
        "--out-base", c.out_base,
        "--job-id", c.job_id,
    ]
    result = _run_cmd(cmd)
    result["stage"] = "audit_chain"

    if not result["success"]:
        result["decision"] = "deny"
        result["reason_code"] = "audit_chain_failed"
        return result

    seal_cmd = [
        sys.executable,
        _repo_path("scripts/seal_audit_artifact.py"),
        "--input", os.path.join(c.out_base, "audit_chain.json"),
        "--out", os.path.join(c.out_base, "audit_chain.seal.json"),
        "--job-id", c.job_id,
    ]
    if c.audit_seal_key_env:
        seal_cmd += ["--hmac-key-env", c.audit_seal_key_env]

    seal_result = _run_cmd(seal_cmd)
    result["seal_ok"] = seal_result["success"]
    result["decision"] = "allow" if seal_result["success"] else "deny"
    result["reason_code"] = "ok" if seal_result["success"] else "audit_seal_failed"
    return result


@activity.defn
async def run_telemetry_activity(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Generate telemetry from the completed pipeline run."""
    c = PipelineContext.from_dict(ctx)

    cmd = [
        sys.executable,
        _repo_path("scripts/telemetry_pipeline.py"),
        "--out-base", c.out_base,
        "--tenant-id", c.tenant_id,
        "--format", "otlp-jsonl",
    ]
    result = _run_cmd(cmd)
    result["stage"] = "telemetry"
    result["decision"] = "allow" if result["success"] else "deny"
    result["reason_code"] = "ok" if result["success"] else "telemetry_failed"
    return result


@activity.defn
async def run_runbook_activity(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a runbook from the completed pipeline run."""
    c = PipelineContext.from_dict(ctx)

    cmd = [
        sys.executable,
        _repo_path("scripts/generate_observability_runbook.py"),
        "--out-base", c.out_base,
        "--job-id", c.job_id,
    ]
    result = _run_cmd(cmd)
    result["stage"] = "runbook"
    result["decision"] = "allow" if result["success"] else "deny"
    result["reason_code"] = "ok" if result["success"] else "runbook_failed"
    return result
