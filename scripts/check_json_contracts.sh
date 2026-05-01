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
  "$REPO_ROOT/schemas/record_recovery_service_policy.schema.json"
  "$REPO_ROOT/schemas/record_recovery_service_health.schema.json"
  "$REPO_ROOT/schemas/record_recovery_service_log.schema.json"
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
  "$REPO_ROOT/schemas/audit_bundle_verification.schema.json"
  "$REPO_ROOT/schemas/key_manifest.schema.json"
  "$REPO_ROOT/schemas/keyring.schema.json"
  "$REPO_ROOT/schemas/external_kms_config.schema.json"
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
  "$REPO_ROOT/schemas/metadata_db_status.schema.json"
  "$REPO_ROOT/schemas/metadata_db_backup.schema.json"
  "$REPO_ROOT/schemas/metadata_db_export.schema.json"
  "$REPO_ROOT/schemas/authz_tuple_export.schema.json"
  "$REPO_ROOT/schemas/audit_query_api_health.schema.json"
  "$REPO_ROOT/schemas/audit_query_api_response.schema.json"
  "$REPO_ROOT/schemas/audit_query_api_error.schema.json"
  "$REPO_ROOT/schemas/platform_health_api_health.schema.json"
  "$REPO_ROOT/schemas/platform_health_api_response.schema.json"
  "$REPO_ROOT/schemas/platform_health_api_error.schema.json"
  "$REPO_ROOT/schemas/query_workflow_request.schema.json"
  "$REPO_ROOT/schemas/query_workflow_submission.schema.json"
  "$REPO_ROOT/schemas/query_workflow_api_health.schema.json"
  "$REPO_ROOT/schemas/query_workflow_api_response.schema.json"
  "$REPO_ROOT/schemas/query_workflow_api_error.schema.json"
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
  --schema "$REPO_ROOT/schemas/external_kms_config.schema.json" \
  --json "$REPO_ROOT/config/external_kms.example.json"
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
  --schema "$REPO_ROOT/schemas/query_workflow_request.schema.json" \
  --json "$REPO_ROOT/docs/examples/query_request.json"

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

external_kms_port="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
python3 "$REPO_ROOT/scripts/build_runtime_contract_smoke_configs.py" \
  external-kms \
  --out-config "$tmp/external_kms.json" \
  --state-path "$tmp/keyring_external.json" \
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
  --lifecycle-audit-log "$tmp/external_kms_lifecycle_audit.jsonl" \
  --pid-file "$tmp/external_kms.pid" \
  --ready-file "$tmp/external_kms.ready" \
  >"$tmp/external_kms.log" 2>&1 &
external_kms_pid=$!
cleanup() {
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
  --audit-log "$tmp/external_key_access_audit.jsonl" >/dev/null
python3 "$REPO_ROOT/scripts/manage_external_kms.py" rotate \
  --config "$tmp/external_kms.json" \
  --key-name bridge-token \
  --purpose bridge_token \
  --new-version ext-v2 \
  --secret-env BRIDGE_TOKEN_SECRET \
  --caller auto_demo \
  --activate >/dev/null
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
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/keyring.schema.json" --json "$tmp/keyring.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/key_lifecycle_audit.schema.json" --jsonl "$tmp/key_lifecycle_audit.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/keyring.schema.json" --json "$tmp/keyring_external.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/key_lifecycle_audit.schema.json" --jsonl "$tmp/external_kms_lifecycle_audit.jsonl"
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
[[ ! -e "$tmp/record_recovery_service_http.pid" ]] || { echo "[ERROR] HTTP record recovery pid file still exists after stop" >&2; exit 1; }
[[ ! -e "$tmp/record_recovery_service_http.ready" ]] || { echo "[ERROR] HTTP record recovery ready file still exists after stop" >&2; exit 1; }

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
python3 "$REPO_ROOT/scripts/export_authz_tuples.py" \
  --db-path "$tmp/platform_metadata.db" \
  --output "$tmp/platform_metadata_authz_tuples.json" \
  > /dev/null
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/authz_tuple_export.schema.json" \
  --json "$tmp/platform_metadata_authz_tuples.json"
python3 -c 'import json, sys; payload=json.load(open(sys.argv[1], "r", encoding="utf-8")); source=payload["source"]; summary=payload["summary"]; assert source["kind"] == "metadata_db", source; assert summary["subject_count"] == 3, summary; assert summary["active_subject_count"] == 2, summary; assert any(item["object"] == "platform_role:privacy_operator" and item["user"] == "user:auto_demo" for item in payload["tuples"]), payload["tuples"]; assert any(item["object"] == "privacy_service:contract-recovery-service" and item["relation"] == "can_recover" for item in payload["tuples"]), payload["tuples"]' "$tmp/platform_metadata_authz_tuples.json"
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
mkdir -p "$tmp/query_requests"
python3 "$REPO_ROOT/scripts/build_query_workflow_request_fixtures.py" \
  --default-out "$tmp/query_requests/cross_party_match.json" \
  --keep-out "$tmp/query_requests/cross_party_match_keep.json"
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
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_request.schema.json" \
  --json "$tmp/query_requests/cross_party_match.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_submission.schema.json" \
  --json "$tmp/query_workflow_stdout.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/query_workflow_submission.schema.json" \
  --json "$tmp/query_workflow_manifest.json"
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
  --schema "$REPO_ROOT/schemas/query_workflow_api_error.schema.json" \
  --json "$tmp/query_workflow_client_execute_disabled_error.json"
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
  --json "$tmp/metadata_api_client_job.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_response.schema.json" \
  --json "$tmp/metadata_api_client_permissions.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/metadata_api_error.schema.json" \
  --json "$tmp/metadata_api_unauth_error.json"
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

python3 "$REPO_ROOT/scripts/check_platform_health.py" \
  --out-base "$tmp" \
  --metadata-db "$tmp/platform_metadata.db" \
  > "$tmp/platform_health.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/platform_health.schema.json" \
  --json "$tmp/platform_health.json"
python3 "$REPO_ROOT/scripts/check_platform_api_smoke_reports.py" \
  --tmp-dir "$tmp"

python3 "$REPO_ROOT/scripts/scan_repo_hygiene.py" \
  --max-findings 50 \
  > "$tmp/repo_hygiene_scan.json"
python3 "$REPO_ROOT/scripts/check_contract_smoke_reports.py" \
  --tmp-dir "$tmp"

echo "[ok] JSON contract checks passed"
