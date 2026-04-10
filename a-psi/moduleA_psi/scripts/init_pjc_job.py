#!/usr/bin/env python3
import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def count_lines(path: str) -> int:
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def copy_or_link(src: str, dst: str, mode: str) -> None:
    ensure_dir(os.path.dirname(dst))
    if mode == "copy":
        shutil.copy2(src, dst)
        return
    if os.path.lexists(dst):
        os.remove(dst)
    os.symlink(src, dst)


def normalize_csv_path(base_dir: str, path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(base_dir, path))


def load_manifest(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_single_job(job_dir: str, server_csv: str, client_csv: str, link_mode: str, job_id: str) -> Dict[str, Any]:
    server_csv = os.path.abspath(server_csv)
    client_csv = os.path.abspath(client_csv)
    if not os.path.isfile(server_csv):
        raise SystemExit(f"missing server csv: {server_csv}")
    if not os.path.isfile(client_csv):
        raise SystemExit(f"missing client csv: {client_csv}")

    server_dst = os.path.join(job_dir, "server.csv")
    client_dst = os.path.join(job_dir, "client.csv")
    copy_or_link(server_csv, server_dst, link_mode)
    copy_or_link(client_csv, client_dst, link_mode)

    return {
        "job_id": job_id,
        "job_type": "prepared_csv",
        "generated_at_utc": utc_now_iso(),
        "bucket_field": None,
        "bucket_count": 1,
        "bucket": {"field": None, "outputs": []},
        "input_sizes": {
            "exposure_n": count_lines(server_csv),
            "purchase_n": count_lines(client_csv),
        },
        "inputs": {
            "server_csv_src": server_csv,
            "client_csv_src": client_csv,
            "server_csv": server_dst,
            "client_csv": client_dst,
            "link_mode": link_mode,
        },
    }


def build_bucket_job(job_dir: str, manifest: Dict[str, Any], manifest_dir: str, link_mode: str, job_id: str) -> Dict[str, Any]:
    bucket_field = manifest.get("bucket_field")
    buckets: List[Dict[str, Any]] = manifest.get("buckets") or []
    if not bucket_field:
        raise SystemExit("bucket manifest missing bucket_field")
    if not buckets:
        raise SystemExit("bucket manifest has no buckets")

    outputs: List[Dict[str, Any]] = []
    total_exposure_n = 0
    total_purchase_n = 0

    for bucket in buckets:
        bucket_value = str(bucket.get("bucket"))
        server_csv = normalize_csv_path(manifest_dir, str(bucket.get("server_csv")))
        client_csv = normalize_csv_path(manifest_dir, str(bucket.get("client_csv")))
        if not os.path.isfile(server_csv):
            raise SystemExit(f"missing server csv for bucket {bucket_value}: {server_csv}")
        if not os.path.isfile(client_csv):
            raise SystemExit(f"missing client csv for bucket {bucket_value}: {client_csv}")

        subdir = os.path.join(job_dir, f"bucket_{bucket_field}={bucket_value}")
        ensure_dir(subdir)
        server_dst = os.path.join(subdir, "server.csv")
        client_dst = os.path.join(subdir, "client.csv")
        copy_or_link(server_csv, server_dst, link_mode)
        copy_or_link(client_csv, client_dst, link_mode)

        exposure_n = count_lines(server_csv)
        purchase_n = count_lines(client_csv)
        total_exposure_n += exposure_n
        total_purchase_n += purchase_n
        outputs.append({
            "bucket": bucket_value,
            "server_csv": server_dst,
            "client_csv": client_dst,
            "exposure_n": exposure_n,
            "purchase_n": purchase_n,
        })

    return {
        "job_id": job_id,
        "job_type": "prepared_csv_bucketed",
        "generated_at_utc": utc_now_iso(),
        "bucket_field": bucket_field,
        "bucket_count": len(outputs),
        "bucket": {"field": bucket_field, "outputs": outputs},
        "input_sizes": {
            "exposure_n": total_exposure_n,
            "purchase_n": total_purchase_n,
        },
        "inputs": {
            "manifest_source": os.path.join(manifest_dir, os.path.basename(manifest.get("_source", "bucket_manifest.json"))),
            "link_mode": link_mode,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Initialize a dual-machine PJC job from already prepared CSV files.")
    ap.add_argument("--out", required=True, help="Target job directory, e.g. runs/job_csv_ready")
    ap.add_argument("--job-id", default=None, help="Optional job id; defaults to basename of --out")
    ap.add_argument("--server-csv", help="Prepared server.csv for a single non-bucketed job")
    ap.add_argument("--client-csv", help="Prepared client.csv for a single non-bucketed job")
    ap.add_argument("--bucket-manifest", help="JSON manifest describing bucketed CSV inputs")
    ap.add_argument("--link-mode", choices=["copy", "symlink"], default="copy", help="How to materialize CSVs into the job dir")
    args = ap.parse_args()

    out_dir = os.path.abspath(args.out)
    ensure_dir(out_dir)
    job_id = args.job_id or os.path.basename(out_dir)

    use_single = bool(args.server_csv or args.client_csv)
    use_bucket = bool(args.bucket_manifest)
    if use_single == use_bucket:
        raise SystemExit("use either --server-csv/--client-csv or --bucket-manifest")

    if use_single:
        if not args.server_csv or not args.client_csv:
            raise SystemExit("--server-csv and --client-csv must be provided together")
        meta = build_single_job(out_dir, args.server_csv, args.client_csv, args.link_mode, job_id)
    else:
        manifest_path = os.path.abspath(args.bucket_manifest)
        manifest = load_manifest(manifest_path)
        manifest["_source"] = manifest_path
        meta = build_bucket_job(out_dir, manifest, os.path.dirname(manifest_path), args.link_mode, job_id)

    meta_path = os.path.join(out_dir, "job_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[ok] initialized job dir: {out_dir}")
    print(f"[ok] wrote metadata: {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
