#!/usr/bin/env python3
"""
A2: OpenFGA-style authorization check adapter.

Answers "can user:X perform relation R on object:Y?" against the local SQLite
tuple store populated by sync_openfga_tuples.py.

The check is a direct tuple lookup — it does NOT traverse computed relations.
This matches OpenFGA's "check" API for directly-assigned tuples, not the full
relationship hierarchy traversal. Use this for:
  - metadata/query/audit/platform-health read-side gate checks
  - Quick "does this tuple exist?" verification before sidecar ops

Usage:
  python3 scripts/check_openfga_authz.py \
    --tuple-store tmp/openfga_tuples.db \
    --user "user:campaign_analyst" \
    --relation reader \
    --object "dataset:orders_dataset"
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.openfga_http import (  # noqa: E402
    check_tuple as check_openfga_http_tuple,
    openfga_locator,
    resolve_openfga_runtime,
)

CHECK_SCHEMA = "openfga_check_result/v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open_store(path: str) -> sqlite3.Connection:
    if not Path(path).exists():
        raise FileNotFoundError(f"tuple store not found: {path}")
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def check_tuple(
    *,
    store_path: str,
    user: str,
    relation: str,
    object_ref: str,
    openfga_config: str = "",
    openfga_endpoint: str = "",
    openfga_store_id: str = "",
) -> dict:
    if openfga_config or openfga_endpoint:
        runtime = resolve_openfga_runtime(
            config_path=openfga_config,
            endpoint=openfga_endpoint,
            store_id=openfga_store_id,
        )
        payload = check_openfga_http_tuple(
            endpoint_url=runtime["endpoint_url"],
            store_id=runtime["store_id"],
            user=user,
            relation=relation,
            object_ref=object_ref,
            timeout_seconds=int(runtime["timeout_seconds"]),
            auth_token=str(runtime["auth_token"] or ""),
        )
        allowed = bool(payload.get("allowed"))
        return {
            "schema": CHECK_SCHEMA,
            "checked_at_utc": _utc_now(),
            "tuple_store_path": openfga_locator(runtime["endpoint_url"], runtime["store_id"]),
            "backend_kind": "openfga_http",
            "openfga_endpoint": runtime["endpoint_url"],
            "openfga_store_id": runtime["store_id"],
            "user": user,
            "relation": relation,
            "object": object_ref,
            "allowed": allowed,
            "reason": "openfga_check_allowed" if allowed else "openfga_check_denied",
            "matched_tuple": None,
        }

    resolved_path = str(Path(store_path).resolve())
    conn = _open_store(resolved_path)
    try:
        row = conn.execute(
            "SELECT user, relation, object, user_type, object_type, object_id FROM openfga_tuples "
            "WHERE user=? AND relation=? AND object=? LIMIT 1",
            (user, relation, object_ref),
        ).fetchone()
    finally:
        conn.close()

    if row:
        matched = {
            "user": str(row["user"]),
            "relation": str(row["relation"]),
            "object": str(row["object"]),
            "user_type": str(row["user_type"]),
            "object_type": str(row["object_type"]),
            "object_id": str(row["object_id"]),
        }
        return {
            "schema": CHECK_SCHEMA,
            "checked_at_utc": _utc_now(),
            "tuple_store_path": resolved_path,
            "backend_kind": "sqlite",
            "openfga_endpoint": None,
            "openfga_store_id": None,
            "user": user,
            "relation": relation,
            "object": object_ref,
            "allowed": True,
            "reason": "direct_tuple_match",
            "matched_tuple": matched,
        }
    return {
        "schema": CHECK_SCHEMA,
        "checked_at_utc": _utc_now(),
        "tuple_store_path": resolved_path,
        "backend_kind": "sqlite",
        "openfga_endpoint": None,
        "openfga_store_id": None,
        "user": user,
        "relation": relation,
        "object": object_ref,
        "allowed": False,
        "reason": "no_matching_tuple",
        "matched_tuple": None,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="A2: OpenFGA-style authorization check against local tuple store")
    ap.add_argument("--tuple-store", default="", help="Path to local SQLite tuple store")
    ap.add_argument("--openfga-config", default="", help="Path to openfga_config/v1 JSON")
    ap.add_argument("--openfga-endpoint", default="", help="Live OpenFGA endpoint URL")
    ap.add_argument("--openfga-store-id", default="", help="Live OpenFGA store ID")
    ap.add_argument("--user", required=True, help="Subject in 'type:id' form, e.g. 'user:alice'")
    ap.add_argument("--relation", required=True, help="Relation to check, e.g. 'reader'")
    ap.add_argument("--object", required=True, dest="object_ref", help="Object in 'type:id' form, e.g. 'dataset:orders'")
    ap.add_argument("--output", default="", help="Write JSON result to this path (default: stdout)")
    ap.add_argument("--assert-allowed", action="store_true", help="Exit non-zero if not allowed")
    ap.add_argument("--assert-denied", action="store_true", help="Exit non-zero if allowed")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    has_openfga = bool(args.openfga_config or args.openfga_endpoint)
    if not has_openfga and not args.tuple_store:
        raise SystemExit("[ERROR] one of --tuple-store or --openfga-config/--openfga-endpoint is required")
    result = check_tuple(
        store_path=args.tuple_store,
        user=args.user,
        relation=args.relation,
        object_ref=args.object_ref,
        openfga_config=args.openfga_config,
        openfga_endpoint=args.openfga_endpoint,
        openfga_store_id=args.openfga_store_id,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)

    if args.assert_allowed and not result["allowed"]:
        print(f"[error] expected allowed but got denied: {args.user} {args.relation} {args.object_ref}", flush=True)
        return 1
    if args.assert_denied and result["allowed"]:
        print(f"[error] expected denied but got allowed: {args.user} {args.relation} {args.object_ref}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
