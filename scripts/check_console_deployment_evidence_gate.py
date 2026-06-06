#!/usr/bin/env python3
"""Verifier-facing gate for console/browser deployment evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "console_deployment_evidence_gate/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact(path: Path, *, schema: str | None = None, note: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"path": str(path)}
    if schema:
        item["schema"] = schema
    if note:
        item["note"] = note
    return item


def parse_check(
    *,
    name: str,
    status: str,
    expected: Any,
    actual: Any,
    missing_prerequisites: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "name": name,
        "status": status,
        "expected": expected,
        "actual": actual,
    }
    if missing_prerequisites is not None:
        payload["missing_prerequisites"] = missing_prerequisites
    return payload


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def require_ok(res: subprocess.CompletedProcess[str], *, label: str) -> None:
    if res.returncode != 0:
        raise RuntimeError(f"{label} failed ({res.returncode})\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--live-evidence-archive", default="")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    repo_side_checks: list[dict[str, Any]] = []
    live_checks: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    token_storage_path = out_dir / "console_token_storage_check.json"
    res = run(["python3", str(REPO_ROOT / "scripts" / "check_console_token_storage.py")])
    require_ok(res, label="check_console_token_storage")
    token_storage = json.loads(res.stdout)
    write_json(token_storage_path, token_storage)
    repo_side_checks.append(
        parse_check(
            name="repo_side_console_token_storage",
            status="ok" if token_storage.get("status") == "ok" else "fail",
            expected="console keeps bearer tokens out of cross-session localStorage",
            actual=token_storage,
        )
    )
    artifacts.append(artifact(token_storage_path, schema="console_token_storage_check/v1"))

    browser_path = out_dir / "console_browser_session_check.json"
    res = run(["python3", str(REPO_ROOT / "scripts" / "check_console_browser_session.py"), "--out", str(browser_path)])
    if res.returncode == 0:
        browser = load_json(browser_path)
        repo_side_checks.append(
            parse_check(
                name="repo_side_console_browser_session",
                status="ok" if browser.get("status") == "ok" else "fail",
                expected="same-origin console browser session uses HttpOnly/SameSite cookie path",
                actual=browser,
            )
        )
        artifacts.append(artifact(browser_path, schema="console_browser_session_check/v1"))
    else:
        stderr = res.stderr.strip()
        if "PermissionError" in stderr and ("socket" in stderr or "Operation not permitted" in stderr):
            repo_side_checks.append(
                parse_check(
                    name="repo_side_console_browser_session",
                    status="skipped",
                    expected="same-origin console browser session uses HttpOnly/SameSite cookie path",
                    actual={"stderr": stderr},
                    missing_prerequisites=["environment permits loopback listener sockets for console browser-session smoke"],
                )
            )
        else:
            require_ok(res, label="check_console_browser_session")

    headers_path = out_dir / "console_security_headers_check.json"
    res = run(["python3", str(REPO_ROOT / "scripts" / "check_console_security_headers.py"), "--out", str(headers_path)])
    if res.returncode == 0:
        headers = load_json(headers_path)
        repo_side_checks.append(
            parse_check(
                name="repo_side_console_security_headers",
                status="ok" if headers.get("status") == "ok" else "fail",
                expected="console serves strict CSP/security headers and source scan stays clean",
                actual=headers,
            )
        )
        artifacts.append(artifact(headers_path, schema="console_security_headers_check/v1"))
    else:
        stderr = res.stderr.strip()
        if "PermissionError" in stderr and ("socket" in stderr or "Operation not permitted" in stderr):
            repo_side_checks.append(
                parse_check(
                    name="repo_side_console_security_headers",
                    status="skipped",
                    expected="console serves strict CSP/security headers and source scan stays clean",
                    actual={"stderr": stderr},
                    missing_prerequisites=["environment permits loopback listener sockets for console security-header smoke"],
                )
            )
        else:
            require_ok(res, label="check_console_security_headers")

    release_path = out_dir / "console_release_gate_check.json"
    res = run(["python3", str(REPO_ROOT / "scripts" / "check_console_release_gate.py"), "--out", str(release_path)])
    require_ok(res, label="check_console_release_gate")
    release = load_json(release_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_console_release_gate",
            status="ok" if release.get("status") == "ok" else "fail",
            expected="console release path remains reproducible and blocks workflow/lockfile regressions",
            actual=release,
        )
    )
    artifacts.append(artifact(release_path, schema="console_release_gate_check/v1"))

    archive_path = Path(args.live_evidence_archive).resolve() if args.live_evidence_archive else None
    if archive_path is None:
        archive_path = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname="console_live_archive",
            archive_filename="console_live_evidence_archive.json",
            expected_schema="console_live_evidence_archive/v1",
        )
    if archive_path is None:
        live_checks.append(
            parse_check(
                name="live_console_evidence_archive",
                status="skipped",
                expected="operator provides a unified live console deployment evidence archive",
                actual=None,
                missing_prerequisites=["--live-evidence-archive"],
            )
        )
    elif not archive_path.is_file():
        live_checks.append(
            parse_check(
                name="live_console_evidence_archive",
                status="fail",
                expected="operator provides a unified live console deployment evidence archive",
                actual={"path": str(archive_path), "exists": False},
            )
        )
    else:
        archive = load_json(archive_path)
        artifacts.append(artifact(archive_path, schema="console_live_evidence_archive/v1"))
        live_artifact_count = int(archive.get("live_artifact_count") or 0)
        live_checks.append(
            parse_check(
                name="live_console_evidence_archive",
                status="ok" if archive.get("status") == "ok" and live_artifact_count > 0 else "skipped" if archive.get("status") == "ok" else "fail",
                expected="operator provides a unified live console deployment evidence archive",
                actual=archive,
                missing_prerequisites=["archive contains no live console deployment artifacts"] if archive.get("status") == "ok" and live_artifact_count == 0 else None,
            )
        )
        foundation_present = isinstance((archive.get("live_artifacts") or {}).get("live_repo_side_console_foundation"), dict)
        live_checks.append(
            parse_check(
                name="live_console_foundation",
                status="ok" if foundation_present else "skipped",
                expected="current-worktree console/session/header/release baseline is frozen into the live console archive",
                actual=(archive.get("live_artifacts") or {}).get("live_repo_side_console_foundation"),
                missing_prerequisites=["live_repo_side_console_foundation not present in console live archive"] if not foundation_present else None,
            )
        )
        rollout_present = any(
            isinstance((archive.get("live_artifacts") or {}).get(name), dict)
            for name in (
                "live_https_secure_cookie_report",
                "live_oidc_reverse_proxy_report",
                "live_browser_exercise_report",
                "live_release_run_report",
            )
        )
        live_checks.append(
            parse_check(
                name="live_real_console_rollout",
                status="ok" if rollout_present else "skipped",
                expected="real HTTPS/Secure-cookie, reverse-proxy/OIDC, browser exercise, or release-run artifacts are archived",
                actual={
                    key: (archive.get("live_artifacts") or {}).get(key)
                    for key in (
                        "live_https_secure_cookie_report",
                        "live_oidc_reverse_proxy_report",
                        "live_browser_exercise_report",
                        "live_release_run_report",
                    )
                },
                missing_prerequisites=["real console rollout artifacts are still missing"] if not rollout_present else None,
            )
        )

    repo_side_status = "ok" if all(item["status"] in {"ok", "skipped"} for item in repo_side_checks) else "fail"
    concrete_live = [item for item in live_checks if item["name"] == "live_console_evidence_archive"]
    rollout_live = [item for item in live_checks if item["name"] == "live_real_console_rollout"]
    if any(item["status"] == "fail" for item in concrete_live):
        live_status = "fail"
    elif rollout_live and all(item["status"] == "ok" for item in rollout_live):
        live_status = "ok"
    else:
        live_status = "skipped"

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if repo_side_status == "ok" and live_status != "fail" else "fail",
        "repo_side_status": repo_side_status,
        "live_status": live_status,
        "repo_side_checks": repo_side_checks,
        "live_checks": live_checks,
        "repo_side_boundary": [
            "Repo-side checks prove token handling, same-origin session auth, CSP/security headers, and release reproducibility for the console surface.",
            "They do not prove deployed HTTPS/Secure-cookie, reverse-proxy/OIDC, browser exercise on the target hosts, or a real release run in the operator environment.",
        ],
        "live_boundary": [
            "Live console readiness requires operator-provided HTTPS/Secure-cookie, reverse-proxy/OIDC, browser exercise, and release-run artifacts.",
            "When no live archive is supplied, this gate stays at live_status=skipped rather than claiming production-complete console deployment.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "console_deployment_evidence_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
