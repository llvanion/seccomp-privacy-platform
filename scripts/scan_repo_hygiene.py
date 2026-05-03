#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

SKIP_CONTENT_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "target",
    "tmp",
}

GENERATED_PATH_PARTS = {
    "__pycache__",
    "target",
}

GENERATED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".rlib",
    ".rmeta",
    ".o",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
}

HIGH_CONFIDENCE_SECRET_PATTERNS = [
    ("private_key_material", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{30,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("openai_api_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{40,}\b")),
]

GENERIC_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:password|passwd|secret|token|api[_-]?key|private[_-]?key)\b\s*[:=]\s*['\"]([^'\"]{16,})['\"]"
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def rel_path(path: Path) -> str:
    return str(path.resolve().relative_to(REPO_ROOT))


def tracked_files() -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=str(REPO_ROOT),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return [
            REPO_ROOT / item.decode("utf-8")
            for item in result.stdout.split(b"\0")
            if item
        ]
    except Exception:
        files: list[Path] = []
        for root, dirnames, filenames in os.walk(REPO_ROOT):
            dirnames[:] = [name for name in dirnames if name not in {".git", ".venv", "node_modules"}]
            for filename in filenames:
                files.append(Path(root) / filename)
        return files


def path_has_part(path: Path, parts: set[str]) -> bool:
    return any(part in parts for part in path.relative_to(REPO_ROOT).parts)


def is_probably_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
    except OSError:
        return True
    return b"\0" in chunk


def should_scan_content(path: Path, *, max_bytes: int) -> bool:
    if not path.is_file():
        return False
    if path.stat().st_size > max_bytes:
        return False
    if path_has_part(path, SKIP_CONTENT_DIRS):
        return False
    if is_probably_binary(path):
        return False
    return True


def is_generated_artifact_path(path: Path) -> bool:
    relative = path.relative_to(REPO_ROOT)
    if any(part in GENERATED_PATH_PARTS for part in relative.parts):
        return True
    if path.suffix.lower() in GENERATED_SUFFIXES:
        return True
    return False


def scan_file_content(path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return findings
    except OSError:
        return findings

    for line_no, line in enumerate(text.splitlines(), 1):
        for kind, pattern in HIGH_CONFIDENCE_SECRET_PATTERNS:
            if pattern.search(line):
                findings.append({
                    "severity": "error",
                    "kind": kind,
                    "path": rel_path(path),
                    "line": line_no,
                    "message": "high-confidence secret pattern found",
                })
        generic = GENERIC_SECRET_ASSIGNMENT.search(line)
        if generic and not path.name.endswith(".md"):
            value = generic.group(1).strip()
            if "example" not in value.lower() and "local-dev" not in value.lower() and "contract-" not in value.lower():
                findings.append({
                    "severity": "warn",
                    "kind": "generic_secret_assignment",
                    "path": rel_path(path),
                    "line": line_no,
                    "message": "generic secret-like assignment found; verify this is not a real secret",
                })
    return findings


def summarize(findings: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "error": sum(1 for item in findings if item.get("severity") == "error"),
        "warn": sum(1 for item in findings if item.get("severity") == "warn"),
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Run a lightweight repository hygiene/security scan.")
    ap.add_argument("--max-file-bytes", type=int, default=1024 * 1024)
    ap.add_argument("--max-findings", type=int, default=200)
    ap.add_argument("--fail-on-warn", action="store_true")
    ap.add_argument("--allow-findings", action="store_true")
    ap.add_argument("--output", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    paths = tracked_files()
    findings: list[dict[str, Any]] = []
    scanned_content_files = 0
    generated_artifact_paths: list[str] = []

    for path in paths:
        if len(findings) >= args.max_findings:
            break
        if is_generated_artifact_path(path):
            generated_artifact_paths.append(rel_path(path))
            continue
        if should_scan_content(path, max_bytes=args.max_file_bytes):
            scanned_content_files += 1
            findings.extend(scan_file_content(path))

    if generated_artifact_paths:
        findings.append({
            "severity": "warn",
            "kind": "tracked_generated_artifacts",
            "path": None,
            "line": None,
            "message": "tracked files include generated/build-output artifacts",
            "count": len(generated_artifact_paths),
            "sample_paths": generated_artifact_paths[:20],
        })

    truncated = len(findings) >= args.max_findings
    findings = findings[:args.max_findings]
    summary = summarize(findings)
    status = "error" if summary["error"] else ("warn" if summary["warn"] else "ok")
    report = {
        "schema": "repo_hygiene_scan/v1",
        "generated_at_utc": utc_now_iso(),
        "repo_root": str(REPO_ROOT),
        "status": status,
        "summary": {
            **summary,
            "tracked_files": len(paths),
            "scanned_content_files": scanned_content_files,
            "truncated": truncated,
            "max_findings": args.max_findings,
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
    raise SystemExit(main())
