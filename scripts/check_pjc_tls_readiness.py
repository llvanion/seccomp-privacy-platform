#!/usr/bin/env python3
"""Typed TLS readiness probe for public two-host PJC endpoints."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import serve_operator_dashboard as sod  # noqa: E402


SCHEMA = "pjc_tls_readiness/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--role", choices=("server", "client"), default="client")
    ap.add_argument("--peer-host", required=True)
    ap.add_argument("--peer-port", type=int, required=True)
    ap.add_argument("--server-hostname", default="pjc-server")
    ap.add_argument("--cert-dir", required=True)
    ap.add_argument("--tcp-timeout-sec", type=float, default=3.0)
    ap.add_argument("--tls-timeout-sec", type=float, default=3.0)
    ap.add_argument("--output", required=True)
    ap.add_argument("--assert-allow", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    report = sod._two_party_tls_diagnostic({
        "job_id": args.job_id,
        "role": args.role,
        "peer_host": args.peer_host,
        "peer_port": args.peer_port,
        "server_hostname": args.server_hostname,
        "cert_dir": args.cert_dir,
        "tcp_timeout_sec": args.tcp_timeout_sec,
        "tls_timeout_sec": args.tls_timeout_sec,
    })["report"]
    readiness = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if report.get("decision") == "allow" else "fail",
        "job_id": args.job_id,
        "role": args.role,
        "peer_host": args.peer_host,
        "peer_port": args.peer_port,
        "server_hostname": args.server_hostname,
        "diagnostic": report,
        "ready": report.get("decision") == "allow",
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, readiness)
    print(json.dumps(readiness, ensure_ascii=False, indent=2))
    if args.assert_allow and not readiness["ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
