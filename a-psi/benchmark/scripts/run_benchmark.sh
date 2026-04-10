#!/usr/bin/env bash
set -euo pipefail
die(){ echo "[ERROR] $*" >&2; exit 1; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

CRITEO_TSV=""
START_TS=""
END_TS=""
CASES="preset_small"
VALUE_MODE="count"
BUCKET_FIELD=""
NUM_SHARDS=16
MAX_JOBS=8
BASE_PORT=11001
K=20
N=5

usage(){
  echo "Usage: bash benchmark/scripts/run_benchmark.sh --criteo-tsv <path> --start-ts <ts> --end-ts <ts> [--cases preset_small|parallel_sweep|bucket_demo|policy_sweep] [--bucket-field device_type]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --criteo-tsv) CRITEO_TSV="$2"; shift 2;;
    --start-ts) START_TS="$2"; shift 2;;
    --end-ts) END_TS="$2"; shift 2;;
    --cases) CASES="$2"; shift 2;;
    --value-mode) VALUE_MODE="$2"; shift 2;;
    --bucket-field) BUCKET_FIELD="$2"; shift 2;;
    --num-shards) NUM_SHARDS="$2"; shift 2;;
    --max-jobs) MAX_JOBS="$2"; shift 2;;
    --base-port) BASE_PORT="$2"; shift 2;;
    --k) K="$2"; shift 2;;
    --n) N="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) die "unknown arg: $1";;
  esac
done

[[ -n "$CRITEO_TSV" ]] || die "--criteo-tsv required"
[[ -n "$START_TS" ]] || die "--start-ts required"
[[ -n "$END_TS" ]] || die "--end-ts required"

RUN_CASE="$REPO_ROOT/benchmark/scripts/run_case.sh"
[[ -f "$RUN_CASE" ]] || die "missing $RUN_CASE"

mkdir -p "$REPO_ROOT/benchmark/out"

run_case(){
  local case_id="$1"
  local out_job="$2"
  local shards="$3"
  local jobs="$4"
  local k="$5"
  local n="$6"
  local bucket="$7"

  CASE_ID="$case_id" \
  CRITEO_TSV="$CRITEO_TSV" \
  START_TS="$START_TS" \
  END_TS="$END_TS" \
  OUT_JOB_DIR="$out_job" \
  NUM_SHARDS="$shards" \
  MAX_JOBS="$jobs" \
  BASE_PORT="$BASE_PORT" \
  VALUE_MODE="$VALUE_MODE" \
  BUCKET_FIELD="$bucket" \
  K="$k" \
  N="$n" \
  CALLER="bench" \
  bash "$RUN_CASE"
}

case "$CASES" in
  preset_small)
    run_case "small_s8_j4"  "runs/bench_small_s8_j4"  8  4 "$K" "$N" ""
    run_case "small_s16_j8" "runs/bench_small_s16_j8" 16 8 "$K" "$N" ""
    ;;
  parallel_sweep)
    run_case "par_s16_j1" "runs/bench_par_s16_j1" 16 1 "$K" "$N" ""
    run_case "par_s16_j2" "runs/bench_par_s16_j2" 16 2 "$K" "$N" ""
    run_case "par_s16_j4" "runs/bench_par_s16_j4" 16 4 "$K" "$N" ""
    run_case "par_s16_j8" "runs/bench_par_s16_j8" 16 8 "$K" "$N" ""
    ;;
  bucket_demo)
    [[ -n "$BUCKET_FIELD" ]] || die "--bucket-field required for bucket_demo"
    run_case "bucket_s16_j8" "runs/bench_bucket_s16_j8" 16 8 "$K" "$N" "$BUCKET_FIELD"
    ;;
  policy_sweep)
    [[ -n "$BUCKET_FIELD" ]] || die "--bucket-field required for policy_sweep"
    run_case "policy_k5"   "runs/bench_policy_k5"   "$NUM_SHARDS" "$MAX_JOBS" 5   "$N" "$BUCKET_FIELD"
    run_case "policy_k20"  "runs/bench_policy_k20"  "$NUM_SHARDS" "$MAX_JOBS" 20  "$N" "$BUCKET_FIELD"
    run_case "policy_k50"  "runs/bench_policy_k50"  "$NUM_SHARDS" "$MAX_JOBS" 50  "$N" "$BUCKET_FIELD"
    run_case "policy_k100" "runs/bench_policy_k100" "$NUM_SHARDS" "$MAX_JOBS" 100 "$N" "$BUCKET_FIELD"
    ;;
  *)
    die "unknown cases: $CASES"
    ;;
esac

echo "[ok] Done. Next: python3 benchmark/scripts/summarize_and_plot.py"
