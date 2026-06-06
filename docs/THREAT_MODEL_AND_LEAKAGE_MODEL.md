# Threat Model And Leakage Model

## 1. Goal

This document makes the current privacy boundary explicit for the frozen pipeline:

```text
SSE export -> record recovery -> bridge -> PJC -> policy release
```

It does not redefine the pipeline. It records:

1. what assets exist
2. who is allowed to see which layer
3. what each stage is allowed to leak
4. which current controls reduce that leakage
5. which residual risks remain

For the repo-side vs operator-side governance split and the answer-ready
boundary between protocol-internal and protocol-external work, see
[ONLINE_OFFLINE_SECURITY_GOVERNANCE.md](ONLINE_OFFLINE_SECURITY_GOVERNANCE.md).

## 2. Scope

This threat model covers the current repository implementation:

1. `sse/`
2. `services/record_recovery/`
3. `bridge/`
4. `a-psi/`
5. `scripts/run_sse_bridge_pipeline.sh`
6. `scripts/run_live_sse_bridge_demo.sh`
7. current sidecar read adapters and benchmark tooling

It does not claim to cover:

1. a real external KMS/HSM deployment
2. a real multi-tenant production identity plane
3. container or VM isolation outside the local prototype
4. network perimeter controls outside the local loopback examples

## 3. Protected Assets

### Highest sensitivity

1. raw join keys such as email, phone, device ID, internal user ID
2. encrypted record-store passphrases
3. bridge token secret material (`Ktoken`)
4. any future authn/authz callback secrets

### High sensitivity

1. candidate ID sets returned by SSE queries
2. bridge-ready recovered plaintext rows
3. unhashed filter values before audit hashing
4. record-store plaintext rows before encryption

### Medium sensitivity

1. tokenized bridge inputs
2. PJC result files before release policy
3. detailed audit trails
4. metadata sidecar registry / policy / job records

### Lower sensitivity

1. released public reports after policy gating
2. derived observability aggregates
3. default catalog/lineage artifacts without full paths

## 4. Trust Boundaries

### Boundary A: SSE state and query surface

Allowed inside:

1. encrypted/searchable SSE state
2. query execution inputs
3. candidate selection

Current controls:

1. policy-gated export
2. caller-scoped tenant/dataset/service checks
3. audit logging with hashed filters

### Boundary B: record recovery

Allowed inside:

1. candidate ID set
2. encrypted record store
3. plaintext row recovery for authorized candidates only

Current controls:

1. subprocess worker or standalone Unix-socket / HTTP service
2. allowed caller / output root / record-store root enforcement
3. service audit and runtime logs
4. optional shared `sse_export_policy/v1` authz reuse

### Boundary C: bridge

Allowed inside:

1. bridge-ready plaintext rows
2. join-key normalization
3. scoped HMAC tokenization
4. PJC CSV preparation

Current controls:

1. production-mode secret handling
2. bridge audit
3. key-manifest / key-agent / external-KMS secret resolution options
4. FIFO handoff option to reduce at-rest plaintext

### Boundary D: PJC

Allowed inside:

1. tokenized join keys
2. client values needed for the computation
3. protocol logs and result files

Current controls:

1. bridge metadata validation
2. PJC stage audit
3. release always follows through policy gating

Security-model note:

- The current PJC stage is intentionally described as `semi-honest/operator-controlled`.
- In this repository, `semi-honest` means each party is assumed to follow the Google PJC protocol steps correctly while still trying to infer as much as possible from allowed views such as inputs, outputs, logs, timing, and metadata.
- This does **not** cover malicious protocol deviation, semantically false source data, or a participant intentionally trying to package a false business result as a valid run.

### Boundary E: policy release

Allowed inside:

1. raw PJC result
2. threshold / duplicate-query / release checks
3. release audit and public report generation

Current controls:

1. threshold `k`
2. duplicate-query deny mode
3. release audit with `correlation_id`
4. audit-chain sealing and optional archive indexing
5. optional `privacy_budget_ledger/v1` release gate for exact repeated query fingerprints, overlapping / containing query windows, and caller-local budget exhaustion
6. `source_export_manifest/v1` + `source_attestation/v1` +
   `source_truthfulness_report/v1` bind the source snapshot, bridge inputs,
   input commitment, approval id, operator identity, signoff status, and
   freshness checks into the release path
7. `release_policy_gate/v1` + `release_governance_report/v1` bind the
   attestation hash, truthfulness verifier result, input commitment, and final
   release decision into reviewer-facing governance evidence

## 5. Threat Actors

### A. Curious internal operator

Capabilities:

1. can run local scripts
2. can inspect local files available to the same Unix user
3. may try to read intermediate artifacts or logs

Primary risks:

1. reading bridge-ready plaintext files
2. reading raw record-store source files before encryption
3. reusing service configs with broader output roots

### B. Misconfigured service caller

Capabilities:

1. can reach the recovery service over configured local socket or HTTP endpoint
2. may present the wrong caller / tenant / dataset / service identity

Primary risks:

1. unauthorized record recovery
2. path traversal into unexpected output locations
3. service scope confusion

### C. Local compromise of one stage user/process

Capabilities:

1. can read that stage's working files
2. can inspect environment variables for that process
3. can replay allowed local commands

Primary risks:

1. `Ktoken` exposure through env-backed secret refs
2. bridge-ready plaintext disclosure
3. audit tampering if the same principal can both write and modify artifacts

### D. Query-abuse caller

Capabilities:

1. can submit repeated or narrowly varied queries through allowed entrypoints
2. can attempt reconstruction from repeated aggregates

Primary risks:

1. repeated overlap analysis
2. low-`k` probing
3. inference from fine-grained windows or repeated campaigns

### E. Malicious protocol participant

Capabilities:

1. can provide semantically false but structurally valid source data
2. can modify local wrappers, manifests, or runtime parameters before or during PJC
3. can selectively abort, retry, or attempt to package a misleading business conclusion as a normal run

Primary risks:

1. mathematically correct results computed over dishonest business input
2. inconsistent evidence or misleading outputs caused by protocol deviation, bucket/shard manipulation, or selective abort
3. false business conclusions being released unless release, approval, and audit controls stop them

## 6. Stage Leakage Model

### SSE export

Allowed leakage:

1. caller identity
2. role
3. row counts
4. candidate count
5. hashes of filter values
6. output hash and handoff type

Not allowed to leak:

1. raw filter values in audit
2. raw candidate IDs into bridge
3. raw token secret

### Record recovery

Allowed leakage:

1. service scope fields
2. caller / job / role
3. candidate count
4. input/output row counts
5. output hash
6. duration and decision

Not allowed to leak:

1. recovered plaintext rows into audit
2. record-store passphrase
3. raw candidate IDs into bridge or service logs

### Bridge

Allowed leakage:

1. token metadata
2. input/output row counts
3. FIFO vs file handoff type
4. output hashes and token key version

Not allowed to leak:

1. raw join keys in audit
2. raw token secret
3. candidate IDs or raw record-store details

### PJC

Allowed leakage:

1. protocol success/failure
2. input/output artifact hashes
3. result hash
4. duration

Not allowed to leak:

1. raw join keys
2. `Kstore`
3. bridge token secret

### Policy release

Allowed leakage:

1. thresholded released aggregates
2. deny reason codes
3. release decision and correlation

Not allowed to leak:

1. raw intersection membership
2. unreleased fine-grained result detail
3. secrets or raw source identifiers

## 7. Current Mitigations

Implemented mitigations:

1. export policy required by default
2. encrypted record store with PBKDF2HMAC-SHA256 + AES-256-GCM
3. record recovery behind subprocess or standalone service boundary
4. optional Unix-socket and HTTP service auth token
5. caller / tenant / dataset / service scope binding across export and recovery
6. bridge tokenization with scoped HMAC-SHA256
7. production-mode bridge secret handling
8. local key-manifest, key-agent, and external-KMS-shaped secret resolution paths
9. stage-local audits with `correlation_id` and `duration_ms`
10. audit-chain build, seal, archive, and verification helpers
11. FIFO handoff option to reduce persisted plaintext
12. default path-redacted catalog/lineage export
13. `handoff_mode` and `handoff_exposure_assessment` in `mainline_contract_check.json` make the plaintext exposure surface auditable per run (`none` / `low` / `elevated` / `unknown`), with per-role `server_exposure` / `client_exposure` breakdown
14. dedicated FIFO handoff replay (`scripts/verify_fifo_handoff_replay.sh`) wired into CI smoke; both file-mode and FIFO-mode replays assert the exposure assessment so regressions that elevate plaintext exposure fail the build
15. source-truthfulness governance is now a typed, machine-checked layer:
    source export manifest, source attestation, strict verifier, release gate,
    and release governance report are all repo-side artifacts rather than prose

## 8. Residual Risks

> **2026-05-17 update:** several items below have either moved to closed or
> gained much stronger repo-side controls. See
> [`CONTROL_PLANE_HARDENING_LOG.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/CONTROL_PLANE_HARDENING_LOG.md)
> for the audit-ID index, and item 7 below for the new entries.

Current highest residual risks:

1. bridge-ready plaintext still exists by design in file handoff mode (Owner-track S1)
2. standalone recovery service is still a local process boundary, not a separate production deployment boundary
3. secret refs are still env-backed in the local prototype — repo-side `vault_http` and `aws_kms` adapters are complete; **live Vault drill is operator-side (A.2)**
4. audit storage has a local append-only anchor log and repo-side scaffolds for `s3_worm` and `rekor` external sinks; **`--execute` against live AWS Object Lock / Sigstore Rekor is operator-side (A.12)**
5. duplicate-query denial has a privacy-budget ledger gate for near-duplicate or differencing attempts. Repo-side coverage exists through `policy_release.py --privacy-budget-ledger` and `scripts/check_privacy_budget.py`. **New (2026-05-17):** `--require-dp` fail-closed on both `policy_release.py` and `policy_postprocess_buckets.py` (A.11) plus the `scripts/check_bucket_dp_smoke.py` regression smoke close the "DP silently skipped" failure mode. **New (2026-05-20):** local production-style S3 privacy-budget closure is implemented through `policy_release.py --privacy-budget-required --privacy-budget-config`, with caller / tenant / dataset / purpose scoped ledger records and missing-scope denial. Evidence: `scripts/run_s3_privacy_budget_production_evidence.sh` and `tmp/s3_privacy_budget_production_evidence/verification_summary.json`. **New (2026-05-26):** the metadata sidecar now persists imported `privacy_budget_ledger/v1` rows in `privacy_budget_ledger_events` and exposes `query_metadata.py --list-entity privacy-budget-ledger` for scope-filtered operator reads. **New (2026-05-26 v2):** `query_workflow_request/v1`, `submit_query_workflow.py`, and `run_sse_bridge_pipeline.sh` now wire privacy-budget required/config/ledger/scope fields into Stage4 release from the operator/query submission entrypoint. **New (2026-06-06):** repo-side heuristics now actively deny close-window disjoint queries inside configured gap bounds, threshold-round probes, and cross-bucket bucket-probe patterns, instead of only exact duplicates and literal overlaps. Approval flow, VPS/public deployment evidence, and joint certification are still pending.
6. metadata and audit read adapters are read-only, but their access control is still local-token based — **timing-safe (A.3/A.6)** since the 2026-05-17 round and per-caller rate-limited on the metadata API (A.15).
7. **New cross-cutting controls landed 2026-05-17** that this document didn't previously track:
   - **A.4 / A.6 / A.7 / A.8** — keyring `allowed_callers=[]` rejected, `hmac.compare_digest` on every bearer/key-agent compare, atomic keyring write, SIGHUP authz reload on the recovery service.
   - **A.9** — `--max-candidate-ids` and `--max-request-body-bytes` cap recovery-service input before set materialization (DoS hardening).
   - **A.10** — recovery service `--suppress-min-rows-side-channel` collapses below-min into a uniform zero-row success that is indistinguishable from a real no-match; the audit still records `min_rows_suppressed=true` for the operator.
   - **A.13** — operator dashboard `--mtls-enrollment-only-mode` restricts the HTTP surface to `/healthz` + `POST /v1/pjc-mtls/enroll` during PJC Party A enrollment so the rest of the dashboard is never exposed on the bind host.
   - **A.14** — `POST /v1/bucketed-scale-test/run` is async-by-default; long jobs no longer pin an HTTP worker.
   - **A.16 / A.17** — sidecar import now atomic with explicit rollback; `available_port` sets `SO_REUSEADDR` and a `reserve_available_port` helper exists for true reservation.
   - **A.18** — phone normalizer rejects non-E.164 inputs without changing tokens for any previously-valid input.
   - **PJC mTLS rounds 1-4** — `EXPECTED_CA_FINGERPRINT` required at Party B, pairing-token TTL + max-uses + audit JSONL, server auto-shutdown after exhaustion / TTL expiry / idle.
   - **S5 (field-redaction half)** — `policy_release.py --public-report-redact-operator-fields` strips operator-only keys from `public_report.json` and routes them into `operator_release_report/v1`; same flag on `policy_postprocess_buckets.py` skips the `debug.per_bucket_results` block; `run_bucketed_scale_test.sh` passes both by default. **New 2026-06-01:** identity-backed audit API normal callers now receive caller-safe public summaries (`audit_chain_public_summary/v1`, `pipeline_observability_public_summary/v1`, `catalog_lineage_public_summary/v1`) instead of raw audit-chain/observability/catalog-lineage documents, and `scripts/check_audit_api_public_redaction.py` recursively blocks paths, hashes, exact row/timing fields, raw audit arrays, and debug fields in those public API responses. **New 2026-06-02:** `serve_operator_dashboard.py GET /v1/dashboard` requires auth when dashboard auth is configured; normal identity callers receive `operator_dashboard_public_summary/v1`, while full dashboard output is limited to privileged operator/auditor roles, with `scripts/check_operator_dashboard_public_summary.py` denying unauthenticated reads and recursively blocking paths, hashes, raw artifact lists, and exact intersection values in the normal-caller response. **New 2026-06-02 v3:** console home/jobs/audit/observability/catalog routes now branch on public-summary schemas and `scripts/check_console_dashboard_public_summary.py` plus `scripts/check_console_audit_public_summary.py` block regressions where those routes read un-narrowed full payload fields. **New 2026-06-02 v4:** identity-backed metadata API normal callers now receive `caller_safe_metadata_summary` redacted payloads for job list, job detail, caller-permissions, and policy-bindings reads; `scripts/check_metadata_api_public_redaction.py` recursively blocks paths, hashes, exact timing, raw counts, secret/backend refs, artifact payloads, and operator-only fields in those responses, and console metadata clients unwrap `metadata_api_response/v1.result` before rendering redaction notices. **New 2026-06-02 v5:** `bucket_public_report/v1` is now release-safe: below-k bucket labels/counts are omitted, exact bucket sizes are bucketized, `dp_noise` is redacted, and full raw/noise evidence moves to `operator_bucket_report/v1`; `scripts/check_bucket_dp_smoke.py` and JSON contracts reject public bucket reports that leak those fields. **New 2026-06-02 v6:** same-origin console auth now has a repo-side HttpOnly/SameSite session-cookie path (`console_browser_session_check/v1`), and the identity proxy is cookie-aware plus fail-closed when auth is configured (`identity_proxy_auth_smoke/v1`). **New 2026-06-02 v7:** operator console serving now has a repo-side CSP/security-header gate (`console_security_headers_check/v1`): no script/style inline/eval, same-origin `connect-src`, source-level inline-style/raw-HTML rejection, no framing/object embedding, no-sniff/no-referrer/permissions denial, and HSTS under Secure-cookie mode. High-sensitivity padding / delayed release / automatic bucket merge, HTTPS/Secure-cookie deployment evidence, dependency/reproducible console CI, and deployed OIDC evidence remain production strategy items.
   - Each item has at least one permanent regression smoke wired into `scripts/check_json_contracts.sh` and `scripts/check_ci_smoke.sh`.

### 8.1 Residual malicious-participant risks

Even with the current repo-side commitment checks, signed evidence merge,
release binding, privacy budget, and audit/archive controls, the following
risks remain outside the current `semi-honest` PJC claim boundary:

1. a participant can still supply source data that is false in business meaning
   while remaining structurally valid for the computation
2. a participant can still attempt protocol deviation, selective abort, or
   bucket/shard manipulation that creates misleading evidence or misleading
   business conclusions
3. a participant can still try to present a false result as a valid business
   output unless approval, release, external anchoring, and audit review stop it

These risks should be explained as a split control problem:

1. **protocol-internal hardening** addresses malicious deviation inside the
   compute stage through a stronger active-secure or malicious-secure backend
2. **protocol-external governance** addresses source truthfulness and release
   legitimacy through signed approvals, sealed/hash-bound inputs, operator
   release gates, immutable archives, and audit-backed accountability

The repo-side work completed on 2026-06-05 and tightened again on 2026-06-06 is entirely in bucket 2. It improves
source-truthfulness, release-legitimacy, and accountability claims without
changing the `semi-honest` compute-core claim.

This distinction matters for reviewer language: the project can honestly claim
stronger engineering controls and verifier-facing closure today, while still
stating that malicious-participant resistance is a separate security tier from
the now-complete live verifier-evidence tier.

### 8.2 Complete Solution Tracks

For production planning, these items are no longer tracked only as residual risks. They map to complete task packages in [PRODUCTION_SECURITY_COMPLETION_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PRODUCTION_SECURITY_COMPLETION_PLAN.md), and each package must close implementation, tests, evidence, audit, documentation, and three-person certification in one pass.

| Risk | Complete solution track |
| --- | --- |
| bridge-ready plaintext handoff | `S1` eliminates retained plaintext handoff in production mode |
| env/local secret trusted root | `S2` makes real KMS/Vault/cloud KMS the production key source |
| differencing and near-duplicate queries | `S3` adds privacy budget and query-abuse ledger controls; repo-side gate exists via `policy_release.py --privacy-budget-ledger`, `scripts/check_privacy_budget.py`, `privacy_budget_ledger/v1`, and `privacy_budget_check_report/v1`, and is verified by `scripts/verify_privacy_budget_ledger.sh`; **2026-05-20:** local production-style required mode is verified by `scripts/run_s3_privacy_budget_production_evidence.sh` (`required_without_ledger`, `exact_duplicate`, `overlap_near_duplicate`, `budget_exhausted`, `missing_scope`); **2026-05-26:** metadata sidecar persistence/query for ledger rows is repo-side complete via `privacy_budget_ledger_events`; **2026-05-26 v2:** operator/query submission now forwards required/config/ledger/scope fields into Stage4 release repo-side; **2026-06-06:** repo-side heuristics now consume close-window / threshold-round / cross-bucket differencing rules from `privacy_budget_config/v1`; live production closure still requires approval flow, VPS/public deployment evidence, and joint sign-off |
| PJC resource exhaustion or local-only runner | `S4` adds service/worker execution, preflight, limits, and streaming gRPC audit |
| public metadata leakage | `S5` — **field-redaction half closed 2026-05-17** via `--public-report-redact-operator-fields` on `policy_release.py` + `policy_postprocess_buckets.py`; **audit API caller-safe summary gate added 2026-06-01** via public-summary schemas and recursive redaction scan; **operator dashboard caller-safe summary gate added 2026-06-02** via auth-aware `/v1/dashboard` and `operator_dashboard_public_summary/v1`; **console home/jobs/audit/observability/catalog route guards added 2026-06-02 v3**; **metadata API/console caller-safe redaction added 2026-06-02 v4** via `caller_safe_metadata_summary` and `metadata_api_public_redaction_check/v1`; **public bucket label/noise redaction added 2026-06-02 v5** via `bucket_public_report/v1` / `operator_bucket_report/v1`; **same-origin browser session + identity proxy auth fail-closed added 2026-06-02 v6** via `console_browser_session_check/v1` and `identity_proxy_auth_smoke/v1`; **strict console CSP/security headers added 2026-06-02 v7** via `console_security_headers_check/v1`; high-sensitivity auto-merge / padding, HTTPS/Secure-cookie evidence, dependency/reproducible console CI, and deployed OIDC evidence remain Owner / Engineer B work |
| local-only audit trust | `S6` requires externally anchored audit evidence for production release |
| loopback-only cross-party validation | `S7` requires two-machine mTLS validation and peer identity checks |
| semi-honest PJC assumptions | `S8` now has a repo-side input-commitment gate for bridge-generated CSV tamper detection plus signed evidence merge and release binding; protocol-internal malicious-secure compute and stronger source-truthfulness controls remain open |

Until a track is completed and jointly certified, report it as `planned`, `partial`, or `repo-side complete`; do not present it as a solved production guarantee.

## 9. Operational Expectations

Until stronger deployment isolation exists, treat the following as mandatory operator discipline:

1. prefer FIFO handoff when possible
2. keep recovery-service output roots narrow
3. keep encrypted record stores and plaintext source files outside broad shared directories
4. avoid long-lived bridge-ready plaintext artifacts
5. use production-mode bridge secret handling in realistic runs
6. archive and verify audit bundles for any run used outside local development, and use `--anchor-key-env` when you want signed append-only archive entries
7. inspect `mainline_contract_check.json:handoff_exposure_assessment.plaintext_exposure_risk` after every run; treat any `elevated` value without a matching documented `handoff_retention_reason` as a regression, and any `unknown` value as an audit gap to investigate

## 10. Exit Criteria For A Stronger Boundary

The current threat model is materially improved when all of the following exist:

1. durable service/user separation for SSE, recovery, bridge, PJC, and policy stages
2. non-env secret storage behind a real KMS/HSM or equivalent secret backend
3. off-host or externally anchored audit evidence beyond the current local append-only anchor log
4. stronger query-abuse protections beyond exact duplicate detection
5. durable caller identity and authorization beyond local file-config and local bearer tokens

## 11. Relationship To Other Docs

Use this document together with:

1. [docs/SSE_BRIDGE_APSI_PIPELINE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/SSE_BRIDGE_APSI_PIPELINE.md)
2. [docs/INTERFACE_FREEZE_AND_CHANGE_PROCESS.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/INTERFACE_FREEZE_AND_CHANGE_PROCESS.md)
3. [docs/CORE_CONTRACT_FREEZE_MATRIX.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/CORE_CONTRACT_FREEZE_MATRIX.md)
4. [docs/BRIDGE_HANDOFF_HARDENING_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/BRIDGE_HANDOFF_HARDENING_PLAN.md)
5. [docs/OPS_RUNBOOK.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPS_RUNBOOK.md)
6. [docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md)

This document is intended to stay stable at the semantic level even if implementation details continue to move through sidecar-first changes.
