#!/usr/bin/env python3
"""Contract smoke for bucket suppression and DP metadata (PJC_MTLS Risk #6 task 6).

Asserts six invariants against ``a-psi/moduleA_psi/scripts/policy_release.py``
and ``policy_postprocess_buckets.py``:

1. With DP knobs set and a two-bucket attribution fixture (one above k, one
   below k), the release-safe ``bucket_public_report.json``:
     - omits the below-k bucket label instead of publishing a
       ``suppressed=true`` existence signal,
     - redacts exact released-bucket size and DP noise while preserving the
       DP-protected released sum and coarse size bucket.
2. ``policy_release.py --require-dp`` exits non-zero when DP knobs are absent.
3. ``policy_release.py --require-dp`` exits non-zero when ``--dp-epsilon`` is
   set but ``--dp-sensitivity`` is missing.
4. ``policy_postprocess_buckets.py --require-dp`` exits non-zero when DP knobs
   are absent.
5. ``bucket_policy/v1`` is enforced before bucket postprocess: unknown bucket
   labels, bucket-field drift, and above-policy bucket counts fail closed.
6. ``run_pjc_bucketed.sh`` refuses production bucketed jobs that do not carry
   a bucket policy before it starts PJC.
7. With DP knobs set on ``policy_release.py``, the ``public_report.json``
   surfaces ``dp_noise_applied=true`` and a positive ``dp_epsilon``.
8. The operator-only bucket report records the DP noise/raw sum needed to audit
   the public released sum, but the public bucket report does not expose that
   noise.

The harness is self-contained — it generates its own attribution fixture and
job-meta, writes a temp report, runs the two CLIs, and validates outputs in
process. Default contract smoke (``scripts/check_json_contracts.sh``) invokes
this script.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_RELEASE = REPO_ROOT / "a-psi" / "moduleA_psi" / "scripts" / "policy_release.py"
POLICY_BUCKETS = REPO_ROOT / "a-psi" / "moduleA_psi" / "scripts" / "policy_postprocess_buckets.py"
BUCKET_POLICY = REPO_ROOT / "a-psi" / "moduleA_psi" / "scripts" / "bucket_policy.py"
RUN_PJC_BUCKETED = REPO_ROOT / "a-psi" / "moduleA_psi" / "scripts" / "run_pjc_bucketed.sh"


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


def _must_fail(
    cmd: list[str],
    context: str,
    *,
    expect_in_stderr: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    res = _run(cmd, env=env)
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
        "bucket": {
            "field": "campaign_id",
            "outputs": [
                {"bucket": "campaign-a"},
                {"bucket": "campaign-b"},
            ],
        },
        "bucket_policy": {
            "schema": "bucket_policy/v1",
            "bucket_field": "campaign_id",
            "allowed_bucket_fields": ["campaign_id"],
            "allowed_buckets": ["campaign-a", "campaign-b"],
            "max_buckets": 2,
            "bucket_label_pattern": r"^[A-Za-z0-9_.:-]{1,64}$",
            "require_exact_allowed_buckets": True,
            "enforcement": "fail_closed",
            "production_mode": True,
        },
    }
    _write_json(path, payload)
    return payload


def _build_minimal_public_report(path: Path) -> None:
    payload = {
        "schema": "public_report/v2",
        "job_id": "bucket-dp-smoke",
        "dp_noise_applied": True,
        "dp_epsilon": 1.0,
    }
    _write_json(path, payload)


def _copy_positive_fixture(src_dir: Path, dst_dir: Path) -> tuple[dict, dict]:
    dst_dir.mkdir(parents=True, exist_ok=True)
    attr = json.loads((src_dir / "attribution_result.json").read_text(encoding="utf-8"))
    meta = json.loads((src_dir / "job_meta.json").read_text(encoding="utf-8"))
    _write_json(dst_dir / "attribution_result.json", attr)
    _write_json(dst_dir / "job_meta.json", meta)
    _build_minimal_public_report(dst_dir / "public_report.json")
    return attr, meta


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
    operator_bucket_report_path = out_dir / "operator_bucket_report.json"
    audit_log = out_dir / "policy_audit.jsonl"

    _build_attribution_fixture(attribution_path)
    _build_job_meta(job_meta_path)

    bucket_policy_check = _must_succeed(
        [
            sys.executable,
            str(BUCKET_POLICY),
            "--job-meta", str(job_meta_path),
            "--attribution", str(attribution_path),
            "--require-policy",
        ],
        context="bucket_policy.py validates the positive fixture",
    )
    bucket_policy_check_json = json.loads(bucket_policy_check.stdout)
    bucket_policy_hash = bucket_policy_check_json.get("bucket_policy_sha256")
    if not bucket_policy_hash:
        sys.stderr.write(f"[ERROR] bucket_policy.py did not return bucket_policy_sha256: {bucket_policy_check.stdout}\n")
        return 1

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

    # --- Invariant 5: bucket policy rejects unknown labels, field drift, and
    # above-policy bucket counts before public bucket output is written.
    unknown_bucket_dir = out_dir / "bad_unknown_bucket"
    bad_attr, bad_meta = _copy_positive_fixture(out_dir, unknown_bucket_dir)
    bad_meta["bucket_policy"]["max_buckets"] = 3
    _write_json(unknown_bucket_dir / "job_meta.json", bad_meta)
    bad_attr["buckets"].append({"bucket": "campaign-x", "intersection_size": 12, "intersection_sum": 1200})
    _write_json(unknown_bucket_dir / "attribution_result.json", bad_attr)
    _must_fail(
        [
            sys.executable,
            str(POLICY_BUCKETS),
            "--job-dir", str(unknown_bucket_dir),
            "--k", str(args.threshold_k),
            "--require-dp",
            "--dp-epsilon", args.dp_epsilon,
            "--dp-sensitivity", str(args.dp_sensitivity),
        ],
        context="policy_postprocess_buckets.py rejects unknown bucket label",
        expect_in_stderr="not allowed",
    )

    field_drift_dir = out_dir / "bad_bucket_field"
    bad_attr, _ = _copy_positive_fixture(out_dir, field_drift_dir)
    bad_attr["bucket_field"] = "audience_segment"
    _write_json(field_drift_dir / "attribution_result.json", bad_attr)
    _must_fail(
        [
            sys.executable,
            str(POLICY_BUCKETS),
            "--job-dir", str(field_drift_dir),
            "--k", str(args.threshold_k),
            "--require-dp",
            "--dp-epsilon", args.dp_epsilon,
            "--dp-sensitivity", str(args.dp_sensitivity),
        ],
        context="policy_postprocess_buckets.py rejects bucket field drift",
        expect_in_stderr="does not match bucket_policy.bucket_field",
    )

    max_bucket_dir = out_dir / "bad_max_buckets"
    _, bad_meta = _copy_positive_fixture(out_dir, max_bucket_dir)
    bad_meta["bucket_policy"]["max_buckets"] = 1
    _write_json(max_bucket_dir / "job_meta.json", bad_meta)
    _must_fail(
        [
            sys.executable,
            str(BUCKET_POLICY),
            "--job-meta", str(max_bucket_dir / "job_meta.json"),
            "--require-policy",
        ],
        context="bucket_policy.py rejects above-policy bucket count",
        expect_in_stderr="exceeds bucket_policy.max_buckets",
    )

    missing_policy_dir = out_dir / "missing_policy"
    missing_policy_dir.mkdir(parents=True, exist_ok=True)
    missing_meta = json.loads(job_meta_path.read_text(encoding="utf-8"))
    missing_meta.pop("bucket_policy", None)
    _write_json(missing_policy_dir / "job_meta.json", missing_meta)
    _must_fail(
        [
            "bash",
            str(RUN_PJC_BUCKETED),
        ],
        context="run_pjc_bucketed.sh requires bucket policy in production mode",
        expect_in_stderr="job_meta.bucket_policy is required",
        env={
            **os.environ,
            "JOB_DIR": str(missing_policy_dir),
            "PJC_REQUIRE_BUCKET_POLICY": "1",
        },
    )

    shard_manifest = {
        "schema": "job_shard_meta/v1",
        "job_id": "bucket-dp-smoke",
        "num_shards": 2,
        "salt": "smoke",
        "targets": [
            {"bucket": "campaign-a", "dir": "bucket_campaign-a", "shards": [{"shard_id": 0}, {"shard_id": 1}]},
            {"bucket": "campaign-b", "dir": "bucket_campaign-b", "shards": [{"shard_id": 0}, {"shard_id": 1}]},
        ],
    }
    shard_meta_path = out_dir / "job_shard_meta.json"
    _write_json(shard_meta_path, shard_manifest)
    shard_check = _must_succeed(
        [
            sys.executable,
            str(BUCKET_POLICY),
            "--job-meta", str(job_meta_path),
            "--shard-meta", str(shard_meta_path),
            "--require-policy",
        ],
        context="bucket_policy.py validates shard manifest against bucket policy",
    )
    shard_scope = (json.loads(shard_check.stdout).get("shard_scope") or {})
    if shard_scope.get("bucket_policy_sha256") != bucket_policy_hash or not shard_scope.get("shard_manifest_sha256"):
        sys.stderr.write(f"[ERROR] shard scope did not bind bucket policy and shard manifest hashes: {shard_check.stdout}\n")
        return 1

    bad_shard_path = out_dir / "bad_job_shard_meta.json"
    bad_shard = dict(shard_manifest)
    bad_shard["targets"] = list(shard_manifest["targets"]) + [
        {"bucket": "campaign-x", "dir": "bucket_campaign-x", "shards": [{"shard_id": 0}]}
    ]
    _write_json(bad_shard_path, bad_shard)
    _must_fail(
        [
            sys.executable,
            str(BUCKET_POLICY),
            "--job-meta", str(job_meta_path),
            "--shard-meta", str(bad_shard_path),
            "--require-policy",
        ],
        context="bucket_policy.py rejects shard target outside allowed buckets",
        expect_in_stderr="shard targets not allowed",
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
    if not operator_bucket_report_path.is_file():
        sys.stderr.write(f"[ERROR] operator_bucket_report.json missing at {operator_bucket_report_path}\n")
        return 1

    public_report = json.loads(public_report_path.read_text(encoding="utf-8"))
    bucket_report = json.loads(bucket_report_path.read_text(encoding="utf-8"))
    operator_bucket_report = json.loads(operator_bucket_report_path.read_text(encoding="utf-8"))
    for label, report in (("public bucket report", bucket_report), ("operator bucket report", operator_bucket_report)):
        policy_summary = report.get("bucket_policy") or {}
        if policy_summary.get("bucket_policy_sha256") != bucket_policy_hash:
            sys.stderr.write(
                f"[ERROR] {label} did not bind expected bucket_policy_sha256 {bucket_policy_hash}: {policy_summary}\n"
            )
            return 1

    # --- Invariant 5: public_report.json surfaces DP metadata.
    if not public_report.get("dp_noise_applied"):
        sys.stderr.write(f"[ERROR] public_report.dp_noise_applied not true: {public_report}\n")
        return 1
    if not (public_report.get("dp_epsilon") and float(public_report["dp_epsilon"]) > 0):
        sys.stderr.write(f"[ERROR] public_report.dp_epsilon missing/non-positive: {public_report}\n")
        return 1

    # --- Invariant 1: below-k bucket labels are not published.
    buckets = bucket_report.get("buckets") or []
    if len(buckets) != 1:
        sys.stderr.write(f"[ERROR] expected only released bucket in public report, got {len(buckets)}: {bucket_report}\n")
        return 1
    by_name = {b.get("bucket"): b for b in buckets}
    above_k = by_name.get("campaign-a")
    if above_k is None:
        sys.stderr.write(f"[ERROR] missing expected released bucket name: {bucket_report}\n")
        return 1
    if "campaign-b" in by_name:
        sys.stderr.write(f"[ERROR] below-k bucket label leaked in public report: {bucket_report}\n")
        return 1
    redaction = bucket_report.get("redaction") or {}
    if redaction.get("view") != "release_safe_bucket_report" or redaction.get("suppressed_bucket_labels_redacted") is not True:
        sys.stderr.write(f"[ERROR] bucket_public_report missing release-safe redaction marker: {bucket_report}\n")
        return 1
    if above_k.get("suppressed") or above_k.get("intersection_size") is not None or above_k.get("intersection_sum") is None:
        sys.stderr.write(f"[ERROR] public released bucket should redact exact size and release sum: {above_k}\n")
        return 1
    if above_k.get("intersection_size_bucket") != "50-199":
        sys.stderr.write(f"[ERROR] public released bucket missing coarse size bucket: {above_k}\n")
        return 1
    if not above_k.get("dp_noise_applied"):
        sys.stderr.write(f"[ERROR] above-k bucket should have dp_noise_applied=true: {above_k}\n")
        return 1
    if above_k.get("dp_epsilon") is None:
        sys.stderr.write(f"[ERROR] above-k bucket missing dp_epsilon: {above_k}\n")
        return 1
    if "dp_noise" in above_k:
        sys.stderr.write(f"[ERROR] public released bucket leaked dp_noise: {above_k}\n")
        return 1

    # --- Invariant 6: operator report audits released sum = clip(raw + noise, 0).
    op_buckets = operator_bucket_report.get("buckets") or []
    op_by_name = {b.get("bucket"): b for b in op_buckets}
    op_above_k = op_by_name.get("campaign-a")
    op_below_k = op_by_name.get("campaign-b")
    if op_above_k is None or op_below_k is None:
        sys.stderr.write(f"[ERROR] operator bucket report missing full bucket evidence: {operator_bucket_report}\n")
        return 1
    if not op_below_k.get("suppressed") or op_below_k.get("intersection_size") != 3:
        sys.stderr.write(f"[ERROR] operator bucket report should retain below-k evidence: {op_below_k}\n")
        return 1
    raw_sum = 9_000  # from the fixture above
    noise = op_above_k.get("dp_noise")
    released = above_k.get("intersection_sum")
    if noise is None or released is None:
        sys.stderr.write(f"[ERROR] operator/public bucket reports missing dp_noise or intersection_sum: public={above_k} operator={op_above_k}\n")
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
    redacted_bucket_public = redacted_dir / "bucket_public_report.json"
    redacted_operator_bucket = redacted_dir / "operator_bucket_report.json"
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
    redacted_bucket_report = json.loads(redacted_bucket_public.read_text(encoding="utf-8"))
    redacted_operator_bucket_report = json.loads(redacted_operator_bucket.read_text(encoding="utf-8"))
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
    if any(item.get("bucket") == "campaign-b" for item in redacted_bucket_report.get("buckets") or []):
        sys.stderr.write(f"[ERROR] redacted bucket_public_report leaked below-k label: {redacted_bucket_report}\n")
        return 1
    if any("dp_noise" in item for item in redacted_bucket_report.get("buckets") or []):
        sys.stderr.write(f"[ERROR] redacted bucket_public_report leaked dp_noise: {redacted_bucket_report}\n")
        return 1
    if not any(item.get("bucket") == "campaign-b" for item in redacted_operator_bucket_report.get("buckets") or []):
        sys.stderr.write(f"[ERROR] operator_bucket_report should retain below-k evidence: {redacted_operator_bucket_report}\n")
        return 1

    summary = {
        "status": "ok",
        "schema": "bucket_dp_smoke_report/v1",
        "out_dir": str(out_dir),
        "bucket_policy_positive_fixture_valid": True,
        "bucket_policy_unknown_bucket_denied": True,
        "bucket_policy_field_mismatch_denied": True,
        "bucket_policy_max_bucket_denied": True,
        "bucket_policy_required_before_pjc": True,
        "bucket_policy_hash_bound_to_reports": True,
        "shard_manifest_policy_hash_bound": True,
        "shard_manifest_unknown_bucket_denied": True,
        "below_k_suppressed_label_redacted": True,
        "above_k_released_with_dp": True,
        "public_report_dp_noise_applied": True,
        "policy_release_require_dp_fail_closed": True,
        "policy_postprocess_buckets_require_dp_fail_closed": True,
        "released_sum_equals_raw_plus_noise_clipped": True,
        "public_bucket_report_dp_noise_redacted": True,
        "operator_bucket_report_carries_full_set": True,
        "public_report_operator_fields_redacted": True,
        "operator_report_carries_full_set": True,
        "checked_buckets": [
            {
                "bucket": "campaign-a",
                "released_sum": int(released),
                "dp_epsilon": float(above_k["dp_epsilon"]),
                "public_size_bucket": above_k.get("intersection_size_bucket"),
            },
            {
                "bucket": "<suppressed-label-redacted>",
                "suppressed": True,
                "reason_code": "below_k",
            },
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
