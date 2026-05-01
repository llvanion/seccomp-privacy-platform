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
3. [schemas/query_workflow_api_error.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/query_workflow_api_error.schema.json)

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
