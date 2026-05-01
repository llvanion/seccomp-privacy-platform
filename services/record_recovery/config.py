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


def merged_record_recovery_service_scope_value(raw_value: Any, config_value: Any, *, field_name: str) -> str:
    raw = str(raw_value or "").strip()
    config = str(config_value or "").strip()
    if raw and config and raw != config:
        raise ValueError(
            f"conflicting {field_name}: explicit value {raw!r} does not match config value {config!r}"
        )
    return raw or config


def resolve_record_recovery_service_config(config: Dict[str, Any]) -> Dict[str, Any]:
    lifecycle = config.get("lifecycle")
    if lifecycle is None:
        lifecycle = {}
    if not isinstance(lifecycle, dict):
        raise ValueError("record recovery service lifecycle must be an object")
    http_listener = config.get("http_listener")
    if http_listener is None:
        http_listener = {}
    if not isinstance(http_listener, dict):
        raise ValueError("record recovery service http_listener must be an object")

    transport = str(config.get("transport", "") or "").strip()
    if not transport:
        transport = "http" if config.get("endpoint_url") or http_listener else "unix_socket"
    if transport not in {"unix_socket", "http"}:
        raise ValueError("record recovery service transport must be unix_socket or http")

    socket_path = resolve_relative_path(config, str(config.get("socket_path", ""))) if config.get("socket_path") else ""
    endpoint_url = str(config.get("endpoint_url", "") or "").strip()
    bind_host = str(http_listener.get("bind_host", "") or "").strip()
    port = int(http_listener.get("port")) if http_listener.get("port") not in (None, "") else None
    if not endpoint_url and transport == "http" and bind_host and port is not None:
        endpoint_url = f"http://{bind_host}:{port}"

    if transport == "unix_socket" and not socket_path:
        raise ValueError("record recovery service unix_socket transport requires socket_path")
    if transport == "http" and not endpoint_url:
        raise ValueError("record recovery service http transport requires endpoint_url or http_listener")

    return {
        "transport": transport,
        "service_id": str(config.get("service_id", "") or ""),
        "tenant_id": str(config.get("tenant_id", "") or ""),
        "dataset_id": str(config.get("dataset_id", "") or ""),
        "socket_path": socket_path,
        "socket_mode": str(config.get("socket_mode", "600") or "600") if transport == "unix_socket" else "",
        "endpoint_url": endpoint_url,
        "bind_host": bind_host,
        "port": port,
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
