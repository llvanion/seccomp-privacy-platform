#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

VALIDATOR="$REPO_ROOT/scripts/validate_json_contract.py"
TABULAR_VALIDATOR="$REPO_ROOT/scripts/validate_tabular_contract.py"
RUNTIME_SERVICE_HELPERS="$REPO_ROOT/scripts/runtime_service_helpers.py"
SSE_PY="$REPO_ROOT/sse/.venv/bin/python"
if [[ ! -x "$SSE_PY" ]]; then
  SSE_PY="python3"
fi

SCHEMAS=(
  "$REPO_ROOT/schemas/sse_export_policy.schema.json"
  "$REPO_ROOT/schemas/sse_bridge_export_audit.schema.json"
  "$REPO_ROOT/schemas/sse_record_recovery_service_audit.schema.json"
  "$REPO_ROOT/schemas/record_recovery_service_config.schema.json"
  "$REPO_ROOT/schemas/record_recovery_authz_source.schema.json"
  "$REPO_ROOT/schemas/record_recovery_service_policy.schema.json"
  "$REPO_ROOT/schemas/record_recovery_service_health.schema.json"
  "$REPO_ROOT/schemas/record_recovery_service_log.schema.json"
  "$REPO_ROOT/schemas/record_recovery_service_metrics.schema.json"
  "$REPO_ROOT/schemas/record_recovery_boundary_check.schema.json"
  "$REPO_ROOT/schemas/platform_health.schema.json"
  "$REPO_ROOT/schemas/sse_encrypted_record_store.schema.json"
  "$REPO_ROOT/schemas/bridge_job_meta.schema.json"
  "$REPO_ROOT/schemas/bridge_audit.schema.json"
  "$REPO_ROOT/schemas/pjc_audit.schema.json"
  "$REPO_ROOT/schemas/public_report.schema.json"
  "$REPO_ROOT/schemas/policy_audit.schema.json"
  "$REPO_ROOT/schemas/audit_chain.schema.json"
  "$REPO_ROOT/schemas/audit_archive_index.schema.json"
  "$REPO_ROOT/schemas/audit_archive_anchor.schema.json"
  "$REPO_ROOT/schemas/external_audit_anchor_report.schema.json"
  "$REPO_ROOT/schemas/audit_bundle_verification.schema.json"
  "$REPO_ROOT/schemas/key_manifest.schema.json"
  "$REPO_ROOT/schemas/keyring.schema.json"
  "$REPO_ROOT/schemas/vault_kv_backend.schema.json"
  "$REPO_ROOT/schemas/vault_http_client_config.schema.json"
  "$REPO_ROOT/schemas/external_kms_config.schema.json"
  "$REPO_ROOT/schemas/api_identity_token_map.schema.json"
  "$REPO_ROOT/schemas/api_identity_resolution.schema.json"
  "$REPO_ROOT/schemas/key_access_audit.schema.json"
  "$REPO_ROOT/schemas/key_lifecycle_audit.schema.json"
  "$REPO_ROOT/schemas/audit_seal.schema.json"
  "$REPO_ROOT/schemas/mainline_contract_check.schema.json"
  "$REPO_ROOT/schemas/pipeline_observability.schema.json"
  "$REPO_ROOT/schemas/catalog_lineage.schema.json"
  "$REPO_ROOT/schemas/schema_backcompat_check.schema.json"
  "$REPO_ROOT/schemas/query_workflow_benchmark.schema.json"
  "$REPO_ROOT/schemas/read_adapter_benchmark.schema.json"
  "$REPO_ROOT/schemas/record_recovery_benchmark.schema.json"
  "$REPO_ROOT/schemas/pipeline_benchmark.schema.json"
  "$REPO_ROOT/schemas/pjc_benchmark.schema.json"
  "$REPO_ROOT/schemas/live_sse_benchmark.schema.json"
  "$REPO_ROOT/schemas/audit_bundle_benchmark.schema.json"
  "$REPO_ROOT/schemas/platform_health_benchmark.schema.json"
  "$REPO_ROOT/schemas/derived_views_benchmark.schema.json"
  "$REPO_ROOT/schemas/metadata_api_health.schema.json"
  "$REPO_ROOT/schemas/metadata_api_response.schema.json"
  "$REPO_ROOT/schemas/metadata_api_error.schema.json"
  "$REPO_ROOT/schemas/metadata_schema_portability.schema.json"
  "$REPO_ROOT/schemas/postgres_ddl_export.schema.json"
  "$REPO_ROOT/schemas/metadata_import_report.schema.json"
  "$REPO_ROOT/schemas/metadata_db_status.schema.json"
  "$REPO_ROOT/schemas/metadata_db_backup.schema.json"
  "$REPO_ROOT/schemas/metadata_db_restore.schema.json"
  "$REPO_ROOT/schemas/metadata_batch_reconcile.schema.json"
  "$REPO_ROOT/schemas/mutation_log_query.schema.json"
  "$REPO_ROOT/schemas/oidc_claim_map.schema.json"
  "$REPO_ROOT/schemas/vault_http_client_result.schema.json"
  "$REPO_ROOT/schemas/issuer_credential_rotation.schema.json"
  "$REPO_ROOT/schemas/key_backend_drift.schema.json"
  "$REPO_ROOT/schemas/policy_drift.schema.json"
  "$REPO_ROOT/schemas/policy_change_proposal.schema.json"
  "$REPO_ROOT/schemas/metadata_db_export.schema.json"
  "$REPO_ROOT/schemas/metadata_registry_manifest.schema.json"
  "$REPO_ROOT/schemas/metadata_registry_apply_report.schema.json"
  "$REPO_ROOT/schemas/authz_tuple_export.schema.json"
  "$REPO_ROOT/schemas/audit_query_api_health.schema.json"
  "$REPO_ROOT/schemas/audit_query_api_response.schema.json"
  "$REPO_ROOT/schemas/audit_query_api_error.schema.json"
  "$REPO_ROOT/schemas/platform_health_api_health.schema.json"
  "$REPO_ROOT/schemas/platform_health_api_response.schema.json"
  "$REPO_ROOT/schemas/platform_health_api_error.schema.json"
  "$REPO_ROOT/schemas/query_workflow_request.schema.json"
  "$REPO_ROOT/schemas/query_workflow_submission.schema.json"
  "$REPO_ROOT/schemas/query_workflow_receipt.schema.json"
  "$REPO_ROOT/schemas/query_workflow_status.schema.json"
  "$REPO_ROOT/schemas/query_workflow_api_health.schema.json"
  "$REPO_ROOT/schemas/query_workflow_api_response.schema.json"
  "$REPO_ROOT/schemas/query_workflow_status_api_response.schema.json"
  "$REPO_ROOT/schemas/query_workflow_api_error.schema.json"
  "$REPO_ROOT/schemas/observability_dashboard.schema.json"
  "$REPO_ROOT/schemas/observability_alert_report.schema.json"
  "$REPO_ROOT/schemas/query_workflow_status_list.schema.json"
  "$REPO_ROOT/schemas/workflow_retry_eligibility.schema.json"
  "$REPO_ROOT/schemas/operator_triage_report.schema.json"
  "$REPO_ROOT/schemas/identity_proxy_health.schema.json"
  "$REPO_ROOT/schemas/openfga_sync_report.schema.json"
  "$REPO_ROOT/schemas/openfga_check_result.schema.json"
  "$REPO_ROOT/schemas/kms_reachability_report.schema.json"
  "$REPO_ROOT/schemas/service_token_report.schema.json"
  "$REPO_ROOT/schemas/authority_governance_report.schema.json"
  "$REPO_ROOT/schemas/control_plane_deepening_report.schema.json"
)

for schema in "${SCHEMAS[@]}"; do
  python3 -m json.tool "$schema" >/dev/null
done

python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/sse_export_policy.schema.json" \
  --json "$REPO_ROOT/sse/config/export_policy.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/sse_export_policy.schema.json" \
  --json "$REPO_ROOT/sse/config/ecommerce_access_policy.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/key_manifest.schema.json" \
  --json "$REPO_ROOT/config/key_manifest.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/keyring.schema.json" \
  --json "$REPO_ROOT/config/keyring.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/vault_kv_backend.schema.json" \
  --json "$REPO_ROOT/config/vault_kv_backend.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/vault_http_client_config.schema.json" \
  --json "$REPO_ROOT/config/vault_http_client.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/external_kms_config.schema.json" \
  --json "$REPO_ROOT/config/external_kms.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/api_identity_token_map.schema.json" \
  --json "$REPO_ROOT/config/api_identity_tokens.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_service_policy.schema.json" \
  --json "$REPO_ROOT/config/record_recovery_service_policy.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_service_config.schema.json" \
  --json "$REPO_ROOT/config/record_recovery_service.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_service_config.schema.json" \
  --json "$REPO_ROOT/config/record_recovery_http_service.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_service_config.schema.json" \
  --json "$REPO_ROOT/config/record_recovery_http_mtls_service.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_authz_source.schema.json" \
  --json "$REPO_ROOT/config/record_recovery_authz_sqlite.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_request.schema.json" \
  --json "$REPO_ROOT/docs/examples/query_request.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_registry_manifest.schema.json" \
  --json "$REPO_ROOT/config/metadata_registry.example.json"

tmp="$(mktemp -d /tmp/seccomp_contracts.XXXXXX)"
record_recovery_service_pid=""
cleanup() {
  if [[ -n "${record_recovery_service_pid:-}" ]] && kill -0 "$record_recovery_service_pid" 2>/dev/null; then
    kill "$record_recovery_service_pid" 2>/dev/null || true
    wait "$record_recovery_service_pid" 2>/dev/null || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT

python3 "$REPO_ROOT/scripts/export_authz_tuples.py" \
  --policy-config "$REPO_ROOT/sse/config/ecommerce_access_policy.example.json" \
  --output "$tmp/ecommerce_authz_tuples.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/authz_tuple_export.schema.json" \
  --json "$tmp/ecommerce_authz_tuples.json"
grep -n '"subject": "service_account:recovery_ops_demo"' "$tmp/ecommerce_authz_tuples.json" >/dev/null
grep -n '"access_profile": "recovery_service_operator"' "$tmp/ecommerce_authz_tuples.json" >/dev/null
grep -n '"subject_type": "service_account"' "$tmp/ecommerce_authz_tuples.json" >/dev/null
grep -n '"object": "privacy_service:orders-recovery"' "$tmp/ecommerce_authz_tuples.json" >/dev/null

python3 "$REPO_ROOT/scripts/check_schema_backcompat.py" \
  --output "$tmp/schema_backcompat_check.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/schema_backcompat_check.schema.json" \
  --json "$tmp/schema_backcompat_check.json"
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" render-systemd \
  --config "$REPO_ROOT/config/record_recovery_service.example.json" \
  --unit-name seccomp-record-recovery-unix \
  --service-user rrsvc \
  --service-group rrsvc \
  --environment-file /etc/seccomp/seccomp-record-recovery-unix.env \
  --output "$tmp/record_recovery_unix.service" \
  --env-output "$tmp/record_recovery_unix.env" \
  > "$tmp/record_recovery_unix_render.json"
python3 -m json.tool "$tmp/record_recovery_unix_render.json" >/dev/null
grep -n "^User=rrsvc$" "$tmp/record_recovery_unix.service" >/dev/null
grep -n "^Group=rrsvc$" "$tmp/record_recovery_unix.service" >/dev/null
grep -n "^EnvironmentFile=/etc/seccomp/seccomp-record-recovery-unix.env$" "$tmp/record_recovery_unix.service" >/dev/null
grep -n "run_record_recovery_service.py serve --transport unix_socket" "$tmp/record_recovery_unix.service" >/dev/null
grep -n "^SSE_RECORD_RECOVERY_TOKEN=CHANGE_ME$" "$tmp/record_recovery_unix.env" >/dev/null
grep -n "^ProtectSystem=strict$" "$tmp/record_recovery_unix.service" >/dev/null
grep -n "^ProtectHome=true$" "$tmp/record_recovery_unix.service" >/dev/null
grep -n "^PrivateDevices=true$" "$tmp/record_recovery_unix.service" >/dev/null
grep -n "^ProtectKernelTunables=true$" "$tmp/record_recovery_unix.service" >/dev/null
grep -n "^ProtectKernelModules=true$" "$tmp/record_recovery_unix.service" >/dev/null
grep -n "^ProtectControlGroups=true$" "$tmp/record_recovery_unix.service" >/dev/null
grep -n "^LockPersonality=true$" "$tmp/record_recovery_unix.service" >/dev/null
grep -n "^RestrictSUIDSGID=true$" "$tmp/record_recovery_unix.service" >/dev/null
grep -n "^SystemCallFilter=@system-service$" "$tmp/record_recovery_unix.service" >/dev/null
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" render-systemd \
  --config "$REPO_ROOT/config/record_recovery_http_service.example.json" \
  --unit-name seccomp-record-recovery-http \
  --service-user rrhttp \
  --service-group rrhttp \
  --environment-file /etc/seccomp/seccomp-record-recovery-http.env \
  --output "$tmp/record_recovery_http.service" \
  --env-output "$tmp/record_recovery_http.env" \
  > "$tmp/record_recovery_http_render.json"
python3 -m json.tool "$tmp/record_recovery_http_render.json" >/dev/null
grep -n "^After=network-online.target$" "$tmp/record_recovery_http.service" >/dev/null
grep -n "^EnvironmentFile=/etc/seccomp/seccomp-record-recovery-http.env$" "$tmp/record_recovery_http.service" >/dev/null
grep -n "run_record_recovery_service.py serve --transport http" "$tmp/record_recovery_http.service" >/dev/null
grep -n "^SSE_RECORD_RECOVERY_TOKEN=CHANGE_ME$" "$tmp/record_recovery_http.env" >/dev/null
grep -n "^ProtectSystem=strict$" "$tmp/record_recovery_http.service" >/dev/null
grep -n "^ProtectHome=true$" "$tmp/record_recovery_http.service" >/dev/null
grep -n "^PrivateDevices=true$" "$tmp/record_recovery_http.service" >/dev/null
grep -n "^ProtectKernelTunables=true$" "$tmp/record_recovery_http.service" >/dev/null
grep -n "^LockPersonality=true$" "$tmp/record_recovery_http.service" >/dev/null
grep -n "^RestrictSUIDSGID=true$" "$tmp/record_recovery_http.service" >/dev/null
grep -n "^SystemCallFilter=@system-service$" "$tmp/record_recovery_http.service" >/dev/null
python3 "$REPO_ROOT/scripts/benchmark_query_workflow.py" \
  --request-file "$REPO_ROOT/docs/examples/query_request.json" \
  --iterations 1 \
  --output "$tmp/query_workflow_benchmark.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_benchmark.schema.json" \
  --json "$tmp/query_workflow_benchmark.json"
python3 "$REPO_ROOT/scripts/benchmark_read_adapters.py" \
  --iterations 1 \
  --output "$tmp/read_adapter_benchmark.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/read_adapter_benchmark.schema.json" \
  --json "$tmp/read_adapter_benchmark.json"
python3 "$REPO_ROOT/scripts/benchmark_record_recovery.py" \
  --iterations 1 \
  --output "$tmp/record_recovery_benchmark.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_benchmark.schema.json" \
  --json "$tmp/record_recovery_benchmark.json"
python3 "$REPO_ROOT/scripts/benchmark_audit_bundle.py" \
  --iterations 1 \
  --output "$tmp/audit_bundle_benchmark.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_bundle_benchmark.schema.json" \
  --json "$tmp/audit_bundle_benchmark.json"
python3 "$REPO_ROOT/scripts/benchmark_platform_health.py" \
  --iterations 1 \
  --output "$tmp/platform_health_benchmark.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/platform_health_benchmark.schema.json" \
  --json "$tmp/platform_health_benchmark.json"
python3 "$REPO_ROOT/scripts/benchmark_derived_views.py" \
  --iterations 1 \
  --output "$tmp/derived_views_benchmark.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/derived_views_benchmark.schema.json" \
  --json "$tmp/derived_views_benchmark.json"
python3 "$REPO_ROOT/scripts/build_benchmark_contract_fixtures.py" \
  --pipeline-out "$tmp/pipeline_benchmark_contract_fixture.json" \
  --live-out "$tmp/live_sse_benchmark_contract_fixture.json" \
  --pjc-out "$tmp/pjc_benchmark_contract_fixture.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/pipeline_benchmark.schema.json" \
  --json "$tmp/pipeline_benchmark_contract_fixture.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/live_sse_benchmark.schema.json" \
  --json "$tmp/live_sse_benchmark_contract_fixture.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/pjc_benchmark.schema.json" \
  --json "$tmp/pjc_benchmark_contract_fixture.json"
python3 "$REPO_ROOT/scripts/check_benchmark_smoke_reports.py" \
  --query-workflow "$tmp/query_workflow_benchmark.json" \
  --read-adapter "$tmp/read_adapter_benchmark.json" \
  --record-recovery "$tmp/record_recovery_benchmark.json" \
  --pipeline "$tmp/pipeline_benchmark_contract_fixture.json" \
  --live-sse "$tmp/live_sse_benchmark_contract_fixture.json" \
  --audit-bundle "$tmp/audit_bundle_benchmark.json" \
  --platform-health "$tmp/platform_health_benchmark.json" \
  --derived-views "$tmp/derived_views_benchmark.json"

expect_failure() {
  if "$@" >/dev/null 2>&1; then
    echo "[ERROR] expected command to fail: $*" >&2
    exit 1
  fi
}

python3 "$TABULAR_VALIDATOR" \
  --contract bridge-input-csv \
  --path "$REPO_ROOT/bridge/examples/server_export.csv" \
  --role server \
  --join-key-field email
python3 "$TABULAR_VALIDATOR" \
  --contract bridge-input-csv \
  --path "$REPO_ROOT/bridge/examples/client_export.csv" \
  --role client \
  --join-key-field email \
  --value-field amount
python3 "$TABULAR_VALIDATOR" \
  --contract bridge-input-jsonl \
  --path "$REPO_ROOT/sse/examples/bridge_server_records.jsonl" \
  --role server \
  --join-key-field email
python3 "$TABULAR_VALIDATOR" \
  --contract bridge-input-jsonl \
  --path "$REPO_ROOT/sse/examples/bridge_client_records.jsonl" \
  --role client \
  --join-key-field email \
  --value-field amount

python3 "$REPO_ROOT/scripts/check_record_recovery_boundary.py" \
  --output "$tmp/record_recovery_boundary_check.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_boundary_check.schema.json" \
  --json "$tmp/record_recovery_boundary_check.json"

printf '%s\n' \
  'email,amount' \
  ',125' \
  > "$tmp/bad_bridge_input.csv"
expect_failure python3 "$TABULAR_VALIDATOR" \
  --contract bridge-input-csv \
  --path "$tmp/bad_bridge_input.csv" \
  --role client \
  --join-key-field email \
  --value-field amount

printf '%s\n' \
  '{"email":"alice@example.com","amount":"not-an-int"}' \
  > "$tmp/bad_bridge_input.jsonl"
expect_failure python3 "$TABULAR_VALIDATOR" \
  --contract bridge-input-jsonl \
  --path "$tmp/bad_bridge_input.jsonl" \
  --role client \
  --join-key-field email \
  --value-field amount

mkdir -p "$tmp/sse_exports" "$tmp/bridge_job" "$tmp/a_psi_run"

export BRIDGE_TOKEN_SECRET="contract-check-secret"
cat > "$tmp/vault_kv_backend.json" <<EOF
{
  "schema": "vault_kv_backend/v1",
  "secrets": {
    "secret/data/bridge-token": {
      "current_version": "2",
      "versions": {
        "1": {
          "fields": {
            "value": "vault-bridge-secret-v1"
          }
        },
        "2": {
          "fields": {
            "value": "vault-bridge-secret-v2"
          }
        }
      }
    },
    "secret/data/audit-integrity": {
      "current_version": "1",
      "versions": {
        "1": {
          "fields": {
            "seal_secret": "vault-audit-secret-v1"
          }
        }
      }
    }
  }
}
EOF
python3 "$REPO_ROOT/scripts/resolve_key_access.py" \
  --manifest "$REPO_ROOT/config/key_manifest.example.json" \
  --key-id bridge-token-demo-v1 \
  --purpose bridge_token \
  --caller auto_demo \
  --job-id contract-check \
  --audit-log "$tmp/key_access_audit.jsonl" >/dev/null
cp "$REPO_ROOT/config/keyring.example.json" "$tmp/keyring.json"
python3 "$REPO_ROOT/scripts/manage_keyring.py" rotate \
  --keyring "$tmp/keyring.json" \
  --key-name bridge-token \
  --purpose bridge_token \
  --new-version demo-v2 \
  --secret-env BRIDGE_TOKEN_SECRET \
  --caller auto_demo \
  --activate \
  --audit-log "$tmp/key_lifecycle_audit.jsonl" >/dev/null
python3 "$REPO_ROOT/scripts/manage_keyring.py" set-status \
  --keyring "$tmp/keyring.json" \
  --key-name bridge-token \
  --version demo-v1 \
  --status retired \
  --caller auto_demo \
  --audit-log "$tmp/key_lifecycle_audit.jsonl" >/dev/null
cp "$REPO_ROOT/config/keyring.example.json" "$tmp/keyring_vault.json"
python3 -c 'import json, sys; path=sys.argv[1]; payload=json.load(open(path, "r", encoding="utf-8")); payload["keys"]["bridge-token"]["versions"]["demo-v1"]["secret_ref"]={"kind":"vault_kv","name":"secret/data/bridge-token","version":"1","field":"value"}; json.dump(payload, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2); open(path, "a", encoding="utf-8").write("\n")' "$tmp/keyring_vault.json"
export SECCOMP_KEY_AGENT_TOKEN="contract-key-agent-token"
python3 "$REPO_ROOT/scripts/key_agent_service.py" \
  --socket-path "$tmp/key_agent_vault.sock" \
  --keyring "$tmp/keyring_vault.json" \
  --auth-token-env SECCOMP_KEY_AGENT_TOKEN \
  --vault-kv-file "$tmp/vault_kv_backend.json" \
  --audit-log "$tmp/key_agent_vault_access_audit.jsonl" \
  --pid-file "$tmp/key_agent_vault.pid" \
  --ready-file "$tmp/key_agent_vault.ready" \
  >"$tmp/key_agent_vault.log" 2>&1 &
key_agent_vault_pid=$!
if [[ -z "${key_agent_vault_pid:-}" ]]; then
  echo "[ERROR] failed to start vault-backed key agent" >&2
  exit 1
fi
while [[ ! -s "$tmp/key_agent_vault.ready" ]]; do sleep 0.1; done
python3 "$REPO_ROOT/scripts/request_key_agent.py" \
  --socket-path "$tmp/key_agent_vault.sock" \
  --key-name bridge-token \
  --purpose bridge_token \
  --caller auto_demo \
  --job-id contract-check \
  --auth-token-env SECCOMP_KEY_AGENT_TOKEN \
  > "$tmp/key_agent_vault_result.json"
kill "$key_agent_vault_pid" 2>/dev/null || true
wait "$key_agent_vault_pid" 2>/dev/null || true

external_kms_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
python3 "$REPO_ROOT/scripts/build_runtime_contract_smoke_configs.py" \
  external-kms \
  --out-config "$tmp/external_kms.json" \
  --state-path "$tmp/keyring_external.json" \
  --vault-kv-file "$tmp/vault_kv_backend.json" \
  --port "$external_kms_port"
cp "$REPO_ROOT/config/keyring.example.json" "$tmp/keyring_external.json"
export SECCOMP_EXTERNAL_KMS_TOKEN="contract-external-kms-token"
export SECCOMP_EXTERNAL_KMS_ADMIN_TOKEN="contract-external-kms-admin-token"
python3 "$REPO_ROOT/scripts/external_kms_service.py" \
  --bind-host 127.0.0.1 \
  --port "$external_kms_port" \
  --state-file "$tmp/keyring_external.json" \
  --auth-token-env SECCOMP_EXTERNAL_KMS_TOKEN \
  --admin-auth-token-env SECCOMP_EXTERNAL_KMS_ADMIN_TOKEN \
  --vault-kv-file "$tmp/vault_kv_backend.json" \
  --lifecycle-audit-log "$tmp/external_kms_lifecycle_audit.jsonl" \
  --pid-file "$tmp/external_kms.pid" \
  --ready-file "$tmp/external_kms.ready" \
  >"$tmp/external_kms.log" 2>&1 &
external_kms_pid=$!
cleanup() {
  if [[ -n "${key_agent_vault_pid:-}" ]] && kill -0 "$key_agent_vault_pid" 2>/dev/null; then
    kill "$key_agent_vault_pid" 2>/dev/null || true
    wait "$key_agent_vault_pid" 2>/dev/null || true
  fi
  if [[ -n "${external_kms_pid:-}" ]] && kill -0 "$external_kms_pid" 2>/dev/null; then
    kill "$external_kms_pid" 2>/dev/null || true
    wait "$external_kms_pid" 2>/dev/null || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT
python3 "$RUNTIME_SERVICE_HELPERS" wait-json-health \
  --url "http://127.0.0.1:$external_kms_port/healthz"
python3 "$REPO_ROOT/scripts/request_external_kms.py" \
  --config "$tmp/external_kms.json" \
  --key-name bridge-token \
  --purpose bridge_token \
  --caller auto_demo \
  --job-id contract-check \
  --audit-log "$tmp/external_key_access_audit.jsonl" \
  > "$tmp/external_kms_env_result.json"
python3 "$REPO_ROOT/scripts/manage_external_kms.py" rotate \
  --config "$tmp/external_kms.json" \
  --key-name bridge-token \
  --purpose bridge_token \
  --new-version ext-v2 \
  --secret-ref-kind vault_kv \
  --secret-ref-name secret/data/bridge-token \
  --secret-ref-version 2 \
  --secret-ref-field value \
  --caller auto_demo \
  --activate >/dev/null
python3 "$REPO_ROOT/scripts/request_external_kms.py" \
  --config "$tmp/external_kms.json" \
  --key-name bridge-token \
  --purpose bridge_token \
  --caller auto_demo \
  --job-id contract-check \
  --audit-log "$tmp/external_key_access_vault_audit.jsonl" \
  > "$tmp/external_kms_vault_result.json"
python3 "$REPO_ROOT/scripts/manage_external_kms.py" set-status \
  --config "$tmp/external_kms.json" \
  --key-name bridge-token \
  --version demo-v1 \
  --status retired \
  --caller auto_demo >/dev/null

cat > "$tmp/contract_export_policy.json" <<EOF
{
  "schema": "sse_export_policy/v1",
  "callers": {
    "auto_demo": {
      "enabled": true,
      "tenant_id": "contract-tenant",
      "allowed_dataset_ids": ["contract-dataset"],
      "allowed_service_ids": ["contract-recovery-service"],
      "platform_roles": ["query_submitter", "privacy_operator"],
      "access_profile": "commerce_ops_owner",
      "allowed_roles": ["server", "client"],
      "allowed_fields": ["email", "amount"],
      "allowed_join_key_fields": ["email"],
      "allowed_value_fields": ["amount"],
      "allowed_filter_fields": ["campaign"],
      "required_filters": ["campaign"],
      "allowed_filter_values": {
        "campaign": ["demo"]
      },
      "max_export_rows": 100000,
      "min_export_rows": 1,
      "can_use_record_recovery_service": true,
      "can_run_bridge": true,
      "can_run_pjc": true,
      "can_release": true
    },
    "marketing_analyst_demo": {
      "enabled": true,
      "tenant_id": "contract-tenant",
      "allowed_dataset_ids": ["contract-dataset"],
      "allowed_service_ids": ["contract-recovery-service"],
      "platform_roles": ["query_submitter"],
      "access_profile": "campaign_analyst",
      "allowed_roles": ["client"],
      "allowed_fields": ["email", "amount"],
      "allowed_join_key_fields": ["email"],
      "allowed_value_fields": ["amount"],
      "allowed_filter_fields": ["campaign"],
      "required_filters": ["campaign"],
      "allowed_filter_values": {
        "campaign": ["demo"]
      },
      "max_export_rows": 25000,
      "min_export_rows": 1,
      "can_use_record_recovery_service": true,
      "can_run_bridge": true,
      "can_run_pjc": true,
      "can_release": false
    },
    "audit_reviewer_demo": {
      "enabled": false,
      "tenant_id": "contract-tenant",
      "allowed_dataset_ids": ["contract-dataset"],
      "allowed_service_ids": [],
      "platform_roles": ["platform_auditor"],
      "access_profile": "compliance_auditor",
      "allowed_roles": [],
      "allowed_fields": [],
      "allowed_join_key_fields": [],
      "allowed_value_fields": [],
      "allowed_filter_fields": [],
      "required_filters": [],
      "allowed_filter_values": {},
      "max_export_rows": 1,
      "min_export_rows": 0,
      "can_use_record_recovery_service": false,
      "can_run_bridge": false,
      "can_run_pjc": false,
      "can_release": false
    }
  }
}
EOF
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/sse_export_policy.schema.json" \
  --json "$tmp/contract_export_policy.json"
python3 "$REPO_ROOT/scripts/export_authz_tuples.py" \
  --policy-config "$tmp/contract_export_policy.json" \
  --output "$tmp/contract_authz_tuples_policy.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/authz_tuple_export.schema.json" \
  --json "$tmp/contract_authz_tuples_policy.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); summary=payload["summary"]; assert summary["subject_count"] == 3, summary; assert summary["active_subject_count"] == 2, summary; assert summary["disabled_subject_count"] == 1, summary; assert any(item["object"] == "platform_capability:can_release" and item["user"] == "user:auto_demo" for item in payload["tuples"]), payload["tuples"]; assert any(item["relation"] == "reader" and item["object"] == "dataset:contract-dataset" for item in payload["tuples"]), payload["tuples"]' "$tmp/contract_authz_tuples_policy.json"

printf '%s\n' \
  "{\"schema\":\"sse_bridge_export_audit/v1\",\"ts_utc\":\"2026-04-10T00:00:00Z\",\"event\":\"sse_bridge_export\",\"tenant_id\":\"contract-tenant\",\"dataset_id\":\"contract-dataset\",\"service_id\":\"contract-recovery-service\",\"caller\":\"auto_demo\",\"correlation_id\":\"contract-check\",\"job_id\":\"contract-check\",\"role\":\"server\",\"source_file\":null,\"source_sha256\":null,\"output_file\":\"$tmp/sse_exports/server.fifo\",\"output_file_type\":\"fifo\",\"output_sha256\":\"abc\",\"source_format\":\"jsonl\",\"out_format\":\"csv\",\"join_key_field\":\"email\",\"value_field\":null,\"filters\":[],\"input_rows\":1,\"output_rows\":1,\"policy_config\":\"$tmp/contract_export_policy.json\",\"candidate_source\":\"local_filter\",\"record_id_field\":null,\"candidate_count\":null,\"record_store_file\":null,\"record_store_sha256\":null,\"duration_ms\":12,\"decision\":\"allow\",\"reason_code\":\"ok\",\"reason\":\"ok\"}" \
  > "$tmp/sse_exports/export_audit.jsonl"
printf '%s\n' \
  "{\"schema\":\"sse_bridge_export_audit/v1\",\"ts_utc\":\"2026-04-10T00:00:01Z\",\"event\":\"sse_bridge_export\",\"tenant_id\":\"contract-tenant\",\"dataset_id\":\"contract-dataset\",\"service_id\":\"contract-recovery-service\",\"caller\":\"auto_demo\",\"correlation_id\":\"contract-check\",\"job_id\":\"contract-check\",\"role\":\"client\",\"source_file\":null,\"source_sha256\":null,\"output_file\":\"$tmp/sse_exports/client.csv\",\"output_file_type\":\"file\",\"output_sha256\":\"def\",\"source_format\":\"jsonl\",\"out_format\":\"csv\",\"join_key_field\":\"email\",\"value_field\":\"amount\",\"filters\":[{\"field\":\"campaign\",\"value_sha256\":\"123\"}],\"input_rows\":1,\"output_rows\":1,\"policy_config\":\"$tmp/contract_export_policy.json\",\"candidate_source\":\"sse_query\",\"record_id_field\":\"email_hex\",\"candidate_count\":1,\"record_store_file\":\"/tmp/client_store.enc.jsonl\",\"record_store_sha256\":\"abc\",\"record_recovery_boundary\":\"service_socket\",\"duration_ms\":34,\"decision\":\"allow\",\"reason_code\":\"ok\",\"reason\":\"ok\"}" \
  >> "$tmp/sse_exports/export_audit.jsonl"

printf '%s\n' \
  '{"schema":"bridge_audit/v1","ts_unix_ms":1,"event":"bridge_prepare_job","job_id":"contract-check","correlation_id":"contract-check","server_input_file_type":"fifo","server_input_sha256":null,"client_input_file_type":"file","client_input_sha256":"def","duration_ms":56,"decision":"allow","reason_code":"ok","token_secret_source":{"kind":"cli"}}' \
  > "$tmp/bridge_job/bridge_audit.jsonl"

printf '%s\n' \
  '{"schema":"pjc_audit/v1","ts_utc":"2026-04-10T00:00:02Z","event":"pjc_run","job_id":"contract-check","correlation_id":"contract-check","out_dir":"/tmp/a_psi_run","server_csv":"/tmp/server.csv","server_csv_sha256":"abc","client_csv":"/tmp/client.csv","client_csv_sha256":"def","server_log":"/tmp/server.log","server_log_sha256":"123","client_log":"/tmp/client.log","client_log_sha256":"456","result_file":"/tmp/result.json","result_sha256":"789","duration_ms":78,"decision":"allow","reason_code":"ok","reason":"ok","exit_code":0}' \
  > "$tmp/a_psi_run/pjc_audit.jsonl"

printf '%s\n' \
  "{\"schema\":\"sse_record_recovery_service_audit/v1\",\"ts_utc\":\"2026-04-10T00:00:00Z\",\"event\":\"record_recovery_service_request\",\"service_id\":\"contract-recovery-service\",\"tenant_id\":\"contract-tenant\",\"dataset_id\":\"contract-dataset\",\"caller\":\"auto_demo\",\"correlation_id\":\"contract-check\",\"job_id\":\"contract-check\",\"role\":\"client\",\"auth_mode\":\"env_token\",\"transport\":\"unix_socket\",\"socket_path\":\"/tmp/record_recovery.sock\",\"endpoint_url\":null,\"authz_policy_config\":\"$tmp/contract_export_policy.json\",\"record_store_file\":\"/tmp/client_store.enc.jsonl\",\"record_store_sha256\":\"abc\",\"output_file\":\"$tmp/sse_exports/client.csv\",\"output_file_type\":\"file\",\"output_sha256\":\"def\",\"join_key_field\":\"email\",\"value_field\":\"amount\",\"candidate_count\":1,\"filters\":[{\"field\":\"campaign\",\"value_sha256\":\"123\"}],\"input_rows\":1,\"output_rows\":1,\"duration_ms\":23,\"decision\":\"allow\",\"reason_code\":\"ok\",\"reason\":\"ok\"}" \
  > "$tmp/sse_exports/record_recovery_service_audit.jsonl"

printf '%s\n' \
  '{"schema":"bridge_job_meta/v1","job_id":"contract-check","job_type":"bridge_prepared_csv","generator":"bridge-rust-v0","input_sizes":{"exposure_n":1,"purchase_n":1},"bridge":{"token_scheme":"bridge-hmac-sha256-v1","token_scope":"contract-check","token_key_version":"1","normalize_version":"1","normalizer_schema_version":"normalizer-schema/v1","dedup_policy":"one","server":{"join_key_column":"email","normalizer":"email"},"client":{"join_key_column":"email","normalizer":"email"}},"inputs":{},"counts":{}}' \
  > "$tmp/bridge_job/job_meta.json"

printf '%s\n' \
  '{"job_id":"contract-check","correlation_id":"contract-check","intersection_size":1,"intersection_sum":5}' \
  > "$tmp/a_psi_run/attribution_result.json"

printf '%s\n' \
  '{"schema":"public_report/v2","generated_at_utc":"2026-04-10T00:00:00Z","policy_version":"w2-hmac-v1","job_id":"contract-check","correlation_id":"contract-check","caller":"auto_demo","released":false,"reason":"below k","reason_code":"below_k","window":{"start":null,"end":null},"k_threshold":20}' \
  > "$tmp/a_psi_run/public_report.json"

printf '%s\n' \
  '{"ts_utc":"2026-04-10T00:00:00Z","event":"policy_release","policy_version":"w2-hmac-v1","job_id":"contract-check","correlation_id":"contract-check","caller":"auto_demo","window":{"start":null,"end":null},"bucket":null,"value_mode":null,"bridge":null,"input_sizes":{},"input_file":"/tmp/in","input_sha256":"abc","pjc_result_file":"/tmp/in","pjc_result_sha256":"abc","release_file":"/tmp/out","release_sha256":"def","threshold_k":20,"round_sum_to":null,"rate_limit_used":0,"rate_limit_max":5,"canonical_query_signature":"sig","parsed_metrics":{},"duration_ms":11,"decision":"deny","reason":"below k","reason_code":"below_k","released":null,"auth":{"mode":"disabled_or_caller_only","key_id":null,"timestamp":null,"nonce":null,"auth_ok":true,"auth_reason_code":"auth_disabled"}}' \
  > "$tmp/a_psi_run/audit_log.jsonl"

printf '%s\n' \
  '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef' \
  > "$tmp/bridge_job/server.csv"
printf '%s\n' \
  '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef,5' \
  > "$tmp/bridge_job/client.csv"

python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/sse_bridge_export_audit.schema.json" --jsonl "$tmp/sse_exports/export_audit.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/sse_record_recovery_service_audit.schema.json" --jsonl "$tmp/sse_exports/record_recovery_service_audit.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/bridge_job_meta.schema.json" --json "$tmp/bridge_job/job_meta.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/bridge_audit.schema.json" --jsonl "$tmp/bridge_job/bridge_audit.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/pjc_audit.schema.json" --jsonl "$tmp/a_psi_run/pjc_audit.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/public_report.schema.json" --json "$tmp/a_psi_run/public_report.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/policy_audit.schema.json" --jsonl "$tmp/a_psi_run/audit_log.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/key_access_audit.schema.json" --jsonl "$tmp/key_access_audit.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/key_access_audit.schema.json" --jsonl "$tmp/external_key_access_audit.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/key_access_audit.schema.json" --jsonl "$tmp/external_key_access_jwks_audit.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/key_access_audit.schema.json" --jsonl "$tmp/key_agent_vault_access_audit.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/key_access_audit.schema.json" --jsonl "$tmp/key_agent_jwks_access_audit.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/key_access_audit.schema.json" --jsonl "$tmp/external_key_access_vault_audit.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/keyring.schema.json" --json "$tmp/keyring.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/keyring.schema.json" --json "$tmp/keyring_vault.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/key_lifecycle_audit.schema.json" --jsonl "$tmp/key_lifecycle_audit.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/vault_kv_backend.schema.json" --json "$tmp/vault_kv_backend.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/keyring.schema.json" --json "$tmp/keyring_external.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/key_lifecycle_audit.schema.json" --jsonl "$tmp/external_kms_lifecycle_audit.jsonl"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["schema"] == "key_agent_result/v1", payload; assert payload["secret"] == "vault-bridge-secret-v1", payload; assert payload["key_version"] == "demo-v1", payload' "$tmp/key_agent_vault_result.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["schema"] == "key_agent_result/v1", payload; assert payload["secret"] == "contract-jwks-bridge-secret", payload; assert payload["key_version"] == "demo-v1", payload' "$tmp/key_agent_jwks_result.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["schema"] == "external_kms_result/v1", payload; assert payload["secret"] == "contract-check-secret", payload; assert payload["key_version"] == "demo-v1", payload' "$tmp/external_kms_env_result.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["schema"] == "external_kms_result/v1", payload; assert payload["secret"] == "contract-jwks-bridge-secret", payload; assert payload["key_version"] == "demo-v1", payload' "$tmp/external_kms_jwks_result.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["schema"] == "external_kms_result/v1", payload; assert payload["secret"] == "vault-bridge-secret-v2", payload; assert payload["key_version"] == "ext-v2", payload' "$tmp/external_kms_vault_result.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); entry=payload["keys"]["bridge-token"]["versions"]["ext-v2"]["secret_ref"]; assert entry["kind"] == "vault_kv", entry; assert entry["name"] == "secret/data/bridge-token", entry; assert entry["version"] == "2", entry; assert entry["field"] == "value", entry; assert payload["keys"]["bridge-token"]["active_version"] == "ext-v2", payload["keys"]["bridge-token"]' "$tmp/keyring_external.json"
python3 "$TABULAR_VALIDATOR" --contract pjc-server-csv --path "$tmp/bridge_job/server.csv"
python3 "$TABULAR_VALIDATOR" --contract pjc-client-csv --path "$tmp/bridge_job/client.csv"

export SSE_RECORD_RECOVERY_TOKEN="contract-record-recovery-token"
python3 "$REPO_ROOT/scripts/build_runtime_contract_smoke_configs.py" \
  record-recovery-unix \
  --out-config "$tmp/record_recovery_service_config.json" \
  --tmp-dir "$tmp"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/record_recovery_service_config.schema.json" --json "$tmp/record_recovery_service_config.json"
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" start \
  --config "$tmp/record_recovery_service_config.json" \
  > "$tmp/record_recovery_service_start.json"
record_recovery_service_pid="$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field --json-file "$tmp/record_recovery_service_start.json" --field started_pid)"
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" status \
  --config "$tmp/record_recovery_service_config.json" \
  > "$tmp/record_recovery_service_status.json"
expect_failure python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" status \
  --config "$tmp/record_recovery_service_config.json" \
  --service-id wrong-service
python3 "$REPO_ROOT/scripts/request_record_recovery_service.py" \
  --config "$tmp/record_recovery_service_config.json" \
  > "$tmp/record_recovery_service_health.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/record_recovery_service_health.schema.json" --json "$tmp/record_recovery_service_health.json"
cp "$tmp/record_recovery_service_config.json" "$tmp/sse_exports/record_recovery_service_config.json"
cp "$tmp/record_recovery_service_health.json" "$tmp/sse_exports/record_recovery_service_health.json"
expect_failure "$SSE_PY" "$REPO_ROOT/sse/run_client.py" export-bridge-records \
  --source-path "$REPO_ROOT/sse/examples/bridge_server_records.jsonl" \
  --out-path "$tmp/conflicting_scope_export.csv" \
  --role server \
  --source-format jsonl \
  --out-format csv \
  --join-key-field email \
  --unsafe-allow-no-policy \
  --record-recovery-service-config "$tmp/record_recovery_service_config.json" \
  --tenant-id wrong-tenant
"$SSE_PY" "$REPO_ROOT/scripts/record_recovery_contract_smoke_helpers.py" \
  validate-unix-status \
  --status-json "$tmp/record_recovery_service_status.json"
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" stop \
  --config "$tmp/record_recovery_service_config.json" \
  > "$tmp/record_recovery_service_stop.json"
record_recovery_service_pid=""
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/record_recovery_service_log.schema.json" --jsonl "$tmp/record_recovery_service.log"
python3 "$REPO_ROOT/scripts/export_record_recovery_service_metrics.py" \
  --log-jsonl "$tmp/record_recovery_service.log" \
  --out "$tmp/record_recovery_service_metrics.json" \
  --expect-transport unix_socket \
  --expect-event record_recovery_service_start \
  --expect-event record_recovery_service_request \
  --expect-event record_recovery_service_stop \
  --expect-min-requests 1 \
  > /dev/null
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/record_recovery_service_metrics.schema.json" --json "$tmp/record_recovery_service_metrics.json"
[[ ! -e "$tmp/record_recovery.sock" ]] || { echo "[ERROR] record recovery socket still exists after stop" >&2; exit 1; }
[[ ! -e "$tmp/record_recovery_service.pid" ]] || { echo "[ERROR] record recovery pid file still exists after stop" >&2; exit 1; }
[[ ! -e "$tmp/record_recovery_service.ready" ]] || { echo "[ERROR] record recovery ready file still exists after stop" >&2; exit 1; }

export SSE_RECORD_STORE_PASSPHRASE="contract-record-store-passphrase"
"$SSE_PY" "$REPO_ROOT/scripts/record_recovery_contract_smoke_helpers.py" \
  build-store \
  --out-path "$tmp/http_record_store.enc.jsonl"

record_recovery_http_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
python3 "$REPO_ROOT/scripts/build_runtime_contract_smoke_configs.py" \
  record-recovery-http \
  --out-config "$tmp/record_recovery_http_service_config.json" \
  --tmp-dir "$tmp" \
  --port "$record_recovery_http_port"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/record_recovery_service_config.schema.json" --json "$tmp/record_recovery_http_service_config.json"
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" start \
  --config "$tmp/record_recovery_http_service_config.json" \
  > "$tmp/record_recovery_http_service_start.json"
record_recovery_service_pid="$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field --json-file "$tmp/record_recovery_http_service_start.json" --field started_pid)"
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" status \
  --config "$tmp/record_recovery_http_service_config.json" \
  > "$tmp/record_recovery_http_service_status.json"
python3 "$REPO_ROOT/scripts/request_record_recovery_service.py" \
  --config "$tmp/record_recovery_http_service_config.json" \
  > "$tmp/record_recovery_http_service_health.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/record_recovery_service_health.schema.json" --json "$tmp/record_recovery_http_service_health.json"

"$SSE_PY" "$REPO_ROOT/scripts/record_recovery_contract_smoke_helpers.py" \
  run-http-recovery \
  --store-path "$tmp/http_record_store.enc.jsonl" \
  --out-csv "$tmp/http_recovered_client.csv" \
  --result-json "$tmp/http_recovery_result.json" \
  --port "$record_recovery_http_port"
"$SSE_PY" "$REPO_ROOT/scripts/record_recovery_contract_smoke_helpers.py" \
  validate-http-recovery \
  --status-json "$tmp/record_recovery_http_service_status.json" \
  --health-json "$tmp/record_recovery_http_service_health.json" \
  --result-json "$tmp/http_recovery_result.json" \
  --out-csv "$tmp/http_recovered_client.csv"

"$SSE_PY" "$REPO_ROOT/scripts/record_recovery_contract_smoke_helpers.py" \
  expect-http-deny \
  --store-path "$tmp/http_record_store.enc.jsonl" \
  --port "$record_recovery_http_port"

mkdir -p "$tmp/http_home"
HOME="$tmp/http_home" "$SSE_PY" "$REPO_ROOT/scripts/record_recovery_contract_smoke_helpers.py" \
  run-http-export \
  --store-path "$tmp/http_record_store.enc.jsonl" \
  --out-csv "$tmp/http_export_client.csv" \
  --audit-jsonl "$tmp/http_export_audit.jsonl" \
  --port "$record_recovery_http_port"
"$SSE_PY" "$REPO_ROOT/scripts/record_recovery_contract_smoke_helpers.py" \
  validate-http-export \
  --out-csv "$tmp/http_export_client.csv" \
  --audit-jsonl "$tmp/http_export_audit.jsonl"

python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/sse_bridge_export_audit.schema.json" --jsonl "$tmp/http_export_audit.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/sse_record_recovery_service_audit.schema.json" --jsonl "$tmp/record_recovery_service_http_runtime_audit.jsonl"
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" stop \
  --config "$tmp/record_recovery_http_service_config.json" \
  > "$tmp/record_recovery_http_service_stop.json"
record_recovery_service_pid=""
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/record_recovery_service_log.schema.json" --jsonl "$tmp/record_recovery_service_http.log"
python3 "$REPO_ROOT/scripts/export_record_recovery_service_metrics.py" \
  --log-jsonl "$tmp/record_recovery_service_http.log" \
  --out "$tmp/record_recovery_service_http_metrics.json" \
  --expect-transport http \
  --expect-event record_recovery_service_start \
  --expect-event record_recovery_service_request \
  --expect-event record_recovery_service_stop \
  --expect-min-requests 3 \
  > /dev/null
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/record_recovery_service_metrics.schema.json" --json "$tmp/record_recovery_service_http_metrics.json"
[[ ! -e "$tmp/record_recovery_service_http.pid" ]] || { echo "[ERROR] HTTP record recovery pid file still exists after stop" >&2; exit 1; }
[[ ! -e "$tmp/record_recovery_service_http.ready" ]] || { echo "[ERROR] HTTP record recovery ready file still exists after stop" >&2; exit 1; }

# D1: HTTPS/mTLS baseline for the standalone record-recovery HTTP service.
mkdir -p "$tmp/mtls"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -subj "/CN=seccomp-contract-ca" \
  -keyout "$tmp/mtls/ca.key" \
  -out "$tmp/mtls/ca.crt" >/dev/null 2>&1
openssl req -newkey rsa:2048 -nodes \
  -subj "/CN=127.0.0.1" \
  -keyout "$tmp/mtls/server.key" \
  -out "$tmp/mtls/server.csr" >/dev/null 2>&1
openssl x509 -req \
  -in "$tmp/mtls/server.csr" \
  -CA "$tmp/mtls/ca.crt" \
  -CAkey "$tmp/mtls/ca.key" \
  -CAcreateserial \
  -days 1 \
  -out "$tmp/mtls/server.crt" >/dev/null 2>&1
openssl req -newkey rsa:2048 -nodes \
  -subj "/CN=record-recovery-contract-client" \
  -keyout "$tmp/mtls/client.key" \
  -out "$tmp/mtls/client.csr" >/dev/null 2>&1
openssl x509 -req \
  -in "$tmp/mtls/client.csr" \
  -CA "$tmp/mtls/ca.crt" \
  -CAkey "$tmp/mtls/ca.key" \
  -CAcreateserial \
  -days 1 \
  -out "$tmp/mtls/client.crt" >/dev/null 2>&1
record_recovery_mtls_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
python3 "$REPO_ROOT/scripts/build_runtime_contract_smoke_configs.py" \
  record-recovery-http \
  --out-config "$tmp/record_recovery_http_mtls_service_config.json" \
  --tmp-dir "$tmp" \
  --port "$record_recovery_mtls_port" \
  --tls-ca-cert "$tmp/mtls/ca.crt" \
  --tls-server-cert "$tmp/mtls/server.crt" \
  --tls-server-key "$tmp/mtls/server.key" \
  --tls-client-cert "$tmp/mtls/client.crt" \
  --tls-client-key "$tmp/mtls/client.key" \
  --tls-require-client-cert \
  --tls-no-verify-hostname
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/record_recovery_service_config.schema.json" --json "$tmp/record_recovery_http_mtls_service_config.json"
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" start \
  --config "$tmp/record_recovery_http_mtls_service_config.json" \
  > "$tmp/record_recovery_http_mtls_service_start.json"
record_recovery_service_pid="$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field --json-file "$tmp/record_recovery_http_mtls_service_start.json" --field started_pid)"
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" status \
  --config "$tmp/record_recovery_http_mtls_service_config.json" \
  > "$tmp/record_recovery_http_mtls_service_status.json"
python3 "$REPO_ROOT/scripts/request_record_recovery_service.py" \
  --config "$tmp/record_recovery_http_mtls_service_config.json" \
  > "$tmp/record_recovery_http_mtls_service_health.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/record_recovery_service_health.schema.json" --json "$tmp/record_recovery_http_mtls_service_health.json"
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" stop \
  --config "$tmp/record_recovery_http_mtls_service_config.json" \
  > "$tmp/record_recovery_http_mtls_service_stop.json"
record_recovery_service_pid=""
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/record_recovery_service_log.schema.json" --jsonl "$tmp/record_recovery_service_http.log"
python3 -c 'import json, sys; records=[json.loads(line) for line in open(sys.argv[1], "r", encoding="utf-8") if line.strip()]; starts=[r for r in records if r.get("event") == "record_recovery_service_start" and r.get("tls_enabled") is True]; assert starts and starts[-1].get("tls_require_client_cert") is True, records[-5:]' "$tmp/record_recovery_service_http.log"
[[ ! -e "$tmp/record_recovery_service_http.pid" ]] || { echo "[ERROR] mTLS record recovery pid file still exists after stop" >&2; exit 1; }
[[ ! -e "$tmp/record_recovery_service_http.ready" ]] || { echo "[ERROR] mTLS record recovery ready file still exists after stop" >&2; exit 1; }

printf '%s\n' 'not-a-token' > "$tmp/bridge_job/bad_server.csv"
expect_failure python3 "$TABULAR_VALIDATOR" --contract pjc-server-csv --path "$tmp/bridge_job/bad_server.csv"

printf '%s\n' '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef,not-an-int' > "$tmp/bridge_job/bad_client.csv"
expect_failure python3 "$TABULAR_VALIDATOR" --contract pjc-client-csv --path "$tmp/bridge_job/bad_client.csv"

python3 "$REPO_ROOT/scripts/check_mainline_contract.py" \
  --out-base "$tmp" \
  --job-id contract-check \
  --output "$tmp/mainline_contract_check.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/mainline_contract_check.schema.json" \
  --json "$tmp/mainline_contract_check.json"
printf '%s\n' '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef,5' \
  > "$tmp/sse_exports/client.csv"
python3 "$REPO_ROOT/scripts/check_mainline_contract.py" \
  --out-base "$tmp" \
  --job-id contract-check \
  --allow-retained-managed-handoff \
  --retained-managed-handoff-reason contract_smoke_retained_handoff \
  --output "$tmp/mainline_contract_check_retained.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/mainline_contract_check.schema.json" \
  --json "$tmp/mainline_contract_check_retained.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); client=(payload.get("handoff_cleanup") or {}).get("client") or {}; assert payload.get("status") == "ok", payload; assert client.get("status") == "retained", client; assert client.get("retention_reason") == "contract_smoke_retained_handoff", client' "$tmp/mainline_contract_check_retained.json"
rm -f "$tmp/sse_exports/client.csv"
python3 "$REPO_ROOT/scripts/build_audit_chain.py" --out-base "$tmp" --job-id contract-check
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/audit_chain.schema.json" --json "$tmp/audit_chain.json"
python3 "$REPO_ROOT/scripts/export_observability_events.py" \
  --audit-chain "$tmp/audit_chain.json" \
  --out "$tmp/pipeline_observability.json" \
  > "$tmp/pipeline_observability.stdout.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/pipeline_observability.schema.json" --json "$tmp/pipeline_observability.json"
python3 "$REPO_ROOT/scripts/export_catalog_lineage.py" \
  --audit-chain "$tmp/audit_chain.json" \
  --out "$tmp/catalog_lineage.json" \
  > "$tmp/catalog_lineage.stdout.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/catalog_lineage.schema.json" --json "$tmp/catalog_lineage.json"
python3 "$REPO_ROOT/scripts/check_pipeline_artifact_smoke_reports.py" \
  --tmp-dir "$tmp"
python3 "$REPO_ROOT/scripts/seal_audit_artifact.py" --input "$tmp/audit_chain.json" --out "$tmp/audit_chain.seal.json" --job-id contract-check
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/audit_seal.schema.json" --json "$tmp/audit_chain.seal.json"
export SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY="contract-audit-anchor-key"
python3 "$REPO_ROOT/scripts/archive_audit_bundle.py" \
  --audit-chain "$tmp/audit_chain.json" \
  --audit-seal "$tmp/audit_chain.seal.json" \
  --archive-dir "$tmp/audit_archive" \
  --job-id contract-check \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/audit_archive_index.schema.json" --jsonl "$tmp/audit_archive/audit_chain_index.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/audit_archive_anchor.schema.json" --jsonl "$tmp/audit_archive/audit_chain_anchor.jsonl"
python3 "$REPO_ROOT/scripts/publish_external_audit_anchor.py" \
  --anchor-file "$tmp/audit_archive/audit_chain_anchor.jsonl" \
  --external-ledger "$tmp/external_audit_anchor_ledger.jsonl" \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY \
  --require-signature \
  --output "$tmp/external_audit_anchor_report.json" \
  --assert-ok \
  > /dev/null
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/external_audit_anchor_report.schema.json" --json "$tmp/external_audit_anchor_report.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); s=payload["summary"]; assert payload["mode"] == "publish", payload; assert s["status"] == "ok", s; assert s["verified_chain"] is True, s; assert s["published_count"] == s["anchor_record_count"] >= 1, s; assert s["signed_count"] >= 1, s; assert payload["records"][0]["signature_verified"] is True, payload["records"]' "$tmp/external_audit_anchor_report.json"
python3 "$REPO_ROOT/scripts/verify_audit_bundle.py" \
  --audit-chain "$tmp/audit_chain.json" \
  --audit-seal "$tmp/audit_chain.seal.json" \
  --job-id contract-check \
  > "$tmp/audit_bundle_verify_direct.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/audit_bundle_verification.schema.json" --json "$tmp/audit_bundle_verify_direct.json"
python3 "$REPO_ROOT/scripts/verify_audit_bundle.py" \
  --archive-index "$tmp/audit_archive/audit_chain_index.jsonl" \
  --job-id contract-check \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY \
  --restore-dir "$tmp/audit_restore" \
  > "$tmp/audit_bundle_verify_archive.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/audit_bundle_verification.schema.json" --json "$tmp/audit_bundle_verify_archive.json"

python3 "$REPO_ROOT/scripts/init_metadata_db.py" \
  --db-path "$tmp/platform_metadata.db" \
  > "$tmp/platform_metadata_init.json"
python3 "$REPO_ROOT/scripts/import_run_metadata.py" \
  --out-base "$tmp" \
  --db-path "$tmp/platform_metadata.db" \
  > "$tmp/platform_metadata_import.json"
python3 "$REPO_ROOT/scripts/import_run_metadata.py" \
  --out-base "$tmp" \
  --db-path "$tmp/platform_metadata.db" \
  --dry-run \
  > "$tmp/platform_metadata_import_dry_run.json"
python3 "$REPO_ROOT/scripts/import_run_metadata.py" \
  --out-base "$tmp" \
  --db-path "$tmp/platform_metadata.db" \
  > "$tmp/platform_metadata_import_replay.json"
printf '%s\n' "$tmp" > "$tmp/platform_metadata_out_bases.txt"
python3 "$REPO_ROOT/scripts/import_run_metadata.py" \
  --out-base-file "$tmp/platform_metadata_out_bases.txt" \
  --db-path "$tmp/platform_metadata.db" \
  --dry-run \
  > "$tmp/platform_metadata_import_batch.json"
python3 "$REPO_ROOT/scripts/check_metadata_schema_portability.py" \
  --output "$tmp/platform_metadata_schema_portability.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_import_report.schema.json" \
  --json "$tmp/platform_metadata_import.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_import_report.schema.json" \
  --json "$tmp/platform_metadata_import_dry_run.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_import_report.schema.json" \
  --json "$tmp/platform_metadata_import_replay.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_import_report.schema.json" \
  --json "$tmp/platform_metadata_import_batch.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_schema_portability.schema.json" \
  --json "$tmp/platform_metadata_schema_portability.json"
test "$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field --json-file "$tmp/platform_metadata_import.json" --field summary.inserted_job_count)" = "1"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["mode"] == "apply", payload; assert payload["summary"]["inserted_job_count"] == 1, payload; assert payload["summary"]["replaced_job_count"] == 0, payload; item=payload["imports"][0]; assert item["action"] == "insert", item; assert item["existing_job"]["exists"] is False, item; assert item["job_state_after"]["exists"] is True, item; assert item["job_state_after"]["row_counts"]["audit_events"] >= 6, item' "$tmp/platform_metadata_import.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["mode"] == "dry_run", payload; assert payload["summary"]["inserted_job_count"] == 0, payload; assert payload["summary"]["replaced_job_count"] == 1, payload; item=payload["imports"][0]; assert item["action"] == "replace", item; assert item["existing_job"]["exists"] is True, item; assert item["imported_at_utc"] is None, item; assert item["result"] is None, item; assert "job_state_after" not in item, item' "$tmp/platform_metadata_import_dry_run.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["mode"] == "apply", payload; assert payload["summary"]["inserted_job_count"] == 0, payload; assert payload["summary"]["replaced_job_count"] == 1, payload; item=payload["imports"][0]; assert item["action"] == "replace", item; assert item["existing_job"]["exists"] is True, item; assert item["job_state_after"]["exists"] is True, item; assert item["job_state_after"]["row_counts"]["job_artifacts"] >= 8, item' "$tmp/platform_metadata_import_replay.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["mode"] == "dry_run", payload; assert payload["summary"]["processed_run_count"] == 1, payload; item=payload["imports"][0]; assert item["action"] == "replace", item; assert item["out_base"], item' "$tmp/platform_metadata_import_batch.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["status"] == "ok", payload; assert payload["summary"]["sqlite_only_construct_count"] == 0, payload; check_names={item["name"] for item in payload["checks"]}; assert "sqlite_only_constructs" in check_names and "expected_indexes_present" in check_names, payload' "$tmp/platform_metadata_schema_portability.json"
# Postgres DDL target validation
python3 "$REPO_ROOT/scripts/export_postgres_ddl.py" \
  --output "$tmp/postgres_ddl_export.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/postgres_ddl_export.schema.json" \
  --json "$tmp/postgres_ddl_export.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["valid"] is True, payload; assert len(payload["sqlite_only_tokens"]) == 0, payload; assert len(payload["type_upgrade_issues"]) == 0, payload; assert len(payload["column_parity_issues"]) == 0, payload; assert len(payload["table_parity"]["missing_in_postgres"]) == 0, payload; assert "TIMESTAMPTZ" in payload["postgres_types_confirmed"], payload; assert "JSONB" in payload["postgres_types_confirmed"], payload; assert "SERIAL" in payload["postgres_types_confirmed"], payload' "$tmp/postgres_ddl_export.json"
python3 "$REPO_ROOT/scripts/manage_metadata_db.py" \
  status \
  --db-path "$tmp/platform_metadata.db" \
  --output "$tmp/platform_metadata_status_report.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_db_status.schema.json" \
  --json "$tmp/platform_metadata_status_report.json"
platform_metadata_job_count="$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field \
  --json-file "$tmp/platform_metadata_status_report.json" \
  --field summary.job_count)"
[[ "$platform_metadata_job_count" == "1" ]] || { echo "[ERROR] metadata DB status reported unexpected job_count: $platform_metadata_job_count" >&2; exit 1; }
python3 "$REPO_ROOT/scripts/manage_metadata_db.py" \
  export-json \
  --db-path "$tmp/platform_metadata.db" \
  --out-path "$tmp/platform_metadata_export.json" \
  --job-limit 10 \
  --entity-limit 10 \
  --artifact-limit 10 \
  --overwrite \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_db_export.schema.json" \
  --json "$tmp/platform_metadata_export.json"
platform_metadata_export_jobs="$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field \
  --json-file "$tmp/platform_metadata_export.json" \
  --field jobs.jobs)"
[[ "$platform_metadata_export_jobs" == *"contract-check"* ]] || { echo "[ERROR] metadata DB export missing contract-check job" >&2; exit 1; }
python3 "$REPO_ROOT/scripts/manage_metadata_db.py" \
  backup \
  --db-path "$tmp/platform_metadata.db" \
  --out-path "$tmp/platform_metadata.backup.db" \
  --overwrite \
  > "$tmp/platform_metadata_backup.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_db_backup.schema.json" \
  --json "$tmp/platform_metadata_backup.json"
platform_metadata_backup_api="$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field \
  --json-file "$tmp/platform_metadata_backup.json" \
  --field used_sqlite_backup_api)"
[[ "$platform_metadata_backup_api" == "True" ]] || { echo "[ERROR] metadata DB backup did not report SQLite backup API usage" >&2; exit 1; }
python3 "$REPO_ROOT/scripts/manage_metadata_db.py" \
  status \
  --db-path "$tmp/platform_metadata.backup.db" \
  > "$tmp/platform_metadata_backup_status.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_db_status.schema.json" \
  --json "$tmp/platform_metadata_backup_status.json"
python3 "$REPO_ROOT/scripts/manage_metadata_db.py" \
  restore \
  --backup-db-path "$tmp/platform_metadata.backup.db" \
  --out-db-path "$tmp/platform_metadata.restored.db" \
  --overwrite \
  > "$tmp/platform_metadata_restore.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_db_restore.schema.json" \
  --json "$tmp/platform_metadata_restore.json"
platform_metadata_restore_api="$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field \
  --json-file "$tmp/platform_metadata_restore.json" \
  --field used_sqlite_backup_api)"
[[ "$platform_metadata_restore_api" == "True" ]] || { echo "[ERROR] metadata DB restore did not report SQLite backup API usage" >&2; exit 1; }
platform_metadata_restored_job_count="$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field \
  --json-file "$tmp/platform_metadata_restore.json" \
  --field restored_status.summary.job_count)"
[[ "$platform_metadata_restored_job_count" == "1" ]] || { echo "[ERROR] metadata DB restore reported unexpected job_count: $platform_metadata_restored_job_count" >&2; exit 1; }
# Cross-batch reconcile on the imported DB (fresh import should be clean)
python3 "$REPO_ROOT/scripts/reconcile_metadata_batches.py" \
  --db-path "$tmp/platform_metadata.db" \
  --output "$tmp/platform_metadata_reconcile.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_batch_reconcile.schema.json" \
  --json "$tmp/platform_metadata_reconcile.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["mode"] == "dry_run", payload; assert payload["summary"]["status"] == "ok", payload; assert payload["summary"]["total_issues"] == 0, payload; assert payload["summary"]["job_count"] >= 1, payload' "$tmp/platform_metadata_reconcile.json"
# C1-C5 sidecar materialization: workflow transitions, versions, lineage read model, retention/reconcile plan.
python3 "$REPO_ROOT/scripts/materialize_control_plane_deepening.py" \
  --db-path "$tmp/platform_metadata.db" \
  --catalog-lineage "$tmp/catalog_lineage.json" \
  --output "$tmp/control_plane_deepening.json" \
  --assert-ok \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/control_plane_deepening_report.schema.json" \
  --json "$tmp/control_plane_deepening.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); s=payload["summary"]; assert payload["mode"] == "apply", payload; assert s["status"] == "ok", payload; assert s["job_transition_count"] >= 2, s; assert s["policy_version_count"] >= 1, s; assert s["service_version_count"] >= 1, s; assert s["catalog_lineage_count"] >= 4, s; assert s["retention_plan_count"] >= 1, s' "$tmp/control_plane_deepening.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --list-entity job-state-transitions \
  --limit 20 \
  > "$tmp/platform_metadata_job_state_transitions.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --list-entity policy-versions \
  --limit 20 \
  > "$tmp/platform_metadata_policy_versions.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --list-entity service-versions \
  --limit 20 \
  > "$tmp/platform_metadata_service_versions.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --list-entity catalog-lineage-read-model \
  --limit 20 \
  > "$tmp/platform_metadata_catalog_lineage_read_model.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --list-entity retention-reconcile-plan \
  --limit 20 \
  > "$tmp/platform_metadata_retention_reconcile_plan.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["pagination"]["total_matching_count"] >= 2, payload; assert any(item["event_type"] == "job_status" and item["to_state"] in {"released", "denied", "failed", "completed"} for item in payload["items"]), payload["items"]' "$tmp/platform_metadata_job_state_transitions.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["pagination"]["total_matching_count"] >= 1, payload; assert payload["items"][0]["is_current"] is True, payload["items"]' "$tmp/platform_metadata_policy_versions.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["pagination"]["total_matching_count"] >= 1, payload; assert payload["items"][0]["is_current"] is True, payload["items"]' "$tmp/platform_metadata_service_versions.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["pagination"]["total_matching_count"] >= 4, payload; kinds={item["lineage_kind"] for item in payload["items"]}; assert {"dataset", "artifact", "edge"} <= kinds, kinds; assert all(item["path_redacted"] is True for item in payload["items"] if item["lineage_kind"] == "artifact"), payload["items"]' "$tmp/platform_metadata_catalog_lineage_read_model.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["pagination"]["total_matching_count"] >= 1, payload; actions={item["recommended_action"] for item in payload["items"]}; assert "retain" in actions, actions' "$tmp/platform_metadata_retention_reconcile_plan.json"
python3 "$REPO_ROOT/scripts/manage_metadata_db.py" \
  apply-registry \
  --db-path "$tmp/platform_registry.db" \
  --manifest "$REPO_ROOT/config/metadata_registry.example.json" \
  --dry-run \
  --output "$tmp/platform_registry_apply_dry_run.json" \
  > /dev/null
python3 "$REPO_ROOT/scripts/manage_metadata_db.py" \
  apply-registry \
  --db-path "$tmp/platform_registry.db" \
  --manifest "$REPO_ROOT/config/metadata_registry.example.json" \
  --output "$tmp/platform_registry_apply.json" \
  > /dev/null
python3 "$REPO_ROOT/scripts/manage_metadata_db.py" \
  apply-registry \
  --db-path "$tmp/platform_registry.db" \
  --manifest "$REPO_ROOT/config/metadata_registry.example.json" \
  --dry-run \
  --output "$tmp/platform_registry_apply_reconcile.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_registry_apply_report.schema.json" \
  --json "$tmp/platform_registry_apply_dry_run.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_registry_apply_report.schema.json" \
  --json "$tmp/platform_registry_apply.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_registry_apply_report.schema.json" \
  --json "$tmp/platform_registry_apply_reconcile.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); requested=payload["summary"]["requested_counts"]; assert payload["mode"] == "dry_run", payload; assert requested["tenants"] == 1, requested; assert requested["key_refs"] == 2, requested; assert requested["key_versions"] == 2, requested; assert requested["issuer_registry"] == 2, requested; assert payload["summary"]["entity_action_counts"]["insert"] >= 21, payload; assert payload["summary"]["policy_action_counts"]["insert"] == 1, payload; assert payload["validation"]["status"] == "ok", payload' "$tmp/platform_registry_apply_dry_run.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["mode"] == "apply", payload; assert payload["summary"]["entity_action_counts"]["insert"] >= 21, payload; assert payload["summary"]["policy_action_counts"]["insert"] == 1, payload; key_refs=payload["entities"]["key_refs"]; assert len(key_refs) == 2, key_refs; assert any(item["state_after"]["backend_kind"] == "local_keyring" and item["state_after"]["active_version"] == "demo-v1" for item in key_refs), key_refs; issuer_registry=payload["entities"]["issuer_registry"]; assert len(issuer_registry) == 2, issuer_registry; policy=payload["policies"][0]; assert policy["state_after"]["binding_count"] == 5, policy; assert policy["state_after"]["permission_count"] >= 5, policy' "$tmp/platform_registry_apply.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["mode"] == "dry_run", payload; assert payload["summary"]["entity_action_counts"]["noop"] >= 21, payload; assert payload["summary"]["policy_action_counts"]["noop"] == 1, payload' "$tmp/platform_registry_apply_reconcile.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_registry.db" \
  --list-entity policies \
  --limit 5 \
  > "$tmp/platform_registry_policies.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_registry.db" \
  --list-entity caller-identities \
  --caller recovery_ops_demo \
  --limit 20 \
  > "$tmp/platform_registry_caller_identities.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_registry.db" \
  --list-entity caller-permissions \
  --caller commerce_ops_demo \
  --limit 20 \
  > "$tmp/platform_registry_caller_permissions.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_registry.db" \
  --list-entity key-refs \
  --service-id orders-recovery \
  --limit 20 \
  > "$tmp/platform_registry_key_refs.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_registry.db" \
  --list-entity key-versions \
  --key-name bridge-token \
  --limit 20 \
  > "$tmp/platform_registry_key_versions.json"
python3 "$REPO_ROOT/scripts/export_authz_tuples.py" \
  --db-path "$tmp/platform_registry.db" \
  --output "$tmp/platform_registry_authz_tuples.json" \
  > /dev/null
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["count"] == 1, payload; item=payload["items"][0]; assert item["subject_type"] == "service_account", item; assert item["service_id"] == "orders-recovery", item; assert item["enabled"] is True, item; assert "service_operator" in item["platform_roles"], item' "$tmp/platform_registry_caller_identities.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["count"] == 2, payload; names={item["key_name"] for item in payload["items"]}; assert names == {"bridge-token", "audit-integrity"}, names; bridge=next(item for item in payload["items"] if item["key_name"] == "bridge-token"); assert bridge["backend_kind"] == "local_keyring", bridge; assert sorted(bridge["allowed_callers"]) == ["commerce_ops_demo", "recovery_ops_demo"], bridge' "$tmp/platform_registry_key_refs.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["count"] == 1, payload; item=payload["items"][0]; assert item["key_name"] == "bridge-token", item; assert item["version"] == "demo-v1", item; assert item["enabled"] is True, item; assert item["status"] == "active", item; assert item["secret_ref_kind"] == "env", item; assert item["secret_ref_name"] == "BRIDGE_TOKEN_SECRET", item' "$tmp/platform_registry_key_versions.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/authz_tuple_export.schema.json" \
  --json "$tmp/platform_registry_authz_tuples.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); summary=payload["summary"]; assert summary["subject_count"] == 5, summary; assert summary["active_subject_count"] == 3, summary; assert summary["disabled_subject_count"] == 2, summary; assert summary["subject_type_counts"]["service_account"] == 1, summary; assert any(item["subject"] == "service_account:recovery_ops_demo" for item in payload["subjects"]), payload["subjects"]; assert any(item["object"] == "privacy_service:orders-recovery" and item["user"] == "user:commerce_ops_demo" for item in payload["tuples"]), payload["tuples"]' "$tmp/platform_registry_authz_tuples.json"
python3 "$REPO_ROOT/scripts/export_authz_tuples.py" \
  --db-path "$tmp/platform_metadata.db" \
  --output "$tmp/platform_metadata_authz_tuples.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/authz_tuple_export.schema.json" \
  --json "$tmp/platform_metadata_authz_tuples.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); source=payload["source"]; summary=payload["summary"]; assert source["kind"] == "metadata_db", source; assert summary["subject_count"] == 3, summary; assert summary["active_subject_count"] == 2, summary; assert any(item["object"] == "platform_role:privacy_operator" and item["user"] == "user:auto_demo" for item in payload["tuples"]), payload["tuples"]; assert any(item["object"] == "privacy_service:contract-recovery-service" and item["relation"] == "can_recover" for item in payload["tuples"]), payload["tuples"]' "$tmp/platform_metadata_authz_tuples.json"
# Mutation log query: registry apply should have logged mutations
python3 "$REPO_ROOT/scripts/query_mutation_log.py" \
  --db-path "$tmp/platform_registry.db" \
  --output "$tmp/platform_registry_mutation_log.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/mutation_log_query.schema.json" \
  --json "$tmp/platform_registry_mutation_log.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["pagination"]["total_matching_count"] >= 13, payload; ops={m["operation"] for m in payload["mutations"]}; assert "insert" in ops, ops; actors={m["actor"] for m in payload["mutations"]}; assert "apply-registry" in actors, actors; entity_types={m["entity_type"] for m in payload["mutations"]}; assert "policy" in entity_types, entity_types; assert "tenants" in entity_types or "callers" in entity_types, entity_types' "$tmp/platform_registry_mutation_log.json"
# Issuer registry: apply-registry should have registered the example issuers
python3 "$REPO_ROOT/scripts/query_mutation_log.py" \
  --db-path "$tmp/platform_registry.db" \
  --entity-type issuer_registry \
  --output "$tmp/platform_registry_issuer_mutations.json" \
  > /dev/null
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["pagination"]["total_matching_count"] >= 2, payload; issuers={m["entity_id"] for m in payload["mutations"]}; assert "https://keycloak.example.com/realms/commerce" in issuers, issuers; assert "local" in issuers, issuers' "$tmp/platform_registry_issuer_mutations.json"
# OIDC claim mapper smoke: parse a synthetic HS256 JWT with the example Keycloak issuer
_test_jwt="$(python3 - << 'PYEOF'
import base64, hmac as _hmac, hashlib, json, time, sys
s = "test-secret"
h = base64.urlsafe_b64encode(json.dumps({"alg":"HS256","typ":"JWT"}).encode()).rstrip(b"=").decode()
p = base64.urlsafe_b64encode(json.dumps({"iss":"https://keycloak.example.com/realms/commerce","sub":"svc-account-recovery","preferred_username":"recovery_ops_demo","azp":"orders-recovery","tenant_id":"demo_tenant","realm_access":{"roles":["service_operator"]},"aud":"seccomp-privacy-platform","exp":int(time.time())+3600,"iat":int(time.time()),"name":"Recovery Ops Demo SA"}).encode()).rstrip(b"=").decode()
si = f"{h}.{p}".encode()
sig = base64.urlsafe_b64encode(_hmac.new(s.encode(), si, hashlib.sha256).digest()).rstrip(b"=").decode()
print(f"{h}.{p}.{sig}")
PYEOF
)"
OIDC_TEST_SECRET=test-secret python3 "$REPO_ROOT/scripts/map_oidc_claims.py" \
  --token "$_test_jwt" \
  --claim-mapping-config "$REPO_ROOT/config/oidc_claim_mapping.example.json" \
  --verify-secret-env OIDC_TEST_SECRET \
  --db-path "$tmp/platform_registry.db" \
  --trusted-audience seccomp-privacy-platform \
  --require-registered-issuer \
  --output "$tmp/oidc_claim_map.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/oidc_claim_map.schema.json" \
  --json "$tmp/oidc_claim_map.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["valid"] is True, payload; assert payload["signature_verified"] is True, payload; assert payload["issuer_registered"] is True, payload; assert payload["issuer_enabled"] is True, payload; assert payload["audience_ok"] is True, payload; mapped=payload["mapped_fields"]; assert mapped["caller"] == "recovery_ops_demo", mapped; assert mapped["tenant_id"] == "demo_tenant", mapped; assert "service_operator" in mapped["platform_roles"], mapped' "$tmp/oidc_claim_map.json"
# OIDC claim mapper JWKS smoke: verify a synthetic RS256 JWT against an offline file:// JWKS
python3 - <<'PYEOF' "$tmp/oidc_test_jwks.json" "$tmp/oidc_test_rs256.jwt"
import base64, json, sys, time
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

jwks_path, token_path = sys.argv[1], sys.argv[2]
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
pub = key.public_key().public_numbers()
header = {"alg": "RS256", "typ": "JWT", "kid": "demo-kid-1"}
payload = {
    "iss": "https://keycloak.example.com/realms/commerce",
    "sub": "service-account:orders-recovery-operator",
    "preferred_username": "recovery_ops_demo",
    "azp": "orders-recovery",
    "tenant_id": "demo_tenant",
    "realm_access": {"roles": ["service_operator"]},
    "aud": "seccomp-privacy-platform",
    "exp": int(time.time()) + 3600,
    "iat": int(time.time()),
    "name": "Recovery Ops Demo SA",
}
h = b64u(json.dumps(header, separators=(",", ":")).encode())
p = b64u(json.dumps(payload, separators=(",", ":")).encode())
sig = key.sign(f"{h}.{p}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
token = f"{h}.{p}.{b64u(sig)}"
json.dump({
    "keys": [{
        "kty": "RSA",
        "kid": "demo-kid-1",
        "alg": "RS256",
        "use": "sig",
        "n": b64u(pub.n.to_bytes((pub.n.bit_length() + 7) // 8, "big")),
        "e": b64u(pub.e.to_bytes((pub.e.bit_length() + 7) // 8, "big")),
    }]
}, open(jwks_path, "w", encoding="utf-8"))
open(token_path, "w", encoding="utf-8").write(token)
PYEOF
python3 "$REPO_ROOT/scripts/map_oidc_claims.py" \
  --token "$(cat "$tmp/oidc_test_rs256.jwt")" \
  --claim-mapping-config "$REPO_ROOT/config/oidc_claim_mapping.example.json" \
  --jwks-uri "file://$tmp/oidc_test_jwks.json" \
  --db-path "$tmp/platform_registry.db" \
  --trusted-audience seccomp-privacy-platform \
  --require-registered-issuer \
  --output "$tmp/oidc_claim_map_rs256.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/oidc_claim_map.schema.json" \
  --json "$tmp/oidc_claim_map_rs256.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["valid"] is True, payload; assert payload["algorithm"] == "RS256", payload; assert payload["signature_verified"] is True, payload; assert payload["signature_skipped"] is False, payload; assert str(payload.get("jwks_uri") or "").startswith("file://"), payload; mapped=payload["mapped_fields"]; assert mapped["caller"] == "recovery_ops_demo", mapped; assert "service_operator" in mapped["platform_roles"], mapped' "$tmp/oidc_claim_map_rs256.json"
python3 -c 'import json, sys; path=sys.argv[1]; payload={"schema":"metadata_registry_manifest/v1","caller_identities":[{"caller":"recovery_ops_demo","issuer":"https://keycloak.example.com/realms/commerce","subject":"service-account:orders-recovery-operator","subject_type":"service_account","display_name":"Recovery Ops Demo SA","platform_roles":["service_operator"],"enabled":True,"metadata":{"entity_type":"service_account"},"source":"jwt_contract_fixture"}]}; open(path, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")' "$tmp/contract_jwt_identity_registry_manifest.json"
python3 "$REPO_ROOT/scripts/manage_metadata_db.py" \
  apply-registry \
  --db-path "$tmp/platform_registry.db" \
  --manifest "$tmp/contract_jwt_identity_registry_manifest.json" \
  > /dev/null
python3 -c 'import json, sys; path=sys.argv[1]; payload={"schema":"api_identity_token_map/v1","jwt_bearer":{"issuer":"https://keycloak.example.com/realms/commerce","claim_mapping_config":"'"$REPO_ROOT"'/config/oidc_claim_mapping.example.json","jwks_uri":"file://'"$tmp"'/oidc_test_jwks.json","trusted_audiences":["seccomp-privacy-platform"],"require_registered_issuer":True},"tokens":[]}; open(path, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")' "$tmp/api_identity_tokens_jwks.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/api_identity_token_map.schema.json" \
  --json "$tmp/api_identity_tokens_jwks.json"
SECCOMP_METADATA_JWKS_TOKEN="$(cat "$tmp/oidc_test_rs256.jwt")" python3 "$REPO_ROOT/scripts/resolve_api_identity.py" \
  --db-path "$tmp/platform_registry.db" \
  --identity-token-config "$tmp/api_identity_tokens_jwks.json" \
  --bearer-token-env SECCOMP_METADATA_JWKS_TOKEN \
  > "$tmp/api_identity_resolution_jwks.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/api_identity_resolution.schema.json" \
  --json "$tmp/api_identity_resolution_jwks.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); identity=payload["identity"]; assert payload["resolution_mode"] == "bearer_token", payload; assert identity["caller"] == "recovery_ops_demo", identity; assert identity["tenant_id"] == "commerce_tenant", identity; assert identity["issuer"] == "https://keycloak.example.com/realms/commerce", identity; assert identity["issuer_registered"] is True, identity; assert "service_operator" in identity["platform_roles"], identity' "$tmp/api_identity_resolution_jwks.json"
cp "$REPO_ROOT/config/keyring.example.json" "$tmp/keyring_jwks.json"
python3 -c 'import json, sys; path=sys.argv[1]; payload=json.load(open(path, "r", encoding="utf-8")); payload["keys"]["bridge-token"]["allowed_callers"]=["recovery_ops_demo"]; json.dump(payload, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2); open(path, "a", encoding="utf-8").write("\n")' "$tmp/keyring_jwks.json"
export BRIDGE_TOKEN_SECRET="contract-jwks-bridge-secret"
python3 "$REPO_ROOT/scripts/key_agent_service.py" \
  --socket-path "$tmp/key_agent_jwks.sock" \
  --keyring "$tmp/keyring_jwks.json" \
  --metadata-db-path "$tmp/platform_registry.db" \
  --identity-token-config "$tmp/api_identity_tokens_jwks.json" \
  --audit-log "$tmp/key_agent_jwks_access_audit.jsonl" \
  --pid-file "$tmp/key_agent_jwks.pid" \
  --ready-file "$tmp/key_agent_jwks.ready" \
  >"$tmp/key_agent_jwks.log" 2>&1 &
key_agent_jwks_pid=$!
if [[ -z "${key_agent_jwks_pid:-}" ]]; then
  echo "[ERROR] failed to start JWKS-backed key agent" >&2
  exit 1
fi
while [[ ! -s "$tmp/key_agent_jwks.ready" ]]; do sleep 0.1; done
SECCOMP_METADATA_JWKS_TOKEN="$(cat "$tmp/oidc_test_rs256.jwt")" python3 "$REPO_ROOT/scripts/request_key_agent.py" \
  --socket-path "$tmp/key_agent_jwks.sock" \
  --key-name bridge-token \
  --purpose bridge_token \
  --caller recovery_ops_demo \
  --job-id contract-jwks-check \
  --identity-token-env SECCOMP_METADATA_JWKS_TOKEN \
  > "$tmp/key_agent_jwks_result.json"
kill "$key_agent_jwks_pid" 2>/dev/null || true
wait "$key_agent_jwks_pid" 2>/dev/null || true
external_kms_jwks_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
python3 "$REPO_ROOT/scripts/build_runtime_contract_smoke_configs.py" \
  external-kms \
  --out-config "$tmp/external_kms_jwks.json" \
  --state-path "$tmp/keyring_external_jwks.json" \
  --port "$external_kms_jwks_port"
cp "$REPO_ROOT/config/keyring.example.json" "$tmp/keyring_external_jwks.json"
python3 -c 'import json, sys; path=sys.argv[1]; payload=json.load(open(path, "r", encoding="utf-8")); payload["keys"]["bridge-token"]["allowed_callers"]=["recovery_ops_demo"]; payload["keys"]["bridge-token"]["versions"]["demo-v1"]["secret_ref"]={"kind":"env","name":"BRIDGE_TOKEN_SECRET"}; json.dump(payload, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2); open(path, "a", encoding="utf-8").write("\n")' "$tmp/keyring_external_jwks.json"
python3 "$REPO_ROOT/scripts/external_kms_service.py" \
  --bind-host 127.0.0.1 \
  --port "$external_kms_jwks_port" \
  --state-file "$tmp/keyring_external_jwks.json" \
  --metadata-db-path "$tmp/platform_registry.db" \
  --identity-token-config "$tmp/api_identity_tokens_jwks.json" \
  --lifecycle-audit-log "$tmp/external_kms_jwks_lifecycle_audit.jsonl" \
  --pid-file "$tmp/external_kms_jwks.pid" \
  --ready-file "$tmp/external_kms_jwks.ready" \
  >"$tmp/external_kms_jwks.log" 2>&1 &
external_kms_jwks_pid=$!
if [[ -z "${external_kms_jwks_pid:-}" ]]; then
  echo "[ERROR] failed to start JWKS-backed external KMS" >&2
  exit 1
fi
python3 "$RUNTIME_SERVICE_HELPERS" wait-json-health \
  --url "http://127.0.0.1:$external_kms_jwks_port/healthz"
SECCOMP_METADATA_JWKS_TOKEN="$(cat "$tmp/oidc_test_rs256.jwt")" python3 "$REPO_ROOT/scripts/request_external_kms.py" \
  --config "$tmp/external_kms_jwks.json" \
  --key-name bridge-token \
  --purpose bridge_token \
  --caller recovery_ops_demo \
  --job-id contract-jwks-check \
  --identity-token-env SECCOMP_METADATA_JWKS_TOKEN \
  --audit-log "$tmp/external_key_access_jwks_audit.jsonl" \
  > "$tmp/external_kms_jwks_result.json"
kill "$external_kms_jwks_pid" 2>/dev/null || true
wait "$external_kms_jwks_pid" 2>/dev/null || true
# Vault HTTP client mock-mode smoke
python3 "$REPO_ROOT/scripts/vault_http_client.py" \
  --mock-file "$REPO_ROOT/config/vault_kv_backend.example.json" \
  --output "$tmp/vault_http_status.json" \
  status \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/vault_http_client_result.schema.json" \
  --json "$tmp/vault_http_status.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["mode"] == "mock", payload; assert payload["mock_secrets_count"] == 2, payload' "$tmp/vault_http_status.json"
python3 "$REPO_ROOT/scripts/vault_http_client.py" \
  --mock-file "$REPO_ROOT/config/vault_kv_backend.example.json" \
  --output "$tmp/vault_http_get.json" \
  get --path secret/data/bridge-token --field value --redact \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/vault_http_client_result.schema.json" \
  --json "$tmp/vault_http_get.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["ok"] is True, payload; assert payload["value"] == "REDACTED", payload; assert payload["resolved_version"] == "1", payload' "$tmp/vault_http_get.json"
# Issuer credential rotation dry-run on the registry DB
python3 "$REPO_ROOT/scripts/rotate_issuer_credentials.py" \
  --db-path "$tmp/platform_registry.db" \
  --issuer "https://keycloak.example.com/realms/commerce" \
  --dry-run \
  --output "$tmp/issuer_rotation_dry.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/issuer_credential_rotation.schema.json" \
  --json "$tmp/issuer_rotation_dry.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["ok"] is True, payload; assert payload["mode"] == "dry_run", payload; assert payload["issuer"] == "https://keycloak.example.com/realms/commerce", payload; assert payload["issuer_type"] == "keycloak", payload' "$tmp/issuer_rotation_dry.json"
# Key backend drift check: clean manifest → should report status=clean
python3 "$REPO_ROOT/scripts/check_key_backend_drift.py" \
  --db-path "$tmp/platform_registry.db" \
  --manifest "$REPO_ROOT/config/metadata_registry.example.json" \
  --output "$tmp/key_backend_drift_clean.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/key_backend_drift.schema.json" \
  --json "$tmp/key_backend_drift_clean.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["mode"] == "dry_run", payload; assert payload["summary"]["status"] == "clean", payload; assert payload["summary"]["actionable_findings"] == 0, payload; assert payload["summary"]["ref_key_count"] == 2, payload' "$tmp/key_backend_drift_clean.json"
# Key backend drift check via vault_kv source (informational diffs expected, no actionable failures)
python3 "$REPO_ROOT/scripts/check_key_backend_drift.py" \
  --db-path "$tmp/platform_registry.db" \
  --vault-kv-file "$REPO_ROOT/config/vault_kv_backend.example.json" \
  --output "$tmp/key_backend_drift_vault.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/key_backend_drift.schema.json" \
  --json "$tmp/key_backend_drift_vault.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["mode"] == "dry_run", payload; assert payload["summary"]["ref_key_count"] == 2, payload' "$tmp/key_backend_drift_vault.json"
# Policy drift check: clean registry DB should report status=clean
python3 "$REPO_ROOT/scripts/check_policy_drift.py" \
  --db-path "$tmp/platform_registry.db" \
  --output "$tmp/policy_drift_clean.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/policy_drift.schema.json" \
  --json "$tmp/policy_drift_clean.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["mode"] == "dry_run", payload; assert payload["summary"]["status"] == "clean", payload; assert payload["summary"]["registered_policy_count"] == 1, payload' "$tmp/policy_drift_clean.json"
# Policy change proposal: unchanged file → approved with no errors
python3 "$REPO_ROOT/scripts/propose_policy_change.py" \
  --db-path "$tmp/platform_registry.db" \
  --policy-file "$REPO_ROOT/sse/config/ecommerce_access_policy.example.json" \
  --output "$tmp/policy_proposal_approved.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/policy_change_proposal.schema.json" \
  --json "$tmp/policy_proposal_approved.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["governance_status"] == "approved", payload; assert payload["error_count"] == 0, payload; assert payload["mode"] == "dry_run", payload; assert payload["applied"] is False, payload; assert len(payload["caller_diff"]["retained"]) == 5, payload' "$tmp/policy_proposal_approved.json"
# Policy change proposal: removing active bridge caller → blocked
_blocked_policy="$(python3 - << 'PYEOF'
import json, tempfile, sys
p = json.load(open("sse/config/ecommerce_access_policy.example.json"))
del p["callers"]["commerce_ops_demo"]
import tempfile; f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
json.dump(p, f); f.close(); print(f.name)
PYEOF
)"
python3 "$REPO_ROOT/scripts/propose_policy_change.py" \
  --db-path "$tmp/platform_registry.db" \
  --policy-file "$_blocked_policy" \
  --existing-policy-path "$REPO_ROOT/sse/config/ecommerce_access_policy.example.json" \
  --output "$tmp/policy_proposal_blocked.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/policy_change_proposal.schema.json" \
  --json "$tmp/policy_proposal_blocked.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert payload["governance_status"] == "blocked", payload; assert payload["error_count"] >= 1, payload; rules={v["rule"] for v in payload["governance_violations"]}; assert "no_remove_active_bridge_callers" in rules, rules; assert "commerce_ops_demo" in payload["caller_diff"]["removed"], payload["caller_diff"]' "$tmp/policy_proposal_blocked.json"
rm -f "$_blocked_policy"
record_recovery_http_db_authz_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
python3 "$REPO_ROOT/scripts/build_runtime_contract_smoke_configs.py" \
  record-recovery-authz-db \
  --out-config "$tmp/record_recovery_authz_db_source.json" \
  --db-path "$tmp/platform_metadata.db" \
  --policy-path "$tmp/contract_export_policy.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_authz_source.schema.json" \
  --json "$tmp/record_recovery_authz_db_source.json"
python3 "$REPO_ROOT/scripts/build_runtime_contract_smoke_configs.py" \
  record-recovery-http \
  --out-config "$tmp/record_recovery_http_db_authz_service_config.json" \
  --tmp-dir "$tmp" \
  --port "$record_recovery_http_db_authz_port" \
  --service-id contract-recovery-service \
  --tenant-id contract-tenant \
  --dataset-id contract-dataset \
  --authz-config "$tmp/record_recovery_authz_db_source.json"
rm -f \
  "$tmp/record_recovery_service_http_runtime_audit.jsonl" \
  "$tmp/record_recovery_service_http.log" \
  "$tmp/record_recovery_service_http.pid" \
  "$tmp/record_recovery_service_http.ready"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_service_config.schema.json" \
  --json "$tmp/record_recovery_http_db_authz_service_config.json"
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" start \
  --config "$tmp/record_recovery_http_db_authz_service_config.json" \
  > "$tmp/record_recovery_http_db_authz_service_start.json"
record_recovery_service_pid="$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field --json-file "$tmp/record_recovery_http_db_authz_service_start.json" --field started_pid)"
python3 "$REPO_ROOT/scripts/request_record_recovery_service.py" \
  --config "$tmp/record_recovery_http_db_authz_service_config.json" \
  > "$tmp/record_recovery_http_db_authz_service_health.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_service_health.schema.json" \
  --json "$tmp/record_recovery_http_db_authz_service_health.json"
"$SSE_PY" "$REPO_ROOT/scripts/record_recovery_contract_smoke_helpers.py" \
  run-http-recovery \
  --store-path "$tmp/http_record_store.enc.jsonl" \
  --out-csv "$tmp/http_db_authz_recovered_client.csv" \
  --result-json "$tmp/http_db_authz_recovery_result.json" \
  --port "$record_recovery_http_db_authz_port" \
  --job-id contract-db-authz-check \
  --tenant-id contract-tenant \
  --dataset-id contract-dataset \
  --service-id contract-recovery-service
"$SSE_PY" "$REPO_ROOT/scripts/record_recovery_contract_smoke_helpers.py" \
  validate-authz-db-source \
  --health-json "$tmp/record_recovery_http_db_authz_service_health.json" \
  --audit-jsonl "$tmp/record_recovery_service_http_runtime_audit.jsonl" \
  --authz-config "$tmp/record_recovery_authz_db_source.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/sse_record_recovery_service_audit.schema.json" \
  --jsonl "$tmp/record_recovery_service_http_runtime_audit.jsonl"
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" stop \
  --config "$tmp/record_recovery_http_db_authz_service_config.json" \
  > "$tmp/record_recovery_http_db_authz_service_stop.json"
record_recovery_service_pid=""
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --job-id contract-check \
  > "$tmp/platform_metadata_job.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --caller auto_demo \
  --limit 5 \
  > "$tmp/platform_metadata_caller.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --tenant-id contract-tenant \
  --dataset-id contract-dataset \
  --service-id contract-recovery-service \
  --limit 5 \
  > "$tmp/platform_metadata_scope.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --caller auto_demo \
  --stage bridge \
  --limit 5 \
  > "$tmp/platform_metadata_stage.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --caller auto_demo \
  --stage bridge \
  --stage-status allow \
  --stage-sort duration_desc \
  --limit 5 \
  > "$tmp/platform_metadata_stage_filtered.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --caller auto_demo \
  --group-by stage \
  --limit 5 \
  > "$tmp/platform_metadata_group_stage.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --caller auto_demo \
  --group-by status \
  --limit 5 \
  > "$tmp/platform_metadata_group_status.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --caller auto_demo \
  --group-by stage \
  --output-format tsv \
  --limit 5 \
  > "$tmp/platform_metadata_group_stage.tsv"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --caller auto_demo \
  --group-by status \
  --output-format csv \
  --limit 5 \
  > "$tmp/platform_metadata_group_status.csv"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --caller auto_demo \
  --group-by stage \
  --output-format tsv \
  --columns stage,duration_total \
  --limit 5 \
  > "$tmp/platform_metadata_group_stage_columns.tsv"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --caller auto_demo \
  --group-by status \
  --output-format csv \
  --columns status,duration_total \
  --output-file "$tmp/platform_metadata_group_status.out.csv" \
  --limit 5 \
  > "$tmp/platform_metadata_group_status.stdout"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --list-entity tenants \
  --tenant-id contract-tenant \
  --limit 5 \
  > "$tmp/platform_metadata_tenants.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --list-entity services \
  --service-id contract-recovery-service \
  --limit 5 \
  > "$tmp/platform_metadata_services.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --list-entity policies \
  --limit 5 \
  > "$tmp/platform_metadata_policies.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --list-entity policy-bindings \
  --caller auto_demo \
  --limit 5 \
  > "$tmp/platform_metadata_policy_bindings.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --list-entity caller-permissions \
  --caller auto_demo \
  --limit 20 \
  > "$tmp/platform_metadata_caller_permissions.json"
python3 "$REPO_ROOT/scripts/query_metadata.py" \
  --db-path "$tmp/platform_metadata.db" \
  --list-entity caller-permissions \
  --caller auto_demo \
  --limit 2 \
  --offset 2 \
  > "$tmp/platform_metadata_caller_permissions_page.json"
mkdir -p "$tmp/query_requests"
python3 "$REPO_ROOT/scripts/build_query_workflow_request_fixtures.py" \
  --default-out "$tmp/query_requests/cross_party_match.json" \
  --keep-out "$tmp/query_requests/cross_party_match_keep.json" \
  --ecommerce-out "$tmp/query_requests/ecommerce_cross_party_match.json"
python3 "$REPO_ROOT/scripts/submit_query_workflow.py" \
  --request-file "$tmp/query_requests/cross_party_match.json" \
  --dry-run \
  --manifest-out "$tmp/query_workflow_manifest.json" \
  > "$tmp/query_workflow_stdout.json"
python3 "$REPO_ROOT/scripts/submit_query_workflow.py" \
  --request-file "$tmp/query_requests/cross_party_match_keep.json" \
  --dry-run \
  --manifest-out "$tmp/query_workflow_keep_manifest.json" \
  > "$tmp/query_workflow_keep_stdout.json"
query_workflow_api_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
export SECCOMP_QUERY_WORKFLOW_API_TOKEN="contract-query-workflow-api-token"
python3 "$REPO_ROOT/scripts/serve_query_workflow_api.py" \
  --bind-host 127.0.0.1 \
  --port "$query_workflow_api_port" \
  --auth-token-env SECCOMP_QUERY_WORKFLOW_API_TOKEN \
  --pid-file "$tmp/query_workflow_api.pid" \
  --ready-file "$tmp/query_workflow_api.ready" \
  > "$tmp/query_workflow_api.log" 2>&1 &
query_workflow_api_pid=$!
python3 "$RUNTIME_SERVICE_HELPERS" wait-json-health \
  --url "http://127.0.0.1:$query_workflow_api_port/healthz"
python3 "$REPO_ROOT/scripts/materialize_platform_api_smoke_reports.py" \
  --tmp-dir "$tmp" \
  --query-port "$query_workflow_api_port" \
  --query-request-file "$tmp/query_requests/cross_party_match.json"
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  query-health \
  --base-url "http://127.0.0.1:$query_workflow_api_port" \
  --output-file "$tmp/query_workflow_client_health.json" \
  > /dev/null
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  query-submit \
  --base-url "http://127.0.0.1:$query_workflow_api_port" \
  --auth-token-env SECCOMP_QUERY_WORKFLOW_API_TOKEN \
  --request-file "$tmp/query_requests/cross_party_match.json" \
  --output-file "$tmp/query_workflow_client_dry_run.json" \
  > /dev/null
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  query-status \
  --base-url "http://127.0.0.1:$query_workflow_api_port" \
  --auth-token-env SECCOMP_QUERY_WORKFLOW_API_TOKEN \
  --out-base "$tmp/query_workflow_out" \
  --job-id contract-query-workflow \
  --output-file "$tmp/query_workflow_client_status.json" \
  > /dev/null
if python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  query-submit \
  --base-url "http://127.0.0.1:$query_workflow_api_port" \
  --auth-token-env SECCOMP_QUERY_WORKFLOW_API_TOKEN \
  --request-file "$tmp/query_requests/cross_party_match.json" \
  --execute \
  --output-file "$tmp/query_workflow_client_execute_disabled_error.json" \
  > /dev/null; then
  echo "[ERROR] platform API client unexpectedly allowed query execute while disabled" >&2
  exit 1
fi
kill "$query_workflow_api_pid" 2>/dev/null || true
wait "$query_workflow_api_pid" 2>/dev/null || true
query_workflow_execute_api_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
python3 "$REPO_ROOT/scripts/serve_query_workflow_api.py" \
  --bind-host 127.0.0.1 \
  --port "$query_workflow_execute_api_port" \
  --auth-token-env SECCOMP_QUERY_WORKFLOW_API_TOKEN \
  --allow-execute \
  > "$tmp/query_workflow_execute_api.log" 2>&1 &
query_workflow_execute_api_pid=$!
python3 "$RUNTIME_SERVICE_HELPERS" wait-json-health \
  --url "http://127.0.0.1:$query_workflow_execute_api_port/healthz"
python3 "$REPO_ROOT/scripts/materialize_platform_api_smoke_reports.py" \
  --tmp-dir "$tmp" \
  --query-execute-port "$query_workflow_execute_api_port" \
  --query-execute-request-file "$tmp/query_requests/cross_party_match.json"
if python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  query-submit \
  --base-url "http://127.0.0.1:$query_workflow_execute_api_port" \
  --auth-token-env SECCOMP_QUERY_WORKFLOW_API_TOKEN \
  --request-file "$tmp/query_requests/cross_party_match_execute_run_failed.json" \
  --execute \
  --output-file "$tmp/query_workflow_client_execute_run_failed.json" \
  > /dev/null; then
  echo "[ERROR] platform API client unexpectedly returned success for run-failed query execute" >&2
  exit 1
fi
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  query-status \
  --base-url "http://127.0.0.1:$query_workflow_execute_api_port" \
  --auth-token-env SECCOMP_QUERY_WORKFLOW_API_TOKEN \
  --out-base "$tmp/query_workflow_execute_fail_out" \
  --job-id contract-query-workflow-execute-run-failed \
  --output-file "$tmp/query_workflow_client_execute_run_failed_status.json" \
  > /dev/null
kill "$query_workflow_execute_api_pid" 2>/dev/null || true
wait "$query_workflow_execute_api_pid" 2>/dev/null || true
metadata_api_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
export SECCOMP_METADATA_API_TOKEN="contract-metadata-api-token"
python3 "$REPO_ROOT/scripts/serve_metadata_api.py" \
  --db-path "$tmp/platform_metadata.db" \
  --bind-host 127.0.0.1 \
  --port "$metadata_api_port" \
  --auth-token-env SECCOMP_METADATA_API_TOKEN \
  --pid-file "$tmp/metadata_api.pid" \
  --ready-file "$tmp/metadata_api.ready" \
  > "$tmp/metadata_api.log" 2>&1 &
metadata_api_pid=$!
python3 "$RUNTIME_SERVICE_HELPERS" wait-json-health \
  --url "http://127.0.0.1:$metadata_api_port/healthz"
python3 "$REPO_ROOT/scripts/materialize_platform_api_smoke_reports.py" \
  --tmp-dir "$tmp" \
  --metadata-port "$metadata_api_port"
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  metadata-health \
  --base-url "http://127.0.0.1:$metadata_api_port" \
  --output-file "$tmp/metadata_api_client_health.json" \
  > /dev/null
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  metadata-job \
  --base-url "http://127.0.0.1:$metadata_api_port" \
  --auth-token-env SECCOMP_METADATA_API_TOKEN \
  --job-id contract-check \
  --output-file "$tmp/metadata_api_client_job.json" \
  > /dev/null
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  metadata-jobs \
  --base-url "http://127.0.0.1:$metadata_api_port" \
  --auth-token-env SECCOMP_METADATA_API_TOKEN \
  --param caller=auto_demo \
  --param stage=bridge \
  --param limit=5 \
  --output-file "$tmp/metadata_api_client_jobs.json" \
  > /dev/null
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  metadata-entity \
  --base-url "http://127.0.0.1:$metadata_api_port" \
  --auth-token-env SECCOMP_METADATA_API_TOKEN \
  --entity caller-permissions \
  --param caller=auto_demo \
  --param limit=20 \
  --output-file "$tmp/metadata_api_client_permissions.json" \
  > /dev/null
kill "$metadata_api_pid" 2>/dev/null || true
wait "$metadata_api_pid" 2>/dev/null || true
audit_query_api_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
export SECCOMP_AUDIT_QUERY_API_TOKEN="contract-audit-query-api-token"
python3 "$REPO_ROOT/scripts/serve_audit_query_api.py" \
  --out-base "$tmp" \
  --bind-host 127.0.0.1 \
  --port "$audit_query_api_port" \
  --auth-token-env SECCOMP_AUDIT_QUERY_API_TOKEN \
  --pid-file "$tmp/audit_query_api.pid" \
  --ready-file "$tmp/audit_query_api.ready" \
  > "$tmp/audit_query_api.log" 2>&1 &
audit_query_api_pid=$!
python3 "$RUNTIME_SERVICE_HELPERS" wait-json-health \
  --url "http://127.0.0.1:$audit_query_api_port/healthz"
python3 "$REPO_ROOT/scripts/materialize_platform_api_smoke_reports.py" \
  --tmp-dir "$tmp" \
  --audit-port "$audit_query_api_port"
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  audit-health \
  --base-url "http://127.0.0.1:$audit_query_api_port" \
  --output-file "$tmp/audit_query_client_health.json" \
  > /dev/null
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  audit-chain \
  --base-url "http://127.0.0.1:$audit_query_api_port" \
  --auth-token-env SECCOMP_AUDIT_QUERY_API_TOKEN \
  --output-file "$tmp/audit_query_client_audit_chain.json" \
  > /dev/null
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  audit-public-report \
  --base-url "http://127.0.0.1:$audit_query_api_port" \
  --auth-token-env SECCOMP_AUDIT_QUERY_API_TOKEN \
  --output-file "$tmp/audit_query_client_public_report.json" \
  > /dev/null
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  audit-observability \
  --base-url "http://127.0.0.1:$audit_query_api_port" \
  --auth-token-env SECCOMP_AUDIT_QUERY_API_TOKEN \
  --output-file "$tmp/audit_query_client_observability.json" \
  > /dev/null
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  audit-catalog-lineage \
  --base-url "http://127.0.0.1:$audit_query_api_port" \
  --auth-token-env SECCOMP_AUDIT_QUERY_API_TOKEN \
  --output-file "$tmp/audit_query_client_catalog_lineage.json" \
  > /dev/null
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  audit-catalog-lineage \
  --base-url "http://127.0.0.1:$audit_query_api_port" \
  --auth-token-env SECCOMP_AUDIT_QUERY_API_TOKEN \
  --include-paths \
  --output-file "$tmp/audit_query_client_catalog_lineage_with_paths.json" \
  > /dev/null
kill "$audit_query_api_pid" 2>/dev/null || true
wait "$audit_query_api_pid" 2>/dev/null || true
platform_health_api_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
export SECCOMP_PLATFORM_HEALTH_API_TOKEN="contract-platform-health-api-token"
python3 "$REPO_ROOT/scripts/serve_platform_health_api.py" \
  --bind-host 127.0.0.1 \
  --port "$platform_health_api_port" \
  --auth-token-env SECCOMP_PLATFORM_HEALTH_API_TOKEN \
  --pid-file "$tmp/platform_health_api.pid" \
  --ready-file "$tmp/platform_health_api.ready" \
  > "$tmp/platform_health_api.log" 2>&1 &
platform_health_api_pid=$!
python3 "$RUNTIME_SERVICE_HELPERS" wait-json-health \
  --url "http://127.0.0.1:$platform_health_api_port/healthz"
python3 "$REPO_ROOT/scripts/materialize_platform_api_smoke_reports.py" \
  --tmp-dir "$tmp" \
  --platform-health-port "$platform_health_api_port"
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  platform-api-health \
  --base-url "http://127.0.0.1:$platform_health_api_port" \
  --output-file "$tmp/platform_health_client_health.json" \
  > /dev/null
python3 "$REPO_ROOT/scripts/platform_api_client.py" \
  platform-health \
  --base-url "http://127.0.0.1:$platform_health_api_port" \
  --auth-token-env SECCOMP_PLATFORM_HEALTH_API_TOKEN \
  --param out_base="$tmp" \
  --param metadata_db="$tmp/platform_metadata.db" \
  --output-file "$tmp/platform_health_client_report.json" \
  > /dev/null
kill "$platform_health_api_pid" 2>/dev/null || true
wait "$platform_health_api_pid" 2>/dev/null || true
export SECCOMP_METADATA_COMMERCE_OPS_TOKEN="contract-identity-commerce-ops-token"
export SECCOMP_METADATA_MARKETING_ANALYST_TOKEN="contract-identity-marketing-analyst-token"
export SECCOMP_METADATA_AUDITOR_TOKEN="contract-identity-auditor-token"
export SECCOMP_METADATA_RECOVERY_OPS_TOKEN="contract-identity-recovery-ops-token"
export SECCOMP_METADATA_AUTO_DEMO_TOKEN="contract-identity-auto-demo-token"
python3 -c 'import json, sys; path=sys.argv[1]; payload={"schema":"metadata_registry_manifest/v1","caller_identities":[{"caller":"auto_demo","issuer":"local:contract","subject":"user:auto_demo","subject_type":"human_user","display_name":"Contract Auto Demo","platform_roles":["query_submitter","privacy_operator"],"enabled":True,"metadata":{"entity_type":"human_user"},"source":"contract_identity_fixture"}]}; open(path, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")' "$tmp/contract_identity_registry_manifest.json"
python3 -c 'import json, sys; path=sys.argv[1]; payload={"schema":"api_identity_token_map/v1","tokens":[{"token_env":"SECCOMP_METADATA_AUTO_DEMO_TOKEN","issuer":"local:contract","subject":"user:auto_demo","description":"Contract auto demo local bearer token"}]}; open(path, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")' "$tmp/contract_identity_tokens.json"
python3 -c 'import json, sys; path=sys.argv[1]; payload={"schema":"metadata_registry_manifest/v1","caller_identities":[{"caller":"recovery_ops_demo","issuer":"https://keycloak.example.com/realms/commerce","subject":"service-account:orders-recovery-operator","subject_type":"service_account","display_name":"Recovery Ops Demo SA","platform_roles":["service_operator"],"enabled":True,"metadata":{"entity_type":"service_account"},"source":"jwt_contract_fixture"}]}; open(path, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")' "$tmp/contract_jwt_identity_registry_manifest.json"
python3 "$REPO_ROOT/scripts/manage_metadata_db.py" \
  apply-registry \
  --db-path "$tmp/platform_metadata.db" \
  --manifest "$tmp/contract_identity_registry_manifest.json" \
  > /dev/null
python3 "$REPO_ROOT/scripts/manage_metadata_db.py" \
  apply-registry \
  --db-path "$tmp/platform_registry.db" \
  --manifest "$tmp/contract_jwt_identity_registry_manifest.json" \
  > /dev/null
python3 "$REPO_ROOT/scripts/resolve_api_identity.py" \
  --db-path "$tmp/platform_registry.db" \
  --identity-token-config "$REPO_ROOT/config/api_identity_tokens.example.json" \
  --bearer-token-env SECCOMP_METADATA_COMMERCE_OPS_TOKEN \
  > "$tmp/api_identity_resolution_bearer.json"
python3 "$REPO_ROOT/scripts/resolve_api_identity.py" \
  --db-path "$tmp/platform_registry.db" \
  --issuer keycloak:commerce \
  --subject user:marketing_analyst \
  > "$tmp/api_identity_resolution_subject.json"
identity_metadata_api_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
python3 "$REPO_ROOT/scripts/serve_metadata_api.py" \
  --db-path "$tmp/platform_registry.db" \
  --bind-host 127.0.0.1 \
  --port "$identity_metadata_api_port" \
  --identity-token-config "$REPO_ROOT/config/api_identity_tokens.example.json" \
  > "$tmp/identity_metadata_api.log" 2>&1 &
identity_metadata_api_pid=$!
python3 "$RUNTIME_SERVICE_HELPERS" wait-json-health \
  --url "http://127.0.0.1:$identity_metadata_api_port/healthz"
identity_query_api_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
python3 "$REPO_ROOT/scripts/serve_query_workflow_api.py" \
  --bind-host 127.0.0.1 \
  --port "$identity_query_api_port" \
  --metadata-db-path "$tmp/platform_registry.db" \
  --identity-token-config "$REPO_ROOT/config/api_identity_tokens.example.json" \
  --allow-execute \
  > "$tmp/identity_query_workflow_api.log" 2>&1 &
identity_query_api_pid=$!
python3 "$RUNTIME_SERVICE_HELPERS" wait-json-health \
  --url "http://127.0.0.1:$identity_query_api_port/healthz"
identity_audit_api_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
python3 "$REPO_ROOT/scripts/serve_audit_query_api.py" \
  --out-base "$tmp" \
  --bind-host 127.0.0.1 \
  --port "$identity_audit_api_port" \
  --metadata-db-path "$tmp/platform_metadata.db" \
  --identity-token-config "$tmp/contract_identity_tokens.json" \
  > "$tmp/identity_audit_query_api.log" 2>&1 &
identity_audit_api_pid=$!
python3 "$RUNTIME_SERVICE_HELPERS" wait-json-health \
  --url "http://127.0.0.1:$identity_audit_api_port/healthz"
identity_platform_health_api_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
python3 "$REPO_ROOT/scripts/serve_platform_health_api.py" \
  --bind-host 127.0.0.1 \
  --port "$identity_platform_health_api_port" \
  --metadata-db-path "$tmp/platform_registry.db" \
  --identity-token-config "$REPO_ROOT/config/api_identity_tokens.example.json" \
  > "$tmp/identity_platform_health_api.log" 2>&1 &
identity_platform_health_api_pid=$!
python3 "$RUNTIME_SERVICE_HELPERS" wait-json-health \
  --url "http://127.0.0.1:$identity_platform_health_api_port/healthz"
jwks_identity_metadata_api_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
python3 "$REPO_ROOT/scripts/serve_metadata_api.py" \
  --db-path "$tmp/platform_registry.db" \
  --bind-host 127.0.0.1 \
  --port "$jwks_identity_metadata_api_port" \
  --identity-token-config "$tmp/api_identity_tokens_jwks.json" \
  > "$tmp/jwks_identity_metadata_api.log" 2>&1 &
jwks_identity_metadata_api_pid=$!
python3 "$RUNTIME_SERVICE_HELPERS" wait-json-health \
  --url "http://127.0.0.1:$jwks_identity_metadata_api_port/healthz"
python3 "$REPO_ROOT/scripts/materialize_platform_api_smoke_reports.py" \
  --tmp-dir "$tmp" \
  --identity-metadata-port "$identity_metadata_api_port" \
  --identity-query-port "$identity_query_api_port" \
  --identity-query-request-file "$tmp/query_requests/ecommerce_cross_party_match.json" \
  --identity-audit-port "$identity_audit_api_port" \
  --identity-platform-health-port "$identity_platform_health_api_port"
SECCOMP_METADATA_JWKS_TOKEN="$(cat "$tmp/oidc_test_rs256.jwt")" python3 - <<'PYEOF' "$jwks_identity_metadata_api_port" "$tmp/metadata_api_identity_jwks.json"
import json
import os
import sys
import urllib.request

port, out_path = sys.argv[1], sys.argv[2]
token = os.environ["SECCOMP_METADATA_JWKS_TOKEN"]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/identity")
request.add_header("Authorization", f"Bearer {token}")
with opener.open(request, timeout=2) as response:
    payload = json.loads(response.read().decode("utf-8"))
with open(out_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2)
PYEOF
kill "$identity_metadata_api_pid" 2>/dev/null || true
wait "$identity_metadata_api_pid" 2>/dev/null || true
kill "$identity_query_api_pid" 2>/dev/null || true
wait "$identity_query_api_pid" 2>/dev/null || true
kill "$identity_audit_api_pid" 2>/dev/null || true
wait "$identity_audit_api_pid" 2>/dev/null || true
kill "$identity_platform_health_api_pid" 2>/dev/null || true
wait "$identity_platform_health_api_pid" 2>/dev/null || true
kill "$jwks_identity_metadata_api_pid" 2>/dev/null || true
wait "$jwks_identity_metadata_api_pid" 2>/dev/null || true
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_request.schema.json" \
  --json "$tmp/query_requests/cross_party_match.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_request.schema.json" \
  --json "$tmp/query_requests/ecommerce_cross_party_match.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_request.schema.json" \
  --json "$tmp/query_requests/cross_party_match_execute_run_failed.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_submission.schema.json" \
  --json "$tmp/query_workflow_stdout.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_submission.schema.json" \
  --json "$tmp/query_workflow_manifest.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_submission.schema.json" \
  --json "$tmp/query_workflow_out/query_workflow/submission_manifest.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_receipt.schema.json" \
  --jsonl "$tmp/query_workflow_out/query_workflow/execution_receipts.jsonl"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_status.schema.json" \
  --json "$tmp/query_workflow_out/query_workflow/status.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_submission.schema.json" \
  --json "$tmp/query_workflow_out_keep/query_workflow/submission_manifest.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_receipt.schema.json" \
  --jsonl "$tmp/query_workflow_out_keep/query_workflow/execution_receipts.jsonl"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_status.schema.json" \
  --json "$tmp/query_workflow_out_keep/query_workflow/status.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_submission.schema.json" \
  --json "$tmp/query_workflow_execute_fail_out/query_workflow/submission_manifest.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_receipt.schema.json" \
  --jsonl "$tmp/query_workflow_execute_fail_out/query_workflow/execution_receipts.jsonl"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_status.schema.json" \
  --json "$tmp/query_workflow_execute_fail_out/query_workflow/status.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_api_health.schema.json" \
  --json "$tmp/query_workflow_api_health.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_api_health.schema.json" \
  --json "$tmp/query_workflow_client_health.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_api_response.schema.json" \
  --json "$tmp/query_workflow_api_dry_run.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_api_response.schema.json" \
  --json "$tmp/query_workflow_client_dry_run.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_status_api_response.schema.json" \
  --json "$tmp/query_workflow_api_status.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_status_api_response.schema.json" \
  --json "$tmp/query_workflow_client_status.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_api_response.schema.json" \
  --json "$tmp/query_workflow_api_execute_run_failed.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_status_api_response.schema.json" \
  --json "$tmp/query_workflow_api_execute_run_failed_status.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_api_response.schema.json" \
  --json "$tmp/query_workflow_client_execute_run_failed.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_status_api_response.schema.json" \
  --json "$tmp/query_workflow_client_execute_run_failed_status.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_api_error.schema.json" \
  --json "$tmp/query_workflow_client_execute_disabled_error.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_api_error.schema.json" \
  --json "$tmp/query_workflow_api_execute_validation_error.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_api_error.schema.json" \
  --json "$tmp/query_workflow_api_unauth_error.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_api_error.schema.json" \
  --json "$tmp/query_workflow_api_execute_disabled_error.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_health.schema.json" \
  --json "$tmp/metadata_api_health.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_health.schema.json" \
  --json "$tmp/metadata_api_client_health.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_response.schema.json" \
  --json "$tmp/metadata_api_job.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_response.schema.json" \
  --json "$tmp/metadata_api_jobs.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_response.schema.json" \
  --json "$tmp/metadata_api_client_jobs.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_response.schema.json" \
  --json "$tmp/metadata_api_policies.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_response.schema.json" \
  --json "$tmp/metadata_api_permissions.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_response.schema.json" \
  --json "$tmp/metadata_api_permissions_page.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_response.schema.json" \
  --json "$tmp/metadata_api_client_job.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_response.schema.json" \
  --json "$tmp/metadata_api_client_permissions.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_error.schema.json" \
  --json "$tmp/metadata_api_unauth_error.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/api_identity_resolution.schema.json" \
  --json "$tmp/api_identity_resolution_bearer.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/api_identity_resolution.schema.json" \
  --json "$tmp/api_identity_resolution_subject.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/api_identity_token_map.schema.json" \
  --json "$tmp/contract_identity_tokens.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_registry_manifest.schema.json" \
  --json "$tmp/contract_identity_registry_manifest.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_response.schema.json" \
  --json "$tmp/metadata_api_identity.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_response.schema.json" \
  --json "$tmp/metadata_api_identity_jwks.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_error.schema.json" \
  --json "$tmp/metadata_api_identity_forbidden_policies.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_api_response.schema.json" \
  --json "$tmp/query_workflow_identity_dry_run.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_status_api_response.schema.json" \
  --json "$tmp/query_workflow_identity_status.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_api_error.schema.json" \
  --json "$tmp/query_workflow_identity_execute_forbidden.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); identity=payload["result"]["identity"]; assert identity["caller"] == "recovery_ops_demo", identity; assert identity["issuer"] == "https://keycloak.example.com/realms/commerce", identity; assert identity["issuer_registered"] is True, identity; assert "service_operator" in identity["platform_roles"], identity' "$tmp/metadata_api_identity_jwks.json"

# A5-A6 authority governance + remote authority smoke rollup.
python3 "$REPO_ROOT/scripts/sync_openfga_tuples.py" \
  --tuple-store "$tmp/openfga_tuples.db" \
  apply \
  --policy-config "$REPO_ROOT/sse/config/ecommerce_access_policy.example.json" \
  --tuple-store "$tmp/openfga_tuples.db" \
  --output "$tmp/openfga_sync_apply.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/openfga_sync_report.schema.json" \
  --json "$tmp/openfga_sync_apply.json"
python3 "$REPO_ROOT/scripts/check_openfga_authz.py" \
  --tuple-store "$tmp/openfga_tuples.db" \
  --user user:commerce_ops_demo \
  --relation query_submitter \
  --object dataset:orders_analytics \
  --output "$tmp/openfga_check_allowed.json" \
  --assert-allowed
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/openfga_check_result.schema.json" \
  --json "$tmp/openfga_check_allowed.json"
export A5_KMS_ENV_SECRET="contract-kms-reachability-secret"
python3 "$REPO_ROOT/scripts/check_kms_reachability.py" \
  --keyring "$REPO_ROOT/config/keyring.example.json" \
  --vault-kv-file "$REPO_ROOT/config/vault_kv_backend.example.json" \
  --env-var A5_KMS_ENV_SECRET \
  --output "$tmp/kms_reachability_authority.json" \
  --assert-ok
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/kms_reachability_report.schema.json" \
  --json "$tmp/kms_reachability_authority.json"
export A5_SERVICE_TOKEN_SIGNING_KEY="contract-service-token-signing-key"
python3 "$REPO_ROOT/scripts/manage_service_tokens.py" \
  --token-store "$tmp/service_tokens.db" \
  issue \
  --token-store "$tmp/service_tokens.db" \
  --service-id orders-recovery \
  --signing-key-env A5_SERVICE_TOKEN_SIGNING_KEY \
  --scope record_recovery \
  --issuer local-contract \
  --output "$tmp/service_token_issue.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/service_token_report.schema.json" \
  --json "$tmp/service_token_issue.json"
service_token_value="$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field --json-file "$tmp/service_token_issue.json" --field token)"
python3 "$REPO_ROOT/scripts/manage_service_tokens.py" \
  --token-store "$tmp/service_tokens.db" \
  verify \
  --token-store "$tmp/service_tokens.db" \
  --token "$service_token_value" \
  --signing-key-env A5_SERVICE_TOKEN_SIGNING_KEY \
  --output "$tmp/service_token_verify.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/service_token_report.schema.json" \
  --json "$tmp/service_token_verify.json"
python3 "$REPO_ROOT/scripts/check_authority_governance.py" \
  --policy-drift "$tmp/policy_drift_clean.json" \
  --key-drift "$tmp/key_backend_drift_clean.json" \
  --identity-resolution "$tmp/api_identity_resolution_bearer.json" \
  --identity-resolution "$tmp/api_identity_resolution_subject.json" \
  --openfga-check "$tmp/openfga_check_allowed.json" \
  --kms-reachability "$tmp/kms_reachability_authority.json" \
  --service-token-report "$tmp/service_token_issue.json" \
  --service-token-report "$tmp/service_token_verify.json" \
  --issuer-rotation "$tmp/issuer_rotation_dry.json" \
  --output "$tmp/authority_governance_report.json" \
  --assert-ok
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/authority_governance_report.schema.json" \
  --json "$tmp/authority_governance_report.json"
test "$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field --json-file "$tmp/platform_metadata_caller_permissions_page.json" --field pagination.limit)" = "2"
test "$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field --json-file "$tmp/platform_metadata_caller_permissions_page.json" --field pagination.offset)" = "2"
test "$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field --json-file "$tmp/platform_metadata_caller_permissions_page.json" --field pagination.returned_count)" = "2"
test "$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field --json-file "$tmp/platform_metadata_caller_permissions_page.json" --field pagination.has_more)" = "True"
test "$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field --json-file "$tmp/platform_metadata_caller_permissions_page.json" --field permission_summary.caller_count)" = "1"
test "$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field --json-file "$tmp/platform_metadata_stage.json" --field pagination.limit)" = "5"
test "$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field --json-file "$tmp/platform_metadata_stage.json" --field pagination.offset)" = "0"
test "$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field --json-file "$tmp/platform_metadata_stage.json" --field pagination.total_matching_count)" = "1"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_query_api_health.schema.json" \
  --json "$tmp/audit_query_api_health.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_query_api_health.schema.json" \
  --json "$tmp/audit_query_client_health.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_query_api_response.schema.json" \
  --json "$tmp/audit_query_api_public_report.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_query_api_response.schema.json" \
  --json "$tmp/audit_query_api_audit_chain.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_query_api_response.schema.json" \
  --json "$tmp/audit_query_api_observability.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_query_api_response.schema.json" \
  --json "$tmp/audit_query_api_catalog_lineage.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_query_api_response.schema.json" \
  --json "$tmp/audit_query_client_audit_chain.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_query_api_response.schema.json" \
  --json "$tmp/audit_query_client_public_report.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_query_api_response.schema.json" \
  --json "$tmp/audit_query_client_observability.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_query_api_response.schema.json" \
  --json "$tmp/audit_query_client_catalog_lineage.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_query_api_response.schema.json" \
  --json "$tmp/audit_query_client_catalog_lineage_with_paths.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_query_api_error.schema.json" \
  --json "$tmp/audit_query_api_unauth_error.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_query_api_error.schema.json" \
  --json "$tmp/audit_query_api_bad_query_error.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_query_api_response.schema.json" \
  --json "$tmp/audit_query_api_identity_public_report.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/audit_query_api_error.schema.json" \
  --json "$tmp/audit_query_api_identity_include_paths_forbidden.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/platform_health_api_health.schema.json" \
  --json "$tmp/platform_health_api_health.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/platform_health_api_health.schema.json" \
  --json "$tmp/platform_health_client_health.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/platform_health_api_response.schema.json" \
  --json "$tmp/platform_health_api_report.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/platform_health_api_response.schema.json" \
  --json "$tmp/platform_health_client_report.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/platform_health_api_error.schema.json" \
  --json "$tmp/platform_health_api_unauth_error.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/platform_health_api_error.schema.json" \
  --json "$tmp/platform_health_api_identity_forbidden.json"

python3 "$REPO_ROOT/scripts/check_platform_health.py" \
  --out-base "$tmp" \
  --metadata-db "$tmp/platform_metadata.db" \
  > "$tmp/platform_health.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/platform_health.schema.json" \
  --json "$tmp/platform_health.json"
python3 "$REPO_ROOT/scripts/build_observability_dashboard.py" \
  --observability "$tmp/pipeline_observability.json" \
  --platform-health "$tmp/platform_health.json" \
  --out "$tmp/observability_dashboard.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/observability_dashboard.schema.json" \
  --json "$tmp/observability_dashboard.json"
python3 -c 'import json, sys; p=json.load(open(sys.argv[1], "r", encoding="utf-8")); panels=p["panels"]; assert panels["stage_timeline"]["type"] == "stage_timeline", p; assert panels["stage_summary"]["type"] == "stage_summary", p; assert panels["stage_duration"]["type"] == "stage_duration", p; assert panels["release_outcomes"]["type"] == "release_outcomes", p; assert panels["failure_summary"]["type"] == "failure_summary", p; hs=p["health_summary"]; assert hs is not None, p; assert hs["status"] in {"ok","warn","error"}, hs; assert isinstance(hs["check_count"], int), hs' "$tmp/observability_dashboard.json"
python3 "$REPO_ROOT/scripts/build_observability_dashboard.py" \
  --observability "$tmp/pipeline_observability.json" \
  --out "$tmp/observability_dashboard_no_health.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/observability_dashboard.schema.json" \
  --json "$tmp/observability_dashboard_no_health.json"
python3 -c 'import json, sys; p=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert p["health_summary"] is None, p' "$tmp/observability_dashboard_no_health.json"
# B4: alert check — with and without health
python3 "$REPO_ROOT/scripts/check_observability_alerts.py" \
  --dashboard "$tmp/observability_dashboard.json" \
  --platform-health "$tmp/platform_health.json" \
  --out "$tmp/observability_alert_report.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/observability_alert_report.schema.json" \
  --json "$tmp/observability_alert_report.json"
python3 -c 'import json, sys; p=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert p["schema"] == "observability_alert_report/v1", p; assert p["overall_status"] in {"ok","warn","error"}, p; assert p["alert_count"] >= 4, p; assert isinstance(p["firing_count"], int), p; assert any(a["alert_id"] == "release_failure_after_success" and a["firing"] for a in p["alerts"]), p' "$tmp/observability_alert_report.json"
python3 "$REPO_ROOT/scripts/check_observability_alerts.py" \
  --dashboard "$tmp/observability_dashboard_no_health.json" \
  --out "$tmp/observability_alert_report_no_health.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/observability_alert_report.schema.json" \
  --json "$tmp/observability_alert_report_no_health.json"
# B5: status list scan
python3 "$REPO_ROOT/scripts/list_query_workflow_status.py" \
  --search-dir "$tmp" \
  --limit 20 \
  --out "$tmp/workflow_status_list.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_status_list.schema.json" \
  --json "$tmp/workflow_status_list.json"
python3 -c 'import json, sys; p=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert p["schema"] == "query_workflow_status_list/v1", p; assert p["total_found"] >= 2, p; assert len(p["statuses"]) >= 2, p' "$tmp/workflow_status_list.json"
python3 "$REPO_ROOT/scripts/list_query_workflow_status.py" \
  --search-dir "$tmp" \
  --state failed \
  --limit 20 \
  --out "$tmp/workflow_status_list_failed.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_status_list.schema.json" \
  --json "$tmp/workflow_status_list_failed.json"
python3 -c 'import json, sys; p=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert p["filter_state"] == "failed", p; assert all((s.get("state") == "failed") for s in p["statuses"]), p' "$tmp/workflow_status_list_failed.json"
# B6: retry eligibility — failed run
python3 "$REPO_ROOT/scripts/check_workflow_retry_eligibility.py" \
  --status-file "$tmp/query_workflow_execute_fail_out/query_workflow/status.json" \
  --receipts-file "$tmp/query_workflow_execute_fail_out/query_workflow/execution_receipts.jsonl" \
  --out "$tmp/retry_eligibility_run_failed.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/workflow_retry_eligibility.schema.json" \
  --json "$tmp/retry_eligibility_run_failed.json"
python3 -c 'import json, sys; p=json.load(open(sys.argv[1], "r", encoding="utf-8")); assert p["schema"] == "workflow_retry_eligibility/v1", p; assert p["retryable"] is False, p; assert p["resubmit_required"] is True, p; assert p["recommended_action"] == "resubmit", p' "$tmp/retry_eligibility_run_failed.json"
# B6: retry eligibility — completed dry-run (should be "none" action)
python3 "$REPO_ROOT/scripts/check_workflow_retry_eligibility.py" \
  --status-file "$tmp/query_workflow_out/query_workflow/status.json" \
  --out "$tmp/retry_eligibility_dry_run.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/workflow_retry_eligibility.schema.json" \
  --json "$tmp/retry_eligibility_dry_run.json"
# B7: triage report — full run via out-base
python3 "$REPO_ROOT/scripts/run_operator_triage.py" \
  --observability "$tmp/pipeline_observability.json" \
  --platform-health "$tmp/platform_health.json" \
  --dashboard "$tmp/observability_dashboard.json" \
  --out "$tmp/operator_triage.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/operator_triage_report.schema.json" \
  --json "$tmp/operator_triage.json"
python3 -c 'import json, sys; p=json.load(open(sys.argv[1], "r", encoding="utf-8")); secs=p["sections"]; assert secs["dashboard"]["available"] is True, secs["dashboard"]; assert secs["alerts"]["available"] is True, secs["alerts"]; assert secs["platform_health"]["available"] is True, secs["platform_health"]; assert p["overall_status"] in {"ok","warn","error"}, p' "$tmp/operator_triage.json"
python3 "$REPO_ROOT/scripts/check_platform_api_smoke_reports.py" \
  --tmp-dir "$tmp"

python3 "$REPO_ROOT/scripts/scan_repo_hygiene.py" \
  --max-findings 50 \
  > "$tmp/repo_hygiene_scan.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/repo_hygiene_scan.schema.json" \
  --json "$tmp/repo_hygiene_scan.json"

python3 "$REPO_ROOT/scripts/check_malformed_input_gate.py" \
  --out "$tmp/malformed_input_gate.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/malformed_input_gate.schema.json" \
  --json "$tmp/malformed_input_gate.json"

python3 "$REPO_ROOT/scripts/check_pre_release_gate.py" \
  --out "$tmp/pre_release_gate.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/pre_release_gate.schema.json" \
  --json "$tmp/pre_release_gate.json"

python3 "$REPO_ROOT/scripts/check_operator_readiness.py" \
  --out "$tmp/operator_readiness.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/operator_readiness.schema.json" \
  --json "$tmp/operator_readiness.json"

python3 "$REPO_ROOT/scripts/check_contract_smoke_reports.py" \
  --tmp-dir "$tmp"

echo "[ok] JSON contract checks passed"
