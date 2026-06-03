#!/usr/bin/env python3
"""Gate network-facing pickle exposure in the SSE frontend.

The SSE WebSocket protocol must use the JSON/base64 codec in
``frontend.common.wire``. Pickle remains allowed only for trusted local
``service_meta`` persistence, not for WebSocket messages or message content.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SSE_ROOT = REPO_ROOT / "sse"
FRONTEND_ROOTS = [
    REPO_ROOT / "sse" / "frontend" / "server",
    REPO_ROOT / "sse" / "frontend" / "client",
]
NETWORK_EXAMPLE_FILES = [
    REPO_ROOT / "sse" / "example_usage.py",
]
PICKLE_CALLS = {"loads", "dumps", "load", "dump"}

LOCAL_PERSISTENCE_FILES = {
    Path("sse/frontend/server/services/file_manager.py"),
    Path("sse/frontend/client/services/file_manager.py"),
}


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def pickle_findings(path: Path) -> list[dict[str, Any]]:
    tree = ast.parse(load_text(path), filename=rel(path))
    findings: list[dict[str, Any]] = []
    module_aliases: set[str] = set()
    imported_functions: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pickle":
                    alias_name = alias.asname or alias.name
                    module_aliases.add(alias_name)
                    findings.append({"line": node.lineno, "call": f"import {alias_name}=pickle"})
        elif isinstance(node, ast.ImportFrom) and node.module == "pickle":
            for alias in node.names:
                alias_name = alias.asname or alias.name
                findings.append({"line": node.lineno, "call": f"from pickle import {alias.name}"})
                if alias.name == "*":
                    imported_functions["*"] = "*"
                elif alias.name in PICKLE_CALLS:
                    imported_functions[alias_name] = alias.name

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr not in PICKLE_CALLS:
                continue
            base = func.value
            if isinstance(base, ast.Name) and base.id in module_aliases:
                findings.append({"line": node.lineno, "call": f"pickle.{func.attr}"})
        elif isinstance(func, ast.Name):
            if "*" in imported_functions and func.id in PICKLE_CALLS:
                findings.append({"line": node.lineno, "call": f"pickle.{func.id}"})
            elif func.id in imported_functions:
                findings.append({"line": node.lineno, "call": f"pickle.{imported_functions[func.id]}"})
    return findings


def check_wire_roundtrip(errors: list[str]) -> None:
    sys.path.insert(0, str(SSE_ROOT))
    try:
        from frontend.common.wire import (
            WireProtocolError,
            decode_content,
            dumps_message,
            encode_content,
            loads_message,
        )
    except Exception as exc:
        errors.append(f"wire codec import failed: {exc}")
        return

    try:
        content = encode_content({"tokens": [{"token_bytes": b"abc", "token_digest": b"\x00\x01"}]})
        message = {
            "type": "multi_token",
            "sid": "sid1",
            "content": content,
            "request_id": "req1",
        }
        decoded = loads_message(dumps_message(message))
        if decoded != message:
            errors.append("wire message roundtrip changed decoded payload")
        decoded_content = decode_content(decoded["content"])
        if decoded_content != {"tokens": [{"token_bytes": b"abc", "token_digest": b"\x00\x01"}]}:
            errors.append("wire structured content roundtrip changed decoded payload")
        try:
            loads_message('{"schema":"bad","payload":{}}')
        except WireProtocolError:
            pass
        else:
            errors.append("wire codec accepted unsupported schema")
        try:
            loads_message('{"schema":"sse.frontend.ws/v1","payload":{"x":NaN}}')
        except WireProtocolError:
            pass
        else:
            errors.append("wire codec accepted non-finite JSON constant")
        try:
            dumps_message({"x": float("nan")})
        except ValueError:
            pass
        else:
            errors.append("wire codec emitted non-finite JSON number")
    except Exception as exc:
        errors.append(f"wire codec roundtrip failed: {exc}")


def main() -> int:
    findings: list[dict[str, Any]] = []
    errors: list[str] = []

    global_config = REPO_ROOT / "sse" / "global_config.py"
    run_server = REPO_ROOT / "sse" / "run_server.py"
    connector = REPO_ROOT / "sse" / "frontend" / "server" / "connector.py"

    global_config_text = load_text(global_config)
    required_global_tokens = [
        "SSE_ALLOW_LEGACY_PICKLE_WS",
        "assert_legacy_pickle_bind_allowed",
        "is_loopback_host",
    ]
    for token in required_global_tokens:
        if token not in global_config_text:
            errors.append(f"missing {token} in {rel(global_config)}")

    for guarded_path in (run_server, connector):
        if "assert_legacy_pickle_bind_allowed" not in load_text(guarded_path):
            errors.append(f"missing legacy pickle bind guard in {rel(guarded_path)}")

    wire_codec = REPO_ROOT / "sse" / "frontend" / "common" / "wire.py"
    wire_text = load_text(wire_codec)
    for token in ("WIRE_SCHEMA", "dumps_message", "loads_message", "encode_content", "decode_content"):
        if token not in wire_text:
            errors.append(f"missing {token} in {rel(wire_codec)}")
    check_wire_roundtrip(errors)

    for root in FRONTEND_ROOTS:
        paths = sorted(root.rglob("*.py"))
        if root == FRONTEND_ROOTS[-1]:
            paths.extend(NETWORK_EXAMPLE_FILES)
        for path in paths:
            usages = pickle_findings(path)
            if not usages:
                continue
            relative = Path(rel(path))
            if relative in LOCAL_PERSISTENCE_FILES:
                classification = "local_persistence_pickle"
            else:
                classification = "unexpected_network_pickle"
                errors.append(f"unexpected network-facing pickle use in {relative}")
            findings.append({
                "path": str(relative),
                "classification": classification,
                "calls": usages,
            })

    status = "fail" if errors else "ok"
    report = {
        "schema": "network_pickle_gate/v1",
        "status": status,
        "summary": {
            "allowed_local_persistence_files": sorted(str(p) for p in LOCAL_PERSISTENCE_FILES),
            "finding_count": len(findings),
            "error_count": len(errors),
        },
        "findings": findings,
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
