#!/usr/bin/env bash
# Verify that old PJC mTLS client certs cannot be reused across job-bound
# session manifests.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CREATE_PY="$SCRIPT_DIR/create_pjc_mtls_session.py"
CHECK_PY="$SCRIPT_DIR/check_pjc_mtls_session_manifest.py"

OUT_ROOT="${PJC_MTLS_REUSE_EVIDENCE_DIR:-$REPO_ROOT/tmp/pjc_mtls_reuse_defense}"
rm -rf "$OUT_ROOT"
mkdir -p "$OUT_ROOT"

SESSION_A="$OUT_ROOT/session_a"
SESSION_B="$OUT_ROOT/session_b"
REPLAY_DIR="$OUT_ROOT/replay_old_client_against_session_b"

python3 "$CREATE_PY" --job-id reuse-a --out-dir "$SESSION_A" --ttl-hours 24 > "$OUT_ROOT/create_session_a.json"
python3 "$CREATE_PY" --job-id reuse-b --out-dir "$SESSION_B" --ttl-hours 24 > "$OUT_ROOT/create_session_b.json"

PASS=1

echo "[case-1] session A client accepted for job reuse-a"
python3 "$CHECK_PY" \
  --manifest "$SESSION_A/session_manifest.json" \
  --cert-dir "$SESSION_A" \
  --role client \
  --job-id reuse-a \
  --output "$OUT_ROOT/case1_session_a_client_allow.json" \
  --assert-allow > /dev/null || PASS=0

echo "[case-2] session A manifest rejected for job reuse-b"
set +e
python3 "$CHECK_PY" \
  --manifest "$SESSION_A/session_manifest.json" \
  --cert-dir "$SESSION_A" \
  --role client \
  --job-id reuse-b \
  --output "$OUT_ROOT/case2_job_id_mismatch_deny.json" \
  --assert-allow > "$OUT_ROOT/case2.stdout" 2> "$OUT_ROOT/case2.stderr"
RC2=$?
set -e
if [[ "$RC2" -eq 0 ]]; then
  echo "[FAIL] case-2 expected job_id mismatch denial" >&2
  PASS=0
fi

echo "[case-3] old session A client cert rejected under session B manifest"
cp -R "$SESSION_B" "$REPLAY_DIR"
cp "$SESSION_A/client.crt" "$REPLAY_DIR/client.crt"
cp "$SESSION_A/client.key" "$REPLAY_DIR/client.key"
set +e
python3 "$CHECK_PY" \
  --manifest "$SESSION_B/session_manifest.json" \
  --cert-dir "$REPLAY_DIR" \
  --role server \
  --job-id reuse-b \
  --output "$OUT_ROOT/case3_old_client_replay_deny.json" \
  --assert-allow > "$OUT_ROOT/case3.stdout" 2> "$OUT_ROOT/case3.stderr"
RC3=$?
set -e
if [[ "$RC3" -eq 0 ]]; then
  echo "[FAIL] case-3 expected old client cert replay denial" >&2
  PASS=0
fi

python3 - "$OUT_ROOT" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

out = Path(sys.argv[1])
case1 = json.loads((out / "case1_session_a_client_allow.json").read_text(encoding="utf-8"))
case2 = json.loads((out / "case2_job_id_mismatch_deny.json").read_text(encoding="utf-8"))
case3 = json.loads((out / "case3_old_client_replay_deny.json").read_text(encoding="utf-8"))

assert case1["decision"] == "allow", case1
assert case2["decision"] == "deny", case2
assert case2["reason_code"] == "job_id_mismatch", case2
assert case3["decision"] == "deny", case3
assert case3["reason_code"] in {
    "expected_client_fingerprint_mismatch",
    "expected_client_ca_mismatch",
}, case3

summary = {
    "schema": "pjc_mtls_reuse_defense_report/v1",
    "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "status": "pass",
    "cases": [
        {
            "case": "fresh_session_allow",
            "decision": case1["decision"],
            "evidence": str(out / "case1_session_a_client_allow.json"),
        },
        {
            "case": "manifest_job_id_reuse",
            "decision": case2["decision"],
            "reason_code": case2["reason_code"],
            "evidence": str(out / "case2_job_id_mismatch_deny.json"),
        },
        {
            "case": "old_client_cert_replay",
            "decision": case3["decision"],
            "reason_code": case3["reason_code"],
            "evidence": str(out / "case3_old_client_replay_deny.json"),
        },
    ],
    "errors": [],
}
(out / "verification_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

sha256sum \
  "$OUT_ROOT/create_session_a.json" \
  "$OUT_ROOT/create_session_b.json" \
  "$OUT_ROOT/case1_session_a_client_allow.json" \
  "$OUT_ROOT/case2_job_id_mismatch_deny.json" \
  "$OUT_ROOT/case3_old_client_replay_deny.json" \
  "$OUT_ROOT/verification_summary.json" \
  > "$OUT_ROOT/final_evidence_hashes.sha256"

cat > "$OUT_ROOT/EVIDENCE_SUMMARY.md" <<EOF
# PJC mTLS Reuse Defense Evidence

Status: pass

This evidence verifies that the PJC mTLS wrappers can use a job-bound session
manifest to reject certificate reuse across jobs.

## Cases

| Case | Expected | Evidence |
| --- | --- | --- |
| Fresh session A client for job reuse-a | allow | \`case1_session_a_client_allow.json\` |
| Session A manifest reused for job reuse-b | deny \`job_id_mismatch\` | \`case2_job_id_mismatch_deny.json\` |
| Old session A client cert used under session B manifest | deny replay | \`case3_old_client_replay_deny.json\` |

## Operational Use

Create a fresh mTLS session per PJC job:

\`\`\`bash
python3 scripts/create_pjc_mtls_session.py --job-id <job_id> --out-dir tmp/pjc_mtls_sessions/<job_id> --ttl-hours 24
\`\`\`

Run Party A and Party B with:

\`\`\`bash
CERT_DIR=tmp/pjc_mtls_sessions/<job_id> JOB_ID=<job_id> PJC_MTLS_REQUIRE_SESSION_MANIFEST=1 ...
\`\`\`

The TLS wrappers automatically validate \`session_manifest.json\` before
starting when it exists in \`CERT_DIR\`.
EOF

if [[ "$PASS" -ne 1 ]]; then
  exit 1
fi

echo "{\"status\":\"pass\",\"out_dir\":\"$OUT_ROOT\"}"
