#!/usr/bin/env python3
import argparse
import csv
import json
import random
from pathlib import Path


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def synthetic_order_record(index: int, *, customer_pool: int, merchant_pool: int) -> dict[str, str | int]:
    return {
        "order_id": f"ORD-{index:08d}",
        "customer_id": f"CUST-{random.randint(1, customer_pool):07d}",
        "merchant_id": f"MERCH-{random.randint(1, merchant_pool):05d}",
        "email": f"customer-{index:08d}@example.com",
        "campaign": "demo" if index % 2 == 0 else "other",
        "amount": random.randint(100, 1000000),
        "status": random.choice(["completed", "refunded", "pending"]),
        "created_at": f"2024-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}",
    }


def generate_orders_jsonl(*, output: Path, count: int, customer_pool: int, merchant_pool: int) -> None:
    rows = [synthetic_order_record(index, customer_pool=customer_pool, merchant_pool=merchant_pool) for index in range(count)]
    write_jsonl(output, rows)


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
    ap = argparse.ArgumentParser(description="Generate synthetic benchmark datasets for SSE, bridge, and PJC scale tests.")
    sub = ap.add_subparsers(dest="mode", required=True)

    orders = sub.add_parser("orders-jsonl")
    orders.add_argument("--output", required=True)
    orders.add_argument("--count", type=int, required=True)
    orders.add_argument("--customer-pool", type=int, default=500000)
    orders.add_argument("--merchant-pool", type=int, default=10000)

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
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.mode == "orders-jsonl":
        if args.count <= 0:
            raise SystemExit("[ERROR] --count must be positive")
        generate_orders_jsonl(
            output=Path(args.output),
            count=args.count,
            customer_pool=args.customer_pool,
            merchant_pool=args.merchant_pool,
        )
    elif args.mode == "bridge-csv":
        generate_bridge_csvs(
            server_csv=Path(args.server_csv),
            client_csv=Path(args.client_csv),
            server_rows=args.server_rows,
            client_rows=args.client_rows,
            overlap=args.overlap,
        )
    else:
        generate_pjc_csvs(
            server_csv=Path(args.server_csv),
            client_csv=Path(args.client_csv),
            server_items=args.server_items,
            client_items=args.client_items,
            overlap=args.overlap,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
