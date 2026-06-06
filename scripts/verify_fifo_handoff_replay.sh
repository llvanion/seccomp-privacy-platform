#!/usr/bin/env bash
# Replay the pipeline in FIFO handoff mode against checked-in example inputs
# and assert both:
#   1. intersection_size=2 and intersection_sum=425
#   2. SSE export audit records output_file_type=fifo for both roles
#   3. No sse_exports/server.csv or client.csv on disk after bridge completes
#   4. mainline_contract_check.json records status=removed for both roles
#
# Usage:
#   bash scripts/verify_fifo_handoff_replay.sh [--keep-out-dir]
#
# Options:
#   --keep-out-dir  Do not delete the output directory after a successful run.
#
# Exit codes:
#   0  Replay passed — all assertions matched.
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

OUT_BASE="$(mktemp -d /tmp/seccomp_fifo_replay.XXXXXX)"
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
if [[ -n "$ORIGINAL_HOME" ]]; then
  mkdir -p "$REPLAY_HOME/.cache"
  for cache_name in bazel bazelisk; do
    if [[ -e "$ORIGINAL_HOME/.cache/$cache_name" && ! -e "$REPLAY_HOME/.cache/$cache_name" ]]; then
      ln -s "$ORIGINAL_HOME/.cache/$cache_name" "$REPLAY_HOME/.cache/$cache_name"
    fi
  done
fi
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

echo "[replay] running fifo-mode pipeline..."
HOME="$REPLAY_HOME" \
RUSTUP_HOME="$RUSTUP_HOME_REPLAY" \
CARGO_HOME="$CARGO_HOME_REPLAY" \
PJC_ALLOW_LEGACY_UNARY="${PJC_ALLOW_LEGACY_UNARY:-1}" \
bash "$SCRIPT_DIR/run_sse_bridge_pipeline.sh" \
  --server-source "$REPO_ROOT/sse/examples/bridge_server_records.jsonl" \
  --client-source "$REPO_ROOT/sse/examples/bridge_client_records.jsonl" \
  --server-join-key-field email \
  --client-join-key-field email \
  --client-value-field amount \
  --server-normalizer email \
  --client-normalizer email \
  --client-value-mode raw-int \
  --client-value-max 1000000 \
  --client-allowed-value-field amount \
  --client-value-unit minor_currency_unit \
  --client-value-currency USD \
  --server-filter campaign=demo \
  --client-filter campaign=demo \
  --token-scope fifo-replay-scope \
  --token-secret local-dev-secret \
  --job-id fifo_replay_job \
  --out-base "$OUT_BASE" \
  --caller auto_demo \
  --sse-export-policy-config "$REPO_ROOT/sse/config/export_policy.example.json" \
  --sse-export-handoff-mode fifo \
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

ACTUAL_SIZE="$(python3 -c "import json; r=json.load(open('$REPORT')); print(r.get('details',{}).get('intersection_size','MISSING'))")"
ACTUAL_SUM="$(python3 -c "import json; r=json.load(open('$REPORT')); d=r.get('details',{}); print(d.get('intersection_sum_raw', d.get('intersection_sum','MISSING')))")"

AUDIT_LOG="$OUT_BASE/sse_exports/export_audit.jsonl"
if [[ ! -f "$AUDIT_LOG" ]]; then
  echo "[FAIL] export_audit.jsonl not found at $AUDIT_LOG" >&2
  exit 1
fi
SERVER_HANDOFF_TYPE="$(python3 -c "
import json, sys
lines = [json.loads(l) for l in open('$AUDIT_LOG') if l.strip()]
rec = next((l for l in reversed(lines) if l.get('role') == 'server'), {})
print(rec.get('output_file_type', 'MISSING'))
")"
CLIENT_HANDOFF_TYPE="$(python3 -c "
import json, sys
lines = [json.loads(l) for l in open('$AUDIT_LOG') if l.strip()]
rec = next((l for l in reversed(lines) if l.get('role') == 'client'), {})
print(rec.get('output_file_type', 'MISSING'))
")"

MAINLINE="$OUT_BASE/mainline_contract_check.json"
if [[ ! -f "$MAINLINE" ]]; then
  echo "[FAIL] mainline_contract_check.json not found at $MAINLINE" >&2
  exit 1
fi
SERVER_HANDOFF_STATUS="$(python3 -c "import json; p=json.load(open('$MAINLINE')); print(((p.get('handoff_cleanup') or {}).get('server') or {}).get('status','MISSING'))")"
CLIENT_HANDOFF_STATUS="$(python3 -c "import json; p=json.load(open('$MAINLINE')); print(((p.get('handoff_cleanup') or {}).get('client') or {}).get('status','MISSING'))")"
HANDOFF_MODE="$(python3 -c "import json; p=json.load(open('$MAINLINE')); v=p.get('handoff_mode'); print('' if v is None else v)")"
EXPOSURE_RISK="$(python3 -c "import json; p=json.load(open('$MAINLINE')); print(((p.get('handoff_exposure_assessment') or {}).get('plaintext_exposure_risk','MISSING')))")"
SERVER_EXPOSURE_RISK="$(python3 -c "import json; p=json.load(open('$MAINLINE')); print(((p.get('handoff_exposure_assessment') or {}).get('server_exposure') or {}).get('exposure_risk','MISSING'))")"
CLIENT_EXPOSURE_RISK="$(python3 -c "import json; p=json.load(open('$MAINLINE')); print(((p.get('handoff_exposure_assessment') or {}).get('client_exposure') or {}).get('exposure_risk','MISSING'))")"

PASS=1

if [[ "$ACTUAL_SIZE" != "$EXPECTED_SIZE" ]]; then
  echo "[FAIL] intersection_size mismatch: expected=$EXPECTED_SIZE actual=$ACTUAL_SIZE" >&2
  PASS=0
fi
if [[ "$ACTUAL_SUM" != "$EXPECTED_SUM" ]]; then
  echo "[FAIL] intersection_sum mismatch: expected=$EXPECTED_SUM actual=$ACTUAL_SUM" >&2
  PASS=0
fi
if [[ "$SERVER_HANDOFF_TYPE" != "fifo" ]]; then
  echo "[FAIL] server output_file_type in SSE audit mismatch: expected=fifo actual=$SERVER_HANDOFF_TYPE" >&2
  PASS=0
fi
if [[ "$CLIENT_HANDOFF_TYPE" != "fifo" ]]; then
  echo "[FAIL] client output_file_type in SSE audit mismatch: expected=fifo actual=$CLIENT_HANDOFF_TYPE" >&2
  PASS=0
fi
if [[ -f "$OUT_BASE/sse_exports/server.csv" ]]; then
  echo "[FAIL] sse_exports/server.csv still exists after FIFO bridge run (plaintext should not have been written)" >&2
  PASS=0
fi
if [[ -f "$OUT_BASE/sse_exports/client.csv" ]]; then
  echo "[FAIL] sse_exports/client.csv still exists after FIFO bridge run (plaintext should not have been written)" >&2
  PASS=0
fi
if [[ "$SERVER_HANDOFF_STATUS" != "removed" ]]; then
  echo "[FAIL] mainline_contract_check server handoff status mismatch: expected=removed actual=$SERVER_HANDOFF_STATUS" >&2
  PASS=0
fi
if [[ "$CLIENT_HANDOFF_STATUS" != "removed" ]]; then
  echo "[FAIL] mainline_contract_check client handoff status mismatch: expected=removed actual=$CLIENT_HANDOFF_STATUS" >&2
  PASS=0
fi
if [[ "$HANDOFF_MODE" != "fifo" ]]; then
  echo "[FAIL] mainline_contract_check handoff_mode mismatch: expected=fifo actual=$HANDOFF_MODE" >&2
  PASS=0
fi
if [[ "$EXPOSURE_RISK" != "none" ]]; then
  echo "[FAIL] mainline_contract_check handoff_exposure_assessment.plaintext_exposure_risk mismatch: expected=none actual=$EXPOSURE_RISK" >&2
  PASS=0
fi
if [[ "$SERVER_EXPOSURE_RISK" != "none" ]]; then
  echo "[FAIL] mainline_contract_check server_exposure.exposure_risk mismatch: expected=none actual=$SERVER_EXPOSURE_RISK" >&2
  PASS=0
fi
if [[ "$CLIENT_EXPOSURE_RISK" != "none" ]]; then
  echo "[FAIL] mainline_contract_check client_exposure.exposure_risk mismatch: expected=none actual=$CLIENT_EXPOSURE_RISK" >&2
  PASS=0
fi

if [[ "$PASS" -eq 0 ]]; then
  exit 1
fi

echo "[ok] fifo handoff replay passed: intersection_size=$ACTUAL_SIZE intersection_sum=$ACTUAL_SUM server_handoff_type=$SERVER_HANDOFF_TYPE client_handoff_type=$CLIENT_HANDOFF_TYPE server_handoff=$SERVER_HANDOFF_STATUS client_handoff=$CLIENT_HANDOFF_STATUS handoff_mode=$HANDOFF_MODE exposure_risk=$EXPOSURE_RISK"
