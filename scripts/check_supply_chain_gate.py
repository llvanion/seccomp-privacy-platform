#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "supply_chain_evidence/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def add_finding(
    findings: list[dict[str, Any]],
    *,
    severity: str,
    check: str,
    path: Path | None,
    message: str,
    expected: Any,
    actual: Any,
) -> None:
    findings.append(
        {
            "severity": severity,
            "check": check,
            "path": rel(path) if path is not None else None,
            "message": message,
            "expected": expected,
            "actual": actual,
        }
    )


def requirement_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines: list[str] = []
    current = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            current += line[:-1].strip() + " "
            continue
        current += line
        lines.append(current.strip())
        current = ""
    if current:
        lines.append(current.strip())
    return lines


def parse_python_components(paths: list[Path]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    pattern = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?\s*(==|~=|===)\s*([^;\s]+)")
    for path in paths:
        for requirement in requirement_lines(path):
            if requirement.startswith(("-r ", "--requirement ", "-c ", "--constraint ")):
                continue
            match = pattern.match(requirement)
            name = requirement.split("=", 1)[0].strip() if not match else match.group(1)
            components.append(
                {
                    "ecosystem": "python",
                    "name": name,
                    "version": match.group(3) if match else None,
                    "source": rel(path),
                    "scope": "dev" if "dev" in path.name else "runtime",
                }
            )
    return components


def parse_npm_components(lockfile_path: Path) -> list[dict[str, Any]]:
    if not lockfile_path.exists():
        return []
    lockfile = load_json(lockfile_path)
    components: list[dict[str, Any]] = []
    for package_path, package in sorted((lockfile.get("packages") or {}).items()):
        if not package_path:
            continue
        name = package.get("name")
        if not name and package_path.startswith("node_modules/"):
            name = package_path[len("node_modules/") :]
        components.append(
            {
                "ecosystem": "npm",
                "name": name,
                "version": package.get("version"),
                "source": rel(lockfile_path),
                "scope": "dev" if package.get("dev") else "runtime",
            }
        )
    return components


def parse_cargo_components(lockfile_path: Path) -> list[dict[str, Any]]:
    if not lockfile_path.exists():
        return []
    data = tomllib.loads(lockfile_path.read_text(encoding="utf-8"))
    components: list[dict[str, Any]] = []
    for package in data.get("package", []):
        if not isinstance(package, dict):
            continue
        components.append(
            {
                "ecosystem": "cargo",
                "name": package.get("name"),
                "version": package.get("version"),
                "source": rel(lockfile_path),
                "scope": "runtime",
            }
        )
    return components


def command_in_text(text: str, command: str) -> bool:
    return command in text or re.sub(r"\s+", " ", command) in re.sub(r"\s+", " ", text)


def git_value(args: list[str]) -> str | None:
    result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local supply-chain, release, and test evidence gates.")
    parser.add_argument("--out", default="", help="Optional output JSON path.")
    args = parser.parse_args()

    findings: list[dict[str, Any]] = []
    runtime_req = REPO_ROOT / "sse" / "requirements.txt"
    dev_req = REPO_ROOT / "sse" / "requirements-dev.txt"
    console_package = REPO_ROOT / "console" / "package.json"
    console_lock = REPO_ROOT / "console" / "package-lock.json"
    bridge_cargo = REPO_ROOT / "bridge" / "Cargo.toml"
    bridge_lock = REPO_ROOT / "bridge" / "Cargo.lock"
    release_workflow = REPO_ROOT / ".github" / "workflows" / "release.yml"
    ci_workflow = REPO_ROOT / ".github" / "workflows" / "json-contracts.yml"
    ci_smoke = REPO_ROOT / "scripts" / "check_ci_smoke.sh"

    for path, check in (
        (runtime_req, "python_runtime_requirements"),
        (dev_req, "python_dev_requirements"),
        (console_package, "console_package_json"),
        (console_lock, "console_lockfile"),
        (bridge_cargo, "bridge_cargo_toml"),
        (bridge_lock, "bridge_cargo_lock"),
        (release_workflow, "release_workflow"),
        (ci_workflow, "ci_workflow"),
    ):
        if not path.exists():
            add_finding(
                findings,
                severity="error",
                check=check,
                path=path,
                message="required supply-chain artifact is missing",
                expected="present",
                actual="missing",
            )

    dev_requirements = requirement_lines(dev_req)
    if not any(line.lower().startswith("pytest") for line in dev_requirements):
        add_finding(
            findings,
            severity="error",
            check="pytest_dependency",
            path=dev_req,
            message="Python test dependency must be explicit",
            expected="pytest pinned in sse/requirements-dev.txt",
            actual=dev_requirements,
        )

    ci_text = ci_workflow.read_text(encoding="utf-8") if ci_workflow.exists() else ""
    ci_commands = {
        "ci_install_runtime_python": "python3 -m pip install -r sse/requirements.txt",
        "ci_install_dev_python": "python3 -m pip install -r sse/requirements-dev.txt",
        "ci_pytest": "python3 -m pytest sse/test",
        "ci_console_npm_ci": "npm --prefix console ci --no-audit --no-fund",
        "ci_console_typecheck": "npm --prefix console run typecheck",
        "ci_console_build": "npm --prefix console run build:strict",
    }
    for check, command in ci_commands.items():
        if not command_in_text(ci_text, command):
            add_finding(
                findings,
                severity="error",
                check=check,
                path=ci_workflow,
                message="CI workflow must run required supply-chain/test command",
                expected=command,
                actual="missing",
            )

    if re.search(r"\bnpm\s+(?:--prefix\s+console\s+)?install\b", ci_text):
        add_finding(
            findings,
            severity="error",
            check="ci_no_npm_install",
            path=ci_workflow,
            message="CI must use npm ci rather than npm install",
            expected="npm ci only",
            actual="npm install present",
        )

    release_text = release_workflow.read_text(encoding="utf-8") if release_workflow.exists() else ""
    if "npm ci --no-audit --no-fund" not in release_text:
        add_finding(
            findings,
            severity="error",
            check="release_console_npm_ci",
            path=release_workflow,
            message="release workflow must install console dependencies with npm ci",
            expected="npm ci --no-audit --no-fund",
            actual="missing",
        )
    if "npm run build:strict" not in release_text:
        add_finding(
            findings,
            severity="error",
            check="release_console_strict_build",
            path=release_workflow,
            message="release workflow must build console with strict build",
            expected="npm run build:strict",
            actual="missing",
        )
    if "npm run typecheck" in release_text and "continue-on-error: true" in release_text.split("npm run typecheck", 1)[0][-180:]:
        add_finding(
            findings,
            severity="error",
            check="release_typecheck_blocking",
            path=release_workflow,
            message="release typecheck must be blocking",
            expected="no continue-on-error near typecheck",
            actual="continue-on-error: true",
        )

    ci_smoke_text = ci_smoke.read_text(encoding="utf-8") if ci_smoke.exists() else ""
    for command in (
        "scripts/check_console_release_gate.py",
        "scripts/check_supply_chain_gate.py",
    ):
        if command not in ci_smoke_text:
            add_finding(
                findings,
                severity="error",
                check=f"local_ci_{Path(command).stem}",
                path=ci_smoke,
                message="local CI smoke must run supply-chain release checks",
                expected=command,
                actual="missing",
            )

    artifacts: list[dict[str, Any]] = []
    for path in (runtime_req, dev_req, console_package, console_lock, bridge_cargo, bridge_lock, release_workflow, ci_workflow):
        if path.exists():
            artifacts.append({"path": rel(path), "sha256": sha256_file(path)})

    components = [
        *parse_python_components([runtime_req, dev_req]),
        *parse_npm_components(console_lock),
        *parse_cargo_components(bridge_lock),
    ]

    by_ecosystem: dict[str, int] = {}
    for component in components:
        by_ecosystem[component["ecosystem"]] = by_ecosystem.get(component["ecosystem"], 0) + 1
        if not component.get("version"):
            add_finding(
                findings,
                severity="warn",
                check="component_version_present",
                path=Path(component["source"]),
                message="SBOM component lacks an explicit version",
                expected="version",
                actual=component,
            )

    advisory_policy = {
        "mode": "interface-only",
        "npm": "CI uses npm ci --no-audit to avoid network-dependent advisory instability; production should add npm audit or pinned offline advisory DB.",
        "python": "requirements are pinned with ~=; production should add pip-audit or pinned offline advisory DB.",
        "rust": "Cargo.lock is committed; production should add cargo audit or pinned offline advisory DB.",
        "status": "operator-side",
    }
    provenance = {
        "mode": "local-materials",
        "git_commit": git_value(["rev-parse", "HEAD"]),
        "git_tree": git_value(["rev-parse", "HEAD^{tree}"]),
        "release_workflow": rel(release_workflow),
        "ci_workflow": rel(ci_workflow),
        "external_attestation_status": "operator-side",
    }

    error_count = sum(1 for item in findings if item["severity"] == "error")
    warn_count = sum(1 for item in findings if item["severity"] == "warn")
    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "status": "fail" if error_count else "ok",
        "summary": {
            "artifact_count": len(artifacts),
            "component_count": len(components),
            "component_count_by_ecosystem": by_ecosystem,
            "error_count": error_count,
            "warn_count": warn_count,
            "pytest_dependency_declared": any(line.lower().startswith("pytest") for line in dev_requirements),
            "ci_runs_pytest": command_in_text(ci_text, "python3 -m pytest sse/test"),
            "ci_runs_console_strict_build": command_in_text(ci_text, "npm --prefix console run build:strict"),
            "release_console_typecheck_blocking": not any(f["check"] == "release_typecheck_blocking" for f in findings),
            "advisory_policy_status": advisory_policy["status"],
            "external_provenance_status": provenance["external_attestation_status"],
        },
        "artifacts": artifacts,
        "sbom": {
            "format": "local_component_inventory/v1",
            "components": components,
        },
        "provenance": provenance,
        "advisory_policy": advisory_policy,
        "findings": findings,
    }

    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 1 if error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
