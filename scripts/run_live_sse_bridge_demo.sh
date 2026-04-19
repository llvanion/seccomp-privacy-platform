#!/usr/bin/env bash
set -euo pipefail

die() { echo "[ERROR] $*" >&2; exit 1; }
log() { echo "[INFO] $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SSE_DIR="${SSE_DIR:-$REPO_ROOT/sse}"
SSE_PY="${SSE_PY:-$SSE_DIR/.venv/bin/python}"
PIPELINE_SH="${PIPELINE_SH:-$REPO_ROOT/scripts/run_sse_bridge_pipeline.sh}"
EXPORT_POLICY="${EXPORT_POLICY:-$REPO_ROOT/sse/config/export_policy.example.json}"

RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
DEFAULT_RUN_ROOT="$REPO_ROOT/tmp/live_sse_bridge_demo"
AUTHZ_DEFAULT_RUN_ROOT="/tmp/seccomp_live_sse_bridge_demo"
RUN_ROOT="${RUN_ROOT:-$DEFAULT_RUN_ROOT}"
STATE_BASE="${STATE_BASE:-}"
OUT_BASE="${OUT_BASE:-}"
SSE_HOME="${SSE_HOME:-}"
WORK_DIR="${WORK_DIR:-}"
SERVICE_NAME="${SERVICE_NAME:-}"
JOB_ID="${JOB_ID:-}"
CALLER="${CALLER:-auto_demo}"
TOKEN_SCOPE="${TOKEN_SCOPE:-auto-demo-scope}"
TOKEN_SECRET="${TOKEN_SECRET:-local-dev-secret}"
TOKEN_SECRET_KEY_NAME="${TOKEN_SECRET_KEY_NAME:-}"
KEYRING="${KEYRING:-}"
EXTERNAL_KMS_CONFIG="${EXTERNAL_KMS_CONFIG:-}"
EXTERNAL_KMS_MODE="${EXTERNAL_KMS_MODE:-auto}"
K_THRESHOLD="${K_THRESHOLD:-1}"
RATE_N="${RATE_N:-5}"
SSE_EXPORT_HANDOFF_MODE="${SSE_EXPORT_HANDOFF_MODE:-file}"
RECORD_RECOVERY_SERVICE_MODE="${RECORD_RECOVERY_SERVICE_MODE:-auto}"
RECORD_RECOVERY_SERVICE_CONFIG="${RECORD_RECOVERY_SERVICE_CONFIG:-}"

SERVER_LOG="${SERVER_LOG:-}"
SERVER_SOURCE_NORMALIZED=""
CLIENT_SOURCE_NORMALIZED=""
SSE_DB_PATH=""
SERVER_RECORD_STORE_PATH=""
CLIENT_RECORD_STORE_PATH=""
MANIFEST_PATH=""
PIPELINE_RECOVERY_PID_FILE=""
PIPELINE_RECOVERY_READY_FILE=""

RECORD_STORE_KEY_ENV="${RECORD_STORE_KEY_ENV:-SSE_RECORD_STORE_PASSPHRASE}"
RECORD_RECOVERY_AUTHZ_CONFIG="${RECORD_RECOVERY_AUTHZ_CONFIG:-}"
KEEP_SERVER=0
BOOTSTRAP_ONLY=0
SERVER_STARTED_BY_SCRIPT=0
SERVER_PID=""
RUN_ROOT_EXPLICIT=0
STATE_BASE_EXPLICIT=0
OUT_BASE_EXPLICIT=0

usage() {
  cat <<EOF
Usage:
  $0 [options]

Options:
  --run-id <id>                        override generated run id
  --run-root <dir>                     default: $REPO_ROOT/tmp/live_sse_bridge_demo
  --state-base <dir>                   explicit SSE/client state directory
  --out-base <dir>                     explicit pipeline output directory
  --service-name <name>                SSE service name for this run
  --job-id <id>                        pipeline job id
  --caller <id>                        default: auto_demo
  --token-scope <scope>                default: auto-demo-scope
  --token-secret <secret>              default: local-dev-secret
  --token-secret-key-name <name>       optional key-agent key name for bridge token resolution
  --keyring <path>                     required with --token-secret-key-name
  --external-kms-config <path>         external KMS config used with --token-secret-key-name
  --external-kms-mode <m>              auto|manual, default: auto
  --k <int>                            release threshold, default: 1
  --n <int>                            release rate limit, default: 5
  --record-recovery-service-mode <m>   auto|manual|subprocess, default: auto
  --record-recovery-service-config <p> optional shared recovery-service config for pipeline/manual service mode
  --record-recovery-authz-config <p>   optional authz policy for auto-started recovery service
  --sse-export-handoff-mode <m>        file|fifo, default: file
  --bootstrap-only                     prepare live SSE state but do not run pipeline
  --keep-server                        do not stop the SSE server on exit when this script started it
  -h|--help                            show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id) RUN_ID="$2"; shift 2 ;;
    --run-root) RUN_ROOT="$2"; RUN_ROOT_EXPLICIT=1; shift 2 ;;
    --state-base) STATE_BASE="$2"; STATE_BASE_EXPLICIT=1; shift 2 ;;
    --out-base) OUT_BASE="$2"; OUT_BASE_EXPLICIT=1; shift 2 ;;
    --service-name) SERVICE_NAME="$2"; shift 2 ;;
    --job-id) JOB_ID="$2"; shift 2 ;;
    --caller) CALLER="$2"; shift 2 ;;
    --token-scope) TOKEN_SCOPE="$2"; shift 2 ;;
    --token-secret) TOKEN_SECRET="$2"; shift 2 ;;
    --token-secret-key-name) TOKEN_SECRET_KEY_NAME="$2"; shift 2 ;;
    --keyring) KEYRING="$2"; shift 2 ;;
    --external-kms-config) EXTERNAL_KMS_CONFIG="$2"; shift 2 ;;
    --external-kms-mode) EXTERNAL_KMS_MODE="$2"; shift 2 ;;
    --k) K_THRESHOLD="$2"; shift 2 ;;
    --n) RATE_N="$2"; shift 2 ;;
    --record-recovery-service-mode) RECORD_RECOVERY_SERVICE_MODE="$2"; shift 2 ;;
    --record-recovery-service-config) RECORD_RECOVERY_SERVICE_CONFIG="$2"; shift 2 ;;
    --record-recovery-authz-config) RECORD_RECOVERY_AUTHZ_CONFIG="$2"; shift 2 ;;
    --sse-export-handoff-mode) SSE_EXPORT_HANDOFF_MODE="$2"; shift 2 ;;
    --bootstrap-only) BOOTSTRAP_ONLY=1; shift ;;
    --keep-server) KEEP_SERVER=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown arg: $1" ;;
  esac
done

[[ -x "$SSE_PY" ]] || die "missing SSE python: $SSE_PY"
[[ -f "$PIPELINE_SH" ]] || die "missing pipeline script: $PIPELINE_SH"
[[ -f "$EXPORT_POLICY" ]] || die "missing export policy: $EXPORT_POLICY"
[[ -z "$RECORD_RECOVERY_AUTHZ_CONFIG" || -f "$RECORD_RECOVERY_AUTHZ_CONFIG" ]] || die "missing record recovery authz config: $RECORD_RECOVERY_AUTHZ_CONFIG"
[[ -z "$RECORD_RECOVERY_SERVICE_CONFIG" || -f "$RECORD_RECOVERY_SERVICE_CONFIG" ]] || die "missing record recovery service config: $RECORD_RECOVERY_SERVICE_CONFIG"
[[ -z "$TOKEN_SECRET_KEY_NAME" || -n "$KEYRING" || -n "$EXTERNAL_KMS_CONFIG" ]] || die "--token-secret-key-name requires --keyring or --external-kms-config"
[[ -z "$KEYRING" || -z "$EXTERNAL_KMS_CONFIG" ]] || die "use only one of --keyring or --external-kms-config"
[[ -z "$KEYRING" || -f "$KEYRING" ]] || die "missing keyring: $KEYRING"
[[ -z "$EXTERNAL_KMS_CONFIG" || -f "$EXTERNAL_KMS_CONFIG" ]] || die "missing external KMS config: $EXTERNAL_KMS_CONFIG"
[[ "$SSE_EXPORT_HANDOFF_MODE" == "file" || "$SSE_EXPORT_HANDOFF_MODE" == "fifo" ]] || die "--sse-export-handoff-mode must be file or fifo"
[[ "$RECORD_RECOVERY_SERVICE_MODE" == "auto" || "$RECORD_RECOVERY_SERVICE_MODE" == "manual" || "$RECORD_RECOVERY_SERVICE_MODE" == "subprocess" ]] || die "--record-recovery-service-mode must be auto, manual, or subprocess"
[[ "$EXTERNAL_KMS_MODE" == "auto" || "$EXTERNAL_KMS_MODE" == "manual" ]] || die "--external-kms-mode must be auto or manual"

if [[ -n "$RECORD_RECOVERY_AUTHZ_CONFIG" && "$RUN_ROOT_EXPLICIT" == "0" && "$STATE_BASE_EXPLICIT" == "0" && "$OUT_BASE_EXPLICIT" == "0" && "$RUN_ROOT" == "$DEFAULT_RUN_ROOT" ]]; then
  RUN_ROOT="$AUTHZ_DEFAULT_RUN_ROOT"
fi

STATE_BASE="${STATE_BASE:-$RUN_ROOT/state-$RUN_ID}"
OUT_BASE="${OUT_BASE:-$RUN_ROOT/run-$RUN_ID}"
SSE_HOME="${SSE_HOME:-$STATE_BASE/home}"
WORK_DIR="${WORK_DIR:-$STATE_BASE/work}"
SERVICE_NAME="${SERVICE_NAME:-bridge_sse_demo_$RUN_ID}"
JOB_ID="${JOB_ID:-live_sse_demo_$RUN_ID}"
SERVER_LOG="${SERVER_LOG:-$STATE_BASE/sse_server.log}"
SERVER_SOURCE_NORMALIZED="$WORK_DIR/bridge_server_records.norm.jsonl"
CLIENT_SOURCE_NORMALIZED="$WORK_DIR/bridge_client_records.norm.jsonl"
SSE_DB_PATH="$WORK_DIR/bridge_demo_db.json"
SERVER_RECORD_STORE_PATH="$WORK_DIR/server_records.enc.jsonl"
CLIENT_RECORD_STORE_PATH="$WORK_DIR/client_records.enc.jsonl"
MANIFEST_PATH="$OUT_BASE/live_demo_manifest.json"
PIPELINE_RECOVERY_PID_FILE="$OUT_BASE/sse_exports/record_recovery_service.pid"
PIPELINE_RECOVERY_READY_FILE="$OUT_BASE/sse_exports/record_recovery_service.ready"

mkdir -p "$STATE_BASE" "$WORK_DIR" "$OUT_BASE"
ORIGINAL_HOME="${HOME:-}"
export HOME="$SSE_HOME"
mkdir -p "$HOME"
if [[ -n "$ORIGINAL_HOME" ]]; then
  export RUSTUP_HOME="${RUSTUP_HOME:-$ORIGINAL_HOME/.rustup}"
  export CARGO_HOME="${CARGO_HOME:-$ORIGINAL_HOME/.cargo}"
fi

if [[ -z "${!RECORD_STORE_KEY_ENV:-}" ]]; then
  printf -v "$RECORD_STORE_KEY_ENV" '%s' "local-record-store-passphrase"
  export "$RECORD_STORE_KEY_ENV"
fi

ensure_keyring_demo_secret() {
  [[ -n "$TOKEN_SECRET_KEY_NAME" ]] || return 0
  [[ -n "$KEYRING" ]] || return 0
  local secret_env
  secret_env="$(
    python3 -c 'import json,sys; data=json.load(open(sys.argv[1], "r", encoding="utf-8")); key=data["keys"][sys.argv[2]]; version=key["active_version"]; ref=key["versions"][version]["secret_ref"]; 
if ref.get("kind") != "env": raise SystemExit("unsupported secret_ref kind for live demo");
print(ref["name"])' \
      "$KEYRING" "$TOKEN_SECRET_KEY_NAME"
  )"
  if [[ -z "${!secret_env:-}" ]]; then
    printf -v "$secret_env" '%s' "$TOKEN_SECRET"
    export "$secret_env"
  fi
}

ensure_keyring_demo_secret

ensure_external_kms_demo_secret() {
  [[ -n "$TOKEN_SECRET_KEY_NAME" ]] || return 0
  [[ -n "$EXTERNAL_KMS_CONFIG" ]] || return 0
  [[ "$EXTERNAL_KMS_MODE" == "auto" ]] || return 0
  local secret_env
  secret_env="$(
    python3 -c 'import json,os,sys; cfg_path=sys.argv[1]; key_name=sys.argv[2]; cfg=json.load(open(cfg_path, "r", encoding="utf-8")); auto=cfg.get("auto_start") or {}; state=auto.get("state_file"); 
if not state: raise SystemExit(0)
if not os.path.isabs(state): state=os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(cfg_path)), state))
data=json.load(open(state, "r", encoding="utf-8")); key=data["keys"][key_name]; version=key["active_version"]; ref=key["versions"][version]["secret_ref"];
if ref.get("kind") != "env": raise SystemExit("unsupported secret_ref kind for live demo");
print(ref["name"])' \
      "$EXTERNAL_KMS_CONFIG" "$TOKEN_SECRET_KEY_NAME"
  )"
  if [[ -n "$secret_env" && -z "${!secret_env:-}" ]]; then
    printf -v "$secret_env" '%s' "$TOKEN_SECRET"
    export "$secret_env"
  fi
}

ensure_external_kms_demo_secret

port_ready() {
  python3 -c 'import socket,sys; s=socket.socket(); s.settimeout(0.2); rc=s.connect_ex(("127.0.0.1", 8001)); s.close(); sys.exit(0 if rc == 0 else 1)'
}

wait_for_port() {
  local attempts=0
  while [[ $attempts -lt 100 ]]; do
    if port_ready; then
      return 0
    fi
    sleep 0.1
    attempts=$((attempts + 1))
  done
  return 1
}

cleanup() {
  if [[ "$SERVER_STARTED_BY_SCRIPT" == "1" && "$KEEP_SERVER" == "0" && -n "$SERVER_PID" ]]; then
    if kill -0 "$SERVER_PID" 2>/dev/null; then
      kill "$SERVER_PID" 2>/dev/null || true
      wait "$SERVER_PID" 2>/dev/null || true
    fi
  fi
}
trap cleanup EXIT

ensure_server() {
  if port_ready; then
    log "Reusing existing SSE server on ws://localhost:8001"
    return 0
  fi

  log "Starting SSE server"
  (
    cd "$SSE_DIR"
    "$SSE_PY" run_server.py start
  ) >"$SERVER_LOG" 2>&1 &
  SERVER_PID=$!
  SERVER_STARTED_BY_SCRIPT=1
  wait_for_port || die "SSE server did not become ready; see $SERVER_LOG"
  log "SSE server is ready; log: $SERVER_LOG"
}

prepare_demo_inputs() {
  log "Preparing normalized demo records and SSE keyword database"
  python3 - "$REPO_ROOT/sse/examples/bridge_server_records.jsonl" "$REPO_ROOT/sse/examples/bridge_client_records.jsonl" "$SERVER_SOURCE_NORMALIZED" "$CLIENT_SOURCE_NORMALIZED" "$SSE_DB_PATH" <<'PY'
import json
import sys
from pathlib import Path

server_in = Path(sys.argv[1])
client_in = Path(sys.argv[2])
server_out = Path(sys.argv[3])
client_out = Path(sys.argv[4])
db_out = Path(sys.argv[5])

def normalize_record(record):
    email = str(record["email"]).strip().lower()
    normalized = dict(record)
    normalized["email"] = email
    normalized["email_hex"] = email.encode("utf-8").hex()
    return normalized

campaign_index = {}
for src, dst in ((server_in, server_out), (client_in, client_out)):
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("r", encoding="utf-8") as in_f, dst.open("w", encoding="utf-8") as out_f:
        for line in in_f:
            raw = line.strip()
            if not raw:
                continue
            record = normalize_record(json.loads(raw))
            campaign = str(record.get("campaign", "")).strip()
            email_hex = record["email_hex"]
            if campaign:
                campaign_index.setdefault(campaign, [])
                if email_hex not in campaign_index[campaign]:
                    campaign_index[campaign].append(email_hex)
            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")

with db_out.open("w", encoding="utf-8") as f:
    json.dump(campaign_index, f, ensure_ascii=False, sort_keys=True)
PY
}

bootstrap_sse_service() {
  local config_path="$STATE_BASE/cjj14_bridge_config"
  local mapping_path="$HOME/.sse/client/service_mapping.json"

  log "Bootstrapping live SSE service state"
  (
    cd "$SSE_DIR"
    "$SSE_PY" run_client.py generate-config --scheme CJJ14.PiBas --save-path "$config_path"
    "$SSE_PY" run_client.py create-service --config "$config_path" --sname "$SERVICE_NAME"
    "$SSE_PY" run_client.py generate-key --sname "$SERVICE_NAME"
    "$SSE_PY" run_client.py upload-config --sname "$SERVICE_NAME"
    "$SSE_PY" run_client.py encrypt-database --sname "$SERVICE_NAME" --db-path "$SSE_DB_PATH"
    "$SSE_PY" run_client.py upload-encrypted-database --sname "$SERVICE_NAME"
    "$SSE_PY" run_client.py create-encrypted-record-store \
      --source-path "$SERVER_SOURCE_NORMALIZED" \
      --out-path "$SERVER_RECORD_STORE_PATH" \
      --source-format jsonl \
      --record-id-field email_hex \
      --key-env "$RECORD_STORE_KEY_ENV"
    "$SSE_PY" run_client.py create-encrypted-record-store \
      --source-path "$CLIENT_SOURCE_NORMALIZED" \
      --out-path "$CLIENT_RECORD_STORE_PATH" \
      --source-format jsonl \
      --record-id-field email_hex \
      --key-env "$RECORD_STORE_KEY_ENV"
  )

  [[ -f "$config_path" ]] || die "missing generated SSE config: $config_path"
  [[ -f "$mapping_path" ]] || die "missing service mapping after bootstrap: $mapping_path"
  [[ -f "$SERVER_RECORD_STORE_PATH" ]] || die "missing server record store: $SERVER_RECORD_STORE_PATH"
  [[ -f "$CLIENT_RECORD_STORE_PATH" ]] || die "missing client record store: $CLIENT_RECORD_STORE_PATH"
}

write_manifest() {
  local public_report_path="$OUT_BASE/a_psi_run/public_report.json"
  local export_audit_path="$OUT_BASE/sse_exports/export_audit.jsonl"
  local recovery_audit_path="$OUT_BASE/sse_exports/record_recovery_service_audit.jsonl"
  local recovery_health_path="$OUT_BASE/sse_exports/record_recovery_service_health.json"
  local recovery_runtime_config_path="$OUT_BASE/sse_exports/record_recovery_service_config.json"
  local recovery_log_path="$OUT_BASE/sse_exports/record_recovery_service.log"
  local bridge_meta_path="$OUT_BASE/bridge_job/job_meta.json"
  local bridge_audit_path="$OUT_BASE/bridge_job/bridge_audit.jsonl"
  local audit_chain_path="$OUT_BASE/audit_chain.json"
  local audit_seal_path="$OUT_BASE/audit_chain.seal.json"
  python3 - "$MANIFEST_PATH" "$STATE_BASE" "$OUT_BASE" "$JOB_ID" "$SERVICE_NAME" "$public_report_path" "$export_audit_path" "$recovery_audit_path" "$recovery_health_path" "$recovery_runtime_config_path" "$recovery_log_path" "$bridge_meta_path" "$bridge_audit_path" "$audit_chain_path" "$audit_seal_path" "$SERVER_LOG" "$SERVER_SOURCE_NORMALIZED" "$CLIENT_SOURCE_NORMALIZED" "$SSE_DB_PATH" "$SERVER_RECORD_STORE_PATH" "$CLIENT_RECORD_STORE_PATH" "$PIPELINE_RECOVERY_PID_FILE" "$PIPELINE_RECOVERY_READY_FILE" "$RECORD_STORE_KEY_ENV" "$RECORD_RECOVERY_SERVICE_MODE" "$SSE_EXPORT_HANDOFF_MODE" "$RECORD_RECOVERY_SERVICE_CONFIG" "$RECORD_RECOVERY_AUTHZ_CONFIG" "$TOKEN_SECRET_KEY_NAME" "$KEYRING" "$EXTERNAL_KMS_CONFIG" "$EXTERNAL_KMS_MODE" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
public_report_path = Path(sys.argv[6])
runtime_config_path = Path(sys.argv[10])
public_report = {}
if public_report_path.is_file():
    public_report = json.loads(public_report_path.read_text(encoding="utf-8"))
details = public_report.get("details", {}) if isinstance(public_report.get("details"), dict) else {}
runtime_config = {}
if runtime_config_path.is_file():
    runtime_config = json.loads(runtime_config_path.read_text(encoding="utf-8"))
lifecycle = runtime_config.get("lifecycle", {}) if isinstance(runtime_config.get("lifecycle"), dict) else {}

manifest = {
    "run_type": "live_sse_bridge_demo",
    "state_base": str(Path(sys.argv[2]).resolve()),
    "out_base": str(Path(sys.argv[3]).resolve()),
    "job_id": sys.argv[4],
    "service_name": sys.argv[5],
    "runtime": {
        "record_store_key_env": sys.argv[24],
        "record_recovery_service_mode": sys.argv[25],
        "sse_export_handoff_mode": sys.argv[26],
        "record_recovery_service_config": sys.argv[27] or None,
        "record_recovery_authz_config": sys.argv[28] or None,
        "token_secret_key_name": sys.argv[29] or None,
        "keyring": sys.argv[30] or None,
        "external_kms_config": sys.argv[31] or None,
        "external_kms_mode": sys.argv[32] or None,
    },
    "state_artifacts": {
        "sse_server_log": str(Path(sys.argv[16]).resolve()),
        "server_source_normalized": str(Path(sys.argv[17]).resolve()),
        "client_source_normalized": str(Path(sys.argv[18]).resolve()),
        "sse_keyword_db": str(Path(sys.argv[19]).resolve()),
        "server_record_store": str(Path(sys.argv[20]).resolve()),
        "client_record_store": str(Path(sys.argv[21]).resolve()),
    },
    "outputs": {
        "public_report": str(public_report_path.resolve()),
        "export_audit": str(Path(sys.argv[7]).resolve()),
        "record_recovery_service_audit": str(Path(sys.argv[8]).resolve()),
        "record_recovery_service_health": str(Path(sys.argv[9]).resolve()),
        "record_recovery_service_runtime_config": str(runtime_config_path.resolve()),
        "record_recovery_service_log": str(Path(sys.argv[11]).resolve()),
        "bridge_job_meta": str(Path(sys.argv[12]).resolve()),
        "bridge_audit": str(Path(sys.argv[13]).resolve()),
        "audit_chain": str(Path(sys.argv[14]).resolve()),
        "audit_seal": str(Path(sys.argv[15]).resolve()),
        "record_recovery_service_pid_file": str(Path(lifecycle.get("pid_file", sys.argv[22])).resolve()),
        "record_recovery_service_ready_file": str(Path(lifecycle.get("ready_file", sys.argv[23])).resolve()),
    },
    "result": {
        "intersection_size": public_report.get("intersection_size", details.get("intersection_size")),
        "intersection_sum": public_report.get("intersection_sum", details.get("intersection_sum")),
        "released": public_report.get("released"),
        "reason_code": public_report.get("reason_code"),
    },
}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

verify_demo_result() {
  local public_report_path="$OUT_BASE/a_psi_run/public_report.json"
  [[ -f "$public_report_path" ]] || die "missing public report: $public_report_path"
  python3 - "$public_report_path" <<'PY'
import json
import sys
from pathlib import Path

public_report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
details = public_report.get("details", {}) if isinstance(public_report.get("details"), dict) else {}
size = public_report.get("intersection_size", details.get("intersection_size"))
total = public_report.get("intersection_sum", details.get("intersection_sum"))
if size != 2 or total != 425:
    raise SystemExit(f"unexpected live demo result: intersection_size={size}, intersection_sum={total}")
PY
}

run_pipeline() {
  log "Running live SSE-backed pipeline"
  local pipeline_cmd=(
    bash "$PIPELINE_SH"
    --server-record-store-path "$SERVER_RECORD_STORE_PATH" \
    --client-record-store-path "$CLIENT_RECORD_STORE_PATH" \
    --server-record-store-key-env "$RECORD_STORE_KEY_ENV" \
    --client-record-store-key-env "$RECORD_STORE_KEY_ENV" \
    --server-join-key-field email \
    --client-join-key-field email \
    --client-value-field amount \
    --server-normalizer email \
    --client-normalizer email \
    --client-value-mode raw-int \
    --server-sse-keyword demo \
    --client-sse-keyword demo \
    --server-record-id-field email_hex \
    --client-record-id-field email_hex \
    --server-record-id-format hex \
    --client-record-id-format hex \
    --server-sse-sname "$SERVICE_NAME" \
    --client-sse-sname "$SERVICE_NAME" \
    --token-scope "$TOKEN_SCOPE" \
    --job-id "$JOB_ID" \
    --out-base "$OUT_BASE" \
    --caller "$CALLER" \
    --sse-export-policy-config "$EXPORT_POLICY" \
    --record-recovery-service-mode "$RECORD_RECOVERY_SERVICE_MODE" \
    --sse-export-handoff-mode "$SSE_EXPORT_HANDOFF_MODE" \
    --server-filter campaign=demo \
    --client-filter campaign=demo \
    --k "$K_THRESHOLD" \
    --n "$RATE_N"
  )
  if [[ -n "$TOKEN_SECRET_KEY_NAME" ]]; then
    pipeline_cmd+=(--token-secret-key-name "$TOKEN_SECRET_KEY_NAME")
    if [[ -n "$KEYRING" ]]; then
      pipeline_cmd+=(--keyring "$KEYRING")
    fi
    if [[ -n "$EXTERNAL_KMS_CONFIG" ]]; then
      pipeline_cmd+=(--external-kms-config "$EXTERNAL_KMS_CONFIG" --external-kms-mode "$EXTERNAL_KMS_MODE")
    fi
  else
    pipeline_cmd+=(--token-secret "$TOKEN_SECRET")
  fi
  if [[ -n "$RECORD_RECOVERY_AUTHZ_CONFIG" ]]; then
    pipeline_cmd+=(--record-recovery-authz-config "$RECORD_RECOVERY_AUTHZ_CONFIG")
  fi
  if [[ -n "$RECORD_RECOVERY_SERVICE_CONFIG" ]]; then
    pipeline_cmd+=(--record-recovery-service-config "$RECORD_RECOVERY_SERVICE_CONFIG")
  fi
  "${pipeline_cmd[@]}"
}

ensure_server
prepare_demo_inputs
bootstrap_sse_service

if [[ "$BOOTSTRAP_ONLY" == "1" ]]; then
  log "Bootstrap completed without running the pipeline"
  log "  state base: $STATE_BASE"
  log "  service name: $SERVICE_NAME"
  exit 0
fi

run_pipeline
verify_demo_result
write_manifest

log "Live SSE-backed demo passed"
log "  intersection_size=2"
log "  intersection_sum=425"
log "  output base: $OUT_BASE"
log "  manifest: $MANIFEST_PATH"
