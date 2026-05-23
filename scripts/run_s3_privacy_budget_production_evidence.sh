#!/usr/bin/env bash
# Production-style S3 privacy-budget closed-loop evidence.
#
# This is still local technical evidence, but unlike the repo-side smoke it
# exercises fail-closed production mode with an explicit per-scope budget
# configuration: caller + tenant + dataset + purpose.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

OUT_DIR="${S3_PRIVACY_BUDGET_PROD_OUT_DIR:-$REPO_ROOT/tmp/s3_privacy_budget_production_evidence}"
POLICY_RELEASE="$REPO_ROOT/a-psi/moduleA_psi/scripts/policy_release.py"
CHECK_PY="$REPO_ROOT/scripts/check_privacy_budget.py"
VALIDATE_PY="$REPO_ROOT/scripts/validate_json_contract.py"

mkdir -p "$OUT_DIR"

LEDGER="$OUT_DIR/privacy_budget_ledger.jsonl"
AUDIT="$OUT_DIR/privacy_budget_policy_audit.jsonl"
CONFIG="$OUT_DIR/privacy_budget.production.json"
CHECK_REPORT="$OUT_DIR/privacy_budget_check_report.json"
SUMMARY_JSON="$OUT_DIR/verification_summary.json"
SUMMARY_MD="$OUT_DIR/EVIDENCE_SUMMARY.md"
HASHES="$OUT_DIR/final_evidence_hashes.sha256"

: > "$LEDGER"
: > "$AUDIT"

cat > "$CONFIG" <<'JSON'
{
  "schema": "privacy_budget_config/v1",
  "default": {
    "max_queries": 0,
    "near_duplicate_window_seconds": 0,
    "near_duplicate_window_round_seconds": 3600,
    "near_duplicate_threshold_round_step": 5
  },
  "scopes": [
    {
      "match": {
        "caller": "s3_privacy_budget_production_evidence",
        "tenant_id": "tenant-prod-a",
        "dataset_id": "orders-2026",
        "purpose": "attribution-release"
      },
      "max_queries": 1,
      "near_duplicate_window_seconds": 86400,
      "near_duplicate_window_round_seconds": 3600,
      "near_duplicate_threshold_round_step": 5
    }
  ]
}
JSON

printf '%s\n' \
  '{"intersection_size":2,"intersection_sum":425,"server_addr":"privacy-budget-production-local","tls":true}' \
  > "$OUT_DIR/result.json"

write_meta() {
  local path="$1"
  local job_id="$2"
  local start="$3"
  local end="$4"
  local tenant="$5"
  local dataset="$6"
  local purpose="$7"
  printf '{"job_id":"%s","window_start":"%s","window_end":"%s","bucket":"campaign-a","tenant_id":"%s","dataset_id":"%s","purpose":"%s"}\n' \
    "$job_id" "$start" "$end" "$tenant" "$dataset" "$purpose" > "$path"
}

write_meta "$OUT_DIR/meta_1_allow.json" \
  "s3-prod-budget-job-1" "2026-01-01T00:00:00Z" "2026-01-31T00:00:00Z" \
  "tenant-prod-a" "orders-2026" "attribution-release"
write_meta "$OUT_DIR/meta_2_duplicate.json" \
  "s3-prod-budget-job-2" "2026-01-01T00:00:00Z" "2026-01-31T00:00:00Z" \
  "tenant-prod-a" "orders-2026" "attribution-release"
write_meta "$OUT_DIR/meta_3_overlap.json" \
  "s3-prod-budget-job-3" "2026-01-15T00:00:00Z" "2026-02-15T00:00:00Z" \
  "tenant-prod-a" "orders-2026" "attribution-release"
write_meta "$OUT_DIR/meta_4_exhausted.json" \
  "s3-prod-budget-job-4" "2026-03-01T00:00:00Z" "2026-03-31T00:00:00Z" \
  "tenant-prod-a" "orders-2026" "attribution-release"
write_meta "$OUT_DIR/meta_5_missing_scope.json" \
  "s3-prod-budget-job-5" "2026-04-01T00:00:00Z" "2026-04-30T00:00:00Z" \
  "tenant-prod-b" "orders-2026" "attribution-release"

release_required() {
  local meta="$1"
  local out="$2"
  python3 "$POLICY_RELEASE" \
    --input "$OUT_DIR/result.json" \
    --job-meta "$meta" \
    --out "$out" \
    --audit-log "$AUDIT" \
    --caller s3_privacy_budget_production_evidence \
    --threshold-k 1 \
    --max-queries 10 \
    --privacy-budget-required \
    --privacy-budget-config "$CONFIG" \
    --privacy-budget-ledger "$LEDGER"
}

set +e
python3 "$POLICY_RELEASE" \
  --input "$OUT_DIR/result.json" \
  --job-meta "$OUT_DIR/meta_1_allow.json" \
  --out "$OUT_DIR/report_0_missing_ledger.json" \
  --audit-log "$AUDIT" \
  --caller s3_privacy_budget_production_evidence \
  --threshold-k 1 \
  --max-queries 10 \
  --privacy-budget-required \
  --privacy-budget-config "$CONFIG" \
  > "$OUT_DIR/case_0_missing_ledger.log" 2>&1
missing_ledger_rc=$?
set -e
if [[ "$missing_ledger_rc" -eq 0 ]]; then
  echo "[FAIL] --privacy-budget-required without --privacy-budget-ledger unexpectedly succeeded" >&2
  exit 1
fi

release_required "$OUT_DIR/meta_1_allow.json" "$OUT_DIR/report_1_allow.json" > "$OUT_DIR/case_1_allow.log" 2>&1
release_required "$OUT_DIR/meta_2_duplicate.json" "$OUT_DIR/report_2_duplicate.json" > "$OUT_DIR/case_2_duplicate.log" 2>&1
release_required "$OUT_DIR/meta_3_overlap.json" "$OUT_DIR/report_3_overlap.json" > "$OUT_DIR/case_3_overlap.log" 2>&1
release_required "$OUT_DIR/meta_4_exhausted.json" "$OUT_DIR/report_4_exhausted.json" > "$OUT_DIR/case_4_exhausted.log" 2>&1
release_required "$OUT_DIR/meta_5_missing_scope.json" "$OUT_DIR/report_5_missing_scope.json" > "$OUT_DIR/case_5_missing_scope.log" 2>&1

python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/privacy_budget_config.schema.json" --json "$CONFIG" > /dev/null
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/public_report.schema.json" --json "$OUT_DIR/report_1_allow.json" > /dev/null
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/public_report.schema.json" --json "$OUT_DIR/report_2_duplicate.json" > /dev/null
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/public_report.schema.json" --json "$OUT_DIR/report_3_overlap.json" > /dev/null
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/public_report.schema.json" --json "$OUT_DIR/report_4_exhausted.json" > /dev/null
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/public_report.schema.json" --json "$OUT_DIR/report_5_missing_scope.json" > /dev/null
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/policy_audit.schema.json" --jsonl "$AUDIT" > /dev/null
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/privacy_budget_ledger.schema.json" --jsonl "$LEDGER" > /dev/null

python3 "$CHECK_PY" \
  --ledger "$LEDGER" \
  --expect-consumed-min 1 \
  --expect-deny-reason privacy_budget_duplicate_query \
  --expect-deny-reason privacy_budget_near_duplicate \
  --expect-deny-reason privacy_budget_exhausted \
  --expect-deny-reason privacy_budget_missing_scope \
  --output "$CHECK_REPORT" \
  > /dev/null

python3 "$VALIDATE_PY" \
  --schema "$REPO_ROOT/schemas/privacy_budget_check_report.schema.json" \
  --json "$CHECK_REPORT" \
  > /dev/null

python3 - "$OUT_DIR" "$LEDGER" "$CHECK_REPORT" "$SUMMARY_JSON" "$missing_ledger_rc" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

out_dir = Path(sys.argv[1])
ledger_path = Path(sys.argv[2])
check_report_path = Path(sys.argv[3])
summary_path = Path(sys.argv[4])
missing_ledger_rc = int(sys.argv[5])

reports = {
    "allow": json.loads((out_dir / "report_1_allow.json").read_text(encoding="utf-8")),
    "duplicate": json.loads((out_dir / "report_2_duplicate.json").read_text(encoding="utf-8")),
    "overlap": json.loads((out_dir / "report_3_overlap.json").read_text(encoding="utf-8")),
    "exhausted": json.loads((out_dir / "report_4_exhausted.json").read_text(encoding="utf-8")),
    "missing_scope": json.loads((out_dir / "report_5_missing_scope.json").read_text(encoding="utf-8")),
}
rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
check_report = json.loads(check_report_path.read_text(encoding="utf-8"))

assert missing_ledger_rc != 0, missing_ledger_rc
assert reports["allow"]["released"] is True, reports["allow"]
assert reports["duplicate"]["released"] is False, reports["duplicate"]
assert reports["duplicate"]["reason_code"] == "privacy_budget_duplicate_query", reports["duplicate"]
assert reports["overlap"]["released"] is False, reports["overlap"]
assert reports["overlap"]["reason_code"] == "privacy_budget_near_duplicate", reports["overlap"]
assert reports["exhausted"]["released"] is False, reports["exhausted"]
assert reports["exhausted"]["reason_code"] == "privacy_budget_exhausted", reports["exhausted"]
assert reports["missing_scope"]["released"] is False, reports["missing_scope"]
assert reports["missing_scope"]["reason_code"] == "privacy_budget_missing_scope", reports["missing_scope"]
assert len(rows) == 5, rows
assert rows[0]["tenant_id"] == "tenant-prod-a" and rows[0]["budget"]["consumed"] is True, rows[0]
assert rows[1]["abuse_signal"] == "exact_duplicate" and rows[1]["budget"]["consumed"] is False, rows[1]
assert rows[2]["abuse_signal"] == "near_duplicate_or_differencing" and rows[2]["budget"]["consumed"] is False, rows[2]
assert rows[3]["abuse_signal"] == "budget_exhausted" and rows[3]["budget"]["consumed"] is False, rows[3]
assert rows[4]["tenant_id"] == "tenant-prod-b" and rows[4]["reason_code"] == "privacy_budget_missing_scope", rows[4]
assert check_report["status"] == "ok", check_report

summary = {
    "schema": "s3_privacy_budget_production_evidence/v1",
    "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "status": "pass",
    "out_dir": str(out_dir),
    "cases": [
        {
            "case": "required_without_ledger",
            "expected": "fail_closed",
            "actual_exit_code": missing_ledger_rc,
            "evidence": str(out_dir / "case_0_missing_ledger.log"),
        },
        {
            "case": "configured_scope_first_release",
            "expected": "allow",
            "actual_released": reports["allow"]["released"],
            "reason_code": reports["allow"].get("reason_code"),
            "evidence": str(out_dir / "report_1_allow.json"),
        },
        {
            "case": "exact_duplicate",
            "expected": "deny",
            "actual_released": reports["duplicate"]["released"],
            "reason_code": reports["duplicate"].get("reason_code"),
            "evidence": str(out_dir / "report_2_duplicate.json"),
        },
        {
            "case": "overlap_near_duplicate",
            "expected": "deny",
            "actual_released": reports["overlap"]["released"],
            "reason_code": reports["overlap"].get("reason_code"),
            "evidence": str(out_dir / "report_3_overlap.json"),
        },
        {
            "case": "budget_exhausted",
            "expected": "deny",
            "actual_released": reports["exhausted"]["released"],
            "reason_code": reports["exhausted"].get("reason_code"),
            "evidence": str(out_dir / "report_4_exhausted.json"),
        },
        {
            "case": "missing_scope",
            "expected": "deny",
            "actual_released": reports["missing_scope"]["released"],
            "reason_code": reports["missing_scope"].get("reason_code"),
            "evidence": str(out_dir / "report_5_missing_scope.json"),
        },
    ],
    "ledger_records": len(rows),
    "check_report": str(check_report_path),
    "errors": [],
}
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

sha256sum \
  "$CONFIG" \
  "$OUT_DIR/result.json" \
  "$OUT_DIR/meta_1_allow.json" \
  "$OUT_DIR/meta_2_duplicate.json" \
  "$OUT_DIR/meta_3_overlap.json" \
  "$OUT_DIR/meta_4_exhausted.json" \
  "$OUT_DIR/meta_5_missing_scope.json" \
  "$OUT_DIR/case_0_missing_ledger.log" \
  "$OUT_DIR/report_1_allow.json" \
  "$OUT_DIR/report_2_duplicate.json" \
  "$OUT_DIR/report_3_overlap.json" \
  "$OUT_DIR/report_4_exhausted.json" \
  "$OUT_DIR/report_5_missing_scope.json" \
  "$LEDGER" \
  "$AUDIT" \
  "$CHECK_REPORT" \
  "$SUMMARY_JSON" \
  > "$HASHES"

cat > "$SUMMARY_MD" <<EOF
# S3 Privacy Budget Production Evidence

Generated: $(python3 -c 'import datetime; print(datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"))')

Status: pass

This evidence package verifies a local production-style privacy-budget closed
loop. The release path is fail-closed when production budget mode is enabled
without a ledger, and configured budget scopes are enforced by caller, tenant,
dataset, and purpose before any public release is allowed.

## Cases

| Case | Expected | Observed | Evidence |
| --- | --- | --- | --- |
| required without ledger | fail closed | non-zero exit | \`case_0_missing_ledger.log\` |
| configured scope first release | allow | released=true | \`report_1_allow.json\` |
| exact duplicate | deny | \`privacy_budget_duplicate_query\` | \`report_2_duplicate.json\` |
| overlapping window | deny | \`privacy_budget_near_duplicate\` | \`report_3_overlap.json\` |
| budget exhausted | deny | \`privacy_budget_exhausted\` | \`report_4_exhausted.json\` |
| missing scope | deny | \`privacy_budget_missing_scope\` | \`report_5_missing_scope.json\` |

## Artifacts

- Config: \`privacy_budget.production.json\`
- Ledger: \`privacy_budget_ledger.jsonl\`
- Policy audit: \`privacy_budget_policy_audit.jsonl\`
- Check report: \`privacy_budget_check_report.json\`
- Verification summary: \`verification_summary.json\`
- Hash manifest: \`final_evidence_hashes.sha256\`

## Final Report Language

- S3 privacy budget production-style closed loop: local evidence completed
- Closed-loop controls verified: fail-closed required mode, scoped budget config,
  consumed-budget ledger, duplicate-query denial, overlapping-window denial,
  budget-exhaustion denial, missing-scope denial
- Remaining production work: wire this same required mode into the operator
  query entry point and metadata sidecar persistence; then obtain joint
  certification over a real deployment run
EOF

echo "{\"status\":\"pass\",\"out_dir\":\"$OUT_DIR\",\"cases\":6,\"ledger\":\"$LEDGER\"}"
