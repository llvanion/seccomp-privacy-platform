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

## 8. Residual Risks

Current highest residual risks:

1. bridge-ready plaintext still exists by design in file handoff mode
2. standalone recovery service is still a local process boundary, not a separate production deployment boundary
3. secret refs are still env-backed in the local prototype
4. audit storage now has a local append-only anchor log, but it is not yet externally anchored or off-host tamper-evident
5. duplicate-query denial does not yet cover near-duplicate or differencing attacks
6. metadata and audit read adapters are read-only, but their access control is still local-token based

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
