#!/usr/bin/env python3
import argparse
import csv
import json
import re
from typing import Any, Iterable, NoReturn, Optional


TOKEN_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def die(msg: str) -> NoReturn:
    raise SystemExit(f"[ERROR] {msg}")


def ensure_int(value: Any, context: str) -> None:
    if isinstance(value, bool):
        die(f"{context} must be an integer")
    if isinstance(value, int):
        return
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return
    die(f"{context} must be an integer")


def ensure_token(value: str, context: str) -> None:
    if not TOKEN_RE.fullmatch(value):
        die(f"{context} must be a 64-character hex HMAC token")


def iter_csv_rows(path: str) -> Iterable[list[str]]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        yield from csv.reader(f)


def validate_bridge_input_csv(path: str, role: str, join_key_field: str, value_field: Optional[str]) -> None:
    rows = iter(iter_csv_rows(path))
    try:
        header = next(rows)
    except StopIteration:
        die(f"{path} is empty")

    if join_key_field not in header:
        die(f"{path} is missing join key column {join_key_field}")
    join_idx = header.index(join_key_field)

    value_idx = None
    if role == "client" and value_field:
        if value_field not in header:
            die(f"{path} is missing value column {value_field}")
        value_idx = header.index(value_field)

    for row_no, row in enumerate(rows, start=2):
        if not row:
            continue
        if join_idx >= len(row) or not row[join_idx].strip():
            die(f"{path}:{row_no} has an empty join key")
        if value_idx is not None:
            if value_idx >= len(row):
                die(f"{path}:{row_no} is missing value column {value_field}")
            ensure_int(row[value_idx], f"{path}:{row_no} value column {value_field}")


def validate_bridge_input_jsonl(path: str, role: str, join_key_field: str, value_field: Optional[str]) -> None:
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as e:
                die(f"{path}:{line_no} invalid JSON: {e.msg}")
            if not isinstance(row, dict):
                die(f"{path}:{line_no} must be a JSON object")
            join_key = row.get(join_key_field)
            if not isinstance(join_key, str) or not join_key.strip():
                die(f"{path}:{line_no} join key {join_key_field} must be a non-empty string")
            if role == "client" and value_field:
                if value_field not in row:
                    die(f"{path}:{line_no} is missing value field {value_field}")
                ensure_int(row[value_field], f"{path}:{line_no} value field {value_field}")


def validate_pjc_csv(path: str, columns: int) -> None:
    for row_no, row in enumerate(iter_csv_rows(path), start=1):
        if len(row) != columns:
            die(f"{path}:{row_no} must have exactly {columns} columns")
        ensure_token(row[0], f"{path}:{row_no} token")
        if columns == 2:
            ensure_int(row[1], f"{path}:{row_no} value")


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate local CSV/JSONL contracts that are not JSON schema files.")
    ap.add_argument(
        "--contract",
        required=True,
        choices=["bridge-input-csv", "bridge-input-jsonl", "pjc-server-csv", "pjc-client-csv"],
    )
    ap.add_argument("--path", required=True)
    ap.add_argument("--role", choices=["server", "client"], default="server")
    ap.add_argument("--join-key-field", default="")
    ap.add_argument("--value-field", default="")
    args = ap.parse_args()

    if args.contract.startswith("bridge-input-") and not args.join_key_field:
        die("--join-key-field is required for bridge input contracts")

    if args.contract == "bridge-input-csv":
        validate_bridge_input_csv(args.path, args.role, args.join_key_field, args.value_field or None)
    elif args.contract == "bridge-input-jsonl":
        validate_bridge_input_jsonl(args.path, args.role, args.join_key_field, args.value_field or None)
    elif args.contract == "pjc-server-csv":
        validate_pjc_csv(args.path, columns=1)
    elif args.contract == "pjc-client-csv":
        validate_pjc_csv(args.path, columns=2)
    else:
        die(f"unsupported contract {args.contract}")

    print(f"[ok] {args.contract}: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
