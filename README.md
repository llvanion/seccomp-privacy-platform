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
- `bridge` owns join-key normalization, scoped HMAC token generation, job metadata, and bridge-stage audit.
- `a-psi` owns PJC execution, result thresholding, duplicate-query denial, audit logging, and public report generation.

The current implementation is suitable for a works-competition prototype and local integration demo. It is not yet a production multi-tenant database platform; the remaining work is tracked in `review.md` and summarized in `CODEX_CONTEXT.md`.

The current control-plane baseline now includes caller-scoped tenant/dataset/service authorization in `sse/config/export_policy.example.json`, and the recovery-service runtime contract now binds `service_id`, `tenant_id`, and `dataset_id` so the SSE export path, the long-running recovery service, and the integrated pipeline all resolve the same scope.

Latest verified outcomes:

- file-mode integrated demo: `intersection_size=2`, `intersection_sum=425`
- FIFO handoff integrated demo: `intersection_size=2`, `intersection_sum=425`
- live SSE-backed demo with encrypted record stores and auto recovery service: `intersection_size=2`, `intersection_sum=425`

Directory map:

- `DIRECTORY_STRUCTURE.md`

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

### 3. Run the local file-based integrated demo

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

This is the simplest end-to-end path: local source files feed the SSE export boundary, then `bridge`, `a-psi`, and policy release.

### 4. Run the live SSE-backed demo end-to-end

The repo now includes a wrapper that starts or reuses the local SSE server, bootstraps a fresh SSE service, prepares normalized demo inputs plus encrypted record stores, runs the integrated pipeline, verifies `intersection_size=2` / `intersection_sum=425`, and writes a run manifest:

```bash
bash scripts/run_live_sse_bridge_demo.sh
```

Outputs are written under `tmp/live_sse_bridge_demo/`. The most useful artifact is the run manifest, which records the exact `state_base`, `out_base`, `job_id`, `service_name`, and final result for that invocation:

- `tmp/live_sse_bridge_demo/run-*/live_demo_manifest.json`
- `tmp/live_sse_bridge_demo/run-*/a_psi_run/public_report.json`
- `tmp/live_sse_bridge_demo/run-*/audit_chain.json`

`live_demo_manifest.json` now also records runtime options, normalized demo inputs, encrypted record-store paths, recovery-service lifecycle artifacts, and final release status.

Useful flags:

- `--bootstrap-only`: prepare SSE server/service state and encrypted record stores without running the pipeline
- `--keep-server`: leave the SSE server running when this wrapper started it
- `--token-secret-key-name <name>` plus `--keyring <path>`: run the live demo through the local key-agent/KMS path instead of passing `--token-secret`
- `--token-secret-key-name <name>` plus `--external-kms-config <path>`: run the live demo through the external HTTP KMS path instead of passing `--token-secret`
- `--record-recovery-service-mode auto|manual|subprocess`: override the recovery boundary used by the integrated run
- `--record-recovery-authz-config <path>`: optional authz policy for the auto-started recovery service
- `--sse-export-handoff-mode file|fifo`: choose bridge handoff persistence vs FIFO streaming

When `--record-recovery-authz-config` is supplied and no explicit `--run-root` / `--state-base` / `--out-base` is given, the live demo now defaults its run root to `/tmp/seccomp_live_sse_bridge_demo` so the example authz policy's `/tmp` prefix constraints line up with the generated output paths.

### 5. Optional SSE-backed encrypted record-store export

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

For a longer-lived local boundary, start the recovery service and give it an audit log plus an allowlist for trusted callers:

```bash
cd sse
export SSE_RECORD_RECOVERY_TOKEN=<token>
.venv/bin/python run_client.py serve-record-recovery \
  --service-id bridge-demo-recovery \
  --tenant-id demo_tenant \
  --dataset-id bridge_demo_dataset \
  --socket-path /tmp/sse_record_recovery.sock \
  --socket-mode 600 \
  --auth-token-env SSE_RECORD_RECOVERY_TOKEN \
  --authz-config "$PWD/config/export_policy.example.json" \
  --allowed-caller auto_demo \
  --allowed-output-root "$PWD/../tmp" \
  --allowed-record-store-root /tmp \
  --audit-log "$PWD/../tmp/record_recovery_service_audit.jsonl" \
  --pid-file "$PWD/../tmp/record_recovery_service.pid" \
  --ready-file "$PWD/../tmp/record_recovery_service.ready"
cd ..
```

The default aligned policy is now `sse/config/export_policy.example.json`, validated by `schemas/sse_export_policy.schema.json`. It carries the export/bridge/PJC/release booleans plus caller-scoped `tenant_id`, `allowed_dataset_ids`, `allowed_service_ids`, and `can_use_record_recovery_service`, so the recovery-service boundary reuses the same caller/tenant/dataset/service contract as the rest of the pipeline. The older `config/record_recovery_service_policy.example.json` remains as a narrower service-only compatibility example. For aligned manual operations, `config/record_recovery_service.example.json` and `schemas/record_recovery_service_config.schema.json` now act as the shared runtime contract for `run_client.py serve-record-recovery --config`, `scripts/request_record_recovery_service.py --config`, `scripts/manage_record_recovery_service.py --config`, `run_client.py export-bridge-records --record-recovery-service-config`, and pipeline-side `--record-recovery-service-config`.

To verify that the pre-started service is the one the pipeline expects:

```bash
python3 scripts/request_record_recovery_service.py \
  --config config/record_recovery_service.example.json
```

Or manage the whole service lifecycle outside the pipeline:

```bash
python3 scripts/manage_record_recovery_service.py start \
  --config config/record_recovery_service.example.json
python3 scripts/manage_record_recovery_service.py status \
  --config config/record_recovery_service.example.json
python3 scripts/manage_record_recovery_service.py stop \
  --config config/record_recovery_service.example.json
```

Then add either `--record-recovery-service-config config/record_recovery_service.example.json` or the lower-level `--record-recovery-socket /tmp/sse_record_recovery.sock` plus `--record-recovery-auth-env SSE_RECORD_RECOVERY_TOKEN` to `scripts/run_sse_bridge_pipeline.sh` when the pipeline should use and validate that service boundary. `run_client.py export-bridge-records` accepts the same aligned config through `--record-recovery-service-config`.
If encrypted record stores are used, the orchestrator now defaults to `--record-recovery-service-mode auto`, which auto-starts a local recovery service, generates an auth token env var if needed, uses a short `/tmp/seccomp_rr_<hash>.sock` socket path by default to avoid `AF_UNIX` path-length failures, writes an effective `sse_exports/record_recovery_service_config.json`, captures `sse_exports/record_recovery_service_health.json` through the shared recovery-service client, and shuts the service down after the run. That runtime config now also records the resolved `service_id`, `tenant_id`, and `dataset_id`, so manual and auto service modes stay aligned with the export/pipeline policy. By default the pid/ready lifecycle files still land under `sse_exports/`, but when the shared config provides explicit lifecycle paths the pipeline now honors them and records the effective result in the runtime config artifact. `--record-recovery-authz-config` can now point to either the legacy `config/record_recovery_service_policy.example.json` or the unified `sse/config/export_policy.example.json`. Use `--record-recovery-service-mode manual` to point at a pre-started service, or `--record-recovery-service-mode subprocess` to force the older worker-subprocess path.

The pipeline writes:

```text
tmp/sse_bridge_pipeline_demo/
├── sse_exports/
├── bridge_job/
├── audit_chain.json
├── audit_chain.seal.json
└── a_psi_run/
```

Key output files:

- `sse_exports/export_audit.jsonl`
- `sse_exports/record_recovery_service_audit.jsonl`, when the recovery service path is used
- `sse_exports/record_recovery_service_config.json`, the effective runtime config reused by manager/health/export paths
- `sse_exports/record_recovery_service.log`, when the orchestrator auto-starts the recovery service
- `sse_exports/record_recovery_service_health.json`, when the recovery service path is used
- `sse_exports/record_recovery_service.pid`, when the orchestrator auto-starts the recovery service
- `sse_exports/record_recovery_service.ready`, when the orchestrator auto-starts the recovery service
- `bridge_job/server.csv`
- `bridge_job/client.csv`
- `bridge_job/job_meta.json`
- `bridge_job/bridge_audit.jsonl`
- `a_psi_run/pjc_audit.jsonl`
- `key_access_audit.jsonl`, when `--token-secret-key-id` or `--token-secret-key-name` is used
- `a_psi_run/attribution_result.json`
- `a_psi_run/public_report.json`
- `a_psi_run/audit_log.jsonl`
- `audit_chain.json`
- `audit_chain.seal.json`
- optional archived copies plus `audit_chain_index.jsonl` when `--audit-archive-dir` is used

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
.venv/bin/python run_client.py serve-record-recovery --help
```

This command performs local controlled export into a bridge-ready CSV/JSONL format.
Use `--caller`, `--policy-config`, `--audit-log`, and `--job-id` to enforce caller-specific export policy and write an audit record before the Rust bridge sees join-key fields. Policy config is required by default; ad-hoc local exports must pass `--unsafe-allow-no-policy` explicitly.
Use `--sse-keyword` with `--record-id-field` and optional `--record-id-format` / `--sid` / `--sname` when the export should first query SSE and then materialize only the matching candidate rows. This mode rejects `--unsafe-allow-no-policy`.
Use `create-encrypted-record-store` plus `--record-store-path` / `--record-store-key-env` when those matching rows should be recovered from an encrypted local record store instead of a plaintext JSONL/CSV source. The default recovery path runs through the `toolkit.record_recovery_worker` subprocess boundary and records `record_recovery_boundary=worker_subprocess` in SSE export audit.
For a longer-lived boundary, start `run_client.py serve-record-recovery` and pass either `--record-recovery-service-config` or `--record-recovery-socket` plus optional `--record-recovery-auth-env` to `export-bridge-records` or `scripts/run_sse_bridge_pipeline.sh`. The service can enforce `--allowed-caller`, optional `--authz-config`, and its own `--audit-log`. SSE export audit records `record_recovery_boundary=service_socket`, and the service audit can be validated separately or folded into `audit_chain.json`. When encrypted record stores are used, the orchestrator defaults to `--record-recovery-service-mode auto`; `manual` and `subprocess` remain available for explicit control. `--record-recovery-authz-config` is wired into the auto-started service path.
For the integrated script, pass `--sse-export-handoff-mode fifo` to stream bridge-ready plaintext through named pipes into the Rust bridge instead of persisting `sse_exports/server.csv` and `sse_exports/client.csv`. SSE audit records the FIFO output type and write-time output hash; bridge audit records FIFO input type without reopening the pipe.

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
`scripts/run_sse_bridge_pipeline.sh` also honors `BRIDGE_BIN`, so local engineering and deployment wrappers can point the orchestrator at a prebuilt bridge binary instead of `cargo run --`.

For example:

```bash
BRIDGE_BIN=/path/to/bridge bash scripts/run_sse_bridge_pipeline.sh ...
```

The integrated pipeline can also resolve the bridge token secret through a local key manifest:

```bash
export BRIDGE_TOKEN_SECRET=<secret>
bash scripts/run_sse_bridge_pipeline.sh ... \
  --token-secret-key-id bridge-token-demo-v1 \
  --key-manifest "$PWD/config/key_manifest.example.json" \
  --production-mode
```

`scripts/resolve_key_access.py` enforces the key entry's enabled/active/purpose checks, returns only the env-var reference and key version, and appends `key_access_audit/v1` without logging the secret.

The stronger local KMS-like path uses a keyring plus an auto-started Unix-socket key agent:

```bash
export BRIDGE_TOKEN_SECRET=<secret>
bash scripts/run_sse_bridge_pipeline.sh ... \
  --token-secret-key-name bridge-token \
  --keyring "$PWD/config/keyring.example.json" \
  --production-mode
```

In that mode, `scripts/run_sse_bridge_pipeline.sh` auto-starts `scripts/key_agent_service.py`, resolves the active key version from `config/keyring.example.json`, injects the secret into a bridge-only env var, writes `key_access_audit.jsonl`, and passes the resolved `token_key_version` into bridge metadata. The older `--token-secret-key-id` plus `--key-manifest` path remains for compatibility.

There is now also an external-KMS-shaped path using an HTTP boundary:

```bash
export BRIDGE_TOKEN_SECRET=<secret>
bash scripts/run_sse_bridge_pipeline.sh ... \
  --token-secret-key-name bridge-token \
  --external-kms-config "$PWD/config/external_kms.example.json" \
  --production-mode
```

In that mode, `scripts/run_sse_bridge_pipeline.sh` reads `config/external_kms.example.json`, auto-starts `scripts/external_kms_service.py` when `auto_start` is configured, resolves the active key version through `scripts/request_external_kms.py`, injects the secret into the same bridge-only env var flow, writes `key_access_audit.jsonl` with `secret_source.kind=external_kms`, and passes the resolved `token_key_version` into bridge metadata. `scripts/manage_external_kms.py` drives lifecycle changes over the HTTP API, while `scripts/check_json_contracts.sh` now exercises both local keyring lifecycle and external KMS lifecycle smoke paths.

For lifecycle operations, use:

```bash
python3 scripts/manage_keyring.py describe --keyring config/keyring.example.json
python3 scripts/manage_keyring.py rotate \
  --keyring config/keyring.example.json \
  --key-name bridge-token \
  --purpose bridge_token \
  --new-version demo-v2 \
  --secret-env BRIDGE_TOKEN_SECRET_NEXT \
  --caller auto_demo \
  --activate \
  --audit-log tmp/key_lifecycle_audit.jsonl
python3 scripts/manage_keyring.py set-status \
  --keyring config/keyring.example.json \
  --key-name bridge-token \
  --version demo-v1 \
  --status retired \
  --caller auto_demo \
  --audit-log tmp/key_lifecycle_audit.jsonl
```

## Schemas

Versioned JSON schema files live under `schemas/`:

- `schemas/sse_export_policy.schema.json`
- `schemas/sse_bridge_export_audit.schema.json`
- `schemas/sse_record_recovery_service_audit.schema.json`
- `schemas/record_recovery_service_health.schema.json`
- `schemas/record_recovery_service_policy.schema.json`
- `schemas/sse_encrypted_record_store.schema.json`
- `schemas/bridge_job_meta.schema.json`
- `schemas/bridge_audit.schema.json`
- `schemas/pjc_audit.schema.json`
- `schemas/public_report.schema.json`
- `schemas/policy_audit.schema.json`
- `schemas/audit_chain.schema.json`
- `schemas/audit_archive_index.schema.json`
- `schemas/key_manifest.schema.json`
- `schemas/keyring.schema.json`
- `schemas/external_kms_config.schema.json`
- `schemas/key_access_audit.schema.json`
- `schemas/key_lifecycle_audit.schema.json`
- `schemas/audit_seal.schema.json`

Use `scripts/validate_json_contract.py` for local JSON/JSONL contract checks. The integrated pipeline runs it for export policy config, optional auto-service record-recovery authz config, optional keyring config, optional external KMS config, SSE export audit, optional record-recovery service audit when its path is supplied, optional record-recovery service health output when the service path is used, bridge `job_meta.json`, bridge audit, PJC audit, key access audit, public report, policy audit, audit chain output, audit seal output, and optional audit archive index output.

Use `scripts/validate_tabular_contract.py` for CSV/JSONL handoff contracts that are not JSON schema files. The integrated pipeline uses it for file-mode SSE bridge handoff CSVs and generated PJC server/client CSVs. The contract smoke suite includes negative fixtures for malformed bridge/PJC tabular inputs.

Run `bash scripts/check_json_contracts.sh` for the local contract smoke suite. The same command is wired into `.github/workflows/json-contracts.yml`.

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
- optional Unix-socket record recovery service for encrypted-store materialization
- caller-scoped tenant/dataset/service authorization in `sse_export_policy/v1`, reused by export, pipeline, and recovery-service paths
- optional legacy `record_recovery_service_policy/v1` compatibility config for narrower service-only checks
- recovery-service lifecycle hooks with socket mode plus pid/ready files
- Rust `bridge` CLI with `generate` and `prepare-job`
- bridge production mode and env-based token secret handling
- orchestrator override via `BRIDGE_BIN` for prebuilt bridge deployments
- local key manifest resolution and key access audit for bridge token secrets
- local keyring, Unix-socket key agent, and lifecycle manager for bridge token resolution, rotation, and deactivation
- external HTTP KMS mock boundary for bridge token resolution plus remote lifecycle admin operations
- bridge metadata validation in `a-psi`
- policy release exact duplicate-query denial with `--deny-duplicate-query`
- automatic `sse -> bridge -> a-psi -> policy` orchestrator
- cross-stage `audit_chain.json` plus `audit_chain.seal.json`, with optional local archive/index output via `--audit-archive-dir`
- JSON and tabular contract smoke validation
- demo PJC run producing `intersection_size=2`, `intersection_sum=425`

Still needed after the current prototype:

- Continue hardening the local Unix-socket recovery service toward a separately deployed boundary with stronger authn, supervision, and non-local lifecycle control.
- Extend the current caller/tenant/dataset/service policy baseline into a fuller SQL/control-plane metadata layer.
- Add a SQL metadata/control-plane layer for jobs, policies, audits, services, and dataset metadata.
- Replace the current mock external KMS and env-backed secret refs with a real KMS/HSM or dedicated secret store.
- Finalize join-key normalization schemas and versioning policy.
- Add semantic schema checks for future optional bridge handoff formats.
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
