#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "validate_ecommerce_fact_import.py"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def run_validator(*, table: str, input_path: Path, output_path: Path, allow_reject: bool = False) -> dict:
    cmd = [
        sys.executable,
        str(VALIDATOR),
        "--table",
        table,
        "--input",
        str(input_path),
        "--output",
        str(output_path),
    ]
    if allow_reject:
        cmd.append("--allow-reject")
    subprocess.run(cmd, cwd=str(REPO_ROOT), check=True, stdout=subprocess.DEVNULL)
    return json.loads(output_path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-test e-commerce fact import validation gates.")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    good_order = {
        "order_id": "o-1",
        "tenant_id": "commerce_tenant",
        "dataset_id": "orders_analytics",
        "service_id": "svc-commerce",
        "buyer_email": "buyer@example.com",
        "platform_id": "shopify",
        "campaign_id": "campaign-demo",
        "currency": "USD",
        "total_amount_cents": 12345,
        "placed_at_utc": "2026-06-01T01:00:00Z",
        "status": "paid",
        "created_at_utc": "2026-06-01T01:00:00Z",
        "ingested_at_utc": "2026-06-01T01:01:00Z",
    }
    good_path = out_dir / "orders_good.jsonl"
    write_jsonl(good_path, [good_order])
    good = run_validator(table="orders", input_path=good_path, output_path=out_dir / "orders_good_report.json")
    require(good.get("decision") == "allow", f"expected good import allow: {good}")
    require("buyer_email" in (good.get("checked_columns") or []), f"join key was not checked: {good}")

    address_path = out_dir / "orders_address.jsonl"
    write_jsonl(address_path, [{**good_order, "delivery_address": "1 Secret Street"}])
    address = run_validator(
        table="orders",
        input_path=address_path,
        output_path=out_dir / "orders_address_report.json",
        allow_reject=True,
    )
    require(address.get("decision") == "deny", f"expected address import deny: {address}")
    require((address.get("summary") or {}).get("sensitive_column", 0) >= 1, f"expected sensitive column finding: {address}")

    negative_path = out_dir / "orders_negative_value.jsonl"
    write_jsonl(negative_path, [{**good_order, "total_amount_cents": -1}])
    negative = run_validator(
        table="orders",
        input_path=negative_path,
        output_path=out_dir / "orders_negative_value_report.json",
        allow_reject=True,
    )
    require(negative.get("decision") == "deny", f"expected negative value deny: {negative}")
    require((negative.get("summary") or {}).get("value_error", 0) >= 1, f"expected value error finding: {negative}")

    support_path = out_dir / "support_transcript.jsonl"
    write_jsonl(
        support_path,
        [
            {
                "order_id": "o-1",
                "tenant_id": "commerce_tenant",
                "dataset_id": "orders_analytics",
                "interaction_type": "complaint",
                "channel": "chat",
                "agent_id": "agent-1",
                "resolution_status": "open",
                "raw_transcript": "buyer disclosed private details",
                "created_at_utc": "2026-06-01T01:02:00Z",
                "ingested_at_utc": "2026-06-01T01:03:00Z",
            }
        ],
    )
    support = run_validator(
        table="customer_service_interactions",
        input_path=support_path,
        output_path=out_dir / "support_transcript_report.json",
        allow_reject=True,
    )
    require(support.get("decision") == "deny", f"expected transcript import deny: {support}")
    require((support.get("summary") or {}).get("sensitive_column", 0) >= 1, f"expected sensitive transcript finding: {support}")

    report = {
        "schema": "ecommerce_fact_import_validation_smoke/v1",
        "status": "ok",
        "allow_decision": good.get("decision"),
        "address_decision": address.get("decision"),
        "negative_value_decision": negative.get("decision"),
        "support_transcript_decision": support.get("decision"),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    (out_dir / "ecommerce_fact_import_validation_smoke.json").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
