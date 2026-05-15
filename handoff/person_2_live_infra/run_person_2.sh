#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

EVIDENCE_DIR="${PERSON2_EVIDENCE_DIR:-tmp/team_evidence/person_2}"
RECOVERY_CONFIG="${PERSON2_RECOVERY_CONFIG:-config/record_recovery_http_service.example.json}"
RECOVERY_CANDIDATES="${PERSON2_RECOVERY_CANDIDATES:-1000}"
RECOVERY_CONCURRENCY="${PERSON2_RECOVERY_CONCURRENCY:-5}"
BRIDGE_SERVER_ROWS="${PERSON2_BRIDGE_SERVER_ROWS:-1000}"
BRIDGE_CLIENT_ROWS="${PERSON2_BRIDGE_CLIENT_ROWS:-1000}"

usage() {
  cat <<'USAGE'
Usage:
  bash handoff/person_2_live_infra/run_person_2.sh <mode>

Modes:
  prepare     Create evidence directory and seed EVIDENCE_LOG.md.
  service     Start recovery-service from configured config in foreground.
  health      Probe configured recovery-service health.
  benchmarks  Run lightweight record-recovery and bridge benchmarks.
  infra-plan  Render static infra topology reports when generators exist.
  all         Run prepare, health, benchmarks, and infra-plan.

Environment:
  PERSON2_EVIDENCE_DIR          default tmp/team_evidence/person_2
  PERSON2_RECOVERY_CONFIG       default config/record_recovery_http_service.example.json
  PERSON2_RECOVERY_CANDIDATES   default 1000
  PERSON2_RECOVERY_CONCURRENCY  default 5
  PERSON2_BRIDGE_SERVER_ROWS    default 1000
  PERSON2_BRIDGE_CLIENT_ROWS    default 1000
USAGE
}

log() {
  mkdir -p "$EVIDENCE_DIR"
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$EVIDENCE_DIR/person_2_run.log"
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
    cp handoff/person_2_live_infra/EVIDENCE_LOG.md "$EVIDENCE_DIR/EVIDENCE_LOG.md"
  fi
  log "prepared $EVIDENCE_DIR"
}

service() {
  prepare
  log "starting recovery service with config=$RECOVERY_CONFIG"
  exec python3 scripts/run_record_recovery_service.py serve --config "$RECOVERY_CONFIG"
}

health() {
  prepare
  run_logged recovery_service_health \
    python3 scripts/request_record_recovery_service.py \
      --config "$RECOVERY_CONFIG" \
      --health \
      --output "$EVIDENCE_DIR/recovery_service_health.json"
}

benchmarks() {
  prepare
  run_logged benchmark_record_recovery \
    python3 scripts/benchmark_record_recovery.py \
      --candidate-count "$RECOVERY_CANDIDATES" \
      --concurrency "$RECOVERY_CONCURRENCY" \
      --mode g2b_acceptance \
      --output "$EVIDENCE_DIR/record_recovery_benchmark.json"

  run_logged benchmark_bridge \
    python3 scripts/benchmark_bridge.py \
      --server-rows "$BRIDGE_SERVER_ROWS" \
      --client-rows "$BRIDGE_CLIENT_ROWS" \
      --mode prepare_job_jsonl \
      --output "$EVIDENCE_DIR/bridge_benchmark.json"
}

infra_plan() {
  prepare
  run_logged render_postgres_ha_topology \
    python3 scripts/render_postgres_ha_topology.py \
      --out-dir "$EVIDENCE_DIR/postgres-ha" \
      --output "$EVIDENCE_DIR/postgres_ha_topology_report.json"

  run_logged render_patroni_failover_topology \
    python3 scripts/render_patroni_failover_topology.py \
      --out-dir "$EVIDENCE_DIR/patroni-ha" \
      --output "$EVIDENCE_DIR/patroni_failover_topology_report.json"

  run_logged render_pgbouncer_topology \
    python3 scripts/render_pgbouncer_topology.py \
      --out-dir "$EVIDENCE_DIR/pgbouncer" \
      --output "$EVIDENCE_DIR/pgbouncer_topology_report.json"

  run_logged render_observability_topology \
    python3 scripts/render_observability_topology.py \
      --output "$EVIDENCE_DIR/observability_topology_report.json"
}

mode="${1:-}"
case "$mode" in
  prepare) prepare ;;
  service) service ;;
  health) health ;;
  benchmarks) benchmarks ;;
  infra-plan) infra_plan ;;
  all) prepare; health; benchmarks; infra_plan ;;
  -h|--help|help|"") usage ;;
  *) usage; exit 2 ;;
esac
