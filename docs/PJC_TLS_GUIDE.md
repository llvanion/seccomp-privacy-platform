# PJC Cross-Internet mTLS Guide

This guide explains how to run the Private Join and Compute (PJC) step between two parties on separate machines over the internet, with mutual TLS protecting the gRPC channel.

## Architecture

```
Party A (server side)                    Party B (client side)
─────────────────────                    ────────────────────
PJC server binary                        PJC client binary
    │ plain gRPC                              │ plain gRPC
    │ 127.0.0.1:10501                         │ 127.0.0.1:10503
    ▼                                         ▼
socat / pjc_tls_proxy.py ─── mTLS ──► socat / pjc_tls_proxy.py
    0.0.0.0:10502 (internet)                 (connects to A:10502)
```

The PJC binary itself never touches the network. The TLS layer sits between the two machines and handles all transport security. Neither party's raw data leaves their machine — the PSI protocol cryptographically protects the records and only the final intersection result is revealed.

## Security Model

| Property | How it is provided |
| -------- | ------------------ |
| Confidentiality | TLS 1.2+ encryption on all gRPC messages |
| Server authentication | Party B verifies Party A's cert is signed by the shared CA |
| Client authentication (mTLS) | Party A verifies Party B's cert is signed by the shared CA |
| Data privacy | PSI protocol — neither party learns the other's raw records |
| HMAC token integrity | `BRIDGE_TOKEN_SECRET` shared out-of-band before the run |

> **Note:** The CA used here is self-signed and private to this job. It is not a public CA. Its only purpose is to authenticate the two parties to each other.

## Prerequisites

Both machines need:
- `openssl` (cert generation, Party A only)
- `socat` **or** Python 3.8+ (TLS proxy)
- The compiled PJC server/client binaries

Install socat if missing:
```bash
sudo apt-get install socat    # Debian/Ubuntu
sudo yum install socat        # RHEL/CentOS
brew install socat            # macOS
```

Or use the pure-Python fallback (`pjc_tls_proxy.py`) — no installation needed.

## Step-by-Step Setup

## Fast Reusable Setup

If the two parties already trust SSH between the machines, use the reusable helpers instead of manually copying certificate files each time.

Party A prepares or reuses one long-lived job-test CA and stages the Party B bundle:

```bash
cd ~/Desktop/seccomp-privacy-platform

bash a-psi/moduleA_psi/scripts/prepare_pjc_mtls_party_a.sh
```

This creates:

```text
tmp/pjc_mtls_shared/certs/              # Party A runtime CERT_DIR
tmp/pjc_mtls_shared/party_b_bundle/     # ca.crt + client.crt + client.key for Party B
```

Party B fetches the bundle over SSH once:

```bash
cd ~/Desktop/seccomp-privacy-platform

SERVER_HOST=<PartyA public IP, hostname, or VPN IP> \
PARTY_A_SSH=<ssh-user>@<PartyA public IP, hostname, or VPN IP> \
bash a-psi/moduleA_psi/scripts/fetch_pjc_mtls_party_b.sh
```

After that, Party B can run future jobs by changing only `SERVER_HOST`, `CLIENT_CSV`, and `JOB_ID`:

```bash
SERVER_HOST=<PartyA public IP, hostname, or VPN IP> \
CLIENT_CSV="$HOME/client.csv" \
JOB_ID=cross-internet-job-001 \
bash a-psi/moduleA_psi/scripts/run_pjc_client_tls_auto.sh
```

For first-time runs, `run_pjc_client_tls_auto.sh` can also fetch automatically when `PARTY_A_SSH` is provided:

```bash
SERVER_HOST=<PartyA public IP, hostname, or VPN IP> \
PARTY_A_SSH=<ssh-user>@<PartyA public IP, hostname, or VPN IP> \
CLIENT_CSV="$HOME/client.csv" \
JOB_ID=cross-internet-job-001 \
bash a-psi/moduleA_psi/scripts/run_pjc_client_tls_auto.sh
```

The SSH connection is the trust bootstrap. Verify the printed CA fingerprint over a separate channel before treating the run as production evidence.

### Step 1 — Party A generates certificates (once)

```bash
# On Party A's machine
CERT_DIR=a-psi/moduleA_psi/config/tls \
  bash a-psi/moduleA_psi/scripts/gen_pjc_tls_certs.sh
```

This creates:

| File | Keep where |
| ---- | ---------- |
| `ca.key` | Party A only — never share |
| `server.crt` + `server.key` | Party A only |
| `ca.crt` | Share with Party B |
| `client.crt` + `client.key` | Share with Party B |

### Step 2 — Party A sends cert bundle to Party B (secure channel)

```bash
# Example using scp — verify the fingerprint over a separate channel
scp ca.crt client.crt client.key party_b@PARTY_B_HOST:~/pjc_certs/
```

**Always verify the CA fingerprint** over a separate channel (phone, Signal, etc.) before Party B accepts the certs:

```bash
# Party A prints this
openssl x509 -in a-psi/moduleA_psi/config/tls/ca.crt -fingerprint -sha256 -noout

# Party B verifies it matches
openssl x509 -in ~/pjc_certs/ca.crt -fingerprint -sha256 -noout
```

### Step 3 — Both parties run SSE export + bridge (locally, same HMAC key)

The `BRIDGE_TOKEN_SECRET` must be the same on both sides. Share it out-of-band before this step.

```bash
# Party A (server role)
export BRIDGE_TOKEN_SECRET=<shared-secret>
bash scripts/run_sse_bridge_pipeline.sh \
  --server-input sse/examples/bridge_server_records.jsonl \
  --client-input /dev/null \
  --job-id cross-internet-job-001 \
  ...
# Produces: bridge_job/server.csv

# Party B (client role) — same BRIDGE_TOKEN_SECRET
bash scripts/run_sse_bridge_pipeline.sh \
  --client-input sse/examples/bridge_client_records.jsonl \
  --server-input /dev/null \
  ...
# Produces: bridge_job/client.csv
```

### Step 4 — Party A starts the TLS server

```bash
# Open port 10502 in your firewall first
# ufw allow 10502/tcp   (Ubuntu)

export CERT_DIR=a-psi/moduleA_psi/config/tls
export SERVER_CSV=bridge_job/server.csv
export JOB_ID=cross-internet-job-001
export TLS_PORT=10502

bash a-psi/moduleA_psi/scripts/run_pjc_server_tls.sh
```

Party A's terminal will print:
```
[ok] PJC server listening on 127.0.0.1:10501
[ok] TLS proxy running on 0.0.0.0:10502
[info] Party B should connect to: <this-machine-ip>:10502
[info] waiting for PJC protocol to complete...
```

### Step 5 — Party B runs the TLS client

```bash
export CERT_DIR=~/pjc_certs
export SERVER_HOST=PARTY_A_PUBLIC_IP
export CLIENT_CSV=bridge_job/client.csv
export JOB_ID=cross-internet-job-001
export TLS_PORT=10502

bash a-psi/moduleA_psi/scripts/run_pjc_client_tls.sh
```

Output on success:
```
[ok] attribution_result.json
[ok] intersection_size=2  intersection_sum=425
```

## Using the Python Fallback (no socat)

Replace steps 4 and 5 with the Python proxy:

**Party A:**
```bash
# Terminal 1: start TLS proxy
python3 a-psi/moduleA_psi/scripts/pjc_tls_proxy.py server \
  --cert a-psi/moduleA_psi/config/tls/server.crt \
  --key  a-psi/moduleA_psi/config/tls/server.key \
  --ca   a-psi/moduleA_psi/config/tls/ca.crt \
  --tls-port 10502 --local-port 10501 &

# Terminal 2: start PJC server (plain, loopback only)
SERVER_ADDR=127.0.0.1:10501 \
SERVER_CSV=bridge_job/server.csv \
  bash a-psi/moduleA_psi/scripts/run_pjc_server.sh
```

**Party B:**
```bash
# Terminal 1: start TLS client proxy
python3 a-psi/moduleA_psi/scripts/pjc_tls_proxy.py client \
  --cert ~/pjc_certs/client.crt \
  --key  ~/pjc_certs/client.key \
  --ca   ~/pjc_certs/ca.crt \
  --server-host PARTY_A_PUBLIC_IP \
  --tls-port 10502 --local-port 10503 &

# Terminal 2: PJC client connects through local proxy
SERVER_ADDR=127.0.0.1:10503 \
CLIENT_CSV=bridge_job/client.csv \
  bash a-psi/moduleA_psi/scripts/run_pjc_client.sh
```

## Environment Variable Reference

### gen_pjc_tls_certs.sh

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `CERT_DIR` | `config/tls` | Output directory for generated certs |
| `CERT_VALIDITY_DAYS` | `365` | Certificate validity in days |

### run_pjc_server_tls.sh

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `CERT_DIR` | `config/tls` | Directory with `ca.crt`, `server.crt`, `server.key` |
| `SERVER_CSV` | `/tmp/server.csv` | Party A's tokenised server CSV |
| `TLS_PORT` | `10502` | External TLS port (open this in firewall) |
| `PJC_LOCAL_PORT` | `10501` | Loopback port for the PJC binary |
| `BIND_ADDR` | `0.0.0.0` | Interface to bind the TLS port |
| `JOB_ID` | timestamp | Job identifier |

### run_pjc_client_tls.sh

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `SERVER_HOST` | *(required)* | Party A's public IP or hostname |
| `CERT_DIR` | `config/tls` | Directory with `ca.crt`, `client.crt`, `client.key` |
| `CLIENT_CSV` | `/tmp/client.csv` | Party B's tokenised client CSV |
| `TLS_PORT` | `10502` | Party A's TLS port |
| `LOCAL_PROXY_PORT` | `10503` | Local loopback port for the socat client proxy |
| `JOB_ID` | timestamp | Job identifier |

## Port Summary

| Port | Machine | Purpose |
| ---- | ------- | ------- |
| `10501` | Party A | PJC server binary (loopback only, not exposed) |
| `10502` | Party A | socat/proxy TLS listener (**open in firewall**) |
| `10503` | Party B | socat/proxy local TCP entry point (loopback only) |

## Firewall Rules

Only Party A needs an inbound rule:

```bash
# Ubuntu/ufw
sudo ufw allow 10502/tcp

# iptables
sudo iptables -A INPUT -p tcp --dport 10502 -j ACCEPT
```

## Certificate Rotation

To rotate certs (e.g. before cert expiry or after a key compromise):

```bash
# Party A regenerates all certs
CERT_DIR=a-psi/moduleA_psi/config/tls \
  bash a-psi/moduleA_psi/scripts/gen_pjc_tls_certs.sh

# Party A re-shares ca.crt + client.crt + client.key with Party B
# Verify CA fingerprint again over out-of-band channel
```

The old CA cert is not trusted after rotation — Party B must replace their cert bundle.

## S7 Production Identity Gate (2026-05-14)

Out-of-band fingerprint verification (Step 2 above) is necessary but not sufficient: the production PJC wrapper must also assert, programmatically and on every run, that the peer cert it actually received over the wire matches the expected `job_id`-bound identity, fingerprint, validity window, and CA. Run `scripts/check_pjc_tls_identity.py` against the peer cert before handing control to the gRPC layer:

```bash
python3 scripts/check_pjc_tls_identity.py \
  --cert ~/pjc_certs/server.crt \
  --ca-cert ~/pjc_certs/ca.crt \
  --role server \
  --job-id <job_id> \
  --expected-fingerprint-sha256 "<hex sha256, captured out-of-band in Step 2>" \
  --expected-peer-identity "job-<job_id>.partyA.example" \
  --output tmp/pjc_tls_identity_<job_id>.json \
  --assert-allow
```

The report (`pjc_tls_identity_check/v1`) records `decision`, `reason_code`, the actual SHA-256 fingerprint, subject/issuer, every DNS SAN, the notBefore/notAfter window, and a typed `findings[]` array. Decisions:

| Decision / reason_code | Why it fires | Action |
| ---------------------- | ------------ | ------ |
| `allow` / `ok` | every check passed | proceed to start the PJC TLS endpoint |
| `deny` / `cert_unreadable` | PEM did not parse | regenerate or transport again |
| `deny` / `cert_not_yet_valid` | now < notBefore | check clock skew or wait |
| `deny` / `cert_expired` | now > notAfter | rotate certs (see "Cert Rotation" above) |
| `deny` / `fingerprint_mismatch` | actual SHA-256 ≠ expected | the cert on the wire does not match the one verified out-of-band — abort and investigate |
| `deny` / `peer_identity_mismatch` | expected identity not in CN or DNS SANs | the cert is for a different job/peer; do not proceed |
| `deny` / `ca_mismatch` | cert signature does not verify against the supplied CA | wrong CA bundle, or the cert was issued by a foreign CA |

Naming convention: encode the bound `job_id` into the SAN, e.g. `job-<job_id>.partyA.example` for Party A's server cert and `job-<job_id>.partyB.example` for Party B's client cert. Each side passes the *other* side's expected identity to the gate. Both reports — Party A on its inbound client cert, Party B on its inbound server cert — should be saved alongside the PJC audit and merged by Person 1 into the graduation evidence package.

Wrapper integration: when the PJC wrapper writes `pjc_audit/v1`, fill the new optional `tls` block with `transport=mtls`, `peer_role`, `peer_identity` (actual SAN observed), `cert_fingerprint_sha256`, `ca_fingerprint_sha256`, and `identity_check_decision` (decision + reason_code + report path). This lets the audit chain link the runtime mTLS handshake to the typed gate decision.

Re-verify the gate without a real two-machine setup:

```bash
bash scripts/verify_pjc_tls_identity_gate.sh
```

The verifier issues a fresh CA + leaf certs (valid / expired / not-yet-valid / wrong-SAN / wrong-fingerprint / foreign-CA-signed) and asserts the gate returns the expected `reason_code` for each. Evidence under `tmp/pjc_tls_identity_evidence/case{1..6}.json` when run with `--keep-out-dir`. Each report validates against `schemas/pjc_tls_identity_check.schema.json`.

The full S7 closure (real two-machine 1M streaming run, both parties saving and merging audit) requires two Ubuntu hosts with PJC binaries that support `--grpc_stream_chunk_elements` (shares the S4 operator-side prerequisite) and is tracked in [`docs/PRODUCTION_SECURITY_COMPLETION_PLAN.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PRODUCTION_SECURITY_COMPLETION_PLAN.md) under `S7`.

## What Is Not Provided

This TLS layer protects the transport channel. It does not provide:

1. **Certificate revocation** — if Party B's client key is compromised, the only remedy is to regenerate all certs (rotation above).
2. **Forward secrecy** — though TLS 1.3 (used by OpenSSL 3.x) provides it by default.
3. **Protection against a compromised BRIDGE_TOKEN_SECRET** — the bridge HMAC key must still be shared securely and rotated if compromised.
