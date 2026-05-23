# PJC mTLS Reuse Defense

Generated local verification date: 2026-05-20

## Problem

The legacy PJC mTLS workflow can reuse a shared CA and client certificate bundle
across jobs. That protects against clients without a certificate, but it does
not sufficiently constrain a copied old client certificate. If a later job still
trusts the same CA, an attacker who has the old client certificate and key may
try to replay it against the new Party A endpoint.

## Defense

Use one mTLS session per PJC job:

1. Generate a fresh CA for the job.
2. Generate fresh Party A server and Party B client certificates.
3. Bind both leaf certificates to the job through DNS SANs:
   - `job-<job_id>.partyA.example`
   - `job-<job_id>.partyB.example`
4. Keep certificates short-lived.
5. Write a `session_manifest.json` with the job id, fingerprints, identities,
   and validity window.
6. Make the TLS wrappers validate the manifest before starting.

This makes a copied old client certificate fail in two ways:

- TLS layer: a per-job CA means the old cert is not signed by the new job CA.
- Wrapper gate: the old client fingerprint does not match the new job manifest.

## New Scripts

Create a one-job session:

```bash
python3 scripts/create_pjc_mtls_session.py \
  --job-id <job_id> \
  --out-dir tmp/pjc_mtls_sessions/<job_id> \
  --ttl-hours 24
```

Validate a session manifest:

```bash
python3 scripts/check_pjc_mtls_session_manifest.py \
  --manifest tmp/pjc_mtls_sessions/<job_id>/session_manifest.json \
  --cert-dir tmp/pjc_mtls_sessions/<job_id> \
  --role server \
  --job-id <job_id> \
  --assert-allow
```

Regression evidence:

```bash
bash scripts/verify_pjc_mtls_reuse_defense.sh
```

Latest local result:

```json
{
  "status": "pass",
  "out_dir": "/home/llvanion/Desktop/seccomp-privacy-platform/tmp/pjc_mtls_reuse_defense"
}
```

## Wrapper Integration

The existing wrappers now automatically validate a session manifest when it is
present in `CERT_DIR`:

- `a-psi/moduleA_psi/scripts/run_pjc_server_tls.sh`
- `a-psi/moduleA_psi/scripts/run_pjc_client_tls.sh`

To fail closed, set:

```bash
PJC_MTLS_REQUIRE_SESSION_MANIFEST=1
```

Example Party A:

```bash
JOB_ID=cross-vps-006
CERT_DIR=tmp/pjc_mtls_sessions/cross-vps-006

python3 scripts/create_pjc_mtls_session.py \
  --job-id "$JOB_ID" \
  --out-dir "$CERT_DIR" \
  --ttl-hours 24

PJC_MTLS_REQUIRE_SESSION_MANIFEST=1 \
JOB_ID="$JOB_ID" \
CERT_DIR="$CERT_DIR" \
SERVER_CSV=<server.csv> \
OUT_DIR=tmp/pjc_mtls_cross-vps-006/party_a_server \
bash a-psi/moduleA_psi/scripts/run_pjc_server_tls.sh
```

Example Party B:

```bash
JOB_ID=cross-vps-006
CERT_DIR=<received_party_b_bundle_dir>

PJC_MTLS_REQUIRE_SESSION_MANIFEST=1 \
JOB_ID="$JOB_ID" \
CERT_DIR="$CERT_DIR" \
SERVER_HOST=<party-a-ip> \
CLIENT_CSV=<client.csv> \
OUT_DIR=tmp/pjc_mtls_cross-vps-006/party_b_client \
bash a-psi/moduleA_psi/scripts/run_pjc_client_tls.sh
```

Party B should receive only:

```text
ca.crt
client.crt
client.key
session_manifest.json
```

Party A keeps:

```text
ca.key
server.crt
server.key
```

## Verification Cases

The regression script verifies:

| Case | Expected |
| --- | --- |
| fresh session A client for job `reuse-a` | allow |
| session A manifest reused for job `reuse-b` | deny `job_id_mismatch` |
| old session A client cert used under session B manifest | deny replay |

Evidence directory:

```text
tmp/pjc_mtls_reuse_defense/
```

Key artifacts:

- `verification_summary.json`
- `case1_session_a_client_allow.json`
- `case2_job_id_mismatch_deny.json`
- `case3_old_client_replay_deny.json`
- `final_evidence_hashes.sha256`

## Report Language

Use:

```text
PJC mTLS certificate reuse defense: repo-side implemented and verified.
```

Use after a fresh two-host run with this session mode:

```text
PJC mTLS certificate reuse defense: verified in cross-host run <job_id>.
```

Do not claim this protects against private-key theft during the same valid
session window. If an attacker steals the current job's `client.key` before the
job completes, the remaining control is short TTL, one-job scope, endpoint
shutdown, and incident response. That risk requires stronger hardware-backed key
storage or remote attestation to reduce further.
