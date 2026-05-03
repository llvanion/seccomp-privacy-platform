# Code Review — Step 5: Pipeline Orchestration Scripts

**Scope:** `scripts/run_sse_bridge_pipeline.sh`, `scripts/build_audit_chain.py`, `scripts/seal_audit_artifact.py`, `scripts/check_mainline_contract.py`, `scripts/validate_pipeline_policy.py`, `scripts/export_observability_events.py`, `scripts/export_catalog_lineage.py`

---

## 1. Overview

The pipeline scripts are the cross-module orchestration layer. They:

1. Accept parameters for both server and client sides.
2. Drive SSE export → bridge tokenization → PJC → policy release.
3. Construct a correlated audit chain linking all stage audits.
4. Seal the audit chain with HMAC-SHA256 (or Ed25519).
5. Check cross-stage contract consistency (`mainline_contract_check/v1`).
6. Optionally archive the audit bundle for long-term retention.

---

## 2. `run_sse_bridge_pipeline.sh` — Main Pipeline Orchestrator

### 2.1 Configurable Entry Points

All external binaries are resolved via environment variable defaults, making each component swappable:

```bash
BRIDGE_BIN="${BRIDGE_BIN:-cargo run --}"      # or /path/to/bridge
SSE_PY="${SSE_PY:-$SSE_DIR/.venv/bin/python}"
```

This allows CI to swap `cargo run --` for a prebuilt binary and makes each step independently replaceable.

### 2.2 SSE Export Step

For each role (server, client), the orchestrator calls `run_client.py export-bridge-records` with:
- `--policy-config` (required)
- `--audit-log` pointing to `sse_exports/<role>_export_audit.jsonl`
- `--caller`, `--job-id`, `--tenant-id`, `--dataset-id`
- Optional `--sse-keyword`, `--record-store-path`, `--record-store-key-env`
- `--record-recovery-service-config` or socket/endpoint options (for encrypted store path)

The handoff mode is configurable:
- `file` (default): writes `sse_exports/server.csv` and `sse_exports/client.csv`.
- `fifo`: creates named pipes and streams data directly into the bridge, avoiding disk persistence of plaintext.

After the bridge ingests the handoff files (file mode), the orchestrator cleans them by default. The `--keep-sse-export-handoff-files` flag keeps them for debugging but records this as `retained` in `mainline_contract_check.json`.

### 2.3 Key Resolution

Three token-secret modes are supported:

| Mode | How |
|---|---|
| Direct env var | `--token-secret-env BRIDGE_TOKEN_SECRET` |
| Local keyring + key agent | `--token-secret-key-name + --keyring`; auto-starts `key_agent_service.py` |
| External HTTP KMS | `--token-secret-key-name + --external-kms-config`; auto-starts `external_kms_service.py` |

In all modes:
- `key_access_audit.jsonl` is written with the resolved key version.
- The secret is injected into a bridge-only environment variable — it is never passed as a CLI argument.

### 2.4 Record Recovery Service Management

When using encrypted record stores, the orchestrator manages the recovery service lifecycle:

- `auto` mode (default): auto-starts `run_record_recovery_service.py`, generates an auth token, writes effective `record_recovery_service_config.json`, runs the pipeline, and shuts down the service.
- `manual` mode: connects to a pre-started service.
- `subprocess` mode: uses the older worker-subprocess path.

The effective runtime config is materialized to `sse_exports/record_recovery_service_config.json` for auditability.

### 2.5 PJC Execution

The orchestrator runs `validate_bridge_job.py` before PJC. PJC is then run via `run_pjc.sh`, which launches both server and client processes on localhost. Results are written to `a_psi_run/attribution_result.json`.

### 2.6 Policy Release

`policy_release.py` is invoked with `--k` (threshold), `--n` (max queries per window), `--deny-duplicate-query`, and caller context. The public report is written to `a_psi_run/public_report.json`.

---

## 3. `build_audit_chain.py` — Cross-Stage Audit Correlated View

Builds `audit_chain.json` by loading stage-specific JSONL audit records, filtering by `job_id`/`correlation_id`, and assembling them into a single correlated view. Included stages:

- `sse_export_audit` (server and client)
- `record_recovery_service_audit` (optional, per role)
- `bridge_audit`
- `pjc_audit`
- `policy_audit`
- `key_access_audit` (optional)

The chain is a snapshot, not a living log. It provides a single artifact that correlates all stage decisions for one job.

---

## 4. `seal_audit_artifact.py` — Audit Chain Sealing

Writes `audit_chain.seal.json` containing:
- `audit_chain_sha256`: SHA-256 of the audit chain file.
- Optional `hmac_sha256`: HMAC-SHA256 signature over the SHA-256 digest (keyed by `--audit-seal-key-env`).
- Optional `ed25519_signature` + `public_key_fingerprint`: Ed25519 signature (requires `cryptography` package).

This allows external auditors to verify the audit chain has not been tampered with post-run, without requiring re-running the pipeline.

---

## 5. `check_mainline_contract.py` — Cross-Stage Consistency

Emits `mainline_contract_check/v1`, a cross-stage consistency report covering:

### 5.1 Handoff Cleanup

For each role: checks whether the SSE bridge handoff file was cleaned after ingestion, retained by flag, or is in FIFO mode (removed by design). Records `status`: `cleaned` | `retained` | `removed` | `missing`.

### 5.2 handoff_mode / handoff_exposure_assessment

Reports the handoff mode (`file` / `fifo`) and a risk assessment:
- `plaintext_exposure_risk`: `high` | `medium` | `low`
- Per-role `server_exposure` / `client_exposure`: detailed plaintext-at-rest assessment.

### 5.3 Service Audit Consistency

For each role that used a record recovery service, cross-checks:
- `job_id`, `correlation_id`, `caller`, `tenant_id`, `dataset_id`, `service_id`
- `record_recovery_boundary` value
- `candidate_count`, `record_store_sha256`, `filter_hashes`
- `transport`, `output_path`, `output_type`, `output_hash`
- `input_rows` / `output_rows`

If any field mismatches between the SSE export audit and the service audit record, a `service_audit_consistency` finding with severity `error` is added.

---

## 6. `export_observability_events.py` — Derived Stage Telemetry

Derives `pipeline_observability/v1` from `audit_chain.json` without changing main pipeline outputs. Includes:

- One event per stage with `duration_ms` (from embedded audit records).
- Derived `handoff_cleanup` events (from mainline contract).
- Derived `service_audit_consistency` events per role.

The observability output is schema-validated against `schemas/pipeline_observability.schema.json`.

---

## 7. `export_catalog_lineage.py` — Derived Catalog Metadata

Derives `catalog_lineage/v1` from `audit_chain.json`. Includes:
- Job/dataset/service metadata.
- Lineage edges between stages.
- Compact `mainline_contract_summary` (handoff mode, cleanup status, service audit consistency per role).
- Path redaction: sensitive file paths can be redacted via `--redact-paths` (default behavior).

---

## 8. `validate_pipeline_policy.py` — Cross-Stage Permission Check

This script runs before the SSE export step and checks that the caller has all the permissions required for the stages the pipeline will run:

```python
require_platform_permission(caller_policy, "can_run_bridge", caller)
require_platform_permission(caller_policy, "can_run_pjc", caller)
require_platform_permission(caller_policy, "can_release", caller)
```

It also resolves `tenant_id`, `dataset_id`, and `service_id` via `resolve_platform_scope` before any data is read, ensuring scope mismatches are caught before the expensive SSE export step runs.

**Relationship to export-time policy check:** The export command itself also checks policy at the SSE export step. The pipeline policy validator is an earlier, cheaper gate that runs before any data is touched. The export-time check is the authoritative enforcement point.

---

## 9. `archive_audit_bundle.py` + `verify_audit_bundle.py` — Append-Only Audit Archive

### 9.1 Archive Structure

```
archive_dir/
  audit_chain_index.jsonl    # indexed retention log (one entry per archived job)
  audit_chain_anchor.jsonl   # append-only chain log (for replay verification)
  <job_id>/
    audit_chain.json
    audit_chain.seal.json
```

### 9.2 Append-Only Anchor Chain

Each anchor record covers the previous entry in the chain:

```
entry_sha256[n] = SHA-256( entry_sha256[n-1] + "\n" + payload_sha256[n] )
```

where `payload_sha256[n] = SHA-256(canonical_json(anchor_record_without_hash_fields))`.

This forms a hash chain where tampering with any past record (or its position in the chain) invalidates all subsequent `entry_sha256` values. The chain is verified in `verify_audit_bundle.py` by replaying from the first entry.

Optional HMAC-SHA256 signing of each `entry_sha256`:
```python
def sign_anchor_entry(*, anchor_key_env, entry_sha256):
    return hmac_sha256_hex(os.environ[anchor_key_env], entry_sha256)
```

When an anchor key is provided, the verifier checks the HMAC on each entry before accepting it. This prevents an adversary who has write access to the anchor log file from constructing a valid replacement chain without the key.

### 9.3 `summarize_mainline_contract`

The archive module extracts a compact `mainline_contract_summary` from the embedded `mainline_contract_check` in the audit chain. This summary includes:
- `handoff_mode` (file/fifo)
- `handoff_exposure` (plaintext risk level per role)
- Per-role `service_audit_consistency` (ok/fail/not_applicable)

This summary propagates into the `audit_archive_index/v1` record so archive-index reviewers can see recovery-service consistency without reopening each archived audit chain.

### 9.4 Verify + Restore

`verify_audit_bundle.py`:
1. Loads the audit chain and seal.
2. Recomputes the audit chain SHA-256 and compares to the seal.
3. If archive-backed: loads the anchor log, replays the chain, and verifies the anchor entry for this job.
4. If HMAC key env is provided: verifies signatures on each anchor entry.
5. Optional `--restore-to <dir>`: copies the verified bundle to a new directory.

---

## 10. Gate Scripts

### 10.1 `check_malformed_input_gate.py` — Systematic Negative Testing

For each of 20+ (schema, reference_payload) pairs, the gate generates mutated variants:
- Remove each required field.
- Change each field to the wrong type.
- Add an unexpected property (tests `additionalProperties: false`).
- Violate `const` / `enum` constraints.
- Violate `minLength` / `minimum` constraints.

For every mutation, it asserts that `validate_json_contract.py` **rejects** the mutated payload. Any mutation that is accepted indicates the schema is too permissive. This gate tests the validators themselves, not just the data.

### 10.2 `check_pre_release_gate.py` — Unified Pre-Release Check

Runs each gate sub-check as a subprocess, collects exit codes and output schemas, and emits a consolidated `pre_release_gate/v1` JSON report. Gate sub-checks include:
- Schema backcompat check
- Repo hygiene scan
- Dependency hygiene scan
- Record recovery boundary check
- Malformed input gate
- Various benchmark contract validations

A single failing gate exits non-zero and marks the overall status `fail`.

### 10.3 `check_operator_readiness.py` — Operator Environment Audit

Maintains an authoritative `ENV_VAR_CATALOG` listing every `SECCOMP_*` environment variable used by the platform:
- `SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY` — HMAC key for audit anchor signing.
- `SECCOMP_AUDIT_QUERY_API_TOKEN`, `SECCOMP_METADATA_API_TOKEN`, etc. — API auth tokens.
- `SECCOMP_KEY_AGENT_AUTH_TOKEN` — key agent auth.
- `SECCOMP_EXTERNAL_KMS_TOKEN` / `SECCOMP_EXTERNAL_KMS_ADMIN_TOKEN` — KMS tokens.

The check reports which variables are set, which are missing, and which are "required for" a given component. This gives operators a single view of what needs to be provisioned before a deployment is live. The output is an `operator_readiness/v1` JSON report.

---

## 11. `check_platform_health.py` — Comprehensive Health Check

Read-only health aggregator that checks:
- Record recovery service endpoints (Unix socket and HTTP).
- Key agent socket.
- External KMS HTTP endpoint.
- Completed pipeline run artifact integrity (audit chain, seal, mainline contract, handoff cleanup state).
- Metadata DB sanity (table presence, migration version, row counts).

Each check emits a `{name, component, status, details, error}` record. The top-level summary counts `ok`, `warn`, and `error` checks and sets an overall `status`. The result is validated against `schemas/platform_health.schema.json`.

The HTTP wrapper (`serve_platform_health_api.py`) exposes the same report over HTTP without changing the underlying check logic.

---

## 12. `submit_query_workflow.py` — Query/Workflow Adapter with Semantic Validation

This script is a thin adapter that maps a JSON request into the existing pipeline CLI. Its semantic validation is more interesting than typical schema validation:

### 12.1 Secret Method Exclusivity
```python
secret_method_count = sum(
    1 for field in ("token_secret", "token_secret_env", "token_secret_key_id", "token_secret_key_name")
    if isinstance(payload.get(field), str) and payload.get(field)
)
if secret_method_count != 1:
    raise SystemExit("[ERROR] exactly one of ... is required")
```
Exactly one secret method is required — having zero or two is an error.

### 12.2 KMS Mutual Exclusivity
```python
if keyring and external_kms_config:
    raise SystemExit("[ERROR] use only one of keyring or external_kms_config")
```

### 12.3 Production Mode + CLI Secret
```python
if optional_bool(payload, "production_mode") and payload.get("token_secret"):
    raise SystemExit("[ERROR] production_mode forbids token_secret; use token_secret_env or KMS-backed resolution")
```
This enforces the same production-mode gate as the bridge CLI, at the workflow layer.

### 12.4 Handoff Retention Coherence
```python
if cleanup_handoff is False:
    if handoff_mode != "file":
        raise SystemExit("[ERROR] cleanup=false requires handoff_mode=file")
    if not handoff_retention_reason:
        raise SystemExit("[ERROR] handoff_retention_reason is required when cleanup=false")
elif handoff_retention_reason:
    raise SystemExit("[ERROR] handoff_retention_reason is only valid when cleanup=false")
```
If file cleanup is disabled, a reason must be provided. If cleanup is enabled, providing a reason is an error (avoids spurious retention reasons leaking into the mainline contract check).

### 12.5 Path Normalization
All fields in `PATH_FIELDS` are resolved relative to the request file's directory before being passed to the pipeline CLI, so relative paths in the request JSON work correctly regardless of the working directory.

---

## 13. `runtime_service_helpers.py` — Shared Orchestration Primitives

This module is used by `check_json_contracts.sh`, `run_sse_bridge_pipeline.sh`, `run_live_sse_bridge_demo.sh`, and the benchmark wrappers in place of inline port-probing shell snippets.

### 13.1 `available_port`

```python
def available_port(*, host="127.0.0.1") -> int:
    with socket.socket() as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])
```

Binds to port 0 (OS assigns a free port), extracts the port number, then immediately closes the socket. There is an inherent TOCTOU race — another process could bind the port between the check and the service startup. In practice this is negligible for local smoke testing but is worth noting for high-concurrency CI environments.

### 13.2 `wait_for_json_health`

```python
def wait_for_json_health(*, url, timeout_sec, ok_field="ok", ok_value=True):
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            payload = fetch_json(url, ...)
            if payload.get(ok_field) == ok_value:
                return payload
        except Exception:
            pass
        time.sleep(interval_sec)
    raise RuntimeError(...)
```

Uses `ProxyHandler({})` in the opener to disable HTTP proxy for all URLs — this ensures loopback health checks are not accidentally routed through a corporate proxy. This is the same proxy-bypass pattern used in the recovery service client.

### 13.3 `read_json_field`

```python
def read_json_field(*, field_path, json_file=None, default=None):
    # parses dotted field_path like "started_pid" or "health.ok"
```

Used by shell scripts to extract a field from a JSON file without inline `python3 -c` heredocs:
```bash
python3 scripts/runtime_service_helpers.py read-json-field \
  --field started_pid \
  --json-file "$RUNTIME_CONFIG_JSON"
```

`_walk_json_field` traverses dot-separated path components:
```python
for part in field_path.split("."):
    value = value[part]
```

This is a simple but effective alternative to `jq` for the cases in the smoke suite.

---

## 14. Contract Smoke Suite

`scripts/check_json_contracts.sh` is the local contract smoke suite. It:
- Validates all example JSON configs against their schemas.
- Runs a synthetic integrated pipeline end-to-end.
- Validates all output artifacts (audit, bridge metadata, PJC audit, policy audit, mainline contract, etc.).
- Runs both file-mode and FIFO-mode pipeline variants.
- Verifies the recovery service allow/deny paths.
- Validates benchmark fixture contracts.
- Validates metadata sidecar lifecycle outputs.

`scripts/check_ci_smoke.sh` adds:
- Python compile checks for `services/record_recovery/` and `sse/toolkit/` shims.
- Record recovery boundary checks (shims must not gain implementation ownership).
- Shell syntax checks.
- Bridge Rust preflight (`cargo fmt --check` + `cargo test`).
- Repository hygiene scan.
- Dependency hygiene scan.
- Contract smoke.

---

## 15. Identified Gaps / Observations

| Item | Severity | Note |
|---|---|---|
| BRIDGE_BIN default is `cargo run --` | Informational | Development only; CI should use a prebuilt binary |
| Audit chain is a snapshot at run time | Informational | If audit logs are modified post-run, the chain does not detect it (that's what the seal is for) |
| Ed25519 signing requires `cryptography` package | Informational | Gracefully fails if not installed; falls back to HMAC-only sealing |
| `check_mainline_contract.py` is full cross-stage check | Good | Per-role recovery service audit consistency checks are comprehensive |
| No end-to-end replay test for two-machine PJC | Low | Single-machine replay is in CI smoke; two-machine requires separate infra |

---

## 16. Summary

The pipeline orchestration layer is the most complex part of the codebase. It correctly separates concerns: each stage emits its own audit record, the orchestrator assembles the correlated audit chain, and the mainline contract check enforces cross-stage consistency. The handoff cleanup and exposure assessment features directly address the primary remaining security risk (plaintext bridge handoff). The contract smoke suite is comprehensive and forms the effective CI gate for the current prototype.
