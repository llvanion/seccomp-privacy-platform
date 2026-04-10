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
TOKEN_SCOPE=""
TOKEN_SECRET="${TOKEN_SECRET:-}"
TOKEN_SECRET_ENV="${TOKEN_SECRET_ENV:-}"
JOB_ID=""
OUT_BASE=""
CALLER="bridge_demo"
K_THRESHOLD="20"
RATE_N="5"
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
  --server-filter field=value        repeatable
  --client-filter field=value        repeatable
  --token-secret <secret>
  --token-secret-env <env>
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
    --server-filter) SERVER_FILTERS+=("$2"); shift 2 ;;
    --client-filter) CLIENT_FILTERS+=("$2"); shift 2 ;;
    --token-scope) TOKEN_SCOPE="$2"; shift 2 ;;
    --token-secret) TOKEN_SECRET="$2"; shift 2 ;;
    --token-secret-env) TOKEN_SECRET_ENV="$2"; shift 2 ;;
    --job-id) JOB_ID="$2"; shift 2 ;;
    --out-base) OUT_BASE="$2"; shift 2 ;;
    --caller) CALLER="$2"; shift 2 ;;
    --k) K_THRESHOLD="$2"; shift 2 ;;
    --n) RATE_N="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown arg: $1" ;;
  esac
done

[[ -n "$SERVER_SOURCE" ]] || die "--server-source required"
[[ -n "$CLIENT_SOURCE" ]] || die "--client-source required"
[[ -n "$SERVER_JOIN_KEY_FIELD" ]] || die "--server-join-key-field required"
[[ -n "$CLIENT_JOIN_KEY_FIELD" ]] || die "--client-join-key-field required"
[[ -n "$CLIENT_VALUE_FIELD" ]] || [[ "$CLIENT_VALUE_MODE" == "count" ]] || die "--client-value-field required for raw-int"
[[ -n "$TOKEN_SCOPE" ]] || die "--token-scope required"
[[ -n "$JOB_ID" ]] || die "--job-id required"
[[ -n "$OUT_BASE" ]] || die "--out-base required"
[[ -x "$SSE_PY" ]] || die "missing SSE python: $SSE_PY"
[[ -f "$RUN_PJC_SH" ]] || die "missing a-psi runner: $RUN_PJC_SH"
[[ -f "$POLICY_PY" ]] || die "missing policy script: $POLICY_PY"
[[ -f "$VALIDATE_BRIDGE_JOB_PY" ]] || die "missing validate script: $VALIDATE_BRIDGE_JOB_PY"

if [[ -n "$TOKEN_SECRET" && -n "$TOKEN_SECRET_ENV" ]]; then
  die "use either --token-secret or --token-secret-env"
fi
if [[ -z "$TOKEN_SECRET" && -z "$TOKEN_SECRET_ENV" ]]; then
  die "set --token-secret or --token-secret-env"
fi

OUT_BASE="$(mkdir -p "$OUT_BASE" && cd "$OUT_BASE" && pwd)"
SSE_EXPORT_DIR="$OUT_BASE/sse_exports"
BRIDGE_JOB_DIR="$OUT_BASE/bridge_job"
APSI_JOB_DIR="$OUT_BASE/a_psi_run"
mkdir -p "$SSE_EXPORT_DIR" "$BRIDGE_JOB_DIR" "$APSI_JOB_DIR"

SERVER_EXPORT="$SSE_EXPORT_DIR/server.csv"
CLIENT_EXPORT="$SSE_EXPORT_DIR/client.csv"

log "Stage1 SSE export"
SERVER_EXPORT_CMD=(
  "$SSE_PY" run_client.py export-bridge-records
  --source-path "$SERVER_SOURCE"
  --out-path "$SERVER_EXPORT"
  --role server
  --source-format "$SERVER_SOURCE_FORMAT"
  --out-format csv
  --join-key-field "$SERVER_JOIN_KEY_FIELD"
)
for f in "${SERVER_FILTERS[@]}"; do
  SERVER_EXPORT_CMD+=(--filter "$f")
done
(cd "$SSE_DIR" && "${SERVER_EXPORT_CMD[@]}")

CLIENT_EXPORT_CMD=(
  "$SSE_PY" run_client.py export-bridge-records
  --source-path "$CLIENT_SOURCE"
  --out-path "$CLIENT_EXPORT"
  --role client
  --source-format "$CLIENT_SOURCE_FORMAT"
  --out-format csv
  --join-key-field "$CLIENT_JOIN_KEY_FIELD"
)
if [[ -n "$CLIENT_VALUE_FIELD" ]]; then
  CLIENT_EXPORT_CMD+=(--value-field "$CLIENT_VALUE_FIELD")
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
)
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
log "  bridge job:    $BRIDGE_JOB_DIR"
log "  a-psi outputs: $APSI_JOB_DIR"
