#!/usr/bin/env python3
"""
Negative-test gate for JSON contract validators.

For each (schema, reference_payload) pair in CASES, this script generates a
set of purposely-broken mutations (missing required field, wrong type,
unexpected property, const/enum violation, minLength / minimum violation) and
asserts that the repo's validate_json_contract.py REJECTS every one.

Any mutation that is NOT rejected indicates the schema or validator is too
permissive — the gate exits non-zero and prints the offending case.

Output schema: malformed_input_gate/v1
"""

import copy
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).parent.parent
VALIDATOR_PY = REPO_ROOT / "scripts" / "validate_json_contract.py"
SCHEMA_DIR = REPO_ROOT / "schemas"


# ---------------------------------------------------------------------------
# Minimal valid reference payloads for each tested schema
# ---------------------------------------------------------------------------

CASES: list[tuple[str, dict[str, Any]]] = [
    (
        "platform_health/v1",
        {
            "schema": "platform_health/v1",
            "generated_at_utc": "2026-05-01T00:00:00Z",
            "repo_root": "/repo",
            "summary": {"ok": 1, "warn": 0, "error": 0, "status": "ok"},
            "checks": [{"name": "probe", "component": "test", "status": "ok"}],
        },
    ),
    (
        "schema_backcompat_check/v1",
        {
            "schema": "schema_backcompat_check/v1",
            "generated_at_utc": "2026-05-01T00:00:00Z",
            "baseline_path": "/repo/config/baseline.json",
            "checked_count": 1,
            "failed_count": 0,
            "checks": [
                {
                    "path": "/schemas/x.schema.json",
                    "schema_id": "x/v1",
                    "status": "ok",
                    "required": [],
                    "stable_properties": [],
                    "errors": [],
                }
            ],
        },
    ),
    (
        "audit_seal/v1",
        {
            "schema": "audit_seal/v1",
            "ts_utc": "2026-05-01T00:00:00Z",
            "event": "audit_seal",
            "job_id": "test-job",
            "correlation_id": "corr-1",
            "artifact_file": "/tmp/audit_chain.json",
            "artifact_sha256": "abc123",
            "signature_algorithm": None,
            "signature": None,
            "secret_source": None,
        },
    ),
    (
        "bridge_job_meta/v1",
        {
            "schema": "bridge_job_meta/v1",
            "job_id": "test-job",
            "job_type": "bridge_prepared_csv",
            "generator": "test-gen",
            "input_sizes": {"exposure_n": 1, "purchase_n": 1},
            "bridge": {
                "token_scheme": "bridge-hmac-sha256-v1",
                "token_scope": "test-scope",
                "token_key_version": "v1",
                "normalize_version": "v1",
                "normalizer_schema_version": "normalizer-schema/v1",
                "dedup_policy": "first",
                "server": {"join_key_column": "email", "normalizer": "email"},
                "client": {"join_key_column": "email", "normalizer": "identity"},
            },
            "inputs": {},
            "counts": {},
        },
    ),
    (
        "sse_bridge_export_audit/v1",
        {
            "schema": "sse_bridge_export_audit/v1",
            "ts_utc": "2026-05-01T00:00:00Z",
            "event": "sse_bridge_export",
            "caller": "test-caller",
            "role": "server",
            "decision": "allow",
            "reason_code": "ok",
            "candidate_source": "local_filter",
        },
    ),
    (
        "mainline_contract_check/v1",
        {
            "schema": "mainline_contract_check/v1",
            "generated_at_utc": "2026-05-01T00:00:00Z",
            "repo_root": "/repo",
            "out_base": "/tmp/out",
            "job_id": "test-job",
            "status": "ok",
            "canonical_scope": {
                "job_id": "test-job",
                "correlation_id": None,
                "caller": None,
                "tenant_id": None,
                "dataset_id": None,
                "service_id": None,
                "token_scope": "test-scope",
                "token_key_version": "v1",
                "policy_version": None,
            },
            "handoff_cleanup": {
                "server": {"status": "removed", "exists_after_run": False},
                "client": {"status": "cleaned", "exists_after_run": False},
            },
            "summary": {"checks_run": 0, "error_count": 0},
            "findings": [],
        },
    ),
    (
        "pipeline_observability/v1",
        {
            "schema": "pipeline_observability/v1",
            "generated_at_utc": "2026-05-01T00:00:00Z",
            "job_id": "test-job",
            "correlation_id": "corr-1",
            "caller": "test-caller",
            "tenant_id": None,
            "dataset_id": None,
            "service_id": None,
            "summary": {"event_count": 0, "by_stage": {}, "status": "ok"},
            "events": [],
        },
    ),
    (
        "audit_archive_index/v1",
        {
            "schema": "audit_archive_index/v1",
            "ts_utc": "2026-05-01T00:00:00Z",
            "event": "archive_audit_bundle",
            "job_id": "test-job",
            "correlation_id": "corr-1",
            "archive_dir": "/tmp/archive",
            "index_file": "/tmp/archive/index.jsonl",
            "source_audit_chain_file": "/tmp/audit_chain.json",
            "source_audit_seal_file": "/tmp/audit_chain.seal.json",
            "archived_audit_chain_file": "/tmp/archive/audit_chain.json",
            "archived_audit_seal_file": "/tmp/archive/seal.json",
            "audit_chain_sha256": "a" * 64,
            "audit_seal_sha256": "b" * 64,
            "artifact_sha256_verified": True,
            "signature_algorithm": None,
            "signature_verified": None,
            "secret_source": None,
            "source_out_base": None,
            "mainline_contract_summary": {
                "schema": "mainline_contract_check/v1",
                "status": "ok",
                "embedded_in_audit_chain": True,
                "handoff_cleanup": {"server": "removed", "client": "cleaned"},
            },
        },
    ),
]


# ---------------------------------------------------------------------------
# Mutation generators
# ---------------------------------------------------------------------------

def _deep(obj: Any) -> Any:
    return copy.deepcopy(obj)


def mutations_for(schema_def: dict[str, Any], payload: dict[str, Any]) -> list[tuple[str, str, Any]]:
    """Return list of (mutation_type, detail, mutated_payload)."""
    results: list[tuple[str, str, Any]] = []
    props = schema_def.get("properties", {})
    required = schema_def.get("required", [])
    strict = schema_def.get("additionalProperties") is False

    # 1. Missing required field at top level
    for key in required:
        mut = _deep(payload)
        del mut[key]
        results.append(("missing_required", f"$.{key}", mut))

    # 2. const violations
    for key, prop_schema in props.items():
        if "const" in prop_schema and key in payload:
            mut = _deep(payload)
            mut[key] = "__INVALID_CONST_VALUE__"
            results.append(("const_violation", f"$.{key}", mut))

    # 3. enum violations
    for key, prop_schema in props.items():
        if "enum" in prop_schema and key in payload:
            allowed = prop_schema["enum"]
            if None in allowed and len(allowed) <= 2:
                continue  # nullable-only enums don't have easy "bad" values
            mut = _deep(payload)
            mut[key] = "__INVALID_ENUM_VALUE__"
            results.append(("enum_violation", f"$.{key}", mut))

    # 4. Wrong type: swap string for integer and vice versa
    for key, prop_schema in props.items():
        if key not in payload:
            continue
        expected = prop_schema.get("type")
        if not expected:
            continue
        types = expected if isinstance(expected, list) else [expected]
        if "string" in types and "integer" not in types and "null" not in types:
            mut = _deep(payload)
            mut[key] = 99999
            results.append(("wrong_type_string_as_int", f"$.{key}", mut))
        elif "integer" in types and "string" not in types and "null" not in types:
            mut = _deep(payload)
            mut[key] = "not-an-integer"
            results.append(("wrong_type_int_as_str", f"$.{key}", mut))
        elif "boolean" in types and "null" not in types:
            mut = _deep(payload)
            mut[key] = "not-a-boolean"
            results.append(("wrong_type_bool_as_str", f"$.{key}", mut))
        elif "object" in types and "null" not in types:
            mut = _deep(payload)
            mut[key] = "not-an-object"
            results.append(("wrong_type_obj_as_str", f"$.{key}", mut))
        elif "array" in types and "null" not in types:
            mut = _deep(payload)
            mut[key] = "not-an-array"
            results.append(("wrong_type_arr_as_str", f"$.{key}", mut))

    # 5. Extra property (where additionalProperties: false)
    if strict:
        mut = _deep(payload)
        mut["__unknown_extra_property__"] = "injected"
        results.append(("extra_property", "$.__unknown_extra_property__", mut))

    # 6. minLength violation
    for key, prop_schema in props.items():
        if "minLength" in prop_schema and key in payload and isinstance(payload[key], str):
            min_len = prop_schema["minLength"]
            if min_len > 0:
                mut = _deep(payload)
                mut[key] = ""
                results.append(("min_length_violation", f"$.{key}", mut))

    # 7. minimum violation
    for key, prop_schema in props.items():
        if "minimum" in prop_schema and key in payload and isinstance(payload[key], (int, float)):
            mut = _deep(payload)
            mut[key] = prop_schema["minimum"] - 1
            results.append(("minimum_violation", f"$.{key}", mut))

    return results


# ---------------------------------------------------------------------------
# Validator interface
# ---------------------------------------------------------------------------

def _schema_path_for(schema_id: str) -> Path:
    name = schema_id.replace("/", "_").replace("-", "_")
    candidate = SCHEMA_DIR / f"{schema_id.replace('/', '.').rsplit('.', 1)[0]}.schema.json"
    # Prefer exact mapping: "platform_health/v1" → "platform_health.schema.json"
    base = schema_id.split("/")[0]
    direct = SCHEMA_DIR / f"{base}.schema.json"
    if direct.exists():
        return direct
    # Fallback: search by $id
    for p in SCHEMA_DIR.glob("*.schema.json"):
        try:
            s = json.loads(p.read_text())
            if s.get("$id") == schema_id:
                return p
        except Exception:
            continue
    raise FileNotFoundError(f"no schema file found for {schema_id!r}")


def validate_payload(schema_path: Path, payload: Any) -> tuple[bool, str]:
    """Run the local validator against payload. Returns (valid, error_message)."""
    import subprocess

    schema_def = json.loads(schema_path.read_text())
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        tmp = f.name
    try:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR_PY), "--schema", str(schema_path), "--json", tmp],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    finally:
        os.unlink(tmp)


def validate_raw_text(schema_path: Path, raw: str) -> tuple[bool, str]:
    import subprocess

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(raw)
        tmp = f.name
    try:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR_PY), "--schema", str(schema_path), "--json", tmp],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    finally:
        os.unlink(tmp)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Malformed-input negative test gate for JSON schema validators.")
    ap.add_argument("--out", default="", help="Path to write malformed_input_gate/v1 JSON report (default: stdout)")
    ap.add_argument("--verbose", action="store_true", help="Print each mutation result")
    args = ap.parse_args()

    generated_at = utc_now_iso()
    results: list[dict[str, Any]] = []
    accepted_count = 0
    skipped_count = 0

    for schema_id, ref_payload in CASES:
        try:
            schema_path = _schema_path_for(schema_id)
        except FileNotFoundError as e:
            print(f"[WARN] {e}", file=sys.stderr)
            skipped_count += 1
            continue

        # Sanity-check: reference payload must be valid
        valid, err = validate_payload(schema_path, ref_payload)
        if not valid:
            print(f"[ERROR] reference payload for {schema_id!r} is invalid: {err}", file=sys.stderr)
            return 1

        schema_def = json.loads(schema_path.read_text())
        muts = mutations_for(schema_def, ref_payload)

        # Also add generic non-object mutations (truncated JSON, wrong root type)
        raw_bad: list[tuple[str, str, str]] = [
            ("invalid_json", "$", '{"schema": "' + schema_id + '", UNTERMINATED'),
            ("null_root", "$", "null"),
            ("array_root", "$", "[]"),
            ("string_root", "$", '"not-an-object"'),
            ("number_root", "$", "42"),
        ]

        for mut_type, detail, mutated in muts:
            valid, err = validate_payload(schema_path, mutated)
            result_entry: dict[str, Any] = {
                "schema_id": schema_id,
                "mutation_type": mut_type,
                "detail": detail,
                "rejected": not valid,
                "error": err if not valid else None,
            }
            results.append(result_entry)
            if valid:
                accepted_count += 1
                print(f"[FAIL] {schema_id} mutation {mut_type!r} at {detail!r} was NOT rejected", file=sys.stderr)
            elif args.verbose:
                print(f"[ok] {schema_id} {mut_type!r} at {detail!r} rejected as expected")

        for mut_type, detail, raw_text in raw_bad:
            valid, err = validate_raw_text(schema_path, raw_text)
            result_entry = {
                "schema_id": schema_id,
                "mutation_type": mut_type,
                "detail": detail,
                "rejected": not valid,
                "error": err if not valid else None,
            }
            results.append(result_entry)
            if valid:
                accepted_count += 1
                print(f"[FAIL] {schema_id} raw-text mutation {mut_type!r} was NOT rejected", file=sys.stderr)
            elif args.verbose:
                print(f"[ok] {schema_id} {mut_type!r} rejected as expected")

    total = len(results)
    rejected = sum(1 for r in results if r["rejected"])
    status = "ok" if accepted_count == 0 else "fail"

    report: dict[str, Any] = {
        "schema": "malformed_input_gate/v1",
        "generated_at_utc": generated_at,
        "summary": {
            "schemas_tested": len(CASES),
            "mutations_attempted": total,
            "mutations_rejected": rejected,
            "mutations_accepted": accepted_count,
            "mutations_skipped": skipped_count,
            "status": status,
        },
        "results": results,
    }

    report_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(report_text + "\n", encoding="utf-8")
        print(f"[ok] malformed_input_gate: {total} mutations tested, {rejected} rejected, {accepted_count} accepted → {status}")
    else:
        print(report_text)

    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
