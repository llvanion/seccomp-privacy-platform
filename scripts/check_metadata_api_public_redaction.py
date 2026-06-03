#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import Any


FORBIDDEN_KEYS = {
    "out_base",
    "public_report_path",
    "audit_chain_path",
    "artifact_path",
    "path",
    "sha256",
    "source_file",
    "binding_json",
    "details",
    "details_json",
    "metadata_json",
    "counts_json",
    "payload",
    "query_fingerprint",
    "query_payload_sha256",
    "ledger_path",
    "public_report_sha256",
    "source_event_id",
    "key_id",
    "key_version",
    "secret_ref_name",
    "backend_key_version",
    "backend_ref",
    "config_path",
    "imported_at_utc",
    "updated_at_utc",
    "effective_at_utc",
    "duration_ms",
    "total_stage_duration_ms",
    "stage_duration_summary",
    "missing_duration_stages",
    "intersection_size",
    "intersection_sum",
    "budget_used_before",
    "budget_used_after",
    "budget_cost",
    "budget_limit",
    "total_matching_count",
    "stage_summary",
    "grouped_stage_summary",
    "grouped_status_summary",
    "timing_summary",
    "artifacts",
    "audit_chain",
    "audit_seal",
}


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"[ERROR] JSON object expected: {path}")
    return payload


def result_payload(envelope: dict[str, Any]) -> dict[str, Any]:
    if envelope.get("schema") == "metadata_api_response/v1":
        result = envelope.get("result")
        if not isinstance(result, dict):
            raise SystemExit("[ERROR] metadata API response result must be an object")
        return result
    return envelope


def collect_leaks(value: Any, *, path: str = "$") -> list[str]:
    leaks: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_KEYS:
                leaks.append(child_path)
            leaks.extend(collect_leaks(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            leaks.extend(collect_leaks(child, path=f"{path}[{index}]"))
    return leaks


def validate_public_view(path: Path) -> dict[str, Any]:
    envelope = load_json_object(path)
    payload = result_payload(envelope)
    redaction = payload.get("redaction")
    leaks = collect_leaks(payload)
    if not isinstance(redaction, dict) or redaction.get("view") != "caller_safe_metadata_summary":
        leaks.append("$.redaction")
    return {
        "path": str(path),
        "status": "fail" if leaks else "ok",
        "leaks": leaks,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Fail if caller-safe metadata API responses leak operator-only fields.")
    ap.add_argument("json_files", nargs="+", help="metadata_api_response/v1 files or raw caller-safe result objects")
    ap.add_argument("--output", default="", help="Optional JSON report path")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    checks = [validate_public_view(Path(item)) for item in args.json_files]
    failed = [item for item in checks if item["status"] != "ok"]
    report = {
        "schema": "metadata_api_public_redaction_check/v1",
        "status": "fail" if failed else "ok",
        "checked_count": len(checks),
        "failed_count": len(failed),
        "checks": checks,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
