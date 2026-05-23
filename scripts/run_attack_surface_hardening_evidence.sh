#!/usr/bin/env bash
# Run bounded defensive attack-surface gates and write a stable evidence package.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="${ATTACK_SURFACE_EVIDENCE_DIR:-$REPO_ROOT/tmp/attack_surface_hardening_evidence}"

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR/logs" "$OUT_DIR/reports"

PASS=1

run_case() {
  local name="$1"
  shift
  local log="$OUT_DIR/logs/${name}.log"
  echo "[case] $name"
  set +e
  "$@" > "$log" 2>&1
  local rc=$?
  set -e
  python3 - "$OUT_DIR/reports/${name}.json" "$name" "$rc" "$log" <<'PY'
import json
import sys
from datetime import datetime, timezone
out, name, rc_raw, log = sys.argv[1:5]
rc = int(rc_raw)
payload = {
    "schema": "attack_surface_case_result/v1",
    "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "name": name,
    "status": "pass" if rc == 0 else "fail",
    "exit_code": rc,
    "log": log,
}
open(out, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
PY
  if [[ "$rc" -ne 0 ]]; then
    echo "[FAIL] $name rc=$rc; see $log" >&2
    PASS=0
  fi
}

cd "$REPO_ROOT"

run_case pjc_mtls_reuse_defense \
  bash scripts/verify_pjc_mtls_reuse_defense.sh

run_case pjc_preflight_gate \
  bash scripts/verify_pjc_preflight_gate.sh

run_case s3_privacy_budget_repo_evidence \
  bash scripts/run_s3_privacy_budget_evidence.sh

run_case s3_privacy_budget_production_evidence \
  bash scripts/run_s3_privacy_budget_production_evidence.sh

run_case production_handoff_gate \
  bash scripts/verify_production_handoff_gate.sh

run_case production_kms_gate \
  bash scripts/verify_production_kms_gate.sh

run_case external_audit_anchor_gate \
  bash scripts/verify_external_audit_anchor_gate.sh

run_case http_malformed_input_gate \
  python3 scripts/check_http_malformed_input_gate.py \
    --output "$OUT_DIR/http_malformed_input_gate.json"

run_case schema_malformed_input_gate \
  python3 scripts/check_malformed_input_gate.py \
    --out "$OUT_DIR/malformed_input_gate.json"

run_case enrollment_only_mode_smoke \
  python3 scripts/check_enrollment_only_mode_smoke.py \
    --out-dir "$OUT_DIR/enrollment_only_mode"

run_case metadata_api_rate_limit_smoke \
  python3 scripts/check_metadata_api_rate_limit_smoke.py \
    --out-dir "$OUT_DIR/metadata_api_rate_limit"

run_case bucket_dp_smoke \
  python3 scripts/check_bucket_dp_smoke.py \
    --out-dir "$OUT_DIR/bucket_dp_smoke"

python3 - "$OUT_DIR" "$PASS" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

out = Path(sys.argv[1])
pass_flag = int(sys.argv[2])
case_reports = []
for path in sorted((out / "reports").glob("*.json")):
    case_reports.append(json.loads(path.read_text(encoding="utf-8")))

summary = {
    "schema": "attack_surface_hardening_evidence/v1",
    "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "status": "pass" if pass_flag == 1 and all(item["status"] == "pass" for item in case_reports) else "fail",
    "case_count": len(case_reports),
    "pass_count": sum(1 for item in case_reports if item["status"] == "pass"),
    "fail_count": sum(1 for item in case_reports if item["status"] != "pass"),
    "cases": case_reports,
}
(out / "verification_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

lines = [
    "# Attack Surface Hardening Evidence",
    "",
    f"Generated: {summary['generated_at_utc']}",
    "",
    f"Status: {summary['status']}",
    "",
    "| Case | Status | Log |",
    "| --- | --- | --- |",
]
for item in case_reports:
    lines.append(f"| {item['name']} | {item['status']} | `{Path(item['log']).name}` |")
lines.extend([
    "",
    "## Scope",
    "",
    "This package contains bounded defensive checks only. It does not include DoS, brute force, credential stuffing, or third-party target scanning.",
    "",
    "## Report Language",
    "",
    "- Local attack-surface hardening gates: completed when `status=pass`.",
    "- External cloud/KMS/third-party penetration tests: not covered by this package unless separate live evidence exists.",
])
(out / "EVIDENCE_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

sha256sum \
  "$OUT_DIR/verification_summary.json" \
  "$OUT_DIR/EVIDENCE_SUMMARY.md" \
  "$OUT_DIR"/reports/*.json \
  > "$OUT_DIR/final_evidence_hashes.sha256"

cat "$OUT_DIR/verification_summary.json"

if [[ "$PASS" -ne 1 ]]; then
  exit 1
fi
