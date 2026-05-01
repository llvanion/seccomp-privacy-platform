#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import connect_db, sha256_file, utc_now  # noqa: E402


INPUT_POLICY_SCHEMA = "sse_export_policy/v1"
OUTPUT_SCHEMA = "authz_tuple_export/v1"
PLATFORM_ROLE_NAMES = (
    "platform_admin",
    "platform_auditor",
    "privacy_operator",
    "query_submitter",
    "service_operator",
)
CAPABILITY_NAMES = (
    "can_run_bridge",
    "can_run_pjc",
    "can_release",
    "can_use_record_recovery_service",
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def parse_permission_value(value: Any) -> Any:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if item not in (None, "")})


def normalize_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def infer_subject_type(values: dict[str, Any]) -> tuple[str, str]:
    platform_roles = set(normalize_string_list(values.get("platform_roles")))
    access_profile = str(values.get("access_profile") or "").lower()
    if "service_operator" in platform_roles or "service" in access_profile:
        return "service_account", "role_or_profile_inference"
    return "user", "default_user"


def normalize_subject(caller: str, values: dict[str, Any], *, source_policy_id: str | None = None) -> dict[str, Any]:
    platform_roles = [role for role in normalize_string_list(values.get("platform_roles")) if role in PLATFORM_ROLE_NAMES]
    subject_type, subject_type_source = infer_subject_type(values)
    permissions = {name: normalize_bool(values.get(name)) for name in CAPABILITY_NAMES}
    tenant_id = values.get("tenant_id")
    tenant_value = str(tenant_id) if tenant_id not in (None, "") else None
    allowed_dataset_ids = normalize_string_list(values.get("allowed_dataset_ids"))
    allowed_service_ids = normalize_string_list(values.get("allowed_service_ids"))
    return {
        "subject": f"{subject_type}:{caller}",
        "caller": caller,
        "subject_type": subject_type,
        "subject_type_source": subject_type_source,
        "enabled": normalize_bool(values.get("enabled")),
        "tenant_id": tenant_value,
        "platform_roles": platform_roles,
        "access_profile": str(values.get("access_profile")) if values.get("access_profile") not in (None, "") else None,
        "allowed_dataset_ids": allowed_dataset_ids,
        "allowed_service_ids": allowed_service_ids,
        "permissions": permissions,
        "source_policy_id": source_policy_id,
    }


def matches_filters(subject: dict[str, Any], *, caller: str, tenant_id: str, dataset_id: str, service_id: str) -> bool:
    if caller and subject.get("caller") != caller:
        return False
    if tenant_id and subject.get("tenant_id") != tenant_id:
        return False
    if dataset_id and dataset_id not in (subject.get("allowed_dataset_ids") or []):
        return False
    if service_id and service_id not in (subject.get("allowed_service_ids") or []):
        return False
    return True


def build_tuple(user: str, relation: str, object_ref: str) -> dict[str, str]:
    user_type, _ = user.split(":", 1)
    object_type, object_id = object_ref.split(":", 1)
    return {
        "user": user,
        "relation": relation,
        "object": object_ref,
        "user_type": user_type,
        "object_type": object_type,
        "object_id": object_id,
    }


def relation_tuples(subject: dict[str, Any]) -> list[dict[str, str]]:
    enabled = subject.get("enabled")
    if enabled is not True:
        return []
    user = str(subject["subject"])
    tenant_id = subject.get("tenant_id")
    roles = set(subject.get("platform_roles") or [])
    permissions = subject.get("permissions") or {}
    tuples: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(relation: str, object_ref: str) -> None:
        key = (user, relation, object_ref)
        if key in seen:
            return
        seen.add(key)
        tuples.append(build_tuple(user, relation, object_ref))

    if tenant_id:
        add("member", f"tenant:{tenant_id}")
    access_profile = subject.get("access_profile")
    if access_profile:
        add("member", f"access_profile:{access_profile}")
    for role_name in sorted(roles):
        add("assignee", f"platform_role:{role_name}")
    if tenant_id and "platform_admin" in roles:
        add("admin", f"tenant:{tenant_id}")
    if tenant_id and "platform_auditor" in roles:
        add("auditor", f"tenant:{tenant_id}")
    for dataset_id in subject.get("allowed_dataset_ids") or []:
        add("reader", f"dataset:{dataset_id}")
        if "query_submitter" in roles:
            add("query_submitter", f"dataset:{dataset_id}")
        if "privacy_operator" in roles:
            add("privacy_operator", f"dataset:{dataset_id}")
        if permissions.get("can_use_record_recovery_service") is True:
            add("recovery_allowed", f"dataset:{dataset_id}")
    for service_id in subject.get("allowed_service_ids") or []:
        if permissions.get("can_use_record_recovery_service") is True:
            add("can_recover", f"privacy_service:{service_id}")
        if "service_operator" in roles:
            add("operator", f"privacy_service:{service_id}")
    for capability_name, granted in sorted(permissions.items()):
        if granted is True:
            add("grantee", f"platform_capability:{capability_name}")
    return tuples


def summarize(subjects: list[dict[str, Any]], tuples: list[dict[str, str]]) -> dict[str, Any]:
    subject_type_counts = {"user": 0, "service_account": 0}
    for item in subjects:
        subject_type = str(item.get("subject_type") or "user")
        subject_type_counts[subject_type] = subject_type_counts.get(subject_type, 0) + 1

    object_type_counts: dict[str, int] = {}
    relation_counts: dict[str, int] = {}
    for item in tuples:
        object_type = str(item.get("object_type") or "unknown")
        relation = str(item.get("relation") or "unknown")
        object_type_counts[object_type] = object_type_counts.get(object_type, 0) + 1
        relation_counts[relation] = relation_counts.get(relation, 0) + 1

    active_subject_count = sum(1 for item in subjects if item.get("enabled") is True)
    disabled_subject_count = sum(1 for item in subjects if item.get("enabled") is False)
    return {
        "subject_count": len(subjects),
        "active_subject_count": active_subject_count,
        "disabled_subject_count": disabled_subject_count,
        "tuple_count": len(tuples),
        "subject_type_counts": subject_type_counts,
        "object_type_counts": object_type_counts,
        "relation_counts": relation_counts,
    }


def load_subjects_from_policy(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = load_json(path)
    if payload.get("schema") != INPUT_POLICY_SCHEMA:
        raise ValueError(f"{path} must use {INPUT_POLICY_SCHEMA}")
    callers = payload.get("callers")
    if not isinstance(callers, dict):
        raise ValueError(f"{path} must contain a callers object")
    policy_id = sha256_file(path) or str(path.resolve())
    subjects = [
        normalize_subject(str(caller), values, source_policy_id=policy_id)
        for caller, values in sorted(callers.items())
        if isinstance(values, dict)
    ]
    source = {
        "kind": "policy_config",
        "policy_count": 1,
        "policy_ids": [policy_id],
        "policy_paths": [str(path.resolve())],
        "policy_schema_names": [INPUT_POLICY_SCHEMA],
        "policy_path": str(path.resolve()),
    }
    return subjects, source


def load_subjects_from_db(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    conn = connect_db(str(path))
    try:
        rows = conn.execute(
            """
            SELECT
              cp.policy_id,
              p.path AS policy_path,
              p.schema_name,
              cp.caller,
              cp.permission_key,
              cp.permission_value,
              cp.imported_at_utc,
              cp.id
            FROM caller_permissions cp
            JOIN policies p ON p.policy_id = cp.policy_id
            WHERE p.schema_name = ?
            ORDER BY cp.imported_at_utc DESC, cp.id DESC
            """,
            (INPUT_POLICY_SCHEMA,),
        ).fetchall()
    finally:
        conn.close()

    values_by_caller: dict[str, dict[str, Any]] = {}
    source_policy_id_by_caller: dict[str, str] = {}
    seen: set[tuple[str, str]] = set()
    policy_ids: set[str] = set()
    policy_paths: set[str] = set()
    for row in rows:
        caller = str(row["caller"] or "")
        permission_key = str(row["permission_key"] or "")
        if not caller or not permission_key:
            continue
        pair = (caller, permission_key)
        if pair in seen:
            continue
        seen.add(pair)
        values_by_caller.setdefault(caller, {})[permission_key] = parse_permission_value(row["permission_value"])
        source_policy_id_by_caller.setdefault(caller, str(row["policy_id"]))
        policy_ids.add(str(row["policy_id"]))
        if row["policy_path"] not in (None, ""):
            policy_paths.add(str(row["policy_path"]))

    subjects = [
        normalize_subject(caller, values, source_policy_id=source_policy_id_by_caller.get(caller))
        for caller, values in sorted(values_by_caller.items())
    ]
    source = {
        "kind": "metadata_db",
        "policy_count": len(policy_ids),
        "policy_ids": sorted(policy_ids),
        "policy_paths": sorted(policy_paths),
        "policy_schema_names": [INPUT_POLICY_SCHEMA] if policy_ids else [],
        "db_path": str(path.resolve()),
    }
    return subjects, source


def render_export(args: argparse.Namespace) -> dict[str, Any]:
    if args.policy_config:
        subjects, source = load_subjects_from_policy(Path(args.policy_config))
    else:
        subjects, source = load_subjects_from_db(Path(args.db_path))

    filtered_subjects = [
        item
        for item in subjects
        if matches_filters(
            item,
            caller=args.caller,
            tenant_id=args.tenant_id,
            dataset_id=args.dataset_id,
            service_id=args.service_id,
        )
    ]
    tuples: list[dict[str, str]] = []
    for item in filtered_subjects:
        tuples.extend(relation_tuples(item))

    return {
        "schema": OUTPUT_SCHEMA,
        "generated_at_utc": utc_now(),
        "mapping_profile": "openfga_baseline_v1",
        "source": source,
        "filters": {
            "caller": args.caller or None,
            "tenant_id": args.tenant_id or None,
            "dataset_id": args.dataset_id or None,
            "service_id": args.service_id or None,
        },
        "subjects": filtered_subjects,
        "tuples": tuples,
        "summary": summarize(filtered_subjects, tuples),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Export current caller/tenant/dataset/service policy into a tuple baseline for OpenFGA-style authz sync."
    )
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--policy-config", default="")
    source.add_argument("--db-path", default="")
    ap.add_argument("--caller", default="")
    ap.add_argument("--tenant-id", default="")
    ap.add_argument("--dataset-id", default="")
    ap.add_argument("--service-id", default="")
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    payload = render_export(args)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
