#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

python3 -m py_compile \
  a-psi/moduleA_psi/scripts/policy_release.py \
  services/record_recovery/authz.py \
  services/record_recovery/bootstrap.py \
  services/record_recovery/client.py \
  services/record_recovery/common.py \
  services/record_recovery/config.py \
  services/record_recovery/encrypted_record_store.py \
  services/record_recovery/http_service.py \
  services/record_recovery/launcher.py \
  services/record_recovery/observability.py \
  services/record_recovery/runtime.py \
  services/record_recovery/service.py \
  services/record_recovery/worker.py \
  scripts/archive_audit_bundle.py \
  scripts/benchmark_smoke.py \
  scripts/benchmark_query_workflow.py \
  scripts/build_audit_chain.py \
  scripts/check_mainline_contract.py \
  scripts/check_schema_backcompat.py \
  scripts/check_platform_health.py \
  scripts/check_dependency_hygiene.py \
  scripts/check_record_recovery_boundary.py \
  scripts/external_kms_lib.py \
  scripts/external_kms_service.py \
  scripts/export_catalog_lineage.py \
  scripts/export_authz_tuples.py \
  scripts/export_observability_events.py \
  scripts/import_run_metadata.py \
  scripts/init_metadata_db.py \
  scripts/key_agent_service.py \
  scripts/keyring_lib.py \
  scripts/manage_external_kms.py \
  scripts/manage_keyring.py \
  scripts/manage_metadata_db.py \
  scripts/manage_record_recovery_service.py \
  scripts/metadata_db.py \
  scripts/query_metadata.py \
  scripts/platform_api_client.py \
  scripts/request_external_kms.py \
  scripts/request_key_agent.py \
  scripts/request_record_recovery_service.py \
  scripts/resolve_key_access.py \
  scripts/scan_repo_hygiene.py \
  scripts/seal_audit_artifact.py \
  scripts/serve_audit_query_api.py \
  scripts/serve_metadata_api.py \
  scripts/serve_platform_health_api.py \
  scripts/serve_query_workflow_api.py \
  scripts/submit_query_workflow.py \
  scripts/validate_json_contract.py \
  scripts/validate_pipeline_policy.py \
  scripts/validate_tabular_contract.py \
  scripts/verify_audit_bundle.py \
  scripts/write_pjc_audit.py

SSE_PY="$REPO_ROOT/sse/.venv/bin/python"
if [[ ! -x "$SSE_PY" ]]; then
  SSE_PY="python3"
fi

cd "$REPO_ROOT/sse"
"$SSE_PY" -m py_compile \
  frontend/client/commands.py \
  run_client.py \
  toolkit/encrypted_record_store.py \
  toolkit/record_recovery_authz.py \
  toolkit/record_recovery_client.py \
  toolkit/record_recovery_common.py \
  toolkit/record_recovery_http_service.py \
  toolkit/record_recovery_service.py \
  toolkit/record_recovery_service_config.py \
  toolkit/record_recovery_worker.py

cd "$REPO_ROOT"

bash -n scripts/check_ci_smoke.sh
bash -n scripts/check_bridge_rust.sh
bash -n scripts/check_json_contracts.sh
bash -n scripts/run_live_sse_bridge_demo.sh
bash -n scripts/run_sse_bridge_pipeline.sh
bash -n scripts/verify_pipeline_replay.sh

if command -v cargo >/dev/null 2>&1; then
  bash scripts/check_bridge_rust.sh
else
  echo "[WARN] skipping bridge Rust checks because cargo is not installed" >&2
fi

python3 scripts/scan_repo_hygiene.py --fail-on-warn
python3 scripts/check_dependency_hygiene.py --fail-on-warn
python3 scripts/check_record_recovery_boundary.py
python3 scripts/check_schema_backcompat.py
bash scripts/check_json_contracts.sh
bash scripts/verify_pipeline_replay.sh

echo "[ok] CI smoke checks passed"
