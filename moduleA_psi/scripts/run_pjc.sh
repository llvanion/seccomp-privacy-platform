#!/usr/bin/env bash
set -euo pipefail

# ---- Config (can override via env vars) ----
PJC_DIR="${PJC_DIR:-$HOME/Desktop/private-join-and-compute}"
JOB_ID="${JOB_ID:-$(date +%Y%m%d-%H%M%S)}"
OUT_DIR="${OUT_DIR:-$PWD/runs/$JOB_ID}"
SERVER_CSV="${SERVER_CSV:-/tmp/server.csv}"
CLIENT_CSV="${CLIENT_CSV:-/tmp/client.csv}"
SERVER_ADDR="${SERVER_ADDR:-127.0.0.1:10501}"

mkdir -p "$OUT_DIR"

# ---- Ensure we don't route localhost gRPC through proxy ----
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY || true
export no_proxy="localhost,127.0.0.1,0.0.0.0"
export NO_PROXY="$no_proxy"

# ---- Quick sanity checks ----
if [[ ! -d "$PJC_DIR" ]]; then
  echo "[error] PJC_DIR not found: $PJC_DIR" >&2
  exit 1
fi

if [[ ! -f "$SERVER_CSV" ]]; then
  echo "[error] SERVER_CSV not found: $SERVER_CSV" >&2
  echo "Tip: generate dummy data first:" >&2
  echo "  cd $PJC_DIR && bazel run //private_join_and_compute:generate_dummy_data -- --server_data_file=/tmp/server.csv --client_data_file=/tmp/client.csv" >&2
  exit 1
fi

if [[ ! -f "$CLIENT_CSV" ]]; then
  echo "[error] CLIENT_CSV not found: $CLIENT_CSV" >&2
  exit 1
fi

echo "[info] JOB_ID=$JOB_ID"
echo "[info] OUT_DIR=$OUT_DIR"
echo "[info] PJC_DIR=$PJC_DIR"
echo "[info] SERVER_CSV=$SERVER_CSV"
echo "[info] CLIENT_CSV=$CLIENT_CSV"
echo "[info] SERVER_ADDR=$SERVER_ADDR"

# ---- Start server (background) ----
cd "$PJC_DIR"
SERVER_LOG="$OUT_DIR/server.log"
CLIENT_LOG="$OUT_DIR/client.log"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "[info] starting server..."
# Use bazel-bin to avoid extra bazel output in stdout; assumes you've built once.
bazel-bin/private_join_and_compute/server --server_data_file="$SERVER_CSV" >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

# Wait until server listens
echo "[info] waiting for server to listen..."
for i in {1..60}; do
  if ss -lntp 2>/dev/null | grep -q ":10501"; then
    break
  fi
  sleep 0.2
done

if ! ss -lntp 2>/dev/null | grep -q ":10501"; then
  echo "[error] server did not start listening on 10501. Check $SERVER_LOG" >&2
  exit 1
fi

# ---- Run client ----
echo "[info] running client..."
set +e
bazel-bin/private_join_and_compute/client \
  --client_data_file="$CLIENT_CSV" \
  --port="$SERVER_ADDR" \
  >"$CLIENT_LOG" 2>&1
CLIENT_RC=$?
set -e

if [[ $CLIENT_RC -ne 0 ]]; then
  echo "[error] client failed (rc=$CLIENT_RC). Check $CLIENT_LOG and $SERVER_LOG" >&2
  exit $CLIENT_RC
fi

# ---- Parse results ----
# Expected line: "Client: The intersection size is 50 and the intersection-sum is 2837"
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
  "server_csv": "$SERVER_CSV",
  "client_csv": "$CLIENT_CSV",
  "intersection_size": $INTERSECTION_SIZE,
  "intersection_sum": $INTERSECTION_SUM
}
JSON

echo "[ok] $RESULT_JSON"
echo "[ok] intersection_size=$INTERSECTION_SIZE intersection_sum=$INTERSECTION_SUM"
