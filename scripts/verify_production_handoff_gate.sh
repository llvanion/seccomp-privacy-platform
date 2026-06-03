#!/usr/bin/env bash
# S1 production handoff gate verification.
#
# Verifies the production-mode gate enforces "no retained file-mode SSE
# plaintext handoff" without requiring a full pipeline run (the gate logic
# lives in scripts/check_mainline_contract.py and the arg-validation layer
# of scripts/run_sse_bridge_pipeline.sh).
#
# Three assertions:
#   case-1 POSITIVE  — synthetic FIFO/removed run-bundle: production-mode
#                      contract check passes (status=ok, production_mode=True,
#                      plaintext_exposure_risk=none).
#   case-2 NEGATIVE  — synthetic file/retained run-bundle: production-mode
#                      contract check fails with finding kind
#                      production_handoff_plaintext_elevated.
#   case-3 NEGATIVE  — pipeline arg-validation rejects --production-mode +
#                      --keep-sse-export-handoff-files before any binary
#                      runs. Confirms the entry-point can not even be invoked
#                      in a configuration that would land plaintext on disk.
#
# Usage:
#   bash scripts/verify_production_handoff_gate.sh [--keep-out-dir]
#
# Exit codes:
#   0  All three assertions matched.
#   1  Any assertion failed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CHECK_PY="$SCRIPT_DIR/check_mainline_contract.py"
PIPELINE_SH="$SCRIPT_DIR/run_sse_bridge_pipeline.sh"

KEEP_OUT_DIR=0
for arg in "$@"; do
  case "$arg" in
    --keep-out-dir) KEEP_OUT_DIR=1 ;;
    *) echo "[ERROR] unknown argument: $arg" >&2; exit 1 ;;
  esac
done

OUT_ROOT="$(mktemp -d /tmp/seccomp_prod_handoff.XXXXXX)"
cleanup() {
  if [[ "$KEEP_OUT_DIR" -eq 0 ]]; then
    rm -rf "$OUT_ROOT"
  else
    echo "[info] output preserved at: $OUT_ROOT"
  fi
}
trap cleanup EXIT

# ----- helpers -----

# build_run_bundle <out_base> <output_file_type> <retained 0|1>
# Synthesises the minimum SSE/bridge audit pair that check_mainline_contract.py
# inspects for handoff exposure assessment.
build_run_bundle() {
  local out_base="$1"
  local file_type="$2"   # file | fifo
  local retained="$3"    # 0 | 1
  local job_id="prod_gate_synth_job"
  local correlation_id="$job_id"
  local server_output="$out_base/sse_exports/server.csv"
  local client_output="$out_base/sse_exports/client.csv"
  if [[ "$file_type" == "fifo" ]]; then
    server_output="$out_base/sse_exports/server.fifo"
    client_output="$out_base/sse_exports/client.fifo"
  fi
  mkdir -p "$out_base/sse_exports" "$out_base/bridge_job" "$out_base/a_psi_run"

  # Optionally leave behind the plaintext file. For fifo+removed we always
  # remove (FIFO output is consumed). For file+cleaned we remove. For
  # file+retained we leave a placeholder.
  if [[ "$retained" == "1" && "$file_type" == "file" ]]; then
    : > "$server_output"
    : > "$client_output"
  fi

  python3 - "$out_base" "$file_type" "$server_output" "$client_output" "$job_id" "$correlation_id" <<'PY'
import json, sys, hashlib
out_base, file_type, server_output, client_output, job_id, correlation_id = sys.argv[1:7]

base_record = {
    "job_id": job_id,
    "correlation_id": correlation_id,
    "caller": "auto_demo",
}
def export_record(role, output_file):
    return {
        **base_record,
        "role": role,
        "output_file": output_file,
        "output_file_type": file_type,
        "input_rows": 2,
        "output_rows": 2,
    }

with open(f"{out_base}/sse_exports/export_audit.jsonl", "w", encoding="utf-8") as f:
    for role, output_file in (("server", server_output), ("client", client_output)):
        f.write(json.dumps(export_record(role, output_file)) + "\n")

bridge_meta = {
    "job_id": job_id,
    "correlation_id": correlation_id,
    "bridge": {
        "token_scope": "prod-gate-scope",
        "token_key_version": "1",
    },
}
with open(f"{out_base}/bridge_job/job_meta.json", "w", encoding="utf-8") as f:
    json.dump(bridge_meta, f)

# minimal bridge_audit.jsonl — only role-agnostic fields needed by the checker
bridge_audit = {
    "job_id": job_id,
    "correlation_id": correlation_id,
    "server_input_file_type": file_type,
    "client_input_file_type": file_type,
}
if file_type == "file":
    bridge_audit["server_input_sha256"] = hashlib.sha256(b"").hexdigest()
    bridge_audit["client_input_sha256"] = hashlib.sha256(b"").hexdigest()
with open(f"{out_base}/bridge_job/bridge_audit.jsonl", "w", encoding="utf-8") as f:
    f.write(json.dumps(bridge_audit) + "\n")
PY
}

PASS=1

###################################################################
# case-1 POSITIVE: synthetic FIFO/removed run-bundle, production-mode passes
###################################################################
POS_OUT="$OUT_ROOT/positive"
build_run_bundle "$POS_OUT" "fifo" "0"
POS_REPORT="$POS_OUT/contract_check.json"
echo "[case-1] FIFO/removed bundle + --production-mode (expect status=ok)"
if ! python3 "$CHECK_PY" \
      --out-base "$POS_OUT" \
      --job-id "prod_gate_synth_job" \
      --output "$POS_REPORT" \
      --production-mode > /dev/null 2> "$POS_OUT/check.err"; then
  echo "[FAIL] case-1 unexpected non-zero exit; stderr:" >&2
  cat "$POS_OUT/check.err" >&2
  PASS=0
fi
POS_STATUS="$(python3 -c "import json; print(json.load(open('$POS_REPORT')).get('status','MISSING'))")"
POS_PROD="$(python3 -c "import json; print(json.load(open('$POS_REPORT')).get('production_mode','MISSING'))")"
POS_RISK="$(python3 -c "import json; print((json.load(open('$POS_REPORT')).get('handoff_exposure_assessment') or {}).get('plaintext_exposure_risk','MISSING'))")"
if [[ "$POS_STATUS" != "ok" ]]; then
  echo "[FAIL] case-1 expected status=ok, got=$POS_STATUS" >&2; PASS=0
fi
if [[ "$POS_PROD" != "True" ]]; then
  echo "[FAIL] case-1 expected production_mode=True, got=$POS_PROD" >&2; PASS=0
fi
if [[ "$POS_RISK" != "none" ]]; then
  echo "[FAIL] case-1 expected plaintext_exposure_risk=none, got=$POS_RISK" >&2; PASS=0
fi

###################################################################
# case-2 NEGATIVE: synthetic file/retained run-bundle is rejected by the gate
###################################################################
NEG_OUT="$OUT_ROOT/negative_check"
build_run_bundle "$NEG_OUT" "file" "1"
NEG_REPORT="$NEG_OUT/contract_check.json"
echo "[case-2] file/retained bundle + --production-mode (expect status=fail with elevated finding)"
set +e
python3 "$CHECK_PY" \
  --out-base "$NEG_OUT" \
  --job-id "prod_gate_synth_job" \
  --output "$NEG_REPORT" \
  --allow-retained-managed-handoff \
  --retained-managed-handoff-reason "compatibility-debug-retained" \
  --production-mode > /dev/null 2> "$NEG_OUT/check.err"
NEG_RC=$?
set -e
if [[ "$NEG_RC" -eq 0 ]]; then
  echo "[FAIL] case-2 contract checker returned 0; expected non-zero" >&2; PASS=0
fi
NEG_STATUS="$(python3 -c "import json; print(json.load(open('$NEG_REPORT')).get('status','MISSING'))")"
NEG_PROD="$(python3 -c "import json; print(json.load(open('$NEG_REPORT')).get('production_mode','MISSING'))")"
NEG_RISK="$(python3 -c "import json; print((json.load(open('$NEG_REPORT')).get('handoff_exposure_assessment') or {}).get('plaintext_exposure_risk','MISSING'))")"
NEG_KIND="$(python3 -c "
import json
findings = json.load(open('$NEG_REPORT')).get('findings') or []
hits = [f for f in findings if f.get('kind') == 'production_handoff_plaintext_elevated']
print('hit' if hits else 'miss')
")"
if [[ "$NEG_STATUS" != "fail" ]]; then
  echo "[FAIL] case-2 expected status=fail, got=$NEG_STATUS" >&2; PASS=0
fi
if [[ "$NEG_PROD" != "True" ]]; then
  echo "[FAIL] case-2 expected production_mode=True, got=$NEG_PROD" >&2; PASS=0
fi
if [[ "$NEG_RISK" != "elevated" ]]; then
  echo "[FAIL] case-2 expected plaintext_exposure_risk=elevated, got=$NEG_RISK" >&2; PASS=0
fi
if [[ "$NEG_KIND" != "hit" ]]; then
  echo "[FAIL] case-2 expected finding kind=production_handoff_plaintext_elevated; not present" >&2; PASS=0
fi

###################################################################
# case-3 NEGATIVE: pipeline arg-validation rejects production + retained
###################################################################
ARG_OUT="$OUT_ROOT/negative_arg"
mkdir -p "$ARG_OUT"
echo "[case-3] pipeline --production-mode + --keep-sse-export-handoff-files (expect arg rejection)"
set +e
PROD_GATE_TOKEN_SECRET=local-dev-secret \
bash "$PIPELINE_SH" \
  --server-source "$REPO_ROOT/sse/examples/bridge_server_records.jsonl" \
  --client-source "$REPO_ROOT/sse/examples/bridge_client_records.jsonl" \
  --server-join-key-field email \
  --client-join-key-field email \
  --client-value-field amount \
  --server-normalizer email \
  --client-normalizer email \
  --client-value-mode raw-int \
  --client-value-max 1000000 \
  --token-scope prod-gate-scope \
  --token-secret-env PROD_GATE_TOKEN_SECRET \
  --job-id prod_gate_arg_job \
  --out-base "$ARG_OUT" \
  --caller auto_demo \
  --sse-export-policy-config "$REPO_ROOT/sse/config/export_policy.example.json" \
  --sse-export-handoff-mode file \
  --keep-sse-export-handoff-files \
  --handoff-retention-reason "should-be-rejected-by-production-mode" \
  --production-mode \
  > "$ARG_OUT/pipeline.log" 2>&1
ARG_RC=$?
set -e
if [[ "$ARG_RC" -eq 0 ]]; then
  echo "[FAIL] case-3 pipeline exited 0; expected non-zero arg-validation failure" >&2
  PASS=0
elif ! grep -q "production-mode" "$ARG_OUT/pipeline.log"; then
  echo "[FAIL] case-3 pipeline rejected the run but the message did not mention 'production-mode'" >&2
  tail -10 "$ARG_OUT/pipeline.log" >&2
  PASS=0
fi

if [[ "$PASS" -ne 1 ]]; then
  exit 1
fi

echo "[ok] production handoff gate verified: case-1 (FIFO ok) + case-2 (post-hoc fail) + case-3 (arg rejected)"
