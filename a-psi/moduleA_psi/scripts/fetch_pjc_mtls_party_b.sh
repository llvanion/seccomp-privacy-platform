#!/usr/bin/env bash
set -euo pipefail

# Party B helper: fetch the client-side PJC mTLS bundle from Party A over SSH.
# SSH is the trust bootstrap: verify the printed CA fingerprint out-of-band.

SERVER_HOST="${SERVER_HOST:-}"
PARTY_A_SSH="${PARTY_A_SSH:-}"
REMOTE_BUNDLE_DIR="${REMOTE_BUNDLE_DIR:-}"
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
command -v ssh >/dev/null || { echo "[error] ssh not found" >&2; exit 1; }
command -v openssl >/dev/null || { echo "[error] openssl not found" >&2; exit 1; }

if [[ -z "$REMOTE_BUNDLE_DIR" ]]; then
  echo "[info] detecting Party A bundle path on $PARTY_A_SSH"
  REMOTE_BUNDLE_DIR="$(
    ssh "$PARTY_A_SSH" 'sh -s' <<'REMOTE_PROBE'
set -eu
for d in \
  "$HOME/seccomp-privacy-platform/tmp/pjc_mtls_shared/party_b_bundle" \
  "$HOME/Desktop/seccomp-privacy-platform/tmp/pjc_mtls_shared/party_b_bundle" \
  "/root/seccomp-privacy-platform/tmp/pjc_mtls_shared/party_b_bundle"
do
  if [ -f "$d/ca.crt" ] && [ -f "$d/client.crt" ] && [ -f "$d/client.key" ]; then
    printf "%s\n" "$d"
    exit 0
  fi
done
exit 1
REMOTE_PROBE
  )" || {
    echo "[error] could not auto-detect Party A bundle path" >&2
    echo "[hint] run prepare_pjc_mtls_party_a.sh on Party A, or set REMOTE_BUNDLE_DIR explicitly" >&2
    exit 1
  }
fi

mkdir -p "$CERT_DIR"
chmod 700 "$CERT_DIR"

echo "[info] fetching Party B cert bundle from $PARTY_A_SSH:$REMOTE_BUNDLE_DIR"
scp \
  "$PARTY_A_SSH:$REMOTE_BUNDLE_DIR/ca.crt" \
  "$PARTY_A_SSH:$REMOTE_BUNDLE_DIR/client.crt" \
  "$PARTY_A_SSH:$REMOTE_BUNDLE_DIR/client.key" \
  "$CERT_DIR/"

chmod 644 "$CERT_DIR/ca.crt" "$CERT_DIR/client.crt"
chmod 600 "$CERT_DIR/client.key"

echo "[ok] cert bundle stored at: $CERT_DIR"
echo "[info] CA fingerprint; verify it matches Party A out-of-band:"
openssl x509 -in "$CERT_DIR/ca.crt" -fingerprint -sha256 -noout
