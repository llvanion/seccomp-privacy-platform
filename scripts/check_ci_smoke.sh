#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

SMOKE_TMP="$(mktemp -d "${TMPDIR:-/tmp}/seccomp_ci_smoke.XXXXXX")"

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
  services/record_recovery/production.py \
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
  scripts/check_legacy_sse_production_gate.py \
  scripts/check_audit_api_public_redaction.py \
  scripts/check_record_recovery_boundary.py \
  scripts/check_record_recovery_production_gate.py \
  scripts/check_recovery_service_deployment_evidence_gate.py \
  scripts/check_legacy_sse_query_surface_evidence_gate.py \
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
  scripts/archive_legacy_sse_live_evidence.py \
  scripts/archive_recovery_service_live_evidence.py \
  scripts/archive_query_workflow_live_evidence.py \
  scripts/archive_control_plane_live_evidence.py \
  scripts/query_metadata.py \
  scripts/query_workflow_execution_store.py \
  scripts/run_query_workflow_worker.py \
  scripts/cancel_query_workflow_execution.py \
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
  scripts/check_control_plane_deployment_evidence_gate.py \
  scripts/check_query_workflow_durability.py \
  scripts/check_query_workflow_deployment_evidence_gate.py \
  scripts/serve_operator_dashboard.py \
  scripts/serve_audit_query_api.py \
  scripts/serve_identity_proxy.py \
  scripts/serve_metadata_api.py \
  scripts/check_metadata_api_public_redaction.py \
  scripts/check_metadata_backup_restore_drill.py \
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
  scripts/check_ecommerce_fact_import_job_smoke.py \
  scripts/render_ecommerce_live_rollout_fixtures.py \
  scripts/check_business_access_support_relation_binding.py \
  scripts/check_final_live_blockers.py \
  scripts/collect_spiffe_envoy_live_rollout.py \
  scripts/collect_authority_live_rollout.py \
  scripts/collect_ecommerce_live_rollout.py \
  scripts/check_ecommerce_deployment_evidence_gate.py \
  scripts/check_console_token_storage.py \
  scripts/check_console_browser_session.py \
  scripts/check_console_deployment_evidence_gate.py \
  scripts/check_console_release_gate.py \
  scripts/check_console_security_headers.py \
  scripts/check_console_business_access_workbench.py \
  scripts/check_identity_proxy_auth_smoke.py \
  scripts/check_supply_chain_gate.py \
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
  scripts/check_pjc_tls_readiness.py \
  scripts/check_pjc_tls_readiness_smoke.py \
  scripts/archive_public_two_host_live_evidence.py \
  scripts/archive_pjc_resource_isolation_live_evidence.py \
  scripts/archive_ecommerce_live_evidence.py \
  scripts/archive_console_live_evidence.py \
  scripts/archive_pjc_protocol_live_evidence.py \
  scripts/check_release_policy_gate.py \
  scripts/check_release_policy_gate_smoke.py \
  scripts/source_attestation_lib.py \
  scripts/build_source_attestation.py \
  scripts/check_source_attestation.py \
  scripts/check_source_attestation_smoke.py \
  scripts/check_source_attestation_pipeline_smoke.py \
  scripts/build_release_governance_report.py \
  scripts/check_business_access_policy.py \
  scripts/check_business_access_policy_smoke.py \
  scripts/check_business_access_api_smoke.py \
  scripts/check_query_workflow_identity_scope_smoke.py \
  scripts/check_public_two_host_production_readiness_gate.py \
  scripts/materialize_public_two_host_live_run.py \
  scripts/check_pjc_binary_capability_gate.py \
  scripts/check_pjc_resource_isolation_evidence_gate.py \
  scripts/check_pjc_protocol_security_evidence_gate.py \
  scripts/check_spiffe_envoy_templates.py \
  scripts/check_bucketed_scale_test_async_smoke.py \
  scripts/check_metadata_api_rate_limit_smoke.py \
  scripts/write_pjc_audit.py \
  scripts/check_malformed_input_gate.py \
  scripts/check_pre_release_gate.py \
  scripts/check_production_security_closure_gate.py \
  scripts/check_privacy_budget.py \
  scripts/manage_privacy_budget_approval.py \
  scripts/check_privacy_budget_concurrency.py \
  scripts/check_privacy_budget_approval_flow.py \
  scripts/check_privacy_budget_approval_api_smoke.py \
  scripts/check_privacy_budget_deployment_evidence_gate.py \
  scripts/archive_privacy_budget_live_evidence.py \
  scripts/check_authority_governance.py \
  scripts/check_operator_readiness.py \
  scripts/api_identity.py \
  scripts/resolve_api_identity.py \
  scripts/check_identity_jwks_evidence_gate.py \
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
python3 scripts/check_legacy_sse_production_gate.py --out "$SMOKE_TMP/legacy_sse_production_gate.json" >/dev/null
python3 scripts/check_record_recovery_production_gate.py --out "$SMOKE_TMP/record_recovery_production_gate_check.json" >/dev/null
python3 scripts/check_privacy_budget_concurrency.py >/dev/null
python3 scripts/check_privacy_budget_approval_flow.py >/dev/null
python3 scripts/check_privacy_budget_approval_api_smoke.py --out-dir "$SMOKE_TMP/privacy_budget_approval_api_smoke" >/dev/null
python3 scripts/check_source_attestation_smoke.py >/dev/null
python3 scripts/check_source_attestation_pipeline_smoke.py >/dev/null
python3 scripts/archive_privacy_budget_live_evidence.py --job-id privacy-budget-contract --output-dir "$SMOKE_TMP/privacy_budget_live_archive" >/dev/null
python3 scripts/check_privacy_budget_deployment_evidence_gate.py --out-dir "$SMOKE_TMP/privacy_budget_deployment_evidence_gate" >/dev/null
python3 scripts/check_pjc_input_commitment.py >/dev/null
python3 scripts/archive_pjc_protocol_live_evidence.py --job-id pjc-protocol-contract --output-dir "$SMOKE_TMP/pjc_protocol_live_archive" >/dev/null
python3 scripts/check_pjc_protocol_security_evidence_gate.py --out-dir "$SMOKE_TMP/pjc_protocol_security_evidence_gate" --live-evidence-archive "$SMOKE_TMP/pjc_protocol_live_archive/pjc_protocol_live_evidence_archive.json" >/dev/null
python3 scripts/check_malformed_input_gate.py --out /dev/null
python3 scripts/check_pre_release_gate.py --out /dev/null
python3 scripts/check_operator_readiness.py --out /dev/null
python3 scripts/archive_control_plane_live_evidence.py --job-id control-plane-contract --output-dir "$SMOKE_TMP/control_plane_live_archive" >/dev/null
python3 scripts/check_control_plane_deployment_evidence_gate.py --out-dir "$SMOKE_TMP/control_plane_deployment_evidence_gate" --live-evidence-archive "$SMOKE_TMP/control_plane_live_archive/control_plane_live_evidence_archive.json" >/dev/null
python3 scripts/check_query_workflow_durability.py --out "$SMOKE_TMP/query_workflow_durability_check.json" >/dev/null
python3 scripts/archive_query_workflow_live_evidence.py --job-id query-workflow-contract --output-dir "$SMOKE_TMP/query_workflow_live_archive" >/dev/null
python3 scripts/check_query_workflow_deployment_evidence_gate.py --out-dir "$SMOKE_TMP/query_workflow_deployment_evidence_gate" --live-evidence-archive "$SMOKE_TMP/query_workflow_live_archive/query_workflow_live_evidence_archive.json" >/dev/null
python3 scripts/check_business_access_policy_smoke.py >/dev/null
python3 scripts/check_business_access_api_smoke.py --out-dir "$SMOKE_TMP/business_access_api_smoke" >/dev/null
python3 scripts/check_console_business_access_workbench.py >/dev/null
python3 scripts/check_console_token_storage.py >/dev/null
python3 scripts/check_console_browser_session.py --out "$SMOKE_TMP/console_browser_session_check.json" >/dev/null
python3 scripts/archive_console_live_evidence.py --job-id console-contract --output-dir "$SMOKE_TMP/console_live_archive" >/dev/null
python3 scripts/check_console_deployment_evidence_gate.py --out-dir "$SMOKE_TMP/console_deployment_evidence_gate" --live-evidence-archive "$SMOKE_TMP/console_live_archive/console_live_evidence_archive.json" >/dev/null
python3 scripts/check_console_release_gate.py --out "$SMOKE_TMP/console_release_gate_check.json" >/dev/null
python3 scripts/check_console_security_headers.py --out "$SMOKE_TMP/console_security_headers_check.json" >/dev/null
python3 scripts/check_identity_proxy_auth_smoke.py --out "$SMOKE_TMP/identity_proxy_auth_smoke.json" >/dev/null
python3 scripts/check_supply_chain_gate.py --out "$SMOKE_TMP/supply_chain_evidence.json" >/dev/null
python3 scripts/check_console_audit_public_summary.py >/dev/null
python3 scripts/check_console_dashboard_public_summary.py >/dev/null
python3 scripts/check_ecommerce_fact_import.py --out-dir "$SMOKE_TMP/ecommerce_fact_import_smoke" >/dev/null
python3 scripts/check_ecommerce_fact_import_job_smoke.py --out-dir "$SMOKE_TMP/ecommerce_fact_import_job" >/dev/null
python3 scripts/archive_ecommerce_live_evidence.py --job-id ecommerce-contract --output-dir "$SMOKE_TMP/ecommerce_live_archive" >/dev/null
python3 scripts/check_ecommerce_deployment_evidence_gate.py --out-dir "$SMOKE_TMP/ecommerce_deployment_evidence_gate" --live-evidence-archive "$SMOKE_TMP/ecommerce_live_archive/ecommerce_live_evidence_archive.json" >/dev/null
python3 scripts/check_production_security_closure_gate.py --out-dir "$SMOKE_TMP/production_security_closure_gate" --reports-root "$SMOKE_TMP" >/dev/null
python3 scripts/collect_ecommerce_live_rollout.py --output "$SMOKE_TMP/ecommerce_live_rollout_collection.json" >/dev/null
python3 scripts/check_identity_jwks_evidence_gate.py --out-dir "$SMOKE_TMP/identity_jwks_evidence_gate" >/dev/null
python3 scripts/check_live_identity_authority_evidence_gate.py --out-dir "$SMOKE_TMP/live_identity_authority_evidence_gate" >/dev/null
python3 scripts/check_pjc_binary_capability_gate.py --workspace a-psi/private-join-and-compute --requested-bin-dir a-psi/private-join-and-compute/bazel-bin --require-streaming --out "$SMOKE_TMP/pjc_binary_capability_gate.json" >/dev/null
python3 scripts/archive_pjc_resource_isolation_live_evidence.py --job-id pjc-resource-isolation-contract --output-dir "$SMOKE_TMP/pjc_resource_isolation_live_archive" >/dev/null
python3 scripts/check_pjc_resource_isolation_evidence_gate.py --out-dir "$SMOKE_TMP/pjc_resource_isolation_evidence_gate" >/dev/null
python3 scripts/check_public_two_host_production_readiness_gate.py --out-dir "$SMOKE_TMP/public_two_host_production_readiness_gate" >/dev/null
python3 scripts/check_spiffe_envoy_identity_gate.py --out-dir "$SMOKE_TMP/spiffe_envoy_identity_gate" >/dev/null
python3 scripts/archive_spiffe_envoy_live_evidence.py --job-id spiffe-envoy-contract --templates-dir deploy/spiffe_envoy --output-dir "$SMOKE_TMP/spiffe_envoy_live_archive" >/dev/null
python3 scripts/archive_external_anchor_live_evidence.py --job-id external-anchor-contract --output-dir "$SMOKE_TMP/external_anchor_live_archive" >/dev/null
python3 scripts/check_external_anchor_evidence_gate.py --out-dir "$SMOKE_TMP/external_anchor_evidence_gate" >/dev/null
python3 scripts/archive_postgres_ha_live_evidence.py --job-id postgres-ha-contract --output-dir "$SMOKE_TMP/postgres_ha_live_archive" >/dev/null
python3 scripts/check_postgres_ha_evidence_gate.py --out-dir "$SMOKE_TMP/postgres_ha_evidence_gate" --live-evidence-archive "$SMOKE_TMP/postgres_ha_live_archive/postgres_ha_live_evidence_archive.json" >/dev/null
python3 scripts/archive_supply_chain_live_evidence.py --job-id supply-chain-contract --output-dir "$SMOKE_TMP/supply_chain_live_archive" >/dev/null
python3 scripts/check_supply_chain_evidence_gate.py --out-dir "$SMOKE_TMP/supply_chain_evidence_gate" --live-evidence-archive "$SMOKE_TMP/supply_chain_live_archive/supply_chain_live_evidence_archive.json" >/dev/null
python3 scripts/archive_authority_live_evidence.py --job-id authority-contract --output-dir "$SMOKE_TMP/authority_live_archive" >/dev/null
python3 scripts/check_authority_evidence_gate.py --out-dir "$SMOKE_TMP/authority_evidence_gate" --live-evidence-archive "$SMOKE_TMP/authority_live_archive/authority_live_evidence_archive.json" >/dev/null
python3 scripts/archive_observability_live_evidence.py --job-id observability-contract --output-dir "$SMOKE_TMP/observability_live_archive" >/dev/null
python3 scripts/check_observability_evidence_gate.py --out-dir "$SMOKE_TMP/observability_evidence_gate" --live-evidence-archive "$SMOKE_TMP/observability_live_archive/observability_live_evidence_archive.json" >/dev/null
python3 scripts/archive_recovery_service_live_evidence.py --job-id recovery-service-contract --output-dir "$SMOKE_TMP/recovery_service_live_archive" >/dev/null
python3 scripts/check_recovery_service_deployment_evidence_gate.py --out-dir "$SMOKE_TMP/recovery_service_deployment_evidence_gate" >/dev/null
python3 scripts/archive_legacy_sse_live_evidence.py --job-id legacy-sse-contract --output-dir "$SMOKE_TMP/legacy_sse_live_archive" >/dev/null
python3 scripts/check_legacy_sse_query_surface_evidence_gate.py --out-dir "$SMOKE_TMP/legacy_sse_query_surface_evidence_gate" >/dev/null
python3 scripts/check_operator_dashboard_public_summary.py --out-dir "$SMOKE_TMP/operator_dashboard_public_summary" >/dev/null
bash scripts/verify_pjc_production_fail_closed.sh >/dev/null
bash scripts/verify_release_policy_gate_pipeline.sh >/dev/null
python3 scripts/check_record_recovery_boundary.py
python3 scripts/check_schema_backcompat.py
bash scripts/check_json_contracts.sh
bash scripts/verify_pipeline_replay.sh
bash scripts/verify_fifo_handoff_replay.sh

echo "[ok] CI smoke checks passed"
