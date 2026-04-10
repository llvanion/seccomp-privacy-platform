#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import os
from typing import Dict, Any, Iterable, List

def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)

def stable_shard(key: str, num_shards: int, salt: str) -> int:
    msg = f"{salt}|{key}".encode("utf-8")
    h = hashlib.sha256(msg).digest()
    return int.from_bytes(h[:8], "big") % num_shards

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def dump_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def split_one_dir(base_dir: str, num_shards: int, salt: str) -> Dict[str, Any]:
    server_csv = os.path.join(base_dir, "server.csv")
    client_csv = os.path.join(base_dir, "client.csv")
    if not os.path.isfile(server_csv) or not os.path.isfile(client_csv):
        raise FileNotFoundError(f"missing server.csv/client.csv under {base_dir}")

    shard_dirs = [os.path.join(base_dir, f"shard_{i:04d}") for i in range(num_shards)]
    for d in shard_dirs:
        ensure_dir(d)

    server_files = []
    client_files = []
    for i in range(num_shards):
        sf = open(os.path.join(shard_dirs[i], "server.csv"), "w", newline="", encoding="utf-8")
        cf = open(os.path.join(shard_dirs[i], "client.csv"), "w", newline="", encoding="utf-8")
        server_files.append((sf, csv.writer(sf)))
        client_files.append((cf, csv.writer(cf)))

    server_counts = [0] * num_shards
    client_counts = [0] * num_shards

    try:
        with open(server_csv, "r", newline="", encoding="utf-8") as f:
            r = csv.reader(f)
            for row in r:
                if not row:
                    continue
                key = row[0]
                sid = stable_shard(key, num_shards, salt)
                server_files[sid][1].writerow([key])
                server_counts[sid] += 1

        with open(client_csv, "r", newline="", encoding="utf-8") as f:
            r = csv.reader(f)
            for row in r:
                if not row:
                    continue
                key = row[0]
                value = row[1] if len(row) > 1 else "1"
                sid = stable_shard(key, num_shards, salt)
                client_files[sid][1].writerow([key, value])
                client_counts[sid] += 1
    finally:
        for sf, _ in server_files:
            sf.close()
        for cf, _ in client_files:
            cf.close()

    outputs = []
    for i in range(num_shards):
        outputs.append({
            "shard_id": i,
            "dir": shard_dirs[i],
            "server_csv": os.path.join(shard_dirs[i], "server.csv"),
            "client_csv": os.path.join(shard_dirs[i], "client.csv"),
            "exposure_n": server_counts[i],
            "purchase_n": client_counts[i],
        })

    meta = {
        "num_shards": num_shards,
        "salt": salt,
        "outputs": outputs,
    }
    dump_json(os.path.join(base_dir, "shard_meta.json"), meta)
    return meta

def main():
    ap = argparse.ArgumentParser(description="Hash-shard existing PJC inputs for large-scale parallel compute.")
    ap.add_argument("--job-dir", required=True, help="runs/<job_id>")
    ap.add_argument("--num-shards", type=int, required=True)
    ap.add_argument("--salt", default="pjc-shard-v1")
    args = ap.parse_args()

    job_dir = os.path.abspath(args.job_dir)
    job_meta = os.path.join(job_dir, "job_meta.json")
    if not os.path.isfile(job_meta):
        raise SystemExit(f"missing job_meta.json: {job_meta}")

    meta = load_json(job_meta)
    bucket = meta.get("bucket", {}) or {}
    bucket_field = bucket.get("field")
    outputs = bucket.get("outputs") or []

    summary = {"job_dir": job_dir, "num_shards": args.num_shards, "salt": args.salt, "targets": []}

    if bucket_field and outputs:
        for o in outputs:
            b = o.get("bucket")
            sub = os.path.join(job_dir, f"bucket_{bucket_field}={b}")
            shard_meta = split_one_dir(sub, args.num_shards, args.salt)
            summary["targets"].append({"bucket": b, "dir": sub, "shards": shard_meta["outputs"]})
    else:
        shard_meta = split_one_dir(job_dir, args.num_shards, args.salt)
        summary["targets"].append({"bucket": None, "dir": job_dir, "shards": shard_meta["outputs"]})

    dump_json(os.path.join(job_dir, "job_shard_meta.json"), summary)
    print(f"OK. Wrote {os.path.join(job_dir, 'job_shard_meta.json')}")

if __name__ == "__main__":
    main()
