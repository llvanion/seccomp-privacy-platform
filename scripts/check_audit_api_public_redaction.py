#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import Any


FORBIDDEN_KEYS = {
    "paths",
    "path",
    "display_path",
    "out_base",
    "output_file",
    "input_file",
    "source_file",
    "record_store_file",
    "socket_path",
    "endpoint_url",
    "policy_config",
    "authz_policy_config",
    "pjc_result_file",
    "release_file",
    "ledger_path",
    "audit_chain_path",
    "public_report_path",
    "bridge",
    "details",
    "input_sizes",
    "rate_limit_used",
    "rate_limit_max",
    "duration_ms",
    "row_count",
    "output_rows",
    "input_rows",
    "candidate_count",
    "artifact_sha256",
    "sha256",
    "output_sha256",
    "input_sha256",
    "record_store_sha256",
    "release_sha256",
    "pjc_result_sha256",
    "server_input_sha256",
    "client_input_sha256",
    "query_fingerprint",
    "query_payload_sha256",
    "canonical_query_signature",
    "key_access_audit",
    "sse_export_audit",
    "record_recovery_service_audit",
    "bridge_audit",
    "bridge_job_meta",
    "pjc_audit",
    "pjc_result",
    "policy_audit",
    "release_policy_gate",
    "mainline_contract_check",
}


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"[ERROR] JSON object expected: {path}")
    return payload


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


def result_payload(envelope: dict[str, Any]) -> dict[str, Any]:
    if envelope.get("schema") == "audit_query_api_response/v1":
        result = envelope.get("result")
        if not isinstance(result, dict):
            raise SystemExit("[ERROR] audit query response result must be an object")
        return result
    return envelope


def validate_public_view(path: Path) -> dict[str, Any]:
    envelope = load_json_object(path)
    payload = result_payload(envelope)
    schema_name = payload.get("schema")
    allowed_schemas = {
        "public_report/v2",
        "audit_chain_public_summary/v1",
        "pipeline_observability_public_summary/v1",
        "catalog_lineage_public_summary/v1",
    }
    if schema_name not in allowed_schemas:
        raise SystemExit(f"[ERROR] {path} is not a caller-safe audit API schema: {schema_name}")
    leaks = collect_leaks(payload)
    return {
        "path": str(path),
        "schema": schema_name,
        "status": "fail" if leaks else "ok",
        "leaks": leaks,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Fail if caller-safe audit API responses leak operator-only fields.")
    ap.add_argument("json_files", nargs="+", help="audit_query_api_response/v1 files or raw caller-safe result objects")
    ap.add_argument("--output", default="", help="Optional JSON report path")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    checks = [validate_public_view(Path(item)) for item in args.json_files]
    failed = [item for item in checks if item["status"] != "ok"]
    report = {
        "schema": "audit_api_public_redaction_check/v1",
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
