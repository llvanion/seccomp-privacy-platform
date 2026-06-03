# Control-Plane Hardening Log

Status date: 2026-05-17
Owner: Engineer A (control plane / KMS / identity)

This document records the cross-cutting code and script hardenings that Engineer
A applied to close the open items surfaced during the 2026-05-17 doc audit
(`docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md`, `docs/CODE_REVIEW_SUMMARY.md`, and
`docs/PJC_MTLS_OPEN_RISKS.md`).

Each item is keyed by the **A.N** label used in the original audit. Items not
on Engineer A's role (Owner / Engineer B) are noted at the bottom for
hand-off. Items that need live external infrastructure (real Vault, real S3
Object Lock, real Sigstore Rekor) are flagged as operator-side and stay open.

## Round 1 — PJC mTLS surface and bootstrap

These three were the highest-leverage items for a real cross-machine PJC run.

| # | Risk | Fix | Files |
| --- | --- | --- | --- |
| — | PJC mTLS Risk #1: MitM at enrollment | `EXPECTED_CA_FINGERPRINT` is now required in `enroll_pjc_mtls_party_b.sh`. The script verifies the server-returned fingerprint *and* recomputes the fingerprint locally; either mismatch aborts before `client.crt` is written. `ALLOW_UNVERIFIED_CA=1` is the only opt-out and logs a warning. | `a-psi/moduleA_psi/scripts/enroll_pjc_mtls_party_b.sh`, `serve_pjc_mtls_enrollment_party_a.sh` |
| — | PJC mTLS Risk #2: pairing token reuse | Token now has TTL (`PJC_MTLS_PAIRING_TOKEN_TTL_SECONDS`, default 600 s) and use cap (`PJC_MTLS_MAX_ENROLLMENTS`, default 1). Token + meta sidecar are deleted on exhaustion or TTL expiry. Every accept/reject is appended to `tmp/pjc_mtls_shared/enrollment_audit.jsonl` with UTC ts, remote address, CSR public-key SHA-256, issued cert fingerprint, and reason code on rejection. | `scripts/serve_operator_dashboard.py`, `a-psi/moduleA_psi/scripts/serve_pjc_mtls_enrollment_party_a.sh` |
| — | PJC mTLS Risk #3: enrollment endpoint over-exposed | `_enrollment_shutdown_hook` registered in `main()`; fires on exhaustion, TTL expiry, or `PJC_MTLS_ENROLLMENT_IDLE_TIMEOUT_SECONDS`. | `scripts/serve_operator_dashboard.py` |

## Round 2 — Cross-cutting Engineer A items

These five are independent of the PJC mTLS flow and apply to the control-plane
HTTP/RPC surface, KMS, and metadata stack.

| # | Risk | Fix | Files |
| --- | --- | --- | --- |
| A.4 | `allowed_callers=[]` in keyring meant "everyone" | Empty list is now hard-rejected at access time. Field-absent retains legacy "unrestricted" semantics. | `scripts/keyring_lib.py` |
| A.7 | Keyring write was non-atomic | `save_json_object` now writes through `tempfile.mkstemp` in the same directory with `chmod 0600`, `fsync`, and `os.replace`. Kill -9 mid-rotation can no longer corrupt the keyring. | `scripts/keyring_lib.py` |
| A.3 / A.6 | Bearer / key-agent tokens compared with `==` | All comparisons now go through `hmac.compare_digest`. Covers every HTTP adapter (metadata, audit, query, platform-health, operator dashboard) via the shared `resolve_request_identity` plus key agent + identity proxy. | `scripts/api_identity.py`, `scripts/key_agent_service.py`, `scripts/serve_identity_proxy.py`, `services/record_recovery/http_service.py` |
| A.8 | Recovery-service authz needed a restart to pick up policy changes | `SIGHUP` triggers in-process reload via `RecordRecoveryServiceState.reload_authz_policy`. The unix-socket server now reads policy through `service_state` so the swap is observed by in-flight handlers. Malformed policy is rejected and the previous policy is retained. | `services/record_recovery/runtime.py`, `service.py`, `http_service.py` |
| A.5 | Recovery-service request signature didn't bind the body | Already implemented in `services/record_recovery/common.py:76` — verified via tamper test rather than re-implemented. | `services/record_recovery/common.py` (verification only) |

## Round 3 — DoS hardening, atomicity, port hygiene

| # | Risk | Fix | Files |
| --- | --- | --- | --- |
| A.9 | Worker stdin / HTTP body could pin RSS with an unbounded `candidate_ids` | New `--max-candidate-ids` (env: `RECORD_RECOVERY_MAX_CANDIDATE_IDS`) caps inbound `candidate_ids` length before the set is materialized. HTTP service additionally accepts `--max-request-body-bytes` (env: `RECORD_RECOVERY_MAX_BODY_BYTES`) and returns `413` before reading an oversize `Content-Length`. | `services/record_recovery/common.py`, `runtime.py`, `service.py`, `http_service.py`, `worker.py` |
| A.15 | No per-caller rate limit on the metadata API | Per-caller token-bucket rate limit added with `--rate-limit-per-caller` / `--rate-limit-burst` (env-overridable). `/healthz` is unaffected; auth-required endpoints check after identity resolution and return `HTTP 429` on overflow. | `scripts/serve_metadata_api.py` |
| A.16 | Sidecar import non-atomic on Python exception | `import_runs` is now wrapped in an explicit try/except that calls `conn.rollback()` on any exception before re-raising, and `main()` adds a defence-in-depth rollback between `import_runs` returning and `conn.close()`. | `scripts/import_run_metadata.py` |
| A.17 | `available_port()` had a TOCTOU between probe and bind | Probe socket now sets `SO_REUSEADDR` so the most common TIME_WAIT collision can't block the real bind. New `reserve_available_port()` returns `(port, sock)` for in-process callers that want a true reservation. Docstring spells out residual risk. | `scripts/runtime_service_helpers.py` |

## Round 4 — PJC mTLS surface (residual) + DP enforcement + async UI

| # | Risk | Fix | Files |
| --- | --- | --- | --- |
| A.13 | Enrollment script exposed the *whole* operator dashboard for the few seconds enrollment was open | New `--mtls-enrollment-only-mode` on `serve_operator_dashboard.py`. In this mode every HTTP path except `GET /healthz` and `POST /v1/pjc-mtls/enroll` returns `HTTP 404 enrollment_only_mode` with the allowed paths in the body. `serve_pjc_mtls_enrollment_party_a.sh` passes the flag by default; opt out with `DASHBOARD_FULL_SURFACE=1`. | `scripts/serve_operator_dashboard.py`, `a-psi/moduleA_psi/scripts/serve_pjc_mtls_enrollment_party_a.sh` |
| A.14 | `POST /v1/bucketed-scale-test/run` was synchronous (pinned an HTTP worker for the whole PJC run) | Endpoint is now async-by-default. It validates inputs synchronously then spawns a `daemon=True` worker thread and returns `HTTP 202` with a per-run `job_id`. State is exposed via `GET /v1/bucketed-scale-test/{job_id}` and `GET /v1/bucketed-scale-test`. Retention cap of 50 jobs evicts oldest terminal job. Legacy blocking path still reachable via `{"sync": true}` or `?sync=1`. | `scripts/serve_operator_dashboard.py` |
| A.11 | DP could be silently skipped on a release | `--require-dp` fail-closed flag added to both `policy_release.py` and `policy_postprocess_buckets.py`. `run_bucketed_scale_test.sh` now passes it by default so the bundled scale test cannot accidentally release un-DP'd bucket sums. | `a-psi/moduleA_psi/scripts/policy_release.py`, `policy_postprocess_buckets.py`, `run_bucketed_scale_test.sh` |

## Round 5 — Permanent test coverage + side-channel + normalizer

This round converts the per-invocation verifications from earlier rounds into
**permanent regression coverage**, plus closes the two cross-cutting items I
had previously flagged as "other-role" and re-scoped as fixable in repo.

| # | Risk | Fix | Files |
| --- | --- | --- | --- |
| PJC_MTLS task 6 | "Add contract smoke coverage for bucket suppression and DP metadata" was the last item we had no permanent guard for. | `scripts/check_bucket_dp_smoke.py` builds a two-bucket attribution fixture (one above k, one below), runs `policy_release.py` and `policy_postprocess_buckets.py`, and now asserts release-safe bucket output: below-k bucket labels are omitted from `bucket_public_report/v1`, exact bucket sizes and `dp_noise` are redacted from the public bucket report, `operator_bucket_report/v1` retains the full raw/noise evidence, and both CLIs fail closed when `--require-dp` lacks knobs. The public/operator bucket schemas are validated in `scripts/check_json_contracts.sh`. | `scripts/check_bucket_dp_smoke.py`, `schemas/bucket_public_report.schema.json`, `schemas/operator_bucket_report.schema.json`, `scripts/check_json_contracts.sh`, `scripts/check_ci_smoke.sh` |
| A.10 | Recovery service distinguished "no candidates matched" from "matched but below `min_output_rows`" via a deny path — a 1-bit membership probe | New optional server flag `--suppress-min-rows-side-channel` (env: `RECORD_RECOVERY_SUPPRESS_MIN_ROWS_SIDE_CHANNEL=1`) on both `service.py` and `http_service.py`. When on, below-min collapses into a uniform zero-row success: the response shape, output file, and decision/reason are identical to a genuine zero-match. The audit log still records the distinction (`min_rows_suppressed=true`, `min_rows_effective=<n>`) so the operator sees it, but the caller cannot. Default off for backward compat. | `services/record_recovery/common.py`, `runtime.py`, `service.py`, `http_service.py` |
| A.18 | Phone normalizer accepted strings outside the valid E.164 range; tokens for malformed inputs would never match between parties yet were still generated | `normalize_phone()` now (a) keeps the existing behaviour for already-valid E.164 inputs (existing tokens unchanged), (b) rejects pure `+`, (c) rejects > 15 digits, (d) rejects `+0...` (E.164 country codes do not start with 0). 5 new `cargo test` cases cover the rejections plus the `00`-prefix rewrite path that wasn't directly tested. `NORMALIZER_SCHEMA_VERSION` is **unchanged** because every now-rejected input was already an unmatchable junk token, so legitimate cross-party joins are unaffected. | `bridge/src/main.rs` |

## Round 6 — Permanent regression smokes for Rounds 3-4

Round 5 added permanent coverage for A.11 and PJC_MTLS task 6. Round 6 closes
the rest: A.10, A.13, A.14, A.15 each now have a dedicated contract-smoke
script wired into both `scripts/check_json_contracts.sh` and the
`scripts/check_ci_smoke.sh` `py_compile` list. Future refactors that
regress these surfaces fail CI rather than silently flipping.

| # | Smoke | What it asserts |
| --- | --- | --- |
| A.13 | `scripts/check_enrollment_only_mode_smoke.py` | Spins up `serve_operator_dashboard.py --mtls-enrollment-only-mode` on a loopback port. Asserts `GET /healthz` returns 200, five other paths (`/`, `/v1/dashboard`, `/v1/runs`, `POST /v1/runs/select`, `POST /v1/request/submit`) all return 404 with `error=enrollment_only_mode`, and `POST /v1/pjc-mtls/enroll` reaches the real handler (returns 403 `pairing_rejected` for a bad token). |
| A.14 | `scripts/check_bucketed_scale_test_async_smoke.py` | Patches `PJC_MTLS_SCRIPT_DIR` to a tempdir with a fast fake helper. Asserts `POST /v1/bucketed-scale-test/run` returns 202 with `state=running`, polling flips to `succeeded` within 8 s with `result.summary.matches_expected=true`, `GET /v1/bucketed-scale-test` lists the job, and the legacy `?sync=1` path returns 200 directly. |
| A.15 | `scripts/check_metadata_api_rate_limit_smoke.py` | Spins up `serve_metadata_api.py` with `--rate-limit-per-caller=1 --rate-limit-burst=2` against a fresh SQLite DB. Asserts `/healthz` is never rate-limited, the first 2 authed `/v1/jobs` requests succeed, and the very next one returns HTTP 429 with a rate-limit envelope. |
| A.10 | `scripts/check_min_rows_side_channel_smoke.py` | Pure-Python: asserts `enforce_row_limits` still raises on below-min direct call, `evaluate_min_rows_suppression` returns the right boolean across 5 cases, `RecordRecoveryServiceState` still carries the `suppress_min_rows_side_channel` field (default `False`, explicit `True` propagates through `build_service_state`), and the env-var coercion path works. Locks the toggle in even if no real recovery service is available in the smoke environment. |

## Round 7 — S5 public-report metadata redaction

Original S5 concern (from `docs/PRODUCTION_SECURITY_COMPLETION_PLAN.md`):
`public_report.json` carries raw row counts and per-bucket detail that an
ordinary caller should not see. Operator metrics belong in the operator
console / audit trail, not the public release.

| # | Risk | Fix | Files |
| --- | --- | --- | --- |
| S5 | `public_report.json` shipped `input_sizes`, `rate_limit_used/max`, `bridge`, `details`, and (via `policy_postprocess_buckets.py`) a `debug.per_bucket_results` block — direct frame-count and per-bucket leak to anyone with read access to the public release. | Two opt-in flags plus release-safe bucket split. `policy_release.py --public-report-redact-operator-fields` strips the five operator-only keys from `public_report.json` (sets `operator_fields_redacted=true`) and routes the full set into a sibling `operator_release_report/v1` document. `policy_postprocess_buckets.py` now writes release-safe `bucket_public_report/v1`: below-k bucket labels are omitted, exact bucket sizes are bucketized, and `dp_noise` is redacted so raw sums cannot be reconstructed. Full per-bucket raw/noise evidence is written to `operator_bucket_report/v1`. `run_bucketed_scale_test.sh` passes the redaction flags by default. | `a-psi/moduleA_psi/scripts/policy_release.py`, `policy_postprocess_buckets.py`, `schemas/bucket_public_report.schema.json`, `schemas/operator_bucket_report.schema.json`, `run_bucketed_scale_test.sh`, `scripts/check_bucket_dp_smoke.py` |

The existing `scripts/check_bucket_dp_smoke.py` now asserts two new
invariants in its second pass: the redacted public report carries none of
`input_sizes / rate_limit_used / rate_limit_max / bridge / details`, the
sibling `operator_report.json` carries them all under
`operator_release_report/v1`, and the bucket postprocess writes
`debug.bucket_results_redacted=true` instead of `debug.per_bucket_results`.

## Verification done in-process during the work session

Every Round 2-4 fix has at least one inline verification done before claiming
"done" — no Round-N fix was reported as complete without observed behavior.
Highlights (full transcripts in the chat history; not yet wired into permanent
contract smoke):

- **A.4**: empty `allowed_callers` rejected, absent field still accepted, named caller enforced.
- **A.7**: write produces mode `0o600` with no leftover temp file.
- **A.5**: legit signature verifies; tampered body fails verify.
- **A.8**: policy edit + reload swaps callers; bad JSON keeps the old policy.
- **A.9**: `parse_candidate_payload` rejects over-cap, accepts under-cap, unlimited still works at cap=0.
- **A.13**: live curl smoke — `/healthz` 200, `/`, `/v1/dashboard`, `/v1/runs`, `POST /v1/runs/select` all return 404 `enrollment_only_mode`; `POST /v1/pjc-mtls/enroll` reaches the handler and returns 403 `pairing_rejected` for a bad token.
- **A.14**: in-process patched bash helper — initial 202 returned `running`, polling returned `succeeded` within ~300 ms, list endpoint returned the job with the right state.
- **A.11**: `policy_release.py --require-dp` and `policy_postprocess_buckets.py --require-dp` both exit non-zero at argparse time with `missing/non-positive: --dp-epsilon, --dp-sensitivity` when knobs are absent.
- **A.10**: `enforce_row_limits` still raises on direct call (back-compat), and `evaluate_min_rows_suppression(rows=2, min=5)` returns True. `RecordRecoveryServiceState(suppress_min_rows_side_channel=True)` carries the toggle through `build_service_state`.
- **A.18**: `cargo test` in `bridge/` → 10 passed, 0 failed (5 new + 5 pre-existing). Tightening behaves identically on every previously-valid E.164 input.
- **PJC_MTLS task 6**: `python3 scripts/check_bucket_dp_smoke.py --out-dir tmp/bucket_dp_smoke` returns `status=ok`; below-k bucket labels are redacted from the public bucket report, public buckets omit exact size and `dp_noise`, and `operator_bucket_report/v1` carries the full raw/noise evidence needed to verify `released_sum == max(0, round(raw_sum + dp_noise))`.
- **A.13 smoke**: 5 blocked paths all return 404 `enrollment_only_mode`, `/healthz` returns 200, enroll handler reachable.
- **A.14 smoke**: async 202 with `state=running`, poll flips to `succeeded` in ~300 ms, list endpoint contains the job, `?sync=1` returns 200 directly.
- **A.15 smoke**: with `--rate-limit-burst=2`, exactly 2 `/v1/jobs` requests succeed and the next returns HTTP 429.
- **A.10 smoke**: pure-Python checks pass — `evaluate_min_rows_suppression` returns the right boolean for all 5 cases, `RecordRecoveryServiceState` field defaults to `False`, explicit `True` propagates.
- **S5**: redacted `public_report.json` strips all 5 operator-only keys; sibling `operator_report.json` carries them under `operator_release_report/v1`; bucket-postprocess writes `bucket_results_redacted=true` instead of `per_bucket_results`.

## Items left open

### Operator-side (need live infrastructure, not code)

| Audit ID | Item | Why open |
| --- | --- | --- |
| A.2 / B.1 | Live Vault / AWS KMS reachability drill | Repo-side scaffolding exists; needs an operator-controlled Vault endpoint to execute against. |
| A.12 / B.4 | `publish_external_audit_anchor.py --execute` against real S3 Object Lock and Sigstore Rekor | Needs AWS bucket with Object Lock enabled and/or Rekor signing keys; repo paths verified in-process only. |
| Risk #4 | VPS-to-laptop 1k bucketed mTLS evidence | Needs a real VPS and the matching `enrollment_audit.jsonl` line in the evidence bundle. |
| K3 | External penetration test | Vendor scope. |

### Other-role (still open; flagged for hand-off)

| Audit ID | Item | Role |
| --- | --- | --- |
| S5 (residual) | Small-shard auto-merge / padding (the field-redaction half of S5 is now closed in Round 7) | Owner / Engineer B |
| S8 | Commit-and-prove for PJC inputs; path toward malicious-secure PSI-SUM | Owner |

A.10 (record-recovery side channel) and A.18 (phone normalizer) were originally
flagged as Owner-role items; on closer inspection both turned out to be
in-repo, behaviour-preserving tightenings safe for Engineer A to land, so
they were closed in Round 5. Owner is welcome to override or extend. Same
story for the field-redaction part of S5 — closed in Round 7; the
small-shard merge/padding part is still Owner / Engineer B work.

### Engineer A continuation (still partial)

| Audit ID | Item | Notes |
| --- | --- | --- |
| Risk #6 / S3 | Lift `--require-dp` from per-CLI to a server-side mandatory gate; central epsilon/sensitivity presets per dataset/query; metadata-read-model integration of the budget ledger | The per-CLI flag closes the "accidental skip" failure mode but is not a *tenant-wide* enforcement. |
| Risk #5 SPA polling | Update the operator dashboard SPA to poll the new bucketed-scale-test endpoints | Engineer B owns the SPA. Backend is ready. |

## Audit ID → location index

For grep-ability when a follow-up references the same number:

- A.3 / A.6 — `scripts/api_identity.py:359`, `scripts/key_agent_service.py:117`, `scripts/serve_identity_proxy.py:123`
- A.4 — `scripts/keyring_lib.py:223`
- A.5 — `services/record_recovery/common.py:76`
- A.7 — `scripts/keyring_lib.py:36`
- A.8 — `services/record_recovery/runtime.py:53`
- A.9 — `services/record_recovery/common.py:259`
- A.10 — `services/record_recovery/common.py:evaluate_min_rows_suppression`; `service.py:suppress_quietly` branch
- A.11 — `a-psi/moduleA_psi/scripts/policy_release.py` near `--require-dp`; `policy_postprocess_buckets.py` near `--require-dp`
- A.13 — `scripts/serve_operator_dashboard.py` (`DashboardServer.mtls_enrollment_only_mode`)
- A.14 — `scripts/serve_operator_dashboard.py` (`_BUCKETED_SCALE_TEST_JOBS`)
- A.15 — `scripts/serve_metadata_api.py:_TokenBucket`
- A.16 — `scripts/import_run_metadata.py:import_runs`
- A.17 — `scripts/runtime_service_helpers.py:available_port`
- A.18 — `bridge/src/main.rs:normalize_phone`
- PJC_MTLS task 6 — `scripts/check_bucket_dp_smoke.py`
- A.10 regression smoke — `scripts/check_min_rows_side_channel_smoke.py`
- A.13 regression smoke — `scripts/check_enrollment_only_mode_smoke.py`
- A.14 regression smoke — `scripts/check_bucketed_scale_test_async_smoke.py`
- A.15 regression smoke — `scripts/check_metadata_api_rate_limit_smoke.py`
- S5 — `a-psi/moduleA_psi/scripts/policy_release.py:PUBLIC_REPORT_OPERATOR_ONLY_FIELDS`, `_maybe_write_operator_report`; `policy_postprocess_buckets.py` near `--public-report-redact-operator-fields`
