#!/usr/bin/env bash
set -euo pipefail

# Runs only the PJC client process. Use this on the client-side machine.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PJC_DIR="${PJC_DIR:-$MODULE_ROOT/private-join-and-compute}"
PJC_BIN_DIR="${PJC_BIN_DIR:-}"
JOB_ID="${JOB_ID:-$(date +%Y%m%d-%H%M%S)}"
OUT_DIR="${OUT_DIR:-$MODULE_ROOT/runs/$JOB_ID}"
CLIENT_CSV="${CLIENT_CSV:-/tmp/client.csv}"
SERVER_ADDR="${SERVER_ADDR:-127.0.0.1:10501}"
GRPC_MAX_MESSAGE_MB="${GRPC_MAX_MESSAGE_MB:-512}"
PJC_GRPC_STREAM_CHUNK_ELEMENTS="${PJC_GRPC_STREAM_CHUNK_ELEMENTS:-4096}"
PJC_BUILD="${PJC_BUILD:-0}"
SERVER_CONNECT_RETRIES="${SERVER_CONNECT_RETRIES:-10}"
SERVER_CONNECT_DELAY_SEC="${SERVER_CONNECT_DELAY_SEC:-2}"
RESULT_CALLBACK_URL="${RESULT_CALLBACK_URL:-}"
RESULT_CALLBACK_TOKEN="${RESULT_CALLBACK_TOKEN:-}"
SHARED_RESULT_DIR="${SHARED_RESULT_DIR:-}"

resolve_path() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *) printf '%s\n' "$MODULE_ROOT/$1" ;;
  esac
}

OUT_DIR="$(resolve_path "$OUT_DIR")"
CLIENT_CSV="$(resolve_path "$CLIENT_CSV")"

mkdir -p "$OUT_DIR"

unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY || true
export no_proxy="localhost,127.0.0.1,0.0.0.0"
export NO_PROXY="$no_proxy"

if [[ -z "$PJC_BIN_DIR" ]]; then
  [[ -d "$PJC_DIR" ]] || { echo "[error] PJC_DIR not found: $PJC_DIR" >&2; exit 1; }
fi
[[ -f "$CLIENT_CSV" ]] || { echo "[error] CLIENT_CSV not found: $CLIENT_CSV" >&2; exit 1; }

SERVER_PORT="${SERVER_ADDR##*:}"
if ! [[ "$SERVER_PORT" =~ ^[0-9]+$ ]]; then
  echo "[error] SERVER_ADDR must be host:port, got: $SERVER_ADDR" >&2
  exit 1
fi

echo "[info] JOB_ID=$JOB_ID"
echo "[info] OUT_DIR=$OUT_DIR"
echo "[info] PJC_DIR=$PJC_DIR"
echo "[info] PJC_BIN_DIR=${PJC_BIN_DIR:-<via bazel>}"
echo "[info] CLIENT_CSV=$CLIENT_CSV"
echo "[info] SERVER_ADDR=$SERVER_ADDR"
echo "[info] GRPC_MAX_MESSAGE_MB=$GRPC_MAX_MESSAGE_MB"
echo "[info] PJC_GRPC_STREAM_CHUNK_ELEMENTS=$PJC_GRPC_STREAM_CHUNK_ELEMENTS"
echo "[info] SERVER_CONNECT_RETRIES=$SERVER_CONNECT_RETRIES"

if [[ -n "$PJC_BIN_DIR" ]]; then
  cd "$(dirname "$(resolve_path "$PJC_BIN_DIR")")"
else
  cd "$PJC_DIR"
fi

CLIENT_LOG="$OUT_DIR/client.log"

if [[ "$PJC_BUILD" == "1" ]]; then
  echo "[info] building PJC client binary..."
  bazel build -c opt //private_join_and_compute:client >/dev/null
fi

if [[ -n "$PJC_BIN_DIR" ]]; then
  BIN_DIR="$(resolve_path "$PJC_BIN_DIR")"
else
  BIN_DIR="$(bazel info bazel-bin)"
fi
CLIENT_BIN="$BIN_DIR/private_join_and_compute/client"

[[ -x "$CLIENT_BIN" ]] || { echo "[error] client binary not found/executable: $CLIENT_BIN" >&2; exit 1; }

echo "[info] running client..."
attempt=1
CLIENT_RC=1
while [[ "$attempt" -le "$SERVER_CONNECT_RETRIES" ]]; do
  set +e
  "$CLIENT_BIN" \
    --client_data_file="$CLIENT_CSV" \
    --port="$SERVER_ADDR" \
    --grpc_max_message_mb="$GRPC_MAX_MESSAGE_MB" \
    --grpc_stream_chunk_elements="$PJC_GRPC_STREAM_CHUNK_ELEMENTS" \
    >"$CLIENT_LOG" 2>&1
  CLIENT_RC=$?
  set -e

  if [[ $CLIENT_RC -eq 0 ]]; then
    break
  fi

  echo "[warn] client attempt $attempt/$SERVER_CONNECT_RETRIES failed (rc=$CLIENT_RC). Retrying in ${SERVER_CONNECT_DELAY_SEC}s..." >&2
  attempt=$((attempt + 1))
  sleep "$SERVER_CONNECT_DELAY_SEC"
done

if [[ $CLIENT_RC -ne 0 ]]; then
  echo "[error] client failed after $SERVER_CONNECT_RETRIES attempts. Check $CLIENT_LOG" >&2
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
  "timestamp": "$NOW_ISO",
  "server_addr": "$SERVER_ADDR",
  "client_csv": "$CLIENT_CSV",
  "grpc_max_message_mb": $GRPC_MAX_MESSAGE_MB,
  "grpc_stream_chunk_elements": $PJC_GRPC_STREAM_CHUNK_ELEMENTS,
  "intersection_size": $INTERSECTION_SIZE,
  "intersection_sum": $INTERSECTION_SUM
}
JSON

echo "[ok] $RESULT_JSON"
echo "[ok] intersection_size=$INTERSECTION_SIZE intersection_sum=$INTERSECTION_SUM"

if [[ -n "$SHARED_RESULT_DIR" ]]; then
  mkdir -p "$SHARED_RESULT_DIR"
  cp "$RESULT_JSON" "$SHARED_RESULT_DIR/${JOB_ID}.json"
  echo "[ok] copied result to $SHARED_RESULT_DIR/${JOB_ID}.json"
fi

if [[ -n "$RESULT_CALLBACK_URL" ]]; then
  python3 "$SCRIPT_DIR/push_result.py" \
    --url "$RESULT_CALLBACK_URL" \
    --result "$RESULT_JSON" \
    --token "$RESULT_CALLBACK_TOKEN"
fi
