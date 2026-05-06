#!/usr/bin/env python3
import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import (  # noqa: E402
    apply_migrations,
    connect_db,
    database_backend,
    database_version,
    expected_migration_versions,
    row_to_dict,
    sha256_file,
    table_exists,
    utc_now,
)
from scripts.metadata_registry import (  # noqa: E402
    MANIFEST_SCHEMA,
    apply_policy_plan,
    load_json,
    plan_policy_file,
)
from scripts.query_metadata import query_entities, query_jobs  # noqa: E402


STATUS_SCHEMA = "metadata_db_status/v1"
BACKUP_SCHEMA = "metadata_db_backup/v1"
RESTORE_SCHEMA = "metadata_db_restore/v1"
EXPORT_SCHEMA = "metadata_db_export/v1"
REGISTRY_APPLY_SCHEMA = "metadata_registry_apply_report/v1"

CORE_TABLES = (
    "schema_migrations",
    "tenants",
    "datasets",
    "services",
    "callers",
    "caller_identities",
    "key_refs",
    "key_versions",
    "jobs",
    "job_artifacts",
    "job_stage_status",
    "audit_events",
    "audit_chains",
    "audit_seals",
    "policies",
    "policy_bindings",
    "caller_permissions",
    "key_access_events",
    "control_plane_mutations",
    "issuer_registry",
)

MANAGED_ENTITY_SPECS = {
    "tenants": {
        "table": "tenants",
        "key": "tenant_id",
        "fields": ("source",),
    },
    "datasets": {
        "table": "datasets",
        "key": "dataset_id",
        "fields": ("tenant_id", "source"),
    },
    "services": {
        "table": "services",
        "key": "service_id",
        "fields": ("tenant_id", "dataset_id", "service_type", "transport", "config_path"),
    },
    "callers": {
        "table": "callers",
        "key": "caller",
        "fields": ("tenant_id", "source"),
    },
}

PLATFORM_ROLE_NAMES = (
    "platform_admin",
    "platform_auditor",
    "privacy_operator",
    "query_submitter",
    "service_operator",
)


def sqlite_scalar(conn: Any, query: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(query, params).fetchone()
    if row is None:
        return None
    return row[0]


def load_status_summary(conn: Any) -> dict[str, Any]:
    table_counts: dict[str, int] = {}
    for table_name in CORE_TABLES:
        if not table_exists(conn, table_name):
            table_counts[table_name] = 0
            continue
        count = sqlite_scalar(conn, f"SELECT COUNT(*) FROM {table_name}")
        table_counts[table_name] = int(count or 0)

    return {
        "tenant_count": table_counts["tenants"],
        "dataset_count": table_counts["datasets"],
        "service_count": table_counts["services"],
        "caller_count": table_counts["callers"],
        "job_count": table_counts["jobs"],
        "artifact_count": table_counts["job_artifacts"],
        "stage_status_count": table_counts["job_stage_status"],
        "audit_event_count": table_counts["audit_events"],
        "audit_chain_count": table_counts["audit_chains"],
        "audit_seal_count": table_counts["audit_seals"],
        "policy_count": table_counts["policies"],
        "policy_binding_count": table_counts["policy_bindings"],
        "caller_permission_count": table_counts["caller_permissions"],
        "key_access_event_count": table_counts["key_access_events"],
        "issuer_registry_count": table_counts.get("issuer_registry", 0),
        "mutation_count": table_counts.get("control_plane_mutations", 0),
        "latest_job_id": sqlite_scalar(
            conn,
            "SELECT job_id FROM jobs ORDER BY imported_at_utc DESC, job_id DESC LIMIT 1",
        ),
        "latest_imported_at_utc": sqlite_scalar(
            conn,
            "SELECT imported_at_utc FROM jobs ORDER BY imported_at_utc DESC, job_id DESC LIMIT 1",
        ),
        "latest_job_created_at_utc": sqlite_scalar(
            conn,
            "SELECT created_at_utc FROM jobs WHERE created_at_utc IS NOT NULL ORDER BY created_at_utc DESC, job_id DESC LIMIT 1",
        ),
        "latest_policy_imported_at_utc": sqlite_scalar(
            conn,
            "SELECT imported_at_utc FROM policies ORDER BY imported_at_utc DESC, policy_id DESC LIMIT 1",
        ),
        "table_counts": table_counts,
    }


def applied_migrations(conn: Any) -> list[str]:
    if not table_exists(conn, "schema_migrations"):
        return []
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    ]


def build_status_report(*, db_path: str = "", db_dsn: str = "") -> dict[str, Any]:
    path = Path(db_path).resolve() if db_path else None
    if path is not None and not path.is_file():
        raise SystemExit(f"[ERROR] metadata DB does not exist: {path}")
    conn = connect_db(str(path) if path else "", dsn=db_dsn)
    try:
        backend = database_backend(conn)
        db_version = database_version(conn)
        applied = applied_migrations(conn)
        expected = expected_migration_versions()
        pending = [version for version in expected if version not in applied]
        summary = load_status_summary(conn)
    finally:
        conn.close()

    warnings: list[str] = []
    if pending:
        warnings.append("pending_migrations")
    if summary["job_count"] == 0:
        warnings.append("no_jobs_imported")

    return {
        "schema": STATUS_SCHEMA,
        "generated_at_utc": utc_now(),
        "db_path": str(path) if path else None,
        "db_dsn": db_dsn or None,
        "status": "warn" if warnings else "ok",
        "backend": backend,
        "sqlite_version": str(db_version or ""),
        "size_bytes": path.stat().st_size if path else None,
        "sha256": sha256_file(path) if path else None,
        "applied_migrations": applied,
        "expected_migrations": expected,
        "pending_migrations": pending,
        "summary": summary,
        "warnings": warnings,
    }


def write_json(path_value: str, payload: dict[str, Any]) -> str:
    path = Path(path_value)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def ensure_output_path(out_path: str, *, overwrite: bool) -> Path:
    path = Path(out_path)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    if path.exists() and not overwrite:
        raise SystemExit(f"[ERROR] output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def normalize_optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def normalize_platform_roles(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    roles = sorted({str(item) for item in value if item in PLATFORM_ROLE_NAMES})
    return roles


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if item not in (None, "")})


def load_registry_manifest(manifest_path: str) -> tuple[Path, dict[str, Any]]:
    path = Path(manifest_path).resolve()
    if not path.is_file():
        raise SystemExit(f"[ERROR] registry manifest does not exist: {path}")
    payload = load_json(path)
    if payload.get("schema") != MANIFEST_SCHEMA:
        raise SystemExit(f"[ERROR] registry manifest must use {MANIFEST_SCHEMA}: {path}")
    return path, payload


def normalize_manifest_entity(
    entity_name: str,
    entry: Any,
    *,
    manifest_dir: Path,
) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise SystemExit(f"[ERROR] manifest {entity_name} entries must be objects")
    if entity_name == "tenants":
        tenant_id = normalize_optional_text(entry.get("tenant_id"))
        if not tenant_id:
            raise SystemExit("[ERROR] tenant manifest entries require tenant_id")
        return {
            "tenant_id": tenant_id,
            "source": normalize_optional_text(entry.get("source")) or "registry_manifest",
        }
    if entity_name == "datasets":
        dataset_id = normalize_optional_text(entry.get("dataset_id"))
        tenant_id = normalize_optional_text(entry.get("tenant_id"))
        if not dataset_id or not tenant_id:
            raise SystemExit("[ERROR] dataset manifest entries require dataset_id and tenant_id")
        return {
            "dataset_id": dataset_id,
            "tenant_id": tenant_id,
            "source": normalize_optional_text(entry.get("source")) or "registry_manifest",
        }
    if entity_name == "services":
        service_id = normalize_optional_text(entry.get("service_id"))
        tenant_id = normalize_optional_text(entry.get("tenant_id"))
        dataset_id = normalize_optional_text(entry.get("dataset_id"))
        if not service_id or not tenant_id or not dataset_id:
            raise SystemExit("[ERROR] service manifest entries require service_id, tenant_id, and dataset_id")
        config_path = normalize_optional_text(entry.get("config_path"))
        if config_path:
            candidate = Path(config_path)
            if not candidate.is_absolute():
                config_path = str((manifest_dir / candidate).resolve())
            else:
                config_path = str(candidate.resolve())
        return {
            "service_id": service_id,
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "service_type": normalize_optional_text(entry.get("service_type")) or "record_recovery",
            "transport": normalize_optional_text(entry.get("transport")),
            "config_path": config_path,
        }
    caller = normalize_optional_text(entry.get("caller"))
    tenant_id = normalize_optional_text(entry.get("tenant_id"))
    if not caller or not tenant_id:
        raise SystemExit("[ERROR] caller manifest entries require caller and tenant_id")
    return {
        "caller": caller,
        "tenant_id": tenant_id,
        "source": normalize_optional_text(entry.get("source")) or "registry_manifest",
    }


def normalize_manifest_caller_identity(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise SystemExit("[ERROR] manifest caller_identities entries must be objects")
    caller = normalize_optional_text(entry.get("caller"))
    subject = normalize_optional_text(entry.get("subject"))
    subject_type = normalize_optional_text(entry.get("subject_type"))
    if not caller or not subject or not subject_type:
        raise SystemExit("[ERROR] caller identity entries require caller, subject, and subject_type")
    if subject_type not in ("human_user", "service_account", "local_operator"):
        raise SystemExit(
            f"[ERROR] caller identity subject_type must be human_user, service_account, or local_operator: {subject_type}"
        )
    metadata = entry.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise SystemExit("[ERROR] caller identity metadata must be an object when provided")
    return {
        "caller": caller,
        "issuer": normalize_optional_text(entry.get("issuer")) or "",
        "subject": subject,
        "subject_type": subject_type,
        "service_id": normalize_optional_text(entry.get("service_id")),
        "display_name": normalize_optional_text(entry.get("display_name")),
        "platform_roles_json": json.dumps(normalize_platform_roles(entry.get("platform_roles")), ensure_ascii=False),
        "enabled": 1 if entry.get("enabled", True) else 0,
        "metadata_json": json.dumps(metadata, ensure_ascii=False) if metadata is not None else None,
        "source": normalize_optional_text(entry.get("source")) or "registry_manifest",
    }


def normalize_manifest_key_ref(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise SystemExit("[ERROR] manifest key_refs entries must be objects")
    key_name = normalize_optional_text(entry.get("key_name"))
    purpose = normalize_optional_text(entry.get("purpose"))
    backend_kind = normalize_optional_text(entry.get("backend_kind"))
    active_version = normalize_optional_text(entry.get("active_version"))
    versions = entry.get("versions")
    if not key_name or not purpose or not backend_kind or not active_version:
        raise SystemExit(
            "[ERROR] key_refs entries require key_name, purpose, backend_kind, and active_version"
        )
    if not isinstance(versions, list) or not versions:
        raise SystemExit("[ERROR] key_refs entries require a non-empty versions array")
    desired_versions: list[dict[str, Any]] = []
    seen_versions: set[str] = set()
    active_version_match_count = 0
    for item in versions:
        if not isinstance(item, dict):
            raise SystemExit("[ERROR] key_refs.versions entries must be objects")
        version = normalize_optional_text(item.get("version"))
        if not version:
            raise SystemExit("[ERROR] key_refs.versions entries require version")
        if version in seen_versions:
            raise SystemExit(f"[ERROR] duplicate key version {version} in key_ref {key_name}")
        seen_versions.add(version)
        status = normalize_optional_text(item.get("status"))
        if status not in ("active", "inactive", "retired"):
            raise SystemExit(
                f"[ERROR] key_refs.versions status must be active, inactive, or retired: {status}"
            )
        enabled = item.get("enabled")
        if not isinstance(enabled, bool):
            raise SystemExit("[ERROR] key_refs.versions enabled must be a boolean")
        secret_ref_kind = normalize_optional_text(item.get("secret_ref_kind"))
        secret_ref_name = normalize_optional_text(item.get("secret_ref_name"))
        if bool(secret_ref_kind) != bool(secret_ref_name):
            raise SystemExit(
                "[ERROR] key_refs.versions secret_ref_kind and secret_ref_name must be provided together"
            )
        metadata = item.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise SystemExit("[ERROR] key_refs.versions metadata must be an object when provided")
        if version == active_version:
            active_version_match_count += 1
            if status != "active" or enabled is not True:
                raise SystemExit(
                    f"[ERROR] key_ref {key_name} active_version {active_version} must be enabled and active"
                )
        desired_versions.append(
            {
                "key_name": key_name,
                "version": version,
                "enabled": 1 if enabled else 0,
                "status": status,
                "secret_ref_kind": secret_ref_kind,
                "secret_ref_name": secret_ref_name,
                "backend_key_version": normalize_optional_text(item.get("backend_key_version")),
                "created_at_utc": normalize_optional_text(item.get("created_at_utc")),
                "source": normalize_optional_text(item.get("source")) or normalize_optional_text(entry.get("source")) or "registry_manifest",
                "metadata_json": json.dumps(metadata, ensure_ascii=False) if metadata is not None else None,
            }
        )
    if active_version_match_count != 1:
        raise SystemExit(
            f"[ERROR] key_ref {key_name} active_version must match exactly one versions entry"
        )
    active_rows = [item for item in desired_versions if item["status"] == "active"]
    if len(active_rows) != 1 or str(active_rows[0]["version"]) != active_version:
        raise SystemExit(
            f"[ERROR] key_ref {key_name} must have exactly one active version matching active_version"
        )
    return {
        "key_name": key_name,
        "purpose": purpose,
        "service_id": normalize_optional_text(entry.get("service_id")),
        "backend_kind": backend_kind,
        "backend_ref": normalize_optional_text(entry.get("backend_ref")),
        "active_version": active_version,
        "allowed_callers_json": json.dumps(
            normalize_string_list(entry.get("allowed_callers")),
            ensure_ascii=False,
        ),
        "source": normalize_optional_text(entry.get("source")) or "registry_manifest",
        "versions": desired_versions,
    }


VALID_ISSUER_TYPES = ("keycloak", "vault", "service_account", "local", "external")


def normalize_manifest_issuer_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise SystemExit("[ERROR] manifest issuer_registry entries must be objects")
    issuer = normalize_optional_text(entry.get("issuer"))
    issuer_type = normalize_optional_text(entry.get("issuer_type"))
    if not issuer:
        raise SystemExit("[ERROR] issuer_registry entries require issuer")
    if issuer_type not in VALID_ISSUER_TYPES:
        raise SystemExit(
            f"[ERROR] issuer_type must be one of {VALID_ISSUER_TYPES}: {issuer_type!r}"
        )
    claim_mapping = entry.get("claim_mapping")
    if claim_mapping is not None and not isinstance(claim_mapping, dict):
        raise SystemExit("[ERROR] issuer_registry claim_mapping must be an object when provided")
    trusted_audiences = entry.get("trusted_audiences")
    if trusted_audiences is not None and not isinstance(trusted_audiences, list):
        raise SystemExit("[ERROR] issuer_registry trusted_audiences must be an array when provided")
    return {
        "issuer": issuer,
        "issuer_type": issuer_type,
        "display_name": normalize_optional_text(entry.get("display_name")),
        "service_id": normalize_optional_text(entry.get("service_id")),
        "jwks_uri": normalize_optional_text(entry.get("jwks_uri")),
        "token_endpoint": normalize_optional_text(entry.get("token_endpoint")),
        "claim_mapping_json": json.dumps(claim_mapping, ensure_ascii=False) if claim_mapping is not None else None,
        "trusted_audiences_json": json.dumps(trusted_audiences, ensure_ascii=False) if trusted_audiences is not None else None,
        "enabled": 1 if entry.get("enabled", True) else 0,
        "source": normalize_optional_text(entry.get("source")) or "registry_manifest",
    }


def fetch_existing_issuer_state(
    conn: sqlite3.Connection,
    *,
    issuer: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM issuer_registry WHERE issuer = ?", (issuer,)
    ).fetchone()
    return row_to_dict(row)


def plan_issuer_entry(
    conn: sqlite3.Connection,
    *,
    desired: dict[str, Any],
) -> dict[str, Any]:
    existing = fetch_existing_issuer_state(conn, issuer=str(desired["issuer"]))
    action = "insert"
    if existing is not None:
        action = "noop"
        for field_name in (
            "issuer_type", "display_name", "service_id", "jwks_uri", "token_endpoint",
            "claim_mapping_json", "trusted_audiences_json", "enabled", "source",
        ):
            if existing.get(field_name) != desired.get(field_name):
                action = "update"
                break
    return {
        "entity": "issuer_registry",
        "key_name": "issuer",
        "key_value": str(desired["issuer"]),
        "action": action,
        "existing": existing,
        "desired": desired,
    }


def apply_issuer_entry(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    *,
    imported_at: str,
) -> dict[str, Any]:
    desired = dict(plan["desired"])
    if plan["action"] != "noop":
        conn.execute(
            """
            INSERT INTO issuer_registry(
              issuer, issuer_type, display_name, service_id, jwks_uri, token_endpoint,
              claim_mapping_json, trusted_audiences_json, enabled, source,
              created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(issuer) DO UPDATE SET
              issuer_type=excluded.issuer_type,
              display_name=excluded.display_name,
              service_id=excluded.service_id,
              jwks_uri=excluded.jwks_uri,
              token_endpoint=excluded.token_endpoint,
              claim_mapping_json=excluded.claim_mapping_json,
              trusted_audiences_json=excluded.trusted_audiences_json,
              enabled=excluded.enabled,
              source=excluded.source,
              updated_at_utc=excluded.updated_at_utc
            """,
            (
                desired["issuer"],
                desired["issuer_type"],
                desired["display_name"],
                desired.get("service_id"),
                desired["jwks_uri"],
                desired["token_endpoint"],
                desired["claim_mapping_json"],
                desired["trusted_audiences_json"],
                desired["enabled"],
                desired["source"],
                imported_at,
                imported_at,
            ),
        )
    state_after = fetch_existing_issuer_state(conn, issuer=str(desired["issuer"]))
    return {
        "entity": "issuer_registry",
        "key_name": "issuer",
        "key_value": str(plan["key_value"]),
        "action": str(plan["action"]),
        "existing": plan["existing"],
        "desired": desired,
        "state_after": state_after,
    }


def normalize_manifest_policy_entry(entry: Any, *, manifest_dir: Path) -> dict[str, Any]:
    if isinstance(entry, str):
        entry = {"path": entry}
    if not isinstance(entry, dict):
        raise SystemExit("[ERROR] manifest policies entries must be strings or objects")
    path_value = normalize_optional_text(entry.get("path"))
    if not path_value:
        raise SystemExit("[ERROR] policy manifest entries require path")
    path = Path(path_value)
    if not path.is_absolute():
        path = (manifest_dir / path).resolve()
    else:
        path = path.resolve()
    return {
        "path": str(path),
        "required_schema": normalize_optional_text(entry.get("required_schema")) or "sse_export_policy/v1",
    }


def fetch_existing_entity_state(
    conn: sqlite3.Connection,
    *,
    entity_name: str,
    key_value: str,
) -> dict[str, Any] | None:
    spec = MANAGED_ENTITY_SPECS[entity_name]
    row = conn.execute(
        f"SELECT * FROM {spec['table']} WHERE {spec['key']} = ?",
        (key_value,),
    ).fetchone()
    return row_to_dict(row)


def plan_managed_entity(
    conn: sqlite3.Connection,
    *,
    entity_name: str,
    desired: dict[str, Any],
) -> dict[str, Any]:
    spec = MANAGED_ENTITY_SPECS[entity_name]
    key_name = str(spec["key"])
    key_value = str(desired[key_name])
    existing = fetch_existing_entity_state(conn, entity_name=entity_name, key_value=key_value)
    action = "insert"
    if existing is not None:
        action = "noop"
        for field_name in spec["fields"]:
            if existing.get(field_name) != desired.get(field_name):
                action = "update"
                break
    return {
        "entity": entity_name,
        "key_name": key_name,
        "key_value": key_value,
        "action": action,
        "existing": existing,
        "desired": desired,
    }


def apply_managed_entity(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    *,
    imported_at: str,
) -> dict[str, Any]:
    entity_name = str(plan["entity"])
    action = str(plan["action"])
    desired = dict(plan["desired"])
    if action != "noop":
        if entity_name == "tenants":
            conn.execute(
                """
                INSERT INTO tenants(tenant_id, created_at_utc, source, last_seen_job_id)
                VALUES(?, ?, ?, NULL)
                ON CONFLICT(tenant_id) DO UPDATE SET
                  source=excluded.source
                """,
                (desired["tenant_id"], imported_at, desired["source"]),
            )
        elif entity_name == "datasets":
            conn.execute(
                """
                INSERT INTO datasets(dataset_id, tenant_id, created_at_utc, source, last_seen_job_id)
                VALUES(?, ?, ?, ?, NULL)
                ON CONFLICT(dataset_id) DO UPDATE SET
                  tenant_id=excluded.tenant_id,
                  source=excluded.source
                """,
                (desired["dataset_id"], desired["tenant_id"], imported_at, desired["source"]),
            )
        elif entity_name == "services":
            conn.execute(
                """
                INSERT INTO services(
                  service_id, tenant_id, dataset_id, service_type, transport, config_path, created_at_utc, last_seen_job_id
                ) VALUES(?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(service_id) DO UPDATE SET
                  tenant_id=excluded.tenant_id,
                  dataset_id=excluded.dataset_id,
                  service_type=excluded.service_type,
                  transport=excluded.transport,
                  config_path=excluded.config_path
                """,
                (
                    desired["service_id"],
                    desired["tenant_id"],
                    desired["dataset_id"],
                    desired["service_type"],
                    desired["transport"],
                    desired["config_path"],
                    imported_at,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO callers(caller, tenant_id, created_at_utc, source, last_seen_job_id)
                VALUES(?, ?, ?, ?, NULL)
                ON CONFLICT(caller) DO UPDATE SET
                  tenant_id=excluded.tenant_id,
                  source=excluded.source
                """,
                (desired["caller"], desired["tenant_id"], imported_at, desired["source"]),
            )
    state_after = fetch_existing_entity_state(
        conn,
        entity_name=entity_name,
        key_value=str(plan["key_value"]),
    )
    return {
        "entity": entity_name,
        "key_name": str(plan["key_name"]),
        "key_value": str(plan["key_value"]),
        "action": action,
        "existing": plan["existing"],
        "desired": desired,
        "state_after": state_after,
    }


def validate_unique_keys(items: list[dict[str, Any]], *, entity_name: str, key_name: str) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in items:
        value = str(item[key_name])
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    if duplicates:
        raise SystemExit(f"[ERROR] duplicate {entity_name} values in manifest are not allowed: {', '.join(sorted(duplicates))}")


def validate_unique_caller_identity_keys(items: list[dict[str, Any]]) -> None:
    seen: set[tuple[str, str, str]] = set()
    duplicates: list[str] = []
    for item in items:
        key = (str(item["caller"]), str(item["issuer"]), str(item["subject"]))
        if key in seen:
            rendered = "|".join(key)
            if rendered not in duplicates:
                duplicates.append(rendered)
        seen.add(key)
    if duplicates:
        raise SystemExit(
            f"[ERROR] duplicate caller identity entries in manifest are not allowed: {', '.join(sorted(duplicates))}"
        )


def validate_unique_key_ref_keys(items: list[dict[str, Any]]) -> None:
    validate_unique_keys(items, entity_name="key_name", key_name="key_name")


def load_existing_ids(conn: sqlite3.Connection, table: str, column: str) -> set[str]:
    return {str(row[0]) for row in conn.execute(f"SELECT {column} FROM {table}").fetchall() if row[0] not in (None, "")}


def validate_manifest_references(
    conn: sqlite3.Connection,
    *,
    tenants: list[dict[str, Any]],
    datasets: list[dict[str, Any]],
    services: list[dict[str, Any]],
    callers: list[dict[str, Any]],
    caller_identities: list[dict[str, Any]],
    key_refs: list[dict[str, Any]],
    policy_plans: list[dict[str, Any]],
) -> dict[str, int]:
    known_tenants = load_existing_ids(conn, "tenants", "tenant_id") | {item["tenant_id"] for item in tenants}
    known_datasets = load_existing_ids(conn, "datasets", "dataset_id") | {item["dataset_id"] for item in datasets}
    known_services = load_existing_ids(conn, "services", "service_id") | {item["service_id"] for item in services}
    known_callers = load_existing_ids(conn, "callers", "caller") | {item["caller"] for item in callers}

    checked_reference_count = 0
    for item in datasets:
        checked_reference_count += 1
        if item["tenant_id"] not in known_tenants:
            raise SystemExit(f"[ERROR] dataset {item['dataset_id']} references unknown tenant_id {item['tenant_id']}")
    for item in callers:
        checked_reference_count += 1
        if item["tenant_id"] not in known_tenants:
            raise SystemExit(f"[ERROR] caller {item['caller']} references unknown tenant_id {item['tenant_id']}")
    for item in caller_identities:
        checked_reference_count += 1
        if item["caller"] not in known_callers:
            raise SystemExit(f"[ERROR] caller identity {item['subject']} references unknown caller {item['caller']}")
        service_id = item.get("service_id")
        if service_id:
            checked_reference_count += 1
            if service_id not in known_services:
                raise SystemExit(
                    f"[ERROR] caller identity {item['subject']} references unknown service_id {service_id}"
                )
    for item in key_refs:
        service_id = item.get("service_id")
        if service_id:
            checked_reference_count += 1
            if service_id not in known_services:
                raise SystemExit(
                    f"[ERROR] key_ref {item['key_name']} references unknown service_id {service_id}"
                )
        for caller_name in json.loads(item["allowed_callers_json"]):
            checked_reference_count += 1
            if caller_name not in known_callers:
                raise SystemExit(
                    f"[ERROR] key_ref {item['key_name']} references unknown allowed caller {caller_name}"
                )
    for item in services:
        checked_reference_count += 2
        if item["tenant_id"] not in known_tenants:
            raise SystemExit(f"[ERROR] service {item['service_id']} references unknown tenant_id {item['tenant_id']}")
        if item["dataset_id"] not in known_datasets:
            raise SystemExit(f"[ERROR] service {item['service_id']} references unknown dataset_id {item['dataset_id']}")
    for plan in policy_plans:
        callers_payload = (plan.get("payload") or {}).get("callers") or {}
        if not isinstance(callers_payload, dict):
            continue
        for caller_name, values in callers_payload.items():
            if not isinstance(values, dict):
                continue
            checked_reference_count += 1
            caller_text = str(caller_name)
            if caller_text not in known_callers:
                raise SystemExit(f"[ERROR] policy {plan['policy_path']} references unknown caller {caller_text}")
            tenant_id = normalize_optional_text(values.get("tenant_id"))
            if tenant_id:
                checked_reference_count += 1
                if tenant_id not in known_tenants:
                    raise SystemExit(f"[ERROR] policy {plan['policy_path']} references unknown tenant_id {tenant_id}")
            for dataset_id in values.get("allowed_dataset_ids") or []:
                dataset_text = normalize_optional_text(dataset_id)
                if not dataset_text:
                    continue
                checked_reference_count += 1
                if dataset_text not in known_datasets:
                    raise SystemExit(f"[ERROR] policy {plan['policy_path']} references unknown dataset_id {dataset_text}")
            for service_id in values.get("allowed_service_ids") or []:
                service_text = normalize_optional_text(service_id)
                if not service_text:
                    continue
                checked_reference_count += 1
                if service_text not in known_services:
                    raise SystemExit(f"[ERROR] policy {plan['policy_path']} references unknown service_id {service_text}")
    return {"checked_reference_count": checked_reference_count}


def fetch_existing_caller_identity_state(
    conn: sqlite3.Connection,
    *,
    caller: str,
    issuer: str,
    subject: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
          caller,
          issuer,
          subject,
          subject_type,
          service_id,
          display_name,
          platform_roles_json,
          enabled,
          metadata_json,
          source,
          created_at_utc
        FROM caller_identities
        WHERE caller = ? AND issuer = ? AND subject = ?
        """,
        (caller, issuer, subject),
    ).fetchone()
    return row_to_dict(row)


def fetch_existing_key_ref_state(
    conn: sqlite3.Connection,
    *,
    key_name: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
          key_name,
          purpose,
          service_id,
          backend_kind,
          backend_ref,
          active_version,
          allowed_callers_json,
          source,
          created_at_utc,
          updated_at_utc
        FROM key_refs
        WHERE key_name = ?
        """,
        (key_name,),
    ).fetchone()
    return row_to_dict(row)


def fetch_existing_key_version_state(
    conn: sqlite3.Connection,
    *,
    key_name: str,
    version: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
          key_name,
          version,
          enabled,
          status,
          secret_ref_kind,
          secret_ref_name,
          backend_key_version,
          created_at_utc,
          source,
          metadata_json
        FROM key_versions
        WHERE key_name = ? AND version = ?
        """,
        (key_name, version),
    ).fetchone()
    return row_to_dict(row)


def plan_caller_identity(
    conn: sqlite3.Connection,
    *,
    desired: dict[str, Any],
) -> dict[str, Any]:
    existing = fetch_existing_caller_identity_state(
        conn,
        caller=str(desired["caller"]),
        issuer=str(desired["issuer"]),
        subject=str(desired["subject"]),
    )
    action = "insert"
    if existing is not None:
        action = "noop"
        for field_name in (
            "subject_type",
            "service_id",
            "display_name",
            "platform_roles_json",
            "enabled",
            "metadata_json",
            "source",
        ):
            if existing.get(field_name) != desired.get(field_name):
                action = "update"
                break
    key_value = "|".join(
        (
            str(desired["caller"]),
            str(desired["issuer"]),
            str(desired["subject"]),
        )
    )
    return {
        "entity": "caller_identities",
        "key_name": "caller|issuer|subject",
        "key_value": key_value,
        "action": action,
        "existing": existing,
        "desired": desired,
    }


def apply_caller_identity(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    *,
    imported_at: str,
) -> dict[str, Any]:
    desired = dict(plan["desired"])
    if plan["action"] != "noop":
        conn.execute(
            """
            INSERT INTO caller_identities(
              caller, issuer, subject, subject_type, service_id, display_name,
              platform_roles_json, enabled, metadata_json, source, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(caller, issuer, subject) DO UPDATE SET
              subject_type=excluded.subject_type,
              service_id=excluded.service_id,
              display_name=excluded.display_name,
              platform_roles_json=excluded.platform_roles_json,
              enabled=excluded.enabled,
              metadata_json=excluded.metadata_json,
              source=excluded.source
            """,
            (
                desired["caller"],
                desired["issuer"],
                desired["subject"],
                desired["subject_type"],
                desired["service_id"],
                desired["display_name"],
                desired["platform_roles_json"],
                desired["enabled"],
                desired["metadata_json"],
                desired["source"],
                imported_at,
            ),
        )
    state_after = fetch_existing_caller_identity_state(
        conn,
        caller=str(desired["caller"]),
        issuer=str(desired["issuer"]),
        subject=str(desired["subject"]),
    )
    return {
        "entity": "caller_identities",
        "key_name": str(plan["key_name"]),
        "key_value": str(plan["key_value"]),
        "action": str(plan["action"]),
        "existing": plan["existing"],
        "desired": desired,
        "state_after": state_after,
    }


def plan_key_ref(
    conn: sqlite3.Connection,
    *,
    desired: dict[str, Any],
) -> dict[str, Any]:
    existing = fetch_existing_key_ref_state(conn, key_name=str(desired["key_name"]))
    action = "insert"
    if existing is not None:
        action = "noop"
        for field_name in (
            "purpose",
            "service_id",
            "backend_kind",
            "backend_ref",
            "active_version",
            "allowed_callers_json",
            "source",
        ):
            if existing.get(field_name) != desired.get(field_name):
                action = "update"
                break
    return {
        "entity": "key_refs",
        "key_name": "key_name",
        "key_value": str(desired["key_name"]),
        "action": action,
        "existing": existing,
        "desired": {
            key: value
            for key, value in desired.items()
            if key != "versions"
        },
    }


def plan_key_version(
    conn: sqlite3.Connection,
    *,
    desired: dict[str, Any],
) -> dict[str, Any]:
    existing = fetch_existing_key_version_state(
        conn,
        key_name=str(desired["key_name"]),
        version=str(desired["version"]),
    )
    action = "insert"
    if existing is not None:
        action = "noop"
        for field_name in (
            "enabled",
            "status",
            "secret_ref_kind",
            "secret_ref_name",
            "backend_key_version",
            "created_at_utc",
            "source",
            "metadata_json",
        ):
            if existing.get(field_name) != desired.get(field_name):
                action = "update"
                break
    return {
        "entity": "key_versions",
        "key_name": "key_name|version",
        "key_value": f"{desired['key_name']}|{desired['version']}",
        "action": action,
        "existing": existing,
        "desired": desired,
    }


def apply_key_ref(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    *,
    imported_at: str,
) -> dict[str, Any]:
    desired = dict(plan["desired"])
    if plan["action"] != "noop":
        conn.execute(
            """
            INSERT INTO key_refs(
              key_name, purpose, service_id, backend_kind, backend_ref, active_version,
              allowed_callers_json, source, created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key_name) DO UPDATE SET
              purpose=excluded.purpose,
              service_id=excluded.service_id,
              backend_kind=excluded.backend_kind,
              backend_ref=excluded.backend_ref,
              active_version=excluded.active_version,
              allowed_callers_json=excluded.allowed_callers_json,
              source=excluded.source,
              updated_at_utc=excluded.updated_at_utc
            """,
            (
                desired["key_name"],
                desired["purpose"],
                desired["service_id"],
                desired["backend_kind"],
                desired["backend_ref"],
                desired["active_version"],
                desired["allowed_callers_json"],
                desired["source"],
                imported_at,
                imported_at,
            ),
        )
    state_after = fetch_existing_key_ref_state(conn, key_name=str(desired["key_name"]))
    return {
        "entity": "key_refs",
        "key_name": str(plan["key_name"]),
        "key_value": str(plan["key_value"]),
        "action": str(plan["action"]),
        "existing": plan["existing"],
        "desired": desired,
        "state_after": state_after,
    }


def apply_key_version(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
) -> dict[str, Any]:
    desired = dict(plan["desired"])
    if plan["action"] != "noop":
        conn.execute(
            """
            INSERT INTO key_versions(
              key_name, version, enabled, status, secret_ref_kind, secret_ref_name,
              backend_key_version, created_at_utc, source, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key_name, version) DO UPDATE SET
              enabled=excluded.enabled,
              status=excluded.status,
              secret_ref_kind=excluded.secret_ref_kind,
              secret_ref_name=excluded.secret_ref_name,
              backend_key_version=excluded.backend_key_version,
              created_at_utc=excluded.created_at_utc,
              source=excluded.source,
              metadata_json=excluded.metadata_json
            """,
            (
                desired["key_name"],
                desired["version"],
                desired["enabled"],
                desired["status"],
                desired["secret_ref_kind"],
                desired["secret_ref_name"],
                desired["backend_key_version"],
                desired["created_at_utc"],
                desired["source"],
                desired["metadata_json"],
            ),
        )
    state_after = fetch_existing_key_version_state(
        conn,
        key_name=str(desired["key_name"]),
        version=str(desired["version"]),
    )
    return {
        "entity": "key_versions",
        "key_name": str(plan["key_name"]),
        "key_value": str(plan["key_value"]),
        "action": str(plan["action"]),
        "existing": plan["existing"],
        "desired": desired,
        "state_after": state_after,
    }


def log_mutation(
    conn: sqlite3.Connection,
    *,
    operation: str,
    entity_type: str,
    entity_id: str,
    actor: str | None,
    source: str | None,
    old_state: Any,
    new_state: Any,
    applied_at: str,
    notes: str | None = None,
) -> None:
    """Write one row to control_plane_mutations. Silently skips if table doesn't exist yet."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='control_plane_mutations'"
    ).fetchone()
    if not exists:
        return
    conn.execute(
        """
        INSERT INTO control_plane_mutations(
          mutation_id, operation, entity_type, entity_id, actor, source,
          old_state_json, new_state_json, status, applied_at_utc, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?, ?)
        """,
        (
            str(uuid.uuid4()),
            operation,
            entity_type,
            entity_id,
            actor,
            source,
            json.dumps(old_state, ensure_ascii=False) if old_state is not None else None,
            json.dumps(new_state, ensure_ascii=False) if new_state is not None else None,
            applied_at,
            notes,
        ),
    )


def log_entity_mutations(
    conn: sqlite3.Connection,
    results: list[dict[str, Any]],
    *,
    applied_at: str,
    actor: str | None = None,
    source: str | None = None,
) -> None:
    """Log mutations for all non-noop entity apply results."""
    for result in results:
        action = str(result.get("action") or "")
        if action == "noop":
            continue
        entity_type = str(result.get("entity") or "unknown")
        entity_id = str(result.get("key_value") or "")
        old_state = result.get("existing")
        new_state = result.get("state_after")
        log_mutation(
            conn,
            operation=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor=actor,
            source=source,
            old_state=old_state,
            new_state=new_state,
            applied_at=applied_at,
        )


def summarize_registry_apply(
    *,
    entity_results: dict[str, list[dict[str, Any]]],
    policy_results: list[dict[str, Any]],
    validation: dict[str, Any],
) -> dict[str, Any]:
    entity_action_counts = {"insert": 0, "update": 0, "noop": 0}
    policy_action_counts = {"insert": 0, "replace": 0, "repair": 0, "noop": 0}
    requested_counts: dict[str, int] = {}
    for entity_name, rows in entity_results.items():
        requested_counts[entity_name] = len(rows)
        for row in rows:
            action = str(row.get("action") or "")
            if action in entity_action_counts:
                entity_action_counts[action] += 1
    for row in policy_results:
        action = str(row.get("action") or "")
        if action in policy_action_counts:
            policy_action_counts[action] += 1
    return {
        "requested_counts": {
            **requested_counts,
            "policies": len(policy_results),
        },
        "entity_action_counts": entity_action_counts,
        "policy_action_counts": policy_action_counts,
        "checked_reference_count": int(validation.get("checked_reference_count") or 0),
    }


def cmd_apply_registry(args: argparse.Namespace) -> int:
    manifest_path, manifest = load_registry_manifest(args.manifest)
    manifest_dir = manifest_path.parent
    tenants = [normalize_manifest_entity("tenants", item, manifest_dir=manifest_dir) for item in manifest.get("tenants", [])]
    datasets = [normalize_manifest_entity("datasets", item, manifest_dir=manifest_dir) for item in manifest.get("datasets", [])]
    services = [normalize_manifest_entity("services", item, manifest_dir=manifest_dir) for item in manifest.get("services", [])]
    callers = [normalize_manifest_entity("callers", item, manifest_dir=manifest_dir) for item in manifest.get("callers", [])]
    caller_identities = [
        normalize_manifest_caller_identity(item)
        for item in manifest.get("caller_identities", [])
    ]
    key_refs = [normalize_manifest_key_ref(item) for item in manifest.get("key_refs", [])]
    issuer_entries = [normalize_manifest_issuer_entry(item) for item in manifest.get("issuer_registry", [])]
    policies = [normalize_manifest_policy_entry(item, manifest_dir=manifest_dir) for item in manifest.get("policies", [])]

    validate_unique_keys(tenants, entity_name="tenant_id", key_name="tenant_id")
    validate_unique_keys(datasets, entity_name="dataset_id", key_name="dataset_id")
    validate_unique_keys(services, entity_name="service_id", key_name="service_id")
    validate_unique_keys(callers, entity_name="caller", key_name="caller")
    validate_unique_caller_identity_keys(caller_identities)
    validate_unique_key_ref_keys(key_refs)
    validate_unique_keys(issuer_entries, entity_name="issuer", key_name="issuer")
    validate_unique_keys(policies, entity_name="policy path", key_name="path")

    conn = connect_db(args.db_path, dsn=args.db_dsn)
    try:
        applied_migrations = apply_migrations(conn)
        entity_plans = {
            "tenants": [plan_managed_entity(conn, entity_name="tenants", desired=item) for item in tenants],
            "datasets": [plan_managed_entity(conn, entity_name="datasets", desired=item) for item in datasets],
            "services": [plan_managed_entity(conn, entity_name="services", desired=item) for item in services],
            "callers": [plan_managed_entity(conn, entity_name="callers", desired=item) for item in callers],
            "caller_identities": [plan_caller_identity(conn, desired=item) for item in caller_identities],
            "key_refs": [plan_key_ref(conn, desired=item) for item in key_refs],
            "key_versions": [
                plan_key_version(conn, desired=version)
                for item in key_refs
                for version in item["versions"]
            ],
            "issuer_registry": [plan_issuer_entry(conn, desired=item) for item in issuer_entries],
        }
        policy_plans = [
            plan_policy_file(
                conn,
                policy_path=item["path"],
                required_schema=str(item["required_schema"] or ""),
            )
            for item in policies
        ]
        validation_summary = validate_manifest_references(
            conn,
            tenants=tenants,
            datasets=datasets,
            services=services,
            callers=callers,
            caller_identities=caller_identities,
            key_refs=key_refs,
            policy_plans=policy_plans,
        )

        entity_results: dict[str, list[dict[str, Any]]] = {}
        policy_results: list[dict[str, Any]] = []
        imported_at = utc_now()
        if not args.dry_run:
            try:
                for entity_name in ("tenants", "datasets", "services", "callers"):
                    entity_results[entity_name] = [
                        apply_managed_entity(conn, plan, imported_at=imported_at)
                        for plan in entity_plans[entity_name]
                    ]
                entity_results["caller_identities"] = [
                    apply_caller_identity(conn, plan, imported_at=imported_at)
                    for plan in entity_plans["caller_identities"]
                ]
                entity_results["key_refs"] = [
                    apply_key_ref(conn, plan, imported_at=imported_at)
                    for plan in entity_plans["key_refs"]
                ]
                entity_results["key_versions"] = [
                    apply_key_version(conn, plan)
                    for plan in entity_plans["key_versions"]
                ]
                entity_results["issuer_registry"] = [
                    apply_issuer_entry(conn, plan, imported_at=imported_at)
                    for plan in entity_plans["issuer_registry"]
                ]
                for plan in policy_plans:
                    policy_results.append(apply_policy_plan(conn, plan, imported_at=imported_at))
                # Mutation audit trail: log all non-noop writes
                manifest_source = str(manifest_path)
                for entity_name, results in entity_results.items():
                    log_entity_mutations(
                        conn,
                        results,
                        applied_at=imported_at,
                        actor="apply-registry",
                        source=manifest_source,
                    )
                for pol_result in policy_results:
                    pol_action = str(pol_result.get("action") or "")
                    if pol_action != "noop":
                        log_mutation(
                            conn,
                            operation=pol_action,
                            entity_type="policy",
                            entity_id=str(pol_result.get("policy_id") or pol_result.get("policy_path") or ""),
                            actor="apply-registry",
                            source=manifest_source,
                            old_state=pol_result.get("existing_policy"),
                            new_state=pol_result.get("state_after"),
                            applied_at=imported_at,
                        )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        else:
            entity_results = {
                entity_name: [
                    {
                        **plan,
                        "state_after": None,
                    }
                    for plan in entity_plans[entity_name]
                ]
                for entity_name in entity_plans
            }
            policy_results = [
                {
                    "policy_id": plan["policy_id"],
                    "policy_path": plan["policy_path"],
                    "schema_name": plan["schema_name"],
                    "action": plan["action"],
                    "existing_policy": plan["existing_policy"],
                    "incoming": plan["incoming"],
                    "state_after": None,
                }
                for plan in policy_plans
            ]
    finally:
        conn.close()

    report = {
        "schema": REGISTRY_APPLY_SCHEMA,
        "generated_at_utc": utc_now(),
        "db_path": str(Path(args.db_path).resolve()) if args.db_path else None,
        "db_dsn": args.db_dsn or None,
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "mode": "dry_run" if args.dry_run else "apply",
        "applied_migrations": applied_migrations,
        "summary": summarize_registry_apply(
            entity_results=entity_results,
            policy_results=policy_results,
            validation=validation_summary,
        ),
        "validation": {
            "status": "ok",
            **validation_summary,
        },
        "entities": entity_results,
        "policies": policy_results,
    }
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    report = build_status_report(db_path=args.db_path, db_dsn=args.db_dsn)
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    source_path = Path(args.db_path).resolve()
    if not source_path.is_file():
        raise SystemExit(f"[ERROR] metadata DB does not exist: {source_path}")
    backup_path = ensure_output_path(args.out_path, overwrite=args.overwrite)
    if backup_path == source_path:
        raise SystemExit("[ERROR] backup output must differ from source DB path")

    source_conn = connect_db(str(source_path))
    try:
        if backup_path.exists():
            backup_path.unlink()
        dest_conn = sqlite3.connect(str(backup_path))
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
        status = build_status_report(db_path=str(source_path))
    finally:
        source_conn.close()

    report = {
        "schema": BACKUP_SCHEMA,
        "generated_at_utc": utc_now(),
        "status": "ok",
        "source_db_path": str(source_path),
        "backup_db_path": str(backup_path),
        "source_sha256": sha256_file(source_path),
        "backup_sha256": sha256_file(backup_path),
        "source_size_bytes": source_path.stat().st_size,
        "backup_size_bytes": backup_path.stat().st_size,
        "applied_migrations": status["applied_migrations"],
        "used_sqlite_backup_api": True,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    backup_path = Path(args.backup_db_path).resolve()
    if not backup_path.is_file():
        raise SystemExit(f"[ERROR] backup DB does not exist: {backup_path}")
    restored_path = ensure_output_path(args.out_db_path, overwrite=args.overwrite)
    if restored_path == backup_path:
        raise SystemExit("[ERROR] restore output must differ from backup DB path")

    source_conn = connect_db(str(backup_path))
    try:
        if restored_path.exists():
            restored_path.unlink()
        dest_conn = sqlite3.connect(str(restored_path))
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()

    restored_status = build_status_report(db_path=str(restored_path))
    report = {
        "schema": RESTORE_SCHEMA,
        "generated_at_utc": utc_now(),
        "status": "ok",
        "backup_db_path": str(backup_path),
        "restored_db_path": str(restored_path),
        "backup_sha256": sha256_file(backup_path),
        "restored_sha256": sha256_file(restored_path),
        "backup_size_bytes": backup_path.stat().st_size,
        "restored_size_bytes": restored_path.stat().st_size,
        "overwrite": bool(args.overwrite),
        "used_sqlite_backup_api": True,
        "restored_status": restored_status,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def export_entities(conn: sqlite3.Connection, *, limit: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for entity_name in (
        "tenants",
        "datasets",
        "services",
        "callers",
        "caller-identities",
        "key-refs",
        "key-versions",
        "policies",
        "policy-bindings",
        "caller-permissions",
    ):
        result[entity_name] = query_entities(conn, entity=entity_name, limit=limit)
    return result


def cmd_export_json(args: argparse.Namespace) -> int:
    db_path = Path(args.db_path).resolve() if args.db_path else None
    if db_path is not None and not db_path.is_file():
        raise SystemExit(f"[ERROR] metadata DB does not exist: {db_path}")
    if args.job_limit <= 0 or args.entity_limit <= 0:
        raise SystemExit("[ERROR] --job-limit and --entity-limit must be positive")
    out_path = ensure_output_path(args.out_path, overwrite=args.overwrite)

    conn = connect_db(str(db_path) if db_path else "", dsn=args.db_dsn)
    try:
        status = build_status_report(db_path=str(db_path) if db_path else "", db_dsn=args.db_dsn)
        jobs = query_jobs(conn, limit=args.job_limit)
        entities = export_entities(conn, limit=args.entity_limit)
        sample_artifacts = [
            row_to_dict(row)
            for row in conn.execute(
                """
                SELECT job_id, stage, artifact_type, path, sha256, file_format, exists_on_disk
                FROM job_artifacts
                ORDER BY job_id DESC, stage ASC, artifact_type ASC
                LIMIT ?
                """,
                (args.artifact_limit,),
            ).fetchall()
        ]
    finally:
        conn.close()

    export_payload = {
        "schema": EXPORT_SCHEMA,
        "generated_at_utc": utc_now(),
        "db_path": str(db_path) if db_path else None,
        "db_dsn": args.db_dsn or None,
        "out_path": str(out_path),
        "job_limit": args.job_limit,
        "entity_limit": args.entity_limit,
        "artifact_limit": args.artifact_limit,
        "status": status,
        "jobs": jobs,
        "entities": entities,
        "sample_artifacts": sample_artifacts,
    }
    out_path.write_text(json.dumps(export_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(export_payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Manage the SQLite metadata sidecar lifecycle.")
    sub = ap.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Report metadata DB status, migrations, and table counts.")
    status.add_argument("--db-path", default="")
    status.add_argument("--db-dsn", default="")
    status.add_argument("--output", default="")

    backup = sub.add_parser("backup", help="Create a consistent SQLite backup copy with the backup API.")
    backup.add_argument("--db-path", required=True)
    backup.add_argument("--out-path", required=True)
    backup.add_argument("--overwrite", action="store_true")

    restore = sub.add_parser("restore", help="Restore a SQLite metadata DB copy from a backup DB.")
    restore.add_argument("--backup-db-path", required=True)
    restore.add_argument("--out-db-path", required=True)
    restore.add_argument("--overwrite", action="store_true")

    export_json = sub.add_parser("export-json", help="Export a portable JSON snapshot of the metadata sidecar.")
    export_json.add_argument("--db-path", default="")
    export_json.add_argument("--db-dsn", default="")
    export_json.add_argument("--out-path", required=True)
    export_json.add_argument("--job-limit", type=int, default=20)
    export_json.add_argument("--entity-limit", type=int, default=20)
    export_json.add_argument("--artifact-limit", type=int, default=20)
    export_json.add_argument("--overwrite", action="store_true")

    apply_registry = sub.add_parser(
        "apply-registry",
        help="Apply a controlled registry/policy manifest into the metadata sidecar.",
    )
    apply_registry.add_argument("--db-path", default="")
    apply_registry.add_argument("--db-dsn", default="")
    apply_registry.add_argument("--manifest", required=True)
    apply_registry.add_argument("--dry-run", action="store_true")
    apply_registry.add_argument("--output", default="")

    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.command in {"status", "export-json", "apply-registry"} and not getattr(args, "db_path", "") and not getattr(args, "db_dsn", ""):
        raise SystemExit("[ERROR] one of --db-path or --db-dsn is required")
    if args.command == "status":
        return cmd_status(args)
    if args.command == "backup":
        return cmd_backup(args)
    if args.command == "restore":
        return cmd_restore(args)
    if args.command == "apply-registry":
        return cmd_apply_registry(args)
    return cmd_export_json(args)


if __name__ == "__main__":
    raise SystemExit(main())
