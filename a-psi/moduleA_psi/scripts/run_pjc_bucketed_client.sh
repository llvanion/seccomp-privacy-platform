#!/usr/bin/env bash
set -euo pipefail

die() { echo "[ERROR] $*" >&2; exit 1; }
log() { echo "[INFO] $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

JOB_DIR="${JOB_DIR:-}"
RUN_PJC_CLIENT_SH="${RUN_PJC_CLIENT_SH:-$SCRIPT_DIR/run_pjc_client.sh}"
MERGE_PY="${MERGE_PY:-$SCRIPT_DIR/merge_bucket_results.py}"
SERVER_ADDR="${SERVER_ADDR:-127.0.0.1:10501}"
PJC_DIR="${PJC_DIR:-$REPO_ROOT/private-join-and-compute}"
GRPC_MAX_MESSAGE_MB="${GRPC_MAX_MESSAGE_MB:-512}"
PJC_GRPC_STREAM_CHUNK_ELEMENTS="${PJC_GRPC_STREAM_CHUNK_ELEMENTS:-4096}"
PJC_BUILD="${PJC_BUILD:-0}"
SERVER_CONNECT_RETRIES="${SERVER_CONNECT_RETRIES:-20}"
SERVER_CONNECT_DELAY_SEC="${SERVER_CONNECT_DELAY_SEC:-2}"
RESULT_CALLBACK_URL="${RESULT_CALLBACK_URL:-}"
RESULT_CALLBACK_TOKEN="${RESULT_CALLBACK_TOKEN:-}"
SHARED_RESULT_DIR="${SHARED_RESULT_DIR:-}"

[[ -n "$JOB_DIR" ]] || die "JOB_DIR is required"
JOB_DIR="$(cd "$JOB_DIR" && pwd)"
[[ -f "$JOB_DIR/job_meta.json" ]] || die "missing $JOB_DIR/job_meta.json"
[[ -f "$RUN_PJC_CLIENT_SH" ]] || die "missing run_pjc_client.sh: $RUN_PJC_CLIENT_SH"
[[ -f "$MERGE_PY" ]] || die "missing merge_bucket_results.py: $MERGE_PY"

PY='import json,sys; m=json.load(open(sys.argv[1])); b=m.get("bucket",{}); print(b.get("field") or ""); [print(o.get("bucket")) for o in (b.get("outputs") or [])]'
mapfile -t INFO < <(python3 -c "$PY" "$JOB_DIR/job_meta.json")
BUCKET_FIELD="${INFO[0]}"
[[ -n "$BUCKET_FIELD" ]] || die "job_meta.json has no bucket_field; use run_pjc_client.sh for non-bucketed jobs"

for bucket in "${INFO[@]:1}"; do
  sub="$JOB_DIR/bucket_${BUCKET_FIELD}=${bucket}"
  [[ -f "$sub/client.csv" ]] || die "missing $sub/client.csv"
  log "running bucket=$bucket against $SERVER_ADDR"
  export PJC_DIR JOB_ID="$(basename "$JOB_DIR")" OUT_DIR="$sub"
  export CLIENT_CSV="$sub/client.csv" SERVER_ADDR GRPC_MAX_MESSAGE_MB PJC_BUILD
  export PJC_GRPC_STREAM_CHUNK_ELEMENTS
  export SERVER_CONNECT_RETRIES SERVER_CONNECT_DELAY_SEC
  export RESULT_CALLBACK_URL RESULT_CALLBACK_TOKEN SHARED_RESULT_DIR
  bash "$RUN_PJC_CLIENT_SH"
done

log "merging bucket results under $JOB_DIR"
python3 "$MERGE_PY" --job-dir "$JOB_DIR" --strict

if [[ -n "$SHARED_RESULT_DIR" && -f "$JOB_DIR/attribution_result.json" ]]; then
  mkdir -p "$SHARED_RESULT_DIR"
  cp "$JOB_DIR/attribution_result.json" "$SHARED_RESULT_DIR/$(basename "$JOB_DIR").json"
  log "copied merged result to $SHARED_RESULT_DIR/$(basename "$JOB_DIR").json"
fi

log "all bucket client runs completed"
