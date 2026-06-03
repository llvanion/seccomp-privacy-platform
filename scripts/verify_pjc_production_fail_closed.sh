#!/usr/bin/env bash
# Verify PJC production wrappers fail closed before launching external services.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

OUT_ROOT="$(mktemp -d /tmp/seccomp_pjc_prod_gate.XXXXXX)"
cleanup() {
  rm -rf "$OUT_ROOT"
}
trap cleanup EXIT

SERVER_CSV="$OUT_ROOT/server.csv"
CLIENT_CSV="$OUT_ROOT/client.csv"
CERT_DIR="$OUT_ROOT/certs"
mkdir -p "$CERT_DIR"
printf 'id,value\ns1,10\n' > "$SERVER_CSV"
printf 'id,value\nc1,10\n' > "$CLIENT_CSV"
touch "$CERT_DIR/ca.crt" "$CERT_DIR/server.crt" "$CERT_DIR/server.key" "$CERT_DIR/client.crt" "$CERT_DIR/client.key"

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

run_expect_fail "local_missing_limits" "PJC_PRODUCTION_MODE=1 requires PJC_RESOURCE_LIMITS" \
  env \
    PJC_PRODUCTION_MODE=1 \
    SERVER_CSV="$SERVER_CSV" \
    CLIENT_CSV="$CLIENT_CSV" \
    OUT_DIR="$OUT_ROOT/local_missing_limits" \
    PJC_BIN_DIR="$OUT_ROOT/no_bins" \
    bash "$REPO_ROOT/a-psi/moduleA_psi/scripts/run_pjc.sh"

run_expect_fail "local_unary_forbidden" "PJC_PRODUCTION_MODE=1 forbids legacy unary mode" \
  env \
    PJC_PRODUCTION_MODE=1 \
    PJC_RESOURCE_LIMITS="$REPO_ROOT/config/pjc_resource_limits.example.json" \
    PJC_GRPC_STREAM_CHUNK_ELEMENTS=0 \
    SERVER_CSV="$SERVER_CSV" \
    CLIENT_CSV="$CLIENT_CSV" \
    OUT_DIR="$OUT_ROOT/local_unary_forbidden" \
    PJC_BIN_DIR="$OUT_ROOT/no_bins" \
    bash "$REPO_ROOT/a-psi/moduleA_psi/scripts/run_pjc.sh"

run_expect_fail "local_wide_plain_bind" "plain gRPC must bind loopback" \
  env \
    PJC_PRODUCTION_MODE=1 \
    PJC_RESOURCE_LIMITS="$REPO_ROOT/config/pjc_resource_limits.example.json" \
    SERVER_ADDR="0.0.0.0:10501" \
    SERVER_CSV="$SERVER_CSV" \
    CLIENT_CSV="$CLIENT_CSV" \
    OUT_DIR="$OUT_ROOT/local_wide_plain_bind" \
    PJC_BIN_DIR="$OUT_ROOT/no_bins" \
    bash "$REPO_ROOT/a-psi/moduleA_psi/scripts/run_pjc.sh"

run_expect_fail "tls_server_missing_manifest_requirement" "PJC_PRODUCTION_MODE=1 requires PJC_MTLS_REQUIRE_SESSION_MANIFEST=1" \
  env \
    PJC_PRODUCTION_MODE=1 \
    PJC_RESOURCE_LIMITS="$REPO_ROOT/config/pjc_resource_limits.example.json" \
    CERT_DIR="$CERT_DIR" \
    SERVER_CSV="$SERVER_CSV" \
    OUT_DIR="$OUT_ROOT/tls_server_missing_manifest_requirement" \
    PJC_BIN_DIR="$OUT_ROOT/no_bins" \
    bash "$REPO_ROOT/a-psi/moduleA_psi/scripts/run_pjc_server_tls.sh"

run_expect_fail "tls_server_wide_bind_requires_override" "broad TLS bind requires PJC_ALLOW_PRODUCTION_WIDE_BIND=1" \
  env \
    PJC_PRODUCTION_MODE=1 \
    PJC_RESOURCE_LIMITS="$REPO_ROOT/config/pjc_resource_limits.example.json" \
    PJC_MTLS_REQUIRE_SESSION_MANIFEST=1 \
    CERT_DIR="$CERT_DIR" \
    SERVER_CSV="$SERVER_CSV" \
    OUT_DIR="$OUT_ROOT/tls_server_wide_bind_requires_override" \
    PJC_BIN_DIR="$OUT_ROOT/no_bins" \
    bash "$REPO_ROOT/a-psi/moduleA_psi/scripts/run_pjc_server_tls.sh"

run_expect_fail "tls_client_missing_limits" "PJC_PRODUCTION_MODE=1 requires PJC_RESOURCE_LIMITS" \
  env \
    PJC_PRODUCTION_MODE=1 \
    SERVER_HOST=127.0.0.1 \
    CERT_DIR="$CERT_DIR" \
    CLIENT_CSV="$CLIENT_CSV" \
    OUT_DIR="$OUT_ROOT/tls_client_missing_limits" \
    PJC_BIN_DIR="$OUT_ROOT/no_bins" \
    bash "$REPO_ROOT/a-psi/moduleA_psi/scripts/run_pjc_client_tls.sh"

run_expect_fail "pipeline_missing_pjc_resource_limits" "--pjc-resource-limits is required in --production-mode" \
  env \
    PROD_GATE_TOKEN_SECRET=local-dev-secret \
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
      --token-scope pjc-prod-gate-scope \
      --token-secret-env PROD_GATE_TOKEN_SECRET \
      --job-id pjc_prod_gate_pipeline \
      --out-base "$OUT_ROOT/pipeline_missing_pjc_resource_limits" \
      --caller auto_demo \
      --sse-export-policy-config "$REPO_ROOT/sse/config/export_policy.example.json" \
      --production-mode

run_expect_fail "pipeline_missing_release_policy_gate_config" "--release-policy-gate-config is required in --production-mode" \
  env \
    PROD_GATE_TOKEN_SECRET=local-dev-secret \
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
      --token-scope pjc-prod-gate-scope \
      --token-secret-env PROD_GATE_TOKEN_SECRET \
      --job-id pjc_prod_gate_pipeline_release_gate \
      --out-base "$OUT_ROOT/pipeline_missing_release_policy_gate_config" \
      --caller auto_demo \
      --sse-export-policy-config "$REPO_ROOT/sse/config/export_policy.example.json" \
      --pjc-resource-limits "$REPO_ROOT/config/pjc_resource_limits.example.json" \
      --production-mode

echo "[ok] PJC production fail-closed wrappers verified"
