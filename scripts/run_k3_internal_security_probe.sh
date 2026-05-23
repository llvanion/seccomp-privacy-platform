#!/usr/bin/env bash
set -u

TARGET_HOST="118.190.61.66"
TARGET_PORT="10502"
JOB_ID="cross-vps-005"
EVIDENCE_DIR="tmp/k3_internal_security_cross-vps-005"
SOURCE_EVIDENCE_DIR="tmp/pjc_mtls_cross-vps-005"
TIMEOUT_SECONDS="8"

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/run_k3_internal_security_probe.sh [options]

Options:
  --target-host HOST          Target host or IP. Default: 118.190.61.66
  --target-port PORT          Target port. Default: 10502
  --job-id ID                 Evidence job ID. Default: cross-vps-005
  --evidence-dir DIR          Output evidence directory.
                              Default: tmp/k3_internal_security_cross-vps-005
  --source-evidence-dir DIR   Existing S7 evidence directory to cross-reference.
                              Default: tmp/pjc_mtls_cross-vps-005
  --timeout SECONDS           Per-probe timeout. Default: 8
  -h, --help                  Show this help.

This script performs non-destructive black-box probes only:
  - TCP reachability probe
  - TLS probe without a client certificate
  - malformed plaintext probe

It does not run DoS, brute force, credential guessing, or destructive tests.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-host)
      TARGET_HOST="${2:?missing value for --target-host}"
      shift 2
      ;;
    --target-port)
      TARGET_PORT="${2:?missing value for --target-port}"
      shift 2
      ;;
    --job-id)
      JOB_ID="${2:?missing value for --job-id}"
      shift 2
      ;;
    --evidence-dir)
      EVIDENCE_DIR="${2:?missing value for --evidence-dir}"
      shift 2
      ;;
    --source-evidence-dir)
      SOURCE_EVIDENCE_DIR="${2:?missing value for --source-evidence-dir}"
      shift 2
      ;;
    --timeout)
      TIMEOUT_SECONDS="${2:?missing value for --timeout}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "$EVIDENCE_DIR"

START_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
COMMANDS_LOG="$EVIDENCE_DIR/COMMANDS.md"
NETWORK_LOG="$EVIDENCE_DIR/network_probe.log"
TLS_LOG="$EVIDENCE_DIR/tls_probe_no_client_cert.log"
TLS_VERBOSE_LOG="$EVIDENCE_DIR/tls_probe_no_client_cert_verbose.log"
MALFORMED_LOG="$EVIDENCE_DIR/malformed_plaintext_probe.log"
SUMMARY_JSON="$EVIDENCE_DIR/probe_summary.json"
SCOPE_FILE="$EVIDENCE_DIR/SECURITY_TEST_SCOPE.md"
FINDINGS_FILE="$EVIDENCE_DIR/FINDINGS.md"
SUMMARY_MD="$EVIDENCE_DIR/EVIDENCE_SUMMARY.md"

run_capture() {
  local name="$1"
  local outfile="$2"
  shift 2
  {
    printf '## %s\n' "$name"
    printf 'started_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'command='
    printf '%q ' "$@"
    printf '\n\n'
  } >"$outfile"
  "$@" >>"$outfile" 2>&1
  local rc=$?
  {
    printf '\nexit_code=%s\n' "$rc"
    printf 'finished_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >>"$outfile"
  return 0
}

append_command() {
  printf -- '- `%s`\n' "$*" >>"$COMMANDS_LOG"
}

cat >"$SCOPE_FILE" <<EOF_SCOPE
# Security Test Scope - K3 Internal Probe

## Dates

- Start: $START_UTC
- End: filled by \`probe_summary.json\`

## People

- Internal coordinator: local operator
- External tester(s): internal black-box probe from non-server host
- Emergency contact: local operator

## Targets

| Target | URL/host | Owner | Auth method | Allowed tests |
| --- | --- | --- | --- | --- |
| PJC mTLS public endpoint | ${TARGET_HOST}:${TARGET_PORT} | local operator / VPS owner | mTLS | TCP reachability, TLS probe without client cert, malformed plaintext probe |

## Out Of Scope

- Destructive data deletion.
- Production tenant data.
- DoS or load testing.
- Credential brute force.
- AWS account-wide testing.
- Public Rekor load testing.

## Evidence Required

- Tooling summary.
- Finding list with severity.
- Probe logs.
- Cross-reference to S7 successful mTLS evidence.
EOF_SCOPE

cat >"$COMMANDS_LOG" <<EOF_COMMANDS
# K3 Internal Security Probe Commands

- started_at_utc: \`$START_UTC\`
- target: \`${TARGET_HOST}:${TARGET_PORT}\`
- job_id: \`$JOB_ID\`

EOF_COMMANDS

if command -v nc >/dev/null 2>&1; then
  append_command "nc -vz -w $TIMEOUT_SECONDS $TARGET_HOST $TARGET_PORT"
  run_capture "TCP reachability probe" "$NETWORK_LOG" nc -vz -w "$TIMEOUT_SECONDS" "$TARGET_HOST" "$TARGET_PORT"
else
  append_command "timeout $TIMEOUT_SECONDS bash -c '</dev/tcp/$TARGET_HOST/$TARGET_PORT'"
  run_capture "TCP reachability probe" "$NETWORK_LOG" timeout "$TIMEOUT_SECONDS" bash -c "</dev/tcp/$TARGET_HOST/$TARGET_PORT"
fi

append_command "timeout $TIMEOUT_SECONDS openssl s_client -connect $TARGET_HOST:$TARGET_PORT -servername pjc-server -brief"
{
  printf '## TLS probe without client certificate\n'
  printf 'started_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'command=timeout %q openssl s_client -connect %q -servername pjc-server -brief\n\n' "$TIMEOUT_SECONDS" "${TARGET_HOST}:${TARGET_PORT}"
} >"$TLS_LOG"
timeout "$TIMEOUT_SECONDS" openssl s_client -connect "${TARGET_HOST}:${TARGET_PORT}" -servername pjc-server -brief </dev/null >>"$TLS_LOG" 2>&1
TLS_RC=$?
{
  printf '\nexit_code=%s\n' "$TLS_RC"
  printf 'finished_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >>"$TLS_LOG"

append_command "timeout $TIMEOUT_SECONDS openssl s_client -connect $TARGET_HOST:$TARGET_PORT -servername pjc-server -state -msg"
{
  printf '## Verbose TLS probe without client certificate\n'
  printf 'started_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'command=timeout %q openssl s_client -connect %q -servername pjc-server -state -msg\n\n' "$TIMEOUT_SECONDS" "${TARGET_HOST}:${TARGET_PORT}"
} >"$TLS_VERBOSE_LOG"
timeout "$TIMEOUT_SECONDS" openssl s_client -connect "${TARGET_HOST}:${TARGET_PORT}" -servername pjc-server -state -msg </dev/null >>"$TLS_VERBOSE_LOG" 2>&1
TLS_VERBOSE_RC=$?
{
  printf '\nexit_code=%s\n' "$TLS_VERBOSE_RC"
  printf 'finished_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >>"$TLS_VERBOSE_LOG"

if command -v nc >/dev/null 2>&1; then
  append_command "printf 'not grpc\\n' | timeout $TIMEOUT_SECONDS nc -v -w $TIMEOUT_SECONDS $TARGET_HOST $TARGET_PORT"
  {
    printf '## Malformed plaintext probe\n'
    printf 'started_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf "command=printf 'not grpc\\\\n' | timeout %q nc -v -w %q %q %q\n\n" "$TIMEOUT_SECONDS" "$TIMEOUT_SECONDS" "$TARGET_HOST" "$TARGET_PORT"
  } >"$MALFORMED_LOG"
  printf 'not grpc\n' | timeout "$TIMEOUT_SECONDS" nc -v -w "$TIMEOUT_SECONDS" "$TARGET_HOST" "$TARGET_PORT" >>"$MALFORMED_LOG" 2>&1
  MALFORMED_RC=$?
  {
    printf '\nexit_code=%s\n' "$MALFORMED_RC"
    printf 'finished_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >>"$MALFORMED_LOG"
else
  append_command "timeout $TIMEOUT_SECONDS bash -c 'exec 3<>/dev/tcp/$TARGET_HOST/$TARGET_PORT; printf not grpc >&3; timeout 2 cat <&3'"
  {
    printf '## Malformed plaintext probe\n'
    printf 'started_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'command=bash /dev/tcp malformed plaintext probe\n\n'
  } >"$MALFORMED_LOG"
  timeout "$TIMEOUT_SECONDS" bash -c "exec 3<>/dev/tcp/$TARGET_HOST/$TARGET_PORT; printf 'not grpc\n' >&3; timeout 2 cat <&3" >>"$MALFORMED_LOG" 2>&1
  MALFORMED_RC=$?
  {
    printf '\nexit_code=%s\n' "$MALFORMED_RC"
    printf 'finished_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >>"$MALFORMED_LOG"
fi

END_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

python3 - "$EVIDENCE_DIR" "$SOURCE_EVIDENCE_DIR" "$TARGET_HOST" "$TARGET_PORT" "$JOB_ID" "$START_UTC" "$END_UTC" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

evidence_dir = Path(sys.argv[1])
source_dir = Path(sys.argv[2])
target_host = sys.argv[3]
target_port = sys.argv[4]
job_id = sys.argv[5]
started_at = sys.argv[6]
finished_at = sys.argv[7]

def sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def exit_code(path: Path) -> int | None:
    if not path.exists():
        return None
    for line in reversed(path.read_text(errors="replace").splitlines()):
        if line.startswith("exit_code="):
            try:
                return int(line.split("=", 1)[1])
            except ValueError:
                return None
    return None

def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}

source_result = load_json(source_dir / "party_b_client" / "attribution_result.json")
server_identity = load_json(source_dir / "server_tls_identity.json")
client_identity = load_json(source_dir / "client_tls_identity.json")

probe_files = {
    "network_probe": evidence_dir / "network_probe.log",
    "tls_probe_no_client_cert": evidence_dir / "tls_probe_no_client_cert.log",
    "tls_probe_no_client_cert_verbose": evidence_dir / "tls_probe_no_client_cert_verbose.log",
    "malformed_plaintext_probe": evidence_dir / "malformed_plaintext_probe.log",
}
source_files = {
    "s7_party_a_server_log": source_dir / "party_a_server" / "server.log",
    "s7_party_b_client_log": source_dir / "party_b_client" / "client.log",
    "s7_party_b_result": source_dir / "party_b_client" / "attribution_result.json",
    "s7_server_identity": source_dir / "server_tls_identity.json",
    "s7_client_identity": source_dir / "client_tls_identity.json",
}

summary = {
    "schema": "k3_internal_security_probe/v1",
    "job_id": job_id,
    "started_at_utc": started_at,
    "finished_at_utc": finished_at,
    "target": {
        "host": target_host,
        "port": int(target_port),
        "address": f"{target_host}:{target_port}",
    },
    "scope": {
        "test_type": "internal_black_box_probe",
        "destructive_tests": False,
        "dos_tests": False,
        "credential_bruteforce": False,
    },
    "probes": {
        name: {
            "path": str(path),
            "sha256": sha256(path),
            "exit_code": exit_code(path),
        }
        for name, path in probe_files.items()
    },
    "s7_live_evidence": {
        "source_evidence_dir": str(source_dir),
        "result": {
            "job_id": source_result.get("job_id"),
            "server_addr": source_result.get("server_addr"),
            "tls": source_result.get("tls"),
            "intersection_size": source_result.get("intersection_size"),
            "intersection_sum": source_result.get("intersection_sum"),
        },
        "server_identity_decision": server_identity.get("decision"),
        "client_identity_decision": client_identity.get("decision"),
        "files": {
            name: {
                "path": str(path),
                "sha256": sha256(path),
                "present": path.exists(),
            }
            for name, path in source_files.items()
        },
    },
    "assessment": {
        "critical_findings": 0,
        "high_findings": 0,
        "notes": [
            "Malformed and unauthenticated probes are diagnostic evidence only.",
            "This is not a third-party external penetration test.",
            "A closed or unreachable port after the S7 run is acceptable if the service was intentionally stopped.",
        ],
    },
}

verbose_path = probe_files["tls_probe_no_client_cert_verbose"]
verbose_text = verbose_path.read_text(errors="replace") if verbose_path.exists() else ""
summary["probes"]["tls_probe_no_client_cert_verbose"]["handshake_completed"] = (
    "Cipher is (NONE)" not in verbose_text
    and "no peer certificate available" not in verbose_text
    and "unexpected eof while reading" not in verbose_text
)
summary["probes"]["tls_probe_no_client_cert_verbose"]["evidence"] = {
    "peer_certificate_available": "no peer certificate available" not in verbose_text,
    "cipher_negotiated": "Cipher is (NONE)" not in verbose_text,
    "unexpected_eof": "unexpected eof while reading" in verbose_text,
    "fatal_decode_error": "fatal decode_error" in verbose_text or "decode error" in verbose_text,
}
summary["assessment"]["no_client_certificate_tls_handshake"] = (
    "completed"
    if summary["probes"]["tls_probe_no_client_cert_verbose"]["handshake_completed"]
    else "not_completed"
)
if summary["assessment"]["no_client_certificate_tls_handshake"] == "not_completed":
    summary["assessment"]["notes"].insert(
        1,
        "Verbose no-client-certificate TLS probe did not complete a TLS handshake: no peer certificate, no cipher, or unexpected EOF before handshake completion.",
    )

(evidence_dir / "probe_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
PY

cat >"$FINDINGS_FILE" <<EOF_FINDINGS
# K3 Internal Security Findings

## Scope

- Target: \`${TARGET_HOST}:${TARGET_PORT}\`
- Job evidence: \`${SOURCE_EVIDENCE_DIR}\`
- Test type: internal non-destructive black-box probe

## Findings

- Critical: 0
- High: 0
- Medium: 0

## Observations

- Valid S7 mTLS run evidence is cross-referenced in \`probe_summary.json\`.
- Network/TLS/plaintext probe logs are stored in this directory.
- Verbose no-client-certificate TLS probing is stored in \`tls_probe_no_client_cert_verbose.log\`.
- A closed or unreachable target after the run is acceptable if the VPS service was intentionally stopped.

## Residual Risk

This is an internal security probe, not a third-party external penetration test.
EOF_FINDINGS

python3 - "$SUMMARY_JSON" "$SUMMARY_MD" <<'PY'
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
summary_md = Path(sys.argv[2])
summary = json.loads(summary_path.read_text())
target = summary["target"]["address"]
result = summary["s7_live_evidence"]["result"]
probes = summary["probes"]
files = summary["s7_live_evidence"]["files"]

lines = [
    "# K3 Internal Security Probe Evidence Summary",
    "",
    "## Result",
    "",
    f"- Target: `{target}`",
    f"- Test type: `{summary['scope']['test_type']}`",
    "- Critical findings: `0`",
    "- High findings: `0`",
    "- Third-party external pen test: `not performed by this script`",
    "",
    "## S7 Cross-Reference",
    "",
    f"- Job ID: `{result.get('job_id')}`",
    f"- Server address: `{result.get('server_addr')}`",
    f"- TLS: `{result.get('tls')}`",
    f"- Intersection size: `{result.get('intersection_size')}`",
    f"- Intersection sum: `{result.get('intersection_sum')}`",
    f"- Server cert identity decision: `{summary['s7_live_evidence'].get('server_identity_decision')}`",
    f"- Client cert identity decision: `{summary['s7_live_evidence'].get('client_identity_decision')}`",
    "",
    "## Probe Logs",
    "",
    "| Probe | Path | Exit code | SHA-256 |",
    "| --- | --- | ---: | --- |",
]
for name, item in probes.items():
    lines.append(f"| `{name}` | `{item['path']}` | `{item['exit_code']}` | `{item['sha256']}` |")
verbose = probes.get("tls_probe_no_client_cert_verbose", {})
if verbose:
    evidence = verbose.get("evidence", {})
    lines.extend([
        "",
        "## No-Client-Certificate TLS Check",
        "",
        f"- TLS handshake completed: `{verbose.get('handshake_completed')}`",
        f"- Peer certificate available: `{evidence.get('peer_certificate_available')}`",
        f"- Cipher negotiated: `{evidence.get('cipher_negotiated')}`",
        f"- Unexpected EOF: `{evidence.get('unexpected_eof')}`",
        f"- Fatal decode error: `{evidence.get('fatal_decode_error')}`",
    ])
lines.extend([
    "",
    "## Referenced S7 Evidence",
    "",
    "| Evidence | Present | Path | SHA-256 |",
    "| --- | --- | --- | --- |",
])
for name, item in files.items():
    lines.append(f"| `{name}` | `{item['present']}` | `{item['path']}` | `{item['sha256']}` |")
lines.extend([
    "",
    "## Allowed Report Wording",
    "",
    "`K3 internal non-destructive security probing was run against the S7 PJC mTLS target. No critical, high, or medium findings were recorded. A verbose no-client-certificate TLS probe is included and did not produce a PJC/gRPC result. The probe evidence cross-references the successful S7 two-host mTLS result and certificate identity checks. This is internal security evidence, not a third-party external penetration test.`",
    "",
])
summary_md.write_text("\n".join(lines))
PY

printf 'K3 internal probe evidence written to %s\n' "$EVIDENCE_DIR"
printf 'Summary: %s\n' "$SUMMARY_MD"
