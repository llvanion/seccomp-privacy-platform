#!/usr/bin/env python3
"""Create an OpenFGA store and upload the platform authorization model."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import utc_now  # noqa: E402
from scripts.openfga_http import load_openfga_config  # noqa: E402

REPORT_SCHEMA = "openfga_model_setup_report/v1"


def _json_request(method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("OpenFGA returned non-object JSON")
    return payload


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    config = load_openfga_config(args.openfga_config)
    endpoint = str(config.get("endpoint_url") or "").rstrip("/")
    model_path = str(Path(args.model).resolve())
    model = json.loads(Path(args.model).read_text(encoding="utf-8"))
    type_defs = model.get("type_definitions") if isinstance(model, dict) else []
    mode = "execute" if args.execute else "dry_run"
    store_id = str(args.store_id or config.get("store_id") or "").strip() or None
    auth_model_id = None
    try:
        if args.execute:
            if not store_id:
                created = _json_request("POST", f"{endpoint}/stores", {"name": args.store_name})
                store_id = str(created.get("id") or "")
            uploaded = _json_request("POST", f"{endpoint}/stores/{store_id}/authorization-models", model)
            auth_model_id = str(uploaded.get("authorization_model_id") or uploaded.get("id") or "") or None
        return {
            "schema": REPORT_SCHEMA,
            "generated_at_utc": utc_now(),
            "mode": mode,
            "ok": True,
            "error": None,
            "endpoint_url": endpoint,
            "model_path": model_path,
            "store_name": args.store_name,
            "store_id": store_id,
            "authorization_model_id": auth_model_id,
            "type_definition_count": len(type_defs) if isinstance(type_defs, list) else 0,
        }
    except Exception as exc:
        return {
            "schema": REPORT_SCHEMA,
            "generated_at_utc": utc_now(),
            "mode": mode,
            "ok": False,
            "error": str(exc),
            "endpoint_url": endpoint,
            "model_path": model_path,
            "store_name": args.store_name,
            "store_id": store_id,
            "authorization_model_id": None,
            "type_definition_count": len(type_defs) if isinstance(type_defs, list) else 0,
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="Set up OpenFGA authorization model")
    ap.add_argument("--openfga-config", required=True)
    ap.add_argument("--model", default="config/openfga_authorization_model.json")
    ap.add_argument("--store-name", default="seccomp-privacy")
    ap.add_argument("--store-id", default="")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--output", default="")
    ap.add_argument("--assert-ok", action="store_true")
    args = ap.parse_args()
    report = build_report(args)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 1 if args.assert_ok and not report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
