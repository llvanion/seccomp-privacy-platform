#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import serve_operator_dashboard as dashboard
from metadata_db import apply_migrations, connect_db
from runtime_service_helpers import available_port


REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PUBLIC_KEYS = {
    "path",
    "display_path",
    "out_base",
    "out_base_display",
    "sha256",
    "public_report_sha256",
    "audit_chain_sha256",
    "input_sha256",
    "output_sha256",
    "query_fingerprint",
    "query_payload_sha256",
    "artifact_inventory",
    "items",
    "intersection_size",
    "intersection_sum",
    "details",
    "bridge",
}


def request_json(url: str, *, token: str = "", method: str = "GET", payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return int(exc.code), json.loads(raw) if raw else {"error": "empty_error_response"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_no_public_leaks(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            require(key not in FORBIDDEN_PUBLIC_KEYS, f"public dashboard leaked {path}.{key}: {value}")
            require_no_public_leaks(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            require_no_public_leaks(child, path=f"{path}[{index}]")


def seed_identity_metadata(db_path: Path, *, token_config_path: Path) -> None:
    now = dashboard._utc_now()
    normal_env = "SECCOMP_DASHBOARD_NORMAL_TOKEN"
    admin_env = "SECCOMP_DASHBOARD_ADMIN_TOKEN"
    os.environ[normal_env] = "dashboard-normal-token"
    os.environ[admin_env] = "dashboard-admin-token"
    token_config_path.write_text(
        json.dumps(
            {
                "schema": "api_identity_token_map/v1",
                "tokens": [
                    {"token_env": normal_env, "issuer": "smoke", "subject": "user:normal"},
                    {"token_env": admin_env, "issuer": "smoke", "subject": "user:admin"},
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with connect_db(str(db_path)) as conn:
        apply_migrations(conn)
        conn.execute(
            "INSERT OR IGNORE INTO tenants(tenant_id, created_at_utc, source) VALUES(?, ?, ?)",
            ("demo_tenant", now, "operator_dashboard_public_summary_smoke"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO callers(caller, tenant_id, created_at_utc, source) VALUES(?, ?, ?, ?)",
            ("normal_demo", "demo_tenant", now, "operator_dashboard_public_summary_smoke"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO callers(caller, tenant_id, created_at_utc, source) VALUES(?, ?, ?, ?)",
            ("admin_demo", "demo_tenant", now, "operator_dashboard_public_summary_smoke"),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO caller_identities(
              caller, issuer, subject, subject_type, display_name,
              platform_roles_json, enabled, source, created_at_utc
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "normal_demo",
                "smoke",
                "user:normal",
                "user",
                "Normal Dashboard Caller",
                json.dumps(["query_submitter"]),
                1,
                "operator_dashboard_public_summary_smoke",
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
                "admin_demo",
                "smoke",
                "user:admin",
                "user",
                "Admin Dashboard Caller",
                json.dumps(["platform_admin"]),
                1,
                "operator_dashboard_public_summary_smoke",
                now,
            ),
        )
        conn.commit()


def seed_run(out_base: Path) -> None:
    a_psi = out_base / "a_psi_run"
    qwf = out_base / "query_workflow"
    a_psi.mkdir(parents=True, exist_ok=True)
    qwf.mkdir(parents=True, exist_ok=True)
    (a_psi / "public_report.json").write_text(
        json.dumps(
            {
                "schema": "public_report/v2",
                "generated_at_utc": "2026-06-02T00:00:00Z",
                "policy_version": "smoke",
                "job_id": "dashboard-public-smoke",
                "correlation_id": "dashboard-public-smoke",
                "caller": "normal_demo",
                "released": True,
                "reason": "ok",
                "reason_code": "ok",
                "window": {"start": None, "end": None},
                "k_threshold": 1,
                "details": {"intersection_size": 2, "intersection_sum_raw": 425},
                "bridge": {"server_csv_sha256": "a" * 64},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (a_psi / "attribution_result.json").write_text(
        json.dumps({"intersection_size": 2, "intersection_sum": 425}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (qwf / "status.json").write_text(
        json.dumps(
            {
                "schema": "query_workflow_status/v1",
                "workflow": "query_workflow",
                "mode": "execute",
                "job_id": "dashboard-public-smoke",
                "out_base": str(out_base),
                "state": "completed",
                "terminal": True,
                "last_updated_at_utc": "2026-06-02T00:00:00Z",
                "latest_receipt_id": "receipt-1",
                "receipt_count": 1,
                "last_exit_code": 0,
                "artifact_summary": {},
                "public_report_available": True,
                "audit_chain_available": False,
                "caller": "normal_demo",
                "tenant_id": "demo_tenant",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test caller-safe operator dashboard summaries.")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="seccomp_dashboard_public.") as tmp_raw:
        tmp_dir = Path(tmp_raw)
        out_base = tmp_dir / "run"
        out_base.mkdir(parents=True)
        seed_run(out_base)
        db_path = tmp_dir / "metadata.db"
        token_config_path = tmp_dir / "identity_tokens.json"
        seed_identity_metadata(db_path, token_config_path=token_config_path)

        port = available_port()
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
            base = f"http://127.0.0.1:{port}/v1/dashboard"
            unauth_status, unauth = request_json(base)
            require(unauth_status == 403, f"expected unauth dashboard 403, got {unauth_status}: {unauth}")

            normal_status, normal = request_json(base, token=os.environ["SECCOMP_DASHBOARD_NORMAL_TOKEN"])
            require(normal_status == 200, f"expected normal dashboard 200, got {normal_status}: {normal}")
            require(normal.get("schema") == "operator_dashboard_public_summary/v1", f"normal caller did not get public summary: {normal}")
            require_no_public_leaks(normal)
            require((normal.get("redaction") or {}).get("exact_results_redacted") is True, f"redaction marker missing: {normal}")
            normal_runs_status, normal_runs = request_json(
                f"http://127.0.0.1:{port}/v1/runs",
                token=os.environ["SECCOMP_DASHBOARD_NORMAL_TOKEN"],
            )
            require(normal_runs_status == 403, f"normal caller should not read full runs: {normal_runs_status}: {normal_runs}")
            normal_job_status, normal_job = request_json(
                f"http://127.0.0.1:{port}/v1/jobs/dashboard-public-smoke",
                token=os.environ["SECCOMP_DASHBOARD_NORMAL_TOKEN"],
            )
            require(normal_job_status == 403, f"normal caller should not read full job detail: {normal_job_status}: {normal_job}")
            normal_result_status, normal_result = request_json(
                f"http://127.0.0.1:{port}/v1/jobs/dashboard-public-smoke/result",
                token=os.environ["SECCOMP_DASHBOARD_NORMAL_TOKEN"],
            )
            require(normal_result_status == 403, f"normal caller should not read exact job result: {normal_result_status}: {normal_result}")
            normal_start_status, normal_start = request_json(
                f"http://127.0.0.1:{port}/v1/jobs/start",
                token=os.environ["SECCOMP_DASHBOARD_NORMAL_TOKEN"],
                method="POST",
                payload={},
            )
            require(normal_start_status == 403, f"normal caller should not start dashboard jobs directly: {normal_start_status}: {normal_start}")

            admin_status, admin = request_json(base, token=os.environ["SECCOMP_DASHBOARD_ADMIN_TOKEN"])
            require(admin_status == 200, f"expected admin dashboard 200, got {admin_status}: {admin}")
            require(admin.get("schema") != "operator_dashboard_public_summary/v1", f"admin got public summary unexpectedly: {admin}")
            require("audit_center" in admin and "job_control" in admin, f"admin dashboard missing operator fields: {admin}")
            require("result" in (admin.get("job_control") or {}), f"admin dashboard missing exact result: {admin}")
            admin_job_status, admin_job = request_json(
                f"http://127.0.0.1:{port}/v1/jobs/dashboard-public-smoke",
                token=os.environ["SECCOMP_DASHBOARD_ADMIN_TOKEN"],
            )
            require(admin_job_status == 200, f"admin should read full job detail: {admin_job_status}: {admin_job}")
            require("out_base" in admin_job and "result" in admin_job, f"admin job detail missing full fields: {admin_job}")
            admin_result_status, admin_result = request_json(
                f"http://127.0.0.1:{port}/v1/jobs/dashboard-public-smoke/result",
                token=os.environ["SECCOMP_DASHBOARD_ADMIN_TOKEN"],
            )
            require(admin_result_status == 200, f"admin should read exact job result: {admin_result_status}: {admin_result}")
            require(admin_result.get("intersection_size") == 2, f"admin exact result missing: {admin_result}")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    report = {
        "schema": "operator_dashboard_public_summary_smoke/v1",
        "status": "ok",
        "unauth_status": unauth_status,
        "normal_schema": normal.get("schema"),
        "admin_full_view": "audit_center" in admin and "job_control" in admin,
        "normal_full_read_status": normal_job_status,
        "normal_exact_result_status": normal_result_status,
        "normal_direct_start_status": normal_start_status,
        "admin_full_job_status": admin_job_status,
        "admin_exact_result_status": admin_result_status,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    (out_dir / "operator_dashboard_public_summary_smoke.json").write_text(text + "\n", encoding="utf-8")
    (out_dir / "operator_dashboard_public_summary.json").write_text(json.dumps(normal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
