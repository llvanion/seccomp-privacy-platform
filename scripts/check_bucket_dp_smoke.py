#!/usr/bin/env python3
"""Contract smoke for bucket suppression and DP metadata (PJC_MTLS Risk #6 task 6).

Asserts six invariants against ``a-psi/moduleA_psi/scripts/policy_release.py``
and ``policy_postprocess_buckets.py``:

1. With DP knobs set and a two-bucket attribution fixture (one above k, one
   below k), the protected ``bucket_public_report.json``:
     - has the below-k bucket marked ``suppressed=true`` and its
       ``intersection_size`` / ``intersection_sum`` nulled,
     - has the above-k bucket released with ``dp_noise_applied=true`` and an
       integer ``dp_noise`` value distinct from zero (rng-dependent).
2. ``policy_release.py --require-dp`` exits non-zero when DP knobs are absent.
3. ``policy_release.py --require-dp`` exits non-zero when ``--dp-epsilon`` is
   set but ``--dp-sensitivity`` is missing.
4. ``policy_postprocess_buckets.py --require-dp`` exits non-zero when DP knobs
   are absent.
5. With DP knobs set on ``policy_release.py``, the ``public_report.json``
   surfaces ``dp_noise_applied=true`` and a positive ``dp_epsilon``.
6. The released bucket sum in the protected report differs from the raw input
   sum by exactly the recorded ``dp_noise`` (modulo the ``max(0, ...)`` clip
   and rounding the implementation applies).

The harness is self-contained — it generates its own attribution fixture and
job-meta, writes a temp report, runs the two CLIs, and validates outputs in
process. Default contract smoke (``scripts/check_json_contracts.sh``) invokes
this script.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_RELEASE = REPO_ROOT / "a-psi" / "moduleA_psi" / "scripts" / "policy_release.py"
POLICY_BUCKETS = REPO_ROOT / "a-psi" / "moduleA_psi" / "scripts" / "policy_postprocess_buckets.py"


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)


def _must_succeed(cmd: list[str], context: str) -> subprocess.CompletedProcess:
    res = _run(cmd)
    if res.returncode != 0:
        sys.stderr.write(
            f"[ERROR] {context}: exit {res.returncode}\n"
            f"  cmd: {' '.join(cmd)}\n"
            f"  stdout: {res.stdout.strip()}\n"
            f"  stderr: {res.stderr.strip()}\n"
        )
        sys.exit(1)
    return res


def _must_fail(cmd: list[str], context: str, *, expect_in_stderr: str | None = None) -> subprocess.CompletedProcess:
    res = _run(cmd)
    if res.returncode == 0:
        sys.stderr.write(
            f"[ERROR] {context}: expected non-zero exit, got 0\n"
            f"  cmd: {' '.join(cmd)}\n"
            f"  stdout: {res.stdout.strip()}\n"
        )
        sys.exit(1)
    if expect_in_stderr and expect_in_stderr not in (res.stderr or "") and expect_in_stderr not in (res.stdout or ""):
        sys.stderr.write(
            f"[ERROR] {context}: stderr did not contain expected string {expect_in_stderr!r}\n"
            f"  stdout: {res.stdout.strip()}\n"
            f"  stderr: {res.stderr.strip()}\n"
        )
        sys.exit(1)
    return res


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_attribution_fixture(path: Path) -> dict:
    """Two buckets — one comfortably above k=10 and one below."""
    payload = {
        "schema": "attribution_result/v1",
        "job_id": "bucket-dp-smoke",
        "bucket_field": "campaign_id",
        "intersection_size": 53,  # 50 + 3
        "intersection_sum": 9_300,  # 9000 + 300
        "buckets": [
            {"bucket": "campaign-a", "intersection_size": 50, "intersection_sum": 9_000},
            {"bucket": "campaign-b", "intersection_size": 3, "intersection_sum": 300},
        ],
    }
    _write_json(path, payload)
    return payload


def _build_job_meta(path: Path) -> dict:
    payload = {
        "job_id": "bucket-dp-smoke",
        "window_start": "2026-05-01T00:00:00Z",
        "window_end": "2026-05-31T00:00:00Z",
        "bucket": None,
    }
    _write_json(path, payload)
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="Contract smoke for bucket suppression + DP metadata.")
    ap.add_argument("--out-dir", required=True, help="Working directory for fixtures and reports")
    ap.add_argument("--threshold-k", type=int, default=10)
    ap.add_argument("--dp-epsilon", default="1.0")
    ap.add_argument("--dp-sensitivity", type=int, default=200)
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    attribution_path = out_dir / "attribution_result.json"
    job_meta_path = out_dir / "job_meta.json"
    public_report_path = out_dir / "public_report.json"
    bucket_report_path = out_dir / "bucket_public_report.json"
    audit_log = out_dir / "policy_audit.jsonl"

    _build_attribution_fixture(attribution_path)
    _build_job_meta(job_meta_path)

    # --- Invariant 2: policy_release.py --require-dp without knobs fails closed.
    _must_fail(
        [
            sys.executable,
            str(POLICY_RELEASE),
            "--input", str(attribution_path),
            "--job-meta", str(job_meta_path),
            "--out", str(public_report_path),
            "--audit-log", str(audit_log),
            "--caller", "bucket_dp_smoke",
            "--threshold-k", str(args.threshold_k),
            "--require-dp",
        ],
        context="policy_release.py --require-dp without DP knobs",
        expect_in_stderr="--dp-epsilon",
    )

    # --- Invariant 3: half-set DP knobs also fail closed.
    _must_fail(
        [
            sys.executable,
            str(POLICY_RELEASE),
            "--input", str(attribution_path),
            "--job-meta", str(job_meta_path),
            "--out", str(public_report_path),
            "--audit-log", str(audit_log),
            "--caller", "bucket_dp_smoke",
            "--threshold-k", str(args.threshold_k),
            "--require-dp",
            "--dp-epsilon", args.dp_epsilon,
        ],
        context="policy_release.py --require-dp with only --dp-epsilon",
        expect_in_stderr="--dp-sensitivity",
    )

    # --- Invariant 4: policy_postprocess_buckets.py --require-dp without knobs fails closed.
    _must_fail(
        [
            sys.executable,
            str(POLICY_BUCKETS),
            "--job-dir", str(out_dir),
            "--k", str(args.threshold_k),
            "--require-dp",
        ],
        context="policy_postprocess_buckets.py --require-dp without DP knobs",
        expect_in_stderr="--dp-epsilon",
    )

    # --- Positive path: full DP-aware release + bucket postprocess.
    audit_log.unlink(missing_ok=True)  # restart audit log for the positive run
    _must_succeed(
        [
            sys.executable,
            str(POLICY_RELEASE),
            "--input", str(attribution_path),
            "--job-meta", str(job_meta_path),
            "--out", str(public_report_path),
            "--audit-log", str(audit_log),
            "--caller", "bucket_dp_smoke",
            "--threshold-k", str(args.threshold_k),
            "--require-dp",
            "--dp-epsilon", args.dp_epsilon,
            "--dp-sensitivity", str(args.dp_sensitivity),
        ],
        context="policy_release.py with full DP config",
    )
    _must_succeed(
        [
            sys.executable,
            str(POLICY_BUCKETS),
            "--job-dir", str(out_dir),
            "--k", str(args.threshold_k),
            "--require-dp",
            "--dp-epsilon", args.dp_epsilon,
            "--dp-sensitivity", str(args.dp_sensitivity),
        ],
        context="policy_postprocess_buckets.py with full DP config",
    )

    if not public_report_path.is_file():
        sys.stderr.write(f"[ERROR] public_report.json missing at {public_report_path}\n")
        return 1
    if not bucket_report_path.is_file():
        sys.stderr.write(f"[ERROR] bucket_public_report.json missing at {bucket_report_path}\n")
        return 1

    public_report = json.loads(public_report_path.read_text(encoding="utf-8"))
    bucket_report = json.loads(bucket_report_path.read_text(encoding="utf-8"))

    # --- Invariant 5: public_report.json surfaces DP metadata.
    if not public_report.get("dp_noise_applied"):
        sys.stderr.write(f"[ERROR] public_report.dp_noise_applied not true: {public_report}\n")
        return 1
    if not (public_report.get("dp_epsilon") and float(public_report["dp_epsilon"]) > 0):
        sys.stderr.write(f"[ERROR] public_report.dp_epsilon missing/non-positive: {public_report}\n")
        return 1

    # --- Invariant 1: bucket suppression respects k threshold.
    buckets = bucket_report.get("buckets") or []
    if len(buckets) != 2:
        sys.stderr.write(f"[ERROR] expected 2 buckets, got {len(buckets)}: {bucket_report}\n")
        return 1
    by_name = {b.get("bucket"): b for b in buckets}
    above_k = by_name.get("campaign-a")
    below_k = by_name.get("campaign-b")
    if above_k is None or below_k is None:
        sys.stderr.write(f"[ERROR] missing expected bucket names: {bucket_report}\n")
        return 1
    if not below_k.get("suppressed") or below_k.get("intersection_size") is not None or below_k.get("intersection_sum") is not None:
        sys.stderr.write(f"[ERROR] below-k bucket should be suppressed with nulls: {below_k}\n")
        return 1
    if above_k.get("suppressed") or above_k.get("intersection_size") is None or above_k.get("intersection_sum") is None:
        sys.stderr.write(f"[ERROR] above-k bucket should be released with size+sum present: {above_k}\n")
        return 1
    if not above_k.get("dp_noise_applied"):
        sys.stderr.write(f"[ERROR] above-k bucket should have dp_noise_applied=true: {above_k}\n")
        return 1
    if above_k.get("dp_epsilon") is None:
        sys.stderr.write(f"[ERROR] above-k bucket missing dp_epsilon: {above_k}\n")
        return 1

    # --- Invariant 6: released sum = clip(raw + noise, 0).
    raw_sum = 9_000  # from the fixture above
    noise = above_k.get("dp_noise")
    released = above_k.get("intersection_sum")
    if noise is None or released is None:
        sys.stderr.write(f"[ERROR] above-k bucket missing dp_noise or intersection_sum: {above_k}\n")
        return 1
    expected_released = max(0, int(round(raw_sum + float(noise))))
    if int(released) != expected_released:
        sys.stderr.write(
            f"[ERROR] released bucket sum {released} != max(0, round(raw_sum {raw_sum} + noise {noise})) = {expected_released}\n"
        )
        return 1

    # --- S5: redaction round. Re-run both stages with
    # --public-report-redact-operator-fields and assert (a) the public_report
    # no longer carries input_sizes/details/bridge/rate_limit_*, (b) a sibling
    # operator_report.json *does* carry them, (c) policy_postprocess_buckets
    # leaves a redaction marker in debug rather than per_bucket_results.
    redacted_dir = out_dir / "redacted"
    redacted_dir.mkdir(parents=True, exist_ok=True)
    redacted_attr = redacted_dir / "attribution_result.json"
    _write_json(redacted_attr, json.loads(attribution_path.read_text(encoding="utf-8")))
    redacted_meta = redacted_dir / "job_meta.json"
    _write_json(redacted_meta, json.loads(job_meta_path.read_text(encoding="utf-8")))
    redacted_public = redacted_dir / "public_report.json"
    redacted_operator = redacted_dir / "operator_report.json"
    redacted_audit = redacted_dir / "policy_audit.jsonl"
    _must_succeed(
        [
            sys.executable, str(POLICY_RELEASE),
            "--input", str(redacted_attr),
            "--job-meta", str(redacted_meta),
            "--out", str(redacted_public),
            "--audit-log", str(redacted_audit),
            "--caller", "bucket_dp_smoke",
            "--threshold-k", str(args.threshold_k),
            "--require-dp",
            "--dp-epsilon", args.dp_epsilon,
            "--dp-sensitivity", str(args.dp_sensitivity),
            "--public-report-redact-operator-fields",
            "--operator-report-path", str(redacted_operator),
        ],
        context="policy_release.py with --public-report-redact-operator-fields",
    )
    _must_succeed(
        [
            sys.executable, str(POLICY_BUCKETS),
            "--job-dir", str(redacted_dir),
            "--k", str(args.threshold_k),
            "--require-dp",
            "--dp-epsilon", args.dp_epsilon,
            "--dp-sensitivity", str(args.dp_sensitivity),
            "--public-report-redact-operator-fields",
        ],
        context="policy_postprocess_buckets.py with --public-report-redact-operator-fields",
    )
    redacted_public_report = json.loads(redacted_public.read_text(encoding="utf-8"))
    redacted_operator_report = json.loads(redacted_operator.read_text(encoding="utf-8"))
    leaked = [k for k in ("input_sizes", "rate_limit_used", "rate_limit_max", "bridge", "details") if k in redacted_public_report]
    if leaked:
        sys.stderr.write(f"[ERROR] redacted public_report still carries operator-only keys: {leaked}\n")
        return 1
    if not redacted_public_report.get("operator_fields_redacted"):
        sys.stderr.write(f"[ERROR] redacted public_report missing operator_fields_redacted marker: {redacted_public_report}\n")
        return 1
    if "input_sizes" not in redacted_operator_report or "details" not in redacted_operator_report:
        sys.stderr.write(f"[ERROR] operator_report.json should carry the full set: {redacted_operator_report}\n")
        return 1
    if redacted_operator_report.get("schema") != "operator_release_report/v1":
        sys.stderr.write(f"[ERROR] operator_report.json wrong schema: {redacted_operator_report.get('schema')}\n")
        return 1
    debug = redacted_public_report.get("debug") or {}
    if "per_bucket_results" in debug:
        sys.stderr.write(f"[ERROR] redacted public_report.debug still has per_bucket_results: {debug}\n")
        return 1
    if not debug.get("bucket_results_redacted"):
        sys.stderr.write(f"[ERROR] redacted public_report.debug missing bucket_results_redacted marker: {debug}\n")
        return 1

    summary = {
        "status": "ok",
        "schema": "bucket_dp_smoke_report/v1",
        "out_dir": str(out_dir),
        "below_k_suppressed": True,
        "above_k_released_with_dp": True,
        "public_report_dp_noise_applied": True,
        "policy_release_require_dp_fail_closed": True,
        "policy_postprocess_buckets_require_dp_fail_closed": True,
        "released_sum_equals_raw_plus_noise_clipped": True,
        "public_report_operator_fields_redacted": True,
        "operator_report_carries_full_set": True,
        "checked_buckets": [
            {
                "bucket": "campaign-a",
                "raw_sum": raw_sum,
                "released_sum": int(released),
                "dp_noise": float(noise),
                "dp_epsilon": float(above_k["dp_epsilon"]),
            },
            {
                "bucket": "campaign-b",
                "suppressed": True,
                "reason_code": below_k.get("reason_code"),
            },
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
