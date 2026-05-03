#!/usr/bin/env python3
import ipaddress
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict


EXTERNAL_KMS_CONFIG_SCHEMA = "external_kms_config/v1"


def load_json_object(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def load_external_kms_config(path: str) -> Dict[str, Any]:
    config = load_json_object(path)
    if config.get("schema") != EXTERNAL_KMS_CONFIG_SCHEMA:
        raise ValueError(f"unsupported external KMS config schema: {config.get('schema')}")
    config["_config_file"] = os.path.abspath(path)
    config["_config_dir"] = os.path.dirname(config["_config_file"])
    return config


def endpoint_url(config: Dict[str, Any]) -> str:
    value = str(config.get("endpoint_url", "")).strip()
    if not value:
        raise ValueError("external KMS config is missing endpoint_url")
    return value.rstrip("/")


def request_timeout_sec(config: Dict[str, Any]) -> float:
    value = config.get("request_timeout_sec", 5)
    try:
        timeout = float(value)
    except (TypeError, ValueError) as e:
        raise ValueError("external KMS request_timeout_sec must be numeric") from e
    if timeout <= 0:
        raise ValueError("external KMS request_timeout_sec must be positive")
    return timeout


def resolve_relative_path(config: Dict[str, Any], path_value: str) -> str:
    if os.path.isabs(path_value):
        return path_value
    config_dir = str(config.get("_config_dir", ""))
    if not config_dir:
        raise ValueError("external KMS config missing _config_dir")
    return os.path.abspath(os.path.join(config_dir, path_value))


def auth_env_name(config: Dict[str, Any], *, admin: bool) -> str:
    field = "admin_auth_token_env" if admin else "auth_token_env"
    value = config.get(field, "")
    if value is None:
        return ""
    return str(value).strip()


def auth_token(config: Dict[str, Any], *, admin: bool) -> str:
    env_name = auth_env_name(config, admin=admin)
    if not env_name:
        return ""
    value = os.environ.get(env_name, "")
    if not value:
        raise ValueError(f"environment variable {env_name} is not set")
    return value


def auto_start_config(config: Dict[str, Any]) -> Dict[str, Any]:
    value = config.get("auto_start")
    if not isinstance(value, dict):
        raise ValueError("external KMS config is missing auto_start")
    return value


def endpoint_url_from_parts(bind_host: str, port: int) -> str:
    return f"http://{bind_host}:{port}"


def _should_bypass_proxy(url: str) -> bool:
    hostname = urllib.parse.urlsplit(url).hostname
    if not hostname:
        return False
    lowered = hostname.lower()
    if lowered == "localhost" or lowered.endswith(".localhost"):
        return True
    try:
        parsed_ip = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return parsed_ip.is_loopback or parsed_ip.is_private or parsed_ip.is_link_local


def _open_request(request: urllib.request.Request, *, timeout: float):
    if _should_bypass_proxy(request.full_url):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


def _json_request(config: Dict[str, Any], *,
                  method: str,
                  path: str,
                  payload: Dict[str, Any] | None = None,
                  admin: bool = False,
                  bearer_token_override: str = "") -> Dict[str, Any]:
    base_url = endpoint_url(config)
    url = urllib.parse.urljoin(base_url + "/", path.lstrip("/"))
    headers = {"Accept": "application/json"}
    token = bearer_token_override or auth_token(config, admin=admin)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    timeout = request_timeout_sec(config)
    try:
        with _open_request(request, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raw = e.read()
        if raw:
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict) and data.get("schema") == "external_kms_error/v1":
                raise RuntimeError(str(data.get("error", "external KMS request failed"))) from e
        raise RuntimeError(f"external KMS HTTP error: {e.code}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"external KMS request failed: {e.reason}") from e

    if not raw:
        raise RuntimeError("external KMS returned an empty response")
    try:
        result = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"external KMS returned invalid JSON: {e}") from e
    if not isinstance(result, dict):
        raise RuntimeError("external KMS returned a non-object response")
    if result.get("schema") == "external_kms_error/v1":
        raise RuntimeError(str(result.get("error", "external KMS request failed")))
    return result


def resolve_secret_via_external_kms(config: Dict[str, Any], *,
                                    key_name: str,
                                    purpose: str,
                                    caller: str,
                                    job_id: str,
                                    identity_bearer_token: str = "") -> Dict[str, Any]:
    return _json_request(
        config,
        method="POST",
        path="/v1/resolve",
        payload={
            "key_name": key_name,
            "purpose": purpose,
            "caller": caller,
            "job_id": job_id,
        },
        admin=False,
        bearer_token_override=identity_bearer_token,
    )


def rotate_external_key(config: Dict[str, Any], *,
                        key_name: str,
                        purpose: str,
                        new_version: str,
                        secret_env: str,
                        secret_ref_kind: str = "",
                        secret_ref_name: str = "",
                        secret_ref_version: str = "",
                        secret_ref_field: str = "",
                        caller: str,
                        activate: bool,
                        create_key: bool,
                        identity_bearer_token: str = "") -> Dict[str, Any]:
    return _json_request(
        config,
        method="POST",
        path="/v1/admin/rotate",
        payload={
            "key_name": key_name,
            "purpose": purpose,
            "new_version": new_version,
            "secret_env": secret_env,
            "secret_ref_kind": secret_ref_kind,
            "secret_ref_name": secret_ref_name,
            "secret_ref_version": secret_ref_version,
            "secret_ref_field": secret_ref_field,
            "caller": caller,
            "activate": activate,
            "create_key": create_key,
        },
        admin=True,
        bearer_token_override=identity_bearer_token,
    )


def set_external_key_status(config: Dict[str, Any], *,
                            key_name: str,
                            version: str,
                            status: str,
                            caller: str,
                            identity_bearer_token: str = "") -> Dict[str, Any]:
    return _json_request(
        config,
        method="POST",
        path="/v1/admin/set-status",
        payload={
            "key_name": key_name,
            "version": version,
            "status": status,
            "caller": caller,
        },
        admin=True,
        bearer_token_override=identity_bearer_token,
    )


def check_external_kms_health(config: Dict[str, Any]) -> Dict[str, Any]:
    return _json_request(config, method="GET", path="/healthz")
