#!/usr/bin/env python3
"""Gate legacy SSE WebSocket production retirement.

The historical SSE WebSocket frontend is allowed only as a local/demo
compatibility interface. Production mode must fail closed before the server can
bind, even on loopback and even if the demo wide-bind override is present.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SSE_ROOT = REPO_ROOT / "sse"
SCHEMA_ID = "legacy_sse_production_gate/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def python_check(source: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    full_env["PYTHONPATH"] = str(SSE_ROOT)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=str(REPO_ROOT),
        env=full_env,
        capture_output=True,
        text=True,
    )


def add_finding(
    findings: list[dict[str, Any]],
    *,
    kind: str,
    message: str,
    expected: Any,
    actual: Any,
    path: Path | None = None,
) -> None:
    item: dict[str, Any] = {
        "kind": kind,
        "message": message,
        "expected": expected,
        "actual": actual,
    }
    if path is not None:
        item["path"] = rel(path)
    findings.append(item)


def main() -> int:
    ap = argparse.ArgumentParser(description="Check legacy SSE WebSocket production retirement gates.")
    ap.add_argument("--out", default="", help=f"Path to write {SCHEMA_ID} JSON report (default: stdout)")
    args = ap.parse_args()

    findings: list[dict[str, Any]] = []
    global_config = SSE_ROOT / "global_config.py"
    run_server = SSE_ROOT / "run_server.py"
    connector = SSE_ROOT / "frontend" / "server" / "connector.py"
    dockerfile = SSE_ROOT / "Dockerfile"

    global_text = load_text(global_config)
    for token in ("SSE_PRODUCTION_MODE", "production_mode_enabled", "legacy SSE WebSocket is retired for production"):
        if token not in global_text:
            add_finding(
                findings,
                kind="missing_production_retirement_guard",
                message="global_config.py must define and enforce legacy SSE production retirement",
                expected=token,
                actual="missing",
                path=global_config,
            )

    for guarded in (run_server, connector):
        text = load_text(guarded)
        if "assert_legacy_pickle_bind_allowed" not in text:
            add_finding(
                findings,
                kind="missing_startup_guard",
                message="legacy SSE startup path does not call the bind/production guard",
                expected="assert_legacy_pickle_bind_allowed",
                actual="missing",
                path=guarded,
            )

    production_cases = [
        (
            "production_loopback_denied",
            {"SSE_PRODUCTION_MODE": "1"},
            "ServerConfig.assert_legacy_pickle_bind_allowed('127.0.0.1')",
        ),
        (
            "production_wide_bind_override_denied",
            {"SSE_PRODUCTION_MODE": "1", "SSE_ALLOW_LEGACY_PICKLE_WS": "1"},
            "ServerConfig.assert_legacy_pickle_bind_allowed('0.0.0.0')",
        ),
    ]
    production_results: dict[str, dict[str, Any]] = {}
    for name, env, expr in production_cases:
        proc = python_check(
            "from global_config import ServerConfig\n"
            "try:\n"
            f"    {expr}\n"
            "except RuntimeError as exc:\n"
            "    print(str(exc))\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit(7)\n",
            env=env,
        )
        production_results[name] = {
            "exit_code": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
        if proc.returncode != 0 or "retired for production" not in proc.stdout:
            add_finding(
                findings,
                kind="production_start_allowed",
                message=f"legacy SSE startup was not denied for {name}",
                expected="RuntimeError containing retired for production",
                actual=production_results[name],
                path=global_config,
            )

    demo_loopback = python_check(
        "from global_config import ServerConfig\n"
        "ServerConfig.assert_legacy_pickle_bind_allowed('127.0.0.1')\n",
        env={"SSE_PRODUCTION_MODE": "0"},
    )
    demo_wide = python_check(
        "from global_config import ServerConfig\n"
        "ServerConfig.assert_legacy_pickle_bind_allowed('0.0.0.0')\n",
        env={"SSE_PRODUCTION_MODE": "0", "SSE_ALLOW_LEGACY_PICKLE_WS": "1"},
    )
    demo_wide_without_override = python_check(
        "from global_config import ServerConfig\n"
        "try:\n"
        "    ServerConfig.assert_legacy_pickle_bind_allowed('0.0.0.0')\n"
        "except RuntimeError as exc:\n"
        "    print(str(exc))\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(7)\n",
        env={"SSE_PRODUCTION_MODE": "0"},
    )
    demo_results = {
        "demo_loopback_exit_code": demo_loopback.returncode,
        "demo_wide_override_exit_code": demo_wide.returncode,
        "demo_wide_without_override_exit_code": demo_wide_without_override.returncode,
        "demo_wide_without_override_stdout": demo_wide_without_override.stdout.strip(),
    }
    if demo_loopback.returncode != 0:
        add_finding(
            findings,
            kind="demo_loopback_broken",
            message="local demo loopback startup should remain available outside production mode",
            expected=0,
            actual=demo_loopback.returncode,
            path=global_config,
        )
    if demo_wide.returncode != 0:
        add_finding(
            findings,
            kind="demo_override_broken",
            message="explicit demo wide-bind override should remain available outside production mode",
            expected=0,
            actual=demo_wide.returncode,
            path=global_config,
        )
    if demo_wide_without_override.returncode != 0 or "refusing to bind to non-loopback" not in demo_wide_without_override.stdout:
        add_finding(
            findings,
            kind="wide_bind_without_override_allowed",
            message="non-loopback demo bind must still require explicit override",
            expected="RuntimeError containing refusing to bind to non-loopback",
            actual=demo_results,
            path=global_config,
        )

    docker_text = load_text(dockerfile) if dockerfile.exists() else ""
    docker_checks = {
        "sets_production_mode": "SSE_PRODUCTION_MODE=1" in docker_text,
        "runs_legacy_server": "run_server.py start" in docker_text,
    }
    if docker_checks["runs_legacy_server"] and not docker_checks["sets_production_mode"]:
        add_finding(
            findings,
            kind="docker_legacy_entrypoint_not_retired",
            message="SSE Docker image starts the legacy WebSocket without production retirement enabled",
            expected="ENV SSE_PRODUCTION_MODE=1 before CMD",
            actual=docker_checks,
            path=dockerfile,
        )

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "status": "fail" if findings else "ok",
        "summary": {
            "production_mode_env": "SSE_PRODUCTION_MODE",
            "demo_wide_bind_override_env": "SSE_ALLOW_LEGACY_PICKLE_WS",
            "finding_count": len(findings),
        },
        "checks": {
            "production_cases": production_results,
            "demo_cases": demo_results,
            "docker": docker_checks,
        },
        "findings": findings,
    }

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
