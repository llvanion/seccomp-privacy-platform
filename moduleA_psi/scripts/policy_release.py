import argparse
import json
import os
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from decimal import Decimal, ROUND_HALF_UP

def cents_to_eur_str(cents: int) -> str:
    #Convert integer cents to euro string with 2 decimals, avoiding float issues.
    eur = (Decimal(int(cents)) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(eur, "f")

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def try_get(d: Dict[str, Any], *keys, default=None):
    """Try multiple candidate keys; return first match."""
    for k in keys:
        if k in d:
            return d[k]
    return default


def parse_pjc_result(result: Dict[str, Any]) -> Dict[str, Optional[int]]:
    """
    Normalize possible output formats from different scripts/wrappers.
    Expected canonical fields:
      - intersection_size
      - intersection_sum
    """
    # Direct keys (most likely from your run_pjc wrapper output)
    size = try_get(result, "intersection_size", "size", default=None)
    total = try_get(result, "intersection_sum", "sum", default=None)

    # Some wrappers may nest payloads
    if size is None or total is None:
        payload = try_get(result, "result", "output", "metrics", default={})
        if isinstance(payload, dict):
            if size is None:
                size = try_get(payload, "intersection_size", "size", default=None)
            if total is None:
                total = try_get(payload, "intersection_sum", "sum", default=None)

    # Cast to int if possible
    def to_int(x):
        if x is None:
            return None
        try:
            return int(x)
        except Exception:
            return None

    return {
        "intersection_size": to_int(size),
        "intersection_sum": to_int(total),
    }


def apply_policy(
    metrics: Dict[str, Optional[int]],
    threshold_k: int,
    round_sum_to: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Minimal release policy:
      - Release only if intersection_size >= threshold_k
      - Optional rounding for sum (e.g., 10 / 100) to reduce granularity leakage
    """
    size = metrics.get("intersection_size")
    total = metrics.get("intersection_sum")

    if size is None or total is None:
        return {
            "decision": "deny",
            "reason": "missing_required_metrics",
            "released": None,
        }

    if size < threshold_k:
        return {
            "decision": "deny",
            "reason": f"intersection_size_below_threshold({size} < {threshold_k})",
            "released": None,
        }

    released_sum = total
    if round_sum_to is not None and round_sum_to > 1:
        released_sum = int(round(total / round_sum_to) * round_sum_to)

    return {
        "decision": "allow",
        "reason": "threshold_passed",
        "released": {
            "intersection_size": size,
            "intersection_sum": released_sum,
        },
    }


def append_audit_log(audit_log_path: str, record: Dict[str, Any]) -> None:
    ensure_dir(os.path.dirname(audit_log_path) or ".")
    with open(audit_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser(description="W2 policy release for PJC outputs")
    ap.add_argument(
        "--input",
        required=True,
        help="Path to PJC output JSON (e.g., runs/<job_id>/attribution_result.json)",
    )
    ap.add_argument(
        "--out",
        required=True,
        help="Output release JSON path (e.g., runs/<job_id>/release.json)",
    )
    ap.add_argument(
        "--threshold-k",
        type=int,
        default=100,
        help="Minimum intersection_size required for release",
    )
    ap.add_argument(
        "--round-sum-to",
        type=int,
        default=None,
        help="Optional rounding granularity for released intersection_sum (e.g., 10, 100)",
    )
    ap.add_argument(
        "--audit-log",
        default="runs/audit_log.jsonl",
        help="Append-only audit log path (.jsonl)",
    )
    ap.add_argument(
        "--query-id",
        default=None,
        help="Optional query/job identifier for audit tracing",
    )
    ap.add_argument(
        "--policy-version",
        default="w2-min-v1",
        help="Policy version label for auditing",
    )
    args = ap.parse_args()

    result = load_json(args.input)
    metrics = parse_pjc_result(result)

    policy_out = apply_policy(
        metrics=metrics,
        threshold_k=args.threshold_k,
        round_sum_to=args.round_sum_to,
    )

    released = policy_out["released"]

        # If amount mode uses cents internally, present euros in output.
        # We detect "amount mode" by assuming intersection_sum is in cents (as produced by your prep_inputs amount path).
    if released is not None and "intersection_sum" in released:
        cents = released["intersection_sum"]
        released = {
            **released,
            "intersection_sum_cents": cents,           # keep raw cents for trace/debug
            "intersection_sum_eur": cents_to_eur_str(cents),  # display
        }
        # If you want the *main* field to be euros:
        released["intersection_sum"] = released["intersection_sum_eur"]

    release_doc = {
        "schema": "policy_release_result/v1",
        "generated_at_utc": utc_now_iso(),
        "policy_version": args.policy_version,
        "input_file": os.path.abspath(args.input),
        "threshold_k": args.threshold_k,
        "round_sum_to": args.round_sum_to,
        "decision": policy_out["decision"],
        "reason": policy_out["reason"],
        "released": released,
    }

    ensure_dir(os.path.dirname(args.out) or ".")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(release_doc, f, ensure_ascii=False, indent=2)

    audit_record = {
        "ts_utc": utc_now_iso(),
        "event": "policy_release",
        "policy_version": args.policy_version,
        "query_id": args.query_id,
        "input_file": os.path.abspath(args.input),
        "input_sha256": sha256_file(args.input),
        "threshold_k": args.threshold_k,
        "round_sum_to": args.round_sum_to,
        "parsed_metrics": metrics,
        "decision": policy_out["decision"],
        "reason": policy_out["reason"],
        "released": released,
        "release_file": os.path.abspath(args.out),
    }
    append_audit_log(args.audit_log, audit_record)

    print(f"[ok] release file: {os.path.abspath(args.out)}")
    print(f"[ok] audit log appended: {os.path.abspath(args.audit_log)}")
    print(json.dumps(release_doc, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()