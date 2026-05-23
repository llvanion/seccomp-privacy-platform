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

> **2026-05-17 update:** Many of the items below are now closed in code across
> rounds 1-7 of Engineer A's control-plane hardening. See
> [`CONTROL_PLANE_HARDENING_LOG.md`](CONTROL_PLANE_HARDENING_LOG.md) for the
> audit-ID index and the permanent regression-smoke list. The tables below
> retain the original audit row with a new **Resolution** column.

### Open Risks (documented in project)

| Risk | Severity | Resolution |
|---|---|---|
| Bridge-ready CSV handoff is plaintext (file mode) | Medium | Still open in code; FIFO mode + cleanup-by-default + `handoff_exposure_assessment` are the documented mitigations. Owner-track (S1). |
| Token secret is env-backed, not real KMS/HSM | Medium | Repo-side Vault HTTP / AWS KMS adapters complete (`scripts/keyring_lib.py`). Live Vault drill is operator-side (A.2). |
| Policy is file-config based, not durable SQL control plane | Medium | SQL sidecar exists as read-only overlay; write-path control plane is in Engineer 2 backlog. Still partial. |
| Linear O(n) scans in rate limit / nonce checks | Low | Acceptable for prototype scale; needs indexing for high-volume production. Open. |
| Laplace DP noise uses `random.uniform` | Low | **Closed** — `policy_postprocess_buckets.py` now uses `secrets.SystemRandom`. `--require-dp` fail-closed flag added on both stages (A.11). |
| Missing timestamp → anti-replay check is opt-in | Low | Open by design — provided client always sends timestamp; only risk is custom clients. |

### Security Tooling Gaps (cross-cutting)

| Tool | What it catches | What it misses |
|---|---|---|
| `scan_repo_hygiene.py` | Known secret format patterns (AWS, GH, OpenAI…), tracked build artifacts | High-entropy anonymous tokens, secrets in untracked files |
| `check_dependency_hygiene.py` | Unpinned Python requirements, Cargo version ranges | CVEs, yanked packages, hash/SBOM verification |
| `check_record_recovery_boundary.py` | Functions/classes in shim files, wrong import target | Import-level `__all__` manipulation |

### Code Quality Observations (not project-documented)

| Item | Module | Severity | Resolution |
|---|---|---|---|
| Phone normalizer is basic (no full E.164 normalization) | Bridge | Low | **Closed (A.18)** — `normalize_phone` now rejects bare `+`, > 15 digits, and `+0…`; `NORMALIZER_SCHEMA_VERSION` unchanged so existing tokens are stable. 5 new `cargo test` cases. |
| `dedup_policy` is only validated in Python, not Rust | Bridge | Low | Open (Owner-track). |
| Import is not atomic (no rollback on partial failure) | SQL sidecar | Low | **Closed (A.16)** — `import_run_metadata.py:import_runs` wraps the loop in explicit try/`conn.rollback()`; `main()` adds defence-in-depth rollback. |
| `random.uniform` for Laplace noise | A-PSI policy release | Low | **Closed** — now uses `secrets.SystemRandom`; `--require-dp` fail-closed flag (A.11) for full enforcement. |
| No rate limit on `serve_metadata_api.py` | SQL sidecar HTTP | Low | **Closed (A.15)** — per-caller token bucket via `--rate-limit-per-caller` / `--rate-limit-burst`; `/healthz` bypassed; HTTP 429 past burst. Regression smoke `scripts/check_metadata_api_rate_limit_smoke.py`. |
| `allowed_callers = []` in keyring means unrestricted access | Key management | Medium | **Closed (A.4)** — empty list now hard-rejected at access time; field-absent retains legacy "unrestricted" semantics. |
| Key agent auth is plain equality check, not HMAC-signed | Key management | Low | **Closed (A.6)** — `hmac.compare_digest` everywhere bearer/key-agent tokens are compared. |
| Keyring file written without temp-file+rename atomicity | Key management | Low | **Closed (A.7)** — `save_json_object` uses `tempfile.mkstemp` + 0600 + `fsync` + `os.replace` in the same directory. |
| Worker subprocess stdin candidate set has no size limit | Record recovery | Low | **Closed (A.9)** — `--max-candidate-ids` / `RECORD_RECOVERY_MAX_CANDIDATE_IDS` caps inbound list length before the set is materialized; HTTP service also accepts `--max-request-body-bytes` (returns 413). |
| Query workflow `SECRET_FIELDS` set declared but not redacted in `build_command` | Pipeline scripts | Low | Open (Engineer B track). |
| Observability artifact IDs for FIFO-mode items include sequential index (not stable across re-runs) | Sidecar exporters | Low | Open (Engineer B track). |
| Authz policy loaded at service startup; policy file changes require service restart | Record recovery | Low | **Closed (A.8)** — SIGHUP triggers in-process reload via `RecordRecoveryServiceState.reload_authz_policy`; bad JSON keeps old policy and emits structured `authz_reload_status=error` log. |
| Keyring transport auto-detection in `config.py` is implicit (no transport = infer from other fields) | Record recovery | Low | Open (Owner-track). |
| `allowed_callers = []` in authz means no per-caller restriction (only `allowed_callers` service-level list applies) | Record recovery authz | Low | Kept as designed — service-level intent differs from keyring; the keyring trap (A.4) was the real bug. |
| `min_output_rows` enforcement can leak membership via zero-row vs non-zero-row distinction | Record recovery authz | Informational | **Closed (A.10)** — `--suppress-min-rows-side-channel` (env: `RECORD_RECOVERY_SUPPRESS_MIN_ROWS_SIDE_CHANNEL=1`) collapses below-min into a uniform zero-row success; audit still records `min_rows_suppressed=true` for the operator. Regression smoke `scripts/check_min_rows_side_channel_smoke.py`. |
| Silently drops rows with empty join-key or value-field during row selection | Record recovery common | Low | Open (Owner-track). |
| `available_port` has TOCTOU race between port allocation and service bind | Runtime helpers | Low | **Closed (A.17)** — probe now sets `SO_REUSEADDR`; new `reserve_available_port()` returns `(port, sock)` for in-process callers that want a true reservation. |
| HTTP adapter bearer-token comparison is plain equality, not constant-time | HTTP adapters | Low | **Closed (A.3)** — `hmac.compare_digest` in `scripts/api_identity.py`, `serve_identity_proxy.py`, and `services/record_recovery/http_service.py`. Covers metadata, audit, query, platform-health, operator-dashboard via the shared `resolve_request_identity`. |
| Metadata API serializes all DB access with a global `threading.Lock` | HTTP adapters | Low | Open (performance, not security). |
| Filter values in SSE export audit are SHA-256 hashed (keys logged in plaintext) | SSE export audit | Informational | Kept as designed. |
| `enabled=False` must be explicitly set; absent `enabled` is always `True` | SSE policy + authz | Informational | Kept as designed. |
| `dataset_id` and `service_id` auto-deduced from policy when caller has exactly one allowed value | SSE policy | Good: reduces config friction | — |
| External KMS client writes audit on both success and failure; key agent does not | Key management | Low: key agent audit comes from server side | — |
| `plan_policy_file` uses SHA-256 of file as `policy_id`; path changes without content change get `noop` | SQL registry | Low: correct semantics but could confuse | — |
| Replay scripts use inline `python3 -c` for JSON extraction (not `runtime_service_helpers.py`) | Replay scripts | Low | Open (cleanup). |
| `benchmark_pipeline.py` verifies embedded mainline contract matches sidecar file bit-for-bit | Benchmarks | Good: catches audit-chain embedding bugs | — |

### New controls introduced 2026-05-17 (not in original review)

| Control | Where | Audit ID |
|---|---|---|
| `--mtls-enrollment-only-mode` on the operator dashboard restricts the HTTP surface to `/healthz` + `POST /v1/pjc-mtls/enroll` during PJC Party A enrollment | `scripts/serve_operator_dashboard.py`, `a-psi/moduleA_psi/scripts/serve_pjc_mtls_enrollment_party_a.sh` | A.13 |
| `POST /v1/bucketed-scale-test/run` is async-by-default (202 + `GET /v1/bucketed-scale-test/{job_id}`); legacy `?sync=1` available | `scripts/serve_operator_dashboard.py` | A.14 |
| `policy_release.py --public-report-redact-operator-fields` strips operator-only keys from `public_report.json` and routes the full set into `operator_release_report/v1`; same flag on `policy_postprocess_buckets.py` skips `debug.per_bucket_results` | `a-psi/moduleA_psi/scripts/policy_release.py`, `policy_postprocess_buckets.py` | S5 (field-redaction half) |
| Recovery-service request signature now covers a canonical body SHA-256 (`common.py:_canonical_request_message`); tampered bodies fail HMAC verify | `services/record_recovery/common.py` | A.5 (verified existing implementation) |
| PJC mTLS pairing token TTL + max-enrollments + audit JSONL + auto-shutdown after exhaustion / idle | `scripts/serve_operator_dashboard.py`, `a-psi/moduleA_psi/scripts/serve_pjc_mtls_enrollment_party_a.sh` | PJC_MTLS Risks #2, #3 |
| Party B enrollment requires `EXPECTED_CA_FINGERPRINT` (server-returned and locally re-computed) | `a-psi/moduleA_psi/scripts/enroll_pjc_mtls_party_b.sh` | PJC_MTLS Risk #1 |

### Permanent regression smokes added

| Smoke | Covers | Wired into |
|---|---|---|
| `scripts/check_bucket_dp_smoke.py` | bucket k-suppression + DP metadata + `--require-dp` fail-closed + S5 field redaction | `check_json_contracts.sh`, `check_ci_smoke.sh` |
| `scripts/check_enrollment_only_mode_smoke.py` | A.13 enrollment-only HTTP surface | same |
| `scripts/check_bucketed_scale_test_async_smoke.py` | A.14 async 202 + polling + list + legacy sync | same |
| `scripts/check_metadata_api_rate_limit_smoke.py` | A.15 per-caller HTTP 429 past burst | same |
| `scripts/check_min_rows_side_channel_smoke.py` | A.10 helper contracts + dataclass field default | same |

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

> **2026-05-17 update:** Items 4-7 below have all been completed across
> Rounds 1-7. See [`CONTROL_PLANE_HARDENING_LOG.md`](CONTROL_PLANE_HARDENING_LOG.md)
> for the audit-ID index. The remaining items are operator-side or other-role
> work.

1. **Engineer A Block 1–3 (Identity mapping + Vault/KMS):** Replace mock KMS and file-backed policy with real Vault/cloud KMS and unified identity. Repo-side adapters complete (`vault_http`, `aws_kms`, OIDC claim mapper, issuer registry); **live Vault reachability drill is still operator-side (A.2)**.

2. **Engineer B Block 1–2 (Execute permissions + durable workflow):** Wire `--allow-execute` through proper authz rather than a simple server flag; add durable workflow state persistence. The query workflow adapter's semantic validation is already production-quality — the main gap is the authz integration.

3. **Engineer 2 Block 5 (PostgreSQL migration path):** Validate the full sidecar query layer against PostgreSQL, not just DDL portability. The `ARTIFACT_TYPE_STAGE_MAP` and query patterns should migrate cleanly.

4. ~~**Fix `allowed_callers = []` semantics**~~ — **Done (A.4)**. Empty list now hard-rejected at access time; legacy field-absent path preserved.

5. ~~**Fix Laplace noise RNG**~~ — **Done**. `policy_postprocess_buckets.py` uses `secrets.SystemRandom`; `--require-dp` fail-closed flag added on both stages (A.11).

6. ~~**Recovery service payload signing**~~ — **Verified existing implementation (A.5)**. `services/record_recovery/common.py:_canonical_request_message` already binds `request_payload_sha256` into the HMAC input; tamper test confirms a modified body fails verify.

7. ~~**Keyring write atomicity**~~ — **Done (A.7)**. `save_json_object` uses `tempfile.mkstemp` + 0600 + `fsync` + `os.replace` in the same directory.

8. **External audit anchor `--execute` against live AWS S3 Object Lock and Sigstore Rekor** (A.12) — repo paths verified in-process only, needs live credentials.

9. **VPS-to-laptop 1k bucketed mTLS evidence** (PJC_MTLS Risk #4) — wrappers complete, needs a real two-machine run.

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
