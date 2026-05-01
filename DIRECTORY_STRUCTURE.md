# Project Directory Structure

This file is the quick map of the repository layout. Keep it synchronized with [review.md](/home/llvanion/Desktop/seccomp-privacy-platform/review.md) and [CODEX_CONTEXT.md](/home/llvanion/Desktop/seccomp-privacy-platform/CODEX_CONTEXT.md) whenever the architecture or primary entrypoints change.

## Top Level

```text
.
├── a-psi/
├── bridge/
├── config/
├── docs/
├── schemas/
├── scripts/
├── sse/
├── tmp/
├── CODEX_CONTEXT.md
├── DIRECTORY_STRUCTURE.md
├── README.md
└── review.md
```

## Directory Roles

- `a-psi/`: PJC execution, bridge job validation, governed result release, and policy audit.
- `bridge/`: Rust CLI for join-key normalization, token generation, bridge job preparation, and bridge-stage audit.
- `config/`: local example control-plane config such as the bridge token key manifest, keyring, external KMS client config, and recovery-service runtime config.
- `docs/`: higher-level integration and deployment notes.
- `migrations/metadata/`: pure SQL schema migrations for the SQLite control-plane sidecar.
- `schemas/`: JSON schema contracts for policy, audit, job metadata, key access, key lifecycle, audit sealing/archive indexing, record-recovery service authz, and query/workflow wrapper envelopes.
- `scripts/`: cross-module orchestration, contract validation, key resolution, audit chain building, sealing, and local archive indexing.
- `sse/`: searchable encryption prototype, controlled bridge export, encrypted record store, and record recovery boundary.
- `tmp/`: local demo and smoke-test output area.

## Key Files And Entrypoints

- [README.md](/home/llvanion/Desktop/seccomp-privacy-platform/README.md): workspace overview and integrated quick start.
- [review.md](/home/llvanion/Desktop/seccomp-privacy-platform/review.md): detailed implementation/review history and remaining gaps.
- [CODEX_CONTEXT.md](/home/llvanion/Desktop/seccomp-privacy-platform/CODEX_CONTEXT.md): compact working snapshot for coding sessions.
- [scripts/run_sse_bridge_pipeline.sh](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/run_sse_bridge_pipeline.sh): end-to-end orchestration, including effective recovery-service runtime config materialization.
- [scripts/run_live_sse_bridge_demo.sh](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/run_live_sse_bridge_demo.sh): one-command live SSE bootstrap plus full pipeline verification.
- [scripts/run_record_recovery_service.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/run_record_recovery_service.py): standalone record-recovery service launcher decoupled from the SSE CLI.
- [migrations/metadata/001_init.sql](/home/llvanion/Desktop/seccomp-privacy-platform/migrations/metadata/001_init.sql): initial SQLite control-plane sidecar schema for jobs, artifacts, audits, policies, and scoped registry tables.
- [scripts/init_metadata_db.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/init_metadata_db.py): initializes the SQLite metadata sidecar and applies SQL migrations.
- [scripts/import_run_metadata.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/import_run_metadata.py): imports one existing pipeline run directory into the metadata sidecar.
- [scripts/query_metadata.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/query_metadata.py): read-only metadata query CLI by `job_id`, scope, imported registry entities, or policy tables.
- [scripts/serve_metadata_api.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/serve_metadata_api.py): thin local read-only HTTP API over the imported metadata sidecar.
- [schemas/metadata_api_health.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/metadata_api_health.schema.json): health envelope contract for the metadata sidecar HTTP API.
- [schemas/metadata_api_response.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/metadata_api_response.schema.json): success envelope contract for the metadata sidecar HTTP API.
- [schemas/metadata_api_error.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/metadata_api_error.schema.json): error envelope contract for the metadata sidecar HTTP API.
- [scripts/submit_query_workflow.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/submit_query_workflow.py): structured query/workflow submission adapter that maps a limited request JSON onto the existing integrated pipeline CLI.
- [scripts/serve_query_workflow_api.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/serve_query_workflow_api.py): local HTTP wrapper over the query/workflow submit adapter, with auth and dry-run-first behavior.
- [scripts/platform_api_client.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/platform_api_client.py): thin local SDK/CLI shell that calls the metadata, query-workflow, audit/public-report, and platform-health HTTP adapters.
- [scripts/serve_audit_query_api.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/serve_audit_query_api.py): local read-only HTTP adapter for completed-run public reports, audit chains, and derived observability/catalog views.
- [scripts/serve_platform_health_api.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/serve_platform_health_api.py): local read-only HTTP adapter for `platform_health/v1` checks over recovery services, key agent, external KMS, completed runs, and metadata DBs.
- [scripts/check_schema_backcompat.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/check_schema_backcompat.py): backward-compatibility guard for frozen schema files.
- [scripts/benchmark_query_workflow.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/benchmark_query_workflow.py): dry-run latency benchmark for query-workflow CLI/HTTP/client entrypoints.
- [schemas/query_workflow_request.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_request.schema.json): structural request contract for the query/workflow adapter.
- [schemas/query_workflow_submission.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_submission.schema.json): structural manifest contract emitted by the query/workflow adapter.
- [schemas/query_workflow_api_health.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_api_health.schema.json): health envelope contract for the local query/workflow HTTP wrapper.
- [schemas/query_workflow_api_response.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_api_response.schema.json): success envelope contract for the local query/workflow HTTP wrapper.
- [schemas/query_workflow_api_error.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_api_error.schema.json): error envelope contract for the local query/workflow HTTP wrapper.
- [schemas/audit_query_api_health.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/audit_query_api_health.schema.json): health envelope contract for the audit/public-report query adapter.
- [schemas/audit_query_api_response.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/audit_query_api_response.schema.json): success envelope contract for the audit/public-report query adapter.
- [schemas/platform_health_api_health.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/platform_health_api_health.schema.json): health envelope contract for the platform health query adapter.
- [schemas/platform_health_api_response.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/platform_health_api_response.schema.json): success envelope contract for the platform health query adapter.
- [schemas/schema_backcompat_check.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/schema_backcompat_check.schema.json): report contract for the schema backward-compatibility guard.
- [schemas/query_workflow_benchmark.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_benchmark.schema.json): benchmark-report contract for query-workflow dry-run entrypoints.
- [schemas/audit_query_api_error.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/audit_query_api_error.schema.json): error envelope contract for the audit/public-report query adapter.
- [schemas/platform_health_api_error.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/platform_health_api_error.schema.json): error envelope contract for the platform health query adapter.
- [scripts/check_platform_health.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/check_platform_health.py): sidecar health probe for recovery services, key agent, external KMS, completed pipeline runs, and metadata DBs.
- [scripts/check_record_recovery_boundary.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/check_record_recovery_boundary.py): verifies that legacy `sse/toolkit` recovery files remain compatibility shims for `services.record_recovery`.
- [scripts/check_ci_smoke.sh](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/check_ci_smoke.sh): unified local/CI smoke entrypoint for Python compile checks, shell syntax checks, hygiene scan, and contract smoke.
- [scripts/check_bridge_rust.sh](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/check_bridge_rust.sh): bridge Rust preflight using `cargo fmt --check` and `cargo test` with a temporary target dir.
- [scripts/benchmark_smoke.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/benchmark_smoke.py): lightweight benchmark wrapper for existing smoke-check entrypoints.
- [scripts/export_observability_events.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/export_observability_events.py): read-only sidecar exporter from `audit_chain.json` to `pipeline_observability/v1`.
- [scripts/export_catalog_lineage.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/export_catalog_lineage.py): read-only sidecar exporter from `audit_chain.json` to `catalog_lineage/v1`.
- [scripts/verify_audit_bundle.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/verify_audit_bundle.py): sidecar verifier/restorer for `audit_chain.json` plus `audit_chain.seal.json` bundles and archive-index entries.
- [scripts/scan_repo_hygiene.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/scan_repo_hygiene.py): lightweight high-confidence secret and tracked generated-artifact scanner.
- [scripts/check_dependency_hygiene.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/check_dependency_hygiene.py): offline dependency-manifest reproducibility check for first-party requirements and Cargo manifests.
- [scripts/write_pjc_audit.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/write_pjc_audit.py): PJC stage audit writer used by the integrated orchestrator.
- [docs/ECOMMERCE_PRIVACY_PLATFORM_SCENARIO.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_PRIVACY_PLATFORM_SCENARIO.md): detailed business scenario for the e-commerce privacy database platform, including roles, data boundaries, and SSE/PJC cooperation.
- [docs/OPS_RUNBOOK.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPS_RUNBOOK.md): sidecar operations runbook for health checks, artifact checks, metadata DB checks, and troubleshooting.
- [docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md): owner-held task boundary for the privacy core, interface governance, leakage model, and release semantics.
- [docs/TASK_ENGINEER_A_CONTROL_PLANE_IDENTITY_ACCESS.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_ENGINEER_A_CONTROL_PLANE_IDENTITY_ACCESS.md): delegated task boundary for control-plane metadata, identity, authorization, and key-management integration.
- [docs/TASK_ENGINEER_B_QUERY_CATALOG_WORKFLOW_OBSERVABILITY.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_ENGINEER_B_QUERY_CATALOG_WORKFLOW_OBSERVABILITY.md): delegated task boundary for query entrypoints, catalog, workflow, observability, UI/SDK shell, benchmark, and security checks.
- [docs/QUERY_INTERFACE_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/QUERY_INTERFACE_PLAN.md): first-stage query/workflow wrapper request format and boundary plan.
- [docs/BENCHMARK_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/BENCHMARK_PLAN.md): first-stage benchmark plan for smoke checks, schema guards, and query-workflow dry-run entrypoints.
- [sse/run_client.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/run_client.py): SSE CLI entrypoint.
- [sse/frontend/client/commands.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/frontend/client/commands.py): SSE export policy/audit logic and record recovery client path.
- [sse/toolkit/encrypted_record_store.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/encrypted_record_store.py): compatibility shim for the service-owned encrypted record-store implementation.
- [sse/toolkit/record_recovery_worker.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/record_recovery_worker.py): compatibility shim for the service-owned subprocess recovery worker.
- [sse/toolkit/record_recovery_service.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/record_recovery_service.py): compatibility shim for the service-owned Unix-socket recovery service implementation.
- [sse/toolkit/record_recovery_http_service.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/record_recovery_http_service.py): compatibility shim for the service-owned HTTP recovery service adapter.
- [sse/toolkit/record_recovery_client.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/record_recovery_client.py): compatibility shim for the service-owned recovery client.
- [sse/toolkit/record_recovery_service_config.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/record_recovery_service_config.py): compatibility shim that now re-exports service-owned config helpers.
- [services/record_recovery/README.md](/home/llvanion/Desktop/seccomp-privacy-platform/services/record_recovery/README.md): deploy-unit notes for the standalone recovery service packaging layer.
- [services/record_recovery/launcher.py](/home/llvanion/Desktop/seccomp-privacy-platform/services/record_recovery/launcher.py): standalone launcher that resolves config, picks transport, and dispatches into the current service implementation.
- [services/record_recovery/config.py](/home/llvanion/Desktop/seccomp-privacy-platform/services/record_recovery/config.py): service-owned runtime config loader and merge helper.
- [services/record_recovery/runtime.py](/home/llvanion/Desktop/seccomp-privacy-platform/services/record_recovery/runtime.py): service-owned runtime state and lifecycle helper layer shared by Unix-socket and HTTP service adapters.
- [services/record_recovery/service.py](/home/llvanion/Desktop/seccomp-privacy-platform/services/record_recovery/service.py): service-owned Unix-socket adapter, request handling, health response, and recovery-service audit writer.
- [services/record_recovery/http_service.py](/home/llvanion/Desktop/seccomp-privacy-platform/services/record_recovery/http_service.py): service-owned HTTP adapter for `/healthz`, `/health`, and `/recover`.
- [services/record_recovery/authz.py](/home/llvanion/Desktop/seccomp-privacy-platform/services/record_recovery/authz.py): service-owned recovery authz evaluator, including unified export-policy reuse and legacy service-policy compatibility.
- [services/record_recovery/common.py](/home/llvanion/Desktop/seccomp-privacy-platform/services/record_recovery/common.py): service-owned recovery result/health/error payload helpers and bridge-row selection/output helpers.
- [services/record_recovery/client.py](/home/llvanion/Desktop/seccomp-privacy-platform/services/record_recovery/client.py): service-owned Unix-socket/HTTP recovery client used by export flows and service health checks.
- [services/record_recovery/worker.py](/home/llvanion/Desktop/seccomp-privacy-platform/services/record_recovery/worker.py): service-owned subprocess recovery worker for local encrypted record-store materialization.
- [services/record_recovery/encrypted_record_store.py](/home/llvanion/Desktop/seccomp-privacy-platform/services/record_recovery/encrypted_record_store.py): service-owned encrypted record-store creation and candidate row recovery implementation.
- [sse/toolkit/platform_policy.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/platform_policy.py): shared caller/tenant/dataset/service policy helper reused by export, pipeline validation, and recovery-service authz.
- [sse/toolkit/record_recovery_authz.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/record_recovery_authz.py): compatibility shim for the service-owned recovery authz evaluator.
- [sse/toolkit/record_recovery_common.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/record_recovery_common.py): compatibility shim for service-owned recovery common helpers.
- [config/record_recovery_service_policy.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/config/record_recovery_service_policy.example.json): example authz policy for the recovery service.
- [config/record_recovery_service.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/config/record_recovery_service.example.json): example shared runtime config for the recovery service, including `service_id`, `tenant_id`, and `dataset_id`.
- [config/record_recovery_http_service.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/config/record_recovery_http_service.example.json): example HTTP transport config for the standalone recovery service, including lifecycle paths and auth token env wiring.
- [config/keyring.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/config/keyring.example.json): example keyring with active-version lifecycle state for the local key agent.
- [config/external_kms.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/config/external_kms.example.json): example external HTTP KMS client config with optional auto-start metadata.
- [schemas/sse_record_recovery_service_audit.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/sse_record_recovery_service_audit.schema.json): service-side recovery audit contract.
- [schemas/record_recovery_service_health.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/record_recovery_service_health.schema.json): service health/status contract for manual and pipeline-side checks.
- [schemas/record_recovery_service_config.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/record_recovery_service_config.schema.json): shared runtime config contract for the recovery service, including bound service scope.
- [schemas/record_recovery_service_policy.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/record_recovery_service_policy.schema.json): recovery-service authz policy contract.
- [schemas/record_recovery_boundary_check.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/record_recovery_boundary_check.schema.json): contract for the recovery implementation-boundary check output.
- [schemas/keyring.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/keyring.schema.json): keyring lifecycle contract.
- [schemas/external_kms_config.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/external_kms_config.schema.json): external HTTP KMS client-config contract.
- [schemas/key_lifecycle_audit.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/key_lifecycle_audit.schema.json): key lifecycle audit contract.
- [schemas/pjc_audit.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/pjc_audit.schema.json): PJC stage audit contract.
- [schemas/audit_archive_index.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/audit_archive_index.schema.json): local audit bundle archive-index contract.
- [bridge/src/main.rs](/home/llvanion/Desktop/seccomp-privacy-platform/bridge/src/main.rs): bridge CLI implementation.
- [a-psi/moduleA_psi/scripts/policy_release.py](/home/llvanion/Desktop/seccomp-privacy-platform/a-psi/moduleA_psi/scripts/policy_release.py): result-governance and public release logic.

## Module Notes

### `sse/`

- `run_client.py`: CLI for config, search, export, encrypted-store creation, and record-recovery service startup.
- `frontend/client/services/`: client-side SSE service interaction.
- `toolkit/`: crypto/data utilities plus compatibility shims for recovery modules.
- `services/record_recovery/`: standalone service package that owns recovery-service config/runtime assembly, transport adapters, request handling, service-side audit payloads, recovery-service authz, common payload/row helpers, the recovery-service client, the subprocess worker, and encrypted record-store handling. Recovery business logic should be added here; `sse/toolkit` recovery files are compatibility shims.
- `config/export_policy.example.json`: example SSE export policy.
- `examples/`: local demo datasets used by the integrated pipeline.

### `bridge/`

- `src/main.rs`: `generate` and `prepare-job` commands.
- `examples/`: sample bridge input CSVs.
- `README.md`: bridge-specific CLI notes.

### `a-psi/`

- `moduleA_psi/scripts/run_pjc.sh`: PJC runner wrapper.
- `moduleA_psi/scripts/validate_bridge_job.py`: bridge metadata validation before PJC.
- `moduleA_psi/scripts/policy_release.py`: threshold/rate-limit/duplicate-query policy release.

### `scripts/`

- `run_sse_bridge_pipeline.sh`: integrated demo pipeline, including auto-started recovery service wiring, effective recovery runtime-config materialization, and optional recovery authz config validation.
- `run_live_sse_bridge_demo.sh`: starts or reuses the local SSE server, bootstraps fresh demo state, creates encrypted record stores, and runs the live SSE-backed pipeline.
- `validate_pipeline_policy.py`: coarse caller permission checks for bridge/PJC/release stages.
- `keyring_lib.py`: shared keyring lifecycle and key-access audit helpers.
- `key_agent_service.py`: local Unix-socket key agent for bridge token resolution.
- `request_key_agent.py`: local key-agent client used by the orchestrator.
- `manage_keyring.py`: key rotation/deactivation lifecycle CLI.
- `external_kms_service.py`: mock external HTTP KMS service for token resolution and lifecycle updates.
- `request_external_kms.py`: external HTTP KMS client used by the orchestrator.
- `request_record_recovery_service.py`: recovery-service health client used by the orchestrator and manual operations, including config-driven checks.
- `manage_record_recovery_service.py`: lifecycle CLI for starting, probing, and stopping the recovery service outside pipeline auto-start.
- `manage_external_kms.py`: lifecycle admin CLI that talks to the external HTTP KMS API.
- `metadata_db.py`: shared SQLite connection/migration/hash helpers for the control-plane sidecar.
- `init_metadata_db.py`: initialize/apply migrations for the metadata sidecar.
- `import_run_metadata.py`: import existing run artifacts into the metadata sidecar.
- `query_metadata.py`: query imported jobs, artifacts, audits, and release summaries from the metadata sidecar.
- `serve_metadata_api.py`: expose the metadata sidecar over local HTTP for UI/SDK prototype work, with envelopes frozen in `schemas/metadata_api_*.schema.json`.
- `submit_query_workflow.py`: validate a limited request JSON and submit or dry-run the integrated pipeline through an adapter layer.
- `serve_query_workflow_api.py`: expose the query/workflow adapter over local HTTP for UI/SDK prototype work.
- `platform_api_client.py`: thin local SDK/CLI shell over the metadata, query-workflow, audit/public-report, and platform-health HTTP adapters.
- `serve_audit_query_api.py`: expose completed-run public-report, audit-chain, observability, and catalog-lineage views over local HTTP.
- `serve_platform_health_api.py`: expose `platform_health/v1` over local HTTP without changing the underlying CLI-side checks.
- `check_schema_backcompat.py`: compare frozen schema files against the committed compatibility baseline.
- `benchmark_query_workflow.py`: benchmark query-workflow dry-run entrypoints across CLI, HTTP API, and platform client surfaces.
- `query_workflow_request.schema.json`: structural request contract for the query/workflow adapter.
- `query_workflow_submission.schema.json`: structural submission-manifest contract for the query/workflow adapter.
- `query_workflow_api_health.schema.json`, `query_workflow_api_response.schema.json`, `query_workflow_api_error.schema.json`: local HTTP wrapper envelope contracts.
- `audit_query_api_health.schema.json`, `audit_query_api_response.schema.json`, `audit_query_api_error.schema.json`: local HTTP wrapper envelope contracts for the audit/public-report query adapter.
- `schema_backcompat_check.schema.json`: report contract for the frozen-schema compatibility guard.
- `query_workflow_benchmark.schema.json`: report contract for the query-workflow dry-run benchmark.
- `check_platform_health.py`: read-only sidecar health check aggregator for service endpoints, completed run artifacts, and sidecar DBs.
- `serve_platform_health_api.py`: read-only HTTP surface over the same component checks and report schema.
- `check_record_recovery_boundary.py`: AST-based guard that keeps legacy recovery toolkit files compatibility-only.
- `check_ci_smoke.sh`: local and CI preflight wrapper for compile, shell syntax, hygiene, and contract checks.
- `check_bridge_rust.sh`: bridge-specific Rust format/test wrapper that avoids repository target pollution.
- `benchmark_smoke.py`: emits `smoke_benchmark/v1` timing reports for hygiene, contract, or CI-smoke checks.
- `export_observability_events.py`: derives stage-level observability events from an existing audit chain.
- `export_catalog_lineage.py`: derives catalog metadata and lineage edges from an existing audit chain.
- `validate_json_contract.py`: local JSON/JSONL schema validation.
- `validate_tabular_contract.py`: CSV/JSONL handoff validation for non-JSON contracts.
- `build_audit_chain.py`: correlated cross-stage audit view.
- `archive_audit_bundle.py`: local audit-chain/archive indexing helper for retention outside the run directory.
- `verify_audit_bundle.py`: verifies audit-chain seals and can restore a verified archived bundle into a target directory.
- `scan_repo_hygiene.py`: scans tracked files for high-confidence secrets and tracked generated artifacts.
- `check_dependency_hygiene.py`: checks first-party dependency manifests for basic pinning/reproducibility hygiene.
- `resolve_key_access.py`: local key-manifest resolution and key-access audit.
- `seal_audit_artifact.py`: audit-chain hash/HMAC seal generation.
- `check_json_contracts.sh`: contract smoke suite used locally and in CI, now including metadata sidecar `init -> import -> query` smoke.

## Maintenance Rule

- Update this file when a new top-level directory appears, when ownership of a directory changes, or when a new cross-module entrypoint becomes part of the normal development path.
