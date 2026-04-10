#!/usr/bin/env bash
set -euo pipefail

die(){ echo "[ERROR] $*" >&2; exit 1; }
log(){ echo "[INFO] $*"; }

# -----------------------------------------------------------------------------
# run_pipeline_bucketed.sh
#
# End-to-end A-line pipeline (Prep -> PJC -> Policy Release)
# - If --bucket-field is provided: run PJC per bucket (optionally in parallel),
#   merge bucket results into job-level attribution_result.json, then run policy.
#
# Paths assume repo layout:
#   moduleA_psi/scripts/prep_inputs.py
#   moduleA_psi/scripts/run_pjc.sh
#   moduleA_psi/scripts/policy_release.py
#   moduleA_psi/scripts/run_pjc_bucketed.sh
#   moduleA_psi/scripts/merge_bucket_results.py
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

PREP_PY="${PREP_PY:-$REPO_ROOT/moduleA_psi/scripts/prep_inputs.py}"
RUN_PJC_SH="${RUN_PJC_SH:-$REPO_ROOT/moduleA_psi/scripts/run_pjc.sh}"
POLICY_PY="${POLICY_PY:-$REPO_ROOT/moduleA_psi/scripts/policy_release.py}"

RUN_PJC_BUCKETED_SH="${RUN_PJC_BUCKETED_SH:-$REPO_ROOT/moduleA_psi/scripts/run_pjc_bucketed.sh}"
MERGE_PY="${MERGE_PY:-$REPO_ROOT/moduleA_psi/scripts/merge_bucket_results.py}"

# Inputs
CRITEO_TSV=""
OUT_DIR=""
JOB_ID=""
START_TS=""
END_TS=""
VALUE_MODE="count"
BUCKET_FIELD=""
HMAC_SECRET=""
USE_CONVERSION_TS=0

# Policy
K_THRESHOLD="20"
RATE_N="5"
CALLER="demo"

# Bucket compute controls
BUCKET_PARALLEL=0
BUCKET_MAX_JOBS=4
BUCKET_BASE_PORT=10501
GRPC_MAX_MESSAGE_MB="${GRPC_MAX_MESSAGE_MB:-512}"

usage(){
  cat <<EOF
Usage:
  bash moduleA_psi/scripts/run_pipeline_bucketed.sh \
    --criteo-tsv <path> --start-ts <unix_ts> --end-ts <unix_ts> --out <runs/job_id> [options]

Options:
  --job-id <id>
  --value-mode count|amount              (default: count)
  --bucket-field <field>                 Enable business buckets
  --hmac-secret <secret>
  --purchase-use-conversion-ts

  --k <int>                              Threshold-k (default: 20)
  --n <int>                              Max queries per caller (default: 5)
  --caller <id>                          (default: demo)

  --bucket-parallel                      Run buckets in parallel
  --bucket-max-jobs <int>                Parallel workers (default: 4)
  --bucket-base-port <int>               Base port (default: 10501)

Env:
  GRPC_MAX_MESSAGE_MB                    gRPC max message MB (default: 512)
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

    --k) K_THRESHOLD="$2"; shift 2;;
    --n) RATE_N="$2"; shift 2;;
    --caller) CALLER="$2"; shift 2;;

    --bucket-parallel) BUCKET_PARALLEL=1; shift;;
    --bucket-max-jobs) BUCKET_MAX_JOBS="$2"; shift 2;;
    --bucket-base-port) BUCKET_BASE_PORT="$2"; shift 2;;

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

log "Stage2: run PJC"
if [[ -z "$BUCKET_FIELD" ]]; then
  export OUT_DIR="$OUT_DIR"
  export JOB_ID="$JOB_ID"
  export SERVER_CSV="$OUT_DIR/server.csv"
  export CLIENT_CSV="$OUT_DIR/client.csv"
  export GRPC_MAX_MESSAGE_MB="$GRPC_MAX_MESSAGE_MB"
  bash "$RUN_PJC_SH"
else
  [[ -f "$RUN_PJC_BUCKETED_SH" ]] || die "missing run_pjc_bucketed.sh: $RUN_PJC_BUCKETED_SH"
  [[ -f "$MERGE_PY" ]] || die "missing merge_bucket_results.py: $MERGE_PY"

  export JOB_DIR="$OUT_DIR"
  export RUN_PJC_SH="$RUN_PJC_SH"
  export MERGE_PY="$MERGE_PY"
  export PARALLEL="$BUCKET_PARALLEL"
  export MAX_JOBS="$BUCKET_MAX_JOBS"
  export BASE_PORT="$BUCKET_BASE_PORT"
  export GRPC_MAX_MESSAGE_MB="$GRPC_MAX_MESSAGE_MB"
  bash "$RUN_PJC_BUCKETED_SH"
fi

[[ -f "$OUT_DIR/attribution_result.json" ]] || die "missing $OUT_DIR/attribution_result.json"

log "Stage3: policy release"
AUDIT_LOG="$OUT_DIR/audit_log.jsonl"
python3 "$POLICY_PY"   --job-dir "$OUT_DIR"   --caller "$CALLER"   --k "$K_THRESHOLD"   --n "$RATE_N"   --audit-log "$AUDIT_LOG"

log "DONE"
log "Outputs:"
log "  $OUT_DIR/job_meta.json"
log "  $OUT_DIR/attribution_result.json"
log "  $OUT_DIR/public_report.json"
log "  $AUDIT_LOG"
