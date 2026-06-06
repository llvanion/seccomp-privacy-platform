# Current Security And Completion Audit

Date: 2026-06-01

2026-06-06 repo-side tightening update:

- source truthfulness strict mode now also enforces dual signoff, reviewer /
  operator identity separation, source-export-manifest presence in strict mode,
  and manifest scope binding.
- release gate strict mode now also enforces `require_dual_signoff=true`,
  truthfulness-report strictness/signoff expectation binding, and external
  anchor `records[].job_id` binding to the released job.
- privacy-budget heuristics now consume the existing
  `near_duplicate_window_seconds`, `near_duplicate_window_round_seconds`, and
  `near_duplicate_threshold_round_step` config fields to deny close-window
  differencing, threshold-round probes, and cross-bucket bucket-probe patterns
  repo-side; approval requests can now carry `privacy_budget_bucket_probe`.
- record-recovery production gate now fails closed unless HTTP production
  configs provide `allowed_output_roots`, `allowed_record_store_roots`, and
  `max_rows_per_request > 0`.

This is the current status source of truth for the repository. It is based on a
full first-party implementation inventory plus focused line review of the
security-boundary files surfaced by that inventory. Historical documents remain
useful for implementation detail, but their "complete" wording must be read as
"complete inside the old platform-baseline scope" unless this document says the
same item is production-complete.

Project positioning note:

- The technical core of this repository is **metadata/control-plane database +
  SSE + Google PJC**, not a generic business application.
- The `ecommerce` layer is a **key business-adaptation narrative and validation
  domain**, not the replacement for the technical core.
- The project should therefore be described as an **e-commerce privacy-compute
  platform** whose kernel remains searchable encryption, controlled recovery,
  bridge tokenization, and two-party computation.

Implementation details for all known remaining work are tracked in
[REMAINING_WORK_IMPLEMENTATION_BACKLOG.md](REMAINING_WORK_IMPLEMENTATION_BACKLOG.md).

For the mixed repo-side / operator-side governance split, use
[ONLINE_OFFLINE_SECURITY_GOVERNANCE.md](ONLINE_OFFLINE_SECURITY_GOVERNANCE.md)
as the concise reviewer-facing answer sheet. This audit remains the
authoritative status source; the governance document organizes the answer
format for source truthfulness, release legitimacy, trust-root, and protocol
claim questions.

## 1. Scope Reviewed

Traversal scope:

- Included first-party `.py`, `.sh`, `.rs`, `.ts`, and `.tsx` implementation
  files under `sse/`, `services/`, `bridge/`, `a-psi/moduleA_psi/scripts/`,
  `scripts/`, `console/src/`, `migrations/metadata/`, `config/`, and CI/release
  workflow files.
- Excluded vendored PJC source under `a-psi/private-join-and-compute/`,
  dependency directories, generated `tmp/` output, and virtualenv contents.
- Inventory size at review time: 393 first-party implementation files, 95,463
  lines by `wc -l`.

Commands used for coverage and verification:

```bash
rg --files -g '*.py' -g '*.sh' -g '*.rs' -g '*.ts' -g '*.tsx' \
  -g '!sse/.venv/**' \
  -g '!console/node_modules/**' \
  -g '!a-psi/private-join-and-compute/**' \
  -g '!tmp/**' \
  -g '!**/__pycache__/**' | sort

bash scripts/check_ci_smoke.sh
cargo test
npm --prefix console ci
npm --prefix console run typecheck
npm --prefix console run build:strict
python3 -m pytest sse/test
```

Current verification result:

- `bash scripts/check_ci_smoke.sh`: passed.
- `cargo test` in `bridge/`: passed, 10 tests.
- Console reproducibility is now repo-side gated: `console/package-lock.json`
  is committed, release uses `npm ci`, release typecheck is blocking, normal CI
  installs with `npm --prefix console ci` and runs console typecheck plus strict
  build, and `scripts/check_console_release_gate.py` rejects lockfile/workflow
  regressions.
- `python3 -m pytest sse/test`: passed locally with `sse/.venv` after installing
  `sse/requirements-dev.txt`; 100 tests passed.
- `scripts/check_supply_chain_gate.py` now emits `supply_chain_evidence/v1`
  with artifact hashes, Python/npm/Cargo component inventory, local provenance
  materials, and explicit operator-side status for external advisory/provenance
  evidence. Live GitHub Actions evidence and external SBOM/provenance/advisory
  enforcement remain separate supply-chain work.

## 2. Direct Answers

| Question | Current Answer |
| --- | --- |
| Is the protocol safe? | Safe only under the current prototype assumptions: local or controlled deployment, honest/semi-honest PJC participants, policy-gated release, input-commitment-checked bridge outputs, signed source-attestation-backed release governance, and operator-controlled secrets. Here `semi-honest` means parties are assumed to follow the Google PJC protocol steps correctly while still trying to infer as much as possible from allowed views; it does **not** cover malicious protocol deviation or maliciously fabricated source data. The new source-truthfulness path closes repo-side governance gaps; it does **not** turn Google PJC into a malicious-secure protocol and it does **not** replace external trust roots. |
| Is functionality complete? | The local demo/mainline is complete enough to run `SSE -> recovery -> bridge -> PJC -> policy release` and verify its contracts. Production platform functionality is not complete: the query workflow now has repo-side sidecar/DB-backed worker lifecycle evidence, and metadata DB restore is SHA-bound to a local backup report with tamper-denial evidence. Privacy-budget live PostgreSQL/browser deployment evidence, real KMS/authority lifecycle, live PostgreSQL/HA failover/restore evidence, live resource-isolated PJC worker evidence, public-network mTLS evidence, external immutable audit anchoring, and live console release evidence remain incomplete or operator-side. |
| Can it stop realistic attacks? | It stops some realistic mistakes and low-effort attacks: raw join-key exchange, production-mode direct token-secret CLI usage, malformed HTTP inputs, duplicate exact queries, default-release privacy-budget double spend, one-time near-duplicate approval consumption, legacy SSE network-pickle RCE, PJC post-bridge CSV/commitment tampering in the repo-side path, tampered local metadata backups when restore is bound to a backup report, some handoff retention risks, and local audit tampering. It does not yet reliably stop malicious-party protocol manipulation, browser token theft after XSS, production MITM/misdeployment without live mTLS evidence, live PostgreSQL/HA failure modes without target-host drills, live PJC worker DoS/OOM, or statistical attacks beyond current budget/approval heuristics. |
| Is the software layer safe? | Better than a typical prototype, but not production-hardened. There are clear hardening wins already implemented, plus P0/P1 gaps listed below. |

## 3. Status Vocabulary

Use these terms consistently:

- **Production-complete**: implemented, verified by automated gates, verified in
  realistic deployment topology, and documented with rollback/operation steps.
- **Repo-side complete**: code, examples, schemas, and dry-run/live optional
  hooks exist in the repository, but production services or credentials are not
  running in this workspace.
- **Baseline-complete**: complete only for the earlier local platform-baseline
  scope; not a claim of production security.
- **Partial**: some controls exist, but at least one security property still
  depends on manual discipline, operator-only evidence, or an unimplemented
  close-the-loop path.
- **Planned**: design exists but implementation or evidence is not enough to
  depend on it.

## 4. P0 / P1 Risk Register

### P0-01 Legacy SSE WebSocket Deserialization

Evidence:

- `sse/frontend/common/wire.py` now defines the network codec:
  `sse.frontend.ws/v1` JSON envelopes with explicit base64 markers for bytes.
- `sse/frontend/server/connector.py`,
  `sse/frontend/server/services/service.py`, and
  `sse/frontend/server/services/comm.py` now use the JSON codec instead of
  `pickle.loads`/`pickle.dumps` on WebSocket frames.
- `sse/frontend/client/services/service.py`,
  `sse/frontend/client/commands.py`, and `sse/example_usage.py` now use the
  same codec for network messages and structured content.
- `scripts/check_no_network_pickle.py` rejects network-facing pickle under
  `sse/frontend/server/` and `sse/frontend/client/`, allowing only local
  `service_meta` persistence files.
- `sse/global_config.py` now treats `SSE_PRODUCTION_MODE=1` as a hard
  retirement switch for this legacy WebSocket. In production mode it refuses
  startup on loopback and also refuses the demo wide-bind override.
- `scripts/check_legacy_sse_production_gate.py` verifies production refusal,
  demo loopback compatibility, demo wide-bind override behavior, and Docker
  default retirement.
- `sse/API_Docs.md` documents the JSON/base64 protocol.
- `sse/global_config.py` previously defaulted server host to an empty bind
  address; this review changed the default to `127.0.0.1`.

Impact:

- The direct network pickle RCE class is closed in the current code.
- The legacy/demo WebSocket is no longer a production candidate in repo-side
  policy. Production deployments must use the query workflow / bridge pipeline
  APIs instead of hardening this historical interface.

Current status:

- Code-complete for network pickle removal on 2026-06-01.
- Default bind host remains loopback.
- Non-loopback bind still fails closed unless `SSE_ALLOW_LEGACY_PICKLE_WS=1` is
  set as an explicit demo-only override.
- `SSE_PRODUCTION_MODE=1` fails closed before legacy WebSocket startup, even on
  loopback and even with `SSE_ALLOW_LEGACY_PICKLE_WS=1`.
- `sse/Dockerfile` sets `SSE_PRODUCTION_MODE=1`; starting that image now proves
  retirement by refusing the legacy server command instead of listening.
- Still open for production: deployed runbooks and live host evidence must show
  the legacy WebSocket is not the production query surface.

Required fix:

1. Keep `scripts/check_no_network_pickle.py` in CI.
2. Keep `scripts/check_legacy_sse_production_gate.py` in CI and pre-release
   gates.
3. Keep `sse/frontend/server/*` classified as local/demo; production wording
   must point to the query workflow / bridge pipeline APIs instead.
4. Treat remaining trusted-local pickle persistence as a separate lower-priority
   migration, not as a network RCE blocker.

### P0-02 Privacy Budget Transaction Is Repo-Side For Default Release

Evidence:

- `a-psi/moduleA_psi/scripts/policy_release.py` now creates or uses a
  transactional privacy-budget SQLite store when `--privacy-budget-ledger` is
  enabled. The default store path is `<privacy-budget-ledger>.sqlite`, with an
  explicit override available through `--privacy-budget-store`.
- The store bootstraps existing `privacy_budget_ledger/v1` JSONL records by
  source-record hash, starts `BEGIN IMMEDIATE`, loads same-scope prior records,
  evaluates exact duplicate / overlap / budget exhaustion inside the
  transaction, reserves the decision, writes public/operator/ledger/audit
  outputs, and commits.
- The consumption table records scope key, query fingerprint, caller, tenant,
  dataset, purpose, bucket/window, budget cost/limit, used before/after,
  decision, reason, approval ID, job ID, public-report hash, source-record hash,
  status, and payload JSON.
- A partial unique index prevents a second reserved/committed allowed consume
  for the same `(scope_key, query_fingerprint)`.
- `scripts/check_privacy_budget_concurrency.py` is in the smoke path and proves
  two concurrent releases with headroom for one produce exactly one allowed
  release and one deterministic deny.
- `privacy_budget_approval_events` and `privacy_budget_approval_decision/v1`
  now provide repo-side approve/reject/expire/consume state and audit events.
- `serve_operator_dashboard.py` exposes authenticated operator HTTP endpoints
  for approval list/approve/reject/expire, with tenant/caller scope checks,
  same-identity approval denial, reject/expire reason requirements, and
  decision JSONL evidence.
- The operator console SPA has a `privacy_budget_approvals` section that lists
  approval requests and triggers approve/reject/expire actions against those
  endpoints.
- `policy_release.py --privacy-budget-approval-id` consumes an approved
  near-duplicate request in the same transaction as the budget consume, rejects
  scope/fingerprint mismatches, rejects same-identity self approval, and blocks
  reuse after consumed/rejected/expired states.
- `scripts/check_privacy_budget_approval_flow.py` covers the approval lifecycle.
- `migrations/metadata/014_add_privacy_budget_consumption.sql` plus PostgreSQL
  bootstrap DDL provide schema parity for the metadata sidecar.

Impact:

- The previous JSONL-only double-spend race is closed for the default local
  policy-release path.
- The privacy-budget close-loop is still not production-complete because live
  PostgreSQL/HA evidence and deployed browser-console evidence are not complete.

Current status:

- Partial / repo-side SQLite close-loop complete. The default release path has
  SQL transaction, concurrency gate, approval lifecycle gate, and authenticated
  operator HTTP/browser approval surface; live PostgreSQL/HA evidence remains
  P0.

Required fix:

1. Run and record live PostgreSQL/HA evidence for the same concurrency,
   approval lifecycle, and duplicate-denial behavior.
2. Run deployed browser-console evidence against that live store.

### P0-03 PJC Input Commitments Are Repo-Side Complete; Malicious Security Is Not

Evidence:

- The project wraps Google Private Join and Compute for two-party computation.
- `bridge/src/main.rs` now writes `input_commitments.json` beside generated PJC
  CSVs using `pjc_input_commitment/v1`. The manifest records `job_id`,
  token scope/key version, normalizer, source-input hash where available, output
  CSV SHA-256, row count, and client value summary.
- `bridge_job_meta/v1`, `bridge_audit/v1`, and `pjc_audit/v1` carry the input
  commitment path/hash so downstream evidence can identify the committed inputs.
- `a-psi/moduleA_psi/scripts/validate_bridge_job.py` validates commitment hash,
  CSV hash, row count, normalizer, join-key metadata, and client value metadata.
- `scripts/preflight_pjc_job.py` supports `--input-commitment` and
  `--job-meta` plus `--require-input-commitment`; production PJC wrappers set
  the requirement and fail before launching PJC when the commitment is missing,
  hash-mismatched, CSV-mismatched, or semantically drifted from `job_meta.json`.
- `scripts/run_sse_bridge_pipeline.sh` passes the bridge commitment into Stage3
  PJC, passes `job_meta.json` into preflight, and records the commitment in the
  PJC audit.
- `scripts/check_pjc_input_commitment.py` covers the good path, post-bridge CSV
  mutation, commitment-hash mutation, token-scope mismatch, normalizer mismatch,
  normalizer-schema-version mismatch, negative values, and over-max values.
- `pjc_two_party_signed_run_manifest/v1` now signs Party A / Party B run
  manifests using Ed25519 over canonical JSON. The payload binds job id, repo
  commit, local and peer input commitment hashes, PJC result hash, policy
  decision, public report hash, audit-chain hash, and TLS identity metadata.
- `pjc_two_party_evidence_merge/v1` now verifies manifest signatures,
  cross-party commitment exchange, cross-party TLS identity exchange, result
  hash, policy decision, and audit-chain consistency.
- `release_policy_gate/v1` can require `require_pjc_evidence_merge=true` and
  compares the merge result hashes against the `policy_audit/v1`
  `pjc_result_sha256`; `scripts/check_release_policy_gate_smoke.py` covers
  result replacement denial.
- `release_policy_gate/v1` can also require `require_external_anchor=true`.
  Strict production config now requires an uploaded S3 Object Lock/Rekor
  `external_audit_anchor_report/v1`; missing, local, planned, unuploaded, or
  production-finding anchor reports deny release.
- `source_export_manifest/v1`, `source_attestation/v1`,
  `source_truthfulness_report/v1`, and `release_governance_report/v1` now bind
  the source snapshot, bridge inputs, input commitment, approval/signoff
  metadata, release gate decision, and reviewer-facing governance summary.
- `release_policy_gate_config/v1` now supports
  `require_source_attestation`, `require_signed_signoff`,
  `require_dual_signoff`, `require_bound_input_commitment`,
  `strict_source_attestation`, and `max_source_attestation_age_hours`;
  missing, unbound, unsigned, stale, single-signed, same-identity
  dual-signoff, planned/local/manual evidence now fails closed in strict
  repo-side mode.
- Operator dashboard job snapshots, caller-safe public summaries, and
  `/v1/runs?state=...` filtering now derive visible state from the release gate:
  external-anchor denials become `pending_external_anchor`; other release-gate
  denials become `blocked`.
- `client_value_mode=raw-int` now has committed value policy checks. Bridge
  emits `value_policy`, source summary, and output summary; production raw-int
  requires an explicit max value, allowed value field, value unit, and currency
  for minor currency units; validate/preflight recompute the PJC client CSV
  summary and deny negative, above-bound, or semantically unallowlisted values.
- `docs/PJC_MTLS_OPEN_RISKS.md` still treats production PJC strength and public
  deployment evidence as partial.

Impact:

- The repo-side path now detects accidental or malicious mutation of
  bridge-generated CSVs before PJC execution, detects signed evidence/result
  substitution before public release when the strict release gate config is used,
  prevents out-of-policy raw integer values from entering PJC, and prevents the
  operator dashboard from presenting a gate-denied release as completed.
- This is not a malicious-secure PJC protocol. A participant can still lie about
  its source data before bridge generation, choose adversarial records, or exploit
  repeated/near-duplicate windows unless the release policy and operator controls
  stop that behavior.
- Value range control is software policy validation, not a cryptographic proof.

Residual malicious-participant consequences worth stating explicitly:

1. A participant can provide **semantically false but structurally valid** input
   rows and still obtain a mathematically correct result over false data.
2. A participant can attempt to deviate from the protocol implementation,
   selectively abort, or manipulate bucket/shard structure, resulting in
   inconsistent evidence or misleading outputs.
3. A participant can try to package a false business conclusion as a valid run
   unless the release/audit/evidence chain and operator approval process stop
   that action.

Current status:

- Repo-side input-commitment gate, signed two-party manifest merge,
  source-truthfulness governance, and result-to-release binding are complete and
  regression-tested.
- Production claims must still say `semi-honest/operator-controlled` unless a
  real malicious-secure component or range-proof/value-proof package is added.

Current production-closure status (authoritative as of the current worktree):

- `tmp/production_security_closure_gate/production_security_closure_gate.json`
  now reports `module_count=16`, `live_ok_count=16`, `live_fail_count=0`, and
  `live_skipped_count=0`.
- `tmp/final_live_blockers_report.json` now reports
  `remaining_live_module_count=0`.

This means the project has completed its verifier-facing live module closure,
while still retaining the protocol-level `semi-honest` boundary for PJC.

Required fix:

1. Keep the product claim explicit: current Google PJC usage is
   `semi-honest/operator-controlled`.
2. Treat the new source-attestation stack as **protocol-external governance**,
   not as `malicious-secure` computation.
3. Remaining unresolved work should now be described in only two buckets:
   - **Protocol-internal hardening**: adopt or add a genuinely active-secure /
     malicious-secure PSI-SUM or 2PC/MPC backend, plus any real proof system
     for adversarial-value/source claims.
   - **External trust-root / operator infrastructure**: real immutable anchor,
     enterprise identity/KMS lifecycle, live HA/worker/SRE evidence, and other
     deployment-owned trust roots.
4. In product and reviewer language, treat malicious-participant resistance as a
   **separate security tier** from the now-complete live verifier evidence tier.

### P0-04 PJC Resource Isolation Wrapper Is Repo-Side Fail-Closed

Evidence:

- `run_pjc.sh`, `run_pjc_server_tls.sh`, and `run_pjc_client_tls.sh` now support
  `PJC_PRODUCTION_MODE=1`.
- Production mode fails before launching PJC/socat when `PJC_RESOURCE_LIMITS`
  is missing.
- Production mode rejects `PJC_GRPC_STREAM_CHUNK_ELEMENTS=0` and rejects PJC
  binaries that lack `--grpc_stream_chunk_elements` instead of silently falling
  back to unary.
- `pjc_binary_capability_gate/v1` now makes one more production-critical check
  verifier-readable: the selected `PJC_BIN_DIR` must resolve to a fresh Bazel
  output directory, not a stale workspace convenience `bazel-bin` tree whose
  binaries lag behind current `server.cc` / `client.cc` source capability.
- Legacy unary fallback requires explicit `PJC_ALLOW_LEGACY_UNARY=1`.
- TLS wrappers require `PJC_MTLS_REQUIRE_SESSION_MANIFEST=1` in production mode.
- Broad production TLS bind requires explicit `PJC_ALLOW_PRODUCTION_WIDE_BIND=1`.
- `scripts/verify_pjc_production_fail_closed.sh` is in the CI smoke path and
  covers missing limits, forbidden unary, non-loopback plain gRPC, missing
  session-manifest requirement, broad bind without override, and TLS client
  missing limits.
- `run_sse_bridge_pipeline.sh --production-mode` now requires
  `--pjc-resource-limits`, passes `PJC_PRODUCTION_MODE=1` and preflight scope
  into Stage3, and fails before invoking the PJC wrapper if the checked PJC
  binaries lack streaming support. Local replay/demo unary fallback remains
  explicit via `PJC_ALLOW_LEGACY_UNARY=1`.

Impact:

- The previous silent downgrade and missing-preflight wrapper paths are closed
  for direct wrapper launches and the main pipeline production-mode entrypoint.
- DoS/resource isolation is still not production-complete until live
  CPU/memory/pids/timeout worker evidence exists.

Current status:

- Partial / repo-side wrapper gate complete. Production wrapper argument and
  launch checks fail closed; live resource-isolated execution evidence remains
  open.

Required fix:

1. Surface preflight reports in dashboard job details.
2. Run PJC under real resource isolation and record timeout/cancel/over-limit
   evidence.
3. Record a production streaming success run with actual PJC binaries.

### P0-05 Public-Network mTLS Evidence Is Incomplete

Evidence:

- `docs/PJC_MTLS_OPEN_RISKS.md` records public-internet bucketed evidence as
  only partially validated: TCP reachability succeeded, but TLS handshakes
  failed during the recorded attempt.

Impact:

- The repository cannot currently prove that the documented two-host public
  mTLS deployment works end to end under realistic network conditions.

Current status:

- Partial / evidence gap.

Required fix:

1. Run a two-host PJC mTLS drill with fresh certs and captured logs.
2. Store sanitized evidence under the documented handoff directory.
3. Make failed TLS diagnostics actionable in the runbook.

### P1-01 Real Authority Sources Are Repo-Side, Not Production-Operated

Evidence:

- Keycloak/OpenFGA/Vault/AWS KMS adapters, compose files, and dry-run/live hooks
  exist.
- Production documents still mark live validation as operator-provided.

Impact:

- Production secret and identity safety still depends on deployment work outside
  the repository.

Current status:

- Repo-side complete, operator-side incomplete.

Required fix:

1. Run live Keycloak/OpenFGA/Vault/cloud-KMS drills in a managed environment.
2. Capture credential rotation, revocation, backup, restore, and break-glass
   evidence.

### P1-02 External Immutable Audit Anchor Not Proven Live

Evidence:

- Local audit chain/seal/archive tooling exists.
- External S3 Object Lock / Sigstore Rekor paths are documented and scaffolded,
  but the default smoke uses local/offline evidence.

Impact:

- Local compromise can still rewrite or remove evidence unless the external
  anchor path is actually executed and monitored.

Current status:

- Partial.

Required fix:

1. Execute S3 Object Lock or Rekor anchoring against a real account/service.
2. Add verify-from-external-anchor gate and tamper evidence.

### P1-03 Read API Metadata Leakage Controls

Evidence:

- `scripts/serve_audit_query_api.py` now separates caller-safe read views from
  operator evidence. Identity-backed non-privileged callers receive
  `audit_chain_public_summary/v1`,
  `pipeline_observability_public_summary/v1`, and
  `catalog_lineage_public_summary/v1` instead of raw audit-chain,
  observability, or catalog-lineage documents.
- The public-report endpoint applies an allowlist and marks the returned report
  as `operator_fields_redacted: true`.
- `scripts/check_audit_api_public_redaction.py` recursively fails if
  caller-safe audit API responses contain raw audit arrays, artifact paths,
  hashes, exact row counts, detailed timing, `bridge`, `details`, or query
  fingerprints.
- `scripts/check_json_contracts.sh` now validates the new public-summary
  schemas and runs the redaction scan against identity-backed normal-caller
  audit API responses.
- `serve_operator_dashboard.py GET /v1/dashboard` now becomes auth-aware when
  bearer/identity auth is configured. Normal identity callers receive
  `operator_dashboard_public_summary/v1`, which redacts paths, hashes, raw
  artifact lists, and exact intersection results; full dashboard output is
  limited to `platform_admin`, `platform_auditor`, `privacy_operator`, and
  `compliance_auditor`.
- `scripts/check_operator_dashboard_public_summary.py` covers unauthenticated
  dashboard denial, normal-caller public summary redaction, and privileged full
  view. It also verifies normal callers cannot use `/v1/runs`,
  `/v1/jobs/{job_id}`, `/v1/jobs/{job_id}/result`, or direct
  `/v1/jobs/start` to bypass the dashboard public-summary split.
- The repo-side SPA now treats `/v1/dashboard` as a full/public union:
  `console/src/routes/home.tsx` and `console/src/routes/jobs.tsx` branch on
  `operator_dashboard_public_summary/v1` and render only coarse job/workflow,
  health, artifact-count, and redaction-marker fields for normal callers.
  `scripts/check_console_dashboard_public_summary.py` freezes that route-level
  guard.
- The repo-side SPA now also treats audit query sidecar results as
  full/public unions. `console/src/api/sidecars.ts` unwraps
  `audit_query_api_response/v1.result`; `console/src/routes/audit.tsx`,
  `console/src/routes/observability.tsx`, and `console/src/routes/catalog.tsx`
  branch on `audit_chain_public_summary/v1`,
  `pipeline_observability_public_summary/v1`, and
  `catalog_lineage_public_summary/v1` before reading full audit event or
  lineage fields. `scripts/check_console_audit_public_summary.py` and
  `console_audit_public_summary_check/v1` freeze that route-level guard.

Impact:

- Normal identity-backed callers can still verify release status and coarse
  pipeline state without receiving operator-only evidence or small-count
  side-channel fields from the audit API.
- This does not yet finish all read-surface leakage controls: dashboard HTTP,
  console home/jobs, console audit/observability/catalog, and identity-backed
  metadata job/entity reads now have caller-safe summary or redacted behavior,
  but future metadata entities must stay on the same explicit contract
  discipline and small-bucket coarsening remains open.

Current status:

- Audit API caller-safe views are repo-side complete and regression-tested.
- Operator dashboard HTTP caller-safe summary is repo-side complete and
  regression-tested.
- Console home/jobs/audit/observability/catalog public-summary coverage is
  repo-side complete and regression-tested.
- Identity-backed metadata API job list, job detail, caller-permissions, and
  policy-bindings reads return `caller_safe_metadata_summary` redacted payloads
  for normal callers; console metadata routes unwrap
  `metadata_api_response/v1.result` and show redaction notices.
- `bucket_public_report/v1` is now release-safe: below-k bucket labels/counts
  are omitted, exact bucket sizes are bucketized, and `dp_noise` is redacted;
  full raw/noise evidence moves to `operator_bucket_report/v1`.
- `identity_jwks_evidence_gate/v1` now packages the repo-side RS256/JWKS
  identity evidence into a verifier-readable report: synthetic `file://` JWKS
  claim mapping, JWKS-backed `resolve_api_identity`, JWKS-backed metadata
  `/v1/identity`, and JWKS-backed key-agent / external-KMS access all have one
  archived contract surface.
- `live_identity_authority_evidence_gate/v1` now wraps the repo-side JWKS
  baseline together with live-capable authority hooks: client-credentials
  request, live JWKS claim verification, live `resolve_api_identity`, and live
  metadata `/v1/identity` are all represented in one verifier-facing report,
  with explicit `skipped` states when operator-provided live prerequisites are
  absent.
- `public_two_host_production_readiness_gate/v1` now does the same for the
  public two-host PJC boundary: it aggregates repo-side `check_pjc_two_party_smoke.py`,
  `check_pjc_tls_diagnostic_smoke.py`, `check_release_policy_gate_smoke.py`,
  and archived `S7/K3` evidence-integrity verification into one verifier-facing
  report, then records live management/data-plane checks as `ok|fail|skipped`.
  It makes a crucial distinction explicit: a public host that is TCP-reachable
  but only exposes an HTTP-gateway pattern on candidate admin ports is not
  enough to claim fresh two-host production readiness.
- `public_two_host_live_materialization_report/v1` now freezes the clean-room
  staging step for fresh two-host runs. It copies only Party A/Party B input
  artifacts and mTLS session materials into a new staging directory, strips any
  inherited `client.log`, `server.log`, `attribution_result.json`, preflight,
  session-check, and binary-capability outputs, and records the kept-file hash
  inventory plus stripped-source file list for verifier review. The clean-room
  cert layout now mirrors runtime expectations: a shared `cert_dir` contains
  `ca.crt`, `server.crt`, `server.key`, `client.crt`, `client.key`, and
  `session_manifest.json` for server-side manifest validation, while
  `party_b_bundle/` keeps the client-only bundle used by Party B.
- `pjc_tls_readiness/v1` now separates “is the public mTLS endpoint truly ready
  for a job-bound client handshake” from the previous raw TCP liveness check.
  It reuses the typed TLS diagnostic path with the real client cert bundle,
  produces a frozen readiness report, and is intended to replace plain
  `socket.create_connection()` probes that can hit the TLS listener and create
  verifier-confusing `SSL_accept unexpected eof` noise without representing a
  real workload failure.
- `public_two_host_live_evidence_archive/v1` now freezes the completed
  clean-room public two-host bucketed run. The current-worktree `cross-vps-008`
  archive proves a public `TLSv1.3` mTLS run on `118.190.61.66:10504` with
  `bucket_count=8`, merged `intersection_size=420`, merged
  `intersection_sum=2137273`, per-bucket `tls=true` attribution results, Party
  A server logs, Party B client logs, per-bucket preflight/session checks, and
  a clean-room materialization report. The verifier-facing readiness gate now
  treats that archive as authoritative even when a post-run `tcp_refused`
  probe sees the listener has already exited.
- High-sensitivity padding, delayed release, or automatic bucket merge remains
  partial.

Required fix:

1. Decide whether high-sensitivity deployments require padding, delayed
   release, or automatic merge-to-other beyond report-layer bucket redaction.
2. Keep recursive redaction scans in CI for new public API payloads.
3. Preserve the normal-caller metadata redaction contract when new metadata
   entities are exposed.

### P1-03B Business Field-Level Read Controls

Evidence:

- `business_access_policy/v1` defines role/persona field decisions for merchant,
  courier, support, buyer, field marketing, fraud analyst, and compliance
  auditor workflows.
- `serve_metadata_api.py POST /v1/business-access/check` binds the requested
  business role to the authenticated identity and tenant scope.
- `serve_metadata_api.py POST /v1/business-data/read-preview` now enforces the
  same policy before reading e-commerce fact tables: denied fields return HTTP
  403, masked fields return mask markers without selecting raw values, and
  filters cannot override the authorized `scope`.
- Read-preview no longer trusts caller-supplied relationship strings by
  themselves for the main commerce personas. The fact layer now carries bound
  relationship anchors (`orders.merchant_business_identity_id`,
  `orders.buyer_business_identity_id`,
  `order_attribution.assigned_marketer_business_identity_id`,
  `order_payment.assigned_fraud_analyst_business_identity_id`,
  `order_payment.fraud_case_id`, and
  `customer_service_interactions.case_id`), and
  `serve_metadata_api.py` binds them back to `business_identities` before
  returning a business access decision or preview.
- Read-preview still uses a narrow SQL filter allowlist; sensitive fields such
  as buyer email cannot be used as filters, reducing mask/deny bypass through
  existence queries.
- `business_data_read_preview/v1` and `business_access_api_smoke/v1` freeze the
  evidence shape. `scripts/check_business_access_api_smoke.py` covers allow,
  deny, mask, role spoofing, `order_id` filter conflict, and tenant filter
  conflict, plus sensitive-field filter rejection, fraud payment/contact
  allow-deny coverage, field marketer attribution/contact allow-deny coverage,
  and caller-scoped / cross-tenant denial for the `business-identities`
  directory. As of 2026-06-04 it also covers repo-side relationship-spoof
  denial for merchant/buyer/logistics/fraud/marketer paths. As of 2026-06-05
  it also proves the non-privileged support caller path over loopback HTTP:
  support sees masked buyer contact only on its assigned case, support case
  spoofing is rejected with HTTP 403, and
  `check_business_access_support_relation_binding.py` still freezes the same
  repo-side relation-binding proof for the support persona
  (`bound_identity_id=support-1`, `bound_case_id=case-1`) without pretending
  that this is deployment evidence.
- As of 2026-06-04, the default repo-side contract chain is also back in sync
  with these semantics: `bash scripts/check_json_contracts.sh` now validates
  the updated commerce smoke fields, the support relation-binding artifact, the
  fact-layer relation columns, and the current verifier-facing `public_two_host`
  / `ecommerce` gate statuses instead of stale `live_status=skipped` assumptions.
- `scripts/validate_ecommerce_fact_import.py` emits
  `ecommerce_fact_import_validation/v1` for candidate JSONL fact imports. The
  smoke covers a valid order import plus denial for hidden address fields, raw
  support transcripts, and negative monetary values.
- `scripts/import_ecommerce_fact_rows.py` now reuses that same validator before
  writing rows, applies metadata migrations, and inserts into the fact table in
  one transaction. `scripts/check_ecommerce_fact_import.py` proves the allowed
  import commits, a sensitive-column candidate is rejected before insert, and a
  duplicate-order batch rolls back without changing the table count.
- `ecommerce_production_exposure_gate/v1` aggregates the fact-layer report,
  business access policy smoke, business access API smoke, direct
  query/workflow identity-scope smoke, operator request workflow smoke, and
  console manifest exposure check. It now also emits a structured
  `exposure_matrix` that separates attacker, internal adversary, and verifier
  evidence views, including request-workflow evidence that submitters cannot
  spoof caller/tenant/dataset scope or recovery-service scope, direct
  query/workflow API evidence that identity-bound dry-run and execute paths keep
  caller/dataset/recovery-service bindings, non-review analysts cannot
  list/detail/approve/reject another caller's submission, and compliance
  auditors cannot approve but can reject. It distinguishes repo-side evidence
  from live production prerequisites.
- As of 2026-06-05, the same repo-side commerce module now also includes:
  1. `console_business_access_workbench_check/v1`, proving the console SPA has
     a dedicated `Business Access Workbench` route wired to
     `metadataApi.businessAccessCheck()` and
     `metadataApi.businessDataReadPreview()`, and
  2. `ecommerce_fact_import_job_smoke/v1`, proving a manifest-driven
     `ecommerce_fact_import_job/v1` wrapper commits allowed rows and denies
     protected-column batches without mutating final row count.

Impact:

- The repo now has one enforced business read path that prevents the obvious
  "policy-check says deny, but another endpoint returns the raw field" bypass
  for the current e-commerce fact tables.
- This is not a full production ABAC system. Future business read endpoints and
  browser views must reuse the same pre-SELECT decision pattern or they will
  reintroduce the bypass.
- The repo-side batch importer prevents obvious sensitive-column drift before
  fact loading and proves rollback behavior, but production event streams,
  warehouse jobs, and external ETL systems still need to call this gate or an
  equivalent policy-enforced importer.

Current status:

- Repo-side enforced read-preview is complete and regression-tested.
- Repo-side candidate import validation plus transactional SQLite/PostgreSQL
  importer path is complete and regression-tested.
- Repo-side production exposure gate is complete and regression-tested.
- Full business API, deployed production ETL wiring, live browser-console role
  exercise, real OIDC/OpenFGA/ABAC parity, live Postgres drills, and external
  audit anchoring remain production-environment work.
- Fresh public two-host Party A/Party B evidence on the current worktree and a
  real VPS admin entrypoint remain production-environment work even though the
  repo-side readiness gate and archived S7/K3 evidence now have frozen
  contracts.

Required fix:

1. Treat `business-data/read-preview` as the reference gate for every new
   business read endpoint.
2. Use `import_ecommerce_fact_rows.py` or an equivalent validator-first
   transaction in every production ETL/batch import before sensitive business
   rows are accepted into fact tables.
3. Add browser-console workflows and externalized ABAC evidence if production
   claims include direct business-user access.
4. Archive `ecommerce_production_exposure_gate/v1` for each production release
   and fill its `real_production_remaining` items with live evidence rather than
   repo-side smokes.

### P1-04 Browser Console Token Storage

Evidence:

- `console/src/api/config.ts` now persists only sidecar base URLs in
  `localStorage` (`seccomp.console.baseUrls.v1`).
- Bearer tokens are kept in `sessionStorage` (`seccomp.console.tokens.session.v1`)
  only as a fallback for cross-origin sidecar/debug use; the same-origin
  production path is HttpOnly cookie based.
- `serve_operator_dashboard.py` exposes `POST /v1/session/login`,
  `POST /v1/session/logout`, and `GET /v1/session`. Login exchanges an
  identity bearer token for `seccomp_identity_session` with `HttpOnly`,
  `SameSite=Strict`, and `Path=/`; `--session-cookie-secure` enables the
  `Secure` attribute behind HTTPS/TLS.
- `api_identity.py` now accepts either `Authorization: Bearer ...` or the
  configured identity session cookie. Metadata, query-workflow, audit,
  platform-health, operator-dashboard, and identity-proxy adapters use that
  shared resolver.
- `console/src/api/client.ts` sends `credentials: "same-origin"`, and
  `console/src/routes/settings.tsx` can establish/clear the browser session
  while clearing the fallback operator token from console config.
- `scripts/check_console_token_storage.py` fails CI if future console source
  code tries to persist token/Bearer/Authorization material through
  `localStorage` or stops sending same-origin credentials; its report validates
  as `console_token_storage_check/v1`.
- `scripts/check_console_browser_session.py` validates the HttpOnly cookie path:
  unauthenticated dashboard read is denied, login emits `HttpOnly` /
  `SameSite=Strict`, cookie-only dashboard/session reads succeed, and logout
  expires the cookie. The report validates as
  `console_browser_session_check/v1`.
- `scripts/check_identity_proxy_auth_smoke.py` validates that the identity proxy
  fails closed when auth is configured, overwrites spoofed `X-Identity-*`
  headers, accepts the same HttpOnly session cookie, and does not synthesize an
  `Authorization` header for cookie-only requests.
- `serve_operator_dashboard.py` now emits browser security headers for JSON API
  and SPA static responses: CSP, `X-Content-Type-Options=nosniff`,
  `X-Frame-Options=DENY`, `Referrer-Policy=no-referrer`, and a restrictive
  `Permissions-Policy`. `connect-src`, `script-src`, and `style-src` are
  same-origin only, CSP forbids `unsafe-inline` / `unsafe-eval`, and HSTS is
  emitted when `--session-cookie-secure` is enabled.
- `scripts/check_console_security_headers.py` validates `/healthz`,
  `/v1/dashboard`, `/`, and `/assets/app.js` headers, scans `console/src` for
  inline style/raw HTML sinks, and validates Secure-cookie / HSTS mode as
  `console_security_headers_check/v1`.

Impact:

- Cross-session `localStorage` bearer-token theft is closed for the current SPA.
- Same-origin console deployments no longer require JavaScript to retain a
  bearer token after login; an active-tab XSS cannot read the HttpOnly cookie.
- If operators keep using fallback Bearer tokens for cross-origin sidecars or
  debug workflows, active-tab XSS can still steal those fallback tokens.
- Browser injection blast radius is reduced by a repo-side CSP/security-header
  gate with no inline script/style allowance and a source scan for inline style
  or raw HTML sinks.
- Production still needs HTTPS/Secure-cookie deployment evidence, dependency
  audit/SBOM/provenance controls, and live reverse-proxy/OIDC evidence.

Current status:

- Repo-side browser session path, browser security-header gate, and reproducible
  console CI/release gate are complete for same-origin deployments. Overall
  production auth remains partial until reverse-proxy/OIDC deployment evidence,
  Secure-cookie TLS evidence, dependency audit/SBOM/provenance, and live release
  evidence are captured.

Required fix:

1. Serve the console behind HTTPS/TLS with `--session-cookie-secure` and capture
   live browser evidence.
2. Keep CSP/security-header and console release-gate checks in CI and add
   dependency audit/SBOM/provenance gates.
3. Keep `scripts/check_console_token_storage.py`,
   `scripts/check_console_browser_session.py`,
   `scripts/check_identity_proxy_auth_smoke.py`,
   `scripts/check_console_security_headers.py`, and
   `scripts/check_console_release_gate.py` in CI so token/session/header/release
   handling cannot regress.

### P1-05 Console Release Gate Is Repo-Side Reproducible

Evidence:

- `console/package-lock.json` is committed with npm lockfileVersion 3 and root
  dependencies matching `console/package.json`.
- `.github/workflows/release.yml` now installs console dependencies with
  `npm ci --no-audit --no-fund`, runs blocking `npm run typecheck`, and builds
  with `npm run build:strict`.
- `.github/workflows/json-contracts.yml` now sets up Node 20, runs
  `npm --prefix console ci --no-audit --no-fund`, then runs console typecheck
  and strict build before repo smoke.
- `scripts/check_console_release_gate.py` emits
  `console_release_gate_check/v1` and rejects missing lockfile, `npm install`
  fallback, advisory release typecheck, missing strict build, or missing local
  CI smoke coverage.
- `scripts/check_json_contracts.sh` and `scripts/check_ci_smoke.sh` both run
  the release-gate check.

Impact:

- Console dependency installation and release builds are reproducible repo-side,
  and TypeScript errors can no longer pass the release console job by advisory
  continuation.

Current status:

- Repo-side complete. Remaining supply-chain work is live GitHub Actions release
  evidence plus SBOM/provenance/dependency-advisory policy.

Required fix:

1. Capture a real GitHub Actions release/CI run showing console `npm ci`,
   typecheck, and strict build passing.
2. Add SBOM/provenance/dependency-advisory gates for console release artifacts.

### P1-06A Recovery Service HTTP Production Gate Is Repo-Side Fail-Closed

Evidence:

- `services/record_recovery/production.py` defines one production policy for
  HTTP recovery service runtime config.
- `services/record_recovery/http_service.py`, `services/record_recovery/launcher.py`,
  and `scripts/manage_record_recovery_service.py` enforce that policy before
  direct service launch, launcher dispatch, managed start, or systemd render.
- Production HTTP now requires request authentication, authz policy, and either
  signed requests or mTLS client certificates. Non-loopback HTTP listeners
  require mTLS client certificates. Identity-token auth additionally requires
  a metadata DB path.
- `scripts/check_record_recovery_production_gate.py` emits
  `record_recovery_production_gate_check/v1` and proves negative cases for
  missing auth, missing authz, identity without metadata DB, identity without
  HMAC/mTLS, public listener without mTLS, env-enabled production mode, and
  positive loopback signed-request / public mTLS render paths.

Impact:

- A production-mode recovery endpoint cannot be accidentally launched as an
  unauthenticated HTTP service from the repo entrypoints.
- This is not live deployment proof. It does not by itself prove a host firewall,
  Kubernetes NetworkPolicy, hardened service user, or real public-network mTLS
  session.

Current status:

- Repo-side complete. Live production deployment evidence remains partial.

Required fix:

1. Keep `scripts/check_record_recovery_production_gate.py` in CI/contracts and
   pre-release gates.
2. Capture live service-user/systemd sandbox evidence for the rendered unit.
3. Capture host firewall or Kubernetes NetworkPolicy evidence.
4. Capture public-network mTLS request evidence against a deployed recovery
   service.

### P1-06B Static Identity Token Comparison

Evidence:

- `scripts/api_identity.py` previously compared static token-map entries with
  normal string equality.

Impact:

- Low practical risk in this local adapter, but inconsistent with constant-time
  comparison used elsewhere.

Current status:

- Fixed on 2026-06-01 by switching to `hmac.compare_digest`.

## 5. Attack Coverage Matrix

| Attack / Failure Mode | Current Coverage | Gap |
| --- | --- | --- |
| Raw data exchange between parties | Stronger: bridge tokenization and policy-gated recovery avoid direct raw join-key exchange. | Bridge-ready plaintext still exists in some modes; FIFO/default cleanup reduces but does not eliminate operator misuse. |
| Local malformed HTTP requests | Good: contract smoke covers many bad inputs and role gates. | Continue adding negative tests for every new HTTP adapter. |
| Replay against record recovery | Good: request timestamp and HMAC request signing exist. | Custom clients that omit timestamp/signature must stay denied in production profiles. |
| Exact duplicate query | Good: duplicate-query denial, privacy ledger exact fingerprint checks, and transactional SQL consume exist for the default release path. | Approval-consume and live PostgreSQL evidence remain open. |
| Concurrent privacy-budget double spend | Improved: SQLite transactional consume and a race test now cover the default release path. | Need live PostgreSQL/HA evidence. |
| MITM on PJC public network | Partial. | Need live two-host mTLS success evidence and cert rotation drill. |
| Malicious PJC participant | Improved only for repo-side metadata-to-input tamper: commitment checks catch post-bridge CSV and manifest mutation before PJC. | Need adversary model, signed two-party evidence, result-to-commitment release binding, value proof/validation, or malicious-secure protocol choice. |
| DoS/OOM on PJC workload | Partial. | Resource preflight and streaming must fail closed in production. |
| Audit log tamper on local host | Improved: local chain/seal exists and final release can require an uploaded S3/Rekor external-anchor report. | Live S3/Rekor credentials, upload, read-back, and deployed same-run publication evidence remain operator-side. |
| Metadata leakage through read APIs | Improved: identity-backed audit API, operator dashboard, metadata API job/entity reads, console home/jobs/audit/observability/catalog/metadata routes, and public bucket reports receive or render public-summary/redacted schemas with redaction/static gates. | High-sensitivity padding/merge strategy and future metadata entities must stay on the same redaction contract. |
| Browser token theft after XSS | Improved: same-origin console auth now has repo-side HttpOnly/SameSite session-cookie flow, static token-storage gate, and browser-session smoke. | Fallback Bearer token mode remains for cross-origin/debug use; production still needs HTTPS/Secure-cookie evidence, CSP, and dependency/no-inline gates. |
| Exposed legacy SSE WebSocket | Repo-side retired for production: network pickle RCE removed, default bind is loopback, and `SSE_PRODUCTION_MODE=1` refuses startup even with demo override. | Need deployed host evidence that production traffic uses query workflow / bridge APIs and does not expose this legacy server. |
| Duplicate or stale query workflow execution | Improved: `submit_query_workflow.py` and dashboard async start refuse to overwrite existing sidecar state; `query_workflow_executions` records DB-backed queue/claim/lease/heartbeat/cancel/timeout/terminal state; `run_query_workflow_worker.py` owns queued work outside submit/HTTP threads; `query_workflow_durability_check/v1` covers duplicate dry-run, execute-from-accepted, duplicate execute, stale-running visibility, active duplicate DB claim denial, terminal replay denial, expired-lease steal, enqueue-to-worker completion, cancellation, timeout, and restart-steal semantics. | Still not a complete production queue; needs supervised deployed workers, multi-worker retry policy, target-host restart drills, and live PostgreSQL/HA evidence. |
| Tampered metadata DB backup restore | Improved: `restore_metadata_db.py` can require `metadata_db_backup_report/v1.backup.sha256` or `--expect-backup-sha256`; `metadata_backup_restore_drill/v1` proves local backup verification, SHA-bound restore, probe-row preservation, portability check, and tampered-backup denial. | Still not live PostgreSQL/Patroni/pgBouncer HA; needs external backup storage, target-host restore, failover, and API/query smoke against restored DB. |

## 6. Problem Identification Plan

Use this sequence whenever the project is re-assessed. The goal is to prevent
old "baseline complete" wording from hiding current production risk.

### 6.1 Build A Fresh Core Inventory

```bash
rg --files -g '*.py' -g '*.sh' -g '*.rs' -g '*.ts' -g '*.tsx' \
  -g '!sse/.venv/**' \
  -g '!console/node_modules/**' \
  -g '!a-psi/private-join-and-compute/**' \
  -g '!tmp/**' \
  -g '!**/__pycache__/**' | sort > tmp/core_implementation_files.txt

xargs wc -l < tmp/core_implementation_files.txt > tmp/core_implementation_loc.txt
```

### 6.2 Scan Security-Sensitive Patterns Across The Whole Inventory

```bash
rg -n "pickle\.loads|yaml\.load|eval\(|exec\(|shell=True|os\.system|subprocess\.|HTTPServer|ThreadingHTTPServer|websockets\.serve|0\.0\.0\.0|OPENSSL-LISTEN|compare_digest|bearer|token_secret|localStorage|dangerouslySetInnerHTML|innerHTML" \
  sse services bridge a-psi/moduleA_psi/scripts scripts console/src config migrations .github
```

Every hit must be classified as:

- network-facing input
- local trusted tool input
- generated artifact handling
- test/demo only
- false positive

Do not close a finding by saying "documented" unless there is also a code gate
or a production-mode refusal path.

### 6.3 Required Gates Before Any "Production-Ready" Claim

```bash
bash scripts/check_ci_smoke.sh
cargo test
npm --prefix console ci
npm --prefix console run typecheck
npm --prefix console run build:strict
python3 -m pytest sse/test
python3 scripts/check_supply_chain_gate.py
```

Additional production gates still needed:

1. Live PostgreSQL/HA privacy-budget concurrency and operator approval API drill.
2. Live resource-isolated PJC worker with timeout/cancel and large streaming
   success evidence.
3. Legacy SSE production decision: retire it or add auth, service identity, TLS,
   rate limits, and deployment gates.
4. Two-host PJC mTLS live drill.
5. Signed PJC commitment exchange, result-to-commitment release binding, and
   evidence merge.
6. Real Keycloak/OpenFGA/Vault/cloud-KMS live drill.
7. External immutable audit anchor write-and-verify drill.
8. External supply-chain provenance and dependency advisory enforcement from the
   real release environment.

### 6.4 Documentation Gate

Before merging future status docs:

1. If a document says "complete", it must specify **baseline-complete**,
   **repo-side complete**, or **production-complete**.
2. If a document says "only X remains", it must link to this audit and the
   relevant current production plan.
3. If implementation detail is moved, the new document must link to the old
   detailed source or preserve the command/config snippets.
4. Session reports should not be the default project-status entry point.

## 7. Recommended Next Work

1. Finish privacy-budget operator HTTP API and live PostgreSQL evidence.
2. Produce live PJC resource-isolated worker evidence.
3. Add signed PJC commitment exchange and release binding, or document
   semi-honest-only product claims.
4. Produce a clean two-host mTLS evidence package.
   Archive the corresponding `public_two_host_live_materialization_report/v1`
   first so verifiers can distinguish fresh current-worktree runtime evidence
   from stale bucket outputs copied forward from a prior local run.
5. Use typed TLS readiness rather than raw TCP probes before each public bucket
   handoff. The live `cross-vps-008` clean-room run now shows multiple bucket
   successes while Party A still logs `SSL_accept unexpected eof`; that EOF is
   consistent with a non-mTLS readiness probe touching the TLS listener, so
   future verifier-facing evidence must rely on `pjc_tls_readiness/v1`.
6. Public clean-room bucketed validation is now complete on the current
   worktree. Remaining live-production work is no longer “can two hosts run”;
   it is higher-order deployment trust, such as SPIFFE/SPIRE + Envoy live
   identity rollout and operator-owned trust-root custody.
- `spiffe_envoy_identity_gate/v1` now packages that next trust boundary into a
  verifier-facing gate. It freezes the committed SPIFFE peer allowlist and the
  SPIRE/Envoy template lint as repo-side checks, while marking positive
  Envoy/SPIRE run evidence, wrong-peer reject, expired-SVID reject,
  trust-bundle reject, and Envoy access-log evidence as `skipped` until an
  operator supplies real deployment artifacts.
- `spiffe_envoy_live_evidence_archive/v1` now provides the matching archive
  shape for those live artifacts. Once a real SPIFFE/SPIRE + Envoy deployment
  exists, positive run evidence, wrong-peer rejects, expired-SVID rejects,
  trust-bundle rejects, and Envoy access logs can be frozen into one bundle and
  then consumed by `spiffe_envoy_identity_gate/v1`.
- `external_anchor_evidence_gate/v1` and `external_anchor_live_evidence_archive/v1`
  now do the same for immutable external anchoring. The repo-side gate freezes
  planned Rekor publication plus the strict `verify_external_audit_anchor_gate.sh`
  negative set, while the live archive gives operator S3 Object Lock / Rekor
  uploads a stable bundle shape to feed back into verifier-facing checks.
- `postgres_ha_evidence_gate/v1` and `postgres_ha_live_evidence_archive/v1`
  now do the same for metadata durability. The gate aggregates the existing
  backup/restore drill, failover retry test, primary/replica topology,
  Patroni failover topology, and pgBouncer topology into one verifier-facing
  report, while the live archive gives operator-side PostgreSQL/Patroni/
  pgBouncer evidence a single bundle shape once real target-host drills are
  available.
- `supply_chain_evidence_gate/v1` and `supply_chain_live_evidence_archive/v1`
  now do the same for release/provenance evidence. The gate wraps the existing
  `supply_chain_evidence/v1` repo-side inventory/report, while the live archive
  gives GitHub Actions run evidence, release checksums, provenance/attestation,
  and advisory outputs a single verifier-facing bundle shape.
- `authority_evidence_gate/v1` and `authority_live_evidence_archive/v1` now do
  the same for live identity/authz/KMS authority rollout. The gate consumes the
  existing `authority_governance_report/v1` plus the repo-side
  `live_identity_authority_evidence_gate/v1`, while the live archive gives
  operator Keycloak/OpenFGA/Vault/cloud-KMS evidence a single bundle shape once
  those deployment artifacts exist.
  Current VPS inventory still shows no running Keycloak/OpenFGA/Vault/KMS
  processes and no corresponding live artifact directories under `tmp/`, so
  this remaining module is presently blocked on operator infrastructure rather
  than missing repo-side code.
- `observability_evidence_gate/v1` and `observability_live_evidence_archive/v1`
  now do the same for Tempo/Grafana/Prometheus/alerting. The gate consumes the
  checked-in topology and alert-daemon smoke, while the live archive provides a
  stable bundle shape for operator Tempo push, Grafana render, webhook, and
  heartbeat evidence once live observability services exist.
- `recovery_service_deployment_evidence_gate/v1` and
  `recovery_service_live_evidence_archive/v1` now do the same for deployed
  recovery-service hardening. The gate aggregates the repo-side HTTP
  production gate, failover continuity test, committed Kubernetes recovery
  topology, and tenant-scoped NetworkPolicy render, while the live archive
  gives operator systemd/service-user sandbox, firewall or NetworkPolicy,
  public-network mTLS, and target-host failover artifacts one stable verifier-
  facing bundle shape.
- `privacy_budget_deployment_evidence_gate/v1` and
  `privacy_budget_live_evidence_archive/v1` now do the same for privacy-budget
  deployment closure. The gate aggregates repo-side transactional concurrency,
  approval lifecycle, authenticated approval API, HttpOnly console session, and
  cookie-aware identity proxy evidence, while the live archive gives operator
  PostgreSQL/HA, deployed browser-console, approval API, and duplicate-denial
  artifacts one stable verifier-facing bundle shape.
- `legacy_sse_query_surface_evidence_gate/v1` and
  `legacy_sse_live_evidence_archive/v1` now do the same for the retired legacy
  SSE WebSocket query surface. The gate wraps the existing
  `legacy_sse_production_gate/v1` repo-side retirement proof, while the live
  archive provides a single bundle shape for operator route, socket, and ingress
  evidence that production traffic does not expose that interface.
- `pjc_resource_isolation_evidence_gate/v1` and
  `pjc_resource_isolation_live_evidence_archive/v1` now do the same for PJC
  worker resource isolation. The gate aggregates repo-side preflight limits,
  binary freshness/streaming capability, and production wrapper fail-closed
  checks, while the live archive gives operator systemd/Kubernetes limits,
  timeout/cancel, and production streaming success artifacts one stable
  verifier-facing bundle shape.
- `query_workflow_deployment_evidence_gate/v1` and
  `query_workflow_live_evidence_archive/v1` now do the same for the query
  workflow execution plane. The gate aggregates repo-side DB-backed durability,
  lease/cancel/timeout/restart-steal semantics, and local worker-run evidence,
  while the live archive gives operator worker supervision, retry, restart, and
  PostgreSQL/HA artifacts one stable verifier-facing bundle shape.
- `ecommerce_deployment_evidence_gate/v1` and
  `ecommerce_live_evidence_archive/v1` now do the same for the commerce data
  and persona surface. The gate wraps the repo-side
  `ecommerce_production_exposure_gate/v1`, while the live archive gives
  operator identity/ABAC, approved fact-import, TLS/NetworkPolicy, and
  Postgres/anchor artifacts one stable verifier-facing bundle shape.
  As of 2026-06-05, `collect_ecommerce_live_rollout.py` now provides the same
  typed `live_rollout_collection_report/v1` entrypoint for this module that
  `spiffe_envoy` and `authority` already had: it records which live e-commerce
  artifacts were actually supplied, archives them, rebuilds the verifier gate,
  and emits a stable `ok|blocked|error` rollout report before public/live
  verification starts.
  As of 2026-06-05, the remaining e-commerce live artifact slots are no longer
  untyped placeholders either: `ecommerce_live_oidc_abac_report/v1`,
  `ecommerce_live_fact_import_report/v1`,
  `ecommerce_live_tls_network_policy_report/v1`,
  `ecommerce_live_postgres_anchor_report/v1`, and
  `ecommerce_logistics_live_rollout_report/v1` now define the verifier-facing
  shape that real public validation should produce.
  As of 2026-06-04, that archive can also carry a verifier-facing
  `live_logistics_rollout_report` artifact for the newly completed
  `delivery_route_legs` / courier / station-operator / last-mile persona slice.
  That remote logistics rollout report is now archived in the local
  authoritative worktree, and the e-commerce gate/closure can therefore report
  `live_status=ok` for `ecommerce` without pretending that the remaining
  identity/import/TLS/Postgres live artifacts already exist.
- `console_deployment_evidence_gate/v1` and
  `console_live_evidence_archive/v1` now do the same for the browser-facing
  console. The gate aggregates repo-side token-storage, same-origin session,
  CSP/security-header, and release reproducibility evidence, while the live
  archive gives operator HTTPS/Secure-cookie, reverse-proxy/OIDC, browser
  exercise, and release-run artifacts one stable verifier-facing bundle shape.
- `control_plane_deployment_evidence_gate/v1` and
  `control_plane_live_evidence_archive/v1` now do the same for the metadata /
  audit / platform-health control plane. The gate aggregates repo-side
  operator-readiness, HTTP malformed-input defense, control-plane read-model
  materialization, and metadata API redaction evidence, while the live archive
  gives operator runbook, metadata/platform API, and reverse-proxy artifacts one
  stable verifier-facing bundle shape.
- `pjc_protocol_security_evidence_gate/v1` and
  `pjc_protocol_live_evidence_archive/v1` now do the same for protocol-security
  claims around malicious participants. The gate aggregates repo-side input
  commitment, signed two-party evidence, and release-binding checks, and it
  explicitly freezes the current claim boundary as `semi_honest_only` unless a
  real malicious-secure component is added.
- `production_security_closure_gate/v1` now sits above those module-level gates
  and aggregates them into one authoritative machine-readable closure report.
  It does not erase module-level boundaries; it summarizes which major surfaces
  are repo-side complete and which still remain live-status `skipped`.
- As of 2026-06-04, the top-level closure also replays the standard
  module-specific live archives when they already exist under `tmp/`, instead of
  silently falling back to repo-side-only gate reruns. In a validated local
  replay, this now lets `ecommerce` surface as `live_status=ok` at the top
  level after the archived logistics rollout report was pulled back from the
  remote VPS, while the remaining modules correctly stay `live_status=skipped`
  until their own operator-side rollout artifacts are supplied.
- `ecommerce`, `console`, and `control_plane` now default to foundation-aware
  live archives. Their current verifier-facing repo-side gates are frozen into
  archive shape by default, so the top-level closure can report
  `live_foundation_status=ok` for those surfaces while `live_status` correctly
  remains `skipped` until operator rollout artifacts exist.
- Current authoritative local evidence now shows fourteen modules with real
  operator-side rollout evidence merged into the verifier-facing top-level
  closure: `ecommerce`, `control_plane`, `observability`, `query_workflow`,
  `postgres_ha`, `supply_chain`, `console`, `pjc_protocol`, and
  `public_two_host`, `legacy_sse`, `privacy_budget`, `recovery_service`, and
  `external_anchor`. `ecommerce` carries the real logistics rollout report;
  `control_plane` carries VPS-backed operator runbook plus live
  metadata/platform API reports; `observability` carries live webhook and
  heartbeat evidence captured from the VPS; `query_workflow` carries VPS-backed
  restart-drill evidence for the DB-backed worker path; `postgres_ha` carries a
  real restore report plus restored metadata API smoke captured from the VPS;
  `supply_chain` carries deployed-code checksum and provenance evidence
  collected directly from the VPS; `console` carries real browser-session and
  release evidence captured from the VPS; `pjc_protocol` carries public-two-host
  live archive evidence plus signed manifest and release-binding reports
  derived from the authoritative two-host evidence set; `public_two_host` now
  auto-consumes the authoritative cross-vps-008 archive and clean
  materialization report to prove completed public two-host rollout evidence;
  `legacy_sse` now carries real VPS socket/route/ingress retirement evidence;
  `privacy_budget` now carries real approval API and duplicate-denial evidence
  combined with already-collected browser-console and PostgreSQL/restore
  evidence; `recovery_service` now carries a real VPS failover report;
  `external_anchor` now carries a real Rekor transparency-log upload report,
  and `pjc_resource_isolation` now also carries refreshed canonical timeout/
  cancel plus streaming-success rollout evidence. `authority` has also crossed
  into verifier-facing `live_status=ok` using real VPS-backed Keycloak,
  OpenFGA, and Vault health evidence, while the remaining blocked module now
  has a typed operator-side collection/blocker report in
  `tmp/spiffe_envoy_live_rollout_collection.json`,
  and `spiffe_envoy` has now also been lifted using real VPS-backed SPIRE +
  Envoy evidence: a positive mTLS echo run, wrong-peer reject, expired-SVID
  reject, trust-bundle reject, and Envoy access log archive. The top-level
  `tmp/production_security_closure_gate/production_security_closure_gate.json`
  now embeds `tmp/final_live_blockers_report.json`, and that blocker report is
  now empty because every module has verifier-facing `live_status=ok`.
5. Collect live GitHub Actions release evidence for the console/supply-chain
   gates.
6. Execute and verify one real external immutable audit anchor path.
7. Revisit protocol claims: explicitly choose semi-honest-only claims or add
   malicious-secure protections.

Use [REMAINING_WORK_IMPLEMENTATION_BACKLOG.md](REMAINING_WORK_IMPLEMENTATION_BACKLOG.md)
for the file/function-level implementation plan, gates, and evidence required
for each item above.
