# PJC mTLS Open Risks and Hardening Plan

Status date: 2026-05-23

This document tracks the remaining risks in the cross-machine PJC mTLS and
business-bucket test workflow. It focuses on risks that are not fully solved by
the current scripts.

For the broader cross-cutting answer about which issues are already closed
repo-side, which require online + offline governance together, and which only a
malicious-secure backend could solve, see
[ONLINE_OFFLINE_SECURITY_GOVERNANCE.md](ONLINE_OFFLINE_SECURITY_GOVERNANCE.md).

## Current Coverage

| Risk | Status | Current control |
| --- | --- | --- |
| Private-key leakage during certificate exchange | Mostly solved | CSR enrollment keeps `client.key` on Party B. `ca.key`, `server.key`, and `server.crt` stay on Party A. |
| Manual certificate file transfer | Solved for the normal path | Party A runs `serve_pjc_mtls_enrollment_party_a.sh`; Party B runs `enroll_pjc_mtls_party_b.sh`. |
| SSH requirement for Party B | Solved for the normal path | Party B no longer needs SSH access to Party A for certificate enrollment. SSH fetch remains only as fallback. |
| Proxy environment breaking loopback / local enrollment | Solved | PJC TLS client and enrollment HTTP client bypass proxy variables for local traffic. |
| Server certificate common-name mismatch with public IP | Solved | Client verifies `TLS_SERVER_COMMON_NAME=pjc-server` instead of requiring the certificate CN to equal the IP address. |
| Enrollment service man-in-the-middle | Solved | Party B's `enroll_pjc_mtls_party_b.sh` now requires either `EXPECTED_CA_FINGERPRINT` or a `PJC_MTLS_BOOTSTRAP=pjc-mtls://enroll?...` URI containing a CA fingerprint pin, and refuses the bundle if the returned CA fingerprint or the locally re-computed fingerprint does not match. `ALLOW_UNVERIFIED_CA=1` is the explicit opt-out. |
| Pairing token reuse or theft | Solved | Pairing token now has `PJC_MTLS_PAIRING_TOKEN_TTL_SECONDS` (default 600s) and `PJC_MTLS_MAX_ENROLLMENTS` (default 1) enforced server-side, with token deletion after exhaustion and audit JSONL of every accept/reject. |
| Client certificate reuse across jobs | Repo-side solved | `scripts/create_pjc_mtls_session.py` creates per-job CA/server/client certs plus `session_manifest.json`; `run_pjc_server_tls.sh` and `run_pjc_client_tls.sh` validate the manifest when present and can fail closed with `PJC_MTLS_REQUIRE_SESSION_MANIFEST=1`. Regression: `bash scripts/verify_pjc_mtls_reuse_defense.sh`. |
| Enrollment endpoint public exposure | Solved | Dashboard server auto-shuts down after `MAX_ENROLLMENTS`, TTL expiry, or `PJC_MTLS_ENROLLMENT_IDLE_TIMEOUT_SECONDS`, AND `serve_pjc_mtls_enrollment_party_a.sh` now launches the dashboard with `--mtls-enrollment-only-mode` — every endpoint except `/healthz` and `POST /v1/pjc-mtls/enroll` returns 404 `enrollment_only_mode`. |
| Synchronous bucketed-scale-test HTTP endpoint | Solved | `POST /v1/bucketed-scale-test/run` is now async by default (returns 202 + `job_id`); state via `GET /v1/bucketed-scale-test/{job_id}` and `GET /v1/bucketed-scale-test`. `?sync=1` or `{"sync": true}` is the explicit opt-in for the legacy blocking path. |
| Small bucket leakage | Solved at report layer | `policy_postprocess_buckets.py` now writes release-safe `bucket_public_report/v1`: below-k bucket labels are omitted, exact bucket sizes and `dp_noise` are redacted, and full raw/noise evidence moves to `operator_bucket_report/v1`. `--require-dp` remains fail-closed. |
| Basic differencing resistance | Repo-side tightened, still not protocol-complete | Total and per-bucket reports support Laplace DP noise. `--require-dp` is now available on `policy_release.py` and `policy_postprocess_buckets.py` and is on by default in `run_bucketed_scale_test.sh`. Exact duplicate query denial, overlap deny, close-window/threshold-round heuristics, and cross-bucket bucket-probe denial now exist in the privacy-budget ledger path. This is still software governance, not a malicious-secure proof against adaptive statistical attacks. |

## Open Risks

## Target Secure Architecture

The strongest production target is not IP/port-based automatic certificate
exchange. IP/port reachability is not an identity proof. The target architecture
is:

1. Party A and Party B first communicate over a controlled network such as
   WireGuard, Tailscale, private VPC, or equivalent.
2. Workload identity comes from SPIFFE/SPIRE. Party A and Party B receive
   short-lived X.509 SVIDs from the configured trust domain.
3. Envoy, Istio, or Linkerd performs mTLS and enforces allowed peer identities.
   The PJC binary remains bound to loopback.
4. Every job records peer SPIFFE ID or job-bound SAN, certificate fingerprint,
   trust-bundle fingerprint, validity window, TLS decision, and PJC result hash.
5. The current pairing-token CSR enrollment flow remains a controlled demo /
   fallback path. It is acceptable only when the one-time token and CA
   fingerprint pin are transmitted over an authenticated confidential channel.
   `ALLOW_UNVERIFIED_CA=1` is lab-only and cannot be used for public evidence.

Migration path:

| Phase | Implementation | Status language |
| --- | --- | --- |
| Demo-safe | `pjc-mtls://enroll` bootstrap URI with token + CA fingerprint pin | current controlled fallback |
| Operator-safe | WireGuard/Tailscale private network plus pinned CSR enrollment | recommended for two-host evidence |
| Production-safe | SPIFFE/SPIRE + Envoy/service mesh mTLS + short-lived SVIDs | target, not yet implemented |

### 1. Enrollment Service Man-in-the-Middle

**Status:** Solved (2026-05-17).

**Original concern:** if Party B accepts an enrollment URL without verifying the
CA fingerprint, a network attacker could substitute a fake enrollment service
and trick Party B into trusting the wrong CA.

**Implemented control:**

1. `enroll_pjc_mtls_party_b.sh` now requires `EXPECTED_CA_FINGERPRINT`
   (alias `PJC_MTLS_EXPECTED_CA_FINGERPRINT`) to be set on the Party B host.
2. The script normalizes and compares the fingerprint against both the value
   returned by the enrollment response and the value re-computed locally from
   the received `ca.crt`. A mismatch aborts before `client.crt` is written.
3. `ALLOW_UNVERIFIED_CA=1` is the only way to skip the check, and it logs a
   `[warn] TOFU only` message so the operator notices.
4. `serve_pjc_mtls_enrollment_party_a.sh` now prints the exact Party B command
   with `EXPECTED_CA_FINGERPRINT='<sha256>'` already filled in, so the operator
   only needs to transmit it through a side channel and Party B can paste it
   directly.
5. `serve_pjc_mtls_enrollment_party_a.sh` also prints a one-line
   `pjc-mtls://enroll?...` bootstrap URI containing the enroll URL, one-time
   pairing token, CA fingerprint pin, and token TTL. `enroll_pjc_mtls_party_b.sh`
   accepts it through `PJC_MTLS_BOOTSTRAP`, parses the fields, and still verifies
   the CA fingerprint before trusting the returned certificate.

**Residual hardening (still optional):**

- Public HTTPS certificate for the enrollment endpoint, Tailscale/WireGuard
  identity, pre-shared root CA, or QR-code fingerprint flow for very high-trust
  deployments.

### 2. Pairing Token Reuse or Theft

**Status:** Solved (2026-05-17).

**Original concern:** the pairing token authorizes CSR signing. If it was
intercepted while Party A's enrollment endpoint was still running, another
client could request a certificate.

**Implemented control:**

1. `PJC_MTLS_PAIRING_TOKEN_TTL_SECONDS` (default `600`) — `_enroll_pjc_mtls_csr`
   rejects with `pairing_rejected` once the wall-clock age of the token exceeds
   the TTL.
2. `PJC_MTLS_MAX_ENROLLMENTS` (default `1`) — after the configured number of
   successful signings, the token is rejected and deleted.
3. Both the token file (`tmp/pjc_mtls_shared/pairing_token`) and the metadata
   sidecar (`tmp/pjc_mtls_shared/pairing_token_meta.json`) are unlinked on
   exhaustion / expiry so a restart cannot accidentally re-use the same token.
4. Every accept/reject is appended to
   `tmp/pjc_mtls_shared/enrollment_audit.jsonl` with UTC timestamp, remote
   address, CSR public-key SHA-256 fingerprint, issued client certificate
   fingerprint, CA fingerprint, and the reason code on rejection.
5. `serve_pjc_mtls_enrollment_party_a.sh` seeds the metadata sidecar so that
   TTL counts from "Party A pressed start", not from the first request.

### 3. Enrollment Endpoint Public Exposure

**Status:** Solved (2026-05-17).

**Original concern:** Party A's enrollment script started the dashboard HTTP
server on a reachable interface when `DASHBOARD_BIND_HOST=0.0.0.0`. If the
operator left it running, the enrollment surface remained exposed.

**Implemented control:**

1. Server registers a `_enrollment_shutdown_hook` during `main()` that removes
   the pid/ready files and shuts down the `ThreadingHTTPServer`. The hook fires
   from three places:
   - successful enrollment that exhausts `MAX_ENROLLMENTS`,
   - a request that arrives after the TTL has expired,
   - a request that arrives after `MAX_ENROLLMENTS` has been reached.
2. Optional idle watch: when
   `PJC_MTLS_ENROLLMENT_IDLE_TIMEOUT_SECONDS > 0`, a daemon thread shuts the
   server down if no successful enrollment is recorded within the window. The
   default is `0` (disabled) so existing operators don't see surprise shutdowns.
3. `serve_pjc_mtls_enrollment_party_a.sh` exports the TTL, max-enrollment and
   idle-timeout envs into the dashboard subprocess and prints them at startup
   so the operator sees the expected cool-down behavior up front.
4. **New (2026-05-17 round 3):** `serve_operator_dashboard.py` now accepts
   `--mtls-enrollment-only-mode`. In this mode every HTTP path except
   `GET /healthz` and `POST /v1/pjc-mtls/enroll` returns
   `HTTP 404 enrollment_only_mode` with `allowed_paths` in the body. The
   bash launcher passes the flag by default; the only way to expose the full
   dashboard again is to set `DASHBOARD_FULL_SURFACE=1` explicitly. This
   removes the "few-seconds-of-full-dashboard" window the previous fix
   couldn't avoid.

**Residual hardening (operator deployment hygiene, not code):**

1. Document cloud firewall rules: only open the enrollment port briefly, then
   close it.

### 4. Public Internet Bucketed End-to-End Evidence

**Status:** Partially validated.

The bucketed mTLS wrappers were verified locally with split Party A / Party B
job directories. The real VPS-to-laptop public internet run has not yet been
executed for the 1k bucketed dataset.

2026-05-23 attempted status: the 1k bucketed dataset and split Party A / Party B
directories were generated, and Party A material was copied to the VPS. TCP
reachability to `118.190.61.66:10502` succeeded, but TLS handshakes failed with
`SSL_connect unexpected eof while reading` before the first bucket could run.
This is evidence of an unresolved public-network / TLS listener path issue, not
completion evidence. Do not mark this risk closed until the full bucketed run
produces the merged `attribution_result.json` and bucket public report.

**Current mitigation:** Scripts exist:

- `run_pjc_bucketed_tls_server.sh`
- `run_pjc_bucketed_tls_client.sh`
- `split_bucketed_pjc_job_for_parties.py`

**Remaining gap:** No real public-network evidence artifact yet.

**Recommended validation:**

1. Generate the 1k bucketed dataset.
2. Split it into `party_a_job/` and `party_b_job/`.
3. Copy only `party_a_job/` to the VPS.
4. Keep only `party_b_job/` on the laptop.
5. Run the bucketed mTLS server/client scripts over the VPS public IP.
6. Save:
   - Party A server logs,
   - Party B client logs,
   - Party B merged `attribution_result.json`,
   - `bucket_public_report.json`,
   - CA fingerprint used for the run,
   - the matching `enrollment_audit.jsonl` line for the Party B client cert.

### 5. Web UI Long-Running Job Experience

**Status:** Solved on the backend (2026-05-17). SPA polling still owned by
Engineer B.

**Implemented control:**

1. `POST /v1/bucketed-scale-test/run` is now async-by-default. It validates the
   inputs synchronously and then spawns a `daemon=True` worker thread,
   returning `HTTP 202` with a generated `job_id` (the supplied `job_id`
   suffixed with a random 8-char hex tag so two runs of the same logical job
   can coexist).
2. `GET /v1/bucketed-scale-test/{job_id}` returns the job snapshot:
   `{ state ∈ running|succeeded|failed, started_at_utc, finished_at_utc,
   duration_sec, params, result, error }`.
3. `GET /v1/bucketed-scale-test` returns the list (most recent first) for the
   admin shell. A simple retention cap (50 jobs) evicts the oldest terminal
   job when exceeded so a long-running server doesn't grow unbounded.
4. The legacy blocking path is still reachable for callers that depend on it,
   via `{"sync": true}` in the body or `?sync=1` on the URL.

**Residual gap (Engineer B SPA work, not blocking):**

1. Update the Live Progress view to poll the new endpoints and render per-bucket
   progress / log-tail.
2. Add a cancellation endpoint backed by `subprocess.terminate()` of the worker.

### 6. Differential Privacy Production Strength

**Status:** Partially solved (2026-05-17). Per-run enforcement landed; the
multi-tenant / approval-policy story is still pending.

DP noise is implemented for total and bucket-level reports, the RNG uses
`SystemRandom`, and missing-DP runs can now fail-closed at argparse time.

**Current mitigation:**

- `policy_release.py` supports `--dp-epsilon`, `--dp-sensitivity`, and the new
  `--require-dp` fail-closed flag (refuses to start if either knob is missing
  or non-positive).
- `policy_postprocess_buckets.py` applies per-bucket Laplace noise and also
  supports `--require-dp` for bucket reports.
- Public bucket reports redact the sampled `dp_noise`, below-k labels, and
  exact bucket sizes. Operator-only bucket reports retain raw/noise evidence for
  audit.
- `run_bucketed_scale_test.sh` now passes `--require-dp` to both stages by
  default, so the bundled bucketed scale test cannot accidentally release
  un-DP'd bucket sums.
- `policy_release.py` supports duplicate-query denial and optional privacy
  budget ledger.

**Remaining gap (S3, still partial):** Epsilon selection, sensitivity,
repeated-query accounting, and approval policy are not centrally enforced for
every run mode. `--require-dp` is a *per-invocation* fail-closed; an operator
can still launch a one-off `policy_release.py` without it.

**Recommended hardening (next steps):**

1. Make privacy budget ledger mandatory for public reports (server-side, not
   per-CLI).
2. Define approved epsilon/sensitivity presets per dataset and query type.
3. Add role-gated approval for high-epsilon or low-k requests.
4. Add regression tests for:
   - repeated same query,
   - overlapping-window query,
   - low-k bucket suppression,
   - DP metadata presence in public reports.

## One-Step Production Gap Register

The project is not allowed to claim "two-party out-of-box" until this register
is empty. The target is a single guided flow, not a collection of manual scripts.

| Gap | Status | Why it still matters | Evidence required |
| --- | ------ | -------------------- | ----------------- |
| Identity target live rollout | Operator/live evidence open | The safest architecture is SPIFFE/SPIRE + Envoy/service mesh. Repo-side templates now exist under `deploy/spiffe_envoy/` and are structurally linted by `scripts/check_spiffe_envoy_templates.py`; a real deployment still must prove the trust domain and peer allowlist. | positive Envoy/SPIRE PJC run; wrong SPIFFE ID reject; expired/wrong trust bundle reject |
| Preflight API | Repo-side implemented | `POST /v1/pjc-mtls/preflight` now produces `pjc_two_party_preflight/v1`; still needs real two-host evidence | `pjc_two_party_preflight/v1` from both parties on the same live job |
| Role package API | Repo-side implemented | `POST /v1/pjc/role-package/export` and `/import` validate hashes and undeclared files; still needs cross-host operator exercise | exported package manifest, imported package validation report from both hosts |
| Cross-host role lifecycle | Repo-side implemented | `/v1/pjc/roles/{server,client}/start`, `/status`, `/cancel` persist PID/log/hash state; still needs real Party A/B run evidence | server/client status JSON, log hashes, cancellation evidence |
| Evidence merge gate | Repo-side implemented | `/v1/pjc/evidence/verify-merge` compares job id, commit, input manifests, optional bucket-policy/shard-manifest hashes, TLS identity, result hash, policy decision, and audit chain; still needs real two-party artifacts | merged evidence bundle with allow/deny decision, including bucket/shard scope hash match when bucketed/sharded jobs are used |
| Negative-case panel | Repo-side implemented | `/v1/pjc-mtls/negative-cases/run` covers wrong token, expired token, wrong CA, wrong peer, closed port, commit mismatch, modified CSV, and privacy denial; still needs live negative evidence | typed negative-case summary with every expected denial |
| Public bucketed TLS EOF noise | Mitigated by live evidence + typed readiness | The completed clean-room `cross-vps-008` public run on `118.190.61.66:10504` proves `TLSv1.3` mTLS succeeds for all 8 buckets. The repeated `SSL_accept unexpected eof` lines on Party A correlate with the old plain-TCP readiness touch, not with workload failure. `pjc_tls_readiness/v1` now exists to replace that probe with a real typed mTLS readiness check. | Keep bucketed wrappers on `pjc_tls_readiness/v1`; archive future public runs with `public_two_host_live_evidence_archive/v1` |
| Full guided frontend wizard | Repo-side implemented | The `#s9-wizard` flow exists in `scripts/serve_operator_dashboard.py`; it still needs an operator walkthrough on two hosts. | operator walkthrough recording or screenshots plus successful API trace |
| Server-side release gate | Repo-side implemented | `POST /v1/release/policy-gate` and `scripts/check_release_policy_gate.py` enforce DP metadata, k, privacy-budget ledger, duplicate-query defenses, bound PJC evidence, and uploaded external-anchor evidence when configured. | repeated-query denial, low-k denial, DP metadata evidence, PJC result-binding denial, and live S3/Rekor anchor evidence from the deployed release path |

## Project Security Risk Register

This section separates project-owned security work from deployment-owned trust
roots. The project should close code, schema, and scriptable verification gaps;
it should not claim ownership of enterprise accounts, external WORM storage,
or production network identity systems supplied by an operator.

For reviewer-facing language, this project should be described as:

- a **database/control-plane + SSE + Google PJC** privacy-compute platform
- with `ecommerce` as a **key business-adaptation narrative**, not the
  replacement for the technical kernel
- and with the current PJC compute core explicitly bounded as
  `semi-honest/operator-controlled`

Here `semi-honest` means both parties are assumed to follow the Google PJC
protocol steps correctly while still trying to infer as much as possible from
allowed views such as inputs, outputs, logs, timing, and metadata. It does
**not** mean the project is unsafe, and it does **not** mean the parties are
trusted to provide truthful business data or to avoid malicious protocol
deviation forever. It means the current safety story is split across protocol
assumptions, engineering controls, and governance controls.

| Risk | Project-side control | Remaining verification |
| --- | -------------------- | ---------------------- |
| Real cross-machine mTLS evidence | S9 preflight, role package, role lifecycle, evidence merge, negative-case runner, and TLS diagnostic endpoints are implemented. | Run the full scriptable flow on two hosts and archive both parties' reports. |
| Public post-run `tcp_refused` after a completed run | Not a blocker when a fresh completed archive exists | `pjc_tls_diagnostic/v1` run after Party A exits will legitimately report `tcp_refused`. `public_two_host_production_readiness_gate/v1` now prefers a fresh `public_two_host_live_evidence_archive/v1` over a post-run listener probe when the archive proves the completed run. | Preserve fresh archive + clean-room report so the gate can distinguish “listener exited after success” from “listener never came up” |
| Malicious or malformed participant input | Input manifests, package hashes, preflight CSV/hash checks, and negative cases catch tampering at the wrapper layer. | S8 commit-and-prove / malicious-secure PSI-SUM remains a protocol-hardening path for adversarial participants. |
| Public release bypass | `release_policy_gate/v1` enforces DP/k/privacy-budget/PJC-evidence/external-anchor conditions before release. | Ensure every deployed public-release path calls the gate; no direct bypass to lower-level scripts. |
| Metadata / side-channel leakage | Public-report redaction, bucket suppression, DP metadata, min-row side-channel controls, audit API caller-safe summaries, and repo-side dashboard role-gated public summaries exist. | Small-shard merge/padding, console route-level caller-safe views, and live/operator review of the deployed dashboard auth path remain open. |
| Resource exhaustion / DoS | Role lifecycle uses controlled env allowlists, timeout/cancel state, preflight resource fields, and role status logs. | Real large-input and timeout evidence on the deployment hosts. |
| Audit credibility | The project produces structured evidence, hashes, merge reports, policy-gate reports, and external-anchor interfaces. | The immutable trust root is operator-provided: Rekor/Sigstore, S3 Object Lock, enterprise WORM storage, timestamp authority, or internal audit platform. AWS S3 Object Lock is not required for student validation when no enterprise account is available. |

Audit credibility is therefore an integration boundary, not an unsolved
student-side defect. The platform's responsibility is to emit stable,
hash-addressed reports and expose anchoring hooks; the deployment's
responsibility is to provide and operate the external immutable sink.

## Malicious-Participant Narrative

The remaining PJC security problem should be described precisely. The most
important unresolved risk is **not** "the attacker immediately reads all
plaintext". The more realistic remaining risk is:

1. a participant can provide semantically false but structurally valid source
   data and obtain a mathematically correct result over dishonest business input
2. a participant can deviate from the protocol or selectively abort, producing
   misleading evidence or misleading business conclusions
3. a participant can try to package a false result as a normal run unless the
   release, approval, and audit chain stop it

That is why the current project should not claim `malicious-secure` PJC.

### What is already solved inside the current framework

The project already has meaningful engineering controls:

1. `SSE` limits the data entering the computation to candidate-selection output
   rather than exchanging full raw datasets
2. record recovery and bridge tokenization constrain the plaintext boundary
3. input manifests, package hashes, preflight CSV/hash checks, and negative
   cases catch many wrapper-layer tampering mistakes
4. signed two-party evidence, release binding, privacy budget, approval flow,
   audit chain, and external-anchor hooks make false publication harder to hide

These controls are valuable and should be claimed as such. They are stronger
than a bare protocol demo. They are **not** the same thing as full
malicious-secure computation.

### What must be explained as protocol-internal vs protocol-external

The remaining security story should be split into two tracks:

1. **Protocol-internal hardening**
   This is the part that would actually change the PJC adversary model. It
   requires a stronger active-secure or malicious-secure backend, such as an
   active-secure PSI-SUM / 2PC path, rather than simply wrapping the current
   Google PJC binary and claiming the core changed.
2. **Protocol-external governance**
   This addresses source truthfulness and release legitimacy through signed
   approvals, sealed/hash-bound inputs, release gates, immutable archives, and
   post-run audit accountability. This track is a legitimate part of the
   security story because real business-data truthfulness and formal release
   authority are not solved by the compute kernel alone.

   Status update as of 2026-06-05:

   - Repo-side typed artifacts now exist for this track:
     `source_export_manifest/v1`, `source_attestation/v1`,
     `source_truthfulness_report/v1`, and `release_governance_report/v1`.
   - Strict release configs can now fail closed on missing attestation,
     unsigned signoff, stale/planned/local/manual evidence, and unbound
     input-commitment / release-hash drift.
   - This closes the remaining **repo-side** governance gap for
     source-truthfulness and release-legitimacy claims. It does **not** upgrade
     Google PJC from `semi-honest` to `malicious-secure`.

### Competition-safe wording

For a competition artifact, the stable claim should therefore be:

- the current platform provides a **semi-honest compute core with strong
  engineering constraints and verifier-facing evidence**
- the remaining malicious-participant gap is explicitly understood
- source truthfulness and release legitimacy are controlled partly through
  governance and partly through the release/audit pipeline
- the project does **not** overclaim that "adding a proof layer" automatically
  turns Google PJC into a malicious-secure protocol

## Scriptable Two-Host Verification Path

When two machines are available, prefer scripts and typed endpoint evidence
over manual inspection:

1. Sync both hosts to the same commit. If the VPS cannot reach GitHub directly,
   use `scripts/sync_vps_github_via_local_proxy.sh` from the local machine.
2. Party A starts enrollment with
   `a-psi/moduleA_psi/scripts/serve_pjc_mtls_enrollment_party_a.sh`.
3. Party B enrolls with
   `a-psi/moduleA_psi/scripts/enroll_pjc_mtls_party_b.sh` using the printed
   `PJC_MTLS_BOOTSTRAP`.
4. Generate and split the bucketed job with
   `a-psi/moduleA_psi/scripts/generate_bucketed_pjc_dataset.py` and
   `a-psi/moduleA_psi/scripts/split_bucketed_pjc_job_for_parties.py`.
5. Use the dashboard wizard or direct endpoints for:
   - `POST /v1/pjc-mtls/preflight`
   - `POST /v1/pjc/role-package/export`
   - `POST /v1/pjc/role-package/import`
   - `POST /v1/pjc/roles/server/start`
   - `POST /v1/pjc/roles/client/start`
   - `GET /v1/pjc/roles/{role}/status`
   - `POST /v1/pjc/evidence/verify-merge`
   - `POST /v1/release/policy-gate`
   - `POST /v1/pjc-mtls/negative-cases/run`
6. If the data-plane handshake fails, run
   `POST /v1/pjc-mtls/tls-diagnostic` before changing the configuration so the
   failure is captured as `pjc_tls_diagnostic/v1`.
7. Archive the resulting `pjc_two_party_preflight/v1`,
   `pjc_role_package/v1`, `pjc_role_status/v1`,
   `pjc_two_party_evidence_merge/v1`, `release_policy_gate/v1`,
   `pjc_two_party_negative_cases/v1`, and `pjc_tls_diagnostic/v1` reports.
8. Before spending operator time on a new public run, execute
   `scripts/check_public_two_host_production_readiness_gate.py`. It now
   packages the repo-side two-party/TLS/release baseline, archived S7/K3
   evidence integrity, and optional live VPS management/data-plane probes into a
   single report. A TCP-reachable host that answers candidate admin ports with
   an HTTP `502 Bad Gateway` pattern is a live blocker, not valid management
   evidence.

The existing local regression scripts remain the fast gate before attempting
the live run:

- `python3 scripts/check_pjc_two_party_smoke.py`
- `python3 scripts/check_pjc_tls_diagnostic_smoke.py`
- `python3 scripts/check_release_policy_gate_smoke.py`
- `python3 scripts/check_spiffe_envoy_templates.py --assert-allow`
- `bash scripts/check_json_contracts.sh`

## Immediate Next Tasks

1. ~~Enforce `EXPECTED_CA_FINGERPRINT` in Party B enrollment.~~ Done 2026-05-17.
2. ~~Add one-time / TTL pairing token support.~~ Done 2026-05-17.
3. ~~Auto-stop Party A enrollment after one successful enrollment.~~ Done
   2026-05-17 (also supports optional idle-timeout shutdown).
4. Run and archive a real VPS-to-laptop 1k bucketed mTLS evidence set, and
   include the matching `enrollment_audit.jsonl` line in the evidence bundle.
5. ~~Convert the bucketed scale-test web endpoint from synchronous request to
   background job + polling.~~ Done 2026-05-17 (backend); SPA polling still
   owned by Engineer B.
6. ~~Add contract smoke coverage for bucket suppression and DP metadata.~~ Done
   2026-05-17 — `scripts/check_bucket_dp_smoke.py` is wired into
   `scripts/check_json_contracts.sh` and asserts six invariants (below-k
   suppression, above-k DP-aware release, public-report DP metadata,
   `--require-dp` fail-closed on both stages, released-sum equality).
7. ~~Carve out a dedicated enrollment-only HTTP server mode so the rest of the
   dashboard surface is never exposed during enrollment.~~ Done 2026-05-17 —
   `--mtls-enrollment-only-mode` is on by default in
   `serve_pjc_mtls_enrollment_party_a.sh`; opt out with `DASHBOARD_FULL_SURFACE=1`.
8. Lift the per-CLI `--require-dp` into a server-side mandatory policy gate so
   the privacy budget ledger and DP enforcement apply to *every* release mode,
   not just the bundled scripts (continuation of S3).

## Verification Notes (2026-05-17)

The new pairing-token state machine and shutdown hook were exercised in-process
against `scripts/serve_operator_dashboard.py` with an isolated temp directory:

- `_ensure_pairing_token()` writes the metadata sidecar with the configured TTL
  and max-enrollment caps.
- A wrong token is rejected with `invalid_token` and logged.
- A malformed CSR with a valid token is rejected with `invalid_csr` and logged.
- A real RSA-2048 CSR + valid token signs successfully, returns
  `enrollments_remaining=0`, fires the shutdown hook with reason
  `"max enrollments reached"`, and deletes the token + meta files. A second
  attempt with the same token is then rejected as `invalid_token`.
- Forcing `issued_at_epoch` into the past triggers `token_expired`, fires the
  shutdown hook with reason `"pairing token expired"`, and deletes state.

These traces are reproducible via the inline Python harness used during the
2026-05-17 work session. Task #6 below is now done: `check_bucket_dp_smoke.py`
is the first permanent contract-smoke gate around the bucket/DP layer; the
pairing-token state machine itself still relies on the inline harness above.

## Round 5 Additions (2026-05-17)

- `scripts/check_bucket_dp_smoke.py` is the new permanent contract smoke for
  the bucket suppression + DP metadata invariants. Wired into
  `scripts/check_json_contracts.sh` and `scripts/check_ci_smoke.sh`.
- Recovery service learned `--suppress-min-rows-side-channel`: when on,
  below-min results return a uniform zero-row success indistinguishable from
  a genuine no-match. Audit log still records `min_rows_suppressed=true` for
  the operator.
- Bridge `normalize_phone` now rejects bare `+`, > 15 digits, and `+0...`
  (E.164 country codes cannot start with 0). Existing valid tokens unchanged;
  5 new `cargo test` cases ride along.

See `docs/CONTROL_PLANE_HARDENING_LOG.md` for the cross-cutting audit-ID index
across all five rounds.

## Round 6 Additions (2026-05-17)

Four new contract-smoke scripts pin the Round 3–4 hardenings into CI so a
future refactor that regresses them fails the build rather than silently
flipping the surface back. All four are wired into
`scripts/check_json_contracts.sh` and the `scripts/check_ci_smoke.sh`
`py_compile` list.

- `scripts/check_enrollment_only_mode_smoke.py` (A.13) — five blocked paths
  return 404 `enrollment_only_mode`; `/healthz` and `POST /v1/pjc-mtls/enroll`
  reach handlers.
- `scripts/check_bucketed_scale_test_async_smoke.py` (A.14) — async 202 →
  polling → list, plus legacy `?sync=1`.
- `scripts/check_metadata_api_rate_limit_smoke.py` (A.15) — per-caller token
  bucket returns HTTP 429 past burst; `/healthz` is never rate-limited.
- `scripts/check_min_rows_side_channel_smoke.py` (A.10) — locks in the helper
  contracts and the service-state field so the toggle can't silently disappear.

## Round 7 Additions (2026-05-17)

S5 (public-report metadata leakage) is now closed in code for the field
redaction half. The small-shard merge/padding half is still Owner / Engineer B
work; see `docs/CONTROL_PLANE_HARDENING_LOG.md` § Items left open.

- `policy_release.py --public-report-redact-operator-fields` strips
  `input_sizes`, `rate_limit_used`, `rate_limit_max`, `bridge`, and `details`
  from `public_report.json`. The full report is written to a sibling
  `operator_release_report/v1` document (`--operator-report-path`, default
  `<out>.operator.json`).
- `policy_postprocess_buckets.py --public-report-redact-operator-fields`
  skips writing `debug.per_bucket_results` / `debug.bucket_policy` into the
  public report; `bucket_public_report.json` is release-safe, while
  `operator_bucket_report.json` carries full per-bucket raw/noise evidence.
- `run_bucketed_scale_test.sh` passes both flags by default.
- `scripts/check_bucket_dp_smoke.py` was extended with a second-pass redacted
  run that asserts (a) no operator-only keys leak into `public_report.json`,
  (b) `operator_report.json` carries the full set with
  `schema=operator_release_report/v1`, and (c) the bucket postprocess writes
  `debug.bucket_results_redacted=true` instead of the per-bucket detail.

## S9 Verification Notes (2026-05-23)

Re-verified the two-party out-of-box control-plane contracts on the current
working tree. Repo-side state matches the previous note and still passes
locally:

- `python3 scripts/check_pjc_two_party_smoke.py` — all five subchecks pass
  (preflight allow + `input_manifest_hash_mismatch` deny; role package export +
  import round-trip + tampered-payload deny; `_start_role` / `_role_status_payload`
  / `_cancel_role` round trip against `/bin/true`-style surrogate role script;
  evidence merge agreement + `result_hash_mismatch` deny; all eight required
  negative cases — `wrong_token`, `expired_token`, `wrong_ca`, `wrong_peer`,
  `closed_port`, `commit_mismatch`, `modified_csv`, `privacy_denial`).
- `bash scripts/check_json_contracts.sh` validates the five existing two-party
  schemas plus the four new schemas added this session.
- `python3 scripts/check_enrollment_only_mode_smoke.py` and
  `python3 scripts/check_bucketed_scale_test_async_smoke.py` both report
  `"status": "ok"` against the dashboard server.

## S9 Additions (2026-05-23 v2)

The four remaining repo-side gaps from the previous status entry are now
closed locally. Each comes with a deterministic smoke that does not require
a real cluster or two real hosts.

1. **Guided wizard.** `scripts/serve_operator_dashboard.py` now renders an
   in-page wizard (`#s9-wizard`) that chains `Invite → Enroll → Preflight →
   Run → Verify → Negative cases → Archive` against the existing endpoints.
   Each step blocks the next until the backend returns `decision=allow` (or
   `status=ok`), surfaces typed reports inline, and exposes copyable
   `bootstrap_uri`, cert paths, role-package paths, and final evidence paths.
2. **Production role lifecycle defaults.** `_role_command` defaults
   `cert_dir`, `role_dir`, and `out_dir` to discoverable repo-side paths
   (`tmp/pjc_mtls_shared/certs`, `tmp/pjc_role_dirs/<job>`,
   `tmp/pjc_two_party/runs/<job>_<role>`), validates that the cert dir
   carries the per-role material (`ca.crt` + `server.{crt,key}` or
   `client.{crt,key}`) and that `job_meta.json` exists in the role dir
   before launching, and broadens `PJC_ROLE_ENV_ALLOWLIST` to pass through
   `PJC_DIR`, `PJC_BUILD`, `GRPC_MAX_MESSAGE_MB`, `PJC_RESOURCE_LIMITS`,
   `PJC_PREFLIGHT_*`, `RUN_PJC_SERVER_SH`, `RUN_PJC_CLIENT_SH`,
   `SHARED_RESULT_DIR`, and `SERVER_ADDR`. Smoke tests still use an
   explicit `script` override which bypasses the preflight; the production
   path is fail-closed.
3. **Live TLS diagnostic.** `POST /v1/pjc-mtls/tls-diagnostic` produces
   `pjc_tls_diagnostic/v1` capturing TCP outcome, TLS error category
   (`tls_eof`, `tls_alert_handshake`, `tls_protocol_mismatch`,
   `tls_unknown_ca`, `tls_self_signed`, `tls_verify_failed`,
   `io_permission_denied`, `tcp_refused`/`tcp_timeout`/`tcp_no_route`,
   `other`), peer cert fingerprint, local cert/key/CA presence, an
   optional redacted server-log tail, and a suggested operator action.
   Smoke: `scripts/check_pjc_tls_diagnostic_smoke.py` (closed port,
   TCP-accept-then-immediate-close `tls_eof`, missing local certs).
4. **SPIFFE/SPIRE + Envoy templates.** `deploy/spiffe_envoy/` adds
   `spire_server.conf`, `spire_agent.conf`, `envoy_party_a.yaml`,
   `envoy_party_b.yaml`, `peer_spiffe_allowlist.json` (matching
   `spiffe_envoy_peer_allowlist/v1`), and `rotation_notes.md`. The
   allowlist is validated by the JSON contracts check; the structural
   lint `scripts/check_spiffe_envoy_templates.py` emits
   `spiffe_envoy_template_check/v1` and is also wired into the contracts
   gate via `--assert-allow`.
5. **Server-side release policy gate.** `POST /v1/release/policy-gate` +
   `scripts/check_release_policy_gate.py` consume a public report (and an
   optional operator report, privacy budget ledger, PJC evidence merge, policy
   audit log, and external anchor report) against
   `config/release_policy_gate.example.json` and emit
   `release_policy_gate/v1`. They close the `--require-dp` CLI bypass by
   requiring DP metadata, k threshold ≥ policy minimum, an allowed-deny
   reason code for denied releases, a privacy-budget ledger record for
   allowed releases, and a defense-in-depth check that any
   duplicate-query budget decision is not silently released. Strict production
   config also requires bound two-party PJC evidence and an uploaded S3
   Object Lock/Rekor external anchor report before public release. Smoke:
   `scripts/check_release_policy_gate_smoke.py` covers missing ledger,
   low-k, missing DP, allowed release, duplicate-query leak, result-hash
   replacement, missing external anchor, planned/local anchor denial, and
   uploaded S3 anchor allow.

Still required before claiming live "two-party out-of-box" certified:

1. A real two-host / VPS run that produces matching `pjc_two_party_preflight/v1`
   reports on Party A and Party B, a matching pair of role packages and import
   validations, role lifecycle status JSON with non-zero TLS bytes, bucket/shard
   policy hash evidence for bucketed or sharded jobs, an evidence merge with
   `decision="allow"`, an uploaded external anchor report bound by a passing
   `release_policy_gate/v1`, and the negative-case summary recorded against
   real certificates.
2. Root-cause and resolution for the public-10502 TLS EOF observed in the
   previous bucketed VPS attempt — the diagnostic now records the
   `tls_eof` category and a suggested action; the underlying network /
   socat / Envoy decision is owed.
3. Operator-tested rollout of the SPIFFE/SPIRE + Envoy templates against a
   real cluster (the templates are structural references that the lint
   guarantees stay coherent; cluster validation is still owed). This boundary
   is now tracked explicitly by `spiffe_envoy_identity_gate/v1`: repo-side
   template and allowlist coherence are frozen, but live SPIFFE/Envoy evidence
   remains `skipped` until operator artifacts are supplied. Those artifacts now
   also have a stable archive shape: `spiffe_envoy_live_evidence_archive/v1`.
4. Immutable external anchor publication is now tracked the same way:
   `external_anchor_evidence_gate/v1` freezes repo-side publisher + release-gate
   semantics, while `external_anchor_live_evidence_archive/v1` provides the
   bundle shape for live S3 Object Lock / Rekor evidence once operator
   credentials and real sinks are available.
