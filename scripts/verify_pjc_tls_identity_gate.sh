#!/usr/bin/env bash
# S7 PJC mTLS identity gate verification.
#
# Cases:
#   case-1 POSITIVE — valid CA-signed cert + matching expected fingerprint +
#                     matching expected peer identity → decision=allow.
#   case-2 NEGATIVE — wrong fingerprint → reason_code=fingerprint_mismatch.
#   case-3 NEGATIVE — wrong expected peer identity (job-bound SAN/CN) →
#                     reason_code=peer_identity_mismatch.
#   case-4 NEGATIVE — expired cert (notAfter in past) → reason_code=cert_expired.
#   case-5 NEGATIVE — not-yet-valid cert (notBefore in future) →
#                     reason_code=cert_not_yet_valid.
#   case-6 NEGATIVE — cert signed by an unrelated CA → reason_code=ca_mismatch.
#   case-7 SCHEMA   — every report validates against pjc_tls_identity_check/v1.
#
# Usage:
#   bash scripts/verify_pjc_tls_identity_gate.sh [--keep-out-dir]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CHECK_PY="$SCRIPT_DIR/check_pjc_tls_identity.py"
VALIDATE_PY="$SCRIPT_DIR/validate_json_contract.py"
SCHEMA="$REPO_ROOT/schemas/pjc_tls_identity_check.schema.json"

KEEP_OUT_DIR=0
for arg in "$@"; do
  case "$arg" in
    --keep-out-dir) KEEP_OUT_DIR=1 ;;
    *) echo "[ERROR] unknown argument: $arg" >&2; exit 1 ;;
  esac
done

OUT_ROOT="$(mktemp -d /tmp/seccomp_pjc_tls_id.XXXXXX)"
cleanup() {
  if [[ "$KEEP_OUT_DIR" -eq 0 ]]; then
    rm -rf "$OUT_ROOT"
  else
    echo "[info] output preserved at: $OUT_ROOT"
  fi
}
trap cleanup EXIT

# ----- generate certs (CA + valid + expired + not-yet-valid + foreign-CA-signed)
python3 - "$OUT_ROOT" <<'PY'
import datetime, os, sys
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

OUT = sys.argv[1]
NOW = datetime.datetime.now(datetime.timezone.utc)

def write_pem(path, data): open(path, "wb").write(data)
def keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)
def name(cn): return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
def san(dns): return x509.SubjectAlternativeName([x509.DNSName(d) for d in dns])

# ----- CA #1
ca_key = keypair()
ca_cert = (
    x509.CertificateBuilder()
    .subject_name(name("seccomp-test-ca")).issuer_name(name("seccomp-test-ca"))
    .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
    .not_valid_before(NOW - datetime.timedelta(days=1))
    .not_valid_after(NOW + datetime.timedelta(days=30))
    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    .sign(ca_key, hashes.SHA256())
)
write_pem(f"{OUT}/ca.crt", ca_cert.public_bytes(serialization.Encoding.PEM))

# ----- foreign CA #2
foreign_ca_key = keypair()
foreign_ca_cert = (
    x509.CertificateBuilder()
    .subject_name(name("foreign-ca")).issuer_name(name("foreign-ca"))
    .public_key(foreign_ca_key.public_key()).serial_number(x509.random_serial_number())
    .not_valid_before(NOW - datetime.timedelta(days=1))
    .not_valid_after(NOW + datetime.timedelta(days=30))
    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    .sign(foreign_ca_key, hashes.SHA256())
)
write_pem(f"{OUT}/foreign_ca.crt", foreign_ca_cert.public_bytes(serialization.Encoding.PEM))

def issue(cn, dns_names, *, signer_key=ca_key, signer_cert=ca_cert,
          not_before=None, not_after=None, fname="cert"):
    leaf_key = keypair()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name(cn)).issuer_name(signer_cert.subject)
        .public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(not_before or (NOW - datetime.timedelta(days=1)))
        .not_valid_after(not_after or (NOW + datetime.timedelta(days=10)))
        .add_extension(san(dns_names), critical=False)
        .sign(signer_key, hashes.SHA256())
    )
    write_pem(f"{OUT}/{fname}.crt", cert.public_bytes(serialization.Encoding.PEM))
    write_pem(f"{OUT}/{fname}.key", leaf_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

# Valid leaf
issue("job-abc.partyA.example", ["job-abc.partyA.example"], fname="server_valid")
# Expired leaf
issue("job-abc.partyA.example", ["job-abc.partyA.example"],
      not_before=NOW - datetime.timedelta(days=30),
      not_after=NOW - datetime.timedelta(days=1),
      fname="server_expired")
# Not-yet-valid leaf
issue("job-abc.partyA.example", ["job-abc.partyA.example"],
      not_before=NOW + datetime.timedelta(days=2),
      not_after=NOW + datetime.timedelta(days=30),
      fname="server_future")
# Foreign-CA-signed leaf
issue("job-abc.partyA.example", ["job-abc.partyA.example"],
      signer_key=foreign_ca_key, signer_cert=foreign_ca_cert,
      fname="server_foreign_ca")
print("certs written under", OUT)
PY

PASS=1
EXPECTED_SAN="job-abc.partyA.example"
JOB_ID="abc"

# Compute the actual fingerprint for the valid cert
GOOD_FP="$(python3 -c "
import hashlib
from cryptography import x509
from cryptography.hazmat.primitives import serialization
c = x509.load_pem_x509_certificate(open('$OUT_ROOT/server_valid.crt','rb').read())
print(hashlib.sha256(c.public_bytes(serialization.Encoding.DER)).hexdigest())
")"
BAD_FP="0000000000000000000000000000000000000000000000000000000000000000"

decision_field() {
  python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],'MISSING'))" "$1" "$2"
}

# ----- case-1 POSITIVE
REPORT1="$OUT_ROOT/r1.json"
echo "[case-1] valid cert + matching fingerprint + matching peer identity (expect allow)"
set +e
python3 "$CHECK_PY" \
  --cert "$OUT_ROOT/server_valid.crt" \
  --ca-cert "$OUT_ROOT/ca.crt" \
  --role server --job-id "$JOB_ID" \
  --expected-fingerprint-sha256 "$GOOD_FP" \
  --expected-peer-identity "$EXPECTED_SAN" \
  --output "$REPORT1" --assert-allow > /dev/null 2> "$OUT_ROOT/r1.err"
RC1=$?
set -e
if [[ "$RC1" -ne 0 ]]; then
  echo "[FAIL] case-1 expected exit 0; got $RC1"; cat "$OUT_ROOT/r1.err" >&2; PASS=0
fi
if [[ "$(decision_field "$REPORT1" decision)" != "allow" ]]; then
  echo "[FAIL] case-1 expected decision=allow"; PASS=0
fi

# ----- case-2 NEGATIVE wrong fingerprint
REPORT2="$OUT_ROOT/r2.json"
echo "[case-2] wrong expected fingerprint (expect deny fingerprint_mismatch)"
set +e
python3 "$CHECK_PY" \
  --cert "$OUT_ROOT/server_valid.crt" \
  --role server --job-id "$JOB_ID" \
  --expected-fingerprint-sha256 "$BAD_FP" \
  --expected-peer-identity "$EXPECTED_SAN" \
  --output "$REPORT2" --assert-allow > /dev/null 2> "$OUT_ROOT/r2.err"
RC2=$?
set -e
if [[ "$RC2" -eq 0 ]]; then
  echo "[FAIL] case-2 expected non-zero exit"; PASS=0
fi
if [[ "$(decision_field "$REPORT2" reason_code)" != "fingerprint_mismatch" ]]; then
  echo "[FAIL] case-2 expected reason_code=fingerprint_mismatch"; PASS=0
fi

# ----- case-3 NEGATIVE wrong peer identity
REPORT3="$OUT_ROOT/r3.json"
echo "[case-3] wrong expected peer identity (expect deny peer_identity_mismatch)"
set +e
python3 "$CHECK_PY" \
  --cert "$OUT_ROOT/server_valid.crt" \
  --role server --job-id "$JOB_ID" \
  --expected-peer-identity "job-zzz.partyB.example" \
  --output "$REPORT3" --assert-allow > /dev/null 2> "$OUT_ROOT/r3.err"
RC3=$?
set -e
if [[ "$RC3" -eq 0 ]]; then
  echo "[FAIL] case-3 expected non-zero exit"; PASS=0
fi
if [[ "$(decision_field "$REPORT3" reason_code)" != "peer_identity_mismatch" ]]; then
  echo "[FAIL] case-3 expected reason_code=peer_identity_mismatch"; PASS=0
fi

# ----- case-4 NEGATIVE expired cert
REPORT4="$OUT_ROOT/r4.json"
echo "[case-4] expired cert (expect deny cert_expired)"
set +e
python3 "$CHECK_PY" \
  --cert "$OUT_ROOT/server_expired.crt" \
  --role server --job-id "$JOB_ID" \
  --expected-peer-identity "$EXPECTED_SAN" \
  --output "$REPORT4" --assert-allow > /dev/null 2> "$OUT_ROOT/r4.err"
RC4=$?
set -e
if [[ "$RC4" -eq 0 ]]; then
  echo "[FAIL] case-4 expected non-zero exit"; PASS=0
fi
if [[ "$(decision_field "$REPORT4" reason_code)" != "cert_expired" ]]; then
  echo "[FAIL] case-4 expected reason_code=cert_expired, got $(decision_field "$REPORT4" reason_code)"; PASS=0
fi

# ----- case-5 NEGATIVE not-yet-valid
REPORT5="$OUT_ROOT/r5.json"
echo "[case-5] not-yet-valid cert (expect deny cert_not_yet_valid)"
set +e
python3 "$CHECK_PY" \
  --cert "$OUT_ROOT/server_future.crt" \
  --role server --job-id "$JOB_ID" \
  --expected-peer-identity "$EXPECTED_SAN" \
  --output "$REPORT5" --assert-allow > /dev/null 2> "$OUT_ROOT/r5.err"
RC5=$?
set -e
if [[ "$RC5" -eq 0 ]]; then
  echo "[FAIL] case-5 expected non-zero exit"; PASS=0
fi
if [[ "$(decision_field "$REPORT5" reason_code)" != "cert_not_yet_valid" ]]; then
  echo "[FAIL] case-5 expected reason_code=cert_not_yet_valid, got $(decision_field "$REPORT5" reason_code)"; PASS=0
fi

# ----- case-6 NEGATIVE foreign-CA cert
REPORT6="$OUT_ROOT/r6.json"
echo "[case-6] foreign-CA-signed cert (expect deny ca_mismatch)"
set +e
python3 "$CHECK_PY" \
  --cert "$OUT_ROOT/server_foreign_ca.crt" \
  --ca-cert "$OUT_ROOT/ca.crt" \
  --role server --job-id "$JOB_ID" \
  --expected-peer-identity "$EXPECTED_SAN" \
  --output "$REPORT6" --assert-allow > /dev/null 2> "$OUT_ROOT/r6.err"
RC6=$?
set -e
if [[ "$RC6" -eq 0 ]]; then
  echo "[FAIL] case-6 expected non-zero exit"; PASS=0
fi
if [[ "$(decision_field "$REPORT6" reason_code)" != "ca_mismatch" ]]; then
  echo "[FAIL] case-6 expected reason_code=ca_mismatch, got $(decision_field "$REPORT6" reason_code)"; PASS=0
fi

# ----- case-7 SCHEMA validation
echo "[case-7] schema validation across reports"
for f in "$REPORT1" "$REPORT2" "$REPORT3" "$REPORT4" "$REPORT5" "$REPORT6"; do
  if ! python3 "$VALIDATE_PY" --schema "$SCHEMA" --json "$f" > /dev/null; then
    echo "[FAIL] case-7 $f failed schema validation"; PASS=0
  fi
done

if [[ "$PASS" -ne 1 ]]; then
  exit 1
fi

echo "[ok] PJC mTLS identity gate verified: case-1 (allow) + case-2 (fingerprint) + case-3 (peer_identity) + case-4 (expired) + case-5 (not_yet_valid) + case-6 (ca_mismatch) + case-7 (schemas)"
