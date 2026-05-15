#!/usr/bin/env bash
# S3 privacy budget release-gate verification for the current policy_release.py
# implementation.
#
# Cases:
#   case-1 POSITIVE — first legal release is allowed and consumes budget.
#   case-2 NEGATIVE — exact duplicate query is denied before release.
#   case-3 NEGATIVE — distinct query after budget limit is exhausted is denied.
#   case-4 SCHEMA   — public reports, policy audit, ledger, and check report
#                     validate against their v1/v2 schemas.
#
# Usage:
#   bash scripts/verify_privacy_budget_ledger.sh [--keep-out-dir]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
POLICY_RELEASE="$REPO_ROOT/a-psi/moduleA_psi/scripts/policy_release.py"
CHECK_PY="$SCRIPT_DIR/check_privacy_budget.py"
VALIDATE_PY="$SCRIPT_DIR/validate_json_contract.py"

KEEP_OUT_DIR=0
for arg in "$@"; do
  case "$arg" in
    --keep-out-dir) KEEP_OUT_DIR=1 ;;
    *) echo "[ERROR] unknown argument: $arg" >&2; exit 1 ;;
  esac
done

OUT_ROOT="$(mktemp -d /tmp/seccomp_privacy_budget.XXXXXX)"
cleanup() {
  if [[ "$KEEP_OUT_DIR" -eq 0 ]]; then
    rm -rf "$OUT_ROOT"
  else
    echo "[info] output preserved at: $OUT_ROOT"
  fi
}
trap cleanup EXIT

PASS=1
LEDGER="$OUT_ROOT/privacy_budget_ledger.jsonl"
AUDIT="$OUT_ROOT/privacy_budget_policy_audit.jsonl"

printf '%s\n' \
  '{"intersection_size":2,"intersection_sum":10}' \
  > "$OUT_ROOT/result.json"
printf '%s\n' \
  '{"job_id":"privacy-budget-job-1","window_start":"2026-01-01T00:00:00Z","window_end":"2026-01-31T00:00:00Z","bucket":"campaign-a"}' \
  > "$OUT_ROOT/meta_1.json"
printf '%s\n' \
  '{"job_id":"privacy-budget-job-2","window_start":"2026-01-01T00:00:00Z","window_end":"2026-01-31T00:00:00Z","bucket":"campaign-a"}' \
  > "$OUT_ROOT/meta_2.json"
printf '%s\n' \
  '{"job_id":"privacy-budget-job-3","window_start":"2026-02-01T00:00:00Z","window_end":"2026-02-28T00:00:00Z","bucket":"campaign-a"}' \
  > "$OUT_ROOT/meta_3.json"

release_with_budget() {
  local meta="$1"
  local out="$2"
  python3 "$POLICY_RELEASE" \
    --input "$OUT_ROOT/result.json" \
    --job-meta "$meta" \
    --out "$out" \
    --audit-log "$AUDIT" \
    --caller privacy_budget_demo \
    --threshold-k 1 \
    --max-queries 10 \
    --privacy-budget-ledger "$LEDGER" \
    --privacy-budget-limit 1
}

json_field() {
  python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], 'MISSING'))" "$1" "$2"
}

echo "[case-1] first privacy-budget release (expect released=true)"
release_with_budget "$OUT_ROOT/meta_1.json" "$OUT_ROOT/report_1.json" > /dev/null
if [[ "$(json_field "$OUT_ROOT/report_1.json" released)" != "True" ]]; then
  echo "[FAIL] case-1 expected released=True" >&2
  PASS=0
fi

echo "[case-2] exact duplicate privacy query (expect deny privacy_budget_duplicate_query)"
release_with_budget "$OUT_ROOT/meta_2.json" "$OUT_ROOT/report_2.json" > /dev/null
if [[ "$(json_field "$OUT_ROOT/report_2.json" released)" != "False" ]]; then
  echo "[FAIL] case-2 expected released=False" >&2
  PASS=0
fi
if [[ "$(json_field "$OUT_ROOT/report_2.json" reason_code)" != "privacy_budget_duplicate_query" ]]; then
  echo "[FAIL] case-2 expected reason_code=privacy_budget_duplicate_query" >&2
  PASS=0
fi

echo "[case-3] distinct query after budget limit is exhausted (expect deny privacy_budget_exhausted)"
release_with_budget "$OUT_ROOT/meta_3.json" "$OUT_ROOT/report_3.json" > /dev/null
if [[ "$(json_field "$OUT_ROOT/report_3.json" released)" != "False" ]]; then
  echo "[FAIL] case-3 expected released=False" >&2
  PASS=0
fi
if [[ "$(json_field "$OUT_ROOT/report_3.json" reason_code)" != "privacy_budget_exhausted" ]]; then
  echo "[FAIL] case-3 expected reason_code=privacy_budget_exhausted" >&2
  PASS=0
fi

echo "[case-4] schema validation and check-report assertions"
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/public_report.schema.json" --json "$OUT_ROOT/report_1.json" > /dev/null || PASS=0
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/public_report.schema.json" --json "$OUT_ROOT/report_2.json" > /dev/null || PASS=0
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/public_report.schema.json" --json "$OUT_ROOT/report_3.json" > /dev/null || PASS=0
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/policy_audit.schema.json" --jsonl "$AUDIT" > /dev/null || PASS=0
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/privacy_budget_ledger.schema.json" --jsonl "$LEDGER" > /dev/null || PASS=0

python3 "$CHECK_PY" \
  --ledger "$LEDGER" \
  --expect-consumed-min 1 \
  --expect-deny-reason privacy_budget_duplicate_query \
  --expect-deny-reason privacy_budget_exhausted \
  --output "$OUT_ROOT/privacy_budget_check_report.json" \
  > /dev/null || PASS=0
python3 "$VALIDATE_PY" \
  --schema "$REPO_ROOT/schemas/privacy_budget_check_report.schema.json" \
  --json "$OUT_ROOT/privacy_budget_check_report.json" \
  > /dev/null || PASS=0

python3 - "$LEDGER" "$OUT_ROOT/privacy_budget_check_report.json" <<'PY' || PASS=0
import json, sys
ledger_path, report_path = sys.argv[1:]
rows = [json.loads(line) for line in open(ledger_path, encoding="utf-8") if line.strip()]
assert len(rows) == 3, rows
assert rows[0]["decision"] == "allow" and rows[0]["budget"]["consumed"] is True, rows[0]
assert rows[1]["reason_code"] == "privacy_budget_duplicate_query", rows[1]
assert rows[1]["abuse_signal"] == "exact_duplicate", rows[1]
assert rows[1]["budget"]["consumed"] is False, rows[1]
assert rows[2]["reason_code"] == "privacy_budget_exhausted", rows[2]
assert rows[2]["abuse_signal"] == "budget_exhausted", rows[2]
assert rows[2]["budget"]["consumed"] is False, rows[2]
report = json.load(open(report_path, encoding="utf-8"))
summary = report["summary"]
assert report["status"] == "ok", report
assert summary["decision_counts"]["allow"] == 1, summary
assert summary["decision_counts"]["deny"] == 2, summary
PY

if [[ "$PASS" -ne 1 ]]; then
  exit 1
fi

echo "[ok] privacy budget release gate verified: case-1 allow + case-2 duplicate deny + case-3 budget exhausted + case-4 schemas/check-report"
