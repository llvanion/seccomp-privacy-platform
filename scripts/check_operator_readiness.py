#!/usr/bin/env python3
"""
Operator readiness check: validates example configuration files, bridge
example data, pre-release gate status, and documents required env vars.

Produces an operator_readiness/v1 JSON report.  Exits non-zero if any
critical check fails.

Usage:
    python3 scripts/check_operator_readiness.py [--out report.json]
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent
SCRIPTS = REPO_ROOT / "scripts"
SCHEMAS = REPO_ROOT / "schemas"
VALIDATOR_PY = SCRIPTS / "validate_json_contract.py"

# ---------------------------------------------------------------------------
# Env var catalog — authoritative list of SECCOMP_* variables used by the
# platform.  The script checks whether each is currently set so operators
# can see what's missing at a glance.
# ---------------------------------------------------------------------------

ENV_VAR_CATALOG: list[dict[str, str]] = [
    {
        "name": "SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY",
        "role": "audit_archive",
        "description": "HMAC key used to sign append-only audit archive anchor records. "
                       "Passed via --anchor-key-env to archive_audit_bundle.py.",
        "required_for": "audit_bundle_archiving_with_anchor",
    },
    {
        "name": "SECCOMP_AUDIT_QUERY_API_TOKEN",
        "role": "api_auth",
        "description": "Auth token for the audit query HTTP API (serve_audit_query_api.py). "
                       "Required when clients call the audit query API.",
        "required_for": "audit_query_api",
    },
    {
        "name": "SECCOMP_METADATA_API_TOKEN",
        "role": "api_auth",
        "description": "Auth token for the metadata HTTP API (serve_metadata_api.py).",
        "required_for": "metadata_api",
    },
    {
        "name": "SECCOMP_PLATFORM_HEALTH_API_TOKEN",
        "role": "api_auth",
        "description": "Auth token for the platform health HTTP API (serve_platform_health_api.py).",
        "required_for": "platform_health_api",
    },
    {
        "name": "SECCOMP_QUERY_WORKFLOW_API_TOKEN",
        "role": "api_auth",
        "description": "Auth token for the query workflow HTTP API (serve_query_workflow_api.py).",
        "required_for": "query_workflow_api",
    },
    {
        "name": "SECCOMP_KEY_AGENT_AUTH_TOKEN",
        "role": "key_agent",
        "description": "Auth token for the key agent service (key_agent_service.py).",
        "required_for": "key_agent",
    },
    {
        "name": "SECCOMP_EXTERNAL_KMS_TOKEN",
        "role": "external_kms",
        "description": "Bearer token for the external KMS read path (request_external_kms.py).",
        "required_for": "external_kms",
    },
    {
        "name": "SECCOMP_EXTERNAL_KMS_ADMIN_TOKEN",
        "role": "external_kms",
        "description": "Admin token for the external KMS manage path (manage_external_kms.py).",
        "required_for": "external_kms_admin",
    },
]

# ---------------------------------------------------------------------------
# Config files that must exist and be valid against their declared schema
# ---------------------------------------------------------------------------

CONFIG_EXAMPLES: list[tuple[str, str]] = [
    ("config/external_kms.example.json", "schemas/external_kms_config.schema.json"),
    ("config/key_manifest.example.json", "schemas/key_manifest.schema.json"),
    ("config/keyring.example.json", "schemas/keyring.schema.json"),
    ("config/record_recovery_authz_sqlite.example.json", "schemas/record_recovery_authz_source.schema.json"),
    ("config/record_recovery_http_service.example.json", "schemas/record_recovery_service_config.schema.json"),
    ("config/record_recovery_service.example.json", "schemas/record_recovery_service_config.schema.json"),
    ("config/record_recovery_service_policy.example.json", "schemas/record_recovery_service_policy.schema.json"),
    ("sse/config/ecommerce_access_policy.example.json", "schemas/sse_export_policy.schema.json"),
    ("sse/config/export_policy.example.json", "schemas/sse_export_policy.schema.json"),
]

BRIDGE_EXAMPLES: list[str] = [
    "bridge/examples/server_export.csv",
    "bridge/examples/client_export.csv",
    "sse/examples/bridge_server_records.jsonl",
    "sse/examples/bridge_client_records.jsonl",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_config_examples() -> dict[str, Any]:
    files_checked: list[str] = []
    files_failed: list[dict[str, str]] = []

    for rel_config, rel_schema in CONFIG_EXAMPLES:
        config_path = REPO_ROOT / rel_config
        schema_path = REPO_ROOT / rel_schema
        if not config_path.exists():
            files_failed.append({"file": rel_config, "error": "file not found"})
            continue
        if not schema_path.exists():
            files_failed.append({"file": rel_config, "error": f"schema not found: {rel_schema}"})
            continue
        result = subprocess.run(
            [sys.executable, str(VALIDATOR_PY), "--schema", str(schema_path), "--json", str(config_path)],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        files_checked.append(rel_config)
        if result.returncode != 0:
            err = (result.stdout + result.stderr).strip()
            files_failed.append({"file": rel_config, "error": err})

    status = "pass" if not files_failed else "fail"
    return {
        "name": "config_example_files",
        "status": status,
        "files_checked": len(files_checked),
        "files_failed": files_failed,
    }


def check_bridge_examples() -> dict[str, Any]:
    found: list[str] = []
    missing: list[str] = []
    for rel_path in BRIDGE_EXAMPLES:
        p = REPO_ROOT / rel_path
        if p.exists():
            found.append(rel_path)
        else:
            missing.append(rel_path)
    status = "pass" if not missing else "fail"
    return {
        "name": "bridge_example_data",
        "status": status,
        "files_found": len(found),
        "files_missing": missing,
    }


def run_pre_release_gate() -> dict[str, Any]:
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_pre_release_gate.py"), "--out", "/dev/null"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    status = "pass" if result.returncode == 0 else "fail"
    stderr_tail = "\n".join(result.stderr.strip().splitlines()[-5:]) if result.stderr.strip() else None
    return {
        "name": "pre_release_gate",
        "status": status,
        "duration_ms": duration_ms,
        "exit_code": result.returncode,
        "stderr_tail": stderr_tail,
    }


def catalog_env_vars() -> list[dict[str, Any]]:
    result = []
    for entry in ENV_VAR_CATALOG:
        is_set = entry["name"] in os.environ and bool(os.environ[entry["name"]])
        result.append({
            "name": entry["name"],
            "role": entry["role"],
            "description": entry["description"],
            "required_for": entry["required_for"],
            "set": is_set,
        })
    return result


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Operator readiness check.")
    ap.add_argument("--out", default="", help="Path to write operator_readiness/v1 JSON report (default: stdout)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    generated_at = utc_now_iso()

    checks: list[dict[str, Any]] = []

    c = validate_config_examples()
    checks.append(c)
    if args.verbose or c["status"] == "fail":
        icon = "[ok]" if c["status"] == "pass" else "[FAIL]"
        print(f"{icon} config_example_files: checked={c['files_checked']} failed={len(c['files_failed'])}")

    c = check_bridge_examples()
    checks.append(c)
    if args.verbose or c["status"] == "fail":
        icon = "[ok]" if c["status"] == "pass" else "[FAIL]"
        print(f"{icon} bridge_example_data: found={c['files_found']} missing={len(c['files_missing'])}")

    c = run_pre_release_gate()
    checks.append(c)
    if args.verbose or c["status"] == "fail":
        icon = "[ok]" if c["status"] == "pass" else "[FAIL]"
        print(f"{icon} pre_release_gate: exit={c['exit_code']} duration={c['duration_ms']}ms")

    env_catalog = catalog_env_vars()
    env_set = sum(1 for e in env_catalog if e["set"])
    if args.verbose:
        print(f"[info] env_vars: {env_set}/{len(env_catalog)} platform env vars set in current shell")

    total = len(checks)
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = total - passed
    status = "ok" if failed == 0 else "fail"

    report: dict[str, Any] = {
        "schema": "operator_readiness/v1",
        "generated_at_utc": generated_at,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "status": status,
        },
        "checks": checks,
        "env_var_catalog": env_catalog,
    }

    report_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(report_text + "\n", encoding="utf-8")
        env_note = f"({env_set}/{len(env_catalog)} platform env vars set)"
        print(
            f"[ok] operator_readiness: {total} checks, {passed} passed, {failed} failed → {status} {env_note}"
        )
    else:
        print(report_text)

    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
