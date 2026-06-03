#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(method: str, url: str, *, body: dict | None = None, token: str = "", timeout: float = 3.0) -> tuple[int, dict]:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return int(resp.status), payload
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        return int(exc.code), payload


def wait_ready(base: str, *, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            status, payload = request_json("GET", f"{base}/healthz", timeout=0.5)
            if status == 200 and payload.get("ok") is True:
                return
            last = f"{status} {payload}"
        except Exception as exc:
            last = repr(exc)
        time.sleep(0.1)
    raise RuntimeError(f"metadata API did not become ready: {last}")


def init_db(db_path: Path) -> None:
    code = (
        "import sys;"
        f"sys.path.insert(0, {str(REPO_ROOT / 'scripts')!r});"
        "from metadata_db import connect_db, apply_migrations;"
        f"conn=connect_db({str(db_path)!r});"
        "apply_migrations(conn);"
        "conn.executescript('''"
        "INSERT OR IGNORE INTO tenants(tenant_id,created_at_utc,source,last_seen_job_id) VALUES('commerce_tenant','2026-06-01T00:00:00Z','smoke',NULL);"
        "INSERT OR IGNORE INTO callers(caller,tenant_id,created_at_utc,source,last_seen_job_id) VALUES('merchant_caller','commerce_tenant','2026-06-01T00:00:00Z','smoke',NULL);"
        "INSERT OR IGNORE INTO callers(caller,tenant_id,created_at_utc,source,last_seen_job_id) VALUES('admin_caller','commerce_tenant','2026-06-01T00:00:00Z','smoke',NULL);"
        "INSERT OR IGNORE INTO caller_identities(caller,issuer,subject,subject_type,service_id,display_name,platform_roles_json,enabled,metadata_json,source,created_at_utc) VALUES('merchant_caller','local','user:merchant','user',NULL,'Merchant','[\"query_submitter\"]',1,'{\"business_role\":\"merchant_staff\"}','smoke','2026-06-01T00:00:00Z');"
        "INSERT OR IGNORE INTO caller_identities(caller,issuer,subject,subject_type,service_id,display_name,platform_roles_json,enabled,metadata_json,source,created_at_utc) VALUES('admin_caller','local','user:admin','user',NULL,'Admin','[\"platform_admin\"]',1,'{}','smoke','2026-06-01T00:00:00Z');"
        "INSERT OR IGNORE INTO business_identities(business_identity_id,tenant_id,dataset_id,identity_kind,caller_id,subject_external_id,display_label,enabled,created_at_utc,updated_at_utc,metadata_json) VALUES('merchant-1','commerce_tenant','orders_analytics','merchant_staff','merchant_caller','merchant-ext-1','Merchant',1,'2026-06-01T00:00:00Z','2026-06-01T00:00:00Z','{}');"
        "INSERT OR IGNORE INTO orders(order_id,tenant_id,dataset_id,service_id,buyer_email,platform_id,campaign_id,currency,total_amount_cents,placed_at_utc,status,created_at_utc,ingested_at_utc) VALUES('o-1','commerce_tenant','orders_analytics','svc-commerce','buyer@example.com','shopify','campaign-demo','USD',12345,'2026-06-01T01:00:00Z','paid','2026-06-01T01:00:00Z','2026-06-01T01:01:00Z');"
        "''');"
        "conn.commit(); conn.close()"
    )
    subprocess.run([sys.executable, "-c", code], cwd=str(REPO_ROOT), check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-test metadata API business field access checks.")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "metadata.sqlite"
    init_db(db_path)

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    token_env = "BUSINESS_ACCESS_API_SMOKE_TOKEN"
    token = "business-access-smoke-token"
    admin_token_env = "BUSINESS_ACCESS_API_SMOKE_ADMIN_TOKEN"
    admin_token = "business-access-smoke-admin-token"
    identity_config = out_dir / "identity_tokens.json"
    identity_config.write_text(
        json.dumps(
            {
                "schema": "api_identity_token_map/v1",
                "tokens": [
                    {
                        "token_env": token_env,
                        "issuer": "local",
                        "subject": "user:merchant",
                    },
                    {
                        "token_env": admin_token_env,
                        "issuer": "local",
                        "subject": "user:admin",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env[token_env] = token
    env[admin_token_env] = admin_token
    env.pop("HTTP_PROXY", None)
    env.pop("http_proxy", None)
    proc = subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "serve_metadata_api.py"),
            "--db-path", str(db_path),
            "--bind-host", "127.0.0.1",
            "--port", str(port),
            "--identity-token-config", str(identity_config),
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_ready(base)
        status, identities = request_json(
            "GET",
            f"{base}/v1/entities/business-identities?caller=merchant_caller",
            token=token,
        )
        if status != 200 or (identities.get("result") or {}).get("count") != 1:
            raise AssertionError(f"business-identities query failed: {status} {identities}")
        status, allowed = request_json(
            "POST",
            f"{base}/v1/business-access/check",
            token=token,
            body={
                "role": "merchant_staff",
                "entity": "orders",
                "fields": ["orders.order_id"],
                "purpose": "merchant_order_ops",
                "relationship": "merchant_of_order",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1"},
            },
        )
        if status != 200 or (allowed.get("result") or {}).get("decision") != "allow":
            raise AssertionError(f"merchant allow check failed: {status} {allowed}")
        status, preview = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=token,
            body={
                "role": "merchant_staff",
                "entity": "orders",
                "fields": ["orders.order_id", "orders.status", "orders.total_amount_cents"],
                "purpose": "merchant_order_ops",
                "relationship": "merchant_of_order",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1"},
                "limit": 5,
            },
        )
        preview_result = preview.get("result") or {}
        preview_rows = preview_result.get("rows") or []
        if (
            status != 200
            or preview_result.get("decision") != "allow"
            or preview_result.get("count") != 1
            or not preview_rows
            or preview_rows[0].get("orders.total_amount_cents") != 12345
        ):
            raise AssertionError(f"merchant read-preview allow failed: {status} {preview}")
        (out_dir / "business_read_preview_allow.json").write_text(
            json.dumps(preview_result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        status, filter_conflict = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=token,
            body={
                "role": "merchant_staff",
                "entity": "orders",
                "fields": ["orders.order_id"],
                "purpose": "merchant_order_ops",
                "relationship": "merchant_of_order",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1"},
                "filters": {"order_id": "o-2"},
            },
        )
        filter_conflict_status = status
        if filter_conflict_status != 403 or "conflicts with authorized scope" not in str(filter_conflict.get("error") or ""):
            raise AssertionError(f"business read-preview filter conflict was not denied: {filter_conflict_status} {filter_conflict}")
        status, tenant_filter_conflict = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=token,
            body={
                "role": "merchant_staff",
                "entity": "orders",
                "fields": ["orders.order_id"],
                "purpose": "merchant_order_ops",
                "relationship": "merchant_of_order",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1"},
                "filters": {"tenant_id": "other_tenant"},
            },
        )
        tenant_filter_conflict_status = status
        if tenant_filter_conflict_status != 403 or "conflicts with authorized scope" not in str(tenant_filter_conflict.get("error") or ""):
            raise AssertionError(
                f"business read-preview tenant filter conflict was not denied: "
                f"{tenant_filter_conflict_status} {tenant_filter_conflict}"
            )
        status, denied = request_json(
            "POST",
            f"{base}/v1/business-access/check",
            token=token,
            body={
                "role": "merchant_staff",
                "entity": "orders",
                "fields": ["order_fulfillment.delivery_address"],
                "purpose": "merchant_order_ops",
                "relationship": "merchant_of_order",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1"},
            },
        )
        if status != 200 or (denied.get("result") or {}).get("decision") != "deny":
            raise AssertionError(f"merchant deny check failed: {status} {denied}")
        status, preview_denied = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=token,
            body={
                "role": "merchant_staff",
                "entity": "orders",
                "fields": ["orders.buyer_email"],
                "purpose": "merchant_order_ops",
                "relationship": "merchant_of_order",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1"},
            },
        )
        preview_denied_status = status
        if preview_denied_status != 403 or "business field access denied" not in str(preview_denied.get("error") or ""):
            raise AssertionError(f"merchant read-preview deny failed: {preview_denied_status} {preview_denied}")
        status, masked = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=admin_token,
            body={
                "role": "customer_service_agent",
                "entity": "orders",
                "fields": ["orders.order_id", "orders.buyer_email"],
                "purpose": "support_case",
                "relationship": "assigned_support_case",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1", "case_id": "case-1"},
            },
        )
        masked_text = json.dumps(masked, ensure_ascii=False)
        masked_rows = (masked.get("result") or {}).get("rows") or []
        if (
            status != 200
            or (masked.get("result") or {}).get("decision") != "mask"
            or not masked_rows
            or masked_rows[0].get("orders.buyer_email", {}).get("masked") is not True
            or "buyer@example.com" in masked_text
        ):
            raise AssertionError(f"support masked read-preview failed: {status} {masked}")
        if "case_id" not in ((masked.get("result") or {}).get("scope") or {}):
            raise AssertionError(f"support scope context was not preserved: {masked}")
        (out_dir / "business_read_preview_masked.json").write_text(
            json.dumps(masked.get("result") or {}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        status, sensitive_filter = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=admin_token,
            body={
                "role": "customer_service_agent",
                "entity": "orders",
                "fields": ["orders.order_id"],
                "purpose": "support_case",
                "relationship": "assigned_support_case",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1"},
                "filters": {"buyer_email": "buyer@example.com"},
            },
        )
        sensitive_filter_status = status
        if sensitive_filter_status != 400 or "unsupported business data filter" not in str(sensitive_filter.get("error") or ""):
            raise AssertionError(f"sensitive field filter should be rejected: {sensitive_filter_status} {sensitive_filter}")
        status, forbidden = request_json(
            "POST",
            f"{base}/v1/business-access/check",
            token=token,
            body={
                "role": "courier",
                "entity": "order_fulfillment",
                "fields": ["delivery_route.next_stop_label"],
                "purpose": "delivery_next_stop",
                "relationship": "assigned_delivery_leg",
                "scope": {"tenant_id": "commerce_tenant"},
            },
        )
        role_spoof_status = status
        if role_spoof_status != 403:
            raise AssertionError(f"role spoofing should be forbidden: {role_spoof_status} {forbidden}")
        status, preview_role_spoof = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=token,
            body={
                "role": "courier",
                "entity": "order_fulfillment",
                "fields": ["order_fulfillment.status"],
                "purpose": "delivery_next_stop",
                "relationship": "assigned_delivery_leg",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1"},
            },
        )
        preview_role_spoof_status = status
        if preview_role_spoof_status != 403:
            raise AssertionError(f"read-preview role spoofing should be forbidden: {preview_role_spoof_status} {preview_role_spoof}")
        report = {
            "schema": "business_access_api_smoke/v1",
            "status": "ok",
            "business_identity_count": (identities.get("result") or {}).get("count"),
            "merchant_public_decision": (allowed.get("result") or {}).get("decision"),
            "merchant_address_decision": (denied.get("result") or {}).get("decision"),
            "merchant_read_preview_count": preview_result.get("count"),
            "merchant_filter_conflict_status": filter_conflict_status,
            "merchant_tenant_filter_conflict_status": tenant_filter_conflict_status,
            "merchant_read_preview_denied_status": preview_denied_status,
            "support_masked_preview_decision": (masked.get("result") or {}).get("decision"),
            "sensitive_filter_status": sensitive_filter_status,
            "role_spoof_status": role_spoof_status,
            "read_preview_role_spoof_status": preview_role_spoof_status,
        }
        text = json.dumps(report, ensure_ascii=False, indent=2)
        (out_dir / "business_access_api_smoke.json").write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
