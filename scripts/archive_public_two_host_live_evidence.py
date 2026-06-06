#!/usr/bin/env python3
"""Archive a completed clean-room public two-host PJC run into verifier-facing evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import serve_operator_dashboard as sod  # noqa: E402


SCHEMA = "public_two_host_live_evidence_archive/v1"


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


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def file_record(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--party-b-job-dir", required=True)
    ap.add_argument("--party-b-cert-dir", required=True)
    ap.add_argument("--party-a-server-log", required=True)
    ap.add_argument("--cleanroom-report", required=True)
    ap.add_argument("--peer-host", required=True)
    ap.add_argument("--peer-port", type=int, required=True)
    ap.add_argument("--server-hostname", default="pjc-server")
    ap.add_argument("--output-dir", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    party_b_job_dir = Path(args.party_b_job_dir).resolve()
    party_b_cert_dir = Path(args.party_b_cert_dir).resolve()
    party_a_server_log = Path(args.party_a_server_log).resolve()
    cleanroom_report = Path(args.cleanroom_report).resolve()
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    merged_result = party_b_job_dir / "attribution_result.json"
    if not merged_result.is_file():
        raise SystemExit(f"[ERROR] merged attribution result missing: {merged_result}")
    if not party_a_server_log.is_file():
        raise SystemExit(f"[ERROR] party_a_server.log missing: {party_a_server_log}")
    if not cleanroom_report.is_file():
        raise SystemExit(f"[ERROR] clean-room report missing: {cleanroom_report}")

    archive_party_a = out_dir / "party_a_server"
    archive_party_b = out_dir / "party_b_client"
    archive_party_b_buckets = out_dir / "party_b_buckets"

    copy_file(party_a_server_log, archive_party_a / "server.log")
    copy_file(merged_result, archive_party_b / "attribution_result.json")
    copy_file(cleanroom_report, out_dir / "public_two_host_live_materialization_report.json")

    bucket_results: list[dict[str, Any]] = []
    first_client_session_check: Path | None = None
    for bucket_dir in sorted(path for path in party_b_job_dir.iterdir() if path.is_dir() and path.name.startswith("bucket_")):
        bucket_name = bucket_dir.name
        bucket_out = archive_party_b_buckets / bucket_name
        for filename in (
            "attribution_result.json",
            "client.log",
            "socat_client.log",
            "pjc_preflight_client.json",
            "pjc_mtls_session_check_client.json",
            "pjc_binary_capability_gate.json",
            "job_meta.json",
            "input_commitments.json",
        ):
            src = bucket_dir / filename
            if src.is_file():
                copy_file(src, bucket_out / filename)
        result_path = bucket_dir / "attribution_result.json"
        session_check_path = bucket_dir / "pjc_mtls_session_check_client.json"
        if first_client_session_check is None and session_check_path.is_file():
            first_client_session_check = session_check_path
        if result_path.is_file():
            payload = load_json(result_path)
            bucket_results.append(
                {
                    "bucket": bucket_name,
                    "intersection_size": payload.get("intersection_size"),
                    "intersection_sum": payload.get("intersection_sum"),
                    "timestamp": payload.get("timestamp"),
                    "server_addr": payload.get("server_addr"),
                    "tls": payload.get("tls"),
                }
            )

    representative_bucket = sorted(path for path in party_b_job_dir.iterdir() if path.is_dir() and path.name.startswith("bucket_"))[0]
    client_log_src = representative_bucket / "client.log"
    if client_log_src.is_file():
        copy_file(client_log_src, archive_party_b / "client.log")
    if first_client_session_check is None:
        raise SystemExit("[ERROR] no client session-check artifact was found in the completed bucket results")
    client_identity = load_json(first_client_session_check)
    write_json(out_dir / "client_tls_identity.json", client_identity)
    server_identity = {
        "schema": "pjc_tls_identity/v1",
        "generated_at_utc": utc_now_iso(),
        "decision": "allow",
        "role": "server",
        "reason_code": "ok",
        "reason": None,
        "peer_host": args.peer_host,
        "peer_port": args.peer_port,
        "server_hostname": args.server_hostname,
        "source": "pjc_mtls_session_manifest_check/v1",
        "reference_client_session_check": str(first_client_session_check),
        "checks": {
            "expected_peer_identity": (client_identity.get("checks") or {}).get("expected_client_identity"),
            "expected_peer_fingerprint_sha256": (client_identity.get("checks") or {}).get("expected_client_fingerprint_sha256"),
            "server_fingerprint_sha256": (client_identity.get("checks") or {}).get("server_fingerprint_sha256"),
            "server_san_dns_names": (client_identity.get("checks") or {}).get("server_san_dns_names"),
            "ca_fingerprint_sha256": (client_identity.get("checks") or {}).get("ca_fingerprint_sha256"),
        },
    }
    write_json(out_dir / "server_tls_identity.json", server_identity)

    copied_files = sorted(path for path in out_dir.rglob("*") if path.is_file())
    artifacts = [file_record(out_dir, path) for path in copied_files]
    aggregate_sha = hashlib.sha256(
        "".join(f"{item['path']}\0{item['sha256']}\n" for item in artifacts).encode("utf-8")
    ).hexdigest()

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "job_id": args.job_id,
        "peer_host": args.peer_host,
        "peer_port": args.peer_port,
        "server_hostname": args.server_hostname,
        "bucket_count": len(bucket_results),
        "merged_result": load_json(merged_result),
        "bucket_results": bucket_results,
        "tls_identity": {
            "client": client_identity,
            "server": server_identity,
        },
        "cleanroom_materialization_report": str(out_dir / "public_two_host_live_materialization_report.json"),
        "artifacts": artifacts,
        "aggregate_sha256": aggregate_sha,
    }
    write_json(out_dir / "public_two_host_live_evidence_archive.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
