#!/usr/bin/env python3
"""Generate synthetic business-bucketed PJC inputs without external deps.

The generated PJC CSVs contain only HMAC-SHA256 tokens and integer values.
The raw synthetic identifiers are kept in a local records file for test
inspection, and the HMAC secret is never written to job_meta.json.
"""
import argparse
import csv
import hashlib
import hmac
import json
import os
import random
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hmac_sha256_hex(secret: str, msg: str) -> str:
    return hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def write_csv(path: Path, rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(rows)


def load_or_create_secret(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    if args.hmac_secret:
        return args.hmac_secret, {"source": "argument", "secret_file": None, "generated": False}
    if args.hmac_secret_env:
        value = os.environ.get(args.hmac_secret_env, "")
        if not value:
            raise SystemExit(f"[ERROR] env {args.hmac_secret_env} is not set")
        return value, {"source": f"env:{args.hmac_secret_env}", "secret_file": None, "generated": False}
    secret_file = Path(args.secret_file).expanduser().resolve() if args.secret_file else Path(args.out).expanduser().resolve() / ".bucket_hmac_secret"
    if secret_file.is_file() and not args.rotate_secret:
        return secret_file.read_text(encoding="utf-8").strip(), {
            "source": "file",
            "secret_file": str(secret_file),
            "generated": False,
        }
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(32)
    old_umask = os.umask(0o077)
    try:
        secret_file.write_text(secret + "\n", encoding="utf-8")
    finally:
        os.umask(old_umask)
    secret_file.chmod(0o600)
    return secret, {"source": "generated_file", "secret_file": str(secret_file), "generated": True}


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate 1k-scale synthetic business-bucketed PJC inputs.")
    ap.add_argument("--out", required=True, help="Output job directory.")
    ap.add_argument("--job-id", default="", help="Job id; default is basename of --out.")
    ap.add_argument("--records", type=int, default=1000, help="Synthetic server-side user count.")
    ap.add_argument("--buckets", type=int, default=8, help="Number of business buckets.")
    ap.add_argument("--bucket-field", default="campaign_id")
    ap.add_argument("--bucket-prefix", default="campaign")
    ap.add_argument("--overlap-rate", type=float, default=0.42, help="Fraction of server users also present on client side.")
    ap.add_argument("--min-value", type=int, default=100, help="Minimum client value in cents.")
    ap.add_argument("--max-value", type=int, default=10000, help="Maximum client value in cents.")
    ap.add_argument("--seed", type=int, default=20260517)
    ap.add_argument("--hmac-secret", default="", help="Pre-shared HMAC secret. Prefer env/file for real runs.")
    ap.add_argument("--hmac-secret-env", default="", help="Read pre-shared HMAC secret from this env var.")
    ap.add_argument("--secret-file", default="", help="Local secret file path; default <out>/.bucket_hmac_secret.")
    ap.add_argument("--rotate-secret", action="store_true", help="Regenerate --secret-file.")
    ap.add_argument("--extra-client-records", type=int, default=150, help="Client-only non-overlap records.")
    args = ap.parse_args()

    if args.records <= 0:
        raise SystemExit("[ERROR] --records must be positive")
    if args.buckets <= 0:
        raise SystemExit("[ERROR] --buckets must be positive")
    if not (0.0 <= args.overlap_rate <= 1.0):
        raise SystemExit("[ERROR] --overlap-rate must be between 0 and 1")
    if args.min_value < 0 or args.max_value < args.min_value:
        raise SystemExit("[ERROR] invalid value range")

    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    job_id = args.job_id or out.name
    rng = random.Random(args.seed)
    hmac_secret, secret_meta = load_or_create_secret(args)

    bucket_values = [f"{args.bucket_prefix}_{i:02d}" for i in range(args.buckets)]
    server_by_bucket: dict[str, list[str]] = {b: [] for b in bucket_values}
    client_by_bucket: dict[str, list[tuple[str, int]]] = {b: [] for b in bucket_values}
    raw_records: list[dict[str, Any]] = []
    expected_by_bucket: dict[str, dict[str, int]] = {
        b: {"intersection_size": 0, "intersection_sum": 0} for b in bucket_values
    }

    overlap_count = int(round(args.records * args.overlap_rate))
    overlap_indexes = set(rng.sample(range(args.records), overlap_count))

    for idx in range(args.records):
        raw_user_id = f"user_{idx:06d}"
        bucket = bucket_values[idx % args.buckets]
        token = hmac_sha256_hex(hmac_secret, raw_user_id)
        server_by_bucket[bucket].append(token)
        in_client = idx in overlap_indexes
        value = rng.randint(args.min_value, args.max_value) if in_client else None
        if in_client:
            client_by_bucket[bucket].append((token, int(value)))
            expected_by_bucket[bucket]["intersection_size"] += 1
            expected_by_bucket[bucket]["intersection_sum"] += int(value)
        raw_records.append({
            "raw_user_id": raw_user_id,
            args.bucket_field: bucket,
            "party_a_has_exposure": True,
            "party_b_has_purchase": in_client,
            "value_cents": value,
            "token_sha256_prefix": token[:16],
        })

    for idx in range(args.extra_client_records):
        raw_user_id = f"client_only_{idx:06d}"
        bucket = bucket_values[idx % args.buckets]
        token = hmac_sha256_hex(hmac_secret, raw_user_id)
        value = rng.randint(args.min_value, args.max_value)
        client_by_bucket[bucket].append((token, value))
        raw_records.append({
            "raw_user_id": raw_user_id,
            args.bucket_field: bucket,
            "party_a_has_exposure": False,
            "party_b_has_purchase": True,
            "value_cents": value,
            "token_sha256_prefix": token[:16],
        })

    outputs = []
    for bucket in bucket_values:
        sub = out / f"bucket_{args.bucket_field}={bucket}"
        server_rows = [[token] for token in sorted(server_by_bucket[bucket])]
        client_rows = [[token, value] for token, value in sorted(client_by_bucket[bucket])]
        write_csv(sub / "server.csv", server_rows)
        write_csv(sub / "client.csv", client_rows)
        outputs.append({
            "bucket": bucket,
            "server_csv": str(sub / "server.csv"),
            "client_csv": str(sub / "client.csv"),
            "exposure_n": len(server_rows),
            "purchase_n": len(client_rows),
        })

    total_size = sum(v["intersection_size"] for v in expected_by_bucket.values())
    total_sum = sum(v["intersection_sum"] for v in expected_by_bucket.values())
    expected_buckets = [
        {
            "bucket": bucket,
            "intersection_size": expected_by_bucket[bucket]["intersection_size"],
            "intersection_sum": expected_by_bucket[bucket]["intersection_sum"],
        }
        for bucket in bucket_values
    ]

    meta = {
        "job_id": job_id,
        "dataset": "synthetic_business_bucketed_pjc/v1",
        "record_count": args.records,
        "extra_client_records": args.extra_client_records,
        "value_mode": "amount",
        "value_unit": "cent",
        "bucket_field": args.bucket_field,
        "bucket_count": len(outputs),
        "bucket": {"field": args.bucket_field, "outputs": outputs},
        "hmac": {
            "enabled": True,
            "secret_source": secret_meta["source"],
            "secret_file": secret_meta["secret_file"],
            "secret_sha256": hashlib.sha256(hmac_secret.encode("utf-8")).hexdigest(),
            "secret_material_stored_in_job_meta": False,
        },
        "input_sizes": {
            "exposure_n": args.records,
            "purchase_n": sum(len(v) for v in client_by_bucket.values()),
        },
        "expected_result": {
            "intersection_size": total_size,
            "intersection_sum": total_sum,
            "buckets": expected_buckets,
        },
        "generated_at_utc": utc_now_iso(),
        "generator": {
            "script": "generate_bucketed_pjc_dataset.py",
            "seed": args.seed,
            "overlap_rate": args.overlap_rate,
            "min_value": args.min_value,
            "max_value": args.max_value,
        },
    }
    (out / "job_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "expected_result.json").write_text(json.dumps(meta["expected_result"], ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "raw_synthetic_records.jsonl").open("w", encoding="utf-8") as f:
        for row in raw_records:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    print(f"[ok] wrote bucketed PJC dataset: {out}")
    print(f"[ok] job_id={job_id} buckets={len(outputs)} records={args.records} client_rows={meta['input_sizes']['purchase_n']}")
    print(f"[ok] expected intersection_size={total_size} intersection_sum={total_sum}")
    if secret_meta["secret_file"]:
        print(f"[info] hmac secret file: {secret_meta['secret_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
