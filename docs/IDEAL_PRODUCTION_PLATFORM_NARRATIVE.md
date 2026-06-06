# Ideal Production Platform Narrative

This document describes the target production narrative for the privacy
platform. It is intentionally aspirational: it explains what the platform should
be able to claim when the implementation, live evidence, operational runbooks,
and reviewer-facing proof package are complete.

It is not the current completion report. Current status remains tracked in
[CURRENT_SECURITY_AND_COMPLETION_AUDIT.md](CURRENT_SECURITY_AND_COMPLETION_AUDIT.md)
and remaining implementation work remains tracked in
[REMAINING_WORK_IMPLEMENTATION_BACKLOG.md](REMAINING_WORK_IMPLEMENTATION_BACKLOG.md).

## 1. One-Sentence Claim

The ideal platform lets multiple business parties answer approved cross-party
matching and attribution questions without exchanging raw join keys, without
giving operators unnecessary access to plaintext, and without releasing results
until identity, authorization, input integrity, privacy budget, release policy,
and audit evidence all agree.

In production language:

```text
authorized question
-> policy-scoped candidate export
-> authorized record recovery
-> scoped token bridge
-> two-party private join and aggregate
-> release policy and privacy-budget gate
-> public report plus signed audit evidence
```

The platform is not a generic database query tool. It is a governed privacy
computation workflow. Every stage reduces what the next stage can see, and every
cross-boundary artifact is bound to identity, scope, hash, signature, schema,
and audit evidence.

## 2. Product Story

The business problem is cross-party measurement in an e-commerce or advertising
environment.

Examples:

1. An advertiser wants to know how many campaign users purchased from a merchant.
2. A marketplace wants campaign-level conversion sums without receiving buyer
   email addresses from the merchant.
3. A merchant wants aggregate attribution without receiving the platform's raw
   audience list.
4. An auditor wants to verify that a released result came from a governed run,
   not from a manually edited CSV or replaced output file.

The platform's answer is not "trust us". The platform's answer is:

1. The query was submitted by a resolved identity.
2. That identity was authorized for the tenant, dataset, purpose, and role.
3. The source export followed an explicit export policy.
4. Raw join keys were normalized and tokenized before private computation.
5. PJC input artifacts were committed by hash and checked before execution.
6. The two parties signed matching run evidence.
7. The result hash matched the release audit and evidence merge.
8. The public report passed privacy-budget, k-threshold, duplicate-query,
   differential-privacy, and redaction gates.
9. The complete evidence chain can be revalidated later.

## 3. Actors

### Query Submitter

The query submitter asks for a privacy computation. In an ideal production
system the submitter is not represented by a shared local token. It is an OIDC
or service-account identity resolved to:

1. caller
2. tenant
3. dataset scope
4. service scope
5. platform roles
6. business roles
7. allowed purposes

The submitter can request a workflow but cannot directly read intermediate
plaintext, private PJC input CSVs, raw PJC output, operator reports, or audit
internals unless separately authorized.

### Data Owner

The data owner controls one side of the records. In a two-party attribution
workflow, one party may own campaign audience data and the other may own purchase
or conversion records. The ideal platform prevents either party from receiving
the other side's raw join keys during normal operation.

### Privacy Operator

The privacy operator handles approval queues, privacy-budget exceptions,
deployment health, and incident response. The operator is powerful but still
not omnipotent: production controls should prevent an operator from silently
publishing low-k, duplicate, over-budget, or unsigned results.

### Platform Auditor

The auditor inspects evidence. The auditor should be able to answer:

1. Who submitted the query?
2. Which tenant, dataset, and purpose were used?
3. Which policies were applied?
4. Which artifacts were produced?
5. Which hashes and signatures bind them together?
6. Which release gate allowed or denied the result?
7. Whether an artifact was externally anchored.

The auditor should not need raw buyer emails or raw purchase rows to verify
workflow integrity.

### Business Roles

The ideal platform also supports ordinary business roles:

1. merchant staff
2. courier
3. customer service agent
4. buyer
5. field marketer
6. compliance auditor

These roles do not receive the same fields. Field-level policy must be enforced
before data is selected, not merely hidden in the browser.

## 4. Data Sensitivity Layers

The platform treats data as layered by sensitivity.

Highest sensitivity:

1. raw join keys such as email, phone, device ID, or internal user ID
2. record-store passphrases
3. bridge token secret material
4. KMS, Vault, OIDC, or service-account secrets

High sensitivity:

1. candidate ID sets
2. recovered plaintext rows
3. unhashed filter values
4. source business facts before validation
5. PJC input CSVs before or during execution

Medium sensitivity:

1. tokenized join keys
2. PJC raw result files
3. detailed audit logs
4. operator reports
5. metadata sidecar internals

Lower sensitivity:

1. released public reports
2. redacted public summaries
3. approved aggregate observability
4. catalog or lineage views with sensitive fields removed

The ideal system's central discipline is simple: a stage may receive only the
minimum layer needed for its job, and a lower-sensitivity output must not smuggle
higher-sensitivity details through labels, paths, hashes, debug fields, timing,
or small buckets.

## 5. Trust Boundaries

### Boundary A: Query Submission

The query surface receives structured requests. It does not execute arbitrary
commands and does not let a caller bypass policy gates.

Required production properties:

1. OIDC or service-account authentication
2. authorization by tenant, dataset, purpose, and action
3. schema validation for the request
4. semantic validation for secret source, value policy, budget, and release gate
5. audit record for submission and decision
6. dry-run mode that previews the workflow without executing it

The stable request shape is a structured query workflow, not an ad hoc shell
command. The request is translated into the pipeline only after validation.

### Boundary B: SSE Export

SSE export narrows the source dataset to candidate records. In the target
platform this is a policy-scoped operation, not a raw data dump.

Allowed leakage:

1. caller and tenant identity
2. dataset and purpose scope
3. candidate counts
4. hashed filter values
5. output artifact hash
6. handoff mode

Disallowed leakage:

1. raw join keys in audit logs
2. raw filter values in public summaries
3. full source rows outside authorized recovery
4. silent export without policy

Production mode should reject unsafe handoff patterns and avoid retained
plaintext files when FIFO or streaming handoff is available.

### Boundary C: Record Recovery

Record recovery is where encrypted or protected records become plaintext for
authorized candidates. This stage is dangerous and must be tightly scoped.

Required production properties:

1. service identity
2. caller/tenant/dataset authorization
3. record-store root restrictions
4. output root restrictions
5. row and field policy checks
6. request/response audit
7. no raw candidate IDs or passphrases in logs
8. deployable service boundary rather than only a local subprocess
9. production HTTP startup requires authn/authz plus signed requests or mTLS
10. non-loopback recovery listeners require mTLS client certificates

The ideal recovery service is independently deployable and can be tested for
fail-closed behavior on malformed identity, wrong scope, path traversal, and
unauthorized output.

### Boundary D: Bridge

The bridge converts recovered rows into private-computation input. It normalizes
join keys and creates scoped HMAC tokens. Its job is to prevent raw join keys
from crossing into PJC.

Required production properties:

1. stable normalizer semantics
2. scoped token secret resolution through KMS or approved secret backend
3. no raw token secret on production CLI
4. token scope and key version recorded
5. source hash recorded where available
6. output CSV hash recorded
7. row count recorded
8. raw-int value policy recorded and enforced, including range, allowed value
   field, unit, and currency semantics
9. input commitment written beside generated PJC CSVs

The bridge creates a contract: "these exact committed PJC inputs were derived
under this scope, normalizer, value policy, and key version." Later stages must
refuse to proceed if the contract no longer matches.

### Boundary E: PJC

Private Join and Compute runs the two-party computation. In the target system,
PJC does not receive raw email or phone values. It receives tokenized join keys
and the minimum values required for the aggregate.

Required production properties:

1. input commitment required before launch
2. preflight validation of CSV hashes, row counts, token scope, normalizer, and
   value policy
3. resource limits
4. streaming mode for large inputs
5. mTLS or equivalent peer identity
6. two-host evidence for real public-network operation
7. signed run manifests from both parties
8. evidence merge that checks signatures, peer identity, commitment hashes, and
   result hashes

The ideal malicious-security claim must be explicit. If the system uses a
semi-honest PJC protocol plus operational commitments, then the claim must say
so. If the product wants malicious-secure claims, it must add the appropriate
cryptographic protocol, range proof, or proof system and test it as a first-class
security boundary.

### Boundary F: Release Policy

PJC output is not public output. It is an internal result that must pass release
policy.

Required production properties:

1. minimum k threshold
2. duplicate-query denial
3. overlap and near-duplicate controls
4. privacy-budget ledger
5. approval queue for exceptional releases
6. DP requirement when configured
7. public/operator report separation
8. bucket redaction and suppression below threshold
9. release gate binding to PJC result hash and evidence merge
10. audit-chain hash embedded into release evidence

The public report should contain the least information needed by the business
question. Operator-only data such as raw bucket sizes, exact paths, internal
hashes, debug fields, and detailed timing must stay out of caller-facing output.

### Boundary G: Audit And External Anchor

The ideal platform produces evidence that can be verified after the fact.

Required production properties:

1. schema-validated audit records
2. canonical hashes for important artifacts
3. signed two-party manifests
4. audit chain and seal
5. release gate report
6. immutable external anchor
7. tamper-negative verification
8. runbook for evidence collection

When cloud infrastructure is available, the external anchor may be AWS S3 Object
Lock, Rekor, a corporate immutable ledger, or another append-only system. When a
cloud account is not available, the repository may carry the interface, schema,
mock sink, and runbook, but it must not claim that external immutability has
been proven live.

### Boundary H: Console And Operator UI

The browser console is useful but dangerous. It concentrates workflows,
approvals, audit reads, and operator decisions.

Required production properties:

1. HTTPS
2. HttpOnly session cookies
3. Secure cookie mode in deployed HTTPS
4. no bearer token persistence in localStorage
5. strict CSP without inline script/style or unsafe eval
6. same-origin API credentials
7. identity proxy that strips spoofed identity headers
8. caller-safe public summaries for normal users
9. privileged operator views only for authorized roles
10. reproducible release build
11. dependency lockfile, SBOM, and blocking typecheck/build gate

The console must not become the place where raw audit internals accidentally
leak to normal users.

## 6. End-To-End Query Narrative

An ideal production query follows this path.

### Step 1: Submit The Question

A caller submits:

1. query type
2. server and client source references
3. join key fields
4. value field and value policy
5. filters
6. tenant and dataset scope
7. purpose
8. privacy-budget configuration
9. release policy requirements
10. job ID and output scope

The request is schema-valid and semantically valid. If the caller uses raw-int
values in production, the request must include explicit bounds. If privacy
budget is required, the request must include budget config and ledger. If
release gate is required, the release-gate config must be present.

### Step 2: Resolve Identity

The API resolves the caller from OIDC, service-account credentials, or an
approved identity source. The resolved identity is mapped to platform roles and
business roles.

The platform checks:

1. Can this identity submit this query?
2. Is this tenant allowed?
3. Is this dataset allowed?
4. Is this purpose allowed?
5. Is this service allowed to invoke record recovery, bridge, PJC, and release?

If not, the workflow stops before any source data is touched.

### Step 3: Export Candidates

The SSE export step applies filters and policy. It emits a candidate handoff and
an export audit. It does not publish raw keys or raw source rows.

If production mode requires FIFO or streaming handoff, retained plaintext handoff
files are denied.

### Step 4: Recover Authorized Records

If encrypted record stores are used, the recovery service receives the candidate
set and returns only authorized rows. The service enforces caller, tenant,
dataset, output root, record-store root, and field constraints.

The recovery service logs enough to audit the action but not enough to recreate
the sensitive data.

### Step 5: Prepare Bridge Inputs

The bridge normalizes join keys and creates scoped join tokens. It writes:

1. `server.csv`
2. `client.csv`
3. `job_meta.json`
4. `bridge_audit.jsonl`
5. `input_commitments.json`

For value-bearing client rows, it records source and output value summaries and
the configured value policy.

### Step 6: Preflight PJC

Before PJC starts, preflight validates:

1. commitment hash
2. CSV hash
3. row count
4. token scope
5. normalizer
6. normalizer schema version
7. value summary
8. value bounds
9. job metadata consistency
10. resource limit and streaming requirements

Any mismatch stops the run.

### Step 7: Run Two-Party Computation

PJC runs between two authenticated parties. In the ideal public-network path,
both sides have mTLS identities and both sides later sign run manifests.

The output is an internal result, not a released public report.

### Step 8: Merge Evidence

Each party signs a manifest that binds:

1. job ID
2. repository or release version
3. local input commitment hash
4. peer input commitment hash
5. PJC result hash
6. policy decision
7. public report hash
8. audit-chain hash
9. peer TLS identity metadata

The merge step verifies signatures and cross-checks that each party's local view
matches the other party's peer view.

### Step 9: Apply Release Policy

The release gate checks:

1. k threshold
2. duplicate and near-duplicate query risk
3. budget availability
4. required approval state
5. DP requirements
6. public report redaction
7. PJC evidence merge
8. result hash binding
9. audit-chain binding

If allowed, the platform emits a public report. If denied, it emits a denial
reason and audit record.

### Step 10: Anchor And Preserve Evidence

The platform archives the evidence bundle and anchors it externally. A later
reviewer can revalidate that:

1. the public report came from the recorded PJC result
2. the PJC result came from committed inputs
3. the committed inputs matched bridge outputs
4. the release policy allowed the result
5. the audit chain has not been silently replaced

## 7. Business Data Narrative

The ideal platform supports e-commerce data without pretending every business
role can see every field.

### Merchant Staff

Merchant staff may need order status, item summary, campaign attribution, and
merchant-facing aggregates. They should not receive buyer email, phone, full
address, raw support transcripts, or unrelated platform audit internals.

### Courier

A courier may need next-stop logistics data. The courier should not receive the
full buyer profile, campaign attribution internals, complete order history, or
support case details.

### Customer Service Agent

Customer service may need protected contact channels and support status. The
agent should not receive marketing audience membership, unrelated financial
debug fields, or platform-level audit internals.

### Buyer

A buyer can see their own relevant order and delivery data. Buyer self-view is
not equivalent to tenant-wide access.

### Auditor

Auditors may receive broader metadata, evidence summaries, policy decisions, and
operator reports. Even then, the platform should prefer redacted summaries unless
raw details are necessary and authorized.

The rule is pre-selection enforcement: the backend decides which fields may be
selected before the query touches the database. The browser only renders the
already-authorized response.

## 8. Privacy Narrative

The platform protects privacy through layered controls rather than one magic
primitive.

### Data Minimization

Each stage receives only what it needs. The public report receives less than the
operator report. The normal caller receives less than the auditor.

### Tokenization

Raw join keys are normalized and HMAC-tokenized before PJC. Token scope prevents
tokens from being reused as global identifiers across unrelated jobs.

### Private Computation

PJC computes intersection aggregates without exchanging raw join-key sets.

### Release Control

Thresholds, duplicate-query denial, privacy-budget ledgers, approvals, and DP
requirements reduce differencing and reconstruction risk.

### Redaction

Public outputs omit operator-only fields, exact internal paths, raw artifact
hashes where unnecessary, below-threshold bucket labels, and debug details.

### Auditability

Privacy is not only a runtime behavior; it is an evidence claim. The platform
must prove which policies ran and which releases were denied or allowed.

## 9. Security Narrative

The ideal security story is attacker-oriented.

### Attack: Replace A PJC CSV After Bridge

Defense:

1. bridge writes input commitments
2. preflight recomputes CSV hash and row count
3. job metadata is bound to the commitment
4. PJC refuses to launch on mismatch

Evidence:

1. negative smoke that mutates CSV
2. preflight denial report
3. schema-validated commitment

### Attack: Insert Negative Or Inflated Values

Defense:

1. raw-int value policy requires bounds
2. production raw-int requires an allowed value field, value unit, and currency
   for minor currency units
3. bridge records value summaries and value semantics
4. validate/preflight recompute summaries and verify committed value semantics

Evidence:

1. negative smoke for negative value
2. negative smoke for over-max value
3. preflight finding with value-policy violation

### Attack: Expose The Legacy SSE WebSocket As Production

Defense:

1. network pickle is removed from legacy WebSocket frames
2. default bind is loopback
3. demo wide bind requires an explicit override
4. `SSE_PRODUCTION_MODE=1` retires the legacy WebSocket entirely
5. production query traffic uses query workflow / bridge pipeline APIs

Evidence:

1. `network_pickle_gate/v1` has no network-facing pickle findings
2. `legacy_sse_production_gate/v1` proves production startup denial on loopback
   and with demo override
3. live deployment evidence shows no public route to the retired WebSocket

### Attack: Launch An Unauthenticated Recovery Endpoint

Defense:

1. production mode is triggered by config, CLI flag, or
   `RECORD_RECOVERY_PRODUCTION_MODE`
2. direct HTTP adapter, standalone launcher, and managed service start/render
   share one production gate
3. HTTP recovery requires request authentication and authz
4. loopback HTTP must use signed requests or mTLS
5. non-loopback HTTP must use mTLS client certificates
6. identity-token auth must include metadata DB binding and signed requests or
   mTLS

Evidence:

1. `record_recovery_production_gate_check/v1` static policy cases
2. negative command cases for missing auth, missing authz, identity without
   metadata DB, identity without HMAC/mTLS, public listener without mTLS, and
   env-enabled production mode
3. positive systemd render cases for loopback signed-request and public mTLS
   configurations
4. live deployment evidence still required for service-user sandbox, firewall or
   Kubernetes NetworkPolicy, and real public-network mTLS traffic

### Attack: Replace PJC Result Before Release

Defense:

1. two-party signed manifests bind result hash
2. evidence merge verifies signatures and hash agreement
3. release gate compares merge result hash to policy audit

Evidence:

1. forged manifest denial
2. mismatched result hash denial
3. release gate report

### Attack: Run Repeated Near-Duplicate Queries

Defense:

1. canonical query fingerprint
2. duplicate and overlap checks
3. transactional privacy-budget ledger
4. approval queue for exceptions
5. one-time approval consumption

Evidence:

1. concurrency smoke
2. duplicate denial
3. approval lifecycle smoke
4. ledger record

### Attack: Read Operator-Only Details As A Normal User

Defense:

1. identity-aware APIs
2. public-summary response schemas
3. recursive redaction checks
4. console routes that understand public summaries

Evidence:

1. metadata public redaction smoke
2. dashboard public summary smoke
3. console public summary smoke

### Attack: Steal Browser Token Through XSS

Defense:

1. HttpOnly session cookie
2. no localStorage bearer token persistence
3. strict CSP
4. same-origin credentials
5. identity proxy fail-closed behavior

Evidence:

1. console token storage smoke
2. browser session smoke
3. security header smoke
4. deployed HTTPS/Secure-cookie evidence

### Attack: Tamper With Audit Evidence

Defense:

1. canonical audit chain
2. artifact hashes
3. seal
4. release gate binding to an uploaded external immutable anchor report
5. tamper-negative verification

Evidence:

1. anchor report
2. external sink object or entry ID
3. tamper denial
4. production local-file/planned sink denial
5. final `release_policy_gate/v1` decision showing the uploaded anchor report
   was required and accepted

## 10. Production Deployment Narrative

The ideal deployment has at least these components:

1. query workflow API
2. metadata API
3. audit query API
4. operator dashboard
5. identity proxy
6. recovery service
7. key agent or external KMS adapter
8. PostgreSQL metadata and privacy-budget store
9. PJC Party A worker
10. PJC Party B worker
11. audit archive and external anchor
12. reverse proxy with HTTPS
13. monitoring and alerting

For a minimal two-host proof, a local machine plus one VPS can demonstrate:

1. public-network TLS or mTLS
2. two-party PJC run
3. signed manifest exchange
4. release-gate binding
5. HTTPS console session behavior
6. PostgreSQL privacy-budget close-loop
7. append-only or mock external-anchor interface

AWS enterprise services can remain operator-side until a real enterprise account
exists. The platform should still provide interfaces and runbooks for:

1. AWS KMS
2. S3 Object Lock
3. cloud IAM
4. cloud audit logging

But the platform must not mark those live controls production-complete until
real account-backed evidence exists.

## 11. Operational Narrative

The ideal platform is not only secure when everything works. It must be safe
when things fail.

Required operational properties:

1. durable job state
2. idempotent workflow steps
3. crash recovery
4. retry policy
5. cancellation
6. timeout enforcement
7. resource limits
8. backup and restore
9. incident rollback
10. evidence preservation

If PJC crashes, the platform should know whether the job is pending, running,
failed, cancelled, or releasable. If release fails, the platform must not publish
a partial report. If approval is consumed, it must not be reusable after a crash.
If a privacy-budget transaction races, only one release should win.

Current repo-side evidence includes a sidecar-level guard plus metadata DB
execution lifecycle rows. An accepted dry-run can be claimed by execute only
when the request digest, job ID, and out_base match; existing running or
terminal sidecars cannot be overwritten by accidental duplicate starts;
stale-running state remains visible as `wait`. Execute paths can also write
`query_workflow_executions` rows with claim owner, lease expiry, heartbeat,
terminal state, exit code, and artifact paths. Repo-side worker evidence now
also exists: `submit_query_workflow.py --enqueue`, the API enqueue endpoint, and
dashboard approved-request enqueue mode persist queued work, while
`scripts/run_query_workflow_worker.py` owns leases outside the submit/HTTP
thread, heartbeats, honors cancellation, enforces timeout termination, and can
steal expired leases after a worker crash/restart. Evidence is
`query_workflow_durability_check/v1`, including duplicate active DB claim
denial, terminal replay denial, expired-lease steal semantics,
enqueue-to-worker completion, cancellation, timeout, and restart-steal checks.

Metadata DB backup/restore is also repo-side gated: `restore_metadata_db.py` can
bind restore to a backup report SHA-256, and
`metadata_backup_restore_drill/v1` proves local backup verification, SHA-bound
restore, restored probe-row presence, metadata schema portability, and
tampered-backup denial before restore.

This is still not the ideal durable queue. The production platform still needs
supervised deployed workers, live PostgreSQL/HA evidence, multi-worker retry
policy evidence, external backup storage, target-host restore/API smoke,
Patroni/pgBouncer failover evidence, and target-host operator-visible recovery
drills.

## 12. Supply-Chain Narrative

Production security includes the code release path.

Required properties:

1. dependency lockfiles
2. reproducible installs
3. blocking typecheck and build
4. test gate not marked continue-on-error
5. SBOM or dependency inventory
6. dependency audit interface
7. schema and contract checks
8. signed release artifact or provenance statement

The operator console especially needs a reproducible release gate because it is
the browser-facing control surface for approvals, audit review, and query
operations.

The target gate should be partly static and partly live. Static checks should
reject missing lockfiles, `npm install` fallback, advisory typecheck, missing
strict builds, and local CI paths that do not run the release-gate smoke. Live
checks should attach the actual CI/release run, SBOM, provenance, and dependency
advisory results to the evidence package.

## 13. Reviewer Evidence Package

The ideal platform can hand a reviewer an evidence package with:

1. query request
2. identity resolution report
3. export audit
4. recovery service health and audit
5. bridge job metadata
6. input commitments
7. PJC preflight report
8. PJC audit
9. Party A signed manifest
10. Party B signed manifest
11. evidence merge report
12. policy release audit
13. release gate report
14. public report
15. operator report
16. audit chain
17. audit seal
18. external anchor report
19. contract validation report
20. negative-test reports

The evidence package should let the reviewer reproduce the main claims without
access to raw join keys.

## 14. Claim Boundary

The ideal narrative must still be precise. A secure platform is not a platform
that claims every impossible property. It is a platform that states exactly what
it proves.

Safe production claims require:

1. implemented controls
2. automated positive and negative tests
3. live deployment evidence where relevant
4. documented operator runbooks
5. honest residual-risk language

Claims that require special care:

1. **Malicious-secure PJC**: do not claim it unless the protocol actually
   provides malicious security and the evidence package tests it.
2. **Truthful source data**: input commitments prove artifact consistency after
   bridge generation; they do not prove a business system supplied truthful
   values.
3. **External immutability**: local file ledgers are useful tests, not external
   immutable anchors. A production release claim requires an uploaded S3
   Object Lock/Rekor or equivalent anchor report bound by the final release gate.
   The operator console must reflect that same gate: an external-anchor denial is
   `pending_external_anchor`, and any other release-gate denial is `blocked`, not
   a completed public release.
4. **No inference risk**: thresholds and budgets reduce risk; they do not
   eliminate all statistical inference.
5. **Cloud-backed security**: interfaces are not the same as live enterprise
   account evidence.

## 15. Target End State

The target end state is a platform where:

1. a query can be submitted only by an authorized identity
2. business field access is enforced server-side
3. source export is policy-scoped and audited
4. recovered records are minimized and protected
5. raw join keys are tokenized before private computation
6. PJC inputs are committed and preflight-checked
7. two parties sign matching run evidence
8. PJC results are bound to release decisions
9. public reports are privacy-gated and redacted
10. privacy budget is transactional and approval-aware
11. operator console is HTTPS/session/CSP hardened
12. audit evidence is externally anchored
13. production jobs are durable and recoverable
14. release artifacts are reproducible
15. every claim can be defended against an attacker, a reviewer, and a production
    operator

When those conditions are met, the platform can be described as a production
privacy-computation control plane for governed cross-party matching and
attribution. Until then, documentation should continue to distinguish
`repo-side complete`, `operator-side`, and `production-complete`.
