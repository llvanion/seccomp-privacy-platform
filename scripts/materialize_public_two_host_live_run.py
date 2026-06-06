#!/usr/bin/env python3
"""Materialize a clean public two-host live-run staging directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "public_two_host_live_materialization_report/v1"
ROLE_LAYOUT = {
    "party_a": {
        "source_subdir": "party_a_job",
        "staged_subdir": "party_a_job",
        "role": "server",
        "top_level_required": {"job_meta.json", "input_commitments.json", "server.csv"},
        "top_level_optional": {"expected_result.json"},
        "bucket_required": {"job_meta.json", "input_commitments.json", "server.csv"},
    },
    "party_b": {
        "source_subdir": "party_b_job",
        "staged_subdir": "party_b_job",
        "role": "client",
        "top_level_required": {"job_meta.json", "input_commitments.json", "client.csv"},
        "top_level_optional": {"expected_result.json"},
        "bucket_required": {"job_meta.json", "input_commitments.json", "client.csv"},
    },
}
SESSION_LAYOUT = {
    "cert_dir": {
        "source_subdir": ".",
        "required": {"ca.crt", "server.crt", "server.key", "client.crt", "client.key", "session_manifest.json"},
    },
    "party_b_bundle": {
        "source_subdir": "party_b_bundle",
        "required": {"ca.crt", "client.crt", "client.key", "session_manifest.json"},
    },
}
OUTPUT_FILENAMES = {
    "attribution_result.json",
    "client.log",
    "server.log",
    "socat_client.log",
    "pjc_binary_capability_gate.json",
    "pjc_mtls_session_check_client.json",
    "pjc_mtls_session_check_server.json",
    "pjc_preflight_client.json",
    "pjc_preflight_server.json",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"[ERROR] JSON object expected: {path}")
    return payload


def file_record(path: Path, *, relative_to: Path) -> dict[str, Any]:
    return {
        "relative_path": str(path.relative_to(relative_to)),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def detect_output_paths(root: Path) -> list[str]:
    matches: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in OUTPUT_FILENAMES or path.suffix == ".log":
            matches.append(str(path.relative_to(root)))
    return matches


def require_empty_directory(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        return
    if any(path.iterdir()):
        raise SystemExit(f"[ERROR] output directory must be empty: {path}")


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def materialize_party(
    *,
    source_root: Path,
    staged_root: Path,
    source_subdir: str,
    staged_subdir: str,
    role: str,
    top_level_required: set[str],
    top_level_optional: set[str],
    bucket_required: set[str],
) -> dict[str, Any]:
    src_dir = source_root / source_subdir
    if not src_dir.is_dir():
        raise SystemExit(f"[ERROR] missing source party directory: {src_dir}")
    dst_dir = staged_root / staged_subdir
    dst_dir.mkdir(parents=True, exist_ok=True)

    kept_files: list[dict[str, Any]] = []
    stripped_source_files: list[str] = []

    for name in sorted(top_level_required | top_level_optional):
        src_path = src_dir / name
        if src_path.exists():
            copy_file(src_path, dst_dir / name)
            kept_files.append(file_record(dst_dir / name, relative_to=staged_root))
        elif name in top_level_required:
            raise SystemExit(f"[ERROR] missing required {role} staging input: {src_path}")

    for path in sorted(src_dir.iterdir()):
        if path.name in top_level_required or path.name in top_level_optional:
            continue
        if path.is_dir() and path.name.startswith("bucket_"):
            bucket_dst = dst_dir / path.name
            bucket_dst.mkdir(parents=True, exist_ok=True)
            required_seen: set[str] = set()
            for child in sorted(path.iterdir()):
                if child.is_file() and child.name in bucket_required:
                    copy_file(child, bucket_dst / child.name)
                    kept_files.append(file_record(bucket_dst / child.name, relative_to=staged_root))
                    required_seen.add(child.name)
                else:
                    stripped_source_files.append(str(child.relative_to(src_dir)))
            missing = sorted(bucket_required - required_seen)
            if missing:
                raise SystemExit(f"[ERROR] bucket input missing under {path}: {missing}")
            continue
        stripped_source_files.append(str(path.relative_to(src_dir)))

    return {
        "role": role,
        "source_dir": str(src_dir),
        "staged_dir": str(dst_dir),
        "kept_files": kept_files,
        "stripped_source_files": stripped_source_files,
        "expected_runtime_outputs": [
            "pjc_preflight_*",
            "pjc_mtls_session_check_*",
            "pjc_binary_capability_gate.json",
            "client.log/server.log",
            "socat_client.log",
            "attribution_result.json",
        ],
    }


def materialize_session(*, source_session_dir: Path, staged_root: Path) -> dict[str, Any]:
    kept_files: list[dict[str, Any]] = []
    stripped_source_files: list[str] = []
    destinations: dict[str, str] = {}

    for staged_name, layout in SESSION_LAYOUT.items():
        src_dir = source_session_dir if layout["source_subdir"] == "." else source_session_dir / layout["source_subdir"]
        if not src_dir.is_dir():
            raise SystemExit(f"[ERROR] missing session directory: {src_dir}")
        dst_dir = staged_root / staged_name
        dst_dir.mkdir(parents=True, exist_ok=True)
        destinations[staged_name] = str(dst_dir)
        required_seen: set[str] = set()
        for child in sorted(src_dir.iterdir()):
            if child.is_file() and child.name in layout["required"]:
                copy_file(child, dst_dir / child.name)
                kept_files.append(file_record(dst_dir / child.name, relative_to=staged_root))
                required_seen.add(child.name)
            else:
                stripped_source_files.append(str(child.relative_to(source_session_dir)))
        missing = sorted(layout["required"] - required_seen)
        if missing:
            raise SystemExit(f"[ERROR] session staging input missing under {src_dir}: {missing}")

    return {
        "source_session_dir": str(source_session_dir),
        "cert_dir": destinations["cert_dir"],
        "party_b_bundle_dir": destinations["party_b_bundle"],
        "kept_files": kept_files,
        "stripped_source_files": stripped_source_files,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-job-dir", required=True, help="Directory containing party_a_job and party_b_job")
    ap.add_argument("--source-session-dir", required=True, help="Directory containing the live mTLS session bundle")
    ap.add_argument("--out-dir", required=True, help="Empty staging directory to materialize")
    ap.add_argument("--tls-port-base", type=int, default=0)
    ap.add_argument("--pjc-local-port-base", type=int, default=0)
    ap.add_argument("--local-proxy-port-base", type=int, default=0)
    ap.add_argument("--tls-port-mode", default="shared")
    ap.add_argument("--pjc-local-port-mode", default="increment")
    ap.add_argument("--local-proxy-port-mode", default="increment")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    source_job_dir = Path(args.source_job_dir).resolve()
    source_session_dir = Path(args.source_session_dir).resolve()
    out_dir = Path(args.out_dir).resolve()

    if not source_job_dir.is_dir():
        raise SystemExit(f"[ERROR] source job directory does not exist: {source_job_dir}")
    if not source_session_dir.is_dir():
        raise SystemExit(f"[ERROR] source session directory does not exist: {source_session_dir}")
    require_empty_directory(out_dir)

    party_reports: dict[str, Any] = {}
    for name, layout in ROLE_LAYOUT.items():
        party_reports[name] = materialize_party(
            source_root=source_job_dir,
            staged_root=out_dir,
            source_subdir=layout["source_subdir"],
            staged_subdir=layout["staged_subdir"],
            role=layout["role"],
            top_level_required=layout["top_level_required"],
            top_level_optional=layout["top_level_optional"],
            bucket_required=layout["bucket_required"],
        )

    session_report = materialize_session(source_session_dir=source_session_dir, staged_root=out_dir)
    staged_output_paths = detect_output_paths(out_dir)
    source_output_paths = detect_output_paths(source_job_dir / "party_a_job") + detect_output_paths(source_job_dir / "party_b_job")

    job_meta = load_json(source_job_dir / "party_a_job" / "job_meta.json")
    job_id = str(job_meta.get("job_id") or out_dir.name)
    findings: list[str] = []
    if source_output_paths:
        findings.append(
            "Source party directories already contained runtime outputs; the materializer stripped them so the staging directory starts clean."
        )
    if session_report["stripped_source_files"]:
        findings.append(
            "Source session bundle contained extra files beyond the minimum server/client cert material; extras were not copied into the live staging directory."
        )

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if not staged_output_paths else "fail",
        "job_id": job_id,
        "source_job_dir": str(source_job_dir),
        "source_session_dir": str(source_session_dir),
        "out_dir": str(out_dir),
        "parties": party_reports,
        "session_materials": session_report,
        "runtime_hints": {
            "tls_port_base": args.tls_port_base or None,
            "pjc_local_port_base": args.pjc_local_port_base or None,
            "local_proxy_port_base": args.local_proxy_port_base or None,
            "tls_port_mode": args.tls_port_mode,
            "pjc_local_port_mode": args.pjc_local_port_mode,
            "local_proxy_port_mode": args.local_proxy_port_mode,
        },
        "contamination_summary": {
            "source_output_file_count": len(source_output_paths),
            "source_output_examples": source_output_paths[:20],
            "staged_output_file_count": len(staged_output_paths),
            "staged_output_examples": staged_output_paths[:20],
        },
        "findings": findings,
    }
    write_json(out_dir / "public_two_host_live_materialization_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
