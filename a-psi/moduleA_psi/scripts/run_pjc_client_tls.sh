#!/usr/bin/env bash
set -euo pipefail
# Party B: connect to Party A's TLS proxy and run the PJC client.
#
# Architecture:
#   PJC binary → LOCAL_PROXY_PORT (socat, plain) → TLS → Party A:TLS_PORT
#
# Required env / flags:
#   SERVER_HOST   Party A's public IP or hostname
#   CERT_DIR      directory containing ca.crt, client.crt, client.key
#   CLIENT_CSV    path to Party B's tokenised client.csv
#   TLS_PORT      Party A's TLS port (default 10502 — must match server)
#   LOCAL_PROXY_PORT local loopback port socat listens on (default 10503)
#
# Other env vars pass through to run_pjc_client.sh:
#   JOB_ID, OUT_DIR, GRPC_MAX_MESSAGE_MB, PJC_GRPC_STREAM_CHUNK_ELEMENTS,
#   PJC_DIR, PJC_BIN_DIR, PJC_BUILD
#   SERVER_CONNECT_RETRIES, SERVER_CONNECT_DELAY_SEC
#   RESULT_CALLBACK_URL, RESULT_CALLBACK_TOKEN, SHARED_RESULT_DIR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/pjc_binary_helpers.sh"

SERVER_HOST="${SERVER_HOST:-}"
CERT_DIR="${CERT_DIR:-$MODULE_ROOT/config/tls}"
TLS_PORT="${TLS_PORT:-10502}"
LOCAL_PROXY_PORT="${LOCAL_PROXY_PORT:-10503}"
TLS_SERVER_COMMON_NAME="${TLS_SERVER_COMMON_NAME:-pjc-server}"
JOB_ID="${JOB_ID:-$(date +%Y%m%d-%H%M%S)}"
OUT_DIR="${OUT_DIR:-$MODULE_ROOT/runs/$JOB_ID}"
CLIENT_CSV="${CLIENT_CSV:-/tmp/client.csv}"
GRPC_MAX_MESSAGE_MB="${GRPC_MAX_MESSAGE_MB:-512}"
PJC_GRPC_STREAM_CHUNK_ELEMENTS="${PJC_GRPC_STREAM_CHUNK_ELEMENTS:-4096}"
PJC_PRODUCTION_MODE="${PJC_PRODUCTION_MODE:-0}"
PJC_ALLOW_LEGACY_UNARY="${PJC_ALLOW_LEGACY_UNARY:-0}"
PJC_RESOURCE_LIMITS="${PJC_RESOURCE_LIMITS:-}"
PJC_PREFLIGHT_REQUIRED="${PJC_PREFLIGHT_REQUIRED:-0}"
PJC_PREFLIGHT_CALLER="${PJC_PREFLIGHT_CALLER:-auto_demo}"
PJC_PREFLIGHT_TENANT_ID="${PJC_PREFLIGHT_TENANT_ID:-}"
PJC_PREFLIGHT_DATASET_ID="${PJC_PREFLIGHT_DATASET_ID:-}"
PJC_PREFLIGHT_PURPOSE="${PJC_PREFLIGHT_PURPOSE:-bridge_token}"
PJC_PREFLIGHT_SERVER_CSV="${PJC_PREFLIGHT_SERVER_CSV:-}"
PJC_PREFLIGHT_SERVER_ROWS="${PJC_PREFLIGHT_SERVER_ROWS:-0}"
PJC_INPUT_COMMITMENT="${PJC_INPUT_COMMITMENT:-}"
PJC_JOB_META="${PJC_JOB_META:-}"
PJC_REQUIRE_INPUT_COMMITMENT="${PJC_REQUIRE_INPUT_COMMITMENT:-0}"
SERVER_CONNECT_RETRIES="${SERVER_CONNECT_RETRIES:-10}"
SERVER_CONNECT_DELAY_SEC="${SERVER_CONNECT_DELAY_SEC:-2}"
RESULT_CALLBACK_URL="${RESULT_CALLBACK_URL:-}"
RESULT_CALLBACK_TOKEN="${RESULT_CALLBACK_TOKEN:-}"
SHARED_RESULT_DIR="${SHARED_RESULT_DIR:-}"
SESSION_MANIFEST="${PJC_MTLS_SESSION_MANIFEST:-$CERT_DIR/session_manifest.json}"
PJC_MTLS_REQUIRE_SESSION_MANIFEST="${PJC_MTLS_REQUIRE_SESSION_MANIFEST:-0}"

# ── Pre-flight ────────────────────────────────────────────────────────────────
[[ -n "$SERVER_HOST" ]] || {
  echo "[error] SERVER_HOST is required (Party A's IP or hostname)" >&2
  exit 1
}
_require() {
  [[ -f "$1" ]] || { echo "[error] missing: $1" >&2; exit 1; }
}
if [[ "$PJC_PRODUCTION_MODE" == "1" ]]; then
  [[ -n "$PJC_RESOURCE_LIMITS" ]] || { echo "[error] PJC_PRODUCTION_MODE=1 requires PJC_RESOURCE_LIMITS" >&2; exit 1; }
  [[ "$PJC_GRPC_STREAM_CHUNK_ELEMENTS" != "0" ]] || { echo "[error] PJC_PRODUCTION_MODE=1 forbids legacy unary mode; set streaming chunk elements > 0" >&2; exit 1; }
  [[ "$PJC_MTLS_REQUIRE_SESSION_MANIFEST" == "1" ]] || { echo "[error] PJC_PRODUCTION_MODE=1 requires PJC_MTLS_REQUIRE_SESSION_MANIFEST=1" >&2; exit 1; }
elif [[ "$PJC_GRPC_STREAM_CHUNK_ELEMENTS" == "0" && "$PJC_ALLOW_LEGACY_UNARY" != "1" ]]; then
  echo "[error] legacy unary PJC mode requires PJC_ALLOW_LEGACY_UNARY=1" >&2
  exit 1
fi
command -v socat >/dev/null || {
  echo "[error] socat not found. Install with: apt-get install socat" >&2
  echo "[info]  Or use pjc_tls_proxy.py as a fallback (see docs/PJC_TLS_GUIDE.md)" >&2
  exit 1
}
_require "$CERT_DIR/ca.crt"
_require "$CERT_DIR/client.crt"
_require "$CERT_DIR/client.key"

mkdir -p "$OUT_DIR"

unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY || true
export no_proxy="localhost,127.0.0.1,0.0.0.0"
export NO_PROXY="$no_proxy"

echo "[info] JOB_ID=$JOB_ID"
echo "[info] CERT_DIR=$CERT_DIR"
echo "[info] PJC binary → 127.0.0.1:${LOCAL_PROXY_PORT} (socat) → TLS → ${SERVER_HOST}:${TLS_PORT}"
echo "[info] TLS_SERVER_COMMON_NAME=$TLS_SERVER_COMMON_NAME"
echo "[info] OUT_DIR=$OUT_DIR"

if [[ -f "$SESSION_MANIFEST" ]]; then
  SESSION_CHECK="$OUT_DIR/pjc_mtls_session_check_client.json"
  echo "[info] validating PJC mTLS session manifest: $SESSION_MANIFEST"
  python3 "$MODULE_ROOT/../scripts/check_pjc_mtls_session_manifest.py" \
    --manifest "$SESSION_MANIFEST" \
    --cert-dir "$CERT_DIR" \
    --role client \
    --job-id "$JOB_ID" \
    --output "$SESSION_CHECK" \
    --assert-allow \
    > /dev/null
  echo "[ok] session manifest accepted: $SESSION_CHECK"
elif [[ "$PJC_MTLS_REQUIRE_SESSION_MANIFEST" == "1" ]]; then
  echo "[error] PJC_MTLS_REQUIRE_SESSION_MANIFEST=1 but no manifest found at $SESSION_MANIFEST" >&2
  exit 1
else
  echo "[warn] no PJC mTLS session manifest found; legacy reusable-cert mode is allowed for this run" >&2
fi

# ── Resolve PJC binary ────────────────────────────────────────────────────────
PJC_DIR="${PJC_DIR:-$MODULE_ROOT/private-join-and-compute}"
PJC_BIN_DIR="${PJC_BIN_DIR:-}"
PJC_BUILD="${PJC_BUILD:-0}"

resolve_path() {
  case "$1" in /*) echo "$1" ;; *) echo "$MODULE_ROOT/$1" ;; esac
}
CLIENT_CSV="$(resolve_path "$CLIENT_CSV")"
[[ -f "$CLIENT_CSV" ]] || { echo "[error] CLIENT_CSV not found: $CLIENT_CSV" >&2; exit 1; }

if [[ -n "$PJC_RESOURCE_LIMITS" ]]; then
  PREFLIGHT_REPORT="$OUT_DIR/pjc_preflight_client.json"
  PREFLIGHT_ARGS=(
    --resource-limits "$(resolve_path "$PJC_RESOURCE_LIMITS")"
    --client-csv "$CLIENT_CSV"
    --caller "$PJC_PREFLIGHT_CALLER"
    --job-id "$JOB_ID"
    --transport-mode streaming_grpc
    --chunk-size-elements "$PJC_GRPC_STREAM_CHUNK_ELEMENTS"
    --output "$PREFLIGHT_REPORT"
    --assert-allow
  )
  [[ -n "$PJC_PREFLIGHT_TENANT_ID" ]] && PREFLIGHT_ARGS+=(--tenant-id "$PJC_PREFLIGHT_TENANT_ID")
  [[ -n "$PJC_PREFLIGHT_DATASET_ID" ]] && PREFLIGHT_ARGS+=(--dataset-id "$PJC_PREFLIGHT_DATASET_ID")
  [[ -n "$PJC_PREFLIGHT_PURPOSE" ]] && PREFLIGHT_ARGS+=(--purpose "$PJC_PREFLIGHT_PURPOSE")
  if [[ -n "$PJC_PREFLIGHT_SERVER_CSV" ]]; then
    PREFLIGHT_ARGS+=(--server-csv "$(resolve_path "$PJC_PREFLIGHT_SERVER_CSV")")
  else
    PREFLIGHT_ARGS+=(--server-rows "$PJC_PREFLIGHT_SERVER_ROWS")
  fi
  [[ -n "$PJC_INPUT_COMMITMENT" ]] && PREFLIGHT_ARGS+=(--input-commitment "$(resolve_path "$PJC_INPUT_COMMITMENT")")
  [[ -n "$PJC_JOB_META" ]] && PREFLIGHT_ARGS+=(--job-meta "$(resolve_path "$PJC_JOB_META")")
  if [[ "$PJC_REQUIRE_INPUT_COMMITMENT" == "1" || "$PJC_PRODUCTION_MODE" == "1" ]]; then
    PREFLIGHT_ARGS+=(--require-input-commitment)
  fi
  echo "[info] running PJC preflight: $PREFLIGHT_REPORT"
  python3 "$MODULE_ROOT/../scripts/preflight_pjc_job.py" "${PREFLIGHT_ARGS[@]}" > /dev/null
  echo "[ok] PJC preflight accepted client-side launch"
elif [[ "$PJC_PREFLIGHT_REQUIRED" == "1" ]]; then
  echo "[error] PJC_PREFLIGHT_REQUIRED=1 but PJC_RESOURCE_LIMITS is unset" >&2
  exit 1
else
  echo "[warn] PJC resource preflight skipped; set PJC_RESOURCE_LIMITS to enable it" >&2
fi

if [[ "$PJC_BUILD" == "1" ]]; then
  cd "$PJC_DIR"
  echo "[info] building PJC client..."
  bazel build -c opt //private_join_and_compute:client >/dev/null
fi
BIN_DIR="$(resolve_pjc_bin_dir_with_gate "$MODULE_ROOT" "$PJC_DIR" "$PJC_BIN_DIR" "$OUT_DIR" "$PJC_GRPC_STREAM_CHUNK_ELEMENTS")"
CLIENT_BIN="$BIN_DIR/private_join_and_compute/client"
[[ -x "$CLIENT_BIN" ]] || { echo "[error] client binary not found: $CLIENT_BIN" >&2; exit 1; }

# ── Start socat TLS client proxy ──────────────────────────────────────────────
SOCAT_PID=""
cleanup() {
  echo "[info] shutting down..."
  [[ -n "${SOCAT_PID:-}" ]] && kill "$SOCAT_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[info] starting socat TLS client proxy on 127.0.0.1:${LOCAL_PROXY_PORT}..."
socat \
  "TCP-LISTEN:${LOCAL_PROXY_PORT},bind=127.0.0.1,reuseaddr,fork" \
  "OPENSSL:${SERVER_HOST}:${TLS_PORT},cert=${CERT_DIR}/client.crt,key=${CERT_DIR}/client.key,cafile=${CERT_DIR}/ca.crt,verify=1,commonname=${TLS_SERVER_COMMON_NAME}" \
  >"$OUT_DIR/socat_client.log" 2>&1 &
SOCAT_PID=$!

# Wait for local proxy to be listening
for i in {1..30}; do
  if ! kill -0 "$SOCAT_PID" 2>/dev/null; then
    echo "[error] socat client proxy exited before listening. See $OUT_DIR/socat_client.log" >&2
    exit 1
  fi
  if ss -lnt 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${LOCAL_PROXY_PORT}$"; then
    break
  fi
  sleep 0.1
done
if ! kill -0 "$SOCAT_PID" 2>/dev/null; then
  echo "[error] socat client proxy exited before becoming ready. See $OUT_DIR/socat_client.log" >&2
  exit 1
fi
if ! ss -lnt 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${LOCAL_PROXY_PORT}$"; then
  echo "[error] socat proxy did not start on port $LOCAL_PROXY_PORT" >&2
  exit 1
fi
echo "[ok] socat TLS proxy ready on 127.0.0.1:${LOCAL_PROXY_PORT}"

# ── Run PJC client ────────────────────────────────────────────────────────────
CLIENT_LOG="$OUT_DIR/client.log"
PJC_EFFECTIVE_GRPC_STREAM_CHUNK_ELEMENTS="$PJC_GRPC_STREAM_CHUNK_ELEMENTS"
CLIENT_ARGS=(
  --client_data_file="$CLIENT_CSV"
  --port="127.0.0.1:${LOCAL_PROXY_PORT}"
  --grpc_max_message_mb="$GRPC_MAX_MESSAGE_MB"
)
if [[ "$PJC_GRPC_STREAM_CHUNK_ELEMENTS" != "0" ]]; then
  CLIENT_ARGS+=(--grpc_stream_chunk_elements="$PJC_GRPC_STREAM_CHUNK_ELEMENTS")
fi
echo "[info] PJC_EFFECTIVE_GRPC_STREAM_CHUNK_ELEMENTS=$PJC_EFFECTIVE_GRPC_STREAM_CHUNK_ELEMENTS"
echo "[info] running PJC client against local proxy..."

attempt=1
CLIENT_RC=1
while [[ "$attempt" -le "$SERVER_CONNECT_RETRIES" ]]; do
  set +e
  "$CLIENT_BIN" "${CLIENT_ARGS[@]}" >"$CLIENT_LOG" 2>&1
  CLIENT_RC=$?
  set -e
  [[ $CLIENT_RC -eq 0 ]] && break
  echo "[warn] attempt $attempt/$SERVER_CONNECT_RETRIES failed (rc=$CLIENT_RC). Retrying in ${SERVER_CONNECT_DELAY_SEC}s..." >&2
  attempt=$((attempt + 1))
  sleep "$SERVER_CONNECT_DELAY_SEC"
done

if [[ $CLIENT_RC -ne 0 ]]; then
  echo "[error] PJC client failed after $SERVER_CONNECT_RETRIES attempts. See $CLIENT_LOG" >&2
  exit $CLIENT_RC
fi

# ── Parse and write result ────────────────────────────────────────────────────
RESULT_LINE="$(grep -E 'intersection size is [0-9]+.*intersection-sum is [0-9]+' "$CLIENT_LOG" | tail -n 1 || true)"
[[ -n "$RESULT_LINE" ]] || { echo "[error] result line not found in $CLIENT_LOG" >&2; exit 1; }

INTERSECTION_SIZE="$(echo "$RESULT_LINE" | sed -n 's/.*intersection size is \([0-9]\+\).*/\1/p')"
INTERSECTION_SUM="$(echo "$RESULT_LINE"  | sed -n 's/.*intersection-sum is \([0-9]\+\).*/\1/p')"

RESULT_JSON="$OUT_DIR/attribution_result.json"
cat > "$RESULT_JSON" <<JSON
{
  "job_id": "$JOB_ID",
  "correlation_id": "$JOB_ID",
  "timestamp": "$(date -Is)",
  "server_addr": "${SERVER_HOST}:${TLS_PORT}",
  "tls": true,
  "client_csv": "$CLIENT_CSV",
  "grpc_max_message_mb": $GRPC_MAX_MESSAGE_MB,
  "grpc_stream_chunk_elements": $PJC_EFFECTIVE_GRPC_STREAM_CHUNK_ELEMENTS,
  "intersection_size": $INTERSECTION_SIZE,
  "intersection_sum": $INTERSECTION_SUM
}
JSON

echo "[ok] $RESULT_JSON"
echo "[ok] intersection_size=$INTERSECTION_SIZE  intersection_sum=$INTERSECTION_SUM"

[[ -n "$SHARED_RESULT_DIR" ]] && {
  mkdir -p "$SHARED_RESULT_DIR"
  cp "$RESULT_JSON" "$SHARED_RESULT_DIR/${JOB_ID}.json"
  echo "[ok] copied result to $SHARED_RESULT_DIR/${JOB_ID}.json"
}

[[ -n "$RESULT_CALLBACK_URL" ]] && python3 "$SCRIPT_DIR/push_result.py" \
  --url "$RESULT_CALLBACK_URL" \
  --result "$RESULT_JSON" \
  --token "$RESULT_CALLBACK_TOKEN"

exit 0
