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


def build_request(*, out_base: Path, job_id: str = "operator-request-submission-smoke") -> dict[str, Any]:
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
        "server_filters": ["campaign=demo"],
        "client_filters": ["campaign=demo"],
        "token_scope": "operator-request-submission-smoke",
        "token_secret": "operator-request-submission-secret",
        "job_id": job_id,
        "out_base": str(out_base),
        "caller": "auto_demo",
        "tenant_id": "demo_tenant",
        "dataset_id": "bridge_demo_dataset",
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
    os.environ[submitter_env] = "operator-request-submitter-token"
    os.environ[approver_env] = "operator-request-approver-token"
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
            status, response = post_json(
                f"http://127.0.0.1:{port}/v1/request/submit",
                build_request(out_base=out_base),
                token=submitter_token,
            )
            if status != 202:
                raise SystemExit(f"[ERROR] expected HTTP 202, got {status}: {response}")
            if response.get("schema") != "operator_request_submission/v1":
                raise SystemExit(f"[ERROR] unexpected response schema: {response}")
            submission_id = str(response.get("submission_id") or "")
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
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            dashboard._start_job_thread = original_start_job

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sibling_outputs = {
        "list": list_response,
        "detail": detail_response,
        "approve": approve_response,
        "reject": reject_response,
    }
    for suffix, payload in sibling_outputs.items():
        sample_path = out_path.with_name(f"{out_path.stem}_{suffix}{out_path.suffix}")
        sample_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
