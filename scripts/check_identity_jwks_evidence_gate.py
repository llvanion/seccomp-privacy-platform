#!/usr/bin/env python3
"""Verifier-facing gate for JWKS/OIDC-backed identity evidence."""
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
SCHEMA = "identity_jwks_evidence_gate/v1"
RUNTIME_HELPERS = REPO_ROOT / "scripts" / "runtime_service_helpers.py"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def artifact(path: Path, *, schema: str | None = None, note: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"path": str(path)}
    if schema:
        item["schema"] = schema
    if note:
        item["note"] = note
    return item


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def require_ok(res: subprocess.CompletedProcess[str], *, label: str) -> None:
    if res.returncode != 0:
        raise RuntimeError(f"{label} failed ({res.returncode})\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")


def available_port() -> int:
    res = run(["python3", str(RUNTIME_HELPERS), "available-port"])
    require_ok(res, label="available-port")
    return int(res.stdout.strip())


def wait_health(url: str) -> None:
    res = run(["python3", str(RUNTIME_HELPERS), "wait-json-health", "--url", url])
    require_ok(res, label=f"wait-json-health {url}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Aggregate JWKS/OIDC identity repo-side evidence.")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="identity_jwks_gate.") as tmp_raw:
        tmp_dir = Path(tmp_raw)

        export_policy = {
            "schema": "sse_export_policy/v1",
            "callers": {
                "recovery_ops_demo": {
                    "enabled": True,
                    "tenant_id": "commerce_tenant",
                    "allowed_dataset_ids": ["orders_analytics"],
                    "allowed_service_ids": ["orders-recovery"],
                    "platform_roles": ["service_operator"],
                    "allowed_roles": [],
                    "allowed_fields": [],
                    "allowed_join_key_fields": [],
                    "allowed_value_fields": [],
                    "allowed_filter_fields": [],
                    "required_filters": [],
                    "allowed_filter_values": {},
                    "max_export_rows": 1,
                    "min_export_rows": 0,
                    "can_use_record_recovery_service": True,
                    "can_run_bridge": False,
                    "can_run_pjc": False,
                    "can_release": False,
                },
                "commerce_ops_demo": {
                    "enabled": True,
                    "tenant_id": "commerce_tenant",
                    "allowed_dataset_ids": ["orders_analytics"],
                    "allowed_service_ids": ["orders-recovery"],
                    "platform_roles": ["query_submitter", "privacy_operator"],
                    "allowed_roles": ["server", "client"],
                    "allowed_fields": ["email", "amount", "campaign"],
                    "allowed_join_key_fields": ["email"],
                    "allowed_value_fields": ["amount"],
                    "allowed_filter_fields": ["campaign"],
                    "required_filters": ["campaign"],
                    "allowed_filter_values": {"campaign": ["retargeting", "loyalty"]},
                    "max_export_rows": 250000,
                    "min_export_rows": 100,
                    "can_use_record_recovery_service": True,
                    "can_run_bridge": True,
                    "can_run_pjc": True,
                    "can_release": True,
                },
                "marketing_analyst_demo": {
                    "enabled": True,
                    "tenant_id": "commerce_tenant",
                    "allowed_dataset_ids": ["orders_analytics"],
                    "allowed_service_ids": ["orders-recovery"],
                    "platform_roles": ["query_submitter"],
                    "allowed_roles": ["client"],
                    "allowed_fields": ["email", "amount", "campaign"],
                    "allowed_join_key_fields": ["email"],
                    "allowed_value_fields": ["amount"],
                    "allowed_filter_fields": ["campaign"],
                    "required_filters": ["campaign"],
                    "allowed_filter_values": {"campaign": ["retargeting", "loyalty"]},
                    "max_export_rows": 100000,
                    "min_export_rows": 100,
                    "can_use_record_recovery_service": True,
                    "can_run_bridge": True,
                    "can_run_pjc": True,
                    "can_release": False,
                },
            },
        }
        export_policy_path = tmp_dir / "jwks_export_policy.json"
        export_policy_path.write_text(json.dumps(export_policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        registry_manifest = {
            "schema": "metadata_registry_manifest/v1",
            "tenants": [{"tenant_id": "commerce_tenant", "source": "identity_jwks_gate"}],
            "datasets": [{"dataset_id": "orders_analytics", "tenant_id": "commerce_tenant", "source": "identity_jwks_gate"}],
            "services": [{
                "service_id": "orders-recovery",
                "tenant_id": "commerce_tenant",
                "dataset_id": "orders_analytics",
                "service_type": "record_recovery",
                "transport": "http",
                "config_path": "record_recovery_http_service.example.json",
            }],
            "callers": [
                {"caller": "recovery_ops_demo", "tenant_id": "commerce_tenant", "source": "identity_jwks_gate"},
                {"caller": "commerce_ops_demo", "tenant_id": "commerce_tenant", "source": "identity_jwks_gate"},
                {"caller": "marketing_analyst_demo", "tenant_id": "commerce_tenant", "source": "identity_jwks_gate"},
            ],
            "caller_identities": [
                {
                    "caller": "recovery_ops_demo",
                    "issuer": "https://keycloak.example.com/realms/commerce",
                    "subject": "service-account:orders-recovery-operator",
                    "subject_type": "service_account",
                    "service_id": "orders-recovery",
                    "display_name": "Recovery Ops Demo SA",
                    "platform_roles": ["service_operator"],
                    "enabled": True,
                    "metadata": {"entity_type": "service_account"},
                    "source": "identity_jwks_gate",
                },
                {
                    "caller": "commerce_ops_demo",
                    "issuer": "keycloak:commerce",
                    "subject": "user:commerce_ops_owner",
                    "subject_type": "human_user",
                    "display_name": "Commerce Ops Owner",
                    "platform_roles": ["query_submitter", "privacy_operator"],
                    "enabled": True,
                    "metadata": {"entity_type": "human_user"},
                    "source": "identity_jwks_gate",
                },
                {
                    "caller": "marketing_analyst_demo",
                    "issuer": "keycloak:commerce",
                    "subject": "user:marketing_analyst",
                    "subject_type": "human_user",
                    "display_name": "Marketing Analyst",
                    "platform_roles": ["query_submitter"],
                    "enabled": True,
                    "metadata": {"entity_type": "human_user"},
                    "source": "identity_jwks_gate",
                },
            ],
            "issuer_registry": [
                {
                    "issuer": "https://keycloak.example.com/realms/commerce",
                    "issuer_type": "keycloak",
                    "display_name": "Commerce Keycloak Realm",
                    "jwks_uri": f"file://{tmp_dir / 'oidc_test_jwks.json'}",
                    "token_endpoint": "https://keycloak.example.com/realms/commerce/protocol/openid-connect/token",
                    "claim_mapping": {
                        "caller": "preferred_username",
                        "subject": "sub",
                        "subject_type": "_const:service_account",
                        "display_name": "name",
                        "tenant_id": "tenant_id",
                        "service_id": "azp",
                        "platform_roles": "realm_access.roles",
                    },
                    "trusted_audiences": ["seccomp-privacy-platform"],
                    "enabled": True,
                    "source": "identity_jwks_gate",
                }
            ],
            "policies": [
                {
                    "path": str(export_policy_path),
                    "required_schema": "sse_export_policy/v1",
                }
            ],
        }
        registry_manifest_path = tmp_dir / "jwks_registry_manifest.json"
        registry_manifest_path.write_text(json.dumps(registry_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        db_path = tmp_dir / "platform_registry.db"
        res = run([
            "python3",
            str(REPO_ROOT / "scripts" / "manage_metadata_db.py"),
            "apply-registry",
            "--db-path", str(db_path),
            "--manifest", str(registry_manifest_path),
        ])
        require_ok(res, label="apply-registry")

        # Generate synthetic RS256 token + JWKS.
        generate_rs256_script = tmp_dir / "generate_rs256_jwks.py"
        generate_rs256_script.write_text(
            "import base64, json, sys, time\n"
            "from cryptography.hazmat.primitives import hashes\n"
            "from cryptography.hazmat.primitives.asymmetric import padding, rsa\n"
            "\n"
            "def b64u(data: bytes) -> str:\n"
            "    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')\n"
            "\n"
            "jwks_path, token_path = sys.argv[1], sys.argv[2]\n"
            "key = rsa.generate_private_key(public_exponent=65537, key_size=2048)\n"
            "pub = key.public_key().public_numbers()\n"
            "header = {'alg': 'RS256', 'typ': 'JWT', 'kid': 'demo-kid-1'}\n"
            "payload = {\n"
            "    'iss': 'https://keycloak.example.com/realms/commerce',\n"
            "    'sub': 'service-account:orders-recovery-operator',\n"
            "    'preferred_username': 'recovery_ops_demo',\n"
            "    'azp': 'orders-recovery',\n"
            "    'tenant_id': 'commerce_tenant',\n"
            "    'realm_access': {'roles': ['service_operator']},\n"
            "    'aud': 'seccomp-privacy-platform',\n"
            "    'exp': int(time.time()) + 3600,\n"
            "    'iat': int(time.time()),\n"
            "    'name': 'Recovery Ops Demo SA',\n"
            "}\n"
            "h = b64u(json.dumps(header, separators=(',', ':')).encode())\n"
            "p = b64u(json.dumps(payload, separators=(',', ':')).encode())\n"
            "sig = key.sign(f'{h}.{p}'.encode('ascii'), padding.PKCS1v15(), hashes.SHA256())\n"
            "token = f'{h}.{p}.{b64u(sig)}'\n"
            "json.dump({'keys': [{'kty': 'RSA', 'kid': 'demo-kid-1', 'alg': 'RS256', 'use': 'sig', 'n': b64u(pub.n.to_bytes((pub.n.bit_length() + 7) // 8, 'big')), 'e': b64u(pub.e.to_bytes((pub.e.bit_length() + 7) // 8, 'big'))}]}, open(jwks_path, 'w', encoding='utf-8'))\n"
            "open(token_path, 'w', encoding='utf-8').write(token)\n",
            encoding="utf-8",
        )
        res = run([
            "python3",
            str(generate_rs256_script),
            str(tmp_dir / "oidc_test_jwks.json"),
            str(tmp_dir / "oidc_test_rs256.jwt"),
        ])
        require_ok(res, label="generate-rs256-jwks")
        token = (tmp_dir / "oidc_test_rs256.jwt").read_text(encoding="utf-8").strip()

        oidc_claim_map_path = out_dir / "oidc_claim_map_rs256.json"
        res = run([
            "python3",
            str(REPO_ROOT / "scripts" / "map_oidc_claims.py"),
            "--token", token,
            "--claim-mapping-config", str(REPO_ROOT / "config" / "oidc_claim_mapping.example.json"),
            "--jwks-uri", f"file://{tmp_dir / 'oidc_test_jwks.json'}",
            "--db-path", str(db_path),
            "--trusted-audience", "seccomp-privacy-platform",
            "--require-registered-issuer",
            "--output", str(oidc_claim_map_path),
        ])
        require_ok(res, label="oidc-claim-map-rs256")

        identity_token_config = {
            "schema": "api_identity_token_map/v1",
            "jwt_bearer": {
                "issuer": "https://keycloak.example.com/realms/commerce",
                "claim_mapping_config": str(REPO_ROOT / "config" / "oidc_claim_mapping.example.json"),
                "jwks_uri": f"file://{tmp_dir / 'oidc_test_jwks.json'}",
                "trusted_audiences": ["seccomp-privacy-platform"],
                "require_registered_issuer": True,
            },
            "tokens": [],
        }
        identity_token_config_path = tmp_dir / "api_identity_tokens_jwks.json"
        identity_token_config_path.write_text(json.dumps(identity_token_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        env = os.environ.copy()
        env["SECCOMP_METADATA_JWKS_TOKEN"] = token
        api_identity_resolution_path = out_dir / "api_identity_resolution_jwks.json"
        res = run([
            "python3",
            str(REPO_ROOT / "scripts" / "resolve_api_identity.py"),
            "--db-path", str(db_path),
            "--identity-token-config", str(identity_token_config_path),
            "--bearer-token-env", "SECCOMP_METADATA_JWKS_TOKEN",
        ], env=env)
        require_ok(res, label="resolve-api-identity")
        api_identity_resolution_path.write_text(res.stdout, encoding="utf-8")

        # Start JWKS-backed metadata API and query its /v1/identity path.
        port = available_port()
        metadata_proc = subprocess.Popen(
            [
                "python3",
                str(REPO_ROOT / "scripts" / "serve_metadata_api.py"),
                "--db-path", str(db_path),
                "--bind-host", "127.0.0.1",
                "--port", str(port),
                "--identity-token-config", str(identity_token_config_path),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_health(f"http://127.0.0.1:{port}/healthz")
            res = run([
                "python3",
                str(REPO_ROOT / "scripts" / "platform_api_client.py"),
                "metadata-identity",
                "--base-url", f"http://127.0.0.1:{port}",
                "--identity-token-env", "SECCOMP_METADATA_JWKS_TOKEN",
                "--output-file", str(out_dir / "metadata_api_identity_jwks.json"),
            ], env=env)
            require_ok(res, label="metadata-identity-jwks")
        finally:
            metadata_proc.terminate()
            metadata_proc.wait(timeout=10)

        keyring_jwks_path = tmp_dir / "keyring_jwks.json"
        keyring_payload = json.loads((REPO_ROOT / "config" / "keyring.example.json").read_text(encoding="utf-8"))
        keyring_payload["keys"]["bridge-token"]["allowed_callers"] = ["recovery_ops_demo"]
        keyring_jwks_path.write_text(json.dumps(keyring_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        env["BRIDGE_TOKEN_SECRET"] = "contract-jwks-bridge-secret"

        key_agent_socket = tmp_dir / "key_agent_jwks.sock"
        key_agent_audit = out_dir / "key_agent_jwks_access_audit.jsonl"
        key_agent_proc = subprocess.Popen(
            [
                "python3",
                str(REPO_ROOT / "scripts" / "key_agent_service.py"),
                "--socket-path", str(key_agent_socket),
                "--keyring", str(keyring_jwks_path),
                "--metadata-db-path", str(db_path),
                "--identity-token-config", str(identity_token_config_path),
                "--audit-log", str(key_agent_audit),
                "--ready-file", str(tmp_dir / "key_agent_jwks.ready"),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            ready_file = tmp_dir / "key_agent_jwks.ready"
            for _ in range(100):
                if ready_file.exists():
                    break
                subprocess.run(["sleep", "0.1"], check=False)
            else:
                raise RuntimeError("key agent did not become ready")
            res = run([
                "python3",
                str(REPO_ROOT / "scripts" / "request_key_agent.py"),
                "--socket-path", str(key_agent_socket),
                "--key-name", "bridge-token",
                "--purpose", "bridge_token",
                "--caller", "recovery_ops_demo",
                "--job-id", "identity-jwks-gate",
                "--identity-token-env", "SECCOMP_METADATA_JWKS_TOKEN",
            ], env=env)
            require_ok(res, label="request-key-agent-jwks")
            key_agent_result_path = out_dir / "key_agent_jwks_result.json"
            key_agent_result_path.write_text(res.stdout, encoding="utf-8")
        finally:
            key_agent_proc.terminate()
            key_agent_proc.wait(timeout=10)

        external_kms_port = available_port()
        external_kms_config_path = tmp_dir / "external_kms_jwks.json"
        external_kms_state_path = tmp_dir / "keyring_external_jwks.json"
        res = run([
            "python3",
            str(REPO_ROOT / "scripts" / "build_runtime_contract_smoke_configs.py"),
            "external-kms",
            "--out-config", str(external_kms_config_path),
            "--state-path", str(external_kms_state_path),
            "--port", str(external_kms_port),
        ])
        require_ok(res, label="build-external-kms-config")
        external_kms_state_path.write_text(json.dumps(keyring_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        env["SECCOMP_EXTERNAL_KMS_TOKEN"] = "contract-external-kms-token"
        env["SECCOMP_EXTERNAL_KMS_ADMIN_TOKEN"] = "contract-external-kms-admin-token"
        external_kms_proc = subprocess.Popen(
            [
                "python3",
                str(REPO_ROOT / "scripts" / "external_kms_service.py"),
                "--bind-host", "127.0.0.1",
                "--port", str(external_kms_port),
                "--state-file", str(external_kms_state_path),
                "--metadata-db-path", str(db_path),
                "--identity-token-config", str(identity_token_config_path),
                "--lifecycle-audit-log", str(out_dir / "external_kms_jwks_lifecycle_audit.jsonl"),
                "--ready-file", str(tmp_dir / "external_kms_jwks.ready"),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_health(f"http://127.0.0.1:{external_kms_port}/healthz")
            external_kms_audit = out_dir / "external_key_access_jwks_audit.jsonl"
            res = run([
                "python3",
                str(REPO_ROOT / "scripts" / "request_external_kms.py"),
                "--config", str(external_kms_config_path),
                "--key-name", "bridge-token",
                "--purpose", "bridge_token",
                "--caller", "recovery_ops_demo",
                "--job-id", "identity-jwks-gate",
                "--identity-token-env", "SECCOMP_METADATA_JWKS_TOKEN",
                "--audit-log", str(external_kms_audit),
            ], env=env)
            require_ok(res, label="request-external-kms-jwks")
            external_kms_result_path = out_dir / "external_kms_jwks_result.json"
            external_kms_result_path.write_text(res.stdout, encoding="utf-8")
        finally:
            external_kms_proc.terminate()
            external_kms_proc.wait(timeout=10)

        report = {
            "schema": SCHEMA,
            "generated_at_utc": utc_now_iso(),
            "status": "ok",
            "checks": [
                {
                    "name": "oidc_claim_map_rs256",
                    "status": "ok",
                    "expected": "RS256 token verifies against file:// JWKS and maps caller/tenant/platform_roles",
                    "actual": load_json(oidc_claim_map_path),
                },
                {
                    "name": "api_identity_resolution_jwks",
                    "status": "ok",
                    "expected": "JWKS-backed resolve_api_identity returns recovery_ops_demo with commerce_tenant scope",
                    "actual": load_json(api_identity_resolution_path),
                },
                {
                    "name": "metadata_api_identity_jwks",
                    "status": "ok",
                    "expected": "JWKS-backed /v1/identity endpoint returns recovery_ops_demo through HTTP path",
                    "actual": load_json(out_dir / "metadata_api_identity_jwks.json"),
                },
                {
                    "name": "key_agent_jwks_identity_access",
                    "status": "ok",
                    "expected": "JWKS-backed key agent allows recovery_ops_demo and returns demo-v1 secret",
                    "actual": load_json(out_dir / "key_agent_jwks_result.json"),
                },
                {
                    "name": "external_kms_jwks_identity_access",
                    "status": "ok",
                    "expected": "JWKS-backed external KMS allows recovery_ops_demo and returns demo-v1 secret",
                    "actual": load_json(out_dir / "external_kms_jwks_result.json"),
                },
            ],
            "repo_side_boundary": [
                "This gate uses a synthetic RS256 token and offline file:// JWKS, not a live Keycloak realm or HTTPS JWKS endpoint.",
                "It proves verifier-readable JWT/JWKS claim mapping and identity resolution behavior, not live issuer availability, browser login, or production secret custody.",
            ],
            "artifacts": [
                artifact(oidc_claim_map_path, schema="oidc_claim_map/v1"),
                artifact(api_identity_resolution_path, schema="api_identity_resolution/v1"),
                artifact(out_dir / "metadata_api_identity_jwks.json", schema="metadata_api_response/v1"),
                artifact(out_dir / "key_agent_jwks_result.json", schema="key_agent_result/v1"),
                artifact(out_dir / "key_agent_jwks_access_audit.jsonl", schema="key_access_audit/v1"),
                artifact(out_dir / "external_kms_jwks_result.json", schema="external_kms_result/v1"),
                artifact(out_dir / "external_key_access_jwks_audit.jsonl", schema="key_access_audit/v1"),
            ],
        }
        write_json(out_dir / "identity_jwks_evidence_gate.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
