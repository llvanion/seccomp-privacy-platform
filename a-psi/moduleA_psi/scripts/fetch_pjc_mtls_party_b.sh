#!/usr/bin/env bash
set -euo pipefail

# Party B helper: fetch the client-side PJC mTLS bundle from Party A over SSH.
# SSH is the trust bootstrap: verify the printed CA fingerprint out-of-band.

SERVER_HOST="${SERVER_HOST:-}"
PARTY_A_SSH="${PARTY_A_SSH:-}"
REMOTE_BUNDLE_DIR="${REMOTE_BUNDLE_DIR:-~/Desktop/seccomp-privacy-platform/tmp/pjc_mtls_shared/party_b_bundle}"
CERT_DIR="${CERT_DIR:-$HOME/pjc_certs_shared}"

if [[ -z "$PARTY_A_SSH" ]]; then
  if [[ -n "$SERVER_HOST" ]]; then
    PARTY_A_SSH="$SERVER_HOST"
  else
    echo "[error] set PARTY_A_SSH=<user@party-a-host> or SERVER_HOST=<ssh-host-alias>" >&2
    exit 1
  fi
fi

command -v scp >/dev/null || { echo "[error] scp not found" >&2; exit 1; }
command -v openssl >/dev/null || { echo "[error] openssl not found" >&2; exit 1; }

mkdir -p "$CERT_DIR"
chmod 700 "$CERT_DIR"

echo "[info] fetching Party B cert bundle from $PARTY_A_SSH:$REMOTE_BUNDLE_DIR"
scp "$PARTY_A_SSH:$REMOTE_BUNDLE_DIR/ca.crt" "$CERT_DIR/ca.crt"
scp "$PARTY_A_SSH:$REMOTE_BUNDLE_DIR/client.crt" "$CERT_DIR/client.crt"
scp "$PARTY_A_SSH:$REMOTE_BUNDLE_DIR/client.key" "$CERT_DIR/client.key"

chmod 644 "$CERT_DIR/ca.crt" "$CERT_DIR/client.crt"
chmod 600 "$CERT_DIR/client.key"

echo "[ok] cert bundle stored at: $CERT_DIR"
echo "[info] CA fingerprint; verify it matches Party A out-of-band:"
openssl x509 -in "$CERT_DIR/ca.crt" -fingerprint -sha256 -noout
