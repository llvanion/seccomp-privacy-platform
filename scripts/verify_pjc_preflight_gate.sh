#!/usr/bin/env bash
# S4 PJC preflight gate verification.
#
# Cases:
#   case-1 POSITIVE — small input within all limits → decision=allow.
#   case-2 NEGATIVE — server_rows > max_input_rows → reason_code=input_rows_over_limit.
#   case-3 NEGATIVE — server_rows × bytes-per-row > max_input_bytes →
#                     reason_code=input_bytes_over_limit.
#   case-4 NEGATIVE — small chunk_size_elements + large input row count →
#                     reason_code=estimated_frame_count_over_limit.
#   case-5 NEGATIVE — caller without scope rule and default max_input_rows=0 →
#                     reason_code=missing_resource_scope.
#   case-6 SCHEMA   — every preflight report validates against pjc_preflight/v1.
#
# Usage:
#   bash scripts/verify_pjc_preflight_gate.sh [--keep-out-dir]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CHECK_PY="$SCRIPT_DIR/preflight_pjc_job.py"
VALIDATE_PY="$SCRIPT_DIR/validate_json_contract.py"
LIMITS_CONFIG="$REPO_ROOT/config/pjc_resource_limits.example.json"
SCHEMA="$REPO_ROOT/schemas/pjc_preflight.schema.json"

KEEP_OUT_DIR=0
for arg in "$@"; do
  case "$arg" in
    --keep-out-dir) KEEP_OUT_DIR=1 ;;
    *) echo "[ERROR] unknown argument: $arg" >&2; exit 1 ;;
  esac
done

OUT_ROOT="$(mktemp -d /tmp/seccomp_pjc_preflight.XXXXXX)"
cleanup() {
  if [[ "$KEEP_OUT_DIR" -eq 0 ]]; then
    rm -rf "$OUT_ROOT"
  else
    echo "[info] output preserved at: $OUT_ROOT"
  fi
}
trap cleanup EXIT

PASS=1

reason_field() {
  python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('reason_code','MISSING'))" "$1"
}
decision_field() {
  python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('decision','MISSING'))" "$1"
}

# ----- case-1 POSITIVE: small input within limits
REPORT1="$OUT_ROOT/r1.json"
echo "[case-1] small input within limits (expect allow)"
set +e
python3 "$CHECK_PY" \
  --resource-limits "$LIMITS_CONFIG" \
  --server-rows 1000 --client-rows 1000 \
  --caller auto_demo --tenant-id t1 --dataset-id d1 --purpose bridge_token \
  --job-id case1 \
  --transport-mode streaming_grpc --chunk-size-elements 4096 \
  --output "$REPORT1" --assert-allow > /dev/null 2> "$OUT_ROOT/r1.err"
RC1=$?
set -e
if [[ "$RC1" -ne 0 ]]; then
  echo "[FAIL] case-1 expected exit 0; got $RC1"; cat "$OUT_ROOT/r1.err" >&2; PASS=0
fi
if [[ "$(decision_field "$REPORT1")" != "allow" ]]; then
  echo "[FAIL] case-1 expected decision=allow, got $(decision_field "$REPORT1")"; PASS=0
fi

# ----- case-2 NEGATIVE: rows over limit (limit is 2_000_000)
REPORT2="$OUT_ROOT/r2.json"
echo "[case-2] server_rows over limit (expect deny input_rows_over_limit)"
set +e
python3 "$CHECK_PY" \
  --resource-limits "$LIMITS_CONFIG" \
  --server-rows 3000000 --client-rows 1000 \
  --caller auto_demo --tenant-id t1 --dataset-id d1 --purpose bridge_token \
  --job-id case2 \
  --transport-mode streaming_grpc --chunk-size-elements 4096 \
  --output "$REPORT2" --assert-allow > /dev/null 2> "$OUT_ROOT/r2.err"
RC2=$?
set -e
if [[ "$RC2" -eq 0 ]]; then
  echo "[FAIL] case-2 expected non-zero exit"; PASS=0
fi
if [[ "$(reason_field "$REPORT2")" != "input_rows_over_limit" ]]; then
  echo "[FAIL] case-2 expected reason_code=input_rows_over_limit, got $(reason_field "$REPORT2")"; PASS=0
fi

# ----- case-3 NEGATIVE: bytes over limit
# limits.max_input_bytes = 536_870_912 (512 MiB); bytes_per_row=192.
# Need rows*192 > 536_870_912 but rows <= max_input_rows (2_000_000).
# 2_000_000*192 = 384_000_000 — well under 512 MiB. So we have to bump
# bytes_per_row override path: pass server-rows = 2_000_000 with custom CSV
# or invent a very wide CSV. Easier: write a small inline config that
# tightens max_input_bytes for this case.
NARROW_CONFIG="$OUT_ROOT/limits_narrow_bytes.json"
python3 - "$LIMITS_CONFIG" "$NARROW_CONFIG" <<'PY'
import json, sys
src, dst = sys.argv[1:]
cfg = json.load(open(src))
cfg["scopes"][0]["limits"]["max_input_bytes"] = 100_000   # 100 KB
json.dump(cfg, open(dst, "w"))
PY
REPORT3="$OUT_ROOT/r3.json"
echo "[case-3] bytes over limit (expect deny input_bytes_over_limit)"
set +e
python3 "$CHECK_PY" \
  --resource-limits "$NARROW_CONFIG" \
  --server-rows 2000 --client-rows 2000 \
  --caller auto_demo --tenant-id t1 --dataset-id d1 --purpose bridge_token \
  --job-id case3 \
  --transport-mode streaming_grpc --chunk-size-elements 4096 \
  --output "$REPORT3" --assert-allow > /dev/null 2> "$OUT_ROOT/r3.err"
RC3=$?
set -e
if [[ "$RC3" -eq 0 ]]; then
  echo "[FAIL] case-3 expected non-zero exit"; PASS=0
fi
if [[ "$(reason_field "$REPORT3")" != "input_bytes_over_limit" ]]; then
  echo "[FAIL] case-3 expected reason_code=input_bytes_over_limit, got $(reason_field "$REPORT3")"; PASS=0
fi

# ----- case-4 NEGATIVE: frame count over limit
# Limit is 4096 frames. With chunk_size 1, 5000 rows on each side ⇒ 10000 frames.
NARROW_FRAMES="$OUT_ROOT/limits_narrow_frames.json"
python3 - "$LIMITS_CONFIG" "$NARROW_FRAMES" <<'PY'
import json, sys
src, dst = sys.argv[1:]
cfg = json.load(open(src))
cfg["scopes"][0]["limits"]["max_frame_count"] = 100
json.dump(cfg, open(dst, "w"))
PY
REPORT4="$OUT_ROOT/r4.json"
echo "[case-4] frame_count over limit (expect deny estimated_frame_count_over_limit)"
set +e
python3 "$CHECK_PY" \
  --resource-limits "$NARROW_FRAMES" \
  --server-rows 5000 --client-rows 5000 \
  --caller auto_demo --tenant-id t1 --dataset-id d1 --purpose bridge_token \
  --job-id case4 \
  --transport-mode streaming_grpc --chunk-size-elements 1 \
  --output "$REPORT4" --assert-allow > /dev/null 2> "$OUT_ROOT/r4.err"
RC4=$?
set -e
if [[ "$RC4" -eq 0 ]]; then
  echo "[FAIL] case-4 expected non-zero exit"; PASS=0
fi
if [[ "$(reason_field "$REPORT4")" != "estimated_frame_count_over_limit" ]]; then
  echo "[FAIL] case-4 expected reason_code=estimated_frame_count_over_limit, got $(reason_field "$REPORT4")"; PASS=0
fi

# ----- case-5 NEGATIVE: caller without scope rule
REPORT5="$OUT_ROOT/r5.json"
echo "[case-5] unknown caller (expect deny missing_resource_scope)"
set +e
python3 "$CHECK_PY" \
  --resource-limits "$LIMITS_CONFIG" \
  --server-rows 100 --client-rows 100 \
  --caller unknown_caller \
  --job-id case5 \
  --transport-mode streaming_grpc --chunk-size-elements 4096 \
  --output "$REPORT5" --assert-allow > /dev/null 2> "$OUT_ROOT/r5.err"
RC5=$?
set -e
if [[ "$RC5" -eq 0 ]]; then
  echo "[FAIL] case-5 expected non-zero exit"; PASS=0
fi
if [[ "$(reason_field "$REPORT5")" != "missing_resource_scope" ]]; then
  echo "[FAIL] case-5 expected reason_code=missing_resource_scope, got $(reason_field "$REPORT5")"; PASS=0
fi

# ----- case-6 SCHEMA validation
echo "[case-6] schema validation across all reports"
for f in "$REPORT1" "$REPORT2" "$REPORT3" "$REPORT4" "$REPORT5"; do
  if ! python3 "$VALIDATE_PY" --schema "$SCHEMA" --json "$f" > /dev/null; then
    echo "[FAIL] case-6 $f failed schema validation"; PASS=0
  fi
done

if [[ "$PASS" -ne 1 ]]; then
  exit 1
fi

echo "[ok] PJC preflight gate verified: case-1 (allow) + case-2 (rows) + case-3 (bytes) + case-4 (frames) + case-5 (no scope) + case-6 (schemas)"
