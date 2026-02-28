#!/usr/bin/env bash
set -euo pipefail

die() { echo "[ERROR] $*" >&2; exit 1; }
log() { echo "[INFO] $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PREP_PY="$REPO_ROOT/moduleA_psi/scripts/prep_inputs.py"
RUN_PJC_SH="$REPO_ROOT/moduleA_psi/scripts/run_pjc.sh"
POLICY_PY="$REPO_ROOT/moduleA_psi/scripts/policy_release.py"
RUNS_DIR="$REPO_ROOT/runs"

CRITEO_TSV=""
OUT_DIR=""
JOB_ID=""
START_TS=""
END_TS=""
VALUE_MODE="count"
BUCKET_FIELD=""
HMAC_SECRET=""
USE_CONVERSION_TS=0
K_THRESHOLD="20"
RATE_N="5"
CALLER="demo"

AUTH_CONFIG=""
AUTH_REQUIRED=0
KEY_ID=""
TIMESTAMP=""
NONCE=""
SIGNATURE=""

usage() {
  cat <<EOF
Usage:
  $0 --criteo-tsv <path> --start-ts <unix_ts> --end-ts <unix_ts> --out <runs/job_id> [options]

Options:
  --job-id <id>              Optional job id (default: basename of --out)
  --value-mode <mode>        count|amount (default: count)
  --bucket-field <field>     Optional bucket field (e.g. partner_id)
  --hmac-secret <secret>     Optional anonymization secret for W1
  --purchase-use-conversion-ts  Filter purchases by conversion_ts
  --k <int>                  k-threshold for W2 (default: 20)
  --n <int>                  rate limit N for W2 (default: 5)
  --caller <id>              caller id for W2 (default: demo)

  --auth-config <file>       Optional auth config for W2
  --auth-required            Require HMAC auth in W2
  --key-id <id>              HMAC key id
  --timestamp <iso8601>      Request timestamp
  --nonce <str>              Request nonce
  --signature <hex>          HMAC signature
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --criteo-tsv) CRITEO_TSV="$2"; shift 2 ;;
    --out) OUT_DIR="$2"; shift 2 ;;
    --job-id) JOB_ID="$2"; shift 2 ;;
    --start-ts) START_TS="$2"; shift 2 ;;
    --end-ts) END_TS="$2"; shift 2 ;;
    --value-mode) VALUE_MODE="$2"; shift 2 ;;
    --bucket-field) BUCKET_FIELD="$2"; shift 2 ;;
    --hmac-secret) HMAC_SECRET="$2"; shift 2 ;;
    --purchase-use-conversion-ts) USE_CONVERSION_TS=1; shift 1 ;;
    --k) K_THRESHOLD="$2"; shift 2 ;;
    --n) RATE_N="$2"; shift 2 ;;
    --caller) CALLER="$2"; shift 2 ;;
    --auth-config) AUTH_CONFIG="$2"; shift 2 ;;
    --auth-required) AUTH_REQUIRED=1; shift 1 ;;
    --key-id) KEY_ID="$2"; shift 2 ;;
    --timestamp) TIMESTAMP="$2"; shift 2 ;;
    --nonce) NONCE="$2"; shift 2 ;;
    --signature) SIGNATURE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown arg: $1" ;;
  esac
done

[[ -n "$CRITEO_TSV" ]] || { usage; die "missing --criteo-tsv"; }
[[ -n "$START_TS" ]] || { usage; die "missing --start-ts"; }
[[ -n "$END_TS" ]] || { usage; die "missing --end-ts"; }
[[ -n "$OUT_DIR" ]] || { usage; die "missing --out"; }
[[ -f "$CRITEO_TSV" ]] || die "criteo file not found: $CRITEO_TSV"

mkdir -p "$RUNS_DIR"
if [[ "$OUT_DIR" != /* ]]; then
  OUT_DIR="$REPO_ROOT/$OUT_DIR"
fi
mkdir -p "$OUT_DIR"

if [[ -z "$JOB_ID" ]]; then
  JOB_ID="$(basename "$OUT_DIR")"
fi
AUDIT_LOG="$OUT_DIR/audit_log.jsonl"

[[ -f "$PREP_PY" ]] || die "prep_inputs.py not found: $PREP_PY"
[[ -f "$RUN_PJC_SH" ]] || die "run_pjc.sh not found: $RUN_PJC_SH"
[[ -f "$POLICY_PY" ]] || die "policy_release.py not found: $POLICY_PY"

log "job_id=$JOB_ID"
log "out_dir=$OUT_DIR"

log "Stage1 Prep: generating server.csv/client.csv/job_meta.json"
PREP_CMD=(python3 "$PREP_PY"
  --criteo-tsv "$CRITEO_TSV"
  --out "$OUT_DIR"
  --start-ts "$START_TS"
  --end-ts "$END_TS"
  --value-mode "$VALUE_MODE"
  --job-id "$JOB_ID"
)
if [[ -n "$BUCKET_FIELD" ]]; then PREP_CMD+=(--bucket-field "$BUCKET_FIELD"); fi
if [[ -n "$HMAC_SECRET" ]]; then PREP_CMD+=(--hmac-secret "$HMAC_SECRET"); fi
if [[ "$USE_CONVERSION_TS" == "1" ]]; then PREP_CMD+=(--purchase-use-conversion-ts); fi
"${PREP_CMD[@]}"

[[ -f "$OUT_DIR/job_meta.json" ]] || die "missing $OUT_DIR/job_meta.json after prep"
if [[ ! -f "$OUT_DIR/server.csv" && ! -d "$OUT_DIR" ]]; then
  die "prep stage did not produce expected output under $OUT_DIR"
fi

log "Stage2 Run: executing PJC PSI"

export SERVER_CSV="$OUT_DIR/server.csv"
export CLIENT_CSV="$OUT_DIR/client.csv"
export OUT_DIR="$OUT_DIR"
export JOB_ID="$JOB_ID"

bash "$RUN_PJC_SH"

[[ -f "$OUT_DIR/attribution_result.json" ]] || die "missing $OUT_DIR/attribution_result.json after PJC"

log "Stage3 Policy: applying threshold/rate/audit and producing public_report.json"
POLICY_CMD=(python3 "$POLICY_PY"
  --job-dir "$OUT_DIR"
  --caller "$CALLER"
  --k "$K_THRESHOLD"
  --n "$RATE_N"
  --audit-log "$AUDIT_LOG"
)
if [[ -n "$AUTH_CONFIG" ]]; then POLICY_CMD+=(--auth-config "$AUTH_CONFIG"); fi
if [[ "$AUTH_REQUIRED" == "1" ]]; then POLICY_CMD+=(--auth-required); fi
if [[ -n "$KEY_ID" ]]; then POLICY_CMD+=(--key-id "$KEY_ID"); fi
if [[ -n "$TIMESTAMP" ]]; then POLICY_CMD+=(--timestamp "$TIMESTAMP"); fi
if [[ -n "$NONCE" ]]; then POLICY_CMD+=(--nonce "$NONCE"); fi
if [[ -n "$SIGNATURE" ]]; then POLICY_CMD+=(--signature "$SIGNATURE"); fi
"${POLICY_CMD[@]}"

[[ -f "$OUT_DIR/public_report.json" ]] || die "missing $OUT_DIR/public_report.json after policy"

log "DONE."
log "server.csv:        $OUT_DIR/server.csv"
log "client.csv:        $OUT_DIR/client.csv"
log "job_meta.json:     $OUT_DIR/job_meta.json"
log "attribution_result:$OUT_DIR/attribution_result.json"
log "public_report:     $OUT_DIR/public_report.json"
log "audit_log:         $AUDIT_LOG"