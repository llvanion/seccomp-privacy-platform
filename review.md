# SSE + Bridge + A-PSI Platform Review

## 1. Current Status

The repository has a working demo-level end-to-end privacy-computing pipeline:

```text
sse controlled local export -> Rust bridge tokenization -> a-psi/PJC execution -> policy release
```

Implemented modules:

- `sse/`: searchable symmetric encryption prototype plus a policy-guarded local bridge export command
- `bridge/`: Rust CLI for join-key normalization, scoped HMAC token generation, PJC input generation, bridge metadata, and bridge audit
- `a-psi/`: PJC execution, bridge metadata validation, policy release, and audit output
- `scripts/run_sse_bridge_pipeline.sh`: cross-module orchestration with export policy checks and production-mode secret handling
- `schemas/`: initial versioned JSON schema contracts for export policy, bridge job metadata, and bridge audit

Verified demo result:

```text
intersection_size=2
intersection_sum=425
```

The modules can cooperate through a file-based interface, and the highest-risk local export/bridge boundary now has basic policy enforcement and audit. This is still not a production-grade multi-tenant database platform because the SSE export path is still local-file based rather than a true SSE-query-backed candidate extraction path.

## 2. Completed Capabilities

### 2.1 Module Separation

The workspace is organized as:

```text
a-psi/
sse/
bridge/
scripts/
docs/
schemas/
```

Responsibilities:

- `sse` handles encrypted/searchable storage prototype behavior and controlled bridge export.
- `bridge` handles sensitive local tokenization, deduplication, PJC input generation, and bridge-stage audit.
- `a-psi` handles PJC protocol execution and governed result release.
- `scripts` coordinates the demo/integration pipeline.
- `schemas` provides initial versioned contracts for the hardened boundary.

### 2.2 SSE Export Boundary

`sse` has a local export command:

```bash
.venv/bin/python run_client.py export-bridge-records --help
```

Current controls:

- requires `--policy-config` by default
- requires explicit `--unsafe-allow-no-policy` for ad-hoc local no-policy exports
- supports `--caller`, `--job-id`, and `--audit-log`
- enforces per-caller policy:
  - allowed `server` / `client` roles
  - allowed join-key fields
  - allowed value fields
  - allowed exported fields
  - required filters
  - allowed filter values
  - min/max exported row counts
- writes SSE export audit records with:
  - caller
  - job ID
  - role
  - source/output paths and SHA-256 hashes
  - input/output row counts
  - requested field names
  - hashed filter values
  - decision and reason

Sensitive values such as raw email, phone, device ID, and token secrets are not written into the export audit log.

Example policy:

```text
sse/config/export_policy.example.json
```

Schema:

```text
schemas/sse_export_policy.schema.json
```

Current limitation:

The export path now has an optional SSE-backed candidate mode: `--sse-keyword` runs an SSE query first, `--record-id-field` selects the local source field to match against returned identifiers, and `--record-id-format` controls identifier decoding. The audit log records `candidate_source`, `record_id_field`, and `candidate_count`.

It can now also read matching rows from an encrypted record store using `--record-store-path` and `--record-store-key-env`. The store uses PBKDF2HMAC-SHA256 and AES-256-GCM, and stores keyed HMAC tags instead of raw record IDs.

The remaining issue is not candidate selection anymore; it is moving record recovery/materialization behind a service-side boundary rather than local file recovery.

### 2.3 Rust Bridge

The Rust bridge currently supports:

- CSV and JSONL input
- `identity`, `email`, and `phone` normalization modes
- scoped HMAC-SHA256 join-token generation
- `server.csv` generation
- `client.csv` generation
- paired `prepare-job` generation with `job_meta.json`
- bridge metadata fields:
  - `schema`
  - `token_scheme`
  - `token_scope`
  - `token_key_version`
  - `normalize_version`
  - `dedup_policy`
  - server/client join key metadata
  - client value metadata
- bridge audit log:
  - default path: `bridge_job/bridge_audit.jsonl`
  - configurable with `--audit-log`
  - includes input/output hashes, row counts, token metadata, timestamp, production-mode flag, and token-secret source
- production-mode secret hardening:
  - `--production-mode` rejects `--token-secret`
  - `--token-secret-env` is required for production-mode runs
  - audit records only whether the secret came from CLI or an env var, not the secret value

Schemas:

```text
schemas/bridge_job_meta.schema.json
schemas/bridge_audit.schema.json
```

### 2.4 A-PSI Validation and Policy

`a-psi` includes bridge metadata validation:

```bash
python3 moduleA_psi/scripts/validate_bridge_job.py --job-dir <job_dir>
```

Current validation includes:

- required bridge metadata fields
- `input_sizes` consistency with generated CSV row counts
- optional `schema` check for `bridge_job_meta/v1`

`policy_release.py` recognizes bridge metadata and can include bridge context in the public report. It continues to support thresholding, rate limiting, audit, and optional HMAC request authentication.

### 2.5 End-to-End Orchestration

The integrated demo can be run through:

```bash
bash scripts/run_sse_bridge_pipeline.sh ...
```

The orchestrator performs:

1. pipeline policy validation for caller permissions
2. SSE controlled local export
3. Rust bridge paired job generation
4. bridge metadata validation
5. A-PSI/PJC run
6. policy release

The same policy file can now gate:

- SSE export
- bridge execution: `can_run_bridge`
- PJC execution: `can_run_pjc`
- release execution: `can_release`

For production-mode secret handling:

```bash
export BRIDGE_TOKEN_SECRET=<secret>
bash scripts/run_sse_bridge_pipeline.sh ... \
  --token-secret-env BRIDGE_TOKEN_SECRET \
  --production-mode
```

`--production-mode` rejects command-line `--token-secret`.

## 3. Remaining Gaps

### 3.1 Move Record Recovery Behind a Service Boundary

The current `sse export-bridge-records` command can now use SSE search results as the candidate set and can recover records from a local encrypted record store.

Still needed:

- ensure local recovery/export does not print sensitive join keys
- move recovery into a service-side streaming boundary or controlled worker
- avoid writing bridge-ready plaintext files except as explicitly audited handoff artifacts

This is now the highest-priority technical gap for the SSE boundary.

### 3.2 Fine-Grained Permission System

The new policy config is a minimal local policy gate, not a complete permission system.

Still needed:

- durable identity model for callers
- authorization for who can issue SSE queries
- authorization for who can access audit logs and reports
- role separation for:
  - `sse_reader`
  - `bridge_exporter`
  - `bridge_tokenizer`
  - `pjc_runner`
  - `policy_releaser`
  - `auditor`
  - `key_admin`
  - `platform_admin`
- integration with a real authn/authz service or deployment-local account model

### 3.3 Stronger Data Access Control

The current export policy covers field allowlists, required filters, allowed filter values, and row-count constraints.

Still needed for production:

- tenant-level isolation
- campaign ownership checks from a trusted source
- time-window authorization
- event-type authorization
- task/job-level authorization
- per-campaign minimum candidate-set constraints
- structured policy decisions with deny codes that can be audited across all stages

### 3.4 Key Management

Improved:

- bridge supports `--production-mode`
- bridge forbids command-line secrets in production mode
- bridge records `token_key_version`
- bridge audit records secret source without logging the secret value

Still needed:

- key-agent or KMS-like injection for `Ktoken`
- key rotation workflow
- key deactivation workflow
- separation of `Kstore`, `Ktoken`, `Kauth`, and callback secrets
- verification that PJC processes never access `Kstore` or raw join keys
- key access audit and key-version lifecycle state

### 3.5 End-to-End Audit

Improved:

- SSE export audit now records caller, job ID, filters as hashes, input/output hashes, and row counts.
- Bridge audit now records bridge input/output hashes, row counts, token metadata, production mode, and secret source.
- A-PSI policy audit already records release decision and parsed metrics.

Still needed:

- a single correlated audit view across SSE, bridge, PJC, and release
- PJC result hash in the cross-stage audit chain
- deny records for every failed bridge and PJC stage, not only successful bridge audit records
- explicit audit-log access policy
- audit integrity protection, such as append-only storage or signed audit records

Sensitive values that must remain out of logs:

- raw email
- raw phone
- raw device ID
- raw internal user ID
- token secret
- plaintext join-key dumps

### 3.6 Stronger Result Governance

Current policy release supports thresholding, rate limiting, audit, and optional HMAC authentication.

Still needed:

- overlapping-query detection
- similar-query detection
- differential attack mitigation
- per-caller task quota
- per-campaign minimum k
- amount bucketing or precision reduction
- stricter denial reports for sensitive query windows

### 3.7 Schema Contracts

Initial schemas now exist for:

- `schemas/sse_export_policy.schema.json`
- `schemas/sse_bridge_export_audit.schema.json`
- `schemas/sse_encrypted_record_store.schema.json`
- `schemas/bridge_job_meta.schema.json`
- `schemas/bridge_audit.schema.json`

Still needed:

- SSE export record schema
- bridge input CSV/JSONL schema
- PJC CSV input schema
- policy public report schema
- A-PSI audit log schema
- automated schema validation in CI or pre-run checks

### 3.8 Deployment Isolation

The current pipeline still runs in one workspace.

Production deployment should separate:

```text
sse-user
bridge-user
pjc-user
policy-user
auditor
```

Recommended access boundaries:

- `sse-user`: can access SSE state and export directory
- `bridge-user`: can read SSE exports, access `Ktoken`, and write bridge job directories
- `pjc-user`: can read tokenized CSVs and run PJC only
- `policy-user`: can read PJC result and write public reports/audit logs
- `auditor`: read-only audit access

This can be implemented through Linux users first, then hardened through containers.

## 4. Recommended Next Tasks

### Priority 1: Service-Side Record Recovery

Replace local encrypted-store recovery with:

```text
SSE query -> candidate IDs -> controlled service-side recovery stream -> bridge input
```

Keep the current policy config and audit behavior around the new path.

### Priority 2: Cross-Stage Audit Correlation

Add a consistent correlation ID and result hashes across:

- SSE export audit
- bridge audit
- PJC result
- policy release audit

### Priority 3: Schema Validation Automation

Add pre-run or test-time validation for:

- export policy config
- bridge `job_meta.json`
- bridge audit records
- public report
- policy audit records

### Priority 4: Key Management Service Boundary

Move from env-var secret injection toward a key-agent or KMS-like interface with key lifecycle state and key access audit.

### Priority 5: Deployment Isolation

Implement the role/user separation boundaries first with local Linux users and file permissions, then move toward containerized service boundaries.

### Later Backlog for Competition Polish

These are useful for a stronger works-competition submission, but can wait until the core safety path is stable:

- threat model and leakage-model document
- reproducible benchmark scripts and performance report
- multi-tenant isolation model
- deployment and operations package:
  - Docker Compose or container layout
  - backup and restore
  - health checks
  - metrics, tracing, and alerting
- data lifecycle governance:
  - dataset versioning
  - deletion and retention policy
  - key rotation re-encryption plan
- API, SDK, and admin UI:
  - REST or gRPC API
  - Python SDK
  - administrator CLI
  - audit and job-status views
- compatibility extensions:
  - more query types
  - pluggable SSE scheme selection
  - pluggable PSI/PJC backend
  - record store backend abstraction
- security audit readiness:
  - dependency vulnerability scanning
  - secret scanning
  - fuzzing for parsers and file inputs
  - unsafe deserialization review
  - untrusted input-boundary review

## 5. Current Risk Assessment

Current system is suitable for:

- local integration testing
- demo pipeline
- architecture validation
- thesis/project demonstration
- testing the export/bridge boundary policy model

Current system is not yet sufficient for:

- production data platform deployment
- strict multi-tenant access control
- audited real-user data processing
- formal key lifecycle management
- long-running service deployment with separated trust domains

The highest-risk area has been reduced but not eliminated. The bridge boundary now has policy, audit, and production-mode secret controls. The remaining highest-risk area is local bridge-ready plaintext materialization after encrypted-store recovery.

## 6. Recommended Direction

Do not start by rewriting the whole SSE module.

Recommended path:

1. Keep the current SSE module as the searchable storage prototype.
2. Move encrypted-store recovery into a service-side streaming boundary.
3. Keep the Rust bridge as the stable sensitive-data tokenization boundary.
4. Extend audit correlation and schema validation before adding new cryptographic features.
5. Add deployment isolation after the file-level contracts and policy checks stabilize.
