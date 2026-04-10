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

## Outputs

The orchestrator writes three stages under `--out-base`:

- `sse_exports/`
- `bridge_job/`
- `a_psi_run/`

Important files:

- `sse_exports/export_audit.jsonl`
- `bridge_job/server.csv`
- `bridge_job/client.csv`
- `bridge_job/job_meta.json`
- `bridge_job/bridge_audit.jsonl`
- `a_psi_run/attribution_result.json`
- `a_psi_run/public_report.json`
- `a_psi_run/audit_log.jsonl`

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

- Replace local encrypted record-store recovery with a service-side streaming recovery boundary.
- Move bridge secrets to formal key injection and rotation.
- Add stronger validation in `a-psi` for bridge metadata compatibility across both parties.
- Decide the long-term source of truth for join-key normalization rules and versions.

## SSE export boundary controls

`sse export-bridge-records` supports a JSON policy file with per-caller constraints:

- allowed `server` / `client` roles
- allowed join-key and value fields
- required filter fields and allowed filter values
- minimum and maximum export row counts

The example policy is [export_policy.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/sse/config/export_policy.example.json).
The audit log records file hashes, row counts, caller, role, job ID, requested fields, and hashed filter values. It does not log raw email, phone, or device identifiers.
Policy config is required by default. For a local one-off export without policy, pass `--unsafe-allow-no-policy` explicitly; the orchestrator equivalent is `--unsafe-allow-no-sse-export-policy`.

When `--sse-keyword` is supplied, `--unsafe-allow-no-policy` is rejected. The audit log additionally records the candidate source, record ID field, and candidate count. If no record store is supplied, the SSE-backed mode can still use a local source file to materialize bridge-ready rows after the SSE query.

When `--record-store-path` is supplied with `--sse-keyword`, the materialization source is an encrypted record store using PBKDF2HMAC-SHA256 and AES-256-GCM. Row lookup tags are HMAC-SHA256 values derived from the store key and record ID, so raw record IDs are not stored in the record-store index. The remaining plaintext artifact is the audited bridge-ready handoff file.

The same policy file is also used by the orchestrator for coarse pipeline permissions:

- `can_run_bridge`
- `can_run_pjc`
- `can_release`

## Bridge audit and key hardening

The Rust bridge writes `bridge_audit.jsonl` with input/output hashes, row counts, token metadata, and the token secret source. It records whether the secret came from the CLI or from an environment variable, but never records the secret value.

For production-mode runs, use:

```bash
export BRIDGE_TOKEN_SECRET=<secret>
bash scripts/run_sse_bridge_pipeline.sh ... \
  --token-secret-env BRIDGE_TOKEN_SECRET \
  --production-mode
```

In production mode the bridge rejects `--token-secret`.

## Schemas

Versioned schemas are under [schemas](/home/llvanion/Desktop/seccomp-privacy-platform/schemas):

- `sse_export_policy.schema.json`
- `sse_bridge_export_audit.schema.json`
- `sse_encrypted_record_store.schema.json`
- `bridge_job_meta.schema.json`
- `bridge_audit.schema.json`
