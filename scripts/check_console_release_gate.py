#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "console_release_gate_check/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def add_finding(findings: list[dict[str, Any]], *, check: str, path: Path, message: str, expected: Any, actual: Any) -> None:
    findings.append(
        {
            "check": check,
            "path": str(path.relative_to(REPO_ROOT)),
            "message": message,
            "expected": expected,
            "actual": actual,
        }
    )


def section_after(text: str, marker: str, *, stop_markers: list[str] | None = None) -> str:
    idx = text.find(marker)
    if idx < 0:
        return ""
    end = len(text)
    for stop in stop_markers or []:
        stop_idx = text.find(stop, idx + len(marker))
        if stop_idx >= 0:
            end = min(end, stop_idx)
    return text[idx:end]


def line_near(section: str, needle: str, forbidden: str, *, window: int = 5) -> bool:
    lines = section.splitlines()
    for idx, line in enumerate(lines):
        if needle in line:
            nearby = "\n".join(lines[max(0, idx - window) : idx + window + 1])
            if forbidden in nearby:
                return True
    return False


def command_present(text: str, command: str) -> bool:
    compact = re.sub(r"\s+", " ", text)
    return command in compact or command.replace(" ", "  ") in text


def package_dependency_summary(package_json: dict[str, Any], lockfile: dict[str, Any]) -> dict[str, Any]:
    root_pkg = lockfile.get("packages", {}).get("", {})
    package_deps = package_json.get("dependencies", {})
    package_dev_deps = package_json.get("devDependencies", {})
    lock_deps = root_pkg.get("dependencies", {})
    lock_dev_deps = root_pkg.get("devDependencies", {})
    return {
        "package_name": package_json.get("name"),
        "lockfile_name": root_pkg.get("name"),
        "lockfile_version": lockfile.get("lockfileVersion"),
        "dependency_count": len(package_deps),
        "dev_dependency_count": len(package_dev_deps),
        "lock_dependency_count": len(lock_deps),
        "lock_dev_dependency_count": len(lock_dev_deps),
        "dependencies_match": package_deps == lock_deps,
        "dev_dependencies_match": package_dev_deps == lock_dev_deps,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check operator console release/supply-chain gates.")
    parser.add_argument("--out", default="", help="Optional output JSON path.")
    args = parser.parse_args()

    findings: list[dict[str, Any]] = []
    package_json_path = REPO_ROOT / "console" / "package.json"
    lockfile_path = REPO_ROOT / "console" / "package-lock.json"
    release_workflow_path = REPO_ROOT / ".github" / "workflows" / "release.yml"
    ci_workflow_path = REPO_ROOT / ".github" / "workflows" / "json-contracts.yml"
    ci_smoke_path = REPO_ROOT / "scripts" / "check_ci_smoke.sh"

    package_json = load_json(package_json_path)
    lockfile: dict[str, Any] = {}
    if not lockfile_path.exists():
        add_finding(
            findings,
            check="lockfile_exists",
            path=lockfile_path,
            message="console package-lock.json is required for reproducible npm ci installs",
            expected="committed console/package-lock.json",
            actual="missing",
        )
    else:
        lockfile = load_json(lockfile_path)

    dependency_summary = package_dependency_summary(package_json, lockfile) if lockfile else {
        "package_name": package_json.get("name"),
        "lockfile_name": None,
        "lockfile_version": None,
        "dependency_count": len(package_json.get("dependencies", {})),
        "dev_dependency_count": len(package_json.get("devDependencies", {})),
        "lock_dependency_count": 0,
        "lock_dev_dependency_count": 0,
        "dependencies_match": False,
        "dev_dependencies_match": False,
    }

    if lockfile:
        if dependency_summary["lockfile_version"] != 3:
            add_finding(
                findings,
                check="lockfile_version",
                path=lockfile_path,
                message="console lockfile must use npm lockfileVersion 3",
                expected=3,
                actual=dependency_summary["lockfile_version"],
            )
        if dependency_summary["package_name"] != dependency_summary["lockfile_name"]:
            add_finding(
                findings,
                check="lockfile_root_name",
                path=lockfile_path,
                message="console lockfile root package name must match package.json",
                expected=dependency_summary["package_name"],
                actual=dependency_summary["lockfile_name"],
            )
        for field, label in (
            ("dependencies_match", "dependencies"),
            ("dev_dependencies_match", "devDependencies"),
        ):
            if not dependency_summary[field]:
                add_finding(
                    findings,
                    check=f"lockfile_{label}_match",
                    path=lockfile_path,
                    message=f"console lockfile root {label} must match package.json",
                    expected=package_json.get(label, {}),
                    actual=lockfile.get("packages", {}).get("", {}).get(label, {}),
                )

    release_text = release_workflow_path.read_text(encoding="utf-8")
    release_console = section_after(
        release_text,
        "  build-console:",
        stop_markers=["  build-source-tarball:", "  build-docker-image:"],
    )
    if not release_console:
        add_finding(
            findings,
            check="release_console_job",
            path=release_workflow_path,
            message="release workflow must define build-console job",
            expected="build-console job",
            actual="missing",
        )
    else:
        if "actions/setup-node@v4" not in release_console:
            add_finding(
                findings,
                check="release_setup_node",
                path=release_workflow_path,
                message="release console job must configure Node through actions/setup-node@v4",
                expected="actions/setup-node@v4",
                actual="missing",
            )
        if "npm ci --no-audit --no-fund" not in release_console:
            add_finding(
                findings,
                check="release_npm_ci",
                path=release_workflow_path,
                message="release console job must install through npm ci",
                expected="npm ci --no-audit --no-fund",
                actual="missing",
            )
        if re.search(r"\bnpm\s+install\b", release_console):
            add_finding(
                findings,
                check="release_no_npm_install",
                path=release_workflow_path,
                message="release console job must not fall back to npm install",
                expected="no npm install fallback",
                actual="npm install present",
            )
        if "run: npm run typecheck" not in release_console:
            add_finding(
                findings,
                check="release_typecheck",
                path=release_workflow_path,
                message="release console job must run typecheck",
                expected="run: npm run typecheck",
                actual="missing",
            )
        if line_near(release_console, "npm run typecheck", "continue-on-error: true"):
            add_finding(
                findings,
                check="release_typecheck_blocking",
                path=release_workflow_path,
                message="release console typecheck must be blocking",
                expected="no continue-on-error near typecheck",
                actual="continue-on-error: true",
            )
        if "run: npm run build:strict" not in release_console:
            add_finding(
                findings,
                check="release_strict_build",
                path=release_workflow_path,
                message="release console job must run strict build",
                expected="run: npm run build:strict",
                actual="missing",
            )

    ci_text = ci_workflow_path.read_text(encoding="utf-8")
    ci_expectations = {
        "ci_setup_node": "actions/setup-node@v4",
        "ci_npm_ci": "npm --prefix console ci --no-audit --no-fund",
        "ci_typecheck": "npm --prefix console run typecheck",
        "ci_strict_build": "npm --prefix console run build:strict",
    }
    for check, command in ci_expectations.items():
        if command not in ci_text:
            add_finding(
                findings,
                check=check,
                path=ci_workflow_path,
                message="CI smoke workflow must exercise console release prerequisites",
                expected=command,
                actual="missing",
            )
    if re.search(r"\bnpm\s+(?:--prefix\s+console\s+)?install\b", ci_text):
        add_finding(
            findings,
            check="ci_no_npm_install",
            path=ci_workflow_path,
            message="CI smoke workflow must not use npm install for console dependencies",
            expected="npm ci only",
            actual="npm install present",
        )

    ci_smoke_text = ci_smoke_path.read_text(encoding="utf-8")
    for command in (
        "scripts/check_console_release_gate.py",
        "python3 scripts/check_console_release_gate.py",
    ):
        if command_present(ci_smoke_text, command):
            break
    else:
        add_finding(
            findings,
            check="local_ci_release_gate",
            path=ci_smoke_path,
            message="local CI smoke must run the console release-gate check",
            expected="python3 scripts/check_console_release_gate.py",
            actual="missing",
        )

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "status": "fail" if findings else "ok",
        "summary": {
            "lockfile_present": lockfile_path.exists(),
            "release_console_job_present": bool(release_console),
            "ci_workflow_checks_console": all(command in ci_text for command in ci_expectations.values()),
            "local_ci_runs_release_gate": not any(f["check"] == "local_ci_release_gate" for f in findings),
            "finding_count": len(findings),
        },
        "package": dependency_summary,
        "release_workflow": {
            "path": str(release_workflow_path.relative_to(REPO_ROOT)),
            "uses_setup_node": "actions/setup-node@v4" in release_console,
            "uses_npm_ci": "npm ci --no-audit --no-fund" in release_console,
            "uses_npm_install": bool(re.search(r"\bnpm\s+install\b", release_console)),
            "typecheck_blocking": "run: npm run typecheck" in release_console
            and not line_near(release_console, "npm run typecheck", "continue-on-error: true"),
            "uses_strict_build": "run: npm run build:strict" in release_console,
        },
        "ci_workflow": {
            "path": str(ci_workflow_path.relative_to(REPO_ROOT)),
            "uses_setup_node": "actions/setup-node@v4" in ci_text,
            "uses_npm_ci": "npm --prefix console ci --no-audit --no-fund" in ci_text,
            "runs_typecheck": "npm --prefix console run typecheck" in ci_text,
            "runs_strict_build": "npm --prefix console run build:strict" in ci_text,
            "uses_npm_install": bool(re.search(r"\bnpm\s+(?:--prefix\s+console\s+)?install\b", ci_text)),
        },
        "findings": findings,
    }

    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
