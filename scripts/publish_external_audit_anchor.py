#!/usr/bin/env python3
import argparse
import hmac
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.archive_audit_bundle import (  # noqa: E402
    compute_anchor_entry_sha256,
    compute_anchor_payload_sha256,
    hmac_sha256_hex,
    load_jsonl_objects,
    utc_now_iso,
)


SCHEMA_ID = "external_audit_anchor_report/v1"

_TENANT_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


def validate_tenant_segment(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("tenant_id must be a non-empty string")
    candidate = value.strip()
    if not _TENANT_PATH_SEGMENT_RE.match(candidate):
        raise ValueError(
            f"tenant_id {candidate!r} is not a valid path segment "
            "(allowed: alphanumeric plus _ . -)"
        )
    if candidate in (".", ".."):
        raise ValueError(f"tenant_id {candidate!r} is not a valid path segment")
    return candidate


def assert_path_contains_tenant_segment(path: Path, *, tenant_id: str, label: str) -> None:
    parts = path.parts
    if tenant_id not in parts:
        raise ValueError(
            f"{label} {str(path)!r} does not include tenant_id {tenant_id!r} as a path segment"
        )


def verify_anchor_records(
    records: list[dict[str, Any]],
    *,
    anchor_key_env: str,
    require_signature: bool,
    expected_tenant_id: str | None,
) -> list[dict[str, Any]]:
    published_records: list[dict[str, Any]] = []
    previous_entry_sha256: str | None = None
    secret = os.environ.get(anchor_key_env) if anchor_key_env else None
    if anchor_key_env and not secret:
        raise ValueError(f"external audit anchor key env {anchor_key_env} is not set")
    for line_no, record in enumerate(records, 1):
        if record.get("schema") != "audit_archive_anchor/v1":
            raise ValueError(f"anchor line {line_no} has unexpected schema: {record.get('schema')}")
        expected_payload_sha256 = compute_anchor_payload_sha256(record)
        if record.get("payload_sha256") != expected_payload_sha256:
            raise ValueError(f"anchor line {line_no} payload_sha256 mismatch")
        expected_entry_sha256 = compute_anchor_entry_sha256(
            previous_anchor_entry_sha256=previous_entry_sha256,
            payload_sha256=expected_payload_sha256,
        )
        if record.get("entry_sha256") != expected_entry_sha256:
            raise ValueError(f"anchor line {line_no} entry_sha256 mismatch")
        if record.get("previous_anchor_entry_sha256") != previous_entry_sha256:
            raise ValueError(f"anchor line {line_no} previous_anchor_entry_sha256 mismatch")
        record_tenant_raw = record.get("tenant_id")
        record_tenant = str(record_tenant_raw).strip() if isinstance(record_tenant_raw, str) and record_tenant_raw.strip() else None
        if expected_tenant_id is not None:
            if record_tenant is None:
                raise ValueError(
                    f"anchor line {line_no} has no tenant_id but --tenant-id={expected_tenant_id!r} was requested"
                )
            if record_tenant != expected_tenant_id:
                raise ValueError(
                    f"anchor line {line_no} tenant_id mismatch: expected {expected_tenant_id!r}, got {record_tenant!r}"
                )
        signature_algorithm = record.get("signature_algorithm")
        signature_verified: bool | None = None
        if signature_algorithm == "hmac-sha256":
            signature = record.get("signature")
            if not isinstance(signature, str) or not signature:
                raise ValueError(f"anchor line {line_no} missing HMAC signature")
            if secret:
                expected_signature = hmac_sha256_hex(secret, str(record.get("entry_sha256") or ""))
                if not hmac.compare_digest(signature, expected_signature):
                    raise ValueError(f"anchor line {line_no} HMAC signature mismatch")
                signature_verified = True
        elif signature_algorithm is None:
            if require_signature:
                raise ValueError(f"anchor line {line_no} is unsigned")
        else:
            raise ValueError(f"anchor line {line_no} unsupported signature algorithm: {signature_algorithm}")
        published_records.append(
            {
                "job_id": str(record.get("job_id") or ""),
                "chain_position": int(record.get("chain_position") or 0),
                "entry_sha256": str(record.get("entry_sha256") or ""),
                "payload_sha256": str(record.get("payload_sha256") or ""),
                "index_record_sha256": str(record.get("index_record_sha256") or ""),
                "signature_algorithm": signature_algorithm,
                "signature_verified": signature_verified,
                "tenant_id": record_tenant,
                "published": False,
            }
        )
        previous_entry_sha256 = str(record.get("entry_sha256") or "")
    return published_records


def append_external_ledger(
    path: Path,
    records: list[dict[str, Any]],
    *,
    tenant_id: str | None,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            payload = {
                "schema": "external_audit_anchor_ledger/v1",
                "published_at_utc": utc_now_iso(),
                "job_id": record["job_id"],
                "chain_position": record["chain_position"],
                "entry_sha256": record["entry_sha256"],
                "payload_sha256": record["payload_sha256"],
                "index_record_sha256": record["index_record_sha256"],
                "signature_algorithm": record["signature_algorithm"],
                "tenant_id": tenant_id if tenant_id is not None else record.get("tenant_id"),
            }
            f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            record["published"] = True
    return len(records)


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish local audit archive anchor records to an external anchor sink.")
    ap.add_argument("--anchor-file", required=True)
    ap.add_argument("--external-ledger", required=True)
    ap.add_argument("--output", default="")
    ap.add_argument("--anchor-key-env", default="")
    ap.add_argument("--require-signature", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--assert-ok", action="store_true")
    ap.add_argument(
        "--tenant-id",
        default="",
        help=(
            "Optional tenant scope. When set, --anchor-file must live under a directory "
            "named <tenant-id>, --external-ledger must include <tenant-id> as a path segment, "
            "and every anchor record must carry tenant_id=<tenant-id>."
        ),
    )
    args = ap.parse_args()

    tenant_id: str | None = None
    if args.tenant_id:
        tenant_id = validate_tenant_segment(args.tenant_id)

    anchor_path = Path(args.anchor_file).resolve()
    ledger_path = Path(args.external_ledger).resolve()

    if tenant_id is not None:
        assert_path_contains_tenant_segment(anchor_path, tenant_id=tenant_id, label="--anchor-file")
        assert_path_contains_tenant_segment(ledger_path, tenant_id=tenant_id, label="--external-ledger")

    records = verify_anchor_records(
        load_jsonl_objects(str(anchor_path)),
        anchor_key_env=args.anchor_key_env,
        require_signature=args.require_signature,
        expected_tenant_id=tenant_id,
    )
    published_count = 0 if args.dry_run else append_external_ledger(ledger_path, records, tenant_id=tenant_id)
    status = "ok" if records else "fail"
    summary = {
        "status": status,
        "anchor_record_count": len(records),
        "published_count": published_count,
        "verified_chain": bool(records),
        "signed_count": sum(1 for record in records if record["signature_algorithm"] == "hmac-sha256"),
        "last_entry_sha256": records[-1]["entry_sha256"] if records else None,
        "tenant_id": tenant_id,
    }
    external_sink = {
        "kind": "file_ledger",
        "path": str(ledger_path),
        "tenant_id": tenant_id,
    }
    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "source_anchor_file": str(anchor_path),
        "tenant_id": tenant_id,
        "external_sink": external_sink,
        "mode": "dry_run" if args.dry_run else "publish",
        "summary": summary,
        "records": records,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.assert_ok and status != "ok":
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        raise SystemExit(f"[ERROR] {e}") from e
