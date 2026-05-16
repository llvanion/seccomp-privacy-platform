#!/usr/bin/env bash
set -euo pipefail

# Party B convenience wrapper. If CERT_DIR already contains ca.crt,
# client.crt, and client.key, it directly runs the TLS client. If not, it can
# fetch them from Party A over SSH when PARTY_A_SSH is provided.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SERVER_HOST="${SERVER_HOST:-}"
CERT_DIR="${CERT_DIR:-$HOME/pjc_certs_shared}"
AUTO_FETCH_CERTS="${AUTO_FETCH_CERTS:-1}"

[[ -n "$SERVER_HOST" ]] || {
  echo "[error] SERVER_HOST is required (Party A public IP, hostname, or VPN IP)" >&2
  exit 1
}

bundle_ready() {
  [[ -f "$CERT_DIR/ca.crt" && -f "$CERT_DIR/client.crt" && -f "$CERT_DIR/client.key" ]]
}

if ! bundle_ready; then
  if [[ "$AUTO_FETCH_CERTS" != "1" ]]; then
    echo "[error] missing cert bundle in $CERT_DIR and AUTO_FETCH_CERTS is disabled" >&2
    exit 1
  fi
  if [[ -z "${PARTY_A_SSH:-}" ]]; then
    echo "[error] missing cert bundle in $CERT_DIR; set PARTY_A_SSH=<user@party-a-host> for first-time fetch" >&2
    exit 1
  fi
  CERT_DIR="$CERT_DIR" bash "$SCRIPT_DIR/fetch_pjc_mtls_party_b.sh"
fi

export CERT_DIR
exec bash "$SCRIPT_DIR/run_pjc_client_tls.sh"
