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
  --k 1 \
  --n 5
```

## Outputs

The orchestrator writes three stages under `--out-base`:

- `sse_exports/`
- `bridge_job/`
- `a_psi_run/`

Important files:

- `bridge_job/server.csv`
- `bridge_job/client.csv`
- `bridge_job/job_meta.json`
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
  --filter campaign=demo
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
  --filter campaign=demo
```

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

- Replace example plaintext exports with real SSE-side candidate extraction.
- Move bridge secrets to formal key injection and rotation.
- Add stronger validation in `a-psi` for bridge metadata compatibility across both parties.
- Decide the long-term source of truth for join-key normalization rules and versions.
