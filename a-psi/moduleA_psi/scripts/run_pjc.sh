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
source "$SCRIPT_DIR/pjc_binary_helpers.sh"

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
PJC_PRODUCTION_MODE="${PJC_PRODUCTION_MODE:-0}"
PJC_ALLOW_LEGACY_UNARY="${PJC_ALLOW_LEGACY_UNARY:-0}"
PJC_RESOURCE_LIMITS="${PJC_RESOURCE_LIMITS:-}"
PJC_PREFLIGHT_REQUIRED="${PJC_PREFLIGHT_REQUIRED:-0}"
PJC_PREFLIGHT_CALLER="${PJC_PREFLIGHT_CALLER:-auto_demo}"
PJC_PREFLIGHT_TENANT_ID="${PJC_PREFLIGHT_TENANT_ID:-}"
PJC_PREFLIGHT_DATASET_ID="${PJC_PREFLIGHT_DATASET_ID:-}"
PJC_PREFLIGHT_PURPOSE="${PJC_PREFLIGHT_PURPOSE:-bridge_token}"
PJC_INPUT_COMMITMENT="${PJC_INPUT_COMMITMENT:-}"
PJC_JOB_META="${PJC_JOB_META:-}"
PJC_REQUIRE_INPUT_COMMITMENT="${PJC_REQUIRE_INPUT_COMMITMENT:-0}"

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

# Parse port
SERVER_HOST="${SERVER_ADDR%:*}"
SERVER_PORT="${SERVER_ADDR##*:}"
if ! [[ "$SERVER_PORT" =~ ^[0-9]+$ ]]; then
  echo "[error] SERVER_ADDR must be host:port, got: $SERVER_ADDR" >&2
  exit 1
fi

if [[ "$PJC_PRODUCTION_MODE" == "1" ]]; then
  [[ -n "$PJC_RESOURCE_LIMITS" ]] || { echo "[error] PJC_PRODUCTION_MODE=1 requires PJC_RESOURCE_LIMITS" >&2; exit 1; }
  [[ "$PJC_GRPC_STREAM_CHUNK_ELEMENTS" != "0" ]] || { echo "[error] PJC_PRODUCTION_MODE=1 forbids legacy unary mode; set streaming chunk elements > 0" >&2; exit 1; }
  case "$SERVER_HOST" in
    127.0.0.1|localhost|::1) ;;
    *) echo "[error] PJC_PRODUCTION_MODE=1 plain gRPC must bind loopback; use TLS/mTLS wrapper for non-loopback SERVER_ADDR=$SERVER_ADDR" >&2; exit 1 ;;
  esac
elif [[ "$PJC_GRPC_STREAM_CHUNK_ELEMENTS" == "0" && "$PJC_ALLOW_LEGACY_UNARY" != "1" ]]; then
  echo "[error] legacy unary PJC mode requires PJC_ALLOW_LEGACY_UNARY=1" >&2
  exit 1
fi

# ---- Quick sanity checks ----
if [[ -z "$PJC_BIN_DIR" ]]; then
  [[ -d "$PJC_DIR" ]] || { echo "[error] PJC_DIR not found: $PJC_DIR" >&2; exit 1; }
fi
[[ -f "$SERVER_CSV" ]] || { echo "[error] SERVER_CSV not found: $SERVER_CSV" >&2; exit 1; }
[[ -f "$CLIENT_CSV" ]] || { echo "[error] CLIENT_CSV not found: $CLIENT_CSV" >&2; exit 1; }

if [[ -n "$PJC_RESOURCE_LIMITS" ]]; then
  PREFLIGHT_REPORT="$OUT_DIR/pjc_preflight.json"
  PREFLIGHT_ARGS=(
    --resource-limits "$(resolve_path "$PJC_RESOURCE_LIMITS")"
    --server-csv "$SERVER_CSV"
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
  [[ -n "$PJC_INPUT_COMMITMENT" ]] && PREFLIGHT_ARGS+=(--input-commitment "$(resolve_path "$PJC_INPUT_COMMITMENT")")
  [[ -n "$PJC_JOB_META" ]] && PREFLIGHT_ARGS+=(--job-meta "$(resolve_path "$PJC_JOB_META")")
  if [[ "$PJC_REQUIRE_INPUT_COMMITMENT" == "1" || "$PJC_PRODUCTION_MODE" == "1" ]]; then
    PREFLIGHT_ARGS+=(--require-input-commitment)
  fi
  echo "[info] running PJC preflight: $PREFLIGHT_REPORT"
  python3 "$MODULE_ROOT/../scripts/preflight_pjc_job.py" "${PREFLIGHT_ARGS[@]}" > /dev/null
  echo "[ok] PJC preflight accepted local launch"
elif [[ "$PJC_PREFLIGHT_REQUIRED" == "1" ]]; then
  echo "[error] PJC_PREFLIGHT_REQUIRED=1 but PJC_RESOURCE_LIMITS is unset" >&2
  exit 1
else
  echo "[warn] PJC resource preflight skipped; set PJC_RESOURCE_LIMITS to enable it" >&2
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

BIN_DIR="$(resolve_pjc_bin_dir_with_gate "$MODULE_ROOT" "$PJC_DIR" "$PJC_BIN_DIR" "$OUT_DIR" "$PJC_GRPC_STREAM_CHUNK_ELEMENTS")"
SERVER_BIN="$BIN_DIR/private_join_and_compute/server"
CLIENT_BIN="$BIN_DIR/private_join_and_compute/client"

[[ -x "$SERVER_BIN" ]] || { echo "[error] server binary not found/executable: $SERVER_BIN" >&2; exit 1; }
[[ -x "$CLIENT_BIN" ]] || { echo "[error] client binary not found/executable: $CLIENT_BIN" >&2; exit 1; }

PJC_EFFECTIVE_GRPC_STREAM_CHUNK_ELEMENTS="$PJC_GRPC_STREAM_CHUNK_ELEMENTS"
SERVER_ARGS=(
  --server_data_file="$SERVER_CSV"
  --grpc_max_message_mb="$GRPC_MAX_MESSAGE_MB"
  --port="$SERVER_ADDR"
)
CLIENT_ARGS=(
  --client_data_file="$CLIENT_CSV"
  --port="$SERVER_ADDR"
  --grpc_max_message_mb="$GRPC_MAX_MESSAGE_MB"
)
if [[ "$PJC_GRPC_STREAM_CHUNK_ELEMENTS" != "0" ]]; then
  SERVER_ARGS+=(--grpc_stream_chunk_elements="$PJC_GRPC_STREAM_CHUNK_ELEMENTS")
  CLIENT_ARGS+=(--grpc_stream_chunk_elements="$PJC_GRPC_STREAM_CHUNK_ELEMENTS")
fi
echo "[info] PJC_EFFECTIVE_GRPC_STREAM_CHUNK_ELEMENTS=$PJC_EFFECTIVE_GRPC_STREAM_CHUNK_ELEMENTS"

echo "[info] starting server..."
"$SERVER_BIN" "${SERVER_ARGS[@]}" >"$SERVER_LOG" 2>&1 &
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
"$CLIENT_BIN" "${CLIENT_ARGS[@]}" >"$CLIENT_LOG" 2>&1
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
  "grpc_stream_chunk_elements": $PJC_EFFECTIVE_GRPC_STREAM_CHUNK_ELEMENTS,
  "intersection_size": $INTERSECTION_SIZE,
  "intersection_sum": $INTERSECTION_SUM
}
JSON

echo "[ok] $RESULT_JSON"
echo "[ok] intersection_size=$INTERSECTION_SIZE intersection_sum=$INTERSECTION_SUM"
