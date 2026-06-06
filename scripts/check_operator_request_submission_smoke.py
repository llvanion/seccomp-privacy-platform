#!/usr/bin/env python3
"""Smoke-test operator request submission and approval workflow endpoints."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import time
import urllib.request
from urllib.error import HTTPError
from pathlib import Path
from typing import Any

import serve_operator_dashboard as dashboard
from metadata_db import apply_migrations, connect_db
from runtime_service_helpers import available_port


REPO_ROOT = Path(__file__).resolve().parents[1]


def build_request(
    *,
    out_base: Path,
    job_id: str = "operator-request-submission-smoke",
    caller: str = "auto_demo",
) -> dict[str, Any]:
    return {
        "schema": "query_workflow_request/v1",
        "query_type": "cross_party_match",
        "server_source": str(REPO_ROOT / "sse/examples/bridge_server_records.jsonl"),
        "client_source": str(REPO_ROOT / "sse/examples/bridge_client_records.jsonl"),
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
        "server_filters": ["campaign=demo"],
        "client_filters": ["campaign=demo"],
        "token_scope": "operator-request-submission-smoke",
        "token_secret": "operator-request-submission-secret",
        "job_id": job_id,
        "out_base": str(out_base),
        "caller": caller,
        "tenant_id": "demo_tenant",
        "dataset_id": "bridge_demo_dataset",
        "source_system": "ecommerce_fact_import",
        "source_attestation_mode": "operator",
        "source_attestation_approval_id": "approval-operator-request-submission-smoke",
        "source_attestation_operator_identity": "privacy_operator_demo",
        "source_attestation_signoff_status": "approved",
        "source_attestation_signing_key_path": str(out_base / "source_attestation_signing_key.pem"),
        "k": 1,
        "n": 5,
        "sse_export_policy_config": str(REPO_ROOT / "sse/config/export_policy.example.json"),
        "deny_duplicate_query": True,
        "sse_export_handoff_mode": "fifo",
        "cleanup_sse_export_handoff_files_after_bridge": True
    }


def request_json(url: str, *, method: str = "GET", payload: dict[str, Any] | None = None, token: str = "") -> tuple[int, dict[str, Any]]:
    raw = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=raw, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return int(resp.status), body
    except HTTPError as exc:
        raw_error = exc.read().decode("utf-8")
        body = json.loads(raw_error) if raw_error else {"error": "empty_error_response"}
        return int(exc.code), body


def post_json(url: str, payload: dict[str, Any], *, token: str = "") -> tuple[int, dict[str, Any]]:
    raw = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=raw,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return int(resp.status), body
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        body = json.loads(raw) if raw else {"error": "empty_error_response"}
        return int(exc.code), body


def seed_identity_metadata(db_path: Path, *, token_config_path: Path) -> None:
    now = dashboard._utc_now()
    submitter_env = "SECCOMP_OPERATOR_REQUEST_SUBMITTER_TOKEN"
    approver_env = "SECCOMP_OPERATOR_REQUEST_APPROVER_TOKEN"
    analyst_env = "SECCOMP_OPERATOR_REQUEST_ANALYST_TOKEN"
    auditor_env = "SECCOMP_OPERATOR_REQUEST_AUDITOR_TOKEN"
    recovery_env = "SECCOMP_OPERATOR_REQUEST_RECOVERY_TOKEN"
    os.environ[submitter_env] = "operator-request-submitter-token"
    os.environ[approver_env] = "operator-request-approver-token"
    os.environ[analyst_env] = "operator-request-analyst-token"
    os.environ[auditor_env] = "operator-request-auditor-token"
    os.environ[recovery_env] = "operator-request-recovery-token"
    token_config = {
        "schema": "api_identity_token_map/v1",
        "tokens": [
            {
                "token_env": submitter_env,
                "issuer": "smoke",
                "subject": "user:auto_demo"
            },
            {
                "token_env": approver_env,
                "issuer": "smoke",
                "subject": "user:privacy_operator"
            },
            {
                "token_env": analyst_env,
                "issuer": "smoke",
                "subject": "user:campaign_analyst"
            },
            {
                "token_env": auditor_env,
                "issuer": "smoke",
                "subject": "user:compliance_auditor"
            },
            {
                "token_env": recovery_env,
                "issuer": "smoke",
                "subject": "user:recovery_submitter"
            }
        ]
    }
    token_config_path.write_text(json.dumps(token_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with connect_db(str(db_path)) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO tenants(tenant_id, created_at_utc, source) VALUES(?, ?, ?)",
            ("demo_tenant", now, "operator_request_submission_smoke"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO datasets(dataset_id, tenant_id, created_at_utc, source) VALUES(?, ?, ?, ?)",
            ("bridge_demo_dataset", "demo_tenant", now, "operator_request_submission_smoke"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO callers(caller, tenant_id, created_at_utc, source) VALUES(?, ?, ?, ?)",
            ("auto_demo", "demo_tenant", now, "operator_request_submission_smoke"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO callers(caller, tenant_id, created_at_utc, source) VALUES(?, ?, ?, ?)",
            ("privacy_operator_demo", "demo_tenant", now, "operator_request_submission_smoke"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO callers(caller, tenant_id, created_at_utc, source) VALUES(?, ?, ?, ?)",
            ("campaign_analyst_demo", "demo_tenant", now, "operator_request_submission_smoke"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO callers(caller, tenant_id, created_at_utc, source) VALUES(?, ?, ?, ?)",
            ("compliance_auditor_demo", "demo_tenant", now, "operator_request_submission_smoke"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO callers(caller, tenant_id, created_at_utc, source) VALUES(?, ?, ?, ?)",
            ("recovery_submitter_demo", "demo_tenant", now, "operator_request_submission_smoke"),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO policies(policy_id, policy_kind, path, sha256, schema_name, imported_at_utc, payload_json)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "operator_request_submission_policy",
                "sse_export_policy",
                "smoke://operator-request-submission",
                "",
                "sse_export_policy/v1",
                now,
                "{}",
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO caller_identities(
              caller, issuer, subject, subject_type, display_name,
              platform_roles_json, enabled, source, created_at_utc
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "auto_demo",
                "smoke",
                "user:auto_demo",
                "user",
                "Auto Demo",
                json.dumps(["query_submitter"]),
                1,
                "operator_request_submission_smoke",
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO caller_identities(
              caller, issuer, subject, subject_type, display_name,
              platform_roles_json, enabled, source, created_at_utc
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "recovery_submitter_demo",
                "smoke",
                "user:recovery_submitter",
                "user",
                "Recovery Submitter",
                json.dumps(["query_submitter"]),
                1,
                "operator_request_submission_smoke",
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO caller_identities(
              caller, issuer, subject, subject_type, display_name,
              platform_roles_json, enabled, source, created_at_utc
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "privacy_operator_demo",
                "smoke",
                "user:privacy_operator",
                "user",
                "Privacy Operator",
                json.dumps(["privacy_operator"]),
                1,
                "operator_request_submission_smoke",
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO caller_identities(
              caller, issuer, subject, subject_type, display_name,
              platform_roles_json, enabled, source, created_at_utc
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "campaign_analyst_demo",
                "smoke",
                "user:campaign_analyst",
                "user",
                "Campaign Analyst",
                json.dumps(["query_submitter", "campaign_analyst"]),
                1,
                "operator_request_submission_smoke",
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO caller_identities(
              caller, issuer, subject, subject_type, display_name,
              platform_roles_json, enabled, source, created_at_utc
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "compliance_auditor_demo",
                "smoke",
                "user:compliance_auditor",
                "user",
                "Compliance Auditor",
                json.dumps(["compliance_auditor"]),
                1,
                "operator_request_submission_smoke",
                now,
            ),
        )
        permissions = {
            "enabled": True,
            "tenant_id": "demo_tenant",
            "platform_roles": ["query_submitter"],
            "allowed_dataset_ids": ["bridge_demo_dataset"],
            "allowed_service_ids": [],
            "can_run_bridge": True,
            "can_run_pjc": True,
            "can_release": False,
            "can_use_record_recovery_service": False,
        }
        for key, value in permissions.items():
            conn.execute(
                """
                INSERT OR REPLACE INTO caller_permissions(
                  policy_id, caller, permission_key, permission_value, source_file, imported_at_utc
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    "operator_request_submission_policy",
                    "auto_demo",
                    key,
                    json.dumps(value),
                    "operator_request_submission_smoke",
                    now,
                ),
            )
        analyst_permissions = {
            "enabled": True,
            "tenant_id": "demo_tenant",
            "platform_roles": ["query_submitter", "campaign_analyst"],
            "allowed_dataset_ids": ["bridge_demo_dataset"],
            "allowed_service_ids": [],
            "can_run_bridge": True,
            "can_run_pjc": True,
            "can_release": False,
            "can_use_record_recovery_service": False,
        }
        for key, value in analyst_permissions.items():
            conn.execute(
                """
                INSERT OR REPLACE INTO caller_permissions(
                  policy_id, caller, permission_key, permission_value, source_file, imported_at_utc
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    "operator_request_submission_policy",
                    "campaign_analyst_demo",
                    key,
                    json.dumps(value),
                    "operator_request_submission_smoke",
                    now,
                ),
            )
        operator_permissions = {
            "enabled": True,
            "tenant_id": "demo_tenant",
            "platform_roles": ["privacy_operator"],
            "allowed_dataset_ids": ["bridge_demo_dataset"],
            "allowed_service_ids": [],
            "can_run_bridge": True,
            "can_run_pjc": True,
            "can_release": True,
            "can_use_record_recovery_service": False,
        }
        for key, value in operator_permissions.items():
            conn.execute(
                """
                INSERT OR REPLACE INTO caller_permissions(
                  policy_id, caller, permission_key, permission_value, source_file, imported_at_utc
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    "operator_request_submission_policy",
                    "privacy_operator_demo",
                    key,
                    json.dumps(value),
                    "operator_request_submission_smoke",
                    now,
                ),
            )
        auditor_permissions = {
            "enabled": True,
            "tenant_id": "demo_tenant",
            "platform_roles": ["compliance_auditor"],
            "allowed_dataset_ids": ["bridge_demo_dataset"],
            "allowed_service_ids": [],
            "can_run_bridge": False,
            "can_run_pjc": False,
            "can_release": False,
            "can_use_record_recovery_service": False,
        }
        for key, value in auditor_permissions.items():
            conn.execute(
                """
                INSERT OR REPLACE INTO caller_permissions(
                  policy_id, caller, permission_key, permission_value, source_file, imported_at_utc
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    "operator_request_submission_policy",
                    "compliance_auditor_demo",
                    key,
                    json.dumps(value),
                    "operator_request_submission_smoke",
                    now,
                ),
            )
        recovery_permissions = {
            "enabled": True,
            "tenant_id": "demo_tenant",
            "platform_roles": ["query_submitter"],
            "allowed_dataset_ids": ["bridge_demo_dataset"],
            "allowed_service_ids": ["bridge-demo-recovery"],
            "can_run_bridge": True,
            "can_run_pjc": True,
            "can_release": False,
            "can_use_record_recovery_service": True,
        }
        for key, value in recovery_permissions.items():
            conn.execute(
                """
                INSERT OR REPLACE INTO caller_permissions(
                  policy_id, caller, permission_key, permission_value, source_file, imported_at_utc
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    "operator_request_submission_policy",
                    "recovery_submitter_demo",
                    key,
                    json.dumps(value),
                    "operator_request_submission_smoke",
                    now,
                ),
            )
        conn.commit()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Smoke-test operator dashboard request submission and approval endpoints.")
    ap.add_argument("--output", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    with tempfile.TemporaryDirectory(prefix="seccomp_operator_request.") as tmp_dir_raw:
        tmp_dir = Path(tmp_dir_raw)
        out_base = tmp_dir / "run"
        out_base.mkdir(parents=True)
        db_path = tmp_dir / "metadata.db"
        with connect_db(str(db_path)) as conn:
            apply_migrations(conn)
        token_config_path = tmp_dir / "identity_tokens.json"
        seed_identity_metadata(db_path, token_config_path=token_config_path)

        port = available_port()
        original_start_job = dashboard._start_job_thread

        def fake_start_job_thread(server: dashboard.DashboardServer, *, payload: dict[str, Any], request_source: str, request_dir: Path) -> None:
            normalized = dashboard.normalize_request_paths(payload, request_dir=request_dir)
            now = dashboard._utc_now()
            server.set_job({
                "job_id": normalized.get("job_id"),
                "tenant_id": dashboard._normalized_tenant_id(normalized),
                "state": "running",
                "terminal": False,
                "started_at_utc": now,
                "finished_at_utc": None,
                "last_updated_at_utc": now,
                "last_exit_code": None,
                "out_base": str(Path(str(normalized["out_base"])).resolve()),
                "request_source": request_source,
            })

        dashboard._start_job_thread = fake_start_job_thread
        server = dashboard.DashboardServer(
            ("127.0.0.1", port),
            dashboard.DashboardHandler,
            out_base=out_base,
            history_root=tmp_dir,
            history_limit=4,
            pid_file="",
            ready_file="",
            max_concurrent_jobs_per_tenant=0,
            metadata_db_path=str(db_path),
            identity_token_config=str(token_config_path),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.1)
        try:
            submitter_token = os.environ["SECCOMP_OPERATOR_REQUEST_SUBMITTER_TOKEN"]
            approver_token = os.environ["SECCOMP_OPERATOR_REQUEST_APPROVER_TOKEN"]
            analyst_token = os.environ["SECCOMP_OPERATOR_REQUEST_ANALYST_TOKEN"]
            auditor_token = os.environ["SECCOMP_OPERATOR_REQUEST_AUDITOR_TOKEN"]
            recovery_token = os.environ["SECCOMP_OPERATOR_REQUEST_RECOVERY_TOKEN"]
            status, response = post_json(
                f"http://127.0.0.1:{port}/v1/request/submit",
                build_request(out_base=out_base),
                token=submitter_token,
            )
            if status != 202:
                raise SystemExit(f"[ERROR] expected HTTP 202, got {status}: {response}")
            if response.get("schema") != "operator_request_submission/v1":
                raise SystemExit(f"[ERROR] unexpected response schema: {response}")
            request_summary = response.get("request_summary") or {}
            if request_summary.get("source_system") != "ecommerce_fact_import":
                raise SystemExit(f"[ERROR] source_system did not persist into request_summary: {response}")
            if request_summary.get("source_attestation_mode") != "operator":
                raise SystemExit(f"[ERROR] source_attestation_mode did not persist into request_summary: {response}")
            submission_id = str(response.get("submission_id") or "")
            spoof_caller_status, spoof_caller_response = post_json(
                f"http://127.0.0.1:{port}/v1/request/submit",
                build_request(
                    out_base=out_base,
                    job_id="operator-request-submission-spoof-caller",
                    caller="privacy_operator_demo",
                ),
                token=submitter_token,
            )
            if spoof_caller_status != 403 or spoof_caller_response.get("error") != "authz_rejected":
                raise SystemExit(
                    f"[ERROR] caller spoof request should be rejected, got "
                    f"{spoof_caller_status} {spoof_caller_response}"
                )
            spoof_tenant_payload = build_request(
                out_base=out_base,
                job_id="operator-request-submission-spoof-tenant",
            )
            spoof_tenant_payload["tenant_id"] = "other_tenant"
            spoof_tenant_status, spoof_tenant_response = post_json(
                f"http://127.0.0.1:{port}/v1/request/submit",
                spoof_tenant_payload,
                token=submitter_token,
            )
            if spoof_tenant_status != 403 or spoof_tenant_response.get("error") != "authz_rejected":
                raise SystemExit(
                    f"[ERROR] tenant spoof request should be rejected, got "
                    f"{spoof_tenant_status} {spoof_tenant_response}"
                )
            spoof_dataset_payload = build_request(
                out_base=out_base,
                job_id="operator-request-submission-spoof-dataset",
            )
            spoof_dataset_payload["dataset_id"] = "forbidden_dataset"
            spoof_dataset_status, spoof_dataset_response = post_json(
                f"http://127.0.0.1:{port}/v1/request/submit",
                spoof_dataset_payload,
                token=submitter_token,
            )
            if spoof_dataset_status != 403 or spoof_dataset_response.get("error") != "authz_rejected":
                raise SystemExit(
                    f"[ERROR] dataset spoof request should be rejected, got "
                    f"{spoof_dataset_status} {spoof_dataset_response}"
                )
            recovery_without_permission_payload = build_request(
                out_base=out_base,
                job_id="operator-request-submission-recovery-without-permission",
            )
            recovery_without_permission_payload["record_recovery_service_mode"] = "manual"
            recovery_without_permission_payload["record_recovery_service_id"] = "bridge-demo-recovery"
            recovery_without_permission_payload["record_recovery_endpoint_url"] = "http://127.0.0.1:9999"
            recovery_without_permission_status, recovery_without_permission_response = post_json(
                f"http://127.0.0.1:{port}/v1/request/submit",
                recovery_without_permission_payload,
                token=submitter_token,
            )
            if recovery_without_permission_status != 403 or recovery_without_permission_response.get("error") != "authz_rejected":
                raise SystemExit(
                    f"[ERROR] submitter without recovery permission should be rejected, got "
                    f"{recovery_without_permission_status} {recovery_without_permission_response}"
                )
            recovery_good_payload = build_request(
                out_base=out_base,
                job_id="operator-request-submission-recovery-good",
                caller="recovery_submitter_demo",
            )
            recovery_good_payload["record_recovery_service_mode"] = "manual"
            recovery_good_payload["record_recovery_service_id"] = "bridge-demo-recovery"
            recovery_good_payload["record_recovery_endpoint_url"] = "http://127.0.0.1:9999"
            recovery_good_status, recovery_good_response = post_json(
                f"http://127.0.0.1:{port}/v1/request/submit",
                recovery_good_payload,
                token=recovery_token,
            )
            if recovery_good_status != 202 or recovery_good_response.get("service_id") != "bridge-demo-recovery":
                raise SystemExit(
                    f"[ERROR] recovery-authorized submitter should be able to bind allowed service_id, got "
                    f"{recovery_good_status} {recovery_good_response}"
                )
            recovery_spoof_payload = build_request(
                out_base=out_base,
                job_id="operator-request-submission-recovery-spoof",
                caller="recovery_submitter_demo",
            )
            recovery_spoof_payload["record_recovery_service_mode"] = "manual"
            recovery_spoof_payload["record_recovery_service_id"] = "forbidden-recovery"
            recovery_spoof_payload["record_recovery_endpoint_url"] = "http://127.0.0.1:9999"
            recovery_spoof_status, recovery_spoof_response = post_json(
                f"http://127.0.0.1:{port}/v1/request/submit",
                recovery_spoof_payload,
                token=recovery_token,
            )
            if recovery_spoof_status != 403 or recovery_spoof_response.get("error") != "authz_rejected":
                raise SystemExit(
                    f"[ERROR] recovery service spoof should be rejected, got "
                    f"{recovery_spoof_status} {recovery_spoof_response}"
                )
            with connect_db(str(db_path)) as conn:
                row = conn.execute(
                    """
                    SELECT submission_id, status, caller, tenant_id, request_digest
                    FROM workflow_submissions
                    WHERE submission_id = ?
                    """,
                    (submission_id,),
                ).fetchone()
                if row is None:
                    raise SystemExit("[ERROR] workflow_submissions row was not written")
                if str(row["status"]) != "pending_approval":
                    raise SystemExit(f"[ERROR] unexpected submission status: {dict(row)}")
                mutation = conn.execute(
                    """
                    SELECT operation, entity_type, entity_id
                    FROM control_plane_mutations
                    WHERE entity_type = 'workflow_submission' AND entity_id = ?
                    """,
                    (submission_id,),
                ).fetchone()
                if mutation is None:
                    raise SystemExit("[ERROR] submit_request mutation row was not written")
            analyst_list_status, analyst_list_response = request_json(
                f"http://127.0.0.1:{port}/v1/requests?tenant_id=demo_tenant&status=pending_approval",
                token=analyst_token,
            )
            if analyst_list_status != 200 or analyst_list_response.get("returned_count") != 0:
                raise SystemExit(
                    f"[ERROR] non-review analyst should not see another caller's pending requests: "
                    f"{analyst_list_status} {analyst_list_response}"
                )
            analyst_detail_status, analyst_detail_response = request_json(
                f"http://127.0.0.1:{port}/v1/requests/{submission_id}",
                token=analyst_token,
            )
            if analyst_detail_status != 403 or analyst_detail_response.get("error") != "authz_rejected":
                raise SystemExit(
                    f"[ERROR] non-review analyst should not read another caller's request detail: "
                    f"{analyst_detail_status} {analyst_detail_response}"
                )
            analyst_approve_status, analyst_approve_response = post_json(
                f"http://127.0.0.1:{port}/v1/request/{submission_id}/approve",
                {},
                token=analyst_token,
            )
            if analyst_approve_status != 403 or analyst_approve_response.get("error") != "authz_rejected":
                raise SystemExit(
                    f"[ERROR] non-approver analyst should not approve another caller's request: "
                    f"{analyst_approve_status} {analyst_approve_response}"
                )
            analyst_reject_status, analyst_reject_response = post_json(
                f"http://127.0.0.1:{port}/v1/request/{submission_id}/reject",
                {"reason": "analyst should not reject"},
                token=analyst_token,
            )
            if analyst_reject_status != 403 or analyst_reject_response.get("error") != "authz_rejected":
                raise SystemExit(
                    f"[ERROR] non-review analyst should not reject another caller's request: "
                    f"{analyst_reject_status} {analyst_reject_response}"
                )
            list_status, list_response = request_json(
                f"http://127.0.0.1:{port}/v1/requests?tenant_id=demo_tenant&status=pending_approval",
                token=approver_token,
            )
            if list_status != 200 or list_response.get("returned_count", 0) < 1:
                raise SystemExit(f"[ERROR] pending request list failed: {list_status} {list_response}")
            if list_response.get("schema") != "operator_request_submission_list/v1":
                raise SystemExit(f"[ERROR] unexpected list schema: {list_response}")
            detail_status, detail_response = request_json(
                f"http://127.0.0.1:{port}/v1/requests/{submission_id}",
                token=approver_token,
            )
            if detail_status != 200 or detail_response.get("submission_id") != submission_id:
                raise SystemExit(f"[ERROR] request detail failed: {detail_status} {detail_response}")
            if not isinstance(detail_response.get("request"), dict):
                raise SystemExit(f"[ERROR] request detail did not include stored request payload: {detail_response}")
            self_status, self_approve = post_json(
                f"http://127.0.0.1:{port}/v1/request/{submission_id}/approve",
                {},
                token=submitter_token,
            )
            if self_status != 403 or self_approve.get("error") != "same_identity_self_approval":
                raise SystemExit(f"[ERROR] expected same-identity approval reject, got {self_status} {self_approve}")
            approve_status, approve_response = post_json(
                f"http://127.0.0.1:{port}/v1/request/{submission_id}/approve",
                {},
                token=approver_token,
            )
            if approve_status != 202 or approve_response.get("status") != "approved":
                raise SystemExit(f"[ERROR] expected approval, got {approve_status} {approve_response}")
            if not isinstance(approve_response.get("job_control"), dict) or approve_response["job_control"].get("state") != "running":
                raise SystemExit(f"[ERROR] approval did not start job: {approve_response}")
            with connect_db(str(db_path)) as conn:
                approved = conn.execute(
                    """
                    SELECT status, approved_by, approved_at_utc
                    FROM workflow_submissions
                    WHERE submission_id = ?
                    """,
                    (submission_id,),
                ).fetchone()
                if approved is None or approved["status"] != "approved" or approved["approved_by"] != "privacy_operator_demo":
                    raise SystemExit(f"[ERROR] approval row was not updated: {dict(approved) if approved else approved}")
                approval_mutation = conn.execute(
                    """
                    SELECT operation, actor
                    FROM control_plane_mutations
                    WHERE entity_type = 'workflow_submission' AND entity_id = ? AND operation = 'approve_request'
                    """,
                    (submission_id,),
                ).fetchone()
                if approval_mutation is None or approval_mutation["actor"] != "privacy_operator_demo":
                    raise SystemExit("[ERROR] approve_request mutation row was not written")
            second_status, second_response = post_json(
                f"http://127.0.0.1:{port}/v1/request/submit",
                build_request(out_base=out_base, job_id="operator-request-submission-reject-smoke"),
                token=submitter_token,
            )
            if second_status != 202:
                raise SystemExit(f"[ERROR] expected second HTTP 202, got {second_status}: {second_response}")
            reject_id = str(second_response.get("submission_id") or "")
            auditor_list_status, auditor_list_response = request_json(
                f"http://127.0.0.1:{port}/v1/requests?tenant_id=demo_tenant&status=pending_approval",
                token=auditor_token,
            )
            if auditor_list_status != 200 or auditor_list_response.get("returned_count", 0) < 1:
                raise SystemExit(f"[ERROR] auditor pending request list failed: {auditor_list_status} {auditor_list_response}")
            auditor_detail_status, auditor_detail_response = request_json(
                f"http://127.0.0.1:{port}/v1/requests/{reject_id}",
                token=auditor_token,
            )
            if auditor_detail_status != 200 or auditor_detail_response.get("submission_id") != reject_id:
                raise SystemExit(f"[ERROR] auditor request detail failed: {auditor_detail_status} {auditor_detail_response}")
            auditor_approve_status, auditor_approve_response = post_json(
                f"http://127.0.0.1:{port}/v1/request/{reject_id}/approve",
                {},
                token=auditor_token,
            )
            if auditor_approve_status != 403 or auditor_approve_response.get("error") != "authz_rejected":
                raise SystemExit(
                    f"[ERROR] auditor should not approve requests: "
                    f"{auditor_approve_status} {auditor_approve_response}"
                )
            reject_status, reject_response = post_json(
                f"http://127.0.0.1:{port}/v1/request/{reject_id}/reject",
                {"reason": "smoke rejection"},
                token=approver_token,
            )
            if reject_status != 200 or reject_response.get("status") != "rejected":
                raise SystemExit(f"[ERROR] expected rejection, got {reject_status} {reject_response}")
            if reject_response.get("rejection_reason") != "smoke rejection":
                raise SystemExit(f"[ERROR] rejection reason was not preserved: {reject_response}")
            with connect_db(str(db_path)) as conn:
                rejected = conn.execute(
                    """
                    SELECT status, rejected_by, rejection_reason
                    FROM workflow_submissions
                    WHERE submission_id = ?
                    """,
                    (reject_id,),
                ).fetchone()
                if (
                    rejected is None
                    or rejected["status"] != "rejected"
                    or rejected["rejected_by"] != "privacy_operator_demo"
                    or rejected["rejection_reason"] != "smoke rejection"
                ):
                    raise SystemExit(f"[ERROR] rejection row was not updated: {dict(rejected) if rejected else rejected}")
                rejection_mutation = conn.execute(
                    """
                    SELECT operation, actor
                    FROM control_plane_mutations
                    WHERE entity_type = 'workflow_submission' AND entity_id = ? AND operation = 'reject_request'
                    """,
                    (reject_id,),
                ).fetchone()
                if rejection_mutation is None or rejection_mutation["actor"] != "privacy_operator_demo":
                    raise SystemExit("[ERROR] reject_request mutation row was not written")
            third_status, third_response = post_json(
                f"http://127.0.0.1:{port}/v1/request/submit",
                build_request(
                    out_base=out_base,
                    job_id="operator-request-submission-auditor-reject-smoke",
                ),
                token=submitter_token,
            )
            if third_status != 202:
                raise SystemExit(f"[ERROR] expected third HTTP 202, got {third_status}: {third_response}")
            auditor_reject_id = str(third_response.get("submission_id") or "")
            auditor_reject_status, auditor_reject_response = post_json(
                f"http://127.0.0.1:{port}/v1/request/{auditor_reject_id}/reject",
                {"reason": "auditor review rejection"},
                token=auditor_token,
            )
            if auditor_reject_status != 200 or auditor_reject_response.get("status") != "rejected":
                raise SystemExit(
                    f"[ERROR] auditor rejection should succeed, got "
                    f"{auditor_reject_status} {auditor_reject_response}"
                )
            if auditor_reject_response.get("rejected_by") != "compliance_auditor_demo":
                raise SystemExit(f"[ERROR] auditor rejection actor was not preserved: {auditor_reject_response}")
            with connect_db(str(db_path)) as conn:
                auditor_rejected = conn.execute(
                    """
                    SELECT status, rejected_by, rejection_reason
                    FROM workflow_submissions
                    WHERE submission_id = ?
                    """,
                    (auditor_reject_id,),
                ).fetchone()
                if (
                    auditor_rejected is None
                    or auditor_rejected["status"] != "rejected"
                    or auditor_rejected["rejected_by"] != "compliance_auditor_demo"
                    or auditor_rejected["rejection_reason"] != "auditor review rejection"
                ):
                    raise SystemExit(
                        f"[ERROR] auditor rejection row was not updated: "
                        f"{dict(auditor_rejected) if auditor_rejected else auditor_rejected}"
                    )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            dashboard._start_job_thread = original_start_job

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sibling_outputs = {
        "spoof_caller_reject": {
            "status": spoof_caller_status,
            "response": spoof_caller_response,
        },
        "spoof_tenant_reject": {
            "status": spoof_tenant_status,
            "response": spoof_tenant_response,
        },
        "spoof_dataset_reject": {
            "status": spoof_dataset_status,
            "response": spoof_dataset_response,
        },
        "recovery_without_permission_reject": {
            "status": recovery_without_permission_status,
            "response": recovery_without_permission_response,
        },
        "recovery_allowed_submit": recovery_good_response,
        "recovery_service_spoof_reject": {
            "status": recovery_spoof_status,
            "response": recovery_spoof_response,
        },
        "analyst_list": analyst_list_response,
        "analyst_detail_reject": {
            "status": analyst_detail_status,
            "response": analyst_detail_response,
        },
        "analyst_approve_reject": {
            "status": analyst_approve_status,
            "response": analyst_approve_response,
        },
        "analyst_reject_reject": {
            "status": analyst_reject_status,
            "response": analyst_reject_response,
        },
        "list": list_response,
        "detail": detail_response,
        "self_approve_reject": {
            "status": self_status,
            "response": self_approve,
        },
        "approve": approve_response,
        "auditor_list": auditor_list_response,
        "auditor_detail": auditor_detail_response,
        "auditor_approve_reject": {
            "status": auditor_approve_status,
            "response": auditor_approve_response,
        },
        "reject": reject_response,
        "auditor_reject": auditor_reject_response,
    }
    for suffix, payload in sibling_outputs.items():
        sample_path = out_path.with_name(f"{out_path.stem}_{suffix}{out_path.suffix}")
        sample_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
