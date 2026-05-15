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


def _count_csv_rows(path: str) -> int:
    """Count data rows in a CSV (excluding header). Returns 0 for empty."""
    rows = 0
    with open(path, "rb") as fh:
        # Skip header
        header = fh.readline()
        if not header:
            return 0
        for line in fh:
            if line.strip():
                rows += 1
    return rows


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
