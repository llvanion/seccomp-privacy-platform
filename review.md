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
- `scripts/run_sse_bridge_pipeline.sh`: cross-module orchestration with export policy checks, local key-manifest, local key-agent, or external KMS resolution, audit-chain generation, audit sealing, and optional audit-bundle archiving
- `schemas/`: versioned JSON schema contracts for export policy, bridge job metadata, audits, key access, key lifecycle, audit sealing, and audit archive indexing
- shared caller/tenant/dataset/service policy enforcement now aligns SSE export, pipeline-stage validation, and the record-recovery service boundary

Verified demo result:

```text
intersection_size=2
intersection_sum=425
```

Latest verification:

- file-mode integrated pipeline passed with local key-id resolution, production mode, HMAC audit seal, duplicate-query guard enabled, JSON contracts, and tabular contracts
- FIFO handoff integrated pipeline passed without persisting `sse_exports/server.csv` or `sse_exports/client.csv`
- Unix-socket record-recovery export smoke passed from encrypted record store to bridge-ready CSV with `record_recovery_boundary=service_socket`
- Unix-socket record-recovery service audit smoke recorded both allow and service-side caller-deny outcomes
- live SSE-backed integrated pipeline with auto-started record-recovery service passed with `intersection_size=2` and `intersection_sum=425`
- live SSE-backed integrated pipeline with auto-started record-recovery service plus `record_recovery_service_policy/v1` authz passed with `intersection_size=2` and `intersection_sum=425`
- file-mode integrated pipeline also passed using the new local Unix-socket key-agent path with `--token-secret-key-name bridge-token --keyring config/keyring.example.json`, producing `intersection_size=2` and `intersection_sum=425`
- live SSE-backed integrated pipeline also passed using both `record_recovery_service_policy/v1` authz and the new local Unix-socket key-agent path (`--record-recovery-authz-config ... --token-secret-key-name bridge-token --keyring config/keyring.example.json`), producing `intersection_size=2` and `intersection_sum=425`
- file-mode integrated pipeline also passed using the new external HTTP KMS path with `--token-secret-key-name bridge-token --external-kms-config config/external_kms.example.json`, producing `intersection_size=2` and `intersection_sum=425`
- live SSE-backed integrated pipeline also passed using both `record_recovery_service_policy/v1` authz and the new external HTTP KMS path (`--record-recovery-authz-config ... --token-secret-key-name bridge-token --external-kms-config config/external_kms.example.json`), producing `intersection_size=2` and `intersection_sum=425`
- `scripts/run_live_sse_bridge_demo.sh` now reproduces that live SSE-backed path in one command and writes a manifest with the exact `state_base`, `out_base`, `job_id`, `service_name`, and public result
- `scripts/run_live_sse_bridge_demo.sh` now derives `RUN_ROOT`-dependent paths after argument parsing, so explicit `--run-root` / `--state-base` / `--out-base` values propagate correctly, and authz-enabled runs can default to `/tmp`-scoped outputs that match the example recovery-service authz policy
- `scripts/run_live_sse_bridge_demo.sh` now also bridges the demo token secret into the active keyring env when the caller uses `--token-secret-key-name` plus `--keyring`, so the live wrapper can exercise the same key-agent path as the integrated pipeline
- `scripts/run_live_sse_bridge_demo.sh` now also supports `--external-kms-config` and, for the demo auto-start path, bridges the demo token secret into the active external-KMS state file's env ref so the wrapper can exercise the full external KMS path end to end
- `scripts/run_sse_bridge_pipeline.sh` now chooses a short `/tmp/seccomp_rr_<hash>.sock` path for auto-started recovery services when the caller does not provide one, fixing the `AF_UNIX path too long` failure mode surfaced by deep output directories
- `run_client.py serve-record-recovery` now exposes service-lifecycle hooks (`--socket-mode`, `--pid-file`, `--ready-file`) and the auto-started pipeline path writes those lifecycle artifacts under `sse_exports/`
- `sse/toolkit/record_recovery_client.py` now centralizes the recovery-service socket protocol, `scripts/request_record_recovery_service.py` provides a manual health probe, and the integrated pipeline captures/validates `record_recovery_service_health.json` for both auto-started and manual service modes
- `scripts/manage_record_recovery_service.py` now provides explicit `start` / `status` / `stop` lifecycle management for the recovery service outside the integrated pipeline
- `sse/toolkit/record_recovery_service_config.py`, `schemas/record_recovery_service_config.schema.json`, and `config/record_recovery_service.example.json` now provide a shared config source for manual service management, health probes, `run_client.py serve-record-recovery --config`, direct `export-bridge-records --record-recovery-service-config`, and pipeline-side `--record-recovery-service-config`, and a live SSE-backed run using that config path passed with `intersection_size=2` and `intersection_sum=425`
- `scripts/run_sse_bridge_pipeline.sh` now materializes `sse_exports/record_recovery_service_config.json` as the effective runtime config for the recovery service path, reuses it for manager health checks and `export-bridge-records`, and `run_live_sse_bridge_demo.sh` now records that artifact plus the resolved lifecycle paths in its manifest
- `scripts/run_sse_bridge_pipeline.sh` now actually uses `BRIDGE_BIN`, so the integrated flow can target a prebuilt bridge binary instead of assuming `cargo run --`
- both modes produced `intersection_size=2` and `intersection_sum=425`

The modules can cooperate through file/FIFO/Unix-socket interfaces, and the highest-risk local export/bridge boundary now has policy enforcement, SSE-backed candidate selection, encrypted record-store recovery, audit correlation, and schema validation. This is still not a production-grade multi-tenant database platform because the new recovery service is still a local process boundary rather than a separately deployed service with durable authn/authz and lifecycle controls.

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
  - correlation ID
  - job ID
  - role
  - source/output paths, output handoff type, and SHA-256 hashes
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

Encrypted record-store recovery now runs through two controlled boundaries:

- `toolkit.record_recovery_worker` as a subprocess boundary. Candidate IDs and filters are passed over stdin, the worker enforces row-count limits, writes the bridge handoff directly, and returns only non-sensitive metadata such as input/output row counts and output SHA-256 to the parent export command. SSE export audit records `record_recovery_boundary=worker_subprocess` for this path.
- `toolkit.record_recovery_service` as a long-running Unix-socket boundary. `run_client.py serve-record-recovery` starts the service, optional auth is enforced through an env-backed token, allowed callers plus output/store roots can be constrained, and the runtime contract now binds `service_id`, `tenant_id`, and `dataset_id`. `--authz-config` can now point to the unified `sse_export_policy/v1` or the older `record_recovery_service_policy/v1`, so the service can reuse the same caller/tenant/dataset/service contract as SSE export and pipeline-stage validation while still supporting the narrower compatibility policy. The service appends `sse_record_recovery_service_audit/v1` records, answers `sse_record_recovery_health/v1` requests with its bound scope, and `export-bridge-records` or `scripts/run_sse_bridge_pipeline.sh` can target it with `--record-recovery-service-config` or `--record-recovery-socket` plus optional `--record-recovery-auth-env`. A shared `record_recovery_service_config/v1` file aligns manual service management, health probes, direct CLI startup, direct export calls, and pipeline-side service resolution, and the pipeline writes its resolved runtime config back out as `sse_exports/record_recovery_service_config.json`. SSE export audit records `record_recovery_boundary=service_socket` for this path and now also carries `tenant_id` / `dataset_id` / `service_id`.
- `scripts/run_sse_bridge_pipeline.sh` now supports `--record-recovery-service-mode auto|manual|subprocess`; `auto` can start and stop a local recovery service for encrypted record-store runs, wire caller allowlisting plus service audit logging, optionally pass `--record-recovery-authz-config`, and keep the service-side boundary inside the integrated demo path.

The integrated orchestrator can use `--sse-export-handoff-mode fifo` to stream bridge-ready plaintext through named pipes into the Rust bridge instead of persisting `sse_exports/server.csv` and `client.csv`. SSE audit records `output_file_type=fifo` plus a write-time `output_sha256`; bridge audit records FIFO input type and leaves input SHA-256 null rather than reopening the pipe.

The remaining issue is not candidate selection anymore; it is operationalizing the new recovery service into a separately deployed/authenticated boundary and further reducing bridge-ready plaintext handling outside explicitly audited handoff paths.

The bridge/pipeline alignment issue encountered during live verification has also been corrected: the current bridge build now matches the expected cross-module contract for `prepare-job`, including `--audit-log`, native `bridge_audit.jsonl` output, and `job_meta.json` carrying `schema=bridge_job_meta/v1`.

The live SSE bootstrap gap has also narrowed: `scripts/run_live_sse_bridge_demo.sh` now captures the previously manual steps for local SSE server reuse/startup, demo-service creation, normalized `email_hex` materialization, encrypted record-store creation, full pipeline execution, and final result verification.

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
  - includes input/output hashes for regular files, FIFO input type for streaming handoff, row counts, token metadata, timestamp, correlation ID, production-mode flag, and token-secret source
  - appends deny records for failed `generate` / `prepare-job` attempts after audit-log resolution
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

The current `sse export-bridge-records` command can now use SSE search results as the candidate set and can recover records from a local encrypted record store. The integrated pipeline can also stream the bridge-ready handoff through FIFOs so those files are not persisted in `sse_exports`.

Improved:

- encrypted record-store recovery now runs in a controlled subprocess worker rather than in the parent export command
- encrypted record-store recovery also has a long-running Unix-socket service option, and the orchestrator can route record-store exports through that socket
- the Unix-socket service can now restrict callers, emit its own audit stream, and feed that stream into `audit_chain.json`

Still needed:

- separate the Unix-socket service into a durable service/user boundary with lifecycle management
- strengthen authn/authz around recovery requests beyond env-backed local tokens
- avoid writing bridge-ready plaintext files except as explicitly audited handoff artifacts; FIFO mode covers the local integrated script, not a production service boundary

This is now the highest-priority technical gap for the SSE boundary.

### 3.2 Fine-Grained Permission System

The new policy config is a minimal local policy gate, not a complete permission system.

Current lightweight exception worth keeping:

- `record_recovery_service_policy/v1` can preserve service-side caller, field, filter, path, candidate-count, and output-row constraints for the Unix-socket recovery boundary. This is intentionally scoped and should not be mistaken for the future platform-wide authz model.

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
- `scripts/resolve_key_access.py` resolves local key-manifest entries to env-var references without printing secrets
- key manifest entries enforce enabled/active/purpose checks for the bridge token key
- key access audit records `key_access_audit/v1` with key ID, key version, manifest hash, caller, job/correlation ID, and env-var secret source
- the integrated pipeline can use `--token-secret-key-id` plus `--key-manifest` and validates the key manifest and key access audit schema
- `config/keyring.example.json`, `scripts/key_agent_service.py`, and `scripts/request_key_agent.py` now provide a local Unix-socket key-agent path for `Ktoken`; the integrated pipeline can use `--token-secret-key-name` plus `--keyring`, auto-start the service, inject the resolved secret into a bridge-only env var, and write `key_access_audit/v1` with `secret_source.kind=key_agent`
- `scripts/manage_keyring.py` plus `schemas/keyring.schema.json` and `schemas/key_lifecycle_audit.schema.json` now provide local lifecycle operations for rotation and deactivation, with audit records for `rotate` and `set_status`
- `config/external_kms.example.json`, `scripts/external_kms_service.py`, `scripts/request_external_kms.py`, and `scripts/manage_external_kms.py` now provide an external-KMS-shaped HTTP boundary for `Ktoken`; the integrated pipeline can use `--token-secret-key-name` plus `--external-kms-config`, auto-start the HTTP service when `auto_start` is configured, inject the resolved secret into the same bridge-only env var path, and write `key_access_audit/v1` with `secret_source.kind=external_kms`
- `scripts/check_json_contracts.sh` now exercises both external KMS resolve and external KMS lifecycle changes (`rotate`, `set-status`) against the HTTP API, validating `external_kms_config.schema.json`, `key_access_audit.schema.json`, and `key_lifecycle_audit.schema.json`

Still needed:

- separation of `Kstore`, `Ktoken`, `Kauth`, and callback secrets
- verification that PJC processes never access `Kstore` or raw join keys
- replace the current mock external HTTP KMS plus env-backed secret refs with a real KMS/HSM-backed deployment boundary, stronger authn/authz, and non-env secret storage

### 3.5 End-to-End Audit

Improved:

- SSE export audit now records caller, job ID, correlation ID, filters as hashes, input/output hashes, handoff type, and row counts.
- Bridge audit now records bridge input/output hashes for regular files, FIFO input type for streaming handoff, row counts, token metadata, production mode, correlation ID, and secret source.
- Bridge now also writes deny audit records for failed `generate` / `prepare-job` attempts, and the orchestrator now writes `pjc_audit/v1` allow/deny records for the PJC stage.
- A-PSI policy audit records release decision, parsed metrics, correlation ID, and PJC result hash.
- `scripts/build_audit_chain.py` now writes a single `audit_chain.json` view across SSE export, bridge, bridge metadata, PJC audit, PJC result, public report, policy audit, and optional key access audit.
- `scripts/seal_audit_artifact.py` writes `audit_chain.seal.json` with audit-chain SHA-256 and optional HMAC-SHA256 signature from `--audit-seal-key-env`.
- `scripts/archive_audit_bundle.py` can now copy `audit_chain.json` plus `audit_chain.seal.json` into a separate local archive tree and append an `audit_archive_index/v1` record for indexed retention outside the run directory.

Still needed:

- explicit audit-log access policy
- append-only storage guarantees or externally anchored signatures for stronger tamper evidence beyond the new local archive index

Sensitive values that must remain out of logs:

- raw email
- raw phone
- raw device ID
- raw internal user ID
- token secret
- plaintext join-key dumps

### 3.6 Stronger Result Governance

Current policy release supports thresholding, rate limiting, audit, and optional HMAC authentication.

It now also supports `--deny-duplicate-query`, which rejects an exact repeated canonical query signature for the same caller when the prior decision is already present in the policy audit log.

Still needed:

- overlapping-query detection beyond exact duplicate signatures
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
- `schemas/pjc_audit.schema.json`
- `schemas/public_report.schema.json`
- `schemas/policy_audit.schema.json`
- `schemas/audit_chain.schema.json`
- `schemas/key_manifest.schema.json`
- `schemas/key_access_audit.schema.json`
- `schemas/audit_seal.schema.json`

Implemented automation:

- `scripts/validate_json_contract.py` validates JSON and JSONL files against the schema subset used in this repo.
- `scripts/check_json_contracts.sh` runs schema syntax checks, contract validation against sample records, tabular negative fixtures, and audit-chain validation.
- `scripts/validate_tabular_contract.py` validates non-JSON CSV/JSONL handoff contracts for bridge input and PJC input files.
- `.github/workflows/json-contracts.yml` runs the contract check script in GitHub Actions.
- `scripts/run_sse_bridge_pipeline.sh` now validates:
  - export policy config before permission checks
  - file-mode SSE bridge handoff CSVs before bridge preparation
  - SSE export audit JSONL after export
  - bridge `job_meta.json` after bridge preparation
  - bridge audit JSONL after bridge preparation
  - PJC audit JSONL after the PJC stage, including deny-path validation before pipeline exit
  - generated PJC server/client CSV inputs after bridge preparation
  - key access audit JSONL when key-id resolution is used
  - policy public report JSON after release
  - policy audit JSONL after release
  - correlated audit chain JSON after chain generation
  - audit-chain seal JSON after seal generation

Still needed:

- semantic schema checks for future optional bridge handoff formats

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

### Priority 1: Harden Service-Side Record Recovery

Next step is operationalizing the new local recovery service into a durable service-side worker:

```text
SSE query -> candidate IDs -> controlled service-side recovery stream -> bridge input
```

Keep the current policy config, FIFO-style streaming semantics, and audit behavior around the new path.

Implemented baseline since the previous review pass:

- recovery-service runtime config now binds `service_id`, `tenant_id`, and `dataset_id`
- recovery-service health/audit records now surface those scope fields
- SSE export audit also records `tenant_id` / `dataset_id` / `service_id`
- the shared `sse_export_policy/v1` now carries caller-scoped `tenant_id`, `allowed_dataset_ids`, `allowed_service_ids`, and `can_use_record_recovery_service`
- `scripts/validate_pipeline_policy.py`, the SSE export path, and recovery-service request authz now resolve the same caller scope instead of each maintaining a separate ad-hoc stage check

### Priority 2: Cross-Stage Audit Correlation

Implemented baseline: `correlation_id` now follows `job_id` across SSE export audit, bridge audit, PJC result, and policy release audit; policy release also records the PJC result hash. `scripts/build_audit_chain.py` now writes a single `audit_chain.json` view across the pipeline outputs, including key-access audit when present, and the integrated pipeline validates it with `schemas/audit_chain.schema.json`.

Implemented integrity baseline: `scripts/seal_audit_artifact.py` writes `<out-base>/audit_chain.seal.json` with the audit-chain SHA-256 and an optional HMAC-SHA256 signature from `--audit-seal-key-env`; the integrated pipeline validates it with `schemas/audit_seal.schema.json`.

Implemented retention baseline: `scripts/archive_audit_bundle.py` can archive `audit_chain.json` plus `audit_chain.seal.json` into a separate local archive dir, append `audit_archive_index/v1` records to `audit_chain_index.jsonl`, and the integrated pipeline can validate that index when `--audit-archive-dir` is supplied.

Still needed:

- append-only storage guarantees or externally anchored signatures for stronger tamper evidence
- move the current file-config + Unix-socket supervision model to a separately deployed service/process boundary with stronger non-local lifecycle controls

### Priority 3: Schema Validation Automation

Implemented baseline:

- export policy config
- bridge `job_meta.json`
- bridge audit records
- SSE export audit records
- public report schema and validation
- policy audit schema and validation
- audit chain schema and validation
- tabular bridge/PJC input contract validation
- negative contract fixtures for malformed bridge/PJC tabular inputs
- local/CI contract check via `scripts/check_json_contracts.sh` and `.github/workflows/json-contracts.yml`

### Priority 4: Key Management Service Boundary

Implemented baseline: the repo now supports the legacy `--token-secret-key-id` plus `--key-manifest` path, a local Unix-socket key-agent path using `--token-secret-key-name` plus `--keyring`, and an external-KMS-shaped HTTP path using `--token-secret-key-name` plus `--external-kms-config`. The local path auto-starts `scripts/key_agent_service.py`; the external path auto-starts `scripts/external_kms_service.py` when `auto_start` is configured. Both resolve the active key version off the bridge CLI path, write `key_access_audit/v1`, and keep the bridge secret off the command line. `scripts/manage_keyring.py` and `scripts/manage_external_kms.py` provide lifecycle operations backed by `schemas/keyring.schema.json`, `schemas/external_kms_config.schema.json`, and `schemas/key_lifecycle_audit.schema.json`.

Still needed: replace the current mock external KMS and env-backed secret refs with a real KMS/HSM-backed deployment that has stronger authn/authz, non-env secret storage, and durable policy controls.

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

### Gap To A Complete Database Platform

Estimated completion against a "qualified database platform" target: roughly 60% complete, with about 40% still missing. Against the narrower "competition/demo privacy-computing platform" target, the repo is much closer; against a full platform target, the remaining work is concentrated in missing control-plane and productionization modules rather than in the core export/bridge/PJC happy path.

The main missing modules are:

1. SQL metadata and control-plane database
   - persistent catalog for jobs, datasets, policies, audits, service registry, and tenant-scoped metadata
   - replace the current file-config plus shell-orchestrator state model with durable platform state
2. Platform identity, authn/authz, and tenant isolation
   - real user/service identities, session or token validation, role model, tenant resource boundaries, and admin/operator separation
   - extend the current caller/tenant/dataset/service policy baseline into a full platform permission system
3. Independently deployed recovery-service and sensitive service boundary
   - move beyond the current local Unix-socket process model toward separately supervised services with non-local lifecycle control
   - add stronger service authn, deployment isolation, and remote operations support
4. Production key-management and secret backend
   - replace the mock external KMS and env-backed secret refs with a real KMS/HSM or dedicated secret store
   - add durable key policy, rotation, access governance, and operational recovery procedures
5. Deployment, operations, and observability package
   - deployment topology, health checks, backup/restore, metrics, tracing, alerting, and failure-recovery playbooks
   - define service SLOs and platform runbooks
6. Data lifecycle and platform API surface
   - dataset versioning, deletion, retention, re-encryption workflow, compatibility/version policy, and administrator-facing APIs/SDK/UI
   - expose stable management and job-status interfaces instead of relying primarily on local CLI/script entrypoints

Practical count: about 6 major platform modules are still missing or only partially implemented. The current repo already has the core privacy-computing data path, policy baseline, audit baseline, and key-boundary prototype, but it does not yet have the control plane and operational envelope expected from a complete database platform.

## 6. Recommended Direction

Do not start by rewriting the whole SSE module.

Recommended path:

1. Keep the current SSE module as the searchable storage prototype.
2. Move encrypted-store recovery into a service-side streaming boundary.
3. Keep the Rust bridge as the stable sensitive-data tokenization boundary.
4. Extend audit correlation and schema validation before adding new cryptographic features.
5. Add deployment isolation after the file-level contracts and policy checks stabilize.
