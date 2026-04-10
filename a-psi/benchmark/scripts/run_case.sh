#!/usr/bin/env bash
set -euo pipefail
die(){ echo "[ERROR] $*" >&2; exit 1; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

CASE_ID="${CASE_ID:-}"
CRITEO_TSV="${CRITEO_TSV:-}"
START_TS="${START_TS:-}"
END_TS="${END_TS:-}"
OUT_JOB_DIR="${OUT_JOB_DIR:-}"

NUM_SHARDS="${NUM_SHARDS:-0}"
MAX_JOBS="${MAX_JOBS:-4}"
BASE_PORT="${BASE_PORT:-11001}"
BUCKET_FIELD="${BUCKET_FIELD:-}"
VALUE_MODE="${VALUE_MODE:-count}"
K="${K:-20}"
N="${N:-5}"
CALLER="${CALLER:-bench}"
GRPC_MAX_MESSAGE_MB="${GRPC_MAX_MESSAGE_MB:-512}"

[[ -n "$CASE_ID" ]] || die "CASE_ID required"
[[ -n "$CRITEO_TSV" ]] || die "CRITEO_TSV required"
[[ -n "$START_TS" ]] || die "START_TS required"
[[ -n "$END_TS" ]] || die "END_TS required"
[[ -n "$OUT_JOB_DIR" ]] || die "OUT_JOB_DIR required"

PIPELINE="$REPO_ROOT/moduleA_psi/scripts/run_large_pipeline.sh"
[[ -f "$PIPELINE" ]] || die "missing $PIPELINE"

OUTDIR="$REPO_ROOT/benchmark/out/$CASE_ID"
mkdir -p "$OUTDIR"
STDOUT_LOG="$OUTDIR/stdout.log"
STDERR_LOG="$OUTDIR/stderr.log"
METRICS_JSON="$OUTDIR/metrics.json"

set +e
/usr/bin/time -v \
  bash "$PIPELINE" \
    --criteo-tsv "$CRITEO_TSV" \
    --start-ts "$START_TS" \
    --end-ts "$END_TS" \
    --out "$OUT_JOB_DIR" \
    --value-mode "$VALUE_MODE" \
    ${BUCKET_FIELD:+--bucket-field "$BUCKET_FIELD"} \
    --num-shards "$NUM_SHARDS" \
    --max-jobs "$MAX_JOBS" \
    --base-port "$BASE_PORT" \
    --k "$K" \
    --n "$N" \
    --caller "$CALLER" \
  >"$STDOUT_LOG" 2>"$STDERR_LOG"
RC=$?
set -e

ELAPSED="$(grep -E '^\s*Elapsed \(wall clock\) time' "$STDERR_LOG" | awk -F': ' '{print $2}' | tail -n 1 || true)"
MAX_RSS_KB="$(grep -E '^\s*Maximum resident set size' "$STDERR_LOG" | awk -F': ' '{print $2}' | tail -n 1 || true)"
USER_TIME_S="$(grep -E '^\s*User time \(seconds\)' "$STDERR_LOG" | awk -F': ' '{print $2}' | tail -n 1 || true)"
SYS_TIME_S="$(grep -E '^\s*System time \(seconds\)' "$STDERR_LOG" | awk -F': ' '{print $2}' | tail -n 1 || true)"
EXIT_STATUS="$(grep -E '^\s*Exit status' "$STDERR_LOG" | awk -F': ' '{print $2}' | tail -n 1 || true)"

JOB_DIR_ABS="$REPO_ROOT/$OUT_JOB_DIR"

python3 "$REPO_ROOT/benchmark/scripts/collect_metrics.py" \
  --case-id "$CASE_ID" \
  --job-dir "$JOB_DIR_ABS" \
  --elapsed "$ELAPSED" \
  --max-rss-kb "${MAX_RSS_KB:-0}" \
  --user-time-s "${USER_TIME_S:-0}" \
  --sys-time-s "${SYS_TIME_S:-0}" \
  --exit-status "${EXIT_STATUS:-$RC}" \
  --num-shards "$NUM_SHARDS" \
  --max-jobs "$MAX_JOBS" \
  --bucket-field "${BUCKET_FIELD:-}" \
  --value-mode "$VALUE_MODE" \
  --k "$K" \
  --n "$N" \
  --out "$METRICS_JSON"

echo "[ok] case=$CASE_ID rc=$RC metrics=$METRICS_JSON"
exit "$RC"
