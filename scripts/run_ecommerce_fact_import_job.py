#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "ecommerce_fact_import_job/v1"
DEFAULT_POLICY = REPO_ROOT / "config" / "business_access_policy.ecommerce.example.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Run a validator-first e-commerce fact import job manifest.")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--output", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    manifest_path = Path(args.manifest).resolve()
    output_path = Path(args.output).resolve()
    manifest = load_json(manifest_path)

    if manifest.get("schema") != SCHEMA_ID:
        raise SystemExit(f"[ERROR] manifest schema must be {SCHEMA_ID}")

    table = str(manifest.get("table") or "").strip()
    input_path = Path(str(manifest.get("input_path") or "")).resolve()
    metadata_db = str(manifest.get("metadata_db") or "").strip()
    metadata_dsn = str(manifest.get("metadata_dsn") or "").strip()
    policy_path = Path(str(manifest.get("business_access_policy") or DEFAULT_POLICY)).resolve()
    allow_reject = bool(manifest.get("allow_reject"))
    result_path = Path(str(manifest.get("result_path") or (output_path.parent / f"{table}_result.json"))).resolve()

    if not table or not input_path.is_file():
        raise SystemExit("[ERROR] manifest must provide table and an existing input_path")
    if not metadata_db and not metadata_dsn:
        raise SystemExit("[ERROR] manifest must provide metadata_db or metadata_dsn")

    cmd = [
        "python3",
        str(REPO_ROOT / "scripts" / "import_ecommerce_fact_rows.py"),
        "--table",
        table,
        "--input",
        str(input_path),
        "--business-access-policy",
        str(policy_path),
        "--output",
        str(result_path),
    ]
    if metadata_db:
        cmd.extend(["--metadata-db", metadata_db])
    if metadata_dsn:
        cmd.extend(["--metadata-dsn", metadata_dsn])
    if allow_reject:
        cmd.append("--allow-reject")

    res = run(cmd)
    result = load_json(result_path) if result_path.is_file() else None
    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "manifest_path": str(manifest_path),
        "status": "ok" if res.returncode == 0 else "fail",
        "table": table,
        "input_path": str(input_path),
        "result_path": str(result_path),
        "command": cmd,
        "returncode": res.returncode,
        "stdout": res.stdout,
        "stderr": res.stderr,
        "result": result,
    }
    write_json(output_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if res.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

