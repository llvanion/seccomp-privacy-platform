#!/usr/bin/env bash
set -euo pipefail

# Runs only the PJC server process. Use this on the server-side machine.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/pjc_binary_helpers.sh"

PJC_DIR="${PJC_DIR:-$MODULE_ROOT/private-join-and-compute}"
PJC_BIN_DIR="${PJC_BIN_DIR:-}"
JOB_ID="${JOB_ID:-$(date +%Y%m%d-%H%M%S)}"
OUT_DIR="${OUT_DIR:-$MODULE_ROOT/runs/$JOB_ID}"
SERVER_CSV="${SERVER_CSV:-/tmp/server.csv}"
SERVER_ADDR="${SERVER_ADDR:-0.0.0.0:10501}"
GRPC_MAX_MESSAGE_MB="${GRPC_MAX_MESSAGE_MB:-512}"
PJC_GRPC_STREAM_CHUNK_ELEMENTS="${PJC_GRPC_STREAM_CHUNK_ELEMENTS:-4096}"
PJC_BUILD="${PJC_BUILD:-0}"

resolve_path() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *) printf '%s\n' "$MODULE_ROOT/$1" ;;
  esac
}

OUT_DIR="$(resolve_path "$OUT_DIR")"
SERVER_CSV="$(resolve_path "$SERVER_CSV")"

mkdir -p "$OUT_DIR"

unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY || true
export no_proxy="localhost,127.0.0.1,0.0.0.0"
export NO_PROXY="$no_proxy"

if [[ -z "$PJC_BIN_DIR" ]]; then
  [[ -d "$PJC_DIR" ]] || { echo "[error] PJC_DIR not found: $PJC_DIR" >&2; exit 1; }
fi
[[ -f "$SERVER_CSV" ]] || { echo "[error] SERVER_CSV not found: $SERVER_CSV" >&2; exit 1; }

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
echo "[info] SERVER_ADDR=$SERVER_ADDR"
echo "[info] GRPC_MAX_MESSAGE_MB=$GRPC_MAX_MESSAGE_MB"
echo "[info] PJC_GRPC_STREAM_CHUNK_ELEMENTS=$PJC_GRPC_STREAM_CHUNK_ELEMENTS"

SERVER_LOG="$OUT_DIR/server.log"

if [[ "$PJC_BUILD" == "1" ]]; then
  echo "[info] building PJC server binary..."
  bazel build -c opt //private_join_and_compute:server >/dev/null
fi

BIN_DIR="$(resolve_pjc_bin_dir_with_gate "$MODULE_ROOT" "$PJC_DIR" "$PJC_BIN_DIR" "$OUT_DIR" "$PJC_GRPC_STREAM_CHUNK_ELEMENTS")"
SERVER_BIN="$BIN_DIR/private_join_and_compute/server"

[[ -x "$SERVER_BIN" ]] || { echo "[error] server binary not found/executable: $SERVER_BIN" >&2; exit 1; }

echo "[info] starting server..."
echo "[info] log file: $SERVER_LOG"
"$SERVER_BIN" \
  --server_data_file="$SERVER_CSV" \
  --grpc_max_message_mb="$GRPC_MAX_MESSAGE_MB" \
  --grpc_stream_chunk_elements="$PJC_GRPC_STREAM_CHUNK_ELEMENTS" \
  --port="$SERVER_ADDR" \
  2>&1 | tee "$SERVER_LOG"
