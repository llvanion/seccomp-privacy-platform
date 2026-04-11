# Codex Context Snapshot

Purpose: read this file first to understand the project with low token cost. Keep it short and current; use `review.md` only for detailed review history.

## Project Shape

This repo is a privacy-computing database-platform prototype:

- `sse/`: searchable symmetric encryption prototype, SSE-backed candidate export, encrypted record-store recovery.
- `bridge/`: Rust bridge that tokenizes join keys and prepares PJC/A-PSI job inputs.
- `a-psi/`: Private Join and Compute / policy-release side.
- `scripts/run_sse_bridge_pipeline.sh`: orchestrates SSE export -> bridge -> A-PSI/PJC -> policy release.
- `schemas/`: versioned JSON schemas for policy, bridge metadata, export/service audit, key access, audit seal, and encrypted record-store header.

Current demo pipeline expected result:

```text
intersection_size=2
intersection_sum=425
```

Latest local verification: file-mode pipeline with key-id resolution, HMAC audit seal, tabular contracts, and `--deny-duplicate-query` passed; FIFO handoff pipeline also passed. Both produced `intersection_size=2` and `intersection_sum=425`. Contract smoke checks passed after adding `record_recovery_boundary=service_socket` plus service-audit contracts, Unix-socket record-recovery smoke tests verified both the allow path and a service-side caller-allowlist deny path, and a live SSE-backed end-to-end run with `--record-recovery-service-mode auto` completed with `intersection_size=2` and `intersection_sum=425`.

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
- `run_client.py serve-record-recovery` provides a long-running Unix-socket recovery service; `export-bridge-records` and `scripts/run_sse_bridge_pipeline.sh` can target it with `--record-recovery-socket` and optional `--record-recovery-auth-env`, and SSE export audit records `record_recovery_boundary=service_socket`.
- `scripts/run_sse_bridge_pipeline.sh` defaults to `--record-recovery-service-mode auto` when encrypted record stores are used, so it can auto-start and tear down a local recovery service instead of requiring a separate manual startup step.
- Auto recovery-service mode now defaults to a short `/tmp/seccomp_rr_<hash>.sock` Unix socket path when the caller does not provide one, which avoids `AF_UNIX path too long` failures for deep output directories.
- `run_client.py serve-record-recovery` now also supports `--socket-mode`, `--pid-file`, and `--ready-file`, so the local Unix-socket boundary can be supervised more like a real service process.
- `scripts/run_live_sse_bridge_demo.sh` wraps local SSE server startup/reuse, fresh demo-service bootstrap, normalized demo-data generation, encrypted record-store creation, the live pipeline run, and manifest writing for reproducible one-command verification.
- The current bridge module is aligned again with the pipeline contract: `prepare-job` accepts `--audit-log`, writes `bridge_audit.jsonl`, and emits `job_meta.json` with `schema=bridge_job_meta/v1`, so pipeline-side compatibility shims are no longer needed.
- `scripts/run_sse_bridge_pipeline.sh` now honors `BRIDGE_BIN`, so engineering environments can swap `cargo run --` for a prebuilt bridge command without editing the orchestrator.
- The recovery service can enforce `--allowed-caller`, emit `sse_record_recovery_service_audit/v1` records, and `scripts/build_audit_chain.py` can include that audit stream in `audit_chain.json`.
- `scripts/run_sse_bridge_pipeline.sh --sse-export-handoff-mode fifo` streams bridge-ready plaintext through named pipes into the Rust bridge instead of persisting `sse_exports/server.csv` and `client.csv`.
- Bridge supports production mode, bridge audit, metadata schema, and env-based token secret.
- Bridge and policy-release audits include `correlation_id`; policy release also records `pjc_result_sha256`.
- `scripts/resolve_key_access.py` resolves a local key manifest entry to an env-var secret reference, enforces active/purpose checks, and writes `key_access_audit/v1` without printing the secret.
- The orchestrator supports `--token-secret-key-id` plus `--key-manifest` as the local key-management boundary, and still supports direct env-var injection through `--token-secret-env`.
- `scripts/validate_json_contract.py` validates JSON/JSONL files against the repo's local schema subset; the integrated pipeline validates export policy, SSE export audit, optional record-recovery service audit, bridge `job_meta.json`, bridge audit, key access audit, public report, policy audit, audit chain, and audit seal.
- `scripts/validate_tabular_contract.py` validates non-JSON CSV/JSONL handoff contracts for bridge input and PJC server/client CSV; the integrated pipeline validates file-mode SSE bridge handoffs and generated PJC CSV inputs, and the contract smoke suite includes malformed-input negative fixtures.
- `scripts/build_audit_chain.py` writes a correlated `audit_chain.json` view for SSE export, optional record-recovery service audit, bridge, PJC result, public report, policy release audit, and optional key access audit.
- `scripts/seal_audit_artifact.py` writes `audit_chain.seal.json` with the audit-chain SHA-256 and optional HMAC-SHA256 signature from `--audit-seal-key-env`.
- `policy_release.py --deny-duplicate-query` can reject exact repeated canonical query signatures for the same caller.
- `scripts/check_json_contracts.sh` runs the local schema/contract smoke checks; `.github/workflows/json-contracts.yml` wires it into GitHub Actions.

Remaining main risk:

- The default bridge-ready CSV/JSONL handoff is still plaintext by design. FIFO handoff plus the Unix-socket recovery service reduce local plaintext exposure, but the service is still a local process boundary rather than a separately deployed/authenticated production service.
- Fine-grained permission system is intentionally postponed.
- Key management is still local manifest/env-var based, not a real key agent or KMS.
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
- Record recovery service audit schema: `schemas/sse_record_recovery_service_audit.schema.json`
- Pipeline script: `scripts/run_sse_bridge_pipeline.sh`
- Live demo wrapper: `scripts/run_live_sse_bridge_demo.sh`
- Bridge CLI: `bridge/src/main.rs`
- Pipeline policy validator: `scripts/validate_pipeline_policy.py`
- JSON contract validator: `scripts/validate_json_contract.py`
- Tabular contract validator: `scripts/validate_tabular_contract.py`
- Audit chain builder: `scripts/build_audit_chain.py`
- Key manifest resolver: `scripts/resolve_key_access.py`
- Audit seal writer: `scripts/seal_audit_artifact.py`
- JSON contract check script: `scripts/check_json_contracts.sh`
- Bridge metadata validator: `a-psi/moduleA_psi/scripts/validate_bridge_job.py`
- Policy release: `a-psi/moduleA_psi/scripts/policy_release.py`

## Important Commands

Python checks:

```bash
cd sse
.venv/bin/python -m py_compile frontend/client/commands.py run_client.py toolkit/encrypted_record_store.py toolkit/record_recovery_common.py toolkit/record_recovery_worker.py toolkit/record_recovery_service.py
```

Script checks:

```bash
python3 -m py_compile a-psi/moduleA_psi/scripts/policy_release.py scripts/resolve_key_access.py scripts/seal_audit_artifact.py scripts/build_audit_chain.py scripts/validate_json_contract.py scripts/validate_tabular_contract.py
```

Shell check:

```bash
bash -n scripts/run_sse_bridge_pipeline.sh
```

Schema checks:

```bash
python3 -m json.tool schemas/sse_bridge_export_audit.schema.json
python3 -m json.tool schemas/sse_record_recovery_service_audit.schema.json
python3 -m json.tool schemas/sse_encrypted_record_store.schema.json
python3 -m json.tool schemas/public_report.schema.json
python3 -m json.tool schemas/policy_audit.schema.json
python3 -m json.tool schemas/audit_chain.schema.json
python3 -m json.tool schemas/key_manifest.schema.json
python3 -m json.tool schemas/key_access_audit.schema.json
python3 -m json.tool schemas/audit_seal.schema.json
python3 scripts/validate_json_contract.py --schema schemas/sse_export_policy.schema.json --json sse/config/export_policy.example.json
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
