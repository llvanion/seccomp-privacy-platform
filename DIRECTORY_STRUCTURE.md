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
- `config/`: local example control-plane config such as the bridge token key manifest.
- `docs/`: higher-level integration and deployment notes.
- `schemas/`: JSON schema contracts for policy, audit, job metadata, key access, and audit sealing.
- `scripts/`: cross-module orchestration, contract validation, key resolution, audit chain building, and sealing.
- `sse/`: searchable encryption prototype, controlled bridge export, encrypted record store, and record recovery boundary.
- `tmp/`: local demo and smoke-test output area.

## Key Files And Entrypoints

- [README.md](/home/llvanion/Desktop/seccomp-privacy-platform/README.md): workspace overview and integrated quick start.
- [review.md](/home/llvanion/Desktop/seccomp-privacy-platform/review.md): detailed implementation/review history and remaining gaps.
- [CODEX_CONTEXT.md](/home/llvanion/Desktop/seccomp-privacy-platform/CODEX_CONTEXT.md): compact working snapshot for coding sessions.
- [scripts/run_sse_bridge_pipeline.sh](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/run_sse_bridge_pipeline.sh): end-to-end orchestration.
- [scripts/run_live_sse_bridge_demo.sh](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/run_live_sse_bridge_demo.sh): one-command live SSE bootstrap plus full pipeline verification.
- [sse/run_client.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/run_client.py): SSE CLI entrypoint.
- [sse/frontend/client/commands.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/frontend/client/commands.py): SSE export policy/audit logic and record recovery client path.
- [sse/toolkit/encrypted_record_store.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/encrypted_record_store.py): encrypted record-store creation and candidate row recovery.
- [sse/toolkit/record_recovery_worker.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/record_recovery_worker.py): subprocess recovery boundary.
- [sse/toolkit/record_recovery_service.py](/home/llvanion/Desktop/seccomp-privacy-platform/sse/toolkit/record_recovery_service.py): long-running Unix-socket recovery service boundary.
- [schemas/sse_record_recovery_service_audit.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/sse_record_recovery_service_audit.schema.json): service-side recovery audit contract.
- [bridge/src/main.rs](/home/llvanion/Desktop/seccomp-privacy-platform/bridge/src/main.rs): bridge CLI implementation.
- [a-psi/moduleA_psi/scripts/policy_release.py](/home/llvanion/Desktop/seccomp-privacy-platform/a-psi/moduleA_psi/scripts/policy_release.py): result-governance and public release logic.

## Module Notes

### `sse/`

- `run_client.py`: CLI for config, search, export, encrypted-store creation, and record-recovery service startup.
- `frontend/client/services/`: client-side SSE service interaction.
- `toolkit/`: crypto/data utilities plus the encrypted record-store and recovery boundary code.
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

- `run_sse_bridge_pipeline.sh`: integrated demo pipeline.
- `run_live_sse_bridge_demo.sh`: starts or reuses the local SSE server, bootstraps fresh demo state, creates encrypted record stores, and runs the live SSE-backed pipeline.
- `validate_pipeline_policy.py`: coarse caller permission checks for bridge/PJC/release stages.
- `validate_json_contract.py`: local JSON/JSONL schema validation.
- `validate_tabular_contract.py`: CSV/JSONL handoff validation for non-JSON contracts.
- `build_audit_chain.py`: correlated cross-stage audit view.
- `resolve_key_access.py`: local key-manifest resolution and key-access audit.
- `seal_audit_artifact.py`: audit-chain hash/HMAC seal generation.
- `check_json_contracts.sh`: contract smoke suite used locally and in CI.

## Maintenance Rule

- Update this file when a new top-level directory appears, when ownership of a directory changes, or when a new cross-module entrypoint becomes part of the normal development path.
