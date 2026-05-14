#!/usr/bin/env bash
# S6 external audit anchor gate verification.
#
# Cases:
#   case-1 POSITIVE — file_ledger publish of a valid 2-entry anchor chain
#                     finishes with summary.status=ok and the chain is
#                     verified.
#   case-2 NEGATIVE — tampered anchor JSONL (mutate one byte of the second
#                     entry's payload_sha256) is rejected by the publisher
#                     before the sink is touched (publish exits non-zero).
#   case-3 NEGATIVE — production-mode + sink_kind=file_ledger is rejected
#                     with reason kind production_file_ledger_not_external.
#   case-4 NEGATIVE — production-mode + sink_kind=s3_worm without --execute
#                     yields finding kind production_execute_required (and
#                     production_external_anchor_not_uploaded), summary
#                     status=fail.
#   case-5 SCHEMA   — every report validates against external_audit_anchor_report/v1.
#
# Usage:
#   bash scripts/verify_external_audit_anchor_gate.sh [--keep-out-dir]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PUBLISH_PY="$SCRIPT_DIR/publish_external_audit_anchor.py"
VALIDATE_PY="$SCRIPT_DIR/validate_json_contract.py"
SCHEMA="$REPO_ROOT/schemas/external_audit_anchor_report.schema.json"

KEEP_OUT_DIR=0
for arg in "$@"; do
  case "$arg" in
    --keep-out-dir) KEEP_OUT_DIR=1 ;;
    *) echo "[ERROR] unknown argument: $arg" >&2; exit 1 ;;
  esac
done

OUT_ROOT="$(mktemp -d /tmp/seccomp_anchor_gate.XXXXXX)"
cleanup() {
  if [[ "$KEEP_OUT_DIR" -eq 0 ]]; then
    rm -rf "$OUT_ROOT"
  else
    echo "[info] output preserved at: $OUT_ROOT"
  fi
}
trap cleanup EXIT

# ----- synthesize a valid 2-entry anchor JSONL using the project helpers
ANCHOR_DIR="$OUT_ROOT/archive"
ANCHOR_FILE="$ANCHOR_DIR/audit_chain_anchor.jsonl"
mkdir -p "$ANCHOR_DIR"
PYTHONPATH="$REPO_ROOT" python3 - "$ANCHOR_FILE" <<'PY'
import json, os, sys
from datetime import datetime, timezone
from scripts.archive_audit_bundle import (
    compute_anchor_entry_sha256,
    compute_anchor_payload_sha256,
)
anchor_file = sys.argv[1]
prev_entry_sha = None
records = []
for i in range(1, 3):
    base = {
        "schema": "audit_archive_anchor/v1",
        "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": "anchor_audit_bundle",
        "job_id": f"synth_job_{i}",
        "correlation_id": f"synth_job_{i}",
        "tenant_id": None,
        "archive_dir": os.path.dirname(anchor_file),
        "anchor_file": anchor_file,
        "index_file": os.path.join(os.path.dirname(anchor_file), "audit_chain_index.jsonl"),
        "archived_audit_chain_file": os.path.join(os.path.dirname(anchor_file), f"chain_{i}.json"),
        "archived_audit_seal_file": os.path.join(os.path.dirname(anchor_file), f"seal_{i}.json"),
        "index_record_sha256": "f" * 64,
        "previous_anchor_entry_sha256": prev_entry_sha,
        "chain_position": i,
        "signature_algorithm": None,
        "signature": None,
        "secret_source": None,
    }
    payload_sha = compute_anchor_payload_sha256(base)
    base["payload_sha256"] = payload_sha
    base["entry_sha256"] = compute_anchor_entry_sha256(
        previous_anchor_entry_sha256=prev_entry_sha,
        payload_sha256=payload_sha,
    )
    prev_entry_sha = base["entry_sha256"]
    records.append(base)
with open(anchor_file, "w", encoding="utf-8") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"wrote 2 anchor records to {anchor_file}")
PY

PASS=1

run_publish() {
  local out="$1"; shift
  python3 "$PUBLISH_PY" \
    --anchor-file "$ANCHOR_FILE" \
    --output "$out" \
    "$@"
}

field() {
  python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('summary',{}).get(sys.argv[2],'MISSING'))" "$1" "$2"
}
prod_finding_kinds() {
  python3 -c "
import json,sys
findings = json.load(open(sys.argv[1])).get('production_findings') or []
print(','.join(sorted({f.get('kind','') for f in findings})))
" "$1"
}

# ----- case-1 POSITIVE: file_ledger publish
LEDGER="$OUT_ROOT/external_ledger.jsonl"
REPORT1="$OUT_ROOT/r1.json"
echo "[case-1] file_ledger publish (expect summary.status=ok)"
set +e
run_publish "$REPORT1" \
  --external-ledger "$LEDGER" \
  --sink-kind file_ledger \
  --assert-ok > /dev/null 2> "$OUT_ROOT/r1.err"
RC1=$?
set -e
if [[ "$RC1" -ne 0 ]]; then
  echo "[FAIL] case-1 expected exit 0; got $RC1"; cat "$OUT_ROOT/r1.err" >&2; PASS=0
fi
if [[ "$(field "$REPORT1" status)" != "ok" ]]; then
  echo "[FAIL] case-1 expected summary.status=ok"; PASS=0
fi
if [[ "$(field "$REPORT1" verified_chain)" != "True" ]]; then
  echo "[FAIL] case-1 expected verified_chain=True"; PASS=0
fi
if [[ "$(wc -l < "$LEDGER")" != "2" ]]; then
  echo "[FAIL] case-1 expected 2 entries in $LEDGER, got $(wc -l < "$LEDGER")"; PASS=0
fi

# ----- case-2 NEGATIVE: tampered anchor JSONL
ANCHOR_TAMPER_DIR="$OUT_ROOT/tamper"
ANCHOR_TAMPER="$ANCHOR_TAMPER_DIR/audit_chain_anchor.jsonl"
mkdir -p "$ANCHOR_TAMPER_DIR"
python3 - "$ANCHOR_FILE" "$ANCHOR_TAMPER" <<'PY'
import json, sys
src, dst = sys.argv[1:]
with open(src) as f:
    lines = [json.loads(l) for l in f if l.strip()]
# Tamper: replace one hex char in entry 2's payload_sha256
sha = lines[1]["payload_sha256"]
lines[1]["payload_sha256"] = ("a" if sha[0] != "a" else "b") + sha[1:]
with open(dst, "w") as f:
    for r in lines:
        f.write(json.dumps(r) + "\n")
PY
LEDGER_T="$OUT_ROOT/external_ledger_tamper.jsonl"
REPORT2="$OUT_ROOT/r2.json"
echo "[case-2] tampered anchor chain (expect publish rejection)"
set +e
python3 "$PUBLISH_PY" \
  --anchor-file "$ANCHOR_TAMPER" \
  --external-ledger "$LEDGER_T" \
  --sink-kind file_ledger \
  --output "$REPORT2" \
  --assert-ok > /dev/null 2> "$OUT_ROOT/r2.err"
RC2=$?
set -e
if [[ "$RC2" -eq 0 ]]; then
  echo "[FAIL] case-2 expected non-zero exit; got 0"; PASS=0
fi
if grep -q "payload_sha256 mismatch" "$OUT_ROOT/r2.err"; then
  : # expected
else
  echo "[FAIL] case-2 expected stderr to mention 'payload_sha256 mismatch'"; cat "$OUT_ROOT/r2.err" >&2; PASS=0
fi
if [[ -f "$LEDGER_T" ]]; then
  echo "[FAIL] case-2 expected no external ledger file written for tampered chain"; PASS=0
fi

# ----- case-3 NEGATIVE: production-mode + file_ledger
LEDGER3="$OUT_ROOT/external_ledger_prod_file.jsonl"
REPORT3="$OUT_ROOT/r3.json"
echo "[case-3] production-mode + file_ledger (expect production_file_ledger_not_external)"
set +e
run_publish "$REPORT3" \
  --external-ledger "$LEDGER3" \
  --sink-kind file_ledger \
  --production-mode \
  --assert-ok > /dev/null 2> "$OUT_ROOT/r3.err"
RC3=$?
set -e
if [[ "$RC3" -eq 0 ]]; then
  echo "[FAIL] case-3 expected non-zero exit; got 0"; PASS=0
fi
if [[ "$(field "$REPORT3" status)" != "fail" ]]; then
  echo "[FAIL] case-3 expected summary.status=fail, got $(field "$REPORT3" status)"; PASS=0
fi
if ! python3 -c "import json,sys; print(json.load(open('$REPORT3')).get('production_mode'))" | grep -qx "True"; then
  echo "[FAIL] case-3 expected production_mode=True"; PASS=0
fi
KINDS3="$(prod_finding_kinds "$REPORT3")"
if [[ "$KINDS3" != *"production_file_ledger_not_external"* ]]; then
  echo "[FAIL] case-3 expected finding kind production_file_ledger_not_external; got '$KINDS3'"; PASS=0
fi
if [[ -e "$LEDGER3" ]]; then
  echo "[FAIL] case-3 expected production-mode file_ledger rejection before local ledger write"; PASS=0
fi

# ----- case-4 NEGATIVE: production-mode + s3_worm without --execute
REPORT4="$OUT_ROOT/r4.json"
echo "[case-4] production-mode + s3_worm without --execute (expect production_execute_required)"
set +e
run_publish "$REPORT4" \
  --external-ledger "s3://demo-bucket/anchor/key.jsonl" \
  --sink-kind s3_worm \
  --production-mode \
  --assert-ok > /dev/null 2> "$OUT_ROOT/r4.err"
RC4=$?
set -e
if [[ "$RC4" -eq 0 ]]; then
  echo "[FAIL] case-4 expected non-zero exit; got 0"; PASS=0
fi
if [[ "$(field "$REPORT4" status)" != "fail" ]]; then
  echo "[FAIL] case-4 expected summary.status=fail"; PASS=0
fi
KINDS4="$(prod_finding_kinds "$REPORT4")"
if [[ "$KINDS4" != *"production_execute_required"* ]] || [[ "$KINDS4" != *"production_external_anchor_not_uploaded"* ]]; then
  echo "[FAIL] case-4 expected production_execute_required + production_external_anchor_not_uploaded; got '$KINDS4'"; PASS=0
fi

# ----- case-5 SCHEMA validation
echo "[case-5] schema validation across reports"
for f in "$REPORT1" "$REPORT3" "$REPORT4"; do
  if ! python3 "$VALIDATE_PY" --schema "$SCHEMA" --json "$f" > /dev/null; then
    echo "[FAIL] case-5 $f failed schema validation"; PASS=0
  fi
done

if [[ "$PASS" -ne 1 ]]; then
  exit 1
fi

echo "[ok] external audit anchor gate verified: case-1 (file_ledger ok) + case-2 (tamper) + case-3 (prod/file_ledger) + case-4 (prod/s3 not executed) + case-5 (schemas)"
