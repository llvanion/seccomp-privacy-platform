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

If you need the fastest repo context with the lowest token cost, start here instead of reading `docs/*.md` broadly:

- [docs/COMPACT_PLATFORM_BRIEF.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/COMPACT_PLATFORM_BRIEF.md)
- [docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md)
- [docs/NEXT_SESSION_READING_GUIDE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/NEXT_SESSION_READING_GUIDE.md)

The current control-plane baseline now includes caller-scoped tenant/dataset/service authorization in `sse/config/export_policy.example.json`, and the recovery-service runtime contract now binds `service_id`, `tenant_id`, and `dataset_id` so the SSE export path, the long-running recovery service, and the integrated pipeline all resolve the same scope.
The first SQL control-plane sidecar step now also exists as a separate SQLite metadata layer under `migrations/metadata/` and `scripts/{init,import,query}_metadata.py`. It imports existing run artifacts into a durable jobs/audits/services catalog without making the main SSE -> bridge -> A-PSI pipeline depend on a database.

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
Managed file-mode SSE handoff artifacts under `sse_exports/` are now cleaned after `bridge prepare-job` by default. Use `--keep-sse-export-handoff-files --handoff-retention-reason <text>` only for compatibility or debugging when those plaintext files need to remain on disk; that mode is still audited as an explicit retained-handoff exception rather than a silent drift in the default path.

### 4. Run the live SSE-backed demo end-to-end

The repo now includes a wrapper that starts or reuses the local SSE server, bootstraps a fresh SSE service, prepares normalized demo inputs plus encrypted record stores, runs the integrated pipeline, verifies `intersection_size=2` / `intersection_sum=425`, and writes a run manifest:

```bash
bash scripts/run_live_sse_bridge_demo.sh
```

Outputs are written under `tmp/live_sse_bridge_demo/`. The most useful artifact is the run manifest, which records the exact `state_base`, `out_base`, `job_id`, `service_name`, and final result for that invocation:

- `tmp/live_sse_bridge_demo/run-*/live_demo_manifest.json`
- `tmp/live_sse_bridge_demo/run-*/a_psi_run/public_report.json`
- `tmp/live_sse_bridge_demo/run-*/mainline_contract_check.json`
- `tmp/live_sse_bridge_demo/run-*/audit_chain.json`

`live_demo_manifest.json` now also records runtime options, including whether managed file-mode SSE handoff artifacts should be cleaned after bridge ingestion and any explicit retained-handoff reason, plus normalized demo inputs, encrypted record-store paths, recovery-service lifecycle artifacts, final release status, and the released sum in display/raw/cents forms when the public report exposes them.

Useful flags:

- `--bootstrap-only`: prepare SSE server/service state and encrypted record stores without running the pipeline
- `--keep-server`: leave the SSE server running when this wrapper started it
- `--token-secret-key-name <name>` plus `--keyring <path>`: run the live demo through the local key-agent/KMS path instead of passing `--token-secret`
- `--token-secret-key-name <name>` plus `--external-kms-config <path>`: run the live demo through the external HTTP KMS path instead of passing `--token-secret`
- `--record-recovery-service-mode auto|manual|subprocess`: override the recovery boundary used by the integrated run
- `--record-recovery-authz-config <path>`: optional authz policy for the auto-started recovery service
- `--sse-export-handoff-mode file|fifo`: choose bridge handoff persistence vs FIFO streaming
- `--keep-sse-export-handoff-files` plus `--handoff-retention-reason <text>`: opt out of the default live-demo and pipeline cleanup of managed file-mode SSE handoff artifacts after `bridge prepare-job`; `mainline_contract_check.json` records that compatibility mode as `retained` together with the explicit retention reason

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

For a longer-lived local boundary, start the standalone recovery service and give it an audit log plus an allowlist for trusted callers:

```bash
export SSE_RECORD_RECOVERY_TOKEN=<token>
python3 scripts/run_record_recovery_service.py serve \
  --transport unix_socket \
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
  --audit-log "$PWD/tmp/record_recovery_service_audit.jsonl" \
  --pid-file "$PWD/tmp/record_recovery_service.pid" \
  --ready-file "$PWD/tmp/record_recovery_service.ready"
```

The default aligned policy is now `sse/config/export_policy.example.json`, validated by `schemas/sse_export_policy.schema.json`. It carries the export/bridge/PJC/release booleans plus caller-scoped `tenant_id`, `allowed_dataset_ids`, `allowed_service_ids`, and `can_use_record_recovery_service`, so the recovery-service boundary reuses the same caller/tenant/dataset/service contract as the rest of the pipeline. The same schema now also accepts optional `platform_roles` plus `access_profile`, so callers can be tagged with coarse-grained control-plane roles like `query_submitter`, `privacy_operator`, `platform_auditor`, or `service_operator` without changing the frozen pipeline field names. A fuller multi-caller example lives at `sse/config/ecommerce_access_policy.example.json`, and the corresponding role matrix is documented in [docs/ECOMMERCE_ACCESS_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_ACCESS_MODEL.md). The older `config/record_recovery_service_policy.example.json` remains as a narrower service-only compatibility example. For aligned manual operations, `config/record_recovery_service.example.json` and `schemas/record_recovery_service_config.schema.json` now act as the shared runtime contract for `scripts/run_record_recovery_service.py serve --config`, `run_client.py serve-record-recovery --config`, `scripts/request_record_recovery_service.py --config`, `scripts/manage_record_recovery_service.py --config`, `run_client.py export-bridge-records --record-recovery-service-config`, and pipeline-side `--record-recovery-service-config`. When service-side authz should come from the imported SQLite metadata sidecar instead of a raw policy JSON, point `authz_config` at `config/record_recovery_authz_sqlite.example.json` (`record_recovery_authz_source/v1`), which rebuilds the current `sse_export_policy/v1` caller view from `caller_permissions`.
For the HTTP transport variant of that same runtime contract, `config/record_recovery_http_service.example.json` shows the recommended `endpoint_url`, `http_listener`, auth token env, and lifecycle file layout for the standalone launcher.

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

To replay the full live SSE-backed path against a pre-started external HTTP recovery service and assert the manual service boundary stays aligned with the documented health/runtime/mainline contracts:

```bash
bash scripts/verify_record_recovery_manual_service_replay.sh
```

If the service should move from an operator shell into a long-running host-level deploy unit, the same runtime config can now be rendered into a baseline `systemd` service file and env template without changing the launcher contract:

```bash
python3 scripts/manage_record_recovery_service.py render-systemd \
  --config config/record_recovery_http_service.example.json \
  --unit-name seccomp-record-recovery-http \
  --service-user record-recovery \
  --service-group record-recovery \
  --environment-file /etc/seccomp/seccomp-record-recovery-http.env \
  --output /tmp/seccomp-record-recovery-http.service \
  --env-output /tmp/seccomp-record-recovery-http.env.example
```

The generated unit keeps calling `scripts/run_record_recovery_service.py serve`, writes service stdout/stderr to journald, and emits an env template for any startup secret refs such as `auth_token_env`, so the current `record_recovery_service_config/v1` remains the source of truth even when the service is promoted into a dedicated service-user lifecycle.

Then add either `--record-recovery-service-config config/record_recovery_service.example.json` or the lower-level `--record-recovery-socket /tmp/sse_record_recovery.sock` plus `--record-recovery-auth-env SSE_RECORD_RECOVERY_TOKEN` to `scripts/run_sse_bridge_pipeline.sh` when the pipeline should use and validate that service boundary. `run_client.py export-bridge-records` accepts the same aligned config through `--record-recovery-service-config`.
If encrypted record stores are used, the orchestrator now defaults to `--record-recovery-service-mode auto`, which auto-starts a local recovery service through `scripts/run_record_recovery_service.py`, generates an auth token env var if needed, uses a short `/tmp/seccomp_rr_<hash>.sock` socket path by default to avoid `AF_UNIX` path-length failures, writes an effective `sse_exports/record_recovery_service_config.json`, captures `sse_exports/record_recovery_service_health.json` through the shared recovery-service client, and shuts the service down after the run. That runtime config now also records the resolved `service_id`, `tenant_id`, and `dataset_id`, so manual and auto service modes stay aligned with the export/pipeline policy. By default the pid/ready lifecycle files still land under `sse_exports/`, but when the shared config provides explicit lifecycle paths the pipeline now honors them and records the effective result in the runtime config artifact. `--record-recovery-authz-config` can now point to either the legacy `config/record_recovery_service_policy.example.json` or the unified `sse/config/export_policy.example.json`. Use `--record-recovery-service-mode manual` to point at a pre-started service, or `--record-recovery-service-mode subprocess` to force the older worker-subprocess path.

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
- optional archived copies plus `audit_chain_index.jsonl` and `audit_chain_anchor.jsonl` when `--audit-archive-dir` is used

### 6. Optional SQL Metadata Sidecar

The repo now includes a first-stage SQL control-plane sidecar built on SQLite plus pure SQL migrations. It is read-only with respect to the main pipeline: current runs still emit JSON/JSONL artifacts first, and the sidecar imports those artifacts afterward.

Initialize the database:

```bash
python3 scripts/init_metadata_db.py --db-path tmp/platform_metadata.db
```

Import one existing run directory:

```bash
python3 scripts/import_run_metadata.py \
  --out-base tmp/live_sse_bridge_demo/run-20260411T074415Z \
  --db-path tmp/platform_metadata.db
```

Query by job:

```bash
python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --job-id live_sse_demo_20260411T074415Z
```

Check sidecar status, create a consistent SQLite backup, or export a portable JSON snapshot:

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

`--job-id` output now includes `timing_summary`, which gives a stage-by-stage duration map plus `total_stage_duration_ms` derived from imported `job_stage_status` rows.

Query by caller or scope:

```bash
python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --tenant-id demo_tenant \
  --dataset-id bridge_demo_dataset \
  --service-id bridge-demo-recovery

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --stage bridge

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --stage bridge \
  --stage-status allow \
  --stage-sort duration_desc

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --group-by stage

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --group-by status

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --group-by stage \
  --output-format tsv

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --group-by status \
  --output-format csv

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --group-by stage \
  --output-format tsv \
  --columns stage,duration_total

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --group-by status \
  --output-format csv \
  --columns status,duration_total \
  --output-file tmp/platform_metadata_status.csv

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --list-entity tenants \
  --tenant-id demo_tenant

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --list-entity services \
  --service-id bridge-demo-recovery

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --list-entity policies

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --list-entity policy-bindings \
  --caller auto_demo

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --list-entity caller-permissions \
  --caller auto_demo \
  --output-format csv \
  --columns policy_id,caller,permission_key,permission_value
```

The current schema covers `tenants`, `datasets`, `services`, `callers`, `jobs`, `job_artifacts`, `job_stage_status`, `audit_events`, `audit_chains`, `audit_seals`, `policies`, `policy_bindings`, `caller_permissions`, `key_access_events`, and `schema_migrations`. The current migration set is `001_init.sql` plus `002_add_stage_duration_columns.sql`, so imported `job_stage_status` and `audit_events` rows now carry `duration_ms` when the underlying audit records provide it. `query_metadata.py` now also summarizes those stage durations in both job-detail and jobs-list responses, attaches the compact `mainline_contract_summary` loaded from each job's recorded `audit_chain_path`, adds a top-level `mainline_contract_summary_counts` rollup for jobs-list responses so callers can aggregate embedded-mainline, handoff-cleanup, and per-role `service_audit_consistency` outcomes without rescanning each row, and now also carries the same rollup inside both `grouped_status_summary` and `grouped_stage_summary` buckets. `caller-permissions` entity results now also expose a top-level `permission_summary` that compacts the current file-backed authz slice into caller count, tenant IDs, allowed dataset/service IDs, coarse permission booleans, `platform_role_counts`, `callers_by_platform_role`, and per-caller `access_profiles`, so current authz state is easier to audit as a role matrix through metadata CLI/API. `--stage <name>` adds a per-job `matched_stage` record plus an aggregated `stage_summary` for the filtered stage, `--stage-status` / `--stage-sort duration_desc|duration_asc` let the caller narrow that stage view by imported status and rank results by the matched stage duration, `--group-by stage` emits a `grouped_stage_summary` rollup for the currently returned jobs, `--group-by status` emits a `grouped_status_summary` rollup by overall job status, `--list-entity tenants|datasets|services|callers|policies|policy-bindings|caller-permissions` exposes the imported registry and policy tables through the same CLI, and `--output-format csv|tsv` can now render both grouped job rollups and entity lists directly as delimited reports while `--columns` narrows those outputs. `scripts/manage_metadata_db.py` now adds sidecar lifecycle primitives for `status`, SQLite-backup-API `backup`, and portable `export-json`; `scripts/export_authz_tuples.py` adds a first-stage OpenFGA-style relationship export that can read the same caller/tenant/dataset/service policy either from `sse_export_policy/v1` or from the imported metadata DB and freeze it as `authz_tuple_export/v1`. Disabled callers stay visible in the exported `subjects` inventory but do not emit active tuples, so the current file-backed disable semantics survive the sync boundary. `scripts/check_json_contracts.sh` now verifies those lifecycle outputs together with the tuple export, timing summaries, embedded owner-scope summaries, grouped rollups, and synthetic multi-role policy/entity exports round-trip through the sidecar.

For a thin local read-only HTTP wrapper over that same sidecar:

```bash
export SECCOMP_METADATA_API_TOKEN=local-metadata-token
python3 scripts/serve_metadata_api.py \
  --db-path tmp/platform_metadata.db \
  --bind-host 127.0.0.1 \
  --port 18090 \
  --auth-token-env SECCOMP_METADATA_API_TOKEN
```

Example requests:

```bash
curl http://127.0.0.1:18090/healthz
curl -H "Authorization: Bearer $SECCOMP_METADATA_API_TOKEN" \
  "http://127.0.0.1:18090/v1/jobs/live_sse_demo_20260411T074415Z"
curl -H "Authorization: Bearer $SECCOMP_METADATA_API_TOKEN" \
  "http://127.0.0.1:18090/v1/jobs?caller=auto_demo&stage=bridge&limit=5"
curl -H "Authorization: Bearer $SECCOMP_METADATA_API_TOKEN" \
  "http://127.0.0.1:18090/v1/entities/policies?limit=10"
```

The API is read-only, backed by the imported SQLite metadata DB, and does not query SSE, record recovery, bridge, or PJC directly. It exists to support local UI / SDK / control-plane read adapters without changing the frozen main pipeline.
For local supervision, it also accepts optional `--pid-file` and `--ready-file`, and now removes those lifecycle files on graceful `SIGTERM` / `SIGINT` shutdown. Its health/success/error envelopes are now frozen in `schemas/metadata_api_*.schema.json`, guarded by the schema backcompat baseline, and validated by contract smoke.

### 7. Optional Query Submission Wrapper

The repo now also includes a structured query/workflow submission adapter that validates a limited request JSON and maps it onto the existing integrated pipeline CLI:

```bash
python3 scripts/submit_query_workflow.py \
  --request-file docs/examples/query_request.json \
  --dry-run
```

It currently supports the first-stage `query_type=cross_party_match` path and emits a redacted `query_workflow_submission/v1` manifest instead of inventing a new pipeline contract. The request, manifest, and HTTP envelopes are now frozen as local JSON schemas under `schemas/query_workflow_*.schema.json`, while semantic checks such as mutually-exclusive secret modes and KMS dependencies stay enforced in `scripts/submit_query_workflow.py`. Use `--execute` only after the dry-run command looks correct.

The request format and boundary rules are documented in [docs/QUERY_INTERFACE_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/QUERY_INTERFACE_PLAN.md).

For local UI / SDK prototype work, the same adapter also has an HTTP wrapper:

```bash
export SECCOMP_QUERY_WORKFLOW_API_TOKEN=local-query-token
python3 scripts/serve_query_workflow_api.py \
  --bind-host 127.0.0.1 \
  --port 18091 \
  --auth-token-env SECCOMP_QUERY_WORKFLOW_API_TOKEN
```

Example dry-run:

```bash
curl -X POST \
  -H "Authorization: Bearer $SECCOMP_QUERY_WORKFLOW_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Request-Base-Dir: $PWD/docs/examples" \
  --data @docs/examples/query_request.json \
  http://127.0.0.1:18091/v1/query-workflows/dry-run
```

The submit API defaults to dry-run only. `/v1/query-workflows/execute` stays disabled unless the server starts with `--allow-execute`. `scripts/check_json_contracts.sh` now validates the example request, CLI manifest, API health/response envelopes, API error envelopes, and the audit/public-report query adapter envelopes against their local schemas.

For a thin local SDK/CLI prototype over the metadata, query-submit, and audit/public-report sidecar APIs, use:

```bash
python3 scripts/platform_api_client.py query-submit \
  --request-file docs/examples/query_request.json
python3 scripts/platform_api_client.py metadata-entity \
  --entity caller-permissions \
  --param caller=auto_demo \
  --param limit=20
python3 scripts/platform_api_client.py audit-public-report
```

`platform_api_client.py` only forwards to the local metadata/query/audit/platform-health HTTP wrappers. It does not add new control-plane or privacy semantics.

For local UI / SDK / audit-view prototype work, the repo now also includes a read-only audit/public-report adapter over an existing completed run directory:

```bash
export SECCOMP_AUDIT_QUERY_API_TOKEN=local-audit-token
python3 scripts/serve_audit_query_api.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --bind-host 127.0.0.1 \
  --port 18092 \
  --auth-token-env SECCOMP_AUDIT_QUERY_API_TOKEN
```

Example reads:

```bash
curl -H "Authorization: Bearer $SECCOMP_AUDIT_QUERY_API_TOKEN" \
  http://127.0.0.1:18092/v1/public-report
curl -H "Authorization: Bearer $SECCOMP_AUDIT_QUERY_API_TOKEN" \
  http://127.0.0.1:18092/v1/observability
curl -H "Authorization: Bearer $SECCOMP_AUDIT_QUERY_API_TOKEN" \
  http://127.0.0.1:18092/v1/catalog-lineage
```

This adapter is read-only, serves the existing `public_report.json` and `audit_chain.json`, and derives `pipeline_observability/v1` plus `catalog_lineage/v1` on demand without changing the frozen main pipeline. `pipeline_observability/v1` now also includes derived `handoff_cleanup` events plus derived `service_audit_consistency` events sourced from the embedded `mainline_contract_check/v1` payload in `audit_chain.json`, and `catalog_lineage/v1` now carries the same compact `mainline_contract_summary` so catalog consumers can see per-role recovery-service consistency without reopening the full finding list.

For a matching read-only HTTP wrapper over the existing `platform_health/v1` sidecar, use:

```bash
export SECCOMP_PLATFORM_HEALTH_API_TOKEN=local-platform-health-token
python3 scripts/serve_platform_health_api.py \
  --bind-host 127.0.0.1 \
  --port 18093 \
  --auth-token-env SECCOMP_PLATFORM_HEALTH_API_TOKEN
```

Example reads:

```bash
curl http://127.0.0.1:18093/healthz
curl -H "Authorization: Bearer $SECCOMP_PLATFORM_HEALTH_API_TOKEN" \
  "http://127.0.0.1:18093/v1/platform-health?out_base=$PWD/tmp/sse_bridge_pipeline_demo"
curl -H "Authorization: Bearer $SECCOMP_PLATFORM_HEALTH_API_TOKEN" \
  "http://127.0.0.1:18093/v1/platform-health?out_base=$PWD/tmp/sse_bridge_pipeline_demo&metadata_db=$PWD/tmp/platform_metadata.db"
```

This adapter is also read-only. It just exposes the existing `scripts/check_platform_health.py` report over HTTP, reusing the same component-level checks and returning the frozen `platform_health/v1` payload inside API envelopes. For completed runs, that payload now also reports whether `audit_chain.json` embeds `mainline_contract_check/v1` and whether managed handoff cleanup states are valid.

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
python3 ../scripts/run_record_recovery_service.py --help
.venv/bin/python run_client.py serve-record-recovery --help
```

This command performs local controlled export into a bridge-ready CSV/JSONL format.
Use `--caller`, `--policy-config`, `--audit-log`, and `--job-id` to enforce caller-specific export policy and write an audit record before the Rust bridge sees join-key fields. Policy config is required by default; ad-hoc local exports must pass `--unsafe-allow-no-policy` explicitly.
Use `--sse-keyword` with `--record-id-field` and optional `--record-id-format` / `--sid` / `--sname` when the export should first query SSE and then materialize only the matching candidate rows. This mode rejects `--unsafe-allow-no-policy`.
Use `create-encrypted-record-store` plus `--record-store-path` / `--record-store-key-env` when those matching rows should be recovered from an encrypted local record store instead of a plaintext JSONL/CSV source. The default recovery path runs through the `services.record_recovery.worker` subprocess boundary and records `record_recovery_boundary=worker_subprocess` in SSE export audit; `toolkit.record_recovery_worker` remains as a compatibility entrypoint.
For a longer-lived boundary, start `scripts/run_record_recovery_service.py serve` or keep using the older `run_client.py serve-record-recovery` compatibility entrypoint, then pass either `--record-recovery-service-config`, `--record-recovery-socket`, or `--record-recovery-endpoint-url` plus optional `--record-recovery-auth-env` to `export-bridge-records` or `scripts/run_sse_bridge_pipeline.sh`. The service can enforce `--allowed-caller`, optional `--authz-config`, and its own `--audit-log`. SSE export audit records `record_recovery_boundary=service_socket` or `service_http`, and the service audit can be validated separately or folded into `audit_chain.json`. When encrypted record stores are used, the orchestrator defaults to `--record-recovery-service-mode auto`; `manual` and `subprocess` remain available for explicit control. `--record-recovery-authz-config` is wired into the auto-started service path.
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
- `schemas/record_recovery_service_log.schema.json`
- `schemas/record_recovery_service_policy.schema.json`
- `schemas/record_recovery_boundary_check.schema.json`
- `schemas/platform_health.schema.json`
- `schemas/mainline_contract_check.schema.json`
- `schemas/sse_encrypted_record_store.schema.json`
- `schemas/bridge_job_meta.schema.json`
- `schemas/bridge_audit.schema.json`
- `schemas/pjc_audit.schema.json`
- `schemas/public_report.schema.json`
- `schemas/policy_audit.schema.json`
- `schemas/audit_chain.schema.json`
- `schemas/audit_archive_index.schema.json`
- `schemas/audit_archive_anchor.schema.json`
- `schemas/audit_bundle_verification.schema.json`
- `schemas/schema_backcompat_check.schema.json`
- `schemas/key_manifest.schema.json`
- `schemas/keyring.schema.json`
- `schemas/external_kms_config.schema.json`
- `schemas/key_access_audit.schema.json`
- `schemas/key_lifecycle_audit.schema.json`
- `schemas/audit_seal.schema.json`
- `schemas/query_workflow_benchmark.schema.json`
- `schemas/read_adapter_benchmark.schema.json`
- `schemas/sse_export_benchmark.schema.json`
- `schemas/record_recovery_benchmark.schema.json`
- `schemas/pipeline_benchmark.schema.json`
- `schemas/pjc_benchmark.schema.json`
- `schemas/live_sse_benchmark.schema.json`
- `schemas/audit_bundle_benchmark.schema.json`
- `schemas/platform_health_benchmark.schema.json`
- `schemas/derived_views_benchmark.schema.json`

Use `scripts/validate_json_contract.py` for local JSON/JSONL contract checks. The integrated pipeline runs it for export policy config, optional auto-service record-recovery authz config, optional keyring config, optional external KMS config, SSE export audit, optional record-recovery service audit when its path is supplied, optional record-recovery service health output when the service path is used, bridge `job_meta.json`, bridge audit, PJC audit, key access audit, public report, `mainline_contract_check.json`, policy audit, audit chain output, audit seal output, optional audit archive index output, and the read-only `platform_health/v1` report. The stage-owned audits now also carry `duration_ms` for SSE export, recovery service, bridge, PJC, and policy release, and the local contract smoke validates that those timings propagate into the derived `pipeline_observability/v1` output. It also validates the derived `catalog_lineage/v1` output against `schemas/catalog_lineage.schema.json`, runs `scripts/check_schema_backcompat.py` against the frozen sidecar/public-report/audit plus benchmark/report/runtime-log/config schema baseline, and that baseline now also includes the stable main-pipeline audit/policy contracts for SSE export, bridge metadata/audit, PJC audit, policy audit, record-recovery service audit, key access/lifecycle audit, `mainline_contract_check/v1`, the append-only archive contracts `audit_archive_anchor/v1` plus `audit_bundle_verification/v1`, and the encrypted record-store header. It validates `query_workflow_benchmark/v1` output from `scripts/benchmark_query_workflow.py`, `read_adapter_benchmark/v1` output from `scripts/benchmark_read_adapters.py`, `sse_export_benchmark/v1` output from `scripts/benchmark_sse_export.py`, `record_recovery_benchmark/v1` output from `scripts/benchmark_record_recovery.py`, `audit_bundle_benchmark/v1` output from `scripts/benchmark_audit_bundle.py`, `platform_health_benchmark/v1` output from `scripts/benchmark_platform_health.py`, and `derived_views_benchmark/v1` output from `scripts/benchmark_derived_views.py`, and now also semantically checks that those synthetic benchmark reports still retain their expected mode sets and outcome invariants rather than only matching schema shape. That includes query-workflow dry-run mode coverage, metadata/audit read-adapter coverage including metadata job/jobs `mainline_contract_summary` retention plus jobs-list `mainline_contract_summary_counts`, SSE export output-row/candidate-count/worker-boundary/throughput/RSS coverage, record-recovery transport/operation coverage, audit-bundle verify/restore flags plus embedded mainline-contract summaries, append-only archive anchor-log and anchor-signature invariants for archive-backed audit-bundle modes, platform-health component coverage with CLI-only fallback in restricted environments, the existing stage coverage plus derived `handoff_cleanup` events and default path-redaction checks, `record_recovery_service_log/v1` runtime logs captured from both Unix-socket and HTTP recovery-service lifecycle runs plus the `record_recovery_boundary_check/v1` output, and encrypted-store plus recovery-client checks routed through `services.record_recovery` rather than the legacy `sse/toolkit` shim.
The same contract smoke now also validates the new `platform_health_api_*.schema.json` envelopes against both direct HTTP responses and `platform_api_client.py platform-health`, and it exercises `platform_api_client.py` directly for metadata health/job/jobs reads, audit health/audit-chain/catalog-lineage reads, the catalog `--include-paths` branch, and the query `--execute` disabled path instead of only permissions/public-report/observability paths. Those query/metadata/audit/platform-health API smoke assertions now live in `scripts/check_platform_api_smoke_reports.py` instead of large inline Python blocks inside `scripts/check_json_contracts.sh`, and the shared platform-health check now accepts retained handoff compatibility mode alongside cleaned/removed status. The request/response materialization side of that smoke path is also now split out: `scripts/build_query_workflow_request_fixtures.py` writes the default and retained-handoff query request fixtures, while `scripts/materialize_platform_api_smoke_reports.py` captures the direct HTTP response payloads for query/metadata/audit/platform-health adapters. Runtime smoke config/build actions are also pulled out now: `scripts/build_runtime_contract_smoke_configs.py` writes the external-KMS plus Unix-socket/HTTP record-recovery service configs, and `scripts/record_recovery_contract_smoke_helpers.py` owns the synthetic encrypted-store build plus HTTP recover/export helper actions and validations. A new shared `scripts/runtime_service_helpers.py` now owns local available-port allocation, TCP readiness checks, JSON `/healthz` polling, and `started_pid` field extraction, and `scripts/check_json_contracts.sh`, `scripts/run_sse_bridge_pipeline.sh`, `scripts/run_live_sse_bridge_demo.sh`, plus the query/read/platform-health/record-recovery/PJC benchmark wrappers now reuse it instead of carrying separate socket/health polling snippets. The same shell entrypoint now also delegates completed-run artifact semantics for `mainline_contract_check`, `audit_chain`, `pipeline_observability`, and `catalog_lineage` to `scripts/check_pipeline_artifact_smoke_reports.py`, and delegates audit-bundle verify/restore semantics, metadata CLI/entity rollup semantics, metadata TSV/CSV export checks, and repo-hygiene report validation to `scripts/check_contract_smoke_reports.py` rather than keeping those checks inline. At this point `scripts/check_json_contracts.sh` no longer embeds heredoc Python blocks for these contract-smoke paths, and its remaining local service orchestration now also goes through shared helpers rather than inline `python3 -c` port/health probes.

Use `scripts/validate_tabular_contract.py` for CSV/JSONL handoff contracts that are not JSON schema files. The integrated pipeline uses it for file-mode SSE bridge handoff CSVs and generated PJC server/client CSVs. The contract smoke suite includes negative fixtures for malformed bridge/PJC tabular inputs.

Run `bash scripts/check_json_contracts.sh` for the local contract smoke suite. Run `bash scripts/check_ci_smoke.sh` for the broader local/CI preflight, including Python compile checks for the service-owned `services/record_recovery/*.py` implementation plus the `sse/toolkit` compatibility shims, record-recovery boundary checks that prevent legacy shims from regaining implementation logic, shell syntax checks, bridge Rust checks when `cargo` is available, repository hygiene scan, dependency hygiene scan, and contract smoke. `.github/workflows/json-contracts.yml` installs the SSE Python dependencies, provisions Rust stable, and runs that unified CI smoke entrypoint.

Operational sidecar tools:

- `scripts/check_platform_health.py`: read-only health summary for recovery services, key agent, external KMS, completed pipeline runs, and metadata DBs, including embedded mainline-contract and handoff-cleanup checks for completed runs.
- `scripts/serve_platform_health_api.py`: read-only HTTP wrapper over `platform_health/v1`, aligned with the metadata/query/audit sidecar adapters.
- `scripts/verify_audit_bundle.py`: verifies `audit_chain.json` plus `audit_chain.seal.json`, including archive-index lookup, append-only archive-anchor verification, embedded mainline-contract summary checks, and optional restore.
- `scripts/check_record_recovery_boundary.py`: verifies that legacy `sse/toolkit` recovery files remain compatibility shims for `services.record_recovery`.
- `scripts/scan_repo_hygiene.py`: scans tracked first-party files for high-confidence secrets and tracked generated artifacts.
- `scripts/check_schema_backcompat.py`: checks frozen schema files against a committed backward-compatibility baseline and emits `schema_backcompat_check/v1`.
- `scripts/check_dependency_hygiene.py`: checks first-party Python/Cargo dependency manifests for basic reproducibility hygiene without network access.
- `scripts/check_bridge_rust.sh`: runs `cargo fmt --check` and `cargo test` with a temporary target directory.
- `scripts/runtime_service_helpers.py`: shared local-service helper for available-port allocation, TCP readiness checks, JSON `/healthz` polling, and JSON field extraction used by smoke/orchestration wrappers.
- `scripts/benchmark_smoke.py`: emits `smoke_benchmark/v1` timing reports for existing smoke-check entrypoints.
- `scripts/benchmark_query_workflow.py`: benchmarks CLI/HTTP/client dry-run query-workflow entrypoints and emits `query_workflow_benchmark/v1`.
- `scripts/benchmark_read_adapters.py`: benchmarks metadata job/jobs/entity and completed-run audit-chain/public-report/observability/catalog-lineage read adapters over a synthetic completed-run fixture and emits `read_adapter_benchmark/v1`.
- `scripts/benchmark_sse_export.py`: benchmarks encrypted-record-store SSE export over deterministic synthetic e-commerce order records and emits `sse_export_benchmark/v1`; `scripts/benchmark_smoke.py --target sse-export-scale --scale <n>` invokes the same path.
- `scripts/benchmark_record_recovery.py`: benchmarks standalone record-recovery health and recover operations over Unix-socket and HTTP transports and emits `record_recovery_benchmark/v1`; explicit large-candidate runs also report `service_pid` / `service_rss_kb`, and `--mode g2b_acceptance` records sequential/concurrent HTTP throughput, mTLS overhead, and `max_rows_per_request` safety-valve enforcement.
- `scripts/benchmark_pipeline.py`: benchmarks the integrated file-mode pipeline over default file cleanup, explicit retained file handoff with a recorded retention reason, and FIFO handoff modes, and now emits the per-role handoff cleanup summary directly in `pipeline_benchmark/v1` result rows.
- `scripts/benchmark_pjc.py`: benchmarks the standalone PJC runner over a prepared bridge fixture and emits `pjc_benchmark/v1`.
- `scripts/benchmark_live_sse_demo.py`: benchmarks the live SSE-backed wrapper over default file cleanup, explicit retained file handoff with a recorded retention reason, and FIFO handoff modes, and now emits the per-role handoff cleanup summary directly in `live_sse_benchmark/v1` result rows.
- `scripts/benchmark_audit_bundle.py`: benchmarks audit archive, direct verification, archive-index verification, and restore flows and emits `audit_bundle_benchmark/v1`.
- `scripts/benchmark_platform_health.py`: benchmarks read-only platform-health CLI, HTTP API, and client entrypoints over pipeline-run and metadata-db summaries and emits `platform_health_benchmark/v1`.
- `scripts/benchmark_derived_views.py`: benchmarks derived observability and catalog/lineage exporters and emits `derived_views_benchmark/v1`.
- `scripts/export_observability_events.py`: derives schema-validated `pipeline_observability/v1` stage telemetry from `audit_chain.json`.
- `scripts/export_catalog_lineage.py`: derives schema-validated `catalog_lineage/v1` metadata and lineage edges from `audit_chain.json` without storing sensitive plaintext.

See `docs/OPS_RUNBOOK.md` for usage.

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
- Threat model and leakage model: `docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md`
- E-commerce privacy platform scenario: `docs/ECOMMERCE_PRIVACY_PLATFORM_SCENARIO.md`
- Task split for the owner-held privacy core and interface governance: `docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md`
- Task split for control plane, identity, authorization, and key management: `docs/TASK_ENGINEER_A_CONTROL_PLANE_IDENTITY_ACCESS.md`
- Task split for query interface, catalog, workflow, observability, and product shell: `docs/TASK_ENGINEER_B_QUERY_CATALOG_WORKFLOW_OBSERVABILITY.md`
- Query entry / workflow wrapper plan: `docs/QUERY_INTERFACE_PLAN.md`
- Bridge CLI guide: `bridge/README.md`
- A-PSI legacy workflow: `a-psi/README.md`
- SSE usage: `sse/README.md`

## Current Status

Implemented and verified:

- `sse` controlled bridge export command with policy and audit
- SSE-backed candidate export with `--sse-keyword`
- encrypted record-store recovery with `create-encrypted-record-store`
- optional Unix-socket and HTTP record recovery service for encrypted-store materialization
- standalone record recovery deploy unit under `services/record_recovery/` plus launcher `scripts/run_record_recovery_service.py`
- service-owned Unix-socket/HTTP recovery adapters, request/audit handling, recovery-service authz, common payload/row helpers, recovery-service client, worker subprocess, and encrypted record-store handling under `services/record_recovery/`, with old `sse/toolkit/record_recovery_service*.py`, `record_recovery_authz.py`, `record_recovery_common.py`, `record_recovery_client.py`, `record_recovery_worker.py`, and `encrypted_record_store.py` paths kept as compatibility shims
- structured `record_recovery_service_log/v1` runtime logs for Unix-socket and HTTP recovery-service start/request/stop events
- caller-scoped tenant/dataset/service authorization in `sse_export_policy/v1`, reused by export, pipeline, and recovery-service paths
- optional legacy `record_recovery_service_policy/v1` compatibility config for narrower service-only checks
- recovery-service lifecycle hooks with pid/ready files plus standalone launcher `scripts/run_record_recovery_service.py`
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
- read-only observability and catalog/lineage sidecar exports from existing audit chains
- JSON and tabular contract smoke validation
- demo PJC run producing `intersection_size=2`, `intersection_sum=425`

Still needed after the current prototype:

- Continue hardening the record recovery service toward a separately deployed boundary with stronger authn, supervision, and non-local lifecycle control.
- Extend the current caller/tenant/dataset/service policy baseline into a fuller SQL-backed permission/control-plane model; the new SQLite metadata sidecar is only the first catalog/query step.
- Replace the current mock external KMS and env-backed secret refs with a real KMS/HSM or dedicated secret store.
- Finalize join-key normalization schemas and versioning policy.
- Add semantic schema checks for future optional bridge handoff formats.
- Extend the current benchmark coverage, deployment/ops packaging, and the new threat/leakage-model baseline toward production-style deployment controls.
- Extend the current threat model with deployment-specific controls once a real service/KMS boundary exists.
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
