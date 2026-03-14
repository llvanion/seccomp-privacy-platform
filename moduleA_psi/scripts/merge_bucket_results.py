#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict, List


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge per-bucket attribution_result.json into a single job-level attribution_result.json")
    ap.add_argument("--job-dir", required=True, help="runs/<job_id> directory containing job_meta.json and bucket subdirs")
    ap.add_argument("--out", default=None, help="Output attribution_result.json path (default: <job-dir>/attribution_result.json)")
    ap.add_argument("--strict", action="store_true", help="Fail if any bucket is missing attribution_result.json")
    args = ap.parse_args()

    job_dir = os.path.abspath(args.job_dir)
    out_path = os.path.abspath(args.out) if args.out else os.path.join(job_dir, "attribution_result.json")
    job_meta_path = os.path.join(job_dir, "job_meta.json")

    if not os.path.isfile(job_meta_path):
        raise SystemExit(f"missing job_meta.json: {job_meta_path}")

    meta = load_json(job_meta_path)
    bucket_info = meta.get("bucket", {}) or {}
    outputs: List[Dict[str, Any]] = (bucket_info.get("outputs") or [])
    bucket_field = bucket_info.get("field")

    # If no bucket outputs, just pass-through (expect job_dir/attribution_result.json exists)
    if not outputs or bucket_field in (None, "", "None"):
        if not os.path.isfile(os.path.join(job_dir, "attribution_result.json")):
            raise SystemExit("No buckets in job_meta.json and missing attribution_result.json in job dir.")
        if out_path != os.path.join(job_dir, "attribution_result.json"):
            with open(os.path.join(job_dir, "attribution_result.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        print("OK (no buckets).")
        return

    per_bucket: List[Dict[str, Any]] = []
    total_size = 0
    total_sum = 0
    missing: List[str] = []

    for o in outputs:
        b = o.get("bucket")
        # prep_inputs writes server/client csv under subdir: bucket_<field>=<value>/
        sub = os.path.join(job_dir, f"bucket_{bucket_field}={b}")
        res_path = os.path.join(sub, "attribution_result.json")
        if not os.path.isfile(res_path):
            missing.append(res_path)
            continue

        r = load_json(res_path)
        size = int(r.get("intersection_size", 0))
        ssum = int(r.get("intersection_sum", 0))
        total_size += size
        total_sum += ssum
        per_bucket.append(
            {
                "bucket": b,
                "bucket_dir": os.path.relpath(sub, job_dir),
                "intersection_size": size,
                "intersection_sum": ssum,
            }
        )

    if missing and args.strict:
        raise SystemExit("Missing bucket results:\n" + "\n".join(missing))

    merged: Dict[str, Any] = {
        "job_id": meta.get("job_id") or meta.get("job", {}).get("job_id"),
        "timestamp": meta.get("generated_at_utc"),
        "bucket_field": bucket_field,
        "bucket_count_expected": len(outputs),
        "bucket_count_merged": len(per_bucket),
        "missing_bucket_results": [os.path.relpath(p, job_dir) for p in missing],
        "intersection_size": total_size,
        "intersection_sum": total_sum,
        "buckets": per_bucket,
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"OK. Wrote {out_path}")
    print(f"total intersection_size={total_size} intersection_sum={total_sum}")
    if missing:
        print(f"[warn] missing {len(missing)} bucket result(s). Use --strict to fail.")


if __name__ == "__main__":
    main()
