#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPO_ROOT / "config" / "schema_backcompat_baseline.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise SystemExit(f"[ERROR] JSON object expected: {path}")
    return payload


def sorted_unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise SystemExit("[ERROR] baseline lists must contain only strings")
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def check_entry(entry: dict[str, Any]) -> dict[str, Any]:
    path_value = entry.get("path")
    schema_id = entry.get("schema_id")
    required = sorted_unique_strings(entry.get("required") or [])
    stable_properties = sorted_unique_strings(entry.get("stable_properties") or [])
    if not isinstance(path_value, str) or not path_value:
        raise SystemExit(f"[ERROR] baseline entry is missing path: {entry}")
    if not isinstance(schema_id, str) or not schema_id:
        raise SystemExit(f"[ERROR] baseline entry is missing schema_id: {entry}")

    schema_path = (REPO_ROOT / path_value).resolve()
    errors: list[str] = []
    if not schema_path.is_file():
        errors.append(f"schema file does not exist: {schema_path}")
        return {
            "path": path_value,
            "schema_id": schema_id,
            "status": "error",
            "required": required,
            "stable_properties": stable_properties,
            "errors": errors,
        }

    schema = load_json_object(schema_path)
    if schema.get("$id") != schema_id:
        errors.append(f"$id changed: expected {schema_id!r}, got {schema.get('$id')!r}")
    if schema.get("type") != "object":
        errors.append(f"top-level type changed: expected 'object', got {schema.get('type')!r}")

    actual_required = schema.get("required") or []
    if not isinstance(actual_required, list) or not all(isinstance(item, str) for item in actual_required):
        errors.append("schema required list must be a list of strings")
        actual_required = []
    actual_required_set = set(actual_required)
    baseline_required_set = set(required)
    missing_required = sorted(baseline_required_set - actual_required_set)
    extra_required = sorted(actual_required_set - baseline_required_set)
    if missing_required:
        errors.append(f"required properties removed: {missing_required}")
    if extra_required:
        errors.append(f"new required properties added: {extra_required}")

    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        errors.append("schema properties must be an object")
        properties = {}
    missing_properties = sorted(prop for prop in stable_properties if prop not in properties)
    if missing_properties:
        errors.append(f"stable properties removed: {missing_properties}")

    schema_property = properties.get("schema")
    if isinstance(schema_property, dict) and schema_property.get("const") not in (None, schema_id):
        errors.append(f"schema const changed: expected {schema_id!r}, got {schema_property.get('const')!r}")

    return {
        "path": path_value,
        "schema_id": schema_id,
        "status": "error" if errors else "ok",
        "required": required,
        "stable_properties": stable_properties,
        "errors": errors,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Check frozen schema files for backward-compatibility regressions.")
    ap.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="Path to the JSON baseline manifest")
    ap.add_argument("--output", default="", help="Optional path to write the JSON report")
    ap.add_argument("--allow-failures", action="store_true", help="Exit 0 even when compatibility regressions are found")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    baseline_path = Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = (REPO_ROOT / baseline_path).resolve()
    baseline = load_json_object(baseline_path)
    entries = baseline.get("schemas")
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise SystemExit("[ERROR] baseline must contain a 'schemas' list of objects")

    checks = [check_entry(entry) for entry in entries]
    failed_count = sum(1 for item in checks if item["status"] != "ok")
    report = {
        "schema": "schema_backcompat_check/v1",
        "generated_at_utc": utc_now_iso(),
        "baseline_path": str(baseline_path),
        "checked_count": len(checks),
        "failed_count": failed_count,
        "checks": checks,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = (REPO_ROOT / output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.allow_failures:
        return 0
    return 1 if failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
