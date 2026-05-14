#!/usr/bin/env bash
# S2 production KMS gate verification.
#
# Asserts that scripts/check_kms_reachability.py --production-mode rejects
# configurations that would let secret material come from local environment
# variables or local vault_kv fixtures only, and accepts only when a live HTTP
# KMS/Vault reachability check is actually reachable.
#
# Cases:
#   case-1 POSITIVE — production-mode check against the production keyring
#                     example plus a reachable external_kms_http endpoint exits
#                     0, production_mode=true, production_findings=[].
#   case-2 NEGATIVE — production-mode reachability check with only
#                     --env-var BRIDGE_TOKEN_SECRET (no real KMS source)
#                     exits non-zero with overall_status=error and a
#                     production_no_reachable_real_kms_backend finding.
#   case-3 NEGATIVE — production-mode reachability check against the
#                     development keyring (config/keyring.example.json,
#                     all secret_ref.kind=env) exits non-zero with a
#                     production_keyring_no_real_kms_backed_key finding.
#   case-4 NEGATIVE — production-mode with a syntactically valid but skipped
#                     external KMS config exits non-zero.
#   case-5 NEGATIVE — production-mode with an active vault_kv keyring fixture
#                     is rejected even if a reachable HTTP endpoint is present.
#
# Usage:
#   bash scripts/verify_production_kms_gate.sh [--keep-out-dir]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CHECK_PY="$SCRIPT_DIR/check_kms_reachability.py"

KEEP_OUT_DIR=0
for arg in "$@"; do
  case "$arg" in
    --keep-out-dir) KEEP_OUT_DIR=1 ;;
    *) echo "[ERROR] unknown argument: $arg" >&2; exit 1 ;;
  esac
done

OUT_ROOT="$(mktemp -d /tmp/seccomp_prod_kms.XXXXXX)"
HTTP_PID=""
cleanup() {
  if [[ -n "$HTTP_PID" ]]; then
    kill "$HTTP_PID" >/dev/null 2>&1 || true
  fi
  if [[ "$KEEP_OUT_DIR" -eq 0 ]]; then
    rm -rf "$OUT_ROOT"
  else
    echo "[info] output preserved at: $OUT_ROOT"
  fi
}
trap cleanup EXIT

PASS=1

PORT="$(python3 "$SCRIPT_DIR/runtime_service_helpers.py" available-port)"
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$OUT_ROOT" >/dev/null 2>&1 &
HTTP_PID="$!"
python3 "$SCRIPT_DIR/runtime_service_helpers.py" wait-tcp-port --host 127.0.0.1 --port "$PORT" --timeout-sec 5
REACHABLE_EXTERNAL_KMS_CONFIG="$OUT_ROOT/reachable_external_kms.json"
python3 - "$REACHABLE_EXTERNAL_KMS_CONFIG" "$PORT" <<'PY'
import json, sys
path, port = sys.argv[1:]
with open(path, "w", encoding="utf-8") as f:
    json.dump(
        {
            "schema": "external_kms_config/v1",
            "endpoint_url": f"http://127.0.0.1:{port}",
        },
        f,
    )
PY

###################################################################
# case-1 POSITIVE: production keyring + reachable HTTP KMS passes
###################################################################
POS_REPORT="$OUT_ROOT/positive.json"
POS_KEYRING="$REPO_ROOT/config/keyring.production.example.json"
echo "[case-1] production keyring + reachable external_kms_http (expect ok)"
set +e
python3 "$CHECK_PY" \
  --keyring "$POS_KEYRING" \
  --external-kms-config "$REACHABLE_EXTERNAL_KMS_CONFIG" \
  --output "$POS_REPORT" \
  --production-mode \
  --assert-ok > /dev/null 2> "$OUT_ROOT/positive.err"
POS_RC=$?
set -e
POS_OVERALL="$(python3 -c "import json; print(json.load(open('$POS_REPORT')).get('overall_status','MISSING'))")"
POS_PROD="$(python3 -c "import json; print(json.load(open('$POS_REPORT')).get('production_mode','MISSING'))")"
POS_FINDS="$(python3 -c "import json; print(len(json.load(open('$POS_REPORT')).get('production_findings') or []))")"
if [[ "$POS_RC" -ne 0 ]]; then
  echo "[FAIL] case-1 expected exit 0; got $POS_RC. stderr:" >&2
  cat "$OUT_ROOT/positive.err" >&2
  PASS=0
fi
if [[ "$POS_OVERALL" != "ok" ]]; then
  echo "[FAIL] case-1 expected overall_status=ok, got=$POS_OVERALL" >&2; PASS=0
fi
if [[ "$POS_PROD" != "True" ]]; then
  echo "[FAIL] case-1 expected production_mode=True, got=$POS_PROD" >&2; PASS=0
fi
if [[ "$POS_FINDS" != "0" ]]; then
  echo "[FAIL] case-1 expected zero production_findings, got=$POS_FINDS" >&2; PASS=0
fi

###################################################################
# case-2 NEGATIVE: env-var-only backends rejected
###################################################################
NEG1_REPORT="$OUT_ROOT/negative_env_only.json"
echo "[case-2] env-var-only backends + --production-mode (expect error)"
set +e
BRIDGE_TOKEN_SECRET=local-dev-secret \
  python3 "$CHECK_PY" \
    --env-var BRIDGE_TOKEN_SECRET \
    --output "$NEG1_REPORT" \
    --production-mode \
    --assert-ok > /dev/null 2> "$OUT_ROOT/negative_env_only.err"
NEG1_RC=$?
set -e
if [[ "$NEG1_RC" -eq 0 ]]; then
  echo "[FAIL] case-2 expected non-zero exit; got 0" >&2; PASS=0
fi
NEG1_OVERALL="$(python3 -c "import json; print(json.load(open('$NEG1_REPORT')).get('overall_status','MISSING'))")"
NEG1_KIND="$(python3 -c "
import json
findings = json.load(open('$NEG1_REPORT')).get('production_findings') or []
hits = [f for f in findings if f.get('kind') == 'production_no_reachable_real_kms_backend']
print('hit' if hits else 'miss')
")"
if [[ "$NEG1_OVERALL" != "error" ]]; then
  echo "[FAIL] case-2 expected overall_status=error, got=$NEG1_OVERALL" >&2; PASS=0
fi
if [[ "$NEG1_KIND" != "hit" ]]; then
  echo "[FAIL] case-2 expected finding kind=production_no_reachable_real_kms_backend; not present" >&2; PASS=0
fi

###################################################################
# case-3 NEGATIVE: env-only keyring rejected
###################################################################
NEG2_REPORT="$OUT_ROOT/negative_env_keyring.json"
DEV_KEYRING="$REPO_ROOT/config/keyring.example.json"
echo "[case-3] env-only keyring + --production-mode (expect error with no_real_kms_backed_key finding)"
set +e
python3 "$CHECK_PY" \
  --keyring "$DEV_KEYRING" \
  --output "$NEG2_REPORT" \
  --production-mode \
  --assert-ok > /dev/null 2> "$OUT_ROOT/negative_env_keyring.err"
NEG2_RC=$?
set -e
if [[ "$NEG2_RC" -eq 0 ]]; then
  echo "[FAIL] case-3 expected non-zero exit; got 0" >&2; PASS=0
fi
NEG2_OVERALL="$(python3 -c "import json; print(json.load(open('$NEG2_REPORT')).get('overall_status','MISSING'))")"
NEG2_KIND="$(python3 -c "
import json
findings = json.load(open('$NEG2_REPORT')).get('production_findings') or []
hits = [f for f in findings if f.get('kind') == 'production_keyring_no_real_kms_backed_key']
print('hit' if hits else 'miss')
")"
if [[ "$NEG2_OVERALL" != "error" ]]; then
  echo "[FAIL] case-3 expected overall_status=error, got=$NEG2_OVERALL" >&2; PASS=0
fi
if [[ "$NEG2_KIND" != "hit" ]]; then
  echo "[FAIL] case-3 expected finding kind=production_keyring_no_real_kms_backed_key; not present" >&2; PASS=0
fi

###################################################################
# case-4 NEGATIVE: skipped real-backend config rejected
###################################################################
NEG3_REPORT="$OUT_ROOT/negative_skipped_external_kms.json"
SKIPPED_EXTERNAL_KMS_CONFIG="$OUT_ROOT/skipped_external_kms.json"
printf '{"schema":"external_kms_config/v1"}\n' > "$SKIPPED_EXTERNAL_KMS_CONFIG"
echo "[case-4] skipped external KMS config + --production-mode (expect skipped-config finding)"
set +e
python3 "$CHECK_PY" \
  --external-kms-config "$SKIPPED_EXTERNAL_KMS_CONFIG" \
  --output "$NEG3_REPORT" \
  --production-mode \
  --assert-ok > /dev/null 2> "$OUT_ROOT/negative_skipped_external_kms.err"
NEG3_RC=$?
set -e
if [[ "$NEG3_RC" -eq 0 ]]; then
  echo "[FAIL] case-4 expected non-zero exit; got 0" >&2; PASS=0
fi
NEG3_KIND="$(python3 -c "
import json
findings = json.load(open('$NEG3_REPORT')).get('production_findings') or []
hits = [f for f in findings if f.get('kind') == 'production_real_kms_config_skipped']
print('hit' if hits else 'miss')
")"
if [[ "$NEG3_KIND" != "hit" ]]; then
  echo "[FAIL] case-4 expected finding kind=production_real_kms_config_skipped; not present" >&2; PASS=0
fi

###################################################################
# case-5 NEGATIVE: vault_kv active keyring remains local fixture
###################################################################
NEG4_REPORT="$OUT_ROOT/negative_vault_kv_keyring.json"
VAULT_KV_KEYRING="$OUT_ROOT/vault_kv_keyring.json"
python3 - "$VAULT_KV_KEYRING" <<'PY'
import json, sys
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(
        {
            "schema": "keyring/v1",
            "keys": {
                "bridge-token": {
                    "purpose": "bridge_token",
                    "active_version": "v1",
                    "versions": {
                        "v1": {
                            "enabled": True,
                            "status": "active",
                            "created_at_utc": "2026-05-14T00:00:00Z",
                            "secret_ref": {"kind": "vault_kv", "name": "bridge-token"},
                        }
                    },
                }
            },
        },
        f,
    )
PY
echo "[case-5] vault_kv active keyring + reachable HTTP endpoint (expect no_real_kms_backed_key finding)"
set +e
python3 "$CHECK_PY" \
  --keyring "$VAULT_KV_KEYRING" \
  --external-kms-config "$REACHABLE_EXTERNAL_KMS_CONFIG" \
  --output "$NEG4_REPORT" \
  --production-mode \
  --assert-ok > /dev/null 2> "$OUT_ROOT/negative_vault_kv_keyring.err"
NEG4_RC=$?
set -e
if [[ "$NEG4_RC" -eq 0 ]]; then
  echo "[FAIL] case-5 expected non-zero exit; got 0" >&2; PASS=0
fi
NEG4_KIND="$(python3 -c "
import json
findings = json.load(open('$NEG4_REPORT')).get('production_findings') or []
hits = [f for f in findings if f.get('kind') == 'production_keyring_no_real_kms_backed_key']
print('hit' if hits else 'miss')
")"
if [[ "$NEG4_KIND" != "hit" ]]; then
  echo "[FAIL] case-5 expected finding kind=production_keyring_no_real_kms_backed_key; not present" >&2; PASS=0
fi

if [[ "$PASS" -ne 1 ]]; then
  exit 1
fi

echo "[ok] production KMS gate verified: reachable real backend required, env/skipped/vault_kv fixture paths rejected"
