#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CONSOLE_SRC = REPO_ROOT / "console" / "src"
SCHEMA_ID = "console_token_storage_check/v1"

TOKEN_RE = re.compile(r"\b(?:token|bearer|authorization)\b", re.IGNORECASE)
LOCAL_STORAGE_API_RE = re.compile(r"\b(?:window\.)?localStorage\.")
LOCAL_STORAGE_SET_RE = re.compile(r"\b(?:window\.)?localStorage\.setItem\b")
FETCH_CREDENTIALS_RE = re.compile(r"\bcredentials:\s*[\"']same-origin[\"']")
SAFE_LOCAL_STORAGE_TOKEN_CONTEXT = {
    "LEGACY_STORAGE_KEY",
    "removeItem(LEGACY_STORAGE_KEY)",
    "BASE_URL_STORAGE_KEY",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def finding(path: Path, line_no: int, line: str, message: str) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "line_no": line_no,
        "message": message,
        "line": line.strip(),
    }


def scan_file(path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if "localStorage" not in line:
            continue
        if (
            LOCAL_STORAGE_API_RE.search(line)
            and all(token not in line for token in SAFE_LOCAL_STORAGE_TOKEN_CONTEXT)
            and TOKEN_RE.search(line)
        ):
            findings.append(
                finding(
                    path,
                    line_no,
                    line,
                    "console token/authorization material must not be persisted through localStorage",
                )
            )
        if LOCAL_STORAGE_SET_RE.search(line) and not (
            "BASE_URL_STORAGE_KEY" in line and ("baseUrlOnly(" in line or "migrated" in line)
        ):
            findings.append(
                finding(
                    path,
                    line_no,
                    line,
                    "console localStorage writes must be limited to baseUrl-only config",
                )
            )
        if "seccomp.console.config.v1" in line and "LEGACY_STORAGE_KEY" not in line:
            findings.append(
                finding(
                    path,
                    line_no,
                    line,
                    "legacy full console config storage key may only be referenced for migration/removal",
                )
            )
    return findings


def main() -> int:
    findings: list[dict[str, Any]] = []
    scanned_files = 0
    fetch_credentials_same_origin = False
    for path in sorted(CONSOLE_SRC.rglob("*")):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        scanned_files += 1
        text = path.read_text(encoding="utf-8")
        if path.relative_to(REPO_ROOT).as_posix() == "console/src/api/client.ts":
            fetch_credentials_same_origin = bool(FETCH_CREDENTIALS_RE.search(text))
        findings.extend(scan_file(path))
    if not fetch_credentials_same_origin:
        findings.append(
            {
                "path": "console/src/api/client.ts",
                "line_no": 1,
                "message": "console API fetch must send same-origin HttpOnly session cookies",
                "line": "fetch(..., { credentials: 'same-origin' })",
            }
        )
    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "status": "fail" if findings else "ok",
        "scanned_files": scanned_files,
        "fetch_credentials_same_origin": fetch_credentials_same_origin,
        "finding_count": len(findings),
        "findings": findings,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
