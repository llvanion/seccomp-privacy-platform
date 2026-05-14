#!/usr/bin/env bash
set -euo pipefail
# Party A: run PJC server behind a mTLS socat proxy.
#
# Architecture:
#   Internet → TLS_PORT (socat, mTLS) → PJC_LOCAL_PORT (PJC binary, plain gRPC, loopback)
#
# Required env / flags:
#   CERT_DIR      directory containing ca.crt, server.crt, server.key
#   SERVER_CSV    path to Party A's tokenised server.csv
#   TLS_PORT      external TLS listen port (default 10502)
#   PJC_LOCAL_PORT loopback port for the PJC binary (default 10501)
#   BIND_ADDR     external bind address (default 0.0.0.0)
#
# Other env vars pass through to run_pjc_server.sh:
#   PJC_DIR, PJC_BIN_DIR, JOB_ID, OUT_DIR, GRPC_MAX_MESSAGE_MB,
#   PJC_GRPC_STREAM_CHUNK_ELEMENTS, PJC_BUILD

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CERT_DIR="${CERT_DIR:-$MODULE_ROOT/config/tls}"
TLS_PORT="${TLS_PORT:-10502}"
PJC_LOCAL_PORT="${PJC_LOCAL_PORT:-10501}"
BIND_ADDR="${BIND_ADDR:-0.0.0.0}"
JOB_ID="${JOB_ID:-$(date +%Y%m%d-%H%M%S)}"
OUT_DIR="${OUT_DIR:-$MODULE_ROOT/runs/$JOB_ID}"
GRPC_MAX_MESSAGE_MB="${GRPC_MAX_MESSAGE_MB:-512}"
PJC_GRPC_STREAM_CHUNK_ELEMENTS="${PJC_GRPC_STREAM_CHUNK_ELEMENTS:-4096}"

# ── Pre-flight ────────────────────────────────────────────────────────────────
_require() {
  [[ -f "$1" ]] || { echo "[error] missing: $1" >&2; exit 1; }
}
command -v socat >/dev/null || {
  echo "[error] socat not found. Install with: apt-get install socat" >&2
  echo "[info]  Or use pjc_tls_proxy.py as a fallback (see docs/PJC_TLS_GUIDE.md)" >&2
  exit 1
}
_require "$CERT_DIR/ca.crt"
_require "$CERT_DIR/server.crt"
_require "$CERT_DIR/server.key"

mkdir -p "$OUT_DIR"

echo "[info] JOB_ID=$JOB_ID"
echo "[info] CERT_DIR=$CERT_DIR"
echo "[info] TLS listen: ${BIND_ADDR}:${TLS_PORT}  →  127.0.0.1:${PJC_LOCAL_PORT} (plain gRPC)"
echo "[info] OUT_DIR=$OUT_DIR"

# ── Resolve PJC binary ────────────────────────────────────────────────────────
PJC_DIR="${PJC_DIR:-$MODULE_ROOT/private-join-and-compute}"
PJC_BIN_DIR="${PJC_BIN_DIR:-}"
PJC_BUILD="${PJC_BUILD:-0}"
SERVER_CSV="${SERVER_CSV:-/tmp/server.csv}"

resolve_path() {
  case "$1" in /*) echo "$1" ;; *) echo "$MODULE_ROOT/$1" ;; esac
}
SERVER_CSV="$(resolve_path "$SERVER_CSV")"
[[ -f "$SERVER_CSV" ]] || { echo "[error] SERVER_CSV not found: $SERVER_CSV" >&2; exit 1; }

if [[ -n "$PJC_BIN_DIR" ]]; then
  BIN_DIR="$(resolve_path "$PJC_BIN_DIR")"
else
  cd "$PJC_DIR"
  if [[ "$PJC_BUILD" == "1" ]]; then
    echo "[info] building PJC server..."
    bazel build -c opt //private_join_and_compute:server >/dev/null
  fi
  BIN_DIR="$(bazel info bazel-bin)"
fi
SERVER_BIN="$BIN_DIR/private_join_and_compute/server"
[[ -x "$SERVER_BIN" ]] || { echo "[error] server binary not found: $SERVER_BIN" >&2; exit 1; }

# ── Start PJC server on loopback ──────────────────────────────────────────────
SERVER_LOG="$OUT_DIR/server.log"
echo "[info] starting PJC server on 127.0.0.1:${PJC_LOCAL_PORT}..."
"$SERVER_BIN" \
  --server_data_file="$SERVER_CSV" \
  --grpc_max_message_mb="$GRPC_MAX_MESSAGE_MB" \
  --grpc_stream_chunk_elements="$PJC_GRPC_STREAM_CHUNK_ELEMENTS" \
  --port="127.0.0.1:${PJC_LOCAL_PORT}" \
  >"$SERVER_LOG" 2>&1 &
PJC_PID=$!

# Wait for PJC server to be listening
for i in {1..60}; do
  if ss -lnt 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${PJC_LOCAL_PORT}$"; then
    break
  fi
  sleep 0.2
done
if ! ss -lnt 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${PJC_LOCAL_PORT}$"; then
  echo "[error] PJC server did not start on port $PJC_LOCAL_PORT" >&2
  kill "$PJC_PID" 2>/dev/null || true
  exit 1
fi
echo "[ok] PJC server listening on 127.0.0.1:${PJC_LOCAL_PORT}"

# ── Start socat TLS proxy ─────────────────────────────────────────────────────
SOCAT_PID=""
cleanup() {
  echo "[info] shutting down..."
  [[ -n "${SOCAT_PID:-}" ]] && kill "$SOCAT_PID" 2>/dev/null || true
  kill "$PJC_PID" 2>/dev/null || true
  wait "$PJC_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[info] starting socat TLS proxy on ${BIND_ADDR}:${TLS_PORT}..."
socat \
  "OPENSSL-LISTEN:${TLS_PORT},bind=${BIND_ADDR},cert=${CERT_DIR}/server.crt,key=${CERT_DIR}/server.key,cafile=${CERT_DIR}/ca.crt,verify=1,reuseaddr,fork" \
  "TCP:127.0.0.1:${PJC_LOCAL_PORT}" \
  &
SOCAT_PID=$!

echo "[ok] TLS proxy running on ${BIND_ADDR}:${TLS_PORT}"
echo "[info] Party B should connect to: <this-machine-ip>:${TLS_PORT}"
echo "[info] waiting for PJC protocol to complete..."

# Wait for the PJC server to finish (exits after one successful run)
wait "$PJC_PID"
PJC_RC=$?
echo "[info] PJC server exited (rc=$PJC_RC)"
exit $PJC_RC
