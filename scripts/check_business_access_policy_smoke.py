#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY = REPO_ROOT / "config" / "business_access_policy.ecommerce.example.json"
CHECKER = REPO_ROOT / "scripts" / "check_business_access_policy.py"


def run_case(tmp: Path, name: str, args: list[str], expected: str, required_field_decisions: dict[str, str]) -> dict:
    out = tmp / f"{name}.json"
    cmd = [sys.executable, str(CHECKER), "--policy", str(POLICY), "--output", str(out), *args, "--assert-decision", expected]
    subprocess.run(cmd, cwd=str(REPO_ROOT), check=True, stdout=subprocess.DEVNULL)
    payload = json.loads(out.read_text(encoding="utf-8"))
    if payload.get("decision") != expected:
        raise AssertionError(f"{name}: expected {expected}, got {payload.get('decision')}")
    by_field = {item["field"]: item["decision"] for item in payload.get("field_decisions") or []}
    for field, decision in required_field_decisions.items():
        if by_field.get(field) != decision:
            raise AssertionError(f"{name}: expected {field}={decision}, got {by_field.get(field)}")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-test the e-commerce business field-level access policy.")
    ap.add_argument("--output", default="")
    args = ap.parse_args()
    cases = []
    with tempfile.TemporaryDirectory(prefix="business_access_smoke.") as tmp_raw:
        tmp = Path(tmp_raw)
        cases.append(run_case(
            tmp,
            "merchant_denies_address",
            [
                "--role", "merchant_staff",
                "--entity", "orders",
                "--field", "orders.order_id",
                "--field", "order_fulfillment.delivery_address",
                "--purpose", "merchant_order_ops",
                "--relationship", "merchant_of_order",
                "--scope", "tenant_id=commerce_tenant",
                "--scope", "order_id=o-1",
            ],
            "deny",
            {"orders.order_id": "allow", "order_fulfillment.delivery_address": "deny"},
        ))
        cases.append(run_case(
            tmp,
            "courier_next_stop_only",
            [
                "--role", "courier",
                "--entity", "order_fulfillment",
                "--field", "delivery_route.next_stop_label",
                "--field", "delivery_route.final_address",
                "--purpose", "delivery_next_stop",
                "--relationship", "assigned_delivery_leg",
                "--scope", "tenant_id=commerce_tenant",
                "--scope", "delivery_leg_id=leg-1",
            ],
            "deny",
            {"delivery_route.next_stop_label": "allow", "delivery_route.final_address": "deny"},
        ))
        cases.append(run_case(
            tmp,
            "support_masks_contact",
            [
                "--role", "customer_service_agent",
                "--entity", "customer_service_interactions",
                "--field", "customer_service_interactions.resolution_status",
                "--field", "orders.buyer_email",
                "--purpose", "support_case",
                "--relationship", "assigned_support_case",
                "--scope", "tenant_id=commerce_tenant",
                "--scope", "case_id=case-1",
            ],
            "mask",
            {"customer_service_interactions.resolution_status": "allow", "orders.buyer_email": "mask"},
        ))
        cases.append(run_case(
            tmp,
            "buyer_self_contact",
            [
                "--role", "buyer",
                "--entity", "orders",
                "--field", "customer_profile.phone",
                "--field", "orders.status",
                "--purpose", "self_service",
                "--relationship", "self",
                "--scope", "tenant_id=commerce_tenant",
                "--scope", "buyer_id=buyer-1",
            ],
            "allow",
            {"customer_profile.phone": "allow", "orders.status": "allow"},
        ))
        cases.append(run_case(
            tmp,
            "auditor_masks_address",
            [
                "--role", "compliance_auditor",
                "--entity", "orders",
                "--field", "orders.order_id",
                "--field", "customer_profile.address_line1",
                "--purpose", "compliance_audit",
                "--relationship", "tenant_auditor",
                "--scope", "tenant_id=commerce_tenant",
            ],
            "mask",
            {"orders.order_id": "allow", "customer_profile.address_line1": "mask"},
        ))
        cases.append(run_case(
            tmp,
            "merchant_wrong_relationship",
            [
                "--role", "merchant_staff",
                "--entity", "orders",
                "--field", "orders.order_id",
                "--purpose", "merchant_order_ops",
                "--relationship", "self",
                "--scope", "tenant_id=commerce_tenant",
            ],
            "deny",
            {"orders.order_id": "deny"},
        ))
    report = {
        "schema": "business_access_policy_smoke/v1",
        "case_count": len(cases),
        "cases": [
            {
                "name": item["request"]["role"] + ":" + item["request"]["entity"],
                "decision": item["decision"],
                "reason_code": item["reason_code"],
                "summary": item["summary"],
            }
            for item in cases
        ],
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
