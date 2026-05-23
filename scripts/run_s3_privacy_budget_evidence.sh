#!/usr/bin/env bash
# Stable S3 repo-side privacy budget evidence runner.
#
# This script writes a durable evidence package under
# tmp/s3_privacy_budget_repo_evidence/ instead of a throwaway temp directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

OUT_DIR="${S3_PRIVACY_BUDGET_OUT_DIR:-$REPO_ROOT/tmp/s3_privacy_budget_repo_evidence}"
POLICY_RELEASE="$REPO_ROOT/a-psi/moduleA_psi/scripts/policy_release.py"
CHECK_PY="$REPO_ROOT/scripts/check_privacy_budget.py"
VALIDATE_PY="$REPO_ROOT/scripts/validate_json_contract.py"

mkdir -p "$OUT_DIR"

LEDGER="$OUT_DIR/privacy_budget_ledger.jsonl"
AUDIT="$OUT_DIR/privacy_budget_policy_audit.jsonl"
CHECK_REPORT="$OUT_DIR/privacy_budget_check_report.json"
SUMMARY_JSON="$OUT_DIR/verification_summary.json"
SUMMARY_MD="$OUT_DIR/EVIDENCE_SUMMARY.md"
HASHES="$OUT_DIR/final_evidence_hashes.sha256"

: > "$LEDGER"
: > "$AUDIT"

printf '%s\n' \
  '{"intersection_size":2,"intersection_sum":425,"server_addr":"privacy-budget-local","tls":true}' \
  > "$OUT_DIR/result.json"

printf '%s\n' \
  '{"job_id":"s3-budget-job-1","window_start":"2026-01-01T00:00:00Z","window_end":"2026-01-31T00:00:00Z","bucket":"campaign-a"}' \
  > "$OUT_DIR/meta_1_allow.json"
printf '%s\n' \
  '{"job_id":"s3-budget-job-2","window_start":"2026-01-01T00:00:00Z","window_end":"2026-01-31T00:00:00Z","bucket":"campaign-a"}' \
  > "$OUT_DIR/meta_2_duplicate.json"
printf '%s\n' \
  '{"job_id":"s3-budget-job-3","window_start":"2026-01-15T00:00:00Z","window_end":"2026-02-15T00:00:00Z","bucket":"campaign-a"}' \
  > "$OUT_DIR/meta_3_overlap.json"
printf '%s\n' \
  '{"job_id":"s3-budget-job-4","window_start":"2026-03-01T00:00:00Z","window_end":"2026-03-31T00:00:00Z","bucket":"campaign-a"}' \
  > "$OUT_DIR/meta_4_exhausted.json"

release_with_budget() {
  local meta="$1"
  local out="$2"
  python3 "$POLICY_RELEASE" \
    --input "$OUT_DIR/result.json" \
    --job-meta "$meta" \
    --out "$out" \
    --audit-log "$AUDIT" \
    --caller s3_privacy_budget_repo_evidence \
    --threshold-k 1 \
    --max-queries 10 \
    --privacy-budget-ledger "$LEDGER" \
    --privacy-budget-limit 1
}

release_with_budget "$OUT_DIR/meta_1_allow.json" "$OUT_DIR/report_1_allow.json" > "$OUT_DIR/case_1_allow.log" 2>&1
release_with_budget "$OUT_DIR/meta_2_duplicate.json" "$OUT_DIR/report_2_duplicate.json" > "$OUT_DIR/case_2_duplicate.log" 2>&1
release_with_budget "$OUT_DIR/meta_3_overlap.json" "$OUT_DIR/report_3_overlap.json" > "$OUT_DIR/case_3_overlap.log" 2>&1
release_with_budget "$OUT_DIR/meta_4_exhausted.json" "$OUT_DIR/report_4_exhausted.json" > "$OUT_DIR/case_4_exhausted.log" 2>&1

python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/public_report.schema.json" --json "$OUT_DIR/report_1_allow.json" > /dev/null
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/public_report.schema.json" --json "$OUT_DIR/report_2_duplicate.json" > /dev/null
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/public_report.schema.json" --json "$OUT_DIR/report_3_overlap.json" > /dev/null
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/public_report.schema.json" --json "$OUT_DIR/report_4_exhausted.json" > /dev/null
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/policy_audit.schema.json" --jsonl "$AUDIT" > /dev/null
python3 "$VALIDATE_PY" --schema "$REPO_ROOT/schemas/privacy_budget_ledger.schema.json" --jsonl "$LEDGER" > /dev/null

python3 "$CHECK_PY" \
  --ledger "$LEDGER" \
  --expect-consumed-min 1 \
  --expect-deny-reason privacy_budget_duplicate_query \
  --expect-deny-reason privacy_budget_near_duplicate \
  --expect-deny-reason privacy_budget_exhausted \
  --output "$CHECK_REPORT" \
  > /dev/null

python3 "$VALIDATE_PY" \
  --schema "$REPO_ROOT/schemas/privacy_budget_check_report.schema.json" \
  --json "$CHECK_REPORT" \
  > /dev/null

python3 - "$OUT_DIR" "$LEDGER" "$CHECK_REPORT" "$SUMMARY_JSON" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

out_dir = Path(sys.argv[1])
ledger_path = Path(sys.argv[2])
check_report_path = Path(sys.argv[3])
summary_path = Path(sys.argv[4])

reports = {
    "allow": json.loads((out_dir / "report_1_allow.json").read_text(encoding="utf-8")),
    "duplicate": json.loads((out_dir / "report_2_duplicate.json").read_text(encoding="utf-8")),
    "overlap": json.loads((out_dir / "report_3_overlap.json").read_text(encoding="utf-8")),
    "exhausted": json.loads((out_dir / "report_4_exhausted.json").read_text(encoding="utf-8")),
}
rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
check_report = json.loads(check_report_path.read_text(encoding="utf-8"))

assert reports["allow"]["released"] is True, reports["allow"]
assert reports["duplicate"]["released"] is False, reports["duplicate"]
assert reports["duplicate"]["reason_code"] == "privacy_budget_duplicate_query", reports["duplicate"]
assert reports["overlap"]["released"] is False, reports["overlap"]
assert reports["overlap"]["reason_code"] == "privacy_budget_near_duplicate", reports["overlap"]
assert reports["exhausted"]["released"] is False, reports["exhausted"]
assert reports["exhausted"]["reason_code"] == "privacy_budget_exhausted", reports["exhausted"]
assert len(rows) == 4, rows
assert rows[0]["decision"] == "allow" and rows[0]["budget"]["consumed"] is True, rows[0]
assert rows[1]["abuse_signal"] == "exact_duplicate" and rows[1]["budget"]["consumed"] is False, rows[1]
assert rows[2]["abuse_signal"] == "near_duplicate_or_differencing" and rows[2]["budget"]["consumed"] is False, rows[2]
assert rows[3]["abuse_signal"] == "budget_exhausted" and rows[3]["budget"]["consumed"] is False, rows[3]
assert check_report["status"] == "ok", check_report

summary = {
    "schema": "s3_privacy_budget_repo_evidence/v1",
    "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "status": "pass",
    "out_dir": str(out_dir),
    "cases": [
        {
            "case": "first_release",
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
    ],
    "ledger_records": len(rows),
    "check_report": str(check_report_path),
    "errors": [],
}
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

sha256sum \
  "$OUT_DIR/result.json" \
  "$OUT_DIR/meta_1_allow.json" \
  "$OUT_DIR/meta_2_duplicate.json" \
  "$OUT_DIR/meta_3_overlap.json" \
  "$OUT_DIR/meta_4_exhausted.json" \
  "$OUT_DIR/report_1_allow.json" \
  "$OUT_DIR/report_2_duplicate.json" \
  "$OUT_DIR/report_3_overlap.json" \
  "$OUT_DIR/report_4_exhausted.json" \
  "$LEDGER" \
  "$AUDIT" \
  "$CHECK_REPORT" \
  "$SUMMARY_JSON" \
  > "$HASHES"

cat > "$SUMMARY_MD" <<EOF
# S3 Privacy Budget Repo Evidence

Generated: $(python3 -c 'import datetime; print(datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"))')

Status: pass

This evidence package verifies the repo-side S3 privacy budget release gate.
It is local technical evidence only; S3 remains partial until metadata read-model
integration and Person 1 / Person 2 / Person 3 joint certification are complete.

## Cases

| Case | Expected | Observed | Evidence |
| --- | --- | --- | --- |
| first release | allow | released=true | \`report_1_allow.json\` |
| exact duplicate | deny | \`privacy_budget_duplicate_query\` | \`report_2_duplicate.json\` |
| overlapping window | deny | \`privacy_budget_near_duplicate\` | \`report_3_overlap.json\` |
| budget exhausted | deny | \`privacy_budget_exhausted\` | \`report_4_exhausted.json\` |

## Artifacts

- Ledger: \`privacy_budget_ledger.jsonl\`
- Policy audit: \`privacy_budget_policy_audit.jsonl\`
- Check report: \`privacy_budget_check_report.json\`
- Verification summary: \`verification_summary.json\`
- Hash manifest: \`final_evidence_hashes.sha256\`

## Final Report Language

- S3 privacy budget repo-side evidence: completed
- S3 production task status: partial
- Remaining work: metadata sidecar read model, operator query entry point,
  tenant/dataset/purpose budget config source, and three-person joint certification
EOF

echo "{\"status\":\"pass\",\"out_dir\":\"$OUT_DIR\",\"cases\":4,\"ledger\":\"$LEDGER\"}"
