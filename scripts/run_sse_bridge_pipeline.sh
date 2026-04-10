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
TOKEN_SCOPE=""
TOKEN_SECRET="${TOKEN_SECRET:-}"
TOKEN_SECRET_ENV="${TOKEN_SECRET_ENV:-}"
JOB_ID=""
OUT_BASE=""
CALLER="bridge_demo"
K_THRESHOLD="20"
RATE_N="5"
SSE_EXPORT_POLICY_CONFIG=""
SSE_EXPORT_AUDIT_LOG=""
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
  --server-filter field=value        repeatable
  --client-filter field=value        repeatable
  --token-secret <secret>
  --token-secret-env <env>
  --sse-export-policy-config <path> SSE export policy config
  --sse-export-audit-log <path>     default: <out-base>/sse_exports/export_audit.jsonl
  --unsafe-allow-no-sse-export-policy allow ad-hoc export without policy config
  --production-mode                 forbid command-line token secrets in bridge
  --caller <id>                      policy caller, default: bridge_demo
  --k <int>                          release threshold, default: 20
  --n <int>                          rate limit, default: 5
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
    --server-filter) SERVER_FILTERS+=("$2"); shift 2 ;;
    --client-filter) CLIENT_FILTERS+=("$2"); shift 2 ;;
    --token-scope) TOKEN_SCOPE="$2"; shift 2 ;;
    --token-secret) TOKEN_SECRET="$2"; shift 2 ;;
    --token-secret-env) TOKEN_SECRET_ENV="$2"; shift 2 ;;
    --sse-export-policy-config) SSE_EXPORT_POLICY_CONFIG="$2"; shift 2 ;;
    --sse-export-audit-log) SSE_EXPORT_AUDIT_LOG="$2"; shift 2 ;;
    --unsafe-allow-no-sse-export-policy) UNSAFE_ALLOW_NO_SSE_EXPORT_POLICY="1"; shift ;;
    --production-mode) PRODUCTION_MODE="1"; shift ;;
    --job-id) JOB_ID="$2"; shift 2 ;;
    --out-base) OUT_BASE="$2"; shift 2 ;;
    --caller) CALLER="$2"; shift 2 ;;
    --k) K_THRESHOLD="$2"; shift 2 ;;
    --n) RATE_N="$2"; shift 2 ;;
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
[[ -n "$SSE_EXPORT_POLICY_CONFIG" || "$UNSAFE_ALLOW_NO_SSE_EXPORT_POLICY" == "1" ]] || die "--sse-export-policy-config required unless --unsafe-allow-no-sse-export-policy is set"
[[ -z "$SERVER_SSE_KEYWORD" || -n "$SERVER_RECORD_ID_FIELD" ]] || die "--server-record-id-field required with --server-sse-keyword"
[[ -z "$CLIENT_SSE_KEYWORD" || -n "$CLIENT_RECORD_ID_FIELD" ]] || die "--client-record-id-field required with --client-sse-keyword"
[[ -z "$SERVER_RECORD_STORE_PATH" || -n "$SERVER_SSE_KEYWORD" ]] || die "--server-record-store-path requires --server-sse-keyword"
[[ -z "$CLIENT_RECORD_STORE_PATH" || -n "$CLIENT_SSE_KEYWORD" ]] || die "--client-record-store-path requires --client-sse-keyword"
[[ -z "$SERVER_RECORD_STORE_PATH" || -n "$SERVER_RECORD_STORE_KEY_ENV" ]] || die "--server-record-store-key-env required with --server-record-store-path"
[[ -z "$CLIENT_RECORD_STORE_PATH" || -n "$CLIENT_RECORD_STORE_KEY_ENV" ]] || die "--client-record-store-key-env required with --client-record-store-path"
[[ -x "$SSE_PY" ]] || die "missing SSE python: $SSE_PY"
[[ -f "$RUN_PJC_SH" ]] || die "missing a-psi runner: $RUN_PJC_SH"
[[ -f "$POLICY_PY" ]] || die "missing policy script: $POLICY_PY"
[[ -f "$VALIDATE_BRIDGE_JOB_PY" ]] || die "missing validate script: $VALIDATE_BRIDGE_JOB_PY"
[[ -f "$VALIDATE_PIPELINE_POLICY_PY" ]] || die "missing pipeline policy validator: $VALIDATE_PIPELINE_POLICY_PY"

if [[ -n "$TOKEN_SECRET" && -n "$TOKEN_SECRET_ENV" ]]; then
  die "use either --token-secret or --token-secret-env"
fi
if [[ -z "$TOKEN_SECRET" && -z "$TOKEN_SECRET_ENV" ]]; then
  die "set --token-secret or --token-secret-env"
fi
if [[ "$PRODUCTION_MODE" == "1" && -n "$TOKEN_SECRET" ]]; then
  die "--token-secret is forbidden in --production-mode; use --token-secret-env"
fi

if [[ -n "$SSE_EXPORT_POLICY_CONFIG" ]]; then
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

SERVER_EXPORT="$SSE_EXPORT_DIR/server.csv"
CLIENT_EXPORT="$SSE_EXPORT_DIR/client.csv"
if [[ -z "$SSE_EXPORT_AUDIT_LOG" ]]; then
  SSE_EXPORT_AUDIT_LOG="$SSE_EXPORT_DIR/export_audit.jsonl"
fi

log "Stage1 SSE export"
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
(cd "$SSE_DIR" && "${SERVER_EXPORT_CMD[@]}")

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
(cd "$SSE_DIR" && "${CLIENT_EXPORT_CMD[@]}")

log "Stage2 bridge prepare-job"
BRIDGE_CMD=(cargo run -- prepare-job
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
(cd "$BRIDGE_DIR" && "${BRIDGE_CMD[@]}")

python3 "$VALIDATE_BRIDGE_JOB_PY" --job-dir "$BRIDGE_JOB_DIR"

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
(
  cd "$APSI_DIR"
  python3 "$POLICY_PY" \
    --job-dir "$APSI_JOB_DIR" \
    --caller "$CALLER" \
    --k "$K_THRESHOLD" \
    --n "$RATE_N"
)

log "OK"
log "  sse exports:   $SSE_EXPORT_DIR"
log "  sse audit:     $SSE_EXPORT_AUDIT_LOG"
log "  bridge job:    $BRIDGE_JOB_DIR"
log "  a-psi outputs: $APSI_JOB_DIR"
