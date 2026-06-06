#!/usr/bin/env python3
"""Archive SPIFFE/SPIRE + Envoy live evidence into a verifier-facing bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "spiffe_envoy_live_evidence_archive/v1"


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
    ap.add_argument("--templates-dir", default="deploy/spiffe_envoy")
    ap.add_argument("--live-positive-report")
    ap.add_argument("--live-wrong-peer-report")
    ap.add_argument("--live-expired-svid-report")
    ap.add_argument("--live-trust-bundle-reject-report")
    ap.add_argument("--live-envoy-access-log")
    ap.add_argument("--output-dir", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    templates_dir = Path(args.templates_dir).resolve()
    allowlist_path = templates_dir / "peer_spiffe_allowlist.json"
    if not allowlist_path.is_file():
        raise SystemExit(f"[ERROR] missing allowlist: {allowlist_path}")
    copy_file(allowlist_path, out_dir / "peer_spiffe_allowlist.json")

    live_inputs = {
        "live_positive_run": args.live_positive_report,
        "live_wrong_peer_reject": args.live_wrong_peer_report,
        "live_expired_svid_reject": args.live_expired_svid_report,
        "live_trust_bundle_reject": args.live_trust_bundle_reject_report,
        "live_envoy_access_log": args.live_envoy_access_log,
    }

    copied_live: dict[str, Any] = {}
    findings: list[str] = []
    for name, raw in live_inputs.items():
        if not raw:
            copied_live[name] = None
            findings.append(f"{name} not provided")
            continue
        src = Path(raw).resolve()
        if not src.is_file():
            raise SystemExit(f"[ERROR] missing live artifact for {name}: {src}")
        dst = out_dir / src.name
        copy_file(src, dst)
        copied_live[name] = {
            "path": str(dst),
            "is_json": src.suffix == ".json",
            "payload": load_json(dst) if src.suffix == ".json" else None,
        }

    copied_files = sorted(path for path in out_dir.rglob("*") if path.is_file())
    artifacts = [artifact(out_dir, path) for path in copied_files]
    aggregate_sha256 = hashlib.sha256(
        "".join(f"{item['path']}\0{item['sha256']}\n" for item in artifacts).encode("utf-8")
    ).hexdigest()

    live_count = sum(1 for value in copied_live.values() if value is not None)
    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "job_id": args.job_id,
        "templates_dir": str(templates_dir),
        "live_artifact_count": live_count,
        "live_artifacts": copied_live,
        "findings": findings,
        "artifacts": artifacts,
        "aggregate_sha256": aggregate_sha256,
    }
    write_json(out_dir / "spiffe_envoy_live_evidence_archive.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
