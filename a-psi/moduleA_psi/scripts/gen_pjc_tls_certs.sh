#!/usr/bin/env bash
set -euo pipefail
# Generates a self-signed CA + server cert + client cert for PJC mTLS.
#
# Run this on Party A's machine ONCE before the first cross-internet run.
#
# Share these three files with Party B via a secure out-of-band channel
# (e.g. scp + verify fingerprint, encrypted email, Signal):
#   $CERT_DIR/ca.crt
#   $CERT_DIR/client.crt
#   $CERT_DIR/client.key
#
# Keep these private on Party A:
#   $CERT_DIR/ca.key        (CA signing key — never share)
#   $CERT_DIR/server.crt
#   $CERT_DIR/server.key

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CERT_DIR="${CERT_DIR:-$MODULE_ROOT/config/tls}"
DAYS="${CERT_VALIDITY_DAYS:-365}"

command -v openssl >/dev/null || { echo "[error] openssl not found" >&2; exit 1; }

mkdir -p "$CERT_DIR"
chmod 700 "$CERT_DIR"

echo "[info] CERT_DIR=$CERT_DIR"
echo "[info] validity=${DAYS} days"

# ── CA ────────────────────────────────────────────────────────────────────────
echo "[info] generating CA key (4096 bit)..."
openssl genrsa -out "$CERT_DIR/ca.key" 4096 2>/dev/null
chmod 600 "$CERT_DIR/ca.key"

openssl req -new -x509 -days "$DAYS" \
  -key "$CERT_DIR/ca.key" \
  -out "$CERT_DIR/ca.crt" \
  -subj "/CN=pjc-ca/O=PJC-TLS"
chmod 644 "$CERT_DIR/ca.crt"
echo "[ok] ca.crt"

# ── Server cert (Party A) ─────────────────────────────────────────────────────
echo "[info] generating server key and cert..."
openssl genrsa -out "$CERT_DIR/server.key" 4096 2>/dev/null
chmod 600 "$CERT_DIR/server.key"

openssl req -new \
  -key "$CERT_DIR/server.key" \
  -out "$CERT_DIR/server.csr" \
  -subj "/CN=pjc-server/O=PJC-TLS"

openssl x509 -req -days "$DAYS" \
  -in "$CERT_DIR/server.csr" \
  -CA "$CERT_DIR/ca.crt" \
  -CAkey "$CERT_DIR/ca.key" \
  -CAcreateserial \
  -out "$CERT_DIR/server.crt" 2>/dev/null
chmod 644 "$CERT_DIR/server.crt"
rm -f "$CERT_DIR/server.csr"
echo "[ok] server.crt"

# ── Client cert (Party B) ─────────────────────────────────────────────────────
echo "[info] generating client key and cert..."
openssl genrsa -out "$CERT_DIR/client.key" 4096 2>/dev/null
chmod 600 "$CERT_DIR/client.key"

openssl req -new \
  -key "$CERT_DIR/client.key" \
  -out "$CERT_DIR/client.csr" \
  -subj "/CN=pjc-client/O=PJC-TLS"

openssl x509 -req -days "$DAYS" \
  -in "$CERT_DIR/client.csr" \
  -CA "$CERT_DIR/ca.crt" \
  -CAkey "$CERT_DIR/ca.key" \
  -CAcreateserial \
  -out "$CERT_DIR/client.crt" 2>/dev/null
chmod 644 "$CERT_DIR/client.crt"
rm -f "$CERT_DIR/client.csr"
echo "[ok] client.crt"

# ── Fingerprint summary ───────────────────────────────────────────────────────
echo ""
echo "[info] CA fingerprint (share with Party B to verify):"
openssl x509 -in "$CERT_DIR/ca.crt" -fingerprint -sha256 -noout
echo ""
echo "[info] Files to send to Party B (secure channel only):"
echo "  ca.crt     $(cat "$CERT_DIR/ca.crt" | wc -c) bytes"
echo "  client.crt $(cat "$CERT_DIR/client.crt" | wc -c) bytes"
echo "  client.key $(cat "$CERT_DIR/client.key" | wc -c) bytes"
echo ""
echo "[info] Files to keep on Party A only:"
echo "  ca.key     $CERT_DIR/ca.key"
echo "  server.crt $CERT_DIR/server.crt"
echo "  server.key $CERT_DIR/server.key"
echo ""
echo "[ok] done. Cert dir: $CERT_DIR"
