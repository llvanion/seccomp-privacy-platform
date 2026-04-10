# seccomp-privacy-platform

This repository is a multi-module privacy computing workspace that integrates:

- `sse/`: searchable symmetric encryption storage, SSE-backed candidate export, and encrypted record-store recovery
- `bridge/`: Rust-based tokenization and PJC input generation layer
- `a-psi/`: Private Join and Compute execution, result governance, and audit release

The current end-to-end flow is:

```text
SSE search/export -> encrypted record recovery -> Rust bridge tokenization -> A-PSI/PJC execution -> policy release
```

This layout keeps the three responsibilities separated:

- `sse` owns encrypted/searchable storage, SSE-backed candidate selection, controlled export, and encrypted record-store recovery.
- `bridge` owns join-key normalization, scoped HMAC token generation, and job metadata.
- `a-psi` owns PJC execution, result thresholding, audit logging, and public report generation.

The current implementation is suitable for a works-competition prototype and local integration demo. It is not yet a production multi-tenant database platform; the remaining work is tracked in `review.md` and summarized in `CODEX_CONTEXT.md`.

## Repository Layout

```text
.
├── a-psi/     # Existing Private Join and Compute workflow and policy layer
├── bridge/    # Rust bridge for SSE-to-PJC input preparation
├── docs/      # Integration and deployment notes
├── scripts/   # Cross-module orchestration scripts
└── sse/       # Searchable symmetric encryption implementation
```

## Quick Start

### 1. Prepare SSE Python environment

```bash
cd sse
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run_client.py --help
cd ..
```

### 2. Verify Rust bridge

```bash
cd bridge
cargo test
cargo run -- prepare-job \
  --server-input ./examples/server_export.csv \
  --server-input-format csv \
  --server-join-key-column email \
  --server-normalizer email \
  --client-input ./examples/client_export.csv \
  --client-input-format csv \
  --client-join-key-column email \
  --client-value-column amount \
  --client-value-mode raw-int \
  --client-normalizer email \
  --out-dir ./out/demo_job \
  --job-id demo_job \
  --token-scope demo-job \
  --token-secret local-dev-secret
cd ..
```

### 3. Run the full integrated demo

```bash
bash scripts/run_sse_bridge_pipeline.sh \
  --server-source "$PWD/sse/examples/bridge_server_records.jsonl" \
  --client-source "$PWD/sse/examples/bridge_client_records.jsonl" \
  --server-join-key-field email \
  --client-join-key-field email \
  --client-value-field amount \
  --server-normalizer email \
  --client-normalizer email \
  --client-value-mode raw-int \
  --server-filter campaign=demo \
  --client-filter campaign=demo \
  --token-scope auto-demo-scope \
  --token-secret local-dev-secret \
  --job-id auto_demo_job \
  --out-base "$PWD/tmp/sse_bridge_pipeline_demo" \
  --caller auto_demo \
  --sse-export-policy-config "$PWD/sse/config/export_policy.example.json" \
  --k 1 \
  --n 5
```

Expected demo result:

```text
intersection_size=2
intersection_sum=425
```

### 4. Optional SSE-backed encrypted record-store export

For the stronger boundary, build an encrypted record store first. The passphrase is read from an environment variable so it is not placed on the command line:

```bash
cd sse
export SSE_RECORD_STORE_PASSPHRASE=<passphrase>
.venv/bin/python run_client.py create-encrypted-record-store \
  --source-path examples/bridge_client_records.jsonl \
  --out-path exports/client_records.enc.jsonl \
  --source-format jsonl \
  --record-id-field email_hex \
  --key-env SSE_RECORD_STORE_PASSPHRASE
cd ..
```

Then the SSE export can query the SSE service first and recover only matching candidate rows from the encrypted record store:

```bash
cd sse
.venv/bin/python run_client.py export-bridge-records \
  --record-store-path exports/client_records.enc.jsonl \
  --record-store-key-env SSE_RECORD_STORE_PASSPHRASE \
  --out-path exports/client_demo.csv \
  --role client \
  --source-format jsonl \
  --out-format csv \
  --join-key-field email \
  --value-field amount \
  --filter campaign=demo \
  --caller auto_demo \
  --policy-config config/export_policy.example.json \
  --audit-log exports/export_audit.jsonl \
  --job-id auto_demo_job \
  --sse-keyword demo \
  --record-id-field email_hex \
  --record-id-format hex \
  --sname bridge_sse_demo
cd ..
```

The encrypted record store uses PBKDF2HMAC-SHA256, AES-256-GCM, and keyed HMAC-SHA256 record-id tags instead of raw record IDs.

The pipeline writes:

```text
tmp/sse_bridge_pipeline_demo/
├── sse_exports/
├── bridge_job/
└── a_psi_run/
```

Key output files:

- `sse_exports/export_audit.jsonl`
- `bridge_job/server.csv`
- `bridge_job/client.csv`
- `bridge_job/job_meta.json`
- `bridge_job/bridge_audit.jsonl`
- `a_psi_run/attribution_result.json`
- `a_psi_run/public_report.json`
- `a_psi_run/audit_log.jsonl`

## Module Entrypoints

### `sse/`

Use the local venv:

```bash
cd sse
.venv/bin/python run_server.py --help
.venv/bin/python run_client.py --help
```

Bridge export command:

```bash
.venv/bin/python run_client.py export-bridge-records --help
```

This command performs local controlled export into a bridge-ready CSV/JSONL format.
Use `--caller`, `--policy-config`, `--audit-log`, and `--job-id` to enforce caller-specific export policy and write an audit record before the Rust bridge sees join-key fields. Policy config is required by default; ad-hoc local exports must pass `--unsafe-allow-no-policy` explicitly.
Use `--sse-keyword` with `--record-id-field` and optional `--record-id-format` / `--sid` / `--sname` when the export should first query SSE and then materialize only the matching candidate rows. This mode rejects `--unsafe-allow-no-policy`.
Use `create-encrypted-record-store` plus `--record-store-path` / `--record-store-key-env` when those matching rows should be recovered from an encrypted local record store instead of a plaintext JSONL/CSV source.

### `bridge/`

Rust CLI:

```bash
cd bridge
cargo run -- --help
cargo run -- generate --help
cargo run -- prepare-job --help
```

Use `--token-secret-env BRIDGE_TOKEN_SECRET` instead of `--token-secret` for non-demo runs.
In bridge production mode, `--token-secret` is rejected and `--token-secret-env` is required.

## Schemas

Versioned JSON schema files live under `schemas/`:

- `schemas/sse_export_policy.schema.json`
- `schemas/sse_bridge_export_audit.schema.json`
- `schemas/sse_encrypted_record_store.schema.json`
- `schemas/bridge_job_meta.schema.json`
- `schemas/bridge_audit.schema.json`

### `a-psi/`

Core scripts:

```bash
cd a-psi
python3 moduleA_psi/scripts/validate_bridge_job.py --help
bash moduleA_psi/scripts/run_pjc.sh
python3 moduleA_psi/scripts/policy_release.py --help
```

For bridge-generated jobs, `a-psi` validates bridge metadata before job execution when using the job server/client entrypoints.

## Documentation

- Full integrated pipeline guide: `docs/SSE_BRIDGE_APSI_PIPELINE.md`
- Bridge CLI guide: `bridge/README.md`
- A-PSI legacy workflow: `a-psi/README.md`
- SSE usage: `sse/README.md`

## Current Status

Implemented and verified:

- `sse` controlled bridge export command with policy and audit
- SSE-backed candidate export with `--sse-keyword`
- encrypted record-store recovery with `create-encrypted-record-store`
- Rust `bridge` CLI with `generate` and `prepare-job`
- bridge production mode and env-based token secret handling
- bridge metadata validation in `a-psi`
- automatic `sse -> bridge -> a-psi -> policy` orchestrator
- demo PJC run producing `intersection_size=2`, `intersection_sum=425`

Still needed after the current prototype:

- Move encrypted-store recovery into a service-side streaming boundary or controlled worker.
- Add fine-grained permission and tenant isolation.
- Add a SQL metadata/control-plane layer for jobs, policies, audits, services, and dataset metadata.
- Move bridge token secrets to a formal key-management path with lifecycle and audit.
- Finalize join-key normalization schemas and versioning policy.
- Add stronger schema validation automation and cross-stage audit correlation.
- Add benchmarks, deployment/ops packaging, threat model, and leakage-model documentation.
- Decide whether to migrate security-sensitive SSE components from Python to Rust.

## Branching Recommendation

This repository restructuring is a large integration change. Do not push it directly to `main`.

Recommended flow:

```bash
git switch -c integrate-sse-bridge
git add -A
git commit -m "Integrate SSE, Rust bridge, and A-PSI pipeline"
git push -u origin integrate-sse-bridge
```

Then open a pull request for review.
