#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "ecommerce_fact_import_job_smoke/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_manifest(path: Path, *, table: str, input_path: Path, metadata_db: Path, result_path: Path, allow_reject: bool) -> None:
    payload = {
        "schema": "ecommerce_fact_import_job/v1",
        "generated_at_utc": utc_now_iso(),
        "table": table,
        "input_path": str(input_path),
        "metadata_db": str(metadata_db),
        "business_access_policy": str(REPO_ROOT / "config" / "business_access_policy.ecommerce.example.json"),
        "allow_reject": allow_reject,
        "result_path": str(result_path),
    }
    write_json(path, payload)


def count_rows(db_path: Path, table: str) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Smoke-test the validator-first e-commerce fact import job wrapper.")
    ap.add_argument("--out-dir", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="seccomp_ecommerce_fact_job.") as tmp_raw:
        tmp_dir = Path(tmp_raw)
        metadata_db = tmp_dir / "metadata.sqlite"

        allow_input = tmp_dir / "orders_allow.jsonl"
        allow_input.write_text(
            json.dumps(
                {
                    "order_id": "job-o-1",
                    "tenant_id": "commerce_tenant",
                    "dataset_id": "orders_analytics",
                    "buyer_email": "buyer@example.com",
                    "merchant_business_identity_id": "merchant-1",
                    "buyer_business_identity_id": "buyer-1",
                    "currency": "USD",
                    "total_amount_cents": 1299,
                    "placed_at_utc": "2026-06-01T00:00:00Z",
                    "status": "placed",
                    "created_at_utc": "2026-06-01T00:00:00Z",
                    "ingested_at_utc": "2026-06-01T00:00:01Z",
                }
            ) + "\n",
            encoding="utf-8",
        )
        reject_input = tmp_dir / "orders_reject.jsonl"
        reject_input.write_text(
            json.dumps(
                {
                    "order_id": "job-o-2",
                    "tenant_id": "commerce_tenant",
                    "dataset_id": "orders_analytics",
                    "buyer_email": "buyer2@example.com",
                    "merchant_business_identity_id": "merchant-1",
                    "buyer_business_identity_id": "buyer-2",
                    "currency": "USD",
                    "total_amount_cents": 1999,
                    "delivery_address": "forbidden-field",
                    "placed_at_utc": "2026-06-01T00:00:00Z",
                    "status": "placed",
                    "created_at_utc": "2026-06-01T00:00:00Z",
                    "ingested_at_utc": "2026-06-01T00:00:01Z",
                }
            ) + "\n",
            encoding="utf-8",
        )

        allow_manifest = tmp_dir / "allow_manifest.json"
        allow_result = tmp_dir / "allow_result.json"
        make_manifest(allow_manifest, table="orders", input_path=allow_input, metadata_db=metadata_db, result_path=allow_result, allow_reject=False)
        reject_manifest = tmp_dir / "reject_manifest.json"
        reject_result = tmp_dir / "reject_result.json"
        make_manifest(reject_manifest, table="orders", input_path=reject_input, metadata_db=metadata_db, result_path=reject_result, allow_reject=True)

        allow_job_report = out_dir / "allow_job_report.json"
        reject_job_report = out_dir / "reject_job_report.json"
        allow_cmd = ["python3", str(REPO_ROOT / "scripts" / "run_ecommerce_fact_import_job.py"), "--manifest", str(allow_manifest), "--output", str(allow_job_report)]
        reject_cmd = ["python3", str(REPO_ROOT / "scripts" / "run_ecommerce_fact_import_job.py"), "--manifest", str(reject_manifest), "--output", str(reject_job_report)]

        allow_res = run(allow_cmd)
        reject_res = run(reject_cmd)
        allow_report = load_json(allow_job_report)
        reject_report = load_json(reject_job_report)

        row_count_after_allow = count_rows(metadata_db, "orders")
        row_count_after_reject = count_rows(metadata_db, "orders")

        report = {
            "schema": SCHEMA_ID,
            "generated_at_utc": utc_now_iso(),
            "status": "ok" if allow_res.returncode == 0 and reject_res.returncode == 0 else "fail",
            "allow_job_status": allow_report.get("status"),
            "allow_result_decision": ((allow_report.get("result") or {}).get("decision")),
            "allow_inserted_row_count": ((allow_report.get("result") or {}).get("inserted_row_count")),
            "reject_job_status": reject_report.get("status"),
            "reject_result_decision": ((reject_report.get("result") or {}).get("decision")),
            "reject_reason_code": ((reject_report.get("result") or {}).get("reason_code")),
            "orders_row_count_after_allow": row_count_after_allow,
            "orders_row_count_after_reject": row_count_after_reject,
        }
        write_json(out_dir / "ecommerce_fact_import_job_smoke.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

