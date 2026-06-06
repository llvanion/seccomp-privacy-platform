#!/usr/bin/env bash
set -euo pipefail

die() { echo "[ERROR] $*" >&2; exit 1; }
log() { echo "[INFO] $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="$(cd "$MODULE_ROOT/.." && pwd)"
cd "$REPO_ROOT"

JOB_ID="${JOB_ID:-bucketed-scale-1k}"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/tmp/pjc_bucketed_scale_$JOB_ID}"
RECORDS="${RECORDS:-1000}"
BUCKETS="${BUCKETS:-8}"
BUCKET_FIELD="${BUCKET_FIELD:-campaign_id}"
BUCKET_PREFIX="${BUCKET_PREFIX:-campaign}"
ALLOWED_BUCKET_FIELDS="${ALLOWED_BUCKET_FIELDS:-$BUCKET_FIELD}"
ALLOWED_BUCKETS="${ALLOWED_BUCKETS:-}"
MAX_BUCKETS="${MAX_BUCKETS:-$BUCKETS}"
DEFAULT_BUCKET_LABEL_PATTERN='^[A-Za-z0-9_.:-]{1,64}$'
BUCKET_LABEL_PATTERN="${BUCKET_LABEL_PATTERN:-$DEFAULT_BUCKET_LABEL_PATTERN}"
PRODUCTION_MODE="${PRODUCTION_MODE:-0}"
OVERLAP_RATE="${OVERLAP_RATE:-0.42}"
EXTRA_CLIENT_RECORDS="${EXTRA_CLIENT_RECORDS:-150}"
VALUE_MIN="${VALUE_MIN:-100}"
VALUE_MAX="${VALUE_MAX:-10000}"
SEED="${SEED:-20260517}"
K_THRESHOLD="${K_THRESHOLD:-20}"
RATE_N="${RATE_N:-5}"
CALLER="${CALLER:-bucketed_scale_demo}"
DP_EPSILON="${DP_EPSILON:-1.0}"
DP_SENSITIVITY="${DP_SENSITIVITY:-10000}"
ROUND_SUM_TO="${ROUND_SUM_TO:-100}"
BASE_PORT="${BASE_PORT:-10621}"
PARALLEL="${PARALLEL:-0}"
MAX_JOBS="${MAX_JOBS:-4}"
PJC_BIN_DIR="${PJC_BIN_DIR:-}"
PJC_GRPC_STREAM_CHUNK_ELEMENTS="${PJC_GRPC_STREAM_CHUNK_ELEMENTS:-0}"
HMAC_SECRET_ENV="${HMAC_SECRET_ENV:-PJC_BUCKET_HMAC_SECRET}"

export PJC_GRPC_STREAM_CHUNK_ELEMENTS

log "generating synthetic business-bucketed PJC data"
GEN_CMD=(python3 "$SCRIPT_DIR/generate_bucketed_pjc_dataset.py" \
  --out "$OUT_DIR" \
  --job-id "$JOB_ID" \
  --records "$RECORDS" \
  --buckets "$BUCKETS" \
  --bucket-field "$BUCKET_FIELD" \
  --bucket-prefix "$BUCKET_PREFIX" \
  --overlap-rate "$OVERLAP_RATE" \
  --extra-client-records "$EXTRA_CLIENT_RECORDS" \
  --min-value "$VALUE_MIN" \
  --max-value "$VALUE_MAX" \
  --max-buckets "$MAX_BUCKETS" \
  --bucket-label-pattern "$BUCKET_LABEL_PATTERN" \
  --seed "$SEED")
if [[ "$PRODUCTION_MODE" == "1" ]]; then
  GEN_CMD+=(--production-mode)
fi
IFS=',' read -r -a ALLOWED_BUCKET_FIELD_ARR <<< "$ALLOWED_BUCKET_FIELDS"
for field in "${ALLOWED_BUCKET_FIELD_ARR[@]}"; do
  [[ -n "$field" ]] && GEN_CMD+=(--allowed-bucket-field "$field")
done
if [[ -n "$ALLOWED_BUCKETS" ]]; then
  IFS=',' read -r -a ALLOWED_BUCKET_ARR <<< "$ALLOWED_BUCKETS"
  for bucket in "${ALLOWED_BUCKET_ARR[@]}"; do
    [[ -n "$bucket" ]] && GEN_CMD+=(--allowed-bucket "$bucket")
  done
else
  for ((idx=0; idx<BUCKETS; idx++)); do
    GEN_CMD+=(--allowed-bucket "$(printf '%s_%02d' "$BUCKET_PREFIX" "$idx")")
  done
fi
if [[ -n "${!HMAC_SECRET_ENV:-}" ]]; then
  GEN_CMD+=(--hmac-secret-env "$HMAC_SECRET_ENV")
else
  log "env $HMAC_SECRET_ENV not set; generating local secret file under OUT_DIR for this test"
fi
"${GEN_CMD[@]}"

log "running bucketed PJC locally"
JOB_DIR="$OUT_DIR" \
PJC_BIN_DIR="$PJC_BIN_DIR" \
RUN_PJC_SH="$SCRIPT_DIR/run_pjc.sh" \
MERGE_PY="$SCRIPT_DIR/merge_bucket_results.py" \
PJC_REQUIRE_BUCKET_POLICY="$PRODUCTION_MODE" \
BASE_PORT="$BASE_PORT" \
PARALLEL="$PARALLEL" \
MAX_JOBS="$MAX_JOBS" \
bash "$SCRIPT_DIR/run_pjc_bucketed.sh"

log "checking merged result against generated expectation"
python3 - "$OUT_DIR" <<'PY'
import json, sys
from pathlib import Path
job = Path(sys.argv[1])
expected = json.load(open(job / "expected_result.json"))
actual = json.load(open(job / "attribution_result.json"))
if int(actual["intersection_size"]) != int(expected["intersection_size"]) or int(actual["intersection_sum"]) != int(expected["intersection_sum"]):
    raise SystemExit(f"[ERROR] expected {expected}, got {actual}")
print(f"[ok] merged result matches expected: size={actual['intersection_size']} sum={actual['intersection_sum']}")
PY

log "writing split Party A / Party B job directories for public mTLS tests"
python3 "$SCRIPT_DIR/split_bucketed_pjc_job_for_parties.py" --job-dir "$OUT_DIR"

log "running total-result policy release with DP"
python3 "$SCRIPT_DIR/policy_release.py" \
  --job-dir "$OUT_DIR" \
  --caller "$CALLER" \
  --k "$K_THRESHOLD" \
  --n "$RATE_N" \
  --deny-duplicate-query \
  --audit-log "$OUT_DIR/audit_log.jsonl" \
  --dp-epsilon "$DP_EPSILON" \
  --dp-sensitivity "$DP_SENSITIVITY" \
  --require-dp \
  --public-report-redact-operator-fields \
  --operator-report-path "$OUT_DIR/operator_report.json" \
  --bucket-intersection-size

log "running per-bucket k-threshold + DP protection"
python3 "$SCRIPT_DIR/policy_postprocess_buckets.py" \
  --job-dir "$OUT_DIR" \
  --k "$K_THRESHOLD" \
  --dp-epsilon "$DP_EPSILON" \
  --dp-sensitivity "$DP_SENSITIVITY" \
  --require-dp \
  --public-report-redact-operator-fields \
  --round-sum-to "$ROUND_SUM_TO"

log "OK. Important outputs:"
log "  $OUT_DIR/job_meta.json"
log "  $OUT_DIR/expected_result.json"
log "  $OUT_DIR/attribution_result.json"
log "  $OUT_DIR/public_report.json"
log "  $OUT_DIR/bucket_public_report.json"
log "  $OUT_DIR/operator_bucket_report.json"
log "  $OUT_DIR/audit_log.jsonl"
log "  $OUT_DIR/party_a_job"
log "  $OUT_DIR/party_b_job"
