# Code Review — Step 2: Bridge (Rust) Module

**Scope:** `bridge/src/main.rs`, `bridge/Cargo.toml`

---

## 1. Module Purpose

The bridge module is a Rust CLI that converts locally-exported bridge-ready records from the SSE export step into HMAC-tokenized PJC inputs (`server.csv` / `client.csv`). It is the security boundary between plaintext join keys and the tokenized form that A-PSI/PJC operates on.

Two subcommands exist:

| Subcommand | Purpose |
|---|---|
| `generate` | Processes a single-role input (server or client) and writes one CSV plus metadata |
| `prepare-job` | Processes both server and client inputs together, writing both CSVs and a combined `job_meta.json` |

---

## 2. Dependencies (`Cargo.toml`)

Minimal and appropriate:

| Crate | Purpose |
|---|---|
| `anyhow` | Error handling |
| `clap` (derive) | CLI argument parsing |
| `csv` | CSV reading/writing |
| `hmac` | HMAC-SHA256 token computation |
| `serde` / `serde_json` | JSON serialization |
| `sha2` | SHA-256 for file hashes in audit |

No network dependencies. The bridge is fully offline — it reads local files and writes local files.

---

## 3. Core Security Primitive: `join_token`

```rust
fn join_token(join_key: &str, token_scope: &str, token_secret: &str) -> Result<String> {
    let mut mac = HmacSha256::new_from_slice(token_secret.as_bytes())?;
    mac.update(join_key.as_bytes());
    mac.update(b"\n");       // separator prevents concatenation ambiguity
    mac.update(token_scope.as_bytes());
    let digest = mac.finalize().into_bytes();
    Ok(hex_encode(&digest))
}
```

Key properties:
- The `\n` separator between join_key and token_scope prevents input collisions (e.g. `"a" || "bc"` ≠ `"ab" || "c"`).
- All tokens in a job share the same secret and scope, so they are only comparable within that scope.
- The hex-encoded HMAC output is what goes into `server.csv` and `client.csv` — PJC never sees raw join keys.

---

## 4. Normalizers

| Normalizer | Implementation |
|---|---|
| `identity` | Trim whitespace only |
| `email` | Trim + lowercase |
| `phone` | Strip non-digits, replace `00` prefix with `+`, allow leading `+` |

All normalizers drop empty/blank join keys (returning `None`), so rows with missing join keys are silently skipped. This is the expected behavior but callers should be aware that row counts in bridge metadata may differ from SSE export counts when many blank keys exist.

The phone normalizer handles international `+XX` and `00XX` prefix forms but does not normalize country-code formats further. For production use, a proper E.164 normalization library would be more robust.

---

## 5. Deduplication

The default dedup policy is `one_per_user_keep_max_value`:

```rust
fn build_client_values(...) {
    // For each token: if token already exists, keep max(existing, new_value)
    match token_values.get_mut(&token) {
        Some(existing) => { if value > *existing { *existing = value; } }
        None => { token_values.insert(token, value); }
    }
}
```

For server tokens, a `BTreeSet` is used — natural deduplication. For client values, a `BTreeMap<token, max_value>` accumulates the highest value per token.

This is the only dedup policy implemented. The `dedup_policy` field is recorded in `job_meta.json` and bridge audit but not validated against other possible values.

---

## 6. Production Mode

`--production-mode` (or `BRIDGE_PRODUCTION_MODE=1`) activates a security gate:
- If production mode is enabled and `--token-secret` (CLI flag) is used, the bridge fails with an error.
- Production mode requires `--token-secret-env` (reads from environment variable) instead.

This prevents secrets from appearing in shell history or process lists during non-development use.

---

## 7. Audit Trail

Both `generate` and `prepare-job` always write a `bridge_audit/v1` JSONL record to the audit log, even on failure (a separate failure-audit path in `run_generate_with_failure_audit` / `run_prepare_job_with_failure_audit`).

Audit fields include:
- `job_id`, `correlation_id`
- `input_file`, `input_file_type` (file vs FIFO), `input_sha256`
- `server_csv_sha256`, `client_csv_sha256` (for `prepare-job`)
- `token_scheme`, `token_scope`, `token_key_version`
- `normalize_version`, `normalizer_schema_version` (= `"normalizer-schema/v1"`, code constant)
- `server_normalizer`, `client_normalizer`
- `dedup_policy`, `production_mode`, `token_secret_source`
- `duration_ms`, `decision` (allow/deny), `reason_code`

The `normalizer_schema_version` constant (`NORMALIZER_SCHEMA_VERSION = "normalizer-schema/v1"`) is embedded at compile time, distinct from the caller-supplied `normalize_version`. This allows `validate_bridge_job.py` to reject jobs from an unrecognized normalizer implementation.

---

## 8. FIFO Detection

The bridge checks `path_file_type_label` before SHA-256 hashing. If the input is a named pipe (FIFO), `input_file_type = "fifo"` is recorded in the audit and SHA-256 is set to null (cannot hash a FIFO without reading it twice). This is correct behavior for the FIFO handoff mode.

---

## 9. `job_meta.json` Schema (`bridge_job_meta/v1`)

For `prepare-job`, the metadata includes:

```json
{
  "schema": "bridge_job_meta/v1",
  "job_id": "...",
  "job_type": "bridge_prepared_csv",
  "generator": "bridge-rust-v0",
  "bridge": {
    "token_scheme": "bridge-hmac-sha256-v1",
    "token_scope": "...",
    "token_key_version": "1",
    "normalize_version": "1",
    "normalizer_schema_version": "normalizer-schema/v1",
    "dedup_policy": "one_per_user_keep_max_value",
    "server": { "join_key_column": "...", "normalizer": "email" },
    "client": { "join_key_column": "...", "value_column": "...", "value_mode": "raw_int", "normalizer": "email" }
  },
  "counts": { "server_input_rows": N, "client_input_rows": M, ... }
}
```

The schema is frozen and validated by `scripts/validate_bridge_job.py` before PJC runs.

---

## 10. Identified Gaps / Observations

| Item | Severity | Note |
|---|---|---|
| Phone normalizer doesn't enforce E.164 fully | Low | Current form is adequate for demo; production should use a proper library |
| `dedup_policy` field is a free string | Low | Parsed and recorded but not validated against known values in Rust code; validation is in Python (`validate_bridge_job.py`) |
| FIFO input cannot be SHA-256 hashed | Informational | Correct behavior; `input_sha256` is null for FIFOs, recorded in audit |
| `generate` subcommand emits single-role metadata | Informational | `prepare-job` is the canonical path for the integrated pipeline; `generate` supports split single-role runs |
| Bridge reads both CSV files fully into memory | Low | Acceptable for current scale; would need streaming for very large inputs |
| `seen_nonces` equivalent not needed in Rust | N/A | Rust bridge does not use AES-GCM |
| Token secret injected via env var in production | Good | Correct approach; secrets never appear in process arguments in production mode |

---

## 11. Summary

The Rust bridge module is small (single-file), well-scoped, and handles the critical HMAC tokenization step correctly. The join_token function is the core security primitive and is sound. Audit records are comprehensive and include SHA-256 hashes of all input/output files plus the job_meta.json. The production mode gate correctly prevents CLI-flag secret injection. The main remaining limitations are the basic phone normalizer and the fact that dedup_policy is not validated in Rust (only in the downstream Python validator).

