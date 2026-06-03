#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def abspath_or_none(path: str) -> Optional[str]:
    if not path:
        return None
    return os.path.abspath(path)


def sha256_file_if_exists(path: str) -> Optional[str]:
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def append_jsonl(path: str, record: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_record(args: argparse.Namespace) -> Dict[str, Any]:
    record = {
        "schema": "pjc_audit/v1",
        "ts_utc": utc_now_iso(),
        "event": "pjc_run",
        "job_id": args.job_id,
        "correlation_id": args.job_id,
        "out_dir": os.path.abspath(args.out_dir),
        "server_csv": os.path.abspath(args.server_csv),
        "server_csv_sha256": sha256_file_if_exists(args.server_csv),
        "client_csv": os.path.abspath(args.client_csv),
        "client_csv_sha256": sha256_file_if_exists(args.client_csv),
        "input_commitment_file": abspath_or_none(args.input_commitment),
        "input_commitment_sha256": sha256_file_if_exists(args.input_commitment),
        "server_log": abspath_or_none(args.server_log),
        "server_log_sha256": sha256_file_if_exists(args.server_log),
        "client_log": abspath_or_none(args.client_log),
        "client_log_sha256": sha256_file_if_exists(args.client_log),
        "result_file": abspath_or_none(args.result_file),
        "result_sha256": sha256_file_if_exists(args.result_file),
        "duration_ms": args.duration_ms,
        "decision": args.decision,
        "reason_code": args.reason_code,
        "reason": args.reason,
        "exit_code": args.exit_code,
    }
    if args.grpc_stream_chunk_elements is not None:
        record["grpc_stream_chunk_elements"] = args.grpc_stream_chunk_elements
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description="Append a PJC stage audit record.")
    ap.add_argument("--audit-log", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--server-csv", required=True)
    ap.add_argument("--client-csv", required=True)
    ap.add_argument("--input-commitment", default="")
    ap.add_argument("--server-log", default="")
    ap.add_argument("--client-log", default="")
    ap.add_argument("--result-file", default="")
    ap.add_argument("--duration-ms", type=int, default=None)
    ap.add_argument("--decision", required=True, choices=["allow", "deny"])
    ap.add_argument("--reason-code", required=True)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--exit-code", type=int, default=None)
    ap.add_argument("--grpc-stream-chunk-elements", type=int, default=None)
    args = ap.parse_args()

    record = build_record(args)
    append_jsonl(os.path.abspath(args.audit_log), record)
    print(f"[ok] pjc audit: {os.path.abspath(args.audit_log)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
