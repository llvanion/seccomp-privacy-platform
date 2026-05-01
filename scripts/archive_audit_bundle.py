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


def canonical_json_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(payload: Dict[str, Any]) -> str:
    return sha256_hex(canonical_json_bytes(payload))


def archive_index_hash_payload(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if key not in {"anchor_file", "anchor_entry_sha256"}
    }


def archive_index_record_sha256(record: Dict[str, Any]) -> str:
    return sha256_json(archive_index_hash_payload(record))


def load_json_object(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def stringify(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def role_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        role = stringify(record.get("role"))
        if role:
            result[role] = record
    return result


def hmac_sha256_hex(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def load_jsonl_objects(path: str) -> list[Dict[str, Any]]:
    records: list[Dict[str, Any]] = []
    if not os.path.isfile(path):
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


def anchor_signature_algorithm(anchor_key_env: str) -> str | None:
    return "hmac-sha256" if anchor_key_env else None


def anchor_secret_source(anchor_key_env: str) -> Dict[str, Any] | None:
    if not anchor_key_env:
        return None
    return {
        "kind": "env",
        "env": anchor_key_env,
    }


def build_anchor_paths(*, archive_dir: str) -> Dict[str, str]:
    archive_root = os.path.abspath(archive_dir)
    return {
        "anchor_root": archive_root,
        "anchor_file": os.path.join(archive_root, "audit_chain_anchor.jsonl"),
    }


def anchor_payload_fields(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if key not in {"payload_sha256", "entry_sha256", "signature"}
    }


def compute_anchor_payload_sha256(record: Dict[str, Any]) -> str:
    return sha256_json(anchor_payload_fields(record))


def compute_anchor_entry_sha256(*, previous_anchor_entry_sha256: str | None, payload_sha256: str) -> str:
    message = f"{previous_anchor_entry_sha256 or ''}\n{payload_sha256}"
    return sha256_hex(message.encode("utf-8"))


def sign_anchor_entry(*, anchor_key_env: str, entry_sha256: str) -> str | None:
    if not anchor_key_env:
        return None
    secret = os.environ.get(anchor_key_env)
    if not secret:
        raise ValueError(f"audit archive anchor key env {anchor_key_env} is not set")
    return hmac_sha256_hex(secret, entry_sha256)


def last_anchor_entry(path: str) -> Dict[str, Any] | None:
    records = load_jsonl_objects(path)
    if not records:
        return None
    return records[-1]


def summarize_mainline_contract(audit_chain: Dict[str, Any]) -> Dict[str, Any]:
    payload = (
        audit_chain.get("mainline_contract_check")
        if isinstance(audit_chain.get("mainline_contract_check"), dict)
        else {}
    )
    findings = payload.get("findings") if isinstance(payload.get("findings"), list) else []
    handoff_cleanup = payload.get("handoff_cleanup") if isinstance(payload.get("handoff_cleanup"), dict) else {}
    sse_by_role = role_records(
        [
            record
            for record in (audit_chain.get("sse_export_audit") or [])
            if isinstance(record, dict)
        ]
    )
    service_boundary_roles = {
        role_name
        for role_name in ("server", "client")
        if stringify((sse_by_role.get(role_name) or {}).get("record_recovery_boundary")) in {"service_socket", "service_http"}
    }
    service_finding_kinds = [
        str(item.get("kind", ""))
        for item in findings
        if isinstance(item, dict)
    ]
    global_service_failures = {
        kind
        for kind in service_finding_kinds
        if kind in {"missing_service_audit", "service_transport_mismatch"}
    }
    service_audit_consistency = {
        role_name: (
            None
            if not payload
            else "not_applicable"
            if role_name not in service_boundary_roles
            else "fail"
            if global_service_failures
            or any(
                kind == f"missing_{role_name}_service_audit"
                or kind.startswith(f"{role_name}_service_")
                for kind in service_finding_kinds
            )
            else "ok"
        )
        for role_name in ("server", "client")
    }
    return {
        "schema": payload.get("schema"),
        "status": payload.get("status"),
        "embedded_in_audit_chain": bool(payload),
        "handoff_cleanup": {
            role_name: (
                handoff_cleanup.get(role_name).get("status")
                if isinstance(handoff_cleanup.get(role_name), dict)
                else None
            )
            for role_name in ("server", "client")
        },
        "service_audit_consistency": {
            **service_audit_consistency,
            "error_count": len(
                [
                    kind
                    for kind in service_finding_kinds
                    if kind in global_service_failures
                    or any(
                        kind == f"missing_{role_name}_service_audit"
                        or kind.startswith(f"{role_name}_service_")
                        for role_name in ("server", "client")
                    )
                ]
            ),
        },
    }


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


def append_anchor_record(path: str, record: Dict[str, Any]) -> None:
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
    ap.add_argument(
        "--anchor-key-env",
        default="",
        help="Optional env var used to HMAC-sign append-only archive anchor records",
    )
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
    anchor_paths = build_anchor_paths(archive_dir=args.archive_dir)
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
        "mainline_contract_summary": summarize_mainline_contract(audit_chain),
    }
    index_record_sha256 = archive_index_record_sha256(record)
    previous_anchor_entry = last_anchor_entry(anchor_paths["anchor_file"])
    previous_anchor_entry_sha256 = stringify((previous_anchor_entry or {}).get("entry_sha256"))
    anchor_record = {
        "schema": "audit_archive_anchor/v1",
        "ts_utc": utc_now_iso(),
        "event": "anchor_audit_bundle",
        "job_id": args.job_id,
        "correlation_id": args.job_id,
        "archive_dir": archive_paths["archive_root"],
        "anchor_file": os.path.abspath(anchor_paths["anchor_file"]),
        "index_file": os.path.abspath(archive_paths["index"]),
        "archived_audit_chain_file": os.path.abspath(archive_paths["audit_chain"]),
        "archived_audit_seal_file": os.path.abspath(archive_paths["audit_seal"]),
        "index_record_sha256": index_record_sha256,
        "previous_anchor_entry_sha256": previous_anchor_entry_sha256,
        "chain_position": (int(previous_anchor_entry.get("chain_position", 0)) if isinstance(previous_anchor_entry, dict) else 0) + 1,
        "signature_algorithm": anchor_signature_algorithm(args.anchor_key_env),
        "secret_source": anchor_secret_source(args.anchor_key_env),
    }
    anchor_record["payload_sha256"] = compute_anchor_payload_sha256(anchor_record)
    anchor_record["entry_sha256"] = compute_anchor_entry_sha256(
        previous_anchor_entry_sha256=previous_anchor_entry_sha256,
        payload_sha256=anchor_record["payload_sha256"],
    )
    anchor_record["signature"] = sign_anchor_entry(
        anchor_key_env=args.anchor_key_env,
        entry_sha256=anchor_record["entry_sha256"],
    )
    record["anchor_file"] = os.path.abspath(anchor_paths["anchor_file"])
    record["anchor_entry_sha256"] = anchor_record["entry_sha256"]
    append_index_record(archive_paths["index"], record)
    append_anchor_record(anchor_paths["anchor_file"], anchor_record)
    print(f"[ok] archived audit bundle: {archive_paths['index']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        raise SystemExit(f"[ERROR] {e}") from e
