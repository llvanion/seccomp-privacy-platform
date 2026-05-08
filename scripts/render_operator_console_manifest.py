#!/usr/bin/env python3
"""Validate the operator console manifest baseline (Track-E3).

Reads ``config/operator_console/console_manifest.json``, validates its shape
against ``schemas/console_manifest.schema.json``, asserts the eight expected
sections (home / jobs / audit / catalog / permissions / recovery / observability
/ compliance) are present, asserts the static placeholder
``config/operator_console/index.html`` references the manifest at runtime, and
emits ``operator_console_manifest_report/v1``.

The script is contract-only — it does not start any service. It exists so the
docs/OPERATOR_CONSOLE_PRODUCT_PLAN.md baseline cannot drift silently from the
checked-in manifest and static placeholder.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "operator_console_manifest_report/v1"
DEFAULT_MANIFEST = REPO_ROOT / "config" / "operator_console" / "console_manifest.json"
DEFAULT_INDEX_HTML = REPO_ROOT / "config" / "operator_console" / "index.html"
DEFAULT_MANIFEST_SCHEMA = REPO_ROOT / "schemas" / "console_manifest.schema.json"

EXPECTED_SECTIONS = [
    "home",
    "jobs",
    "audit",
    "catalog",
    "permissions",
    "recovery",
    "observability",
    "compliance",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_text(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"[ERROR] missing required artifact: {path}")
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> dict:
    try:
        payload = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[ERROR] {path} is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        raise SystemExit(f"[ERROR] {path} must contain a JSON object")
    return payload


def validate_manifest_shape(manifest: dict, schema_path: Path) -> None:
    """Best-effort local validation against console_manifest/v1.

    We avoid importing jsonschema here because validate_json_contract.py is the
    canonical validator and is invoked separately by contract smoke. This only
    enforces the structural invariants the report needs to compute its summary.
    """
    schema = load_json(schema_path)
    schema_id = schema.get("$id")
    if schema_id != "console_manifest/v1":
        raise SystemExit(f"[ERROR] {schema_path} schema id mismatch: got {schema_id!r}")
    if manifest.get("schema") != "console_manifest/v1":
        raise SystemExit(f"[ERROR] manifest schema field mismatch: got {manifest.get('schema')!r}")
    sections = manifest.get("sections")
    if not isinstance(sections, list) or not sections:
        raise SystemExit("[ERROR] manifest must declare a non-empty sections list")
    for section in sections:
        if not isinstance(section, dict):
            raise SystemExit("[ERROR] each section must be an object")
        for required in ("section", "title", "endpoints", "roles_allowed"):
            if required not in section:
                raise SystemExit(f"[ERROR] section missing required field: {required}")
        if not isinstance(section["endpoints"], list):
            raise SystemExit("[ERROR] section.endpoints must be a list")
        for endpoint in section["endpoints"]:
            if not isinstance(endpoint, dict):
                raise SystemExit("[ERROR] each endpoint must be an object")
            if "method" not in endpoint or "path" not in endpoint:
                raise SystemExit("[ERROR] endpoint must declare method + path")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Validate the operator console manifest baseline and emit operator_console_manifest_report/v1.",
    )
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--manifest-schema", default=str(DEFAULT_MANIFEST_SCHEMA))
    ap.add_argument("--index-html", default=str(DEFAULT_INDEX_HTML))
    ap.add_argument("--output", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    manifest_path = Path(args.manifest).resolve()
    schema_path = Path(args.manifest_schema).resolve()
    index_html_path = Path(args.index_html).resolve()

    manifest = load_json(manifest_path)
    validate_manifest_shape(manifest, schema_path)

    sections_present = [str(s["section"]) for s in manifest.get("sections", [])]
    sections_missing = [name for name in EXPECTED_SECTIONS if name not in sections_present]

    endpoints_total = sum(len(s.get("endpoints", [])) for s in manifest.get("sections", []))
    roles_referenced = sorted({
        role
        for section in manifest.get("sections", [])
        for role in section.get("roles_allowed", [])
    })

    index_html_text = read_text(index_html_path)
    index_links_count = index_html_text.count("href=") + index_html_text.count('"path"')
    static_references_manifest = "console_manifest.json" in index_html_text

    feature_flags = sorted(set(manifest.get("feature_flags", [])))

    status = "ok"
    if sections_missing:
        status = "fail"
    if not static_references_manifest:
        status = "fail"

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "manifest_path": str(manifest_path),
        "static_index_path": str(index_html_path),
        "manifest": manifest,
        "summary": {
            "status": status,
            "section_count": len(sections_present),
            "expected_sections": EXPECTED_SECTIONS,
            "sections_present": sections_present,
            "sections_missing": sections_missing,
            "endpoints_total": endpoints_total,
            "roles_referenced": roles_referenced,
            "static_index_links_count": index_links_count,
            "static_index_references_manifest": static_references_manifest,
            "feature_flags": feature_flags,
        },
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
