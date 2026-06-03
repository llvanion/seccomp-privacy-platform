#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_ID = "business_access_check_report/v1"
POLICY_SCHEMA_ID = "business_access_policy/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json_object(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def as_string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if item not in (None, "")}


def flatten_field_classes(policy: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    classes = policy.get("field_classes")
    if not isinstance(classes, dict):
        return result
    for class_name, spec in classes.items():
        if not isinstance(spec, dict):
            continue
        for field in spec.get("fields") or []:
            field_name = str(field)
            if field_name:
                result[field_name] = str(class_name)
    return result


def parse_scope(values: list[str]) -> dict[str, str]:
    scope: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"--scope entries must be key=value, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("--scope key must not be empty")
        scope[key] = value.strip()
    return scope


def masking_for_field(policy: dict[str, Any], field: str) -> str | None:
    protected = policy.get("protected_fields")
    if not isinstance(protected, dict):
        return None
    spec = protected.get(field)
    if not isinstance(spec, dict):
        return None
    value = spec.get("masking")
    return str(value) if value not in (None, "") else None


def build_report(
    *,
    policy: dict[str, Any],
    role: str,
    entity: str,
    fields: list[str],
    purpose: str | None,
    scope: dict[str, str],
    relationship: str | None,
) -> dict[str, Any]:
    if policy.get("schema") != POLICY_SCHEMA_ID:
        raise ValueError(f"policy must use {POLICY_SCHEMA_ID}")
    roles = policy.get("roles")
    if not isinstance(roles, dict):
        raise ValueError("policy.roles must be an object")
    role_spec = roles.get(role)
    field_to_class = flatten_field_classes(policy)
    if not isinstance(role_spec, dict):
        return deny_all(
            policy=policy,
            role=role,
            entity=entity,
            fields=fields,
            purpose=purpose,
            scope=scope,
            relationship=relationship,
            reason_code="unknown_role",
            reason=f"role {role!r} is not present in policy",
            field_to_class=field_to_class,
        )

    allowed_entities = as_string_set(role_spec.get("allowed_entities"))
    if entity not in allowed_entities:
        return deny_all(
            policy=policy,
            role=role,
            entity=entity,
            fields=fields,
            purpose=purpose,
            scope=scope,
            relationship=relationship,
            reason_code="entity_not_allowed",
            reason=f"role {role} cannot access entity {entity}",
            field_to_class=field_to_class,
        )

    conditions = role_spec.get("conditions") if isinstance(role_spec.get("conditions"), dict) else {}
    if bool(conditions.get("scope_required")) and not scope:
        return deny_all(
            policy=policy,
            role=role,
            entity=entity,
            fields=fields,
            purpose=purpose,
            scope=scope,
            relationship=relationship,
            reason_code="scope_required",
            reason="business access request is missing required scope",
            field_to_class=field_to_class,
        )

    expected_relationship = conditions.get("relationship_required")
    if expected_relationship not in (None, "") and relationship != str(expected_relationship):
        return deny_all(
            policy=policy,
            role=role,
            entity=entity,
            fields=fields,
            purpose=purpose,
            scope=scope,
            relationship=relationship,
            reason_code="relationship_required",
            reason=f"relationship must be {expected_relationship}",
            field_to_class=field_to_class,
        )

    allowed_purposes = as_string_set(conditions.get("purpose_required"))
    if allowed_purposes and (purpose or "") not in allowed_purposes:
        return deny_all(
            policy=policy,
            role=role,
            entity=entity,
            fields=fields,
            purpose=purpose,
            scope=scope,
            relationship=relationship,
            reason_code="purpose_not_allowed",
            reason=f"purpose must be one of {sorted(allowed_purposes)}",
            field_to_class=field_to_class,
        )

    allowed_classes = as_string_set(role_spec.get("allowed_field_classes"))
    masked_classes = as_string_set(role_spec.get("masked_field_classes"))
    denied_classes = as_string_set(role_spec.get("denied_field_classes"))
    field_decisions: list[dict[str, Any]] = []
    for field in fields:
        field_class = field_to_class.get(field)
        if field_class is None:
            field_decisions.append({
                "field": field,
                "field_class": None,
                "decision": "deny",
                "masking": None,
                "reason_code": "unknown_field",
            })
            continue
        if field_class in denied_classes:
            field_decisions.append({
                "field": field,
                "field_class": field_class,
                "decision": "deny",
                "masking": None,
                "reason_code": "field_class_denied",
            })
            continue
        if field_class in masked_classes:
            field_decisions.append({
                "field": field,
                "field_class": field_class,
                "decision": "mask",
                "masking": masking_for_field(policy, field) or "mask",
                "reason_code": "field_class_masked",
            })
            continue
        if field_class in allowed_classes:
            field_decisions.append({
                "field": field,
                "field_class": field_class,
                "decision": "allow",
                "masking": None,
                "reason_code": "field_class_allowed",
            })
            continue
        field_decisions.append({
            "field": field,
            "field_class": field_class,
            "decision": "deny",
            "masking": None,
            "reason_code": "field_class_not_allowed",
        })

    return finish_report(
        policy=policy,
        role=role,
        entity=entity,
        fields=fields,
        purpose=purpose,
        scope=scope,
        relationship=relationship,
        field_decisions=field_decisions,
        default_reason="ok",
    )


def deny_all(
    *,
    policy: dict[str, Any],
    role: str,
    entity: str,
    fields: list[str],
    purpose: str | None,
    scope: dict[str, str],
    relationship: str | None,
    reason_code: str,
    reason: str,
    field_to_class: dict[str, str],
) -> dict[str, Any]:
    return finish_report(
        policy=policy,
        role=role,
        entity=entity,
        fields=fields,
        purpose=purpose,
        scope=scope,
        relationship=relationship,
        field_decisions=[
            {
                "field": field,
                "field_class": field_to_class.get(field),
                "decision": "deny",
                "masking": None,
                "reason_code": reason_code,
            }
            for field in fields
        ],
        default_reason=reason,
        override_decision="deny",
        override_reason_code=reason_code,
    )


def finish_report(
    *,
    policy: dict[str, Any],
    role: str,
    entity: str,
    fields: list[str],
    purpose: str | None,
    scope: dict[str, str],
    relationship: str | None,
    field_decisions: list[dict[str, Any]],
    default_reason: str,
    override_decision: str | None = None,
    override_reason_code: str | None = None,
) -> dict[str, Any]:
    allowed = sum(1 for item in field_decisions if item["decision"] == "allow")
    masked = sum(1 for item in field_decisions if item["decision"] == "mask")
    denied = sum(1 for item in field_decisions if item["decision"] == "deny")
    unknown = sum(1 for item in field_decisions if item["field_class"] is None)
    if override_decision:
        decision = override_decision
    elif denied:
        decision = "deny"
    elif masked:
        decision = "mask"
    else:
        decision = "allow"
    if override_reason_code:
        reason_code = override_reason_code
    elif denied:
        reason_code = "field_denied"
    elif masked:
        reason_code = "requires_masking"
    else:
        reason_code = "ok"
    return {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "policy_id": str(policy.get("policy_id") or ""),
        "policy_version": str(policy.get("version") or ""),
        "request": {
            "role": role,
            "entity": entity,
            "fields": fields,
            "purpose": purpose,
            "scope": scope,
            "relationship": relationship,
        },
        "decision": decision,
        "reason_code": reason_code,
        "reason": default_reason,
        "field_decisions": field_decisions,
        "summary": {
            "allowed_count": allowed,
            "masked_count": masked,
            "denied_count": denied,
            "unknown_field_count": unknown,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Evaluate business_access_policy/v1 for field-level e-commerce access.")
    ap.add_argument("--policy", required=True)
    ap.add_argument("--role", required=True)
    ap.add_argument("--entity", required=True)
    ap.add_argument("--field", action="append", default=[], help="Requested field; may be repeated")
    ap.add_argument("--purpose", default="")
    ap.add_argument("--relationship", default="")
    ap.add_argument("--scope", action="append", default=[], help="Scope key=value; may be repeated")
    ap.add_argument("--output", default="")
    ap.add_argument("--assert-decision", choices=["allow", "mask", "deny"], default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if not args.field:
        raise SystemExit("[ERROR] at least one --field is required")
    policy = load_json_object(args.policy)
    report = build_report(
        policy=policy,
        role=str(args.role),
        entity=str(args.entity),
        fields=[str(item) for item in args.field],
        purpose=str(args.purpose).strip() or None,
        scope=parse_scope(args.scope),
        relationship=str(args.relationship).strip() or None,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.assert_decision and report["decision"] != args.assert_decision:
        raise SystemExit(f"[ERROR] expected decision {args.assert_decision}, got {report['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
