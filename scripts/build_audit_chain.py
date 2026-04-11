#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def sha256_file(path: str) -> Optional[str]:
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json_if_exists(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    records = []
    if not path or not os.path.isfile(path):
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError(f"{path}:{line_no} must contain a JSON object")
            records.append(data)
    return records


def record_matches(record: Dict[str, Any], job_id: str) -> bool:
    return record.get("correlation_id") == job_id or record.get("job_id") == job_id


def filter_records(records: List[Dict[str, Any]], job_id: str) -> List[Dict[str, Any]]:
    return [record for record in records if record_matches(record, job_id)]


def resolve_paths(args: argparse.Namespace) -> Dict[str, str]:
    if args.out_base:
        out_base = os.path.abspath(args.out_base)
        return {
            "out_base": out_base,
            "sse_audit": args.sse_audit or os.path.join(out_base, "sse_exports", "export_audit.jsonl"),
            "record_recovery_service_audit": args.record_recovery_service_audit or os.path.join(out_base, "sse_exports", "record_recovery_service_audit.jsonl"),
            "bridge_audit": args.bridge_audit or os.path.join(out_base, "bridge_job", "bridge_audit.jsonl"),
            "bridge_job_meta": args.bridge_job_meta or os.path.join(out_base, "bridge_job", "job_meta.json"),
            "pjc_result": args.pjc_result or os.path.join(out_base, "a_psi_run", "attribution_result.json"),
            "public_report": args.public_report or os.path.join(out_base, "a_psi_run", "public_report.json"),
            "policy_audit": args.policy_audit or os.path.join(out_base, "a_psi_run", "audit_log.jsonl"),
            "key_access_audit": args.key_access_audit or os.path.join(out_base, "key_access_audit.jsonl"),
            "out": args.out or os.path.join(out_base, "audit_chain.json"),
        }
    return {
        "out_base": "",
        "sse_audit": args.sse_audit,
        "record_recovery_service_audit": args.record_recovery_service_audit,
        "bridge_audit": args.bridge_audit,
        "bridge_job_meta": args.bridge_job_meta,
        "pjc_result": args.pjc_result,
        "public_report": args.public_report,
        "policy_audit": args.policy_audit,
        "key_access_audit": args.key_access_audit,
        "out": args.out,
    }


def build_chain(args: argparse.Namespace) -> Dict[str, Any]:
    paths = resolve_paths(args)
    if not args.job_id:
        raise ValueError("--job-id is required")
    if not paths["out"]:
        raise ValueError("--out is required when --out-base is not supplied")

    sse_export_records = filter_records(load_jsonl(paths["sse_audit"]), args.job_id)
    record_recovery_service_records = filter_records(load_jsonl(paths["record_recovery_service_audit"]), args.job_id)
    bridge_records = filter_records(load_jsonl(paths["bridge_audit"]), args.job_id)
    policy_records = filter_records(load_jsonl(paths["policy_audit"]), args.job_id)
    key_access_records = filter_records(load_jsonl(paths["key_access_audit"]), args.job_id)
    bridge_job_meta = load_json_if_exists(paths["bridge_job_meta"])
    pjc_result = load_json_if_exists(paths["pjc_result"])
    public_report = load_json_if_exists(paths["public_report"])

    return {
        "schema": "audit_chain/v1",
        "generated_at_utc": utc_now_iso(),
        "job_id": args.job_id,
        "correlation_id": args.job_id,
        "paths": {
            "out_base": paths["out_base"] or None,
            "sse_audit": os.path.abspath(paths["sse_audit"]) if paths["sse_audit"] else None,
            "record_recovery_service_audit": os.path.abspath(paths["record_recovery_service_audit"]) if paths["record_recovery_service_audit"] else None,
            "bridge_audit": os.path.abspath(paths["bridge_audit"]) if paths["bridge_audit"] else None,
            "bridge_job_meta": os.path.abspath(paths["bridge_job_meta"]) if paths["bridge_job_meta"] else None,
            "pjc_result": os.path.abspath(paths["pjc_result"]) if paths["pjc_result"] else None,
            "public_report": os.path.abspath(paths["public_report"]) if paths["public_report"] else None,
            "policy_audit": os.path.abspath(paths["policy_audit"]) if paths["policy_audit"] else None,
            "key_access_audit": os.path.abspath(paths["key_access_audit"]) if paths["key_access_audit"] else None,
        },
        "artifacts": {
            "bridge_job_meta_sha256": sha256_file(paths["bridge_job_meta"]),
            "pjc_result_sha256": sha256_file(paths["pjc_result"]),
            "public_report_sha256": sha256_file(paths["public_report"]),
        },
        "counts": {
            "sse_export_audit_records": len(sse_export_records),
            "record_recovery_service_audit_records": len(record_recovery_service_records),
            "bridge_audit_records": len(bridge_records),
            "policy_audit_records": len(policy_records),
            "key_access_audit_records": len(key_access_records),
        },
        "key_access_audit": key_access_records,
        "sse_export_audit": sse_export_records,
        "record_recovery_service_audit": record_recovery_service_records,
        "bridge_audit": bridge_records,
        "bridge_job_meta": bridge_job_meta,
        "pjc_result": pjc_result,
        "public_report": public_report,
        "policy_audit": policy_records,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a single correlated audit-chain view for an SSE -> bridge -> PJC -> release job.")
    ap.add_argument("--out-base", default="", help="Pipeline output directory containing sse_exports/, bridge_job/, and a_psi_run/")
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--out", default="", help="Output audit_chain.json path; defaults to <out-base>/audit_chain.json")
    ap.add_argument("--sse-audit", default="")
    ap.add_argument("--record-recovery-service-audit", default="")
    ap.add_argument("--bridge-audit", default="")
    ap.add_argument("--bridge-job-meta", default="")
    ap.add_argument("--pjc-result", default="")
    ap.add_argument("--public-report", default="")
    ap.add_argument("--policy-audit", default="")
    ap.add_argument("--key-access-audit", default="")
    args = ap.parse_args()

    try:
        chain = build_chain(args)
    except Exception as e:
        raise SystemExit(f"[ERROR] {e}") from e

    paths = resolve_paths(args)
    os.makedirs(os.path.dirname(os.path.abspath(paths["out"])) or ".", exist_ok=True)
    with open(paths["out"], "w", encoding="utf-8") as f:
        json.dump(chain, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[ok] audit chain: {os.path.abspath(paths['out'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
