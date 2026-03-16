#!/usr/bin/env python3
import argparse, json, os, re
from typing import Any, Dict, List

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_elapsed_hms(s: str) -> float:
    if not s:
        return -1.0
    s = s.strip()
    m = re.match(r"^(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)$", s)
    if m:
        h = int(m.group(1) or 0)
        mm = int(m.group(2))
        ss = float(m.group(3))
        return h * 3600 + mm * 60 + ss
    m = re.match(r"^(\d+):(\d+(?:\.\d+)?)$", s)
    if m:
        mm = int(m.group(1))
        ss = float(m.group(2))
        return mm * 60 + ss
    try:
        return float(s)
    except Exception:
        return -1.0

def safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default

def file_line_count(path: str) -> int:
    n = 0
    with open(path, "rb") as f:
        for _ in f:
            n += 1
    return n

def stats(vals: List[int]) -> Dict[str, Any]:
    if not vals:
        return {"min": None, "mean": None, "p95": None, "max": None}
    s = sorted(vals)
    n = len(s)
    mean = sum(s) / n
    p95 = s[max(0, int(0.95 * n) - 1)]
    return {"min": s[0], "mean": mean, "p95": p95, "max": s[-1]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-id", required=True)
    ap.add_argument("--job-dir", required=True)
    ap.add_argument("--elapsed", default="")
    ap.add_argument("--max-rss-kb", default="0")
    ap.add_argument("--user-time-s", default="0")
    ap.add_argument("--sys-time-s", default="0")
    ap.add_argument("--exit-status", default="0")
    ap.add_argument("--num-shards", type=int, default=0)
    ap.add_argument("--max-jobs", type=int, default=4)
    ap.add_argument("--bucket-field", default="")
    ap.add_argument("--value-mode", default="count")
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    job_dir = os.path.abspath(args.job_dir)
    meta_path = os.path.join(job_dir, "job_meta.json")
    attr_path = os.path.join(job_dir, "attribution_result.json")
    pub_path = os.path.join(job_dir, "public_report.json")

    meta = load_json(meta_path) if os.path.isfile(meta_path) else {}
    attr = load_json(attr_path) if os.path.isfile(attr_path) else {}
    pub = load_json(pub_path) if os.path.isfile(pub_path) else {}

    exposure_n = safe_int(meta.get("window", {}).get("dedup", {}).get("exposure_n"), 0)
    purchase_n = safe_int(meta.get("window", {}).get("dedup", {}).get("purchase_n"), 0)

    server_csv = os.path.join(job_dir, "server.csv")
    client_csv = os.path.join(job_dir, "client.csv")
    if exposure_n == 0 and os.path.isfile(server_csv):
        exposure_n = file_line_count(server_csv)
    if purchase_n == 0 and os.path.isfile(client_csv):
        purchase_n = file_line_count(client_csv)

    bucket = meta.get("bucket", {}) or {}
    bucket_field = bucket.get("field") or args.bucket_field or ""
    bucket_outputs = bucket.get("outputs") or []

    b_exp = [safe_int(o.get("exposure_n"), 0) for o in bucket_outputs]
    b_pur = [safe_int(o.get("purchase_n"), 0) for o in bucket_outputs]

    out = {
        "case_id": args.case_id,
        "job_dir": job_dir,
        "run": {
            "exit_status": safe_int(args.exit_status, 0),
            "elapsed_str": args.elapsed,
            "elapsed_s": parse_elapsed_hms(args.elapsed),
            "max_rss_mb": float(args.max_rss_kb) / 1024.0 if args.max_rss_kb else None,
            "cpu_user_s": float(args.user_time_s) if args.user_time_s else None,
            "cpu_sys_s": float(args.sys_time_s) if args.sys_time_s else None,
        },
        "params": {
            "num_shards": args.num_shards,
            "max_jobs": args.max_jobs,
            "bucket_field": bucket_field,
            "value_mode": args.value_mode,
            "k": args.k,
            "n": args.n,
        },
        "dedup": {
            "exposure_n": exposure_n,
            "purchase_n": purchase_n,
            "bucket_count": len(bucket_outputs) if bucket_field else 0,
            "bucket_exposure_stats": stats(b_exp),
            "bucket_purchase_stats": stats(b_pur),
        },
        "result": {
            "intersection_size": safe_int(attr.get("intersection_size"), 0),
            "intersection_sum": safe_int(attr.get("intersection_sum"), 0),
        },
        "policy": {
            "suppressed_bucket_count": pub.get("suppressed_bucket_count") if isinstance(pub, dict) else None,
            "published_bucket_count": pub.get("published_bucket_count") if isinstance(pub, dict) else None,
        }
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
