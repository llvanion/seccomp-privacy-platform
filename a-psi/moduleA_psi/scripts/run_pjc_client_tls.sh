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

SERVER_HOST="${SERVER_HOST:-}"
CERT_DIR="${CERT_DIR:-$MODULE_ROOT/config/tls}"
TLS_PORT="${TLS_PORT:-10502}"
LOCAL_PROXY_PORT="${LOCAL_PROXY_PORT:-10503}"
JOB_ID="${JOB_ID:-$(date +%Y%m%d-%H%M%S)}"
OUT_DIR="${OUT_DIR:-$MODULE_ROOT/runs/$JOB_ID}"
CLIENT_CSV="${CLIENT_CSV:-/tmp/client.csv}"
GRPC_MAX_MESSAGE_MB="${GRPC_MAX_MESSAGE_MB:-512}"
PJC_GRPC_STREAM_CHUNK_ELEMENTS="${PJC_GRPC_STREAM_CHUNK_ELEMENTS:-4096}"
SERVER_CONNECT_RETRIES="${SERVER_CONNECT_RETRIES:-10}"
SERVER_CONNECT_DELAY_SEC="${SERVER_CONNECT_DELAY_SEC:-2}"
RESULT_CALLBACK_URL="${RESULT_CALLBACK_URL:-}"
RESULT_CALLBACK_TOKEN="${RESULT_CALLBACK_TOKEN:-}"
SHARED_RESULT_DIR="${SHARED_RESULT_DIR:-}"

# ── Pre-flight ────────────────────────────────────────────────────────────────
[[ -n "$SERVER_HOST" ]] || {
  echo "[error] SERVER_HOST is required (Party A's IP or hostname)" >&2
  exit 1
}
_require() {
  [[ -f "$1" ]] || { echo "[error] missing: $1" >&2; exit 1; }
}
command -v socat >/dev/null || {
  echo "[error] socat not found. Install with: apt-get install socat" >&2
  echo "[info]  Or use pjc_tls_proxy.py as a fallback (see docs/PJC_TLS_GUIDE.md)" >&2
  exit 1
}
_require "$CERT_DIR/ca.crt"
_require "$CERT_DIR/client.crt"
_require "$CERT_DIR/client.key"

mkdir -p "$OUT_DIR"

echo "[info] JOB_ID=$JOB_ID"
echo "[info] CERT_DIR=$CERT_DIR"
echo "[info] PJC binary → 127.0.0.1:${LOCAL_PROXY_PORT} (socat) → TLS → ${SERVER_HOST}:${TLS_PORT}"
echo "[info] OUT_DIR=$OUT_DIR"

# ── Resolve PJC binary ────────────────────────────────────────────────────────
PJC_DIR="${PJC_DIR:-$MODULE_ROOT/private-join-and-compute}"
PJC_BIN_DIR="${PJC_BIN_DIR:-}"
PJC_BUILD="${PJC_BUILD:-0}"

resolve_path() {
  case "$1" in /*) echo "$1" ;; *) echo "$MODULE_ROOT/$1" ;; esac
}
CLIENT_CSV="$(resolve_path "$CLIENT_CSV")"
[[ -f "$CLIENT_CSV" ]] || { echo "[error] CLIENT_CSV not found: $CLIENT_CSV" >&2; exit 1; }

if [[ -n "$PJC_BIN_DIR" ]]; then
  BIN_DIR="$(resolve_path "$PJC_BIN_DIR")"
else
  cd "$PJC_DIR"
  if [[ "$PJC_BUILD" == "1" ]]; then
    echo "[info] building PJC client..."
    bazel build -c opt //private_join_and_compute:client >/dev/null
  fi
  BIN_DIR="$(bazel info bazel-bin)"
fi
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
  "OPENSSL:${SERVER_HOST}:${TLS_PORT},cert=${CERT_DIR}/client.crt,key=${CERT_DIR}/client.key,cafile=${CERT_DIR}/ca.crt,verify=1" \
  &
SOCAT_PID=$!

# Wait for local proxy to be listening
for i in {1..30}; do
  if ss -lnt 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${LOCAL_PROXY_PORT}$"; then
    break
  fi
  sleep 0.1
done
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
  if "$CLIENT_BIN" --help 2>&1 | grep -q -- "--grpc_stream_chunk_elements"; then
    CLIENT_ARGS+=(--grpc_stream_chunk_elements="$PJC_GRPC_STREAM_CHUNK_ELEMENTS")
  else
    echo "[warn] PJC client binary does not support --grpc_stream_chunk_elements; using legacy unary mode" >&2
    PJC_EFFECTIVE_GRPC_STREAM_CHUNK_ELEMENTS=0
  fi
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
