#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CONSOLE_SRC = REPO_ROOT / "console" / "src"
SCHEMA_ID = "console_business_access_workbench_check/v1"

REQUIRED_PATTERNS = [
    (
        CONSOLE_SRC / "api" / "types.ts",
        "business_access_check_report/v1",
        "console API types must include business_access_check_report/v1",
    ),
    (
        CONSOLE_SRC / "api" / "types.ts",
        "business_data_read_preview/v1",
        "console API types must include business_data_read_preview/v1",
    ),
    (
        CONSOLE_SRC / "api" / "sidecars.ts",
        "businessAccessCheck",
        "metadata sidecar client must expose businessAccessCheck()",
    ),
    (
        CONSOLE_SRC / "api" / "sidecars.ts",
        "businessDataReadPreview",
        "metadata sidecar client must expose businessDataReadPreview()",
    ),
    (
        CONSOLE_SRC / "routes" / "business-access.tsx",
        "BusinessAccessRoute",
        "console must include the business access workbench route",
    ),
    (
        CONSOLE_SRC / "routes" / "business-access.tsx",
        "metadataApi.businessAccessCheck",
        "business access workbench must call metadataApi.businessAccessCheck",
    ),
    (
        CONSOLE_SRC / "routes" / "business-access.tsx",
        "metadataApi.businessDataReadPreview",
        "business access workbench must call metadataApi.businessDataReadPreview",
    ),
    (
        CONSOLE_SRC / "routes" / "business-access.tsx",
        'key: "buyer"',
        "business access workbench must include a buyer preset",
    ),
    (
        CONSOLE_SRC / "routes" / "business-access.tsx",
        'key: "customer_service_agent"',
        "business access workbench must include a support preset",
    ),
    (
        CONSOLE_SRC / "routes" / "business-access.tsx",
        'key: "station_operator"',
        "business access workbench must include a station-operator preset",
    ),
    (
        CONSOLE_SRC / "routes" / "business-access.tsx",
        'key: "field_marketer"',
        "business access workbench must include a field-marketer preset",
    ),
    (
        CONSOLE_SRC / "routes" / "business-access.tsx",
        'purpose: "merchant_order_ops"',
        "merchant preset must use merchant_order_ops purpose",
    ),
    (
        CONSOLE_SRC / "routes" / "business-access.tsx",
        'case_id: "fraud-1"',
        "fraud preset must use the bound fraud case id",
    ),
    (
        CONSOLE_SRC / "routes" / "business-access.tsx",
        'campaign_id: "campaign-demo"',
        "field marketer preset must use the bound campaign id",
    ),
    (
        CONSOLE_SRC / "router.tsx",
        "path: \"business-access\"",
        "router must register /business-access",
    ),
    (
        CONSOLE_SRC / "components" / "layout.tsx",
        "to: \"/business-access\"",
        "sidebar must expose /business-access navigation",
    ),
]

FORBIDDEN_PATTERNS = [
    (
        CONSOLE_SRC / "routes" / "business-access.tsx",
        re.compile(r"localStorage\.", re.IGNORECASE),
        "business access workbench must not persist role/access payloads to localStorage",
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


def main() -> int:
    findings: list[dict[str, Any]] = []
    checked_files = sorted({str(path.relative_to(REPO_ROOT)) for path, *_ in REQUIRED_PATTERNS + FORBIDDEN_PATTERNS})

    for path, needle, message in REQUIRED_PATTERNS:
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if needle not in text:
            findings.append(finding(path, message))

    for path, pattern, message in FORBIDDEN_PATTERNS:
        if not path.is_file():
            findings.append(finding(path, f"console route missing: {path.name}"))
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                findings.append(finding(path, message, line_no=line_no, line=line))

    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "status": "fail" if findings else "ok",
        "checked_files": checked_files,
        "finding_count": len(findings),
        "findings": findings,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
