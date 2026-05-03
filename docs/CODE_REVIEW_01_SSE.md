# Code Review — Step 1: SSE Module

**Scope:** `sse/` directory and the `services/record_recovery/encrypted_record_store.py` implementation it delegates to.

---

## 1. Module Purpose

The `sse/` module is the encrypted storage and controlled-export layer of the platform. It owns:

- A pluggable Searchable Symmetric Encryption (SSE) service that encrypts a keyword-indexed database and allows a server to answer keyword-search queries without learning the plaintext.
- A controlled export command (`export-bridge-records`) that produces bridge-ready CSV/JSONL subsets under caller-scoped policy.
- An encrypted record-store facility (`create-encrypted-record-store`) for building a locally encrypted copy of sensitive records, plus matching candidate-row recovery.
- Two record-recovery service entry points (Unix socket and HTTP) that act as a long-lived boundary between the export step and the bridge pipeline.

---

## 2. Entry Point: `sse/run_client.py`

`run_client.py` is a thin `asyncclick` CLI dispatcher. Key observations:

- Uses `asyncio` via `anyio` backend for commands that need async SSE network calls (search, upload). Pure-sync commands like `export-bridge-records` are dispatched through sync helpers in `commands.py`.
- The `export-bridge-records` command merges options from an optional `--record-recovery-service-config` JSON before dispatching, which keeps the CLI interface clean while allowing all fields to come from a single config file.
- The `serve-record-recovery` and `serve-record-recovery-http` commands both accept a `--config` flag and merge resolved fields from `record_recovery_service_config/v1`, delegating actual service startup to `services/record_recovery/service.py` and `http_service.py`.
- `run_client.py` correctly enforces that `--unsafe-allow-no-policy` is incompatible with `--sse-keyword` (line 315), preventing ad-hoc policy bypass when using the SSE-backed export path.

---

## 3. Core Export Logic: `sse/frontend/client/commands.py`

### 3.1 `export_bridge_records`

The main non-SSE export path:

1. Loads and validates the export policy (`load_platform_policy`, `platform_policy_for_caller`).
2. If `policy_config` is empty and `unsafe_allow_no_policy` is not set, raises an error — policy is required by default.
3. Reads plaintext source records (JSONL or CSV) and applies `key=value` filters.
4. If `candidate_ids` are provided (injected by the SSE-backed code path), limits rows to those matching candidate IDs.
5. For server role: writes only the join-key column to the output CSV/JSONL.
6. For client role: writes the join-key column plus the value column.
7. Writes an `sse_bridge_export_audit/v1` JSONL record containing: caller, job_id, correlation_id, candidate source, output file hash, row count, record-store hash (if used), filter hashes, duration_ms, tenant_id, dataset_id.

### 3.2 `export_bridge_records_from_sse` (async)

The SSE-backed path:

1. Searches the SSE server for the given `sse_keyword` and returns a set of candidate identifiers.
2. Passes those IDs as `candidate_ids` to `export_bridge_records`, which then materializes only the matching rows.
3. If a record store path is provided, routes recovery through the service client (`request_record_recovery`) rather than reading plaintext directly.

### 3.3 Record Recovery Integration

The export command supports three recovery modes:

| Mode | How triggered | What happens |
|---|---|---|
| Worker subprocess | `--record-store-path` without socket/endpoint | `services.record_recovery.worker` subprocess; no secrets cross process boundary |
| Unix socket service | `--record-recovery-socket` | `services.record_recovery.client.request_record_recovery` over Unix socket |
| HTTP service | `--record-recovery-endpoint-url` | Same client, HTTP transport |

---

## 3.4 Scope Resolution and Policy Enforcement

Before any data is read, `commands.py` resolves the full scope and enforces all policy constraints:

```python
scope = resolve_platform_scope(
    caller_policy, caller=caller, tenant_id=tenant_id,
    dataset_id=dataset_id, service_id=record_recovery_service_id,
    require_record_recovery_service=bool(record_store_path and service_configured),
)
```

`_enforce_export_policy` then validates:
- Caller's `can_run_bridge` permission.
- `join_key_field` is in the caller's `allowed_join_key_fields` (if configured).
- `value_field` is in the caller's `allowed_value_fields` (if configured).
- All `filter_pairs` keys are in the caller's `allowed_filter_fields` (if configured).
- Any `required_filters` listed in the policy are present in the actual filter set.

This means a caller cannot use an unapproved join key, value field, or filter field — field-level access control is enforced at the export boundary, not just caller identity.

### 3.5 Recovery Boundary Selection

The export command selects the recovery boundary based on which transport options are provided:

```python
if record_recovery_socket:
    record_recovery_boundary = "service_socket"
elif record_recovery_endpoint_url:
    record_recovery_boundary = "service_http"
else:
    record_recovery_boundary = "worker_subprocess"
```

The `record_recovery_boundary` value is written into the SSE export audit record. The `check_mainline_contract.py` script reads this field to determine whether a recovery service boundary was used for each role, and validates cross-stage consistency accordingly.

### 3.6 Output Hash and Handoff Audit

After writing the output file, the export command computes a SHA-256 of the output and writes it into the SSE export audit record:
```json
{
  "output_sha256": "<sha256 of sse_exports/server.csv>",
  "output_file_type": "file" | "fifo",
  "output_path": "...",
  "duration_ms": N
}
```

For FIFO handoffs, `output_file_type = "fifo"` is recorded (the pipe cannot be hashed after the writer closes it, so the hash is taken at write time by the SSE export command before handing off to the bridge).

---

## 4. Encrypted Record Store: `services/record_recovery/encrypted_record_store.py`

### 4.1 Cryptographic Choices

| Parameter | Value | Rationale |
|---|---|---|
| KDF | PBKDF2HMAC-SHA256 | Standard OWASP 2023-recommended derivation |
| KDF iterations | 600,000 | Meets OWASP 2023 minimum |
| AEAD | AES-256-GCM | Standard authenticated encryption |
| Salt size | 16 bytes | Per-store random salt for KDF |
| Nonce size | 12 bytes (96-bit) | Standard for AES-GCM |
| Record ID tag | Keyed HMAC-SHA256 of record ID | Prevents raw record IDs from appearing in the store |
| Passphrase source | Environment variable only | Never accepted on the command line |

### 4.2 AES-GCM Nonce Uniqueness

The implementation maintains a `seen_nonces` set and raises a `RuntimeError` if an `os.urandom(12)` call produces a duplicate nonce (lines 64–67). This is a defensive assertion rather than a real control: the collision probability is negligible for stores < 2^32 records, but the guard is present.

### 4.3 Store Layout (JSONL)

```
Line 0: header JSON {"schema":"sse_encrypted_record_store/v1","kdf":"PBKDF2HMAC-SHA256","kdf_salt_b64":"...","kdf_iterations":600000,"aead":"AES-256-GCM","record_id_field":"..."}
Line 1+: {"record_id_tag":"<HMAC>","nonce_b64":"...","ciphertext_b64":"..."}
```

The header line is frozen in `config/schema_backcompat_baseline.json` and validated against `schemas/sse_encrypted_record_store.schema.json`.

### 4.4 Candidate Row Recovery

`iter_candidate_rows` re-derives the key from the passphrase and salt, recomputes each candidate's HMAC record-ID tag, scans the store linearly, decrypts matching lines with AES-GCM, and yields plaintext row dicts. This is a linear scan — acceptable for the current prototype scale.

---

## 5. SSE Scheme Implementations

Located in `sse/schemes/`:

- `CGKO06/SSE1`: Basic SSE scheme from Curtomola et al. (CCS 2006). Implements the inverted-index SSE construction.
- `ANSS16/Scheme3`: Adaptive SSE scheme from Asharov, Naor, Segev, Shahaf (CCS 2016).

These implement the underlying cryptographic SSE protocol. Per `CODEX_CONTEXT.md`, these should **not** be modified unless explicitly requested. The platform wraps them with controlled-access semantics rather than changing the crypto.

### 5.1 SSE1 Construction (`CGKO06/SSE1`)

The SSE1 construction builds an encrypted inverted index `A` (an array) plus a lookup table `T`:

- Each keyword `w` maps to a linked list of document IDs in `A`.
- Each node is encrypted under a per-keyword per-position key chain (`K_i,j`), so traversing the list requires the chain keys.
- `T[w]` stores the encrypted (first node address, chain start key) under `F(K2, w)` (a PRF).
- Search emits a token `F(K2, w)` allowing the server to look up `T[w]` and traverse the list without learning the keyword itself.

The array `A` uses a PRP (pseudorandom permutation) `psi` keyed with `K1` to map counter positions to array slots, preventing the server from distinguishing which entries belong to the same keyword.

**Note on scheme correctness:** The implementation directly follows the paper construction. Collisions in the array `A` can occur with probability `N / (2^param_k + s)` as noted in the code comment — this is within the paper's acceptable bounds.

### 5.2 Usage Boundary

The SSE schemes are used exclusively as a candidate-selection mechanism: the server returns a set of document IDs matching a keyword, which the export command uses to filter records. The schemes are not used for storing PII directly in the SSE server — actual records live in the encrypted record store with stronger per-record encryption (AES-256-GCM).

---

## 6. Policy System: `sse/toolkit/platform_policy.py`

The `sse_export_policy/v1` schema carries:

```json
{
  "callers": {
    "<caller_id>": {
      "tenant_id": "...",
      "allowed_dataset_ids": [...],
      "allowed_service_ids": [...],
      "can_use_record_recovery_service": true,
      "can_run_bridge": true,
      "can_run_pjc": true,
      "can_release": true,
      "platform_roles": [...],
      "access_profile": "..."
    }
  }
}
```

Key helpers:
- `load_platform_policy(path)` — loads and validates the policy JSON.
- `platform_policy_for_caller(policy, caller)` — returns caller-specific config or raises if caller not found/disabled.
- `resolve_platform_scope(policy, caller)` — resolves `tenant_id`, `dataset_id`, `service_id` from the policy for a given caller.

The same policy file is reused by the export command, the pipeline validation script, and the recovery service authz evaluator, ensuring consistent scope semantics across all three boundaries.

---

## 7. `platform_policy.py` — Scope Resolution Deep Dive

### 7.1 `resolve_platform_scope`

This is the most subtle helper in the policy layer. Given a caller policy, it resolves effective `tenant_id`, `dataset_id`, and `service_id` with the following rules:

**`tenant_id`:** If both the policy and the request carry a `tenant_id` and they disagree, an error is raised. Otherwise the union of the two values is used (policy wins if the request is empty).

**`dataset_id` (auto-deduction):**
```python
allowed_dataset_ids = platform_policy_string_set(caller_policy, "allowed_dataset_ids")
if requested_dataset_id:
    if allowed_dataset_ids and requested_dataset_id not in allowed_dataset_ids:
        raise PermissionError(...)     # explicit but not allowed
elif len(allowed_dataset_ids) == 1:
    effective_dataset_id = next(iter(allowed_dataset_ids))  # auto-fill
elif len(allowed_dataset_ids) > 1:
    raise PermissionError("... must specify dataset_id")   # ambiguous
```

If a caller has exactly one `allowed_dataset_id` and the request does not specify one, the single value is auto-deduced. If there are multiple allowed datasets and none is specified, the request is rejected. This prevents accidental cross-dataset operations while reducing configuration friction for single-dataset callers.

**`service_id`:** Same logic, but only auto-deduced when `require_record_recovery_service=True`. This prevents the service_id from being silently populated in contexts where no recovery service is needed.

### 7.2 `platform_policy_for_caller`

```python
if caller_policy.get("enabled", True) is False:
    raise PermissionError(f"caller {caller} is disabled")
```

`enabled` must be explicitly set to `False` to disable a caller. Any absent `enabled` field is treated as `True`. This matches the `authorize_record_recovery_request` behavior in `authz.py`, ensuring consistent semantics across both enforcement points.

---

## 8. `_append_export_audit` — Audit Record Construction

The SSE export audit record is the most information-rich audit output in the pipeline. Key decisions in `commands.py:_append_export_audit`:

### 8.1 Filter Value Hashing

```python
"filters": [
    {"field": field, "value_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()}
    for field, value in filters
]
```

Filter *keys* appear in plaintext (they are schema fields, not sensitive). Filter *values* are replaced with SHA-256 hashes. This satisfies the threat model requirement: the audit records enough information to detect filter changes across runs (different hash = different filter value) without exposing the raw campaign IDs, tenants, or other filter values to an auditor.

### 8.2 Dual Allow/Deny Paths

The audit is written in both the success path (decision=allow, with populated row counts and output SHA-256) and the exception handler (decision=deny, with null row counts and reason). The exception handler uses `locals()` checks to avoid `NameError` when the failure happens before certain variables are assigned:

```python
tenant_id=tenant_id if "tenant_id" in locals() else "",
```

This defensive pattern ensures that a policy failure early in the function still produces a useful deny record, capturing whatever scope fields were resolved before the error.

### 8.3 FIFO File Type Detection

```python
"output_file_type": _path_file_type(out_path),
```

`_path_file_type` returns `"fifo"` for named pipes and `"file"` for regular files. This is how the bridge audit, mainline contract check, and observability exporters know that the handoff was streamed rather than persisted — the `output_file_type=fifo` field in the SSE export audit is the canonical source for FIFO detection downstream.

---

## 9. `_run_record_recovery_worker` — Subprocess Row Limit Propagation

The worker subprocess launch propagates the caller's policy row limits into the subprocess CLI:

```python
min_rows = _optional_policy_int(caller_policy, "min_export_rows")
max_rows = _optional_policy_int(caller_policy, "max_export_rows")
if min_rows is not None:
    cmd.extend(["--min-output-rows", str(min_rows)])
if max_rows is not None:
    cmd.extend(["--max-output-rows", str(max_rows)])
```

The `candidate_ids` are sorted before being JSON-serialized into stdin:
```python
"candidate_ids": sorted(_stringify_record_id(item) for item in candidate_ids),
```

Sorting ensures the stdin payload is deterministic across runs for the same candidate set, which makes the worker's behavior reproducible (though the on-disk output order may differ if the record store was built with different record ordering).

The caller validates the worker result schema strictly:
```python
if result.get("schema") != "sse_record_recovery_result/v1":
    raise RuntimeError(...)
for key in ("input_rows", "output_rows", "output_sha256"):
    if key not in result:
        raise RuntimeError(...)
```

---

## 10. SSE-Backed Export Path (`export_bridge_records_from_sse`)

This async function is the entry point for the live SSE-backed mode. The flow is:

```
_search_sse_candidate_ids(sse_keyword, sid/sname, record_id_format)
  → SSE server search
  → convert result bytes to set of candidate IDs (using BytesConverter format)
  → call export_bridge_records(..., candidate_ids=<set>, candidate_source="sse_query")
```

`_search_sse_candidate_ids` awaits `service.handle_keyword_search` with `wait=True`, which blocks until the SSE server returns the full result. The result is then deserialized using `SSEResult.deserialize` and each identifier byte is converted to a string using the specified `record_id_format` (int/hex/raw/utf8).

The important detail: `unsafe_allow_no_policy` is hardcoded to `False` in this path, even though the caller could pass `--unsafe-allow-no-policy` to the non-SSE path. The SSE-backed path always requires a policy — this is enforced in the CLI dispatcher too, but having it hardcoded here provides defense in depth.

---

## 12. Identified Gaps / Observations

| Item | Severity | Note |
|---|---|---|
| Linear scan in `iter_candidate_rows` | Low | Acceptable for prototype/competition scale; would need an index for production |
| `seen_nonces` set grows unbounded | Low | Bounded by store size in `build_record_store`; not an issue in practice |
| No passphrase complexity validation | Low | Users can set a weak passphrase via env var; not enforced |
| Policy reload is synchronous and per-request | Low | Fine for current scale; caching would help under concurrency |
| `serve-record-recovery` (SSE CLI entrypoint) is now a compatibility shim | Informational | `scripts/run_record_recovery_service.py` is the preferred standalone launcher |
| `--unsafe-allow-no-policy` flag exists | Informational | Documented, audited, and explicitly required — acceptable for local development |

---

## 13. Summary

The SSE module is well-structured for a privacy-computing prototype. The cryptographic primitives are sound (PBKDF2+AES-GCM, keyed HMAC record-ID tags). The export boundary enforces policy by default. The encrypted record store correctly separates key derivation from record encryption and avoids putting the passphrase on the command line. The main remaining risk, acknowledged in project docs, is that the bridge-ready CSV handoff remains plaintext by default — the FIFO handoff mode and record-recovery service boundary reduce but do not eliminate this exposure.
