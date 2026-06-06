#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# run_pjc_bucketed.sh
#
# Runs PJC for each bucket produced by prep_inputs.py (job_meta.json).
# Requires:
#   runs/<job_id>/job_meta.json with meta["bucket"]["field"] and meta["bucket"]["outputs"]
# Produces:
#   runs/<job_id>/bucket_<field>=<value>/attribution_result.json
#   runs/<job_id>/attribution_result.json (merged)  [via merge_bucket_results.py]
#
# Notes:
#   - Parallel mode uses separate ports per bucket.
#   - For simplicity, the default is sequential.
# -----------------------------------------------------------------------------

die() { echo "[ERROR] $*" >&2; exit 1; }
log() { echo "[INFO] $*"; }

JOB_DIR="${JOB_DIR:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="$(cd "$MODULE_ROOT/.." && pwd)"
PJC_DIR="${PJC_DIR:-$REPO_ROOT/a-psi/private-join-and-compute}"
RUN_PJC_SH="${RUN_PJC_SH:-./run_pjc_patched.sh}"          # path to patched run_pjc
MERGE_PY="${MERGE_PY:-./merge_bucket_results.py}"         # path to merge script
GRPC_MAX_MESSAGE_MB="${GRPC_MAX_MESSAGE_MB:-512}"
PJC_GRPC_STREAM_CHUNK_ELEMENTS="${PJC_GRPC_STREAM_CHUNK_ELEMENTS:-4096}"
PJC_REQUIRE_BUCKET_POLICY="${PJC_REQUIRE_BUCKET_POLICY:-0}"

# Parallel controls
PARALLEL="${PARALLEL:-0}"          # 0/1
MAX_JOBS="${MAX_JOBS:-4}"          # used when PARALLEL=1
BASE_PORT="${BASE_PORT:-10501}"    # used when PARALLEL=1

usage() {
  cat <<EOF
Usage:
  JOB_DIR=runs/<job_id> $0 [--parallel] [--max-jobs N] [--base-port P]

Env:
  JOB_DIR               required (runs/<job_id>)
  PJC_DIR               path to google/private-join-and-compute
  RUN_PJC_SH            path to run_pjc_patched.sh
  MERGE_PY              path to merge_bucket_results.py
  GRPC_MAX_MESSAGE_MB   grpc limit (default 512)
  PJC_GRPC_STREAM_CHUNK_ELEMENTS encrypted elements per streaming frame (default 4096; 0=legacy unary)
  PARALLEL              0/1 (default 0)
  MAX_JOBS              parallel workers (default 4)
  BASE_PORT             base port (default 10501)
EOF
}

# parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --parallel) PARALLEL=1; shift ;;
    --max-jobs) MAX_JOBS="$2"; shift 2 ;;
    --base-port) BASE_PORT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown arg: $1" ;;
  esac
done

[[ -n "$JOB_DIR" ]] || die "JOB_DIR is required"
JOB_DIR="$(cd "$JOB_DIR" && pwd)"
[[ -f "$JOB_DIR/job_meta.json" ]] || die "missing $JOB_DIR/job_meta.json"

VALIDATE_BUCKET_POLICY_PY="$SCRIPT_DIR/bucket_policy.py"
[[ -f "$VALIDATE_BUCKET_POLICY_PY" ]] || die "missing bucket policy helper: $VALIDATE_BUCKET_POLICY_PY"
POLICY_CMD=(python3 "$VALIDATE_BUCKET_POLICY_PY" --job-meta "$JOB_DIR/job_meta.json")
if [[ "$PJC_REQUIRE_BUCKET_POLICY" == "1" ]]; then
  POLICY_CMD+=(--require-policy)
fi
"${POLICY_CMD[@]}" >/dev/null

# Extract buckets with python (avoid jq dependency)
PY='import json,sys; m=json.load(open(sys.argv[1])); b=m.get("bucket",{}); field=b.get("field"); outs=b.get("outputs") or []; print(field or ""); print(len(outs)); [print(o.get("bucket")) for o in outs]'
mapfile -t INFO < <(python3 -c "$PY" "$JOB_DIR/job_meta.json")
BUCKET_FIELD="${INFO[0]}"
BUCKET_N="${INFO[1]}"

if [[ -z "$BUCKET_FIELD" || "$BUCKET_N" == "0" ]]; then
  die "job_meta.json indicates no buckets. Use run_pjc_patched.sh directly."
fi

log "bucket_field=$BUCKET_FIELD buckets=$BUCKET_N"
log "mode: PARALLEL=$PARALLEL MAX_JOBS=$MAX_JOBS BASE_PORT=$BASE_PORT"

run_one_bucket() {
  local bucket="$1"
  local port="$2"
  local sub="$JOB_DIR/bucket_${BUCKET_FIELD}=${bucket}"

  [[ -f "$sub/server.csv" ]] || die "missing $sub/server.csv"
  [[ -f "$sub/client.csv" ]] || die "missing $sub/client.csv"

  local exposure_n purchase_n
  exposure_n="$(wc -l < "$sub/server.csv" | tr -d ' ')"
  purchase_n="$(wc -l < "$sub/client.csv" | tr -d ' ')"
  if [[ "$exposure_n" == "0" || "$purchase_n" == "0" ]]; then
    log "skip empty bucket=$bucket exposure_n=$exposure_n purchase_n=$purchase_n"
    cat > "$sub/attribution_result.json" <<JSON
{
  "job_id": "$(basename "$JOB_DIR")",
  "server_addr": "skipped-empty-bucket",
  "intersection_size": 0,
  "intersection_sum": 0
}
JSON
    return 0
  fi

  log "bucket=$bucket port=$port"
  export PJC_DIR="$PJC_DIR"
  export JOB_ID="$(basename "$JOB_DIR")"
  export OUT_DIR="$sub"
  export SERVER_CSV="$sub/server.csv"
  export CLIENT_CSV="$sub/client.csv"
  [[ -f "$sub/job_meta.json" ]] && export PJC_JOB_META="$sub/job_meta.json" || unset PJC_JOB_META || true
  [[ -f "$sub/input_commitments.json" ]] && export PJC_INPUT_COMMITMENT="$sub/input_commitments.json" || unset PJC_INPUT_COMMITMENT || true
  export SERVER_ADDR="127.0.0.1:$port"
  export GRPC_MAX_MESSAGE_MB="$GRPC_MAX_MESSAGE_MB"
  export PJC_GRPC_STREAM_CHUNK_ELEMENTS="$PJC_GRPC_STREAM_CHUNK_ELEMENTS"
  bash "$RUN_PJC_SH"
}

if [[ "$PARALLEL" == "0" ]]; then
  i=0
  for bucket in "${INFO[@]:2}"; do
    run_one_bucket "$bucket" "$BASE_PORT"
    i=$((i+1))
  done
else
  # simple job control
  sem_count=0
  i=0
  for bucket in "${INFO[@]:2}"; do
    port=$((BASE_PORT + i))
    run_one_bucket "$bucket" "$port" &
    sem_count=$((sem_count+1))
    i=$((i+1))
    if [[ "$sem_count" -ge "$MAX_JOBS" ]]; then
      wait -n
      sem_count=$((sem_count-1))
    fi
  done
  wait
fi

log "merging bucket results..."
python3 "$MERGE_PY" --job-dir "$JOB_DIR"

log "done."
