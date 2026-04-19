# SSE Bridge A-PSI Pipeline

This workspace now supports a file-based end-to-end flow:

1. `sse` exports a minimal local candidate set
2. `bridge` normalizes join keys and generates scoped join tokens
3. `a-psi` runs PJC on the generated `server.csv` and `client.csv`
4. `policy_release.py` publishes a governed report

## Modules

- [sse](/home/llvanion/Desktop/seccomp-privacy-platform/sse)
- [bridge](/home/llvanion/Desktop/seccomp-privacy-platform/bridge)
- [a-psi](/home/llvanion/Desktop/seccomp-privacy-platform/a-psi)

## Automatic pipeline

Use the orchestrator:

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

For the fully bootstrapped live SSE-backed path, use the wrapper script instead:

```bash
bash scripts/run_live_sse_bridge_demo.sh
```

That wrapper starts or reuses the local SSE server, bootstraps a fresh SSE service with normalized demo keyword IDs, creates encrypted record stores for both sides, runs `scripts/run_sse_bridge_pipeline.sh`, verifies `intersection_size=2` and `intersection_sum=425`, and writes `live_demo_manifest.json` under `tmp/live_sse_bridge_demo/run-*/`.

## Outputs

The orchestrator writes three stages under `--out-base`:

- `sse_exports/`
- `bridge_job/`
- `a_psi_run/`

Important files:

- `sse_exports/export_audit.jsonl`
- `sse_exports/record_recovery_service_health.json`, when the recovery service path is used
- `sse_exports/record_recovery_service.pid`, when the orchestrator auto-starts the recovery service
- `sse_exports/record_recovery_service.ready`, when the orchestrator auto-starts the recovery service
- `bridge_job/server.csv`
- `bridge_job/client.csv`
- `bridge_job/job_meta.json`
- `bridge_job/bridge_audit.jsonl`
- `a_psi_run/pjc_audit.jsonl`
- `key_access_audit.jsonl`, when `--token-secret-key-id` is used
- `audit_chain.json`
- `audit_chain.seal.json`
- `a_psi_run/attribution_result.json`
- `a_psi_run/public_report.json`
- `a_psi_run/audit_log.jsonl`
- `live_demo_manifest.json`, when the wrapper script is used

## Manual step-by-step

### 1. Export from sse

```bash
cd sse
.venv/bin/python run_client.py export-bridge-records \
  --source-path examples/bridge_server_records.jsonl \
  --out-path exports/server_demo.csv \
  --role server \
  --source-format jsonl \
  --out-format csv \
  --join-key-field email \
  --filter campaign=demo \
  --caller auto_demo \
  --policy-config config/export_policy.example.json \
  --audit-log ../tmp/sse_bridge_pipeline_demo/sse_exports/export_audit.jsonl \
  --job-id auto_demo_job
```

```bash
cd sse
.venv/bin/python run_client.py export-bridge-records \
  --source-path examples/bridge_client_records.jsonl \
  --out-path exports/client_demo.csv \
  --role client \
  --source-format jsonl \
  --out-format csv \
  --join-key-field email \
  --value-field amount \
  --filter campaign=demo \
  --caller auto_demo \
  --policy-config config/export_policy.example.json \
  --audit-log ../tmp/sse_bridge_pipeline_demo/sse_exports/export_audit.jsonl \
  --job-id auto_demo_job
```

Optional SSE-backed candidate export:

```bash
cd sse
.venv/bin/python run_client.py export-bridge-records \
  --source-path examples/bridge_client_records.jsonl \
  --out-path exports/client_demo.csv \
  --role client \
  --source-format jsonl \
  --out-format csv \
  --join-key-field email \
  --value-field amount \
  --filter campaign=demo \
  --caller auto_demo \
  --policy-config config/export_policy.example.json \
  --audit-log ../tmp/sse_bridge_pipeline_demo/sse_exports/export_audit.jsonl \
  --job-id auto_demo_job \
  --sse-keyword demo \
  --record-id-field email_hex \
  --record-id-format hex \
  --sname bridge_sse_demo
```

The orchestrator exposes the same mode with `--server-sse-keyword` / `--client-sse-keyword`, paired with `--server-record-id-field` / `--client-record-id-field`, optional `--server-record-id-format` / `--client-record-id-format`, and optional `--server-sse-sid` / `--client-sse-sid` or `--server-sse-sname` / `--client-sse-sname`.

It can also read bridge records from encrypted record stores instead of plaintext source files:

```bash
export SSE_RECORD_STORE_PASSPHRASE=<passphrase>
cd sse
.venv/bin/python run_client.py create-encrypted-record-store \
  --source-path examples/bridge_client_records.jsonl \
  --out-path exports/client_records.enc.jsonl \
  --source-format jsonl \
  --record-id-field email_hex \
  --key-env SSE_RECORD_STORE_PASSPHRASE
```

Then pass `--client-record-store-path` and `--client-record-store-key-env` to `scripts/run_sse_bridge_pipeline.sh` together with `--client-sse-keyword`. Server-side store options use the same pattern: `--server-record-store-path` and `--server-record-store-key-env`.

For a longer-lived local recovery boundary, start the recovery service and point the orchestrator at it:

```bash
export SSE_RECORD_RECOVERY_TOKEN=<token>
cd sse
.venv/bin/python run_client.py serve-record-recovery \
  --socket-path /tmp/sse_record_recovery.sock \
  --socket-mode 600 \
  --auth-token-env SSE_RECORD_RECOVERY_TOKEN \
  --authz-config "$PWD/../config/record_recovery_service_policy.example.json" \
  --allowed-caller auto_demo \
  --allowed-output-root "$PWD/../tmp" \
  --allowed-record-store-root /tmp \
  --audit-log "$PWD/../tmp/record_recovery_service_audit.jsonl" \
  --pid-file "$PWD/../tmp/record_recovery_service.pid" \
  --ready-file "$PWD/../tmp/record_recovery_service.ready"
cd ..
```

`config/record_recovery_service_policy.example.json` is still the lightweight compatibility example for service-side caller/field/filter/path/row checks, validated by `schemas/record_recovery_service_policy.schema.json`. The default aligned path is now the shared `sse/config/export_policy.example.json`, which also carries caller-scoped `tenant_id`, `allowed_dataset_ids`, `allowed_service_ids`, and `can_use_record_recovery_service`. `config/record_recovery_service.example.json` plus `schemas/record_recovery_service_config.schema.json` define the shared runtime contract for manual health checks, service lifecycle commands, direct export usage, and pipeline-side service wiring, including `service_id`, `tenant_id`, and `dataset_id`.

To verify a pre-started service before the pipeline points at it:

```bash
python3 scripts/request_record_recovery_service.py \
  --config config/record_recovery_service.example.json
```

Or manage the service lifecycle explicitly outside the pipeline:

```bash
python3 scripts/manage_record_recovery_service.py start \
  --config config/record_recovery_service.example.json
python3 scripts/manage_record_recovery_service.py status \
  --config config/record_recovery_service.example.json
python3 scripts/manage_record_recovery_service.py stop \
  --config config/record_recovery_service.example.json
```

Then add these flags to `scripts/run_sse_bridge_pipeline.sh` when using encrypted record stores:

```bash
  --record-recovery-service-config config/record_recovery_service.example.json \
  --record-recovery-service-audit-log "$PWD/tmp/record_recovery_service_audit.jsonl"
```

When encrypted record stores are used, the orchestrator defaults to `--record-recovery-service-mode auto`. In that mode it auto-starts `run_client.py serve-record-recovery`, uses a short `/tmp/seccomp_rr_<hash>.sock` socket path by default so deep `--out-base` directories do not trip the `AF_UNIX` path limit, writes an effective `sse_exports/record_recovery_service_config.json`, captures `record_recovery_service_health.json` through the shared recovery-service client, exports through that service, validates the optional service audit log plus health snapshot, and then shuts the service down on exit. By default the lifecycle files still land under `sse_exports/`, but if the shared config provides explicit lifecycle paths the runtime config artifact reflects those resolved paths. Use `--record-recovery-service-mode manual` for a pre-started service, or `--record-recovery-service-mode subprocess` to force the older worker subprocess path.
If that auto-started service should enforce the same caller/tenant/dataset/service policy as the rest of the pipeline, add `--record-recovery-authz-config "$PWD/sse/config/export_policy.example.json"` to `scripts/run_sse_bridge_pipeline.sh` or `scripts/run_live_sse_bridge_demo.sh`. The older `config/record_recovery_service_policy.example.json` remains available for narrower compatibility testing.
For `scripts/run_live_sse_bridge_demo.sh`, when that flag is supplied and no explicit `--run-root` / `--state-base` / `--out-base` is given, the wrapper now defaults to `/tmp/seccomp_live_sse_bridge_demo` so the example policy's `/tmp` prefix constraints still match the generated state and output paths.

### 2. Prepare paired bridge job

```bash
cd bridge
cargo run -- prepare-job \
  --server-input ../sse/exports/server_demo.csv \
  --server-input-format csv \
  --server-join-key-column email \
  --server-normalizer email \
  --client-input ../sse/exports/client_demo.csv \
  --client-input-format csv \
  --client-join-key-column email \
  --client-value-column amount \
  --client-value-mode raw-int \
  --client-normalizer email \
  --out-dir ./out/sse_demo_job \
  --job-id sse_demo_job \
  --token-scope sse-demo-job \
  --token-secret local-dev-secret
```

The orchestrator also honors `BRIDGE_BIN`, so local engineering or deployment wrappers can swap `cargo run --` for a prebuilt bridge command, for example `BRIDGE_BIN=/path/to/bridge`.

### 3. Validate bridge metadata

```bash
cd a-psi
python3 moduleA_psi/scripts/validate_bridge_job.py --job-dir ../bridge/out/sse_demo_job
```

### 4. Run PJC

```bash
cd a-psi
JOB_ID=sse_bridge_demo_run \
OUT_DIR=runs/sse_bridge_demo_run \
SERVER_CSV=../bridge/out/sse_demo_job/server.csv \
CLIENT_CSV=../bridge/out/sse_demo_job/client.csv \
PJC_BIN_DIR=private-join-and-compute/bazel-bin \
bash moduleA_psi/scripts/run_pjc.sh
```

### 5. Policy release

```bash
cd a-psi
python3 moduleA_psi/scripts/policy_release.py \
  --job-dir runs/sse_bridge_demo_run \
  --caller demo \
  --k 1 \
  --n 5
```

## Remaining production tasks

- Harden the local Unix-socket recovery service into a separately deployed/service-user boundary with durable authn/authz and lifecycle management.
- Move the local key manifest/env-var secret reference to formal key injection, rotation, and deactivation.
- Add stronger validation in `a-psi` for bridge metadata compatibility across both parties.
- Decide the long-term source of truth for join-key normalization rules and versions.

## SSE export boundary controls

`sse export-bridge-records` supports a JSON policy file with per-caller constraints:

- allowed `server` / `client` roles
- allowed join-key and value fields
- required filter fields and allowed filter values
- minimum and maximum export row counts

The example policy is [export_policy.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/sse/config/export_policy.example.json).
The audit log records file hashes, row counts, caller, role, job ID, `correlation_id`, output handoff type, requested fields, and hashed filter values. It does not log raw email, phone, or device identifiers.
Policy config is required by default. For a local one-off export without policy, pass `--unsafe-allow-no-policy` explicitly; the orchestrator equivalent is `--unsafe-allow-no-sse-export-policy`.

When `--sse-keyword` is supplied, `--unsafe-allow-no-policy` is rejected. The audit log additionally records the candidate source, record ID field, and candidate count. If no record store is supplied, the SSE-backed mode can still use a local source file to materialize bridge-ready rows after the SSE query.

When `--record-store-path` is supplied with `--sse-keyword`, the materialization source is an encrypted record store using PBKDF2HMAC-SHA256 and AES-256-GCM. Row lookup tags are HMAC-SHA256 values derived from the store key and record ID, so raw record IDs are not stored in the record-store index.

Two recovery boundaries now exist:

- default subprocess worker: `toolkit.record_recovery_worker`, with `record_recovery_boundary=worker_subprocess`
- long-running Unix-socket service: `run_client.py serve-record-recovery`, used via `--record-recovery-service-config` or `--record-recovery-socket` plus optional `--record-recovery-auth-env`, with `record_recovery_boundary=service_socket`; the pipeline now writes and reuses an effective runtime config artifact for this path

Both paths keep candidate IDs and filters out of the bridge process and return only row counts plus output hash metadata to the export parent path. The socket service can additionally enforce allowed callers, optional `record_recovery_service_policy/v1` checks, and emit `sse_record_recovery_service_audit/v1` records, which can be validated separately and included in `audit_chain.json`. The default remaining plaintext artifact is still the audited bridge-ready handoff file or FIFO stream.

The orchestrator also supports a local streaming handoff:

```bash
bash scripts/run_sse_bridge_pipeline.sh ... \
  --sse-export-handoff-mode fifo
```

In FIFO mode, `sse_exports/server.csv` and `sse_exports/client.csv` are replaced by named pipes consumed directly by the Rust bridge. The SSE audit records `output_file_type=fifo` and a write-time `output_sha256`; the bridge audit records FIFO input type and leaves input SHA-256 null instead of reopening the pipe.

The same policy file is also used by the orchestrator for coarse pipeline permissions:

- `can_run_bridge`
- `can_run_pjc`
- `can_release`

## Bridge audit and key hardening

The Rust bridge writes `bridge_audit.jsonl` with input/output hashes for regular files, FIFO input type for streaming handoff, row counts, token metadata, `correlation_id`, and the token secret source. It records whether the secret came from the CLI or from an environment variable, but never records the secret value. It now also appends deny records when `generate` or `prepare-job` fails after audit-log resolution, so failed bridge stages are auditable without depending on shell stderr alone.

For production-mode runs, use:

```bash
export BRIDGE_TOKEN_SECRET=<secret>
bash scripts/run_sse_bridge_pipeline.sh ... \
  --token-secret-env BRIDGE_TOKEN_SECRET \
  --production-mode
```

In production mode the bridge rejects `--token-secret`.

The orchestrator can resolve a token secret through a local key manifest instead of taking an env var name directly:

```bash
export BRIDGE_TOKEN_SECRET=<secret>
bash scripts/run_sse_bridge_pipeline.sh ... \
  --token-secret-key-id bridge-token-demo-v1 \
  --key-manifest "$PWD/config/key_manifest.example.json" \
  --production-mode
```

This calls [resolve_key_access.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/resolve_key_access.py), which checks that the key entry is enabled, active, and allowed for `bridge_token`, then returns only the env-var reference and key version. It appends `key_access_audit/v1` records to `<out-base>/key_access_audit.jsonl` or the path supplied through `--key-access-audit-log`.

The stronger local KMS-like path uses a keyring plus an auto-started Unix-socket key agent:

```bash
export BRIDGE_TOKEN_SECRET=<secret>
bash scripts/run_sse_bridge_pipeline.sh ... \
  --token-secret-key-name bridge-token \
  --keyring "$PWD/config/keyring.example.json" \
  --production-mode
```

That path auto-starts [key_agent_service.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/key_agent_service.py), resolves the active key version through the socket boundary, injects the secret into a bridge-only env var, and still records `key_access_audit/v1`. Local lifecycle operations are handled through [manage_keyring.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/manage_keyring.py), for example rotating a new version or retiring an old one.

There is also an external-KMS-shaped HTTP path:

```bash
export BRIDGE_TOKEN_SECRET=<secret>
bash scripts/run_sse_bridge_pipeline.sh ... \
  --token-secret-key-name bridge-token \
  --external-kms-config "$PWD/config/external_kms.example.json" \
  --production-mode
```

That path reads [external_kms.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/config/external_kms.example.json), auto-starts [external_kms_service.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/external_kms_service.py) when `auto_start` is configured, resolves the active key version through [request_external_kms.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/request_external_kms.py), and records `key_access_audit/v1` with `secret_source.kind=external_kms`. Lifecycle changes can be driven through [manage_external_kms.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/manage_external_kms.py).

For result-governance hardening, pass `--deny-duplicate-query` to the orchestrator. It is forwarded to `policy_release.py` and denies exact repeated canonical query signatures for the same caller.

The orchestrator always builds [audit_chain.json](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/build_audit_chain.py) at the end of a successful run. It then writes `audit_chain.seal.json` through [seal_audit_artifact.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/seal_audit_artifact.py). Without `--audit-seal-key-env`, the seal records the audit-chain SHA-256. With `--audit-seal-key-env`, it also records an HMAC-SHA256 signature and the env-var source, without logging the secret value. When `--audit-archive-dir` is supplied to the orchestrator, [archive_audit_bundle.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/archive_audit_bundle.py) copies both artifacts into a local archive tree and appends an `audit_archive_index/v1` record to `audit_chain_index.jsonl`.

## Schemas

Versioned schemas are under [schemas](/home/llvanion/Desktop/seccomp-privacy-platform/schemas):

- `sse_export_policy.schema.json`
- `sse_bridge_export_audit.schema.json`
- `sse_encrypted_record_store.schema.json`
- `bridge_job_meta.schema.json`
- `bridge_audit.schema.json`
- `pjc_audit.schema.json`
- `public_report.schema.json`
- `keyring.schema.json`
- `external_kms_config.schema.json`
- `key_lifecycle_audit.schema.json`
- `policy_audit.schema.json`
- `audit_chain.schema.json`
- `record_recovery_service_health.schema.json`
- `audit_archive_index.schema.json`
- `key_manifest.schema.json`
- `key_access_audit.schema.json`
- `audit_seal.schema.json`

The local validator is [validate_json_contract.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/validate_json_contract.py). The integrated pipeline uses it to validate export policy config, optional external KMS config, SSE export audit JSONL, optional record-recovery service health JSON, bridge `job_meta.json`, bridge audit JSONL, PJC audit JSONL, key access audit JSONL, public report JSON, policy audit JSONL, audit chain JSON, audit seal JSON, and optional audit archive index JSONL.

[validate_tabular_contract.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/validate_tabular_contract.py) validates CSV/JSONL handoff contracts that are not JSON schema files. The integrated pipeline uses it for file-mode SSE bridge handoff CSVs and generated PJC server/client CSVs. FIFO handoffs are not re-opened for validation; they are covered by the SSE write-time hash and bridge FIFO input audit fields.

[build_audit_chain.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/build_audit_chain.py) writes `<out-base>/audit_chain.json`, a single correlated view of SSE export audit, bridge audit, bridge metadata, PJC audit, PJC result, public report, policy audit, and optional key access audit for the job. [archive_audit_bundle.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/archive_audit_bundle.py) can then archive `audit_chain.json` plus `audit_chain.seal.json` into a separate local retention directory and append `audit_archive_index/v1` records for indexed lookup.

Run [check_json_contracts.sh](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/check_json_contracts.sh) for the local contract smoke suite. The same command is wired into `.github/workflows/json-contracts.yml`.
