#!/usr/bin/env bash
set -euo pipefail

# Party A helper: create/reuse a shared PJC mTLS cert set and stage the
# client-side bundle that Party B may fetch over SSH.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="$(cd "$MODULE_ROOT/.." && pwd)"

CERT_DIR="${CERT_DIR:-$REPO_ROOT/tmp/pjc_mtls_shared/certs}"
BUNDLE_DIR="${BUNDLE_DIR:-$REPO_ROOT/tmp/pjc_mtls_shared/party_b_bundle}"
FORCE_REGENERATE="${FORCE_REGENERATE:-0}"

need_cert_generation() {
  [[ "$FORCE_REGENERATE" == "1" ]] && return 0
  [[ ! -f "$CERT_DIR/ca.crt" ]] && return 0
  [[ ! -f "$CERT_DIR/ca.key" ]] && return 0
  [[ ! -f "$CERT_DIR/server.crt" ]] && return 0
  [[ ! -f "$CERT_DIR/server.key" ]] && return 0
  [[ ! -f "$CERT_DIR/client.crt" ]] && return 0
  [[ ! -f "$CERT_DIR/client.key" ]] && return 0
  return 1
}

if need_cert_generation; then
  echo "[info] generating PJC mTLS certs in $CERT_DIR"
  CERT_DIR="$CERT_DIR" bash "$SCRIPT_DIR/gen_pjc_tls_certs.sh"
else
  echo "[info] reusing existing PJC mTLS certs in $CERT_DIR"
fi

mkdir -p "$BUNDLE_DIR"
chmod 700 "$BUNDLE_DIR"
cp "$CERT_DIR/ca.crt" "$BUNDLE_DIR/ca.crt"
cp "$CERT_DIR/client.crt" "$BUNDLE_DIR/client.crt"
cp "$CERT_DIR/client.key" "$BUNDLE_DIR/client.key"
chmod 644 "$BUNDLE_DIR/ca.crt" "$BUNDLE_DIR/client.crt"
chmod 600 "$BUNDLE_DIR/client.key"

echo "[ok] Party B bundle staged at: $BUNDLE_DIR"
echo "[info] CA fingerprint:"
openssl x509 -in "$CERT_DIR/ca.crt" -fingerprint -sha256 -noout
echo "[info] Party A runtime CERT_DIR:"
echo "  $CERT_DIR"
echo "[info] Party B can fetch with:"
echo "  PARTY_A_SSH=<user@party-a-host> bash a-psi/moduleA_psi/scripts/fetch_pjc_mtls_party_b.sh"
echo "[warn] Never send or commit ca.key/server.key. Only Party B bundle files are meant to be shared."
