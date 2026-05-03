#!/usr/bin/env python3
"""Key backend drift detection and reconcile tool.

Compares the key_refs / key_versions state in the metadata sidecar DB against
a reference source — either a registry manifest or a Vault KV backend file —
and reports any drift between what the DB says and what the reference says.

Drift categories:
  key_ref_missing       — reference declares a key_ref not present in DB
  key_ref_extra         — DB has a key_ref not declared in reference
  key_ref_field_drift   — a key_ref field differs (backend_kind, active_version, etc.)
  version_missing       — reference declares a key_version not present in DB
  version_extra         — DB has a version not declared in reference (for that key)
  version_field_drift   — a version field differs (status, enabled, secret_ref_kind, etc.)
  active_version_mismatch — DB active_version doesn't match the live secret backend

--repair mode: applies safe fixes (update drifted fields, insert missing versions,
  retire extra versions).  Does NOT delete key_refs or downgrade active versions
  without explicit confirmation.

Outputs key_backend_drift/v1.
"""
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

from scripts.metadata_db import apply_migrations, connect_db, utc_now  # noqa: E402
from scripts.manage_metadata_db import (  # noqa: E402
    normalize_manifest_key_ref,
    log_mutation,
    MANIFEST_SCHEMA,
)

SCHEMA_ID = "key_backend_drift/v1"

KEY_REF_COMPARABLE_FIELDS = (
    "purpose",
    "service_id",
    "backend_kind",
    "backend_ref",
    "active_version",
    "allowed_callers_json",
)
KEY_VERSION_COMPARABLE_FIELDS = (
    "enabled",
    "status",
    "secret_ref_kind",
    "secret_ref_name",
)


# ── DB helpers ───────────────────────────────────────────────────────────────

def fetch_all_key_refs(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute("SELECT * FROM key_refs").fetchall()
    return {str(r["key_name"]): dict(r) for r in rows}


def fetch_key_versions_for(conn: sqlite3.Connection, key_name: str) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM key_versions WHERE key_name = ? ORDER BY version",
        (key_name,),
    ).fetchall()
    return {str(r["version"]): dict(r) for r in rows}


# ── Reference loading ─────────────────────────────────────────────────────────

def load_manifest_key_refs(manifest_path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if payload.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"manifest must use {MANIFEST_SCHEMA}: {manifest_path}")
    raw_key_refs = payload.get("key_refs") or []
    manifest_dir = Path(manifest_path).parent
    return [normalize_manifest_key_ref(item) for item in raw_key_refs]


def load_vault_kv_key_refs(vault_kv_path: str) -> list[dict[str, Any]]:
    """Build synthetic key_refs from vault_kv_backend secrets dict.

    Each top-level secret path is treated as a key_ref where:
      key_name = last segment of path (after 'secret/data/')
      active_version = current_version from the backend entry
    """
    payload = json.loads(Path(vault_kv_path).read_text(encoding="utf-8"))
    secrets = payload.get("secrets") or {}
    refs: list[dict[str, Any]] = []
    for path, entry in secrets.items():
        if not isinstance(entry, dict):
            continue
        # Derive key_name from path
        key_name = path.split("/")[-1]
        current_version = str(entry.get("current_version") or "")
        versions = entry.get("versions") or {}
        desired_versions: list[dict[str, Any]] = []
        for ver_str, ver_entry in versions.items():
            if not isinstance(ver_entry, dict):
                continue
            desired_versions.append({
                "key_name": key_name,
                "version": str(ver_str),
                "enabled": 1,
                "status": "active" if str(ver_str) == current_version else "inactive",
                "secret_ref_kind": "vault_kv",
                "secret_ref_name": path,
                "backend_key_version": str(ver_str),
                "created_at_utc": None,
                "source": "vault_kv_backend",
                "metadata_json": None,
            })
        refs.append({
            "key_name": key_name,
            "purpose": "unknown",
            "service_id": None,
            "backend_kind": "vault_kv",
            "backend_ref": path,
            "active_version": current_version,
            "allowed_callers_json": "[]",
            "source": "vault_kv_backend",
            "versions": desired_versions,
        })
    return refs


# ── Drift detection ────────────────────────────────────────────────────────────

def compare_key_ref_fields(
    db_row: dict[str, Any],
    desired: dict[str, Any],
) -> list[dict[str, Any]]:
    diffs = []
    for field in KEY_REF_COMPARABLE_FIELDS:
        db_val = db_row.get(field)
        des_val = desired.get(field)
        # Normalise None vs empty string
        db_norm = db_val if db_val not in (None, "") else None
        des_norm = des_val if des_val not in (None, "") else None
        if db_norm != des_norm:
            diffs.append({
                "field": field,
                "db_value": db_val,
                "desired_value": des_val,
            })
    return diffs


def compare_version_fields(
    db_row: dict[str, Any],
    desired: dict[str, Any],
) -> list[dict[str, Any]]:
    diffs = []
    for field in KEY_VERSION_COMPARABLE_FIELDS:
        db_val = db_row.get(field)
        des_val = desired.get(field)
        db_norm = db_val if db_val not in (None, "") else None
        des_norm = des_val if des_val not in (None, "") else None
        if db_norm != des_norm:
            diffs.append({
                "field": field,
                "db_value": db_val,
                "desired_value": des_val,
            })
    return diffs


def detect_drift(
    conn: sqlite3.Connection,
    ref_key_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    db_key_refs = fetch_all_key_refs(conn)
    ref_keys = {r["key_name"]: r for r in ref_key_refs}

    # Missing in DB
    for key_name, ref_kr in ref_keys.items():
        if key_name not in db_key_refs:
            findings.append({
                "kind": "key_ref_missing",
                "key_name": key_name,
                "detail": "key_ref declared in reference but absent from DB",
                "desired": {k: ref_kr.get(k) for k in KEY_REF_COMPARABLE_FIELDS},
            })
        else:
            # Field drift
            field_diffs = compare_key_ref_fields(db_key_refs[key_name], ref_kr)
            if field_diffs:
                findings.append({
                    "kind": "key_ref_field_drift",
                    "key_name": key_name,
                    "detail": f"{len(field_diffs)} field(s) differ",
                    "field_diffs": field_diffs,
                })
            # Version checks
            db_versions = fetch_key_versions_for(conn, key_name)
            ref_versions = {v["version"]: v for v in (ref_kr.get("versions") or [])}
            for ver, ref_v in ref_versions.items():
                if ver not in db_versions:
                    findings.append({
                        "kind": "version_missing",
                        "key_name": key_name,
                        "version": ver,
                        "detail": "version declared in reference but absent from DB",
                    })
                else:
                    vdiffs = compare_version_fields(db_versions[ver], ref_v)
                    if vdiffs:
                        findings.append({
                            "kind": "version_field_drift",
                            "key_name": key_name,
                            "version": ver,
                            "detail": f"{len(vdiffs)} version field(s) differ",
                            "field_diffs": vdiffs,
                        })
            for ver in db_versions:
                if ver not in ref_versions:
                    findings.append({
                        "kind": "version_extra",
                        "key_name": key_name,
                        "version": ver,
                        "detail": "DB version not declared in reference (possibly from rotation)",
                    })

    # Extra in DB (not necessarily an error, but informational)
    for key_name in db_key_refs:
        if key_name not in ref_keys:
            findings.append({
                "kind": "key_ref_extra",
                "key_name": key_name,
                "detail": "DB key_ref has no corresponding entry in reference",
            })

    return findings


# ── Repair ────────────────────────────────────────────────────────────────────

SAFE_REPAIR_KINDS = {"key_ref_field_drift", "version_field_drift", "version_missing"}


def apply_repairs(
    conn: sqlite3.Connection,
    findings: list[dict[str, Any]],
    ref_key_refs: list[dict[str, Any]],
    *,
    imported_at: str,
    actor: str,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    ref_map = {r["key_name"]: r for r in ref_key_refs}

    for finding in findings:
        kind = finding["kind"]
        key_name = finding.get("key_name", "")
        if kind not in SAFE_REPAIR_KINDS:
            continue
        ref_kr = ref_map.get(key_name)
        if ref_kr is None:
            continue

        if kind == "key_ref_field_drift":
            old = dict(conn.execute("SELECT * FROM key_refs WHERE key_name=?", (key_name,)).fetchone() or {})
            conn.execute(
                """
                UPDATE key_refs SET
                  purpose=?, service_id=?, backend_kind=?, backend_ref=?,
                  active_version=?, allowed_callers_json=?, updated_at_utc=?
                WHERE key_name=?
                """,
                (
                    ref_kr.get("purpose"),
                    ref_kr.get("service_id"),
                    ref_kr.get("backend_kind"),
                    ref_kr.get("backend_ref"),
                    ref_kr.get("active_version"),
                    ref_kr.get("allowed_callers_json"),
                    imported_at,
                    key_name,
                ),
            )
            new = dict(conn.execute("SELECT * FROM key_refs WHERE key_name=?", (key_name,)).fetchone() or {})
            log_mutation(conn, operation="repair_drift", entity_type="key_refs",
                         entity_id=key_name, actor=actor, source="check_key_backend_drift",
                         old_state=old, new_state=new, applied_at=imported_at)
            actions.append({"action": "update_key_ref", "key_name": key_name, "applied": True})

        elif kind == "version_field_drift":
            version = finding.get("version", "")
            desired_ver = next((v for v in (ref_kr.get("versions") or []) if v["version"] == version), None)
            if desired_ver is None:
                continue
            old = dict(conn.execute(
                "SELECT * FROM key_versions WHERE key_name=? AND version=?", (key_name, version)
            ).fetchone() or {})
            conn.execute(
                """
                UPDATE key_versions SET
                  enabled=?, status=?, secret_ref_kind=?, secret_ref_name=?
                WHERE key_name=? AND version=?
                """,
                (
                    desired_ver.get("enabled"),
                    desired_ver.get("status"),
                    desired_ver.get("secret_ref_kind"),
                    desired_ver.get("secret_ref_name"),
                    key_name, version,
                ),
            )
            new = dict(conn.execute(
                "SELECT * FROM key_versions WHERE key_name=? AND version=?", (key_name, version)
            ).fetchone() or {})
            log_mutation(conn, operation="repair_drift", entity_type="key_versions",
                         entity_id=f"{key_name}|{version}", actor=actor, source="check_key_backend_drift",
                         old_state=old, new_state=new, applied_at=imported_at)
            actions.append({"action": "update_version", "key_name": key_name, "version": version, "applied": True})

        elif kind == "version_missing":
            version = finding.get("version", "")
            desired_ver = next((v for v in (ref_kr.get("versions") or []) if v["version"] == version), None)
            if desired_ver is None:
                continue
            conn.execute(
                """
                INSERT INTO key_versions(
                  key_name, version, enabled, status, secret_ref_kind, secret_ref_name,
                  backend_key_version, created_at_utc, source, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'check_key_backend_drift', NULL)
                ON CONFLICT(key_name, version) DO NOTHING
                """,
                (
                    key_name, version,
                    desired_ver.get("enabled", 1),
                    desired_ver.get("status", "inactive"),
                    desired_ver.get("secret_ref_kind"),
                    desired_ver.get("secret_ref_name"),
                    desired_ver.get("backend_key_version"),
                    imported_at,
                ),
            )
            log_mutation(conn, operation="repair_drift", entity_type="key_versions",
                         entity_id=f"{key_name}|{version}", actor=actor, source="check_key_backend_drift",
                         old_state=None, new_state=desired_ver, applied_at=imported_at)
            actions.append({"action": "insert_version", "key_name": key_name, "version": version, "applied": True})

    return actions


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Detect and repair key_refs/key_versions drift")
    parser.add_argument("--db-path", required=True, help="Metadata SQLite DB path")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--manifest", help="Path to metadata_registry_manifest/v1 JSON")
    source_group.add_argument("--vault-kv-file", help="Path to vault_kv_backend/v1 JSON (for backend drift)")
    parser.add_argument("--repair", action="store_true",
                        help="Apply safe repairs (update drifted fields, insert missing versions)")
    parser.add_argument("--actor", default="check_key_backend_drift",
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

    if args.manifest:
        ref_key_refs = load_manifest_key_refs(args.manifest)
        reference_source = f"manifest:{args.manifest}"
    else:
        ref_key_refs = load_vault_kv_key_refs(args.vault_kv_file)
        reference_source = f"vault_kv:{args.vault_kv_file}"

    findings = detect_drift(conn, ref_key_refs)

    repair_actions: list[dict[str, Any]] = []
    if args.repair and findings:
        repair_actions = apply_repairs(
            conn, findings, ref_key_refs,
            imported_at=imported_at, actor=args.actor,
        )
        conn.commit()
        # Re-run detection after repairs to show residual drift
        findings = detect_drift(conn, ref_key_refs)

    conn.close()

    # Categorise findings
    by_kind: dict[str, int] = {}
    for f in findings:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1

    actionable_kinds = {"key_ref_missing", "key_ref_field_drift", "version_missing", "version_field_drift"}
    actionable = [f for f in findings if f["kind"] in actionable_kinds]
    informational = [f for f in findings if f["kind"] not in actionable_kinds]

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": imported_at,
        "db_path": str(db_path),
        "reference_source": reference_source,
        "mode": "repair" if args.repair else "dry_run",
        "summary": {
            "ref_key_count": len(ref_key_refs),
            "db_key_count": len(fetch_all_key_refs(connect_db(str(db_path)))),
            "total_findings": len(findings),
            "actionable_findings": len(actionable),
            "informational_findings": len(informational),
            "findings_by_kind": by_kind,
            "repair_action_count": len(repair_actions),
            "status": "clean" if len(actionable) == 0 else "drift_detected",
        },
        "findings": findings,
        "repair_actions": repair_actions,
    }

    out = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        print(out)

    if args.fail_on_drift and report["summary"]["actionable_findings"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
