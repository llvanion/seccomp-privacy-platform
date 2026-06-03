#!/usr/bin/env python3
"""
S4 PJC preflight gate.

Estimates input rows / bytes / memory / streaming-frame count from the
server and client CSV inputs and rejects the job before launch when any
configured limit would be exceeded. Emits `pjc_preflight/v1`.

Usage:
  python3 scripts/preflight_pjc_job.py \
    --resource-limits config/pjc_resource_limits.example.json \
    --server-csv tmp/bridge_job/server.csv \
    --client-csv tmp/bridge_job/client.csv \
    --caller auto_demo --tenant-id t1 --dataset-id d1 --purpose bridge_token \
    --job-id <job> \
    --transport-mode streaming_grpc \
    --chunk-size-elements 4096 \
    --output tmp/pjc_preflight.json \
    --assert-allow
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PREFLIGHT_SCHEMA = "pjc_preflight/v1"
LIMITS_SCHEMA = "pjc_resource_limits/v1"
DEFAULT_BYTES_PER_ROW = 192          # bridge-ready row, conservative upper bound
DEFAULT_MEMORY_FACTOR = 4.0          # peak memory ≈ N · sizeof(row) · factor


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json_object(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_csv_rows(path: str) -> int:
    """Count non-empty rows in bridge-ready PJC CSV files, which have no header."""
    rows = 0
    with open(path, "rb") as fh:
        for line in fh:
            if line.strip():
                rows += 1
    return rows


def _summarize_client_csv_values(path: str) -> dict[str, Any]:
    values: list[int] = []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for row_no, row in enumerate(csv.reader(fh), start=1):
            if not row:
                continue
            if len(row) < 2:
                raise ValueError(f"client CSV row {row_no} missing value column")
            try:
                values.append(int(str(row[1]).strip()))
            except ValueError as exc:
                raise ValueError(f"client CSV row {row_no} value is not an integer: {row[1]!r}") from exc
    return {
        "sum": sum(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "non_negative": all(value >= 0 for value in values),
    }


def _normalize_value_policy(policy: Any, *, value_mode: Any) -> dict[str, Any] | None:
    if policy is None:
        if value_mode == "raw_int":
            return {"min_value": 0, "max_value": None, "allow_negative": False}
        return None
    if not isinstance(policy, dict):
        raise ValueError("client value_policy must be an object or null")
    min_value = policy.get("min_value")
    max_value = policy.get("max_value")
    allow_negative = bool(policy.get("allow_negative", False))
    for label, value in (("min_value", min_value), ("max_value", max_value)):
        if value is not None and not isinstance(value, int):
            raise ValueError(f"client value_policy.{label} must be an integer or null")
    if min_value is not None and max_value is not None and min_value > max_value:
        raise ValueError("client value_policy min_value > max_value")
    if not allow_negative and min_value is not None and min_value < 0:
        raise ValueError("client value_policy min_value is negative while allow_negative=false")
    return {"min_value": min_value, "max_value": max_value, "allow_negative": allow_negative}


def _value_policy_findings(
    *,
    policy: dict[str, Any],
    actual_summary: dict[str, Any],
    expected_summary: Any,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not isinstance(expected_summary, dict):
        findings.append({
            "kind": "value_policy_violation",
            "message": "input commitment client.value_summary must be an object",
            "expected": "value_summary object",
            "actual": expected_summary,
        })
    else:
        for field in ("sum", "min", "max", "non_negative"):
            if actual_summary.get(field) != expected_summary.get(field):
                findings.append({
                    "kind": "value_policy_violation",
                    "message": f"client value_summary.{field} does not match client CSV",
                    "expected": expected_summary.get(field),
                    "actual": actual_summary.get(field),
                })
                break
    if not policy["allow_negative"] and actual_summary.get("non_negative") is False:
        findings.append({
            "kind": "value_policy_violation",
            "message": "client CSV contains negative values but value_policy.allow_negative=false",
            "expected": "non-negative values",
            "actual": actual_summary,
        })
    min_value = policy.get("min_value")
    max_value = policy.get("max_value")
    actual_min = actual_summary.get("min")
    actual_max = actual_summary.get("max")
    if min_value is not None and actual_min is not None and actual_min < min_value:
        findings.append({
            "kind": "value_policy_violation",
            "message": f"client CSV minimum {actual_min} is below value_policy.min_value {min_value}",
            "expected": min_value,
            "actual": actual_min,
        })
    if max_value is not None and actual_max is not None and actual_max > max_value:
        findings.append({
            "kind": "value_policy_violation",
            "message": f"client CSV maximum {actual_max} is above value_policy.max_value {max_value}",
            "expected": max_value,
            "actual": actual_max,
        })
    return findings


def _compare_input_commitment_to_job_meta(
    *,
    commitment: dict[str, Any],
    job_meta: dict[str, Any],
    commitment_sha256: str,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def add(message: str, expected: Any, actual: Any) -> None:
        findings.append({
            "kind": "input_commitment_mismatch",
            "message": message,
            "expected": expected,
            "actual": actual,
        })

    bridge = job_meta.get("bridge")
    if not isinstance(bridge, dict):
        add("job_meta bridge section is missing", "bridge object", bridge)
        return findings

    inputs = job_meta.get("inputs") if isinstance(job_meta.get("inputs"), dict) else {}
    expected_commitment_sha256 = inputs.get("input_commitment_sha256")
    if expected_commitment_sha256 and expected_commitment_sha256 != commitment_sha256:
        add(
            "input commitment sha256 does not match job_meta",
            expected_commitment_sha256,
            commitment_sha256,
        )

    for field in (
        "job_id",
        "token_scheme",
        "token_scope",
        "token_key_version",
        "normalize_version",
        "normalizer_schema_version",
        "dedup_policy",
    ):
        expected = job_meta.get("job_id") if field == "job_id" else bridge.get(field)
        if commitment.get(field) != expected:
            add(
                f"input commitment {field} does not match job_meta",
                expected,
                commitment.get(field),
            )

    sizes = job_meta.get("input_sizes") if isinstance(job_meta.get("input_sizes"), dict) else {}
    parties = commitment.get("parties") if isinstance(commitment.get("parties"), dict) else {}
    role_sizes = {
        "server": sizes.get("exposure_n"),
        "client": sizes.get("purchase_n"),
    }
    for role in ("server", "client"):
        party = parties.get(role)
        if not isinstance(party, dict):
            continue
        bridge_role = bridge.get(role)
        if not isinstance(bridge_role, dict):
            add(f"job_meta bridge.{role} section is missing", f"{role} object", bridge_role)
            continue
        expected_rows = role_sizes[role]
        if expected_rows is not None and party.get("output_row_count") != expected_rows:
            add(
                f"input commitment {role}.output_row_count does not match job_meta",
                expected_rows,
                party.get("output_row_count"),
            )
        for field in ("input_file", "input_format", "join_key_column", "normalizer"):
            expected = bridge_role.get(field)
            if expected is not None and party.get(field) != expected:
                add(
                    f"input commitment {role}.{field} does not match job_meta",
                    expected,
                    party.get(field),
                )
        if role == "client":
            for field in ("value_column", "value_mode"):
                expected = bridge_role.get(field)
                if party.get(field) != expected:
                    add(
                        f"input commitment client.{field} does not match job_meta",
                        expected,
                        party.get(field),
                    )
            try:
                commitment_policy = _normalize_value_policy(
                    party.get("value_policy"),
                    value_mode=party.get("value_mode"),
                )
                meta_policy = _normalize_value_policy(
                    bridge_role.get("value_policy"),
                    value_mode=bridge_role.get("value_mode"),
                )
            except ValueError as exc:
                add(str(exc), "valid client value policy", party.get("value_policy"))
            else:
                if commitment_policy != meta_policy:
                    add(
                        "input commitment client.value_policy does not match job_meta",
                        meta_policy,
                        commitment_policy,
                    )

    return findings


def _scope_match(rule: dict[str, Any], scope: dict[str, Any]) -> bool:
    match = rule.get("match") or {}
    if not isinstance(match, dict):
        return False
    if str(match.get("caller") or "").strip() != scope["caller"]:
        return False
    for field in ("tenant_id", "dataset_id", "purpose"):
        configured = match.get(field)
        if configured is None or configured == "*":
            continue
        if configured != scope[field]:
            return False
    return True


def _resolve_limits(
    config: dict[str, Any], scope: dict[str, Any]
) -> tuple[Optional[int], dict[str, Any]]:
    default = config.get("default") or {}
    if not isinstance(default, dict):
        default = {}
    base = {
        "max_input_rows": int(default.get("max_input_rows", 0)),
        "max_input_bytes": int(default.get("max_input_bytes", 0)),
        "max_estimated_memory_mb": int(default.get("max_estimated_memory_mb", 0)),
        "max_frame_count": int(default.get("max_frame_count", 0)),
        "timeout_sec": int(default.get("timeout_sec", 0)),
        "estimated_bytes_per_row": int(
            default.get("estimated_bytes_per_row", DEFAULT_BYTES_PER_ROW)
        ),
        "estimated_memory_factor": float(
            default.get("estimated_memory_factor", DEFAULT_MEMORY_FACTOR)
        ),
    }
    scopes = config.get("scopes") or []
    if not isinstance(scopes, list):
        scopes = []
    for idx, rule in enumerate(scopes):
        if not isinstance(rule, dict):
            continue
        if _scope_match(rule, scope):
            limits = rule.get("limits") or {}
            effective = dict(base)
            for k in (
                "max_input_rows",
                "max_input_bytes",
                "max_estimated_memory_mb",
                "max_frame_count",
                "timeout_sec",
                "estimated_bytes_per_row",
            ):
                if k in limits:
                    effective[k] = int(limits[k])
            if "estimated_memory_factor" in limits:
                effective["estimated_memory_factor"] = float(limits["estimated_memory_factor"])
            return idx, effective
    return None, base


def _estimate_bytes(rows: int, file_path: Optional[str], bytes_per_row: int) -> int:
    if file_path and os.path.exists(file_path):
        return os.path.getsize(file_path)
    return rows * bytes_per_row


def _validate_input_commitment(
    *,
    path: Optional[str],
    job_meta_path: Optional[str],
    require: bool,
    job_id: str,
    server_csv: Optional[str],
    client_csv: Optional[str],
    server_rows: int,
    client_rows: int,
) -> tuple[Optional[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    if not path:
        if require:
            findings.append({
                "kind": "missing_input_commitment",
                "message": "input commitment is required before PJC launch",
                "expected": "pjc_input_commitment/v1 file",
                "actual": None,
            })
        return None, findings
    if not os.path.isfile(path):
        findings.append({
            "kind": "missing_input_commitment",
            "message": f"input commitment not found: {path}",
            "expected": "readable file",
            "actual": path,
        })
        return None, findings
    commitment = _load_json_object(path)
    summary: dict[str, Any] = {
        "file": os.path.abspath(path),
        "sha256": _sha256_file(path),
        "job_id": commitment.get("job_id"),
    }
    if job_meta_path:
        if not os.path.isfile(job_meta_path):
            findings.append({
                "kind": "input_commitment_mismatch",
                "message": f"job_meta not found: {job_meta_path}",
                "expected": "readable bridge_job_meta/v1 file",
                "actual": job_meta_path,
            })
        else:
            summary["job_meta_file"] = os.path.abspath(job_meta_path)
            summary["job_meta_sha256"] = _sha256_file(job_meta_path)
            try:
                job_meta = _load_json_object(job_meta_path)
            except ValueError as exc:
                findings.append({
                    "kind": "input_commitment_mismatch",
                    "message": str(exc),
                    "expected": "bridge_job_meta/v1 object",
                    "actual": job_meta_path,
                })
            else:
                if job_meta.get("schema") not in (None, "bridge_job_meta/v1"):
                    findings.append({
                        "kind": "input_commitment_mismatch",
                        "message": f"unsupported job_meta schema: {job_meta.get('schema')}",
                        "expected": "bridge_job_meta/v1",
                        "actual": job_meta.get("schema"),
                    })
                findings.extend(_compare_input_commitment_to_job_meta(
                    commitment=commitment,
                    job_meta=job_meta,
                    commitment_sha256=summary["sha256"],
                ))
    if commitment.get("schema") != "pjc_input_commitment/v1":
        findings.append({
            "kind": "input_commitment_mismatch",
            "message": f"unsupported input commitment schema: {commitment.get('schema')}",
            "expected": "pjc_input_commitment/v1",
            "actual": commitment.get("schema"),
        })
    if commitment.get("job_id") != job_id:
        findings.append({
            "kind": "input_commitment_mismatch",
            "message": "input commitment job_id does not match preflight job_id",
            "expected": job_id,
            "actual": commitment.get("job_id"),
        })
    parties = commitment.get("parties") if isinstance(commitment.get("parties"), dict) else {}
    for role, csv_path, row_count in (
        ("server", server_csv, server_rows),
        ("client", client_csv, client_rows),
    ):
        party = parties.get(role)
        if not isinstance(party, dict):
            findings.append({
                "kind": "input_commitment_mismatch",
                "message": f"input commitment missing {role} party",
                "expected": role,
                "actual": None,
            })
            continue
        if csv_path and os.path.isfile(csv_path):
            actual_hash = _sha256_file(csv_path)
            summary[f"{role}_csv_sha256"] = actual_hash
            if party.get("output_csv_sha256") != actual_hash:
                findings.append({
                    "kind": "input_commitment_mismatch",
                    "message": f"{role} CSV hash does not match input commitment",
                    "expected": party.get("output_csv_sha256"),
                    "actual": actual_hash,
                })
        if party.get("output_row_count") != row_count:
            findings.append({
                "kind": "input_commitment_mismatch",
                "message": f"{role} row count does not match input commitment",
                "expected": party.get("output_row_count"),
                "actual": row_count,
            })
        if role == "client" and csv_path and os.path.isfile(csv_path):
            try:
                policy = _normalize_value_policy(party.get("value_policy"), value_mode=party.get("value_mode"))
                if policy is not None:
                    actual_summary = _summarize_client_csv_values(csv_path)
                    summary["client_value_policy"] = policy
                    summary["client_value_summary"] = actual_summary
                    findings.extend(
                        _value_policy_findings(
                            policy=policy,
                            actual_summary=actual_summary,
                            expected_summary=party.get("value_summary"),
                        )
                    )
            except ValueError as exc:
                findings.append({
                    "kind": "value_policy_violation",
                    "message": str(exc),
                    "expected": "client CSV values satisfying input commitment policy",
                    "actual": csv_path,
                })
    return summary, findings


def evaluate(
    *,
    config: dict[str, Any],
    scope: dict[str, Any],
    server_csv: Optional[str],
    client_csv: Optional[str],
    server_rows_override: Optional[int],
    client_rows_override: Optional[int],
    transport_mode: str,
    chunk_size_elements: int,
    input_commitment_path: Optional[str],
    job_meta_path: Optional[str],
    require_input_commitment: bool,
    job_id: str,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    matched_idx, limits = _resolve_limits(config, scope)

    server_rows = server_rows_override if server_rows_override is not None else (
        _count_csv_rows(server_csv) if server_csv else 0
    )
    client_rows = client_rows_override if client_rows_override is not None else (
        _count_csv_rows(client_csv) if client_csv else 0
    )

    bytes_per_row = int(limits["estimated_bytes_per_row"])
    server_bytes = _estimate_bytes(server_rows, server_csv, bytes_per_row)
    client_bytes = _estimate_bytes(client_rows, client_csv, bytes_per_row)
    total_rows = server_rows + client_rows
    total_bytes = server_bytes + client_bytes

    estimated_memory_mb = round(
        total_bytes * float(limits["estimated_memory_factor"]) / (1024 * 1024),
        2,
    )

    if transport_mode == "streaming_grpc" and chunk_size_elements > 0:
        # Two streams (server, client); each splits its rows across frames.
        estimated_frame_count = (
            (server_rows + chunk_size_elements - 1) // chunk_size_elements
            + (client_rows + chunk_size_elements - 1) // chunk_size_elements
        )
    else:
        estimated_frame_count = 2  # one unary call per side

    if matched_idx is None and limits["max_input_rows"] == 0:
        findings.append(
            {
                "kind": "missing_resource_scope",
                "message": (
                    f"no resource scope matched caller={scope['caller']} and default max_input_rows=0; "
                    "add a scope rule before launching this job"
                ),
                "expected": "scope rule with max_input_rows > 0",
                "actual": None,
            }
        )

    def _add_finding(kind: str, message: str, expected: Any, actual: Any) -> None:
        findings.append(
            {
                "kind": kind,
                "message": message,
                "expected": expected,
                "actual": actual,
            }
        )

    if server_csv and not os.path.exists(server_csv) and server_rows_override is None:
        _add_finding(
            "missing_input_file",
            f"server CSV not found: {server_csv}",
            expected="readable file",
            actual=server_csv,
        )
    if client_csv and not os.path.exists(client_csv) and client_rows_override is None:
        _add_finding(
            "missing_input_file",
            f"client CSV not found: {client_csv}",
            expected="readable file",
            actual=client_csv,
        )

    input_commitment, commitment_findings = _validate_input_commitment(
        path=input_commitment_path,
        job_meta_path=job_meta_path,
        require=require_input_commitment,
        job_id=job_id,
        server_csv=server_csv,
        client_csv=client_csv,
        server_rows=server_rows,
        client_rows=client_rows,
    )
    findings.extend(commitment_findings)

    if limits["max_input_rows"] > 0 and total_rows > limits["max_input_rows"]:
        _add_finding(
            "input_rows_over_limit",
            f"total input rows {total_rows} > max_input_rows {limits['max_input_rows']}",
            expected=limits["max_input_rows"],
            actual=total_rows,
        )

    if limits["max_input_bytes"] > 0 and total_bytes > limits["max_input_bytes"]:
        _add_finding(
            "input_bytes_over_limit",
            f"total input bytes {total_bytes} > max_input_bytes {limits['max_input_bytes']}",
            expected=limits["max_input_bytes"],
            actual=total_bytes,
        )

    if (
        limits["max_estimated_memory_mb"] > 0
        and estimated_memory_mb > limits["max_estimated_memory_mb"]
    ):
        _add_finding(
            "estimated_memory_over_limit",
            (
                f"estimated peak memory {estimated_memory_mb}MB > "
                f"max_estimated_memory_mb {limits['max_estimated_memory_mb']}MB"
            ),
            expected=limits["max_estimated_memory_mb"],
            actual=estimated_memory_mb,
        )

    if limits["max_frame_count"] > 0 and estimated_frame_count > limits["max_frame_count"]:
        _add_finding(
            "estimated_frame_count_over_limit",
            (
                f"estimated frame count {estimated_frame_count} > "
                f"max_frame_count {limits['max_frame_count']}"
            ),
            expected=limits["max_frame_count"],
            actual=estimated_frame_count,
        )

    if findings:
        decision = "deny"
        reason_code = findings[0]["kind"]
        reason = findings[0]["message"]
    else:
        decision = "allow"
        reason_code = "ok"
        reason = None

    return {
        "schema": PREFLIGHT_SCHEMA,
        "generated_at_utc": _utc_now_iso(),
        "job_id": job_id,
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason,
        "scope": scope,
        "transport": {
            "mode": transport_mode,
            "chunk_size_elements": int(chunk_size_elements),
        },
        "input_commitment": input_commitment,
        "estimates": {
            "server_input_rows": int(server_rows),
            "client_input_rows": int(client_rows),
            "server_input_bytes": int(server_bytes),
            "client_input_bytes": int(client_bytes),
            "estimated_memory_mb": float(estimated_memory_mb),
            "estimated_frame_count": int(estimated_frame_count),
        },
        "limits": {
            "max_input_rows": int(limits["max_input_rows"]),
            "max_input_bytes": int(limits["max_input_bytes"]),
            "max_estimated_memory_mb": int(limits["max_estimated_memory_mb"]),
            "max_frame_count": int(limits["max_frame_count"]),
            "timeout_sec": int(limits["timeout_sec"]),
            "matched_scope_index": matched_idx,
        },
        "findings": findings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="S4 PJC preflight: estimate input/memory/frame count and reject before launch"
    )
    ap.add_argument("--resource-limits", required=True, help="pjc_resource_limits/v1 JSON file")
    ap.add_argument("--server-csv", default=None)
    ap.add_argument("--client-csv", default=None)
    ap.add_argument("--server-rows", type=int, default=None,
                    help="Override server row count instead of reading the CSV")
    ap.add_argument("--client-rows", type=int, default=None,
                    help="Override client row count instead of reading the CSV")
    ap.add_argument("--caller", required=True)
    ap.add_argument("--tenant-id", default=None)
    ap.add_argument("--dataset-id", default=None)
    ap.add_argument("--purpose", default=None)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--transport-mode", choices=["streaming_grpc", "unary_grpc"],
                    default="streaming_grpc")
    ap.add_argument("--chunk-size-elements", type=int, default=4096)
    ap.add_argument("--input-commitment", default=None)
    ap.add_argument("--job-meta", default=None,
                    help="Optional bridge_job_meta/v1 file used to bind commitment semantics before PJC launch")
    ap.add_argument("--require-input-commitment", action="store_true")
    ap.add_argument("--output", default="", help="Write JSON report to this path (default: stdout)")
    ap.add_argument("--assert-allow", action="store_true",
                    help="Exit non-zero if decision is not 'allow'")
    args = ap.parse_args()

    config = _load_json_object(args.resource_limits)
    if config.get("schema") != LIMITS_SCHEMA:
        raise SystemExit(f"[ERROR] resource limits config must use schema {LIMITS_SCHEMA}")

    scope = {
        "caller": args.caller,
        "tenant_id": args.tenant_id,
        "dataset_id": args.dataset_id,
        "purpose": args.purpose,
    }
    report = evaluate(
        config=config,
        scope=scope,
        server_csv=args.server_csv,
        client_csv=args.client_csv,
        server_rows_override=args.server_rows,
        client_rows_override=args.client_rows,
        transport_mode=args.transport_mode,
        chunk_size_elements=args.chunk_size_elements,
        input_commitment_path=args.input_commitment,
        job_meta_path=args.job_meta,
        require_input_commitment=args.require_input_commitment,
        job_id=args.job_id,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")
    if args.assert_allow and report["decision"] != "allow":
        print(
            f"[error] PJC preflight denied job {report['job_id']}: "
            f"{report['reason_code']}: {report['reason']}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
