#!/usr/bin/env bash
set -euo pipefail

die() { echo "[ERROR] $*" >&2; exit 1; }
log() { echo "[INFO] $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

JOB_DIR="${JOB_DIR:-}"
RUN_PJC_SERVER_SH="${RUN_PJC_SERVER_SH:-$SCRIPT_DIR/run_pjc_server.sh}"
SERVER_ADDR="${SERVER_ADDR:-0.0.0.0:10501}"
PJC_DIR="${PJC_DIR:-$REPO_ROOT/private-join-and-compute}"
GRPC_MAX_MESSAGE_MB="${GRPC_MAX_MESSAGE_MB:-512}"
PJC_GRPC_STREAM_CHUNK_ELEMENTS="${PJC_GRPC_STREAM_CHUNK_ELEMENTS:-4096}"
PJC_BUILD="${PJC_BUILD:-0}"

[[ -n "$JOB_DIR" ]] || die "JOB_DIR is required"
JOB_DIR="$(cd "$JOB_DIR" && pwd)"
[[ -f "$JOB_DIR/job_meta.json" ]] || die "missing $JOB_DIR/job_meta.json"
[[ -f "$RUN_PJC_SERVER_SH" ]] || die "missing run_pjc_server.sh: $RUN_PJC_SERVER_SH"

PY='import json,sys; m=json.load(open(sys.argv[1])); b=m.get("bucket",{}); print(b.get("field") or ""); [print(o.get("bucket")) for o in (b.get("outputs") or [])]'
mapfile -t INFO < <(python3 -c "$PY" "$JOB_DIR/job_meta.json")
BUCKET_FIELD="${INFO[0]}"
[[ -n "$BUCKET_FIELD" ]] || die "job_meta.json has no bucket_field; use run_pjc_server.sh for non-bucketed jobs"

for bucket in "${INFO[@]:1}"; do
  sub="$JOB_DIR/bucket_${BUCKET_FIELD}=${bucket}"
  [[ -f "$sub/server.csv" ]] || die "missing $sub/server.csv"
  log "serving bucket=$bucket from $sub"
  export PJC_DIR JOB_ID="$(basename "$JOB_DIR")" OUT_DIR="$sub"
  export SERVER_CSV="$sub/server.csv" SERVER_ADDR GRPC_MAX_MESSAGE_MB PJC_BUILD
  export PJC_GRPC_STREAM_CHUNK_ELEMENTS
  bash "$RUN_PJC_SERVER_SH"
done

log "all bucket server runs completed"
