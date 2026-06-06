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
        "INSERT OR IGNORE INTO callers(caller,tenant_id,created_at_utc,source,last_seen_job_id) VALUES('buyer_caller','commerce_tenant','2026-06-01T00:00:00Z','smoke',NULL);"
        "INSERT OR IGNORE INTO callers(caller,tenant_id,created_at_utc,source,last_seen_job_id) VALUES('fraud_caller','commerce_tenant','2026-06-01T00:00:00Z','smoke',NULL);"
        "INSERT OR IGNORE INTO callers(caller,tenant_id,created_at_utc,source,last_seen_job_id) VALUES('marketer_caller','commerce_tenant','2026-06-01T00:00:00Z','smoke',NULL);"
        "INSERT OR IGNORE INTO callers(caller,tenant_id,created_at_utc,source,last_seen_job_id) VALUES('admin_caller','commerce_tenant','2026-06-01T00:00:00Z','smoke',NULL);"
        "INSERT OR IGNORE INTO callers(caller,tenant_id,created_at_utc,source,last_seen_job_id) VALUES('support_caller','commerce_tenant','2026-06-01T00:00:00Z','smoke',NULL);"
        "INSERT OR IGNORE INTO caller_identities(caller,issuer,subject,subject_type,service_id,display_name,platform_roles_json,enabled,metadata_json,source,created_at_utc) VALUES('merchant_caller','local','user:merchant','user',NULL,'Merchant','[\"query_submitter\"]',1,'{\"business_role\":\"merchant_staff\"}','smoke','2026-06-01T00:00:00Z');"
        "INSERT OR IGNORE INTO caller_identities(caller,issuer,subject,subject_type,service_id,display_name,platform_roles_json,enabled,metadata_json,source,created_at_utc) VALUES('buyer_caller','local','user:buyer','user',NULL,'Buyer','[\"query_submitter\"]',1,'{\"business_role\":\"buyer\"}','smoke','2026-06-01T00:00:00Z');"
        "INSERT OR IGNORE INTO caller_identities(caller,issuer,subject,subject_type,service_id,display_name,platform_roles_json,enabled,metadata_json,source,created_at_utc) VALUES('fraud_caller','local','user:fraud','user',NULL,'Fraud','[\"fraud_analyst\"]',1,'{\"business_role\":\"fraud_analyst\"}','smoke','2026-06-01T00:00:00Z');"
        "INSERT OR IGNORE INTO caller_identities(caller,issuer,subject,subject_type,service_id,display_name,platform_roles_json,enabled,metadata_json,source,created_at_utc) VALUES('marketer_caller','local','user:marketer','user',NULL,'Marketer','[\"campaign_analyst\"]',1,'{\"business_role\":\"field_marketer\"}','smoke','2026-06-01T00:00:00Z');"
        "INSERT OR IGNORE INTO caller_identities(caller,issuer,subject,subject_type,service_id,display_name,platform_roles_json,enabled,metadata_json,source,created_at_utc) VALUES('admin_caller','local','user:admin','user',NULL,'Admin','[\"platform_admin\"]',1,'{}','smoke','2026-06-01T00:00:00Z');"
        "INSERT OR IGNORE INTO caller_identities(caller,issuer,subject,subject_type,service_id,display_name,platform_roles_json,enabled,metadata_json,source,created_at_utc) VALUES('support_caller','local','user:support','user',NULL,'Support','[\"query_submitter\"]',1,'{\"business_role\":\"customer_service_agent\"}','smoke','2026-06-01T00:00:00Z');"
        "INSERT OR IGNORE INTO business_identities(business_identity_id,tenant_id,dataset_id,identity_kind,caller_id,subject_external_id,display_label,enabled,created_at_utc,updated_at_utc,metadata_json) VALUES('merchant-1','commerce_tenant','orders_analytics','merchant_staff','merchant_caller','merchant-ext-1','Merchant',1,'2026-06-01T00:00:00Z','2026-06-01T00:00:00Z','{}');"
        "INSERT OR IGNORE INTO business_identities(business_identity_id,tenant_id,dataset_id,identity_kind,caller_id,subject_external_id,display_label,enabled,created_at_utc,updated_at_utc,metadata_json) VALUES('buyer-1','commerce_tenant','orders_analytics','buyer','buyer_caller','buyer-ext-1','Buyer',1,'2026-06-01T00:00:00Z','2026-06-01T00:00:00Z','{}');"
        "INSERT OR IGNORE INTO business_identities(business_identity_id,tenant_id,dataset_id,identity_kind,caller_id,subject_external_id,display_label,enabled,created_at_utc,updated_at_utc,metadata_json) VALUES('fraud-1','commerce_tenant','orders_analytics','fraud_analyst','fraud_caller','fraud-ext-1','Fraud',1,'2026-06-01T00:00:00Z','2026-06-01T00:00:00Z','{}');"
        "INSERT OR IGNORE INTO business_identities(business_identity_id,tenant_id,dataset_id,identity_kind,caller_id,subject_external_id,display_label,enabled,created_at_utc,updated_at_utc,metadata_json) VALUES('marketer-1','commerce_tenant','orders_analytics','field_marketer','marketer_caller','marketer-ext-1','Marketer',1,'2026-06-01T00:00:00Z','2026-06-01T00:00:00Z','{}');"
        "INSERT OR IGNORE INTO business_identities(business_identity_id,tenant_id,dataset_id,identity_kind,caller_id,subject_external_id,display_label,enabled,created_at_utc,updated_at_utc,metadata_json) VALUES('support-1','commerce_tenant','orders_analytics','customer_service_agent','support_caller','support-ext-1','Support',1,'2026-06-01T00:00:00Z','2026-06-01T00:00:00Z','{}');"
        "INSERT OR IGNORE INTO callers(caller,tenant_id,created_at_utc,source,last_seen_job_id) VALUES('courier_caller','commerce_tenant','2026-06-01T00:00:00Z','smoke',NULL);"
        "INSERT OR IGNORE INTO callers(caller,tenant_id,created_at_utc,source,last_seen_job_id) VALUES('station_caller','commerce_tenant','2026-06-01T00:00:00Z','smoke',NULL);"
        "INSERT OR IGNORE INTO callers(caller,tenant_id,created_at_utc,source,last_seen_job_id) VALUES('last_mile_caller','commerce_tenant','2026-06-01T00:00:00Z','smoke',NULL);"
        "INSERT OR IGNORE INTO caller_identities(caller,issuer,subject,subject_type,service_id,display_name,platform_roles_json,enabled,metadata_json,source,created_at_utc) VALUES('courier_caller','local','user:courier','user',NULL,'Courier','[\"query_submitter\"]',1,'{\"business_role\":\"courier\"}','smoke','2026-06-01T00:00:00Z');"
        "INSERT OR IGNORE INTO caller_identities(caller,issuer,subject,subject_type,service_id,display_name,platform_roles_json,enabled,metadata_json,source,created_at_utc) VALUES('station_caller','local','user:station','user',NULL,'Station','[\"query_submitter\"]',1,'{\"business_role\":\"station_operator\"}','smoke','2026-06-01T00:00:00Z');"
        "INSERT OR IGNORE INTO caller_identities(caller,issuer,subject,subject_type,service_id,display_name,platform_roles_json,enabled,metadata_json,source,created_at_utc) VALUES('last_mile_caller','local','user:last-mile','user',NULL,'Last Mile','[\"query_submitter\"]',1,'{\"business_role\":\"last_mile_courier\"}','smoke','2026-06-01T00:00:00Z');"
        "INSERT OR IGNORE INTO business_identities(business_identity_id,tenant_id,dataset_id,identity_kind,caller_id,subject_external_id,display_label,enabled,created_at_utc,updated_at_utc,metadata_json) VALUES('courier-1','commerce_tenant','orders_analytics','courier','courier_caller','courier-ext-1','Courier',1,'2026-06-01T00:00:00Z','2026-06-01T00:00:00Z','{}');"
        "INSERT OR IGNORE INTO business_identities(business_identity_id,tenant_id,dataset_id,identity_kind,caller_id,subject_external_id,display_label,enabled,created_at_utc,updated_at_utc,metadata_json) VALUES('station-1','commerce_tenant','orders_analytics','station_operator','station_caller','station-ext-1','Station',1,'2026-06-01T00:00:00Z','2026-06-01T00:00:00Z','{}');"
        "INSERT OR IGNORE INTO business_identities(business_identity_id,tenant_id,dataset_id,identity_kind,caller_id,subject_external_id,display_label,enabled,created_at_utc,updated_at_utc,metadata_json) VALUES('last-mile-1','commerce_tenant','orders_analytics','last_mile_courier','last_mile_caller','last-mile-ext-1','Last Mile',1,'2026-06-01T00:00:00Z','2026-06-01T00:00:00Z','{}');"
        "INSERT OR IGNORE INTO orders(order_id,tenant_id,dataset_id,service_id,buyer_email,merchant_business_identity_id,buyer_business_identity_id,platform_id,campaign_id,currency,total_amount_cents,placed_at_utc,status,created_at_utc,ingested_at_utc) VALUES('o-1','commerce_tenant','orders_analytics','svc-commerce','buyer@example.com','merchant-1','buyer-1','shopify','campaign-demo','USD',12345,'2026-06-01T01:00:00Z','paid','2026-06-01T01:00:00Z','2026-06-01T01:01:00Z');"
        "INSERT OR IGNORE INTO order_attribution(order_id,tenant_id,dataset_id,assigned_marketer_business_identity_id,attribution_type,channel,campaign_id,creative_id,attribution_weight,created_at_utc,ingested_at_utc) VALUES('o-1','commerce_tenant','orders_analytics','marketer-1','last_touch','field','campaign-demo','creative-demo',0.75,'2026-06-01T01:00:00Z','2026-06-01T01:01:00Z');"
        "INSERT OR IGNORE INTO order_payment(order_id,tenant_id,dataset_id,assigned_fraud_analyst_business_identity_id,fraud_case_id,payment_method,provider_id,paid_amount_cents,paid_at_utc,risk_score,is_disputed,created_at_utc,ingested_at_utc) VALUES('o-1','commerce_tenant','orders_analytics','fraud-1','fraud-1','card','provider-risk',12345,'2026-06-01T01:00:30Z',0.87,0,'2026-06-01T01:00:00Z','2026-06-01T01:01:00Z');"
        "INSERT OR IGNORE INTO delivery_route_legs(leg_id,route_id,order_id,tenant_id,dataset_id,service_id,leg_sequence,leg_kind,assigned_courier_id,assigned_station_id,assigned_region_id,origin_node_label,destination_node_label,destination_city,destination_district,next_stop_label,next_stop_window,next_stop_geohash_prefix,pickup_station_label,pickup_station_geohash_prefix,final_recipient_zone,final_address_token,final_address_line1,recipient_phone,status,started_at_utc,created_at_utc,ingested_at_utc) VALUES('leg-1','route-1','o-1','commerce_tenant','orders_analytics','svc-commerce',1,'pickup_to_hub','courier-1','station-1','region-tj','Beijing Community Station','Tianjin South Hub','Tianjin',NULL,'Tianjin South Hub','2026-06-01T09:00:00Z/2026-06-01T11:00:00Z','wx4g','Beijing Community Station','wx4e','beijing-chaoyang','addr-token-1',NULL,NULL,'in_transit','2026-06-01T08:00:00Z','2026-06-01T08:00:00Z','2026-06-01T08:05:00Z');"
        "INSERT OR IGNORE INTO delivery_route_legs(leg_id,route_id,order_id,tenant_id,dataset_id,service_id,leg_sequence,leg_kind,assigned_courier_id,assigned_station_id,assigned_region_id,origin_node_label,destination_node_label,destination_city,destination_district,next_stop_label,next_stop_window,next_stop_geohash_prefix,pickup_station_label,pickup_station_geohash_prefix,final_recipient_zone,final_address_token,final_address_line1,recipient_phone,status,started_at_utc,created_at_utc,ingested_at_utc) VALUES('leg-2','route-1','o-1','commerce_tenant','orders_analytics','svc-commerce',2,'hub_to_last_mile','courier-1','station-1','region-bj','Tianjin South Hub','Beijing Chaoyang Last-Mile Station','Beijing','Chaoyang','Beijing Chaoyang Last-Mile Station','2026-06-01T12:00:00Z/2026-06-01T14:00:00Z','wx4g','Chaoyang Station','wx4g','beijing-chaoyang','addr-token-1',NULL,NULL,'arrived_at_station','2026-06-01T11:30:00Z','2026-06-01T11:30:00Z','2026-06-01T11:35:00Z');"
        "INSERT OR IGNORE INTO delivery_route_legs(leg_id,route_id,order_id,tenant_id,dataset_id,service_id,leg_sequence,leg_kind,assigned_courier_id,assigned_station_id,assigned_region_id,origin_node_label,destination_node_label,destination_city,destination_district,next_stop_label,next_stop_window,next_stop_geohash_prefix,pickup_station_label,pickup_station_geohash_prefix,final_recipient_zone,final_address_token,final_address_line1,recipient_phone,status,started_at_utc,created_at_utc,ingested_at_utc) VALUES('leg-3','route-1','o-1','commerce_tenant','orders_analytics','svc-commerce',3,'last_mile','last-mile-1','station-1','region-bj','Beijing Chaoyang Last-Mile Station','Beijing Chaoyang Block 7','Beijing','Chaoyang','Building 7 Pickup Locker','2026-06-01T15:00:00Z/2026-06-01T17:00:00Z','wx4g','Chaoyang Station','wx4g','beijing-chaoyang','addr-token-1','Beijing Chaoyang Block 7','13800001234','out_for_delivery','2026-06-01T14:30:00Z','2026-06-01T14:30:00Z','2026-06-01T14:35:00Z');"
        "INSERT OR IGNORE INTO customer_service_interactions(order_id,tenant_id,dataset_id,case_id,interaction_type,channel,agent_id,opened_at_utc,closed_at_utc,resolution_status,created_at_utc,ingested_at_utc) VALUES('o-1','commerce_tenant','orders_analytics','case-1','delivery_issue','chat','support-1','2026-06-01T01:05:00Z',NULL,'open','2026-06-01T01:05:00Z','2026-06-01T01:06:00Z');"
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
    if db_path.exists():
        db_path.unlink()
    init_db(db_path)

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    token_env = "BUSINESS_ACCESS_API_SMOKE_TOKEN"
    token = "example-business-access-smoke-token"
    buyer_token_env = "BUSINESS_ACCESS_API_SMOKE_BUYER_TOKEN"
    buyer_token = "example-business-access-smoke-buyer-token"
    support_token_env = "BUSINESS_ACCESS_API_SMOKE_SUPPORT_TOKEN"
    support_token = "example-business-access-smoke-support-token"
    fraud_token_env = "BUSINESS_ACCESS_API_SMOKE_FRAUD_TOKEN"
    fraud_token = "example-business-access-smoke-fraud-token"
    marketer_token_env = "BUSINESS_ACCESS_API_SMOKE_MARKETER_TOKEN"
    marketer_token = "example-business-access-smoke-marketer-token"
    courier_token_env = "BUSINESS_ACCESS_API_SMOKE_COURIER_TOKEN"
    courier_token = "example-business-access-smoke-courier-token"
    station_token_env = "BUSINESS_ACCESS_API_SMOKE_STATION_TOKEN"
    station_token = "example-business-access-smoke-station-token"
    last_mile_token_env = "BUSINESS_ACCESS_API_SMOKE_LAST_MILE_TOKEN"
    last_mile_token = "example-business-access-smoke-last-mile-token"
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
                        "token_env": buyer_token_env,
                        "issuer": "local",
                        "subject": "user:buyer",
                    },
                    {
                        "token_env": support_token_env,
                        "issuer": "local",
                        "subject": "user:support",
                    },
                    {
                        "token_env": fraud_token_env,
                        "issuer": "local",
                        "subject": "user:fraud",
                    },
                    {
                        "token_env": marketer_token_env,
                        "issuer": "local",
                        "subject": "user:marketer",
                    },
                    {
                        "token_env": courier_token_env,
                        "issuer": "local",
                        "subject": "user:courier",
                    },
                    {
                        "token_env": station_token_env,
                        "issuer": "local",
                        "subject": "user:station",
                    },
                    {
                        "token_env": last_mile_token_env,
                        "issuer": "local",
                        "subject": "user:last-mile",
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
    env[buyer_token_env] = buyer_token
    env[support_token_env] = support_token
    env[fraud_token_env] = fraud_token
    env[marketer_token_env] = marketer_token
    env[courier_token_env] = courier_token
    env[station_token_env] = station_token
    env[last_mile_token_env] = last_mile_token
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
        status, business_identity_spoof = request_json(
            "GET",
            f"{base}/v1/entities/business-identities?caller=fraud_caller",
            token=token,
        )
        business_identity_spoof_status = status
        if business_identity_spoof_status != 403 or "caller-scoped metadata access denied" not in str(business_identity_spoof.get("error") or ""):
            raise AssertionError(
                f"business-identities caller spoof should be rejected: "
                f"{business_identity_spoof_status} {business_identity_spoof}"
            )
        status, business_identity_tenant_spoof = request_json(
            "GET",
            f"{base}/v1/entities/business-identities?caller=merchant_caller&tenant_id=other_tenant",
            token=token,
        )
        business_identity_tenant_spoof_status = status
        if business_identity_tenant_spoof_status != 403 or "caller-scoped metadata access denied" not in str(business_identity_tenant_spoof.get("error") or ""):
            raise AssertionError(
                f"business-identities cross-tenant spoof should be rejected: "
                f"{business_identity_tenant_spoof_status} {business_identity_tenant_spoof}"
            )
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
        if ((allowed.get("result") or {}).get("relationship_binding") or {}).get("bound_identity_id") != "merchant-1":
            raise AssertionError(f"merchant relationship binding failed: {status} {allowed}")
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
        (out_dir / "merchant_address_deny_check.json").write_text(
            json.dumps(denied.get("result") or {}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        status, merchant_contact_denied = request_json(
            "POST",
            f"{base}/v1/business-access/check",
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
        if status != 200 or (merchant_contact_denied.get("result") or {}).get("decision") != "deny":
            raise AssertionError(f"merchant contact deny check failed: {status} {merchant_contact_denied}")
        (out_dir / "merchant_contact_deny_check.json").write_text(
            json.dumps(merchant_contact_denied.get("result") or {}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
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
        status, merchant_scope_spoof = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=token,
            body={
                "role": "merchant_staff",
                "entity": "orders",
                "fields": ["orders.order_id"],
                "purpose": "merchant_order_ops",
                "relationship": "merchant_of_order",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1", "merchant_business_identity_id": "merchant-2"},
            },
        )
        merchant_scope_spoof_status = status
        if merchant_scope_spoof_status != 403:
            raise AssertionError(f"merchant relationship spoof should be forbidden: {merchant_scope_spoof_status} {merchant_scope_spoof}")
        status, masked = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=support_token,
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
        support_binding = (masked.get("result") or {}).get("relationship_binding") or {}
        if support_binding.get("status") != "ok":
            raise AssertionError(f"support relationship binding failed: {status} {masked}")
        (out_dir / "business_read_preview_masked.json").write_text(
            json.dumps(masked.get("result") or {}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (out_dir / "support_masked_check.json").write_text(
            json.dumps(masked.get("result") or {}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        status, support_scope_spoof = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=support_token,
            body={
                "role": "customer_service_agent",
                "entity": "orders",
                "fields": ["orders.order_id", "orders.buyer_email"],
                "purpose": "support_case",
                "relationship": "assigned_support_case",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1", "case_id": "case-2"},
            },
        )
        support_scope_spoof_status = status
        if support_scope_spoof_status != 403:
            raise AssertionError(f"support relationship spoof should be forbidden: {support_scope_spoof_status} {support_scope_spoof}")
        status, sensitive_filter = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=support_token,
            body={
                "role": "customer_service_agent",
                "entity": "orders",
                "fields": ["orders.order_id"],
                "purpose": "support_case",
                "relationship": "assigned_support_case",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1", "case_id": "case-1"},
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
        status, courier_scope_spoof = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=courier_token,
            body={
                "role": "courier",
                "entity": "delivery_route_legs",
                "fields": ["delivery_route.next_stop_label"],
                "purpose": "delivery_next_stop",
                "relationship": "assigned_delivery_leg",
                "scope": {"tenant_id": "commerce_tenant", "leg_id": "leg-1", "assigned_courier_id": "courier-2"},
            },
        )
        courier_scope_spoof_status = status
        if courier_scope_spoof_status != 403:
            raise AssertionError(f"courier relationship spoof should be forbidden: {courier_scope_spoof_status} {courier_scope_spoof}")
        status, courier_leg = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=courier_token,
            body={
                "role": "courier",
                "entity": "delivery_route_legs",
                "fields": [
                    "delivery_route.leg_id",
                    "delivery_route.next_stop_label",
                    "delivery_route.leg_sequence",
                ],
                "purpose": "delivery_next_stop",
                "relationship": "assigned_delivery_leg",
                "scope": {"tenant_id": "commerce_tenant", "leg_id": "leg-1", "assigned_courier_id": "courier-1"},
            },
        )
        courier_leg_result = courier_leg.get("result") or {}
        courier_rows = courier_leg_result.get("rows") or []
        if status != 200 or courier_leg_result.get("decision") != "allow" or not courier_rows or courier_rows[0].get("delivery_route.next_stop_label") != "Tianjin South Hub":
            raise AssertionError(f"courier next-stop preview failed: {status} {courier_leg}")
        if (courier_leg_result.get("relationship_binding") or {}).get("bound_identity_id") != "courier-1":
            raise AssertionError(f"courier relationship binding failed: {status} {courier_leg}")
        (out_dir / "courier_leg_preview.json").write_text(
            json.dumps(courier_leg_result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        status, courier_final_denied = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=courier_token,
            body={
                "role": "courier",
                "entity": "delivery_route_legs",
                "fields": ["delivery_route.final_address_line1"],
                "purpose": "delivery_next_stop",
                "relationship": "assigned_delivery_leg",
                "scope": {"tenant_id": "commerce_tenant", "leg_id": "leg-1", "assigned_courier_id": "courier-1"},
            },
        )
        courier_final_denied_status = status
        if courier_final_denied_status != 403:
            raise AssertionError(f"courier final address should be denied on upstream leg: {courier_final_denied_status} {courier_final_denied}")
        status, station_handoff = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=station_token,
            body={
                "role": "station_operator",
                "entity": "delivery_route_legs",
                "fields": [
                    "delivery_route.pickup_station_label",
                    "delivery_route.assigned_station_id",
                ],
                "purpose": "station_handoff",
                "relationship": "assigned_station_leg",
                "scope": {"tenant_id": "commerce_tenant", "leg_id": "leg-2", "assigned_station_id": "station-1"},
            },
        )
        station_handoff_result = station_handoff.get("result") or {}
        station_rows = station_handoff_result.get("rows") or []
        if status != 200 or station_handoff_result.get("decision") != "allow" or not station_rows or station_rows[0].get("delivery_route.pickup_station_label") != "Chaoyang Station":
            raise AssertionError(f"station handoff preview failed: {status} {station_handoff}")
        if (station_handoff_result.get("relationship_binding") or {}).get("bound_identity_id") != "station-1":
            raise AssertionError(f"station relationship binding failed: {status} {station_handoff}")
        (out_dir / "station_leg_preview.json").write_text(
            json.dumps(station_handoff_result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        status, station_final_denied = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=station_token,
            body={
                "role": "station_operator",
                "entity": "delivery_route_legs",
                "fields": ["delivery_route.final_address_line1"],
                "purpose": "station_handoff",
                "relationship": "assigned_station_leg",
                "scope": {"tenant_id": "commerce_tenant", "leg_id": "leg-2", "assigned_station_id": "station-1"},
            },
        )
        station_final_denied_status = status
        if station_final_denied_status != 403:
            raise AssertionError(f"station final address should be denied: {station_final_denied_status} {station_final_denied}")
        status, last_mile_allowed = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=last_mile_token,
            body={
                "role": "last_mile_courier",
                "entity": "delivery_route_legs",
                "fields": [
                    "delivery_route.final_address_line1",
                    "delivery_route.recipient_phone",
                ],
                "purpose": "last_mile_delivery",
                "relationship": "assigned_last_mile_leg",
                "scope": {"tenant_id": "commerce_tenant", "leg_id": "leg-3", "assigned_courier_id": "last-mile-1"},
            },
        )
        last_mile_result = last_mile_allowed.get("result") or {}
        last_mile_rows = last_mile_result.get("rows") or []
        if (
            status != 200
            or last_mile_result.get("decision") != "mask"
            or not last_mile_rows
            or last_mile_rows[0].get("delivery_route.final_address_line1") != "Beijing Chaoyang Block 7"
            or last_mile_rows[0].get("delivery_route.recipient_phone", {}).get("masked") is not True
        ):
            raise AssertionError(f"last-mile courier preview failed: {status} {last_mile_allowed}")
        if (last_mile_result.get("relationship_binding") or {}).get("bound_identity_id") != "last-mile-1":
            raise AssertionError(f"last-mile relationship binding failed: {status} {last_mile_allowed}")
        (out_dir / "last_mile_leg_preview.json").write_text(
            json.dumps(last_mile_result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        status, buyer_self = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=buyer_token,
            body={
                "role": "buyer",
                "entity": "orders",
                "fields": ["orders.order_id", "orders.status"],
                "purpose": "self_service",
                "relationship": "self",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1", "buyer_id": "buyer-1"},
            },
        )
        buyer_self_result = buyer_self.get("result") or {}
        if status != 200 or buyer_self_result.get("decision") != "allow":
            raise AssertionError(f"buyer self preview failed: {status} {buyer_self}")
        status, buyer_scope_spoof = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=buyer_token,
            body={
                "role": "buyer",
                "entity": "orders",
                "fields": ["orders.order_id"],
                "purpose": "self_service",
                "relationship": "self",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1", "buyer_id": "buyer-2"},
            },
        )
        buyer_scope_spoof_status = status
        if buyer_scope_spoof_status != 403:
            raise AssertionError(f"buyer relationship spoof should be forbidden: {buyer_scope_spoof_status} {buyer_scope_spoof}")
        status, fraud_allowed = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=fraud_token,
            body={
                "role": "fraud_analyst",
                "entity": "order_payment",
                "fields": ["order_payment.payment_method", "order_payment.risk_score", "order_payment.is_disputed"],
                "purpose": "fraud_review",
                "relationship": "fraud_review_queue",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1", "case_id": "fraud-1"},
                "limit": 5,
            },
        )
        fraud_allowed_result = fraud_allowed.get("result") or {}
        fraud_rows = fraud_allowed_result.get("rows") or []
        if (
            status != 200
            or fraud_allowed_result.get("decision") != "allow"
            or not fraud_rows
            or fraud_rows[0].get("order_payment.risk_score") != 0.87
        ):
            raise AssertionError(f"fraud analyst payment preview failed: {status} {fraud_allowed}")
        if (fraud_allowed_result.get("relationship_binding") or {}).get("bound_case_id") != "fraud-1":
            raise AssertionError(f"fraud relationship binding failed: {status} {fraud_allowed}")
        (out_dir / "fraud_payment_preview.json").write_text(
            json.dumps(fraud_allowed_result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        status, fraud_scope_spoof = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=fraud_token,
            body={
                "role": "fraud_analyst",
                "entity": "order_payment",
                "fields": ["order_payment.risk_score"],
                "purpose": "fraud_review",
                "relationship": "fraud_review_queue",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1", "case_id": "fraud-2"},
            },
        )
        fraud_scope_spoof_status = status
        if fraud_scope_spoof_status != 403:
            raise AssertionError(f"fraud relationship spoof should be forbidden: {fraud_scope_spoof_status} {fraud_scope_spoof}")
        status, fraud_contact_denied = request_json(
            "POST",
            f"{base}/v1/business-access/check",
            token=fraud_token,
            body={
                "role": "fraud_analyst",
                "entity": "orders",
                "fields": ["orders.buyer_email"],
                "purpose": "fraud_review",
                "relationship": "fraud_review_queue",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1", "case_id": "fraud-1"},
            },
        )
        if status != 200 or (fraud_contact_denied.get("result") or {}).get("decision") != "deny":
            raise AssertionError(f"fraud analyst contact deny failed: {status} {fraud_contact_denied}")
        (out_dir / "fraud_contact_deny_check.json").write_text(
            json.dumps(fraud_contact_denied.get("result") or {}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        status, marketer_allowed = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=marketer_token,
            body={
                "role": "field_marketer",
                "entity": "order_attribution",
                "fields": [
                    "order_attribution.channel",
                    "order_attribution.campaign_id",
                    "order_attribution.attribution_weight",
                ],
                "purpose": "campaign_analysis",
                "relationship": "campaign_assignee",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1", "campaign_id": "campaign-demo"},
                "limit": 5,
            },
        )
        marketer_allowed_result = marketer_allowed.get("result") or {}
        marketer_rows = marketer_allowed_result.get("rows") or []
        if (
            status != 200
            or marketer_allowed_result.get("decision") != "allow"
            or not marketer_rows
            or marketer_rows[0].get("order_attribution.campaign_id") != "campaign-demo"
        ):
            raise AssertionError(f"field marketer attribution preview failed: {status} {marketer_allowed}")
        if (marketer_allowed_result.get("relationship_binding") or {}).get("bound_campaign_id") != "campaign-demo":
            raise AssertionError(f"field marketer relationship binding failed: {status} {marketer_allowed}")
        (out_dir / "field_marketer_attribution_preview.json").write_text(
            json.dumps(marketer_allowed_result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        status, marketer_scope_spoof = request_json(
            "POST",
            f"{base}/v1/business-data/read-preview",
            token=marketer_token,
            body={
                "role": "field_marketer",
                "entity": "order_attribution",
                "fields": ["order_attribution.campaign_id"],
                "purpose": "campaign_analysis",
                "relationship": "campaign_assignee",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1", "campaign_id": "campaign-other"},
            },
        )
        marketer_scope_spoof_status = status
        if marketer_scope_spoof_status != 403:
            raise AssertionError(f"marketer relationship spoof should be forbidden: {marketer_scope_spoof_status} {marketer_scope_spoof}")
        status, marketer_contact_denied = request_json(
            "POST",
            f"{base}/v1/business-access/check",
            token=marketer_token,
            body={
                "role": "field_marketer",
                "entity": "orders",
                "fields": ["orders.buyer_email"],
                "purpose": "campaign_analysis",
                "relationship": "campaign_assignee",
                "scope": {"tenant_id": "commerce_tenant", "order_id": "o-1", "campaign_id": "campaign-demo"},
            },
        )
        if status != 200 or (marketer_contact_denied.get("result") or {}).get("decision") != "deny":
            raise AssertionError(f"field marketer contact deny failed: {status} {marketer_contact_denied}")
        (out_dir / "field_marketer_contact_deny_check.json").write_text(
            json.dumps(marketer_contact_denied.get("result") or {}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        report = {
            "schema": "business_access_api_smoke/v1",
            "status": "ok",
            "business_identity_count": (identities.get("result") or {}).get("count"),
            "business_identity_spoof_status": business_identity_spoof_status,
            "business_identity_cross_tenant_status": business_identity_tenant_spoof_status,
            "merchant_public_decision": (allowed.get("result") or {}).get("decision"),
            "merchant_address_decision": (denied.get("result") or {}).get("decision"),
            "merchant_read_preview_count": preview_result.get("count"),
            "merchant_filter_conflict_status": filter_conflict_status,
            "merchant_tenant_filter_conflict_status": tenant_filter_conflict_status,
            "merchant_read_preview_denied_status": preview_denied_status,
            "merchant_relationship_spoof_status": merchant_scope_spoof_status,
            "support_masked_preview_decision": (masked.get("result") or {}).get("decision"),
            "support_relationship_binding_status": support_binding.get("status"),
            "support_relationship_spoof_status": support_scope_spoof_status,
            "sensitive_filter_status": sensitive_filter_status,
            "role_spoof_status": role_spoof_status,
            "read_preview_role_spoof_status": preview_role_spoof_status,
            "courier_leg_preview_decision": courier_leg_result.get("decision"),
            "courier_final_address_denied_status": courier_final_denied_status,
            "courier_relationship_spoof_status": courier_scope_spoof_status,
            "station_leg_preview_decision": station_handoff_result.get("decision"),
            "station_final_address_denied_status": station_final_denied_status,
            "last_mile_preview_decision": last_mile_result.get("decision"),
            "buyer_self_preview_decision": buyer_self_result.get("decision"),
            "buyer_relationship_spoof_status": buyer_scope_spoof_status,
            "fraud_payment_preview_decision": fraud_allowed_result.get("decision"),
            "fraud_relationship_spoof_status": fraud_scope_spoof_status,
            "fraud_contact_decision": (fraud_contact_denied.get("result") or {}).get("decision"),
            "field_marketer_attribution_preview_decision": marketer_allowed_result.get("decision"),
            "field_marketer_relationship_spoof_status": marketer_scope_spoof_status,
            "field_marketer_contact_decision": (marketer_contact_denied.get("result") or {}).get("decision"),
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
