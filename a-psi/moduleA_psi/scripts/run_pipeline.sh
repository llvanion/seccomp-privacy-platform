#!/usr/bin/env bash
set -euo pipefail

die() { echo "[ERROR] $*" >&2; exit 1; }
log() { echo "[INFO] $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Keep original repo root inference but allow override
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

PREP_PY="${PREP_PY:-$REPO_ROOT/moduleA_psi/scripts/prep_inputs.py}"
RUN_PJC_SH="${RUN_PJC_SH:-$REPO_ROOT/moduleA_psi/scripts/run_pjc.sh}"
POLICY_PY="${POLICY_PY:-$REPO_ROOT/moduleA_psi/scripts/policy_release.py}"

# New helpers (recommended)
RUN_PJC_PATCHED_SH="${RUN_PJC_PATCHED_SH:-$SCRIPT_DIR/run_pjc_patched.sh}"
RUN_PJC_BUCKETED_SH="${RUN_PJC_BUCKETED_SH:-$SCRIPT_DIR/run_pjc_bucketed.sh}"
MERGE_PY="${MERGE_PY:-$SCRIPT_DIR/merge_bucket_results.py}"

RUNS_DIR="${RUNS_DIR:-$REPO_ROOT/runs}"

CRITEO_TSV=""
OUT_DIR=""
JOB_ID=""
START_TS=""
END_TS=""
VALUE_MODE="count"
BUCKET_FIELD=""
HMAC_SECRET=""
USE_CONVERSION_TS=0

K_THRESHOLD="20"
RATE_N="5"
CALLER="demo"

# Parallel bucket execution
BUCKET_PARALLEL=0
BUCKET_MAX_JOBS=4
BUCKET_BASE_PORT=10501

usage() {
  cat <<EOF
Usage:
  $0 --criteo-tsv <path> --start-ts <unix_ts> --end-ts <unix_ts> --out <runs/job_id> [options]

Options:
  --job-id <id>              Optional job id (default: basename of --out)
  --value-mode <mode>        count|amount (default: count)
  --bucket-field <field>     Optional business bucket field (e.g. device_type)
  --hmac-secret <secret>     Optional anonymization secret for W1
  --purchase-use-conversion-ts  Filter purchases by conversion_ts

  # W2 policy release
  --k <int>                  k-threshold (default: 20)
  --n <int>                  rate limit N (default: 5)
  --caller <id>              caller id (default: demo)

  # Bucket compute controls (when --bucket-field is set)
  --bucket-parallel          Run buckets in parallel (default: sequential)
  --bucket-max-jobs <int>    Max parallel workers (default: 4)
  --bucket-base-port <int>   Base port for bucket workers (default: 10501)

Examples:
  $0 --criteo-tsv data/CriteoSearchData --start-ts 1596439471 --end-ts 1597845871 --out runs/w3_demo

  # Business bucket + parallel compute
  $0 --criteo-tsv data/CriteoSearchData --start-ts 1596439471 --end-ts 1597845871 --out runs/w3_b \
     --bucket-field device_type --bucket-parallel --bucket-max-jobs 8
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --criteo-tsv) CRITEO_TSV="$2"; shift 2 ;;
    --out) OUT_DIR="$2"; shift 2 ;;
    --job-id) JOB_ID="$2"; shift 2 ;;
    --start-ts) START_TS="$2"; shift 2 ;;
    --end-ts) END_TS="$2"; shift 2 ;;
    --value-mode) VALUE_MODE="$2"; shift 2 ;;
    --bucket-field) BUCKET_FIELD="$2"; shift 2 ;;
    --hmac-secret) HMAC_SECRET="$2"; shift 2 ;;
    --purchase-use-conversion-ts) USE_CONVERSION_TS=1; shift ;;
    --k) K_THRESHOLD="$2"; shift 2 ;;
    --n) RATE_N="$2"; shift 2 ;;
    --caller) CALLER="$2"; shift 2 ;;
    --bucket-parallel) BUCKET_PARALLEL=1; shift ;;
    --bucket-max-jobs) BUCKET_MAX_JOBS="$2"; shift 2 ;;
    --bucket-base-port) BUCKET_BASE_PORT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown arg: $1" ;;
  esac
done

[[ -n "$CRITEO_TSV" ]] || die "--criteo-tsv required"
[[ -n "$OUT_DIR" ]] || die "--out required"
[[ -n "$START_TS" ]] || die "--start-ts required"
[[ -n "$END_TS" ]] || die "--end-ts required"

mkdir -p "$RUNS_DIR"
OUT_DIR="$(cd "$(dirname "$OUT_DIR")" && pwd)/$(basename "$OUT_DIR")"
JOB_ID="${JOB_ID:-$(basename "$OUT_DIR")}"
mkdir -p "$OUT_DIR"

# sanity
[[ -f "$PREP_PY" ]] || die "PREP_PY not found: $PREP_PY"
[[ -f "$POLICY_PY" ]] || die "POLICY_PY not found: $POLICY_PY"

log "job_id=$JOB_ID"
log "out_dir=$OUT_DIR"

log "Stage1 Prep: generating PJC inputs + job_meta.json"
PREP_CMD=(python3 "$PREP_PY"
  --criteo-tsv "$CRITEO_TSV"
  --out "$OUT_DIR"
  --start-ts "$START_TS"
  --end-ts "$END_TS"
  --value-mode "$VALUE_MODE"
  --job-id "$JOB_ID"
)
if [[ -n "$BUCKET_FIELD" ]]; then PREP_CMD+=(--bucket-field "$BUCKET_FIELD"); fi
if [[ -n "$HMAC_SECRET" ]]; then PREP_CMD+=(--hmac-secret "$HMAC_SECRET"); fi
if [[ "$USE_CONVERSION_TS" == "1" ]]; then PREP_CMD+=(--purchase-use-conversion-ts); fi
"${PREP_CMD[@]}"

[[ -f "$OUT_DIR/job_meta.json" ]] || die "missing $OUT_DIR/job_meta.json after prep"

log "Stage2 Run: executing PJC PSI"
if [[ -z "$BUCKET_FIELD" ]]; then
  # Non-bucketed job: run once
  export SERVER_CSV="$OUT_DIR/server.csv"
  export CLIENT_CSV="$OUT_DIR/client.csv"
  export OUT_DIR="$OUT_DIR"
  export JOB_ID="$JOB_ID"
  bash "$RUN_PJC_SH"
else
  # Bucketed job: recommend patched runner + merge
  export JOB_DIR="$OUT_DIR"
  export MERGE_PY="$MERGE_PY"
  export RUN_PJC_SH="$RUN_PJC_PATCHED_SH"
  export BASE_PORT="$BUCKET_BASE_PORT"
  export MAX_JOBS="$BUCKET_MAX_JOBS"
  export PARALLEL="$BUCKET_PARALLEL"
  bash "$RUN_PJC_BUCKETED_SH"
fi

[[ -f "$OUT_DIR/attribution_result.json" ]] || die "missing $OUT_DIR/attribution_result.json after PJC"

log "Stage3 Policy: applying threshold/rate/audit and producing public_report.json"
AUDIT_LOG="$OUT_DIR/audit_log.jsonl"
python3 "$POLICY_PY" \
  --job-dir "$OUT_DIR" \
  --caller "$CALLER" \
  --k "$K_THRESHOLD" \
  --n "$RATE_N" \
  --audit-log "$AUDIT_LOG"

log "OK. Outputs:"
log "  $OUT_DIR/job_meta.json"
log "  $OUT_DIR/attribution_result.json"
log "  $OUT_DIR/public_report.json"
log "  $AUDIT_LOG"
