#!/usr/bin/env python3
import argparse
import json
import os
import socket
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SSE_DIR = REPO_ROOT / "sse"

sys.path.insert(0, str(SSE_DIR))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from external_kms_lib import check_external_kms_health, load_external_kms_config  # noqa: E402
from services.record_recovery.config import (  # noqa: E402
    load_resolved_record_recovery_service_config,
    merged_record_recovery_service_value,
)
from services.record_recovery.client import request_record_recovery_health  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def repo_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def optional_repo_path(path_value: str) -> str:
    if not path_value:
        return ""
    return str(repo_path(path_value))


def load_json_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_optional_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = load_json_file(path)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def health_result(name: str,
                  status: str,
                  *,
                  component: str,
                  details: dict[str, Any] | None = None,
                  error: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "component": component,
        "status": status,
    }
    if details:
        result["details"] = details
    if error:
        result["error"] = error
    return result


def check_record_recovery_config(
    config_path: str,
    identity_auth_env: str,
    identity_bearer_token: str,
) -> dict[str, Any]:
    display = config_path
    try:
        config = load_resolved_record_recovery_service_config(optional_repo_path(config_path))
        socket_path = merged_record_recovery_service_value("", config.get("socket_path", ""))
        endpoint_url = merged_record_recovery_service_value("", config.get("endpoint_url", ""))
        auth_env = merged_record_recovery_service_value("", config.get("auth_token_env", ""))
        if not socket_path and not endpoint_url:
            raise RuntimeError("config has neither socket_path nor endpoint_url")
        health = request_record_recovery_health(
            socket_path=Path(socket_path) if socket_path else None,
            endpoint_url=endpoint_url,
            auth_env=auth_env,
            identity_auth_env=identity_auth_env,
            identity_bearer_token=identity_bearer_token,
        )
        details = {
            "config": optional_repo_path(config_path),
            "transport": "http" if endpoint_url else "unix_socket",
            "socket_path": socket_path or None,
            "endpoint_url": endpoint_url or None,
            "health": health,
        }
        return health_result(display, "ok", component="record_recovery", details=details)
    except Exception as e:
        return health_result(display, "error", component="record_recovery", error=str(e))


def check_record_recovery_endpoint(
    socket_path: str,
    endpoint_url: str,
    auth_env: str,
    identity_auth_env: str,
    identity_bearer_token: str,
) -> dict[str, Any]:
    name = endpoint_url or socket_path
    try:
        if not socket_path and not endpoint_url:
            raise RuntimeError("socket_path or endpoint_url is required")
        health = request_record_recovery_health(
            socket_path=Path(socket_path) if socket_path else None,
            endpoint_url=endpoint_url,
            auth_env=auth_env,
            identity_auth_env=identity_auth_env,
            identity_bearer_token=identity_bearer_token,
        )
        return health_result(
            name,
            "ok",
            component="record_recovery",
            details={
                "transport": "http" if endpoint_url else "unix_socket",
                "socket_path": socket_path or None,
                "endpoint_url": endpoint_url or None,
                "health": health,
            },
        )
    except Exception as e:
        return health_result(name, "error", component="record_recovery", error=str(e))


def _read_optional_env(env_name: str) -> str:
    if not env_name:
        return ""
    value = os.environ.get(env_name, "")
    if not value:
        raise RuntimeError(f"environment variable {env_name} is not set")
    return value


def check_key_agent(
    *,
    key_agent_socket: str,
    key_agent_auth_env: str,
    key_agent_identity_token_env: str,
    key_agent_identity_bearer_token: str,
    key_name: str,
    key_purpose: str,
    caller: str,
    job_id: str,
) -> dict[str, Any]:
    name = key_agent_socket
    try:
        if not key_agent_socket:
            raise RuntimeError("--key-agent-socket is required")
        payload = {
            "caller": caller,
            "job_id": job_id,
            "key_name": key_name,
            "purpose": key_purpose,
        }
        token = _read_optional_env(key_agent_auth_env)
        if token:
            payload["auth_token"] = token
        identity_token = _read_optional_env(key_agent_identity_token_env)
        if identity_token:
            payload["identity_bearer_token"] = identity_token
        elif key_agent_identity_bearer_token:
            payload["identity_bearer_token"] = key_agent_identity_bearer_token

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.connect(key_agent_socket)
            client.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = client.recv(8192)
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            client.close()

        raw = b"".join(chunks)
        if not raw:
            raise RuntimeError("key agent returned an empty response")
        response = json.loads(raw.decode("utf-8"))
        if not isinstance(response, dict):
            raise RuntimeError("key agent returned a non-object response")
        if response.get("schema") == "key_agent_error/v1":
            raise RuntimeError(str(response.get("error", "key agent failed")))
        if response.get("schema") != "key_agent_result/v1":
            raise RuntimeError(f"unexpected key agent schema: {response.get('schema')}")
        details = {
            "socket_path": key_agent_socket,
            "caller": caller,
            "key_id": response.get("key_id"),
            "key_version": response.get("key_version"),
            "secret_present": bool(response.get("secret")),
        }
        return health_result(name, "ok", component="key_agent", details=details)
    except Exception as e:
        return health_result(name or "key_agent", "error", component="key_agent", error=str(e))


def check_external_kms(config_path: str) -> dict[str, Any]:
    try:
        config = load_external_kms_config(optional_repo_path(config_path))
        response = check_external_kms_health(config)
        details = {
            "config": optional_repo_path(config_path),
            "health": response,
        }
        return health_result(config_path, "ok", component="external_kms", details=details)
    except Exception as e:
        return health_result(config_path, "error", component="external_kms", error=str(e))


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else None,
    }


def summarize_mainline_contract_check(base: Path, chain: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    findings: list[str] = []
    embedded = chain.get("mainline_contract_check") if isinstance(chain.get("mainline_contract_check"), dict) else {}
    chain_paths = chain.get("paths") if isinstance(chain.get("paths"), dict) else {}
    artifact_path = Path(str(chain_paths.get("mainline_contract_check") or (base / "mainline_contract_check.json"))).resolve()
    sidecar = load_optional_json_object(artifact_path)
    payload = embedded or sidecar
    if not payload:
        findings.append("mainline_contract_check_missing")
        return {
            "source": None,
            "path": str(artifact_path),
            "schema": None,
            "status": None,
            "summary_error_count": None,
            "handoff_cleanup": {},
            "embedded_in_audit_chain": False,
        }, findings

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    payload_findings = payload.get("findings") if isinstance(payload.get("findings"), list) else []
    handoff_cleanup = payload.get("handoff_cleanup") if isinstance(payload.get("handoff_cleanup"), dict) else {}
    handoff_exposure_assessment = (
        payload.get("handoff_exposure_assessment")
        if isinstance(payload.get("handoff_exposure_assessment"), dict)
        else {}
    )
    handoff_mode = payload.get("handoff_mode")
    mainline_status = payload.get("status")
    sse_by_role: dict[str, dict[str, Any]] = {}
    for record in chain.get("sse_export_audit") if isinstance(chain.get("sse_export_audit"), list) else []:
        if not isinstance(record, dict):
            continue
        role = record.get("role")
        if role in {"server", "client"}:
            sse_by_role[str(role)] = record
    service_boundary_roles = {
        role_name
        for role_name in ("server", "client")
        if (sse_by_role.get(role_name) or {}).get("record_recovery_boundary") in {"service_socket", "service_http"}
    }
    service_finding_kinds = [
        str(item.get("kind", ""))
        for item in payload_findings
        if isinstance(item, dict)
    ]
    global_service_failures = {
        kind
        for kind in service_finding_kinds
        if kind in {"missing_service_audit", "service_transport_mismatch"}
    }
    if payload.get("schema") != "mainline_contract_check/v1":
        findings.append("mainline_contract_check_schema")
    if mainline_status != "ok":
        findings.append("mainline_contract_check_status")
    for role_name in ("server", "client"):
        entry = handoff_cleanup.get(role_name) if isinstance(handoff_cleanup.get(role_name), dict) else {}
        entry_status = entry.get("status")
        if entry_status not in {"cleaned", "removed"} and not (
            entry_status == "retained" and mainline_status == "ok"
        ):
            findings.append(f"{role_name}_handoff_cleanup")
    if not embedded:
        findings.append("mainline_contract_check_not_embedded")

    return {
        "source": "audit_chain" if embedded else "sidecar",
        "path": str(artifact_path),
        "schema": payload.get("schema"),
        "status": payload.get("status"),
        "summary_error_count": summary.get("error_count"),
        "handoff_mode": handoff_mode,
        "handoff_exposure_assessment": {
            "handoff_mode": handoff_exposure_assessment.get("handoff_mode"),
            "plaintext_exposure_risk": handoff_exposure_assessment.get("plaintext_exposure_risk"),
            "server_exposure_risk": (
                (handoff_exposure_assessment.get("server_exposure") or {}).get("exposure_risk")
                if isinstance(handoff_exposure_assessment.get("server_exposure"), dict)
                else None
            ),
            "client_exposure_risk": (
                (handoff_exposure_assessment.get("client_exposure") or {}).get("exposure_risk")
                if isinstance(handoff_exposure_assessment.get("client_exposure"), dict)
                else None
            ),
        },
        "retained_handoff_compatibility_mode": any(
            (
                isinstance(handoff_cleanup.get(role_name), dict)
                and handoff_cleanup.get(role_name).get("status") == "retained"
            )
            for role_name in ("server", "client")
        ) and mainline_status == "ok",
        "handoff_cleanup": {
            role_name: {
                "status": (
                    handoff_cleanup.get(role_name).get("status")
                    if isinstance(handoff_cleanup.get(role_name), dict)
                    else None
                ),
                "managed_by_out_base": (
                    handoff_cleanup.get(role_name).get("managed_by_out_base")
                    if isinstance(handoff_cleanup.get(role_name), dict)
                    else None
                ),
                "exists_after_run": (
                    handoff_cleanup.get(role_name).get("exists_after_run")
                    if isinstance(handoff_cleanup.get(role_name), dict)
                    else None
                ),
            }
            for role_name in ("server", "client")
        },
        "service_audit_consistency": {
            role_name: (
                None
                if not payload
                else "not_applicable"
                if role_name not in service_boundary_roles
                else "fail"
                if global_service_failures
                or any(
                    kind == f"missing_{role_name}_service_audit"
                    or kind.startswith(f"{role_name}_service_")
                    for kind in service_finding_kinds
                )
                else "ok"
            )
            for role_name in ("server", "client")
        } | {
            "error_count": len(
                [
                    kind
                    for kind in service_finding_kinds
                    if kind in global_service_failures
                    or any(
                        kind == f"missing_{role_name}_service_audit"
                        or kind.startswith(f"{role_name}_service_")
                        for role_name in ("server", "client")
                    )
                ]
            ),
        },
        "embedded_in_audit_chain": bool(embedded),
    }, findings


def check_pipeline_run(out_base: str) -> dict[str, Any]:
    base = repo_path(out_base)
    required = {
        "export_audit": base / "sse_exports" / "export_audit.jsonl",
        "job_meta": base / "bridge_job" / "job_meta.json",
        "bridge_audit": base / "bridge_job" / "bridge_audit.jsonl",
        "pjc_audit": base / "a_psi_run" / "pjc_audit.jsonl",
        "public_report": base / "a_psi_run" / "public_report.json",
        "audit_chain": base / "audit_chain.json",
        "audit_seal": base / "audit_chain.seal.json",
    }
    artifacts = {name: _artifact(path) for name, path in required.items()}
    missing = [name for name, artifact in artifacts.items() if not artifact["exists"]]
    details: dict[str, Any] = {
        "out_base": str(base),
        "artifacts": artifacts,
    }
    if required["public_report"].is_file():
        try:
            report = load_json_file(required["public_report"])
            if isinstance(report, dict):
                details["public_report"] = {
                    "schema": report.get("schema"),
                    "job_id": report.get("job_id"),
                    "caller": report.get("caller"),
                    "released": report.get("released"),
                    "intersection_size": report.get("intersection_size"),
                    "intersection_sum": report.get("intersection_sum"),
                    "reason_code": report.get("reason_code"),
                }
        except Exception as e:
            missing.append("public_report_parse")
            details["public_report_error"] = str(e)
    if required["audit_chain"].is_file():
        try:
            chain = load_json_file(required["audit_chain"])
            if isinstance(chain, dict):
                details["audit_chain"] = {
                    "schema": chain.get("schema"),
                    "job_id": chain.get("job_id"),
                    "correlation_id": chain.get("correlation_id"),
                    "mainline_contract_check_embedded": isinstance(chain.get("mainline_contract_check"), dict),
                }
                mainline_details, mainline_findings = summarize_mainline_contract_check(base, chain)
                details["mainline_contract_check"] = mainline_details
                missing.extend(mainline_findings)
        except Exception as e:
            missing.append("audit_chain_parse")
            details["audit_chain_error"] = str(e)
    status = "error" if missing else "ok"
    if missing:
        details["missing_or_invalid"] = missing
    return health_result(str(base), status, component="pipeline_run", details=details)


def check_metadata_db(db_path: str) -> dict[str, Any]:
    path = repo_path(db_path)
    try:
        if not path.is_file():
            raise RuntimeError(f"metadata DB does not exist: {path}")
        conn = sqlite3.connect(path)
        try:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
            required = {"jobs", "job_artifacts", "audit_events", "schema_migrations"}
            missing = sorted(required - tables)
            if missing:
                raise RuntimeError(f"metadata DB missing tables: {', '.join(missing)}")
            details = {
                "db_path": str(path),
                "jobs": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
                "audit_events": conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0],
                "job_artifacts": conn.execute("SELECT COUNT(*) FROM job_artifacts").fetchone()[0],
                "migrations": [
                    row[0]
                    for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
                ],
            }
        finally:
            conn.close()
        return health_result(str(path), "ok", component="metadata_db", details=details)
    except Exception as e:
        return health_result(str(path), "error", component="metadata_db", error=str(e))


def build_health_report(
    *,
    record_recovery_configs: list[str] | None = None,
    record_recovery_socket: str = "",
    record_recovery_endpoint_url: str = "",
    record_recovery_auth_env: str = "",
    record_recovery_identity_auth_env: str = "",
    record_recovery_identity_bearer_token: str = "",
    key_agent_socket: str = "",
    key_agent_auth_env: str = "",
    key_agent_identity_token_env: str = "",
    key_agent_identity_bearer_token: str = "",
    key_name: str = "bridge-token",
    key_purpose: str = "bridge_token",
    caller: str = "auto_demo",
    job_id: str = "platform_health_check",
    external_kms_configs: list[str] | None = None,
    out_bases: list[str] | None = None,
    metadata_dbs: list[str] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    for config_path in record_recovery_configs or []:
        checks.append(
            check_record_recovery_config(
                config_path,
                record_recovery_identity_auth_env,
                record_recovery_identity_bearer_token,
            )
        )
    if record_recovery_socket or record_recovery_endpoint_url:
        checks.append(check_record_recovery_endpoint(
            record_recovery_socket,
            record_recovery_endpoint_url,
            record_recovery_auth_env,
            record_recovery_identity_auth_env,
            record_recovery_identity_bearer_token,
        ))
    if key_agent_socket:
        checks.append(check_key_agent(
            key_agent_socket=key_agent_socket,
            key_agent_auth_env=key_agent_auth_env,
            key_agent_identity_token_env=key_agent_identity_token_env,
            key_agent_identity_bearer_token=key_agent_identity_bearer_token,
            key_name=key_name,
            key_purpose=key_purpose,
            caller=caller,
            job_id=job_id,
        ))
    for config_path in external_kms_configs or []:
        checks.append(check_external_kms(config_path))
    for out_base in out_bases or []:
        checks.append(check_pipeline_run(out_base))
    for db_path in metadata_dbs or []:
        checks.append(check_metadata_db(db_path))

    if not checks:
        checks.append(health_result(
            "no_checks_requested",
            "warn",
            component="platform_health",
            details={
                "hint": "Pass --record-recovery-config, --external-kms-config, --out-base, --metadata-db, or --key-agent-socket.",
            },
        ))

    counts = {
        "ok": sum(1 for item in checks if item.get("status") == "ok"),
        "warn": sum(1 for item in checks if item.get("status") == "warn"),
        "error": sum(1 for item in checks if item.get("status") == "error"),
    }
    return {
        "schema": "platform_health/v1",
        "generated_at_utc": utc_now(),
        "repo_root": str(REPO_ROOT),
        "summary": {
            **counts,
            "status": "error" if counts["error"] else ("warn" if counts["warn"] else "ok"),
        },
        "checks": checks,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Run sidecar health probes for platform services and pipeline artifacts.",
    )
    ap.add_argument("--record-recovery-config", action="append", default=[],
                    help="Probe a recovery service through record_recovery_service_config/v1. Repeatable.")
    ap.add_argument("--record-recovery-socket", default="")
    ap.add_argument("--record-recovery-endpoint-url", default="")
    ap.add_argument("--record-recovery-auth-env", default="")
    ap.add_argument("--record-recovery-identity-auth-env", default="")
    ap.add_argument("--record-recovery-identity-bearer-token", default="")
    ap.add_argument("--key-agent-socket", default="")
    ap.add_argument("--key-agent-auth-env", default="")
    ap.add_argument("--key-agent-identity-token-env", default="")
    ap.add_argument("--key-agent-identity-bearer-token", default="")
    ap.add_argument("--key-name", default="bridge-token")
    ap.add_argument("--key-purpose", default="bridge_token")
    ap.add_argument("--caller", default="auto_demo")
    ap.add_argument("--job-id", default="platform_health_check")
    ap.add_argument("--external-kms-config", action="append", default=[],
                    help="Probe an external KMS health endpoint. Repeatable.")
    ap.add_argument("--out-base", action="append", default=[],
                    help="Check a completed pipeline run directory. Repeatable.")
    ap.add_argument("--metadata-db", action="append", default=[],
                    help="Check an initialized metadata sidecar DB. Repeatable.")
    ap.add_argument("--output", default="", help="Optional path to write the health JSON report.")
    ap.add_argument("--allow-errors", action="store_true",
                    help="Always exit 0 after writing the report.")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    report = build_health_report(
        record_recovery_configs=args.record_recovery_config,
        record_recovery_socket=args.record_recovery_socket,
        record_recovery_endpoint_url=args.record_recovery_endpoint_url,
        record_recovery_auth_env=args.record_recovery_auth_env,
        record_recovery_identity_auth_env=args.record_recovery_identity_auth_env,
        record_recovery_identity_bearer_token=args.record_recovery_identity_bearer_token,
        key_agent_socket=args.key_agent_socket,
        key_agent_auth_env=args.key_agent_auth_env,
        key_agent_identity_token_env=args.key_agent_identity_token_env,
        key_agent_identity_bearer_token=args.key_agent_identity_bearer_token,
        key_name=args.key_name,
        key_purpose=args.key_purpose,
        caller=args.caller,
        job_id=args.job_id,
        external_kms_configs=args.external_kms_config,
        out_bases=args.out_base,
        metadata_dbs=args.metadata_db,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = repo_path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.allow_errors:
        return 0
    return 1 if (report.get("summary") or {}).get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
