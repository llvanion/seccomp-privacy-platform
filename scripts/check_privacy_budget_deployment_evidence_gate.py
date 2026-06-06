#!/usr/bin/env python3
"""Verifier-facing gate for privacy-budget deployment evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "privacy_budget_deployment_evidence_gate/v1"


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

    concurrency_path = out_dir / "privacy_budget_concurrency_check.json"
    res = run(["python3", str(REPO_ROOT / "scripts" / "check_privacy_budget_concurrency.py"), "--work-dir", str(out_dir / "pb_concurrency")])
    require_ok(res, label="check_privacy_budget_concurrency")
    concurrency = json.loads(res.stdout)
    write_json(concurrency_path, concurrency)
    repo_side_checks.append(
        parse_check(
            name="repo_side_privacy_budget_concurrency",
            status="ok" if concurrency.get("status") == "ok" else "fail",
            expected="transactional privacy-budget store allows exactly one concurrent consume and denies the loser deterministically",
            actual=concurrency,
        )
    )
    artifacts.append(artifact(concurrency_path, schema="privacy_budget_concurrency_check/v1"))

    approval_flow_path = out_dir / "privacy_budget_approval_flow_check.json"
    res = run(["python3", str(REPO_ROOT / "scripts" / "check_privacy_budget_approval_flow.py"), "--work-dir", str(out_dir / "pb_approval_flow")])
    require_ok(res, label="check_privacy_budget_approval_flow")
    approval_flow = json.loads(res.stdout)
    write_json(approval_flow_path, approval_flow)
    repo_side_checks.append(
        parse_check(
            name="repo_side_privacy_budget_approval_flow",
            status="ok" if approval_flow.get("status") == "ok" else "fail",
            expected="approval lifecycle rejects self-approval, supports approve/reject/expire, and consumes approvals only once",
            actual=approval_flow,
        )
    )
    artifacts.append(artifact(approval_flow_path, schema="privacy_budget_approval_flow_check/v1"))

    approval_api_dir = out_dir / "privacy_budget_approval_api_smoke"
    res = run(["python3", str(REPO_ROOT / "scripts" / "check_privacy_budget_approval_api_smoke.py"), "--out-dir", str(approval_api_dir)])
    if res.returncode == 0:
        approval_api = load_json(approval_api_dir / "privacy_budget_approval_api_smoke.json")
        repo_side_checks.append(
            parse_check(
                name="repo_side_privacy_budget_approval_api",
                status="ok" if approval_api.get("status") == "ok" else "fail",
                expected="authenticated approval API exposes pending queue and approve/reject/expire transitions with self-approval denial",
                actual=approval_api,
            )
        )
        artifacts.append(artifact(approval_api_dir / "privacy_budget_approval_api_smoke.json", schema="privacy_budget_approval_api_smoke/v1"))
        artifacts.append(artifact(approval_api_dir / "privacy_budget_approval_list.json", schema="privacy_budget_approval_list/v1"))
        artifacts.append(artifact(approval_api_dir / "privacy_budget_approval_transition.json", schema="privacy_budget_approval_transition/v1"))
    else:
        stderr = res.stderr.strip()
        if "PermissionError" in stderr and ("socket" in stderr or "Operation not permitted" in stderr):
            repo_side_checks.append(
                parse_check(
                    name="repo_side_privacy_budget_approval_api",
                    status="skipped",
                    expected="authenticated approval API exposes pending queue and approve/reject/expire transitions with self-approval denial",
                    actual={"stderr": stderr},
                    missing_prerequisites=["environment permits loopback listener sockets for privacy-budget approval API smoke"],
                )
            )
        else:
            require_ok(res, label="check_privacy_budget_approval_api_smoke")

    browser_path = out_dir / "console_browser_session_check.json"
    res = run(["python3", str(REPO_ROOT / "scripts" / "check_console_browser_session.py"), "--out", str(browser_path)])
    if res.returncode == 0:
        browser = load_json(browser_path)
        repo_side_checks.append(
            parse_check(
                name="repo_side_privacy_budget_console_session",
                status="ok" if browser.get("status") == "ok" else "fail",
                expected="same-origin console can use HttpOnly/SameSite cookie session instead of retaining bearer token in JavaScript",
                actual=browser,
            )
        )
        artifacts.append(artifact(browser_path, schema="console_browser_session_check/v1"))
    else:
        stderr = res.stderr.strip()
        if "PermissionError" in stderr and ("socket" in stderr or "Operation not permitted" in stderr):
            repo_side_checks.append(
                parse_check(
                    name="repo_side_privacy_budget_console_session",
                    status="skipped",
                    expected="same-origin console can use HttpOnly/SameSite cookie session instead of retaining bearer token in JavaScript",
                    actual={"stderr": stderr},
                    missing_prerequisites=["environment permits loopback listener sockets for console browser-session smoke"],
                )
            )
        else:
            require_ok(res, label="check_console_browser_session")

    proxy_path = out_dir / "identity_proxy_auth_smoke.json"
    res = run(["python3", str(REPO_ROOT / "scripts" / "check_identity_proxy_auth_smoke.py"), "--out", str(proxy_path)])
    if res.returncode == 0:
        proxy = load_json(proxy_path)
        repo_side_checks.append(
            parse_check(
                name="repo_side_privacy_budget_identity_proxy",
                status="ok" if proxy.get("status") == "ok" else "fail",
                expected="identity proxy fails closed without auth and resolves identity from same-origin session cookie without forwarding bearer auth",
                actual=proxy,
            )
        )
        artifacts.append(artifact(proxy_path, schema="identity_proxy_auth_smoke/v1"))
    else:
        stderr = res.stderr.strip()
        if "PermissionError" in stderr and ("socket" in stderr or "Operation not permitted" in stderr):
            repo_side_checks.append(
                parse_check(
                    name="repo_side_privacy_budget_identity_proxy",
                    status="skipped",
                    expected="identity proxy fails closed without auth and resolves identity from same-origin session cookie without forwarding bearer auth",
                    actual={"stderr": stderr},
                    missing_prerequisites=["environment permits loopback listener sockets for identity proxy auth smoke"],
                )
            )
        else:
            require_ok(res, label="check_identity_proxy_auth_smoke")

    archive_path = Path(args.live_evidence_archive).resolve() if args.live_evidence_archive else None
    if archive_path is None:
        archive_path = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname="privacy_budget_live_archive",
            archive_filename="privacy_budget_live_evidence_archive.json",
            expected_schema="privacy_budget_live_evidence_archive/v1",
        )
    if archive_path is None:
        live_checks.append(
            parse_check(
                name="live_privacy_budget_evidence_archive",
                status="skipped",
                expected="operator provides a unified live privacy-budget deployment evidence archive",
                actual=None,
                missing_prerequisites=["--live-evidence-archive"],
            )
        )
    elif not archive_path.is_file():
        live_checks.append(
            parse_check(
                name="live_privacy_budget_evidence_archive",
                status="fail",
                expected="operator provides a unified live privacy-budget deployment evidence archive",
                actual={"path": str(archive_path), "exists": False},
            )
        )
    else:
        archive = load_json(archive_path)
        artifacts.append(artifact(archive_path, schema="privacy_budget_live_evidence_archive/v1"))
        live_artifact_count = int(archive.get("live_artifact_count") or 0)
        live_checks.append(
            parse_check(
                name="live_privacy_budget_evidence_archive",
                status="ok" if archive.get("status") == "ok" and live_artifact_count > 0 else "skipped" if archive.get("status") == "ok" else "fail",
                expected="operator provides a unified live privacy-budget deployment evidence archive",
                actual=archive,
                missing_prerequisites=["archive contains no live privacy-budget deployment artifacts"] if archive.get("status") == "ok" and live_artifact_count == 0 else None,
            )
        )

    repo_side_status = "ok" if all(item["status"] in {"ok", "skipped"} for item in repo_side_checks) else "fail"
    concrete_live = [item for item in live_checks if item["name"] == "live_privacy_budget_evidence_archive"]
    live_status = (
        "fail" if any(item["status"] == "fail" for item in concrete_live)
        else "ok" if concrete_live and all(item["status"] == "ok" for item in concrete_live)
        else "skipped"
    )

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if repo_side_status == "ok" and live_status != "fail" else "fail",
        "repo_side_status": repo_side_status,
        "live_status": live_status,
        "repo_side_checks": repo_side_checks,
        "live_checks": live_checks,
        "repo_side_boundary": [
            "Repo-side checks prove transactional duplicate/near-duplicate denial, one-time approval consumption, authenticated approval API behavior, and same-origin browser/session identity handling.",
            "They do not prove live PostgreSQL/HA durability for the same store, nor a deployed browser-console path behind production TLS/cookie settings.",
        ],
        "live_boundary": [
            "Live privacy-budget readiness requires operator-provided PostgreSQL/HA, deployed browser-console, approval API, and duplicate-denial artifacts.",
            "When no live archive is supplied, this gate stays at live_status=skipped rather than claiming production-complete privacy-budget deployment.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "privacy_budget_deployment_evidence_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
