#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DEMO_ROOT="${1:-$REPO_ROOT/tmp/defense_demo}"
PID_DIR="$DEMO_ROOT/pids"
RECOVERY_CONFIG="$REPO_ROOT/config/record_recovery_http_service.example.json"

log() { echo "[INFO] $*"; }

if [[ ! -d "$PID_DIR" ]]; then
  log "no pid directory: $PID_DIR"
  exit 0
fi

shopt -s nullglob
for pid_file in "$PID_DIR"/*.pid; do
  name="$(basename "$pid_file" .pid)"
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    log "stopping $name (pid=$pid)"
    kill "$pid" 2>/dev/null || true
    sleep 0.5
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$pid_file"
done
shopt -u nullglob

python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" stop --config "$RECOVERY_CONFIG" >/dev/null 2>&1 || true

log "defense demo services stopped"
