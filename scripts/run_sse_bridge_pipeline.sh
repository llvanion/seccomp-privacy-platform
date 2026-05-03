#!/usr/bin/env bash
set -euo pipefail

die() { echo "[ERROR] $*" >&2; exit 1; }
log() { echo "[INFO] $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SSE_DIR="${SSE_DIR:-$REPO_ROOT/sse}"
BRIDGE_DIR="${BRIDGE_DIR:-$REPO_ROOT/bridge}"
APSI_DIR="${APSI_DIR:-$REPO_ROOT/a-psi}"

SSE_PY="${SSE_PY:-$SSE_DIR/.venv/bin/python}"
BRIDGE_BIN="${BRIDGE_BIN:-cargo run --}"
RUN_PJC_SH="${RUN_PJC_SH:-$APSI_DIR/moduleA_psi/scripts/run_pjc.sh}"
POLICY_PY="${POLICY_PY:-$APSI_DIR/moduleA_psi/scripts/policy_release.py}"
VALIDATE_BRIDGE_JOB_PY="${VALIDATE_BRIDGE_JOB_PY:-$APSI_DIR/moduleA_psi/scripts/validate_bridge_job.py}"
VALIDATE_PIPELINE_POLICY_PY="${VALIDATE_PIPELINE_POLICY_PY:-$REPO_ROOT/scripts/validate_pipeline_policy.py}"
VALIDATE_JSON_CONTRACT_PY="${VALIDATE_JSON_CONTRACT_PY:-$REPO_ROOT/scripts/validate_json_contract.py}"
VALIDATE_TABULAR_CONTRACT_PY="${VALIDATE_TABULAR_CONTRACT_PY:-$REPO_ROOT/scripts/validate_tabular_contract.py}"
BUILD_AUDIT_CHAIN_PY="${BUILD_AUDIT_CHAIN_PY:-$REPO_ROOT/scripts/build_audit_chain.py}"
CHECK_MAINLINE_CONTRACT_PY="${CHECK_MAINLINE_CONTRACT_PY:-$REPO_ROOT/scripts/check_mainline_contract.py}"
WRITE_PJC_AUDIT_PY="${WRITE_PJC_AUDIT_PY:-$REPO_ROOT/scripts/write_pjc_audit.py}"
ARCHIVE_AUDIT_BUNDLE_PY="${ARCHIVE_AUDIT_BUNDLE_PY:-$REPO_ROOT/scripts/archive_audit_bundle.py}"
RESOLVE_KEY_ACCESS_PY="${RESOLVE_KEY_ACCESS_PY:-$REPO_ROOT/scripts/resolve_key_access.py}"
KEY_AGENT_SERVICE_PY="${KEY_AGENT_SERVICE_PY:-$REPO_ROOT/scripts/key_agent_service.py}"
REQUEST_KEY_AGENT_PY="${REQUEST_KEY_AGENT_PY:-$REPO_ROOT/scripts/request_key_agent.py}"
EXTERNAL_KMS_SERVICE_PY="${EXTERNAL_KMS_SERVICE_PY:-$REPO_ROOT/scripts/external_kms_service.py}"
REQUEST_EXTERNAL_KMS_PY="${REQUEST_EXTERNAL_KMS_PY:-$REPO_ROOT/scripts/request_external_kms.py}"
REQUEST_RECORD_RECOVERY_SERVICE_PY="${REQUEST_RECORD_RECOVERY_SERVICE_PY:-$REPO_ROOT/scripts/request_record_recovery_service.py}"
MANAGE_RECORD_RECOVERY_SERVICE_PY="${MANAGE_RECORD_RECOVERY_SERVICE_PY:-$REPO_ROOT/scripts/manage_record_recovery_service.py}"
RUN_RECORD_RECOVERY_SERVICE_PY="${RUN_RECORD_RECOVERY_SERVICE_PY:-$REPO_ROOT/scripts/run_record_recovery_service.py}"
SEAL_AUDIT_ARTIFACT_PY="${SEAL_AUDIT_ARTIFACT_PY:-$REPO_ROOT/scripts/seal_audit_artifact.py}"
RUNTIME_SERVICE_HELPERS_PY="${RUNTIME_SERVICE_HELPERS_PY:-$REPO_ROOT/scripts/runtime_service_helpers.py}"
PJC_BIN_DIR="${PJC_BIN_DIR:-$APSI_DIR/private-join-and-compute/bazel-bin}"

SERVER_SOURCE=""
CLIENT_SOURCE=""
SERVER_JOIN_KEY_FIELD=""
CLIENT_JOIN_KEY_FIELD=""
CLIENT_VALUE_FIELD=""
SERVER_NORMALIZER="identity"
CLIENT_NORMALIZER="identity"
SERVER_SOURCE_FORMAT="jsonl"
CLIENT_SOURCE_FORMAT="jsonl"
CLIENT_VALUE_MODE="count"
SERVER_SSE_KEYWORD=""
CLIENT_SSE_KEYWORD=""
SERVER_RECORD_ID_FIELD=""
CLIENT_RECORD_ID_FIELD=""
SERVER_RECORD_ID_FORMAT="utf8"
CLIENT_RECORD_ID_FORMAT="utf8"
SERVER_SSE_SID=""
CLIENT_SSE_SID=""
SERVER_SSE_SNAME=""
CLIENT_SSE_SNAME=""
SERVER_RECORD_STORE_PATH=""
CLIENT_RECORD_STORE_PATH=""
SERVER_RECORD_STORE_KEY_ENV=""
CLIENT_RECORD_STORE_KEY_ENV=""
RECORD_RECOVERY_SOCKET=""
RECORD_RECOVERY_ENDPOINT_URL=""
RECORD_RECOVERY_AUTH_ENV=""
RECORD_RECOVERY_SERVICE_CONFIG=""
RECORD_RECOVERY_AUTHZ_CONFIG=""
RECORD_RECOVERY_SERVICE_AUDIT_LOG=""
RECORD_RECOVERY_SERVICE_LOG=""
RECORD_RECOVERY_SERVICE_HEALTH_JSON=""
RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON=""
RECORD_RECOVERY_SERVICE_MODE="auto"
RECORD_RECOVERY_TRANSPORT="unix_socket"
RECORD_RECOVERY_SOCKET_MODE="600"
RECORD_RECOVERY_SERVICE_ID=""
RECORD_RECOVERY_CONFIG_SERVICE_ID=""
RECORD_RECOVERY_CONFIG_TENANT_ID=""
RECORD_RECOVERY_CONFIG_DATASET_ID=""
TOKEN_SCOPE=""
TOKEN_SECRET="${TOKEN_SECRET:-}"
TOKEN_SECRET_ENV="${TOKEN_SECRET_ENV:-}"
TOKEN_SECRET_KEY_ID=""
TOKEN_SECRET_KEY_NAME=""
TOKEN_KEY_VERSION="1"
KEY_MANIFEST=""
KEYRING=""
KEY_ACCESS_AUDIT_LOG=""
KEY_AGENT_SOCKET=""
KEY_AGENT_AUTH_ENV=""
KEY_AGENT_LOG=""
KEY_AGENT_MODE="auto"
EXTERNAL_KMS_CONFIG=""
EXTERNAL_KMS_MODE="auto"
EXTERNAL_KMS_LOG=""
EXTERNAL_KMS_LIFECYCLE_AUDIT_LOG=""
AUDIT_SEAL_KEY_ENV=""
AUDIT_ARCHIVE_DIR=""
PJC_AUDIT_LOG=""
JOB_ID=""
OUT_BASE=""
CALLER="bridge_demo"
TENANT_ID=""
DATASET_ID=""
K_THRESHOLD="20"
RATE_N="5"
DENY_DUPLICATE_QUERY="0"
SSE_EXPORT_POLICY_CONFIG=""
SSE_EXPORT_AUDIT_LOG=""
SSE_EXPORT_HANDOFF_MODE="file"
CLEANUP_SSE_EXPORT_HANDOFF_FILES_AFTER_BRIDGE="1"
HANDOFF_RETENTION_REASON=""
UNSAFE_ALLOW_NO_SSE_EXPORT_POLICY="0"
PRODUCTION_MODE="0"
SERVER_FILTERS=()
CLIENT_FILTERS=()

usage() {
  cat <<EOF
Usage:
  $0 \\
    --server-source <path> \\
    --client-source <path> \\
    --server-join-key-field <field> \\
    --client-join-key-field <field> \\
    --client-value-field <field> \\
    --token-scope <scope> \\
    --job-id <id> \\
    --out-base <dir> [options]

Options:
  --server-source-format jsonl|csv   default: jsonl
  --client-source-format jsonl|csv   default: jsonl
  --server-normalizer identity|email|phone
  --client-normalizer identity|email|phone
  --client-value-mode count|raw-int  default: count
  --server-sse-keyword <keyword>     optional SSE-backed server candidate keyword
  --client-sse-keyword <keyword>     optional SSE-backed client candidate keyword
  --server-record-id-field <field>   required with --server-sse-keyword
  --client-record-id-field <field>   required with --client-sse-keyword
  --server-record-id-format int|hex|raw|utf8 default: utf8
  --client-record-id-format int|hex|raw|utf8 default: utf8
  --server-sse-sid <sid>
  --client-sse-sid <sid>
  --server-sse-sname <name>
  --client-sse-sname <name>
  --server-record-store-path <path> optional encrypted record store path
  --client-record-store-path <path> optional encrypted record store path
  --server-record-store-key-env <env> record store passphrase env var
  --client-record-store-key-env <env> record store passphrase env var
  --record-recovery-socket <path> optional Unix socket for long-running record recovery service
  --record-recovery-endpoint-url <url> optional HTTP endpoint for long-running record recovery service
  --record-recovery-auth-env <env> optional env var containing the record recovery service auth token
  --record-recovery-service-config <path> optional JSON config shared by manual/auto recovery service management
  --record-recovery-authz-config <path> optional JSON authz policy passed to auto-started recovery service
  --record-recovery-service-id <id> optional service-instance id for record recovery requests
  --record-recovery-service-audit-log <path> optional service audit log validated after export
  --record-recovery-service-log <path> optional stdout/stderr log for auto-started recovery service
  --record-recovery-service-health-json <path> optional service health snapshot written before export
  --record-recovery-service-mode auto|manual|subprocess default: auto; applies when encrypted record stores are used
  --record-recovery-socket-mode <octal> filesystem mode for the recovery Unix socket, default: 600
  --server-filter field=value        repeatable
  --client-filter field=value        repeatable
  --token-secret <secret>
  --token-secret-env <env>
  --token-secret-key-id <id>       resolve token secret env from --key-manifest
  --token-secret-key-name <name>   resolve token secret through --keyring or --external-kms-config
  --token-key-version <version>    default: 1; overridden by --token-secret-key-id
  --key-manifest <path>            local key manifest for key-id resolution
  --keyring <path>                 local keyring for key-agent/KMS resolution
  --key-agent-socket <path>        optional Unix socket for long-running key agent
  --key-agent-auth-env <env>       optional env var containing the key-agent auth token
  --key-agent-log <path>           optional stdout/stderr log for auto-started key agent
  --key-agent-mode auto|manual     default: auto; applies when --token-secret-key-name is used
  --external-kms-config <path>     external KMS config for HTTP-based token-secret resolution
  --external-kms-mode auto|manual  default: auto; auto starts the mock external KMS when config includes auto_start
  --external-kms-log <path>        optional stdout/stderr log for auto-started external KMS
  --key-access-audit-log <path>    default: <out-base>/key_access_audit.jsonl
  --audit-seal-key-env <env>       optional env var used to HMAC-seal audit_chain.json
  --audit-archive-dir <dir>        optional local archive dir for indexed audit bundle copies
  --pjc-audit-log <path>           default: <out-base>/a_psi_run/pjc_audit.jsonl
  --sse-export-policy-config <path> SSE export policy config
  --sse-export-audit-log <path>     default: <out-base>/sse_exports/export_audit.jsonl
  --sse-export-handoff-mode file|fifo default: file; fifo streams plaintext handoff through named pipes
  --cleanup-sse-export-handoff-files-after-bridge force file-mode SSE plaintext handoff cleanup after bridge prepare-job (default)
  --keep-sse-export-handoff-files keep file-mode SSE plaintext handoff files after bridge prepare-job
  --handoff-retention-reason <text> required with --keep-sse-export-handoff-files; records why plaintext handoff retention is explicitly allowed
  --unsafe-allow-no-sse-export-policy allow ad-hoc export without policy config
  --production-mode                 forbid command-line token secrets in bridge
  --caller <id>                      policy caller, default: bridge_demo
  --tenant-id <id>                   optional tenant scope aligned with policy and service config
  --dataset-id <id>                  optional dataset scope aligned with policy and service config
  --k <int>                          release threshold, default: 20
  --n <int>                          rate limit, default: 5
  --deny-duplicate-query             deny exact repeated policy-release query signatures
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-source) SERVER_SOURCE="$2"; shift 2 ;;
    --client-source) CLIENT_SOURCE="$2"; shift 2 ;;
    --server-source-format) SERVER_SOURCE_FORMAT="$2"; shift 2 ;;
    --client-source-format) CLIENT_SOURCE_FORMAT="$2"; shift 2 ;;
    --server-join-key-field) SERVER_JOIN_KEY_FIELD="$2"; shift 2 ;;
    --client-join-key-field) CLIENT_JOIN_KEY_FIELD="$2"; shift 2 ;;
    --client-value-field) CLIENT_VALUE_FIELD="$2"; shift 2 ;;
    --server-normalizer) SERVER_NORMALIZER="$2"; shift 2 ;;
    --client-normalizer) CLIENT_NORMALIZER="$2"; shift 2 ;;
    --client-value-mode) CLIENT_VALUE_MODE="$2"; shift 2 ;;
    --server-sse-keyword) SERVER_SSE_KEYWORD="$2"; shift 2 ;;
    --client-sse-keyword) CLIENT_SSE_KEYWORD="$2"; shift 2 ;;
    --server-record-id-field) SERVER_RECORD_ID_FIELD="$2"; shift 2 ;;
    --client-record-id-field) CLIENT_RECORD_ID_FIELD="$2"; shift 2 ;;
    --server-record-id-format) SERVER_RECORD_ID_FORMAT="$2"; shift 2 ;;
    --client-record-id-format) CLIENT_RECORD_ID_FORMAT="$2"; shift 2 ;;
    --server-sse-sid) SERVER_SSE_SID="$2"; shift 2 ;;
    --client-sse-sid) CLIENT_SSE_SID="$2"; shift 2 ;;
    --server-sse-sname) SERVER_SSE_SNAME="$2"; shift 2 ;;
    --client-sse-sname) CLIENT_SSE_SNAME="$2"; shift 2 ;;
    --server-record-store-path) SERVER_RECORD_STORE_PATH="$2"; shift 2 ;;
    --client-record-store-path) CLIENT_RECORD_STORE_PATH="$2"; shift 2 ;;
    --server-record-store-key-env) SERVER_RECORD_STORE_KEY_ENV="$2"; shift 2 ;;
    --client-record-store-key-env) CLIENT_RECORD_STORE_KEY_ENV="$2"; shift 2 ;;
    --record-recovery-socket) RECORD_RECOVERY_SOCKET="$2"; shift 2 ;;
    --record-recovery-endpoint-url) RECORD_RECOVERY_ENDPOINT_URL="$2"; shift 2 ;;
    --record-recovery-auth-env) RECORD_RECOVERY_AUTH_ENV="$2"; shift 2 ;;
    --record-recovery-service-config) RECORD_RECOVERY_SERVICE_CONFIG="$2"; shift 2 ;;
    --record-recovery-authz-config) RECORD_RECOVERY_AUTHZ_CONFIG="$2"; shift 2 ;;
    --record-recovery-service-id) RECORD_RECOVERY_SERVICE_ID="$2"; shift 2 ;;
    --record-recovery-service-audit-log) RECORD_RECOVERY_SERVICE_AUDIT_LOG="$2"; shift 2 ;;
    --record-recovery-service-log) RECORD_RECOVERY_SERVICE_LOG="$2"; shift 2 ;;
    --record-recovery-service-health-json) RECORD_RECOVERY_SERVICE_HEALTH_JSON="$2"; shift 2 ;;
    --record-recovery-service-mode) RECORD_RECOVERY_SERVICE_MODE="$2"; shift 2 ;;
    --record-recovery-socket-mode) RECORD_RECOVERY_SOCKET_MODE="$2"; shift 2 ;;
    --server-filter) SERVER_FILTERS+=("$2"); shift 2 ;;
    --client-filter) CLIENT_FILTERS+=("$2"); shift 2 ;;
    --token-scope) TOKEN_SCOPE="$2"; shift 2 ;;
    --token-secret) TOKEN_SECRET="$2"; shift 2 ;;
    --token-secret-env) TOKEN_SECRET_ENV="$2"; shift 2 ;;
    --token-secret-key-id) TOKEN_SECRET_KEY_ID="$2"; shift 2 ;;
    --token-secret-key-name) TOKEN_SECRET_KEY_NAME="$2"; shift 2 ;;
    --token-key-version) TOKEN_KEY_VERSION="$2"; shift 2 ;;
    --key-manifest) KEY_MANIFEST="$2"; shift 2 ;;
    --keyring) KEYRING="$2"; shift 2 ;;
    --key-agent-socket) KEY_AGENT_SOCKET="$2"; shift 2 ;;
    --key-agent-auth-env) KEY_AGENT_AUTH_ENV="$2"; shift 2 ;;
    --key-agent-log) KEY_AGENT_LOG="$2"; shift 2 ;;
    --key-agent-mode) KEY_AGENT_MODE="$2"; shift 2 ;;
    --external-kms-config) EXTERNAL_KMS_CONFIG="$2"; shift 2 ;;
    --external-kms-mode) EXTERNAL_KMS_MODE="$2"; shift 2 ;;
    --external-kms-log) EXTERNAL_KMS_LOG="$2"; shift 2 ;;
    --key-access-audit-log) KEY_ACCESS_AUDIT_LOG="$2"; shift 2 ;;
    --audit-seal-key-env) AUDIT_SEAL_KEY_ENV="$2"; shift 2 ;;
    --audit-archive-dir) AUDIT_ARCHIVE_DIR="$2"; shift 2 ;;
    --pjc-audit-log) PJC_AUDIT_LOG="$2"; shift 2 ;;
    --sse-export-policy-config) SSE_EXPORT_POLICY_CONFIG="$2"; shift 2 ;;
    --sse-export-audit-log) SSE_EXPORT_AUDIT_LOG="$2"; shift 2 ;;
    --sse-export-handoff-mode) SSE_EXPORT_HANDOFF_MODE="$2"; shift 2 ;;
    --cleanup-sse-export-handoff-files-after-bridge) CLEANUP_SSE_EXPORT_HANDOFF_FILES_AFTER_BRIDGE="1"; shift ;;
    --keep-sse-export-handoff-files) CLEANUP_SSE_EXPORT_HANDOFF_FILES_AFTER_BRIDGE="0"; shift ;;
    --handoff-retention-reason) HANDOFF_RETENTION_REASON="$2"; shift 2 ;;
    --unsafe-allow-no-sse-export-policy) UNSAFE_ALLOW_NO_SSE_EXPORT_POLICY="1"; shift ;;
    --production-mode) PRODUCTION_MODE="1"; shift ;;
    --job-id) JOB_ID="$2"; shift 2 ;;
    --out-base) OUT_BASE="$2"; shift 2 ;;
    --caller) CALLER="$2"; shift 2 ;;
    --tenant-id) TENANT_ID="$2"; shift 2 ;;
    --dataset-id) DATASET_ID="$2"; shift 2 ;;
    --k) K_THRESHOLD="$2"; shift 2 ;;
    --n) RATE_N="$2"; shift 2 ;;
    --deny-duplicate-query) DENY_DUPLICATE_QUERY="1"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown arg: $1" ;;
  esac
done

normalize_repo_path() {
  local path="$1"
  if [[ -z "$path" ]]; then
    return 0
  fi
  if [[ "$path" = /* ]]; then
    printf '%s\n' "$path"
    return 0
  fi
  printf '%s\n' "$REPO_ROOT/$path"
}

SERVER_SOURCE="$(normalize_repo_path "$SERVER_SOURCE")"
CLIENT_SOURCE="$(normalize_repo_path "$CLIENT_SOURCE")"
SERVER_RECORD_STORE_PATH="$(normalize_repo_path "$SERVER_RECORD_STORE_PATH")"
CLIENT_RECORD_STORE_PATH="$(normalize_repo_path "$CLIENT_RECORD_STORE_PATH")"
RECORD_RECOVERY_SOCKET="$(normalize_repo_path "$RECORD_RECOVERY_SOCKET")"
RECORD_RECOVERY_SERVICE_CONFIG="$(normalize_repo_path "$RECORD_RECOVERY_SERVICE_CONFIG")"
RECORD_RECOVERY_AUTHZ_CONFIG="$(normalize_repo_path "$RECORD_RECOVERY_AUTHZ_CONFIG")"
KEY_MANIFEST="$(normalize_repo_path "$KEY_MANIFEST")"
KEYRING="$(normalize_repo_path "$KEYRING")"
EXTERNAL_KMS_CONFIG="$(normalize_repo_path "$EXTERNAL_KMS_CONFIG")"
SSE_EXPORT_POLICY_CONFIG="$(normalize_repo_path "$SSE_EXPORT_POLICY_CONFIG")"

[[ -n "$SERVER_SOURCE" || -n "$SERVER_RECORD_STORE_PATH" ]] || die "--server-source or --server-record-store-path required"
[[ -n "$CLIENT_SOURCE" || -n "$CLIENT_RECORD_STORE_PATH" ]] || die "--client-source or --client-record-store-path required"
[[ -n "$SERVER_JOIN_KEY_FIELD" ]] || die "--server-join-key-field required"
[[ -n "$CLIENT_JOIN_KEY_FIELD" ]] || die "--client-join-key-field required"
[[ -n "$CLIENT_VALUE_FIELD" ]] || [[ "$CLIENT_VALUE_MODE" == "count" ]] || die "--client-value-field required for raw-int"
[[ -n "$TOKEN_SCOPE" ]] || die "--token-scope required"
[[ -n "$JOB_ID" ]] || die "--job-id required"
[[ -n "$OUT_BASE" ]] || die "--out-base required"
[[ "$SSE_EXPORT_HANDOFF_MODE" == "file" || "$SSE_EXPORT_HANDOFF_MODE" == "fifo" ]] || die "--sse-export-handoff-mode must be file or fifo"
[[ "$SSE_EXPORT_HANDOFF_MODE" == "file" || "$CLEANUP_SSE_EXPORT_HANDOFF_FILES_AFTER_BRIDGE" == "1" ]] || die "--keep-sse-export-handoff-files is only valid with --sse-export-handoff-mode=file"
[[ -n "$SSE_EXPORT_POLICY_CONFIG" || "$UNSAFE_ALLOW_NO_SSE_EXPORT_POLICY" == "1" ]] || die "--sse-export-policy-config required unless --unsafe-allow-no-sse-export-policy is set"
[[ -z "$SERVER_SSE_KEYWORD" || -n "$SERVER_RECORD_ID_FIELD" ]] || die "--server-record-id-field required with --server-sse-keyword"
[[ -z "$CLIENT_SSE_KEYWORD" || -n "$CLIENT_RECORD_ID_FIELD" ]] || die "--client-record-id-field required with --client-sse-keyword"
[[ -z "$SERVER_RECORD_STORE_PATH" || -n "$SERVER_SSE_KEYWORD" ]] || die "--server-record-store-path requires --server-sse-keyword"
[[ -z "$CLIENT_RECORD_STORE_PATH" || -n "$CLIENT_SSE_KEYWORD" ]] || die "--client-record-store-path requires --client-sse-keyword"
[[ -z "$SERVER_RECORD_STORE_PATH" || -n "$SERVER_RECORD_STORE_KEY_ENV" ]] || die "--server-record-store-key-env required with --server-record-store-path"
[[ -z "$CLIENT_RECORD_STORE_PATH" || -n "$CLIENT_RECORD_STORE_KEY_ENV" ]] || die "--client-record-store-key-env required with --client-record-store-path"
[[ -z "$RECORD_RECOVERY_AUTH_ENV" || -n "$RECORD_RECOVERY_SOCKET" || -n "$RECORD_RECOVERY_ENDPOINT_URL" || -n "$RECORD_RECOVERY_SERVICE_CONFIG" ]] || die "--record-recovery-auth-env requires a record recovery service address or config"
[[ "$RECORD_RECOVERY_SERVICE_MODE" == "auto" || "$RECORD_RECOVERY_SERVICE_MODE" == "manual" || "$RECORD_RECOVERY_SERVICE_MODE" == "subprocess" ]] || die "--record-recovery-service-mode must be auto, manual, or subprocess"
[[ -z "$RECORD_RECOVERY_AUTHZ_CONFIG" || "$RECORD_RECOVERY_SERVICE_MODE" == "auto" ]] || die "--record-recovery-authz-config currently requires --record-recovery-service-mode=auto"
[[ "$RECORD_RECOVERY_SOCKET_MODE" =~ ^[0-7]{3,4}$ ]] || die "--record-recovery-socket-mode must be octal like 600 or 0600"
[[ "$KEY_AGENT_MODE" == "auto" || "$KEY_AGENT_MODE" == "manual" ]] || die "--key-agent-mode must be auto or manual"
[[ -z "$KEY_AGENT_AUTH_ENV" || -n "$KEY_AGENT_SOCKET" || "$KEY_AGENT_MODE" == "auto" ]] || die "--key-agent-auth-env requires --key-agent-socket unless --key-agent-mode=auto"
[[ "$EXTERNAL_KMS_MODE" == "auto" || "$EXTERNAL_KMS_MODE" == "manual" ]] || die "--external-kms-mode must be auto or manual"
[[ -x "$SSE_PY" ]] || die "missing SSE python: $SSE_PY"
[[ -f "$RUN_PJC_SH" ]] || die "missing a-psi runner: $RUN_PJC_SH"
[[ -f "$POLICY_PY" ]] || die "missing policy script: $POLICY_PY"
[[ -f "$VALIDATE_BRIDGE_JOB_PY" ]] || die "missing validate script: $VALIDATE_BRIDGE_JOB_PY"
[[ -f "$VALIDATE_PIPELINE_POLICY_PY" ]] || die "missing pipeline policy validator: $VALIDATE_PIPELINE_POLICY_PY"
[[ -f "$VALIDATE_JSON_CONTRACT_PY" ]] || die "missing JSON contract validator: $VALIDATE_JSON_CONTRACT_PY"
[[ -f "$VALIDATE_TABULAR_CONTRACT_PY" ]] || die "missing tabular contract validator: $VALIDATE_TABULAR_CONTRACT_PY"
[[ -f "$BUILD_AUDIT_CHAIN_PY" ]] || die "missing audit chain builder: $BUILD_AUDIT_CHAIN_PY"
[[ -f "$WRITE_PJC_AUDIT_PY" ]] || die "missing PJC audit writer: $WRITE_PJC_AUDIT_PY"
[[ -f "$ARCHIVE_AUDIT_BUNDLE_PY" ]] || die "missing audit archive script: $ARCHIVE_AUDIT_BUNDLE_PY"
[[ -f "$RESOLVE_KEY_ACCESS_PY" ]] || die "missing key access resolver: $RESOLVE_KEY_ACCESS_PY"
[[ -f "$KEY_AGENT_SERVICE_PY" ]] || die "missing key agent service: $KEY_AGENT_SERVICE_PY"
[[ -f "$REQUEST_KEY_AGENT_PY" ]] || die "missing key agent client: $REQUEST_KEY_AGENT_PY"
[[ -f "$EXTERNAL_KMS_SERVICE_PY" ]] || die "missing external KMS service: $EXTERNAL_KMS_SERVICE_PY"
[[ -f "$REQUEST_EXTERNAL_KMS_PY" ]] || die "missing external KMS client: $REQUEST_EXTERNAL_KMS_PY"
[[ -f "$REQUEST_RECORD_RECOVERY_SERVICE_PY" ]] || die "missing record recovery service client: $REQUEST_RECORD_RECOVERY_SERVICE_PY"
[[ -f "$MANAGE_RECORD_RECOVERY_SERVICE_PY" ]] || die "missing record recovery service manager: $MANAGE_RECORD_RECOVERY_SERVICE_PY"
[[ -f "$RUN_RECORD_RECOVERY_SERVICE_PY" ]] || die "missing standalone record recovery launcher: $RUN_RECORD_RECOVERY_SERVICE_PY"
[[ -f "$SEAL_AUDIT_ARTIFACT_PY" ]] || die "missing audit seal script: $SEAL_AUDIT_ARTIFACT_PY"

if [[ "$CLEANUP_SSE_EXPORT_HANDOFF_FILES_AFTER_BRIDGE" != "1" ]]; then
  [[ "$SSE_EXPORT_HANDOFF_MODE" == "file" ]] || die "--keep-sse-export-handoff-files requires --sse-export-handoff-mode=file"
  [[ -n "${HANDOFF_RETENTION_REASON:-}" ]] || die "--handoff-retention-reason is required with --keep-sse-export-handoff-files"
else
  [[ -z "${HANDOFF_RETENTION_REASON:-}" ]] || die "--handoff-retention-reason is only valid with --keep-sse-export-handoff-files"
fi

if [[ -n "$TOKEN_SECRET_KEY_ID" ]]; then
  [[ -n "$KEY_MANIFEST" ]] || die "--token-secret-key-id requires --key-manifest"
fi
if [[ -n "$TOKEN_SECRET_KEY_NAME" ]]; then
  [[ -n "$KEYRING" || -n "$EXTERNAL_KMS_CONFIG" ]] || die "--token-secret-key-name requires --keyring or --external-kms-config"
  [[ -z "$KEYRING" || -z "$EXTERNAL_KMS_CONFIG" ]] || die "use only one of --keyring or --external-kms-config with --token-secret-key-name"
fi
SECRET_METHODS=0
[[ -n "$TOKEN_SECRET" ]] && SECRET_METHODS=$((SECRET_METHODS + 1))
[[ -n "$TOKEN_SECRET_ENV" ]] && SECRET_METHODS=$((SECRET_METHODS + 1))
[[ -n "$TOKEN_SECRET_KEY_ID" ]] && SECRET_METHODS=$((SECRET_METHODS + 1))
[[ -n "$TOKEN_SECRET_KEY_NAME" ]] && SECRET_METHODS=$((SECRET_METHODS + 1))
if [[ "$SECRET_METHODS" -gt 1 ]]; then
  die "use only one of --token-secret, --token-secret-env, --token-secret-key-id, or --token-secret-key-name"
fi
if [[ "$SECRET_METHODS" -eq 0 ]]; then
  die "set --token-secret, --token-secret-env, --token-secret-key-id, or --token-secret-key-name"
fi
if [[ "$PRODUCTION_MODE" == "1" && -n "$TOKEN_SECRET" ]]; then
  die "--token-secret is forbidden in --production-mode; use --token-secret-env"
fi

if [[ -n "$SSE_EXPORT_POLICY_CONFIG" ]]; then
  PIPELINE_POLICY_ARGS=(
    --policy-config "$SSE_EXPORT_POLICY_CONFIG"
    --caller "$CALLER"
    --tenant-id "$TENANT_ID"
    --dataset-id "$DATASET_ID"
    --service-id "$RECORD_RECOVERY_SERVICE_ID"
    --require-bridge
    --require-pjc
    --require-release
  )
  if [[ (-n "$SERVER_RECORD_STORE_PATH" || -n "$CLIENT_RECORD_STORE_PATH") && "$RECORD_RECOVERY_SERVICE_MODE" != "subprocess" ]]; then
    PIPELINE_POLICY_ARGS+=(--require-record-recovery)
  fi
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/sse_export_policy.schema.json" \
    --json "$SSE_EXPORT_POLICY_CONFIG"
  python3 "$VALIDATE_PIPELINE_POLICY_PY" "${PIPELINE_POLICY_ARGS[@]}"
fi

if [[ -n "$RECORD_RECOVERY_AUTHZ_CONFIG" ]]; then
  if ! python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/record_recovery_service_policy.schema.json" \
    --json "$RECORD_RECOVERY_AUTHZ_CONFIG" >/dev/null 2>&1; then
    python3 "$VALIDATE_JSON_CONTRACT_PY" \
      --schema "$REPO_ROOT/schemas/sse_export_policy.schema.json" \
      --json "$RECORD_RECOVERY_AUTHZ_CONFIG"
  fi
fi

if [[ -n "$RECORD_RECOVERY_SERVICE_CONFIG" ]]; then
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/record_recovery_service_config.schema.json" \
    --json "$RECORD_RECOVERY_SERVICE_CONFIG"
fi

if [[ -n "$KEYRING" ]]; then
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/keyring.schema.json" \
    --json "$KEYRING"
fi

if [[ -n "$EXTERNAL_KMS_CONFIG" ]]; then
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/external_kms_config.schema.json" \
    --json "$EXTERNAL_KMS_CONFIG"
fi

OUT_BASE="$(mkdir -p "$OUT_BASE" && cd "$OUT_BASE" && pwd)"
SSE_EXPORT_DIR="$OUT_BASE/sse_exports"
BRIDGE_JOB_DIR="$OUT_BASE/bridge_job"
APSI_JOB_DIR="$OUT_BASE/a_psi_run"
mkdir -p "$SSE_EXPORT_DIR" "$BRIDGE_JOB_DIR" "$APSI_JOB_DIR"

if [[ "$SSE_EXPORT_HANDOFF_MODE" == "fifo" ]]; then
  SERVER_EXPORT="$SSE_EXPORT_DIR/server.fifo"
  CLIENT_EXPORT="$SSE_EXPORT_DIR/client.fifo"
  SERVER_EXPORT_STATUS_FILE="$SSE_EXPORT_DIR/server_export.status"
  CLIENT_EXPORT_STATUS_FILE="$SSE_EXPORT_DIR/client_export.status"
  BRIDGE_STATUS_FILE="$SSE_EXPORT_DIR/bridge_prepare.status"
else
  SERVER_EXPORT="$SSE_EXPORT_DIR/server.csv"
  CLIENT_EXPORT="$SSE_EXPORT_DIR/client.csv"
fi
if [[ -z "$SSE_EXPORT_AUDIT_LOG" ]]; then
  SSE_EXPORT_AUDIT_LOG="$SSE_EXPORT_DIR/export_audit.jsonl"
fi
if [[ -z "$KEY_ACCESS_AUDIT_LOG" ]]; then
  KEY_ACCESS_AUDIT_LOG="$OUT_BASE/key_access_audit.jsonl"
fi
if [[ -z "$KEY_AGENT_LOG" ]]; then
  KEY_AGENT_LOG="$OUT_BASE/key_agent.log"
fi
if [[ -z "$EXTERNAL_KMS_LOG" ]]; then
  EXTERNAL_KMS_LOG="$OUT_BASE/external_kms.log"
fi
if [[ -z "$EXTERNAL_KMS_LIFECYCLE_AUDIT_LOG" ]]; then
  EXTERNAL_KMS_LIFECYCLE_AUDIT_LOG="$OUT_BASE/external_kms_lifecycle_audit.jsonl"
fi
if [[ -z "$PJC_AUDIT_LOG" ]]; then
  PJC_AUDIT_LOG="$APSI_JOB_DIR/pjc_audit.jsonl"
fi
if [[ -z "$RECORD_RECOVERY_SERVICE_HEALTH_JSON" ]]; then
  RECORD_RECOVERY_SERVICE_HEALTH_JSON="$SSE_EXPORT_DIR/record_recovery_service_health.json"
fi
if [[ -z "$RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON" ]]; then
  RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON="$SSE_EXPORT_DIR/record_recovery_service_config.json"
fi

if [[ -n "$TOKEN_SECRET_KEY_ID" ]]; then
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/key_manifest.schema.json" \
    --json "$KEY_MANIFEST"
  KEY_RESOLUTION_JSON="$(
    python3 "$RESOLVE_KEY_ACCESS_PY" \
      --manifest "$KEY_MANIFEST" \
      --key-id "$TOKEN_SECRET_KEY_ID" \
      --purpose bridge_token \
      --caller "$CALLER" \
      --job-id "$JOB_ID" \
      --audit-log "$KEY_ACCESS_AUDIT_LOG"
  )"
  TOKEN_SECRET_ENV="$(python3 "$RUNTIME_SERVICE_HELPERS_PY" read-json-field --field env <<< "$KEY_RESOLUTION_JSON")"
  TOKEN_KEY_VERSION="$(python3 "$RUNTIME_SERVICE_HELPERS_PY" read-json-field --field key_version <<< "$KEY_RESOLUTION_JSON")"
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/key_access_audit.schema.json" \
    --jsonl "$KEY_ACCESS_AUDIT_LOG"
fi

SERVER_EXPORT_PID=""
CLIENT_EXPORT_PID=""
KEY_AGENT_SERVICE_PID=""
KEY_AGENT_SERVICE_STARTED="0"
EXTERNAL_KMS_SERVICE_PID=""
EXTERNAL_KMS_SERVICE_STARTED="0"
RECORD_RECOVERY_SERVICE_PID=""
RECORD_RECOVERY_SERVICE_STARTED="0"
RECORD_RECOVERY_USE_SERVICE="0"
RECORD_RECOVERY_ROOT_ARGS=()
RECORD_RECOVERY_ALLOWED_CALLERS=()
RECORD_RECOVERY_ALLOWED_OUTPUT_ROOTS=()
RECORD_RECOVERY_ALLOWED_RECORD_STORE_ROOTS=()
RECORD_RECOVERY_CONFIG_PID_FILE=""
RECORD_RECOVERY_CONFIG_READY_FILE=""
RECORD_RECOVERY_CONFIG_LOG_FILE=""
KEY_AGENT_PID_FILE=""
KEY_AGENT_READY_FILE=""
EXTERNAL_KMS_PID_FILE=""
EXTERNAL_KMS_READY_FILE=""
RECORD_RECOVERY_SERVICE_PID_FILE=""
RECORD_RECOVERY_SERVICE_READY_FILE=""
BRIDGE_BIN_ARR=()
KEY_AGENT_RESOLVED_ENV_SET="0"
EXTERNAL_KMS_RESOLVED_ENV_SET="0"
EXTERNAL_KMS_ENDPOINT_URL=""
EXTERNAL_KMS_AUTH_ENV=""
EXTERNAL_KMS_ADMIN_AUTH_ENV=""

abspath_parent_dir() {
  local path="$1"
  (cd "$(dirname "$path")" && pwd)
}

normalize_optional_path() {
  local path="$1"
  normalize_repo_path "$path"
}

record_recovery_service_config_value() {
  local field="$1"
  python3 -c 'import sys; from pathlib import Path; repo_root=Path(sys.argv[1]); config_path=sys.argv[2]; field=sys.argv[3]; sys.path.insert(0, str(repo_root)); from services.record_recovery.config import load_record_recovery_service_config, resolve_record_recovery_service_config; cfg=resolve_record_recovery_service_config(load_record_recovery_service_config(config_path)); value=cfg.get(field);
if value is None:
    print("")
elif isinstance(value, list):
    print("\n".join(str(item) for item in value))
else:
    print(value)' "$REPO_ROOT" "$RECORD_RECOVERY_SERVICE_CONFIG" "$field"
}

load_record_recovery_service_config_array() {
  local field="$1"
  local array_name="$2"
  local -n target="$array_name"
  target=()
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    target+=("$line")
  done < <(record_recovery_service_config_value "$field")
}

append_unique_value() {
  local array_name="$1"
  local value="$2"
  local -n target="$array_name"
  local existing
  [[ -n "$value" ]] || return 0
  for existing in "${target[@]}"; do
    [[ "$existing" == "$value" ]] && return 0
  done
  target+=("$value")
}

json_array() {
  python3 -c 'import json, sys; print(json.dumps(sys.argv[1:], ensure_ascii=False))' "$@"
}

resolve_platform_scope_json() {
  local require_service="$1"
  python3 -c 'import json, sys; from pathlib import Path; repo_root=Path(sys.argv[1]); policy_config=sys.argv[2]; caller=sys.argv[3]; tenant_id=sys.argv[4]; dataset_id=sys.argv[5]; service_id=sys.argv[6]; require_service=sys.argv[7] == "1"; sys.path.insert(0, str(repo_root / "sse")); from toolkit.platform_policy import load_platform_policy, platform_policy_for_caller, resolve_platform_scope; 
if not policy_config:
    print(json.dumps({"tenant_id": tenant_id, "dataset_id": dataset_id, "service_id": service_id}, ensure_ascii=False))
else:
    policy=load_platform_policy(policy_config)
    caller_policy=platform_policy_for_caller(policy, caller)
    print(json.dumps(resolve_platform_scope(caller_policy=caller_policy, caller=caller, tenant_id=tenant_id, dataset_id=dataset_id, service_id=service_id, require_record_recovery_service=require_service), ensure_ascii=False))' "$REPO_ROOT" "$SSE_EXPORT_POLICY_CONFIG" "$CALLER" "$TENANT_ID" "$DATASET_ID" "$RECORD_RECOVERY_SERVICE_ID" "$require_service"
}

read_status_file() {
  local status_file="$1"
  [[ -f "$status_file" ]] || return 1
  tr -d '[:space:]' < "$status_file"
}

start_command_with_status() {
  local pid_var="$1"
  local status_file="$2"
  local workdir="$3"
  shift 3
  rm -f "$status_file"
  (
    local rc=0
    cd "$workdir" || rc=$?
    if [[ "$rc" -eq 0 ]]; then
      "$@" || rc=$?
    fi
    printf '%s\n' "$rc" > "$status_file"
    exit "$rc"
  ) &
  printf -v "$pid_var" '%s' "$!"
}

write_record_recovery_service_runtime_config() {
  [[ "$RECORD_RECOVERY_USE_SERVICE" == "1" ]] || return 0
  [[ "$RECORD_RECOVERY_SERVICE_MODE" != "subprocess" ]] || return 0
  [[ -n "$RECORD_RECOVERY_SOCKET" || -n "$RECORD_RECOVERY_ENDPOINT_URL" ]] || return 0

  local allowed_callers_json allowed_output_roots_json allowed_record_store_roots_json
  allowed_callers_json="$(json_array "${RECORD_RECOVERY_ALLOWED_CALLERS[@]}")"
  allowed_output_roots_json="$(json_array "${RECORD_RECOVERY_ALLOWED_OUTPUT_ROOTS[@]}")"
  allowed_record_store_roots_json="$(json_array "${RECORD_RECOVERY_ALLOWED_RECORD_STORE_ROOTS[@]}")"

  python3 - "$RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON" "$RECORD_RECOVERY_TRANSPORT" "$RECORD_RECOVERY_SERVICE_ID" "$TENANT_ID" "$DATASET_ID" "$RECORD_RECOVERY_SOCKET" "$RECORD_RECOVERY_ENDPOINT_URL" "$RECORD_RECOVERY_SOCKET_MODE" "$RECORD_RECOVERY_AUTH_ENV" "$RECORD_RECOVERY_AUTHZ_CONFIG" "$RECORD_RECOVERY_SERVICE_AUDIT_LOG" "$RECORD_RECOVERY_SERVICE_PID_FILE" "$RECORD_RECOVERY_SERVICE_READY_FILE" "$RECORD_RECOVERY_SERVICE_LOG" "$allowed_callers_json" "$allowed_output_roots_json" "$allowed_record_store_roots_json" <<'PY'
import json
import sys
from pathlib import Path

out_path = Path(sys.argv[1])
out_path.parent.mkdir(parents=True, exist_ok=True)
payload = {
    "schema": "record_recovery_service_config/v1",
    "transport": sys.argv[2] or "unix_socket",
    "service_id": sys.argv[3] or None,
    "tenant_id": sys.argv[4] or None,
    "dataset_id": sys.argv[5] or None,
    "socket_path": sys.argv[6] or None,
    "endpoint_url": sys.argv[7] or None,
    "socket_mode": sys.argv[8] or "600",
    "auth_token_env": sys.argv[9] or None,
    "authz_config": sys.argv[10] or None,
    "allowed_callers": json.loads(sys.argv[15]),
    "allowed_output_roots": json.loads(sys.argv[16]),
    "allowed_record_store_roots": json.loads(sys.argv[17]),
    "audit_log": sys.argv[11] or None,
    "lifecycle": {
        "pid_file": sys.argv[12] or None,
        "ready_file": sys.argv[13] or None,
        "log_file": sys.argv[14] or None,
    },
}
out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/record_recovery_service_config.schema.json" \
    --json "$RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON"
}

SERVER_SOURCE="$(normalize_optional_path "$SERVER_SOURCE")"
CLIENT_SOURCE="$(normalize_optional_path "$CLIENT_SOURCE")"
SERVER_RECORD_STORE_PATH="$(normalize_optional_path "$SERVER_RECORD_STORE_PATH")"
CLIENT_RECORD_STORE_PATH="$(normalize_optional_path "$CLIENT_RECORD_STORE_PATH")"
RECORD_RECOVERY_SOCKET="$(normalize_optional_path "$RECORD_RECOVERY_SOCKET")"
RECORD_RECOVERY_ENDPOINT_URL="${RECORD_RECOVERY_ENDPOINT_URL:-}"
RECORD_RECOVERY_SERVICE_CONFIG="$(normalize_optional_path "$RECORD_RECOVERY_SERVICE_CONFIG")"
RECORD_RECOVERY_AUTHZ_CONFIG="$(normalize_optional_path "$RECORD_RECOVERY_AUTHZ_CONFIG")"
RECORD_RECOVERY_SERVICE_AUDIT_LOG="$(normalize_optional_path "$RECORD_RECOVERY_SERVICE_AUDIT_LOG")"
RECORD_RECOVERY_SERVICE_LOG="$(normalize_optional_path "$RECORD_RECOVERY_SERVICE_LOG")"
RECORD_RECOVERY_SERVICE_HEALTH_JSON="$(normalize_optional_path "$RECORD_RECOVERY_SERVICE_HEALTH_JSON")"
KEY_MANIFEST="$(normalize_optional_path "$KEY_MANIFEST")"
KEYRING="$(normalize_optional_path "$KEYRING")"
KEY_ACCESS_AUDIT_LOG="$(normalize_optional_path "$KEY_ACCESS_AUDIT_LOG")"
KEY_AGENT_SOCKET="$(normalize_optional_path "$KEY_AGENT_SOCKET")"
KEY_AGENT_LOG="$(normalize_optional_path "$KEY_AGENT_LOG")"
EXTERNAL_KMS_CONFIG="$(normalize_optional_path "$EXTERNAL_KMS_CONFIG")"
EXTERNAL_KMS_LOG="$(normalize_optional_path "$EXTERNAL_KMS_LOG")"
EXTERNAL_KMS_LIFECYCLE_AUDIT_LOG="$(normalize_optional_path "$EXTERNAL_KMS_LIFECYCLE_AUDIT_LOG")"
PJC_AUDIT_LOG="$(normalize_optional_path "$PJC_AUDIT_LOG")"
SSE_EXPORT_POLICY_CONFIG="$(normalize_optional_path "$SSE_EXPORT_POLICY_CONFIG")"
SSE_EXPORT_AUDIT_LOG="$(normalize_optional_path "$SSE_EXPORT_AUDIT_LOG")"
AUDIT_ARCHIVE_DIR="$(normalize_optional_path "$AUDIT_ARCHIVE_DIR")"

if [[ -n "$RECORD_RECOVERY_SERVICE_CONFIG" ]]; then
  config_record_recovery_transport="$(record_recovery_service_config_value transport)"
  [[ -n "$config_record_recovery_transport" ]] && RECORD_RECOVERY_TRANSPORT="$config_record_recovery_transport"
  RECORD_RECOVERY_CONFIG_SERVICE_ID="$(record_recovery_service_config_value service_id)"
  RECORD_RECOVERY_CONFIG_TENANT_ID="$(record_recovery_service_config_value tenant_id)"
  RECORD_RECOVERY_CONFIG_DATASET_ID="$(record_recovery_service_config_value dataset_id)"
  [[ -n "$RECORD_RECOVERY_SERVICE_ID" ]] || RECORD_RECOVERY_SERVICE_ID="$(record_recovery_service_config_value service_id)"
  [[ -n "$TENANT_ID" ]] || TENANT_ID="$(record_recovery_service_config_value tenant_id)"
  [[ -n "$DATASET_ID" ]] || DATASET_ID="$(record_recovery_service_config_value dataset_id)"
  [[ -n "$RECORD_RECOVERY_SOCKET" ]] || RECORD_RECOVERY_SOCKET="$(record_recovery_service_config_value socket_path)"
  [[ -n "$RECORD_RECOVERY_ENDPOINT_URL" ]] || RECORD_RECOVERY_ENDPOINT_URL="$(record_recovery_service_config_value endpoint_url)"
  [[ -n "$RECORD_RECOVERY_AUTH_ENV" ]] || RECORD_RECOVERY_AUTH_ENV="$(record_recovery_service_config_value auth_token_env)"
  [[ -n "$RECORD_RECOVERY_AUTHZ_CONFIG" ]] || RECORD_RECOVERY_AUTHZ_CONFIG="$(record_recovery_service_config_value authz_config)"
  [[ -n "$RECORD_RECOVERY_SERVICE_AUDIT_LOG" ]] || RECORD_RECOVERY_SERVICE_AUDIT_LOG="$(record_recovery_service_config_value audit_log)"
  RECORD_RECOVERY_CONFIG_PID_FILE="$(record_recovery_service_config_value pid_file)"
  RECORD_RECOVERY_CONFIG_READY_FILE="$(record_recovery_service_config_value ready_file)"
  RECORD_RECOVERY_CONFIG_LOG_FILE="$(record_recovery_service_config_value log_file)"
  [[ -n "$RECORD_RECOVERY_SERVICE_LOG" ]] || RECORD_RECOVERY_SERVICE_LOG="$RECORD_RECOVERY_CONFIG_LOG_FILE"
  load_record_recovery_service_config_array allowed_callers RECORD_RECOVERY_ALLOWED_CALLERS
  load_record_recovery_service_config_array allowed_output_roots RECORD_RECOVERY_ALLOWED_OUTPUT_ROOTS
  load_record_recovery_service_config_array allowed_record_store_roots RECORD_RECOVERY_ALLOWED_RECORD_STORE_ROOTS
fi
if [[ -n "$RECORD_RECOVERY_ENDPOINT_URL" && -z "$RECORD_RECOVERY_SOCKET" ]]; then
  RECORD_RECOVERY_TRANSPORT="http"
elif [[ -n "$RECORD_RECOVERY_SOCKET" ]]; then
  RECORD_RECOVERY_TRANSPORT="unix_socket"
fi
if [[ -z "$RECORD_RECOVERY_SERVICE_AUDIT_LOG" ]]; then
  RECORD_RECOVERY_SERVICE_AUDIT_LOG="$SSE_EXPORT_DIR/record_recovery_service_audit.jsonl"
fi
if [[ -z "$RECORD_RECOVERY_SERVICE_LOG" ]]; then
  RECORD_RECOVERY_SERVICE_LOG="$SSE_EXPORT_DIR/record_recovery_service.log"
fi

append_record_store_root() {
  local record_store_path="$1"
  [[ -n "$record_store_path" ]] || return 0
  append_unique_value RECORD_RECOVERY_ALLOWED_RECORD_STORE_ROOTS "$(abspath_parent_dir "$record_store_path")"
}

require_matching_scope_value() {
  local field_name="$1"
  local expected="$2"
  local actual="$3"
  local source_name="$4"
  [[ -n "$expected" ]] || return 0
  [[ "$expected" == "$actual" ]] || die "$source_name $field_name=$expected does not match resolved $field_name=$actual"
}

wait_for_socket() {
  local socket_path="$1"
  local attempts=0
  while [[ $attempts -lt 100 ]]; do
    if [[ -S "$socket_path" ]]; then
      return 0
    fi
    sleep 0.1
    attempts=$((attempts + 1))
  done
  return 1
}

verify_record_recovery_service_health() {
  [[ "$RECORD_RECOVERY_USE_SERVICE" == "1" && ( -n "$RECORD_RECOVERY_SOCKET" || -n "$RECORD_RECOVERY_ENDPOINT_URL" ) ]] || return 0

  local health_json
  if [[ -n "$RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON" && -f "$RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON" ]]; then
    health_json="$(
      python3 "$REQUEST_RECORD_RECOVERY_SERVICE_PY" \
        --config "$RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON"
    )"
  elif [[ -n "$RECORD_RECOVERY_ENDPOINT_URL" ]]; then
    health_json="$(
      python3 "$REQUEST_RECORD_RECOVERY_SERVICE_PY" \
        --endpoint-url "$RECORD_RECOVERY_ENDPOINT_URL" \
        --auth-token-env "$RECORD_RECOVERY_AUTH_ENV"
    )"
  elif [[ -n "$RECORD_RECOVERY_AUTH_ENV" ]]; then
    health_json="$(
      python3 "$REQUEST_RECORD_RECOVERY_SERVICE_PY" \
        --socket-path "$RECORD_RECOVERY_SOCKET" \
        --auth-token-env "$RECORD_RECOVERY_AUTH_ENV"
    )"
  else
    health_json="$(
      python3 "$REQUEST_RECORD_RECOVERY_SERVICE_PY" \
        --socket-path "$RECORD_RECOVERY_SOCKET"
    )"
  fi
  printf '%s\n' "$health_json" > "$RECORD_RECOVERY_SERVICE_HEALTH_JSON"
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/record_recovery_service_health.schema.json" \
    --json "$RECORD_RECOVERY_SERVICE_HEALTH_JSON"
  python3 - "$RECORD_RECOVERY_SERVICE_HEALTH_JSON" "$RECORD_RECOVERY_TRANSPORT" "$RECORD_RECOVERY_SOCKET" "$RECORD_RECOVERY_ENDPOINT_URL" "$RECORD_RECOVERY_SERVICE_ID" "$TENANT_ID" "$DATASET_ID" "$RECORD_RECOVERY_AUTHZ_CONFIG" "$RECORD_RECOVERY_SERVICE_AUDIT_LOG" <<'PY'
import json
import sys
from pathlib import Path

health_path = Path(sys.argv[1])
expected_transport = sys.argv[2]
expected_socket = sys.argv[3]
expected_endpoint = sys.argv[4]
expected_service_id = sys.argv[5]
expected_tenant_id = sys.argv[6]
expected_dataset_id = sys.argv[7]
expected_authz = sys.argv[8]
expected_audit = sys.argv[9]
data = json.loads(health_path.read_text(encoding="utf-8"))

def ensure_match(field_name: str, expected: str, actual) -> None:
    if not expected:
        return
    actual_text = "" if actual is None else str(actual)
    if actual_text != expected:
        raise SystemExit(
            f"record recovery health mismatch for {field_name}: expected {expected!r}, got {actual_text!r}"
        )

ensure_match("transport", expected_transport, data.get("transport"))
ensure_match("socket_path", expected_socket, data.get("socket_path"))
ensure_match("endpoint_url", expected_endpoint, data.get("endpoint_url"))
ensure_match("service_id", expected_service_id, data.get("service_id"))
ensure_match("tenant_id", expected_tenant_id, data.get("tenant_id"))
ensure_match("dataset_id", expected_dataset_id, data.get("dataset_id"))
ensure_match("authz_policy_config", expected_authz, data.get("authz_policy_config"))
ensure_match("audit_log", expected_audit, data.get("audit_log"))
PY
}

wait_for_http_url() {
  local endpoint_url="$1"
  python3 "$RUNTIME_SERVICE_HELPERS_PY" wait-json-health --url "$endpoint_url/healthz"
}

external_kms_config_value() {
  local field="$1"
  python3 -c 'import json,os,sys; cfg_path=sys.argv[1]; field=sys.argv[2]; data=json.load(open(cfg_path, "r", encoding="utf-8")); value=data
for part in field.split("."):
    if not isinstance(value, dict):
        value=None
        break
    value=value.get(part)
if value is None:
    print("")
elif field.endswith("state_file") and isinstance(value, str) and value and not os.path.isabs(value):
    print(os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(cfg_path)), value)))
else:
    print(value)' "$EXTERNAL_KMS_CONFIG" "$field"
}

default_record_recovery_socket() {
  python3 -c 'import hashlib, sys; seed="|".join(sys.argv[1:]); print(f"/tmp/seccomp_rr_{hashlib.sha256(seed.encode()).hexdigest()[:16]}.sock")' "$OUT_BASE" "$JOB_ID" "$CALLER"
}

default_key_agent_socket() {
  python3 -c 'import hashlib, sys; seed="|".join(sys.argv[1:]); print(f"/tmp/seccomp_key_agent_{hashlib.sha256(seed.encode()).hexdigest()[:16]}.sock")' "$OUT_BASE" "$JOB_ID" "$CALLER"
}

start_key_agent_service() {
  [[ -n "$TOKEN_SECRET_KEY_NAME" && -z "$EXTERNAL_KMS_CONFIG" ]] || return 0
  if [[ "$KEY_AGENT_MODE" == "manual" ]]; then
    [[ -n "$KEY_AGENT_SOCKET" ]] || die "--key-agent-socket required when --key-agent-mode=manual"
    return 0
  fi

  [[ -n "$KEY_AGENT_SOCKET" ]] || KEY_AGENT_SOCKET="$(default_key_agent_socket)"
  [[ -n "$KEY_AGENT_AUTH_ENV" ]] || KEY_AGENT_AUTH_ENV="SECCOMP_KEY_AGENT_AUTH_TOKEN"
  if [[ -z "${!KEY_AGENT_AUTH_ENV:-}" ]]; then
    printf -v "$KEY_AGENT_AUTH_ENV" '%s' "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    export "$KEY_AGENT_AUTH_ENV"
  fi

  KEY_AGENT_PID_FILE="$OUT_BASE/key_agent.pid"
  KEY_AGENT_READY_FILE="$OUT_BASE/key_agent.ready"

  rm -f "$KEY_AGENT_SOCKET" "$KEY_AGENT_PID_FILE" "$KEY_AGENT_READY_FILE"
  (
    cd "$REPO_ROOT"
    python3 "$KEY_AGENT_SERVICE_PY" \
      --socket-path "$KEY_AGENT_SOCKET" \
      --keyring "$KEYRING" \
      --auth-token-env "$KEY_AGENT_AUTH_ENV" \
      --allowed-caller "$CALLER" \
      --audit-log "$KEY_ACCESS_AUDIT_LOG" \
      --pid-file "$KEY_AGENT_PID_FILE" \
      --ready-file "$KEY_AGENT_READY_FILE"
  ) >"$KEY_AGENT_LOG" 2>&1 &
  KEY_AGENT_SERVICE_PID=$!
  KEY_AGENT_SERVICE_STARTED="1"
  wait_for_socket "$KEY_AGENT_SOCKET" || die "key agent socket did not become ready: $KEY_AGENT_SOCKET"
  log "Auto-started key agent: $KEY_AGENT_SOCKET"
  log "  key agent log: $KEY_AGENT_LOG"
}

cleanup_key_agent_service() {
  if [[ "$KEY_AGENT_SERVICE_STARTED" == "1" ]]; then
    if [[ -n "$KEY_AGENT_SERVICE_PID" ]] && kill -0 "$KEY_AGENT_SERVICE_PID" 2>/dev/null; then
      kill "$KEY_AGENT_SERVICE_PID" 2>/dev/null || true
      wait "$KEY_AGENT_SERVICE_PID" 2>/dev/null || true
    fi
    rm -f "$KEY_AGENT_SOCKET" "$KEY_AGENT_PID_FILE" "$KEY_AGENT_READY_FILE"
    KEY_AGENT_SERVICE_PID=""
    KEY_AGENT_SERVICE_STARTED="0"
  fi
  if [[ "$KEY_AGENT_RESOLVED_ENV_SET" == "1" && -n "$TOKEN_SECRET_ENV" ]]; then
    unset "$TOKEN_SECRET_ENV" || true
    KEY_AGENT_RESOLVED_ENV_SET="0"
  fi
}

resolve_key_via_agent() {
  [[ -n "$TOKEN_SECRET_KEY_NAME" && -z "$EXTERNAL_KMS_CONFIG" ]] || return 0
  local key_resolution_json
  key_resolution_json="$(
    python3 "$REQUEST_KEY_AGENT_PY" \
      --socket-path "$KEY_AGENT_SOCKET" \
      --key-name "$TOKEN_SECRET_KEY_NAME" \
      --purpose bridge_token \
      --caller "$CALLER" \
      --job-id "$JOB_ID" \
      --auth-token-env "$KEY_AGENT_AUTH_ENV"
  )"
  local resolved_secret
  resolved_secret="$(python3 "$RUNTIME_SERVICE_HELPERS_PY" read-json-field --field secret <<< "$key_resolution_json")"
  TOKEN_SECRET_ENV="BRIDGE_TOKEN_SECRET_RESOLVED"
  printf -v "$TOKEN_SECRET_ENV" '%s' "$resolved_secret"
  export "$TOKEN_SECRET_ENV"
  KEY_AGENT_RESOLVED_ENV_SET="1"
  TOKEN_KEY_VERSION="$(python3 "$RUNTIME_SERVICE_HELPERS_PY" read-json-field --field key_version <<< "$key_resolution_json")"
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/key_access_audit.schema.json" \
    --jsonl "$KEY_ACCESS_AUDIT_LOG"
}

start_external_kms_service() {
  [[ -n "$EXTERNAL_KMS_CONFIG" ]] || return 0

  EXTERNAL_KMS_ENDPOINT_URL="$(external_kms_config_value endpoint_url)"
  EXTERNAL_KMS_AUTH_ENV="$(external_kms_config_value auth_token_env)"
  EXTERNAL_KMS_ADMIN_AUTH_ENV="$(external_kms_config_value admin_auth_token_env)"
  [[ -n "$EXTERNAL_KMS_ENDPOINT_URL" ]] || die "external KMS config is missing endpoint_url"

  if [[ "$EXTERNAL_KMS_MODE" == "manual" ]]; then
    return 0
  fi

  local bind_host port state_file vault_kv_file
  bind_host="$(external_kms_config_value auto_start.bind_host)"
  port="$(external_kms_config_value auto_start.port)"
  state_file="$(external_kms_config_value auto_start.state_file)"
  vault_kv_file="$(external_kms_config_value auto_start.vault_kv_file)"
  [[ -n "$bind_host" && -n "$port" && -n "$state_file" ]] || die "--external-kms-mode=auto requires auto_start in $EXTERNAL_KMS_CONFIG"

  if [[ -n "$EXTERNAL_KMS_AUTH_ENV" && -z "${!EXTERNAL_KMS_AUTH_ENV:-}" ]]; then
    printf -v "$EXTERNAL_KMS_AUTH_ENV" '%s' "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    export "$EXTERNAL_KMS_AUTH_ENV"
  fi
  if [[ -n "$EXTERNAL_KMS_ADMIN_AUTH_ENV" && -z "${!EXTERNAL_KMS_ADMIN_AUTH_ENV:-}" ]]; then
    printf -v "$EXTERNAL_KMS_ADMIN_AUTH_ENV" '%s' "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    export "$EXTERNAL_KMS_ADMIN_AUTH_ENV"
  fi

  EXTERNAL_KMS_PID_FILE="$OUT_BASE/external_kms.pid"
  EXTERNAL_KMS_READY_FILE="$OUT_BASE/external_kms.ready"
  rm -f "$EXTERNAL_KMS_PID_FILE" "$EXTERNAL_KMS_READY_FILE"
  (
    cd "$REPO_ROOT"
    external_cmd=(
      python3 "$EXTERNAL_KMS_SERVICE_PY"
      --bind-host "$bind_host"
      --port "$port"
      --state-file "$state_file"
      --lifecycle-audit-log "$EXTERNAL_KMS_LIFECYCLE_AUDIT_LOG"
      --pid-file "$EXTERNAL_KMS_PID_FILE"
      --ready-file "$EXTERNAL_KMS_READY_FILE"
    )
    if [[ -n "$EXTERNAL_KMS_AUTH_ENV" ]]; then
      external_cmd+=(--auth-token-env "$EXTERNAL_KMS_AUTH_ENV")
    fi
    if [[ -n "$EXTERNAL_KMS_ADMIN_AUTH_ENV" ]]; then
      external_cmd+=(--admin-auth-token-env "$EXTERNAL_KMS_ADMIN_AUTH_ENV")
    fi
    if [[ -n "$vault_kv_file" ]]; then
      external_cmd+=(--vault-kv-file "$vault_kv_file")
    fi
    "${external_cmd[@]}"
  ) >"$EXTERNAL_KMS_LOG" 2>&1 &
  EXTERNAL_KMS_SERVICE_PID=$!
  EXTERNAL_KMS_SERVICE_STARTED="1"
  wait_for_http_url "$EXTERNAL_KMS_ENDPOINT_URL" || die "external KMS endpoint did not become ready: $EXTERNAL_KMS_ENDPOINT_URL"
  log "Auto-started external KMS: $EXTERNAL_KMS_ENDPOINT_URL"
  log "  external KMS log: $EXTERNAL_KMS_LOG"
}

cleanup_external_kms_service() {
  if [[ "$EXTERNAL_KMS_SERVICE_STARTED" == "1" ]]; then
    if [[ -n "$EXTERNAL_KMS_SERVICE_PID" ]] && kill -0 "$EXTERNAL_KMS_SERVICE_PID" 2>/dev/null; then
      kill "$EXTERNAL_KMS_SERVICE_PID" 2>/dev/null || true
      wait "$EXTERNAL_KMS_SERVICE_PID" 2>/dev/null || true
    fi
    rm -f "$EXTERNAL_KMS_PID_FILE" "$EXTERNAL_KMS_READY_FILE"
    EXTERNAL_KMS_SERVICE_PID=""
    EXTERNAL_KMS_SERVICE_STARTED="0"
  fi
  if [[ "$EXTERNAL_KMS_RESOLVED_ENV_SET" == "1" && -n "$TOKEN_SECRET_ENV" ]]; then
    unset "$TOKEN_SECRET_ENV" || true
    EXTERNAL_KMS_RESOLVED_ENV_SET="0"
  fi
}

resolve_key_via_external_kms() {
  [[ -n "$EXTERNAL_KMS_CONFIG" ]] || return 0
  local key_resolution_json resolved_secret
  key_resolution_json="$(
    python3 "$REQUEST_EXTERNAL_KMS_PY" \
      --config "$EXTERNAL_KMS_CONFIG" \
      --key-name "$TOKEN_SECRET_KEY_NAME" \
      --purpose bridge_token \
      --caller "$CALLER" \
      --job-id "$JOB_ID" \
      --audit-log "$KEY_ACCESS_AUDIT_LOG"
  )"
  resolved_secret="$(python3 "$RUNTIME_SERVICE_HELPERS_PY" read-json-field --field secret <<< "$key_resolution_json")"
  TOKEN_SECRET_ENV="BRIDGE_TOKEN_SECRET_RESOLVED"
  printf -v "$TOKEN_SECRET_ENV" '%s' "$resolved_secret"
  export "$TOKEN_SECRET_ENV"
  EXTERNAL_KMS_RESOLVED_ENV_SET="1"
  TOKEN_KEY_VERSION="$(python3 "$RUNTIME_SERVICE_HELPERS_PY" read-json-field --field key_version <<< "$key_resolution_json")"
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/key_access_audit.schema.json" \
    --jsonl "$KEY_ACCESS_AUDIT_LOG"
}

start_record_recovery_service() {
  [[ "$RECORD_RECOVERY_USE_SERVICE" == "1" ]] || return 0
  if [[ "$RECORD_RECOVERY_SERVICE_MODE" == "subprocess" ]]; then
    return 0
  fi
  if [[ "$RECORD_RECOVERY_SERVICE_MODE" == "manual" ]]; then
    [[ -n "$RECORD_RECOVERY_SOCKET" || -n "$RECORD_RECOVERY_ENDPOINT_URL" || -n "$RECORD_RECOVERY_SERVICE_CONFIG" ]] || die "--record-recovery-socket, --record-recovery-endpoint-url, or --record-recovery-service-config required when --record-recovery-service-mode=manual"
    [[ -n "$RECORD_RECOVERY_SERVICE_PID_FILE" ]] || RECORD_RECOVERY_SERVICE_PID_FILE="$RECORD_RECOVERY_CONFIG_PID_FILE"
    [[ -n "$RECORD_RECOVERY_SERVICE_READY_FILE" ]] || RECORD_RECOVERY_SERVICE_READY_FILE="$RECORD_RECOVERY_CONFIG_READY_FILE"
    [[ -n "$RECORD_RECOVERY_SERVICE_LOG" ]] || RECORD_RECOVERY_SERVICE_LOG="$RECORD_RECOVERY_CONFIG_LOG_FILE"
    write_record_recovery_service_runtime_config
    python3 "$MANAGE_RECORD_RECOVERY_SERVICE_PY" status \
      --config "$RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON" >/dev/null
    verify_record_recovery_service_health
    return 0
  fi

  if [[ "$RECORD_RECOVERY_TRANSPORT" == "http" ]]; then
    [[ -n "$RECORD_RECOVERY_ENDPOINT_URL" ]] || die "record recovery HTTP auto mode requires --record-recovery-endpoint-url or config endpoint_url/http_listener"
  else
    [[ -n "$RECORD_RECOVERY_SOCKET" ]] || RECORD_RECOVERY_SOCKET="$(default_record_recovery_socket)"
  fi
  [[ -n "$RECORD_RECOVERY_AUTH_ENV" ]] || RECORD_RECOVERY_AUTH_ENV="SSE_RECORD_RECOVERY_AUTH_TOKEN"
  if [[ -z "${!RECORD_RECOVERY_AUTH_ENV:-}" ]]; then
    printf -v "$RECORD_RECOVERY_AUTH_ENV" '%s' "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    export "$RECORD_RECOVERY_AUTH_ENV"
  fi

  append_unique_value RECORD_RECOVERY_ALLOWED_CALLERS "$CALLER"
  append_unique_value RECORD_RECOVERY_ALLOWED_OUTPUT_ROOTS "$OUT_BASE"
  append_record_store_root "$SERVER_RECORD_STORE_PATH"
  append_record_store_root "$CLIENT_RECORD_STORE_PATH"
  [[ -n "$RECORD_RECOVERY_SERVICE_PID_FILE" ]] || RECORD_RECOVERY_SERVICE_PID_FILE="$RECORD_RECOVERY_CONFIG_PID_FILE"
  [[ -n "$RECORD_RECOVERY_SERVICE_PID_FILE" ]] || RECORD_RECOVERY_SERVICE_PID_FILE="$SSE_EXPORT_DIR/record_recovery_service.pid"
  [[ -n "$RECORD_RECOVERY_SERVICE_READY_FILE" ]] || RECORD_RECOVERY_SERVICE_READY_FILE="$RECORD_RECOVERY_CONFIG_READY_FILE"
  [[ -n "$RECORD_RECOVERY_SERVICE_READY_FILE" ]] || RECORD_RECOVERY_SERVICE_READY_FILE="$SSE_EXPORT_DIR/record_recovery_service.ready"
  [[ -n "$RECORD_RECOVERY_SERVICE_LOG" ]] || RECORD_RECOVERY_SERVICE_LOG="$RECORD_RECOVERY_CONFIG_LOG_FILE"
  write_record_recovery_service_runtime_config

  rm -f "$RECORD_RECOVERY_SOCKET"
  rm -f "$RECORD_RECOVERY_SERVICE_PID_FILE" "$RECORD_RECOVERY_SERVICE_READY_FILE"
  local start_cmd=(
    python3 "$MANAGE_RECORD_RECOVERY_SERVICE_PY"
    start
    --config "$RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON"
  )
  local start_json
  start_json="$("${start_cmd[@]}")"
  RECORD_RECOVERY_SERVICE_PID="$(python3 "$RUNTIME_SERVICE_HELPERS_PY" read-json-field --field started_pid --default '' <<< "$start_json")"
  RECORD_RECOVERY_SERVICE_STARTED="1"
  verify_record_recovery_service_health
  if [[ "$RECORD_RECOVERY_TRANSPORT" == "http" ]]; then
    log "Auto-started record recovery service: $RECORD_RECOVERY_ENDPOINT_URL"
  else
    log "Auto-started record recovery service: $RECORD_RECOVERY_SOCKET"
  fi
  log "  record recovery service log: $RECORD_RECOVERY_SERVICE_LOG"
}

cleanup_record_recovery_service() {
  if [[ "$RECORD_RECOVERY_SERVICE_STARTED" == "1" ]]; then
    python3 "$MANAGE_RECORD_RECOVERY_SERVICE_PY" stop \
      --config "$RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON" >/dev/null 2>&1 || true
    rm -f "$RECORD_RECOVERY_SOCKET"
    rm -f "$RECORD_RECOVERY_SERVICE_PID_FILE" "$RECORD_RECOVERY_SERVICE_READY_FILE"
    RECORD_RECOVERY_SERVICE_PID=""
    RECORD_RECOVERY_SERVICE_STARTED="0"
  fi
}

cleanup_handoff() {
  if [[ "$SSE_EXPORT_HANDOFF_MODE" == "fifo" ]]; then
    if [[ -n "$SERVER_EXPORT_PID" ]] && kill -0 "$SERVER_EXPORT_PID" 2>/dev/null; then
      kill "$SERVER_EXPORT_PID" 2>/dev/null || true
    fi
    if [[ -n "$CLIENT_EXPORT_PID" ]] && kill -0 "$CLIENT_EXPORT_PID" 2>/dev/null; then
      kill "$CLIENT_EXPORT_PID" 2>/dev/null || true
    fi
    SERVER_EXPORT_PID=""
    CLIENT_EXPORT_PID=""
    rm -f "$SERVER_EXPORT" "$CLIENT_EXPORT" \
      "$SERVER_EXPORT_STATUS_FILE" "$CLIENT_EXPORT_STATUS_FILE" "$BRIDGE_STATUS_FILE"
  fi
}

cleanup_persisted_sse_export_handoff_files() {
  [[ "$SSE_EXPORT_HANDOFF_MODE" == "file" ]] || return 0
  [[ "$CLEANUP_SSE_EXPORT_HANDOFF_FILES_AFTER_BRIDGE" == "1" ]] || return 0
  rm -f "$SERVER_EXPORT" "$CLIENT_EXPORT"
}
cleanup_all() {
  cleanup_handoff
  cleanup_key_agent_service
  cleanup_external_kms_service
  cleanup_record_recovery_service
}
trap cleanup_all EXIT

if [[ -n "$SERVER_RECORD_STORE_PATH" || -n "$CLIENT_RECORD_STORE_PATH" ]]; then
  if [[ "$RECORD_RECOVERY_SERVICE_MODE" != "subprocess" || -n "$RECORD_RECOVERY_SOCKET" || -n "$RECORD_RECOVERY_ENDPOINT_URL" ]]; then
    RECORD_RECOVERY_USE_SERVICE="1"
  fi
fi

if [[ -n "$SSE_EXPORT_POLICY_CONFIG" ]]; then
  PLATFORM_SCOPE_JSON="$(resolve_platform_scope_json "$RECORD_RECOVERY_USE_SERVICE")"
  RESOLVED_TENANT_ID="$(python3 "$RUNTIME_SERVICE_HELPERS_PY" read-json-field --field tenant_id --default '' <<< "$PLATFORM_SCOPE_JSON")"
  RESOLVED_DATASET_ID="$(python3 "$RUNTIME_SERVICE_HELPERS_PY" read-json-field --field dataset_id --default '' <<< "$PLATFORM_SCOPE_JSON")"
  RESOLVED_RECORD_RECOVERY_SERVICE_ID="$(python3 "$RUNTIME_SERVICE_HELPERS_PY" read-json-field --field service_id --default '' <<< "$PLATFORM_SCOPE_JSON")"
  if [[ "$RECORD_RECOVERY_USE_SERVICE" == "1" ]]; then
    require_matching_scope_value "tenant_id" "$RECORD_RECOVERY_CONFIG_TENANT_ID" "$RESOLVED_TENANT_ID" "record recovery service config"
    require_matching_scope_value "dataset_id" "$RECORD_RECOVERY_CONFIG_DATASET_ID" "$RESOLVED_DATASET_ID" "record recovery service config"
    require_matching_scope_value "service_id" "$RECORD_RECOVERY_CONFIG_SERVICE_ID" "$RESOLVED_RECORD_RECOVERY_SERVICE_ID" "record recovery service config"
  fi
  TENANT_ID="$RESOLVED_TENANT_ID"
  DATASET_ID="$RESOLVED_DATASET_ID"
  RECORD_RECOVERY_SERVICE_ID="$RESOLVED_RECORD_RECOVERY_SERVICE_ID"
fi

start_key_agent_service
start_external_kms_service
resolve_key_via_agent
resolve_key_via_external_kms
start_record_recovery_service

log "Stage1 SSE export"
if [[ "$SSE_EXPORT_HANDOFF_MODE" == "fifo" ]]; then
  rm -f "$SERVER_EXPORT" "$CLIENT_EXPORT"
  mkfifo "$SERVER_EXPORT" "$CLIENT_EXPORT"
  log "Using FIFO SSE export handoff; bridge-ready plaintext will not be persisted in sse_exports"
elif [[ "$CLEANUP_SSE_EXPORT_HANDOFF_FILES_AFTER_BRIDGE" != "1" ]]; then
  log "Using retained file-mode SSE export handoff compatibility path"
  log "  retention reason: $HANDOFF_RETENTION_REASON"
fi
if [[ -n "$TOKEN_SECRET_KEY_NAME" ]]; then
  if [[ -n "$EXTERNAL_KMS_CONFIG" ]]; then
    log "Using external KMS for bridge token secret: $TOKEN_SECRET_KEY_NAME"
    log "  external KMS endpoint: $EXTERNAL_KMS_ENDPOINT_URL"
    if [[ "$EXTERNAL_KMS_SERVICE_STARTED" == "1" ]]; then
      log "  external KMS pid file: $EXTERNAL_KMS_PID_FILE"
      log "  external KMS ready file: $EXTERNAL_KMS_READY_FILE"
      log "  external KMS lifecycle audit: $EXTERNAL_KMS_LIFECYCLE_AUDIT_LOG"
    fi
  else
    log "Using key agent for bridge token secret: $TOKEN_SECRET_KEY_NAME"
    log "  key agent socket: $KEY_AGENT_SOCKET"
  fi
  log "  key access audit: $KEY_ACCESS_AUDIT_LOG"
  if [[ "$KEY_AGENT_SERVICE_STARTED" == "1" ]]; then
    log "  key agent pid file: $KEY_AGENT_PID_FILE"
    log "  key agent ready file: $KEY_AGENT_READY_FILE"
  fi
fi
if [[ "$RECORD_RECOVERY_USE_SERVICE" == "1" && ( -n "$RECORD_RECOVERY_SOCKET" || -n "$RECORD_RECOVERY_ENDPOINT_URL" ) ]]; then
  if [[ -n "$RECORD_RECOVERY_ENDPOINT_URL" ]]; then
    log "Using record recovery service endpoint: $RECORD_RECOVERY_ENDPOINT_URL"
  else
    log "Using record recovery service socket: $RECORD_RECOVERY_SOCKET"
  fi
  if [[ -n "$RECORD_RECOVERY_SERVICE_ID" ]]; then
    log "  record recovery service id: $RECORD_RECOVERY_SERVICE_ID"
  fi
  if [[ -n "$TENANT_ID" || -n "$DATASET_ID" ]]; then
    log "  recovery scope: tenant=${TENANT_ID:-<unset>} dataset=${DATASET_ID:-<unset>}"
  fi
  if [[ -n "$RECORD_RECOVERY_AUTHZ_CONFIG" ]]; then
    log "  record recovery authz config: $RECORD_RECOVERY_AUTHZ_CONFIG"
  fi
  if [[ -n "$RECORD_RECOVERY_SERVICE_PID_FILE" ]]; then
    log "  record recovery pid file: $RECORD_RECOVERY_SERVICE_PID_FILE"
  fi
  if [[ -n "$RECORD_RECOVERY_SERVICE_READY_FILE" ]]; then
    log "  record recovery ready file: $RECORD_RECOVERY_SERVICE_READY_FILE"
  fi
  if [[ -f "$RECORD_RECOVERY_SERVICE_HEALTH_JSON" ]]; then
    log "  record recovery health: $RECORD_RECOVERY_SERVICE_HEALTH_JSON"
  fi
  if [[ -f "$RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON" ]]; then
    log "  record recovery runtime config: $RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON"
  fi
fi
SERVER_EXPORT_CMD=(
  "$SSE_PY" run_client.py export-bridge-records
  --out-path "$SERVER_EXPORT"
  --role server
  --source-format "$SERVER_SOURCE_FORMAT"
  --out-format csv
  --join-key-field "$SERVER_JOIN_KEY_FIELD"
  --caller "$CALLER"
  --audit-log "$SSE_EXPORT_AUDIT_LOG"
  --job-id "$JOB_ID"
  --tenant-id "$TENANT_ID"
  --dataset-id "$DATASET_ID"
)
if [[ -n "$SERVER_SOURCE" ]]; then
  SERVER_EXPORT_CMD+=(--source-path "$SERVER_SOURCE")
fi
if [[ -n "$SERVER_RECORD_STORE_PATH" ]]; then
  SERVER_EXPORT_CMD+=(--record-store-path "$SERVER_RECORD_STORE_PATH" --record-store-key-env "$SERVER_RECORD_STORE_KEY_ENV")
  if [[ "$RECORD_RECOVERY_USE_SERVICE" == "1" && ( -n "$RECORD_RECOVERY_SOCKET" || -n "$RECORD_RECOVERY_ENDPOINT_URL" ) ]]; then
    SERVER_EXPORT_CMD+=(--record-recovery-service-config "$RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON")
    if [[ -n "$RECORD_RECOVERY_SERVICE_ID" ]]; then
      SERVER_EXPORT_CMD+=(--record-recovery-service-id "$RECORD_RECOVERY_SERVICE_ID")
    fi
  fi
fi
if [[ -n "$SSE_EXPORT_POLICY_CONFIG" ]]; then
  SERVER_EXPORT_CMD+=(--policy-config "$SSE_EXPORT_POLICY_CONFIG")
elif [[ "$UNSAFE_ALLOW_NO_SSE_EXPORT_POLICY" == "1" ]]; then
  SERVER_EXPORT_CMD+=(--unsafe-allow-no-policy)
fi
if [[ -n "$SERVER_SSE_KEYWORD" ]]; then
  SERVER_EXPORT_CMD+=(--sse-keyword "$SERVER_SSE_KEYWORD" --record-id-field "$SERVER_RECORD_ID_FIELD" --record-id-format "$SERVER_RECORD_ID_FORMAT")
  if [[ -n "$SERVER_SSE_SID" ]]; then
    SERVER_EXPORT_CMD+=(--sid "$SERVER_SSE_SID")
  fi
  if [[ -n "$SERVER_SSE_SNAME" ]]; then
    SERVER_EXPORT_CMD+=(--sname "$SERVER_SSE_SNAME")
  fi
fi
for f in "${SERVER_FILTERS[@]}"; do
  SERVER_EXPORT_CMD+=(--filter "$f")
done
if [[ "$SSE_EXPORT_HANDOFF_MODE" == "fifo" ]]; then
  start_command_with_status SERVER_EXPORT_PID "$SERVER_EXPORT_STATUS_FILE" "$SSE_DIR" "${SERVER_EXPORT_CMD[@]}"
else
  (cd "$SSE_DIR" && "${SERVER_EXPORT_CMD[@]}")
fi

CLIENT_EXPORT_CMD=(
  "$SSE_PY" run_client.py export-bridge-records
  --out-path "$CLIENT_EXPORT"
  --role client
  --source-format "$CLIENT_SOURCE_FORMAT"
  --out-format csv
  --join-key-field "$CLIENT_JOIN_KEY_FIELD"
  --caller "$CALLER"
  --audit-log "$SSE_EXPORT_AUDIT_LOG"
  --job-id "$JOB_ID"
  --tenant-id "$TENANT_ID"
  --dataset-id "$DATASET_ID"
)
if [[ -n "$CLIENT_SOURCE" ]]; then
  CLIENT_EXPORT_CMD+=(--source-path "$CLIENT_SOURCE")
fi
if [[ -n "$CLIENT_RECORD_STORE_PATH" ]]; then
  CLIENT_EXPORT_CMD+=(--record-store-path "$CLIENT_RECORD_STORE_PATH" --record-store-key-env "$CLIENT_RECORD_STORE_KEY_ENV")
  if [[ "$RECORD_RECOVERY_USE_SERVICE" == "1" && ( -n "$RECORD_RECOVERY_SOCKET" || -n "$RECORD_RECOVERY_ENDPOINT_URL" ) ]]; then
    CLIENT_EXPORT_CMD+=(--record-recovery-service-config "$RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON")
    if [[ -n "$RECORD_RECOVERY_SERVICE_ID" ]]; then
      CLIENT_EXPORT_CMD+=(--record-recovery-service-id "$RECORD_RECOVERY_SERVICE_ID")
    fi
  fi
fi
if [[ -n "$CLIENT_VALUE_FIELD" ]]; then
  CLIENT_EXPORT_CMD+=(--value-field "$CLIENT_VALUE_FIELD")
fi
if [[ -n "$SSE_EXPORT_POLICY_CONFIG" ]]; then
  CLIENT_EXPORT_CMD+=(--policy-config "$SSE_EXPORT_POLICY_CONFIG")
elif [[ "$UNSAFE_ALLOW_NO_SSE_EXPORT_POLICY" == "1" ]]; then
  CLIENT_EXPORT_CMD+=(--unsafe-allow-no-policy)
fi
if [[ -n "$CLIENT_SSE_KEYWORD" ]]; then
  CLIENT_EXPORT_CMD+=(--sse-keyword "$CLIENT_SSE_KEYWORD" --record-id-field "$CLIENT_RECORD_ID_FIELD" --record-id-format "$CLIENT_RECORD_ID_FORMAT")
  if [[ -n "$CLIENT_SSE_SID" ]]; then
    CLIENT_EXPORT_CMD+=(--sid "$CLIENT_SSE_SID")
  fi
  if [[ -n "$CLIENT_SSE_SNAME" ]]; then
    CLIENT_EXPORT_CMD+=(--sname "$CLIENT_SSE_SNAME")
  fi
fi
for f in "${CLIENT_FILTERS[@]}"; do
  CLIENT_EXPORT_CMD+=(--filter "$f")
done
if [[ "$SSE_EXPORT_HANDOFF_MODE" == "fifo" ]]; then
  start_command_with_status CLIENT_EXPORT_PID "$CLIENT_EXPORT_STATUS_FILE" "$SSE_DIR" "${CLIENT_EXPORT_CMD[@]}"
else
  (cd "$SSE_DIR" && "${CLIENT_EXPORT_CMD[@]}")
fi

if [[ "$SSE_EXPORT_HANDOFF_MODE" == "file" ]]; then
  python3 "$VALIDATE_TABULAR_CONTRACT_PY" \
    --contract bridge-input-csv \
    --path "$SERVER_EXPORT" \
    --role server \
    --join-key-field "$SERVER_JOIN_KEY_FIELD"
  CLIENT_BRIDGE_CONTRACT_CMD=(
    python3 "$VALIDATE_TABULAR_CONTRACT_PY"
    --contract bridge-input-csv
    --path "$CLIENT_EXPORT"
    --role client
    --join-key-field "$CLIENT_JOIN_KEY_FIELD"
  )
  if [[ -n "$CLIENT_VALUE_FIELD" ]]; then
    CLIENT_BRIDGE_CONTRACT_CMD+=(--value-field "$CLIENT_VALUE_FIELD")
  fi
  "${CLIENT_BRIDGE_CONTRACT_CMD[@]}"
fi

if [[ "$SSE_EXPORT_HANDOFF_MODE" == "file" && -f "$SSE_EXPORT_AUDIT_LOG" ]]; then
  log "Verifying bridge input file hashes against SSE export audit (input commitment check)"
  ACTUAL_SERVER_HASH="$(sha256sum "$SERVER_EXPORT" | cut -d' ' -f1)"
  ACTUAL_CLIENT_HASH="$(sha256sum "$CLIENT_EXPORT" | cut -d' ' -f1)"
  AUDIT_SERVER_HASH="$(python3 - "$SSE_EXPORT_AUDIT_LOG" <<'PYEOF'
import json, sys
lines = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
rec = next((l for l in reversed(lines) if l.get("role") == "server"), {})
print(rec.get("output_hash", ""))
PYEOF
)"
  AUDIT_CLIENT_HASH="$(python3 - "$SSE_EXPORT_AUDIT_LOG" <<'PYEOF'
import json, sys
lines = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
rec = next((l for l in reversed(lines) if l.get("role") == "client"), {})
print(rec.get("output_hash", ""))
PYEOF
)"
  if [[ -z "$AUDIT_SERVER_HASH" || -z "$AUDIT_CLIENT_HASH" ]]; then
    log "WARN: output_hash not found in SSE export audit — skipping input commitment check"
  elif [[ "$ACTUAL_SERVER_HASH" != "$AUDIT_SERVER_HASH" || "$ACTUAL_CLIENT_HASH" != "$AUDIT_CLIENT_HASH" ]]; then
    die "Input commitment check FAILED: bridge input file hashes do not match SSE export audit. Possible file substitution. Aborting."
  else
    log "Input commitment check PASSED: bridge input hashes match SSE export audit"
  fi
fi

log "Stage2 bridge prepare-job"
read -r -a BRIDGE_BIN_ARR <<< "$BRIDGE_BIN"
[[ ${#BRIDGE_BIN_ARR[@]} -gt 0 ]] || die "BRIDGE_BIN resolved to an empty command"
BRIDGE_CMD=("${BRIDGE_BIN_ARR[@]}" prepare-job
  --server-input "$SERVER_EXPORT"
  --server-input-format csv
  --server-join-key-column "$SERVER_JOIN_KEY_FIELD"
  --server-normalizer "$SERVER_NORMALIZER"
  --client-input "$CLIENT_EXPORT"
  --client-input-format csv
  --client-join-key-column "$CLIENT_JOIN_KEY_FIELD"
  --client-value-mode "$CLIENT_VALUE_MODE"
  --client-normalizer "$CLIENT_NORMALIZER"
  --out-dir "$BRIDGE_JOB_DIR"
  --job-id "$JOB_ID"
  --token-scope "$TOKEN_SCOPE"
  --token-key-version "$TOKEN_KEY_VERSION"
  --audit-log "$BRIDGE_JOB_DIR/bridge_audit.jsonl"
)
if [[ "$PRODUCTION_MODE" == "1" ]]; then
  BRIDGE_CMD+=(--production-mode)
fi
if [[ -n "$CLIENT_VALUE_FIELD" ]]; then
  BRIDGE_CMD+=(--client-value-column "$CLIENT_VALUE_FIELD")
fi
if [[ -n "$TOKEN_SECRET" ]]; then
  BRIDGE_CMD+=(--token-secret "$TOKEN_SECRET")
else
  BRIDGE_CMD+=(--token-secret-env "$TOKEN_SECRET_ENV")
fi
BRIDGE_RC=0
if [[ "$SSE_EXPORT_HANDOFF_MODE" == "fifo" ]]; then
  start_command_with_status BRIDGE_PID "$BRIDGE_STATUS_FILE" "$BRIDGE_DIR" "${BRIDGE_CMD[@]}"
  while true; do
    if SERVER_EXPORT_RC="$(read_status_file "$SERVER_EXPORT_STATUS_FILE")"; then
      if [[ "$SERVER_EXPORT_RC" -ne 0 ]]; then
        [[ -n "$BRIDGE_PID" ]] && kill "$BRIDGE_PID" 2>/dev/null || true
        [[ -n "$CLIENT_EXPORT_PID" ]] && kill "$CLIENT_EXPORT_PID" 2>/dev/null || true
        wait "$BRIDGE_PID" 2>/dev/null || true
        wait "$CLIENT_EXPORT_PID" 2>/dev/null || true
        cleanup_handoff
        exit "$SERVER_EXPORT_RC"
      fi
    fi
    if CLIENT_EXPORT_RC="$(read_status_file "$CLIENT_EXPORT_STATUS_FILE")"; then
      if [[ "$CLIENT_EXPORT_RC" -ne 0 ]]; then
        [[ -n "$BRIDGE_PID" ]] && kill "$BRIDGE_PID" 2>/dev/null || true
        [[ -n "$SERVER_EXPORT_PID" ]] && kill "$SERVER_EXPORT_PID" 2>/dev/null || true
        wait "$BRIDGE_PID" 2>/dev/null || true
        wait "$SERVER_EXPORT_PID" 2>/dev/null || true
        cleanup_handoff
        exit "$CLIENT_EXPORT_RC"
      fi
    fi
    if BRIDGE_RC="$(read_status_file "$BRIDGE_STATUS_FILE")"; then
      wait "$BRIDGE_PID" 2>/dev/null || true
      break
    fi
    sleep 0.1
  done
  if [[ "$BRIDGE_RC" -ne 0 ]]; then
    [[ -n "$SERVER_EXPORT_PID" ]] && kill "$SERVER_EXPORT_PID" 2>/dev/null || true
    [[ -n "$CLIENT_EXPORT_PID" ]] && kill "$CLIENT_EXPORT_PID" 2>/dev/null || true
    wait "$SERVER_EXPORT_PID" 2>/dev/null || true
    wait "$CLIENT_EXPORT_PID" 2>/dev/null || true
    cleanup_handoff
    exit "$BRIDGE_RC"
  fi
  wait "$SERVER_EXPORT_PID"
  SERVER_EXPORT_RC=$?
  wait "$CLIENT_EXPORT_PID"
  CLIENT_EXPORT_RC=$?
  [[ "$SERVER_EXPORT_RC" -eq 0 ]] || exit "$SERVER_EXPORT_RC"
  [[ "$CLIENT_EXPORT_RC" -eq 0 ]] || exit "$CLIENT_EXPORT_RC"
  SERVER_EXPORT_PID=""
  CLIENT_EXPORT_PID=""
  rm -f "$SERVER_EXPORT" "$CLIENT_EXPORT" \
    "$SERVER_EXPORT_STATUS_FILE" "$CLIENT_EXPORT_STATUS_FILE" "$BRIDGE_STATUS_FILE"
else
  (cd "$BRIDGE_DIR" && "${BRIDGE_CMD[@]}") || BRIDGE_RC=$?
  [[ "$BRIDGE_RC" -eq 0 ]] || exit "$BRIDGE_RC"
fi
cleanup_persisted_sse_export_handoff_files

python3 "$VALIDATE_JSON_CONTRACT_PY" \
  --schema "$REPO_ROOT/schemas/sse_bridge_export_audit.schema.json" \
  --jsonl "$SSE_EXPORT_AUDIT_LOG"

if [[ -n "$RECORD_RECOVERY_SERVICE_AUDIT_LOG" && -f "$RECORD_RECOVERY_SERVICE_AUDIT_LOG" ]]; then
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/sse_record_recovery_service_audit.schema.json" \
    --jsonl "$RECORD_RECOVERY_SERVICE_AUDIT_LOG"
fi
if [[ -n "$RECORD_RECOVERY_SERVICE_HEALTH_JSON" && -f "$RECORD_RECOVERY_SERVICE_HEALTH_JSON" ]]; then
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/record_recovery_service_health.schema.json" \
    --json "$RECORD_RECOVERY_SERVICE_HEALTH_JSON"
fi
if [[ -n "$RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON" && -f "$RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON" ]]; then
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/record_recovery_service_config.schema.json" \
    --json "$RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON"
fi

python3 "$VALIDATE_JSON_CONTRACT_PY" \
  --schema "$REPO_ROOT/schemas/bridge_job_meta.schema.json" \
  --json "$BRIDGE_JOB_DIR/job_meta.json"

python3 "$VALIDATE_JSON_CONTRACT_PY" \
  --schema "$REPO_ROOT/schemas/bridge_audit.schema.json" \
  --jsonl "$BRIDGE_JOB_DIR/bridge_audit.jsonl"

python3 "$VALIDATE_BRIDGE_JOB_PY" --job-dir "$BRIDGE_JOB_DIR"

python3 "$VALIDATE_TABULAR_CONTRACT_PY" \
  --contract pjc-server-csv \
  --path "$BRIDGE_JOB_DIR/server.csv"
python3 "$VALIDATE_TABULAR_CONTRACT_PY" \
  --contract pjc-client-csv \
  --path "$BRIDGE_JOB_DIR/client.csv"

log "Stage3 a-psi run"
cp "$BRIDGE_JOB_DIR/job_meta.json" "$APSI_JOB_DIR/job_meta.json"
PJC_STARTED_MS="$(date +%s%3N)"
PJC_RC=0
(
  cd "$APSI_DIR"
  JOB_ID="$JOB_ID" \
  OUT_DIR="$APSI_JOB_DIR" \
  SERVER_CSV="$BRIDGE_JOB_DIR/server.csv" \
  CLIENT_CSV="$BRIDGE_JOB_DIR/client.csv" \
  PJC_BIN_DIR="$PJC_BIN_DIR" \
  bash "$RUN_PJC_SH"
) || PJC_RC=$?
PJC_ENDED_MS="$(date +%s%3N)"
PJC_DURATION_MS="$((PJC_ENDED_MS - PJC_STARTED_MS))"

PJC_AUDIT_CMD=(
  python3 "$WRITE_PJC_AUDIT_PY"
  --audit-log "$PJC_AUDIT_LOG"
  --job-id "$JOB_ID"
  --out-dir "$APSI_JOB_DIR"
  --server-csv "$BRIDGE_JOB_DIR/server.csv"
  --client-csv "$BRIDGE_JOB_DIR/client.csv"
  --server-log "$APSI_JOB_DIR/server.log"
  --client-log "$APSI_JOB_DIR/client.log"
  --result-file "$APSI_JOB_DIR/attribution_result.json"
  --duration-ms "$PJC_DURATION_MS"
)
if [[ "$PJC_RC" -eq 0 ]]; then
  "${PJC_AUDIT_CMD[@]}" \
    --decision allow \
    --reason-code ok \
    --reason ok
else
  "${PJC_AUDIT_CMD[@]}" \
    --decision deny \
    --reason-code pjc_run_failed \
    --reason "pjc run failed" \
    --exit-code "$PJC_RC"
fi

python3 "$VALIDATE_JSON_CONTRACT_PY" \
  --schema "$REPO_ROOT/schemas/pjc_audit.schema.json" \
  --jsonl "$PJC_AUDIT_LOG"

[[ "$PJC_RC" -eq 0 ]] || exit "$PJC_RC"

log "Stage4 policy release"
POLICY_RELEASE_CMD=(
  python3 "$POLICY_PY"
  --job-dir "$APSI_JOB_DIR"
  --caller "$CALLER"
  --k "$K_THRESHOLD"
  --n "$RATE_N"
)
if [[ "$DENY_DUPLICATE_QUERY" == "1" ]]; then
  POLICY_RELEASE_CMD+=(--deny-duplicate-query)
fi
(
  cd "$APSI_DIR"
  "${POLICY_RELEASE_CMD[@]}"
)

python3 "$VALIDATE_JSON_CONTRACT_PY" \
  --schema "$REPO_ROOT/schemas/public_report.schema.json" \
  --json "$APSI_JOB_DIR/public_report.json"

python3 "$VALIDATE_JSON_CONTRACT_PY" \
  --schema "$REPO_ROOT/schemas/policy_audit.schema.json" \
  --jsonl "$APSI_JOB_DIR/audit_log.jsonl"

BUILD_AUDIT_CHAIN_CMD=(
  python3 "$BUILD_AUDIT_CHAIN_PY"
  --out-base "$OUT_BASE"
  --job-id "$JOB_ID"
)
if [[ -n "$RECORD_RECOVERY_SERVICE_AUDIT_LOG" ]]; then
  BUILD_AUDIT_CHAIN_CMD+=(--record-recovery-service-audit "$RECORD_RECOVERY_SERVICE_AUDIT_LOG")
fi
BUILD_AUDIT_CHAIN_CMD+=(--pjc-audit "$PJC_AUDIT_LOG")
MAINLINE_CONTRACT_CMD=(
  python3 "$CHECK_MAINLINE_CONTRACT_PY"
  --out-base "$OUT_BASE"
  --job-id "$JOB_ID"
  --output "$OUT_BASE/mainline_contract_check.json"
)
if [[ "$CLEANUP_SSE_EXPORT_HANDOFF_FILES_AFTER_BRIDGE" != "1" ]]; then
  MAINLINE_CONTRACT_CMD+=(--allow-retained-managed-handoff)
  MAINLINE_CONTRACT_CMD+=(--retained-managed-handoff-reason "$HANDOFF_RETENTION_REASON")
fi
"${MAINLINE_CONTRACT_CMD[@]}"

python3 "$VALIDATE_JSON_CONTRACT_PY" \
  --schema "$REPO_ROOT/schemas/mainline_contract_check.schema.json" \
  --json "$OUT_BASE/mainline_contract_check.json"

"${BUILD_AUDIT_CHAIN_CMD[@]}"

python3 "$VALIDATE_JSON_CONTRACT_PY" \
  --schema "$REPO_ROOT/schemas/audit_chain.schema.json" \
  --json "$OUT_BASE/audit_chain.json"

SEAL_CMD=(
  python3 "$SEAL_AUDIT_ARTIFACT_PY"
  --input "$OUT_BASE/audit_chain.json"
  --out "$OUT_BASE/audit_chain.seal.json"
  --job-id "$JOB_ID"
)
if [[ -n "$AUDIT_SEAL_KEY_ENV" ]]; then
  SEAL_CMD+=(--hmac-key-env "$AUDIT_SEAL_KEY_ENV")
fi
"${SEAL_CMD[@]}"

python3 "$VALIDATE_JSON_CONTRACT_PY" \
  --schema "$REPO_ROOT/schemas/audit_seal.schema.json" \
  --json "$OUT_BASE/audit_chain.seal.json"

if [[ -n "$AUDIT_ARCHIVE_DIR" ]]; then
  AUDIT_ARCHIVE_CMD=(
    python3 "$ARCHIVE_AUDIT_BUNDLE_PY"
    --audit-chain "$OUT_BASE/audit_chain.json"
    --audit-seal "$OUT_BASE/audit_chain.seal.json"
    --archive-dir "$AUDIT_ARCHIVE_DIR"
    --job-id "$JOB_ID"
  )
  if [[ -n "$AUDIT_SEAL_KEY_ENV" ]]; then
    AUDIT_ARCHIVE_CMD+=(--hmac-key-env "$AUDIT_SEAL_KEY_ENV")
  fi
  "${AUDIT_ARCHIVE_CMD[@]}"
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/audit_archive_index.schema.json" \
    --jsonl "$AUDIT_ARCHIVE_DIR/audit_chain_index.jsonl"
fi

log "OK"
log "  sse exports:   $SSE_EXPORT_DIR"
log "  sse audit:     $SSE_EXPORT_AUDIT_LOG"
log "  pjc audit:     $PJC_AUDIT_LOG"
if [[ -n "$TOKEN_SECRET_KEY_NAME" || -n "$TOKEN_SECRET_KEY_ID" ]]; then
  log "  key access audit: $KEY_ACCESS_AUDIT_LOG"
fi
if [[ -n "$TOKEN_SECRET_KEY_NAME" ]]; then
  if [[ -n "$EXTERNAL_KMS_CONFIG" ]]; then
    log "  external KMS endpoint: $EXTERNAL_KMS_ENDPOINT_URL"
    if [[ "$EXTERNAL_KMS_SERVICE_STARTED" == "1" ]]; then
      log "  external KMS log: $EXTERNAL_KMS_LOG"
      log "  external KMS lifecycle audit: $EXTERNAL_KMS_LIFECYCLE_AUDIT_LOG"
    fi
  else
    log "  key agent socket: $KEY_AGENT_SOCKET"
    if [[ "$KEY_AGENT_SERVICE_STARTED" == "1" ]]; then
      log "  key agent log:   $KEY_AGENT_LOG"
    fi
  fi
fi
if [[ "$RECORD_RECOVERY_USE_SERVICE" == "1" ]]; then
  log "  recovery audit: $RECORD_RECOVERY_SERVICE_AUDIT_LOG"
  if [[ -n "$RECORD_RECOVERY_ENDPOINT_URL" ]]; then
    log "  recovery endpoint: $RECORD_RECOVERY_ENDPOINT_URL"
  else
    log "  recovery socket: $RECORD_RECOVERY_SOCKET"
  fi
  if [[ -n "$RECORD_RECOVERY_AUTHZ_CONFIG" ]]; then
    log "  recovery authz config: $RECORD_RECOVERY_AUTHZ_CONFIG"
  fi
  log "  recovery pid file: $RECORD_RECOVERY_SERVICE_PID_FILE"
  log "  recovery ready file: $RECORD_RECOVERY_SERVICE_READY_FILE"
  log "  recovery health: $RECORD_RECOVERY_SERVICE_HEALTH_JSON"
  log "  recovery runtime config: $RECORD_RECOVERY_SERVICE_RUNTIME_CONFIG_JSON"
  if [[ "$RECORD_RECOVERY_SERVICE_STARTED" == "1" ]]; then
    log "  recovery log:   $RECORD_RECOVERY_SERVICE_LOG"
  fi
fi
log "  bridge job:    $BRIDGE_JOB_DIR"
log "  a-psi outputs: $APSI_JOB_DIR"
log "  audit chain:   $OUT_BASE/audit_chain.json"
log "  contract check:$OUT_BASE/mainline_contract_check.json"
log "  audit seal:    $OUT_BASE/audit_chain.seal.json"
if [[ -n "$AUDIT_ARCHIVE_DIR" ]]; then
  log "  audit archive: $AUDIT_ARCHIVE_DIR"
  log "  audit index:   $AUDIT_ARCHIVE_DIR/audit_chain_index.jsonl"
fi
