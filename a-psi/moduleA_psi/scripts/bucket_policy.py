#!/usr/bin/env python3
"""Bucket/shard policy helpers for bucketed PJC jobs."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


DEFAULT_BUCKET_LABEL_PATTERN = r"^[A-Za-z0-9_.:-]{1,64}$"


class BucketPolicyError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise BucketPolicyError(f"{path} must contain a JSON object")
    return payload


def _normalize_label(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise BucketPolicyError(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise BucketPolicyError(f"{label} must be non-empty")
    if len(text) > 128:
        raise BucketPolicyError(f"{label} is too long")
    if not all(ch.isalnum() or ch in "_.:-" for ch in text):
        raise BucketPolicyError(f"{label} contains unsupported characters")
    return text


def _normalize_list(value: Any, label: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise BucketPolicyError(f"{label} must be a list")
    out = [_normalize_label(item, f"{label}[{idx}]") for idx, item in enumerate(value)]
    return sorted(set(out))


def _bucket_value_from_item(item: Any, label: str) -> str:
    if not isinstance(item, dict):
        raise BucketPolicyError(f"{label} must be an object")
    return _normalize_label(item.get("bucket"), f"{label}.bucket")


def _compiled_pattern(pattern: Any) -> re.Pattern[str] | None:
    if pattern in (None, ""):
        return None
    if not isinstance(pattern, str):
        raise BucketPolicyError("bucket_policy.bucket_label_pattern must be a string")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise BucketPolicyError(f"bucket_policy.bucket_label_pattern is invalid: {exc}") from exc


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_bucket_policy(
    *,
    bucket_field: str,
    bucket_values: list[str],
    allowed_bucket_fields: list[str],
    allowed_buckets: list[str],
    max_buckets: int | None,
    bucket_label_pattern: str | None,
    production_mode: bool,
) -> dict[str, Any]:
    normalized_field = _normalize_label(bucket_field, "bucket_field")
    normalized_values = [_normalize_label(value, "bucket value") for value in bucket_values]
    normalized_allowed_fields = _normalize_list(allowed_bucket_fields, "allowed_bucket_fields")
    normalized_allowed_buckets = _normalize_list(allowed_buckets, "allowed_buckets")
    if not normalized_allowed_fields:
        if production_mode:
            raise BucketPolicyError("production bucket policy requires --allowed-bucket-field")
        normalized_allowed_fields = [normalized_field]
    if normalized_field not in normalized_allowed_fields:
        raise BucketPolicyError(
            f"bucket_field {normalized_field!r} is not listed in bucket_policy.allowed_bucket_fields"
        )
    if not normalized_allowed_buckets:
        if production_mode:
            raise BucketPolicyError("production bucket policy requires --allowed-bucket")
        normalized_allowed_buckets = sorted(set(normalized_values))
    if max_buckets is None:
        if production_mode:
            raise BucketPolicyError("production bucket policy requires --max-buckets")
        max_buckets = len(normalized_values)
    if max_buckets <= 0:
        raise BucketPolicyError("bucket_policy.max_buckets must be positive")
    pattern = bucket_label_pattern or DEFAULT_BUCKET_LABEL_PATTERN
    matcher = _compiled_pattern(pattern)
    if matcher is not None:
        bad = [value for value in normalized_values if not matcher.fullmatch(value)]
        if bad:
            raise BucketPolicyError(f"bucket values do not match bucket_label_pattern: {bad}")
    if len(set(normalized_values)) > max_buckets:
        raise BucketPolicyError(
            f"bucket count {len(set(normalized_values))} exceeds bucket_policy.max_buckets {max_buckets}"
        )
    not_allowed = sorted(set(normalized_values) - set(normalized_allowed_buckets))
    if not_allowed:
        raise BucketPolicyError(f"bucket values not allowed by bucket_policy.allowed_buckets: {not_allowed}")
    missing = sorted(set(normalized_allowed_buckets) - set(normalized_values))
    if production_mode and missing:
        raise BucketPolicyError(f"bucket_policy.allowed_buckets includes buckets not generated: {missing}")
    return {
        "schema": "bucket_policy/v1",
        "bucket_field": normalized_field,
        "allowed_bucket_fields": normalized_allowed_fields,
        "allowed_buckets": sorted(set(normalized_allowed_buckets)),
        "max_buckets": int(max_buckets),
        "bucket_label_pattern": pattern,
        "require_exact_allowed_buckets": bool(production_mode),
        "enforcement": "fail_closed",
        "production_mode": bool(production_mode),
    }


def bucket_policy_sha256(policy: dict[str, Any] | None) -> str | None:
    if policy is None:
        return None
    return _canonical_sha256(policy)


def _bucket_outputs(meta: dict[str, Any]) -> tuple[str, list[str]]:
    bucket = meta.get("bucket")
    if not isinstance(bucket, dict):
        raise BucketPolicyError("job_meta.bucket must be an object")
    field = _normalize_label(bucket.get("field"), "job_meta.bucket.field")
    outputs = bucket.get("outputs")
    if not isinstance(outputs, list):
        raise BucketPolicyError("job_meta.bucket.outputs must be a list")
    values = [_bucket_value_from_item(item, f"job_meta.bucket.outputs[{idx}]") for idx, item in enumerate(outputs)]
    if not values:
        raise BucketPolicyError("job_meta.bucket.outputs must not be empty")
    return field, values


def validate_job_meta_bucket_policy(meta: dict[str, Any], *, require_policy: bool = False) -> dict[str, Any] | None:
    policy = meta.get("bucket_policy")
    if policy in (None, ""):
        if require_policy:
            raise BucketPolicyError("job_meta.bucket_policy is required")
        return None
    field, values = _bucket_outputs(meta)
    if not isinstance(policy, dict):
        raise BucketPolicyError("job_meta.bucket_policy must be an object")
    if policy.get("schema") not in (None, "bucket_policy/v1"):
        raise BucketPolicyError(f"unsupported bucket_policy schema: {policy.get('schema')!r}")
    allowed_fields = _normalize_list(policy.get("allowed_bucket_fields"), "bucket_policy.allowed_bucket_fields")
    allowed_buckets = _normalize_list(policy.get("allowed_buckets"), "bucket_policy.allowed_buckets")
    policy_field = _normalize_label(policy.get("bucket_field", field), "bucket_policy.bucket_field")
    if policy_field != field:
        raise BucketPolicyError(f"bucket_policy.bucket_field {policy_field!r} does not match job_meta bucket field {field!r}")
    if allowed_fields and field not in allowed_fields:
        raise BucketPolicyError(f"bucket field {field!r} is not allowed by bucket_policy.allowed_bucket_fields")
    max_buckets = policy.get("max_buckets")
    if max_buckets is not None:
        if not isinstance(max_buckets, int) or max_buckets <= 0:
            raise BucketPolicyError("bucket_policy.max_buckets must be a positive integer")
        if len(set(values)) > max_buckets:
            raise BucketPolicyError(f"bucket count {len(set(values))} exceeds bucket_policy.max_buckets {max_buckets}")
    matcher = _compiled_pattern(policy.get("bucket_label_pattern"))
    if matcher is not None:
        bad = [value for value in values if not matcher.fullmatch(value)]
        if bad:
            raise BucketPolicyError(f"bucket values do not match bucket_policy.bucket_label_pattern: {bad}")
    if allowed_buckets:
        not_allowed = sorted(set(values) - set(allowed_buckets))
        if not_allowed:
            raise BucketPolicyError(f"bucket values not allowed by bucket_policy.allowed_buckets: {not_allowed}")
        if policy.get("require_exact_allowed_buckets") is True:
            missing = sorted(set(allowed_buckets) - set(values))
            if missing:
                raise BucketPolicyError(f"bucket_policy.allowed_buckets missing from job outputs: {missing}")
    return {
        "schema": "bucket_policy/v1",
        "bucket_field": field,
        "allowed_bucket_fields": allowed_fields,
        "allowed_buckets": allowed_buckets,
        "max_buckets": max_buckets,
        "bucket_label_pattern": policy.get("bucket_label_pattern"),
        "require_exact_allowed_buckets": bool(policy.get("require_exact_allowed_buckets", False)),
        "enforcement": str(policy.get("enforcement") or "fail_closed"),
        "production_mode": bool(policy.get("production_mode", False)),
    }


def bucket_scope_summary(meta: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if policy is None:
        policy = validate_job_meta_bucket_policy(meta)
    if policy is None:
        return None
    field, values = _bucket_outputs(meta)
    return {
        "schema": "bucket_scope/v1",
        "bucket_field": field,
        "bucket_count": len(set(values)),
        "bucket_policy_sha256": bucket_policy_sha256(policy),
        "allowed_bucket_count": len(policy.get("allowed_buckets") or []),
        "bucket_labels_redacted": True,
        "require_exact_allowed_buckets": bool(policy.get("require_exact_allowed_buckets", False)),
        "enforcement": policy.get("enforcement") or "fail_closed",
    }


def validate_shard_bucket_policy(shard_meta: dict[str, Any], policy: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(shard_meta, dict):
        raise BucketPolicyError("job_shard_meta must be an object")
    targets = shard_meta.get("targets")
    if not isinstance(targets, list):
        raise BucketPolicyError("job_shard_meta.targets must be a list")
    target_buckets: list[str] = []
    total_shards = 0
    max_shards_per_target = 0
    for idx, target in enumerate(targets):
        if not isinstance(target, dict):
            raise BucketPolicyError(f"job_shard_meta.targets[{idx}] must be an object")
        if target.get("bucket") is not None:
            target_buckets.append(_normalize_label(target.get("bucket"), f"job_shard_meta.targets[{idx}].bucket"))
        shards = target.get("shards")
        if not isinstance(shards, list):
            raise BucketPolicyError(f"job_shard_meta.targets[{idx}].shards must be a list")
        if not shards:
            raise BucketPolicyError(f"job_shard_meta.targets[{idx}].shards must not be empty")
        total_shards += len(shards)
        max_shards_per_target = max(max_shards_per_target, len(shards))
        seen_ids: set[int] = set()
        for shard_idx, shard in enumerate(shards):
            if not isinstance(shard, dict):
                raise BucketPolicyError(f"job_shard_meta.targets[{idx}].shards[{shard_idx}] must be an object")
            shard_id = shard.get("shard_id")
            if not isinstance(shard_id, int) or shard_id < 0:
                raise BucketPolicyError(
                    f"job_shard_meta.targets[{idx}].shards[{shard_idx}].shard_id must be a non-negative integer"
                )
            if shard_id in seen_ids:
                raise BucketPolicyError(f"duplicate shard_id {shard_id} in job_shard_meta.targets[{idx}]")
            seen_ids.add(shard_id)
    if policy is not None and target_buckets:
        allowed = set(policy.get("allowed_buckets") or [])
        if allowed:
            not_allowed = sorted(set(target_buckets) - allowed)
            if not_allowed:
                raise BucketPolicyError(f"shard targets not allowed by bucket_policy.allowed_buckets: {not_allowed}")
        max_buckets = policy.get("max_buckets")
        if max_buckets is not None and len(set(target_buckets)) > int(max_buckets):
            raise BucketPolicyError(
                f"shard target bucket count {len(set(target_buckets))} exceeds bucket_policy.max_buckets {max_buckets}"
            )
        if policy.get("require_exact_allowed_buckets") is True:
            missing = sorted(allowed - set(target_buckets))
            if missing:
                raise BucketPolicyError(f"bucket_policy.allowed_buckets missing from shard targets: {missing}")
    salt = shard_meta.get("salt")
    if salt is not None:
        _normalize_label(salt, "job_shard_meta.salt")
    num_shards = shard_meta.get("num_shards")
    if not isinstance(num_shards, int) or num_shards <= 0:
        raise BucketPolicyError("job_shard_meta.num_shards must be a positive integer")
    if max_shards_per_target > num_shards:
        raise BucketPolicyError("job_shard_meta target shard count exceeds num_shards")
    return {
        "schema": "shard_scope/v1",
        "num_shards": num_shards,
        "target_count": len(targets),
        "bucket_target_count": len(set(target_buckets)),
        "total_shards": total_shards,
        "max_shards_per_target": max_shards_per_target,
        "bucket_policy_sha256": bucket_policy_sha256(policy),
        "shard_manifest_sha256": _canonical_sha256(shard_meta),
        "bucket_labels_redacted": True,
    }


def validate_attribution_bucket_policy(attr: dict[str, Any], policy: dict[str, Any] | None) -> None:
    if policy is None:
        return
    attr_field = attr.get("bucket_field")
    if attr_field != policy["bucket_field"]:
        raise BucketPolicyError(
            f"attribution bucket_field {attr_field!r} does not match bucket_policy.bucket_field {policy['bucket_field']!r}"
        )
    buckets = attr.get("buckets")
    if not isinstance(buckets, list):
        raise BucketPolicyError("attribution buckets must be a list")
    values = [_bucket_value_from_item(item, f"attribution.buckets[{idx}]") for idx, item in enumerate(buckets)]
    max_buckets = policy.get("max_buckets")
    if max_buckets is not None and len(set(values)) > int(max_buckets):
        raise BucketPolicyError(f"attribution bucket count {len(set(values))} exceeds bucket_policy.max_buckets {max_buckets}")
    allowed_buckets = policy.get("allowed_buckets") or []
    if allowed_buckets:
        not_allowed = sorted(set(values) - set(allowed_buckets))
        if not_allowed:
            raise BucketPolicyError(f"attribution buckets not allowed by bucket_policy.allowed_buckets: {not_allowed}")
    pattern = _compiled_pattern(policy.get("bucket_label_pattern"))
    if pattern is not None:
        bad = [value for value in values if not pattern.fullmatch(value)]
        if bad:
            raise BucketPolicyError(f"attribution buckets do not match bucket_policy.bucket_label_pattern: {bad}")


def public_bucket_policy_summary(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "bucket_field": policy.get("bucket_field"),
        "max_buckets": policy.get("max_buckets"),
        "bucket_policy_sha256": bucket_policy_sha256(policy),
        "allowed_bucket_count": len(policy.get("allowed_buckets") or []),
        "allowed_bucket_labels_redacted": True,
        "require_exact_allowed_buckets": bool(policy.get("require_exact_allowed_buckets", False)),
        "enforcement": policy.get("enforcement") or "fail_closed",
    }


def operator_bucket_policy_evidence(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "bucket_field": policy.get("bucket_field"),
        "bucket_policy_sha256": bucket_policy_sha256(policy),
        "allowed_bucket_fields": policy.get("allowed_bucket_fields") or [],
        "allowed_buckets": policy.get("allowed_buckets") or [],
        "max_buckets": policy.get("max_buckets"),
        "bucket_label_pattern": policy.get("bucket_label_pattern"),
        "require_exact_allowed_buckets": bool(policy.get("require_exact_allowed_buckets", False)),
        "enforcement": policy.get("enforcement") or "fail_closed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate bucket_policy/v1 inside bucketed PJC job_meta.json")
    parser.add_argument("--job-meta", required=True)
    parser.add_argument("--attribution", default="")
    parser.add_argument("--shard-meta", default="")
    parser.add_argument("--require-policy", action="store_true")
    args = parser.parse_args()
    try:
        meta = _load_json(Path(args.job_meta))
        policy = validate_job_meta_bucket_policy(meta, require_policy=args.require_policy)
        if args.attribution:
            validate_attribution_bucket_policy(_load_json(Path(args.attribution)), policy)
        shard_scope = None
        if args.shard_meta:
            shard_scope = validate_shard_bucket_policy(_load_json(Path(args.shard_meta)), policy)
    except BucketPolicyError as exc:
        raise SystemExit(f"[ERROR] {exc}") from exc
    print(json.dumps(
        {
            "schema": "bucket_policy_check/v1",
            "status": "ok",
            "policy_present": policy is not None,
            "bucket_policy_sha256": bucket_policy_sha256(policy),
            "bucket_scope": bucket_scope_summary(meta, policy) if policy else None,
            "shard_scope": shard_scope if args.shard_meta else None,
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
