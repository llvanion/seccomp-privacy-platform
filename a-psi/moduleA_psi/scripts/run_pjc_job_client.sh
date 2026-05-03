#!/usr/bin/env bash
set -euo pipefail

die() { echo "[ERROR] $*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

JOB_DIR="${JOB_DIR:-${1:-}}"
SERVER_ADDR="${SERVER_ADDR:-127.0.0.1:10501}"
RUN_PJC_CLIENT_SH="${RUN_PJC_CLIENT_SH:-$SCRIPT_DIR/run_pjc_client.sh}"
RUN_PJC_BUCKETED_CLIENT_SH="${RUN_PJC_BUCKETED_CLIENT_SH:-$SCRIPT_DIR/run_pjc_bucketed_client.sh}"
VALIDATE_BRIDGE_JOB_PY="${VALIDATE_BRIDGE_JOB_PY:-$SCRIPT_DIR/validate_bridge_job.py}"

[[ -n "$JOB_DIR" ]] || die "JOB_DIR required"
JOB_DIR="$(cd "$JOB_DIR" && pwd)"
[[ -f "$JOB_DIR/job_meta.json" ]] || die "missing $JOB_DIR/job_meta.json"

if python3 - <<'PY' "$JOB_DIR/job_meta.json"
import json,sys
m=json.load(open(sys.argv[1], encoding="utf-8"))
raise SystemExit(0 if isinstance(m.get("bridge"), dict) else 1)
PY
then
  python3 "$VALIDATE_BRIDGE_JOB_PY" --job-dir "$JOB_DIR"
fi

BUCKET_FIELD="$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print((m.get("bucket",{}) or {}).get("field") or "")' "$JOB_DIR/job_meta.json")"

export JOB_DIR SERVER_ADDR
if [[ -n "$BUCKET_FIELD" ]]; then
  bash "$RUN_PJC_BUCKETED_CLIENT_SH"
else
  export JOB_ID="${JOB_ID:-$(basename "$JOB_DIR")}"
  export OUT_DIR="${OUT_DIR:-$JOB_DIR}"
  export CLIENT_CSV="${CLIENT_CSV:-$JOB_DIR/client.csv}"
  bash "$RUN_PJC_CLIENT_SH"
fi
