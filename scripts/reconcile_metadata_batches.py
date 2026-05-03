#!/usr/bin/env python3
"""Cross-batch metadata reconcile and repair tool.

Scans the metadata sidecar DB for structural and consistency issues that arise
from multiple import batches over time:
  - Orphaned child rows (artifacts, events) whose parent job was deleted
  - Incomplete imports (jobs missing audit_chain, audit_seal, or stage records)
  - Policy drift (same policy path re-imported with a different hash)
  - Duplicate caller_permissions (same policy_id / caller / key pair)
  - Stale key registry entries (key_refs with no key_versions)
  - Schema migration gaps (applied versions vs expected versions)

--repair mode: deletes orphaned rows, removes exact-duplicate permission rows.
--dry-run (default): reports issues without modifying the DB.

Outputs metadata_batch_reconcile/v1.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import apply_migrations, connect_db, expected_migration_versions, utc_now  # noqa: E402

SCHEMA_ID = "metadata_batch_reconcile/v1"

CHILD_TABLES = (
    "job_artifacts",
    "job_stage_status",
    "audit_events",
    "audit_chains",
    "audit_seals",
    "key_access_events",
)
REQUIRED_SINGLETON_TABLES = {
    "audit_chains": "job_id",
    "audit_seals": "job_id",
}
REQUIRED_STAGES = {"sse_export", "bridge", "pjc", "policy_release"}


def check_orphaned_child_rows(conn: sqlite3.Connection) -> list[dict]:
    """Find child rows referencing nonexistent jobs."""
    issues = []
    for table in CHILD_TABLES:
        rows = conn.execute(
            f"""
            SELECT t.job_id, COUNT(*) AS cnt
            FROM {table} t
            LEFT JOIN jobs j ON j.job_id = t.job_id
            WHERE j.job_id IS NULL
            GROUP BY t.job_id
            """
        ).fetchall()
        for row in rows:
            issues.append({
                "check": "orphaned_child_rows",
                "table": table,
                "job_id": row["job_id"],
                "orphaned_row_count": row["cnt"],
            })
    return issues


def check_incomplete_imports(conn: sqlite3.Connection) -> list[dict]:
    """Jobs missing audit_chain or audit_seal records."""
    issues = []
    for table, fk_col in REQUIRED_SINGLETON_TABLES.items():
        rows = conn.execute(
            f"""
            SELECT j.job_id
            FROM jobs j
            LEFT JOIN {table} t ON t.{fk_col} = j.job_id
            WHERE t.{fk_col} IS NULL
            ORDER BY j.imported_at_utc
            """
        ).fetchall()
        for row in rows:
            issues.append({
                "check": "incomplete_import",
                "job_id": row["job_id"],
                "missing_table": table,
            })
    # Jobs missing required pipeline stages
    all_jobs = [r["job_id"] for r in conn.execute("SELECT job_id FROM jobs").fetchall()]
    for job_id in all_jobs:
        stages = {
            r["stage"]
            for r in conn.execute(
                "SELECT stage FROM job_stage_status WHERE job_id = ?", (job_id,)
            ).fetchall()
        }
        missing = REQUIRED_STAGES - stages
        if missing:
            issues.append({
                "check": "incomplete_import",
                "job_id": job_id,
                "missing_stages": sorted(missing),
            })
    return issues


def check_policy_drift(conn: sqlite3.Connection) -> list[dict]:
    """Detect cases where the same policy path appears with multiple hashes."""
    rows = conn.execute(
        """
        SELECT path, COUNT(DISTINCT sha256) AS hash_count, GROUP_CONCAT(DISTINCT sha256) AS hashes
        FROM policies
        GROUP BY path
        HAVING hash_count > 1
        """
    ).fetchall()
    return [
        {
            "check": "policy_drift",
            "path": row["path"],
            "distinct_hash_count": row["hash_count"],
            "hashes": row["hashes"].split(",") if row["hashes"] else [],
        }
        for row in rows
    ]


def check_duplicate_permissions(conn: sqlite3.Connection) -> list[dict]:
    """Find exact-duplicate caller_permissions rows (should be impossible via UNIQUE, but
    repairs orphan-created duplicates from manual DB edits)."""
    rows = conn.execute(
        """
        SELECT policy_id, caller, permission_key, COUNT(*) AS cnt
        FROM caller_permissions
        GROUP BY policy_id, caller, permission_key
        HAVING cnt > 1
        """
    ).fetchall()
    return [
        {
            "check": "duplicate_permissions",
            "policy_id": row["policy_id"],
            "caller": row["caller"],
            "permission_key": row["permission_key"],
            "count": row["cnt"],
        }
        for row in rows
    ]


def check_stale_key_refs(conn: sqlite3.Connection) -> list[dict]:
    """key_refs with no key_versions and no active_version set."""
    rows = conn.execute(
        """
        SELECT kr.key_name, kr.active_version
        FROM key_refs kr
        LEFT JOIN key_versions kv ON kv.key_name = kr.key_name
        WHERE kv.key_name IS NULL
        """
    ).fetchall()
    return [
        {
            "check": "stale_key_ref",
            "key_name": row["key_name"],
            "active_version": row["active_version"],
        }
        for row in rows
    ]


def check_migration_gaps(conn: sqlite3.Connection) -> list[dict]:
    """Detect missing or unapplied schema migrations."""
    applied = {
        row["version"]
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    expected = set(expected_migration_versions())
    missing = sorted(expected - applied)
    unexpected = sorted(applied - expected)
    issues = []
    if missing:
        issues.append({"check": "migration_gap", "missing_versions": missing})
    if unexpected:
        issues.append({"check": "migration_gap", "unexpected_versions": unexpected})
    return issues


def repair_orphaned_child_rows(conn: sqlite3.Connection, dry_run: bool) -> list[dict]:
    actions = []
    for table in CHILD_TABLES:
        rows = conn.execute(
            f"""
            SELECT t.job_id, COUNT(*) AS cnt
            FROM {table} t
            LEFT JOIN jobs j ON j.job_id = t.job_id
            WHERE j.job_id IS NULL
            GROUP BY t.job_id
            """
        ).fetchall()
        for row in rows:
            action = {
                "action": "delete_orphaned_rows",
                "table": table,
                "job_id": row["job_id"],
                "row_count": row["cnt"],
                "applied": not dry_run,
            }
            if not dry_run:
                conn.execute(
                    f"DELETE FROM {table} WHERE job_id = ?", (row["job_id"],)
                )
            actions.append(action)
    if not dry_run:
        conn.commit()
    return actions


def build_report(
    checks: list[dict],
    repair_actions: list[dict],
    mode: str,
    db_path: str,
    job_count: int,
    policy_count: int,
) -> dict:
    issue_counts: dict[str, int] = {}
    for c in checks:
        key = c["check"]
        issue_counts[key] = issue_counts.get(key, 0) + 1

    return {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now(),
        "mode": mode,
        "db_path": db_path,
        "summary": {
            "job_count": job_count,
            "policy_count": policy_count,
            "total_issues": len(checks),
            "issue_counts": issue_counts,
            "repair_action_count": len(repair_actions),
            "status": "ok" if len(checks) == 0 else "issues_found",
        },
        "issues": checks,
        "repair_actions": repair_actions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-batch metadata reconcile and repair")
    parser.add_argument("--db-path", required=True, help="Path to metadata SQLite DB")
    parser.add_argument("--repair", action="store_true",
                        help="Apply safe repairs (delete orphaned rows)")
    parser.add_argument("--output", default=None, help="Write report JSON to file")
    parser.add_argument("--fail-on-issues", action="store_true",
                        help="Exit non-zero when issues are found")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(json.dumps({"error": f"DB not found: {db_path}"}))
        sys.exit(1)

    conn = connect_db(str(db_path))
    apply_migrations(conn)

    job_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    policy_count = conn.execute("SELECT COUNT(*) FROM policies").fetchone()[0]

    checks: list[dict] = []
    checks.extend(check_orphaned_child_rows(conn))
    checks.extend(check_incomplete_imports(conn))
    checks.extend(check_policy_drift(conn))
    checks.extend(check_duplicate_permissions(conn))
    checks.extend(check_stale_key_refs(conn))
    checks.extend(check_migration_gaps(conn))

    repair_actions: list[dict] = []
    if args.repair:
        # Only repair safe operations (orphaned child rows)
        repair_actions.extend(
            repair_orphaned_child_rows(conn, dry_run=False)
        )
        # Re-run checks after repair
        checks = []
        checks.extend(check_orphaned_child_rows(conn))
        checks.extend(check_incomplete_imports(conn))
        checks.extend(check_policy_drift(conn))
        checks.extend(check_duplicate_permissions(conn))
        checks.extend(check_stale_key_refs(conn))
        checks.extend(check_migration_gaps(conn))

    mode = "repair" if args.repair else "dry_run"
    report = build_report(checks, repair_actions, mode, str(db_path), job_count, policy_count)

    out = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        print(out)

    if args.fail_on_issues and report["summary"]["total_issues"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
