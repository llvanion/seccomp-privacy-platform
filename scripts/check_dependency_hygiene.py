#!/usr/bin/env python3
import argparse
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PY_REQ_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?\s*(==|~=|===)")
SKIP_PARTS = {
    ".git",
    ".venv",
    "bazel-private-join-and-compute",
    "bazel-bin",
    "bazel-out",
    "bazel-testlogs",
    "external",
    "target",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def rel_path(path: Path) -> str:
    return str(path.resolve().relative_to(REPO_ROOT))


def add_finding(findings: list[dict[str, Any]],
                *,
                severity: str,
                kind: str,
                path: Path,
                line: int | None,
                message: str) -> None:
    findings.append({
        "severity": severity,
        "kind": kind,
        "path": rel_path(path),
        "line": line,
        "message": message,
    })


def logical_requirement_lines(path: Path) -> list[tuple[int, str]]:
    logical: list[tuple[int, str]] = []
    current_line_no = 0
    current = ""
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not current:
            current_line_no = line_no
        if line.endswith("\\"):
            current += line[:-1].strip() + " "
            continue
        current += line
        logical.append((current_line_no, current.strip()))
        current = ""
    if current:
        logical.append((current_line_no, current.strip()))
    return logical


def check_requirements(path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for line_no, line in logical_requirement_lines(path):
        if line.startswith(("-r ", "--requirement ", "-c ", "--constraint ")):
            continue
        if line.startswith(("--index-url", "--extra-index-url", "--find-links", "--trusted-host")):
            continue
        requirement = line.split(" --hash=", 1)[0].strip()
        if not PY_REQ_PATTERN.match(requirement):
            add_finding(
                findings,
                severity="warn",
                kind="unpinned_python_requirement",
                path=path,
                line=line_no,
                message="Python requirement should use ==, ~=, or === pinning",
            )
    return findings


def dependency_version(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        version = value.get("version")
        return str(version) if version is not None else None
    return None


def dependency_uses_remote_source(value: Any) -> bool:
    return isinstance(value, dict) and any(key in value for key in ("git", "path"))


def check_cargo_toml(path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    lock_path = path.with_name("Cargo.lock")
    if not lock_path.is_file():
        add_finding(
            findings,
            severity="error",
            kind="missing_cargo_lock",
            path=path,
            line=None,
            message="Cargo.toml should have a sibling Cargo.lock for reproducible binary builds",
        )
    dependencies = data.get("dependencies", {})
    if not isinstance(dependencies, dict):
        return findings
    for name, value in dependencies.items():
        version = dependency_version(value)
        if version is None and not dependency_uses_remote_source(value):
            add_finding(
                findings,
                severity="warn",
                kind="unversioned_cargo_dependency",
                path=path,
                line=None,
                message=f"Cargo dependency {name} has no version constraint",
            )
        elif version is not None and version.strip() == "*":
            add_finding(
                findings,
                severity="error",
                kind="wildcard_cargo_dependency",
                path=path,
                line=None,
                message=f"Cargo dependency {name} uses wildcard version",
            )
        if dependency_uses_remote_source(value):
            add_finding(
                findings,
                severity="warn",
                kind="remote_or_path_cargo_dependency",
                path=path,
                line=None,
                message=f"Cargo dependency {name} uses git/path source; verify reproducibility and trust boundary",
            )
    return findings


def discover_files() -> tuple[list[Path], list[Path]]:
    requirement_files = sorted(REPO_ROOT.glob("**/requirements*.txt"))
    requirement_files = [
        path
        for path in requirement_files
        if not any(part in SKIP_PARTS for part in path.relative_to(REPO_ROOT).parts)
    ]
    cargo_files = sorted(REPO_ROOT.glob("**/Cargo.toml"))
    cargo_files = [
        path
        for path in cargo_files
        if not any(part in SKIP_PARTS for part in path.relative_to(REPO_ROOT).parts)
    ]
    return requirement_files, cargo_files


def summarize(findings: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "error": sum(1 for item in findings if item.get("severity") == "error"),
        "warn": sum(1 for item in findings if item.get("severity") == "warn"),
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Check local dependency manifests for basic reproducibility hygiene.")
    ap.add_argument("--fail-on-warn", action="store_true")
    ap.add_argument("--allow-findings", action="store_true")
    ap.add_argument("--output", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    requirement_files, cargo_files = discover_files()
    findings: list[dict[str, Any]] = []
    for path in requirement_files:
        findings.extend(check_requirements(path))
    for path in cargo_files:
        findings.extend(check_cargo_toml(path))
    summary = summarize(findings)
    status = "error" if summary["error"] else ("warn" if summary["warn"] else "ok")
    report = {
        "schema": "dependency_hygiene/v1",
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "status": status,
        "summary": {
            **summary,
            "requirements_files": [rel_path(path) for path in requirement_files],
            "cargo_toml_files": [rel_path(path) for path in cargo_files],
        },
        "findings": findings,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = REPO_ROOT / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.allow_findings:
        return 0
    if summary["error"]:
        return 1
    if args.fail_on_warn and summary["warn"]:
        return 1
    return 0


if __name__ == "__main__":
    if sys.version_info < (3, 11):
        raise SystemExit("[ERROR] Python 3.11+ is required for tomllib")
    raise SystemExit(main())
