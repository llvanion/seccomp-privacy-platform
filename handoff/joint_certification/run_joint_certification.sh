#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

JOINT_CERT_DIR="${JOINT_CERT_DIR:-tmp/team_evidence/joint_certification}"
PERSON1_DIR="${PERSON1_EVIDENCE_DIR:-tmp/team_evidence/person_1}"
PERSON2_DIR="${PERSON2_EVIDENCE_DIR:-tmp/team_evidence/person_2}"
PERSON3_DIR="${PERSON3_EVIDENCE_DIR:-tmp/team_evidence/person_3}"

TASKS=(S1 S2 S3 S4 S5 S6 S7 S8)

usage() {
  cat <<'USAGE'
Usage:
  bash handoff/joint_certification/run_joint_certification.sh <mode> [task|all]

Modes:
  init <task|all>      Create joint-certification packet templates.
  repo-gates           Run all available repo-side S gates.
  evaluate <task|all>  Write honest status summaries for S tasks.
  all                  Run init all, repo-gates, and evaluate all.

Environment:
  JOINT_CERT_DIR        default tmp/team_evidence/joint_certification
  PERSON1_EVIDENCE_DIR  default tmp/team_evidence/person_1
  PERSON2_EVIDENCE_DIR  default tmp/team_evidence/person_2
  PERSON3_EVIDENCE_DIR  default tmp/team_evidence/person_3
USAGE
}

log() {
  mkdir -p "$JOINT_CERT_DIR"
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$JOINT_CERT_DIR/joint_certification.log"
}

valid_task() {
  local task="$1"
  for t in "${TASKS[@]}"; do
    [[ "$t" == "$task" ]] && return 0
  done
  return 1
}

task_title() {
  case "$1" in
    S1) echo "Eliminate plaintext handoff at rest" ;;
    S2) echo "Formal KMS and key lifecycle" ;;
    S3) echo "Privacy budget and query-abuse controls" ;;
    S4) echo "PJC service/resource isolation and DoS guard" ;;
    S5) echo "Metadata leakage control" ;;
    S6) echo "External tamper-evident audit anchoring" ;;
    S7) echo "Two-machine mTLS joint validation" ;;
    S8) echo "Malicious-PJC input commitment path" ;;
    *) echo "Unknown task" ;;
  esac
}

honest_status() {
  case "$1" in
    S1) echo "repo-side complete" ;;
    S2) echo "repo-side complete" ;;
    S3) echo "partial" ;;
    S4) echo "partial" ;;
    S5) echo "planned" ;;
    S6) echo "repo-side complete" ;;
    S7) echo "repo-side complete" ;;
    S8) echo "planned" ;;
    *) echo "unknown" ;;
  esac
}

missing_to_complete() {
  case "$1" in
    S1) echo "Person 2 / Person 3 cross-machine service-identity validation, encrypted artifact + KEK path, and signed joint certification." ;;
    S2) echo "Live Vault/AWS KMS drill, disabled-key/version e2e refusal evidence, and signed joint certification." ;;
    S3) echo "Metadata read model, tenant/dataset/purpose budget source, near-duplicate approval path, richer differencing samples, and signed joint certification." ;;
    S4) echo "Production PJC worker/service, resource limits enforced in the runner, timeout/crash recovery, audit fields, scale evidence, and signed joint certification." ;;
    S5) echo "Public/operator metadata split, role-based detailed metrics, small-shard merge/reject/padding behavior, and signed joint certification." ;;
    S6) echo "Live S3 Object Lock or Rekor --execute evidence with operator credentials, independent verifier evidence, and signed joint certification." ;;
    S7) echo "Two Ubuntu hosts, real mTLS PJC run, both parties' audit bundles, wrong-cert/MITM/replay negative evidence, and signed joint certification." ;;
    S8) echo "Commitment schema, bridge commitment manifest, PJC pre-run commitment verification, policy-release binding, tamper negatives, and signed joint certification." ;;
    *) echo "Unknown missing work." ;;
  esac
}

repo_gate_names() {
  case "$1" in
    S1) echo "verify_production_handoff_gate" ;;
    S2) echo "verify_production_kms_gate" ;;
    S3) echo "verify_privacy_budget_ledger" ;;
    S4) echo "verify_pjc_preflight_gate" ;;
    S5) echo "" ;;
    S6) echo "verify_external_audit_anchor_gate" ;;
    S7) echo "verify_pjc_tls_identity_gate" ;;
    S8) echo "" ;;
    *) echo "" ;;
  esac
}

repo_gate_script() {
  case "$1" in
    verify_production_handoff_gate) echo "scripts/verify_production_handoff_gate.sh" ;;
    verify_production_kms_gate) echo "scripts/verify_production_kms_gate.sh" ;;
    verify_privacy_budget_ledger) echo "scripts/verify_privacy_budget_ledger.sh" ;;
    verify_pjc_preflight_gate) echo "scripts/verify_pjc_preflight_gate.sh" ;;
    verify_external_audit_anchor_gate) echo "scripts/verify_external_audit_anchor_gate.sh" ;;
    verify_pjc_tls_identity_gate) echo "scripts/verify_pjc_tls_identity_gate.sh" ;;
    *) echo "" ;;
  esac
}

for_each_task_arg() {
  local arg="${1:-all}"
  if [[ "$arg" == "all" ]]; then
    printf '%s\n' "${TASKS[@]}"
  else
    valid_task "$arg" || { echo "[ERROR] unknown task: $arg" >&2; exit 2; }
    printf '%s\n' "$arg"
  fi
}

init_task() {
  local task="$1"
  local dir="$JOINT_CERT_DIR/$task"
  mkdir -p "$dir"
  local title
  title="$(task_title "$task")"

  cat > "$dir/TASK_SUMMARY.md" <<EOF
# $task - $title

## Scope

Task ID: $task

Current generated status: $(honest_status "$task")

## Missing Before Completed

$(missing_to_complete "$task")

## Source Documents

- docs/PRODUCTION_SECURITY_COMPLETION_PLAN.md
- docs/team/TEAM_COLLABORATION_AND_REPORTING_PLAN.md
- docs/OPS_RUNBOOK.md
EOF

  cat > "$dir/COMMANDS.md" <<EOF
# $task Commands

## Repo-Side Gate

$(repo_gate_names "$task")

Run all repo-side S gates:

\`\`\`bash
bash handoff/joint_certification/run_joint_certification.sh repo-gates
\`\`\`

## Evaluation

\`\`\`bash
bash handoff/joint_certification/run_joint_certification.sh evaluate $task
\`\`\`
EOF

  cat > "$dir/EVIDENCE_INDEX.md" <<EOF
# $task Evidence Index

## Person Evidence Directories

- Person 1: $PERSON1_DIR
- Person 2: $PERSON2_DIR
- Person 3: $PERSON3_DIR

## Repo Gate Evidence

- $JOINT_CERT_DIR/repo_gates/

## Evidence Paths

Add final evidence paths here before marking completed.
EOF

  cat > "$dir/JOINT_CERTIFICATION.md" <<EOF
# $task Joint Certification

| Field | Value |
| --- | --- |
| task_id | $task |
| task_title | $title |
| final_status | $(honest_status "$task") |
| generated_at_utc | $(date -u +%Y-%m-%dT%H:%M:%SZ) |

## Person 1 Certification

- Status: pending
- Name:
- Evidence reviewed:
- Notes:

## Person 2 Certification

- Status: pending
- Name:
- Evidence reviewed:
- Notes:

## Person 3 Certification

- Status: pending
- Name:
- Evidence reviewed:
- Notes:

## Missing Before Completed

$(missing_to_complete "$task")

## Report Wording

Current allowed wording: "$task is $(honest_status "$task")."
EOF
  log "initialized $dir"
}

run_gate_keep() {
  local name="$1"
  local script="$2"
  local out_dir="$JOINT_CERT_DIR/repo_gates/$name"
  local log_path="$JOINT_CERT_DIR/repo_gates/${name}.log"
  mkdir -p "$JOINT_CERT_DIR/repo_gates"
  rm -rf "$out_dir"
  log "start repo gate $name"
  set +e
  bash "$script" --keep-out-dir 2>&1 | tee "$log_path"
  local rc=${PIPESTATUS[0]}
  set -e
  local preserved
  preserved="$(grep -Eo 'output preserved at: .*$' "$log_path" | tail -n 1 | sed 's/output preserved at: //')"
  if [[ -n "$preserved" && -d "$preserved" ]]; then
    mkdir -p "$out_dir"
    cp -a "$preserved"/. "$out_dir"/
    log "copied $name evidence from $preserved to $out_dir"
  else
    log "no preserved evidence directory found for $name"
  fi
  if [[ "$rc" -ne 0 ]]; then
    log "repo gate $name failed with rc=$rc"
    return "$rc"
  fi
  log "done repo gate $name"
}

repo_gates() {
  mkdir -p "$JOINT_CERT_DIR/repo_gates"
  local pass=1
  run_gate_keep verify_production_handoff_gate "$(repo_gate_script verify_production_handoff_gate)" || pass=0
  run_gate_keep verify_production_kms_gate "$(repo_gate_script verify_production_kms_gate)" || pass=0
  run_gate_keep verify_privacy_budget_ledger "$(repo_gate_script verify_privacy_budget_ledger)" || pass=0
  run_gate_keep verify_pjc_preflight_gate "$(repo_gate_script verify_pjc_preflight_gate)" || pass=0
  run_gate_keep verify_external_audit_anchor_gate "$(repo_gate_script verify_external_audit_anchor_gate)" || pass=0
  run_gate_keep verify_pjc_tls_identity_gate "$(repo_gate_script verify_pjc_tls_identity_gate)" || pass=0
  [[ "$pass" -eq 1 ]]
}

evaluate_task() {
  local task="$1"
  init_task "$task"
  local dir="$JOINT_CERT_DIR/$task"
  local gate
  gate="$(repo_gate_names "$task")"
  local gate_status="not_applicable"
  if [[ -n "$gate" ]]; then
    if [[ -d "$JOINT_CERT_DIR/repo_gates/$gate" ]]; then
      gate_status="present"
    else
      gate_status="missing"
    fi
  fi

  cat >> "$dir/EVIDENCE_INDEX.md" <<EOF

## Generated Evaluation

| Field | Value |
| --- | --- |
| evaluated_at_utc | $(date -u +%Y-%m-%dT%H:%M:%SZ) |
| repo_gate | ${gate:-none} |
| repo_gate_status | $gate_status |
| honest_final_status | $(honest_status "$task") |
EOF

  cat > "$dir/JOINT_CERTIFICATION.md" <<EOF
# $task Joint Certification

| Field | Value |
| --- | --- |
| task_id | $task |
| task_title | $(task_title "$task") |
| final_status | $(honest_status "$task") |
| repo_gate | ${gate:-none} |
| repo_gate_status | $gate_status |
| evaluated_at_utc | $(date -u +%Y-%m-%dT%H:%M:%SZ) |

## Person 1 Certification

- Status: pending
- Name:
- Evidence reviewed:
- Notes:

## Person 2 Certification

- Status: pending
- Name:
- Evidence reviewed:
- Notes:

## Person 3 Certification

- Status: pending
- Name:
- Evidence reviewed:
- Notes:

## Missing Before Completed

$(missing_to_complete "$task")

## Evidence Paths

- Person 1: $PERSON1_DIR
- Person 2: $PERSON2_DIR
- Person 3: $PERSON3_DIR
- Repo gates: $JOINT_CERT_DIR/repo_gates

## Report Wording

Current allowed wording: "$task is $(honest_status "$task"). Do not describe it as completed until all three certifications and required live/operator evidence are present."
EOF
  log "evaluated $task as $(honest_status "$task")"
}

mode="${1:-}"
target="${2:-all}"

case "$mode" in
  init)
    while read -r task; do init_task "$task"; done < <(for_each_task_arg "$target")
    ;;
  repo-gates)
    repo_gates
    ;;
  evaluate)
    while read -r task; do evaluate_task "$task"; done < <(for_each_task_arg "$target")
    ;;
  all)
    while read -r task; do init_task "$task"; done < <(for_each_task_arg all)
    repo_gates
    while read -r task; do evaluate_task "$task"; done < <(for_each_task_arg all)
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    usage
    exit 2
    ;;
esac
