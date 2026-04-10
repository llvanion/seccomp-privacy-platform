# Codex Context Snapshot

Purpose: read this file first to understand the project with low token cost. Keep it short and current; use `review.md` only for detailed review history.

## Project Shape

This repo is a privacy-computing database-platform prototype:

- `sse/`: searchable symmetric encryption prototype, SSE-backed candidate export, encrypted record-store recovery.
- `bridge/`: Rust bridge that tokenizes join keys and prepares PJC/A-PSI job inputs.
- `a-psi/`: Private Join and Compute / policy-release side.
- `scripts/run_sse_bridge_pipeline.sh`: orchestrates SSE export -> bridge -> A-PSI/PJC -> policy release.
- `schemas/`: versioned JSON schemas for policy, bridge metadata, audit, and encrypted record-store header.

Current demo pipeline expected result:

```text
intersection_size=2
intersection_sum=425
```

## Current Security Boundary

Implemented:

- SSE export policy gate is required by default unless explicit unsafe flag is used.
- SSE export audit writes hashes, row counts, caller, job id, candidate source, record-store hash, and decision.
- `--sse-keyword` makes export query SSE first and filter by returned candidate IDs.
- `create-encrypted-record-store` builds a local encrypted record store with:
  - PBKDF2HMAC-SHA256
  - AES-256-GCM
  - keyed HMAC-SHA256 record-id tags instead of raw record IDs
  - passphrase read from env var, not CLI
- `export-bridge-records` can recover candidate rows from `--record-store-path` with `--record-store-key-env`.
- Bridge supports production mode, bridge audit, metadata schema, and env-based token secret.

Remaining main risk:

- The final bridge-ready CSV/JSONL handoff is still plaintext by design. Next step is service-side streaming or a controlled worker so recovered rows do not become a long-lived local file.
- Fine-grained permission system is intentionally postponed.
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
- Pipeline script: `scripts/run_sse_bridge_pipeline.sh`
- Bridge CLI: `bridge/src/main.rs`
- Pipeline policy validator: `scripts/validate_pipeline_policy.py`
- Bridge metadata validator: `a-psi/moduleA_psi/scripts/validate_bridge_job.py`

## Important Commands

Python checks:

```bash
cd sse
.venv/bin/python -m py_compile frontend/client/commands.py run_client.py toolkit/encrypted_record_store.py
```

Shell check:

```bash
bash -n scripts/run_sse_bridge_pipeline.sh
```

Schema checks:

```bash
python3 -m json.tool schemas/sse_bridge_export_audit.schema.json
python3 -m json.tool schemas/sse_encrypted_record_store.schema.json
```

Bridge checks, if Rust changes:

```bash
cd bridge
cargo fmt --check
cargo test
```

## Working Notes

- Do not rewrite SSE cryptographic scheme implementations unless explicitly requested.
- Prefer adding platform/control-plane boundaries around SSE rather than changing `sse/schemes/*`.
- `review.md` is intentionally detailed and may be updated after meaningful state changes.
- Keep this file concise. Update it whenever architecture, risk status, or primary entry points change.
