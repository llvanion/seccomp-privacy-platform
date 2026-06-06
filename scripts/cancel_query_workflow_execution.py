#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from query_workflow_execution_store import connect_execution_db, metadata_json, request_cancel_execution
from submit_query_workflow import (
    append_jsonl,
    build_command,
    build_receipt,
    build_status,
    json_sha256,
    load_jsonl_objects,
    query_workflow_sidecar_paths,
    write_json,
)


SCHEMA = "query_workflow_cancel_request/v1"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Request cancellation for a DB-backed query workflow execution.")
    ap.add_argument("--metadata-db-path", default="")
    ap.add_argument("--metadata-db-dsn", default="")
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--actor", default="")
    ap.add_argument("--reason", default="")
    ap.add_argument("--out", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    conn = connect_execution_db(args.metadata_db_path, args.metadata_db_dsn)
    try:
        row = request_cancel_execution(
            conn,
            job_id=args.job_id,
            actor=args.actor,
            reason=args.reason,
        )
    finally:
        conn.close()
    sidecar_written = False
    sidecar_status_path = ""
    meta = metadata_json(row)
    payload = meta.get("raw_payload")
    if isinstance(payload, dict):
        command = meta.get("command") if isinstance(meta.get("command"), list) else build_command(payload)
        request_digest = str(row.get("request_digest") or json_sha256(payload))
        sidecar_paths = query_workflow_sidecar_paths(str(payload.get("out_base") or row.get("out_base") or ""))
        event = "cancelled" if bool(row.get("terminal")) else "cancel_requested"
        exit_code = 130 if bool(row.get("terminal")) else None
        receipt = build_receipt(
            payload=payload,
            mode="execute",
            event=event,
            request_digest=request_digest,
            command=[str(item) for item in command],
            exit_code=exit_code,
            error_class="cancel_requested",
            error_message=args.reason or "execution cancellation requested",
        )
        append_jsonl(sidecar_paths["execution_receipts"], receipt)
        receipt_count = len(load_jsonl_objects(sidecar_paths["execution_receipts"]))
        status = build_status(
            payload=payload,
            mode="execute",
            state=str(row.get("state") or event),
            terminal=bool(row.get("terminal")),
            latest_receipt=receipt,
            receipt_count=receipt_count,
            exit_code=exit_code,
        )
        write_json(sidecar_paths["status"], status)
        sidecar_written = True
        sidecar_status_path = str(sidecar_paths["status"])
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "job_id": args.job_id,
        "state": row.get("state"),
        "terminal": bool(row.get("terminal")),
        "actor": args.actor or None,
        "reason": args.reason or None,
        "sidecar_written": sidecar_written,
        "sidecar_status_path": sidecar_status_path or None,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        from pathlib import Path

        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
