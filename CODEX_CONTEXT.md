# Codex Context Snapshot

Purpose: read this file first to understand the project with low token cost. Keep it short and current; use `review.md` only for detailed review history.

## Project Shape

This repo is a privacy-computing database-platform prototype:

- `sse/`: searchable symmetric encryption prototype, SSE-backed candidate export, encrypted record-store recovery.
- `bridge/`: Rust bridge that tokenizes join keys and prepares PJC/A-PSI job inputs.
- `a-psi/`: Private Join and Compute / policy-release side.
- `scripts/run_sse_bridge_pipeline.sh`: orchestrates SSE export -> bridge -> A-PSI/PJC -> policy release.
- `schemas/`: versioned JSON schemas for policy, bridge metadata, export/service audit, key access, audit seal/archive, and encrypted record-store header.

Current demo pipeline expected result:

```text
intersection_size=2
intersection_sum=425
```

Latest local verification: file-mode pipeline with key-id resolution, HMAC audit seal, tabular contracts, and `--deny-duplicate-query` passed; FIFO handoff pipeline also passed. Both produced `intersection_size=2` and `intersection_sum=425`. Contract smoke checks passed after adding `record_recovery_boundary=service_socket` plus service-audit contracts, Unix-socket record-recovery smoke tests verified both the allow path and a service-side caller-allowlist deny path, a file-mode integrated pipeline using the local key-agent path (`--token-secret-key-name bridge-token --keyring config/keyring.example.json`) completed with `intersection_size=2` and `intersection_sum=425`, a file-mode integrated pipeline using the external HTTP KMS path (`--token-secret-key-name bridge-token --external-kms-config config/external_kms.example.json`) completed with `intersection_size=2` and `intersection_sum=425`, live SSE-backed end-to-end runs completed with `intersection_size=2` and `intersection_sum=425` for both `--record-recovery-service-mode auto` plus `--record-recovery-authz-config config/record_recovery_service_policy.example.json`, the combined local key-agent path, and the combined external KMS path, contract smoke checks now also validate local audit-bundle archiving through `audit_archive_index/v1`, the recovery-service health contract `record_recovery_service_health/v1`, and the shared recovery-service config contract `record_recovery_service_config/v1`, and targeted follow-up checks verified that the unified export policy now resolves caller-scoped `tenant_id` / `dataset_id` / `service_id`, that SSE export audit records those scope fields, and that record-recovery service request handling and service audit use the same scope contract.

## Current Security Boundary

Implemented:

- SSE export policy gate is required by default unless explicit unsafe flag is used.
- SSE export audit writes hashes, row counts, caller, job id, candidate source, record-store hash, and decision.
- SSE export audit includes `correlation_id`, output handoff type, and a write-time output hash so FIFO handoff streams can still be audited.
- `--sse-keyword` makes export query SSE first and filter by returned candidate IDs.
- `create-encrypted-record-store` builds a local encrypted record store with:
  - PBKDF2HMAC-SHA256
  - AES-256-GCM
  - keyed HMAC-SHA256 record-id tags instead of raw record IDs
  - passphrase read from env var, not CLI
- `export-bridge-records` can recover candidate rows from `--record-store-path` with `--record-store-key-env`.
- Encrypted record-store recovery now runs through `toolkit.record_recovery_worker` as a subprocess boundary; candidate IDs and filters go over stdin, the worker writes the bridge handoff directly, and the parent export command only receives non-sensitive metadata.
- `run_client.py serve-record-recovery` provides a long-running Unix-socket recovery service; `export-bridge-records` and `scripts/run_sse_bridge_pipeline.sh` can target it with `--record-recovery-service-config` or `--record-recovery-socket` and optional `--record-recovery-auth-env`, and SSE export audit records `record_recovery_boundary=service_socket`.
- `run_client.py serve-record-recovery` now binds `service_id`, `tenant_id`, and `dataset_id` through `record_recovery_service_config/v1`, reports them in `record_recovery_service_health/v1`, and records them in `sse_record_recovery_service_audit/v1`.
- `run_client.py serve-record-recovery` also supports optional `--authz-config` with either the unified `sse_export_policy/v1` or the older `record_recovery_service_policy/v1`, so the recovery boundary can reuse the same caller/tenant/dataset/service contract as export and pipeline validation while retaining backward compatibility for the narrower service-only policy.
- `scripts/run_sse_bridge_pipeline.sh` defaults to `--record-recovery-service-mode auto` when encrypted record stores are used, so it can auto-start and tear down a local recovery service instead of requiring a separate manual startup step.
- `scripts/run_sse_bridge_pipeline.sh` now also accepts `--record-recovery-authz-config` for that auto-started service path and validates it against `schemas/record_recovery_service_policy.schema.json`.
- Auto recovery-service mode now defaults to a short `/tmp/seccomp_rr_<hash>.sock` Unix socket path when the caller does not provide one, which avoids `AF_UNIX path too long` failures for deep output directories.
- `run_client.py serve-record-recovery` now also supports `--socket-mode`, `--pid-file`, and `--ready-file`, so the local Unix-socket boundary can be supervised more like a real service process.
- `sse/toolkit/record_recovery_client.py` now centralizes the recovery-service socket protocol so the SSE export path, manual health checks, and pipeline orchestration use the same request/response handling.
- The recovery service now also answers `op=health` with `sse_record_recovery_health/v1`, and the integrated pipeline records `record_recovery_service_health.json` before using a manual or auto-started service.
- `scripts/manage_record_recovery_service.py` now provides `start`, `status`, and `stop` lifecycle commands for the recovery service outside the pipeline auto-start path.
- `sse/toolkit/record_recovery_service_config.py`, `schemas/record_recovery_service_config.schema.json`, and `config/record_recovery_service.example.json` now provide a shared config source for manual service management, health probes, `run_client.py serve-record-recovery --config`, direct `export-bridge-records --record-recovery-service-config`, and pipeline-side `--record-recovery-service-config`.
- `scripts/run_sse_bridge_pipeline.sh` now materializes `sse_exports/record_recovery_service_config.json` as the effective recovery-service runtime config and reuses it for service health checks, manager start/stop, and export-side client wiring; `run_live_sse_bridge_demo.sh` now records that artifact and the resolved lifecycle paths in its manifest.
- `scripts/run_live_sse_bridge_demo.sh` wraps local SSE server startup/reuse, fresh demo-service bootstrap, normalized demo-data generation, encrypted record-store creation, the live pipeline run, and manifest writing for reproducible one-command verification.
- `scripts/run_live_sse_bridge_demo.sh` now derives `RUN_ROOT`-dependent paths after argument parsing, so `--run-root`, `--state-base`, and `--out-base` actually propagate through the whole live path; when authz config is enabled and no explicit roots are provided, it defaults to `/tmp/seccomp_live_sse_bridge_demo` so the example authz policy stays aligned.
- `scripts/run_live_sse_bridge_demo.sh` now also bridges the demo token secret into the active keyring env when `--token-secret-key-name` plus `--keyring` is used, so the live wrapper can exercise the full key-agent path instead of only direct token-secret injection.
- `scripts/run_live_sse_bridge_demo.sh` now also supports `--external-kms-config` and, for the demo auto-start path, bridges the demo token secret into the active external-KMS state file's env ref so the live wrapper can exercise the full external KMS path.
- The current bridge module is aligned again with the pipeline contract: `prepare-job` accepts `--audit-log`, writes `bridge_audit.jsonl`, and emits `job_meta.json` with `schema=bridge_job_meta/v1`, so pipeline-side compatibility shims are no longer needed.
- `scripts/run_sse_bridge_pipeline.sh` now honors `BRIDGE_BIN`, so engineering environments can swap `cargo run --` for a prebuilt bridge command without editing the orchestrator.
- The recovery service can enforce `--allowed-caller`, emit `sse_record_recovery_service_audit/v1` records, and `scripts/build_audit_chain.py` can include that audit stream in `audit_chain.json`.
- `scripts/run_sse_bridge_pipeline.sh --sse-export-handoff-mode fifo` streams bridge-ready plaintext through named pipes into the Rust bridge instead of persisting `sse_exports/server.csv` and `client.csv`.
- Bridge supports production mode, bridge audit, metadata schema, and env-based token secret.
- Bridge and policy-release audits include `correlation_id`; policy release also records `pjc_result_sha256`.
- `scripts/resolve_key_access.py` resolves a local key manifest entry to an env-var secret reference, enforces active/purpose checks, and writes `key_access_audit/v1` without printing the secret.
- `scripts/key_agent_service.py`, `scripts/request_key_agent.py`, `scripts/manage_keyring.py`, and `config/keyring.example.json` now provide a local KMS-like path with active-version resolution, Unix-socket key access, rotation, and deactivation lifecycle operations.
- `scripts/external_kms_service.py`, `scripts/request_external_kms.py`, `scripts/manage_external_kms.py`, and `config/external_kms.example.json` now provide an external-KMS-shaped HTTP boundary with remote lifecycle admin operations.
- The orchestrator supports the legacy `--token-secret-key-id` plus `--key-manifest` path, the `--token-secret-key-name` plus `--keyring` local key-agent path, and the `--token-secret-key-name` plus `--external-kms-config` external HTTP KMS path, while still supporting direct env-var injection through `--token-secret-env`.
- `scripts/validate_json_contract.py` validates JSON/JSONL files against the repo's local schema subset; the integrated pipeline validates export policy, SSE export audit, optional record-recovery service audit, bridge `job_meta.json`, bridge audit, PJC audit, key access audit, public report, policy audit, audit chain, and audit seal.
- `scripts/validate_tabular_contract.py` validates non-JSON CSV/JSONL handoff contracts for bridge input and PJC server/client CSV; the integrated pipeline validates file-mode SSE bridge handoffs and generated PJC CSV inputs, and the contract smoke suite includes malformed-input negative fixtures.
- `scripts/write_pjc_audit.py` appends `pjc_audit/v1` records for the PJC stage, including deny records on failure.
- `scripts/build_audit_chain.py` writes a correlated `audit_chain.json` view for SSE export, optional record-recovery service audit, bridge, PJC audit, PJC result, public report, policy release audit, and optional key access audit.
- `scripts/seal_audit_artifact.py` writes `audit_chain.seal.json` with the audit-chain SHA-256 and optional HMAC-SHA256 signature from `--audit-seal-key-env`.
- `scripts/archive_audit_bundle.py` can copy `audit_chain.json` plus `audit_chain.seal.json` into a local archive dir and append an `audit_archive_index/v1` record for indexed retention.
- `policy_release.py --deny-duplicate-query` can reject exact repeated canonical query signatures for the same caller.
- `scripts/check_json_contracts.sh` runs the local schema/contract smoke checks; `.github/workflows/json-contracts.yml` wires it into GitHub Actions.

Remaining main risk:

- The default bridge-ready CSV/JSONL handoff is still plaintext by design. FIFO handoff plus the Unix-socket recovery service reduce local plaintext exposure, but the service is still a local process boundary rather than a separately deployed/authenticated production service.
- The repo now has a shared caller/tenant/dataset/service policy baseline across export, pipeline, and recovery-service checks, but it is still file-config based rather than a durable SQL/control-plane permission system.
- Key management now has both a local key-agent/keyring boundary and a mock external HTTP KMS boundary, but both still depend on env-backed secret refs rather than a real KMS/HSM secret backend.
- SQL/platform metadata layer has not been added; add later for jobs/policies/audits/service registry, not as a replacement for SSE crypto core.

Later competition backlog:

- Threat model and leakage-model writeup.
- Benchmarks and reproducible performance report.
- Multi-tenant isolation, deployment/ops, backup/restore, metrics/tracing.
- Data lifecycle governance, API/SDK/admin UI, compatibility extensions.
- Security audit readiness: dependency scan, secret scan, fuzzing, unsafe deserialization/input-boundary review.

## Key Entry Points

- SSE CLI: `sse/run_client.py`
- SSE export logic: `sse/frontend/client/commands.py`
- SSE waitable search result fix: `sse/frontend/client/services/service.py`
- Encrypted record store: `sse/toolkit/encrypted_record_store.py`
- Record recovery worker: `sse/toolkit/record_recovery_worker.py`
- Record recovery service: `sse/toolkit/record_recovery_service.py`
- Record recovery client: `sse/toolkit/record_recovery_client.py`
- Record recovery service config loader: `sse/toolkit/record_recovery_service_config.py`
- Shared platform policy helper: `sse/toolkit/platform_policy.py`
- Record recovery authz helper: `sse/toolkit/record_recovery_authz.py`
- Record recovery service audit schema: `schemas/sse_record_recovery_service_audit.schema.json`
- Record recovery service health schema: `schemas/record_recovery_service_health.schema.json`
- Record recovery service config schema/example: `schemas/record_recovery_service_config.schema.json`, `config/record_recovery_service.example.json`
- Record recovery service authz schema/example: `schemas/record_recovery_service_policy.schema.json`, `config/record_recovery_service_policy.example.json` (legacy narrow policy); unified path uses `schemas/sse_export_policy.schema.json`, `sse/config/export_policy.example.json`
- Pipeline script: `scripts/run_sse_bridge_pipeline.sh`
- Live demo wrapper: `scripts/run_live_sse_bridge_demo.sh`
- Keyring library: `scripts/keyring_lib.py`
- Key agent service/client: `scripts/key_agent_service.py`, `scripts/request_key_agent.py`
- Key lifecycle manager: `scripts/manage_keyring.py`
- Keyring schema/example: `schemas/keyring.schema.json`, `config/keyring.example.json`
- External KMS service/client/admin: `scripts/external_kms_service.py`, `scripts/request_external_kms.py`, `scripts/manage_external_kms.py`
- External KMS config schema/example: `schemas/external_kms_config.schema.json`, `config/external_kms.example.json`
- Key lifecycle audit schema: `schemas/key_lifecycle_audit.schema.json`
- Bridge CLI: `bridge/src/main.rs`
- Pipeline policy validator: `scripts/validate_pipeline_policy.py`
- JSON contract validator: `scripts/validate_json_contract.py`
- Tabular contract validator: `scripts/validate_tabular_contract.py`
- PJC audit writer: `scripts/write_pjc_audit.py`
- Audit chain builder: `scripts/build_audit_chain.py`
- Key manifest resolver: `scripts/resolve_key_access.py`
- Audit seal writer: `scripts/seal_audit_artifact.py`
- Audit archive writer: `scripts/archive_audit_bundle.py`
- Record recovery service health client: `scripts/request_record_recovery_service.py` (`--config` supported)
- Record recovery service manager: `scripts/manage_record_recovery_service.py`
- JSON contract check script: `scripts/check_json_contracts.sh`
- Bridge metadata validator: `a-psi/moduleA_psi/scripts/validate_bridge_job.py`
- Policy release: `a-psi/moduleA_psi/scripts/policy_release.py`

## Important Commands

Python checks:

```bash
cd sse
.venv/bin/python -m py_compile frontend/client/commands.py run_client.py toolkit/encrypted_record_store.py toolkit/record_recovery_authz.py toolkit/record_recovery_common.py toolkit/record_recovery_client.py toolkit/record_recovery_service_config.py toolkit/record_recovery_worker.py toolkit/record_recovery_service.py
```

Script checks:

```bash
python3 -m py_compile a-psi/moduleA_psi/scripts/policy_release.py scripts/resolve_key_access.py scripts/keyring_lib.py scripts/key_agent_service.py scripts/request_key_agent.py scripts/request_record_recovery_service.py scripts/manage_record_recovery_service.py scripts/manage_keyring.py scripts/external_kms_lib.py scripts/external_kms_service.py scripts/request_external_kms.py scripts/manage_external_kms.py scripts/seal_audit_artifact.py scripts/archive_audit_bundle.py scripts/build_audit_chain.py scripts/write_pjc_audit.py scripts/validate_json_contract.py scripts/validate_tabular_contract.py
```

Shell check:

```bash
bash -n scripts/run_sse_bridge_pipeline.sh
```

Schema checks:

```bash
python3 -m json.tool schemas/sse_bridge_export_audit.schema.json
python3 -m json.tool schemas/record_recovery_service_policy.schema.json
python3 -m json.tool schemas/sse_record_recovery_service_audit.schema.json
python3 -m json.tool schemas/record_recovery_service_health.schema.json
python3 -m json.tool schemas/record_recovery_service_config.schema.json
python3 -m json.tool schemas/sse_encrypted_record_store.schema.json
python3 -m json.tool schemas/public_report.schema.json
python3 -m json.tool schemas/pjc_audit.schema.json
python3 -m json.tool schemas/policy_audit.schema.json
python3 -m json.tool schemas/audit_chain.schema.json
python3 -m json.tool schemas/audit_archive_index.schema.json
python3 -m json.tool schemas/key_manifest.schema.json
python3 -m json.tool schemas/keyring.schema.json
python3 -m json.tool schemas/external_kms_config.schema.json
python3 -m json.tool schemas/key_access_audit.schema.json
python3 -m json.tool schemas/key_lifecycle_audit.schema.json
python3 -m json.tool schemas/audit_seal.schema.json
python3 scripts/validate_json_contract.py --schema schemas/sse_export_policy.schema.json --json sse/config/export_policy.example.json
python3 scripts/validate_json_contract.py --schema schemas/record_recovery_service_policy.schema.json --json config/record_recovery_service_policy.example.json
python3 scripts/validate_json_contract.py --schema schemas/keyring.schema.json --json config/keyring.example.json
python3 scripts/validate_json_contract.py --schema schemas/external_kms_config.schema.json --json config/external_kms.example.json
bash scripts/check_json_contracts.sh
```

Bridge checks, if Rust changes:

```bash
cd bridge
cargo fmt --check
tmp=$(mktemp -d /tmp/bridge_cargo_test.XXXXXX); CARGO_TARGET_DIR="$tmp" cargo test; rc=$?; rm -rf "$tmp"; exit "$rc"
```

## Working Notes

- Do not rewrite SSE cryptographic scheme implementations unless explicitly requested.
- Prefer adding platform/control-plane boundaries around SSE rather than changing `sse/schemes/*`.
- `review.md` is intentionally detailed and may be updated after meaningful state changes.
- Keep `DIRECTORY_STRUCTURE.md` in sync with `review.md` and this file when entrypoints or ownership change.
- Keep this file concise. Update it whenever architecture, risk status, or primary entry points change.
