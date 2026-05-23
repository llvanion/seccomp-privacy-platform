#!/usr/bin/env bash
set -euo pipefail

# Party B helper: generate client.key locally, submit only a CSR to Party A's
# dashboard enrollment endpoint, and store ca.crt + client.crt next to the key.

SERVER_HOST="${SERVER_HOST:-}"
DASHBOARD_PORT="${DASHBOARD_PORT:-18134}"
PJC_MTLS_ENROLL_URL="${PJC_MTLS_ENROLL_URL:-}"
PJC_MTLS_BOOTSTRAP="${PJC_MTLS_BOOTSTRAP:-}"
PJC_MTLS_PAIRING_TOKEN="${PJC_MTLS_PAIRING_TOKEN:-${PAIRING_TOKEN:-}}"
CERT_DIR="${CERT_DIR:-$HOME/pjc_certs_shared}"
EXPECTED_CA_FINGERPRINT="${EXPECTED_CA_FINGERPRINT:-${PJC_MTLS_EXPECTED_CA_FINGERPRINT:-}}"
ALLOW_UNVERIFIED_CA="${ALLOW_UNVERIFIED_CA:-0}"

command -v openssl >/dev/null || { echo "[error] openssl not found" >&2; exit 1; }
command -v python3 >/dev/null || { echo "[error] python3 not found" >&2; exit 1; }

if [[ -n "$PJC_MTLS_BOOTSTRAP" ]]; then
  if ! BOOTSTRAP_OUTPUT="$(python3 - "$PJC_MTLS_BOOTSTRAP" <<'PY'
import sys
from urllib.parse import parse_qs, urlparse

raw = sys.argv[1].strip()
parsed = urlparse(raw)
if parsed.scheme != "pjc-mtls" or parsed.netloc != "enroll":
    raise SystemExit("[error] PJC_MTLS_BOOTSTRAP must start with pjc-mtls://enroll")
params = parse_qs(parsed.query, keep_blank_values=False)
def one(name: str) -> str:
    values = params.get(name) or []
    if len(values) != 1 or not values[0].strip():
        raise SystemExit(f"[error] bootstrap URI missing {name}")
    return values[0].strip()
print(one("url"))
print(one("token"))
print(one("ca_sha256"))
PY
  )"; then
    exit 1
  fi
  mapfile -t BOOTSTRAP_PARTS <<< "$BOOTSTRAP_OUTPUT"
  [[ "${#BOOTSTRAP_PARTS[@]}" -eq 3 ]] || {
    echo "[error] bootstrap URI parse returned an unexpected field count" >&2
    exit 1
  }
  PJC_MTLS_ENROLL_URL="${PJC_MTLS_ENROLL_URL:-${BOOTSTRAP_PARTS[0]}}"
  PJC_MTLS_PAIRING_TOKEN="${PJC_MTLS_PAIRING_TOKEN:-${BOOTSTRAP_PARTS[1]}}"
  EXPECTED_CA_FINGERPRINT="${EXPECTED_CA_FINGERPRINT:-${BOOTSTRAP_PARTS[2]}}"
fi

if [[ -z "$PJC_MTLS_ENROLL_URL" ]]; then
  if [[ -z "$SERVER_HOST" ]]; then
    echo "[error] set SERVER_HOST=<party-a-host>, PJC_MTLS_ENROLL_URL=<url>, or PJC_MTLS_BOOTSTRAP=<pjc-mtls://...>" >&2
    exit 1
  fi
  PJC_MTLS_ENROLL_URL="http://${SERVER_HOST}:${DASHBOARD_PORT}/v1/pjc-mtls/enroll"
fi

if [[ -z "$PJC_MTLS_PAIRING_TOKEN" ]]; then
  echo "[error] set PJC_MTLS_PAIRING_TOKEN=<token printed by Party A>" >&2
  exit 1
fi

if [[ -z "$EXPECTED_CA_FINGERPRINT" && "$ALLOW_UNVERIFIED_CA" != "1" ]]; then
  echo "[error] set EXPECTED_CA_FINGERPRINT=<SHA256 fingerprint printed by Party A>" >&2
  echo "        (verify it through an independent channel; or set ALLOW_UNVERIFIED_CA=1 to skip)" >&2
  exit 1
fi

python3 - "$PJC_MTLS_ENROLL_URL" "$PJC_MTLS_PAIRING_TOKEN" "$CERT_DIR" "$EXPECTED_CA_FINGERPRINT" <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib import request

enroll_url, pairing_token, cert_dir_raw, expected_fp_raw = sys.argv[1:5]
cert_dir = Path(cert_dir_raw).expanduser().resolve()


def _normalize_fp(value: str) -> str:
    text = value.strip()
    if "=" in text:
        text = text.split("=", 1)[1]
    return text.replace(":", "").replace(" ", "").lower()


expected_fp_norm = _normalize_fp(expected_fp_raw) if expected_fp_raw else ""
cert_dir.mkdir(parents=True, exist_ok=True)
cert_dir.chmod(0o700)

key_path = cert_dir / "client.key"
csr_path = cert_dir / "client.csr"
if not key_path.is_file():
    subprocess.run(["openssl", "genrsa", "-out", str(key_path), "4096"], check=True)
    key_path.chmod(0o600)

subprocess.run(
    [
        "openssl",
        "req",
        "-new",
        "-key",
        str(key_path),
        "-out",
        str(csr_path),
        "-subj",
        "/CN=pjc-client/O=PJC-TLS",
    ],
    check=True,
)

payload = json.dumps(
    {
        "pairing_token": pairing_token,
        "csr_pem": csr_path.read_text(encoding="utf-8"),
    },
    ensure_ascii=False,
).encode("utf-8")
req = request.Request(
    enroll_url,
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
opener = request.build_opener(request.ProxyHandler({}))
with opener.open(req, timeout=30) as resp:
    response = json.loads(resp.read().decode("utf-8"))

if response.get("status") != "ok":
    raise SystemExit(f"[error] enrollment failed: {response}")

returned_fp = str(response.get("fingerprint") or "")
returned_fp_norm = _normalize_fp(returned_fp)
if expected_fp_norm:
    if not returned_fp_norm:
        raise SystemExit("[error] enrollment response omitted CA fingerprint; refusing to trust CA")
    if returned_fp_norm != expected_fp_norm:
        raise SystemExit(
            "[error] CA fingerprint mismatch — refusing enrollment\n"
            f"  expected: {expected_fp_raw.strip()}\n"
            f"  returned: {returned_fp}"
        )

ca_crt_text = response["ca_crt"]
ca_path = cert_dir / "ca.crt"
ca_path.write_text(ca_crt_text, encoding="utf-8")
ca_path.chmod(0o644)

local_fp = subprocess.run(
    ["openssl", "x509", "-in", str(ca_path), "-fingerprint", "-sha256", "-noout"],
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=True,
).stdout
local_fp_norm = _normalize_fp(local_fp)
if expected_fp_norm and local_fp_norm != expected_fp_norm:
    raise SystemExit(
        "[error] CA file fingerprint mismatch — refusing enrollment\n"
        f"  expected: {expected_fp_raw.strip()}\n"
        f"  local:    {local_fp.strip()}"
    )

(cert_dir / "client.crt").write_text(response["client_crt"], encoding="utf-8")
(cert_dir / "client.crt").chmod(0o644)

verify = subprocess.run(
    ["openssl", "verify", "-CAfile", str(cert_dir / "ca.crt"), str(cert_dir / "client.crt")],
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=False,
)
if verify.returncode != 0:
    raise SystemExit(verify.stderr or verify.stdout)

print(f"[ok] cert bundle stored at: {cert_dir}")
print(f"[ok] {verify.stdout.strip()}")
print(f"[info] CA fingerprint: {returned_fp or local_fp.strip()}")
if expected_fp_norm:
    print("[ok] CA fingerprint matched EXPECTED_CA_FINGERPRINT")
else:
    print("[warn] EXPECTED_CA_FINGERPRINT was unset (ALLOW_UNVERIFIED_CA=1) — TOFU only")
print("[info] client.key stayed local on Party B")
PY
