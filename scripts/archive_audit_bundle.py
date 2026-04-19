#!/usr/bin/env python3
import argparse
import hashlib
import hmac
import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json_object(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def hmac_sha256_hex(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_audit_bundle(*,
                        audit_chain_path: str,
                        audit_seal_path: str,
                        job_id: str,
                        hmac_key_env: str) -> tuple[Dict[str, Any], Dict[str, Any], str, str, Optional[bool]]:
    audit_chain = load_json_object(audit_chain_path)
    audit_seal = load_json_object(audit_seal_path)

    if audit_chain.get("schema") != "audit_chain/v1":
        raise ValueError(f"unexpected audit chain schema: {audit_chain.get('schema')}")
    if audit_seal.get("schema") != "audit_seal/v1":
        raise ValueError(f"unexpected audit seal schema: {audit_seal.get('schema')}")
    if str(audit_chain.get("job_id", "")) != job_id:
        raise ValueError(f"audit chain job_id mismatch: expected {job_id}, got {audit_chain.get('job_id')}")
    if str(audit_seal.get("job_id", "")) != job_id:
        raise ValueError(f"audit seal job_id mismatch: expected {job_id}, got {audit_seal.get('job_id')}")

    audit_chain_sha256 = sha256_hex(read_bytes(audit_chain_path))
    if audit_seal.get("artifact_sha256") != audit_chain_sha256:
        raise ValueError("audit seal artifact_sha256 does not match audit_chain.json")

    signature_algorithm = audit_seal.get("signature_algorithm")
    signature = audit_seal.get("signature")
    signature_verified: Optional[bool] = None
    if signature_algorithm is None:
        if signature is not None:
            raise ValueError("audit seal signature must be null when signature_algorithm is null")
    elif signature_algorithm == "hmac-sha256":
        if not isinstance(signature, str) or not signature:
            raise ValueError("audit seal signature must be present for hmac-sha256")
        if hmac_key_env:
            secret = os.environ.get(hmac_key_env)
            if not secret:
                raise ValueError(f"audit archive key env {hmac_key_env} is not set")
            expected = hmac_sha256_hex(secret, audit_chain_sha256)
            if not hmac.compare_digest(signature, expected):
                raise ValueError("audit seal HMAC does not match audit_chain.json")
            signature_verified = True
    else:
        raise ValueError(f"unsupported audit seal signature algorithm: {signature_algorithm}")

    audit_seal_sha256 = sha256_hex(read_bytes(audit_seal_path))
    return audit_chain, audit_seal, audit_chain_sha256, audit_seal_sha256, signature_verified


def copy_if_missing(src: str, dst: str, *, expected_sha256: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    if os.path.exists(dst):
        existing_sha256 = sha256_hex(read_bytes(dst))
        if existing_sha256 != expected_sha256:
            raise ValueError(f"archive path already exists with different contents: {dst}")
        return
    shutil.copy2(src, dst)
    copied_sha256 = sha256_hex(read_bytes(dst))
    if copied_sha256 != expected_sha256:
        raise ValueError(f"archived file hash mismatch after copy: {dst}")


def build_archive_paths(*, archive_dir: str, job_id: str, audit_chain_sha256: str, audit_seal_sha256: str) -> Dict[str, str]:
    archive_root = os.path.abspath(archive_dir)
    return {
        "archive_root": archive_root,
        "audit_chain": os.path.join(archive_root, "audit_chains", f"audit_chain_{job_id}_{audit_chain_sha256}.json"),
        "audit_seal": os.path.join(archive_root, "audit_seals", f"audit_seal_{job_id}_{audit_seal_sha256}.json"),
        "index": os.path.join(archive_root, "audit_chain_index.jsonl"),
    }


def append_index_record(path: str, record: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Archive audit_chain.json plus audit_chain.seal.json into a local audit bundle index.")
    ap.add_argument("--audit-chain", required=True)
    ap.add_argument("--audit-seal", required=True)
    ap.add_argument("--archive-dir", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--hmac-key-env", default="", help="Optional env var used to verify an HMAC-sealed audit bundle")
    args = ap.parse_args()

    audit_chain, audit_seal, audit_chain_sha256, audit_seal_sha256, signature_verified = verify_audit_bundle(
        audit_chain_path=args.audit_chain,
        audit_seal_path=args.audit_seal,
        job_id=args.job_id,
        hmac_key_env=args.hmac_key_env,
    )
    archive_paths = build_archive_paths(
        archive_dir=args.archive_dir,
        job_id=args.job_id,
        audit_chain_sha256=audit_chain_sha256,
        audit_seal_sha256=audit_seal_sha256,
    )
    copy_if_missing(args.audit_chain, archive_paths["audit_chain"], expected_sha256=audit_chain_sha256)
    copy_if_missing(args.audit_seal, archive_paths["audit_seal"], expected_sha256=audit_seal_sha256)

    record = {
        "schema": "audit_archive_index/v1",
        "ts_utc": utc_now_iso(),
        "event": "archive_audit_bundle",
        "job_id": args.job_id,
        "correlation_id": args.job_id,
        "archive_dir": archive_paths["archive_root"],
        "index_file": os.path.abspath(archive_paths["index"]),
        "source_audit_chain_file": os.path.abspath(args.audit_chain),
        "source_audit_seal_file": os.path.abspath(args.audit_seal),
        "archived_audit_chain_file": os.path.abspath(archive_paths["audit_chain"]),
        "archived_audit_seal_file": os.path.abspath(archive_paths["audit_seal"]),
        "audit_chain_sha256": audit_chain_sha256,
        "audit_seal_sha256": audit_seal_sha256,
        "artifact_sha256_verified": True,
        "signature_algorithm": audit_seal.get("signature_algorithm"),
        "signature_verified": signature_verified,
        "secret_source": audit_seal.get("secret_source"),
        "source_out_base": (audit_chain.get("paths") or {}).get("out_base"),
    }
    append_index_record(archive_paths["index"], record)
    print(f"[ok] archived audit bundle: {archive_paths['index']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        raise SystemExit(f"[ERROR] {e}") from e
