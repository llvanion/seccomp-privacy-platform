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

from bucket_policy import BucketPolicyError, build_bucket_policy, bucket_policy_sha256


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hmac_sha256_hex(secret: str, msg: str) -> str:
    return hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def write_csv(path: Path, rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(rows)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
    ap.add_argument("--allowed-bucket-field", action="append", default=[], help="Allowed bucket field; repeatable.")
    ap.add_argument("--allowed-bucket", action="append", default=[], help="Allowed bucket label; repeatable.")
    ap.add_argument("--max-buckets", type=int, default=None, help="Maximum allowed bucket count.")
    ap.add_argument("--bucket-label-pattern", default="", help="Regex that every bucket label must match.")
    ap.add_argument("--production-mode", action="store_true", help="Require explicit bucket allowlist policy.")
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
    try:
        bucket_policy = build_bucket_policy(
            bucket_field=args.bucket_field,
            bucket_values=bucket_values,
            allowed_bucket_fields=args.allowed_bucket_field,
            allowed_buckets=args.allowed_bucket,
            max_buckets=args.max_buckets,
            bucket_label_pattern=args.bucket_label_pattern or None,
            production_mode=args.production_mode,
        )
    except BucketPolicyError as exc:
        raise SystemExit(f"[ERROR] {exc}") from exc
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

    raw_records_path = out / "raw_synthetic_records.jsonl"
    with raw_records_path.open("w", encoding="utf-8") as f:
        for row in raw_records:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    outputs = []
    client_total_sum = 0
    client_total_min: int | None = None
    client_total_max: int | None = None
    for bucket in bucket_values:
        sub = out / f"bucket_{args.bucket_field}={bucket}"
        server_rows = [[token] for token in sorted(server_by_bucket[bucket])]
        client_rows = [[token, value] for token, value in sorted(client_by_bucket[bucket])]
        write_csv(sub / "server.csv", server_rows)
        write_csv(sub / "client.csv", client_rows)
        client_values = [value for _, value in sorted(client_by_bucket[bucket])]
        if client_values:
            client_total_sum += sum(client_values)
            bucket_min = min(client_values)
            bucket_max = max(client_values)
            client_total_min = bucket_min if client_total_min is None else min(client_total_min, bucket_min)
            client_total_max = bucket_max if client_total_max is None else max(client_total_max, bucket_max)
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

    flat_server_csv = out / "server.csv"
    flat_client_csv = out / "client.csv"
    write_csv(flat_server_csv, [[token] for bucket in bucket_values for token in sorted(server_by_bucket[bucket])])
    write_csv(flat_client_csv, [[token, value] for bucket in bucket_values for token, value in sorted(client_by_bucket[bucket])])

    raw_records_sha256 = sha256_file(raw_records_path)
    flat_server_sha256 = sha256_file(flat_server_csv)
    flat_client_sha256 = sha256_file(flat_client_csv)

    input_commitment = {
        "schema": "pjc_input_commitment/v1",
        "job_id": job_id,
        "generated_by": "generate_bucketed_pjc_dataset.py",
        "token_scheme": "bridge-hmac-sha256-v1",
        "token_scope": f"bucketed-scale:{job_id}",
        "token_key_version": "1",
        "normalize_version": "synthetic-bucketed-v1",
        "normalizer_schema_version": "normalizer-schema/v1",
        "dedup_policy": "synthetic_exact_tokens",
        "bucket_scope": {
            "schema": "bucket_scope/v1",
            "bucket_field": args.bucket_field,
            "bucket_count": len(outputs),
            "bucket_policy_sha256": bucket_policy_sha256(bucket_policy),
            "allowed_bucket_count": len(bucket_policy.get("allowed_buckets") or []),
            "bucket_labels_redacted": True,
            "require_exact_allowed_buckets": bool(bucket_policy.get("require_exact_allowed_buckets", False)),
            "enforcement": bucket_policy.get("enforcement") or "fail_closed",
        },
        "shard_scope": None,
        "parties": {
            "server": {
                "role": "server",
                "input_file": str(raw_records_path),
                "input_format": "jsonl",
                "source_input_sha256": raw_records_sha256,
                "join_key_column": "email",
                "normalizer": "email",
                "value_column": None,
                "value_mode": None,
                "value_policy": None,
                "source_value_summary": None,
                "output_csv": str(flat_server_csv),
                "output_csv_sha256": flat_server_sha256,
                "output_row_count": args.records,
                "value_summary": None,
            },
            "client": {
                "role": "client",
                "input_file": str(raw_records_path),
                "input_format": "jsonl",
                "source_input_sha256": raw_records_sha256,
                "join_key_column": "email",
                "normalizer": "email",
                "value_column": "amount",
                "value_mode": "raw_int",
                "value_policy": {
                    "min_value": args.min_value,
                    "max_value": args.max_value,
                    "allow_negative": False,
                    "allowed_value_columns": ["amount"],
                    "value_unit": "minor_currency_unit",
                    "currency": "USD",
                },
                "source_value_summary": {
                    "sum": client_total_sum,
                    "min": client_total_min,
                    "max": client_total_max,
                    "non_negative": True,
                },
                "output_csv": str(flat_client_csv),
                "output_csv_sha256": flat_client_sha256,
                "output_row_count": sum(len(v) for v in client_by_bucket.values()),
                "value_summary": {
                    "sum": client_total_sum,
                    "min": client_total_min,
                    "max": client_total_max,
                    "non_negative": True,
                },
            },
        },
    }

    meta = {
        "job_id": job_id,
        "dataset": "synthetic_business_bucketed_pjc/v1",
        "record_count": args.records,
        "extra_client_records": args.extra_client_records,
        "value_mode": "amount",
        "value_unit": "cent",
        "bucket_field": args.bucket_field,
        "bucket_count": len(outputs),
        "bucket_policy_sha256": bucket_policy_sha256(bucket_policy),
        "bucket_policy": bucket_policy,
        "bucket": {"field": args.bucket_field, "outputs": outputs},
        "bridge": {
            "token_scheme": input_commitment["token_scheme"],
            "token_scope": input_commitment["token_scope"],
            "token_key_version": input_commitment["token_key_version"],
            "normalize_version": input_commitment["normalize_version"],
            "normalizer_schema_version": input_commitment["normalizer_schema_version"],
            "dedup_policy": input_commitment["dedup_policy"],
            "server": {
                "input_file": input_commitment["parties"]["server"]["input_file"],
                "input_format": input_commitment["parties"]["server"]["input_format"],
                "join_key_column": input_commitment["parties"]["server"]["join_key_column"],
                "normalizer": input_commitment["parties"]["server"]["normalizer"],
            },
            "client": {
                "input_file": input_commitment["parties"]["client"]["input_file"],
                "input_format": input_commitment["parties"]["client"]["input_format"],
                "join_key_column": input_commitment["parties"]["client"]["join_key_column"],
                "value_column": input_commitment["parties"]["client"]["value_column"],
                "value_mode": input_commitment["parties"]["client"]["value_mode"],
                "value_policy": input_commitment["parties"]["client"]["value_policy"],
                "normalizer": input_commitment["parties"]["client"]["normalizer"],
            },
        },
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
        "inputs": {
            "server_csv": str(flat_server_csv),
            "client_csv": str(flat_client_csv),
            "input_commitment_file": str(out / "input_commitments.json"),
            "input_commitment_sha256": None,
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
    (out / "input_commitments.json").write_text(json.dumps(input_commitment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta["inputs"]["input_commitment_sha256"] = sha256_file(out / "input_commitments.json")
    (out / "job_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "expected_result.json").write_text(json.dumps(meta["expected_result"], ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ok] wrote bucketed PJC dataset: {out}")
    print(f"[ok] job_id={job_id} buckets={len(outputs)} records={args.records} client_rows={meta['input_sizes']['purchase_n']}")
    print(f"[ok] expected intersection_size={total_size} intersection_sum={total_sum}")
    if secret_meta["secret_file"]:
        print(f"[info] hmac secret file: {secret_meta['secret_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
