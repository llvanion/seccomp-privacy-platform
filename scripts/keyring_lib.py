#!/usr/bin/env python3
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Tuple


KEYRING_SCHEMA = "keyring/v1"
KEY_LIFECYCLE_AUDIT_SCHEMA = "key_lifecycle_audit/v1"
KEY_ACCESS_AUDIT_SCHEMA = "key_access_audit/v1"
VAULT_KV_BACKEND_SCHEMA = "vault_kv_backend/v1"


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
        raise ValueError(f"{path} must contain a JSON object")
    return data


def save_json_object(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def append_jsonl(path: str, record: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _keys_object(keyring: Dict[str, Any]) -> Dict[str, Any]:
    if keyring.get("schema") != KEYRING_SCHEMA:
        raise ValueError(f"unsupported keyring schema: {keyring.get('schema')}")
    keys = keyring.get("keys")
    if not isinstance(keys, dict):
        raise ValueError("keyring must contain a keys object")
    return keys


def key_entry(keyring: Dict[str, Any], key_name: str) -> Dict[str, Any]:
    keys = _keys_object(keyring)
    entry = keys.get(key_name)
    if not isinstance(entry, dict):
        raise ValueError(f"unknown key name: {key_name}")
    return entry


def version_entry(key_entry_value: Dict[str, Any], version: str) -> Dict[str, Any]:
    versions = key_entry_value.get("versions")
    if not isinstance(versions, dict):
        raise ValueError("key entry must contain a versions object")
    entry = versions.get(version)
    if not isinstance(entry, dict):
        raise ValueError(f"unknown key version: {version}")
    return entry


def active_version(key_entry_value: Dict[str, Any]) -> str:
    version = key_entry_value.get("active_version")
    if not version:
        raise ValueError("key entry does not have an active_version")
    return str(version)


def resolve_active_key(keyring: Dict[str, Any], *, key_name: str) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    key_value = key_entry(keyring, key_name)
    version = active_version(key_value)
    version_value = version_entry(key_value, version)
    return version, key_value, version_value


def normalize_secret_ref(secret_ref: Any) -> Dict[str, Any]:
    if not isinstance(secret_ref, dict):
        raise ValueError("secret_ref must be an object")
    kind = str(secret_ref.get("kind", "") or "").strip()
    name = str(secret_ref.get("name", "") or "").strip()
    if not kind:
        raise ValueError("secret_ref.kind is required")
    if not name:
        raise ValueError("secret_ref.name is required")
    if kind == "env":
        return {
            "kind": kind,
            "name": name,
        }
    if kind in ("vault_kv", "vault_http"):
        value: Dict[str, Any] = {
            "kind": kind,
            "name": name,
        }
        version = str(secret_ref.get("version", "") or "").strip()
        field = str(secret_ref.get("field", "") or "").strip()
        if version:
            value["version"] = version
        if field:
            value["field"] = field
        return value
    raise ValueError(f"unsupported secret_ref kind {kind}")


def load_vault_kv_backend(path: str) -> Dict[str, Any]:
    payload = load_json_object(path)
    if payload.get("schema") != VAULT_KV_BACKEND_SCHEMA:
        raise ValueError(f"unsupported vault backend schema: {payload.get('schema')}")
    secrets = payload.get("secrets")
    if not isinstance(secrets, dict):
        raise ValueError("vault backend must contain a secrets object")
    return payload


def resolve_secret_ref(*, secret_ref: Dict[str, Any], vault_kv_file: str = "", vault_http_config: Dict[str, Any] | None = None) -> str:
    normalized = normalize_secret_ref(secret_ref)
    kind = normalized["kind"]
    if kind == "env":
        secret = os.environ.get(normalized["name"])
        if secret is None:
            raise PermissionError(f"environment variable for secret_ref {normalized['name']} is not set")
        return secret
    if kind == "vault_kv":
        if not vault_kv_file:
            raise PermissionError("vault_kv secret_ref requires a vault backend file")
        backend = load_vault_kv_backend(vault_kv_file)
        secret_entry = backend["secrets"].get(normalized["name"])
        if not isinstance(secret_entry, dict):
            raise PermissionError(f"vault_kv secret path not found: {normalized['name']}")
        versions = secret_entry.get("versions")
        if not isinstance(versions, dict):
            raise ValueError(f"vault_kv secret path {normalized['name']} is missing versions")
        version = str(normalized.get("version") or secret_entry.get("current_version") or "").strip()
        if not version:
            raise ValueError(f"vault_kv secret path {normalized['name']} is missing current_version")
        version_entry_value = versions.get(version)
        if not isinstance(version_entry_value, dict):
            raise PermissionError(f"vault_kv secret version not found: {normalized['name']}#{version}")
        fields = version_entry_value.get("fields")
        if not isinstance(fields, dict):
            raise ValueError(f"vault_kv secret path {normalized['name']} version {version} is missing fields")
        field = str(normalized.get("field") or "value")
        secret = fields.get(field)
        if not isinstance(secret, str):
            raise PermissionError(f"vault_kv secret field not found: {normalized['name']}#{version}:{field}")
        return secret
    if kind == "vault_http":
        # Import here to avoid circular dependency at module load time
        import importlib
        vh = importlib.import_module("scripts.vault_http_client")
        value, _ = vh.resolve_vault_http_secret_ref(
            secret_ref=normalized,
            client_config=vault_http_config,
            mock_file=vault_kv_file,
        )
        return value
    raise ValueError(f"unsupported secret_ref kind {kind}")


def ensure_key_access_allowed(*,
                              keyring: Dict[str, Any],
                              key_name: str,
                              purpose: str,
                              caller: str) -> Tuple[str, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    version, key_value, version_value = resolve_active_key(keyring, key_name=key_name)

    key_purpose = str(key_value.get("purpose", ""))
    if not key_purpose:
        raise ValueError(f"key {key_name} is missing purpose")
    if key_purpose != purpose:
        raise PermissionError(f"key {key_name} cannot be used for purpose {purpose}")

    if version_value.get("enabled", True) is not True:
        raise PermissionError(f"key {key_name} version {version} is disabled")
    if version_value.get("status", "active") != "active":
        raise PermissionError(f"key {key_name} version {version} is not active")

    allowed_callers = key_value.get("allowed_callers", [])
    if allowed_callers is None:
        allowed_callers = []
    if not isinstance(allowed_callers, list):
        raise ValueError(f"key {key_name} allowed_callers must be a list")
    if allowed_callers and caller not in {str(item) for item in allowed_callers}:
        raise PermissionError(f"caller {caller} is not allowed to access key {key_name}")

    secret_ref = version_value.get("secret_ref")
    normalized_secret_ref = normalize_secret_ref(secret_ref)
    return version, key_value, version_value, normalized_secret_ref


def promote_version(*, keyring: Dict[str, Any], key_name: str, version: str) -> None:
    key_value = key_entry(keyring, key_name)
    versions = key_value["versions"]
    target = version_entry(key_value, version)
    target["enabled"] = True
    target["status"] = "active"
    previous_active = str(key_value.get("active_version") or "")
    for version_name, value in versions.items():
        if not isinstance(value, dict):
            raise ValueError("key versions must be objects")
        if version_name == version:
            continue
        if value.get("status") == "active":
            value["status"] = "inactive"
    key_value["active_version"] = version
    if previous_active and previous_active != version and previous_active in versions:
        previous = versions[previous_active]
        if isinstance(previous, dict) and previous.get("status") == "active":
            previous["status"] = "inactive"


def set_version_status(*, keyring: Dict[str, Any], key_name: str, version: str, status: str) -> None:
    if status not in {"active", "inactive", "retired"}:
        raise ValueError(f"unsupported key status: {status}")
    key_value = key_entry(keyring, key_name)
    target = version_entry(key_value, version)
    target["status"] = status
    if status == "active":
        target["enabled"] = True
        promote_version(keyring=keyring, key_name=key_name, version=version)
        return
    if str(key_value.get("active_version") or "") == version:
        key_value["active_version"] = None


def rotate_key(*,
               keyring: Dict[str, Any],
               key_name: str,
               purpose: str,
               new_version: str,
               caller: str,
               activate: bool,
               secret_env: str = "",
               secret_ref: Dict[str, Any] | None = None,
               create_key: bool = False) -> None:
    keys = _keys_object(keyring)
    key_value = keys.get(key_name)
    if key_value is None:
        if not create_key:
            raise ValueError(f"unknown key name: {key_name}")
        key_value = {
            "purpose": purpose,
            "active_version": None,
            "allowed_callers": [caller],
            "versions": {},
        }
        keys[key_name] = key_value
    if not isinstance(key_value, dict):
        raise ValueError(f"key {key_name} must be an object")

    if key_value.get("purpose") != purpose:
        raise ValueError(f"key {key_name} purpose mismatch: expected {key_value.get('purpose')} got {purpose}")

    versions = key_value.get("versions")
    if not isinstance(versions, dict):
        raise ValueError(f"key {key_name} versions must be an object")
    if new_version in versions:
        raise ValueError(f"key {key_name} version {new_version} already exists")

    if secret_ref is None:
        if not secret_env:
            raise ValueError("secret_env or secret_ref is required")
        secret_ref_value = {
            "kind": "env",
            "name": secret_env,
        }
    else:
        secret_ref_value = normalize_secret_ref(secret_ref)

    versions[new_version] = {
        "enabled": True,
        "status": "active" if activate else "inactive",
        "created_at_utc": utc_now_iso(),
        "secret_ref": secret_ref_value,
    }
    if activate:
        promote_version(keyring=keyring, key_name=key_name, version=new_version)


def append_key_access_audit(*,
                            path: str,
                            caller: str,
                            job_id: str,
                            key_id: str,
                            key_version: str,
                            purpose: str,
                            decision: str,
                            reason_code: str,
                            config_file: str,
                            secret_source_kind: str,
                            secret_source_name: str,
                            resolver_kind: str,
                            socket_path: str | None = None,
                            endpoint_url: str | None = None,
                            reason: str | None = None) -> None:
    record: Dict[str, Any] = {
        "schema": KEY_ACCESS_AUDIT_SCHEMA,
        "ts_utc": utc_now_iso(),
        "event": "key_access",
        "caller": caller,
        "job_id": job_id or None,
        "correlation_id": job_id or None,
        "key_id": key_id,
        "key_version": key_version,
        "purpose": purpose,
        "decision": decision,
        "reason_code": reason_code,
        "manifest_file": os.path.abspath(config_file),
        "manifest_sha256": sha256_file(config_file),
        "secret_source": {
            "kind": secret_source_kind,
            "name": secret_source_name,
        },
        "resolver": {
            "kind": resolver_kind,
            "socket_path": socket_path,
            "endpoint_url": endpoint_url,
        },
    }
    if reason is not None:
        record["reason"] = reason
    append_jsonl(path, record)


def append_key_lifecycle_audit(*,
                               path: str,
                               caller: str,
                               keyring_file: str,
                               key_name: str,
                               key_version: str,
                               action: str,
                               status: str,
                               decision: str,
                               reason_code: str,
                               secret_source_kind: str = "env",
                               secret_source_name: str | None = None,
                               reason: str | None = None) -> None:
    record: Dict[str, Any] = {
        "schema": KEY_LIFECYCLE_AUDIT_SCHEMA,
        "ts_utc": utc_now_iso(),
        "event": "key_lifecycle_change",
        "caller": caller,
        "key_name": key_name,
        "key_version": key_version,
        "action": action,
        "status": status,
        "decision": decision,
        "reason_code": reason_code,
        "keyring_file": os.path.abspath(keyring_file),
        "keyring_sha256": sha256_file(keyring_file),
        "secret_source": {
            "kind": secret_source_kind,
            "name": secret_source_name,
        },
    }
    if reason is not None:
        record["reason"] = reason
    append_jsonl(path, record)
