#!/usr/bin/env python3
"""
A2: OpenFGA tuple sync adapter.

Reads an authz_tuple_export/v1 source (policy file, metadata DB, or pre-generated
export file) and syncs tuples into a local SQLite tuple store.

Modes:
  dry_run   — show what would be added/removed, do not write
  apply     — upsert new tuples, optionally remove tuples no longer present
  reconcile — report diff only (same as dry_run but with explicit reconcile label)

Usage:
  python3 scripts/sync_openfga_tuples.py dry-run \
    --policy-config sse/config/ecommerce_access_policy.example.json \
    --tuple-store tmp/openfga_tuples.db

  python3 scripts/sync_openfga_tuples.py apply \
    --policy-config sse/config/ecommerce_access_policy.example.json \
    --tuple-store tmp/openfga_tuples.db \
    --prune

  python3 scripts/sync_openfga_tuples.py reconcile \
    --db-path tmp/platform_metadata.db \
    --tuple-store tmp/openfga_tuples.db
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.export_authz_tuples import (  # noqa: E402
    load_subjects_from_db,
    load_subjects_from_policy,
    relation_tuples,
)
from scripts.openfga_http import (  # noqa: E402
    openfga_locator,
    read_all_tuples,
    resolve_openfga_runtime,
    write_tuples,
)

SYNC_SCHEMA = "openfga_sync_report/v1"
MIGRATION = """
CREATE TABLE IF NOT EXISTS openfga_tuples (
    id INTEGER PRIMARY KEY,
    user TEXT NOT NULL,
    relation TEXT NOT NULL,
    object TEXT NOT NULL,
    user_type TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    source_policy_id TEXT,
    synced_at_utc TEXT NOT NULL,
    UNIQUE (user, relation, object)
);
CREATE INDEX IF NOT EXISTS idx_openfga_tuples_user ON openfga_tuples (user);
CREATE INDEX IF NOT EXISTS idx_openfga_tuples_object ON openfga_tuples (object);
CREATE INDEX IF NOT EXISTS idx_openfga_tuples_relation ON openfga_tuples (relation);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open_store(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(MIGRATION)
    conn.commit()
    return conn


def _store_tuple_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM openfga_tuples").fetchone()[0])


def _store_all_keys(conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
    rows = conn.execute("SELECT user, relation, object FROM openfga_tuples").fetchall()
    return {(str(r["user"]), str(r["relation"]), str(r["object"])) for r in rows}


def _load_source_tuples(args: argparse.Namespace) -> tuple[list[dict[str, Any]], str]:
    if getattr(args, "export_file", ""):
        raw = json.loads(Path(args.export_file).read_text(encoding="utf-8"))
        if raw.get("schema") != "authz_tuple_export/v1":
            raise ValueError(f"export file must use authz_tuple_export/v1: {args.export_file}")
        return raw.get("tuples") or [], "tuple_export_file"
    if getattr(args, "policy_config", ""):
        subjects, _ = load_subjects_from_policy(Path(args.policy_config))
        tuples: list[dict[str, Any]] = []
        for subj in subjects:
            tuples.extend(relation_tuples(subj))
        return tuples, "policy_config"
    if getattr(args, "db_path", ""):
        subjects, _ = load_subjects_from_db(Path(args.db_path))
        tuples = []
        for subj in subjects:
            tuples.extend(relation_tuples(subj))
        return tuples, "metadata_db"
    raise ValueError("one of --policy-config, --db-path, or --export-file is required")


def _run_sync(
    *,
    args: argparse.Namespace,
    mode: str,
    dry_run: bool,
) -> dict[str, Any]:
    source_tuples, source_kind = _load_source_tuples(args)
    source_set: set[tuple[str, str, str]] = {
        (str(t["user"]), str(t["relation"]), str(t["object"])) for t in source_tuples
    }
    source_by_key: dict[tuple[str, str, str], dict[str, Any]] = {
        (str(t["user"]), str(t["relation"]), str(t["object"])): t for t in source_tuples
    }

    backend_kind = "sqlite"
    openfga_endpoint = None
    openfga_store_id = None
    if getattr(args, "openfga_config", "") or getattr(args, "openfga_endpoint", ""):
        runtime = resolve_openfga_runtime(
            config_path=str(getattr(args, "openfga_config", "") or ""),
            endpoint=str(getattr(args, "openfga_endpoint", "") or ""),
            store_id=str(getattr(args, "openfga_store_id", "") or ""),
        )
        backend_kind = "openfga_http"
        openfga_endpoint = runtime["endpoint_url"]
        openfga_store_id = runtime["store_id"]
        store_path = openfga_locator(runtime["endpoint_url"], runtime["store_id"])
        store_set = set(
            read_all_tuples(
                endpoint_url=runtime["endpoint_url"],
                store_id=runtime["store_id"],
                timeout_seconds=int(runtime["timeout_seconds"]),
                auth_token=str(runtime["auth_token"] or ""),
            )
        )
        count_before = len(store_set)
        to_add = sorted(source_set - store_set)
        to_remove = sorted(store_set - source_set) if getattr(args, "prune", False) else []
        unchanged = len(source_set & store_set)
        count_after = None
        if not dry_run:
            write_tuples(
                endpoint_url=runtime["endpoint_url"],
                store_id=runtime["store_id"],
                writes=to_add,
                deletes=to_remove,
                timeout_seconds=int(runtime["timeout_seconds"]),
                auth_token=str(runtime["auth_token"] or ""),
            )
            count_after = count_before + len(to_add) - len(to_remove)
    else:
        store_path = str(Path(args.tuple_store).resolve())
        conn = _open_store(store_path)
        try:
            count_before = _store_tuple_count(conn)
            store_set = _store_all_keys(conn)

            to_add = sorted(source_set - store_set)
            to_remove = sorted(store_set - source_set) if getattr(args, "prune", False) else []
            unchanged = len(source_set & store_set)

            count_after = None
            if not dry_run:
                ts = _utc_now()
                for key in to_add:
                    t = source_by_key[key]
                    conn.execute(
                        """
                        INSERT INTO openfga_tuples
                          (user, relation, object, user_type, object_type, object_id, source_policy_id, synced_at_utc)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(user, relation, object) DO UPDATE SET
                          user_type=excluded.user_type,
                          object_type=excluded.object_type,
                          object_id=excluded.object_id,
                          source_policy_id=excluded.source_policy_id,
                          synced_at_utc=excluded.synced_at_utc
                        """,
                        (
                            str(t["user"]), str(t["relation"]), str(t["object"]),
                            str(t.get("user_type", "")), str(t.get("object_type", "")),
                            str(t.get("object_id", "")),
                            t.get("source_policy_id"),
                            ts,
                        ),
                    )
                for key in to_remove:
                    conn.execute(
                        "DELETE FROM openfga_tuples WHERE user=? AND relation=? AND object=?",
                        key,
                    )
                conn.commit()
                count_after = _store_tuple_count(conn)
        finally:
            conn.close()

    _SAMPLE = 5
    added_sample = [
        {"user": k[0], "relation": k[1], "object": k[2]}
        for k in to_add[:_SAMPLE]
    ]
    removed_sample = [
        {"user": k[0], "relation": k[1], "object": k[2]}
        for k in to_remove[:_SAMPLE]
    ]
    return {
        "schema": SYNC_SCHEMA,
        "generated_at_utc": _utc_now(),
        "mode": mode,
        "status": "dry_run" if dry_run else "ok",
        "source_kind": source_kind,
        "tuple_store_path": store_path,
        "backend_kind": backend_kind,
        "openfga_endpoint": openfga_endpoint,
        "openfga_store_id": openfga_store_id,
        "source_tuple_count": len(source_set),
        "store_tuple_count_before": count_before,
        "store_tuple_count_after": count_after,
        "added": len(to_add),
        "removed": len(to_remove),
        "unchanged": unchanged,
        "error": None,
        "added_sample": added_sample,
        "removed_sample": removed_sample,
    }


def _build_source_args(ap: argparse.ArgumentParser) -> None:
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--policy-config", default="", help="Path to sse_export_policy/v1 config")
    src.add_argument("--db-path", default="", help="Path to metadata SQLite DB")
    src.add_argument("--export-file", default="", help="Path to pre-generated authz_tuple_export/v1 JSON")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="A2: OpenFGA tuple sync adapter — dry-run / apply / reconcile")
    ap.add_argument("--tuple-store", default="", help="Path to local SQLite tuple store")
    ap.add_argument("--openfga-config", default="", help="Path to openfga_config/v1 JSON")
    ap.add_argument("--openfga-endpoint", default="", help="Live OpenFGA endpoint URL")
    ap.add_argument("--openfga-store-id", default="", help="Live OpenFGA store ID")
    ap.add_argument("--output", default="", help="Write JSON report to this path (default: stdout)")
    sub = ap.add_subparsers(dest="command", required=True)

    dry = sub.add_parser("dry-run", help="Show what would change without writing")
    _build_source_args(dry)
    dry.add_argument("--tuple-store", default="", help="Path to local SQLite tuple store")
    dry.add_argument("--openfga-config", default="", help="Path to openfga_config/v1 JSON")
    dry.add_argument("--openfga-endpoint", default="", help="Live OpenFGA endpoint URL")
    dry.add_argument("--openfga-store-id", default="", help="Live OpenFGA store ID")
    dry.add_argument("--output", default="")

    apply_p = sub.add_parser("apply", help="Upsert new tuples into the store")
    _build_source_args(apply_p)
    apply_p.add_argument("--tuple-store", default="", help="Path to local SQLite tuple store")
    apply_p.add_argument("--openfga-config", default="", help="Path to openfga_config/v1 JSON")
    apply_p.add_argument("--openfga-endpoint", default="", help="Live OpenFGA endpoint URL")
    apply_p.add_argument("--openfga-store-id", default="", help="Live OpenFGA store ID")
    apply_p.add_argument("--prune", action="store_true", help="Remove tuples no longer in source")
    apply_p.add_argument("--output", default="")

    recon = sub.add_parser("reconcile", help="Report diff between store and source")
    _build_source_args(recon)
    recon.add_argument("--tuple-store", default="", help="Path to local SQLite tuple store")
    recon.add_argument("--openfga-config", default="", help="Path to openfga_config/v1 JSON")
    recon.add_argument("--openfga-endpoint", default="", help="Live OpenFGA endpoint URL")
    recon.add_argument("--openfga-store-id", default="", help="Live OpenFGA store ID")
    recon.add_argument("--output", default="")

    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    cmd = args.command
    has_openfga = bool(args.openfga_config or args.openfga_endpoint)
    if not has_openfga and not args.tuple_store:
        raise SystemExit("[ERROR] one of --tuple-store or --openfga-config/--openfga-endpoint is required")

    if cmd == "dry-run":
        report = _run_sync(args=args, mode="dry_run", dry_run=True)
    elif cmd == "apply":
        report = _run_sync(args=args, mode="apply", dry_run=False)
    elif cmd == "reconcile":
        report = _run_sync(args=args, mode="reconcile", dry_run=True)
    else:
        raise SystemExit(f"unknown command: {cmd}")

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"[ok] sync report written to {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
