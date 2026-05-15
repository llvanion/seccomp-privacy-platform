#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, NoReturn


def die(msg: str) -> NoReturn:
    raise SystemExit(f"[ERROR] {msg}")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json_object(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        die(f"{path} must contain a JSON object")
    return data


def append_jsonl(path: str, record: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def key_entry(manifest: Dict[str, Any], key_id: str) -> Dict[str, Any]:
    keys = manifest.get("keys")
    if not isinstance(keys, dict):
        die("key manifest must contain a keys object")
    entry = keys.get(key_id)
    if not isinstance(entry, dict):
        die(f"unknown key id: {key_id}")
    return entry


def ensure_key_allowed(entry: Dict[str, Any], *, key_id: str, purpose: str) -> None:
    if entry.get("enabled", True) is not True:
        die(f"key {key_id} is disabled")
    if entry.get("status", "active") != "active":
        die(f"key {key_id} is not active")
    allowed_purposes = entry.get("purposes", [])
    if not isinstance(allowed_purposes, list):
        die(f"key {key_id} purposes must be a list")
    if purpose not in {str(item) for item in allowed_purposes}:
        die(f"key {key_id} cannot be used for purpose {purpose}")
    env = entry.get("env")
    if not env:
        die(f"key {key_id} is missing env")
    if os.environ.get(str(env)) is None:
        die(f"environment variable for key {key_id} is not set")


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve a key id to an env-var secret reference without printing the secret.")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--key-id", required=True)
    ap.add_argument("--purpose", required=True)
    ap.add_argument("--caller", required=True)
    ap.add_argument("--job-id", default="")
    ap.add_argument("--tenant-id", default="")
    ap.add_argument("--dataset-id", default="")
    ap.add_argument("--audit-log", required=True)
    args = ap.parse_args()

    manifest = load_json_object(args.manifest)
    entry = key_entry(manifest, args.key_id)
    ensure_key_allowed(entry, key_id=args.key_id, purpose=args.purpose)

    result = {
        "key_id": args.key_id,
        "key_version": str(entry.get("version", args.key_id)),
        "env": str(entry["env"]),
    }
    append_jsonl(args.audit_log, {
        "schema": "key_access_audit/v1",
        "ts_utc": utc_now_iso(),
        "event": "key_access",
        "caller": args.caller,
        "job_id": args.job_id or None,
        "correlation_id": args.job_id or None,
        "tenant_id": args.tenant_id or None,
        "dataset_id": args.dataset_id or None,
        "key_id": args.key_id,
        "key_version": result["key_version"],
        "purpose": args.purpose,
        "decision": "allow",
        "reason_code": "ok",
        "manifest_file": os.path.abspath(args.manifest),
        "manifest_sha256": sha256_file(args.manifest),
        "secret_source": {"kind": "env", "name": result["env"]},
        "resolver": {"kind": "manifest_resolver", "socket_path": None},
    })
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
