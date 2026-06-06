#!/usr/bin/env bash
set -euo pipefail

die() { echo "[ERROR] $*" >&2; exit 1; }
log() { echo "[INFO] $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

JOB_DIR="${JOB_DIR:-}"
RUN_PJC_SERVER_SH="${RUN_PJC_SERVER_SH:-$SCRIPT_DIR/run_pjc_server.sh}"
SERVER_ADDR="${SERVER_ADDR:-0.0.0.0:10501}"
PJC_DIR="${PJC_DIR:-$REPO_ROOT/private-join-and-compute}"
GRPC_MAX_MESSAGE_MB="${GRPC_MAX_MESSAGE_MB:-512}"
PJC_GRPC_STREAM_CHUNK_ELEMENTS="${PJC_GRPC_STREAM_CHUNK_ELEMENTS:-4096}"
PJC_BUILD="${PJC_BUILD:-0}"
PJC_REQUIRE_BUCKET_POLICY="${PJC_REQUIRE_BUCKET_POLICY:-0}"

[[ -n "$JOB_DIR" ]] || die "JOB_DIR is required"
JOB_DIR="$(cd "$JOB_DIR" && pwd)"
[[ -f "$JOB_DIR/job_meta.json" ]] || die "missing $JOB_DIR/job_meta.json"
[[ -f "$RUN_PJC_SERVER_SH" ]] || die "missing run_pjc_server.sh: $RUN_PJC_SERVER_SH"
VALIDATE_BUCKET_POLICY_PY="$SCRIPT_DIR/bucket_policy.py"
[[ -f "$VALIDATE_BUCKET_POLICY_PY" ]] || die "missing bucket policy helper: $VALIDATE_BUCKET_POLICY_PY"
POLICY_CMD=(python3 "$VALIDATE_BUCKET_POLICY_PY" --job-meta "$JOB_DIR/job_meta.json")
if [[ "$PJC_REQUIRE_BUCKET_POLICY" == "1" ]]; then
  POLICY_CMD+=(--require-policy)
fi
"${POLICY_CMD[@]}" >/dev/null

PY='import json,sys; m=json.load(open(sys.argv[1])); b=m.get("bucket",{}); print(b.get("field") or ""); [print(o.get("bucket")) for o in (b.get("outputs") or [])]'
mapfile -t INFO < <(python3 -c "$PY" "$JOB_DIR/job_meta.json")
BUCKET_FIELD="${INFO[0]}"
[[ -n "$BUCKET_FIELD" ]] || die "job_meta.json has no bucket_field; use run_pjc_server.sh for non-bucketed jobs"
JOB_META_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("job_id") or "")' "$JOB_DIR/job_meta.json")"
[[ -n "$JOB_META_ID" ]] || JOB_META_ID="$(basename "$JOB_DIR")"
BUCKET_ONLY="${BUCKET_ONLY:-}"

for bucket in "${INFO[@]:1}"; do
  if [[ -n "$BUCKET_ONLY" && "$bucket" != "$BUCKET_ONLY" ]]; then
    continue
  fi
  sub="$JOB_DIR/bucket_${BUCKET_FIELD}=${bucket}"
  [[ -f "$sub/server.csv" ]] || die "missing $sub/server.csv"
  log "serving bucket=$bucket from $sub"
  export PJC_DIR JOB_ID="$JOB_META_ID" OUT_DIR="$sub"
  export SERVER_CSV="$sub/server.csv" SERVER_ADDR GRPC_MAX_MESSAGE_MB PJC_BUILD
  export PJC_GRPC_STREAM_CHUNK_ELEMENTS
  [[ -f "$sub/job_meta.json" ]] && export PJC_JOB_META="$sub/job_meta.json" || unset PJC_JOB_META || true
  [[ -f "$sub/input_commitments.json" ]] && export PJC_INPUT_COMMITMENT="$sub/input_commitments.json" || unset PJC_INPUT_COMMITMENT || true
  if [[ -f "$sub/job_meta.json" ]]; then
    PJC_PREFLIGHT_CLIENT_ROWS="$(python3 -c 'import json,sys; print((json.load(open(sys.argv[1])).get("input_sizes") or {}).get("purchase_n") or 0)' "$sub/job_meta.json")"
    export PJC_PREFLIGHT_CLIENT_ROWS
  else
    unset PJC_PREFLIGHT_CLIENT_ROWS || true
  fi
  bash "$RUN_PJC_SERVER_SH"
done

log "all bucket server runs completed"
