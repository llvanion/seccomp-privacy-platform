#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

EVIDENCE_DIR="${PERSON3_EVIDENCE_DIR:-tmp/team_evidence/person_3}"
AUDIT_CHAIN="${PERSON3_AUDIT_CHAIN:-tmp/sse_bridge_pipeline_demo/audit_chain.json}"
JOB_ID="${PERSON3_JOB_ID:-sse_demo_job}"
ANCHOR_KEY_ENV="${PERSON3_ANCHOR_KEY_ENV:-SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY}"
S3_LEDGER="${PERSON3_S3_LEDGER:-s3://seccomp-audit-archive/audit/ledger.jsonl}"
REKOR_URL="${PERSON3_REKOR_URL:-https://rekor.sigstore.dev}"

usage() {
  cat <<'USAGE'
Usage:
  bash handoff/person_3_security_audit/run_person_3.sh <mode>

Modes:
  prepare                  Create evidence directory, scope template, and findings file.
  pretest                  Run malformed-input and audit-tamper reports.
  external-anchor-planned  Produce planned S3 WORM and Rekor reports without external credentials.
  gates                    Run repo-side production/security gate scripts.
  all                      Run prepare, pretest, external-anchor-planned, and gates.

Environment:
  PERSON3_EVIDENCE_DIR     default tmp/team_evidence/person_3
  PERSON3_AUDIT_CHAIN      default tmp/sse_bridge_pipeline_demo/audit_chain.json
  PERSON3_JOB_ID           default sse_demo_job
  PERSON3_ANCHOR_KEY_ENV   default SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY
  PERSON3_S3_LEDGER        default s3://seccomp-audit-archive/audit/ledger.jsonl
  PERSON3_REKOR_URL        default https://rekor.sigstore.dev
USAGE
}

log() {
  mkdir -p "$EVIDENCE_DIR"
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$EVIDENCE_DIR/person_3_run.log"
}

run_logged() {
  local name="$1"
  shift
  log "start $name"
  "$@" 2>&1 | tee "$EVIDENCE_DIR/${name}.log"
  log "done $name"
}

prepare() {
  mkdir -p "$EVIDENCE_DIR"
  if [[ ! -f "$EVIDENCE_DIR/EVIDENCE_LOG.md" ]]; then
    cp handoff/person_3_security_audit/EVIDENCE_LOG.md "$EVIDENCE_DIR/EVIDENCE_LOG.md"
  fi
  if [[ ! -f "$EVIDENCE_DIR/SECURITY_TEST_SCOPE.md" ]]; then
    cp handoff/person_3_security_audit/SECURITY_TEST_SCOPE_TEMPLATE.md "$EVIDENCE_DIR/SECURITY_TEST_SCOPE.md"
  fi
  if [[ ! -f "$EVIDENCE_DIR/FINDINGS.md" ]]; then
    cat > "$EVIDENCE_DIR/FINDINGS.md" <<'EOF'
# Security Findings

Use one section per finding.

## Finding <id>

- Severity:
- Target:
- Timestamp:
- Reproduction:
- Evidence:
- Owner:
- Disposition: open | fixed | accepted risk | not reproducible
EOF
  fi
  log "prepared $EVIDENCE_DIR"
}

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    log "required file not found: $path"
    log "set PERSON3_AUDIT_CHAIN to a fresh Person 1 audit_chain.json, or run Person 1 demo first"
    return 1
  fi
}

pretest() {
  prepare
  require_file "$AUDIT_CHAIN"

  run_logged seal_audit_artifact \
    python3 scripts/seal_audit_artifact.py \
      --input "$AUDIT_CHAIN" \
      --out "$EVIDENCE_DIR/audit_chain.seal.json" \
      --job-id "$JOB_ID"

  run_logged verify_audit_tamper_resistance \
    python3 scripts/verify_audit_tamper_resistance.py \
      --audit-chain "$AUDIT_CHAIN" \
      --audit-seal "$EVIDENCE_DIR/audit_chain.seal.json" \
      --job-id "$JOB_ID" \
      --output "$EVIDENCE_DIR/audit_tamper_resistance.json"

  run_logged check_http_malformed_input_gate \
    python3 scripts/check_http_malformed_input_gate.py \
      --output "$EVIDENCE_DIR/http_malformed_input_gate.json"

  run_logged validate_audit_tamper_resistance \
    python3 scripts/validate_json_contract.py \
      --schema schemas/audit_tamper_resistance.schema.json \
      --json "$EVIDENCE_DIR/audit_tamper_resistance.json"

  run_logged validate_http_malformed_input_gate \
    python3 scripts/validate_json_contract.py \
      --schema schemas/http_malformed_input_gate.schema.json \
      --json "$EVIDENCE_DIR/http_malformed_input_gate.json"
}

external_anchor_planned() {
  prepare
  require_file "$AUDIT_CHAIN"
  if [[ ! -f "$EVIDENCE_DIR/audit_chain.seal.json" ]]; then
    run_logged seal_audit_artifact \
      python3 scripts/seal_audit_artifact.py \
        --input "$AUDIT_CHAIN" \
        --out "$EVIDENCE_DIR/audit_chain.seal.json" \
        --job-id "$JOB_ID"
  fi

  export "$ANCHOR_KEY_ENV=${!ANCHOR_KEY_ENV:-local-audit-anchor}"
  run_logged archive_audit_bundle \
    python3 scripts/archive_audit_bundle.py \
      --audit-chain "$AUDIT_CHAIN" \
      --audit-seal "$EVIDENCE_DIR/audit_chain.seal.json" \
      --archive-dir "$EVIDENCE_DIR/audit_archive" \
      --job-id "$JOB_ID" \
      --anchor-key-env "$ANCHOR_KEY_ENV"

  local anchor_file="$EVIDENCE_DIR/audit_archive/audit_chain_anchor.jsonl"
  run_logged publish_s3_worm_planned \
    python3 scripts/publish_external_audit_anchor.py \
      --anchor-file "$anchor_file" \
      --external-ledger "$S3_LEDGER" \
      --sink-kind s3_worm \
      --anchor-key-env "$ANCHOR_KEY_ENV" \
      --output "$EVIDENCE_DIR/s3_worm_planned.json"

  run_logged publish_rekor_planned \
    python3 scripts/publish_external_audit_anchor.py \
      --anchor-file "$anchor_file" \
      --external-ledger "$REKOR_URL" \
      --sink-kind rekor \
      --anchor-key-env "$ANCHOR_KEY_ENV" \
      --output "$EVIDENCE_DIR/rekor_planned.json"
}

gates() {
  prepare
  run_logged verify_production_handoff_gate bash scripts/verify_production_handoff_gate.sh
  run_logged verify_production_kms_gate bash scripts/verify_production_kms_gate.sh
  run_logged verify_external_audit_anchor_gate bash scripts/verify_external_audit_anchor_gate.sh
  run_logged verify_pjc_tls_identity_gate bash scripts/verify_pjc_tls_identity_gate.sh
}

mode="${1:-}"
case "$mode" in
  prepare) prepare ;;
  pretest) pretest ;;
  external-anchor-planned) external_anchor_planned ;;
  gates) gates ;;
  all) prepare; pretest; external_anchor_planned; gates ;;
  -h|--help|help|"") usage ;;
  *) usage; exit 2 ;;
esac
