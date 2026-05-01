# -*- coding:utf-8 _*-
import json
from pathlib import Path

from services.record_recovery.bootstrap import ensure_repo_paths


ensure_repo_paths()

from toolkit.platform_policy import (  # noqa: E402
    load_platform_policy,
    platform_policy_for_caller,
    resolve_platform_scope,
)


POLICY_SCHEMA = "record_recovery_service_policy/v1"
PLATFORM_POLICY_SCHEMA = "sse_export_policy/v1"


def load_authz_policy(path: str) -> dict:
    if not path:
        return {}
    policy_path = Path(path)
    with policy_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("record recovery authz config must be a JSON object")
    schema = data.get("schema")
    if schema == PLATFORM_POLICY_SCHEMA:
        return load_platform_policy(path)
    if schema is not None and schema not in {POLICY_SCHEMA, PLATFORM_POLICY_SCHEMA}:
        raise ValueError(f"unsupported record recovery authz schema: {schema}")
    return data


def _as_set(policy: dict, key: str) -> set[str]:
    raw = policy.get(key, [])
    if raw is None:
        return set()
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be a list")
    return {str(item) for item in raw}


def _ensure_prefix(path: Path, prefixes: list[str], field_name: str) -> None:
    if not prefixes:
        return
    resolved = path.resolve()
    for raw_prefix in prefixes:
        prefix = Path(str(raw_prefix)).resolve()
        try:
            resolved.relative_to(prefix)
            return
        except ValueError:
            continue
    raise PermissionError(f"{field_name} {resolved} is outside allowed prefixes")


def _ensure_allowed_filter_values(policy: dict, filters: list[tuple[str, str]], caller: str) -> None:
    allowed_filter_values = policy.get("allowed_filter_values", {})
    if allowed_filter_values is None:
        allowed_filter_values = {}
    if not isinstance(allowed_filter_values, dict):
        raise ValueError("allowed_filter_values must be an object")
    for field, value in filters:
        allowed_values = allowed_filter_values.get(field)
        if allowed_values is None:
            continue
        if not isinstance(allowed_values, list):
            raise ValueError(f"allowed_filter_values.{field} must be a list")
        if str(value) not in {str(item) for item in allowed_values}:
            raise PermissionError(f"caller {caller} cannot use filter {field}={value}")


def _effective_min_rows(requested_min_rows: int | None, policy_min_rows: int | None) -> int | None:
    if requested_min_rows is None:
        return policy_min_rows
    if policy_min_rows is None:
        return requested_min_rows
    return max(requested_min_rows, policy_min_rows)


def _effective_max_rows(requested_max_rows: int | None, policy_max_rows: int | None) -> int | None:
    if requested_max_rows is None:
        return policy_max_rows
    if policy_max_rows is None:
        return requested_max_rows
    return min(requested_max_rows, policy_max_rows)


def authorize_record_recovery_request(
    *,
    policy: dict,
    caller: str,
    tenant_id: str,
    dataset_id: str,
    service_id: str,
    role: str,
    join_key_field: str,
    value_field: str,
    filters: list[tuple[str, str]],
    candidate_count: int,
    requested_min_output_rows: int | None,
    requested_max_output_rows: int | None,
    record_store_path: Path,
    out_path: Path,
) -> tuple[int | None, int | None]:
    if not policy:
        return requested_min_output_rows, requested_max_output_rows

    if policy.get("schema") == PLATFORM_POLICY_SCHEMA:
        caller_policy = platform_policy_for_caller(policy, caller)
        resolve_platform_scope(
            caller_policy=caller_policy,
            caller=caller,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            service_id=service_id,
            require_record_recovery_service=True,
        )
        policy = {"callers": {caller: caller_policy}}

    callers = policy.get("callers")
    if not isinstance(callers, dict):
        raise ValueError("record recovery authz config must contain a callers object")
    caller_policy = callers.get(caller)
    if not isinstance(caller_policy, dict):
        raise PermissionError(f"caller {caller} is not allowed to use record recovery service")
    if caller_policy.get("enabled", True) is False:
        raise PermissionError(f"caller {caller} is disabled for record recovery service")

    allowed_roles = _as_set(caller_policy, "allowed_roles")
    if allowed_roles and role not in allowed_roles:
        raise PermissionError(f"caller {caller} cannot recover role {role}")

    allowed_join_key_fields = _as_set(caller_policy, "allowed_join_key_fields")
    if allowed_join_key_fields and join_key_field not in allowed_join_key_fields:
        raise PermissionError(f"caller {caller} cannot recover join key field {join_key_field}")

    allowed_value_fields = _as_set(caller_policy, "allowed_value_fields")
    if value_field and allowed_value_fields and value_field not in allowed_value_fields:
        raise PermissionError(f"caller {caller} cannot recover value field {value_field}")

    required_filters = _as_set(caller_policy, "required_filters")
    present_filters = {field for field, _ in filters}
    missing_filters = sorted(required_filters - present_filters)
    if missing_filters:
        raise PermissionError(f"caller {caller} must include filters {missing_filters}")

    allowed_filter_fields = _as_set(caller_policy, "allowed_filter_fields")
    if allowed_filter_fields:
        disallowed_filters = sorted(present_filters - allowed_filter_fields)
        if disallowed_filters:
            raise PermissionError(f"caller {caller} cannot filter on fields {disallowed_filters}")

    _ensure_allowed_filter_values(caller_policy, filters, caller)

    max_candidate_count = caller_policy.get("max_candidate_count")
    if max_candidate_count is not None and candidate_count > int(max_candidate_count):
        raise PermissionError(
            f"caller {caller} candidate count {candidate_count} exceeds max_candidate_count {max_candidate_count}"
        )

    policy_min_rows = caller_policy.get("min_output_rows")
    if policy_min_rows is not None and requested_min_output_rows is not None and requested_min_output_rows < int(policy_min_rows):
        raise PermissionError(
            f"caller {caller} requested min_output_rows {requested_min_output_rows} is below policy minimum {policy_min_rows}"
        )

    policy_max_rows = caller_policy.get("max_output_rows")
    if policy_max_rows is not None and requested_max_output_rows is not None and requested_max_output_rows > int(policy_max_rows):
        raise PermissionError(
            f"caller {caller} requested max_output_rows {requested_max_output_rows} exceeds policy max {policy_max_rows}"
        )

    output_prefixes = caller_policy.get("allowed_output_prefixes", [])
    if not isinstance(output_prefixes, list):
        raise ValueError("allowed_output_prefixes must be a list")
    _ensure_prefix(out_path, [str(item) for item in output_prefixes], "output path")

    record_store_prefixes = caller_policy.get("allowed_record_store_prefixes", [])
    if not isinstance(record_store_prefixes, list):
        raise ValueError("allowed_record_store_prefixes must be a list")
    _ensure_prefix(record_store_path, [str(item) for item in record_store_prefixes], "record store path")

    return (
        _effective_min_rows(
            requested_min_rows=requested_min_output_rows,
            policy_min_rows=int(policy_min_rows) if policy_min_rows is not None else None,
        ),
        _effective_max_rows(
            requested_max_rows=requested_max_output_rows,
            policy_max_rows=int(policy_max_rows) if policy_max_rows is not None else None,
        ),
    )


def authz_policy_path(path: str) -> str | None:
    if not path:
        return None
    return str(Path(path).resolve())
