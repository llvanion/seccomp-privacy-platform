#!/usr/bin/env python3
"""Verifier-facing gate for authority / KMS / identity evidence."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "authority_evidence_gate/v1"
DEFAULT_LIVE_ARCHIVE = REPO_ROOT / "tmp" / "authority_live_archive" / "authority_live_evidence_archive.json"


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


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=full_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def require_ok(res: subprocess.CompletedProcess[str], *, label: str) -> None:
    if res.returncode != 0:
        raise RuntimeError(f"{label} failed ({res.returncode})\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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

    synthetic_dir = out_dir / "repo_side_inputs"
    synthetic_dir.mkdir(parents=True, exist_ok=True)

    policy_drift_path = synthetic_dir / "policy_drift_clean.json"
    write_json(policy_drift_path, {
        "schema": "policy_drift/v1",
        "summary": {"status": "clean", "registered_policy_count": 1, "total_findings": 0},
    })
    key_drift_path = synthetic_dir / "key_backend_drift_clean.json"
    write_json(key_drift_path, {
        "schema": "key_backend_drift/v1",
        "summary": {"status": "clean", "ref_key_count": 2, "db_key_count": 2, "actionable_findings": 0, "informational_findings": 0},
    })
    identity_bearer_path = synthetic_dir / "api_identity_resolution_bearer.json"
    write_json(identity_bearer_path, {
        "schema": "api_identity_resolution/v1",
        "resolution_mode": "bearer_token",
        "identity": {"caller": "commerce_ops_demo", "platform_roles": ["platform_admin"]},
        "access_summary": {"query_submit_allowed": True, "query_execute_allowed": True},
    })
    identity_subject_path = synthetic_dir / "api_identity_resolution_subject.json"
    write_json(identity_subject_path, {
        "schema": "api_identity_resolution/v1",
        "resolution_mode": "subject_lookup",
        "identity": {"caller": "commerce_ops_demo", "platform_roles": ["platform_admin"]},
        "access_summary": {"query_submit_allowed": True, "query_execute_allowed": True},
    })
    openfga_check_path = synthetic_dir / "openfga_check_allowed.json"
    write_json(openfga_check_path, {
        "schema": "openfga_check_result/v1",
        "user": "user:commerce_ops_demo",
        "relation": "query_submitter",
        "object": "dataset:orders_analytics",
        "allowed": True,
        "tuple_store_path": str(REPO_ROOT / "config" / "openfga.example.json"),
        "backend_kind": "sqlite_fallback",
    })
    synthetic_env = {
        "A5_KMS_ENV_SECRET": "contract-kms-reachability-secret",
        "A5_SERVICE_TOKEN_SIGNING_KEY": "contract-service-token-signing-secret",
    }

    kms_path = synthetic_dir / "kms_reachability_authority.json"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "check_kms_reachability.py"),
        "--keyring", str(REPO_ROOT / "config" / "keyring.example.json"),
        "--vault-kv-file", str(REPO_ROOT / "config" / "vault_kv_backend.example.json"),
        "--env-var", "A5_KMS_ENV_SECRET",
        "--output", str(kms_path),
        "--assert-ok",
    ], env=synthetic_env)
    require_ok(res, label="check_kms_reachability")

    service_token_issue_path = synthetic_dir / "service_token_issue.json"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "manage_service_tokens.py"),
        "--token-store", str(synthetic_dir / "service_tokens.db"),
        "issue",
        "--token-store", str(synthetic_dir / "service_tokens.db"),
        "--service-id", "orders-recovery",
        "--signing-key-env", "A5_SERVICE_TOKEN_SIGNING_KEY",
        "--scope", "record_recovery",
        "--issuer", "local-contract",
        "--output", str(service_token_issue_path),
    ], env=synthetic_env)
    require_ok(res, label="manage_service_tokens issue")
    issued = load_json(service_token_issue_path)
    token = str(issued.get("token") or "")
    if not token:
        raise RuntimeError("service token issue report missing token")
    service_token_verify_path = synthetic_dir / "service_token_verify.json"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "manage_service_tokens.py"),
        "--token-store", str(synthetic_dir / "service_tokens.db"),
        "verify",
        "--token-store", str(synthetic_dir / "service_tokens.db"),
        "--token", token,
        "--signing-key-env", "A5_SERVICE_TOKEN_SIGNING_KEY",
        "--output", str(service_token_verify_path),
    ], env=synthetic_env)
    require_ok(res, label="manage_service_tokens verify")

    issuer_rotation_path = synthetic_dir / "issuer_rotation_dry.json"
    write_json(issuer_rotation_path, {
        "schema": "issuer_credential_rotation/v1",
        "ok": True,
        "mode": "dry_run",
        "issuer": "https://keycloak.example.com/realms/commerce",
        "issuer_type": "keycloak",
        "key_rotation_count": 1,
    })

    authority_governance_path = out_dir / "authority_governance_report.json"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "check_authority_governance.py"),
        "--policy-drift", str(policy_drift_path),
        "--key-drift", str(key_drift_path),
        "--identity-resolution", str(identity_bearer_path),
        "--identity-resolution", str(identity_subject_path),
        "--openfga-check", str(openfga_check_path),
        "--kms-reachability", str(kms_path),
        "--service-token-report", str(service_token_issue_path),
        "--service-token-report", str(service_token_verify_path),
        "--issuer-rotation", str(issuer_rotation_path),
        "--output", str(authority_governance_path),
    ])
    require_ok(res, label="check_authority_governance")
    authority_governance = load_json(authority_governance_path)
    repo_side_checks.append(
        parse_check(
            name="repo_side_authority_governance",
            status="ok" if authority_governance.get("overall_status") == "ok" else "fail",
            expected="authority governance rollup remains clean across policy/key/identity/authz/kms/service-token/issuer categories",
            actual=authority_governance,
        )
    )
    artifacts.append(artifact(authority_governance_path, schema="authority_governance_report/v1"))

    live_identity_dir = out_dir / "live_identity_authority"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "check_live_identity_authority_evidence_gate.py"),
        "--out-dir", str(live_identity_dir),
    ])
    if res.returncode == 0:
        live_identity_report = load_json(live_identity_dir / "live_identity_authority_evidence_gate.json")
        repo_side_checks.append(
            parse_check(
                name="repo_side_live_identity_authority_gate",
                status="ok" if live_identity_report.get("repo_side_status") == "ok" else "fail",
                expected="live identity authority gate remains green on its repo-side baseline",
                actual=live_identity_report,
            )
        )
        artifacts.append(artifact(live_identity_dir / "live_identity_authority_evidence_gate.json", schema="live_identity_authority_evidence_gate/v1"))
    else:
        combined = "\n".join(part for part in ((res.stdout or "").strip(), (res.stderr or "").strip()) if part)
        if "PermissionError" in combined and ("socket" in combined or "Operation not permitted" in combined):
            repo_side_checks.append(
                parse_check(
                    name="repo_side_live_identity_authority_gate",
                    status="skipped",
                    expected="live identity authority gate remains green on its repo-side baseline",
                    actual={"stdout": res.stdout, "stderr": res.stderr},
                    missing_prerequisites=["environment permits loopback listener sockets for JWKS/identity authority smoke"],
                )
            )
        else:
            require_ok(res, label="check_live_identity_authority_evidence_gate")

    archive_path = Path(args.live_evidence_archive).resolve() if args.live_evidence_archive else None
    if archive_path is None:
        archive_path = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname="authority_live_archive",
            archive_filename="authority_live_evidence_archive.json",
            expected_schema="authority_live_evidence_archive/v1",
        )
        if archive_path is None and DEFAULT_LIVE_ARCHIVE.is_file():
            archive_path = DEFAULT_LIVE_ARCHIVE.resolve()
    if archive_path is None:
        live_checks.append(
            parse_check(
                name="live_authority_evidence_archive",
                status="skipped",
                expected="operator provides a unified live authority evidence archive",
                actual=None,
                missing_prerequisites=["--live-evidence-archive or tmp/authority_live_archive/authority_live_evidence_archive.json"],
            )
        )
    elif not archive_path.is_file():
        live_checks.append(
            parse_check(
                name="live_authority_evidence_archive",
                status="fail",
                expected="operator provides a unified live authority evidence archive",
                actual={"path": str(archive_path), "exists": False},
            )
        )
    else:
        archive = load_json(archive_path)
        artifacts.append(artifact(archive_path, schema="authority_live_evidence_archive/v1"))
        live_artifact_count = int(archive.get("live_artifact_count") or 0)
        live_checks.append(
            parse_check(
                name="live_authority_evidence_archive",
                status="ok" if archive.get("status") == "ok" and live_artifact_count > 0 else "skipped" if archive.get("status") == "ok" else "fail",
                expected="operator provides a unified live authority evidence archive",
                actual=archive,
                missing_prerequisites=["archive contains no live authority artifacts"] if archive.get("status") == "ok" and live_artifact_count == 0 else None,
            )
        )
        foundation_present = isinstance((archive.get("live_artifacts") or {}).get("live_repo_side_authority_foundation"), dict)
        live_checks.append(
            parse_check(
                name="live_authority_foundation",
                status="ok" if foundation_present else "skipped",
                expected="current-worktree authority governance/live-identity foundation is frozen into the live authority archive",
                actual=(archive.get("live_artifacts") or {}).get("live_repo_side_authority_foundation"),
                missing_prerequisites=["live_repo_side_authority_foundation not present in authority live archive"] if not foundation_present else None,
            )
        )
        authority_live_present = any(
            isinstance((archive.get("live_artifacts") or {}).get(name), dict)
            for name in (
                "live_keycloak_report",
                "live_openfga_report",
                "live_vault_report",
                "live_cloud_kms_report",
                "live_rotation_report",
            )
        )
        live_checks.append(
            parse_check(
                name="live_real_authority_rollout",
                status="ok" if authority_live_present else "skipped",
                expected="real Keycloak/OpenFGA/Vault/cloud-KMS/rotation deployment artifacts are archived",
                actual={
                    key: (archive.get("live_artifacts") or {}).get(key)
                    for key in (
                        "live_keycloak_report",
                        "live_openfga_report",
                        "live_vault_report",
                        "live_cloud_kms_report",
                        "live_rotation_report",
                    )
                },
                missing_prerequisites=["real authority rollout artifacts are still missing"] if not authority_live_present else None,
            )
        )

    repo_side_status = "ok" if all(item["status"] in {"ok", "skipped"} for item in repo_side_checks) else "fail"
    concrete_live = [item for item in live_checks if item["name"] == "live_authority_evidence_archive"]
    authority_live = [item for item in live_checks if item["name"] == "live_real_authority_rollout"]
    if any(item["status"] == "fail" for item in concrete_live):
        live_status = "fail"
    elif authority_live and all(item["status"] == "ok" for item in authority_live):
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
            "Repo-side checks prove governance rollups, adapters, and dry-run/live-capable authority hooks remain coherent.",
            "They do not prove a real Keycloak/OpenFGA/Vault/cloud-KMS deployment, secret custody, or break-glass workflow on target infrastructure.",
        ],
        "live_boundary": [
            "Live authority readiness requires operator-provided evidence for real Keycloak/OIDC, OpenFGA, Vault/cloud-KMS, and rotation/revocation drills.",
            "When no live archive is supplied, this gate stays at live_status=skipped rather than claiming production-complete authority rollout.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "authority_evidence_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
