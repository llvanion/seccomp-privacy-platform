# Query Interface Plan

## 1. Goal

This document defines the first-stage query entrypoint around the frozen privacy pipeline.

The goal is not to invent a new execution engine. The goal is to provide a structured submission surface that still runs the existing:

```text
SSE export -> record recovery -> bridge -> PJC -> policy release
```

## 2. First-Stage Shape

The first-stage query entrypoint is:

```bash
python3 scripts/submit_query_workflow.py \
  --request-file <request.json> \
  --dry-run
```

Or execute the validated request:

```bash
python3 scripts/submit_query_workflow.py \
  --request-file <request.json> \
  --execute
```

This wrapper only translates a structured request into the existing `scripts/run_sse_bridge_pipeline.sh` CLI.

For local UI / SDK prototype work, there is also a thin HTTP wrapper over the same adapter:

```bash
export SECCOMP_QUERY_WORKFLOW_API_TOKEN=local-query-token
python3 scripts/serve_query_workflow_api.py \
  --bind-host 127.0.0.1 \
  --port 18091 \
  --auth-token-env SECCOMP_QUERY_WORKFLOW_API_TOKEN
```

For a thin SDK-style local client over that HTTP wrapper, use:

```bash
python3 scripts/platform_api_client.py query-submit \
  --request-file docs/examples/query_request.json
```

It does not:

1. query SSE directly
2. bypass export policy
3. read encrypted record stores directly
4. change bridge tokenization
5. change PJC input/output semantics
6. change release policy

## 3. Supported Query Type

Current supported `query_type`:

1. `cross_party_match`

This maps to the current SSE -> bridge -> PJC integrated pipeline and is the closest supported shape to:

1. advertiser/platform overlap
2. conversion matching
3. privacy-preserving intersection aggregate release

## 4. Request Format

Current request schema label:

```text
query_workflow_request/v1
```

Example:

```json
{
  "schema": "query_workflow_request/v1",
  "query_type": "cross_party_match",
  "server_source": "sse/examples/bridge_server_records.jsonl",
  "client_source": "sse/examples/bridge_client_records.jsonl",
  "server_join_key_field": "email",
  "client_join_key_field": "email",
  "client_value_field": "amount",
  "server_normalizer": "email",
  "client_normalizer": "email",
  "client_value_mode": "raw-int",
  "server_filters": ["campaign=demo"],
  "client_filters": ["campaign=demo"],
  "token_scope": "query-demo-scope",
  "token_secret_env": "BRIDGE_TOKEN_SECRET",
  "job_id": "query_demo_job",
  "out_base": "tmp/query_demo_job",
  "caller": "auto_demo",
  "tenant_id": "demo_tenant",
  "dataset_id": "bridge_demo_dataset",
  "k": 1,
  "n": 5,
  "sse_export_policy_config": "sse/config/export_policy.example.json",
  "deny_duplicate_query": true,
  "sse_export_handoff_mode": "fifo"
}
```

Relative paths are resolved relative to the request file directory, not the current shell directory.

For the HTTP API, there is no request file. In that transport, relative paths are resolved against:

1. the `X-Request-Base-Dir` header when present
2. the repository root when the header is omitted

The structural request contract is now frozen in [schemas/query_workflow_request.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_request.schema.json). Semantic rules that are awkward to express in the repo's lightweight validator, such as mutually-exclusive secret sources or KMS dependency checks, remain enforced in [scripts/submit_query_workflow.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/submit_query_workflow.py).

## 5. Secret Handling

The wrapper supports the same mutually-exclusive secret modes as the integrated pipeline:

1. `token_secret`
2. `token_secret_env`
3. `token_secret_key_id`
4. `token_secret_key_name`

The wrapper redacts raw `token_secret` in its submission manifest and in the echoed command preview.

For production-like usage, prefer:

1. `token_secret_env`
2. `token_secret_key_id` + `key_manifest`
3. `token_secret_key_name` + `keyring`
4. `token_secret_key_name` + `external_kms_config`

## 6. Output

The wrapper emits a submission manifest:

```text
query_workflow_submission/v1
```

The manifest includes:

1. request file path
2. query type
3. workflow target
4. dry-run vs execute mode
5. redacted command
6. redacted request summary
7. exit code when execution was attempted

This manifest is intentionally sidecar-only. It does not replace `audit_chain.json` or any frozen pipeline artifact.

The manifest structure is frozen in [schemas/query_workflow_submission.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_submission.schema.json).

## 7. HTTP API

Health:

```text
GET /healthz
```

Dry-run submit:

```text
POST /v1/query-workflows/dry-run
```

Optional execute submit:

```text
POST /v1/query-workflows/execute
```

Notes:

1. both POST endpoints accept the same `query_workflow_request/v1` JSON body as the CLI
2. non-health endpoints require `Authorization: Bearer ...` when `--auth-token-env` is set
3. `/v1/query-workflows/execute` is disabled by default and only enabled when the server starts with `--allow-execute`
4. the API returns a wrapper envelope plus the same redacted `query_workflow_submission/v1` manifest used by the CLI

The HTTP envelopes are now frozen in:

1. [schemas/query_workflow_api_health.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_api_health.schema.json)
2. [schemas/query_workflow_api_response.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_api_response.schema.json)
3. [schemas/query_workflow_status_api_response.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_status_api_response.schema.json)
4. [schemas/query_workflow_api_error.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_api_error.schema.json)

Current sidecar lifecycle artifacts:

1. [schemas/query_workflow_submission.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_submission.schema.json)
2. [schemas/query_workflow_receipt.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_receipt.schema.json)
3. [schemas/query_workflow_status.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_status.schema.json)

Current sidecar layout under `out_base`:

1. `query_workflow/submission_manifest.json`
2. `query_workflow/execution_receipts.jsonl`
3. `query_workflow/status.json`

Current read surface for the status sidecar:

```text
GET /v1/query-workflows/status?out_base=<absolute-path>[&job_id=<job-id>]
```

And through the thin local shell:

```bash
python3 scripts/platform_api_client.py query-status \
  --out-base /abs/path/to/out_base \
  --job-id <job-id>
```

The current `POST /dry-run` and `POST /execute` success envelopes now also include the latest sidecar `receipt`, `status`, and the resolved sidecar paths. This remains wrapper-side metadata; it does not replace `audit_chain.json` or `public_report.json`.

The current `GET /v1/query-workflows/status` envelope is now split onto its own top-level schema id, `query_workflow_status_api_response/v1`, instead of reusing the submit envelope schema.

## 8. Boundary Rules

This wrapper is allowed because it is:

1. adapter-only
2. backward compatible
3. built on the frozen pipeline CLI
4. not a new source of truth for pipeline semantics

This wrapper must not:

1. add new main-pipeline fields without change approval
2. reinterpret `caller`, `tenant_id`, `dataset_id`, `service_id`, `job_id`, or `correlation_id`
3. bypass `sse_export_policy`
4. expose high-sensitivity plaintext through the wrapper response

## 9. Future Extension

Possible later extensions:

1. request templates for merchant aggregate queries
2. request templates for internal fine-grained SSE export queries
3. Temporal-backed execution and retry wrapper
4. UI form / SDK client layered on the same request format
5. read/write control-plane APIs tied to metadata DB and authn/authz

Those later steps should still treat `submit_query_workflow.py` as an adapter layer unless the project owner explicitly approves a stronger interface contract.

The current contract is now protected in three layers:

1. markdown examples and boundary notes in this document
2. local JSON schemas under `schemas/query_workflow_*.schema.json`
3. `scripts/check_json_contracts.sh` smoke coverage for example request validation, CLI dry-run manifest validation, API health/response validation, and API error-envelope validation

The current local SDK shell is intentionally thin: [scripts/platform_api_client.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/platform_api_client.py) just wraps the metadata/query HTTP adapters and is covered by contract smoke for metadata reads plus query dry-run.

## 10. Remaining Implementation Blocks

From the current `dry-run + optional execute` adapter baseline to a platform-grade query entrypoint, this plan still needs `4` focused blocks on the query/workflow line.

### Block Q1: Execute Governance Contract

What is already true today:

1. `scripts/serve_query_workflow_api.py` keeps `/v1/query-workflows/execute` disabled by default.
2. `scripts/api_identity.py` already distinguishes submit vs execute roles and permission gates.
3. `scripts/submit_query_workflow.py` already enforces the first request-shape and secret-mode rules.

What still needs to be made explicit:

1. which request shapes are allowed for operator-triggered execute, not just for dry-run
2. which secret modes remain acceptable for production-like execute
3. which fields must always be identity-bound and never caller-overridden
4. which failure modes are validation failures vs execution failures

Expected write-back:

1. this document
2. `docs/TASK_ENGINEER_B_QUERY_CATALOG_WORKFLOW_OBSERVABILITY.md`
3. any new change request doc if a new stable field is required

### Block Q2: Execution Receipt And Status Contract

The current submission manifest is useful, but still too thin for an operator surface.

This block should define:

1. a stable started/completed/failed receipt shape around `query_workflow_submission/v1`
2. the default materialization path for those receipts
3. how a read-only status view finds the latest receipt for a `job_id` or `correlation_id`
4. how receipt/status stays sidecar-only and does not replace `audit_chain.json`

The key rule is:

1. query receipt/status may summarize execution lifecycle
2. query receipt/status must not become a second truth source for privacy semantics

### ~~Block Q3: Durable Submit/Status Wrapper~~ ✓

Implemented `2026-05-03` as engineer B `B5`.

Entry: `scripts/list_query_workflow_status.py`

The status sidecar (`query_workflow/status.json`) already provides per-run status from B2. B5 adds a durable multi-run listing layer: `list_query_workflow_status.py` recursively scans a directory tree for all `query_workflow/status.json` files and returns a compact summary list as `query_workflow_status_list/v1`.

Supported filters: `--state`, `--job-id`, `--limit`. Results are sorted by `last_updated_at_utc` descending so the most recent jobs appear first. Contract frozen in `schemas/query_workflow_status_list.schema.json` and covered by contract smoke (two paths: unfiltered + state=failed filter).

```bash
python3 scripts/list_query_workflow_status.py \
  --search-dir tmp \
  --state failed \
  --limit 20 \
  --out tmp/workflow_status_list_failed.json
```

### ~~Block Q4: Retry And Operator Lifecycle Rules~~ ✓

Implemented `2026-05-03` as engineer B `B6`.

Entry: `scripts/check_workflow_retry_eligibility.py`

Retry rules:

| `state` | `error_class` / `last_exit_code` | `recommended_action` | Rationale |
| ------- | -------------------------------- | -------------------- | --------- |
| `accepted` / `running` | — | `wait` | Not terminal; check status again later |
| `completed` | — | `none` | Succeeded; no retry needed |
| `rejected` | `validation_rejected` | `resubmit` | Fix request shape, then re-submit with same or new `job_id` |
| `rejected` | `authz_rejected` | `resubmit` | Fix identity/permissions, then re-submit |
| `failed` | `launch_failed` | `retry` | Transient environment error; same request + new `job_id` is safe |
| `failed` | `run_failed` or `exit_code≠0` | `resubmit` | Pipeline ran but failed; inspect artifacts before re-submitting |
| unknown terminal | — | `investigate` | Manual investigation required |

Duplicate-query guard uses `job_id`. When re-submitting after a `run_failed`, always choose a new `job_id` to avoid the guard rejecting the re-submitted request.

Contract frozen in `schemas/workflow_retry_eligibility.schema.json` and covered by two contract smoke paths (failed run + completed dry-run).

```bash
python3 scripts/check_workflow_retry_eligibility.py \
  --status-file tmp/my_job/query_workflow/status.json \
  --out tmp/my_job/retry_eligibility.json
```

## 11. Target Execute Governance Contract

This section is the recommended target contract for Block `Q1`. It describes how `--execute` should behave once the wrapper is treated as an operator-facing platform entrypoint rather than a local convenience adapter.

### 11.1 Entry Conditions

An execute request should only be accepted when all of the following are true:

1. the caller uses the same structural request shape as `dry-run`
2. the request still validates under `query_workflow_request/v1`
3. execute is explicitly enabled for the transport being used
4. the authenticated identity is allowed to submit and execute, not only to submit
5. the bound `caller`, `tenant_id`, `dataset_id`, and `record_recovery_service_id` stay within the authenticated identity scope

### 11.2 Current Allowed Query Shape

Until a broader query catalog is explicitly added, execute should stay limited to:

1. `query_type=cross_party_match`
2. the existing `scripts/run_sse_bridge_pipeline.sh` adapter target
3. the frozen SSE -> recovery -> bridge -> PJC -> release path

The execute path should still not:

1. define a new execution engine
2. add a second privacy-policy surface
3. bypass `sse_export_policy`
4. reinterpret mainline job or scope semantics

### 11.3 Field Binding Rules

The wrapper already has enough identity information to support a stricter contract than a raw pass-through CLI.

Target binding rules:

1. `caller` must always resolve to the authenticated identity and must not be caller-overridden
2. `tenant_id` must be identity-bound whenever the identity carries a tenant binding
3. `dataset_id` must either match the requested allowed dataset or be auto-bound when there is only one allowed dataset
4. `record_recovery_service_id` must either match the requested allowed service or be auto-bound when there is only one allowed service
5. `job_id` remains caller-supplied, but duplicate-query and replay protections still apply

### 11.4 Secret And Handoff Rules

For operator-grade execute, the wrapper should treat some request shapes as acceptable only for local development, not as the preferred long-term execution contract.

Recommended rules:

1. `token_secret` is acceptable for local development only; production-like execute should prefer `token_secret_env` or KMS-backed resolution
2. `unsafe_allow_no_sse_export_policy` should be treated as non-executable in the platform-facing path
3. retained file handoff should remain exceptional and must always carry `handoff_retention_reason`
4. FIFO handoff remains the preferred execute mode when the environment supports it
5. record-recovery execution modes should stay limited to the already supported wrapper modes and must not create a second recovery semantics surface

### 11.5 Failure Classification

The wrapper needs a stable operator-readable distinction between different failure classes.

Recommended lifecycle classes:

1. `validation_rejected`: request shape, secret-mode, or semantic validation failed before launch
2. `authz_rejected`: identity/role/permission/scope checks failed before launch
3. `launch_failed`: the wrapper could not start the underlying pipeline command
4. `run_failed`: the pipeline command started but exited non-zero
5. `completed`: the pipeline command exited zero and terminal sidecar artifacts can be inspected

Recommended transport mapping:

1. validation failures -> local error / HTTP `400`
2. authz failures -> local error / HTTP `403`
3. disabled execute endpoint -> local error / HTTP `403`
4. launch failures -> local error / HTTP `500`
5. run failures -> local error / HTTP `502` while preserving the redacted command and receipt context

Current repo baseline:

1. `query_workflow_api_error/v1` now emits `error_class` for `validation_rejected`, `authz_rejected`, `endpoint_disabled`, `not_found`, and `internal_error`
2. contract smoke now covers disabled execute, validation-rejected execute, identity authz-rejected execute, and `run_failed` execute with a persisted failed `status.json`
3. non-zero execute remains a `502` success envelope carrying the redacted manifest, latest failed receipt, and latest failed status

## 12. Target Receipt And Status Sidecar Contract

This section is the recommended target contract for Block `Q2`. It keeps receipt/status in the sidecar layer and explicitly out of the frozen main pipeline artifact set.

### 12.1 Contract Split

The current `query_workflow_submission/v1` manifest is still useful, but it should become only the first lifecycle artifact.

Recommended next-stage split:

1. `query_workflow_submission/v1`: immutable request/command manifest
2. `query_workflow_receipt/v1`: immutable lifecycle receipt for `accepted|started|completed|failed|rejected`
3. `query_workflow_status/v1`: latest read-optimized status summary for operators and shells

These labels are recommended targets for the next implementation block; they are not yet frozen runtime contracts in the current repo state.

### 12.2 Recommended Materialization Paths

For a run rooted at `out_base`, the wrapper should materialize its sidecar lifecycle files under a dedicated subdirectory rather than scattering them across the completed-run root.

Recommended layout:

1. `<out_base>/query_workflow/submission_manifest.json`
2. `<out_base>/query_workflow/execution_receipts.jsonl`
3. `<out_base>/query_workflow/status.json`

That layout keeps:

1. wrapper lifecycle state easy to find
2. audit/public-report/mainline artifacts separate from wrapper state
3. future read adapters able to join on one predictable subdirectory

### 12.3 Receipt Shape

Each immutable receipt should capture enough lifecycle context to explain what happened without becoming a second source of privacy truth.

Recommended receipt fields:

1. `receipt_id`
2. `schema`
3. `event`
4. `job_id`
5. `correlation_id` when known
6. `caller`
7. `tenant_id`
8. `dataset_id`
9. `mode`
10. `request_digest`
11. `submitted_at_utc`
12. `finished_at_utc` when terminal
13. `exit_code` when launch happened
14. `request_summary`
15. `redacted_command`
16. `artifacts` as path-redacted or existence-only pointers

Recommended `event` values:

1. `accepted`
2. `started`
3. `completed`
4. `failed`
5. `rejected`

### 12.4 Status Shape

The status document should be a compact summary over the latest known lifecycle state, not a replacement for the receipt stream.

Recommended status fields:

1. `schema`
2. `job_id`
3. `correlation_id`
4. `caller`
5. `tenant_id`
6. `dataset_id`
7. `workflow`
8. `state`
9. `terminal`
10. `last_updated_at_utc`
11. `latest_receipt_id`
12. `receipt_count`
13. `last_exit_code`
14. `artifact_summary`
15. `public_report_available`
16. `audit_chain_available`

Recommended `state` values:

1. `accepted`
2. `running`
3. `completed`
4. `failed`
5. `rejected`

### 12.5 Read Rules

The status sidecar should be readable without re-running the pipeline.

Recommended lookup order:

1. by explicit `out_base`
2. by `job_id` when the wrapper already knows the expected `out_base`
3. by `correlation_id` when a read adapter or metadata join can map it back to the wrapper sidecar

The read side should default to:

1. redacted command echo
2. artifact existence and digest hints
3. no plaintext payload disclosure
4. no raw secret material

## 13. Target Operator Lifecycle

For the next implementation stage, the expected operator flow should be:

1. run `dry-run` and review the bound request shape
2. confirm the request is still within identity scope and policy scope
3. execute only through an explicitly enabled transport
4. inspect the wrapper receipt/status sidecar first
5. inspect `audit_chain.json`, `public_report.json`, `pipeline_observability/v1`, and `platform_health/v1` only after the wrapper lifecycle state is known

This keeps the operator workflow ordered:

1. wrapper lifecycle first
2. run artifacts second
3. health/triage views third
