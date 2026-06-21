#!/usr/bin/env python3
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:18094"
PRIVACY_BASE = "http://127.0.0.1:18194"
COOKIE = "seccomp_identity_session=demo-console-operator-token"


def request_json(url: str, *, method: str = "GET", body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> tuple[int, Any]:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"Cookie": COOKIE}
    if headers:
        hdrs.update(headers)
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=payload, headers=hdrs, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=120) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, raw


def expect_ok(name: str, status: int, payload: Any) -> None:
    if status >= 400:
        raise SystemExit(f"[FAIL] {name}: HTTP {status} -> {payload}")
    print(f"[OK] {name}: HTTP {status}")


def main() -> int:
    login_status, login_payload = request_json(
        f"{BASE}/v1/session/login",
        method="POST",
        body={"bearer_token": "demo-console-operator-token", "max_age_seconds": 8 * 60 * 60},
        headers={"Content-Type": "application/json"},
    )
    expect_ok("session_login", login_status, login_payload)

    checks: list[tuple[str, str, str, dict[str, Any] | None]] = [
        ("dashboard", f"{BASE}/v1/dashboard", "GET", None),
        ("runs", f"{BASE}/v1/runs?limit=5", "GET", None),
        ("requests_list", f"{BASE}/v1/requests?limit=5", "GET", None),
        ("privacy_budget_main", f"{BASE}/v1/privacy-budget/approvals?limit=10", "GET", None),
        ("privacy_budget_standalone", f"{PRIVACY_BASE}/v1/privacy-budget/approvals?limit=10", "GET", None),
        ("sse_query", f"{BASE}/v1/sse/search", "POST", {"keyword": "China", "db_path": "sse/example_db.json", "output_format": "hex"}),
        ("pjc_only", f"{BASE}/v1/pjc/run-only", "POST", {
            "server_csv": "bridge/out/demo_job/server.csv",
            "client_csv": "bridge/out/demo_job/client.csv",
            "job_meta": "bridge/out/demo_job/job_meta.json",
            "job_id": "console-regression-pjc-only",
            "caller": "auto_demo",
            "tenant_id": "demo_tenant",
            "dataset_id": "bridge_demo_dataset",
            "threshold_k": 1,
            "max_queries": 5,
            "pjc_build": False,
        }),
        ("audit_public_report", f"{BASE}/proxy/audit/v1/public-report", "GET", None),
        ("audit_chain", f"{BASE}/proxy/audit/v1/audit-chain", "GET", None),
        ("audit_observability", f"{BASE}/proxy/audit/v1/observability", "GET", None),
        ("audit_lineage", f"{BASE}/proxy/audit/v1/catalog-lineage", "GET", None),
    ]

    for name, url, method, body in checks:
      status, payload = request_json(url, method=method, body=body)
      expect_ok(name, status, payload)

    job_id = f"request-demo-{int(time.time())}"
    request_body = {
        "submitted_by": "console-operator",
        "tenant_id": "demo_tenant",
        "dataset_id": "bridge_demo_dataset",
        "service_id": "bridge-demo-recovery",
        "query_type": "cross_party_match",
        "request": {
            "schema": "query_workflow_request/v1",
            "query_type": "cross_party_match",
            "caller": "console_operator",
            "tenant_id": "demo_tenant",
            "dataset_id": "bridge_demo_dataset",
            "record_recovery_service_id": "bridge-demo-recovery",
            "server_source": "sse/examples/bridge_server_records.jsonl",
            "client_source": "sse/examples/bridge_client_records.jsonl",
            "server_join_key_field": "email",
            "client_join_key_field": "email",
            "client_value_field": "amount",
            "server_normalizer": "email",
            "client_normalizer": "email",
            "client_value_mode": "raw-int",
            "token_scope": "defense-demo-scope",
            "token_secret_env": "BRIDGE_TOKEN_SECRET",
            "job_id": job_id,
            "out_base": f"tmp/defense_demo/runs/{job_id}",
            "sse_export_policy_config": "sse/config/export_policy.example.json",
            "server_filters": ["campaign=demo"],
            "client_filters": ["campaign=demo"],
            "k": 1,
            "n": 5,
            "deny_duplicate_query": True,
            "sse_export_handoff_mode": "fifo",
            "cleanup_sse_export_handoff_files_after_bridge": True,
        },
    }
    submit_status, submit_payload = request_json(f"{BASE}/v1/request/submit", method="POST", body=request_body)
    expect_ok("request_submit", submit_status, submit_payload)

    request_id = submit_payload["submission_id"]
    detail_status, detail_payload = request_json(f"{BASE}/v1/requests/{urllib.parse.quote(request_id)}")
    expect_ok("request_detail", detail_status, detail_payload)

    health_status, health_payload = request_json(
        f"{BASE}/proxy/health/v1/platform-health?out_base="
        + urllib.parse.quote(str(REPO_ROOT / "tmp/defense_demo/runs/main_completed_run"))
        + "&metadata_db="
        + urllib.parse.quote(str(REPO_ROOT / "tmp/defense_demo/db/platform_metadata.db"))
    )
    expect_ok("platform_health", health_status, health_payload)

    business_headers = {"Authorization": "Bearer demo-merchant-token"}
    business_check_status, business_check_payload = request_json(
        "http://127.0.0.1:18190/v1/business-access/check",
        method="POST",
        body={
            "role": "merchant_staff",
            "entity": "orders",
            "fields": ["orders.order_id", "orders.total_amount_cents", "orders.buyer_email"],
            "purpose": "merchant_order_ops",
            "relationship": "merchant_of_order",
            "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1"},
        },
        headers=business_headers,
    )
    expect_ok("business_access_check", business_check_status, business_check_payload)

    business_preview_status, business_preview_payload = request_json(
        "http://127.0.0.1:18190/v1/business-data/read-preview",
        method="POST",
        body={
            "role": "merchant_staff",
            "entity": "orders",
            "fields": ["orders.order_id", "orders.status", "orders.total_amount_cents"],
            "purpose": "merchant_order_ops",
            "relationship": "merchant_of_order",
            "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1"},
        },
        headers=business_headers,
    )
    expect_ok("business_data_preview", business_preview_status, business_preview_payload)

    print("[OK] all checked console-backed features passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
