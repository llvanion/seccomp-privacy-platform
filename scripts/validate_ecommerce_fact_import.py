#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from check_business_access_policy import flatten_field_classes, load_json_object


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "ecommerce_fact_import_validation/v1"
DEFAULT_POLICY = REPO_ROOT / "config" / "business_access_policy.ecommerce.example.json"

TABLE_SPECS: dict[str, dict[str, Any]] = {
    "orders": {
        "required": {
            "order_id",
            "tenant_id",
            "dataset_id",
            "buyer_email",
            "merchant_business_identity_id",
            "buyer_business_identity_id",
            "currency",
            "total_amount_cents",
            "placed_at_utc",
            "status",
            "created_at_utc",
            "ingested_at_utc",
        },
        "optional": {"id", "service_id", "platform_id", "campaign_id"},
        "field_map": {
            "order_id": "orders.order_id",
            "platform_id": "orders.platform_id",
            "campaign_id": "orders.campaign_id",
            "currency": "orders.currency",
            "total_amount_cents": "orders.total_amount_cents",
            "placed_at_utc": "orders.placed_at_utc",
            "status": "orders.status",
            "buyer_email": "orders.buyer_email",
        },
    },
    "order_items": {
        "required": {
            "order_id",
            "tenant_id",
            "dataset_id",
            "sku_id",
            "quantity",
            "unit_price_cents",
            "line_total_cents",
            "created_at_utc",
            "ingested_at_utc",
        },
        "optional": {"id", "category_id"},
        "field_map": {
            "sku_id": "order_items.sku_id",
            "category_id": "order_items.category_id",
            "quantity": "order_items.quantity",
            "unit_price_cents": "order_items.unit_price_cents",
            "line_total_cents": "order_items.line_total_cents",
        },
    },
    "order_attribution": {
        "required": {
            "order_id",
            "tenant_id",
            "dataset_id",
            "assigned_marketer_business_identity_id",
            "attribution_type",
            "channel",
            "attribution_weight",
            "created_at_utc",
            "ingested_at_utc",
        },
        "optional": {"id", "campaign_id", "creative_id"},
        "field_map": {
            "attribution_type": "order_attribution.attribution_type",
            "channel": "order_attribution.channel",
            "campaign_id": "order_attribution.campaign_id",
            "creative_id": "order_attribution.creative_id",
            "attribution_weight": "order_attribution.attribution_weight",
        },
    },
    "order_payment": {
        "required": {
            "order_id",
            "tenant_id",
            "dataset_id",
            "assigned_fraud_analyst_business_identity_id",
            "fraud_case_id",
            "payment_method",
            "paid_amount_cents",
            "is_disputed",
            "created_at_utc",
            "ingested_at_utc",
        },
        "optional": {"id", "provider_id", "paid_at_utc", "risk_score"},
        "field_map": {
            "payment_method": "order_payment.payment_method",
            "provider_id": "order_payment.provider_id",
            "paid_amount_cents": "order_payment.paid_amount_cents",
            "paid_at_utc": "order_payment.paid_at_utc",
            "risk_score": "order_payment.risk_score",
            "is_disputed": "order_payment.is_disputed",
        },
    },
    "order_fulfillment": {
        "required": {
            "order_id",
            "tenant_id",
            "dataset_id",
            "status",
            "created_at_utc",
            "ingested_at_utc",
        },
        "optional": {"id", "carrier_id", "warehouse_id", "shipped_at_utc", "delivered_at_utc", "delivery_latency_minutes"},
        "field_map": {
            "carrier_id": "order_fulfillment.carrier_id",
            "warehouse_id": "order_fulfillment.warehouse_id",
            "shipped_at_utc": "order_fulfillment.shipped_at_utc",
            "delivered_at_utc": "order_fulfillment.delivered_at_utc",
            "status": "order_fulfillment.status",
            "delivery_latency_minutes": "order_fulfillment.delivery_latency_minutes",
        },
    },
    "delivery_route_legs": {
        "required": {
            "leg_id",
            "route_id",
            "order_id",
            "tenant_id",
            "dataset_id",
            "leg_sequence",
            "leg_kind",
            "origin_node_label",
            "destination_node_label",
            "destination_city",
            "next_stop_label",
            "status",
            "created_at_utc",
            "ingested_at_utc",
        },
        "optional": {
            "id",
            "service_id",
            "assigned_courier_id",
            "assigned_station_id",
            "assigned_region_id",
            "destination_district",
            "next_stop_window",
            "next_stop_geohash_prefix",
            "pickup_station_label",
            "pickup_station_geohash_prefix",
            "final_recipient_zone",
            "final_address_token",
            "final_address_line1",
            "final_address_line2",
            "recipient_phone",
            "started_at_utc",
            "completed_at_utc",
        },
        "field_map": {
            "leg_id": "delivery_route.leg_id",
            "route_id": "delivery_route.route_id",
            "leg_sequence": "delivery_route.leg_sequence",
            "leg_kind": "delivery_route.leg_kind",
            "assigned_courier_id": "delivery_route.assigned_courier_id",
            "assigned_station_id": "delivery_route.assigned_station_id",
            "assigned_region_id": "delivery_route.assigned_region_id",
            "origin_node_label": "delivery_route.origin_node_label",
            "destination_node_label": "delivery_route.destination_node_label",
            "destination_city": "delivery_route.destination_city",
            "destination_district": "delivery_route.destination_district",
            "next_stop_label": "delivery_route.next_stop_label",
            "next_stop_window": "delivery_route.next_stop_window",
            "next_stop_geohash_prefix": "delivery_route.next_stop_geohash_prefix",
            "pickup_station_label": "delivery_route.pickup_station_label",
            "pickup_station_geohash_prefix": "delivery_route.pickup_station_geohash_prefix",
            "final_recipient_zone": "delivery_route.final_recipient_zone",
            "final_address_token": "delivery_route.final_address_token",
            "final_address_line1": "delivery_route.final_address_line1",
            "final_address_line2": "delivery_route.final_address_line2",
            "recipient_phone": "delivery_route.recipient_phone",
            "status": "delivery_route.status",
            "started_at_utc": "delivery_route.started_at_utc",
            "completed_at_utc": "delivery_route.completed_at_utc",
        },
    },
    "customer_service_interactions": {
        "required": {
            "order_id",
            "tenant_id",
            "dataset_id",
            "case_id",
            "interaction_type",
            "channel",
            "agent_id",
            "resolution_status",
            "created_at_utc",
            "ingested_at_utc",
        },
        "optional": {"id", "opened_at_utc", "closed_at_utc"},
        "field_map": {
            "interaction_type": "customer_service_interactions.interaction_type",
            "channel": "customer_service_interactions.channel",
            "agent_id": "customer_service_interactions.agent_id",
            "opened_at_utc": "customer_service_interactions.opened_at_utc",
            "closed_at_utc": "customer_service_interactions.closed_at_utc",
            "resolution_status": "customer_service_interactions.resolution_status",
        },
    },
}

INTEGER_COLUMNS = {
    "id",
    "total_amount_cents",
    "quantity",
    "unit_price_cents",
    "line_total_cents",
    "paid_amount_cents",
    "is_disputed",
    "delivery_latency_minutes",
    "leg_sequence",
}
NUMBER_COLUMNS = {"attribution_weight", "risk_score"}
NON_NEGATIVE_COLUMNS = {
    "total_amount_cents",
    "quantity",
    "unit_price_cents",
    "line_total_cents",
    "paid_amount_cents",
    "delivery_latency_minutes",
}
INTERNAL_COLUMNS = {
    "id",
    "tenant_id",
    "dataset_id",
    "service_id",
    "created_at_utc",
    "ingested_at_utc",
    "order_id",
    "merchant_business_identity_id",
    "buyer_business_identity_id",
    "assigned_marketer_business_identity_id",
    "assigned_fraud_analyst_business_identity_id",
    "fraud_case_id",
    "case_id",
    "agent_id",
}
SENSITIVE_COLUMN_MARKERS = (
    "address",
    "phone",
    "transcript",
    "raw_",
    "full_route",
    "recipient",
    "postal",
    "geo",
    "card",
    "pan",
    "account",
    "passport",
    "id_card",
    "ssn",
)
NON_IMPORTABLE_PROTECTED_FIELDS = {
    "delivery_route.final_address_line1",
    "delivery_route.final_address_line2",
    "delivery_route.recipient_phone",
    "delivery_route.final_address_token",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def finding(*, row_no: int | None, column: str | None, kind: str, message: str) -> dict[str, Any]:
    return {
        "row_no": row_no,
        "column": column,
        "kind": kind,
        "message": message,
    }


def is_sensitive_column(column: str) -> bool:
    lowered = column.lower()
    return any(marker in lowered for marker in SENSITIVE_COLUMN_MARKERS)


def load_jsonl_rows(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for row_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                findings.append(finding(row_no=row_no, column=None, kind="invalid_json", message=str(exc)))
                continue
            if not isinstance(payload, dict):
                findings.append(finding(row_no=row_no, column=None, kind="invalid_row", message="row must be a JSON object"))
                continue
            rows.append(payload)
    if not rows and not findings:
        findings.append(finding(row_no=None, column=None, kind="empty_input", message="import file contains no rows"))
    return rows, findings


def validate_value(row_no: int, column: str, value: Any, *, required: bool) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if value is None:
        if required:
            findings.append(finding(row_no=row_no, column=column, kind="missing_required_value", message="required value is null"))
        return findings
    if isinstance(value, str) and not value.strip() and required:
        findings.append(finding(row_no=row_no, column=column, kind="missing_required_value", message="required value is empty"))
    if column in INTEGER_COLUMNS:
        if isinstance(value, bool) or not isinstance(value, int):
            findings.append(finding(row_no=row_no, column=column, kind="type_error", message="value must be an integer"))
        elif column in NON_NEGATIVE_COLUMNS and value < 0:
            findings.append(finding(row_no=row_no, column=column, kind="value_error", message="value must be non-negative"))
        elif column == "is_disputed" and value not in (0, 1):
            findings.append(finding(row_no=row_no, column=column, kind="value_error", message="is_disputed must be 0 or 1"))
    elif column in NUMBER_COLUMNS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            findings.append(finding(row_no=row_no, column=column, kind="type_error", message="value must be a number"))
        elif column == "attribution_weight" and not (0 <= float(value) <= 1):
            findings.append(finding(row_no=row_no, column=column, kind="value_error", message="attribution_weight must be between 0 and 1"))
        elif column == "risk_score" and not (0 <= float(value) <= 1):
            findings.append(finding(row_no=row_no, column=column, kind="value_error", message="risk_score must be between 0 and 1"))
    elif not isinstance(value, str):
        findings.append(finding(row_no=row_no, column=column, kind="type_error", message="value must be a string"))
    return findings


def validate_rows(*, table: str, rows: list[dict[str, Any]], policy: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    spec = TABLE_SPECS[table]
    required = set(spec["required"])
    allowed = required | set(spec["optional"])
    field_map = dict(spec["field_map"])
    field_to_class = flatten_field_classes(policy)
    checked_columns: set[str] = set()
    findings: list[dict[str, Any]] = []

    protected_fields = policy.get("protected_fields") if isinstance(policy.get("protected_fields"), dict) else {}
    if table == "orders" and "orders.buyer_email" not in protected_fields:
        findings.append(finding(row_no=None, column="buyer_email", kind="policy_unprotected_join_key", message="orders.buyer_email must remain listed in protected_fields"))

    for row_no, row in enumerate(rows, start=1):
        missing = sorted(column for column in required if column not in row)
        for column in missing:
            findings.append(finding(row_no=row_no, column=column, kind="missing_required_column", message="required column is missing"))
        for column, value in row.items():
            checked_columns.add(column)
            if column not in allowed:
                kind = "sensitive_column" if is_sensitive_column(column) else "unknown_column"
                findings.append(finding(row_no=row_no, column=column, kind=kind, message=f"column is not allowed for table {table}"))
                continue
            findings.extend(validate_value(row_no, column, value, required=column in required))
            policy_field = field_map.get(column)
            if policy_field and policy_field not in field_to_class:
                findings.append(
                    finding(
                        row_no=row_no,
                        column=column,
                        kind="policy_unclassified_column",
                        message=f"business policy does not classify {policy_field}",
                    )
                )
            elif policy_field in NON_IMPORTABLE_PROTECTED_FIELDS:
                findings.append(
                    finding(
                        row_no=row_no,
                        column=column,
                        kind="protected_field_not_importable",
                        message=f"{policy_field} must not be imported into the fact-layer baseline",
                    )
                )
            elif column not in INTERNAL_COLUMNS and not policy_field:
                findings.append(
                    finding(
                        row_no=row_no,
                        column=column,
                        kind="policy_unmapped_column",
                        message="business column has no policy field mapping",
                    )
                )
    return findings, sorted(checked_columns)


def summarize_findings(findings: list[dict[str, Any]]) -> dict[str, int]:
    keys = [
        "invalid_json",
        "invalid_row",
        "empty_input",
        "missing_required_column",
        "missing_required_value",
        "unknown_column",
        "sensitive_column",
        "protected_field_not_importable",
        "policy_unclassified_column",
        "policy_unmapped_column",
        "policy_unprotected_join_key",
        "type_error",
        "value_error",
    ]
    return {key: sum(1 for item in findings if item.get("kind") == key) for key in keys}


def build_validation_report(*, table: str, input_path: Path, policy: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows, load_findings = load_jsonl_rows(input_path)
    row_findings, checked_columns = validate_rows(table=table, rows=rows, policy=policy)
    findings = load_findings + row_findings
    decision = "deny" if findings else "allow"
    reason_code = "ok" if not findings else str(findings[0]["kind"])
    return (
        {
            "schema": SCHEMA_ID,
            "generated_at_utc": utc_now_iso(),
            "table": table,
            "input_path": str(input_path),
            "policy_id": str(policy.get("policy_id") or ""),
            "policy_version": str(policy.get("version") or ""),
            "decision": decision,
            "reason_code": reason_code,
            "row_count": len(rows),
            "checked_columns": checked_columns,
            "summary": summarize_findings(findings),
            "findings": findings,
        },
        rows,
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Validate proposed e-commerce fact-layer JSONL imports before loading fact tables.")
    ap.add_argument("--table", required=True, choices=sorted(TABLE_SPECS))
    ap.add_argument("--input", required=True, help="JSONL file containing candidate fact rows")
    ap.add_argument("--business-access-policy", default=str(DEFAULT_POLICY))
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-reject", action="store_true", help="Exit 0 even when the candidate import is denied")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        raise SystemExit(f"[ERROR] input file does not exist: {input_path}")
    policy = load_json_object(args.business_access_policy)
    report, _rows = build_validation_report(table=args.table, input_path=input_path, policy=policy)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if report["decision"] == "deny" and not args.allow_reject:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
