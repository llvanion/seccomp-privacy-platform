# -*- coding:utf-8 _*-
import json
from pathlib import Path
from typing import Any, Dict


POLICY_SCHEMA = "sse_export_policy/v1"


def load_platform_policy(path: str) -> Dict[str, Any]:
    if not path:
        return {}
    policy_path = Path(path)
    with policy_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("platform policy config must be a JSON object")
    schema = data.get("schema")
    if schema is not None and schema != POLICY_SCHEMA:
        raise ValueError(f"unsupported platform policy schema: {schema}")
    return data


def platform_policy_for_caller(policy: Dict[str, Any], caller: str) -> Dict[str, Any]:
    if not policy:
        return {}
    callers = policy.get("callers")
    if not isinstance(callers, dict):
        raise ValueError("platform policy config must contain a callers object")
    caller_policy = callers.get(caller)
    if not isinstance(caller_policy, dict):
        raise PermissionError(f"caller {caller} is not allowed")
    if caller_policy.get("enabled", True) is False:
        raise PermissionError(f"caller {caller} is disabled")
    return caller_policy


def platform_policy_string_set(caller_policy: Dict[str, Any], key: str) -> set[str]:
    raw = caller_policy.get(key, [])
    if raw is None:
        return set()
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be a list")
    return {str(item) for item in raw}


def require_platform_permission(caller_policy: Dict[str, Any], key: str, caller: str) -> None:
    if caller_policy.get(key) is not True:
        raise PermissionError(f"caller {caller} is missing permission {key}=true")


def resolve_platform_scope(*,
                           caller_policy: Dict[str, Any],
                           caller: str,
                           tenant_id: str = "",
                           dataset_id: str = "",
                           service_id: str = "",
                           require_record_recovery_service: bool = False) -> Dict[str, str]:
    effective_tenant_id = str(caller_policy.get("tenant_id") or "").strip()
    requested_tenant_id = str(tenant_id or "").strip()
    if effective_tenant_id and requested_tenant_id and requested_tenant_id != effective_tenant_id:
        raise PermissionError(
            f"caller {caller} cannot use tenant_id {requested_tenant_id}; expected {effective_tenant_id}"
        )
    if requested_tenant_id:
        effective_tenant_id = requested_tenant_id

    allowed_dataset_ids = platform_policy_string_set(caller_policy, "allowed_dataset_ids")
    requested_dataset_id = str(dataset_id or "").strip()
    effective_dataset_id = requested_dataset_id
    if requested_dataset_id:
        if allowed_dataset_ids and requested_dataset_id not in allowed_dataset_ids:
            raise PermissionError(f"caller {caller} cannot use dataset_id {requested_dataset_id}")
    elif len(allowed_dataset_ids) == 1:
        effective_dataset_id = next(iter(allowed_dataset_ids))
    elif len(allowed_dataset_ids) > 1:
        raise PermissionError(f"caller {caller} must specify dataset_id")

    allowed_service_ids = platform_policy_string_set(caller_policy, "allowed_service_ids")
    requested_service_id = str(service_id or "").strip()
    effective_service_id = requested_service_id
    if requested_service_id:
        if allowed_service_ids and requested_service_id not in allowed_service_ids:
            raise PermissionError(f"caller {caller} cannot use service_id {requested_service_id}")
    elif require_record_recovery_service and len(allowed_service_ids) == 1:
        effective_service_id = next(iter(allowed_service_ids))
    elif require_record_recovery_service and len(allowed_service_ids) > 1:
        raise PermissionError(f"caller {caller} must specify service_id")

    if require_record_recovery_service:
        require_platform_permission(caller_policy, "can_use_record_recovery_service", caller)

    return {
        "tenant_id": effective_tenant_id,
        "dataset_id": effective_dataset_id,
        "service_id": effective_service_id,
    }
