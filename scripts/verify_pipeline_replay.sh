#!/usr/bin/env bash
# Replay the file-mode pipeline against the checked-in example inputs and
# assert intersection_size=2 and intersection_sum=425.
#
# Usage:
#   bash scripts/verify_pipeline_replay.sh [--keep-out-dir]
#
# Options:
#   --keep-out-dir  Do not delete the output directory after a successful run.
#
# Exit codes:
#   0  Replay passed — intersection_size and intersection_sum matched.
#   1  Replay failed — mismatch or pipeline error.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

KEEP_OUT_DIR=0
for arg in "$@"; do
  case "$arg" in
    --keep-out-dir) KEEP_OUT_DIR=1 ;;
    *) echo "[ERROR] unknown argument: $arg" >&2; exit 1 ;;
  esac
done

OUT_BASE="$(mktemp -d /tmp/seccomp_replay.XXXXXX)"
cleanup() {
  if [[ "$KEEP_OUT_DIR" -eq 0 ]]; then
    rm -rf "$OUT_BASE"
  else
    echo "[info] output preserved at: $OUT_BASE"
  fi
}
trap cleanup EXIT

EXPECTED_SIZE=2
EXPECTED_SUM=425

echo "[replay] running file-mode pipeline..."
bash "$SCRIPT_DIR/run_sse_bridge_pipeline.sh" \
  --server-source "$REPO_ROOT/sse/examples/bridge_server_records.jsonl" \
  --client-source "$REPO_ROOT/sse/examples/bridge_client_records.jsonl" \
  --server-join-key-field email \
  --client-join-key-field email \
  --client-value-field amount \
  --server-normalizer email \
  --client-normalizer email \
  --client-value-mode raw-int \
  --server-filter campaign=demo \
  --client-filter campaign=demo \
  --token-scope replay-verify-scope \
  --token-secret local-dev-secret \
  --job-id replay_verify_job \
  --out-base "$OUT_BASE" \
  --caller auto_demo \
  --sse-export-policy-config "$REPO_ROOT/sse/config/export_policy.example.json" \
  --k 1 \
  --n 5 \
  > "$OUT_BASE/pipeline.log" 2>&1 || {
    echo "[FAIL] pipeline exited non-zero" >&2
    tail -20 "$OUT_BASE/pipeline.log" >&2
    exit 1
  }

REPORT="$OUT_BASE/a_psi_run/public_report.json"
if [[ ! -f "$REPORT" ]]; then
  echo "[FAIL] public_report.json not found at $REPORT" >&2
  exit 1
fi

ACTUAL_SIZE="$(python3 -c "import json,sys; r=json.load(open('$REPORT')); print(r.get('details',{}).get('intersection_size','MISSING'))")"
# intersection_sum_raw carries the raw integer regardless of value_mode display format
ACTUAL_SUM="$(python3 -c "import json,sys; r=json.load(open('$REPORT')); d=r.get('details',{}); print(d.get('intersection_sum_raw', d.get('intersection_sum','MISSING')))")"

PASS=1
if [[ "$ACTUAL_SIZE" != "$EXPECTED_SIZE" ]]; then
  echo "[FAIL] intersection_size mismatch: expected=$EXPECTED_SIZE actual=$ACTUAL_SIZE" >&2
  PASS=0
fi
if [[ "$ACTUAL_SUM" != "$EXPECTED_SUM" ]]; then
  echo "[FAIL] intersection_sum mismatch: expected=$EXPECTED_SUM actual=$ACTUAL_SUM" >&2
  PASS=0
fi

if [[ "$PASS" -eq 0 ]]; then
  exit 1
fi

echo "[ok] pipeline replay passed: intersection_size=$ACTUAL_SIZE intersection_sum=$ACTUAL_SUM"
