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
  scripts/benchmark_bridge.py \
  scripts/benchmark_dashboard_jobs.py \
  scripts/benchmark_pipeline.py \
  scripts/benchmark_pipeline_slo.py \
  scripts/benchmark_pjc.py \
  scripts/benchmark_smoke.py \
  scripts/benchmark_query_workflow.py \
  scripts/compare_read_adapter_backends.py \
  scripts/build_audit_chain.py \
  scripts/build_benchmark_contract_fixtures.py \
  scripts/check_benchmark_smoke_reports.py \
  scripts/check_mainline_contract.py \
  scripts/check_schema_backcompat.py \
  scripts/check_platform_health.py \
  scripts/check_dependency_hygiene.py \
  scripts/check_no_network_pickle.py \
  scripts/check_audit_api_public_redaction.py \
  scripts/check_record_recovery_boundary.py \
  scripts/external_kms_lib.py \
  scripts/external_kms_service.py \
  scripts/export_catalog_lineage.py \
  scripts/export_authz_tuples.py \
  scripts/export_observability_events.py \
  scripts/export_otel_events.py \
  scripts/export_record_recovery_service_metrics.py \
  scripts/verify_operator_shell_regression.py \
  scripts/import_run_metadata.py \
  scripts/init_metadata_db.py \
  scripts/key_agent_service.py \
  scripts/keyring_lib.py \
  scripts/manage_external_kms.py \
  scripts/manage_keyring.py \
  scripts/manage_metadata_db.py \
  scripts/materialize_control_plane_deepening.py \
  scripts/manage_service_tokens.py \
  scripts/manage_record_recovery_service.py \
  scripts/metadata_db.py \
  scripts/query_metadata.py \
  scripts/platform_api_client.py \
  scripts/publish_external_audit_anchor.py \
  scripts/request_external_kms.py \
  scripts/request_key_agent.py \
  scripts/request_record_recovery_service.py \
  scripts/resolve_key_access.py \
  scripts/scan_repo_hygiene.py \
  scripts/seal_audit_artifact.py \
  scripts/check_kms_reachability.py \
  scripts/check_openfga_authz.py \
  scripts/check_operator_request_submission_smoke.py \
  scripts/serve_operator_dashboard.py \
  scripts/serve_audit_query_api.py \
  scripts/serve_identity_proxy.py \
  scripts/serve_metadata_api.py \
  scripts/check_metadata_api_public_redaction.py \
  scripts/serve_platform_health_api.py \
  scripts/serve_query_workflow_api.py \
  scripts/sync_openfga_tuples.py \
  scripts/submit_query_workflow.py \
  scripts/validate_json_contract.py \
  scripts/validate_pipeline_policy.py \
  scripts/validate_tabular_contract.py \
  scripts/verify_audit_bundle.py \
  scripts/verify_audit_tamper_resistance.py \
  scripts/check_http_malformed_input_gate.py \
  scripts/benchmark_mtls_overhead.py \
  scripts/render_observability_topology.py \
  scripts/render_ecommerce_fact_layer.py \
  scripts/validate_ecommerce_fact_import.py \
  scripts/check_ecommerce_fact_import_validation.py \
  scripts/import_ecommerce_fact_rows.py \
  scripts/check_ecommerce_fact_import.py \
  scripts/check_console_token_storage.py \
  scripts/check_console_browser_session.py \
  scripts/check_console_security_headers.py \
  scripts/check_identity_proxy_auth_smoke.py \
  scripts/check_console_audit_public_summary.py \
  scripts/check_console_dashboard_public_summary.py \
  scripts/check_operator_dashboard_public_summary.py \
  scripts/render_operator_console_manifest.py \
  scripts/run_alert_check_daemon.py \
  scripts/run_chaos_test.py \
  scripts/test_metadata_db_failover.py \
  scripts/check_alert_webhook_smoke.py \
  scripts/check_bucket_dp_smoke.py \
  scripts/check_min_rows_side_channel_smoke.py \
  scripts/check_enrollment_only_mode_smoke.py \
  scripts/check_pjc_two_party_smoke.py \
  scripts/check_pjc_tls_diagnostic_smoke.py \
  scripts/check_release_policy_gate.py \
  scripts/check_release_policy_gate_smoke.py \
  scripts/check_business_access_policy.py \
  scripts/check_business_access_policy_smoke.py \
  scripts/check_business_access_api_smoke.py \
  scripts/check_spiffe_envoy_templates.py \
  scripts/check_bucketed_scale_test_async_smoke.py \
  scripts/check_metadata_api_rate_limit_smoke.py \
  scripts/write_pjc_audit.py \
  scripts/check_malformed_input_gate.py \
  scripts/check_pre_release_gate.py \
  scripts/check_privacy_budget.py \
  scripts/manage_privacy_budget_approval.py \
  scripts/check_privacy_budget_concurrency.py \
  scripts/check_privacy_budget_approval_flow.py \
  scripts/check_privacy_budget_approval_api_smoke.py \
  scripts/check_authority_governance.py \
  scripts/check_operator_readiness.py \
  scripts/api_identity.py \
  scripts/resolve_api_identity.py \
  scripts/map_oidc_claims.py \
  scripts/vault_http_client.py \
  scripts/issue_mtls_certs.py \
  scripts/cloud_kms_adapter.py \
  scripts/request_oidc_client_credentials.py \
  scripts/setup_openfga_model.py \
  scripts/openfga_http.py \
  scripts/rotate_issuer_credentials.py

SSE_PY="$REPO_ROOT/sse/.venv/bin/python"
if [[ ! -x "$SSE_PY" ]]; then
  SSE_PY="python3"
fi

cd "$REPO_ROOT/sse"
"$SSE_PY" -m py_compile \
  frontend/client/commands.py \
  frontend/client/services/service.py \
  frontend/common/wire.py \
  global_config.py \
  run_server.py \
  frontend/server/connector.py \
  frontend/server/services/comm.py \
  frontend/server/services/service.py \
  run_client.py \
  toolkit/encrypted_record_store.py \
  toolkit/logger/logger.py \
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
bash -n scripts/verify_fifo_handoff_replay.sh
bash -n scripts/verify_pjc_production_fail_closed.sh
bash -n scripts/verify_release_policy_gate_pipeline.sh

if command -v cargo >/dev/null 2>&1; then
  bash scripts/check_bridge_rust.sh
else
  echo "[WARN] skipping bridge Rust checks because cargo is not installed" >&2
fi

python3 scripts/scan_repo_hygiene.py --fail-on-warn
python3 scripts/check_dependency_hygiene.py --fail-on-warn
python3 scripts/check_no_network_pickle.py >/dev/null
python3 scripts/check_privacy_budget_concurrency.py >/dev/null
python3 scripts/check_privacy_budget_approval_flow.py >/dev/null
python3 scripts/check_privacy_budget_approval_api_smoke.py --out-dir tmp/privacy_budget_approval_api_smoke >/dev/null
python3 scripts/check_pjc_input_commitment.py >/dev/null
python3 scripts/check_malformed_input_gate.py --out /dev/null
python3 scripts/check_pre_release_gate.py --out /dev/null
python3 scripts/check_operator_readiness.py --out /dev/null
python3 scripts/check_business_access_policy_smoke.py >/dev/null
python3 scripts/check_business_access_api_smoke.py --out-dir tmp/business_access_api_smoke >/dev/null
python3 scripts/check_console_token_storage.py >/dev/null
python3 scripts/check_console_browser_session.py --out tmp/console_browser_session_check.json >/dev/null
python3 scripts/check_console_security_headers.py --out tmp/console_security_headers_check.json >/dev/null
python3 scripts/check_identity_proxy_auth_smoke.py --out tmp/identity_proxy_auth_smoke.json >/dev/null
python3 scripts/check_console_audit_public_summary.py >/dev/null
python3 scripts/check_console_dashboard_public_summary.py >/dev/null
python3 scripts/check_ecommerce_fact_import.py --out-dir tmp/ecommerce_fact_import_smoke >/dev/null
python3 scripts/check_operator_dashboard_public_summary.py --out-dir tmp/operator_dashboard_public_summary >/dev/null
bash scripts/verify_pjc_production_fail_closed.sh >/dev/null
bash scripts/verify_release_policy_gate_pipeline.sh >/dev/null
python3 scripts/check_record_recovery_boundary.py
python3 scripts/check_schema_backcompat.py
bash scripts/check_json_contracts.sh
bash scripts/verify_pipeline_replay.sh
bash scripts/verify_fifo_handoff_replay.sh

echo "[ok] CI smoke checks passed"
