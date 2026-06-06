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

## Trust Bootstrap Choices

Do **not** treat "Party A and Party B know an IP address and port" as a secure
certificate-exchange protocol. IP/port reachability only proves that something
is listening at that network location. It does not prove that the listener is
the intended Party A. If Party B accepts a CA certificate from that endpoint
without any independent authentication, an active network attacker can run a
fake enrollment service, sign Party B's CSR with an attacker-controlled CA, and
make the later mTLS connection authenticate the wrong peer.

Use one of these bootstrap modes:

| Mode | Status | When to use |
| --- | --- | --- |
| `pjc-mtls://enroll?...` bootstrap URI | Recommended for two-host demos | Party A prints one URI containing the enrollment URL, one-time pairing token, and CA fingerprint pin. Party B pastes it into `PJC_MTLS_BOOTSTRAP=...`; the script still verifies the returned CA fingerprint. |
| Separate `SERVER_HOST` + `PJC_MTLS_PAIRING_TOKEN` + `EXPECTED_CA_FINGERPRINT` | Recommended explicit form | Same security properties as the bootstrap URI, easier to audit field by field. |
| WireGuard / Tailscale / SSH trusted channel plus fingerprint check | Stronger operator bootstrap | Use a private authenticated channel for the enrollment endpoint or for transmitting the bootstrap URI. |
| SPIFFE/SPIRE + Envoy, Istio/Linkerd, Vault PKI, step-ca, or cert-manager | Production direction | Replace ad-hoc enrollment with workload identity and managed certificate lifecycle. |
| IP/port only with `ALLOW_UNVERIFIED_CA=1` | Unsafe lab mode only | TOFU. Do not use for public-network evidence or production claims. |

The repository implements the first two modes. The client private key is still
generated on Party B and never leaves Party B; Party A receives only a CSR.

## Most Secure Production Target

The required production flow is **not** automatic certificate exchange over a
bare IP address. The production target is pre-established workload identity plus
automatic mTLS that still feels out-of-box to both operators:

```text
Party A worker ── loopback ── Envoy sidecar ── mTLS ── Envoy sidecar ── loopback ── Party B worker
                         ▲                         ▲
                         │                         │
                    SPIRE Agent               SPIRE Agent
                         ▲                         ▲
                         └────── SPIRE Server / trust domain ──────┘
```

Implementation plan:

1. Put Party A and Party B on a controlled network first: WireGuard, Tailscale,
   private VPC, or equivalent. Do not expose the enrollment service or PJC
   data-plane listener to the whole internet.
2. Run SPIRE Server as the trust-domain authority and one SPIRE Agent per host.
   Define workload selectors for the Party A and Party B PJC workers.
3. Give each worker an X.509 SVID with short TTL. Envoy obtains SVIDs through
   SDS / workload API and terminates mTLS for the local PJC binary.
4. Configure Envoy authorization so Party A only accepts the expected Party B
   SPIFFE ID, and Party B only accepts the expected Party A SPIFFE ID.
5. Keep the PJC binary bound to loopback. Only Envoy listens on the controlled
   network interface.
6. Record the runtime identity evidence for every job:
   - trust domain
   - peer SPIFFE ID
   - SVID / leaf certificate fingerprint
   - trust-bundle fingerprint
   - notBefore / notAfter
   - Envoy peer-auth decision
   - PJC result hash and server/client log hashes
7. Keep the existing `pjc-mtls://enroll` CSR flow only as a two-host demo /
   fallback path. It is acceptable for controlled evidence when paired with a
   CA fingerprint pin and one-time token, but it is not the most secure
   production target.

Recommended open-source stack:

| Layer | Preferred option | Role |
| --- | --- | --- |
| Network isolation | WireGuard or Tailscale | Keeps PJC ports off the open internet. |
| Workload identity | SPIFFE/SPIRE | Issues short-lived X.509 SVIDs to Party A/B workers. |
| mTLS proxy | Envoy | Performs mTLS, peer verification, and policy enforcement. |
| Kubernetes alternative | Istio or Linkerd | Provides service-mesh mTLS and workload policy when deployed on K8s. |
| Certificate authority fallback | Vault PKI, step-ca, cert-manager | Managed PKI when SPIFFE/SPIRE is not available. |

Completion criteria for this target:

1. Positive run: Party A and Party B complete PJC over Envoy/SPIRE mTLS.
2. Wrong peer negative run: a workload with the wrong SPIFFE ID is rejected
   before reaching the PJC binary.
3. Expired / wrong trust-bundle negative run: TLS fails closed.
4. Evidence bundle includes both parties' Envoy/SPIRE identity material and PJC
   result/audit artifacts.

## One-Step Two-Party Flow

The final operator experience must be:

```text
Party A: Create secure invite -> run preflight -> start server role
Party B: Paste invite -> enroll -> run preflight -> start client role
Both:    Merge evidence -> verify result -> archive release package
```

This is "out-of-box" only if every step above is implemented in the control
plane and fails closed. Manual scp of certs, unaudited firewall guesses, or
trusting an IP/port by itself does not meet the bar.

### Secure Invite Format

The bare-host fallback invite is:

```text
pjc-mtls://enroll?url=<https-or-http-enrollment-url>&token=<one-time-token>&ca_sha256=<ca-fingerprint>&ttl=<seconds>
```

Implementation requirements:

1. Party A emits the URI from both
   `serve_pjc_mtls_enrollment_party_a.sh` and the X-UI
   `POST /v1/pjc-mtls/party-a/prepare` endpoint.
2. The token is random, one-time by default, TTL-bound, and deleted after use or
   expiry.
3. Party B may provide only the URI. If Party B also provides explicit URL,
   token, or fingerprint fields, the backend must compare them to the URI and
   reject conflicts.
4. Party B generates `client.key` locally and never sends it over the network.
5. Party B stores `client.key` with mode `0600` and verifies both the returned
   CA fingerprint and the fingerprint of the saved `ca.crt`.
6. The enrollment service runs in enrollment-only mode and exposes only
   `/healthz` plus `/v1/pjc-mtls/enroll`.

This fallback is acceptable for a two-host demo only when the invite is
transmitted over a trusted channel and the fingerprint pin is preserved. The
production target remains SPIFFE/SPIRE + Envoy/service mesh.

### Preflight Gate

Before either side can press "Run", the UI must call a preflight that records:

| Check | Failure action |
| ----- | -------------- |
| repo commit and helper-script version match | reject run |
| PJC binaries exist and report expected flags | reject run |
| Party A data-plane port reachable from Party B | reject run |
| TLS handshake succeeds with mTLS | reject run |
| peer certificate identity/fingerprint matches job policy | reject run |
| input CSV hash equals role manifest hash | reject run |
| bucket count, row count, byte size, and chunk size within limits | reject run |
| output directory writable and evidence paths unique | reject run |

The evidence file for this gate should be `pjc_two_party_preflight/v1` and must
be archived by both parties.

### Role Lifecycle

The scripts already separate Party A and Party B role directories. The
out-of-box product must expose them through stable UI/API calls:

| Endpoint | Responsibility |
| -------- | -------------- |
| `POST /v1/pjc/role-package/export` | create a Party A or Party B package with manifests, hashes, expected ports, and redacted operator notes |
| `POST /v1/pjc/role-package/import` | validate package schema and hashes before writing it locally |
| `POST /v1/pjc/roles/server/start` | start Party A loopback PJC server plus TLS/service-mesh listener |
| `POST /v1/pjc/roles/client/start` | start Party B client through local TLS/service-mesh proxy |
| `GET /v1/pjc/roles/{role}/status` | return running PID, port, peer, logs, and last audit hash |
| `POST /v1/pjc/roles/{role}/cancel` | terminate child process and proxy, write cancellation audit |
| `POST /v1/pjc/evidence/verify-merge` | verify both parties' manifests, TLS identity, logs, and final result hash |

### Negative Cases Required for Graduation

A run is not "一步到位" until the UI can execute and archive these negative
cases:

1. wrong pairing token rejected
2. expired token rejected and token state deleted
3. wrong CA fingerprint rejected before writing certs
4. wrong peer identity rejected before PJC starts
5. closed or filtered data-plane port rejected by preflight
6. mismatched repo commit or helper version rejected
7. modified input CSV rejected by manifest hash
8. below-k / exhausted privacy budget denied by release policy

### Repo-Side Control-Plane Status

As of 2026-05-23, the S9 control-plane contracts are implemented repo-side in
`scripts/serve_operator_dashboard.py`:

| Contract | Endpoint / schema | Local coverage |
| -------- | ----------------- | -------------- |
| Preflight | `POST /v1/pjc-mtls/preflight`, `pjc_two_party_preflight/v1` | helper smoke validates allow and deny paths |
| Role package | `POST /v1/pjc/role-package/export`, `POST /v1/pjc/role-package/import`, `pjc_role_package/v1` | round-trip and tamper detection |
| Role lifecycle | `POST /v1/pjc/roles/{server,client}/start`, `GET /v1/pjc/roles/{role}/status`, `POST /v1/pjc/roles/{role}/cancel`, `pjc_role_status/v1` | surrogate subprocess start/status/cancel |
| Evidence merge | `POST /v1/pjc/evidence/verify-merge`, `pjc_two_party_evidence_merge/v1` | agreement and mismatch paths |
| Negative cases | `POST /v1/pjc-mtls/negative-cases/run`, `pjc_two_party_negative_cases/v1` | all eight expected denials |

The regression entry point is `scripts/check_pjc_two_party_smoke.py`; the five
new schemas are included in `scripts/check_json_contracts.sh`, and the smoke is
listed in `scripts/check_ci_smoke.sh`.

The control-plane gained four additional helpers on 2026-05-23 that close the
gaps previously called out in this section. All of them have a focused smoke
that runs in CI without needing two real hosts:

| Contract | Endpoint / schema | Local smoke |
| -------- | ----------------- | ----------- |
| Live TLS diagnostic | `POST /v1/pjc-mtls/tls-diagnostic`, `pjc_tls_diagnostic/v1` | `scripts/check_pjc_tls_diagnostic_smoke.py` — closed-port deny, TCP-accepts-then-closes (`tls_eof`), missing-cert hint |
| Typed TLS readiness | `pjc_tls_readiness/v1` via `scripts/check_pjc_tls_readiness.py` | `scripts/check_pjc_tls_readiness_smoke.py` — `tcp_timeout`, `tls_eof`, and allow-level mTLS readiness |
| Server-side release gate | `POST /v1/release/policy-gate`, `release_policy_gate/v1` + `release_policy_gate_config/v1` | `scripts/check_release_policy_gate_smoke.py` — missing ledger / low-k / missing DP / allowed / duplicate-query leak |
| SPIFFE/SPIRE + Envoy templates | `deploy/spiffe_envoy/*`, `spiffe_envoy_peer_allowlist/v1`, `spiffe_envoy_template_check/v1` | `scripts/check_spiffe_envoy_templates.py --assert-allow` |
| SPIFFE/SPIRE + Envoy identity gate | `spiffe_envoy_identity_gate/v1` | `scripts/check_spiffe_envoy_identity_gate.py` — repo-side allowlist/template coherence, live deployment artifacts explicitly `skipped` until provided |
| SPIFFE/SPIRE + Envoy live archive | `spiffe_envoy_live_evidence_archive/v1` | `scripts/archive_spiffe_envoy_live_evidence.py` — freezes any operator-provided positive/negative run evidence and Envoy access logs into one verifier package |
| Guided two-party wizard | `renderS9Wizard` in `scripts/serve_operator_dashboard.py` (frontend only) | wired against the existing backend smokes; navigates the dashboard at `#s9-wizard` |

This is still not the same as production certification. The remaining
evidence gap is a real two-host run where Party A and Party B each archive
their preflight, role status, evidence merge, negative-case, and
(once a release is produced) `release_policy_gate/v1` reports. The known VPS
public `10502` TLS EOF case can now be triaged from the wizard's Run step via
the new diagnostic, but the underlying network/operator action is still owed.

## Web-UI CSR Enrollment Setup

The existing PJC X-UI can bootstrap mTLS without SSH and without sending
certificate files by hand. The script-first flow is:

1. Party A runs one script that prepares the CA and starts the enrollment endpoint.
2. Party A sends the printed Party B command to Party B.
3. Party B runs that command.
4. Party B's script generates `client.key` locally, sends only a CSR to Party A, and
   receives `ca.crt` + `client.crt`.

`client.key` never leaves Party B. `ca.key`, `server.crt`, and `server.key`
never leave Party A.

Use the same dashboard port you already use for `serve_operator_dashboard.py`;
this flow does not change the PJC ports:

| Purpose | Default |
| ------- | ------- |
| PJC server loopback | `127.0.0.1:10501` |
| External mTLS PJC port | `10502` |
| PJC client loopback proxy | `127.0.0.1:10503` |

Party A starts the existing web UI enrollment service on an address Party B can
reach:

```bash
cd ~/Desktop/seccomp-privacy-platform

SERVER_HOST=<PartyA public IP, hostname, or VPN IP> \
bash a-psi/moduleA_psi/scripts/serve_pjc_mtls_enrollment_party_a.sh
```

The script prints the enroll URL, pairing token, CA fingerprint, and the exact
Party B command. Keep this terminal running while Party B enrolls.

The script also prints a one-line bootstrap URI:

```text
pjc-mtls://enroll?url=...&token=...&ca_sha256=...
```

Party B can paste that one value instead of setting three separate variables:

```bash
cd ~/Desktop/seccomp-privacy-platform

PJC_MTLS_BOOTSTRAP='<pjc-mtls://enroll?... printed by Party A>' \
bash a-psi/moduleA_psi/scripts/enroll_pjc_mtls_party_b.sh
```

Treat the bootstrap URI like a short-lived secret. It contains the one-time
pairing token and the CA fingerprint pin. Send it over an authenticated and
confidential channel when possible, and keep the default token TTL /
max-enrollment limits enabled.

Party B runs the printed command:

```bash
cd ~/Desktop/seccomp-privacy-platform

SERVER_HOST=<PartyA public IP, hostname, or VPN IP> \
PJC_MTLS_PAIRING_TOKEN=<token printed by Party A> \
bash a-psi/moduleA_psi/scripts/enroll_pjc_mtls_party_b.sh
```

After enrollment, Party B can run:

```bash
export JOB_ID=cross-internet-job-001
export CERT_DIR="$HOME/pjc_certs_shared"
export SERVER_HOST=<PartyA public IP, hostname, or VPN IP>
export TLS_PORT=10502
export CLIENT_CSV="$PWD/bridge/out/sse_demo_job/client.csv"
export PJC_BIN_DIR="$PWD/a-psi/private-join-and-compute/bazel-bin"
export OUT_DIR="$PWD/tmp/pjc_mtls_$JOB_ID/party_b_client"

bash a-psi/moduleA_psi/scripts/run_pjc_client_tls.sh
```

Or combine first-time enrollment with the client wrapper:

```bash
export JOB_ID=cross-internet-job-001
export SERVER_HOST=<PartyA public IP, hostname, or VPN IP>
export PJC_MTLS_PAIRING_TOKEN=<token printed by Party A>
export CLIENT_CSV="$PWD/bridge/out/sse_demo_job/client.csv"
export PJC_BIN_DIR="$PWD/a-psi/private-join-and-compute/bazel-bin"
export OUT_DIR="$PWD/tmp/pjc_mtls_$JOB_ID/party_b_client"

bash a-psi/moduleA_psi/scripts/run_pjc_client_tls_auto.sh
```

The pairing token is the trust bootstrap. For production-grade evidence,
verify the displayed CA fingerprint out-of-band before Party B accepts the
certificate.

Do not use `ALLOW_UNVERIFIED_CA=1` for public-network evidence. That flag is
only for isolated lab debugging where TOFU is acceptable.

## 1k Business-Bucket Scale Test

For a local end-to-end test with generated business buckets:

```bash
cd ~/Desktop/seccomp-privacy-platform

JOB_ID=bucketed-scale-1k \
RECORDS=1000 \
BUCKETS=8 \
BUCKET_FIELD=campaign_id \
K_THRESHOLD=20 \
DP_EPSILON=1.0 \
DP_SENSITIVITY=10000 \
BASE_PORT=10621 \
PJC_BIN_DIR="$PWD/a-psi/private-join-and-compute/bazel-bin" \
bash a-psi/moduleA_psi/scripts/run_bucketed_scale_test.sh
```

Outputs:

```text
tmp/pjc_bucketed_scale_<JOB_ID>/job_meta.json
tmp/pjc_bucketed_scale_<JOB_ID>/expected_result.json
tmp/pjc_bucketed_scale_<JOB_ID>/attribution_result.json
tmp/pjc_bucketed_scale_<JOB_ID>/public_report.json
tmp/pjc_bucketed_scale_<JOB_ID>/bucket_public_report.json
tmp/pjc_bucketed_scale_<JOB_ID>/audit_log.jsonl
tmp/pjc_bucketed_scale_<JOB_ID>/party_a_job/
tmp/pjc_bucketed_scale_<JOB_ID>/party_b_job/
```

The generated PJC CSVs contain only HMAC tokens. If `PJC_BUCKET_HMAC_SECRET`
is set, the generator uses that shared secret. If it is not set, the test
creates a local `0600` secret file under the output directory for demo use.
The secret material is not written to `job_meta.json`.

The existing web UI exposes the same flow in **Business Bucket Scale Test**.

## Public Bucketed mTLS Run

After Party B has enrolled or otherwise has a cert bundle, the same bucketed
job can run across two machines over mTLS. Use the split role directories from
the scale test: Party A gets only `party_a_job/`, Party B gets only
`party_b_job/`. Keep the default PJC TLS data-plane port unless it is already
in use.

Party A:

```bash
cd /root/seccomp-privacy-platform

export JOB_DIR="$PWD/tmp/pjc_bucketed_scale_bucketed-scale-1k/party_a_job"
export CERT_DIR="$PWD/tmp/pjc_mtls_shared/certs"
export PJC_BIN_DIR="$PWD/a-psi/private-join-and-compute/bazel-bin"
export TLS_PORT=10502
export PJC_LOCAL_PORT=10501
export BIND_ADDR=0.0.0.0
export PJC_GRPC_STREAM_CHUNK_ELEMENTS=0

bash a-psi/moduleA_psi/scripts/run_pjc_bucketed_tls_server.sh
```

Party B:

```bash
cd ~/Desktop/seccomp-privacy-platform

export JOB_DIR="$PWD/tmp/pjc_bucketed_scale_bucketed-scale-1k/party_b_job"
export CERT_DIR="$HOME/pjc_certs_shared"
export SERVER_HOST=<PartyA public IP, hostname, or VPN IP>
export PJC_BIN_DIR="$PWD/a-psi/private-join-and-compute/bazel-bin"
export TLS_PORT=10502
export LOCAL_PROXY_PORT=10503
export PJC_GRPC_STREAM_CHUNK_ELEMENTS=0

bash a-psi/moduleA_psi/scripts/run_pjc_bucketed_tls_client.sh
```

Party B writes and merges `attribution_result.json`, then can run
`policy_release.py` and `policy_postprocess_buckets.py` as in the local scale
test.

## SSH Fallback Setup

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
