#!/usr/bin/env python3
"""Collect live supply-chain rollout evidence from a running operator host."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_checked(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"command failed ({res.returncode}): {' '.join(cmd)}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
        )
    return res


def git_value(args: list[str]) -> str | None:
    res = subprocess.run(["git", *args], cwd=str(REPO_ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if res.returncode != 0:
        return None
    return res.stdout.strip() or None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--job-id", default="supply-chain-live-rollout")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    tracked = [
        Path("scripts/serve_metadata_api.py"),
        Path("scripts/serve_platform_health_api.py"),
        Path("scripts/serve_query_workflow_api.py"),
        Path("scripts/serve_operator_dashboard.py"),
        Path("scripts/check_json_contracts.sh"),
        Path(".github/workflows/json-contracts.yml"),
        Path("config/schema_backcompat_baseline.json"),
    ]
    checksums: list[dict[str, Any]] = []
    for rel in tracked:
        path = (REPO_ROOT / rel).resolve()
        if not path.is_file():
            continue
        checksums.append(
            {
                "path": str(rel),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    release_checksums = {
        "schema": "supply_chain_live_release_checksums/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "artifact_count": len(checksums),
        "artifacts": checksums,
    }
    write_json(out_dir / "supply_chain_live_release_checksums.json", release_checksums)

    provenance = {
        "schema": "supply_chain_live_provenance_report/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "repo_root": str(REPO_ROOT),
        "git_commit": git_value(["rev-parse", "--short", "HEAD"]),
        "git_branch": git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
        "git_status_short": run_checked(["git", "status", "--short"]).stdout.splitlines(),
        "release_backup_candidates": sorted(
            str(path)
            for path in Path("/root").glob("seccomp_repo_code_backup_*.tgz")
        )[-5:],
        "uploaded_sync_bundle_present": (Path("/root/seccomp_authoritative_sync.tgz").is_file()),
    }
    write_json(out_dir / "supply_chain_live_provenance_report.json", provenance)

    summary = {
        "schema": "supply_chain_live_rollout_collection/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "job_id": args.job_id,
        "live_release_checksums": str(out_dir / "supply_chain_live_release_checksums.json"),
        "live_provenance_report": str(out_dir / "supply_chain_live_provenance_report.json"),
    }
    write_json(out_dir / "supply_chain_live_rollout_collection.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
