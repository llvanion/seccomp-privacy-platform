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
  "$REPO_ROOT/schemas/record_recovery_service_config.schema.json"
  "$REPO_ROOT/schemas/record_recovery_service_policy.schema.json"
  "$REPO_ROOT/schemas/record_recovery_service_health.schema.json"
  "$REPO_ROOT/schemas/sse_encrypted_record_store.schema.json"
  "$REPO_ROOT/schemas/bridge_job_meta.schema.json"
  "$REPO_ROOT/schemas/bridge_audit.schema.json"
  "$REPO_ROOT/schemas/pjc_audit.schema.json"
  "$REPO_ROOT/schemas/public_report.schema.json"
  "$REPO_ROOT/schemas/policy_audit.schema.json"
  "$REPO_ROOT/schemas/audit_chain.schema.json"
  "$REPO_ROOT/schemas/audit_archive_index.schema.json"
  "$REPO_ROOT/schemas/key_manifest.schema.json"
  "$REPO_ROOT/schemas/keyring.schema.json"
  "$REPO_ROOT/schemas/external_kms_config.schema.json"
  "$REPO_ROOT/schemas/key_access_audit.schema.json"
  "$REPO_ROOT/schemas/key_lifecycle_audit.schema.json"
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

external_kms_port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
python3 - "$tmp/external_kms.json" "$tmp/keyring_external.json" "$external_kms_port" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
state_path = Path(sys.argv[2])
port = int(sys.argv[3])
config = {
    "schema": "external_kms_config/v1",
    "endpoint_url": f"http://127.0.0.1:{port}",
    "auth_token_env": "SECCOMP_EXTERNAL_KMS_TOKEN",
    "admin_auth_token_env": "SECCOMP_EXTERNAL_KMS_ADMIN_TOKEN",
    "request_timeout_sec": 5,
    "auto_start": {
        "bind_host": "127.0.0.1",
        "port": port,
        "state_file": str(state_path),
    },
}
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
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
for _ in $(seq 1 100); do
  if python3 -c 'import json,sys,urllib.request; raw=urllib.request.urlopen(sys.argv[1], timeout=0.5).read(); data=json.loads(raw.decode("utf-8")); sys.exit(0 if data.get("ok") is True else 1)' "http://127.0.0.1:$external_kms_port/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
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
  '{"schema":"pjc_audit/v1","ts_utc":"2026-04-10T00:00:02Z","event":"pjc_run","job_id":"contract-check","correlation_id":"contract-check","out_dir":"/tmp/a_psi_run","server_csv":"/tmp/server.csv","server_csv_sha256":"abc","client_csv":"/tmp/client.csv","client_csv_sha256":"def","server_log":"/tmp/server.log","server_log_sha256":"123","client_log":"/tmp/client.log","client_log_sha256":"456","result_file":"/tmp/result.json","result_sha256":"789","decision":"allow","reason_code":"ok","reason":"ok","exit_code":0}' \
  > "$tmp/a_psi_run/pjc_audit.jsonl"

printf '%s\n' \
  '{"schema":"sse_record_recovery_service_audit/v1","ts_utc":"2026-04-10T00:00:00Z","event":"record_recovery_service_request","service_id":"contract-recovery-service","tenant_id":"contract-tenant","dataset_id":"contract-dataset","caller":"auto_demo","correlation_id":"contract-check","job_id":"contract-check","role":"client","auth_mode":"env_token","socket_path":"/tmp/record_recovery.sock","authz_policy_config":"/tmp/record_recovery_policy.json","record_store_file":"/tmp/client_store.enc.jsonl","record_store_sha256":"abc","output_file":"/tmp/client.csv","output_file_type":"file","output_sha256":"def","join_key_field":"email","value_field":"amount","candidate_count":1,"filters":[{"field":"campaign","value_sha256":"123"}],"input_rows":1,"output_rows":1,"decision":"allow","reason_code":"ok","reason":"ok"}' \
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
python3 - "$tmp/record_recovery_service_config.json" "$tmp" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
tmp = Path(sys.argv[2])
payload = {
    "schema": "record_recovery_service_config/v1",
    "service_id": "contract-recovery-service",
    "tenant_id": "contract-tenant",
    "dataset_id": "contract-dataset",
    "socket_path": str((tmp / "record_recovery.sock").resolve()),
    "socket_mode": "600",
    "auth_token_env": "SSE_RECORD_RECOVERY_TOKEN",
    "allowed_callers": ["auto_demo"],
    "allowed_output_roots": [str(tmp.resolve())],
    "allowed_record_store_roots": [str(tmp.resolve())],
    "audit_log": str((tmp / "record_recovery_service_runtime_audit.jsonl").resolve()),
    "lifecycle": {
        "pid_file": str((tmp / "record_recovery_service.pid").resolve()),
        "ready_file": str((tmp / "record_recovery_service.ready").resolve()),
        "log_file": str((tmp / "record_recovery_service.log").resolve()),
    },
}
config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/record_recovery_service_config.schema.json" --json "$tmp/record_recovery_service_config.json"
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" start \
  --config "$tmp/record_recovery_service_config.json" \
  > "$tmp/record_recovery_service_start.json"
record_recovery_service_pid="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], "r", encoding="utf-8"))["started_pid"])' "$tmp/record_recovery_service_start.json")"
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" status \
  --config "$tmp/record_recovery_service_config.json" \
  > "$tmp/record_recovery_service_status.json"
python3 "$REPO_ROOT/scripts/request_record_recovery_service.py" \
  --config "$tmp/record_recovery_service_config.json" \
  > "$tmp/record_recovery_service_health.json"
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/record_recovery_service_health.schema.json" --json "$tmp/record_recovery_service_health.json"
python3 - "$tmp/record_recovery_service_status.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], "r", encoding="utf-8"))
if data.get("reachable") is not True:
    raise SystemExit("status check did not reach record recovery service")
if data.get("health", {}).get("schema") != "sse_record_recovery_health/v1":
    raise SystemExit("status check returned unexpected health schema")
PY
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" stop \
  --config "$tmp/record_recovery_service_config.json" \
  > "$tmp/record_recovery_service_stop.json"
record_recovery_service_pid=""
[[ ! -e "$tmp/record_recovery.sock" ]] || { echo "[ERROR] record recovery socket still exists after stop" >&2; exit 1; }
[[ ! -e "$tmp/record_recovery_service.pid" ]] || { echo "[ERROR] record recovery pid file still exists after stop" >&2; exit 1; }
[[ ! -e "$tmp/record_recovery_service.ready" ]] || { echo "[ERROR] record recovery ready file still exists after stop" >&2; exit 1; }

printf '%s\n' 'not-a-token' > "$tmp/bridge_job/bad_server.csv"
expect_failure python3 "$TABULAR_VALIDATOR" --contract pjc-server-csv --path "$tmp/bridge_job/bad_server.csv"

printf '%s\n' '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef,not-an-int' > "$tmp/bridge_job/bad_client.csv"
expect_failure python3 "$TABULAR_VALIDATOR" --contract pjc-client-csv --path "$tmp/bridge_job/bad_client.csv"

python3 "$REPO_ROOT/scripts/build_audit_chain.py" --out-base "$tmp" --job-id contract-check
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/audit_chain.schema.json" --json "$tmp/audit_chain.json"
python3 "$REPO_ROOT/scripts/seal_audit_artifact.py" --input "$tmp/audit_chain.json" --out "$tmp/audit_chain.seal.json" --job-id contract-check
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/audit_seal.schema.json" --json "$tmp/audit_chain.seal.json"
python3 "$REPO_ROOT/scripts/archive_audit_bundle.py" \
  --audit-chain "$tmp/audit_chain.json" \
  --audit-seal "$tmp/audit_chain.seal.json" \
  --archive-dir "$tmp/audit_archive" \
  --job-id contract-check
python3 "$VALIDATOR" --schema "$REPO_ROOT/schemas/audit_archive_index.schema.json" --jsonl "$tmp/audit_archive/audit_chain_index.jsonl"

echo "[ok] JSON contract checks passed"
