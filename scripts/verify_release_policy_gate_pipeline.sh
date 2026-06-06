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
      --client-allowed-value-field amount \
      --client-value-unit minor_currency_unit \
      --client-value-currency USD \
      --token-scope release-gate-pipeline-scope \
      --token-secret-env RELEASE_GATE_TOKEN_SECRET \
      --job-id release_gate_pipeline_missing_config \
      --out-base "$OUT_ROOT/pipeline_missing_release_policy_gate_config" \
      --caller auto_demo \
      --sse-export-policy-config "$REPO_ROOT/sse/config/export_policy.example.json" \
      --pjc-resource-limits "$REPO_ROOT/config/pjc_resource_limits.example.json" \
      --production-mode

cat > "$OUT_ROOT/source_attestation_required.json" <<'JSON'
{
  "schema": "release_policy_gate_config/v1",
  "require_dp": true,
  "min_dp_epsilon": 0.1,
  "max_dp_epsilon": 5.0,
  "min_k": 1,
  "require_privacy_budget": false,
  "budget_ledger_path": null,
  "duplicate_query_denied": true,
  "require_public_report_redaction": false,
  "require_source_attestation": true,
  "require_signed_signoff": true,
  "require_dual_signoff": true,
  "require_bound_input_commitment": true,
  "strict_source_attestation": true,
  "max_source_attestation_age_hours": 168,
  "require_pjc_evidence_merge": false,
  "require_external_anchor": false,
  "allowed_deny_reason_codes": [
    "below_k",
    "below_min_rows",
    "rate_limit_exceeded",
    "privacy_budget_exhausted",
    "privacy_budget_duplicate_query",
    "privacy_budget_near_duplicate",
    "privacy_budget_bucket_probe",
    "privacy_budget_missing_scope",
    "privacy_budget_config_missing"
  ]
}
JSON

run_expect_fail "pipeline_missing_source_attestation_fields" "--source-system is required when source attestation is enabled" \
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
      --client-allowed-value-field amount \
      --client-value-unit minor_currency_unit \
      --client-value-currency USD \
      --token-scope release-gate-source-attestation-scope \
      --token-secret-env RELEASE_GATE_TOKEN_SECRET \
      --job-id release_gate_pipeline_missing_source_attestation \
      --out-base "$OUT_ROOT/pipeline_missing_source_attestation" \
      --caller auto_demo \
      --tenant-id demo_tenant \
      --dataset-id bridge_demo_dataset \
      --sse-export-policy-config "$REPO_ROOT/sse/config/export_policy.example.json" \
      --pjc-resource-limits "$REPO_ROOT/config/pjc_resource_limits.example.json" \
      --release-policy-gate-config "$OUT_ROOT/source_attestation_required.json" \
      --production-mode

python3 "$REPO_ROOT/scripts/check_release_policy_gate_smoke.py" >/dev/null

echo "[ok] release policy gate pipeline fail-closed verified"
