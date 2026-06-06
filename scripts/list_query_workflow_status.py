#!/usr/bin/env python3
"""Scan a directory tree for query_workflow/status.json files and return a summary list."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
LIST_SCHEMA = "query_workflow_status_list/v1"
STATUS_SCHEMA = "query_workflow_status/v1"
STATUS_SUBPATH = Path("query_workflow") / "status.json"
VALID_STATES = {
    "accepted",
    "queued",
    "running",
    "completed",
    "failed",
    "rejected",
    "cancel_requested",
    "cancelled",
    "timed_out",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def repo_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def compact_status(status_path: Path, raw: dict[str, Any]) -> dict[str, Any]:
    out_base = str(status_path.parent.parent)
    return {
        "out_base": out_base,
        "status_path": str(status_path),
        "job_id": raw.get("job_id"),
        "correlation_id": raw.get("correlation_id"),
        "caller": raw.get("caller"),
        "tenant_id": raw.get("tenant_id"),
        "state": raw.get("state"),
        "terminal": raw.get("terminal"),
        "last_updated_at_utc": raw.get("last_updated_at_utc"),
        "receipt_count": raw.get("receipt_count"),
        "last_exit_code": raw.get("last_exit_code"),
        "mode": raw.get("mode"),
    }


def scan_status_files(
    search_dir: Path,
    *,
    filter_state: str | None = None,
    filter_job_id: str | None = None,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Return (results_up_to_limit, total_found)."""
    found: list[dict[str, Any]] = []
    for status_path in sorted(search_dir.rglob("query_workflow/status.json")):
        try:
            raw = json.loads(status_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(raw, dict):
            continue
        if raw.get("schema") != STATUS_SCHEMA:
            continue
        if filter_state and raw.get("state") != filter_state:
            continue
        if filter_job_id and raw.get("job_id") != filter_job_id:
            continue
        found.append(compact_status(status_path, raw))
    # Sort by last_updated_at_utc descending (most recent first), nulls last
    has_ts = sorted(
        [r for r in found if r.get("last_updated_at_utc")],
        key=lambda r: r["last_updated_at_utc"],
        reverse=True,
    )
    no_ts = [r for r in found if not r.get("last_updated_at_utc")]
    ordered = has_ts + no_ts
    return ordered[:limit], len(ordered)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Scan a directory tree for query_workflow/status.json files.",
    )
    ap.add_argument("--search-dir", required=True, help="Root directory to scan recursively")
    ap.add_argument("--state", default="", help=f"Filter by state: {', '.join(sorted(VALID_STATES))}")
    ap.add_argument("--job-id", default="", help="Filter by job_id")
    ap.add_argument("--limit", type=int, default=50, help="Max entries to return (default 50)")
    ap.add_argument("--out", default="", help="Output path for query_workflow_status_list.json")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    search_dir = repo_path(args.search_dir)
    if not search_dir.is_dir():
        raise SystemExit(f"[ERROR] search directory does not exist: {search_dir}")
    filter_state = args.state or None
    if filter_state and filter_state not in VALID_STATES:
        raise SystemExit(f"[ERROR] invalid state filter {filter_state!r}; valid: {sorted(VALID_STATES)}")
    filter_job_id = args.job_id or None
    limit = max(1, args.limit)
    results, total = scan_status_files(
        search_dir,
        filter_state=filter_state,
        filter_job_id=filter_job_id,
        limit=limit,
    )
    report: dict[str, Any] = {
        "schema": LIST_SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "search_dir": str(search_dir),
        "filter_state": filter_state,
        "filter_job_id": filter_job_id,
        "total_found": total,
        "returned_count": len(results),
        "limit": limit,
        "statuses": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out_path = repo_path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
