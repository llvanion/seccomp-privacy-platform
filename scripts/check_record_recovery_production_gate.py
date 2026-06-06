#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "record_recovery_production_gate_check/v1"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from services.record_recovery.production import record_recovery_production_findings  # noqa: E402
from validate_json_contract import load_json as load_schema_json, validate_value  # noqa: E402


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_case(
    name: str,
    command: list[str],
    *,
    expect_success: bool,
    expected_text: str = "",
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    result = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        env=full_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    matched_text = not expected_text or expected_text in combined
    passed = (result.returncode == 0 if expect_success else result.returncode != 0) and matched_text
    return {
        "name": name,
        "command": command,
        "expect_success": expect_success,
        "exit_code": result.returncode,
        "passed": passed,
        "expected_text": expected_text or None,
        "stderr_tail": "\n".join(result.stderr.strip().splitlines()[-5:]) if result.stderr.strip() else None,
    }


def config_payload(
    *,
    tmp: Path,
    name: str,
    bind_host: str,
    auth_token_env: str = "",
    authz_config: str = "",
    metadata_db_path: str = "",
    identity_token_config: str = "",
    tls: dict[str, Any] | None = None,
    production_mode: bool = True,
    allowed_output_roots: list[str] | None = None,
    allowed_record_store_roots: list[str] | None = None,
    max_rows_per_request: int = 256,
) -> dict[str, Any]:
    return {
        "schema": "record_recovery_service_config/v1",
        "transport": "http",
        "production_mode": production_mode,
        "service_id": f"prod-gate-{name}",
        "tenant_id": "prod-gate-tenant",
        "dataset_id": "prod-gate-dataset",
        "endpoint_url": f"{'https' if tls and tls.get('enabled') else 'http'}://{bind_host}:18081",
        "http_listener": {
            "bind_host": bind_host,
            "port": 18081,
        },
        "auth_token_env": auth_token_env,
        "metadata_db_path": metadata_db_path,
        "identity_token_config": identity_token_config,
        "authz_config": authz_config,
        "allowed_callers": ["auto_demo"],
        "allowed_output_roots": [str(tmp)] if allowed_output_roots is None else allowed_output_roots,
        "allowed_record_store_roots": [str(tmp)] if allowed_record_store_roots is None else allowed_record_store_roots,
        "max_rows_per_request": max_rows_per_request,
        "audit_log": str(tmp / f"{name}_audit.jsonl"),
        "tls": tls or {},
        "lifecycle": {
            "pid_file": str(tmp / f"{name}.pid"),
            "ready_file": str(tmp / f"{name}.ready"),
            "log_file": str(tmp / f"{name}.log"),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify record-recovery HTTP production-mode startup gates.")
    ap.add_argument("--out", default="", help="Write record_recovery_production_gate_check/v1 JSON")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="record_recovery_production_gate_") as tmpdir:
        tmp = Path(tmpdir)
        authz = REPO_ROOT / "sse" / "config" / "export_policy.example.json"
        dummy_identity = tmp / "identity_tokens.json"
        dummy_identity.write_text(
            json.dumps({"schema": "api_identity_tokens/v1", "tokens": []}, indent=2) + "\n",
            encoding="utf-8",
        )
        dummy_metadata = tmp / "metadata.db"
        dummy_metadata.write_text("", encoding="utf-8")

        configs = {
            "loopback_authz_signed": config_payload(
                tmp=tmp,
                name="loopback_authz_signed",
                bind_host="127.0.0.1",
                auth_token_env="SSE_RECORD_RECOVERY_TOKEN",
                authz_config=str(authz),
            ),
            "loopback_no_auth": config_payload(
                tmp=tmp,
                name="loopback_no_auth",
                bind_host="127.0.0.1",
                authz_config=str(authz),
            ),
            "loopback_no_authz": config_payload(
                tmp=tmp,
                name="loopback_no_authz",
                bind_host="127.0.0.1",
                auth_token_env="SSE_RECORD_RECOVERY_TOKEN",
            ),
            "loopback_missing_roots": config_payload(
                tmp=tmp,
                name="loopback_missing_roots",
                bind_host="127.0.0.1",
                auth_token_env="SSE_RECORD_RECOVERY_TOKEN",
                authz_config=str(authz),
                allowed_output_roots=[],
                allowed_record_store_roots=[],
            ),
            "loopback_missing_row_cap": config_payload(
                tmp=tmp,
                name="loopback_missing_row_cap",
                bind_host="127.0.0.1",
                auth_token_env="SSE_RECORD_RECOVERY_TOKEN",
                authz_config=str(authz),
                max_rows_per_request=0,
            ),
            "loopback_identity_no_metadata": config_payload(
                tmp=tmp,
                name="loopback_identity_no_metadata",
                bind_host="127.0.0.1",
                identity_token_config=str(dummy_identity),
                authz_config=str(authz),
            ),
            "loopback_identity_no_mtls": config_payload(
                tmp=tmp,
                name="loopback_identity_no_mtls",
                bind_host="127.0.0.1",
                identity_token_config=str(dummy_identity),
                metadata_db_path=str(dummy_metadata),
                authz_config=str(authz),
            ),
            "public_no_mtls": config_payload(
                tmp=tmp,
                name="public_no_mtls",
                bind_host="0.0.0.0",
                auth_token_env="SSE_RECORD_RECOVERY_TOKEN",
                authz_config=str(authz),
            ),
            "public_mtls": config_payload(
                tmp=tmp,
                name="public_mtls",
                bind_host="0.0.0.0",
                auth_token_env="SSE_RECORD_RECOVERY_TOKEN",
                authz_config=str(authz),
                tls={
                    "enabled": True,
                    "server_cert": str(tmp / "server.crt"),
                    "server_key": str(tmp / "server.key"),
                    "ca_cert": str(tmp / "ca.crt"),
                    "require_client_cert": True,
                },
            ),
            "loopback_env_no_authz": config_payload(
                tmp=tmp,
                name="loopback_env_no_authz",
                bind_host="127.0.0.1",
                auth_token_env="SSE_RECORD_RECOVERY_TOKEN",
                production_mode=False,
            ),
        }

        expected_static = {
            "loopback_authz_signed": [],
            "loopback_no_auth": ["missing_request_auth", "missing_signed_request_or_mtls"],
            "loopback_no_authz": ["missing_authz_policy"],
            "loopback_missing_roots": ["missing_output_root_restrictions", "missing_record_store_root_restrictions"],
            "loopback_missing_row_cap": ["missing_max_rows_per_request"],
            "loopback_identity_no_metadata": [
                "missing_identity_metadata_db",
                "missing_signed_request_or_mtls",
            ],
            "loopback_identity_no_mtls": ["missing_signed_request_or_mtls"],
            "public_no_mtls": ["public_http_requires_mtls"],
            "public_mtls": [],
            "loopback_env_no_authz": ["missing_authz_policy"],
        }

        config_paths: dict[str, Path] = {}
        for name, payload in configs.items():
            path = tmp / f"{name}.json"
            write_json(path, payload)
            config_paths[name] = path

        static_cases = []
        for name, payload in configs.items():
            findings = record_recovery_production_findings(payload)
            finding_kinds = [item["kind"] for item in findings]
            expected_finding_kinds = expected_static[name]
            static_cases.append({
                "name": name,
                "expected_finding_kinds": expected_finding_kinds,
                "finding_kinds": finding_kinds,
                "finding_count": len(findings),
                "passed": finding_kinds == expected_finding_kinds,
            })

        cases = [
            run_case(
                "direct_http_service_rejects_missing_auth",
                [
                    sys.executable,
                    "-m",
                    "services.record_recovery.http_service",
                    "--bind-host",
                    "127.0.0.1",
                    "--port",
                    "18081",
                    "--production-mode",
                ],
                expect_success=False,
                expected_text="missing_request_auth",
            ),
            run_case(
                "launcher_rejects_missing_authz",
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "run_record_recovery_service.py"),
                    "serve",
                    "--config",
                    str(config_paths["loopback_no_authz"]),
                ],
                expect_success=False,
                expected_text="missing_authz_policy",
            ),
            run_case(
                "launcher_rejects_missing_root_restrictions",
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "run_record_recovery_service.py"),
                    "serve",
                    "--config",
                    str(config_paths["loopback_missing_roots"]),
                ],
                expect_success=False,
                expected_text="missing_output_root_restrictions",
            ),
            run_case(
                "launcher_rejects_missing_row_cap",
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "run_record_recovery_service.py"),
                    "serve",
                    "--config",
                    str(config_paths["loopback_missing_row_cap"]),
                ],
                expect_success=False,
                expected_text="missing_max_rows_per_request",
            ),
            run_case(
                "env_production_mode_rejects_missing_authz",
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "manage_record_recovery_service.py"),
                    "render-systemd",
                    "--config",
                    str(config_paths["loopback_env_no_authz"]),
                    "--output",
                    str(tmp / "env_no_authz.service"),
                ],
                expect_success=False,
                expected_text="missing_authz_policy",
                env={"RECORD_RECOVERY_PRODUCTION_MODE": "1"},
            ),
            run_case(
                "manager_start_rejects_public_without_mtls",
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "manage_record_recovery_service.py"),
                    "start",
                    "--config",
                    str(config_paths["public_no_mtls"]),
                ],
                expect_success=False,
                expected_text="public_http_requires_mtls",
            ),
            run_case(
                "manager_render_rejects_identity_without_metadata",
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "manage_record_recovery_service.py"),
                    "render-systemd",
                    "--config",
                    str(config_paths["loopback_identity_no_metadata"]),
                    "--output",
                    str(tmp / "bad_identity.service"),
                ],
                expect_success=False,
                expected_text="missing_identity_metadata_db",
            ),
            run_case(
                "manager_render_rejects_identity_without_signed_or_mtls",
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "manage_record_recovery_service.py"),
                    "render-systemd",
                    "--config",
                    str(config_paths["loopback_identity_no_mtls"]),
                    "--output",
                    str(tmp / "bad_identity_no_mtls.service"),
                ],
                expect_success=False,
                expected_text="missing_signed_request_or_mtls",
            ),
            run_case(
                "manager_render_accepts_loopback_signed_authz",
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "manage_record_recovery_service.py"),
                    "render-systemd",
                    "--config",
                    str(config_paths["loopback_authz_signed"]),
                    "--output",
                    str(tmp / "loopback_authz_signed.service"),
                ],
                expect_success=True,
                expected_text="--production-mode",
            ),
            run_case(
                "manager_render_accepts_public_mtls_signed_authz",
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "manage_record_recovery_service.py"),
                    "render-systemd",
                    "--config",
                    str(config_paths["public_mtls"]),
                    "--output",
                    str(tmp / "public_mtls.service"),
                ],
                expect_success=True,
                expected_text="--production-mode",
            ),
        ]

        summary = {
            "status": "ok" if all(case["passed"] for case in cases) and all(case["passed"] for case in static_cases) else "fail",
            "checked_count": len(cases) + len(static_cases),
            "passed_count": sum(1 for case in cases if case["passed"]) + sum(1 for case in static_cases if case["passed"]),
            "failed_count": sum(1 for case in cases if not case["passed"]) + sum(1 for case in static_cases if not case["passed"]),
            "static_case_count": len(static_cases),
        }
        payload = {
            "schema": SCHEMA_ID,
            "generated_at_utc": utc_now_iso(),
            "summary": summary,
            "static_cases": static_cases,
            "cases": cases,
            "claim_boundary": {
                "repo_side_evidence": "production-mode HTTP recovery startup and render gates reject unsafe configs before service launch",
                "production_remaining": "live service-user sandbox evidence, host firewall or Kubernetes NetworkPolicy, and deployed mTLS traffic evidence remain operator-side",
            },
        }

    if args.out:
        out = Path(args.out)
        write_json(out, payload)
        schema = load_schema_json(REPO_ROOT / "schemas" / "record_recovery_production_gate_check.schema.json")
        validate_value(schema, payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["summary"]["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
