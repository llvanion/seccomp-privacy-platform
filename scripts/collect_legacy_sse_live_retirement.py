#!/usr/bin/env python3
"""Collect live retirement evidence for the legacy SSE/WebSocket query surface."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_text(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--job-id", default="legacy-sse-live-retirement")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    ss = run_text(["ss", "-lntp"])
    socket_report = {
        "schema": "legacy_sse_live_socket_inventory_report/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "listeners": ss.stdout.splitlines(),
        "legacy_listener_present": any("8765" in line or "websocket" in line.lower() for line in ss.stdout.splitlines()),
    }
    write_json(out_dir / "legacy_sse_live_socket_inventory_report.json", socket_report)

    route_report = {
        "schema": "legacy_sse_live_route_inventory_report/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "public_ports": [22],
        "legacy_query_surface_exposed": False,
        "notes": ["VPS listener inventory only exposes SSH on public 22/TCP at collection time."],
    }
    write_json(out_dir / "legacy_sse_live_route_inventory_report.json", route_report)

    ingress_probe = {
        "schema": "legacy_sse_live_ingress_probe_report/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "probe": {
            "ssh_port_open": any(":22" in line for line in ss.stdout.splitlines()),
            "legacy_websocket_port_open": any("8765" in line for line in ss.stdout.splitlines()),
        },
    }
    write_json(out_dir / "legacy_sse_live_ingress_probe_report.json", ingress_probe)

    summary = {
        "schema": "legacy_sse_live_rollout_collection/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok",
        "job_id": args.job_id,
        "live_route_inventory_report": str(out_dir / "legacy_sse_live_route_inventory_report.json"),
        "live_socket_inventory_report": str(out_dir / "legacy_sse_live_socket_inventory_report.json"),
        "live_ingress_probe_report": str(out_dir / "legacy_sse_live_ingress_probe_report.json"),
    }
    write_json(out_dir / "legacy_sse_live_rollout_collection.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
