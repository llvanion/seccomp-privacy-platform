#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CONSOLE_SRC = REPO_ROOT / "console" / "src"
SCHEMA_ID = "console_dashboard_public_summary_check/v1"

REQUIRED_PATTERNS = [
    (
        CONSOLE_SRC / "api" / "types.ts",
        "operator_dashboard_public_summary/v1",
        "dashboard API type union must include operator_dashboard_public_summary/v1",
    ),
    (
        CONSOLE_SRC / "api" / "types.ts",
        "isOperatorDashboardPublicSummary",
        "dashboard API must expose an explicit public-summary type guard",
    ),
    (
        CONSOLE_SRC / "routes" / "home.tsx",
        "isOperatorDashboardPublicSummary",
        "home route must branch on dashboard public-summary responses",
    ),
    (
        CONSOLE_SRC / "routes" / "home.tsx",
        "DashboardPublicSummaryPanel",
        "home route must render a caller-safe dashboard summary panel",
    ),
    (
        CONSOLE_SRC / "routes" / "jobs.tsx",
        "isOperatorDashboardPublicSummary",
        "jobs route must branch on dashboard public-summary responses",
    ),
    (
        CONSOLE_SRC / "routes" / "jobs.tsx",
        "redacted-current-job",
        "jobs route must not link caller-safe synthetic rows to full job detail",
    ),
]

FORBIDDEN_FULL_PAYLOAD_PATTERNS = [
    (
        CONSOLE_SRC / "routes" / "home.tsx",
        re.compile(r"JsonBlock\s+data=\{data\.audit_center\}"),
        "home route must not render dashboard audit_center from the un-narrowed dashboard union",
    ),
    (
        CONSOLE_SRC / "routes" / "home.tsx",
        re.compile(r"data\?\.audit_center"),
        "home route must not test audit_center on the un-narrowed dashboard union",
    ),
    (
        CONSOLE_SRC / "routes" / "jobs.tsx",
        re.compile(r"dashboardQ\.data\?\.(?:jobs|recent_runs)"),
        "jobs route must not read full job arrays from the un-narrowed dashboard union",
    ),
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def finding(path: Path, message: str, *, line_no: int | None = None, line: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": str(path.relative_to(REPO_ROOT)),
        "message": message,
    }
    if line_no is not None:
        payload["line_no"] = line_no
    if line is not None:
        payload["line"] = line.strip()
    return payload


def scan_required_patterns() -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path, needle, message in REQUIRED_PATTERNS:
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if needle not in text:
            findings.append(finding(path, message))
    return findings


def scan_forbidden_patterns() -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path, pattern, message in FORBIDDEN_FULL_PAYLOAD_PATTERNS:
        if not path.is_file():
            findings.append(finding(path, f"console route missing: {path.name}"))
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                findings.append(finding(path, message, line_no=line_no, line=line))
    return findings


def main() -> int:
    findings = scan_required_patterns() + scan_forbidden_patterns()
    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "status": "fail" if findings else "ok",
        "checked_files": sorted(
            str(path.relative_to(REPO_ROOT))
            for path in {
                *(entry[0] for entry in REQUIRED_PATTERNS),
                *(entry[0] for entry in FORBIDDEN_FULL_PAYLOAD_PATTERNS),
            }
        ),
        "finding_count": len(findings),
        "findings": findings,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
