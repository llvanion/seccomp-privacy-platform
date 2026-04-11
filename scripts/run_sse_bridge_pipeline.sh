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
RESOLVE_KEY_ACCESS_PY="${RESOLVE_KEY_ACCESS_PY:-$REPO_ROOT/scripts/resolve_key_access.py}"
SEAL_AUDIT_ARTIFACT_PY="${SEAL_AUDIT_ARTIFACT_PY:-$REPO_ROOT/scripts/seal_audit_artifact.py}"
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
RECORD_RECOVERY_AUTH_ENV=""
RECORD_RECOVERY_SERVICE_AUDIT_LOG=""
RECORD_RECOVERY_SERVICE_LOG=""
RECORD_RECOVERY_SERVICE_MODE="auto"
RECORD_RECOVERY_SOCKET_MODE="600"
TOKEN_SCOPE=""
TOKEN_SECRET="${TOKEN_SECRET:-}"
TOKEN_SECRET_ENV="${TOKEN_SECRET_ENV:-}"
TOKEN_SECRET_KEY_ID=""
TOKEN_KEY_VERSION="1"
KEY_MANIFEST=""
KEY_ACCESS_AUDIT_LOG=""
AUDIT_SEAL_KEY_ENV=""
JOB_ID=""
OUT_BASE=""
CALLER="bridge_demo"
K_THRESHOLD="20"
RATE_N="5"
DENY_DUPLICATE_QUERY="0"
SSE_EXPORT_POLICY_CONFIG=""
SSE_EXPORT_AUDIT_LOG=""
SSE_EXPORT_HANDOFF_MODE="file"
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
  --record-recovery-auth-env <env> optional env var containing the record recovery service auth token
  --record-recovery-service-audit-log <path> optional service audit log validated after export
  --record-recovery-service-log <path> optional stdout/stderr log for auto-started recovery service
  --record-recovery-service-mode auto|manual|subprocess default: auto; applies when encrypted record stores are used
  --record-recovery-socket-mode <octal> filesystem mode for the recovery Unix socket, default: 600
  --server-filter field=value        repeatable
  --client-filter field=value        repeatable
  --token-secret <secret>
  --token-secret-env <env>
  --token-secret-key-id <id>       resolve token secret env from --key-manifest
  --token-key-version <version>    default: 1; overridden by --token-secret-key-id
  --key-manifest <path>            local key manifest for key-id resolution
  --key-access-audit-log <path>    default: <out-base>/key_access_audit.jsonl
  --audit-seal-key-env <env>       optional env var used to HMAC-seal audit_chain.json
  --sse-export-policy-config <path> SSE export policy config
  --sse-export-audit-log <path>     default: <out-base>/sse_exports/export_audit.jsonl
  --sse-export-handoff-mode file|fifo default: file; fifo streams plaintext handoff through named pipes
  --unsafe-allow-no-sse-export-policy allow ad-hoc export without policy config
  --production-mode                 forbid command-line token secrets in bridge
  --caller <id>                      policy caller, default: bridge_demo
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
    --record-recovery-auth-env) RECORD_RECOVERY_AUTH_ENV="$2"; shift 2 ;;
    --record-recovery-service-audit-log) RECORD_RECOVERY_SERVICE_AUDIT_LOG="$2"; shift 2 ;;
    --record-recovery-service-log) RECORD_RECOVERY_SERVICE_LOG="$2"; shift 2 ;;
    --record-recovery-service-mode) RECORD_RECOVERY_SERVICE_MODE="$2"; shift 2 ;;
    --record-recovery-socket-mode) RECORD_RECOVERY_SOCKET_MODE="$2"; shift 2 ;;
    --server-filter) SERVER_FILTERS+=("$2"); shift 2 ;;
    --client-filter) CLIENT_FILTERS+=("$2"); shift 2 ;;
    --token-scope) TOKEN_SCOPE="$2"; shift 2 ;;
    --token-secret) TOKEN_SECRET="$2"; shift 2 ;;
    --token-secret-env) TOKEN_SECRET_ENV="$2"; shift 2 ;;
    --token-secret-key-id) TOKEN_SECRET_KEY_ID="$2"; shift 2 ;;
    --token-key-version) TOKEN_KEY_VERSION="$2"; shift 2 ;;
    --key-manifest) KEY_MANIFEST="$2"; shift 2 ;;
    --key-access-audit-log) KEY_ACCESS_AUDIT_LOG="$2"; shift 2 ;;
    --audit-seal-key-env) AUDIT_SEAL_KEY_ENV="$2"; shift 2 ;;
    --sse-export-policy-config) SSE_EXPORT_POLICY_CONFIG="$2"; shift 2 ;;
    --sse-export-audit-log) SSE_EXPORT_AUDIT_LOG="$2"; shift 2 ;;
    --sse-export-handoff-mode) SSE_EXPORT_HANDOFF_MODE="$2"; shift 2 ;;
    --unsafe-allow-no-sse-export-policy) UNSAFE_ALLOW_NO_SSE_EXPORT_POLICY="1"; shift ;;
    --production-mode) PRODUCTION_MODE="1"; shift ;;
    --job-id) JOB_ID="$2"; shift 2 ;;
    --out-base) OUT_BASE="$2"; shift 2 ;;
    --caller) CALLER="$2"; shift 2 ;;
    --k) K_THRESHOLD="$2"; shift 2 ;;
    --n) RATE_N="$2"; shift 2 ;;
    --deny-duplicate-query) DENY_DUPLICATE_QUERY="1"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown arg: $1" ;;
  esac
done

[[ -n "$SERVER_SOURCE" || -n "$SERVER_RECORD_STORE_PATH" ]] || die "--server-source or --server-record-store-path required"
[[ -n "$CLIENT_SOURCE" || -n "$CLIENT_RECORD_STORE_PATH" ]] || die "--client-source or --client-record-store-path required"
[[ -n "$SERVER_JOIN_KEY_FIELD" ]] || die "--server-join-key-field required"
[[ -n "$CLIENT_JOIN_KEY_FIELD" ]] || die "--client-join-key-field required"
[[ -n "$CLIENT_VALUE_FIELD" ]] || [[ "$CLIENT_VALUE_MODE" == "count" ]] || die "--client-value-field required for raw-int"
[[ -n "$TOKEN_SCOPE" ]] || die "--token-scope required"
[[ -n "$JOB_ID" ]] || die "--job-id required"
[[ -n "$OUT_BASE" ]] || die "--out-base required"
[[ "$SSE_EXPORT_HANDOFF_MODE" == "file" || "$SSE_EXPORT_HANDOFF_MODE" == "fifo" ]] || die "--sse-export-handoff-mode must be file or fifo"
[[ -n "$SSE_EXPORT_POLICY_CONFIG" || "$UNSAFE_ALLOW_NO_SSE_EXPORT_POLICY" == "1" ]] || die "--sse-export-policy-config required unless --unsafe-allow-no-sse-export-policy is set"
[[ -z "$SERVER_SSE_KEYWORD" || -n "$SERVER_RECORD_ID_FIELD" ]] || die "--server-record-id-field required with --server-sse-keyword"
[[ -z "$CLIENT_SSE_KEYWORD" || -n "$CLIENT_RECORD_ID_FIELD" ]] || die "--client-record-id-field required with --client-sse-keyword"
[[ -z "$SERVER_RECORD_STORE_PATH" || -n "$SERVER_SSE_KEYWORD" ]] || die "--server-record-store-path requires --server-sse-keyword"
[[ -z "$CLIENT_RECORD_STORE_PATH" || -n "$CLIENT_SSE_KEYWORD" ]] || die "--client-record-store-path requires --client-sse-keyword"
[[ -z "$SERVER_RECORD_STORE_PATH" || -n "$SERVER_RECORD_STORE_KEY_ENV" ]] || die "--server-record-store-key-env required with --server-record-store-path"
[[ -z "$CLIENT_RECORD_STORE_PATH" || -n "$CLIENT_RECORD_STORE_KEY_ENV" ]] || die "--client-record-store-key-env required with --client-record-store-path"
[[ -z "$RECORD_RECOVERY_AUTH_ENV" || -n "$RECORD_RECOVERY_SOCKET" ]] || die "--record-recovery-auth-env requires --record-recovery-socket"
[[ "$RECORD_RECOVERY_SERVICE_MODE" == "auto" || "$RECORD_RECOVERY_SERVICE_MODE" == "manual" || "$RECORD_RECOVERY_SERVICE_MODE" == "subprocess" ]] || die "--record-recovery-service-mode must be auto, manual, or subprocess"
[[ "$RECORD_RECOVERY_SOCKET_MODE" =~ ^[0-7]{3,4}$ ]] || die "--record-recovery-socket-mode must be octal like 600 or 0600"
[[ -x "$SSE_PY" ]] || die "missing SSE python: $SSE_PY"
[[ -f "$RUN_PJC_SH" ]] || die "missing a-psi runner: $RUN_PJC_SH"
[[ -f "$POLICY_PY" ]] || die "missing policy script: $POLICY_PY"
[[ -f "$VALIDATE_BRIDGE_JOB_PY" ]] || die "missing validate script: $VALIDATE_BRIDGE_JOB_PY"
[[ -f "$VALIDATE_PIPELINE_POLICY_PY" ]] || die "missing pipeline policy validator: $VALIDATE_PIPELINE_POLICY_PY"
[[ -f "$VALIDATE_JSON_CONTRACT_PY" ]] || die "missing JSON contract validator: $VALIDATE_JSON_CONTRACT_PY"
[[ -f "$VALIDATE_TABULAR_CONTRACT_PY" ]] || die "missing tabular contract validator: $VALIDATE_TABULAR_CONTRACT_PY"
[[ -f "$BUILD_AUDIT_CHAIN_PY" ]] || die "missing audit chain builder: $BUILD_AUDIT_CHAIN_PY"
[[ -f "$RESOLVE_KEY_ACCESS_PY" ]] || die "missing key access resolver: $RESOLVE_KEY_ACCESS_PY"
[[ -f "$SEAL_AUDIT_ARTIFACT_PY" ]] || die "missing audit seal script: $SEAL_AUDIT_ARTIFACT_PY"

if [[ -n "$TOKEN_SECRET_KEY_ID" ]]; then
  [[ -n "$KEY_MANIFEST" ]] || die "--token-secret-key-id requires --key-manifest"
fi
SECRET_METHODS=0
[[ -n "$TOKEN_SECRET" ]] && SECRET_METHODS=$((SECRET_METHODS + 1))
[[ -n "$TOKEN_SECRET_ENV" ]] && SECRET_METHODS=$((SECRET_METHODS + 1))
[[ -n "$TOKEN_SECRET_KEY_ID" ]] && SECRET_METHODS=$((SECRET_METHODS + 1))
if [[ "$SECRET_METHODS" -gt 1 ]]; then
  die "use only one of --token-secret, --token-secret-env, or --token-secret-key-id"
fi
if [[ "$SECRET_METHODS" -eq 0 ]]; then
  die "set --token-secret, --token-secret-env, or --token-secret-key-id"
fi
if [[ "$PRODUCTION_MODE" == "1" && -n "$TOKEN_SECRET" ]]; then
  die "--token-secret is forbidden in --production-mode; use --token-secret-env"
fi

if [[ -n "$SSE_EXPORT_POLICY_CONFIG" ]]; then
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/sse_export_policy.schema.json" \
    --json "$SSE_EXPORT_POLICY_CONFIG"
  python3 "$VALIDATE_PIPELINE_POLICY_PY" \
    --policy-config "$SSE_EXPORT_POLICY_CONFIG" \
    --caller "$CALLER" \
    --require-bridge \
    --require-pjc \
    --require-release
fi

OUT_BASE="$(mkdir -p "$OUT_BASE" && cd "$OUT_BASE" && pwd)"
SSE_EXPORT_DIR="$OUT_BASE/sse_exports"
BRIDGE_JOB_DIR="$OUT_BASE/bridge_job"
APSI_JOB_DIR="$OUT_BASE/a_psi_run"
mkdir -p "$SSE_EXPORT_DIR" "$BRIDGE_JOB_DIR" "$APSI_JOB_DIR"

if [[ "$SSE_EXPORT_HANDOFF_MODE" == "fifo" ]]; then
  SERVER_EXPORT="$SSE_EXPORT_DIR/server.fifo"
  CLIENT_EXPORT="$SSE_EXPORT_DIR/client.fifo"
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
if [[ -z "$RECORD_RECOVERY_SERVICE_AUDIT_LOG" ]]; then
  RECORD_RECOVERY_SERVICE_AUDIT_LOG="$SSE_EXPORT_DIR/record_recovery_service_audit.jsonl"
fi
if [[ -z "$RECORD_RECOVERY_SERVICE_LOG" ]]; then
  RECORD_RECOVERY_SERVICE_LOG="$SSE_EXPORT_DIR/record_recovery_service.log"
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
  TOKEN_SECRET_ENV="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["env"])' <<< "$KEY_RESOLUTION_JSON")"
  TOKEN_KEY_VERSION="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["key_version"])' <<< "$KEY_RESOLUTION_JSON")"
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/key_access_audit.schema.json" \
    --jsonl "$KEY_ACCESS_AUDIT_LOG"
fi

SERVER_EXPORT_PID=""
CLIENT_EXPORT_PID=""
RECORD_RECOVERY_SERVICE_PID=""
RECORD_RECOVERY_SERVICE_STARTED="0"
RECORD_RECOVERY_USE_SERVICE="0"
RECORD_RECOVERY_ROOT_ARGS=()
RECORD_RECOVERY_SERVICE_PID_FILE=""
RECORD_RECOVERY_SERVICE_READY_FILE=""
BRIDGE_BIN_ARR=()

abspath_parent_dir() {
  local path="$1"
  (cd "$(dirname "$path")" && pwd)
}

append_record_store_root() {
  local record_store_path="$1"
  [[ -n "$record_store_path" ]] || return 0
  RECORD_RECOVERY_ROOT_ARGS+=(--allowed-record-store-root "$(abspath_parent_dir "$record_store_path")")
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

default_record_recovery_socket() {
  python3 -c 'import hashlib, sys; seed="|".join(sys.argv[1:]); print(f"/tmp/seccomp_rr_{hashlib.sha256(seed.encode()).hexdigest()[:16]}.sock")' "$OUT_BASE" "$JOB_ID" "$CALLER"
}

start_record_recovery_service() {
  [[ "$RECORD_RECOVERY_USE_SERVICE" == "1" ]] || return 0
  if [[ "$RECORD_RECOVERY_SERVICE_MODE" == "subprocess" ]]; then
    return 0
  fi
  if [[ "$RECORD_RECOVERY_SERVICE_MODE" == "manual" ]]; then
    [[ -n "$RECORD_RECOVERY_SOCKET" ]] || die "--record-recovery-socket required when --record-recovery-service-mode=manual"
    return 0
  fi

  [[ -n "$RECORD_RECOVERY_SOCKET" ]] || RECORD_RECOVERY_SOCKET="$(default_record_recovery_socket)"
  [[ -n "$RECORD_RECOVERY_AUTH_ENV" ]] || RECORD_RECOVERY_AUTH_ENV="SSE_RECORD_RECOVERY_AUTH_TOKEN"
  if [[ -z "${!RECORD_RECOVERY_AUTH_ENV:-}" ]]; then
    printf -v "$RECORD_RECOVERY_AUTH_ENV" '%s' "$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    export "$RECORD_RECOVERY_AUTH_ENV"
  fi

  RECORD_RECOVERY_ROOT_ARGS=(
    --allowed-output-root "$OUT_BASE"
    --allowed-caller "$CALLER"
  )
  RECORD_RECOVERY_SERVICE_PID_FILE="$SSE_EXPORT_DIR/record_recovery_service.pid"
  RECORD_RECOVERY_SERVICE_READY_FILE="$SSE_EXPORT_DIR/record_recovery_service.ready"
  append_record_store_root "$SERVER_RECORD_STORE_PATH"
  append_record_store_root "$CLIENT_RECORD_STORE_PATH"

  local service_cmd=(
    "$SSE_PY" run_client.py serve-record-recovery
    --socket-path "$RECORD_RECOVERY_SOCKET"
    --socket-mode "$RECORD_RECOVERY_SOCKET_MODE"
    --auth-token-env "$RECORD_RECOVERY_AUTH_ENV"
    --audit-log "$RECORD_RECOVERY_SERVICE_AUDIT_LOG"
    --pid-file "$RECORD_RECOVERY_SERVICE_PID_FILE"
    --ready-file "$RECORD_RECOVERY_SERVICE_READY_FILE"
  )
  service_cmd+=("${RECORD_RECOVERY_ROOT_ARGS[@]}")

  rm -f "$RECORD_RECOVERY_SOCKET"
  rm -f "$RECORD_RECOVERY_SERVICE_PID_FILE" "$RECORD_RECOVERY_SERVICE_READY_FILE"
  (cd "$SSE_DIR" && "${service_cmd[@]}") >"$RECORD_RECOVERY_SERVICE_LOG" 2>&1 &
  RECORD_RECOVERY_SERVICE_PID=$!
  RECORD_RECOVERY_SERVICE_STARTED="1"
  wait_for_socket "$RECORD_RECOVERY_SOCKET" || die "record recovery service socket did not become ready: $RECORD_RECOVERY_SOCKET"
  log "Auto-started record recovery service: $RECORD_RECOVERY_SOCKET"
  log "  record recovery service log: $RECORD_RECOVERY_SERVICE_LOG"
}

cleanup_record_recovery_service() {
  if [[ "$RECORD_RECOVERY_SERVICE_STARTED" == "1" ]]; then
    if [[ -n "$RECORD_RECOVERY_SERVICE_PID" ]] && kill -0 "$RECORD_RECOVERY_SERVICE_PID" 2>/dev/null; then
      kill "$RECORD_RECOVERY_SERVICE_PID" 2>/dev/null || true
      wait "$RECORD_RECOVERY_SERVICE_PID" 2>/dev/null || true
    fi
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
    rm -f "$SERVER_EXPORT" "$CLIENT_EXPORT"
  fi
}
cleanup_all() {
  cleanup_handoff
  cleanup_record_recovery_service
}
trap cleanup_all EXIT

if [[ -n "$SERVER_RECORD_STORE_PATH" || -n "$CLIENT_RECORD_STORE_PATH" ]]; then
  if [[ "$RECORD_RECOVERY_SERVICE_MODE" != "subprocess" || -n "$RECORD_RECOVERY_SOCKET" ]]; then
    RECORD_RECOVERY_USE_SERVICE="1"
  fi
fi

start_record_recovery_service

log "Stage1 SSE export"
if [[ "$SSE_EXPORT_HANDOFF_MODE" == "fifo" ]]; then
  rm -f "$SERVER_EXPORT" "$CLIENT_EXPORT"
  mkfifo "$SERVER_EXPORT" "$CLIENT_EXPORT"
  log "Using FIFO SSE export handoff; bridge-ready plaintext will not be persisted in sse_exports"
fi
if [[ "$RECORD_RECOVERY_USE_SERVICE" == "1" && -n "$RECORD_RECOVERY_SOCKET" ]]; then
  log "Using record recovery service socket: $RECORD_RECOVERY_SOCKET"
  if [[ -n "$RECORD_RECOVERY_SERVICE_PID_FILE" ]]; then
    log "  record recovery pid file: $RECORD_RECOVERY_SERVICE_PID_FILE"
  fi
  if [[ -n "$RECORD_RECOVERY_SERVICE_READY_FILE" ]]; then
    log "  record recovery ready file: $RECORD_RECOVERY_SERVICE_READY_FILE"
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
)
if [[ -n "$SERVER_SOURCE" ]]; then
  SERVER_EXPORT_CMD+=(--source-path "$SERVER_SOURCE")
fi
if [[ -n "$SERVER_RECORD_STORE_PATH" ]]; then
  SERVER_EXPORT_CMD+=(--record-store-path "$SERVER_RECORD_STORE_PATH" --record-store-key-env "$SERVER_RECORD_STORE_KEY_ENV")
  if [[ "$RECORD_RECOVERY_USE_SERVICE" == "1" && -n "$RECORD_RECOVERY_SOCKET" ]]; then
    SERVER_EXPORT_CMD+=(--record-recovery-socket "$RECORD_RECOVERY_SOCKET")
    if [[ -n "$RECORD_RECOVERY_AUTH_ENV" ]]; then
      SERVER_EXPORT_CMD+=(--record-recovery-auth-env "$RECORD_RECOVERY_AUTH_ENV")
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
  (cd "$SSE_DIR" && "${SERVER_EXPORT_CMD[@]}") &
  SERVER_EXPORT_PID=$!
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
)
if [[ -n "$CLIENT_SOURCE" ]]; then
  CLIENT_EXPORT_CMD+=(--source-path "$CLIENT_SOURCE")
fi
if [[ -n "$CLIENT_RECORD_STORE_PATH" ]]; then
  CLIENT_EXPORT_CMD+=(--record-store-path "$CLIENT_RECORD_STORE_PATH" --record-store-key-env "$CLIENT_RECORD_STORE_KEY_ENV")
  if [[ "$RECORD_RECOVERY_USE_SERVICE" == "1" && -n "$RECORD_RECOVERY_SOCKET" ]]; then
    CLIENT_EXPORT_CMD+=(--record-recovery-socket "$RECORD_RECOVERY_SOCKET")
    if [[ -n "$RECORD_RECOVERY_AUTH_ENV" ]]; then
      CLIENT_EXPORT_CMD+=(--record-recovery-auth-env "$RECORD_RECOVERY_AUTH_ENV")
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
  (cd "$SSE_DIR" && "${CLIENT_EXPORT_CMD[@]}") &
  CLIENT_EXPORT_PID=$!
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
(cd "$BRIDGE_DIR" && "${BRIDGE_CMD[@]}") || BRIDGE_RC=$?
if [[ "$SSE_EXPORT_HANDOFF_MODE" == "fifo" ]]; then
  if [[ "$BRIDGE_RC" -ne 0 ]]; then
    cleanup_handoff
    exit "$BRIDGE_RC"
  fi
  wait "$SERVER_EXPORT_PID"
  wait "$CLIENT_EXPORT_PID"
  SERVER_EXPORT_PID=""
  CLIENT_EXPORT_PID=""
  rm -f "$SERVER_EXPORT" "$CLIENT_EXPORT"
else
  [[ "$BRIDGE_RC" -eq 0 ]] || exit "$BRIDGE_RC"
fi

python3 "$VALIDATE_JSON_CONTRACT_PY" \
  --schema "$REPO_ROOT/schemas/sse_bridge_export_audit.schema.json" \
  --jsonl "$SSE_EXPORT_AUDIT_LOG"

if [[ -n "$RECORD_RECOVERY_SERVICE_AUDIT_LOG" && -f "$RECORD_RECOVERY_SERVICE_AUDIT_LOG" ]]; then
  python3 "$VALIDATE_JSON_CONTRACT_PY" \
    --schema "$REPO_ROOT/schemas/sse_record_recovery_service_audit.schema.json" \
    --jsonl "$RECORD_RECOVERY_SERVICE_AUDIT_LOG"
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
(
  cd "$APSI_DIR"
  JOB_ID="$JOB_ID" \
  OUT_DIR="$APSI_JOB_DIR" \
  SERVER_CSV="$BRIDGE_JOB_DIR/server.csv" \
  CLIENT_CSV="$BRIDGE_JOB_DIR/client.csv" \
  PJC_BIN_DIR="$PJC_BIN_DIR" \
  bash "$RUN_PJC_SH"
)

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

log "OK"
log "  sse exports:   $SSE_EXPORT_DIR"
log "  sse audit:     $SSE_EXPORT_AUDIT_LOG"
if [[ "$RECORD_RECOVERY_USE_SERVICE" == "1" ]]; then
  log "  recovery audit: $RECORD_RECOVERY_SERVICE_AUDIT_LOG"
  log "  recovery socket: $RECORD_RECOVERY_SOCKET"
  log "  recovery pid file: $RECORD_RECOVERY_SERVICE_PID_FILE"
  log "  recovery ready file: $RECORD_RECOVERY_SERVICE_READY_FILE"
  if [[ "$RECORD_RECOVERY_SERVICE_STARTED" == "1" ]]; then
    log "  recovery log:   $RECORD_RECOVERY_SERVICE_LOG"
  fi
fi
log "  bridge job:    $BRIDGE_JOB_DIR"
log "  a-psi outputs: $APSI_JOB_DIR"
log "  audit chain:   $OUT_BASE/audit_chain.json"
log "  audit seal:    $OUT_BASE/audit_chain.seal.json"
