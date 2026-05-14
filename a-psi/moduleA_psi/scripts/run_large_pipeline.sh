#!/usr/bin/env bash
set -euo pipefail

die(){ echo "[ERROR] $*" >&2; exit 1; }
log(){ echo "[INFO] $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

PREP_PY="${PREP_PY:-$REPO_ROOT/moduleA_psi/scripts/prep_inputs.py}"
RUN_PJC_SH="${RUN_PJC_SH:-$REPO_ROOT/moduleA_psi/scripts/run_pjc.sh}"
POLICY_PY="${POLICY_PY:-$REPO_ROOT/moduleA_psi/scripts/policy_release.py}"

SHARD_PY="${SHARD_PY:-$REPO_ROOT/moduleA_psi/scripts/shard_pjc_inputs.py}"
RUN_SHARDED_SH="${RUN_SHARDED_SH:-$REPO_ROOT/moduleA_psi/scripts/run_pjc_sharded_parallel.sh}"

CRITEO_TSV=""
OUT_DIR=""
JOB_ID=""
START_TS=""
END_TS=""
VALUE_MODE="count"
BUCKET_FIELD=""
HMAC_SECRET=""
USE_CONVERSION_TS=0

NUM_SHARDS=0
SHARD_SALT="pjc-shard-v1"
MAX_JOBS=4
BASE_PORT=11001
GRPC_MAX_MESSAGE_MB="${GRPC_MAX_MESSAGE_MB:-512}"
PJC_GRPC_STREAM_CHUNK_ELEMENTS="${PJC_GRPC_STREAM_CHUNK_ELEMENTS:-4096}"

K_THRESHOLD="20"
RATE_N="5"
CALLER="demo"

usage(){
  cat <<EOF
Usage:
  bash moduleA_psi/scripts/run_large_pipeline.sh \
    --criteo-tsv <path> --start-ts <unix_ts> --end-ts <unix_ts> --out <runs/job_id> [options]

Options:
  --job-id <id>
  --value-mode count|amount
  --bucket-field <field>
  --hmac-secret <secret>
  --purchase-use-conversion-ts

  --num-shards <int>         0/1=no sharding; >1 enable hash sharding
  --shard-salt <str>         (default: pjc-shard-v1)
  --max-jobs <int>           (default: 4)
  --base-port <int>          (default: 11001)
  PJC_GRPC_STREAM_CHUNK_ELEMENTS env controls streaming frame size (default: 4096; 0=legacy unary)

  --k <int>                  (default: 20)
  --n <int>                  (default: 5)
  --caller <id>              (default: demo)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --criteo-tsv) CRITEO_TSV="$2"; shift 2;;
    --out) OUT_DIR="$2"; shift 2;;
    --job-id) JOB_ID="$2"; shift 2;;
    --start-ts) START_TS="$2"; shift 2;;
    --end-ts) END_TS="$2"; shift 2;;
    --value-mode) VALUE_MODE="$2"; shift 2;;
    --bucket-field) BUCKET_FIELD="$2"; shift 2;;
    --hmac-secret) HMAC_SECRET="$2"; shift 2;;
    --purchase-use-conversion-ts) USE_CONVERSION_TS=1; shift;;

    --num-shards) NUM_SHARDS="$2"; shift 2;;
    --shard-salt) SHARD_SALT="$2"; shift 2;;
    --max-jobs) MAX_JOBS="$2"; shift 2;;
    --base-port) BASE_PORT="$2"; shift 2;;

    --k) K_THRESHOLD="$2"; shift 2;;
    --n) RATE_N="$2"; shift 2;;
    --caller) CALLER="$2"; shift 2;;

    -h|--help) usage; exit 0;;
    *) die "unknown arg: $1";;
  esac
done

[[ -n "$CRITEO_TSV" ]] || die "--criteo-tsv required"
[[ -n "$OUT_DIR" ]] || die "--out required"
[[ -n "$START_TS" ]] || die "--start-ts required"
[[ -n "$END_TS" ]] || die "--end-ts required"
[[ -f "$PREP_PY" ]] || die "missing PREP_PY: $PREP_PY"
[[ -f "$RUN_PJC_SH" ]] || die "missing RUN_PJC_SH: $RUN_PJC_SH"
[[ -f "$POLICY_PY" ]] || die "missing POLICY_PY: $POLICY_PY"

JOB_ID="${JOB_ID:-$(basename "$OUT_DIR")}"
mkdir -p "$(dirname "$OUT_DIR")"
OUT_DIR="$(cd "$(dirname "$OUT_DIR")" && pwd)/$(basename "$OUT_DIR")"
mkdir -p "$OUT_DIR"

log "job_id=$JOB_ID"
log "out_dir=$OUT_DIR"

log "Stage1: prep inputs"
PREP_CMD=(python3 "$PREP_PY"
  --criteo-tsv "$CRITEO_TSV"
  --out "$OUT_DIR"
  --start-ts "$START_TS"
  --end-ts "$END_TS"
  --value-mode "$VALUE_MODE"
  --job-id "$JOB_ID"
)
[[ -n "$BUCKET_FIELD" ]] && PREP_CMD+=(--bucket-field "$BUCKET_FIELD")
[[ -n "$HMAC_SECRET" ]] && PREP_CMD+=(--hmac-secret "$HMAC_SECRET")
[[ "$USE_CONVERSION_TS" == "1" ]] && PREP_CMD+=(--purchase-use-conversion-ts)
"${PREP_CMD[@]}"

[[ -f "$OUT_DIR/job_meta.json" ]] || die "missing $OUT_DIR/job_meta.json"

if [[ "$NUM_SHARDS" -le 1 ]]; then
  log "Stage2: direct PJC (no sharding)"
  export OUT_DIR="$OUT_DIR"
  export JOB_ID="$JOB_ID"
  export SERVER_CSV="$OUT_DIR/server.csv"
  export CLIENT_CSV="$OUT_DIR/client.csv"
  export GRPC_MAX_MESSAGE_MB="$GRPC_MAX_MESSAGE_MB"
  export PJC_GRPC_STREAM_CHUNK_ELEMENTS="$PJC_GRPC_STREAM_CHUNK_ELEMENTS"
  bash "$RUN_PJC_SH"
else
  [[ -f "$SHARD_PY" ]] || die "missing shard_pjc_inputs.py: $SHARD_PY"
  [[ -f "$RUN_SHARDED_SH" ]] || die "missing run_pjc_sharded_parallel.sh: $RUN_SHARDED_SH"
  log "Stage2: hash sharding into $NUM_SHARDS shard(s)"
  python3 "$SHARD_PY" --job-dir "$OUT_DIR" --num-shards "$NUM_SHARDS" --salt "$SHARD_SALT"
  log "Stage3: parallel PJC over shards"
  JOB_DIR="$OUT_DIR" RUN_PJC_SH="$RUN_PJC_SH" BASE_PORT="$BASE_PORT" MAX_JOBS="$MAX_JOBS" PJC_GRPC_STREAM_CHUNK_ELEMENTS="$PJC_GRPC_STREAM_CHUNK_ELEMENTS" bash "$RUN_SHARDED_SH"
fi

[[ -f "$OUT_DIR/attribution_result.json" ]] || die "missing $OUT_DIR/attribution_result.json"

log "Stage4: policy release"
AUDIT_LOG="$OUT_DIR/audit_log.jsonl"
python3 "$POLICY_PY"   --job-dir "$OUT_DIR"   --caller "$CALLER"   --k "$K_THRESHOLD"   --n "$RATE_N"   --audit-log "$AUDIT_LOG"

log "DONE"
log "Outputs:"
log "  $OUT_DIR/job_meta.json"
log "  $OUT_DIR/attribution_result.json"
log "  $OUT_DIR/public_report.json"
log "  $AUDIT_LOG"
