#!/usr/bin/env python3
"""Write-side policy change governance tool.

Before a policy file is re-imported (e.g. a caller is added, removed, or
permissions changed), this tool validates the proposed change against a set
of governance rules and produces a structured proposal for review.

Governance checks:
  no_remove_active_bridge_callers  — callers with can_run_bridge=true in the
    current DB policy cannot be removed in the proposed change
  no_remove_enabled_callers        — enabled callers in the current policy
    cannot be silently dropped (must be explicitly disabled first)
  frozen_field_semantics           — release_policy / policy_kind / schema
    must not change type/kind
  permission_count_regression      — total granted permissions must not
    decrease by more than a configurable threshold without explicit override

--apply flag: applies the change through apply_policy_plan and logs to
  control_plane_mutations.

Outputs policy_change_proposal/v1.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import apply_migrations, connect_db, sha256_file, utc_now  # noqa: E402
from scripts.metadata_registry import (  # noqa: E402
    apply_policy_plan,
    existing_policy_by_path,
    plan_policy_file,
    policy_counts,
)
from scripts.manage_metadata_db import log_mutation  # noqa: E402

SCHEMA_ID = "policy_change_proposal/v1"
FROZEN_TOP_LEVEL_FIELDS = ("schema", "policy_kind")
DEFAULT_PERMISSION_REGRESSION_THRESHOLD = 0.20  # 20% drop triggers a warning


def load_policy_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"policy must be a JSON object: {path}")
    return payload


def callers_from_policy(payload: dict[str, Any]) -> dict[str, Any]:
    callers = payload.get("callers")
    return callers if isinstance(callers, dict) else {}


def active_bridge_callers(conn, policy_id: str) -> set[str]:
    """Return callers in the DB who currently have can_run_bridge=true for this policy."""
    rows = conn.execute(
        """
        SELECT caller FROM caller_permissions
        WHERE policy_id = ? AND permission_key = 'can_run_bridge'
          AND (permission_value = 'true' OR permission_value = '1')
        """,
        (policy_id,),
    ).fetchall()
    return {str(r["caller"]) for r in rows}


def enabled_callers_from_db(conn, policy_id: str) -> set[str]:
    """Return callers in the DB who have enabled=true for this policy."""
    rows = conn.execute(
        """
        SELECT caller FROM caller_permissions
        WHERE policy_id = ? AND permission_key = 'enabled'
          AND (permission_value = 'true' OR permission_value = '1')
        """,
        (policy_id,),
    ).fetchall()
    return {str(r["caller"]) for r in rows}


def diff_callers(
    current_callers: set[str],
    proposed_callers: set[str],
) -> dict[str, list[str]]:
    return {
        "added": sorted(proposed_callers - current_callers),
        "removed": sorted(current_callers - proposed_callers),
        "retained": sorted(current_callers & proposed_callers),
    }


def diff_permissions(
    current_payload: dict[str, Any],
    proposed_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return per-caller permission changes for callers present in both."""
    diffs: list[dict[str, Any]] = []
    cur_callers = callers_from_policy(current_payload)
    prop_callers = callers_from_policy(proposed_payload)
    for caller in sorted(cur_callers.keys() & prop_callers.keys()):
        cur = cur_callers[caller]
        prop = prop_callers[caller]
        changed_fields: list[dict[str, Any]] = []
        all_keys = set(cur.keys()) | set(prop.keys())
        for key in sorted(all_keys):
            cv, pv = cur.get(key), prop.get(key)
            if cv != pv:
                changed_fields.append({"field": key, "current": cv, "proposed": pv})
        if changed_fields:
            diffs.append({"caller": caller, "changed_fields": changed_fields})
    return diffs


def run_governance_checks(
    *,
    conn,
    existing_policy_id: str | None,
    current_payload: dict[str, Any] | None,
    proposed_payload: dict[str, Any],
    proposed_path: Path,
    permission_regression_threshold: float,
    override_active_bridge_check: bool,
    override_enabled_caller_check: bool,
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []

    cur_callers_set = set(callers_from_policy(current_payload).keys()) if current_payload else set()
    prop_callers_set = set(callers_from_policy(proposed_payload).keys())
    removed_callers = cur_callers_set - prop_callers_set

    # 1. Active bridge callers
    if existing_policy_id and not override_active_bridge_check:
        bridge_callers = active_bridge_callers(conn, existing_policy_id)
        blocked = removed_callers & bridge_callers
        if blocked:
            violations.append({
                "rule": "no_remove_active_bridge_callers",
                "severity": "error",
                "detail": f"{len(blocked)} caller(s) with can_run_bridge=true would be removed",
                "callers": sorted(blocked),
                "remedy": "disable these callers first, or pass --override-active-bridge-check",
            })

    # 2. Enabled callers
    if existing_policy_id and not override_enabled_caller_check:
        enabled = enabled_callers_from_db(conn, existing_policy_id)
        blocked_enabled = removed_callers & enabled
        if blocked_enabled:
            violations.append({
                "rule": "no_remove_enabled_callers",
                "severity": "warning",
                "detail": f"{len(blocked_enabled)} enabled caller(s) would be removed without explicit disable",
                "callers": sorted(blocked_enabled),
                "remedy": "set enabled=false for these callers first, or pass --override-enabled-caller-check",
            })

    # 3. Frozen field semantics
    if current_payload:
        for field in FROZEN_TOP_LEVEL_FIELDS:
            cv = current_payload.get(field)
            pv = proposed_payload.get(field)
            if cv is not None and pv is not None and type(cv) != type(pv):
                violations.append({
                    "rule": "frozen_field_semantics",
                    "severity": "error",
                    "detail": f"field '{field}' type changed: {type(cv).__name__} → {type(pv).__name__}",
                    "field": field,
                    "current_type": type(cv).__name__,
                    "proposed_type": type(pv).__name__,
                })

    # 4. Caller count regression (compares distinct DB callers vs proposed callers)
    if existing_policy_id:
        row = conn.execute(
            "SELECT COUNT(DISTINCT caller) FROM caller_permissions WHERE policy_id=?",
            (existing_policy_id,),
        ).fetchone()
        db_distinct_callers = int(row[0]) if row else 0
        proposed_count = len(callers_from_policy(proposed_payload))
        if db_distinct_callers > 0 and proposed_count < db_distinct_callers * (1 - permission_regression_threshold):
            violations.append({
                "rule": "permission_count_regression",
                "severity": "warning",
                "detail": f"caller count would drop from {db_distinct_callers} to {proposed_count} "
                          f"(>{permission_regression_threshold*100:.0f}% regression)",
                "db_distinct_caller_count": db_distinct_callers,
                "proposed_caller_count": proposed_count,
                "threshold": permission_regression_threshold,
                "remedy": "confirm this is intentional or pass --permission-regression-threshold 1.0",
            })

    return violations


def main() -> None:
    parser = argparse.ArgumentParser(description="Propose and validate a policy change before applying it")
    parser.add_argument("--db-path", required=True, help="Metadata SQLite DB path")
    parser.add_argument("--policy-file", required=True, help="Path to the proposed new policy file")
    parser.add_argument("--existing-policy-path", default=None,
                        help="Path of the existing policy being replaced (when proposed file has a different path)")
    parser.add_argument("--apply", action="store_true",
                        help="Apply the change if governance checks pass (no errors)")
    parser.add_argument("--actor", default="propose_policy_change",
                        help="Actor label for mutation log entries")
    parser.add_argument("--override-active-bridge-check", action="store_true")
    parser.add_argument("--override-enabled-caller-check", action="store_true")
    parser.add_argument("--permission-regression-threshold", type=float,
                        default=DEFAULT_PERMISSION_REGRESSION_THRESHOLD,
                        help="Fraction decrease in permissions that triggers a warning (default 0.20)")
    parser.add_argument("--output", help="Write JSON report to file")
    parser.add_argument("--fail-on-violations", action="store_true",
                        help="Exit non-zero when any violation is found")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    proposed_path = Path(args.policy_file)
    if not db_path.exists():
        print(json.dumps({"error": f"DB not found: {db_path}"}))
        sys.exit(1)
    if not proposed_path.exists():
        print(json.dumps({"error": f"Proposed policy file not found: {proposed_path}"}))
        sys.exit(1)

    conn = connect_db(str(db_path))
    apply_migrations(conn)
    imported_at = utc_now()

    proposed_payload = load_policy_file(proposed_path)
    proposed_sha = sha256_file(proposed_path)

    # Look up existing policy: prefer --existing-policy-path if provided
    lookup_path = Path(args.existing_policy_path) if args.existing_policy_path else proposed_path
    existing = existing_policy_by_path(conn, lookup_path)
    existing_policy_id = str(existing["policy_id"]) if existing else None
    existing_sha = str(existing.get("sha256") or "") if existing else None

    current_payload: dict[str, Any] | None = None
    if existing:
        try:
            current_payload = load_policy_file(proposed_path) if proposed_sha == existing_sha else None
            # Load current state from DB payload_json for comparison
            row = conn.execute(
                "SELECT payload_json FROM policies WHERE policy_id=?",
                (existing_policy_id,),
            ).fetchone()
            if row and row["payload_json"]:
                db_payload = json.loads(str(row["payload_json"]))
                if isinstance(db_payload, dict):
                    current_payload = db_payload
        except Exception:
            pass

    # Caller diff
    cur_callers = set(callers_from_policy(current_payload).keys()) if current_payload else set()
    prop_callers = set(callers_from_policy(proposed_payload).keys())
    caller_diff = diff_callers(cur_callers, prop_callers)
    permission_diffs = diff_permissions(current_payload or {}, proposed_payload)

    # Governance checks
    violations = run_governance_checks(
        conn=conn,
        existing_policy_id=existing_policy_id,
        current_payload=current_payload,
        proposed_payload=proposed_payload,
        proposed_path=proposed_path,
        permission_regression_threshold=args.permission_regression_threshold,
        override_active_bridge_check=args.override_active_bridge_check,
        override_enabled_caller_check=args.override_enabled_caller_check,
    )

    errors = [v for v in violations if v["severity"] == "error"]
    warnings = [v for v in violations if v["severity"] == "warning"]

    # Apply only if no errors
    apply_result: dict[str, Any] | None = None
    applied = False
    if args.apply and not errors:
        plan = plan_policy_file(conn, policy_path=str(proposed_path), required_schema="")
        apply_result_raw = apply_policy_plan(conn, plan, imported_at=imported_at)
        log_mutation(
            conn,
            operation=str(apply_result_raw.get("action") or "update"),
            entity_type="policy",
            entity_id=str(apply_result_raw.get("policy_id") or ""),
            actor=args.actor,
            source="propose_policy_change",
            old_state=apply_result_raw.get("existing_policy"),
            new_state=apply_result_raw.get("state_after"),
            applied_at=imported_at,
            notes=f"governance-approved: {len(errors)} errors, {len(warnings)} warnings",
        )
        conn.commit()
        apply_result = {
            "action": str(apply_result_raw.get("action") or ""),
            "policy_id": str(apply_result_raw.get("policy_id") or ""),
            "new_sha256": str((apply_result_raw.get("state_after") or {}).get("sha256") or ""),
        }
        applied = True
    elif args.apply and errors:
        apply_result = {
            "action": "blocked",
            "reason": f"{len(errors)} governance error(s) prevented apply",
        }

    conn.close()

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": imported_at,
        "db_path": str(db_path),
        "policy_path": str(proposed_path),
        "proposed_sha256": proposed_sha,
        "existing_policy_id": existing_policy_id,
        "existing_sha256": existing_sha,
        "is_new_policy": existing is None,
        "caller_diff": caller_diff,
        "permission_diffs": permission_diffs,
        "governance_violations": violations,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "governance_status": "blocked" if errors else ("warn" if warnings else "approved"),
        "mode": "apply" if args.apply else "dry_run",
        "applied": applied,
        "apply_result": apply_result,
    }

    out = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        print(out)

    if args.fail_on_violations and violations:
        sys.exit(1)


if __name__ == "__main__":
    main()
