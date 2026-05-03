#!/usr/bin/env bash
# Replay the default pipeline command surface against the checked-in example
# inputs and assert both:
#   1. intersection_size=2 and intersection_sum=425
#   2. the no-flag default still resolves to managed file-mode handoff cleanup
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
REPLAY_HOME="$OUT_BASE/home"
ORIGINAL_HOME="${HOME:-}"
if [[ -n "$ORIGINAL_HOME" ]]; then
  RUSTUP_HOME_REPLAY="${RUSTUP_HOME:-$ORIGINAL_HOME/.rustup}"
  CARGO_HOME_REPLAY="${CARGO_HOME:-$ORIGINAL_HOME/.cargo}"
else
  RUSTUP_HOME_REPLAY="${RUSTUP_HOME:-}"
  CARGO_HOME_REPLAY="${CARGO_HOME:-}"
fi
mkdir -p "$REPLAY_HOME"
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
HOME="$REPLAY_HOME" \
RUSTUP_HOME="$RUSTUP_HOME_REPLAY" \
CARGO_HOME="$CARGO_HOME_REPLAY" \
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
MAINLINE="$OUT_BASE/mainline_contract_check.json"
if [[ ! -f "$MAINLINE" ]]; then
  echo "[FAIL] mainline_contract_check.json not found at $MAINLINE" >&2
  exit 1
fi
SERVER_HANDOFF_STATUS="$(python3 -c "import json; p=json.load(open('$MAINLINE')); print(((p.get('handoff_cleanup') or {}).get('server') or {}).get('status','MISSING'))")"
CLIENT_HANDOFF_STATUS="$(python3 -c "import json; p=json.load(open('$MAINLINE')); print(((p.get('handoff_cleanup') or {}).get('client') or {}).get('status','MISSING'))")"
SERVER_RETENTION_REASON="$(python3 -c "import json; p=json.load(open('$MAINLINE')); v=(((p.get('handoff_cleanup') or {}).get('server') or {}).get('retention_reason')); print('' if v is None else v)")"
CLIENT_RETENTION_REASON="$(python3 -c "import json; p=json.load(open('$MAINLINE')); v=(((p.get('handoff_cleanup') or {}).get('client') or {}).get('retention_reason')); print('' if v is None else v)")"
HANDOFF_MODE="$(python3 -c "import json; p=json.load(open('$MAINLINE')); v=p.get('handoff_mode'); print('' if v is None else v)")"
EXPOSURE_RISK="$(python3 -c "import json; p=json.load(open('$MAINLINE')); print(((p.get('handoff_exposure_assessment') or {}).get('plaintext_exposure_risk','MISSING')))")"

PASS=1
if [[ "$ACTUAL_SIZE" != "$EXPECTED_SIZE" ]]; then
  echo "[FAIL] intersection_size mismatch: expected=$EXPECTED_SIZE actual=$ACTUAL_SIZE" >&2
  PASS=0
fi
if [[ "$ACTUAL_SUM" != "$EXPECTED_SUM" ]]; then
  echo "[FAIL] intersection_sum mismatch: expected=$EXPECTED_SUM actual=$ACTUAL_SUM" >&2
  PASS=0
fi
if [[ "$SERVER_HANDOFF_STATUS" != "cleaned" ]]; then
  echo "[FAIL] default handoff server status mismatch: expected=cleaned actual=$SERVER_HANDOFF_STATUS" >&2
  PASS=0
fi
if [[ "$CLIENT_HANDOFF_STATUS" != "cleaned" ]]; then
  echo "[FAIL] default handoff client status mismatch: expected=cleaned actual=$CLIENT_HANDOFF_STATUS" >&2
  PASS=0
fi
if [[ -n "$SERVER_RETENTION_REASON" || -n "$CLIENT_RETENTION_REASON" ]]; then
  echo "[FAIL] default file-mode replay unexpectedly recorded a retained handoff reason" >&2
  PASS=0
fi
if [[ "$HANDOFF_MODE" != "file" ]]; then
  echo "[FAIL] mainline_contract_check handoff_mode mismatch: expected=file actual=$HANDOFF_MODE" >&2
  PASS=0
fi
if [[ "$EXPOSURE_RISK" != "low" ]]; then
  echo "[FAIL] mainline_contract_check handoff_exposure_assessment.plaintext_exposure_risk mismatch: expected=low actual=$EXPOSURE_RISK" >&2
  PASS=0
fi

if [[ "$PASS" -eq 0 ]]; then
  exit 1
fi

echo "[ok] pipeline replay passed: intersection_size=$ACTUAL_SIZE intersection_sum=$ACTUAL_SUM server_handoff=$SERVER_HANDOFF_STATUS client_handoff=$CLIENT_HANDOFF_STATUS handoff_mode=$HANDOFF_MODE exposure_risk=$EXPOSURE_RISK"
