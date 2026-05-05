#!/usr/bin/env python3
import json
import os
from pathlib import Path
from typing import Any

from metadata_db import connect_db, row_to_dict
from map_oidc_claims import DEFAULT_CLAIM_MAP, load_claim_mapping_config, map_token


IDENTITY_TOKEN_SCHEMA = "api_identity_token_map/v1"
PRIVILEGED_PLATFORM_ROLES = {"platform_admin", "platform_auditor"}
QUERY_SUBMITTER_PLATFORM_ROLES = {"platform_admin", "query_submitter"}
QUERY_EXECUTE_PLATFORM_ROLES = {"platform_admin", "privacy_operator"}
PLATFORM_HEALTH_PLATFORM_ROLES = {"platform_admin", "platform_auditor"}
QUERY_REQUIRED_PERMISSION_KEYS = {"can_run_bridge", "can_run_pjc"}


def load_json_object(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def parse_platform_roles(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return sorted({str(item) for item in value if item not in (None, "")})
    if isinstance(value, str):
        parsed = json.loads(value)
        if not isinstance(parsed, list):
            return []
        return sorted({str(item) for item in parsed if item not in (None, "")})
    return []


def parse_metadata_json(value: Any) -> dict[str, Any] | None:
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    return None


def parse_permission_value(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def normalize_string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return sorted({str(item) for item in value if item not in (None, "")})
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return sorted({str(item) for item in parsed if item not in (None, "")})
    return []


def identity_has_any_role(identity: dict[str, Any] | None, *roles: str) -> bool:
    if not identity:
        return False
    current = set(identity.get("platform_roles") or [])
    return any(role in current for role in roles)


def require_identity_roles(identity: dict[str, Any], *roles: str, error_message: str) -> None:
    if not identity_has_any_role(identity, *roles):
        raise PermissionError(error_message)


def load_identity_token_entries(config_path: str) -> list[dict[str, str]]:
    payload = load_json_object(config_path)
    if payload.get("schema") != IDENTITY_TOKEN_SCHEMA:
        raise ValueError(f"identity token config must use {IDENTITY_TOKEN_SCHEMA}")
    tokens = payload.get("tokens")
    if not isinstance(tokens, list):
        raise ValueError("identity token config must contain a tokens array")
    entries: list[dict[str, str]] = []
    for item in tokens:
        if not isinstance(item, dict):
            raise ValueError("identity token config tokens must be objects")
        token_env = str(item.get("token_env") or "")
        issuer = str(item.get("issuer") or "")
        subject = str(item.get("subject") or "")
        if not token_env or not subject:
            raise ValueError("identity token entries require token_env and subject")
        entries.append(
            {
                "token_env": token_env,
                "issuer": issuer,
                "subject": subject,
            }
        )
    return entries


def load_identity_token_config(config_path: str) -> dict[str, Any]:
    payload = load_json_object(config_path)
    if payload.get("schema") != IDENTITY_TOKEN_SCHEMA:
        raise ValueError(f"identity token config must use {IDENTITY_TOKEN_SCHEMA}")
    return payload


def match_identity_token(config_path: str, bearer_token: str) -> dict[str, str] | None:
    for entry in load_identity_token_entries(config_path):
        expected = os.environ.get(entry["token_env"], "")
        if expected and expected == bearer_token:
            return entry
    return None


def resolve_jwt_identity_token(
    *,
    config_path: str,
    db_path: str,
    bearer_token: str,
) -> dict[str, Any] | None:
    payload = load_identity_token_config(config_path)
    jwt_bearer = payload.get("jwt_bearer")
    if not isinstance(jwt_bearer, dict):
        return None

    claim_mapping = dict(DEFAULT_CLAIM_MAP)
    claim_mapping_config = str(jwt_bearer.get("claim_mapping_config") or "").strip()
    if claim_mapping_config:
        cfg = load_claim_mapping_config(claim_mapping_config)
        override = cfg.get("claim_mapping")
        if isinstance(override, dict):
            claim_mapping.update(override)
        if not jwt_bearer.get("jwks_uri"):
            config_jwks_uri = str(cfg.get("jwks_uri") or "").strip()
            if config_jwks_uri:
                jwt_bearer = {**jwt_bearer, "jwks_uri": config_jwks_uri}

    verify_secret = None
    verify_secret_env = str(jwt_bearer.get("verify_secret_env") or "").strip()
    if verify_secret_env:
        verify_secret = os.environ.get(verify_secret_env)

    trusted_audiences = jwt_bearer.get("trusted_audiences")
    if not isinstance(trusted_audiences, list):
        trusted_audiences = None

    result = map_token(
        bearer_token,
        claim_mapping=claim_mapping,
        verify_secret=verify_secret,
        jwks_uri=str(jwt_bearer.get("jwks_uri") or "").strip() or None,
        db_path=db_path,
        require_registered_issuer=bool(jwt_bearer.get("require_registered_issuer")),
        trusted_audiences=[str(item) for item in trusted_audiences] if trusted_audiences else None,
    )
    if not result.get("valid"):
        raise PermissionError("identity bearer token JWT validation failed")

    expected_issuer = str(jwt_bearer.get("issuer") or "").strip()
    resolved_issuer = str(result.get("issuer") or "").strip()
    if expected_issuer and resolved_issuer != expected_issuer:
        raise PermissionError("identity bearer token issuer mismatch")

    mapped_fields = result.get("mapped_fields") if isinstance(result.get("mapped_fields"), dict) else {}
    subject = str((mapped_fields or {}).get("subject") or result.get("subject") or "").strip()
    if not resolved_issuer or not subject:
        raise PermissionError("identity bearer token did not resolve issuer/subject")

    return {
        "issuer": resolved_issuer,
        "subject": subject,
        "jwt_validation": result,
    }


def lookup_issuer_registry_record(conn, issuer: str) -> dict[str, Any] | None:
    """Return issuer_registry row if the table exists and the issuer is registered."""
    try:
        row = conn.execute(
            "SELECT issuer, issuer_type, display_name, enabled FROM issuer_registry WHERE issuer = ?",
            (issuer,),
        ).fetchone()
        return row_to_dict(row)
    except Exception:
        return None


def resolve_identity_record(
    conn,
    *,
    issuer: str,
    subject: str,
) -> dict[str, Any]:
    # Issuer registry check: if the table exists and the issuer is found but disabled, reject.
    # If the issuer is not registered at all, we allow the resolution (backward-compatible with
    # the static local token map that pre-dates the issuer registry).
    issuer_reg = lookup_issuer_registry_record(conn, issuer)
    if issuer_reg is not None and int(issuer_reg.get("enabled") or 0) != 1:
        raise PermissionError(f"issuer '{issuer}' is registered but disabled in issuer_registry")

    row = conn.execute(
        """
        SELECT
          ci.caller,
          c.tenant_id,
          ci.issuer,
          ci.subject,
          ci.subject_type,
          ci.service_id,
          ci.display_name,
          ci.platform_roles_json,
          ci.enabled,
          ci.metadata_json,
          ci.source,
          ci.created_at_utc
        FROM caller_identities ci
        JOIN callers c ON c.caller = ci.caller
        WHERE ci.issuer = ? AND ci.subject = ?
        ORDER BY ci.id DESC
        LIMIT 1
        """,
        (issuer, subject),
    ).fetchone()
    payload = row_to_dict(row)
    if payload is None:
        raise PermissionError("identity mapping not found in metadata DB")
    if int(payload.get("enabled") or 0) != 1:
        raise PermissionError("identity mapping is disabled")
    permission_summary = load_permission_summary(conn, caller=str(payload["caller"]))
    return {
        "caller": str(payload["caller"]),
        "tenant_id": str(payload["tenant_id"]) if payload.get("tenant_id") not in (None, "") else None,
        "issuer": str(payload["issuer"]) if payload.get("issuer") not in (None, "") else None,
        "subject": str(payload["subject"]),
        "subject_type": str(payload["subject_type"]),
        "service_id": str(payload["service_id"]) if payload.get("service_id") not in (None, "") else None,
        "display_name": str(payload["display_name"]) if payload.get("display_name") not in (None, "") else None,
        "platform_roles": parse_platform_roles(payload.get("platform_roles_json")),
        "permission_summary": permission_summary,
        "metadata": parse_metadata_json(payload.get("metadata_json")),
        "source": str(payload["source"]) if payload.get("source") not in (None, "") else None,
        "created_at_utc": str(payload["created_at_utc"]),
        "issuer_registered": issuer_reg is not None,
        "issuer_type": str(issuer_reg.get("issuer_type") or "") if issuer_reg else None,
    }


def resolve_identity_subject_context(
    *,
    db_path: str,
    issuer: str,
    subject: str,
) -> dict[str, Any]:
    with connect_db(db_path) as conn:
        return resolve_identity_record(conn, issuer=issuer, subject=subject)


def load_permission_summary(conn, *, caller: str) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT permission_key, permission_value
        FROM caller_permissions
        WHERE caller = ?
        ORDER BY permission_key ASC
        """,
        (caller,),
    ).fetchall()
    values: dict[str, Any] = {}
    for row in rows:
        permission_key = str(row["permission_key"] or "")
        if not permission_key:
            continue
        values[permission_key] = parse_permission_value(row["permission_value"])
    return {
        "caller": caller,
        "enabled": values.get("enabled"),
        "tenant_id": str(values.get("tenant_id") or "") or None,
        "access_profile": str(values.get("access_profile") or "") or None,
        "platform_roles": normalize_string_list(values.get("platform_roles")),
        "allowed_dataset_ids": normalize_string_list(values.get("allowed_dataset_ids")),
        "allowed_service_ids": normalize_string_list(values.get("allowed_service_ids")),
        "permissions": {
            "can_run_bridge": values.get("can_run_bridge"),
            "can_run_pjc": values.get("can_run_pjc"),
            "can_release": values.get("can_release"),
            "can_use_record_recovery_service": values.get("can_use_record_recovery_service"),
        },
    }


def resolve_identity_context(
    *,
    db_path: str,
    identity_token_config: str,
    bearer_token: str,
) -> dict[str, Any]:
    matched = match_identity_token(identity_token_config, bearer_token)
    if matched is not None:
        return resolve_identity_subject_context(
            db_path=db_path,
            issuer=str(matched["issuer"]),
            subject=str(matched["subject"]),
        )

    jwt_identity = resolve_jwt_identity_token(
        config_path=identity_token_config,
        db_path=db_path,
        bearer_token=bearer_token,
    )
    if jwt_identity is None:
        raise PermissionError("identity bearer token auth failed")
    return resolve_identity_subject_context(
        db_path=db_path,
        issuer=str(jwt_identity["issuer"]),
        subject=str(jwt_identity["subject"]),
    )


def resolve_request_identity(
    *,
    auth_header: str,
    expected_bearer_token: str,
    db_path: str,
    identity_token_config: str,
    auth_failure_label: str,
) -> dict[str, Any] | None:
    if expected_bearer_token:
        if not auth_header.startswith("Bearer "):
            raise PermissionError("missing bearer token")
        provided = auth_header[len("Bearer "):]
        if provided == expected_bearer_token:
            return None
    if identity_token_config:
        if not auth_header.startswith("Bearer "):
            raise PermissionError("missing bearer token")
        provided = auth_header[len("Bearer "):]
        return resolve_identity_context(
            db_path=db_path,
            identity_token_config=identity_token_config,
            bearer_token=provided,
        )
    if expected_bearer_token:
        raise PermissionError(f"{auth_failure_label} auth failed")
    return None


def build_identity_access_summary(identity: dict[str, Any]) -> dict[str, Any]:
    summary = identity.get("permission_summary") or {}
    return {
        "metadata_privileged": identity_has_any_role(identity, *PRIVILEGED_PLATFORM_ROLES),
        "query_submit_allowed": identity_has_any_role(identity, *QUERY_SUBMITTER_PLATFORM_ROLES),
        "query_execute_allowed": identity_has_any_role(identity, *QUERY_EXECUTE_PLATFORM_ROLES),
        "platform_health_privileged": identity_has_any_role(identity, *PLATFORM_HEALTH_PLATFORM_ROLES),
        "service_operator": identity_has_any_role(identity, "service_operator"),
        "scopes": {
            "caller": identity.get("caller"),
            "tenant_id": identity.get("tenant_id"),
            "service_id": identity.get("service_id"),
            "allowed_dataset_ids": summary.get("allowed_dataset_ids") or [],
            "allowed_service_ids": summary.get("allowed_service_ids") or [],
        },
        "permissions": summary.get("permissions") or {},
    }


def build_identity_resolution_payload(
    identity: dict[str, Any],
    *,
    resolution_mode: str,
) -> dict[str, Any]:
    return {
        "schema": "api_identity_resolution/v1",
        "resolution_mode": resolution_mode,
        "identity": identity,
        "access_summary": build_identity_access_summary(identity),
    }


def metadata_scope_filters(
    identity: dict[str, Any],
    *,
    entity: str | None = None,
    caller: str = "",
    tenant_id: str = "",
) -> dict[str, str]:
    if identity_has_any_role(identity, *PRIVILEGED_PLATFORM_ROLES):
        return {
            "caller": caller,
            "tenant_id": tenant_id,
        }
    scoped_caller = caller or ""
    scoped_tenant_id = tenant_id or ""
    if entity in {"callers", "caller-identities", "caller-permissions", "policy-bindings"}:
        if scoped_caller and scoped_caller != identity["caller"]:
            raise PermissionError("caller-scoped metadata access denied")
        scoped_caller = identity["caller"]
    elif entity in {"policies", "key-refs", "key-versions"}:
        raise PermissionError("requested metadata requires privileged platform role")
    else:
        identity_tenant = str(identity.get("tenant_id") or "")
        if scoped_tenant_id and identity_tenant and scoped_tenant_id != identity_tenant:
            raise PermissionError("tenant-scoped metadata access denied")
        scoped_tenant_id = identity_tenant or scoped_tenant_id
        if not scoped_caller:
            scoped_caller = identity["caller"]
    return {
        "caller": scoped_caller,
        "tenant_id": scoped_tenant_id,
    }


def enforce_identity_scope(
    identity: dict[str, Any],
    *,
    caller: str = "",
    tenant_id: str = "",
    access_label: str = "resource",
) -> dict[str, str]:
    if identity_has_any_role(identity, *PRIVILEGED_PLATFORM_ROLES):
        return {
            "caller": caller,
            "tenant_id": tenant_id,
        }
    scoped_caller = caller or ""
    scoped_tenant_id = tenant_id or ""
    if not scoped_caller and not scoped_tenant_id:
        raise PermissionError(f"{access_label} scope is missing caller/tenant binding")
    if scoped_caller and scoped_caller != identity["caller"]:
        raise PermissionError(f"{access_label} caller does not match authenticated identity")
    identity_tenant = str(identity.get("tenant_id") or "")
    if scoped_tenant_id and identity_tenant and scoped_tenant_id != identity_tenant:
        raise PermissionError(f"{access_label} tenant_id does not match authenticated identity")
    return {
        "caller": scoped_caller or identity["caller"],
        "tenant_id": scoped_tenant_id or identity_tenant,
    }


def enforce_audit_result_access(
    identity: dict[str, Any],
    *,
    caller: str,
    tenant_id: str,
    include_paths: bool,
) -> dict[str, str]:
    scoped = enforce_identity_scope(
        identity,
        caller=caller,
        tenant_id=tenant_id,
        access_label="audit artifact",
    )
    if include_paths and not identity_has_any_role(identity, *PRIVILEGED_PLATFORM_ROLES):
        raise PermissionError("audit include_paths requires platform_admin or platform_auditor role")
    return scoped


def _require_identity_permission(identity: dict[str, Any], permission_key: str) -> None:
    summary = identity.get("permission_summary") or {}
    permissions = summary.get("permissions") or {}
    if permissions.get(permission_key) is not True:
        raise PermissionError(f"query workflow submission requires {permission_key}=true for caller {identity['caller']}")


def _bind_allowed_scope_value(
    *,
    caller: str,
    requested_value: Any,
    allowed_values: list[str],
    field_name: str,
    require_when_ambiguous: bool,
) -> str:
    requested = str(requested_value or "").strip()
    if requested:
        if allowed_values and requested not in set(allowed_values):
            raise PermissionError(f"caller {caller} cannot use {field_name} {requested}")
        return requested
    if len(allowed_values) == 1:
        return allowed_values[0]
    if require_when_ambiguous and len(allowed_values) > 1:
        raise PermissionError(f"caller {caller} must specify {field_name}")
    return requested


def query_uses_record_recovery(payload: dict[str, Any]) -> bool:
    return any(
        str(payload.get(field) or "").strip()
        for field in (
            "record_recovery_socket",
            "record_recovery_endpoint_url",
            "record_recovery_service_config",
            "record_recovery_authz_config",
            "record_recovery_service_id",
        )
    ) or str(payload.get("record_recovery_service_mode") or "").strip() in {"manual", "subprocess"}


def bind_query_request_to_identity(
    identity: dict[str, Any],
    payload: dict[str, Any],
    *,
    execute: bool = False,
) -> dict[str, Any]:
    require_identity_roles(
        identity,
        *QUERY_SUBMITTER_PLATFORM_ROLES,
        error_message="query workflow submission requires query_submitter or platform_admin role",
    )
    if execute:
        require_identity_roles(
            identity,
            *QUERY_EXECUTE_PLATFORM_ROLES,
            error_message="query workflow execute requires privacy_operator or platform_admin role",
        )
    bound = dict(payload)
    caller = bound.get("caller")
    if caller not in (None, "", identity["caller"]):
        raise PermissionError("query caller does not match authenticated identity")
    bound["caller"] = identity["caller"]
    tenant_id = bound.get("tenant_id")
    identity_tenant = identity.get("tenant_id")
    if identity_tenant:
        if tenant_id not in (None, "", identity_tenant):
            raise PermissionError("query tenant_id does not match authenticated identity")
        bound["tenant_id"] = identity_tenant
    if not identity_has_any_role(identity, *PRIVILEGED_PLATFORM_ROLES):
        summary = identity.get("permission_summary") or {}
        if summary.get("enabled") is False:
            raise PermissionError(f"caller {identity['caller']} is disabled for query workflow submission")
        for permission_key in sorted(QUERY_REQUIRED_PERMISSION_KEYS):
            _require_identity_permission(identity, permission_key)
        bound["dataset_id"] = _bind_allowed_scope_value(
            caller=identity["caller"],
            requested_value=bound.get("dataset_id"),
            allowed_values=summary.get("allowed_dataset_ids") or [],
            field_name="dataset_id",
            require_when_ambiguous=True,
        )
        uses_record_recovery = query_uses_record_recovery(bound)
        if uses_record_recovery:
            _require_identity_permission(identity, "can_use_record_recovery_service")
        record_recovery_service_id = _bind_allowed_scope_value(
            caller=identity["caller"],
            requested_value=bound.get("record_recovery_service_id"),
            allowed_values=summary.get("allowed_service_ids") or [],
            field_name="record_recovery_service_id",
            require_when_ambiguous=uses_record_recovery,
        )
        if record_recovery_service_id:
            bound["record_recovery_service_id"] = record_recovery_service_id
    return bound
