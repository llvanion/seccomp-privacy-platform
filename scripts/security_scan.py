#!/usr/bin/env python3
"""Security scanning suite: dependency scan, secret scan, malformed input fuzz fixtures.

All checks operate on existing files and schemas. No privacy-compute logic is modified.

Usage:
  python3 scripts/security_scan.py scan --repo-root .
  python3 scripts/security_scan.py fuzz-fixtures --out-dir tmp/fuzz_fixtures
  python3 scripts/security_scan.py schema-check --schema-dir schemas/
"""

import argparse
import hashlib
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple


REPO_ROOT_DEFAULT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


SECRET_PATTERNS = [
    # High-confidence secret patterns (heuristic)
    (re.compile(r'(?:secret|token|password|passphrase|key)\s*[:=]\s*["\']?([^\s"\'&|;]+)["\']?', re.I),
     "possible_secret_in_assignment"),
    (re.compile(r'(?:SECRET|TOKEN|PASSWORD|PASSPHRASE|KEY)\s*=\s*["\']?([^\s"\']+)["\']?'),
     "possible_secret_in_env"),
    (re.compile(r'-----BEGIN\s+(?:RSA|EC|DSA|OPENSSH)\s+PRIVATE\s+KEY-----'),
     "private_key_marker"),
    (re.compile(r'(?:API[_-]?KEY|api[_-]?key)\s*[:=]\s*["\']([A-Za-z0-9_\-]{8,})["\']'),
     "possible_api_key"),
]

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "target", "bazel-bin",
             "bazel-out", "bazel-testlogs"}
SKIP_EXTENSIONS = {".pyc", ".so", ".dll", ".exe", ".bin", ".png", ".jpg", ".pdf"}


def is_safe_path(path: str) -> bool:
    parts = set(os.path.normpath(path).split(os.sep))
    if parts & SKIP_DIRS:
        return False
    ext = os.path.splitext(path)[1].lower()
    if ext in SKIP_EXTENSIONS:
        return False
    return True


def hash_file(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def scan_secrets(repo_root: str) -> Dict[str, Any]:
    """Scan repository for potential secrets (heuristic, not exhaustive)."""
    findings: List[Dict[str, Any]] = []
    files_scanned = 0

    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            fpath = os.path.join(root, fname)
            if not is_safe_path(fpath):
                continue
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            files_scanned += 1
            for lineno, line in enumerate(content.splitlines(), 1):
                for pattern, reason in SECRET_PATTERNS:
                    m = pattern.search(line)
                    if m:
                        matched = m.group(0)
                        # Skip known safe patterns
                        if any(skip in matched.lower() for skip in [
                            "local-dev-secret", "example", "demo", "placeholder",
                            "contract-check-secret", "your-", "todo", "fixme",
                            "${", "$(", "read -r", "printf",
                        ]):
                            continue
                        findings.append({
                            "file": os.path.relpath(fpath, repo_root),
                            "line": lineno,
                            "reason": reason,
                            "snippet": matched[:80],
                        })

    return {
        "files_scanned": files_scanned,
        "findings": findings,
        "finding_count": len(findings),
    }


def scan_dependencies(repo_root: str) -> Dict[str, Any]:
    """Scan dependency files for known patterns (not a full CVE scan)."""
    dep_files: Dict[str, str] = {}

    for fname in ["requirements.txt", "Cargo.toml", "Cargo.lock", "pyproject.toml",
                  "Pipfile", "Pipfile.lock", "package.json"]:
        for root, dirs, files in os.walk(repo_root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            if fname in files:
                fpath = os.path.join(root, fname)
                dep_files[os.path.relpath(fpath, repo_root)] = hash_file(fpath)

    return {
        "dependency_files": dep_files,
        "file_count": len(dep_files),
        "recommendation": "Run 'pip-audit' for Python deps, 'cargo audit' for Rust deps",
    }


def generate_fuzz_fixtures(out_dir: str) -> int:
    """Generate malformed input fixtures for contract validation testing.

    These fixtures are used by the tabular contract validator to ensure
    malformed CSV/JSONL inputs are properly rejected.
    """
    os.makedirs(out_dir, exist_ok=True)

    fixtures: List[Tuple[str, str, str]] = [
        # Malformed CSV fixtures
        ("bad_csv_empty.csv", "csv",
         "email,amount\n,125\n"),  # empty join key
        ("bad_csv_no_header.csv", "csv",
         "alice@example.com,125\n"),  # no header row
        ("bad_csv_wrong_cols.csv", "csv",
         "email\nno_comma_value\n"),  # missing expected columns
        ("bad_csv_non_int.csv", "csv",
         "email,amount\nalice@example.com,not_a_number\n"),  # non-integer value
        ("bad_csv_empty_file.csv", "csv", ""),  # empty file

        # Malformed JSONL fixtures
        ("bad_jsonl_not_json.jsonl", "jsonl",
         "this is not json at all\n"),
        ("bad_jsonl_empty_line.jsonl", "jsonl",
         "\n{\"email\":\"alice@example.com\",\"amount\":125}\n"),  # leading empty line
        ("bad_jsonl_missing_field.jsonl", "jsonl",
         "{\"amount\":125}\n"),  # missing required join key
        ("bad_jsonl_null_key.jsonl", "jsonl",
         "{\"email\":null,\"amount\":125}\n"),  # null join key
        ("bad_jsonl_non_int_value.jsonl", "jsonl",
         "{\"email\":\"alice@example.com\",\"amount\":\"twelve\"}\n"),  # non-int value
        ("bad_jsonl_array.jsonl", "jsonl",
         "[\"not_an_object\"]\n"),  # array instead of object
        ("bad_jsonl_binary.jsonl", "jsonl",
         "\x00\x01\x02binary garbage\n"),  # binary content

        # Malformed PJC CSV fixtures
        ("bad_pjc_server_short.csv", "pjc",
         "0123456789abcdef\n"),  # too short hash
        ("bad_pjc_client_no_value.csv", "pjc",
         "not_a_hash\n"),  # missing value column
    ]

    for fname, fixture_type, content in fixtures:
        fpath = os.path.join(out_dir, fname)
        with open(fpath, "w", encoding="utf-8", errors="replace") as f:
            f.write(content)
        print(f"  [{fixture_type}] {fname}")

    # Write fixture manifest
    manifest_lines = ["# Malformed Input Fuzz Fixtures", "",
                       "These fixtures test contract validation robustness.", "",
                       "| File | Type | Expected Behavior |",
                       "|------|------|-------------------|",
                       "| bad_csv_empty.csv | csv | Reject empty join key |",
                       "| bad_csv_no_header.csv | csv | Reject missing header |",
                       "| bad_csv_non_int.csv | csv | Reject non-integer value |",
                       "| bad_csv_empty_file.csv | csv | Reject empty file |",
                       "| bad_jsonl_not_json.jsonl | jsonl | Reject non-JSON |",
                       "| bad_jsonl_missing_field.jsonl | jsonl | Reject missing join key |",
                       "| bad_jsonl_null_key.jsonl | jsonl | Reject null join key |",
                       "| bad_jsonl_non_int_value.jsonl | jsonl | Reject non-int value |",
                       "| bad_jsonl_binary.jsonl | jsonl | Reject binary content |",
                       "| bad_pjc_server_short.csv | pjc | Reject short hash |",
                       "| bad_pjc_client_no_value.csv | pjc | Reject missing value |",
                       ""]
    manifest_path = os.path.join(out_dir, "FUZZ_FIXTURES.md")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write("\n".join(manifest_lines) + "\n")
    print(f"\n[ok] {len(fixtures)} fuzz fixtures: {os.path.abspath(out_dir)}")
    return 0


def check_schema_compatibility(schema_dir: str) -> Dict[str, Any]:
    """Check that all JSON schemas are syntactically valid and have consistent $id fields."""
    results: List[Dict[str, Any]] = []
    if not os.path.isdir(schema_dir):
        return {"schemas_checked": 0, "valid": 0, "invalid": 1, "results": results}

    for fname in sorted(os.listdir(schema_dir)):
        if not fname.endswith(".schema.json"):
            continue
        fpath = os.path.join(schema_dir, fname)
        check = {"file": fname, "valid": True, "issues": []}
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                schema = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            check["valid"] = False
            check["issues"].append(f"JSON parse error: {e}")
            results.append(check)
            continue

        schema_id = schema.get("$id", "")
        if not schema_id:
            check["issues"].append("missing $id")
        if schema.get("type") != "object":
            check["issues"].append(f"unexpected type: {schema.get('type')}")
        if "properties" not in schema and schema.get("type") == "object":
            check["issues"].append("object schema missing properties")

        check["schema_id"] = schema_id
        check["valid"] = len(check["issues"]) == 0
        results.append(check)

    valid = sum(1 for r in results if r["valid"])
    return {
        "schemas_checked": len(results),
        "valid": valid,
        "invalid": len(results) - valid,
        "results": results,
    }


def cmd_scan(args: argparse.Namespace) -> int:
    repo_root = os.path.abspath(args.repo_root)
    print(f"=== Secret Scan ===")
    secret_result = scan_secrets(repo_root)
    print(f"  Files scanned: {secret_result['files_scanned']}")
    print(f"  Findings: {secret_result['finding_count']}")

    for finding in secret_result["findings"]:
        print(f"  [WARN] {finding['file']}:{finding['line']} — {finding['reason']}")
        print(f"         {finding['snippet']}")

    print(f"\n=== Dependency Scan ===")
    dep_result = scan_dependencies(repo_root)
    print(f"  Dependency files found: {dep_result['file_count']}")
    for fname, sha in dep_result["dependency_files"].items():
        print(f"  {fname} (sha256={sha[:16]})")
    print(f"  {dep_result['recommendation']}")

    print(f"\n=== Schema Compatibility Check ===")
    schema_dir = os.path.join(repo_root, "schemas")
    schema_result = check_schema_compatibility(schema_dir)
    print(f"  Schemas: {schema_result['schemas_checked']} checked, "
          f"{schema_result['valid']} valid, {schema_result['invalid']} invalid")
    for r in schema_result["results"]:
        if not r["valid"]:
            print(f"  [FAIL] {r['file']}: {', '.join(r['issues'])}")

    report = {
        "schema": "security_scan_report/v1",
        "scanned_at_utc": __import__('datetime').datetime.now(
            __import__('datetime').timezone.utc).isoformat().replace("+00:00", "Z"),
        "repo_root": repo_root,
        "secret_scan": secret_result,
        "dependency_scan": dep_result,
        "schema_check": schema_result,
    }
    report_path = os.path.join(repo_root, "tmp", "security_scan_report.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n[ok] security scan report: {os.path.abspath(report_path)}")

    high_findings = [f for f in secret_result["findings"]
                     if "private_key" in f["reason"]]
    return 1 if high_findings else 0


def cmd_fuzz_fixtures(args: argparse.Namespace) -> int:
    return generate_fuzz_fixtures(os.path.abspath(args.out_dir))


def cmd_schema_check(args: argparse.Namespace) -> int:
    result = check_schema_compatibility(os.path.abspath(args.schema_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["invalid"] == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Security scanning suite")
    sub = ap.add_subparsers(dest="command")

    scan_ap = sub.add_parser("scan", help="Run all security scans")
    scan_ap.add_argument("--repo-root", default=REPO_ROOT_DEFAULT)

    fuzz_ap = sub.add_parser("fuzz-fixtures", help="Generate malformed input fuzz fixtures")
    fuzz_ap.add_argument("--out-dir", default="tmp/fuzz_fixtures")

    schema_ap = sub.add_parser("schema-check", help="Check schema backward compatibility")
    schema_ap.add_argument("--schema-dir", default=f"{REPO_ROOT_DEFAULT}/schemas")

    args = ap.parse_args()
    if args.command == "scan":
        return cmd_scan(args)
    elif args.command == "fuzz-fixtures":
        return cmd_fuzz_fixtures(args)
    elif args.command == "schema-check":
        return cmd_schema_check(args)
    else:
        ap.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
