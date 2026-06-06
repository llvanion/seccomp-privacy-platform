#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
IMPORTER = REPO_ROOT / "scripts" / "import_ecommerce_fact_rows.py"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def run_importer(*, db_path: Path, input_path: Path, output_path: Path, allow_reject: bool = False) -> dict:
    cmd = [
        sys.executable,
        str(IMPORTER),
        "--table",
        "orders",
        "--input",
        str(input_path),
        "--metadata-db",
        str(db_path),
        "--output",
        str(output_path),
    ]
    if allow_reject:
        cmd.append("--allow-reject")
    subprocess.run(cmd, cwd=str(REPO_ROOT), check=True, stdout=subprocess.DEVNULL)
    return json.loads(output_path.read_text(encoding="utf-8"))


def run_importer_for_table(*, table: str, db_path: Path, input_path: Path, output_path: Path, allow_reject: bool = False) -> dict:
    cmd = [
        sys.executable,
        str(IMPORTER),
        "--table",
        table,
        "--input",
        str(input_path),
        "--metadata-db",
        str(db_path),
        "--output",
        str(output_path),
    ]
    if allow_reject:
        cmd.append("--allow-reject")
    subprocess.run(cmd, cwd=str(REPO_ROOT), check=True, stdout=subprocess.DEVNULL)
    return json.loads(output_path.read_text(encoding="utf-8"))


def count_orders(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM orders").fetchone()
        return int(row[0] if row else 0)


def count_delivery_legs(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM delivery_route_legs").fetchone()
        return int(row[0] if row else 0)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def order_row(order_id: str, *, amount: int = 12345) -> dict:
    return {
        "order_id": order_id,
        "tenant_id": "commerce_tenant",
        "dataset_id": "orders_analytics",
        "service_id": "svc-commerce",
        "buyer_email": "buyer@example.com",
        "merchant_business_identity_id": "merchant-1",
        "buyer_business_identity_id": "buyer-1",
        "platform_id": "shopify",
        "campaign_id": "campaign-demo",
        "currency": "USD",
        "total_amount_cents": amount,
        "placed_at_utc": "2026-06-01T01:00:00Z",
        "status": "paid",
        "created_at_utc": "2026-06-01T01:00:00Z",
        "ingested_at_utc": "2026-06-01T01:01:00Z",
    }


def leg_row(leg_id: str, *, leg_sequence: int, leg_kind: str, next_stop_label: str, final_address_line1: str | None = None, recipient_phone: str | None = None) -> dict:
    row = {
        "leg_id": leg_id,
        "route_id": "route-1",
        "order_id": "o-1",
        "tenant_id": "commerce_tenant",
        "dataset_id": "orders_analytics",
        "service_id": "svc-commerce",
        "leg_sequence": leg_sequence,
        "leg_kind": leg_kind,
        "assigned_courier_id": f"courier-{leg_sequence}",
        "assigned_station_id": f"station-{leg_sequence}",
        "assigned_region_id": "region-bj",
        "origin_node_label": "origin-node",
        "destination_node_label": f"dest-node-{leg_sequence}",
        "destination_city": "Beijing" if leg_kind == "last_mile" else "Tianjin",
        "destination_district": "Chaoyang" if leg_kind == "last_mile" else None,
        "next_stop_label": next_stop_label,
        "next_stop_window": "2026-06-01T09:00:00Z/2026-06-01T11:00:00Z",
        "next_stop_geohash_prefix": "wx4g",
        "pickup_station_label": "Station A" if leg_kind == "pickup_to_hub" else None,
        "pickup_station_geohash_prefix": "wx4e" if leg_kind == "pickup_to_hub" else None,
        "final_recipient_zone": "beijing-chaoyang",
        "status": "in_transit",
        "started_at_utc": "2026-06-01T08:00:00Z",
        "completed_at_utc": None,
        "created_at_utc": "2026-06-01T08:00:00Z",
        "ingested_at_utc": "2026-06-01T08:05:00Z",
    }
    if final_address_line1 is not None:
        row["final_address_line1"] = final_address_line1
    if recipient_phone is not None:
        row["recipient_phone"] = recipient_phone
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-test transactional e-commerce fact imports.")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "metadata.db"
    if db_path.exists():
        db_path.unlink()

    allow_input = out_dir / "orders_allow.jsonl"
    write_jsonl(allow_input, [order_row("o-1")])
    allow = run_importer(
        db_path=db_path,
        input_path=allow_input,
        output_path=out_dir / "orders_allow_import.json",
    )
    require(allow.get("decision") == "allow", f"expected allow import: {allow}")
    require(allow.get("transaction") == "committed", f"expected committed import: {allow}")
    require(allow.get("inserted_row_count") == 1, f"expected one inserted row: {allow}")
    require(count_orders(db_path) == 1, "expected one order after allow import")

    sensitive_input = out_dir / "orders_sensitive_reject.jsonl"
    write_jsonl(sensitive_input, [{**order_row("o-2"), "delivery_address": "1 Secret Street"}])
    sensitive = run_importer(
        db_path=db_path,
        input_path=sensitive_input,
        output_path=out_dir / "orders_sensitive_reject_import.json",
        allow_reject=True,
    )
    require(sensitive.get("decision") == "deny", f"expected sensitive import deny: {sensitive}")
    require(sensitive.get("transaction") == "rejected_before_insert", f"expected pre-insert rejection: {sensitive}")
    require(count_orders(db_path) == 1, "sensitive reject changed row count")

    duplicate_input = out_dir / "orders_duplicate_rollback.jsonl"
    write_jsonl(duplicate_input, [order_row("o-1"), order_row("o-3", amount=6789)])
    duplicate = run_importer(
        db_path=db_path,
        input_path=duplicate_input,
        output_path=out_dir / "orders_duplicate_rollback_import.json",
        allow_reject=True,
    )
    require(duplicate.get("decision") == "deny", f"expected duplicate import deny: {duplicate}")
    require(duplicate.get("transaction") == "rolled_back", f"expected rollback: {duplicate}")
    require(duplicate.get("inserted_row_count") == 0, f"rollback should not claim inserted rows: {duplicate}")
    require(count_orders(db_path) == 1, "duplicate rollback changed row count")

    legs_allow_input = out_dir / "delivery_legs_allow.jsonl"
    write_jsonl(
        legs_allow_input,
        [
            leg_row("leg-1", leg_sequence=1, leg_kind="pickup_to_hub", next_stop_label="Tianjin South Hub"),
            leg_row("leg-2", leg_sequence=2, leg_kind="hub_to_last_mile", next_stop_label="Beijing Chaoyang Last-Mile Station"),
            leg_row("leg-3", leg_sequence=3, leg_kind="last_mile", next_stop_label="Building 7 Pickup Locker"),
        ],
    )
    legs_allow = run_importer_for_table(
        table="delivery_route_legs",
        db_path=db_path,
        input_path=legs_allow_input,
        output_path=out_dir / "delivery_legs_allow_import.json",
    )
    require(legs_allow.get("decision") == "allow", f"expected delivery legs allow import: {legs_allow}")
    require(count_delivery_legs(db_path) == 3, "expected three delivery legs after allow import")

    legs_sensitive_input = out_dir / "delivery_legs_sensitive_reject.jsonl"
    write_jsonl(
        legs_sensitive_input,
        [leg_row("leg-4", leg_sequence=1, leg_kind="pickup_to_hub", next_stop_label="Hub", final_address_line1="secret address")],
    )
    legs_sensitive = run_importer_for_table(
        table="delivery_route_legs",
        db_path=db_path,
        input_path=legs_sensitive_input,
        output_path=out_dir / "delivery_legs_sensitive_reject_import.json",
        allow_reject=True,
    )
    require(legs_sensitive.get("decision") == "deny", f"expected sensitive leg import deny: {legs_sensitive}")
    require(count_delivery_legs(db_path) == 3, "sensitive leg reject changed row count")

    attribution_input = out_dir / "order_attribution_allow.jsonl"
    write_jsonl(
        attribution_input,
        [{
            "order_id": "o-1",
            "tenant_id": "commerce_tenant",
            "dataset_id": "orders_analytics",
            "assigned_marketer_business_identity_id": "marketer-1",
            "attribution_type": "last_touch",
            "channel": "field",
            "campaign_id": "campaign-demo",
            "creative_id": "creative-demo",
            "attribution_weight": 0.75,
            "created_at_utc": "2026-06-01T01:00:00Z",
            "ingested_at_utc": "2026-06-01T01:01:00Z",
        }],
    )
    attribution_allow = run_importer_for_table(
        table="order_attribution",
        db_path=db_path,
        input_path=attribution_input,
        output_path=out_dir / "order_attribution_allow_import.json",
    )
    require(attribution_allow.get("decision") == "allow", f"expected attribution allow import: {attribution_allow}")

    payment_input = out_dir / "order_payment_allow.jsonl"
    write_jsonl(
        payment_input,
        [{
            "order_id": "o-1",
            "tenant_id": "commerce_tenant",
            "dataset_id": "orders_analytics",
            "assigned_fraud_analyst_business_identity_id": "fraud-1",
            "fraud_case_id": "fraud-1",
            "payment_method": "card",
            "provider_id": "provider-risk",
            "paid_amount_cents": 12345,
            "paid_at_utc": "2026-06-01T01:00:30Z",
            "risk_score": 0.87,
            "is_disputed": 0,
            "created_at_utc": "2026-06-01T01:00:00Z",
            "ingested_at_utc": "2026-06-01T01:01:00Z",
        }],
    )
    payment_allow = run_importer_for_table(
        table="order_payment",
        db_path=db_path,
        input_path=payment_input,
        output_path=out_dir / "order_payment_allow_import.json",
    )
    require(payment_allow.get("decision") == "allow", f"expected payment allow import: {payment_allow}")

    support_input = out_dir / "customer_service_allow.jsonl"
    write_jsonl(
        support_input,
        [{
            "order_id": "o-1",
            "tenant_id": "commerce_tenant",
            "dataset_id": "orders_analytics",
            "case_id": "case-1",
            "interaction_type": "delivery_issue",
            "channel": "chat",
            "agent_id": "support-1",
            "resolution_status": "open",
            "created_at_utc": "2026-06-01T01:00:00Z",
            "ingested_at_utc": "2026-06-01T01:01:00Z",
        }],
    )
    support_allow = run_importer_for_table(
        table="customer_service_interactions",
        db_path=db_path,
        input_path=support_input,
        output_path=out_dir / "customer_service_allow_import.json",
    )
    require(support_allow.get("decision") == "allow", f"expected support allow import: {support_allow}")

    report = {
        "schema": "ecommerce_fact_import_smoke/v1",
        "status": "ok",
        "allow_decision": allow.get("decision"),
        "allow_transaction": allow.get("transaction"),
        "sensitive_decision": sensitive.get("decision"),
        "sensitive_transaction": sensitive.get("transaction"),
        "duplicate_decision": duplicate.get("decision"),
        "duplicate_transaction": duplicate.get("transaction"),
        "delivery_legs_allow_decision": legs_allow.get("decision"),
        "delivery_legs_sensitive_decision": legs_sensitive.get("decision"),
        "order_attribution_allow_decision": attribution_allow.get("decision"),
        "order_payment_allow_decision": payment_allow.get("decision"),
        "customer_service_allow_decision": support_allow.get("decision"),
        "final_delivery_leg_count": count_delivery_legs(db_path),
        "final_order_count": count_orders(db_path),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    (out_dir / "ecommerce_fact_import_smoke.json").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
