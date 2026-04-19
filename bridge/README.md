# bridge

This directory contains the Rust SSE-to-PJC bridge layer.

Current responsibilities:

- normalize exported join keys
- generate scoped HMAC-SHA256 join tokens
- materialize `server.csv`, `client.csv`, and enriched `job_meta.json` for `a-psi`

## Build

```bash
cd bridge
cargo build
```

## First CLI

Generate `server.csv` from a CSV export:

```bash
cargo run -- generate \
  --input ./examples/server_export.csv \
  --input-format csv \
  --out-dir ./out/server_job \
  --role server \
  --join-key-column email \
  --normalizer email \
  --token-scope demo-job \
  --token-secret local-dev-secret \
  --job-id demo_server_job
```

Generate `client.csv` from a CSV export:

```bash
cargo run -- generate \
  --input ./examples/client_export.csv \
  --input-format csv \
  --out-dir ./out/client_job \
  --role client \
  --join-key-column email \
  --value-column amount \
  --value-mode raw-int \
  --normalizer email \
  --token-scope demo-job \
  --token-secret local-dev-secret \
  --job-id demo_client_job
```

Generate a complete `a-psi` job directory from paired exports:

```bash
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
```

## Notes

- `--token-secret-env BRIDGE_TOKEN_SECRET` is preferred over passing secrets directly in shell history.
- `--production-mode` rejects `--token-secret`; use `--token-secret-env` for production-like runs.
- In the integrated pipeline, `--token-secret-key-id` plus `--key-manifest` can resolve a token-secret env var through `scripts/resolve_key_access.py` and write key access audit without exposing the secret.
- The integrated pipeline also supports `--token-secret-key-name` plus `--keyring`, which auto-starts a local Unix-socket key agent and injects the resolved active key version into bridge metadata without passing the raw secret on the command line.
- The integrated pipeline also supports `--token-secret-key-name` plus `--external-kms-config`, which resolves the active key version through an external HTTP KMS boundary and records `key_access_audit/v1` with `secret_source.kind=external_kms`.
- Bridge writes `bridge_audit.jsonl` by default, or the file specified by `--audit-log`, and now appends deny records when `generate` or `prepare-job` fails after the audit log path is known.
- `--token-scope` should match across both parties for the same PJC job.
- Current input support is `csv` and `jsonl`.
- `prepare-job` writes `server.csv`, `client.csv`, and `job_meta.json` into a single directory that can be consumed by `a-psi`.
