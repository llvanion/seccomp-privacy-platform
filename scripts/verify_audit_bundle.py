#!/usr/bin/env python3
import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from archive_audit_bundle import (
    archive_index_record_sha256,
    build_anchor_paths,
    compute_anchor_entry_sha256,
    compute_anchor_payload_sha256,
    hmac_sha256_hex,
    load_json_object,
    read_bytes,
    sha256_hex,
    sha256_json,
    summarize_mainline_contract,
    verify_audit_bundle,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_jsonl_objects(path: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
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


def select_archive_record(index_path: str, job_id: str) -> dict[str, Any]:
    records = [
        record
        for record in load_jsonl_objects(index_path)
        if record.get("schema") == "audit_archive_index/v1" and str(record.get("job_id", "")) == job_id
    ]
    if not records:
        raise ValueError(f"archive index has no record for job_id: {job_id}")
    return records[-1]


def verify_anchor_record(
    anchor_path: str,
    *,
    expected_index_record_sha256: str,
    expected_archive_dir: str,
    anchor_key_env: str,
) -> tuple[dict[str, Any], bool | None]:
    records = load_jsonl_objects(anchor_path)
    if not records:
        raise ValueError(f"anchor log has no records: {anchor_path}")
    previous_entry_sha256: str | None = None
    matched_record: dict[str, Any] | None = None
    matched_signature_verified: bool | None = None
    for line_no, record in enumerate(records, 1):
        if record.get("schema") != "audit_archive_anchor/v1":
            raise ValueError(f"{anchor_path}:{line_no} has unexpected schema: {record.get('schema')}")
        payload_sha256 = str(record.get("payload_sha256", "") or "")
        expected_payload_sha256 = compute_anchor_payload_sha256(record)
        if payload_sha256 != expected_payload_sha256:
            raise ValueError(f"{anchor_path}:{line_no} payload_sha256 does not match anchor payload")
        expected_entry_sha256 = compute_anchor_entry_sha256(
            previous_anchor_entry_sha256=previous_entry_sha256,
            payload_sha256=payload_sha256,
        )
        entry_sha256 = str(record.get("entry_sha256", "") or "")
        if entry_sha256 != expected_entry_sha256:
            raise ValueError(f"{anchor_path}:{line_no} entry_sha256 does not match append-only chain")
        if record.get("previous_anchor_entry_sha256") != previous_entry_sha256:
            raise ValueError(f"{anchor_path}:{line_no} previous_anchor_entry_sha256 does not match prior entry")
        signature_algorithm = record.get("signature_algorithm")
        signature = record.get("signature")
        signature_verified: bool | None = None
        if signature_algorithm is None:
            if signature is not None:
                raise ValueError(f"{anchor_path}:{line_no} signature must be null when signature_algorithm is null")
        elif signature_algorithm == "hmac-sha256":
            if not isinstance(signature, str) or not signature:
                raise ValueError(f"{anchor_path}:{line_no} signature must be present for hmac-sha256")
            if anchor_key_env:
                secret = os.environ.get(anchor_key_env)
                if not secret:
                    raise ValueError(f"audit archive anchor key env {anchor_key_env} is not set")
                expected_signature = hmac_sha256_hex(secret, entry_sha256)
                if signature != expected_signature:
                    raise ValueError(f"{anchor_path}:{line_no} anchor HMAC does not match entry_sha256")
                signature_verified = True
        else:
            raise ValueError(f"{anchor_path}:{line_no} unsupported anchor signature algorithm: {signature_algorithm}")
        if record.get("archive_dir") != expected_archive_dir:
            raise ValueError(f"{anchor_path}:{line_no} archive_dir does not match selected archive")
        if record.get("index_record_sha256") == expected_index_record_sha256:
            matched_record = record
            matched_signature_verified = signature_verified
        previous_entry_sha256 = entry_sha256
    if matched_record is None:
        raise ValueError(f"anchor log has no record for selected archive index entry: {expected_index_record_sha256}")
    return matched_record, matched_signature_verified


def resolve_sources(args: argparse.Namespace) -> tuple[str, str, dict[str, Any] | None]:
    if args.archive_index:
        record = select_archive_record(args.archive_index, args.job_id)
        audit_chain = str(record.get("archived_audit_chain_file", ""))
        audit_seal = str(record.get("archived_audit_seal_file", ""))
        if not audit_chain or not audit_seal:
            raise ValueError("archive index record is missing archived audit paths")
        return audit_chain, audit_seal, record
    if not args.audit_chain or not args.audit_seal:
        raise ValueError("use --audit-chain plus --audit-seal, or --archive-index")
    return args.audit_chain, args.audit_seal, None


def verify_index_record(record: dict[str, Any],
                        audit_chain_path: str,
                        audit_seal_path: str,
                        audit_chain: dict[str, Any],
                        audit_chain_sha256: str,
                        audit_seal_sha256: str) -> None:
    if record.get("archived_audit_chain_file") != os.path.abspath(audit_chain_path):
        raise ValueError("archive index archived_audit_chain_file does not match selected path")
    if record.get("archived_audit_seal_file") != os.path.abspath(audit_seal_path):
        raise ValueError("archive index archived_audit_seal_file does not match selected path")
    if record.get("audit_chain_sha256") != audit_chain_sha256:
        raise ValueError("archive index audit_chain_sha256 does not match selected chain")
    if record.get("audit_seal_sha256") != audit_seal_sha256:
        raise ValueError("archive index audit_seal_sha256 does not match selected seal")
    if record.get("mainline_contract_summary") != summarize_mainline_contract(audit_chain):
        raise ValueError("archive index mainline_contract_summary does not match selected audit chain")


def verify_archive_anchor(
    *,
    index_record: dict[str, Any],
    anchor_key_env: str,
) -> tuple[dict[str, Any], bool | None]:
    archive_dir = str(index_record.get("archive_dir", "") or "")
    if not archive_dir:
        raise ValueError("archive index record is missing archive_dir")
    anchor_file = str(index_record.get("anchor_file", "") or "")
    if not anchor_file:
        anchor_file = build_anchor_paths(archive_dir=archive_dir)["anchor_file"]
    if not os.path.isfile(anchor_file):
        raise ValueError(f"archive anchor log does not exist: {anchor_file}")
    index_record_sha256 = archive_index_record_sha256(index_record)
    anchor_record, signature_verified = verify_anchor_record(
        anchor_file,
        expected_index_record_sha256=index_record_sha256,
        expected_archive_dir=archive_dir,
        anchor_key_env=anchor_key_env,
    )
    if anchor_record.get("anchor_file") != os.path.abspath(anchor_file):
        raise ValueError("anchor record anchor_file does not match selected anchor path")
    expected_anchor_entry_sha256 = index_record.get("anchor_entry_sha256")
    if expected_anchor_entry_sha256 not in (None, "", anchor_record.get("entry_sha256")):
        raise ValueError("archive index anchor_entry_sha256 does not match selected anchor record")
    return anchor_record, signature_verified


def copy_verified_file(src: str, dst: Path, expected_sha256: str, *, overwrite: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        existing_sha256 = sha256_hex(read_bytes(str(dst)))
        if existing_sha256 == expected_sha256:
            return
        if not overwrite:
            raise ValueError(f"restore target already exists with different contents: {dst}")
    shutil.copy2(src, dst)
    copied_sha256 = sha256_hex(read_bytes(str(dst)))
    if copied_sha256 != expected_sha256:
        raise ValueError(f"restored file hash mismatch: {dst}")


def restore_verified_bundle(*,
                            audit_chain_path: str,
                            audit_seal_path: str,
                            restore_dir: str,
                            audit_chain_sha256: str,
                            audit_seal_sha256: str,
                            overwrite: bool) -> dict[str, Any]:
    root = Path(restore_dir).resolve()
    restored_chain = root / "audit_chain.json"
    restored_seal = root / "audit_chain.seal.json"
    copy_verified_file(audit_chain_path, restored_chain, audit_chain_sha256, overwrite=overwrite)
    copy_verified_file(audit_seal_path, restored_seal, audit_seal_sha256, overwrite=overwrite)
    return {
        "restore_dir": str(root),
        "restored_audit_chain_file": str(restored_chain),
        "restored_audit_seal_file": str(restored_seal),
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Verify and optionally restore an archived audit_chain.json plus audit_chain.seal.json bundle.",
    )
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive-index", default="", help="audit_chain_index.jsonl produced by archive_audit_bundle.py")
    source.add_argument("--audit-chain", default="", help="Direct audit_chain.json path")
    ap.add_argument("--audit-seal", default="", help="Direct audit_chain.seal.json path; required with --audit-chain")
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--hmac-key-env", default="", help="Optional env var used to verify hmac-sha256 seals")
    ap.add_argument("--anchor-key-env", default="", help="Optional env var used to verify HMAC-signed archive anchor records")
    ap.add_argument("--restore-dir", default="", help="Optional directory to restore verified bundle files into")
    ap.add_argument("--overwrite", action="store_true", help="Allow restore to replace existing mismatched files")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    try:
        audit_chain_path, audit_seal_path, index_record = resolve_sources(args)
        audit_chain, audit_seal, audit_chain_sha256, audit_seal_sha256, signature_verified = verify_audit_bundle(
            audit_chain_path=audit_chain_path,
            audit_seal_path=audit_seal_path,
            job_id=args.job_id,
            hmac_key_env=args.hmac_key_env,
        )
        if index_record is not None:
            verify_index_record(
                index_record,
                audit_chain_path,
                audit_seal_path,
                audit_chain,
                audit_chain_sha256,
                audit_seal_sha256,
            )
        anchor_record = None
        anchor_signature_verified = None
        if index_record is not None:
            anchor_record, anchor_signature_verified = verify_archive_anchor(
                index_record=index_record,
                anchor_key_env=args.anchor_key_env,
            )
        restored = None
        if args.restore_dir:
            restored = restore_verified_bundle(
                audit_chain_path=audit_chain_path,
                audit_seal_path=audit_seal_path,
                restore_dir=args.restore_dir,
                audit_chain_sha256=audit_chain_sha256,
                audit_seal_sha256=audit_seal_sha256,
                overwrite=args.overwrite,
            )
        report = {
            "schema": "audit_bundle_verification/v1",
            "ts_utc": utc_now_iso(),
            "verified": True,
            "job_id": args.job_id,
            "correlation_id": audit_chain.get("correlation_id"),
            "source": {
                "archive_index": os.path.abspath(args.archive_index) if args.archive_index else None,
                "audit_chain_file": os.path.abspath(audit_chain_path),
                "audit_seal_file": os.path.abspath(audit_seal_path),
            },
            "audit_chain_sha256": audit_chain_sha256,
            "audit_seal_sha256": audit_seal_sha256,
            "artifact_sha256_verified": True,
            "signature_algorithm": audit_seal.get("signature_algorithm"),
            "signature_verified": signature_verified,
            "archive_index_verified": index_record is not None,
            "anchor_log_verified": anchor_record is not None,
            "anchor_file": os.path.abspath(str(anchor_record.get("anchor_file"))) if isinstance(anchor_record, dict) else None,
            "anchor_entry_sha256": str(anchor_record.get("entry_sha256")) if isinstance(anchor_record, dict) else None,
            "anchor_signature_verified": anchor_signature_verified,
            "mainline_contract_summary": summarize_mainline_contract(audit_chain),
            "restored": restored,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        report = {
            "schema": "audit_bundle_verification/v1",
            "ts_utc": utc_now_iso(),
            "verified": False,
            "job_id": args.job_id,
            "error": str(e),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
