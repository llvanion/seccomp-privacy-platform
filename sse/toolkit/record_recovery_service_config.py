# -*- coding:utf-8 _*-
import json
from pathlib import Path
from typing import Any, Dict


CONFIG_SCHEMA = "record_recovery_service_config/v1"


def load_json_object(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def load_record_recovery_service_config(path: str) -> Dict[str, Any]:
    config = load_json_object(path)
    if config.get("schema") != CONFIG_SCHEMA:
        raise ValueError(f"unsupported record recovery service config schema: {config.get('schema')}")
    config["_config_file"] = str(Path(path).resolve())
    config["_config_dir"] = str(Path(path).resolve().parent)
    return config


def load_resolved_record_recovery_service_config(path: str) -> Dict[str, Any]:
    return resolve_record_recovery_service_config(load_record_recovery_service_config(path))


def resolve_relative_path(config: Dict[str, Any], path_value: str) -> str:
    path = Path(path_value)
    if path.is_absolute():
        return str(path)
    config_dir = config.get("_config_dir")
    if not config_dir:
        raise ValueError("record recovery service config missing _config_dir")
    return str((Path(config_dir) / path).resolve())


def _string_list(value: Any, *, field_name: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return [str(item) for item in value]


def merged_record_recovery_service_value(raw_value: Any, config_value: Any) -> Any:
    if raw_value in (None, "", []):
        return config_value
    return raw_value


def resolve_record_recovery_service_config(config: Dict[str, Any]) -> Dict[str, Any]:
    lifecycle = config.get("lifecycle")
    if lifecycle is None:
        lifecycle = {}
    if not isinstance(lifecycle, dict):
        raise ValueError("record recovery service lifecycle must be an object")

    result = {
        "service_id": str(config.get("service_id", "") or ""),
        "tenant_id": str(config.get("tenant_id", "") or ""),
        "dataset_id": str(config.get("dataset_id", "") or ""),
        "socket_path": resolve_relative_path(config, str(config.get("socket_path", ""))) if config.get("socket_path") else "",
        "socket_mode": str(config.get("socket_mode", "600") or "600"),
        "auth_token_env": str(config.get("auth_token_env", "") or ""),
        "authz_config": resolve_relative_path(config, str(config.get("authz_config", ""))) if config.get("authz_config") else "",
        "allowed_callers": _string_list(config.get("allowed_callers", []), field_name="allowed_callers"),
        "allowed_output_roots": [
            resolve_relative_path(config, value)
            for value in _string_list(config.get("allowed_output_roots", []), field_name="allowed_output_roots")
        ],
        "allowed_record_store_roots": [
            resolve_relative_path(config, value)
            for value in _string_list(config.get("allowed_record_store_roots", []), field_name="allowed_record_store_roots")
        ],
        "audit_log": resolve_relative_path(config, str(config.get("audit_log", ""))) if config.get("audit_log") else "",
        "pid_file": resolve_relative_path(config, str(lifecycle.get("pid_file", ""))) if lifecycle.get("pid_file") else "",
        "ready_file": resolve_relative_path(config, str(lifecycle.get("ready_file", ""))) if lifecycle.get("ready_file") else "",
        "log_file": resolve_relative_path(config, str(lifecycle.get("log_file", ""))) if lifecycle.get("log_file") else "",
    }
    return result
