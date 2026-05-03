#!/usr/bin/env python3
import json
import sqlite3
from pathlib import Path
from typing import Any

from scripts.metadata_db import sha256_file


MANIFEST_SCHEMA = "metadata_registry_manifest/v1"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def serialize_permission_value(value: Any) -> str:
    if isinstance(value, (dict, list, bool, int, float)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def policy_counts(conn: sqlite3.Connection, policy_id: str) -> dict[str, int]:
    return {
        "binding_count": int(
            conn.execute(
                "SELECT COUNT(*) FROM policy_bindings WHERE policy_id = ?",
                (policy_id,),
            ).fetchone()[0]
        ),
        "permission_count": int(
            conn.execute(
                "SELECT COUNT(*) FROM caller_permissions WHERE policy_id = ?",
                (policy_id,),
            ).fetchone()[0]
        ),
    }


def existing_policy_by_path(conn: sqlite3.Connection, policy_path: Path) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT policy_id, policy_kind, path, sha256, schema_name, imported_at_utc
        FROM policies
        WHERE path = ?
        """,
        (str(policy_path.resolve()),),
    ).fetchone()
    if row is None:
        return None
    data = {key: row[key] for key in row.keys()}
    data.update(policy_counts(conn, str(data["policy_id"])))
    return data


def existing_policy_by_id(conn: sqlite3.Connection, policy_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT policy_id, policy_kind, path, sha256, schema_name, imported_at_utc
        FROM policies
        WHERE policy_id = ?
        """,
        (policy_id,),
    ).fetchone()
    if row is None:
        return None
    data = {key: row[key] for key in row.keys()}
    data.update(policy_counts(conn, str(data["policy_id"])))
    return data


def policy_incoming_summary(payload: dict[str, Any]) -> dict[str, Any]:
    callers = payload.get("callers")
    if not isinstance(callers, dict):
        return {
            "caller_count": 0,
            "callers": [],
            "binding_count_expected": 0,
            "permission_count_expected": 0,
        }
    caller_names = sorted(str(caller) for caller, values in callers.items() if isinstance(values, dict))
    permission_count = 0
    for values in callers.values():
        if isinstance(values, dict):
            permission_count += len(values)
    return {
        "caller_count": len(caller_names),
        "callers": caller_names,
        "binding_count_expected": len(caller_names),
        "permission_count_expected": permission_count,
    }


def plan_policy_file(
    conn: sqlite3.Connection,
    *,
    policy_path: str | Path,
    required_schema: str = "",
) -> dict[str, Any]:
    path = Path(policy_path).resolve()
    if not path.is_file():
        raise ValueError(f"policy file does not exist: {path}")
    payload = load_json(path)
    schema_name = str(payload.get("schema") or "")
    if required_schema and schema_name != required_schema:
        raise ValueError(f"{path} must use {required_schema}, got {schema_name or '<missing>'}")
    policy_id = sha256_file(path) or str(path)
    existing_path = existing_policy_by_path(conn, path)
    existing_id = existing_policy_by_id(conn, policy_id)
    incoming = policy_incoming_summary(payload)
    action = "insert"
    existing = existing_path or existing_id
    if existing is not None:
        if str(existing["policy_id"]) != policy_id:
            action = "replace"
        else:
            same_path = str(existing.get("path") or "") == str(path)
            same_bindings = int(existing.get("binding_count") or 0) == int(incoming["binding_count_expected"])
            same_permissions = int(existing.get("permission_count") or 0) == int(incoming["permission_count_expected"])
            action = "noop" if same_path and same_bindings and same_permissions else "repair"
    return {
        "policy_id": policy_id,
        "policy_path": str(path),
        "schema_name": schema_name,
        "payload": payload,
        "required_schema": required_schema or None,
        "incoming": incoming,
        "existing_policy": existing,
        "action": action,
    }


def _insert_policy_children(
    conn: sqlite3.Connection,
    *,
    policy_id: str,
    policy_path: Path,
    callers: dict[str, Any],
    imported_at: str,
) -> None:
    for caller, caller_policy in callers.items():
        if not isinstance(caller_policy, dict):
            continue
        tenant_id = caller_policy.get("tenant_id")
        datasets = caller_policy.get("allowed_dataset_ids")
        services = caller_policy.get("allowed_service_ids")
        conn.execute(
            """
            INSERT INTO policy_bindings(
              policy_id, binding_kind, caller, tenant_id, dataset_id, service_id,
              source_file, binding_json, imported_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                policy_id,
                "caller_policy",
                str(caller),
                str(tenant_id) if tenant_id not in (None, "") else None,
                datasets[0] if isinstance(datasets, list) and len(datasets) == 1 else None,
                services[0] if isinstance(services, list) and len(services) == 1 else None,
                str(policy_path),
                json.dumps(caller_policy, ensure_ascii=False),
                imported_at,
            ),
        )
        for key, value in caller_policy.items():
            conn.execute(
                """
                INSERT INTO caller_permissions(
                  policy_id, caller, permission_key, permission_value, source_file, imported_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    policy_id,
                    str(caller),
                    str(key),
                    serialize_permission_value(value),
                    str(policy_path),
                    imported_at,
                ),
            )


def apply_policy_plan(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    *,
    imported_at: str,
) -> dict[str, Any]:
    path = Path(str(plan["policy_path"])).resolve()
    policy_id = str(plan["policy_id"])
    payload = plan["payload"]
    existing = plan.get("existing_policy")
    existing_policy_id = str(existing["policy_id"]) if isinstance(existing, dict) and existing.get("policy_id") else None
    if existing_policy_id and existing_policy_id != policy_id:
        conn.execute("DELETE FROM policies WHERE policy_id = ?", (existing_policy_id,))

    callers = payload.get("callers")
    if not isinstance(callers, dict):
        callers = {}

    if plan["action"] != "noop":
        conn.execute(
            """
            INSERT INTO policies(policy_id, policy_kind, path, sha256, schema_name, imported_at_utc, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(policy_id) DO UPDATE SET
              policy_kind=excluded.policy_kind,
              path=excluded.path,
              sha256=excluded.sha256,
              schema_name=excluded.schema_name,
              imported_at_utc=excluded.imported_at_utc,
              payload_json=excluded.payload_json
            """,
            (
                policy_id,
                str(plan["schema_name"] or "unknown_policy"),
                str(path),
                sha256_file(path),
                str(plan["schema_name"] or ""),
                imported_at,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.execute("DELETE FROM policy_bindings WHERE policy_id = ?", (policy_id,))
        conn.execute("DELETE FROM caller_permissions WHERE policy_id = ?", (policy_id,))
        _insert_policy_children(
            conn,
            policy_id=policy_id,
            policy_path=path,
            callers=callers,
            imported_at=imported_at,
        )

    state_after = existing_policy_by_id(conn, policy_id)
    return {
        "policy_id": policy_id,
        "policy_path": str(path),
        "schema_name": str(plan["schema_name"]),
        "action": str(plan["action"]),
        "existing_policy": existing,
        "incoming": plan["incoming"],
        "state_after": state_after,
    }
