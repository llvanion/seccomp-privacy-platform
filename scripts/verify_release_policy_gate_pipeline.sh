#!/usr/bin/env bash
# Verify production pipeline cannot bypass the centralized release policy gate.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

OUT_ROOT="$(mktemp -d /tmp/seccomp_release_gate_pipeline.XXXXXX)"
cleanup() {
  rm -rf "$OUT_ROOT"
}
trap cleanup EXIT

run_expect_fail() {
  local name="$1"
  local expected="$2"
  shift 2
  local log="$OUT_ROOT/$name.log"
  set +e
  "$@" >"$log" 2>&1
  local rc=$?
  set -e
  if [[ "$rc" -eq 0 ]]; then
    echo "[FAIL] $name expected non-zero exit" >&2
    cat "$log" >&2
    exit 1
  fi
  if ! grep -q -- "$expected" "$log"; then
    echo "[FAIL] $name expected log to contain: $expected" >&2
    cat "$log" >&2
    exit 1
  fi
  echo "[ok] $name failed closed: $expected"
}

run_expect_fail "pipeline_missing_release_policy_gate_config" "--release-policy-gate-config is required in --production-mode" \
  env \
    RELEASE_GATE_TOKEN_SECRET=local-dev-secret \
    bash "$REPO_ROOT/scripts/run_sse_bridge_pipeline.sh" \
      --server-source "$REPO_ROOT/sse/examples/bridge_server_records.jsonl" \
      --client-source "$REPO_ROOT/sse/examples/bridge_client_records.jsonl" \
      --server-join-key-field email \
      --client-join-key-field email \
      --client-value-field amount \
      --server-normalizer email \
      --client-normalizer email \
      --client-value-mode raw-int \
      --client-value-max 1000000 \
      --token-scope release-gate-pipeline-scope \
      --token-secret-env RELEASE_GATE_TOKEN_SECRET \
      --job-id release_gate_pipeline_missing_config \
      --out-base "$OUT_ROOT/pipeline_missing_release_policy_gate_config" \
      --caller auto_demo \
      --sse-export-policy-config "$REPO_ROOT/sse/config/export_policy.example.json" \
      --pjc-resource-limits "$REPO_ROOT/config/pjc_resource_limits.example.json" \
      --production-mode

python3 "$REPO_ROOT/scripts/check_release_policy_gate_smoke.py" >/dev/null

echo "[ok] release policy gate pipeline fail-closed verified"
