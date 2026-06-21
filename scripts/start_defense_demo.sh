#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DEMO_ROOT="${1:-$REPO_ROOT/tmp/defense_demo}"
DEMO_ROOT="$(cd "$(dirname "$DEMO_ROOT")" && pwd)/$(basename "$DEMO_ROOT")"
MANIFEST="$DEMO_ROOT/defense_demo_manifest.json"
ENV_FILE="$DEMO_ROOT/env.demo.sh"
PID_DIR="$DEMO_ROOT/pids"
LOG_DIR="$DEMO_ROOT/logs"
READY_DIR="$DEMO_ROOT/ready"
RECOVERY_CONFIG="$REPO_ROOT/config/record_recovery_http_service.example.json"

die() { echo "[ERROR] $*" >&2; exit 1; }
log() { echo "[INFO] $*"; }

[[ -f "$MANIFEST" ]] || die "missing defense demo manifest: $MANIFEST; run scripts/prepare_defense_demo.py first"
[[ -f "$ENV_FILE" ]] || die "missing env file: $ENV_FILE"

# shellcheck disable=SC1090
source "$ENV_FILE"

mkdir -p "$PID_DIR" "$LOG_DIR" "$READY_DIR"

if [[ -n "${DEFENSE_DEMO_REQUIRE_AUTH:-}" ]]; then
  REQUIRE_AUTH=1
else
  REQUIRE_AUTH=0
fi

json_field() {
  python3 "$REPO_ROOT/scripts/runtime_service_helpers.py" read-json-field --json-file "$MANIFEST" --field "$1"
}

PORT_FILE="$DEMO_ROOT/ports.json"
if [[ ! -f "$PORT_FILE" ]]; then
  cat >"$PORT_FILE" <<'JSON'
{
  "metadata": 18090,
  "query": 18091,
  "audit": 18092,
  "health": 18093,
  "dashboard": 18094,
  "business_metadata": 18190,
  "privacy_dashboard": 18194
}
JSON
fi

port_field() {
  python3 "$REPO_ROOT/scripts/runtime_service_helpers.py" read-json-field --json-file "$PORT_FILE" --field "$1"
}

MAIN_RUN="$(json_field artifacts.main_completed_run)"
FIXTURE_RUN="$(json_field artifacts.operator_fixture_run)"
PLATFORM_DB="$(json_field artifacts.platform_metadata_db)"
BUSINESS_DB="$(json_field artifacts.business_access_db)"
PRIVACY_DB="$(json_field artifacts.privacy_budget_metadata_db)"
PRIVACY_STORE="$(json_field artifacts.privacy_budget_store)"
PRIVACY_QUEUE="$(json_field artifacts.privacy_budget_approval_queue)"
PRIVACY_DECISIONS="$(json_field artifacts.privacy_budget_approval_decisions)"
IDENTITY_CFG="$(json_field artifacts.identity_token_config)"

METADATA_PORT="$(port_field metadata)"
QUERY_PORT="$(port_field query)"
AUDIT_PORT="$(port_field audit)"
HEALTH_PORT="$(port_field health)"
DASHBOARD_PORT="$(port_field dashboard)"
BUSINESS_METADATA_PORT="$(port_field business_metadata)"
PRIVACY_DASHBOARD_PORT="$(port_field privacy_dashboard)"

AUTH_METADATA_ARGS=()
AUTH_QUERY_ARGS=()
AUTH_AUDIT_ARGS=()
AUTH_HEALTH_ARGS=()
AUTH_DASHBOARD_ARGS=()
AUTH_BUSINESS_ARGS=()
AUTH_PRIVACY_DASHBOARD_ARGS=()
AUTH_MODE_LABEL="open local demo mode"

if [[ "$REQUIRE_AUTH" -eq 1 ]]; then
  AUTH_METADATA_ARGS=(--identity-token-config "$IDENTITY_CFG")
  AUTH_QUERY_ARGS=(--identity-token-config "$IDENTITY_CFG" --metadata-db-path "$PLATFORM_DB")
  AUTH_AUDIT_ARGS=(--identity-token-config "$IDENTITY_CFG" --metadata-db-path "$PLATFORM_DB")
  AUTH_HEALTH_ARGS=(--identity-token-config "$IDENTITY_CFG" --metadata-db-path "$PLATFORM_DB")
  AUTH_DASHBOARD_ARGS=(--identity-token-config "$IDENTITY_CFG")
  AUTH_BUSINESS_ARGS=(--identity-token-config "$IDENTITY_CFG")
  AUTH_PRIVACY_DASHBOARD_ARGS=(--identity-token-config "$IDENTITY_CFG")
  AUTH_MODE_LABEL="identity-token enabled"
fi

start_service() {
  local name="$1"
  shift
  local pid_file="$PID_DIR/$name.pid"
  local ready_file="$READY_DIR/$name.ready"
  local log_file="$LOG_DIR/$name.log"

  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      log "$name already running (pid=$pid)"
      return 0
    fi
    rm -f "$pid_file" "$ready_file"
  fi

  log "starting $name"
  nohup "$@" >"$log_file" 2>&1 &
  local bg_pid=$!
  echo "$bg_pid" >"$pid_file"
}

wait_http() {
  local url="$1"
  local ok_field="${2:-ok}"
  local ok_value="${3:-true}"
  python3 "$REPO_ROOT/scripts/runtime_service_helpers.py" wait-json-health --url "$url" --timeout-sec 20 --ok-field "$ok_field" --ok-value "$ok_value" >/dev/null
}

start_service metadata \
  python3 "$REPO_ROOT/scripts/serve_metadata_api.py" \
  --db-path "$PLATFORM_DB" \
  --bind-host 127.0.0.1 \
  --port "$METADATA_PORT" \
  "${AUTH_METADATA_ARGS[@]}"

start_service query \
  python3 "$REPO_ROOT/scripts/serve_query_workflow_api.py" \
  --bind-host 127.0.0.1 \
  --port "$QUERY_PORT" \
  --allow-execute \
  "${AUTH_QUERY_ARGS[@]}"

start_service audit \
  python3 "$REPO_ROOT/scripts/serve_audit_query_api.py" \
  --out-base "$MAIN_RUN" \
  --bind-host 127.0.0.1 \
  --port "$AUDIT_PORT" \
  "${AUTH_AUDIT_ARGS[@]}"

start_service health \
  python3 "$REPO_ROOT/scripts/serve_platform_health_api.py" \
  --bind-host 127.0.0.1 \
  --port "$HEALTH_PORT" \
  "${AUTH_HEALTH_ARGS[@]}"

log "starting recovery service"
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" stop --config "$RECOVERY_CONFIG" >/dev/null 2>&1 || true
python3 "$REPO_ROOT/scripts/manage_record_recovery_service.py" start --config "$RECOVERY_CONFIG" >"$LOG_DIR/recovery.log" 2>&1

start_service dashboard \
  python3 "$REPO_ROOT/scripts/serve_operator_dashboard.py" \
  --out-base "$MAIN_RUN" \
  --history-root "$DEMO_ROOT/runs" \
  --metadata-db-path "$PLATFORM_DB" \
  --max-concurrent-jobs-per-tenant 3 \
  --privacy-budget-store "$PRIVACY_STORE" \
  --privacy-budget-approval-queue "$PRIVACY_QUEUE" \
  --privacy-budget-approval-decisions "$PRIVACY_DECISIONS" \
  --console-dist "$REPO_ROOT/console/dist" \
  --metadata-api-base-url "http://127.0.0.1:${METADATA_PORT}" \
  --query-api-base-url "http://127.0.0.1:${QUERY_PORT}" \
  --audit-api-base-url "http://127.0.0.1:${AUDIT_PORT}" \
  --health-api-base-url "http://127.0.0.1:${HEALTH_PORT}" \
  "${AUTH_DASHBOARD_ARGS[@]}" \
  --bind-host 127.0.0.1 \
  --port "$DASHBOARD_PORT"

start_service business_metadata \
  python3 "$REPO_ROOT/scripts/serve_metadata_api.py" \
  --db-path "$BUSINESS_DB" \
  --bind-host 127.0.0.1 \
  --port "$BUSINESS_METADATA_PORT" \
  --business-access-policy "$REPO_ROOT/config/business_access_policy.ecommerce.example.json" \
  "${AUTH_BUSINESS_ARGS[@]}"

start_service privacy_dashboard \
  python3 "$REPO_ROOT/scripts/serve_operator_dashboard.py" \
  --out-base "$FIXTURE_RUN" \
  --history-root "$DEMO_ROOT/runs" \
  --metadata-db-path "$PRIVACY_DB" \
  --metadata-api-base-url "http://127.0.0.1:${METADATA_PORT}" \
  --query-api-base-url "http://127.0.0.1:${QUERY_PORT}" \
  --audit-api-base-url "http://127.0.0.1:${AUDIT_PORT}" \
  --health-api-base-url "http://127.0.0.1:${HEALTH_PORT}" \
  --privacy-budget-store "$PRIVACY_STORE" \
  --privacy-budget-approval-queue "$PRIVACY_QUEUE" \
  --privacy-budget-approval-decisions "$PRIVACY_DECISIONS" \
  --console-dist "$REPO_ROOT/console/dist" \
  "${AUTH_PRIVACY_DASHBOARD_ARGS[@]}" \
  --bind-host 127.0.0.1 \
  --port "$PRIVACY_DASHBOARD_PORT"

wait_http "http://127.0.0.1:${METADATA_PORT}/healthz"
wait_http "http://127.0.0.1:${QUERY_PORT}/healthz"
wait_http "http://127.0.0.1:${AUDIT_PORT}/healthz"
wait_http "http://127.0.0.1:${HEALTH_PORT}/healthz"
wait_http "http://127.0.0.1:${DASHBOARD_PORT}/healthz" status ok
wait_http "http://127.0.0.1:${BUSINESS_METADATA_PORT}/healthz"
wait_http "http://127.0.0.1:${PRIVACY_DASHBOARD_PORT}/healthz" status ok

cat <<EOF
[OK] Defense demo is ready

Main console:
  http://127.0.0.1:${DASHBOARD_PORT}/home

Privacy-budget console:
  http://127.0.0.1:${PRIVACY_DASHBOARD_PORT}/privacy-budget-approvals

Business-access metadata sidecar:
  http://127.0.0.1:${BUSINESS_METADATA_PORT}

Settings for main console:
  Metadata      /proxy/metadata
  Query         /proxy/query
  Audit         /proxy/audit
  Health        /proxy/health
  Recovery      http://127.0.0.1:18081

Settings override for /business-access:
  Metadata      http://127.0.0.1:${BUSINESS_METADATA_PORT}

Auth mode:
  ${AUTH_MODE_LABEL}
EOF
