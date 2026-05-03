#!/usr/bin/env bash
# Replay the live SSE-backed demo against a pre-started external record-recovery
# service and assert the manual service boundary still matches the documented
# runtime/health/mainline contracts.
#
# Usage:
#   bash scripts/verify_record_recovery_manual_service_replay.sh [--keep-run-root]
#
# Options:
#   --keep-run-root  Do not delete the temporary run root after a successful run.
set -euo pipefail

die() { echo "[ERROR] $*" >&2; exit 1; }
log() { echo "[INFO] $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

VALIDATOR="$REPO_ROOT/scripts/validate_json_contract.py"
RUNTIME_SERVICE_HELPERS="$REPO_ROOT/scripts/runtime_service_helpers.py"
BUILD_RUNTIME_CONFIGS="$REPO_ROOT/scripts/build_runtime_contract_smoke_configs.py"
MANAGE_RECORD_RECOVERY_SERVICE="$REPO_ROOT/scripts/manage_record_recovery_service.py"
REQUEST_RECORD_RECOVERY_SERVICE="$REPO_ROOT/scripts/request_record_recovery_service.py"
RUN_LIVE_DEMO="$REPO_ROOT/scripts/run_live_sse_bridge_demo.sh"

KEEP_RUN_ROOT=0
for arg in "$@"; do
  case "$arg" in
    --keep-run-root) KEEP_RUN_ROOT=1 ;;
    *) die "unknown argument: $arg" ;;
  esac
done

[[ -f "$VALIDATOR" ]] || die "missing validator: $VALIDATOR"
[[ -f "$RUNTIME_SERVICE_HELPERS" ]] || die "missing runtime helper: $RUNTIME_SERVICE_HELPERS"
[[ -f "$BUILD_RUNTIME_CONFIGS" ]] || die "missing config builder: $BUILD_RUNTIME_CONFIGS"
[[ -f "$MANAGE_RECORD_RECOVERY_SERVICE" ]] || die "missing record recovery manager: $MANAGE_RECORD_RECOVERY_SERVICE"
[[ -f "$REQUEST_RECORD_RECOVERY_SERVICE" ]] || die "missing record recovery requester: $REQUEST_RECORD_RECOVERY_SERVICE"
[[ -f "$RUN_LIVE_DEMO" ]] || die "missing live demo wrapper: $RUN_LIVE_DEMO"

RUN_ROOT="$(mktemp -d /tmp/seccomp_manual_rr_replay.XXXXXX)"
RUN_ID="manual_rr_replay"
CONFIG_PATH="$RUN_ROOT/record_recovery_http_service_config.json"
START_JSON="$RUN_ROOT/record_recovery_service_start.json"
STATUS_JSON="$RUN_ROOT/record_recovery_service_status.json"
HEALTH_JSON="$RUN_ROOT/record_recovery_service_health.json"
STOP_JSON="$RUN_ROOT/record_recovery_service_stop.json"
OUT_BASE="$RUN_ROOT/run-$RUN_ID"
SERVICE_STARTED=0

cleanup() {
  if [[ "$SERVICE_STARTED" == "1" ]]; then
    if [[ -f "$CONFIG_PATH" ]]; then
      python3 "$MANAGE_RECORD_RECOVERY_SERVICE" stop \
        --config "$CONFIG_PATH" \
        > "$STOP_JSON" 2>/dev/null || true
    fi
  fi
  if [[ "$KEEP_RUN_ROOT" -eq 0 ]]; then
    rm -rf "$RUN_ROOT"
  else
    echo "[info] run root preserved at: $RUN_ROOT"
  fi
}
trap cleanup EXIT

export SSE_RECORD_RECOVERY_TOKEN="${SSE_RECORD_RECOVERY_TOKEN:-manual-recovery-token}"
export SSE_RECORD_STORE_PASSPHRASE="${SSE_RECORD_STORE_PASSPHRASE:-local-record-store-passphrase}"

HTTP_PORT="$(python3 "$RUNTIME_SERVICE_HELPERS" available-port)"
python3 "$BUILD_RUNTIME_CONFIGS" \
  record-recovery-http \
  --out-config "$CONFIG_PATH" \
  --tmp-dir "$RUN_ROOT" \
  --port "$HTTP_PORT" \
  --authz-config "$REPO_ROOT/sse/config/export_policy.example.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_service_config.schema.json" \
  --json "$CONFIG_PATH"

log "Starting manual record recovery service"
python3 "$MANAGE_RECORD_RECOVERY_SERVICE" start \
  --config "$CONFIG_PATH" \
  > "$START_JSON"
SERVICE_STARTED=1
python3 "$MANAGE_RECORD_RECOVERY_SERVICE" status \
  --config "$CONFIG_PATH" \
  > "$STATUS_JSON"
python3 "$REQUEST_RECORD_RECOVERY_SERVICE" \
  --config "$CONFIG_PATH" \
  > "$HEALTH_JSON"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_service_health.schema.json" \
  --json "$HEALTH_JSON"

log "Running live demo through manual external recovery service"
bash "$RUN_LIVE_DEMO" \
  --run-id "$RUN_ID" \
  --run-root "$RUN_ROOT" \
  --record-recovery-service-mode manual \
  --record-recovery-service-config "$CONFIG_PATH"

python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_service_config.schema.json" \
  --json "$OUT_BASE/sse_exports/record_recovery_service_config.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_service_health.schema.json" \
  --json "$OUT_BASE/sse_exports/record_recovery_service_health.json"
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/mainline_contract_check.schema.json" \
  --json "$OUT_BASE/mainline_contract_check.json"

python3 - "$CONFIG_PATH" "$HEALTH_JSON" "$OUT_BASE" <<'PY'
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
health = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
out_base = Path(sys.argv[3])
runtime_config = json.loads((out_base / "sse_exports" / "record_recovery_service_config.json").read_text(encoding="utf-8"))
mainline = json.loads((out_base / "mainline_contract_check.json").read_text(encoding="utf-8"))
report = json.loads((out_base / "a_psi_run" / "public_report.json").read_text(encoding="utf-8"))
details = report.get("details", {}) if isinstance(report.get("details"), dict) else {}

def normalize_sum_cents(*values):
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
        if parsed == parsed.to_integral_value():
            return int(parsed)
        cents = parsed * Decimal("100")
        if cents == cents.to_integral_value():
            return int(cents)
    return None

size = report.get("intersection_size", details.get("intersection_size"))
total = normalize_sum_cents(
    report.get("intersection_sum_raw"),
    details.get("intersection_sum_raw"),
    report.get("intersection_sum_cents"),
    details.get("intersection_sum_cents"),
    report.get("intersection_sum"),
    details.get("intersection_sum"),
    report.get("intersection_sum_eur"),
    details.get("intersection_sum_eur"),
)
if size != 2 or total != 425:
    raise SystemExit(f"unexpected replay result: intersection_size={size}, intersection_sum_cents={total}")

if health.get("transport") != "http":
    raise SystemExit(f"unexpected health transport: {health.get('transport')}")
if runtime_config.get("transport") != "http":
    raise SystemExit(f"unexpected runtime transport: {runtime_config.get('transport')}")
for field in ("service_id", "tenant_id", "dataset_id", "endpoint_url", "auth_token_env"):
    expected = config.get(field)
    actual = runtime_config.get(field)
    if expected != actual:
        raise SystemExit(f"runtime config mismatch for {field}: expected={expected!r} actual={actual!r}")
    if field != "auth_token_env" and health.get(field) != expected:
        raise SystemExit(f"health mismatch for {field}: expected={expected!r} actual={health.get(field)!r}")

if mainline.get("status") != "ok":
    raise SystemExit(f"manual service replay mainline status is not ok: {mainline.get('status')}")
if mainline.get("findings"):
    raise SystemExit(f"manual service replay unexpectedly reported findings: {len(mainline.get('findings', []))}")

handoff = mainline.get("handoff_cleanup") or {}
for role_name in ("server", "client"):
    entry = handoff.get(role_name) or {}
    if entry.get("status") != "cleaned":
        raise SystemExit(f"{role_name} handoff cleanup mismatch: {entry.get('status')!r}")
    if entry.get("retention_reason") not in (None, ""):
        raise SystemExit(f"{role_name} handoff unexpectedly retained a reason: {entry.get('retention_reason')!r}")
PY

log "Stopping manual record recovery service"
python3 "$MANAGE_RECORD_RECOVERY_SERVICE" stop \
  --config "$CONFIG_PATH" \
  > "$STOP_JSON"
SERVICE_STARTED=0
python3 "$VALIDATOR" \
  --schema "$REPO_ROOT/schemas/record_recovery_service_log.schema.json" \
  --jsonl "$RUN_ROOT/record_recovery_service_http.log"
[[ ! -e "$RUN_ROOT/record_recovery_service_http.pid" ]] || die "record recovery pid file still exists after stop"
[[ ! -e "$RUN_ROOT/record_recovery_service_http.ready" ]] || die "record recovery ready file still exists after stop"

STARTED_PID="$(python3 "$RUNTIME_SERVICE_HELPERS" read-json-field --json-file "$START_JSON" --field started_pid)"
echo "[ok] manual recovery-service replay passed: intersection_size=2 intersection_sum=425 transport=http started_pid=$STARTED_PID out_base=$OUT_BASE"
