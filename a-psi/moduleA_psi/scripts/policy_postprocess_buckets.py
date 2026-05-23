#!/usr/bin/env python3
import argparse
import json
import math
import os
import secrets
from typing import Any, Dict, List


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


_RNG = secrets.SystemRandom()


def laplace_noise(scale: float) -> float:
    u = _RNG.uniform(-0.5 + 1e-12, 0.5 - 1e-12)
    return -scale * math.copysign(1.0, u) * math.log(1.0 - 2.0 * abs(u))


def main() -> None:
    ap = argparse.ArgumentParser(description="Post-process public_report.json to include per-bucket suppression from attribution_result.json (if present)")
    ap.add_argument("--job-dir", required=True)
    ap.add_argument("--k", type=int, required=True, help="k-threshold")
    ap.add_argument("--report", default=None, help="public_report.json path (default: <job-dir>/public_report.json)")
    ap.add_argument("--attribution", default=None, help="attribution_result.json path (default: <job-dir>/attribution_result.json)")
    ap.add_argument("--out", default=None, help="Protected bucket report path (default: <job-dir>/bucket_public_report.json)")
    ap.add_argument("--dp-epsilon", type=float, default=None, help="Apply Laplace noise to released bucket sums.")
    ap.add_argument("--dp-sensitivity", type=int, default=None, help="Sensitivity for bucket sum DP noise.")
    ap.add_argument("--round-sum-to", type=int, default=None, help="Round released bucket sums after DP.")
    ap.add_argument("--require-dp", action="store_true",
                    help=(
                        "Fail-closed if --dp-epsilon and --dp-sensitivity are not both set "
                        "with positive values. Use on every public bucket report."
                    ))
    ap.add_argument("--public-report-redact-operator-fields", action="store_true",
                    help=(
                        "S5: do NOT inject debug.per_bucket_results / debug.bucket_policy "
                        "into public_report.json. The dedicated bucket_public_report.json "
                        "is unaffected — operators still see everything there."
                    ))
    args = ap.parse_args()

    # Fail-closed DP enforcement (A.11). Bucket reports are exactly the surface
    # where differencing attacks bite hardest; if --require-dp is set we refuse
    # to write the protected report when DP knobs are missing or non-positive.
    if args.require_dp:
        missing = []
        if args.dp_epsilon is None or args.dp_epsilon <= 0:
            missing.append("--dp-epsilon")
        if args.dp_sensitivity is None or args.dp_sensitivity <= 0:
            missing.append("--dp-sensitivity")
        if missing:
            raise SystemExit(
                "policy_postprocess_buckets: --require-dp set but missing/non-positive: "
                + ", ".join(missing)
            )

    job_dir = os.path.abspath(args.job_dir)
    report_path = os.path.abspath(args.report) if args.report else os.path.join(job_dir, "public_report.json")
    attr_path = os.path.abspath(args.attribution) if args.attribution else os.path.join(job_dir, "attribution_result.json")
    out_path = os.path.abspath(args.out) if args.out else os.path.join(job_dir, "bucket_public_report.json")

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
    dp_enabled = args.dp_epsilon is not None and args.dp_sensitivity is not None and args.dp_epsilon > 0 and args.dp_sensitivity > 0
    if args.dp_epsilon is not None and args.dp_epsilon <= 0:
        raise SystemExit("--dp-epsilon must be positive")
    if args.dp_sensitivity is not None and args.dp_sensitivity <= 0:
        raise SystemExit("--dp-sensitivity must be positive")
    out = []
    for b in buckets:
        size = int(b.get("intersection_size", 0))
        raw_sum = int(b.get("intersection_sum", 0))
        released_sum = raw_sum
        noise = None
        if size >= k and dp_enabled:
            noise = laplace_noise(float(args.dp_sensitivity) / float(args.dp_epsilon))
            released_sum = max(0, int(round(float(raw_sum) + noise)))
        if size >= k and args.round_sum_to and args.round_sum_to > 1:
            released_sum = int(round(released_sum / args.round_sum_to) * args.round_sum_to)
        row = {
            "bucket": b.get("bucket"),
            "intersection_size": size if size >= k else None,
            "intersection_sum": released_sum if size >= k else None,
            "suppressed": size < k,
            "reason_code": "below_k" if size < k else "released",
            "dp_noise_applied": bool(size >= k and dp_enabled),
            "dp_epsilon": args.dp_epsilon if size >= k and dp_enabled else None,
            "dp_sensitivity": args.dp_sensitivity if size >= k and dp_enabled else None,
            "dp_noise": noise,
        }
        out.append(row)

    if args.public_report_redact_operator_fields:
        # S5: keep public_report.json clean of per-bucket leakage. The protected
        # bucket_public_report.json is still written below, so the operator
        # console can render exactly the same data — just not through the
        # public-grade report file.
        rep.setdefault("debug", {})
        rep["debug"]["bucket_results_redacted"] = True
        rep["debug"]["bucket_policy"] = {
            "k": k,
            "dp_noise_applied": dp_enabled,
            "redacted": True,
            "reason": "public-report operator-field redaction enabled",
        }
    else:
        rep.setdefault("debug", {})
        rep["debug"]["per_bucket_results"] = out
        rep["debug"]["bucket_policy"] = {
            "k": k,
            "dp_noise_applied": dp_enabled,
            "dp_epsilon": args.dp_epsilon if dp_enabled else None,
            "dp_sensitivity": args.dp_sensitivity if dp_enabled else None,
            "round_sum_to": args.round_sum_to,
        }
    dump_json(report_path, rep)
    protected = {
        "schema": "bucket_public_report/v1",
        "job_id": attr.get("job_id"),
        "bucket_field": attr.get("bucket_field"),
        "bucket_count": len(out),
        "k": k,
        "dp_noise_applied": dp_enabled,
        "dp_epsilon": args.dp_epsilon if dp_enabled else None,
        "dp_sensitivity": args.dp_sensitivity if dp_enabled else None,
        "round_sum_to": args.round_sum_to,
        "buckets": out,
    }
    dump_json(out_path, protected)
    print(f"OK. Updated {report_path} with per_bucket_results (suppressed if < {k}).")
    print(f"OK. Wrote protected bucket report: {out_path}")


if __name__ == "__main__":
    main()
