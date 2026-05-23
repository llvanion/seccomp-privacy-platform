#!/usr/bin/env bash
set -euo pipefail

# Party B convenience wrapper. If CERT_DIR already contains ca.crt,
# client.crt, and client.key, it directly runs the TLS client. If not, it can
# enroll through Party A's dashboard CSR endpoint, or fall back to SSH fetch.

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
  if [[ -n "${PJC_MTLS_PAIRING_TOKEN:-${PAIRING_TOKEN:-}}" || -n "${PJC_MTLS_ENROLL_URL:-}" ]]; then
    CERT_DIR="$CERT_DIR" bash "$SCRIPT_DIR/enroll_pjc_mtls_party_b.sh"
  elif [[ -n "${PARTY_A_SSH:-}" ]]; then
    CERT_DIR="$CERT_DIR" bash "$SCRIPT_DIR/fetch_pjc_mtls_party_b.sh"
  else
    echo "[error] missing cert bundle in $CERT_DIR" >&2
    echo "[hint] set PJC_MTLS_PAIRING_TOKEN=<token> plus SERVER_HOST=<party-a-host> for no-SSH enrollment" >&2
    echo "[hint] or set PARTY_A_SSH=<user@party-a-host> for SSH fallback fetch" >&2
    exit 1
  fi
fi

export CERT_DIR
exec bash "$SCRIPT_DIR/run_pjc_client_tls.sh"
