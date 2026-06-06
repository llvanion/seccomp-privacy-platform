#!/usr/bin/env python3
"""Resolve and verify the effective PJC binary directory."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "pjc_binary_capability_gate/v1"
REPO_ROOT = Path(__file__).resolve().parents[1]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")


def run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def candidate_report(path: Path | None, binary: str) -> dict[str, Any]:
    if path is None:
        return {"path": None, "exists": False, "mtime_utc": None, "supports_streaming_flag": None}
    target = path / "private_join_and_compute" / binary
    if not target.is_file() or not os.access(target, os.X_OK):
        return {"path": str(target), "exists": False, "mtime_utc": None, "supports_streaming_flag": None}
    supports = False
    for flag in ("--helpfull", "--help"):
        res = run([str(target), flag])
        text = (res.stdout or "") + (res.stderr or "")
        if "--grpc_stream_chunk_elements" in text:
            supports = True
            break
    return {
        "path": str(target),
        "exists": True,
        "mtime_utc": iso_mtime(target),
        "supports_streaming_flag": supports,
    }


def same_path(a: Path | None, b: Path | None) -> bool:
    if a is None or b is None:
        return False
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return str(a) == str(b)


def bazel_bin_dir(workspace: Path) -> Path | None:
    if not shutil_which("bazel"):
        return None
    res = run(["bazel", "info", "bazel-bin"], cwd=workspace)
    if res.returncode != 0:
        return None
    text = res.stdout.strip()
    return Path(text) if text else None


def shutil_which(name: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def source_info(path: Path) -> dict[str, Any]:
    return {"path": str(path), "exists": path.exists(), "mtime_utc": iso_mtime(path)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", default=str(REPO_ROOT / "a-psi" / "private-join-and-compute"))
    ap.add_argument("--requested-bin-dir", default="")
    ap.add_argument("--require-streaming", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--print-resolved-bin-dir", action="store_true")
    args = ap.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    requested = Path(args.requested_bin_dir).expanduser().resolve() if args.requested_bin_dir else None
    convenience = workspace / "bazel-bin"
    requested_server = candidate_report(requested, "server") if requested is not None else None
    requested_client = candidate_report(requested, "client") if requested is not None else None
    real_bazel = bazel_bin_dir(workspace)

    server_source = workspace / "private_join_and_compute" / "server.cc"
    client_source = workspace / "private_join_and_compute" / "client.cc"
    sources = {
        "server_cc": source_info(server_source),
        "client_cc": source_info(client_source),
    }
    newest_source_mtime = max(
        [path.stat().st_mtime for path in (server_source, client_source) if path.exists()],
        default=0.0,
    )

    candidates: list[Path] = []
    if requested is not None:
        if same_path(requested, convenience) and real_bazel is not None and not same_path(requested, real_bazel):
            candidates.append(real_bazel)
        candidates.append(requested)
    else:
        if real_bazel is not None:
            candidates.append(real_bazel)
        candidates.append(convenience)

    seen: set[str] = set()
    unique_candidates: list[Path] = []
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)

    resolved_bin_dir: Path | None = None
    resolved_server: dict[str, Any] | None = None
    resolved_client: dict[str, Any] | None = None
    findings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    for candidate in unique_candidates:
        if requested is not None and same_path(candidate, requested) and requested_server is not None and requested_client is not None:
            server = requested_server
            client = requested_client
        else:
            server = candidate_report(candidate, "server")
            client = candidate_report(candidate, "client")
        streaming_ok = (
            server["supports_streaming_flag"] is True
            and client["supports_streaming_flag"] is True
        )
        binaries_present = server["exists"] and client["exists"]
        if not binaries_present:
            continue
        if args.require_streaming and not streaming_ok:
            continue
        resolved_bin_dir = candidate
        resolved_server = server
        resolved_client = client
        break

    if resolved_bin_dir is None:
        fallback = unique_candidates[0] if unique_candidates else None
        resolved_bin_dir = fallback
        resolved_server = candidate_report(fallback, "server")
        resolved_client = candidate_report(fallback, "client")

    assert resolved_server is not None
    assert resolved_client is not None

    checks.append({
        "name": "real_bazel_bin_dir_detected",
        "status": "ok" if real_bazel is not None else "skip",
        "expected": "bazel info bazel-bin resolves a current output directory",
        "actual": str(real_bazel) if real_bazel is not None else None,
    })
    checks.append({
        "name": "resolved_binaries_present",
        "status": "ok" if resolved_server["exists"] and resolved_client["exists"] else "fail",
        "expected": "resolved bin dir contains executable server and client binaries",
        "actual": {
            "resolved_bin_dir": str(resolved_bin_dir) if resolved_bin_dir is not None else None,
            "server_exists": resolved_server["exists"],
            "client_exists": resolved_client["exists"],
        },
    })
    checks.append({
        "name": "server_streaming_flag",
        "status": "ok" if resolved_server["supports_streaming_flag"] is True else "fail" if args.require_streaming else "skip",
        "expected": "server binary supports --grpc_stream_chunk_elements when streaming is required",
        "actual": resolved_server["supports_streaming_flag"],
    })
    checks.append({
        "name": "client_streaming_flag",
        "status": "ok" if resolved_client["supports_streaming_flag"] is True else "fail" if args.require_streaming else "skip",
        "expected": "client binary supports --grpc_stream_chunk_elements when streaming is required",
        "actual": resolved_client["supports_streaming_flag"],
    })

    binary_mtimes = []
    if resolved_server["path"] and Path(resolved_server["path"]).exists():
        binary_mtimes.append(Path(resolved_server["path"]).stat().st_mtime)
    if resolved_client["path"] and Path(resolved_client["path"]).exists():
        binary_mtimes.append(Path(resolved_client["path"]).stat().st_mtime)
    binaries_current = bool(binary_mtimes) and min(binary_mtimes) >= newest_source_mtime
    checks.append({
        "name": "binaries_not_older_than_sources",
        "status": "ok" if binaries_current else "fail",
        "expected": "resolved binaries are at least as new as current server.cc/client.cc sources",
        "actual": {
            "newest_source_mtime_utc": datetime.fromtimestamp(newest_source_mtime, timezone.utc).isoformat().replace("+00:00", "Z") if newest_source_mtime else None,
            "server_binary_mtime_utc": resolved_server["mtime_utc"],
            "client_binary_mtime_utc": resolved_client["mtime_utc"],
        },
    })

    if requested is not None and same_path(requested, convenience) and real_bazel is not None and not same_path(requested, real_bazel):
        findings.append({
            "kind": "stale_convenience_bazel_bin",
            "message": "requested workspace bazel-bin convenience directory differs from the live Bazel output directory",
            "expected": str(real_bazel),
            "actual": str(requested),
        })
    if args.require_streaming and resolved_server["supports_streaming_flag"] is not True:
        findings.append({
            "kind": "server_missing_streaming_flag",
            "message": "resolved server binary does not advertise --grpc_stream_chunk_elements",
            "expected": True,
            "actual": resolved_server["supports_streaming_flag"],
        })
    if args.require_streaming and resolved_client["supports_streaming_flag"] is not True:
        findings.append({
            "kind": "client_missing_streaming_flag",
            "message": "resolved client binary does not advertise --grpc_stream_chunk_elements",
            "expected": True,
            "actual": resolved_client["supports_streaming_flag"],
        })
    if not binaries_current:
        findings.append({
            "kind": "binary_source_drift",
            "message": "resolved binaries are older than the current PJC sources",
            "expected": "rebuild binaries after source changes",
            "actual": {
                "resolved_bin_dir": str(resolved_bin_dir) if resolved_bin_dir is not None else None,
                "server_binary_mtime_utc": resolved_server["mtime_utc"],
                "client_binary_mtime_utc": resolved_client["mtime_utc"],
                "server_source_mtime_utc": sources["server_cc"]["mtime_utc"],
                "client_source_mtime_utc": sources["client_cc"]["mtime_utc"],
            },
        })

    status = "ok" if all(check["status"] in {"ok", "skip"} for check in checks) else "fail"
    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": status,
        "workspace": str(workspace),
        "requested_bin_dir": str(requested) if requested is not None else None,
        "convenience_bin_dir": str(convenience),
        "real_bazel_bin_dir": str(real_bazel) if real_bazel is not None else None,
        "resolved_bin_dir": str(resolved_bin_dir) if resolved_bin_dir is not None else None,
        "require_streaming": bool(args.require_streaming),
        "checks": checks,
        "findings": findings,
        "binaries": {
            "server": resolved_server,
            "client": resolved_client,
        },
        "sources": sources,
    }

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.print_resolved_bin_dir:
        if status != "ok" or resolved_bin_dir is None:
            return 1
        print(str(resolved_bin_dir))
        return 0
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
