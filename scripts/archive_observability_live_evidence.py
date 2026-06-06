#!/usr/bin/env python3
"""Archive observability / alerting live evidence into a verifier-facing bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "observability_live_evidence_archive/v1"


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
    ap.add_argument("--live-repo-side-observability-foundation", default="")
    ap.add_argument("--live-tempo-push-report", default="")
    ap.add_argument("--live-grafana-render-report", default="")
    ap.add_argument("--live-webhook-report", default="")
    ap.add_argument("--live-heartbeat-log", default="")
    ap.add_argument("--output-dir", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    foundation_path = ""

    if not args.live_repo_side_observability_foundation:
        default_foundation = (
            Path(__file__).resolve().parents[1]
            / "tmp"
            / "observability_evidence_gate"
            / "observability_evidence_gate.json"
        )
        if default_foundation.is_file():
            foundation_path = str(default_foundation)
    else:
        foundation_path = args.live_repo_side_observability_foundation

    live_artifacts = {
        "live_repo_side_observability_foundation": None,
        "live_tempo_push_report": None,
        "live_grafana_render_report": None,
        "live_webhook_report": None,
        "live_heartbeat_log": None,
    }
    findings: list[str] = []

    inputs = {
        "live_repo_side_observability_foundation": foundation_path,
        "live_tempo_push_report": args.live_tempo_push_report,
        "live_grafana_render_report": args.live_grafana_render_report,
        "live_webhook_report": args.live_webhook_report,
        "live_heartbeat_log": args.live_heartbeat_log,
    }
    for name, raw in inputs.items():
        if not raw:
            findings.append(f"{name} not provided")
            continue
        src = Path(raw).resolve()
        if not src.is_file():
            raise SystemExit(f"[ERROR] missing live observability artifact for {name}: {src}")
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
    write_json(out_dir / "observability_live_evidence_archive.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
