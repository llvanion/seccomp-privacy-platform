#!/usr/bin/env python3
"""Verifier-facing gate for live-capable identity authority evidence.

This module separates repo-side identity evidence from optionally-executed live
authority checks. It is intentionally usable in two modes:

1. Default repo-side mode: verifies local/frozen contract surfaces and reports
   which live prerequisites are still missing.
2. Live mode: when operator-provided OIDC/JWKS / metadata endpoint parameters
   are present, it executes the corresponding live checks and records their
   results alongside the repo-side baseline.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "live_identity_authority_evidence_gate/v1"


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


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def require_ok(res: subprocess.CompletedProcess[str], *, label: str) -> None:
    if res.returncode != 0:
        raise RuntimeError(f"{label} failed ({res.returncode})\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")


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


def main() -> int:
    ap = argparse.ArgumentParser(description="Aggregate repo-side and live-capable identity authority evidence.")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--live-token-endpoint", default="")
    ap.add_argument("--live-client-id", default="")
    ap.add_argument("--live-client-secret-env", default="")
    ap.add_argument("--live-scope", default="")
    ap.add_argument("--live-bearer-token-env", default="")
    ap.add_argument("--live-jwks-uri", default="")
    ap.add_argument("--live-issuer", default="https://keycloak.example.com/realms/commerce")
    ap.add_argument("--live-trusted-audience", action="append", default=[])
    ap.add_argument("--live-db-path", default="")
    ap.add_argument("--live-db-dsn", default="")
    ap.add_argument("--live-metadata-base-url", default="")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    repo_side_checks: list[dict[str, Any]] = []
    live_checks: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    repo_jwks_dir = out_dir / "repo_side_jwks"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "check_identity_jwks_evidence_gate.py"),
        "--out-dir", str(repo_jwks_dir),
    ])
    if res.returncode != 0:
        raise SystemExit(f"repo-side JWKS evidence gate failed\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")
    repo_jwks_report = load_json(repo_jwks_dir / "identity_jwks_evidence_gate.json")
    repo_side_checks.append(
        parse_check(
            name="repo_side_jwks_evidence_gate",
            status="ok" if repo_jwks_report.get("status") == "ok" else "fail",
            expected="repo-side RS256/JWKS verifier evidence is complete",
            actual=repo_jwks_report,
        )
    )
    artifacts.append(artifact(repo_jwks_dir / "identity_jwks_evidence_gate.json", schema="identity_jwks_evidence_gate/v1"))

    client_creds_dry_run_path = out_dir / "oidc_client_credentials_dry_run.json"
    dry_run_endpoint = args.live_token_endpoint or "https://keycloak.example.com/realms/commerce/protocol/openid-connect/token"
    dry_run_client_id = args.live_client_id or "seccomp-privacy-platform"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "request_oidc_client_credentials.py"),
        "--token-endpoint", dry_run_endpoint,
        "--client-id", dry_run_client_id,
        "--client-secret-env", args.live_client_secret_env or "OIDC_CLIENT_SECRET",
        "--scope", args.live_scope,
        "--output", str(client_creds_dry_run_path),
    ])
    if res.returncode != 0:
        raise SystemExit(f"oidc client credentials dry-run failed\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")
    client_creds_dry_run = load_json(client_creds_dry_run_path)
    repo_side_checks.append(
        parse_check(
            name="oidc_client_credentials_dry_run",
            status="ok" if client_creds_dry_run.get("ok") is True and client_creds_dry_run.get("mode") == "dry_run" else "fail",
            expected="client credentials adapter emits a dry-run report without requiring live secrets",
            actual=client_creds_dry_run,
        )
    )
    artifacts.append(artifact(client_creds_dry_run_path, schema="oidc_client_credentials_report/v1"))

    identity_proxy_path = out_dir / "identity_proxy_auth_smoke.json"
    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "check_identity_proxy_auth_smoke.py"),
        "--out", str(identity_proxy_path),
    ])
    if res.returncode != 0:
        raise SystemExit(f"identity proxy smoke failed\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")
    identity_proxy_report = load_json(identity_proxy_path)
    repo_side_checks.append(
        parse_check(
            name="identity_proxy_auth_smoke",
            status="ok" if identity_proxy_report.get("status") == "ok" else "fail",
            expected="identity proxy fails closed and overwrites spoofed headers",
            actual=identity_proxy_report,
        )
    )
    artifacts.append(artifact(identity_proxy_path, schema="identity_proxy_auth_smoke/v1"))

    live_token_env = args.live_bearer_token_env or "SECCOMP_LIVE_IDENTITY_GATE_TOKEN"
    live_token_file = out_dir / "live_access_token.txt"
    env = os.environ.copy()

    client_creds_missing: list[str] = []
    if not args.live_token_endpoint:
        client_creds_missing.append("--live-token-endpoint")
    if not args.live_client_id:
        client_creds_missing.append("--live-client-id")
    if not args.live_client_secret_env:
        client_creds_missing.append("--live-client-secret-env")
    if client_creds_missing:
        live_checks.append(
            parse_check(
                name="live_client_credentials_execute",
                status="skipped",
                expected="operator provides token endpoint, client id, and client secret env for a live client-credentials request",
                actual=None,
                missing_prerequisites=client_creds_missing,
            )
        )
    else:
        res = run([
            "python3",
            str(REPO_ROOT / "scripts" / "request_oidc_client_credentials.py"),
            "--token-endpoint", args.live_token_endpoint,
            "--client-id", args.live_client_id,
            "--client-secret-env", args.live_client_secret_env,
            "--scope", args.live_scope,
            "--token-output-file", str(live_token_file),
            "--execute",
            "--output", str(out_dir / "oidc_client_credentials_execute.json"),
            "--assert-ok",
        ], env=env)
        report = load_json(out_dir / "oidc_client_credentials_execute.json")
        live_checks.append(
            parse_check(
                name="live_client_credentials_execute",
                status="ok" if res.returncode == 0 and report.get("ok") is True else "fail",
                expected="operator-provided client credentials successfully return a live access token",
                actual=report,
            )
        )
        artifacts.append(artifact(out_dir / "oidc_client_credentials_execute.json", schema="oidc_client_credentials_report/v1"))
        if live_token_file.is_file():
            env[live_token_env] = live_token_file.read_text(encoding="utf-8").strip()

    if not env.get(live_token_env):
        live_checks.append(
            parse_check(
                name="live_oidc_claim_map",
                status="skipped",
                expected="a live bearer token is available for JWKS verification",
                actual=None,
                missing_prerequisites=["--live-bearer-token-env or successful live client credentials execute"],
            )
        )
    elif not args.live_jwks_uri:
        live_checks.append(
            parse_check(
                name="live_oidc_claim_map",
                status="skipped",
                expected="operator provides a live JWKS URI for claim verification",
                actual=None,
                missing_prerequisites=["--live-jwks-uri"],
            )
        )
    else:
        live_claim_map_path = out_dir / "oidc_claim_map_live.json"
        claim_cmd = [
            "python3",
            str(REPO_ROOT / "scripts" / "map_oidc_claims.py"),
            "--token-env", live_token_env,
            "--claim-mapping-config", str(REPO_ROOT / "config" / "oidc_claim_mapping.example.json"),
            "--jwks-uri", args.live_jwks_uri,
            "--output", str(live_claim_map_path),
        ]
        if args.live_db_path:
            claim_cmd.extend(["--db-path", args.live_db_path])
        if args.live_db_dsn:
            claim_cmd.extend(["--db-dsn", args.live_db_dsn])
        for audience in args.live_trusted_audience:
            claim_cmd.extend(["--trusted-audience", audience])
        if args.live_db_path or args.live_db_dsn:
            claim_cmd.append("--require-registered-issuer")
        res = run(claim_cmd, env=env)
        if res.returncode != 0:
            raise SystemExit(f"live oidc claim map failed\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")
        live_claim_map = load_json(live_claim_map_path)
        live_checks.append(
            parse_check(
                name="live_oidc_claim_map",
                status="ok" if live_claim_map.get("valid") is True else "fail",
                expected="live token verifies against operator-provided JWKS and maps identity claims",
                actual=live_claim_map,
            )
        )
        artifacts.append(artifact(live_claim_map_path, schema="oidc_claim_map/v1"))

    if not env.get(live_token_env) or not (args.live_db_path or args.live_db_dsn) or not args.live_jwks_uri:
        missing = []
        if not env.get(live_token_env):
            missing.append("live bearer token")
        if not (args.live_db_path or args.live_db_dsn):
            missing.append("--live-db-path/--live-db-dsn")
        if not args.live_jwks_uri:
            missing.append("--live-jwks-uri")
        live_checks.append(
            parse_check(
                name="live_api_identity_resolution",
                status="skipped",
                expected="live resolve_api_identity path checks issuer registry and caller mapping",
                actual=None,
                missing_prerequisites=missing,
            )
        )
    else:
        live_identity_config_path = out_dir / "live_api_identity_tokens.json"
        live_identity_config = {
            "schema": "api_identity_token_map/v1",
            "jwt_bearer": {
                "issuer": args.live_issuer,
                "claim_mapping_config": str(REPO_ROOT / "config" / "oidc_claim_mapping.example.json"),
                "jwks_uri": args.live_jwks_uri,
                "trusted_audiences": args.live_trusted_audience,
                "require_registered_issuer": True,
            },
            "tokens": [],
        }
        write_json(live_identity_config_path, live_identity_config)
        live_resolution_path = out_dir / "api_identity_resolution_live.json"
        cmd = [
            "python3",
            str(REPO_ROOT / "scripts" / "resolve_api_identity.py"),
            "--identity-token-config", str(live_identity_config_path),
            "--bearer-token-env", live_token_env,
        ]
        if args.live_db_path:
            cmd.extend(["--db-path", args.live_db_path])
        if args.live_db_dsn:
            cmd.extend(["--db-dsn", args.live_db_dsn])
        res = run(cmd, env=env)
        if res.returncode != 0:
            raise SystemExit(f"live api identity resolution failed\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")
        live_resolution_path.write_text(res.stdout, encoding="utf-8")
        live_resolution = load_json(live_resolution_path)
        live_checks.append(
            parse_check(
                name="live_api_identity_resolution",
                status="ok" if live_resolution.get("schema") == "api_identity_resolution/v1" else "fail",
                expected="live resolve_api_identity returns a typed identity resolution payload",
                actual=live_resolution,
            )
        )
        artifacts.append(artifact(live_resolution_path, schema="api_identity_resolution/v1"))

    if not env.get(live_token_env) or not args.live_metadata_base_url:
        missing = []
        if not env.get(live_token_env):
            missing.append("live bearer token")
        if not args.live_metadata_base_url:
            missing.append("--live-metadata-base-url")
        live_checks.append(
            parse_check(
                name="live_metadata_identity_endpoint",
                status="skipped",
                expected="operator provides a live metadata API /v1/identity endpoint",
                actual=None,
                missing_prerequisites=missing,
            )
        )
    else:
        live_metadata_path = out_dir / "metadata_api_identity_live.json"
        res = run([
            "python3",
            str(REPO_ROOT / "scripts" / "platform_api_client.py"),
            "metadata-identity",
            "--base-url", args.live_metadata_base_url,
            "--identity-token-env", live_token_env,
            "--output-file", str(live_metadata_path),
        ], env=env)
        if res.returncode != 0:
            raise SystemExit(f"live metadata identity endpoint check failed\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")
        live_metadata_identity = load_json(live_metadata_path)
        live_checks.append(
            parse_check(
                name="live_metadata_identity_endpoint",
                status="ok" if live_metadata_identity.get("schema") == "metadata_api_response/v1" else "fail",
                expected="live metadata API /v1/identity returns a resolved identity envelope",
                actual=live_metadata_identity,
            )
        )
        artifacts.append(artifact(live_metadata_path, schema="metadata_api_response/v1"))

    repo_side_status = "ok" if all(item["status"] == "ok" for item in repo_side_checks) else "fail"
    live_non_skipped = [item for item in live_checks if item["status"] != "skipped"]
    live_status = (
        "fail" if any(item["status"] == "fail" for item in live_checks)
        else "ok" if live_non_skipped
        else "skipped"
    )
    report = {
        "schema": "live_identity_authority_evidence_gate/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if repo_side_status == "ok" else "fail",
        "repo_side_status": repo_side_status,
        "live_status": live_status,
        "repo_side_checks": repo_side_checks,
        "live_checks": live_checks,
        "repo_side_boundary": [
            "Repo-side checks prove synthetic/file-JWKS and local proxy/adapter behavior only.",
            "They do not prove live issuer uptime, real TLS certificate chain, browser SSO, or operator-held secret custody.",
        ],
        "live_boundary": [
            "Live checks require operator-provided token endpoint, client secret, live JWKS URI, and optionally live metadata API / DB reachability.",
            "When those prerequisites are absent, this gate records skipped live checks rather than claiming production readiness.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "live_identity_authority_evidence_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
