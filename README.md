# seccomp-privacy-platform

This repository is a multi-module privacy computing workspace that integrates:

- `sse/`: searchable symmetric encryption storage and local candidate export
- `bridge/`: Rust-based tokenization and PJC input generation layer
- `a-psi/`: Private Join and Compute execution, result governance, and audit release

The current end-to-end flow is:

```text
SSE local export -> Rust bridge tokenization -> A-PSI/PJC execution -> policy release
```

This layout keeps the three responsibilities separated:

- `sse` owns encrypted/searchable storage and local filtering.
- `bridge` owns join-key normalization, scoped HMAC token generation, and job metadata.
- `a-psi` owns PJC execution, result thresholding, audit logging, and public report generation.

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
  --k 1 \
  --n 5
```

Expected demo result:

```text
intersection_size=2
intersection_sum=425
```

The pipeline writes:

```text
tmp/sse_bridge_pipeline_demo/
├── sse_exports/
├── bridge_job/
└── a_psi_run/
```

Key output files:

- `bridge_job/server.csv`
- `bridge_job/client.csv`
- `bridge_job/job_meta.json`
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

### `bridge/`

Rust CLI:

```bash
cd bridge
cargo run -- --help
cargo run -- generate --help
cargo run -- prepare-job --help
```

Use `--token-secret-env BRIDGE_TOKEN_SECRET` instead of `--token-secret` for non-demo runs.

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

- `sse` local bridge export command
- Rust `bridge` CLI with `generate` and `prepare-job`
- bridge metadata validation in `a-psi`
- automatic `sse -> bridge -> a-psi -> policy` orchestrator
- demo PJC run producing `intersection_size=2`, `intersection_sum=425`

Still needed for production use:

- Replace example plaintext exports with real SSE-side candidate extraction.
- Move bridge token secrets to a formal key-management path.
- Finalize join-key normalization schemas and versioning policy.
- Add stronger schema contracts for exported SSE records and bridge metadata.
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
