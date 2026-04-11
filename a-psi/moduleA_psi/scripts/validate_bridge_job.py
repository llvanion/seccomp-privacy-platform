#!/usr/bin/env python3
import argparse
import csv
import json
import os
from typing import Any, Dict


REQUIRED_BRIDGE_KEYS = [
    "token_scheme",
    "token_scope",
    "token_key_version",
    "normalize_version",
    "dedup_policy",
    "server",
    "client",
]


def die(msg: str) -> "NoReturn":
    raise SystemExit(f"[ERROR] {msg}")


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def count_csv_rows(path: str) -> int:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return sum(1 for _ in csv.reader(f))


def ensure_file(path: str) -> None:
    if not os.path.isfile(path):
        die(f"missing file: {path}")


def validate_bridge_meta(meta: Dict[str, Any], job_dir: str) -> None:
    schema = meta.get("schema")
    if schema is not None and schema != "bridge_job_meta/v1":
        die(f"unsupported job_meta schema: {schema}")

    bridge = meta.get("bridge")
    if not isinstance(bridge, dict):
        die("job_meta.json missing bridge section")

    for key in REQUIRED_BRIDGE_KEYS:
        if key not in bridge:
            die(f"bridge section missing required key: {key}")

    server = bridge.get("server")
    client = bridge.get("client")
    if not isinstance(server, dict):
        die("bridge.server must be an object")
    if not isinstance(client, dict):
        die("bridge.client must be an object")

    if not bridge.get("token_scope"):
        die("bridge.token_scope must be non-empty")
    if not bridge.get("token_scheme"):
        die("bridge.token_scheme must be non-empty")
    if not bridge.get("token_key_version"):
        die("bridge.token_key_version must be non-empty")
    if not bridge.get("normalize_version"):
        die("bridge.normalize_version must be non-empty")

    if not server.get("join_key_column"):
        die("bridge.server.join_key_column must be non-empty")
    if not client.get("join_key_column"):
        die("bridge.client.join_key_column must be non-empty")

    client_value_mode = client.get("value_mode")
    if client_value_mode == "raw_int" and not client.get("value_column"):
        die("bridge.client.value_column required when value_mode=raw_int")

    server_csv = os.path.join(job_dir, "server.csv")
    client_csv = os.path.join(job_dir, "client.csv")
    ensure_file(server_csv)
    ensure_file(client_csv)

    sizes = meta.get("input_sizes")
    if not isinstance(sizes, dict):
        die("job_meta.json missing input_sizes")
    exposure_n = sizes.get("exposure_n")
    purchase_n = sizes.get("purchase_n")
    if exposure_n is None or purchase_n is None:
        die("input_sizes.exposure_n and input_sizes.purchase_n are required")

    actual_exposure_n = count_csv_rows(server_csv)
    actual_purchase_n = count_csv_rows(client_csv)
    if int(exposure_n) != actual_exposure_n:
        die(f"input_sizes.exposure_n mismatch: meta={exposure_n} actual={actual_exposure_n}")
    if int(purchase_n) != actual_purchase_n:
        die(f"input_sizes.purchase_n mismatch: meta={purchase_n} actual={actual_purchase_n}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate bridge-generated job metadata before running PJC.")
    ap.add_argument("--job-dir", required=True, help="Path to the prepared job directory")
    args = ap.parse_args()

    job_dir = os.path.abspath(args.job_dir)
    meta_path = os.path.join(job_dir, "job_meta.json")
    ensure_file(meta_path)
    meta = load_json(meta_path)
    validate_bridge_meta(meta, job_dir)
    print(f"[ok] bridge job metadata validated: {job_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
