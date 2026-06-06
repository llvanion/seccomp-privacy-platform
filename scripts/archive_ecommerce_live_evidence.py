#!/usr/bin/env python3
"""Archive live e-commerce deployment evidence into a verifier-facing bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "ecommerce_live_evidence_archive/v1"
EXPECTED_LIVE_SCHEMAS = {
    "live_oidc_abac_report": "ecommerce_live_oidc_abac_report/v1",
    "live_fact_import_report": "ecommerce_live_fact_import_report/v1",
    "live_tls_network_policy_report": "ecommerce_live_tls_network_policy_report/v1",
    "live_postgres_anchor_report": "ecommerce_live_postgres_anchor_report/v1",
    "live_logistics_rollout_report": "ecommerce_logistics_live_rollout_report/v1",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(src: Path, dst: Path) -> None:
    if src.resolve() == dst.resolve():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def artifact(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--live-repo-side-ecommerce-foundation", default="")
    ap.add_argument("--live-oidc-abac-report", default="")
    ap.add_argument("--live-fact-import-report", default="")
    ap.add_argument("--live-tls-network-policy-report", default="")
    ap.add_argument("--live-postgres-anchor-report", default="")
    ap.add_argument("--live-logistics-rollout-report", default="")
    ap.add_argument("--output-dir", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.live_repo_side_ecommerce_foundation:
        default_foundation = (
            Path(__file__).resolve().parents[1]
            / "tmp"
            / "ecommerce_production_exposure_gate"
            / "ecommerce_production_exposure_gate.json"
        )
        if default_foundation.is_file():
            args.live_repo_side_ecommerce_foundation = str(default_foundation)
    if not args.live_logistics_rollout_report:
        default_logistics_rollout = (
            Path(__file__).resolve().parents[1]
            / "tmp"
            / "logistics_live_synthetic"
            / "ecommerce_logistics_live_rollout_report.json"
        )
        if default_logistics_rollout.is_file():
            args.live_logistics_rollout_report = str(default_logistics_rollout)

    live_artifacts = {
        "live_repo_side_ecommerce_foundation": None,
        "live_oidc_abac_report": None,
        "live_fact_import_report": None,
        "live_tls_network_policy_report": None,
        "live_postgres_anchor_report": None,
    }
    findings: list[str] = []

    inputs = {
        "live_repo_side_ecommerce_foundation": args.live_repo_side_ecommerce_foundation,
        "live_oidc_abac_report": args.live_oidc_abac_report,
        "live_fact_import_report": args.live_fact_import_report,
        "live_tls_network_policy_report": args.live_tls_network_policy_report,
        "live_postgres_anchor_report": args.live_postgres_anchor_report,
    }
    optional_inputs = {
        "live_logistics_rollout_report": args.live_logistics_rollout_report,
    }
    for name, raw in inputs.items():
        if not raw:
            findings.append(f"{name} not provided")
            continue
        src = Path(raw).resolve()
        if not src.is_file():
            raise SystemExit(f"[ERROR] missing live e-commerce artifact for {name}: {src}")
        dst = out_dir / src.name
        copy_file(src, dst)
        payload = load_json(dst) if src.suffix == ".json" else None
        expected_schema = EXPECTED_LIVE_SCHEMAS.get(name)
        if expected_schema and isinstance(payload, dict) and str(payload.get("schema") or "") != expected_schema:
            raise SystemExit(f"[ERROR] unexpected schema for {name}: expected {expected_schema}, got {payload.get('schema')!r}")
        live_artifacts[name] = {"path": str(dst), "payload": payload}
    for name, raw in optional_inputs.items():
        if not raw:
            findings.append(f"{name} not provided")
            continue
        src = Path(raw).resolve()
        if not src.is_file():
            raise SystemExit(f"[ERROR] missing live e-commerce artifact for {name}: {src}")
        dst = out_dir / src.name
        copy_file(src, dst)
        live_artifacts[name] = {"path": str(dst), "payload": load_json(dst) if src.suffix == ".json" else None}

    copied_files = sorted(path for path in out_dir.rglob("*") if path.is_file())
    artifacts = [artifact(out_dir, path) for path in copied_files]
    aggregate_sha256 = hashlib.sha256(
        "".join(f"{item['path']}\0{item['sha256']}\n" for item in artifacts).encode("utf-8")
    ).hexdigest()

    live_artifact_count = sum(1 for item in live_artifacts.values() if item is not None)
    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "job_id": args.job_id,
        "live_artifact_count": live_artifact_count,
        "live_artifacts": live_artifacts,
        "findings": findings,
        "artifacts": artifacts,
        "aggregate_sha256": aggregate_sha256,
    }
    write_json(out_dir / "ecommerce_live_evidence_archive.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
