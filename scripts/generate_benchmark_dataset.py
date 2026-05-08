#!/usr/bin/env python3
import argparse
import csv
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_ID = "benchmark_dataset_generation/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def generate_order_record(
    index: int,
    *,
    rng: random.Random,
    campaign: str,
    customer_pool: int = 500000,
    merchant_pool: int = 10000,
) -> dict[str, Any]:
    amount_cents = rng.randint(100, 1000000)
    return {
        "order_id": f"ORD-{index:08d}",
        "record_id": f"ORD-{index:08d}",
        "email": f"customer-{index:08d}@example.com",
        "customer_id": f"CUST-{rng.randint(1, customer_pool):07d}",
        "merchant_id": f"MERCH-{rng.randint(1, merchant_pool):05d}",
        "amount": str(amount_cents),
        "amount_cents": amount_cents,
        "status": rng.choice(["completed", "refunded", "pending"]),
        "campaign": campaign,
        "created_at": f"2024-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
    }


def write_orders_jsonl(
    *,
    output: Path,
    count: int,
    seed: int,
    campaign: str,
    customer_pool: int,
    merchant_pool: int,
) -> dict[str, Any]:
    rng = random.Random(seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for index in range(count):
            row_campaign = campaign or ("demo" if index % 2 == 0 else "other")
            handle.write(
                json.dumps(
                    generate_order_record(
                        index,
                        rng=rng,
                        campaign=row_campaign,
                        customer_pool=customer_pool,
                        merchant_pool=merchant_pool,
                    ),
                    separators=(",", ":"),
                )
                + "\n"
            )
    return {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "kind": "orders-jsonl",
        "output": str(output.resolve()),
        "count": count,
        "seed": seed,
        "campaign": campaign,
        "fields": [
            "order_id",
            "record_id",
            "email",
            "customer_id",
            "merchant_id",
            "amount",
            "amount_cents",
            "status",
            "campaign",
            "created_at",
        ],
    }


def generate_bridge_csvs(*, server_csv: Path, client_csv: Path, server_rows: int, client_rows: int, overlap: float) -> None:
    overlap_rows = min(server_rows, client_rows, max(0, int(min(server_rows, client_rows) * overlap)))
    shared_ids = [f"shared-{index:08d}@example.com" for index in range(overlap_rows)]
    server_only = [f"server-{index:08d}@example.com" for index in range(server_rows - overlap_rows)]
    client_only = [f"client-{index:08d}@example.com" for index in range(client_rows - overlap_rows)]

    server_csv.parent.mkdir(parents=True, exist_ok=True)
    client_csv.parent.mkdir(parents=True, exist_ok=True)
    with server_csv.open("w", encoding="utf-8", newline="") as server_handle:
        writer = csv.writer(server_handle)
        for token in [*shared_ids, *server_only]:
            writer.writerow([token])
    with client_csv.open("w", encoding="utf-8", newline="") as client_handle:
        writer = csv.writer(client_handle)
        for index, token in enumerate([*shared_ids, *client_only], start=1):
            writer.writerow([token, str(100 + index)])


def generate_pjc_csvs(*, server_csv: Path, client_csv: Path, server_items: int, client_items: int, overlap: float) -> None:
    generate_bridge_csvs(
        server_csv=server_csv,
        client_csv=client_csv,
        server_rows=server_items,
        client_rows=client_items,
        overlap=overlap,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate deterministic benchmark datasets.")
    sub = parser.add_subparsers(dest="mode", required=True)

    orders = sub.add_parser("orders-jsonl", help="Generate synthetic e-commerce order records as JSONL")
    orders.add_argument("--output", required=True)
    orders.add_argument("--count", type=int, required=True)
    orders.add_argument("--customer-pool", type=int, default=500000)
    orders.add_argument("--merchant-pool", type=int, default=10000)
    orders.add_argument("--seed", type=int, default=1337)
    orders.add_argument("--campaign", default="", help="Force one campaign value; default preserves the historical demo/other split")
    orders.add_argument("--report", action="store_true", help="Print a JSON generation report")

    bridge = sub.add_parser("bridge-csv")
    bridge.add_argument("--server-csv", required=True)
    bridge.add_argument("--client-csv", required=True)
    bridge.add_argument("--server-rows", type=int, required=True)
    bridge.add_argument("--client-rows", type=int, required=True)
    bridge.add_argument("--overlap", type=float, default=0.3)

    pjc = sub.add_parser("pjc-csv")
    pjc.add_argument("--server-csv", required=True)
    pjc.add_argument("--client-csv", required=True)
    pjc.add_argument("--server-items", type=int, required=True)
    pjc.add_argument("--client-items", type=int, required=True)
    pjc.add_argument("--overlap", type=float, default=0.2)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.mode == "orders-jsonl":
        if args.count <= 0:
            raise SystemExit("[ERROR] --count must be positive")
        report = write_orders_jsonl(
            output=Path(args.output),
            count=args.count,
            seed=args.seed,
            campaign=args.campaign,
            customer_pool=args.customer_pool,
            merchant_pool=args.merchant_pool,
        )
        if args.report:
            print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.mode == "bridge-csv":
        generate_bridge_csvs(
            server_csv=Path(args.server_csv),
            client_csv=Path(args.client_csv),
            server_rows=args.server_rows,
            client_rows=args.client_rows,
            overlap=args.overlap,
        )
    elif args.mode == "pjc-csv":
        generate_pjc_csvs(
            server_csv=Path(args.server_csv),
            client_csv=Path(args.client_csv),
            server_items=args.server_items,
            client_items=args.client_items,
            overlap=args.overlap,
        )
    else:
        raise SystemExit(f"[ERROR] unsupported command: {args.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
