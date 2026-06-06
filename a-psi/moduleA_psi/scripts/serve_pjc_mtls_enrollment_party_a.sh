#!/usr/bin/env bash
set -euo pipefail

# Party A helper: prepare the PJC mTLS CA/server certs and expose the existing
# operator dashboard enrollment endpoint so Party B can obtain a client cert via
# CSR. This does not change the PJC data-plane ports.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="$(cd "$MODULE_ROOT/.." && pwd)"
cd "$REPO_ROOT"

DASHBOARD_BIND_HOST="${DASHBOARD_BIND_HOST:-0.0.0.0}"
DASHBOARD_PORT="${DASHBOARD_PORT:-18134}"
OUT_BASE="${OUT_BASE:-tmp/operator_dashboard_mtls_enrollment}"
HISTORY_ROOT="${HISTORY_ROOT:-tmp}"
FORCE_REGENERATE="${FORCE_REGENERATE:-0}"
CERT_DIR="${CERT_DIR:-$REPO_ROOT/tmp/pjc_mtls_shared/certs}"
TOKEN_FILE="${PJC_MTLS_PAIRING_TOKEN_FILE:-$REPO_ROOT/tmp/pjc_mtls_shared/pairing_token}"
TOKEN_META_FILE="$REPO_ROOT/tmp/pjc_mtls_shared/pairing_token_meta.json"
PJC_MTLS_PAIRING_TOKEN_TTL_SECONDS="${PJC_MTLS_PAIRING_TOKEN_TTL_SECONDS:-600}"
PJC_MTLS_MAX_ENROLLMENTS="${PJC_MTLS_MAX_ENROLLMENTS:-1}"
PJC_MTLS_ENROLLMENT_IDLE_TIMEOUT_SECONDS="${PJC_MTLS_ENROLLMENT_IDLE_TIMEOUT_SECONDS:-0}"
export PJC_MTLS_PAIRING_TOKEN_TTL_SECONDS PJC_MTLS_MAX_ENROLLMENTS PJC_MTLS_ENROLLMENT_IDLE_TIMEOUT_SECONDS

command -v openssl >/dev/null || { echo "[error] openssl not found" >&2; exit 1; }
command -v python3 >/dev/null || { echo "[error] python3 not found" >&2; exit 1; }

mkdir -p "$(dirname "$TOKEN_FILE")" "$OUT_BASE" "$HISTORY_ROOT"
chmod 700 "$(dirname "$TOKEN_FILE")"

if [[ "$FORCE_REGENERATE" == "1" ]]; then
  rm -f "$TOKEN_FILE" "$TOKEN_META_FILE"
fi

if [[ -z "${PJC_MTLS_PAIRING_TOKEN:-}" ]]; then
  if [[ -f "$TOKEN_FILE" && "$FORCE_REGENERATE" != "1" ]]; then
    PJC_MTLS_PAIRING_TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"
  else
    PJC_MTLS_PAIRING_TOKEN="$(openssl rand -hex 24)"
    umask 077
    printf '%s\n' "$PJC_MTLS_PAIRING_TOKEN" > "$TOKEN_FILE"
  fi
fi
export PJC_MTLS_PAIRING_TOKEN

# Seed the token metadata so TTL counts from "Party A started", not first request.
python3 - "$TOKEN_META_FILE" "$PJC_MTLS_PAIRING_TOKEN" \
  "$PJC_MTLS_PAIRING_TOKEN_TTL_SECONDS" "$PJC_MTLS_MAX_ENROLLMENTS" <<'PY'
import json, os, sys, time
from datetime import datetime, timezone
meta_path, token, ttl_raw, max_raw = sys.argv[1:5]
os.makedirs(os.path.dirname(meta_path), exist_ok=True)
meta = {
    "token": token,
    "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "issued_at_epoch": int(time.time()),
    "ttl_seconds": int(ttl_raw or 0),
    "max_enrollments": int(max_raw or 0),
    "enrollments": 0,
    "source": "serve_pjc_mtls_enrollment_party_a.sh",
}
with open(meta_path, "w", encoding="utf-8") as fh:
    fh.write(json.dumps(meta, sort_keys=True) + "\n")
os.chmod(meta_path, 0o600)
PY

echo "[info] preparing Party A PJC mTLS material..."
CERT_DIR="$CERT_DIR" FORCE_REGENERATE="$FORCE_REGENERATE" bash "$SCRIPT_DIR/prepare_pjc_mtls_party_a.sh"

FINGERPRINT="$(openssl x509 -in "$CERT_DIR/ca.crt" -fingerprint -sha256 -noout)"
if [[ -n "${SERVER_HOST:-}" ]]; then
  ENROLL_URL="${PJC_MTLS_ENROLL_URL:-http://${SERVER_HOST}:${DASHBOARD_PORT}/v1/pjc-mtls/enroll}"
  B_SERVER_HOST="$SERVER_HOST"
else
  ENROLL_URL="${PJC_MTLS_ENROLL_URL:-http://<party-a-host>:${DASHBOARD_PORT}/v1/pjc-mtls/enroll}"
  B_SERVER_HOST="<party-a-host>"
fi
BOOTSTRAP_URI="$(python3 - "$ENROLL_URL" "$PJC_MTLS_PAIRING_TOKEN" "$FINGERPRINT" "$PJC_MTLS_PAIRING_TOKEN_TTL_SECONDS" <<'PY'
import sys
from urllib.parse import urlencode

enroll_url, token, fingerprint, ttl = sys.argv[1:5]
params = {
    "url": enroll_url,
    "token": token,
    "ca_sha256": fingerprint,
    "ttl": ttl,
}
print("pjc-mtls://enroll?" + urlencode(params))
PY
)"

echo "[ok] Party A enrollment endpoint is about to start"
echo "[info] dashboard: http://${SERVER_HOST:-<party-a-host>}:${DASHBOARD_PORT}/"
echo "[info] enroll URL for Party B:"
echo "  $ENROLL_URL"
echo "[info] pairing token for Party B:"
echo "  $PJC_MTLS_PAIRING_TOKEN"
echo "[info] pairing token TTL: ${PJC_MTLS_PAIRING_TOKEN_TTL_SECONDS}s, max enrollments: ${PJC_MTLS_MAX_ENROLLMENTS}"
if [[ "$PJC_MTLS_ENROLLMENT_IDLE_TIMEOUT_SECONDS" -gt 0 ]]; then
  echo "[info] enrollment server will auto-stop after ${PJC_MTLS_ENROLLMENT_IDLE_TIMEOUT_SECONDS}s of inactivity"
fi
echo "[info] CA fingerprint for Party B to verify (compare via independent channel):"
echo "  $FINGERPRINT"
echo "[info] one-line bootstrap URI for Party B (contains token + CA pin; transmit over an authenticated channel):"
echo "  $BOOTSTRAP_URI"
echo "[info] Party B enrollment command:"
echo "  SERVER_HOST=$B_SERVER_HOST \\"
echo "    PJC_MTLS_PAIRING_TOKEN=$PJC_MTLS_PAIRING_TOKEN \\"
echo "    EXPECTED_CA_FINGERPRINT='$FINGERPRINT' \\"
echo "    bash a-psi/moduleA_psi/scripts/enroll_pjc_mtls_party_b.sh"
echo "[info] Party B can alternatively use the one-line bootstrap URI:"
echo "  PJC_MTLS_BOOTSTRAP='$BOOTSTRAP_URI' \\"
echo "    bash a-psi/moduleA_psi/scripts/enroll_pjc_mtls_party_b.sh"
echo "[info] Party B can also combine enrollment with the PJC client:"
echo "  SERVER_HOST=$B_SERVER_HOST \\"
echo "    PJC_MTLS_PAIRING_TOKEN=$PJC_MTLS_PAIRING_TOKEN \\"
echo "    EXPECTED_CA_FINGERPRINT='$FINGERPRINT' \\"
echo "    bash a-psi/moduleA_psi/scripts/run_pjc_client_tls_auto.sh"
echo "[info] server auto-stops after MAX_ENROLLMENTS=$PJC_MTLS_MAX_ENROLLMENTS successful CSR signings"

# Enrollment-only HTTP mode by default — the server will refuse every dashboard
# endpoint except /healthz and POST /v1/pjc-mtls/enroll. Override with
# DASHBOARD_FULL_SURFACE=1 if you really do need the whole dashboard exposed.
DASHBOARD_MODE_FLAG="--mtls-enrollment-only-mode"
if [[ "${DASHBOARD_FULL_SURFACE:-0}" == "1" ]]; then
  echo "[warn] DASHBOARD_FULL_SURFACE=1 — serving the FULL operator dashboard on the bind host"
  DASHBOARD_MODE_FLAG=""
else
  echo "[info] enrollment-only mode: dashboard surface is restricted to /healthz + /v1/pjc-mtls/enroll"
fi

exec python3 scripts/serve_operator_dashboard.py \
  --bind-host "$DASHBOARD_BIND_HOST" \
  --port "$DASHBOARD_PORT" \
  --out-base "$OUT_BASE" \
  --history-root "$HISTORY_ROOT" \
  $DASHBOARD_MODE_FLAG
