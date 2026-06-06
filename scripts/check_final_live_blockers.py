#!/usr/bin/env python3
"""Summarize the current operator-side blockers for the remaining live modules."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "final_live_blockers_report/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="")
    ap.add_argument("--spiffe-collection-report", default="")
    ap.add_argument("--authority-collection-report", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    spiffe_path = Path(args.spiffe_collection_report).resolve() if args.spiffe_collection_report else (REPO_ROOT / "tmp" / "spiffe_envoy_live_rollout_collection.json")
    authority_path = Path(args.authority_collection_report).resolve() if args.authority_collection_report else (REPO_ROOT / "tmp" / "authority_live_rollout_collection.json")
    spiffe_report = load_json(spiffe_path) if spiffe_path.is_file() else None
    authority_report = load_json(authority_path) if authority_path.is_file() else None

    spiffe = {
        "status": str((spiffe_report or {}).get("status") or "blocked"),
        "required_artifacts": list((spiffe_report or {}).get("required_artifacts") or []),
        "collection_report": spiffe_report,
    }
    authority = {
        "status": str((authority_report or {}).get("status") or "blocked"),
        "required_artifacts": list((authority_report or {}).get("required_artifacts") or []),
        "collection_report": authority_report,
    }

    remaining_modules = [
        name
        for name, payload in (
            ("spiffe_envoy", spiffe),
            ("authority", authority),
        )
        if str(payload.get("status") or "blocked") != "ok"
    ]

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "remaining_live_module_count": len(remaining_modules),
        "remaining_modules": remaining_modules,
        "spiffe_envoy": spiffe,
        "authority": authority,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = (REPO_ROOT / out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
