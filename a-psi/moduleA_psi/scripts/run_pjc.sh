#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# run_pjc.sh
# - Runs Google PJC (private-join-and-compute) server+client locally.
# - Writes logs + attribution_result.json into OUT_DIR
#
# Improvements vs demo:
#   - Port readiness check matches SERVER_ADDR (no hardcoded 10501)
#   - Better errors & optional build step
#   - Optional per-run isolation via SERVER_PORT env (if you want many buckets)
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ---- Config (override via env vars) ----
PJC_DIR="${PJC_DIR:-$MODULE_ROOT/private-join-and-compute}"
PJC_BIN_DIR="${PJC_BIN_DIR:-}"
JOB_ID="${JOB_ID:-$(date +%Y%m%d-%H%M%S)}"
OUT_DIR="${OUT_DIR:-$MODULE_ROOT/runs/$JOB_ID}"

SERVER_CSV="${SERVER_CSV:-/tmp/server.csv}"
CLIENT_CSV="${CLIENT_CSV:-/tmp/client.csv}"

# SERVER_ADDR format: host:port
SERVER_ADDR="${SERVER_ADDR:-127.0.0.1:10501}"
GRPC_MAX_MESSAGE_MB="${GRPC_MAX_MESSAGE_MB:-512}"
PJC_GRPC_STREAM_CHUNK_ELEMENTS="${PJC_GRPC_STREAM_CHUNK_ELEMENTS:-4096}"

# If 1, build server/client before running (useful in CI or fresh env)
PJC_BUILD="${PJC_BUILD:-0}"

resolve_path() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *)  printf '%s\n' "$MODULE_ROOT/$1" ;;
  esac
}

OUT_DIR="$(resolve_path "$OUT_DIR")"
SERVER_CSV="$(resolve_path "$SERVER_CSV")"
CLIENT_CSV="$(resolve_path "$CLIENT_CSV")"

mkdir -p "$OUT_DIR"

# ---- Ensure localhost gRPC isn't routed through proxies ----
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY || true
export no_proxy="localhost,127.0.0.1,0.0.0.0"
export NO_PROXY="$no_proxy"

# ---- Quick sanity checks ----
if [[ -z "$PJC_BIN_DIR" ]]; then
  [[ -d "$PJC_DIR" ]] || { echo "[error] PJC_DIR not found: $PJC_DIR" >&2; exit 1; }
fi
[[ -f "$SERVER_CSV" ]] || { echo "[error] SERVER_CSV not found: $SERVER_CSV" >&2; exit 1; }
[[ -f "$CLIENT_CSV" ]] || { echo "[error] CLIENT_CSV not found: $CLIENT_CSV" >&2; exit 1; }

# Parse port
SERVER_HOST="${SERVER_ADDR%:*}"
SERVER_PORT="${SERVER_ADDR##*:}"
if ! [[ "$SERVER_PORT" =~ ^[0-9]+$ ]]; then
  echo "[error] SERVER_ADDR must be host:port, got: $SERVER_ADDR" >&2
  exit 1
fi

echo "[info] JOB_ID=$JOB_ID"
echo "[info] OUT_DIR=$OUT_DIR"
echo "[info] PJC_DIR=$PJC_DIR"
echo "[info] PJC_BIN_DIR=${PJC_BIN_DIR:-<via bazel>}"
echo "[info] SERVER_CSV=$SERVER_CSV"
echo "[info] CLIENT_CSV=$CLIENT_CSV"
echo "[info] SERVER_ADDR=$SERVER_ADDR"
echo "[info] GRPC_MAX_MESSAGE_MB=$GRPC_MAX_MESSAGE_MB"
echo "[info] PJC_GRPC_STREAM_CHUNK_ELEMENTS=$PJC_GRPC_STREAM_CHUNK_ELEMENTS"

if [[ -n "$PJC_BIN_DIR" ]]; then
  cd "$(dirname "$(resolve_path "$PJC_BIN_DIR")")"
else
  cd "$PJC_DIR"
fi

SERVER_LOG="$OUT_DIR/server.log"
CLIENT_LOG="$OUT_DIR/client.log"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [[ "$PJC_BUILD" == "1" ]]; then
  echo "[info] building PJC binaries..."
  bazel build -c opt //private_join_and_compute:server //private_join_and_compute:client >/dev/null
fi

if [[ -n "$PJC_BIN_DIR" ]]; then
  BIN_DIR="$(resolve_path "$PJC_BIN_DIR")"
else
  BIN_DIR="$(bazel info bazel-bin)"
fi
SERVER_BIN="$BIN_DIR/private_join_and_compute/server"
CLIENT_BIN="$BIN_DIR/private_join_and_compute/client"

[[ -x "$SERVER_BIN" ]] || { echo "[error] server binary not found/executable: $SERVER_BIN" >&2; exit 1; }
[[ -x "$CLIENT_BIN" ]] || { echo "[error] client binary not found/executable: $CLIENT_BIN" >&2; exit 1; }

echo "[info] starting server..."
"$SERVER_BIN" \
  --server_data_file="$SERVER_CSV" \
  --grpc_max_message_mb="$GRPC_MAX_MESSAGE_MB" \
  --grpc_stream_chunk_elements="$PJC_GRPC_STREAM_CHUNK_ELEMENTS" \
  --port="$SERVER_ADDR" \
  >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

echo "[info] waiting for server to listen on port $SERVER_PORT..."
for i in {1..80}; do
  if ss -lnt 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${SERVER_PORT}$"; then
    break
  fi
  sleep 0.2
done
if ! ss -lnt 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${SERVER_PORT}$"; then
  echo "[error] server did not start listening on $SERVER_ADDR. Check $SERVER_LOG" >&2
  exit 1
fi

echo "[info] running client..."
set +e
"$CLIENT_BIN" \
  --client_data_file="$CLIENT_CSV" \
  --port="$SERVER_ADDR" \
  --grpc_max_message_mb="$GRPC_MAX_MESSAGE_MB" \
  --grpc_stream_chunk_elements="$PJC_GRPC_STREAM_CHUNK_ELEMENTS" \
  >"$CLIENT_LOG" 2>&1
CLIENT_RC=$?
set -e

if [[ $CLIENT_RC -ne 0 ]]; then
  echo "[error] client failed (rc=$CLIENT_RC). Check $CLIENT_LOG and $SERVER_LOG" >&2
  exit $CLIENT_RC
fi

RESULT_LINE="$(grep -E 'intersection size is [0-9]+.*intersection-sum is [0-9]+' "$CLIENT_LOG" | tail -n 1 || true)"
if [[ -z "$RESULT_LINE" ]]; then
  echo "[error] could not find result line in $CLIENT_LOG" >&2
  exit 1
fi

INTERSECTION_SIZE="$(echo "$RESULT_LINE" | sed -n 's/.*intersection size is \([0-9]\+\).*/\1/p')"
INTERSECTION_SUM="$(echo "$RESULT_LINE" | sed -n 's/.*intersection-sum is \([0-9]\+\).*/\1/p')"

NOW_ISO="$(date -Is)"
RESULT_JSON="$OUT_DIR/attribution_result.json"
cat > "$RESULT_JSON" <<JSON
{
  "job_id": "$JOB_ID",
  "correlation_id": "$JOB_ID",
  "timestamp": "$NOW_ISO",
  "server_addr": "$SERVER_ADDR",
  "server_csv": "$SERVER_CSV",
  "client_csv": "$CLIENT_CSV",
  "grpc_max_message_mb": $GRPC_MAX_MESSAGE_MB,
  "grpc_stream_chunk_elements": $PJC_GRPC_STREAM_CHUNK_ELEMENTS,
  "intersection_size": $INTERSECTION_SIZE,
  "intersection_sum": $INTERSECTION_SUM
}
JSON

echo "[ok] $RESULT_JSON"
echo "[ok] intersection_size=$INTERSECTION_SIZE intersection_sum=$INTERSECTION_SUM"
