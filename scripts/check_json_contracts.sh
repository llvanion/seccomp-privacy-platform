#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

VALIDATOR="$REPO_ROOT/scripts/validate_json_contract.py"
TABULAR_VALIDATOR="$REPO_ROOT/scripts/validate_tabular_contract.py"

SCHEMAS=(
  "$REPO_ROOT/schemas/sse_export_policy.schema.json"
  "$REPO_ROOT/schemas/sse_bridge_export_audit.schema.json"
  "$REPO_ROOT/schemas/sse_record_recovery_service_audit.schema.json"
  "$REPO_ROOT/schemas/record_recovery_service_policy.schema.json"
  "$REPO_ROOT/schemas/sse_encrypted_record_store.schema.json"
  "$REPO_ROOT/schemas/bridge_job_meta.schema.json"
  "$REPO_ROOT/schemas/bridge_audit.schema.json"
  "$REPO_ROOT/schemas/public_report.schema.json"
  "$REPO_ROOT/schemas/policy_audit.schema.json"
  "$REPO_ROOT/schemas/audit_chain.schema.json"
  "$REPO_ROOT/schemas/key_manifest.schema.json"
  "$REPO_ROOT/schemas/key_access_audit.schema.json"
  "$REPO_ROOT/schemas/audit_seal.schema.json"
)

for schema in "${SCHEMAS[@]}"; do
  python3 -m json.tool "$schema" >/dev/null
done

python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/sse_export_policy.schema.json" \
  --json "$REPO_ROOT/sse/config/export_policy.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/key_manifest.schema.json" \
  --json "$REPO_ROOT/config/key_manifest.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_service_policy.schema.json" \
  --json "$REPO_ROOT/config/record_recovery_service_policy.example.json"

tmp="$(mktemp -d /tmp/seccomp_contracts.XXXXXX)"
cleanup() {
  rm -rf "$tmp"
}
trap cleanup EXIT

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

printf '%s\n' \
  '{"schema":"sse_bridge_export_audit/v1","ts_utc":"2026-04-10T00:00:00Z","event":"sse_bridge_export","caller":"auto_demo","correlation_id":"contract-check","job_id":"contract-check","role":"server","source_file":null,"source_sha256":null,"output_file":"/tmp/server.fifo","output_file_type":"fifo","output_sha256":"abc","source_format":"jsonl","out_format":"csv","join_key_field":"email","value_field":null,"filters":[],"input_rows":1,"output_rows":1,"policy_config":null,"candidate_source":"local_filter","record_id_field":null,"candidate_count":null,"record_store_file":null,"record_store_sha256":null,"decision":"allow","reason_code":"ok","reason":"ok"}' \
  > "$tmp/sse_exports/export_audit.jsonl"
printf '%s\n' \
  '{"schema":"sse_bridge_export_audit/v1","ts_utc":"2026-04-10T00:00:01Z","event":"sse_bridge_export","caller":"auto_demo","correlation_id":"contract-check","job_id":"contract-check","role":"client","source_file":null,"source_sha256":null,"output_file":"/tmp/client.csv","output_file_type":"file","output_sha256":"def","source_format":"jsonl","out_format":"csv","join_key_field":"email","value_field":"amount","filters":[],"input_rows":1,"output_rows":1,"policy_config":null,"candidate_source":"sse_query","record_id_field":"email_hex","candidate_count":1,"record_store_file":"/tmp/client_store.enc.jsonl","record_store_sha256":"123","record_recovery_boundary":"service_socket","decision":"allow","reason_code":"ok","reason":"ok"}' \
  >> "$tmp/sse_exports/export_audit.jsonl"

printf '%s\n' \
  '{"schema":"bridge_audit/v1","ts_unix_ms":1,"event":"bridge_prepare_job","job_id":"contract-check","correlation_id":"contract-check","server_input_file_type":"fifo","server_input_sha256":null,"client_input_file_type":"fifo","client_input_sha256":null,"decision":"allow","reason_code":"ok","token_secret_source":{"kind":"cli"}}' \
  > "$tmp/bridge_job/bridge_audit.jsonl"

printf '%s\n' \
  '{"schema":"sse_record_recovery_service_audit/v1","ts_utc":"2026-04-10T00:00:00Z","event":"record_recovery_service_request","caller":"auto_demo","correlation_id":"contract-check","job_id":"contract-check","role":"client","auth_mode":"env_token","socket_path":"/tmp/record_recovery.sock","authz_policy_config":"/tmp/record_recovery_policy.json","record_store_file":"/tmp/client_store.enc.jsonl","record_store_sha256":"abc","output_file":"/tmp/client.csv","output_file_type":"file","output_sha256":"def","join_key_field":"email","value_field":"amount","candidate_count":1,"filters":[{"field":"campaign","value_sha256":"123"}],"input_rows":1,"output_rows":1,"decision":"allow","reason_code":"ok","reason":"ok"}' \
  > "$tmp/sse_exports/record_recovery_service_audit.jsonl"

printf '%s\n' \
  '{"schema":"bridge_job_meta/v1","job_id":"contract-check","job_type":"bridge_prepared_csv","generator":"bridge-rust-v0","input_sizes":{"exposure_n":1,"purchase_n":1},"bridge":{"token_scheme":"bridge-hmac-sha256-v1","token_scope":"contract-check","token_key_version":"1","normalize_version":"1","dedup_policy":"one","server":{},"client":{}},"inputs":{},"counts":{}}' \
  > "$tmp/bridge_job/job_meta.json"

printf '%s\n' \
  '{"job_id":"contract-check","correlation_id":"contract-check","intersection_size":1,"intersection_sum":5}' \
  > "$tmp/a_psi_run/attribution_result.json"

printf '%s\n' \
  '{"schema":"public_report/v2","generated_at_utc":"2026-04-10T00:00:00Z","policy_version":"w2-hmac-v1","job_id":"contract-check","correlation_id":"contract-check","caller":"auto_demo","released":false,"reason":"below k","reason_code":"below_k","window":{"start":null,"end":null},"k_threshold":20}' \
  > "$tmp/a_psi_run/public_report.json"

printf '%s\n' \
  '{"ts_utc":"2026-04-10T00:00:00Z","event":"policy_release","policy_version":"w2-hmac-v1","job_id":"contract-check","correlation_id":"contract-check","caller":"auto_demo","window":{"start":null,"end":null},"bucket":null,"value_mode":null,"bridge":null,"input_sizes":{},"input_file":"/tmp/in","input_sha256":"abc","pjc_result_file":"/tmp/in","pjc_result_sha256":"abc","release_file":"/tmp/out","release_sha256":"def","threshold_k":20,"round_sum_to":null,"rate_limit_used":0,"rate_limit_max":5,"canonical_query_signature":"sig","parsed_metrics":{},"decision":"deny","reason":"below k","reason_code":"below_k","released":null,"auth":{"mode":"disabled_or_caller_only","key_id":null,"timestamp":null,"nonce":null,"auth_ok":true,"auth_reason_code":"auth_disabled"}}' \
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
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/public_report.schema.json" --json "$tmp/a_psi_run/public_report.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/policy_audit.schema.json" --jsonl "$tmp/a_psi_run/audit_log.jsonl"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/key_access_audit.schema.json" --jsonl "$tmp/key_access_audit.jsonl"
python3 "$TABULAR_VALIDATOR" --contract pjc-server-csv --path "$tmp/bridge_job/server.csv"
python3 "$TABULAR_VALIDATOR" --contract pjc-client-csv --path "$tmp/bridge_job/client.csv"

printf '%s\n' 'not-a-token' > "$tmp/bridge_job/bad_server.csv"
expect_failure python3 "$TABULAR_VALIDATOR" --contract pjc-server-csv --path "$tmp/bridge_job/bad_server.csv"

printf '%s\n' '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef,not-an-int' > "$tmp/bridge_job/bad_client.csv"
expect_failure python3 "$TABULAR_VALIDATOR" --contract pjc-client-csv --path "$tmp/bridge_job/bad_client.csv"

python3 "$REPO_ROOT/scripts/build_audit_chain.py" --out-base "$tmp" --job-id contract-check
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/audit_chain.schema.json" --json "$tmp/audit_chain.json"
python3 "$REPO_ROOT/scripts/seal_audit_artifact.py" --input "$tmp/audit_chain.json" --out "$tmp/audit_chain.seal.json" --job-id contract-check
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/audit_seal.schema.json" --json "$tmp/audit_chain.seal.json"

echo "[ok] JSON contract checks passed"
