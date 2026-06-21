#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_cmd(args: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=str(cwd or REPO_ROOT), check=True)


def build_demo_registry_manifest(out_path: Path) -> None:
    payload = {
        "schema": "metadata_registry_manifest/v1",
        "tenants": [
            {"tenant_id": "demo_tenant", "source": "defense_demo"},
            {"tenant_id": "commerce_tenant", "source": "defense_demo"},
            {"tenant_id": "privacy_tenant", "source": "defense_demo"},
        ],
        "datasets": [
            {"dataset_id": "bridge_demo_dataset", "tenant_id": "demo_tenant", "source": "defense_demo"},
            {"dataset_id": "orders_analytics", "tenant_id": "commerce_tenant", "source": "defense_demo"},
        ],
        "services": [
            {
                "service_id": "bridge-demo-recovery",
                "tenant_id": "demo_tenant",
                "dataset_id": "bridge_demo_dataset",
                "service_type": "record_recovery",
                "transport": "http",
                "config_path": str((REPO_ROOT / "config" / "record_recovery_http_service.example.json").resolve()),
            }
        ],
        "callers": [
            {"caller": "auto_demo", "tenant_id": "demo_tenant", "source": "defense_demo"},
            {"caller": "console_operator", "tenant_id": "demo_tenant", "source": "defense_demo"},
            {"caller": "privacy_requester", "tenant_id": "privacy_tenant", "source": "defense_demo"},
            {"caller": "privacy_operator", "tenant_id": "privacy_tenant", "source": "defense_demo"},
        ],
        "caller_identities": [
            {
                "caller": "auto_demo",
                "issuer": "local",
                "subject": "user:auto_demo",
                "subject_type": "human_user",
                "display_name": "Auto Demo",
                "platform_roles": ["query_submitter", "privacy_operator"],
                "enabled": True,
                "metadata": {"entity_type": "human_user"},
                "source": "defense_demo",
            },
            {
                "caller": "console_operator",
                "issuer": "local",
                "subject": "user:console_operator",
                "subject_type": "human_user",
                "display_name": "Console Operator",
                "platform_roles": ["platform_admin", "privacy_operator"],
                "enabled": True,
                "metadata": {"entity_type": "human_user"},
                "source": "defense_demo",
            },
            {
                "caller": "privacy_requester",
                "issuer": "local",
                "subject": "user:requester",
                "subject_type": "human_user",
                "display_name": "Privacy Requester",
                "platform_roles": ["query_submitter"],
                "enabled": True,
                "metadata": {"entity_type": "human_user"},
                "source": "defense_demo",
            },
            {
                "caller": "privacy_operator",
                "issuer": "local",
                "subject": "user:operator",
                "subject_type": "human_user",
                "display_name": "Privacy Operator",
                "platform_roles": ["privacy_operator"],
                "enabled": True,
                "metadata": {"entity_type": "human_user"},
                "source": "defense_demo",
            },
        ],
        "key_refs": [
            {
                "key_name": "bridge-token",
                "purpose": "bridge_token",
                "service_id": "bridge-demo-recovery",
                "backend_kind": "local_keyring",
                "backend_ref": str((REPO_ROOT / "config" / "keyring.example.json").resolve()) + "#keys.bridge-token",
                "active_version": "demo-v1",
                "allowed_callers": ["auto_demo", "console_operator"],
                "source": "defense_demo",
                "versions": [
                    {
                        "version": "demo-v1",
                        "enabled": True,
                        "status": "active",
                        "secret_ref_kind": "env",
                        "secret_ref_name": "BRIDGE_TOKEN_SECRET",
                        "created_at_utc": "2026-04-12T00:00:00Z",
                        "source": "defense_demo",
                    }
                ],
            }
        ],
        "issuer_registry": [
            {
                "issuer": "local",
                "issuer_type": "local",
                "display_name": "Local static token map",
                "enabled": True,
                "source": "defense_demo",
            }
        ],
        "policies": [
            {
                "path": str((REPO_ROOT / "sse" / "config" / "export_policy.example.json").resolve()),
                "required_schema": "sse_export_policy/v1",
            }
        ],
    }
    write_json(out_path, payload)


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def seed_privacy_budget_identity(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO callers(
              caller, tenant_id, created_at_utc, source, last_seen_job_id
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("console_operator", "privacy_tenant", "2026-06-21T00:00:00Z", "defense_demo", None),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO caller_identities(
              caller, issuer, subject, subject_type, service_id, display_name,
              platform_roles_json, enabled, metadata_json, source, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "console_operator",
                "local",
                "user:console_operator",
                "human_user",
                None,
                "Console Operator",
                json.dumps(["platform_admin", "privacy_operator"], ensure_ascii=False),
                1,
                json.dumps({"entity_type": "human_user"}, ensure_ascii=False),
                "defense_demo",
                "2026-06-21T00:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Prepare a self-contained defense demo workspace.")
    ap.add_argument("--out-dir", default="tmp/defense_demo", help="Output demo directory")
    args = ap.parse_args()

    out_dir = (REPO_ROOT / args.out_dir).resolve() if not Path(args.out_dir).is_absolute() else Path(args.out_dir).resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    completed_run_src = REPO_ROOT / "tmp" / "live_sse_bridge_demo" / "run-20260504T023757Z"
    dashboard_run_src = REPO_ROOT / "tmp" / "operator_dashboard_jobtest2"
    metadata_src = REPO_ROOT / "tmp" / "platform_metadata.db"
    business_src = REPO_ROOT / "tmp" / "business_access_api_smoke" / "metadata.sqlite"
    privacy_metadata_src = REPO_ROOT / "tmp" / "privacy_budget_approval_api_smoke" / "metadata.sqlite"
    privacy_store_src = REPO_ROOT / "tmp" / "privacy_budget_approval_api_smoke" / "budget.sqlite"
    privacy_queue_src = REPO_ROOT / "tmp" / "privacy_budget_approval_api_smoke" / "approval_queue.jsonl"
    privacy_decisions_src = REPO_ROOT / "tmp" / "privacy_budget_approval_api_smoke" / "approval_decisions.jsonl"

    required = [
        completed_run_src,
        dashboard_run_src,
        metadata_src,
        business_src,
        privacy_metadata_src,
        privacy_store_src,
        privacy_queue_src,
        privacy_decisions_src,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("[ERROR] missing source demo artifacts:\n" + "\n".join(missing))

    runs_dir = out_dir / "runs"
    copy_tree(completed_run_src, runs_dir / "main_completed_run")
    copy_tree(dashboard_run_src, runs_dir / "operator_fixture_run")

    db_dir = out_dir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(metadata_src, db_dir / "platform_metadata.db")
    shutil.copy2(business_src, db_dir / "business_access.sqlite")
    shutil.copy2(privacy_metadata_src, db_dir / "privacy_budget.sqlite.metadata")
    shutil.copy2(privacy_store_src, db_dir / "privacy_budget.sqlite")
    shutil.copy2(privacy_queue_src, db_dir / "approval_queue.jsonl")
    shutil.copy2(privacy_decisions_src, db_dir / "approval_decisions.jsonl")
    seed_privacy_budget_identity(db_dir / "privacy_budget.sqlite.metadata")

    registry_manifest = out_dir / "config" / "demo_registry_manifest.json"
    build_demo_registry_manifest(registry_manifest)
    run_cmd(
        [
            sys.executable,
            str(SCRIPTS_DIR / "manage_metadata_db.py"),
            "apply-registry",
            "--db-path",
            str(db_dir / "platform_metadata.db"),
            "--manifest",
            str(registry_manifest),
            "--output",
            str(out_dir / "reports" / "platform_registry_apply_report.json"),
        ]
    )

    tokens_payload = {
        "schema": "api_identity_token_map/v1",
        "tokens": [
            {"token_env": "DEFENSE_DEMO_AUTO_DEMO_TOKEN", "issuer": "local", "subject": "user:auto_demo"},
            {"token_env": "DEFENSE_DEMO_CONSOLE_OPERATOR_TOKEN", "issuer": "local", "subject": "user:console_operator"},
            {"token_env": "DEFENSE_DEMO_PRIVACY_REQUESTER_TOKEN", "issuer": "local", "subject": "user:requester"},
            {"token_env": "DEFENSE_DEMO_PRIVACY_OPERATOR_TOKEN", "issuer": "local", "subject": "user:operator"},
            {"token_env": "DEFENSE_DEMO_BUYER_TOKEN", "issuer": "local", "subject": "user:buyer"},
            {"token_env": "DEFENSE_DEMO_MERCHANT_TOKEN", "issuer": "local", "subject": "user:merchant"},
            {"token_env": "DEFENSE_DEMO_SUPPORT_TOKEN", "issuer": "local", "subject": "user:support"},
            {"token_env": "DEFENSE_DEMO_FRAUD_TOKEN", "issuer": "local", "subject": "user:fraud"},
            {"token_env": "DEFENSE_DEMO_MARKETER_TOKEN", "issuer": "local", "subject": "user:marketer"},
            {"token_env": "DEFENSE_DEMO_COURIER_TOKEN", "issuer": "local", "subject": "user:courier"},
            {"token_env": "DEFENSE_DEMO_STATION_TOKEN", "issuer": "local", "subject": "user:station"},
            {"token_env": "DEFENSE_DEMO_LAST_MILE_TOKEN", "issuer": "local", "subject": "user:last-mile"},
        ],
    }
    write_json(out_dir / "config" / "identity_tokens.json", tokens_payload)

    env_template = """# Source this before starting the defense demo services
export DEFENSE_DEMO_SHARED_TOKEN=demo-token
export DEFENSE_DEMO_AUTO_DEMO_TOKEN=demo-auto-demo-token
export DEFENSE_DEMO_CONSOLE_OPERATOR_TOKEN=demo-console-operator-token
export DEFENSE_DEMO_PRIVACY_REQUESTER_TOKEN=demo-privacy-requester-token
export DEFENSE_DEMO_PRIVACY_OPERATOR_TOKEN=demo-privacy-operator-token
export DEFENSE_DEMO_BUYER_TOKEN=demo-buyer-token
export DEFENSE_DEMO_MERCHANT_TOKEN=demo-merchant-token
export DEFENSE_DEMO_SUPPORT_TOKEN=demo-support-token
export DEFENSE_DEMO_FRAUD_TOKEN=demo-fraud-token
export DEFENSE_DEMO_MARKETER_TOKEN=demo-marketer-token
export DEFENSE_DEMO_COURIER_TOKEN=demo-courier-token
export DEFENSE_DEMO_STATION_TOKEN=demo-station-token
export DEFENSE_DEMO_LAST_MILE_TOKEN=demo-last-mile-token
export SSE_RECORD_RECOVERY_TOKEN=demo-recovery-token
export BRIDGE_TOKEN_SECRET=local-dev-secret
"""
    (out_dir / "env.demo.sh").write_text(env_template, encoding="utf-8")

    request_payload = {
        "schema": "query_workflow_request/v1",
        "query_type": "cross_party_match",
        "server_source": str((REPO_ROOT / "sse" / "examples" / "bridge_server_records.jsonl").resolve()),
        "client_source": str((REPO_ROOT / "sse" / "examples" / "bridge_client_records.jsonl").resolve()),
        "server_join_key_field": "email",
        "client_join_key_field": "email",
        "client_value_field": "amount",
        "server_normalizer": "email",
        "client_normalizer": "email",
        "client_value_mode": "raw-int",
        "token_scope": "defense-demo-scope",
        "token_secret_env": "BRIDGE_TOKEN_SECRET",
        "job_id": "defense_demo_job",
        "out_base": str((out_dir / "runs" / "adhoc_query_demo").resolve()),
        "caller": "auto_demo",
        "tenant_id": "demo_tenant",
        "dataset_id": "bridge_demo_dataset",
        "service_id": "bridge-demo-recovery",
        "k": 1,
        "n": 5,
        "sse_export_policy_config": str((REPO_ROOT / "sse" / "config" / "export_policy.example.json").resolve()),
        "deny_duplicate_query": True,
        "sse_export_handoff_mode": "fifo",
        "cleanup_sse_export_handoff_files_after_bridge": True,
    }
    write_json(out_dir / "config" / "query_request.json", request_payload)

    manifest = {
        "schema": "defense_demo_bundle/v1",
        "generated_from": str(REPO_ROOT),
        "demo_root": str(out_dir),
        "artifacts": {
            "main_completed_run": str((runs_dir / "main_completed_run").resolve()),
            "operator_fixture_run": str((runs_dir / "operator_fixture_run").resolve()),
            "platform_metadata_db": str((db_dir / "platform_metadata.db").resolve()),
            "business_access_db": str((db_dir / "business_access.sqlite").resolve()),
            "privacy_budget_metadata_db": str((db_dir / "privacy_budget.sqlite.metadata").resolve()),
            "privacy_budget_store": str((db_dir / "privacy_budget.sqlite").resolve()),
            "privacy_budget_approval_queue": str((db_dir / "approval_queue.jsonl").resolve()),
            "privacy_budget_approval_decisions": str((db_dir / "approval_decisions.jsonl").resolve()),
            "identity_token_config": str((out_dir / "config" / "identity_tokens.json").resolve()),
            "query_request": str((out_dir / "config" / "query_request.json").resolve()),
        },
    }
    write_json(out_dir / "defense_demo_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
