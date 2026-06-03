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


def count_orders(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM orders").fetchone()
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
        "platform_id": "shopify",
        "campaign_id": "campaign-demo",
        "currency": "USD",
        "total_amount_cents": amount,
        "placed_at_utc": "2026-06-01T01:00:00Z",
        "status": "paid",
        "created_at_utc": "2026-06-01T01:00:00Z",
        "ingested_at_utc": "2026-06-01T01:01:00Z",
    }


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

    report = {
        "schema": "ecommerce_fact_import_smoke/v1",
        "status": "ok",
        "allow_decision": allow.get("decision"),
        "allow_transaction": allow.get("transaction"),
        "sensitive_decision": sensitive.get("decision"),
        "sensitive_transaction": sensitive.get("transaction"),
        "duplicate_decision": duplicate.get("decision"),
        "duplicate_transaction": duplicate.get("transaction"),
        "final_order_count": count_orders(db_path),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    (out_dir / "ecommerce_fact_import_smoke.json").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
