#!/usr/bin/env python3
"""Repo-side smoke for identity-bound query/workflow API scope enforcement.

This isolates the direct query/workflow HTTP surface from the larger platform
API smoke so verifier-facing gates can point to a compact, purpose-built piece
of evidence for caller/dataset/recovery-service binding.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

import serve_query_workflow_api as query_api
from metadata_db import apply_migrations, connect_db
from runtime_service_helpers import available_port, wait_for_json_health


REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCHEMA = "query_workflow_identity_scope_smoke/v1"


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def build_request_payload() -> dict[str, Any]:
    suffix = uuid4().hex[:8]
    out_base = REPO_ROOT / "tmp" / f"query_scope_identity_out_{suffix}"
    return {
        "schema": "query_workflow_request/v1",
        "query_type": "cross_party_match",
        "server_source": str(REPO_ROOT / "sse" / "examples" / "bridge_server_records.jsonl"),
        "client_source": str(REPO_ROOT / "sse" / "examples" / "bridge_client_records.jsonl"),
        "server_join_key_field": "email",
        "client_join_key_field": "email",
        "client_value_field": "amount",
        "server_normalizer": "email",
        "client_normalizer": "email",
        "client_value_mode": "raw-int",
        "client_value_min": 0,
        "client_value_max": 1000000,
        "client_allowed_value_fields": ["amount"],
        "client_value_unit": "minor_currency_unit",
        "client_value_currency": "USD",
        "server_filters": ["campaign=retargeting"],
        "client_filters": ["campaign=retargeting"],
        "token_scope": "query-scope-smoke",
        "token_secret": "query-scope-secret",
        "job_id": f"query-scope-identity-{suffix}",
        "out_base": str(out_base),
        "caller": "marketing_analyst_demo",
        "tenant_id": "commerce_tenant",
        "dataset_id": "orders_analytics",
        "k": 1,
        "n": 5,
        "sse_export_policy_config": str(REPO_ROOT / "sse" / "config" / "ecommerce_access_policy.example.json"),
        "deny_duplicate_query": True,
        "sse_export_handoff_mode": "fifo",
        "cleanup_sse_export_handoff_files_after_bridge": True,
    }


def json_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    payload: dict[str, Any],
    *,
    token: str,
    request_base_dir: str,
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Request-Base-Dir": request_base_dir,
        },
        method="POST",
    )
    try:
        with opener.open(request, timeout=5) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8"))


def get_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    token: str,
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with opener.open(request, timeout=5) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode("utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def seed_identity_registry(db_path: Path, *, token_config_path: Path) -> None:
    now = "2026-06-03T00:00:00Z"
    marketing_env = "SECCOMP_QUERY_SCOPE_MARKETING_TOKEN"
    commerce_env = "SECCOMP_QUERY_SCOPE_COMMERCE_TOKEN"
    os.environ[marketing_env] = "query-scope-marketing-token"
    os.environ[commerce_env] = "query-scope-commerce-token"
    token_config = {
        "schema": "api_identity_token_map/v1",
        "tokens": [
            {
                "token_env": marketing_env,
                "issuer": "keycloak:commerce",
                "subject": "user:marketing_analyst",
            },
            {
                "token_env": commerce_env,
                "issuer": "keycloak:commerce",
                "subject": "user:commerce_ops_owner",
            },
        ],
    }
    token_config_path.write_text(json.dumps(token_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with connect_db(str(db_path)) as conn:
        apply_migrations(conn)
        conn.execute(
            "INSERT OR IGNORE INTO tenants(tenant_id, created_at_utc, source) VALUES(?, ?, ?)",
            ("commerce_tenant", now, "query_scope_smoke"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO datasets(dataset_id, tenant_id, created_at_utc, source) VALUES(?, ?, ?, ?)",
            ("orders_analytics", "commerce_tenant", now, "query_scope_smoke"),
        )
        for caller in ("marketing_analyst_demo", "commerce_ops_demo"):
            conn.execute(
                "INSERT OR IGNORE INTO callers(caller, tenant_id, created_at_utc, source) VALUES(?, ?, ?, ?)",
                (caller, "commerce_tenant", now, "query_scope_smoke"),
            )
        for row in (
            (
                "marketing_analyst_demo",
                "keycloak:commerce",
                "user:marketing_analyst",
                "Marketing Analyst",
                ["query_submitter"],
                '{"entity_type":"human_user"}',
            ),
            (
                "commerce_ops_demo",
                "keycloak:commerce",
                "user:commerce_ops_owner",
                "Commerce Ops Owner",
                ["query_submitter", "privacy_operator"],
                '{"entity_type":"human_user"}',
            ),
        ):
            conn.execute(
                """
                INSERT OR REPLACE INTO caller_identities(
                  caller, issuer, subject, subject_type, display_name, platform_roles_json,
                  enabled, metadata_json, source, created_at_utc
                ) VALUES(?, ?, ?, 'user', ?, ?, 1, ?, 'query_scope_smoke', ?)
                """,
                (row[0], row[1], row[2], row[3], json.dumps(row[4]), row[5], now),
            )
        conn.execute(
            """
            INSERT OR IGNORE INTO policies(policy_id, policy_kind, path, sha256, schema_name, imported_at_utc, payload_json)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "query_scope_smoke_policy",
                "sse_export_policy",
                "query_scope_smoke",
                "",
                "sse_export_policy/v1",
                now,
                "{}",
            ),
        )
        permission_sets = {
            "marketing_analyst_demo": {
                "enabled": True,
                "tenant_id": "commerce_tenant",
                "allowed_dataset_ids": ["orders_analytics"],
                "allowed_service_ids": ["orders-recovery"],
                "platform_roles": ["query_submitter"],
                "can_run_bridge": True,
                "can_run_pjc": True,
                "can_release": False,
                "can_use_record_recovery_service": True,
            },
            "commerce_ops_demo": {
                "enabled": True,
                "tenant_id": "commerce_tenant",
                "allowed_dataset_ids": ["orders_analytics"],
                "allowed_service_ids": ["orders-recovery"],
                "platform_roles": ["query_submitter", "privacy_operator"],
                "can_run_bridge": True,
                "can_run_pjc": True,
                "can_release": True,
                "can_use_record_recovery_service": True,
            },
        }
        for caller, values in permission_sets.items():
            for key, value in values.items():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO caller_permissions(
                      policy_id, caller, permission_key, permission_value, source_file, imported_at_utc
                    ) VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "query_scope_smoke_policy",
                        caller,
                        key,
                        json.dumps(value),
                        "query_scope_smoke",
                        now,
                    ),
                )
        conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-test identity-bound query/workflow API scope enforcement.")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="query_scope_smoke.") as tmp_dir_raw:
        tmp_dir = Path(tmp_dir_raw)
        db_path = tmp_dir / "identity_registry.db"
        token_config_path = tmp_dir / "identity_tokens.json"
        seed_identity_registry(db_path, token_config_path=token_config_path)

        port = available_port()
        server = query_api.QueryWorkflowApiServer(
            ("127.0.0.1", port),
            query_api.QueryWorkflowApiHandler,
            auth_token="",
            metadata_db_path=str(db_path),
            metadata_db_dsn="",
            metadata_db_read_dsn="",
            identity_token_config=str(token_config_path),
            allow_execute=True,
            workflow_execution_db_path="",
            workflow_execution_db_dsn="",
            workflow_lease_seconds=300,
            workflow_steal_expired=False,
            pid_file="",
            ready_file="",
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            wait_for_json_health(url=f"http://127.0.0.1:{port}/healthz", timeout_sec=8.0)
            opener = json_opener()
            request_payload = build_request_payload()
            request_base_dir = str(REPO_ROOT)

            marketing_token = os.environ["SECCOMP_QUERY_SCOPE_MARKETING_TOKEN"]
            commerce_token = os.environ["SECCOMP_QUERY_SCOPE_COMMERCE_TOKEN"]

            base_payload = dict(request_payload)
            status_code, dry_run = post_json(
                opener,
                f"http://127.0.0.1:{port}/v1/query-workflows/dry-run",
                base_payload,
                token=marketing_token,
                request_base_dir=request_base_dir,
            )
            if status_code != 200:
                raise AssertionError(f"identity dry-run failed: {status_code} {dry_run}")
            write_json(out_dir / "query_workflow_identity_scope_dry_run.json", dry_run)

            caller_spoof_payload = dict(base_payload)
            caller_spoof_payload["caller"] = "commerce_ops_demo"
            status_code, caller_spoof = post_json(
                opener,
                f"http://127.0.0.1:{port}/v1/query-workflows/dry-run",
                caller_spoof_payload,
                token=marketing_token,
                request_base_dir=request_base_dir,
            )
            if status_code != 403:
                raise AssertionError(f"caller spoof unexpectedly allowed: {status_code} {caller_spoof}")
            write_json(out_dir / "query_workflow_identity_scope_caller_spoof_forbidden.json", caller_spoof)

            dataset_spoof_payload = dict(base_payload)
            dataset_spoof_payload["dataset_id"] = "forbidden-dataset"
            status_code, dataset_spoof = post_json(
                opener,
                f"http://127.0.0.1:{port}/v1/query-workflows/dry-run",
                dataset_spoof_payload,
                token=marketing_token,
                request_base_dir=request_base_dir,
            )
            if status_code != 403:
                raise AssertionError(f"dataset spoof unexpectedly allowed: {status_code} {dataset_spoof}")
            write_json(out_dir / "query_workflow_identity_scope_dataset_spoof_forbidden.json", dataset_spoof)

            tenant_spoof_payload = dict(base_payload)
            tenant_spoof_payload["tenant_id"] = "other-tenant"
            status_code, tenant_spoof = post_json(
                opener,
                f"http://127.0.0.1:{port}/v1/query-workflows/dry-run",
                tenant_spoof_payload,
                token=marketing_token,
                request_base_dir=request_base_dir,
            )
            if status_code != 403:
                raise AssertionError(f"tenant spoof unexpectedly allowed: {status_code} {tenant_spoof}")
            write_json(out_dir / "query_workflow_identity_scope_tenant_spoof_forbidden.json", tenant_spoof)

            recovery_payload = dict(base_payload)
            recovery_payload["job_id"] = f"{base_payload['job_id']}-recovery"
            recovery_payload["out_base"] = f"{base_payload['out_base']}_recovery"
            recovery_payload["record_recovery_service_mode"] = "manual"
            recovery_payload["record_recovery_service_id"] = "orders-recovery"
            recovery_payload["record_recovery_endpoint_url"] = "http://127.0.0.1:9999"
            status_code, recovery_allowed = post_json(
                opener,
                f"http://127.0.0.1:{port}/v1/query-workflows/dry-run",
                recovery_payload,
                token=marketing_token,
                request_base_dir=request_base_dir,
            )
            if status_code != 200:
                raise AssertionError(f"recovery dry-run failed: {status_code} {recovery_allowed}")
            write_json(out_dir / "query_workflow_identity_scope_recovery_allowed.json", recovery_allowed)

            recovery_spoof_payload = dict(recovery_payload)
            recovery_spoof_payload["record_recovery_service_id"] = "forbidden-recovery-service"
            status_code, recovery_spoof = post_json(
                opener,
                f"http://127.0.0.1:{port}/v1/query-workflows/dry-run",
                recovery_spoof_payload,
                token=marketing_token,
                request_base_dir=request_base_dir,
            )
            if status_code != 403:
                raise AssertionError(f"recovery service spoof unexpectedly allowed: {status_code} {recovery_spoof}")
            write_json(out_dir / "query_workflow_identity_scope_recovery_spoof_forbidden.json", recovery_spoof)

            execute_payload = dict(base_payload)
            execute_payload["job_id"] = f"{base_payload['job_id']}-execute-forbidden"
            execute_payload["out_base"] = f"{base_payload['out_base']}_execute_forbidden"
            status_code, execute_forbidden = post_json(
                opener,
                f"http://127.0.0.1:{port}/v1/query-workflows/execute",
                execute_payload,
                token=marketing_token,
                request_base_dir=request_base_dir,
            )
            if status_code != 403:
                raise AssertionError(f"execute unexpectedly allowed: {status_code} {execute_forbidden}")
            write_json(out_dir / "query_workflow_identity_scope_execute_forbidden.json", execute_forbidden)

            execute_allowed_payload = dict(base_payload)
            execute_allowed_payload["job_id"] = f"{base_payload['job_id']}-execute-allowed"
            execute_allowed_payload["out_base"] = f"{base_payload['out_base']}_execute_allowed"
            execute_allowed_payload["caller"] = "commerce_ops_demo"
            execute_allowed_payload["server_source"] = str(REPO_ROOT / "missing_execute_server_records.jsonl")
            execute_allowed_status, execute_allowed = post_json(
                opener,
                f"http://127.0.0.1:{port}/v1/query-workflows/execute",
                execute_allowed_payload,
                token=commerce_token,
                request_base_dir=request_base_dir,
            )
            if execute_allowed_status != 502:
                raise AssertionError(
                    f"execute allowed path did not reach backend execution path: "
                    f"{execute_allowed_status} {execute_allowed}"
                )
            write_json(out_dir / "query_workflow_identity_scope_execute_allowed_run_failed.json", execute_allowed)

            status_out_base = ((dry_run.get("result") or {}).get("manifest") or {}).get("request_summary", {}).get("out_base")
            status_job_id = ((dry_run.get("result") or {}).get("manifest") or {}).get("request_summary", {}).get("job_id")
            query = urllib.parse.urlencode([("out_base", str(status_out_base)), ("job_id", str(status_job_id))])
            status_code, status_payload = get_json(
                opener,
                f"http://127.0.0.1:{port}/v1/query-workflows/status?{query}",
                token=marketing_token,
            )
            if status_code != 200:
                raise AssertionError(f"status lookup failed: {status_code} {status_payload}")
            write_json(out_dir / "query_workflow_identity_scope_status.json", status_payload)
            status_code, cross_caller_status_forbidden = get_json(
                opener,
                f"http://127.0.0.1:{port}/v1/query-workflows/status?{query}",
                token=commerce_token,
            )
            if status_code != 403:
                raise AssertionError(
                    f"cross-caller status lookup unexpectedly allowed: "
                    f"{status_code} {cross_caller_status_forbidden}"
                )
            write_json(
                out_dir / "query_workflow_identity_scope_status_cross_caller_forbidden.json",
                cross_caller_status_forbidden,
            )

            report = {
                "schema": SMOKE_SCHEMA,
                "status": "ok",
                "dry_run_identity_caller": (((dry_run.get("result") or {}).get("authenticated_identity") or {}).get("caller")),
                "caller_spoof_status": caller_spoof.get("error") and 403 or None,
                "dataset_spoof_status": dataset_spoof.get("error") and 403 or None,
                "tenant_spoof_status": tenant_spoof.get("error") and 403 or None,
                "recovery_allowed_service_id": ((((recovery_allowed.get("result") or {}).get("manifest") or {}).get("request_summary") or {}).get("record_recovery_service_id")),
                "recovery_spoof_status": 403,
                "execute_forbidden_status": 403,
                "execute_allowed_http_status": execute_allowed_status,
                "execute_allowed_identity_caller": (((execute_allowed.get("result") or {}).get("authenticated_identity") or {}).get("caller")),
                "status_caller": ((((status_payload.get("result") or {}).get("status") or {}).get("caller"))),
                "status_cross_caller_forbidden_status": 403,
            }
            write_json(out_dir / "query_workflow_identity_scope_smoke.json", report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
