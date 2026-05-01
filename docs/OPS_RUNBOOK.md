# Ops Runbook

This runbook covers sidecar checks around the current privacy pipeline. It does not change the frozen `SSE -> record recovery -> bridge -> PJC -> policy release` path.

## Scope

Use these checks for:

1. Recovery-service reachability and health.
2. Key-agent and external-KMS reachability.
3. Completed pipeline artifact sanity checks.
4. Metadata sidecar DB sanity checks.

Do not use these tools to bypass policy validation, read encrypted record stores directly, or modify bridge/PJC/release contracts.

## Unified Health Check

The unified sidecar probe is:

```bash
python3 scripts/check_platform_health.py
```

With no arguments it returns a `platform_health/v1` warning that no checks were requested. Add one or more targets to make it useful.

### Recovery Service

For a Unix-socket or HTTP service described by the shared config:

```bash
python3 scripts/check_platform_health.py \
  --record-recovery-config config/record_recovery_service.example.json
```

For the HTTP example:

```bash
python3 scripts/check_platform_health.py \
  --record-recovery-config config/record_recovery_http_service.example.json
```

If the service uses `auth_token_env`, the corresponding environment variable must be set before probing.

### Recovery Service Runtime Logs

When the recovery service is started through `scripts/manage_record_recovery_service.py start` with a `log_file` in its config lifecycle block, stdout/stderr are captured there. The service now writes one JSON object per line using `record_recovery_service_log/v1`.

The log records:

- service start and stop events
- health and recover request events
- request ID, transport, service scope, decision, reason code, and `duration_ms`
- non-sensitive caller/job/role/candidate-count context when present

Validate a captured log with:

```bash
python3 scripts/validate_json_contract.py \
  --schema schemas/record_recovery_service_log.schema.json \
  --jsonl tmp/record_recovery_service.log
```

These runtime logs are operational telemetry. They do not replace `sse_record_recovery_service_audit/v1`, which remains the audit stream used by `audit_chain.json`.

### External KMS

```bash
python3 scripts/check_platform_health.py \
  --external-kms-config config/external_kms.example.json
```

If the KMS config uses auth tokens, set the referenced env vars first.

### Key Agent

Probe a running key agent over its Unix socket:

```bash
python3 scripts/check_platform_health.py \
  --key-agent-socket /tmp/seccomp_key_agent.sock \
  --key-name bridge-token \
  --key-purpose bridge_token \
  --caller auto_demo
```

The probe redacts the returned secret and only reports whether a secret was present plus the resolved key version.

### Completed Pipeline Run

Check a completed run directory for the expected artifacts and public report summary:

```bash
python3 scripts/check_platform_health.py \
  --out-base tmp/sse_bridge_pipeline_demo
```

The probe verifies the expected files exist and parses `a_psi_run/public_report.json` plus `audit_chain.json` when present.
For completed runs it now also reports whether `audit_chain.json` embeds `mainline_contract_check/v1`, whether that owner-scope contract check is `status=ok`, whether managed server/client handoff artifacts ended in `removed` / `cleaned` state, and a compact `service_audit_consistency` summary that tells you whether the per-role `server` / `client` recovery-service audit path is `ok`, `fail`, or `not_applicable` relative to the matching SSE export audit records for scope fields, join/value fields, filter hashes, record-store path/hash, and output path/hash/row counts.

### Metadata DB

Check a sidecar metadata DB:

```bash
python3 scripts/check_platform_health.py \
  --metadata-db tmp/platform_metadata.db
```

This verifies the required tables exist and reports row counts for jobs, artifacts, and audit events.

For sidecar lifecycle actions beyond the read-only health probe:

```bash
python3 scripts/manage_metadata_db.py status \
  --db-path tmp/platform_metadata.db

python3 scripts/manage_metadata_db.py backup \
  --db-path tmp/platform_metadata.db \
  --out-path tmp/platform_metadata.backup.db

python3 scripts/manage_metadata_db.py export-json \
  --db-path tmp/platform_metadata.db \
  --out-path tmp/platform_metadata.export.json

python3 scripts/export_authz_tuples.py \
  --db-path tmp/platform_metadata.db \
  --output tmp/platform_authz_tuples.json
```

Use them as follows:

1. `status`: inspect applied/pending migrations, table counts, latest imported job, and DB file digest through `metadata_db_status/v1`
2. `backup`: create a consistent SQLite copy via the backup API, emitting `metadata_db_backup/v1`
3. `export-json`: materialize a portable sidecar snapshot with status, job list, registry/policy entities, and sample artifacts as `metadata_db_export/v1`
4. `export_authz_tuples.py`: materialize the current caller/tenant/dataset/service authz slice as `authz_tuple_export/v1`, either from the sidecar DB or directly from a policy file, for OpenFGA-style relationship sync without changing the frozen pipeline contracts

## Combined Check

Multiple probes can be combined into one report:

```bash
python3 scripts/check_platform_health.py \
  --record-recovery-config config/record_recovery_service.example.json \
  --external-kms-config config/external_kms.example.json \
  --out-base tmp/sse_bridge_pipeline_demo \
  --metadata-db tmp/platform_metadata.db \
  --output tmp/platform_health.json
```

The command exits non-zero if any requested check has `status=error`. Use `--allow-errors` when collecting diagnostics should not fail the surrounding script.

## Platform Health HTTP API

For local UI / SDK / operations tooling that should reuse the existing `platform_health/v1` report over HTTP instead of shelling out directly:

```bash
export SECCOMP_PLATFORM_HEALTH_API_TOKEN=local-platform-health-token
python3 scripts/serve_platform_health_api.py \
  --bind-host 127.0.0.1 \
  --port 18093 \
  --auth-token-env SECCOMP_PLATFORM_HEALTH_API_TOKEN
```

Health:

```bash
curl http://127.0.0.1:18093/healthz
```

Combined report:

```bash
curl -H "Authorization: Bearer $SECCOMP_PLATFORM_HEALTH_API_TOKEN" \
  "http://127.0.0.1:18093/v1/platform-health?out_base=$PWD/tmp/sse_bridge_pipeline_demo&metadata_db=$PWD/tmp/platform_metadata.db"
```

This API is read-only. It does not invent a new health schema or a second implementation path; it wraps the same `scripts/check_platform_health.py` component checks and returns the same `platform_health/v1` result inside HTTP envelopes.

## Existing Focused Tools

Use focused tools when you need lifecycle actions rather than read-only health summaries:

```bash
python3 scripts/manage_record_recovery_service.py status \
  --config config/record_recovery_service.example.json
```

```bash
python3 scripts/request_record_recovery_service.py \
  --config config/record_recovery_service.example.json
```

```bash
python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --job-id auto_demo_job
```

`query_metadata.py --job-id ...` now returns per-stage `duration_ms` in `stage_status` plus per-event `duration_ms` in `audit_events` when the imported run was produced by the current audit writers.
It also carries a compact `mainline_contract_summary` derived from the recorded `audit_chain_path`, so metadata readers can see handoff cleanup state and per-role `service_audit_consistency` without reopening `audit_chain.json` themselves.
It now also returns `timing_summary`, and list queries such as `--caller` / `--tenant-id` include `stage_duration_summary` plus `total_stage_duration_ms` for each returned job, along with a top-level `mainline_contract_summary_counts` rollup for embedded-mainline, handoff-cleanup, and per-role `service_audit_consistency` distributions across the current result set. `grouped_status_summary` and `grouped_stage_summary` buckets now carry the same owner-summary rollup per bucket, and status/stage CSV/TSV exports include those count fields directly. `caller-permissions` entity reads now also return a richer `permission_summary` with `enabled_counts`, `platform_role_counts`, `callers_by_platform_role`, and per-caller `access_profiles`, so operators can inspect the current file-backed authz slice as a compact role matrix instead of manually decoding raw permission rows. Add `--stage bridge` (or any imported stage name) to restrict the job list to runs that imported that stage and to emit a stage-scoped `matched_stage` plus top-level `stage_summary`; add `--stage-status allow|deny|observed|missing` and `--stage-sort duration_desc|duration_asc` when you need to further narrow or rank that stage view; add `--group-by stage` when you want a `grouped_stage_summary` rollup over the returned jobs; add `--group-by status` when you want a `grouped_status_summary` rollup by overall job outcome; add `--list-entity tenants|datasets|services|callers|policies|policy-bindings|caller-permissions` when you want to inspect imported scope entities or policy tables directly; add `--output-format csv|tsv` to export those grouped rollups or entity lists as shell-friendly delimited output; add `--columns` to restrict delimited output to selected fields and `--output-file` to write the rendered report directly to disk.

### Metadata HTTP API

For local UI / SDK / adapter testing, serve the same metadata through a read-only HTTP API:

```bash
export SECCOMP_METADATA_API_TOKEN=local-metadata-token
python3 scripts/serve_metadata_api.py \
  --db-path tmp/platform_metadata.db \
  --bind-host 127.0.0.1 \
  --port 18090 \
  --auth-token-env SECCOMP_METADATA_API_TOKEN
```

Probe health:

```bash
curl http://127.0.0.1:18090/healthz
```

Fetch one job:

```bash
curl -H "Authorization: Bearer $SECCOMP_METADATA_API_TOKEN" \
  "http://127.0.0.1:18090/v1/jobs/auto_demo_job"
```

Fetch filtered jobs or registry/policy entities:

```bash
curl -H "Authorization: Bearer $SECCOMP_METADATA_API_TOKEN" \
  "http://127.0.0.1:18090/v1/jobs?caller=auto_demo&stage=bridge&limit=5"
curl -H "Authorization: Bearer $SECCOMP_METADATA_API_TOKEN" \
  "http://127.0.0.1:18090/v1/entities/policies?limit=10"
```

This API is read-only and DB-backed. It does not re-run imports, query SSE, or bypass the frozen privacy pipeline.
Its health/success/error envelopes are now frozen in `schemas/metadata_api_*.schema.json` and validated by default contract smoke together with the existing API behavior checks.
When you want lifecycle hooks for a local supervisor, pass `--pid-file` and `--ready-file`; the service now removes those files during graceful `SIGTERM` / `SIGINT` shutdown.

## Query Workflow Wrapper

For local query-submit adapter testing without changing the main pipeline entrypoint:

```bash
python3 scripts/submit_query_workflow.py \
  --request-file docs/examples/query_request.json \
  --dry-run
```

This validates a limited JSON request, resolves relative paths against the request file, and emits a redacted submission manifest instead of executing the pipeline immediately.

The request and manifest structures are also pinned in `schemas/query_workflow_request.schema.json` and `schemas/query_workflow_submission.schema.json`. Secret-mode exclusivity and KMS dependency checks still happen in the adapter runtime, not just in schema validation.

To actually run the workflow after inspection:

```bash
python3 scripts/submit_query_workflow.py \
  --request-file docs/examples/query_request.json \
  --execute
```

This wrapper is still adapter-only. It ultimately calls `scripts/run_sse_bridge_pipeline.sh` and does not define a new privacy-computing core contract.

For a local HTTP wrapper over the same adapter:

```bash
export SECCOMP_QUERY_WORKFLOW_API_TOKEN=local-query-token
python3 scripts/serve_query_workflow_api.py \
  --bind-host 127.0.0.1 \
  --port 18091 \
  --auth-token-env SECCOMP_QUERY_WORKFLOW_API_TOKEN
```

Health:

```bash
curl http://127.0.0.1:18091/healthz
```

Dry-run submit:

```bash
curl -X POST \
  -H "Authorization: Bearer $SECCOMP_QUERY_WORKFLOW_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Request-Base-Dir: $PWD/docs/examples" \
  --data @docs/examples/query_request.json \
  http://127.0.0.1:18091/v1/query-workflows/dry-run
```

By default, `/v1/query-workflows/execute` is disabled. Only enable it with `--allow-execute` when you explicitly want the server to run the integrated pipeline.

For a thin local SDK/CLI shell over the metadata, query, audit/public-report, and platform-health APIs:

```bash
python3 scripts/platform_api_client.py query-submit \
  --request-file docs/examples/query_request.json
python3 scripts/platform_api_client.py metadata-entity \
  --entity caller-permissions \
  --param caller=auto_demo \
  --param limit=20
python3 scripts/platform_api_client.py audit-public-report
python3 scripts/platform_api_client.py platform-health \
  --param out_base=tmp/sse_bridge_pipeline_demo \
  --param metadata_db=tmp/platform_metadata.db
```

The local contract smoke now validates:

1. `docs/examples/query_request.json` against `schemas/query_workflow_request.schema.json`
2. CLI dry-run output against `schemas/query_workflow_submission.schema.json`
3. `/healthz`, dry-run success envelopes, and API error envelopes against `schemas/query_workflow_api_*.schema.json`
4. `scripts/platform_api_client.py` against the query submit API including the disabled `--execute` path, metadata health/job/jobs/entity reads, audit health/audit-chain/public-report/observability/catalog-lineage reads including `--include-paths`, and the platform-health API

Those metadata job/job-list reads now also preserve the compact `mainline_contract_summary`, and jobs-list reads also expose `mainline_contract_summary_counts`, so both direct HTTP callers and `platform_api_client.py metadata-job` / `metadata-jobs` can see the owner-scope handoff cleanup and recovery-service consistency verdicts through the metadata surface without client-side rescans.

## Audit/Public-Report Query Adapter

Serve a completed run directory through a read-only HTTP adapter:

```bash
export SECCOMP_AUDIT_QUERY_API_TOKEN=local-audit-token
python3 scripts/serve_audit_query_api.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --bind-host 127.0.0.1 \
  --port 18092 \
  --auth-token-env SECCOMP_AUDIT_QUERY_API_TOKEN
```

Health:

```bash
curl http://127.0.0.1:18092/healthz
```

Public report:

```bash
curl -H "Authorization: Bearer $SECCOMP_AUDIT_QUERY_API_TOKEN" \
  http://127.0.0.1:18092/v1/public-report
```

Observability:

```bash
curl -H "Authorization: Bearer $SECCOMP_AUDIT_QUERY_API_TOKEN" \
  http://127.0.0.1:18092/v1/observability
```

Catalog/lineage:

```bash
curl -H "Authorization: Bearer $SECCOMP_AUDIT_QUERY_API_TOKEN" \
  http://127.0.0.1:18092/v1/catalog-lineage
```

This adapter is read-only. It serves the existing `a_psi_run/public_report.json` and `audit_chain.json` directly, and derives `pipeline_observability/v1` plus `catalog_lineage/v1` on demand from the same audit chain. The observability export now prefers the embedded `mainline_contract_check/v1` payload and emits two derived `handoff_cleanup` events plus two derived `service_audit_consistency` events, so read-side consumers can see both whether managed plaintext handoff artifacts were removed and whether each role's recovery-service boundary was `ok`, `fail`, or `not_applicable` without opening sidecar files separately. The catalog export now also carries the compact `mainline_contract_summary`, including the per-role `service_audit_consistency` verdicts, so lineage consumers can read the same owner-scope recovery-service summary without reparsing the full finding list. It does not touch SSE, bridge, record recovery, or PJC directly.

## Audit Bundle Verification

Build and seal an audit chain from a completed run:

```bash
python3 scripts/build_audit_chain.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --job-id auto_demo_job
python3 scripts/seal_audit_artifact.py \
  --input tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --out tmp/sse_bridge_pipeline_demo/audit_chain.seal.json \
  --job-id auto_demo_job
```

Archive the sealed bundle:

```bash
export SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY=local-audit-anchor
python3 scripts/archive_audit_bundle.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --audit-seal tmp/sse_bridge_pipeline_demo/audit_chain.seal.json \
  --archive-dir tmp/audit_archive \
  --job-id auto_demo_job \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY
```

Verify a direct bundle:

```bash
python3 scripts/verify_audit_bundle.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --audit-seal tmp/sse_bridge_pipeline_demo/audit_chain.seal.json \
  --job-id auto_demo_job
```

Verify and restore from the archive index:

```bash
python3 scripts/verify_audit_bundle.py \
  --archive-index tmp/audit_archive/audit_chain_index.jsonl \
  --job-id auto_demo_job \
  --restore-dir tmp/restored_audit_bundle \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY
```

`archive_audit_bundle.py` now appends an `audit_archive_anchor/v1` record to `audit_chain_anchor.jsonl` for each archived bundle. The anchor log is locally append-only: every entry carries the previous entry hash plus the current index-record hash, and `--anchor-key-env` adds an HMAC over the anchor entry without logging the secret value.

If the seal was created with `--hmac-key-env`, pass the same env var to `verify_audit_bundle.py` to verify the seal HMAC signature. If the archive anchor was created with `--anchor-key-env`, pass the same env var to verify the anchor signature as well. Without those env vars, the tool still verifies artifact SHA-256 values and the anchor-chain linkage, but reports `signature_verified` or `anchor_signature_verified` as `null`. Archive index records and verification reports now also expose a compact `mainline_contract_summary`, including whether `mainline_contract_check/v1` was embedded in `audit_chain.json`, the final `server` / `client` handoff cleanup states, and the per-role `service_audit_consistency` summary for recovery-service runs.

## Repository Hygiene Scan

Run the lightweight secret/build-artifact scan:

```bash
python3 scripts/scan_repo_hygiene.py
```

The scan fails on high-confidence secret material such as private-key blocks, cloud access keys, and common provider tokens. It reports tracked generated artifacts as warnings by default. Use `--fail-on-warn` if a CI job should also fail on warnings, or `--allow-findings` when collecting diagnostics only.

Run the dependency manifest hygiene check:

```bash
python3 scripts/check_dependency_hygiene.py
```

This check is intentionally offline. It verifies first-party Python requirement files and Cargo manifests for basic reproducibility hygiene, while skipping vendored/generated external dependency snapshots.

## Schema Backward-Compatibility Check

Run the frozen-schema compatibility check:

```bash
python3 scripts/check_schema_backcompat.py
```

This compares the committed schema files against `config/schema_backcompat_baseline.json` and emits a `schema_backcompat_check/v1` report. The check is intentionally conservative:

1. schema `$id` must not change
2. stable top-level properties must not disappear
3. existing required fields must not disappear
4. new required fields are treated as breaking until the baseline is deliberately updated

## Smoke Benchmark

Measure existing smoke-check entrypoints without introducing a new runtime path:

```bash
python3 scripts/benchmark_smoke.py --target hygiene --iterations 5
```

Supported targets:

1. `hygiene`: runs `scripts/scan_repo_hygiene.py`.
2. `schema-backcompat`: runs `scripts/check_schema_backcompat.py`.
3. `dependency-hygiene`: runs `scripts/check_dependency_hygiene.py`.
4. `contracts`: runs `scripts/check_json_contracts.sh`.
5. `ci-smoke`: runs `scripts/check_ci_smoke.sh`.

Write a reusable report:

```bash
python3 scripts/benchmark_smoke.py \
  --target contracts \
  --iterations 3 \
  --output tmp/contract_smoke_benchmark.json
```

Benchmark the query-workflow dry-run entrypoints directly:

```bash
python3 scripts/benchmark_query_workflow.py \
  --request-file docs/examples/query_request.json \
  --iterations 3 \
  --mode all \
  --output tmp/query_workflow_benchmark.json
```

This emits `query_workflow_benchmark/v1` and currently compares:

1. `scripts/submit_query_workflow.py --dry-run`
2. `scripts/serve_query_workflow_api.py` + `POST /v1/query-workflows/dry-run`
3. `scripts/platform_api_client.py query-submit`

Default contract smoke now also asserts that the `--mode all` report still covers all three dry-run entrypoints and that each one succeeds.

Benchmark the completed-run metadata and audit read adapters:

```bash
python3 scripts/benchmark_read_adapters.py \
  --iterations 3 \
  --mode all \
  --output tmp/read_adapter_benchmark.json
```

This emits `read_adapter_benchmark/v1` and currently compares:

1. `scripts/query_metadata.py --job-id ...`
2. `scripts/query_metadata.py --caller ... --stage bridge ...`
3. `scripts/serve_metadata_api.py` + `GET /v1/jobs/<job_id>`
4. `scripts/serve_metadata_api.py` + `GET /v1/jobs?...`
5. `scripts/platform_api_client.py metadata-job`
6. `scripts/platform_api_client.py metadata-jobs`
7. `scripts/serve_metadata_api.py` + `GET /v1/entities/caller-permissions?...`
8. `scripts/platform_api_client.py metadata-entity`
9. `scripts/serve_audit_query_api.py` + `GET /v1/audit-chain`
10. `scripts/serve_audit_query_api.py` + `GET /v1/public-report`
11. `scripts/serve_audit_query_api.py` + `GET /v1/observability`
12. `scripts/serve_audit_query_api.py` + `GET /v1/catalog-lineage`
13. `scripts/platform_api_client.py audit-chain`
14. `scripts/platform_api_client.py audit-public-report`
15. `scripts/platform_api_client.py audit-observability`
16. `scripts/platform_api_client.py audit-catalog-lineage`

The benchmark materializes a temporary completed-run bundle plus sidecar metadata DB, then tears them down after the run. It does not require a pre-existing pipeline output directory, and the default contract smoke asserts that the `--mode all` report still contains the full 16-mode surface. The metadata job and jobs-list modes now also pin the embedded `mainline_contract_summary`, and jobs-list modes also pin `mainline_contract_summary_counts`, so the benchmark fails if metadata readers stop carrying handoff cleanup or per-role `service_audit_consistency` verdicts through that read surface.

Benchmark the standalone record-recovery boundary over Unix-socket and HTTP transports:

```bash
python3 scripts/benchmark_record_recovery.py \
  --iterations 3 \
  --mode all \
  --output tmp/record_recovery_benchmark.json
```

This emits `record_recovery_benchmark/v1` and currently compares:

1. `scripts/request_record_recovery_service.py --config ...` health checks
2. `services.record_recovery.client.request_record_recovery_health`
3. `services.record_recovery.client.request_record_recovery`

The benchmark generates a temporary encrypted record store, starts a temporary standalone recovery service through `scripts/manage_record_recovery_service.py`, measures health and recover operations, and then tears the service back down.

Default contract smoke now also asserts the full Unix-socket/HTTP mode set and that the synthetic recover calls still return `output_rows=2`.

Benchmark the integrated file-mode pipeline entrypoint:

```bash
python3 scripts/benchmark_pipeline.py \
  --iterations 1 \
  --mode all \
  --output tmp/pipeline_benchmark.json
```

This emits `pipeline_benchmark/v1` and currently compares:

1. `scripts/run_sse_bridge_pipeline.sh` with normal file handoff
2. `scripts/run_sse_bridge_pipeline.sh --keep-sse-export-handoff-files`
3. `scripts/run_sse_bridge_pipeline.sh --sse-export-handoff-mode fifo`

The benchmark runs the real pipeline against the example bridge inputs and validates that the output still produces `intersection_size=2` and `intersection_sum=425`. It also verifies that managed `server` / `client` handoff artifacts end in the expected owner-visible state for the selected mode: `cleaned` for default file handoff, `retained` for the explicit compatibility mode, and `removed` for FIFO. The result rows now also emit `mainline_contract_check_embedded` plus per-role `handoff_cleanup_*` status and `exists_after_run` fields, so retained-vs-cleaned-vs-removed outcomes remain visible after the run instead of only being enforced internally by the benchmark script. It is intentionally not part of default contract smoke because it is slower and more environment-sensitive than the sidecar-only benchmarks.

Benchmark the standalone PJC runner over a prepared bridge fixture:

```bash
python3 scripts/benchmark_pjc.py \
  --iterations 1 \
  --mode all \
  --output tmp/pjc_benchmark.json
```

This emits `pjc_benchmark/v1` and currently measures:

1. `a-psi/moduleA_psi/scripts/run_pjc.sh`
2. checked-in `bridge/out/sse_demo_job/server.csv`
3. checked-in `bridge/out/sse_demo_job/client.csv`

The benchmark starts the local PJC server on a random loopback port, runs the client, and validates that the resulting `attribution_result.json` still produces `intersection_size=2` and `intersection_sum=425`.

Benchmark the live SSE-backed demo wrapper over default cleanup, retained compatibility, and FIFO handoff modes:

```bash
python3 scripts/benchmark_live_sse_demo.py \
  --iterations 1 \
  --mode all \
  --output tmp/live_sse_benchmark.json
```

This emits `live_sse_benchmark/v1` and currently measures:

1. `scripts/run_live_sse_bridge_demo.sh`
2. `scripts/run_live_sse_bridge_demo.sh --keep-sse-export-handoff-files`
3. `scripts/run_live_sse_bridge_demo.sh --sse-export-handoff-mode fifo`

The benchmark starts or reuses the local SSE server, bootstraps a fresh demo service, runs the live pipeline, and validates that the final result still normalizes to `intersection_size=2` and `intersection_sum=425`. It also verifies that managed `server` / `client` handoff artifacts end in the expected owner-visible state for the selected mode: `cleaned` for default file handoff, `retained` for the explicit compatibility mode, and `removed` for FIFO. The result rows now also emit `mainline_contract_check_embedded` plus per-role `handoff_cleanup_*` status and `exists_after_run` fields, so retained-vs-cleaned-vs-removed outcomes stay visible in the benchmark report itself. It accepts the public-report amount whether it appears as display value, raw integer, or cents field, but it is intentionally not part of default contract smoke because it is the most environment-sensitive local benchmark path.

Benchmark the audit archive and verification entrypoints:

```bash
python3 scripts/benchmark_audit_bundle.py \
  --iterations 1 \
  --mode all \
  --output tmp/audit_bundle_benchmark.json
```

This emits `audit_bundle_benchmark/v1` and currently measures:

1. `scripts/archive_audit_bundle.py`
2. `scripts/verify_audit_bundle.py --audit-chain ... --audit-seal ...`
3. `scripts/verify_audit_bundle.py --archive-index ...`
4. `scripts/verify_audit_bundle.py --archive-index ... --restore-dir ...`

The benchmark materializes a temporary synthetic `audit_chain.json`, seals it through `scripts/seal_audit_artifact.py`, validates the fixture, and then measures archive, direct verify, archive-index verify, and archive-index restore operations. It now also asserts that archive index records and verification reports preserve the embedded owner-scope `mainline_contract_check/v1` summary, including the expected `server=removed` and `client=cleaned` handoff cleanup states, and that archive-backed modes report the expected `anchor_log_verified` / `anchor_signature_verified` results. Because it is self-contained and does not require bridge/PJC/SSE services, it is part of default contract smoke.

The same smoke run now also asserts the expected `archive_index_verified`, `restored`, and anchor-log-path flags for each benchmark mode.

Benchmark the read-only platform health sidecar:

```bash
python3 scripts/benchmark_platform_health.py \
  --iterations 1 \
  --mode all \
  --output tmp/platform_health_benchmark.json
```

This emits `platform_health_benchmark/v1` and currently measures:

1. `scripts/check_platform_health.py --out-base ...`
2. `scripts/check_platform_health.py --metadata-db ...`
3. `scripts/check_platform_health.py --out-base ... --metadata-db ...`
4. `scripts/serve_platform_health_api.py` + `GET /v1/platform-health?out_base=...`
5. `scripts/serve_platform_health_api.py` + `GET /v1/platform-health?metadata_db=...`
6. `scripts/serve_platform_health_api.py` + `GET /v1/platform-health?out_base=...&metadata_db=...`
7. `scripts/platform_api_client.py platform-health`

The benchmark reuses a synthetic completed-run bundle plus imported SQLite metadata DB, seals the synthetic `audit_chain.json` so the pipeline-run probe sees the full expected artifact set, starts the local platform-health HTTP adapter when API/client modes are selected, and validates that each resulting health report still conforms to `platform_health/v1`. Direct HTTP and client responses must also preserve the `platform_health_api_response/v1` envelope. Pipeline-run health now additionally requires the embedded `mainline_contract_check/v1` summary and valid managed handoff cleanup states. Because it is synthetic and read-only, it is part of default contract smoke.

The same smoke run now also asserts the expected component set per mode, while allowing the documented CLI-only fallback when loopback HTTP startup is unavailable in restricted environments.

Benchmark the derived observability and catalog exporters:

```bash
python3 scripts/benchmark_derived_views.py \
  --iterations 1 \
  --mode all \
  --output tmp/derived_views_benchmark.json
```

This emits `derived_views_benchmark/v1` and currently measures:

1. `scripts/export_observability_events.py`
2. `scripts/export_catalog_lineage.py`
3. `scripts/export_catalog_lineage.py --include-paths`

The benchmark reuses the synthetic completed-run fixture, points both exporters at the derived `audit_chain.json`, and validates that observability still carries full stage coverage while catalog export still keeps path redaction off by default unless `--include-paths` is explicitly requested. Observability coverage now explicitly includes both the derived `handoff_cleanup` stage and the derived `service_audit_consistency` stage from the embedded mainline contract payload. Because it is synthetic and read-only, it is part of default contract smoke.

The same smoke run now also asserts the three benchmark modes explicitly and keeps the default-vs-include-paths catalog redaction split pinned semantically.

## Observability Export

Export stage-level observability events from an existing audit chain:

```bash
python3 scripts/export_observability_events.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --out tmp/sse_bridge_pipeline_demo/pipeline_observability.json
```

The output schema is `pipeline_observability/v1`. It is derived from existing audit records and contains the stable telemetry fields called out in the task plan: `job_id`, `correlation_id`, `caller`, `tenant_id`, `dataset_id`, `service_id`, `stage`, `status`, `duration_ms`, `row_count`, and `artifact_sha256`. Current stage-owned audit writers now emit `duration_ms` for SSE export, recovery service, bridge, PJC, and policy release, so new runs surface stage timings directly; older runs can still show `duration_ms=null`. The exporter now also emits a derived `handoff_cleanup` stage for `server` and `client`, plus a derived `service_audit_consistency` stage for `server` and `client`, both sourced from the embedded `mainline_contract_check/v1` payload inside `audit_chain.json`.
Validate it with:

```bash
python3 scripts/validate_json_contract.py \
  --schema schemas/pipeline_observability.schema.json \
  --json tmp/sse_bridge_pipeline_demo/pipeline_observability.json
```

## Catalog And Lineage Export

Export catalog and lineage metadata from the same audit chain:

```bash
python3 scripts/export_catalog_lineage.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --out tmp/sse_bridge_pipeline_demo/catalog_lineage.json
```

The output schema is `catalog_lineage/v1`. By default it records job, dataset, service, artifact-hash, row-count, and stage-edge metadata without full artifact paths and without sensitive plaintext. Use `--include-paths` only when the operator explicitly needs path-level lineage in a controlled environment.
Validate it with:

```bash
python3 scripts/validate_json_contract.py \
  --schema schemas/catalog_lineage.schema.json \
  --json tmp/sse_bridge_pipeline_demo/catalog_lineage.json
```

## Troubleshooting

Common failures:

1. `environment variable ... is not set`: export the auth or secret env var referenced by the config before probing.
2. `connection refused` or `No such file or directory`: the target service is not running, or the config points at the wrong socket or endpoint.
3. `metadata DB does not exist`: initialize and import first with `scripts/init_metadata_db.py` and `scripts/import_run_metadata.py`.
4. Missing pipeline artifacts: rerun the integrated demo or check that `--out-base` points to the root run directory, not a nested artifact directory.
5. `audit seal artifact_sha256 does not match`: the audit chain changed after the seal was created; rebuild the seal or restore the archived copy.
6. `repo_hygiene_scan/v1` warns about tracked generated artifacts: add the generated path to `.gitignore` and remove it from the Git index with `git rm --cached`, preserving local files when needed.

## Baseline Verification

Use the unified CI smoke entrypoint for local preflight:

```bash
bash scripts/check_ci_smoke.sh
```

Use the bridge Rust check when touching `bridge/` or when validating the full preflight locally:

```bash
bash scripts/check_bridge_rust.sh
```

This runs `cargo fmt --check` and `cargo test` with a temporary `/tmp/bridge_cargo_test.*` target directory so local checks do not repopulate tracked repository paths.

Use the contract smoke suite after code or contract changes:

```bash
bash scripts/check_json_contracts.sh
```

Use shell syntax checks after orchestration edits:

```bash
bash -n scripts/run_sse_bridge_pipeline.sh
```
