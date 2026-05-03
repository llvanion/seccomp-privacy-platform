# Code Review — Summary

This document consolidates the per-module code reviews into a platform-level assessment.

Individual module reviews:
1. [SSE Module](CODE_REVIEW_01_SSE.md)
2. [Bridge (Rust) Module](CODE_REVIEW_02_BRIDGE.md)
3. [A-PSI / PJC Module](CODE_REVIEW_03_APSI.md)
4. [Record Recovery Service](CODE_REVIEW_04_RECORD_RECOVERY.md)
5. [Pipeline Orchestration Scripts](CODE_REVIEW_05_SCRIPTS_PIPELINE.md)
6. [SQL Metadata Sidecar](CODE_REVIEW_06_SQL_SIDECAR.md)
7. [Schema and Contract System](CODE_REVIEW_07_SCHEMAS.md)
8. [Key Management](CODE_REVIEW_08_KEY_MANAGEMENT.md)
9. [Sidecar Exporters](CODE_REVIEW_09_SIDECAR_EXPORTERS.md)
10. [Security Tooling](CODE_REVIEW_10_SECURITY_TOOLING.md)
11. [Sidecar HTTP Adapters](CODE_REVIEW_11_HTTP_ADAPTERS.md)
12. [Replay Scripts and Benchmark Suite](CODE_REVIEW_12_REPLAY_AND_BENCHMARKS.md)

---

## 0. Threat Model Alignment

`docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md` formalizes the boundary contract. Cross-checking the code against it:

| Threat model assertion | Code status |
|---|---|
| Raw filter values must not appear in audit logs | ✅ Filter hashes only in `sse_bridge_export_audit/v1` |
| Raw candidate IDs must not cross into bridge | ✅ Worker IPC sends IDs on stdin; bridge receives only the output file |
| Raw token secret must not appear in audit logs | ✅ `key_access_audit/v1` logs env var name only, never the value |
| Bridge-ready plaintext rows reduce with FIFO mode | ✅ FIFO handoff verified in CI; `handoff_exposure_assessment` quantifies risk |
| Recovered plaintext rows must not appear in audit | ✅ Service audit records only row counts, hashes, and decision |
| Query-abuse: threshold `k` enforced | ✅ `policy_release.py:apply_threshold_policy` |
| Query-abuse: duplicate-query denial | ✅ `seen_query_signature` + canonical query signature |
| Audit storage: local append-only anchor chain | ✅ `archive_audit_bundle.py` implements the chain; `verify_audit_bundle.py` replays it |
| Production secret handling enforced | ✅ Bridge `--production-mode` rejects `--token-secret`; query workflow validates this |

**Residual risks acknowledged in threat model but not yet mitigated in code:**
1. Bridge-ready plaintext in file-mode handoff (documented, partially mitigated by FIFO + cleanup-by-default)
2. Secret refs still env-backed (mock KMS only; real Vault/HSM is Engineer A backlog)
3. Audit anchor log not yet externally anchored or off-host
4. Duplicate-query denial does not cover near-duplicate / differencing attacks

---

## 1. What Works Well

### Privacy Pipeline Correctness

The end-to-end pipeline (`SSE export → recovery → bridge → PJC → policy release`) is functionally correct and verified by three independent replay paths: file-mode, FIFO-mode, and live-SSE-mode — all producing `intersection_size=2`, `intersection_sum=425`. The core cryptographic primitives are sound:

- AES-256-GCM with PBKDF2-SHA256 (600k iterations) for encrypted record stores.
- HMAC-SHA256 with scoped join tokens (domain separation via `\n` separator and token_scope).
- HMAC-SHA256 with request signing (request_id + timestamp + op binding).
- Constant-time signature comparison everywhere it matters.

### Contract Governance

The schema backward-compatibility system is a mature engineering decision for a prototype at this scale. Every frozen schema carries a `$id` version string, every stable property is listed in the baseline, and `check_schema_backcompat.py` runs in CI. The `normalizer_schema_version` governance (code constant in Rust, validated in Python before PJC) correctly prevents jobs from unknown normalizer implementations from running.

### Audit Trail

The audit chain is comprehensive. Every stage (SSE export, recovery service, bridge, PJC, policy release, key access) emits a structured JSONL record with `duration_ms`, `decision`, `reason_code`, `correlation_id`, and SHA-256 hashes of input/output artifacts. The `check_mainline_contract.py` cross-stage consistency check validates that the same `job_id`, `caller`, `tenant_id`, `dataset_id`, `service_id`, and cryptographic hashes flow correctly across the entire chain.

### Security Boundary Separation

The module separation correctly maps to security boundaries:

| Boundary | Current form | Quality |
|---|---|---|
| Encrypted store ↔ bridge | Recovery service (Unix socket / HTTP) | Good for prototype |
| Join key ↔ PJC | HMAC token in Rust bridge | Correct |
| PJC result ↔ release | Policy release threshold + audit | Correct |
| Policy config ↔ pipeline | Caller-scoped `sse_export_policy/v1` | Good |
| Token secret ↔ bridge | Env var injection only in production mode | Correct |

### Operator Tooling

The platform has unusually complete operator tooling for a prototype: platform health checks, archive/verify/restore, benchmark suite across 9 dimensions, `check_malformed_input_gate`, `check_pre_release_gate`, `check_operator_readiness`, systemd unit generation, and a structured OPS runbook. These are well above what a typical competition prototype contains.

---

## 2. Risk Summary

### Open Risks (documented in project)

| Risk | Severity | Status |
|---|---|---|
| Bridge-ready CSV handoff is plaintext (file mode) | Medium | Mitigated by FIFO mode and cleanup-by-default; `handoff_exposure_assessment` in mainline contract tracks this |
| Token secret is env-backed, not real KMS/HSM | Medium | Mock KMS exists; real KMS path (Vault/cloud KMS) is planned (Engineer A backlog) |
| Policy is file-config based, not durable SQL control plane | Medium | SQL sidecar exists as read-only overlay; write-path control plane is in Engineer A backlog |
| Linear O(n) scans in rate limit / nonce checks | Low | Acceptable for prototype scale; needs indexing for high-volume production |
| Laplace DP noise uses `random.uniform` | Low | Not cryptographically random; low risk for current demo use |
| Missing timestamp → anti-replay check is opt-in | Low | Provided client always sends timestamp; only risk is custom clients |

### Security Tooling Gaps (cross-cutting)

| Tool | What it catches | What it misses |
|---|---|---|
| `scan_repo_hygiene.py` | Known secret format patterns (AWS, GH, OpenAI…), tracked build artifacts | High-entropy anonymous tokens, secrets in untracked files |
| `check_dependency_hygiene.py` | Unpinned Python requirements, Cargo version ranges | CVEs, yanked packages, hash/SBOM verification |
| `check_record_recovery_boundary.py` | Functions/classes in shim files, wrong import target | Import-level `__all__` manipulation |

### Code Quality Observations (not project-documented)

| Item | Module | Severity |
|---|---|---|
| Phone normalizer is basic (no full E.164 normalization) | Bridge | Low |
| `dedup_policy` is only validated in Python, not Rust | Bridge | Low |
| Import is not atomic (no rollback on partial failure) | SQL sidecar | Low |
| `random.uniform` for Laplace noise | A-PSI policy release | Low |
| No rate limit on `serve_metadata_api.py` | SQL sidecar HTTP | Low |
| `allowed_callers = []` in keyring means unrestricted access | Key management | Medium |
| Key agent auth is plain equality check, not HMAC-signed | Key management | Low |
| Keyring file written without temp-file+rename atomicity | Key management | Low |
| Worker subprocess stdin candidate set has no size limit | Record recovery | Low |
| Query workflow `SECRET_FIELDS` set declared but not redacted in `build_command` | Pipeline scripts | Low |
| Observability artifact IDs for FIFO-mode items include sequential index (not stable across re-runs) | Sidecar exporters | Low |
| Authz policy loaded at service startup; policy file changes require service restart | Record recovery | Low |
| Keyring transport auto-detection in `config.py` is implicit (no transport = infer from other fields) | Record recovery | Low |
| `allowed_callers = []` in authz means no per-caller restriction (only `allowed_callers` service-level list applies) | Record recovery authz | Low |
| `min_output_rows` enforcement can leak membership via zero-row vs non-zero-row distinction | Record recovery authz | Informational |
| Silently drops rows with empty join-key or value-field during row selection | Record recovery common | Low |
| `available_port` has TOCTOU race between port allocation and service bind | Runtime helpers | Low |
| HTTP adapter bearer-token comparison is plain equality, not constant-time | HTTP adapters | Low |
| Metadata API serializes all DB access with a global `threading.Lock` | HTTP adapters | Low |
| Filter values in SSE export audit are SHA-256 hashed (keys logged in plaintext) | SSE export audit | Informational |
| `enabled=False` must be explicitly set; absent `enabled` is always `True` | SSE policy + authz | Informational |
| `dataset_id` and `service_id` auto-deduced from policy when caller has exactly one allowed value | SSE policy | Good: reduces config friction |
| External KMS client writes audit on both success and failure; key agent does not | Key management | Low: key agent audit comes from server side |
| `plan_policy_file` uses SHA-256 of file as `policy_id`; path changes without content change get `noop` | SQL registry | Low: correct semantics but could confuse |
| Replay scripts use inline `python3 -c` for JSON extraction (not `runtime_service_helpers.py`) | Replay scripts | Low |
| `benchmark_pipeline.py` verifies embedded mainline contract matches sidecar file bit-for-bit | Benchmarks | Good: catches audit-chain embedding bugs |

---

## 3. Module Completion Assessment

| Module | Completion | Notes |
|---|---|---|
| SSE (core crypto) | Complete | Do not modify scheme implementations |
| SSE (export policy / audit) | Complete | Frozen schema, verified |
| Bridge (Rust) | Complete | All normalization, tokenization, audit fields present |
| A-PSI / PJC governance | Complete | Threshold, rate limit, dup-query, auth, DP all implemented |
| Record recovery service | Complete | Unix socket + HTTP, HMAC signing, timestamp anti-replay, systemd hardening |
| Pipeline orchestration | Complete | File + FIFO handoff, 3 key modes, mainline contract check |
| SQL sidecar | 4/5 blocks complete | Import, query, API, registry write; Postgres migration path and importer repair remain |
| Schema system | Complete | 66 schemas, backcompat baseline, CI-validated |
| Key management | Prototype | Local keyring + mock KMS exist; real Vault/cloud KMS is Engineer A backlog |
| IAM / identity | Prototype | File-backed policy exists; unified identity mapping is Engineer A backlog |

---

## 4. Recommended Next Steps

Ordered by impact on moving from "prototype" to "platform baseline":

1. **Engineer A Block 1–3 (Identity mapping + Vault/KMS):** Replace mock KMS and file-backed policy with real Vault/cloud KMS and unified identity. This is the highest-leverage remaining gap. The key management code is clean and ready to accept new `secret_ref.kind` values without restructuring.

2. **Engineer B Block 1–2 (Execute permissions + durable workflow):** Wire `--allow-execute` through proper authz rather than a simple server flag; add durable workflow state persistence. The query workflow adapter's semantic validation is already production-quality — the main gap is the authz integration.

3. **Engineer 2 Block 5 (PostgreSQL migration path):** Validate the full sidecar query layer against PostgreSQL, not just DDL portability. The `ARTIFACT_TYPE_STAGE_MAP` and query patterns should migrate cleanly.

4. **Fix `allowed_callers = []` semantics:** Document or change the "empty list = unrestricted" behavior in `keyring_lib.py` to avoid misconfiguration.

5. **Fix Laplace noise RNG:** Replace `random.uniform` with `secrets.SystemRandom()` in `policy_release.py` before any production DP use.

6. **Recovery service payload signing:** Extend request signatures to cover the full payload hash, not just `request_id:timestamp:op`.

7. **Keyring write atomicity:** Use temp-file+rename in `save_json_object` to prevent partial writes during a power failure or kill signal mid-rotation.

---

## 5. SSE Crypto Architecture Summary

The SSE layer uses two academic constructions:
- **CGKO06/SSE1** (Curtomola et al., CCS 2006): encrypted inverted index with linked-list traversal, used for keyword search returning candidate document IDs.
- **ANSS16/Scheme3** (Asharov et al., CCS 2016): adaptive SSE with stronger forward/backward privacy.

**Key design boundary:** The SSE schemes are used only for candidate selection (returning matching document IDs). Actual records are stored in the encrypted record store (AES-256-GCM), not in the SSE index. This separation means compromising the SSE server reveals only which candidate IDs match a keyword, not the record content — record recovery requires a separately guarded passphrase.

---

## 6. Files Created by This Review

All documents are in `docs/` with sequential prefixes:

| File | Module reviewed | Round |
|---|---|---|
| `CODE_REVIEW_01_SSE.md` | `sse/` — SSE schemes, export policy, field-level access control, handoff audit | 1 + 2 |
| `CODE_REVIEW_02_BRIDGE.md` | `bridge/` — Rust tokenization, normalizers, audit | 1 |
| `CODE_REVIEW_03_APSI.md` | `a-psi/` — PJC governance, policy release, bridge validation | 1 |
| `CODE_REVIEW_04_RECORD_RECOVERY.md` | `services/record_recovery/` — service, authz, crypto, systemd, worker IPC | 1 + 2 |
| `CODE_REVIEW_05_SCRIPTS_PIPELINE.md` | `scripts/` — orchestrator, audit chain, anchor chain, gates, query workflow | 1 + 2 |
| `CODE_REVIEW_06_SQL_SIDECAR.md` | `migrations/`, `scripts/metadata_*.py` — DB schema, import stage mapping, replay | 1 + 2 |
| `CODE_REVIEW_07_SCHEMAS.md` | `schemas/`, backcompat baseline, contract validators | 1 |
| `CODE_REVIEW_08_KEY_MANAGEMENT.md` | `scripts/keyring_lib.py`, key agent, external KMS mock | 2 |
| `CODE_REVIEW_09_SIDECAR_EXPORTERS.md` | `export_observability_events.py`, `export_catalog_lineage.py` | 3 |
| `CODE_REVIEW_10_SECURITY_TOOLING.md` | `scan_repo_hygiene.py`, `check_dependency_hygiene.py`, `check_record_recovery_boundary.py` | 3 |
| `CODE_REVIEW_11_HTTP_ADAPTERS.md` | `serve_metadata_api.py`, `serve_audit_query_api.py`, `serve_query_workflow_api.py`, `serve_platform_health_api.py` | 4 |
| `CODE_REVIEW_12_REPLAY_AND_BENCHMARKS.md` | `verify_pipeline_replay.sh`, `verify_fifo_handoff_replay.sh`, `benchmark_pipeline.py`, benchmark architecture | 5 |
| `CODE_REVIEW_SUMMARY.md` | This document | 1–5 |
