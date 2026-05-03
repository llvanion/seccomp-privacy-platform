#!/usr/bin/env python3
"""Issuer credential rotation governance tool.

Rotates service-account tokens / keys associated with entries in the
issuer_registry. On each rotation:
  1. Validates the issuer exists and is enabled in the DB.
  2. Looks up the key_ref (if any) bound to the issuer's service_id.
  3. Generates a new active_version tag and writes it into key_versions.
  4. Logs the rotation in control_plane_mutations.
  5. Optionally updates the vault_kv_backend mock file to reflect the new version.

--dry-run mode performs all checks and plans without writing to the DB or mock.

Outputs issuer_credential_rotation/v1.
"""
import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import apply_migrations, connect_db, utc_now  # noqa: E402

SCHEMA_ID = "issuer_credential_rotation/v1"


def fetch_issuer(conn, issuer: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM issuer_registry WHERE issuer = ?", (issuer,)
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def fetch_key_refs_for_service(conn, service_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM key_refs WHERE service_id = ? ORDER BY key_name", (service_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_active_key_version(conn, key_name: str, version: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM key_versions WHERE key_name = ? AND version = ?",
        (key_name, version),
    ).fetchone()
    return dict(row) if row else None


def next_rotation_version(current_version: str) -> str:
    """Increment a version string: demo-v1 → demo-v2, v3 → v4, 1 → 2."""
    parts = current_version.rsplit("-v", 1)
    if len(parts) == 2:
        try:
            return f"{parts[0]}-v{int(parts[1]) + 1}"
        except ValueError:
            pass
    # Try plain integer
    try:
        return str(int(current_version) + 1)
    except ValueError:
        pass
    # Fallback: append rotation suffix
    return f"{current_version}-rotated"


def rotate_key_in_db(
    conn,
    *,
    key_name: str,
    old_version: str,
    new_version: str,
    imported_at: str,
    secret_ref_kind: str | None,
    secret_ref_name: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    old_state = fetch_active_key_version(conn, key_name, old_version)
    if not dry_run:
        # Insert new version
        conn.execute(
            """
            INSERT INTO key_versions(
              key_name, version, enabled, status, secret_ref_kind, secret_ref_name,
              backend_key_version, created_at_utc, source, metadata_json
            ) VALUES (?, ?, 1, 'active', ?, ?, NULL, ?, 'rotate_issuer_credentials', NULL)
            ON CONFLICT(key_name, version) DO UPDATE SET
              enabled=1, status='active',
              secret_ref_kind=excluded.secret_ref_kind,
              secret_ref_name=excluded.secret_ref_name,
              created_at_utc=excluded.created_at_utc,
              source=excluded.source
            """,
            (key_name, new_version, secret_ref_kind, secret_ref_name, imported_at),
        )
        # Retire old version
        conn.execute(
            "UPDATE key_versions SET status='retired', enabled=0 WHERE key_name=? AND version=?",
            (key_name, old_version),
        )
        # Update key_refs.active_version
        conn.execute(
            "UPDATE key_refs SET active_version=?, updated_at_utc=? WHERE key_name=?",
            (new_version, imported_at, key_name),
        )
    new_state = None if dry_run else fetch_active_key_version(conn, key_name, new_version)
    return {
        "key_name": key_name,
        "old_version": old_version,
        "new_version": new_version,
        "old_state": old_state,
        "new_state": new_state,
        "applied": not dry_run,
    }


def log_rotation_mutation(
    conn,
    *,
    issuer: str,
    key_name: str | None,
    old_version: str | None,
    new_version: str | None,
    applied_at: str,
    actor: str = "rotate_issuer_credentials",
) -> None:
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
        ) VALUES (?, 'rotate', 'issuer_credential', ?, ?, 'rotate_issuer_credentials',
                  ?, ?, 'applied', ?, ?)
        """,
        (
            str(uuid.uuid4()),
            issuer,
            actor,
            json.dumps({"key_name": key_name, "version": old_version}, ensure_ascii=False),
            json.dumps({"key_name": key_name, "version": new_version}, ensure_ascii=False),
            applied_at,
            f"key rotation: {old_version} → {new_version}" if key_name else "issuer credential rotation",
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotate credentials for an issuer_registry entry")
    parser.add_argument("--db-path", required=True, help="Metadata SQLite DB path")
    parser.add_argument("--issuer", required=True, help="Issuer value to rotate credentials for")
    parser.add_argument("--actor", default="rotate_issuer_credentials",
                        help="Actor name for mutation log")
    parser.add_argument("--dry-run", action="store_true", help="Plan without writing")
    parser.add_argument("--output", help="Write report JSON to file")
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(json.dumps({"error": f"DB not found: {db_path}"}))
        sys.exit(1)

    conn = connect_db(str(db_path))
    apply_migrations(conn)
    imported_at = utc_now()

    issuer_rec = fetch_issuer(conn, args.issuer)
    if issuer_rec is None:
        result = {
            "schema": SCHEMA_ID,
            "generated_at_utc": imported_at,
            "issuer": args.issuer,
            "mode": "dry_run" if args.dry_run else "apply",
            "ok": False,
            "error": f"issuer not found in issuer_registry: {args.issuer}",
            "key_rotations": [],
        }
        out = json.dumps(result, indent=2)
        print(out)
        if args.fail_on_error:
            sys.exit(1)
        return

    if not int(issuer_rec.get("enabled") or 0):
        result = {
            "schema": SCHEMA_ID,
            "generated_at_utc": imported_at,
            "issuer": args.issuer,
            "mode": "dry_run" if args.dry_run else "apply",
            "ok": False,
            "error": f"issuer is disabled: {args.issuer}",
            "key_rotations": [],
        }
        out = json.dumps(result, indent=2)
        print(out)
        if args.fail_on_error:
            sys.exit(1)
        return

    service_id = issuer_rec.get("service_id") or ""
    key_rotations: list[dict[str, Any]] = []

    if service_id:
        key_refs = fetch_key_refs_for_service(conn, service_id)
        for key_ref in key_refs:
            key_name = str(key_ref["key_name"])
            active_ver = str(key_ref.get("active_version") or "")
            if not active_ver:
                continue
            new_ver = next_rotation_version(active_ver)
            # Inherit secret_ref from current active version
            cur_kv = fetch_active_key_version(conn, key_name, active_ver)
            secret_ref_kind = str(cur_kv.get("secret_ref_kind") or "") if cur_kv else None
            secret_ref_name = str(cur_kv.get("secret_ref_name") or "") if cur_kv else None
            rotation = rotate_key_in_db(
                conn,
                key_name=key_name,
                old_version=active_ver,
                new_version=new_ver,
                imported_at=imported_at,
                secret_ref_kind=secret_ref_kind or None,
                secret_ref_name=secret_ref_name or None,
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                log_rotation_mutation(
                    conn,
                    issuer=args.issuer,
                    key_name=key_name,
                    old_version=active_ver,
                    new_version=new_ver,
                    applied_at=imported_at,
                    actor=args.actor,
                )
            key_rotations.append(rotation)

    if not args.dry_run and key_rotations:
        conn.commit()

    conn.close()

    result = {
        "schema": SCHEMA_ID,
        "generated_at_utc": imported_at,
        "issuer": args.issuer,
        "issuer_type": issuer_rec.get("issuer_type"),
        "service_id": service_id or None,
        "mode": "dry_run" if args.dry_run else "apply",
        "ok": True,
        "error": None,
        "key_rotation_count": len(key_rotations),
        "key_rotations": key_rotations,
    }

    out = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        print(out)


if __name__ == "__main__":
    main()
