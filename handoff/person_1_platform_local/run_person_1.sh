#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

EVIDENCE_DIR="${PERSON1_EVIDENCE_DIR:-tmp/team_evidence/person_1}"
RUN_ROOT="${PERSON1_LIVE_RUN_ROOT:-$EVIDENCE_DIR/live_sse_bridge_demo}"
DASHBOARD_HOST="${PERSON1_DASHBOARD_HOST:-127.0.0.1}"
DASHBOARD_PORT="${PERSON1_DASHBOARD_PORT:-18134}"
OUT_BASE="${PERSON1_OUT_BASE:-tmp/sse_bridge_pipeline_demo}"
HISTORY_ROOT="${PERSON1_HISTORY_ROOT:-tmp}"
METADATA_DB="${PERSON1_METADATA_DB:-}"

usage() {
  cat <<'USAGE'
Usage:
  bash handoff/person_1_platform_local/run_person_1.sh <mode>

Modes:
  prepare    Create evidence directory and seed EVIDENCE_LOG.md.
  demo       Run live SSE demo and collect core artifacts.
  smoke      Run check_ci_smoke.sh and check_json_contracts.sh.
  dashboard  Start operator dashboard in the foreground.
  all        Run prepare, demo, and smoke.

Environment:
  PERSON1_EVIDENCE_DIR      default tmp/team_evidence/person_1
  PERSON1_LIVE_RUN_ROOT     default $PERSON1_EVIDENCE_DIR/live_sse_bridge_demo
  PERSON1_DASHBOARD_HOST    default 127.0.0.1
  PERSON1_DASHBOARD_PORT    default 18134
  PERSON1_OUT_BASE          default tmp/sse_bridge_pipeline_demo
  PERSON1_HISTORY_ROOT      default tmp
  PERSON1_METADATA_DB       optional metadata DB path for dashboard workflow state
USAGE
}

log() {
  mkdir -p "$EVIDENCE_DIR"
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$EVIDENCE_DIR/person_1_run.log"
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
    cp handoff/person_1_platform_local/EVIDENCE_LOG.md "$EVIDENCE_DIR/EVIDENCE_LOG.md"
  fi
  log "prepared $EVIDENCE_DIR"
}

copy_if_exists() {
  local src="$1"
  local dst="$2"
  if [[ -f "$src" ]]; then
    cp "$src" "$dst"
    log "collected $dst"
  else
    log "missing optional artifact $src"
  fi
}

latest_run_dir() {
  find "$RUN_ROOT" -maxdepth 1 -type d -name 'run-*' 2>/dev/null | sort | tail -n 1
}

demo() {
  prepare
  mkdir -p "$RUN_ROOT"
  run_logged live_sse_bridge_demo bash scripts/run_live_sse_bridge_demo.sh --run-root "$RUN_ROOT"

  local run_dir
  run_dir="$(latest_run_dir)"
  if [[ -z "$run_dir" ]]; then
    log "no run-* directory found under $RUN_ROOT"
    return 1
  fi

  printf '%s\n' "$run_dir" > "$EVIDENCE_DIR/latest_live_run_dir.txt"
  copy_if_exists "$run_dir/live_demo_manifest.json" "$EVIDENCE_DIR/live_demo_manifest.json"
  copy_if_exists "$run_dir/a_psi_run/public_report.json" "$EVIDENCE_DIR/public_report.json"
  copy_if_exists "$run_dir/mainline_contract_check.json" "$EVIDENCE_DIR/mainline_contract_check.json"
  copy_if_exists "$run_dir/audit_chain.json" "$EVIDENCE_DIR/audit_chain.json"
}

smoke() {
  prepare
  run_logged check_ci_smoke bash scripts/check_ci_smoke.sh
  run_logged check_json_contracts bash scripts/check_json_contracts.sh
}

dashboard() {
  prepare
  local args=(
    scripts/serve_operator_dashboard.py
    --out-base "$OUT_BASE"
    --history-root "$HISTORY_ROOT"
    --bind-host "$DASHBOARD_HOST"
    --port "$DASHBOARD_PORT"
  )
  if [[ -n "$METADATA_DB" ]]; then
    args+=(--metadata-db-path "$METADATA_DB")
  fi
  log "starting dashboard http://$DASHBOARD_HOST:$DASHBOARD_PORT/ with out_base=$OUT_BASE history_root=$HISTORY_ROOT"
  exec python3 "${args[@]}"
}

mode="${1:-}"
case "$mode" in
  prepare) prepare ;;
  demo) demo ;;
  smoke) smoke ;;
  dashboard) dashboard ;;
  all) prepare; demo; smoke ;;
  -h|--help|help|"") usage ;;
  *) usage; exit 2 ;;
esac
