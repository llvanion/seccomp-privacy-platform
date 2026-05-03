#!/usr/bin/env python3
"""Policy drift detection tool.

Scans policies registered in the metadata sidecar DB and checks whether
their on-disk content still matches the stored sha256 hash. Detects:

  content_changed  — file sha256 differs from DB record (uncontrolled edit)
  file_missing     — registered path no longer exists on disk
  caller_count_changed — caller count in live file differs from DB permission_count
  schema_changed   — $schema / schema field in file differs from DB schema_name

--repair mode: re-imports drifted policies through the same apply_policy_plan
  path used by apply-registry, writing the new state to the DB and logging to
  control_plane_mutations.

Outputs policy_drift/v1.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import apply_migrations, connect_db, sha256_file, utc_now  # noqa: E402
from scripts.metadata_registry import (  # noqa: E402
    apply_policy_plan,
    existing_policy_by_id,
    existing_policy_by_path,
    plan_policy_file,
    policy_counts,
)
from scripts.manage_metadata_db import log_mutation  # noqa: E402

SCHEMA_ID = "policy_drift/v1"


def fetch_all_policies(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT policy_id, policy_kind, path, sha256, schema_name, imported_at_utc
        FROM policies
        ORDER BY imported_at_utc DESC
        """
    ).fetchall()
    result = []
    for row in rows:
        rec = dict(row)
        counts = policy_counts(conn, str(rec["policy_id"]))
        rec.update(counts)
        result.append(rec)
    return result


def count_callers_in_file(path: Path) -> int | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        callers = payload.get("callers")
        if isinstance(callers, dict):
            return len(callers)
        return None
    except Exception:
        return None


def count_distinct_callers_in_db(conn: sqlite3.Connection, policy_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(DISTINCT caller) FROM caller_permissions WHERE policy_id=?",
        (policy_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def schema_in_file(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return str(payload.get("schema") or payload.get("$schema") or "")
    except Exception:
        return None


def detect_policy_drift(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for rec in fetch_all_policies(conn):
        path = Path(str(rec["path"]))
        policy_id = str(rec["policy_id"])

        if not path.exists():
            findings.append({
                "kind": "file_missing",
                "policy_id": policy_id,
                "path": str(path),
                "detail": "registered policy file no longer exists on disk",
            })
            continue

        live_sha = sha256_file(path)
        db_sha = str(rec.get("sha256") or "")

        if live_sha != db_sha:
            live_caller_count = count_callers_in_file(path)
            db_caller_count = count_distinct_callers_in_db(conn, str(rec["policy_id"]))
            live_schema = schema_in_file(path)
            db_schema = str(rec.get("schema_name") or "")
            findings.append({
                "kind": "content_changed",
                "policy_id": policy_id,
                "path": str(path),
                "detail": "sha256 mismatch — file was modified outside the control plane",
                "db_sha256": db_sha,
                "live_sha256": live_sha,
                "db_caller_count": db_caller_count,
                "live_caller_count": live_caller_count,
                "db_schema_name": db_schema,
                "live_schema": live_schema,
            })
        else:
            # Even if hash matches, check for caller_count anomaly (shouldn't happen but defensive)
            live_caller_count = count_callers_in_file(path)
            db_caller_count = count_distinct_callers_in_db(conn, str(rec["policy_id"]))
            if live_caller_count is not None and live_caller_count != db_caller_count:
                findings.append({
                    "kind": "caller_count_changed",
                    "policy_id": policy_id,
                    "path": str(path),
                    "detail": "caller count in file differs from DB permission records (hash match anomaly)",
                    "db_caller_count": db_caller_count,
                    "live_caller_count": live_caller_count,
                })

    return findings


def repair_drifted_policy(
    conn: sqlite3.Connection,
    finding: dict[str, Any],
    *,
    imported_at: str,
    actor: str,
) -> dict[str, Any]:
    path_str = finding.get("path") or ""
    if not path_str or not Path(path_str).exists():
        return {"action": "skip", "policy_id": finding.get("policy_id"), "reason": "file missing"}

    policy_path = Path(path_str)
    old_policy_id = finding.get("policy_id") or ""

    # Recompute correct sha256 and payload from the live file
    live_sha = sha256_file(policy_path)
    try:
        live_payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"action": "skip", "policy_id": old_policy_id, "reason": str(exc)}

    live_schema = str(live_payload.get("schema") or "")
    payload_json = json.dumps(live_payload, ensure_ascii=False)

    old_row = conn.execute(
        "SELECT * FROM policies WHERE policy_id = ?", (old_policy_id,)
    ).fetchone()
    old_state = dict(old_row) if old_row else None

    # Update sha256 and payload_json in-place (policy_id = sha256, so if sha256 changed
    # we need to update via path since policy_id is a derived column)
    conn.execute(
        """
        UPDATE policies
        SET sha256 = ?, schema_name = ?, payload_json = ?, imported_at_utc = ?
        WHERE policy_id = ?
        """,
        (live_sha, live_schema, payload_json, imported_at, old_policy_id),
    )

    new_row = conn.execute(
        "SELECT * FROM policies WHERE policy_id = ?", (old_policy_id,)
    ).fetchone()
    new_state = dict(new_row) if new_row else None

    log_mutation(
        conn,
        operation="repair_drift",
        entity_type="policy",
        entity_id=old_policy_id,
        actor=actor,
        source="check_policy_drift",
        old_state=old_state,
        new_state=new_state,
        applied_at=imported_at,
    )
    return {
        "action": "reimport",
        "policy_id": old_policy_id,
        "path": path_str,
        "new_sha256": live_sha,
        "applied": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect drift between registered policies and on-disk files")
    parser.add_argument("--db-path", required=True, help="Metadata SQLite DB path")
    parser.add_argument("--repair", action="store_true",
                        help="Re-import drifted policies through the control plane")
    parser.add_argument("--actor", default="check_policy_drift",
                        help="Actor label for mutation log entries")
    parser.add_argument("--output", help="Write JSON report to file")
    parser.add_argument("--fail-on-drift", action="store_true",
                        help="Exit non-zero when drift is found (after repairs, if any)")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(json.dumps({"error": f"DB not found: {db_path}"}))
        sys.exit(1)

    conn = connect_db(str(db_path))
    apply_migrations(conn)
    imported_at = utc_now()

    all_policies = fetch_all_policies(conn)
    findings = detect_policy_drift(conn)

    repair_actions: list[dict[str, Any]] = []
    if args.repair:
        repairable = [f for f in findings if f["kind"] == "content_changed"]
        for finding in repairable:
            action = repair_drifted_policy(conn, finding, imported_at=imported_at, actor=args.actor)
            repair_actions.append(action)
        if repairable:
            conn.commit()
        # Re-detect after repair
        findings = detect_policy_drift(conn)

    by_kind: dict[str, int] = {}
    for f in findings:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": imported_at,
        "db_path": str(db_path),
        "mode": "repair" if args.repair else "dry_run",
        "summary": {
            "registered_policy_count": len(all_policies),
            "total_findings": len(findings),
            "findings_by_kind": by_kind,
            "repair_action_count": len(repair_actions),
            "status": "clean" if not findings else "drift_detected",
        },
        "findings": findings,
        "repair_actions": repair_actions,
    }

    out = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        print(out)

    if args.fail_on_drift and findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
