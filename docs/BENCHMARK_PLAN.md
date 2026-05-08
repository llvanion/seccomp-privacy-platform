# Benchmark Plan

## Goal

This document defines the first-stage benchmark plan around the frozen privacy pipeline and its sidecar adapters.

The goal is not to invent a new benchmark harness inside the main pipeline. The goal is to measure existing entrypoints and adapters with minimal semantic risk.

## Current Coverage

The repository now has eleven lightweight benchmark paths:

1. [scripts/benchmark_smoke.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/benchmark_smoke.py)
2. [scripts/check_schema_backcompat.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/check_schema_backcompat.py) via `benchmark_smoke.py --target schema-backcompat`
3. [scripts/benchmark_query_workflow.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/benchmark_query_workflow.py)
4. [scripts/benchmark_read_adapters.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/benchmark_read_adapters.py)
5. [scripts/benchmark_record_recovery.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/benchmark_record_recovery.py)
6. [scripts/benchmark_pipeline.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/benchmark_pipeline.py)
7. [scripts/benchmark_pjc.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/benchmark_pjc.py)
8. [scripts/benchmark_live_sse_demo.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/benchmark_live_sse_demo.py)
9. [scripts/benchmark_audit_bundle.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/benchmark_audit_bundle.py)
10. [scripts/benchmark_platform_health.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/benchmark_platform_health.py)
11. [scripts/benchmark_derived_views.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/benchmark_derived_views.py)

## Query Workflow Benchmark

Current supported report schema:

```text
query_workflow_benchmark/v1
```

This benchmark only measures `dry-run` entrypoints:

1. CLI adapter: `scripts/submit_query_workflow.py --dry-run`
2. HTTP adapter: `scripts/serve_query_workflow_api.py` + `POST /v1/query-workflows/dry-run`
3. SDK/CLI shell: `scripts/platform_api_client.py query-submit`

Example:

```bash
python3 scripts/benchmark_query_workflow.py \
  --request-file docs/examples/query_request.json \
  --iterations 3 \
  --mode all \
  --output tmp/query_workflow_benchmark.json
```

Why dry-run first:

1. it exercises request parsing, normalization, validation, manifest generation, and local HTTP wrapping
2. it avoids introducing live-pipeline cost and environmental flakiness into the baseline benchmark
3. it is safe to run in local development and CI-like environments
4. default contract smoke now also asserts that the `--mode all` report still covers all three dry-run entrypoints and that each one succeeded

## Next Query Workflow Coverage

The next benchmark expansion on this line should follow the execute-governance and receipt/status work, not race ahead of it.

Recommended order:

1. keep the current `dry-run` benchmark as the always-on fast guard
2. add synthetic receipt/status benchmark coverage only after the wrapper lifecycle contract is documented and implemented
3. keep live execute benchmarking out of default smoke unless it can be made synthetic and self-contained

Recommended next benchmark modes for the query/workflow line:

1. receipt write latency after accepted submit
2. status read latency by `out_base`
3. status read latency by `job_id`
4. execute-disabled rejection latency for the HTTP adapter
5. terminal failed-status read over a synthetic non-zero-exit fixture

The important guardrail is:

1. benchmark the wrapper lifecycle sidecar
2. do not make the fast benchmark path depend on running the full privacy pipeline

When those modes are added, the benchmark report should still keep `dry-run` and lifecycle status separate so timing regressions in the operator shell do not get conflated with full pipeline runtime.

## Read Adapter Benchmark

Current supported report schema:

```text
read_adapter_benchmark/v1
```

This benchmark measures the current completed-run read adapters over a synthetic local fixture:

1. metadata CLI job lookup: `scripts/query_metadata.py --job-id ...`
2. metadata CLI jobs lookup: `scripts/query_metadata.py --caller ... --stage bridge ...`
3. metadata HTTP job adapter: `scripts/serve_metadata_api.py` + `GET /v1/jobs/<job_id>`
4. metadata HTTP jobs adapter: `scripts/serve_metadata_api.py` + `GET /v1/jobs?...`
5. metadata client job shell: `scripts/platform_api_client.py metadata-job`
6. metadata client jobs shell: `scripts/platform_api_client.py metadata-jobs`
7. metadata HTTP entity adapter: `scripts/serve_metadata_api.py` + `GET /v1/entities/caller-permissions?...`
8. metadata client entity shell: `scripts/platform_api_client.py metadata-entity`
9. audit HTTP audit-chain adapter: `scripts/serve_audit_query_api.py` + `GET /v1/audit-chain`
10. audit HTTP public-report adapter: `scripts/serve_audit_query_api.py` + `GET /v1/public-report`
11. audit HTTP observability adapter: `scripts/serve_audit_query_api.py` + `GET /v1/observability`
12. audit HTTP catalog-lineage adapter: `scripts/serve_audit_query_api.py` + `GET /v1/catalog-lineage`
13. audit client audit-chain shell: `scripts/platform_api_client.py audit-chain`
14. audit client public-report shell: `scripts/platform_api_client.py audit-public-report`
15. audit client observability shell: `scripts/platform_api_client.py audit-observability`
16. audit client catalog-lineage shell: `scripts/platform_api_client.py audit-catalog-lineage`

Example:

```bash
python3 scripts/benchmark_read_adapters.py \
  --iterations 3 \
  --mode all \
  --output tmp/read_adapter_benchmark.json
```

PostgreSQL comparison mode is available once a live metadata database exists:

```bash
python3 scripts/benchmark_read_adapters.py \
  --iterations 3 \
  --mode all \
  --db-dsn postgresql://postgres:test@localhost:5432/postgres \
  --output tmp/read_adapter_benchmark_postgres.json
```

Why it uses a synthetic fixture:

1. it benchmarks stable read paths without depending on a pre-existing local run directory
2. it keeps the benchmark adapter-only by materializing a temporary completed-run bundle and sidecar DB
3. it stays suitable for local development and contract smoke because it does not execute the live privacy pipeline
4. contract smoke also asserts that the `--mode all` report still contains the full metadata job/jobs/entity plus audit-chain/public-report/observability/catalog-lineage surface
5. metadata job and jobs-list modes also preserve the embedded `mainline_contract_summary`, including `handoff_cleanup.server=removed`, `handoff_cleanup.client=cleaned`, `service_audit_consistency.server=not_applicable`, `service_audit_consistency.client=ok`, and `error_count=0` for the synthetic completed-run fixture
6. metadata jobs-list modes also preserve the top-level `mainline_contract_summary_counts` rollup, so the same synthetic fixture still aggregates to `job_count=1`, `handoff_cleanup.server.removed=1`, `handoff_cleanup.client.cleaned=1`, `service_audit_consistency.server.not_applicable=1`, `service_audit_consistency.client.ok=1`, and `error_count_total=0`
7. metadata entity modes now also pin a synthetic multi-role policy fixture rather than the repo-wide demo policy, and they assert that `permission_summary` still exposes the caller-scoped role matrix fields for `platform_role_counts`, `access_profiles`, and the expected `query_submitter` / `privacy_operator` coverage for `auto_demo`

## SSE Export Scale Benchmark

Current supported report schema:

```text
sse_export_benchmark/v1
```

This benchmark measures the encrypted-record-store SSE export path over deterministic synthetic e-commerce order records:

1. `scripts/generate_benchmark_dataset.py orders-jsonl` writes synthetic order JSONL with stable `record_id`, `email`, `amount`, `campaign`, and order metadata fields.
2. `scripts/benchmark_sse_export.py` builds an encrypted record store from that JSONL.
3. The benchmark exports bridge-ready rows through the existing `export_bridge_records` worker-subprocess boundary.
4. The report records setup time, export duration, output rows, throughput, audit decision, recovery boundary, and peak RSS.

Example:

```bash
python3 scripts/benchmark_sse_export.py \
  --record-count 100000 \
  --candidate-count 100000 \
  --iterations 1 \
  --output tmp/sse_export_benchmark_100k.json
```

`scripts/benchmark_smoke.py` also exposes the same path:

```bash
python3 scripts/benchmark_smoke.py --target sse-export-scale --scale 100000
```

Default contract smoke keeps this lightweight by running `record_count=5 / candidate_count=3`, validating `sse_export_benchmark/v1`, and semantically asserting output rows, candidate count, audit decision, `worker_subprocess` recovery boundary, throughput, and RSS fields.

Local 2026-05-07 scale runs:

1. 100k records / 100k candidates: 100000 output rows, 2.885s export duration, 34,661 rows/s, peak RSS 84,760 KB.
2. 1M records / 1M candidates: 1000000 output rows, 27.184s export duration, 36,786 rows/s, peak RSS 609,584 KB.

## Record Recovery Benchmark

Current supported report schema:

```text
record_recovery_benchmark/v1
```

This benchmark measures the standalone record-recovery boundary itself over both Unix-socket and HTTP transports:

1. health CLI: `scripts/request_record_recovery_service.py --config ...`
2. direct health client: `services.record_recovery.client.request_record_recovery_health`
3. direct recover client: `services.record_recovery.client.request_record_recovery`

Example:

```bash
python3 scripts/benchmark_record_recovery.py \
  --iterations 3 \
  --mode all \
  --candidate-count 1000 \
  --concurrency 10 \
  --output tmp/record_recovery_benchmark.json
```

Why it uses a synthetic fixture:

1. it benchmarks the service boundary without requiring a pre-existing encrypted record store or long-running service
2. it reuses the current standalone launcher and manager flow instead of introducing a new benchmark-only transport
3. it keeps the benchmark sidecar-only by generating a temporary encrypted record store and temporary service config under `/tmp`
4. `--candidate-count` sizes the synthetic encrypted record store and verifies that recover calls return the same number of rows as requested
5. `--mode http_recover_concurrent --concurrency <n>` issues concurrent HTTP recover requests against the standalone service and reports per-batch throughput
6. `--mode http_recover_mtls` starts the HTTP recovery service with mock-issued mTLS certificates and verifies a client-authenticated recover request
7. `--mode g2b_acceptance` runs sequential plain HTTP, concurrent plain HTTP, mTLS recover, and `http_recover_concurrent_limited` safety-valve coverage in one report
8. result rows now include optional `service_pid` and `service_rss_kb` so larger explicit runs can capture server-side RSS while the recovery service is still running
9. default contract smoke now also asserts the full Unix-socket/HTTP mode set, that the default synthetic recover calls still return `output_rows=2`, and that the default concurrent HTTP batch returns two successful requests; mTLS and G2-b acceptance remain explicit benchmark modes

Local 2026-05-07 large-candidate runs:

1. 1k candidates / 10 Unix-socket recover iterations: p50 187.210ms, p95 221.626ms, 10/10 success, service RSS 30,932 KB.
2. 10k candidates / 5 Unix-socket recover iterations: p50 414.680ms, p95 474.532ms, 5/5 success, service RSS 33,200 KB.
3. G2-b acceptance at 1k candidates / 10 HTTP concurrent requests / 3 iterations: sequential plain HTTP p95 226.842ms, concurrent throughput 15.818 req/s, mTLS p95 overhead -23.519ms, and `max_rows_per_request=100` rejected 10/10 concurrent over-cap requests.

## Full Pipeline Benchmark

Current supported report schema:

```text
pipeline_benchmark/v1
```

This benchmark measures the integrated file-mode pipeline entrypoint itself, including the explicit retained file-handoff compatibility mode:

1. `scripts/run_sse_bridge_pipeline.sh` with regular file handoff
2. `scripts/run_sse_bridge_pipeline.sh --keep-sse-export-handoff-files --handoff-retention-reason benchmark_file_handoff_retained`
3. `scripts/run_sse_bridge_pipeline.sh --sse-export-handoff-mode fifo`

Example:

```bash
python3 scripts/benchmark_pipeline.py \
  --iterations 1 \
  --mode all \
  --server-source "$PWD/sse/examples/bridge_server_records.jsonl" \
  --client-source "$PWD/sse/examples/bridge_client_records.jsonl" \
  --expected-intersection-size 2 \
  --expected-intersection-sum 425 \
  --output tmp/pipeline_benchmark.json
```

What it validates on each successful run:

1. the pipeline command exits successfully
2. `a_psi_run/attribution_result.json` still reports `intersection_size=2`
3. `a_psi_run/attribution_result.json` still reports `intersection_sum=425`
4. `a_psi_run/public_report.json`, `audit_chain.json`, and `mainline_contract_check.json` exist
5. `audit_chain.json` embeds the same `mainline_contract_check/v1` payload as the sidecar file
6. managed `server` / `client` handoff artifacts end in the expected state for the selected mode: `cleaned` for default file handoff, `retained` for explicit compatibility retention, and `removed` for FIFO
7. retained file-handoff mode also records the expected `retention_reason` in `mainline_contract_check.json`

The emitted benchmark result rows now also carry that owner-facing handoff summary explicitly through `mainline_contract_check_embedded`, `handoff_cleanup_server_status`, `handoff_cleanup_client_status`, `handoff_cleanup_server_exists_after_run`, and `handoff_cleanup_client_exists_after_run`, so downstream smoke checks do not need to infer retained-vs-cleaned-vs-removed semantics from stderr or rerun the pipeline.

Why it is not part of contract smoke:

1. it is environment-sensitive and materially slower than the sidecar-only benchmarks
2. it depends on the local bridge and PJC execution environment rather than only on JSON contracts
3. it is intended for reproducible local performance checks, not as a default CI-fast path
4. the benchmark now runs under a temporary `HOME` so SSE runtime logs stay inside the benchmark sandbox instead of depending on the caller's user directory
5. default contract smoke still validates a synthetic `pipeline_benchmark/v1` fixture plus the expected file-cleanup, retained-file, and FIFO mode/command surface so benchmark-contract drift is caught without executing the heavy benchmark
6. `--server-source`, `--client-source`, `--expected-intersection-size`, and `--expected-intersection-sum` allow larger generated fixtures while preserving explicit result assertions

## PJC Benchmark

Current supported report schema:

```text
pjc_benchmark/v1
```

This benchmark measures the standalone PJC runner over a prepared bridge-job fixture:

1. `a-psi/moduleA_psi/scripts/run_pjc.sh`
2. checked-in `bridge/out/sse_demo_job/server.csv`
3. checked-in `bridge/out/sse_demo_job/client.csv`

Example:

```bash
python3 scripts/benchmark_pjc.py \
  --iterations 1 \
  --mode all \
  --server-csv "$PWD/bridge/out/sse_demo_job/server.csv" \
  --client-csv "$PWD/bridge/out/sse_demo_job/client.csv" \
  --expected-intersection-size 2 \
  --expected-intersection-sum 425 \
  --output tmp/pjc_benchmark.json
```

What it validates on each successful run:

1. the PJC runner exits successfully
2. `attribution_result.json` still reports `intersection_size=2`
3. `attribution_result.json` still reports `intersection_sum=425`

Why it is not part of contract smoke:

1. it directly starts the local PJC server on loopback
2. it is slower and more environment-sensitive than the contract-only checks
3. it is intended for reproducible local performance measurements of the prepared PJC path
4. default contract smoke still validates a synthetic `pjc_benchmark/v1` fixture plus the expected single-mode command and checked-in bridge-fixture surface so benchmark-contract drift is caught without starting the PJC runtime
5. `--server-csv`, `--client-csv`, `--expected-intersection-size`, and `--expected-intersection-sum` allow scale fixtures generated outside the checked-in demo job

## Benchmark Dataset Generator

`scripts/generate_benchmark_dataset.py` creates synthetic inputs for the scale-oriented benchmark paths without changing the frozen pipeline contracts:

1. `orders-jsonl`: e-commerce-style JSONL records for SSE/export benchmarking.
2. `bridge-csv`: server/client CSV fixtures with a controlled overlap for prepared bridge/PJC-style experiments.
3. `pjc-csv`: server/client CSV fixtures with a controlled overlap for PJC-only experiments.

Examples:

```bash
python3 scripts/generate_benchmark_dataset.py bridge-csv \
  --server-csv tmp/bridge_server_100k.csv \
  --client-csv tmp/bridge_client_100k.csv \
  --server-rows 100000 \
  --client-rows 100000 \
  --overlap 0.3

python3 scripts/generate_benchmark_dataset.py pjc-csv \
  --server-csv tmp/pjc_server_100k.csv \
  --client-csv tmp/pjc_client_50k.csv \
  --server-items 100000 \
  --client-items 50000 \
  --overlap 0.2
```

## Live SSE Benchmark

Current supported report schema:

```text
live_sse_benchmark/v1
```

This benchmark measures the live SSE-backed wrapper over default file cleanup, explicit retained file-handoff compatibility mode, and FIFO handoff:

1. `scripts/run_live_sse_bridge_demo.sh`
2. `scripts/run_live_sse_bridge_demo.sh --keep-sse-export-handoff-files --handoff-retention-reason benchmark_live_file_handoff_retained`
3. `scripts/run_live_sse_bridge_demo.sh --sse-export-handoff-mode fifo`

Example:

```bash
python3 scripts/benchmark_live_sse_demo.py \
  --iterations 1 \
  --mode all \
  --output tmp/live_sse_benchmark.json
```

What it validates on each successful run:

1. the live wrapper exits successfully
2. `live_demo_manifest.json`, `a_psi_run/public_report.json`, `audit_chain.json`, and `mainline_contract_check.json` exist
3. the final result still yields `intersection_size=2`
4. the final result still normalizes to `intersection_sum=425`, whether the public report exposes display, raw, or cents fields
5. `audit_chain.json` embeds the same `mainline_contract_check/v1` payload as the sidecar file
6. managed `server` / `client` handoff artifacts end in the expected cleanup state for the selected mode: `cleaned` for default file handoff, `retained` for explicit compatibility retention, and `removed` for FIFO
7. retained live-demo handoff mode also records the expected `retention_reason` in `mainline_contract_check.json`

The emitted benchmark result rows now also carry that owner-facing handoff summary explicitly through `mainline_contract_check_embedded`, `handoff_cleanup_server_status`, `handoff_cleanup_client_status`, `handoff_cleanup_server_exists_after_run`, and `handoff_cleanup_client_exists_after_run`, so downstream smoke checks can assert the retained/default/FIFO cleanup contract directly from the report.

Why it is not part of contract smoke:

1. it starts or reuses the local SSE server and bootstraps a fresh SSE demo service
2. it is materially slower and more environment-sensitive than the sidecar-only benchmarks
3. it is intended for reproducible local end-to-end timing checks of the live SSE-backed path
4. the benchmark now runs the wrapper under a temporary `HOME` so SSE runtime logs stay inside the benchmark sandbox instead of depending on the caller's user directory
5. default contract smoke still validates a synthetic `live_sse_benchmark/v1` fixture plus the expected file-cleanup, retained-file, and FIFO mode/command surface so benchmark-contract drift is caught without starting the live demo

## Audit Bundle Benchmark

Current supported report schema:

```text
audit_bundle_benchmark/v1
```

This benchmark measures the current audit retention and verification entrypoints over a synthetic sealed bundle:

1. `scripts/archive_audit_bundle.py`
2. `scripts/verify_audit_bundle.py --audit-chain ... --audit-seal ...`
3. `scripts/verify_audit_bundle.py --archive-index ...`
4. `scripts/verify_audit_bundle.py --archive-index ... --restore-dir ...`

Example:

```bash
python3 scripts/benchmark_audit_bundle.py \
  --iterations 1 \
  --mode all \
  --output tmp/audit_bundle_benchmark.json
```

What it validates on each successful run:

1. a synthetic `audit_chain.json` fixture and its HMAC-backed `audit_chain.seal.json` both validate before benchmarking
2. archive index creation succeeds and references copied audit artifacts
3. direct and archive-index verification both report `verified=true`
4. archive-index restore mode recreates `audit_chain.json` and `audit_chain.seal.json` under the requested restore directory
5. archive index and verification reports preserve the embedded `mainline_contract_check/v1` summary, including `server=removed` and `client=cleaned`
6. the compact `service_audit_consistency` summary also stays stable: synthetic archive-bundle fixtures currently report both roles as `not_applicable`, while service-boundary completed-run fixtures are free to report role-scoped `ok` or `fail`

Why it is part of contract smoke:

1. it is synthetic and self-contained under `/tmp`
2. it only exercises the existing archive/verify sidecar tools
3. it adds repeatable timing coverage for audit retention workflows without running the privacy pipeline
4. default contract smoke now also asserts the per-mode `archive_index_verified` and `restored` flags so archive, verify, and restore semantics do not silently drift

## Platform Health Benchmark

Current supported report schema:

```text
platform_health_benchmark/v1
```

This benchmark measures the read-only platform health sidecar over the synthetic completed-run fixture:

1. `scripts/check_platform_health.py --out-base ...`
2. `scripts/check_platform_health.py --metadata-db ...`
3. `scripts/check_platform_health.py --out-base ... --metadata-db ...`
4. `scripts/serve_platform_health_api.py` + `GET /v1/platform-health?out_base=...`
5. `scripts/serve_platform_health_api.py` + `GET /v1/platform-health?metadata_db=...`
6. `scripts/serve_platform_health_api.py` + `GET /v1/platform-health?out_base=...&metadata_db=...`
7. `scripts/platform_api_client.py platform-health`

Example:

```bash
python3 scripts/benchmark_platform_health.py \
  --iterations 1 \
  --mode all \
  --output tmp/platform_health_benchmark.json
```

What it validates on each successful run:

1. the health report validates as `platform_health/v1`
2. pipeline-run health succeeds against a synthetic completed-run bundle with `audit_chain.json` plus `audit_chain.seal.json`
3. metadata-db health succeeds against the imported synthetic SQLite sidecar DB
4. HTTP and client responses preserve the `platform_health_api_response/v1` envelope and the inner `platform_health/v1` payload
5. pipeline-run health reports an embedded `mainline_contract_check/v1` summary with valid managed handoff cleanup states
6. pipeline-run health also preserves the compact `service_audit_consistency` summary derived from that owner-scope contract check
7. combined mode returns both `pipeline_run` and `metadata_db` checks with overall `status=ok`

Why it is part of contract smoke:

1. it reuses the same synthetic completed-run fixture profile already used by the read-adapter benchmark
2. it only exercises the existing read-only health probe
3. it adds repeatable timing coverage for ops-side health summaries without requiring live services
4. default contract smoke now also asserts component coverage for each mode, while allowing the documented CLI-only fallback when loopback HTTP startup is unavailable

## Derived Views Benchmark

Current supported report schema:

```text
derived_views_benchmark/v1
```

This benchmark measures the derived read-only exporters over the synthetic completed-run fixture:

1. `scripts/export_observability_events.py`
2. `scripts/export_catalog_lineage.py`
3. `scripts/export_catalog_lineage.py --include-paths`

Example:

```bash
python3 scripts/benchmark_derived_views.py \
  --iterations 1 \
  --mode all \
  --output tmp/derived_views_benchmark.json
```

What it validates on each successful run:

1. observability export still validates as `pipeline_observability/v1`
2. observability output still covers `sse_export`, `record_recovery_service`, `bridge`, `pjc`, `policy_release`, the derived `handoff_cleanup` stage, and the derived `service_audit_consistency` stage from the embedded `mainline_contract_check/v1` payload
3. catalog export still validates as `catalog_lineage/v1`
4. both catalog modes also preserve the embedded `mainline_contract_summary`, including `service_audit_consistency.server=not_applicable`, `service_audit_consistency.client=ok`, and `error_count=0` for the synthetic completed-run fixture
5. default catalog export still omits artifact paths, while `--include-paths` restores them explicitly

Why it is part of contract smoke:

1. it reuses the synthetic completed-run fixture profile already exercised by metadata/audit read benchmarks
2. it only exercises existing read-only derived exporters
3. it adds repeatable timing coverage for observability/catalog sidecars without requiring live services
4. default contract smoke now also asserts observability event coverage and the default-vs-include-paths catalog redaction split

## Rules

Benchmark additions should follow these rules:

1. prefer adapters and wrappers over main-pipeline modifications
2. keep benchmark reports versioned as JSON contracts
3. separate stable local dry-run benchmarks from environment-sensitive live benchmarks
4. do not bypass policy validation, record recovery boundaries, or release policy just to collect timings

## Reporting

Current reporting conventions:

1. benchmark scripts emit JSON to stdout
2. benchmark scripts accept `--output` for reusable reports
3. benchmark scripts should default to a small iteration count
4. benchmark scripts should support a non-failing mode for exploratory local runs when practical
