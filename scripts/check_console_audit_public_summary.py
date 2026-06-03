#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CONSOLE_SRC = REPO_ROOT / "console" / "src"
SCHEMA_ID = "console_audit_public_summary_check/v1"

REQUIRED_PATTERNS = [
    (
        CONSOLE_SRC / "api" / "types.ts",
        "audit_chain_public_summary/v1",
        "audit API type union must include audit_chain_public_summary/v1",
    ),
    (
        CONSOLE_SRC / "api" / "types.ts",
        "pipeline_observability_public_summary/v1",
        "audit API type union must include pipeline_observability_public_summary/v1",
    ),
    (
        CONSOLE_SRC / "api" / "types.ts",
        "catalog_lineage_public_summary/v1",
        "audit API type union must include catalog_lineage_public_summary/v1",
    ),
    (
        CONSOLE_SRC / "api" / "types.ts",
        "unwrapAuditQueryResult",
        "audit sidecar responses must unwrap audit_query_api_response/v1 envelopes before route rendering",
    ),
    (
        CONSOLE_SRC / "api" / "sidecars.ts",
        "unwrapAuditQueryResult",
        "audit sidecar client must unwrap audit_query_api_response/v1 result payloads",
    ),
    (
        CONSOLE_SRC / "routes" / "audit.tsx",
        "isAuditChainPublicSummary",
        "audit route must branch on caller-safe audit-chain summaries",
    ),
    (
        CONSOLE_SRC / "routes" / "audit.tsx",
        "isPipelineObservabilityPublicSummary",
        "audit route must branch on caller-safe observability summaries",
    ),
    (
        CONSOLE_SRC / "routes" / "audit.tsx",
        "isCatalogLineagePublicSummary",
        "audit route must branch on caller-safe catalog lineage summaries",
    ),
    (
        CONSOLE_SRC / "routes" / "observability.tsx",
        "isPipelineObservabilityPublicSummary",
        "observability route must branch on caller-safe observability summaries",
    ),
    (
        CONSOLE_SRC / "routes" / "catalog.tsx",
        "isCatalogLineagePublicSummary",
        "catalog route must branch on caller-safe catalog lineage summaries",
    ),
]

FORBIDDEN_FULL_PAYLOAD_PATTERNS = [
    (
        CONSOLE_SRC / "routes" / "audit.tsx",
        re.compile(r"q\.data\?\.events\?\.length"),
        "audit route must not read full observability events on the un-narrowed audit response union",
    ),
    (
        CONSOLE_SRC / "routes" / "audit.tsx",
        re.compile(r"q\.data\?\.nodes\?\.length|q\.data\?\.edges\?\.length"),
        "audit route must not use legacy nodes/edges fields on the un-narrowed catalog response union",
    ),
    (
        CONSOLE_SRC / "routes" / "observability.tsx",
        re.compile(r"q\.data\?\.events"),
        "observability route must not read full event rows before public-summary narrowing",
    ),
    (
        CONSOLE_SRC / "routes" / "catalog.tsx",
        re.compile(r"q\.data\?\.nodes\?\.length|q\.data\?\.edges\?\.length"),
        "catalog route must not use legacy full lineage fields before public-summary narrowing",
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
