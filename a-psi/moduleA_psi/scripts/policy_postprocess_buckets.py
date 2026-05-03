#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict, List


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def main() -> None:
    ap = argparse.ArgumentParser(description="Post-process public_report.json to include per-bucket suppression from attribution_result.json (if present)")
    ap.add_argument("--job-dir", required=True)
    ap.add_argument("--k", type=int, required=True, help="k-threshold")
    ap.add_argument("--report", default=None, help="public_report.json path (default: <job-dir>/public_report.json)")
    ap.add_argument("--attribution", default=None, help="attribution_result.json path (default: <job-dir>/attribution_result.json)")
    args = ap.parse_args()

    job_dir = os.path.abspath(args.job_dir)
    report_path = os.path.abspath(args.report) if args.report else os.path.join(job_dir, "public_report.json")
    attr_path = os.path.abspath(args.attribution) if args.attribution else os.path.join(job_dir, "attribution_result.json")

    if not os.path.isfile(report_path):
        raise SystemExit(f"missing report: {report_path}")
    if not os.path.isfile(attr_path):
        raise SystemExit(f"missing attribution: {attr_path}")

    rep = load_json(report_path)
    attr = load_json(attr_path)

    buckets: List[Dict[str, Any]] = attr.get("buckets") or []
    if not buckets:
        print("OK (no buckets).")
        return

    k = int(args.k)
    out = []
    for b in buckets:
        size = int(b.get("intersection_size", 0))
        row = {
            "bucket": b.get("bucket"),
            "intersection_size": size if size >= k else None,
            "intersection_sum": int(b.get("intersection_sum", 0)) if size >= k else None,
            "suppressed": size < k,
        }
        out.append(row)

    rep.setdefault("debug", {})
    rep["debug"]["per_bucket_results"] = out
    dump_json(report_path, rep)
    print(f"OK. Updated {report_path} with per_bucket_results (suppressed if < {k}).")


if __name__ == "__main__":
    main()
