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
- `schemas/`: JSON schema contracts for policy, audit, job metadata, key access, key lifecycle, audit sealing/archive indexing, and record-recovery service authz.
- `scripts/`: cross-module orchestration, contract validation, key resolution, audit chain building, sealing, and local archive indexing.
- `sse/`: searchable encryption prototype, controlled bridge export, encrypted record store, and record recovery boundary.
- `tmp/`: local demo and smoke-test output area.

## Key Files And Entrypoints

- [README.md](/home/llvanion/Desktop/seccomp-privacy-platform/README.md): workspace overview and integrated quick start.
- [review.md](/home/llvanion/Desktop/seccomp-privacy-platform/review.md): detailed implementation/review history and remaining gaps.
- [CODEX_CONTEXT.md](/home/llvanion/Desktop/seccomp-privacy-platform/CODEX_CONTEXT.md): compact working snapshot for coding sessions.
- [scripts/run_sse_bridge_pipeline.sh](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/run_sse_bridge_pipeline.sh): end-to-end orchestration, including effective recovery-service runtime config materialization.
- [scripts/run_live_sse_bridge_demo.sh](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/run_live_sse_bridge_demo.sh): one-command live SSE bootstrap plus full pipeline verification.
- [scripts/write_pjc_audit.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/write_pjc_audit.py): PJC stage audit writer used by the integrated orchestrator.
- [sse/run_client.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/run_client.py): SSE CLI entrypoint.
- [sse/frontend/client/commands.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/frontend/client/commands.py): SSE export policy/audit logic and record recovery client path.
- [sse/toolkit/encrypted_record_store.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/encrypted_record_store.py): encrypted record-store creation and candidate row recovery.
- [sse/toolkit/record_recovery_worker.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/record_recovery_worker.py): subprocess recovery boundary.
- [sse/toolkit/record_recovery_service.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/record_recovery_service.py): long-running Unix-socket recovery service boundary.
- [sse/toolkit/record_recovery_client.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/record_recovery_client.py): shared recovery-service client used by export flows and service health checks.
- [sse/toolkit/record_recovery_service_config.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/record_recovery_service_config.py): shared recovery-service config loader/merge helper used by the CLI, health probe, manager, and pipeline.
- [sse/toolkit/platform_policy.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/platform_policy.py): shared caller/tenant/dataset/service policy helper reused by export, pipeline validation, and recovery-service authz.
- [sse/toolkit/record_recovery_authz.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/record_recovery_authz.py): recovery-service authz checks, including unified export-policy reuse and legacy service-policy compatibility.
- [config/record_recovery_service_policy.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/config/record_recovery_service_policy.example.json): example authz policy for the recovery service.
- [config/record_recovery_service.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/config/record_recovery_service.example.json): example shared runtime config for the recovery service, including `service_id`, `tenant_id`, and `dataset_id`.
- [config/keyring.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/config/keyring.example.json): example keyring with active-version lifecycle state for the local key agent.
- [config/external_kms.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/config/external_kms.example.json): example external HTTP KMS client config with optional auto-start metadata.
- [schemas/sse_record_recovery_service_audit.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/sse_record_recovery_service_audit.schema.json): service-side recovery audit contract.
- [schemas/record_recovery_service_health.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/record_recovery_service_health.schema.json): service health/status contract for manual and pipeline-side checks.
- [schemas/record_recovery_service_config.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/record_recovery_service_config.schema.json): shared runtime config contract for the recovery service, including bound service scope.
- [schemas/record_recovery_service_policy.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/record_recovery_service_policy.schema.json): recovery-service authz policy contract.
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
- `toolkit/`: crypto/data utilities plus the encrypted record-store, recovery boundary, and lightweight recovery-service authz code.
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
- `validate_json_contract.py`: local JSON/JSONL schema validation.
- `validate_tabular_contract.py`: CSV/JSONL handoff validation for non-JSON contracts.
- `build_audit_chain.py`: correlated cross-stage audit view.
- `archive_audit_bundle.py`: local audit-chain/archive indexing helper for retention outside the run directory.
- `resolve_key_access.py`: local key-manifest resolution and key-access audit.
- `seal_audit_artifact.py`: audit-chain hash/HMAC seal generation.
- `check_json_contracts.sh`: contract smoke suite used locally and in CI.

## Maintenance Rule

- Update this file when a new top-level directory appears, when ownership of a directory changes, or when a new cross-module entrypoint becomes part of the normal development path.
