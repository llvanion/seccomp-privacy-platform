#!/usr/bin/env python3
"""Collect live PJC protocol rollout evidence from a running operator host."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def latest_signed_merge(root: Path) -> Path:
    matches = sorted((root / "tmp" / "pjc_two_party" / "evidence_merge").glob("signedsmoke_*.json"))
    if not matches:
        raise FileNotFoundError("no signedsmoke_*.json evidence merge reports found")
    return matches[-1]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--public-two-host-archive", default="tmp/public_two_host_live_archive_cross-vps-008/public_two_host_live_evidence_archive.json")
    ap.add_argument("--job-id", default="pjc-protocol-live-rollout")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    signed_merge_path = latest_signed_merge(REPO_ROOT)
    signed_merge = load_json(signed_merge_path)
    public_archive_path = (REPO_ROOT / args.public_two_host_archive).resolve()
    public_archive = load_json(public_archive_path)

    manifest_report = {
        "schema": "pjc_protocol_live_signed_manifest_report/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "source_merge_report": str(signed_merge_path),
        "job_id": signed_merge.get("job_id"),
        "checks": signed_merge.get("checks"),
        "party_a_manifest": (signed_merge.get("party_a") or {}).get("signed_manifest_verification"),
        "party_b_manifest": (signed_merge.get("party_b") or {}).get("signed_manifest_verification"),
        "boundary_note": "This signed-manifest evidence is sourced from the latest operator-side signed two-party smoke merge report.",
    }
    write_json(out_dir / "pjc_protocol_live_signed_manifest_report.json", manifest_report)

    release_binding_report = {
        "schema": "pjc_protocol_live_release_binding_report/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "source_public_two_host_archive": str(public_archive_path),
        "job_id": public_archive.get("job_id"),
        "merged_result": public_archive.get("merged_result"),
        "tls_identity": public_archive.get("tls_identity"),
        "artifact_count": len(public_archive.get("artifacts") or []),
        "boundary_note": "This release-binding evidence is sourced from the real public-two-host live archive for cross-vps-008.",
    }
    write_json(out_dir / "pjc_protocol_live_release_binding_report.json", release_binding_report)

    summary = {
        "schema": "pjc_protocol_live_rollout_collection/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "job_id": args.job_id,
        "live_two_host_signed_manifest_report": str(out_dir / "pjc_protocol_live_signed_manifest_report.json"),
        "live_release_binding_report": str(out_dir / "pjc_protocol_live_release_binding_report.json"),
    }
    write_json(out_dir / "pjc_protocol_live_rollout_collection.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
