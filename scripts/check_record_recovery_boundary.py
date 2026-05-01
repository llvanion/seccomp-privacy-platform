#!/usr/bin/env python3
import argparse
import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

SHIMS = {
    "sse/toolkit/encrypted_record_store.py": "services.record_recovery.encrypted_record_store",
    "sse/toolkit/record_recovery_authz.py": "services.record_recovery.authz",
    "sse/toolkit/record_recovery_client.py": "services.record_recovery.client",
    "sse/toolkit/record_recovery_common.py": "services.record_recovery.common",
    "sse/toolkit/record_recovery_http_service.py": "services.record_recovery.http_service",
    "sse/toolkit/record_recovery_service.py": "services.record_recovery.service",
    "sse/toolkit/record_recovery_service_config.py": "services.record_recovery.config",
    "sse/toolkit/record_recovery_worker.py": "services.record_recovery.worker",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def add_finding(findings: list[dict[str, Any]], *, path: str, kind: str, message: str, line: int | None = None) -> None:
    findings.append({
        "severity": "error",
        "kind": kind,
        "path": path,
        "line": line,
        "message": message,
    })


def imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def check_shim(relative_path: str, expected_module: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    path = REPO_ROOT / relative_path
    if not path.is_file():
        add_finding(findings, path=relative_path, kind="missing_shim", message="expected compatibility shim is missing")
        return findings

    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as e:
        add_finding(findings, path=relative_path, kind="syntax_error", message=str(e), line=e.lineno)
        return findings

    if "Compatibility shim" not in text:
        add_finding(
            findings,
            path=relative_path,
            kind="missing_shim_marker",
            message="shim should explicitly identify itself as a compatibility shim",
        )

    modules = imported_modules(tree)
    if expected_module not in modules:
        add_finding(
            findings,
            path=relative_path,
            kind="wrong_implementation_import",
            message=f"shim should re-export from {expected_module}",
        )

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            add_finding(
                findings,
                path=relative_path,
                kind="shim_contains_implementation",
                line=getattr(node, "lineno", None),
                message="compatibility shim should not define functions or classes",
            )
    return findings


def build_result(findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "record_recovery_boundary_check/v1",
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "status": "ok" if not findings else "fail",
        "summary": {
            "checked_shims": len(SHIMS),
            "error": len(findings),
        },
        "implementation_owner": "services.record_recovery",
        "legacy_shim_package": "sse.toolkit",
        "findings": findings,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Verify record-recovery implementation ownership boundaries.")
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-findings", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    findings: list[dict[str, Any]] = []
    for relative_path, expected_module in SHIMS.items():
        findings.extend(check_shim(relative_path, expected_module))

    result = build_result(findings)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)

    if findings and not args.allow_findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
