#!/usr/bin/env bash
set -euo pipefail

# ---------------- helpers ----------------
die() { echo "[ERROR] $*" >&2; exit 1; }
log() { echo "[INFO] $*"; }

usage() {
  cat <<'EOF'
W3 One-click Pipeline (Prep -> Run PJC -> Policy Release)

Usage:
  bash run_pipeline.sh --criteo-tsv <path> --start-ts <sec> --end-ts <sec> [options]

Required:
  --criteo-tsv <file>     Input Criteo TSV
  --start-ts <int>        Window start timestamp (seconds)
  --end-ts <int>          Window end timestamp (seconds)

Options:
  --out <dir>             Output job directory (default: <repo>/runs/<job_id>)
  --job-id <id>           Job id (default: UTC timestamp like 20260227T123000Z)
  --value-mode <mode>     count|amount (default: count)
  --bucket-field <field>  Optional bucket field name (passed to prep_inputs.py)
  --hmac-secret <secret>  Optional HMAC secret (passed to prep_inputs.py)
  --purchase-use-conversion-ts
                          Optional flag (passed to prep_inputs.py)

  --k <int>               Threshold k for policy release (default: 20)
  --round-sum-to <int>    Optional rounding for sum fields in policy release (default: 0 / disabled)
  --audit-log <file>      Audit log jsonl path (default: <repo>/runs/audit_log.jsonl)

Examples:
  bash run_pipeline.sh --criteo-tsv data/CriteoSearchData.tsv --start-ts 1700000000 --end-ts 1700600000 --k 20

Outputs (under <out>):
  server.csv, client.csv, job_meta.json, attribution_result.json, public_report.json
EOF
}

# ---------------- locate repo paths ----------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PREP_PY="$REPO_ROOT/moduleA_psi/scripts/prep_inputs.py"
RUN_PJC_SH="$REPO_ROOT/moduleA_psi/scripts/run_pjc.sh"
POLICY_PY="$REPO_ROOT/moduleA_psi/scripts/policy_release.py"
RUNS_DIR="$REPO_ROOT/runs"

# ---------------- defaults ----------------
CRITEO_TSV=""
START_TS=""
END_TS=""

JOB_ID="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR=""               # default computed after parsing
VALUE_MODE="count"

BUCKET_FIELD=""
HMAC_SECRET=""
USE_CONV_TS=0

K_THRESHOLD="20"
ROUND_SUM_TO=""          # empty means "do not pass flag"
AUDIT_LOG="$RUNS_DIR/audit_log.jsonl"

# ---------------- parse args ----------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --criteo-tsv) CRITEO_TSV="$2"; shift 2;;
    --start-ts) START_TS="$2"; shift 2;;
    --end-ts) END_TS="$2"; shift 2;;

    --out) OUT_DIR="$2"; shift 2;;
    --job-id) JOB_ID="$2"; shift 2;;
    --value-mode) VALUE_MODE="$2"; shift 2;;

    --bucket-field) BUCKET_FIELD="$2"; shift 2;;
    --hmac-secret) HMAC_SECRET="$2"; shift 2;;
    --purchase-use-conversion-ts) USE_CONV_TS=1; shift 1;;

    --k) K_THRESHOLD="$2"; shift 2;;
    --round-sum-to) ROUND_SUM_TO="$2"; shift 2;;
    --audit-log) AUDIT_LOG="$2"; shift 2;;

    -h|--help) usage; exit 0;;
    *) die "Unknown arg: $1 (try --help)";;
  esac
done

# ---------------- validate required ----------------
[[ -n "$CRITEO_TSV" ]] || { usage; die "missing --criteo-tsv"; }
[[ -n "$START_TS" ]] || { usage; die "missing --start-ts"; }
[[ -n "$END_TS" ]] || { usage; die "missing --end-ts"; }

[[ -f "$CRITEO_TSV" ]] || die "criteo tsv not found: $CRITEO_TSV"
[[ -f "$PREP_PY" ]] || die "prep_inputs.py not found: $PREP_PY"
[[ -f "$POLICY_PY" ]] || die "policy_release.py not found: $POLICY_PY"
[[ -f "$RUN_PJC_SH" ]] || die "run_pjc.sh not found: $RUN_PJC_SH"

mkdir -p "$RUNS_DIR"

if [[ -z "$OUT_DIR" ]]; then
  OUT_DIR="$RUNS_DIR/$JOB_ID"
else
  # allow relative path
  if [[ "$OUT_DIR" != /* ]]; then
    OUT_DIR="$REPO_ROOT/$OUT_DIR"
  fi
fi

mkdir -p "$OUT_DIR"

# audit log can be anywhere; make parent dir
AUDIT_DIR="$(cd "$(dirname "$AUDIT_LOG")" && pwd 2>/dev/null || true)"
if [[ -z "$AUDIT_DIR" ]]; then
  mkdir -p "$(dirname "$AUDIT_LOG")"
else
  mkdir -p "$AUDIT_DIR"
fi

log "job_id=$JOB_ID"
log "out_dir=$OUT_DIR"
log "audit_log=$AUDIT_LOG"

# ---------------- stage 1: Prep ----------------
log "Stage 1/3: Prep inputs -> server.csv / client.csv / job_meta.json"

PREP_CMD=(python3 "$PREP_PY"
  --criteo-tsv "$CRITEO_TSV"
  --out "$OUT_DIR"
  --start-ts "$START_TS"
  --end-ts "$END_TS"
  --value-mode "$VALUE_MODE"
)

if [[ -n "$HMAC_SECRET" ]]; then
  PREP_CMD+=(--hmac-secret "$HMAC_SECRET")
fi
if [[ -n "$BUCKET_FIELD" ]]; then
  PREP_CMD+=(--bucket-field "$BUCKET_FIELD")
fi
if [[ "$USE_CONV_TS" -eq 1 ]]; then
  PREP_CMD+=(--purchase-use-conversion-ts)
fi

"${PREP_CMD[@]}"

[[ -f "$OUT_DIR/server.csv" ]] || die "missing $OUT_DIR/server.csv after prep"
[[ -f "$OUT_DIR/client.csv" ]] || die "missing $OUT_DIR/client.csv after prep"
[[ -f "$OUT_DIR/job_meta.json" ]] || die "missing $OUT_DIR/job_meta.json after prep"

# ---------------- stage 2: Run PJC ----------------
log "Stage 2/3: Run PJC -> attribution_result.json"

# run_pjc.sh uses SERVER_CSV/CLIENT_CSV and OUT_DIR env vars; override them here
SERVER_CSV="$OUT_DIR/server.csv" \
CLIENT_CSV="$OUT_DIR/client.csv" \
OUT_DIR="$OUT_DIR" \
JOB_ID="$JOB_ID" \
bash "$RUN_PJC_SH"

[[ -f "$OUT_DIR/attribution_result.json" ]] || die "missing $OUT_DIR/attribution_result.json after PJC"

# ---------------- stage 3: Policy ----------------
log "Stage 3/3: Policy release -> public_report.json"

POLICY_CMD=(python3 "$POLICY_PY"
  --input "$OUT_DIR/attribution_result.json"
  --out "$OUT_DIR/public_report.json"
  --threshold-k "$K_THRESHOLD"
  --audit-log "$AUDIT_LOG"
  --query-id "$JOB_ID"
)

if [[ -n "$ROUND_SUM_TO" ]]; then
  POLICY_CMD+=(--round-sum-to "$ROUND_SUM_TO")
fi

"${POLICY_CMD[@]}"

[[ -f "$OUT_DIR/public_report.json" ]] || die "missing $OUT_DIR/public_report.json after policy release"

log "DONE ✅"
log "Artifacts:"
log "  - $OUT_DIR/server.csv"
log "  - $OUT_DIR/client.csv"
log "  - $OUT_DIR/job_meta.json"
log "  - $OUT_DIR/attribution_result.json"
log "  - $OUT_DIR/public_report.json"
log "Audit:"
log "  - $AUDIT_LOG"