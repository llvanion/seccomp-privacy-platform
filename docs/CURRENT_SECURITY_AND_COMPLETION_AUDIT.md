# Current Security And Completion Audit

Date: 2026-06-01

This is the current status source of truth for the repository. It is based on a
full first-party implementation inventory plus focused line review of the
security-boundary files surfaced by that inventory. Historical documents remain
useful for implementation detail, but their "complete" wording must be read as
"complete inside the old platform-baseline scope" unless this document says the
same item is production-complete.

Implementation details for all known remaining work are tracked in
[REMAINING_WORK_IMPLEMENTATION_BACKLOG.md](REMAINING_WORK_IMPLEMENTATION_BACKLOG.md).

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
npm --prefix console run typecheck
npm --prefix console run build
python3 -m pytest sse/test
```

Current verification result:

- `bash scripts/check_ci_smoke.sh`: passed.
- `cargo test` in `bridge/`: passed, 10 tests.
- Console checks did not run in this workspace because `console/node_modules`
  is incomplete and no lockfile is present. `npm --prefix console run typecheck`
  failed with `tsc: not found`; `npm --prefix console run build` failed with
  `vite: not found`.
- `python3 -m pytest sse/test` did not run because `pytest` is not installed in
  the active Python environment.

## 2. Direct Answers

| Question | Current Answer |
| --- | --- |
| Is the protocol safe? | Safe only under the current prototype assumptions: local or controlled deployment, honest/semi-honest PJC participants, policy-gated release, input-commitment-checked bridge outputs, and operator-controlled secrets. It is not yet a production-secure protocol against malicious PJC computation/source-data lies, side-channel/differencing attacks beyond the current budget heuristics, exposed legacy SSE WebSocket services without production auth/TLS, or incomplete real-authority deployments. |
| Is functionality complete? | The local demo/mainline is complete enough to run `SSE -> recovery -> bridge -> PJC -> policy release` and verify its contracts. Production platform functionality is not complete: durable workflow, privacy-budget live PostgreSQL/browser deployment evidence, real KMS/authority lifecycle, live resource-isolated PJC worker evidence, public-network mTLS evidence, external immutable audit anchoring, and console release gates remain incomplete or operator-side. |
| Can it stop realistic attacks? | It stops some realistic mistakes and low-effort attacks: raw join-key exchange, production-mode direct token-secret CLI usage, malformed HTTP inputs, duplicate exact queries, default-release privacy-budget double spend, one-time near-duplicate approval consumption, legacy SSE network-pickle RCE, PJC post-bridge CSV/commitment tampering in the repo-side path, some handoff retention risks, and local audit tampering. It does not yet reliably stop malicious-party protocol manipulation, browser token theft after XSS, production MITM/misdeployment without live mTLS evidence, live PJC worker DoS/OOM, or statistical attacks beyond current budget/approval heuristics. |
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
- `sse/API_Docs.md` documents the JSON/base64 protocol.
- `sse/global_config.py` previously defaulted server host to an empty bind
  address; this review changed the default to `127.0.0.1`.

Impact:

- The direct network pickle RCE class is closed in the current code.
- If this legacy/demo WebSocket server is exposed beyond loopback, residual
  risk remains from missing production authentication, service identity,
  transport hardening, rate limits, and deployment policy.

Current status:

- Code-complete for network pickle removal on 2026-06-01.
- Default bind host remains loopback.
- Non-loopback bind still fails closed unless `SSE_ALLOW_LEGACY_PICKLE_WS=1` is
  set as an explicit demo-only override.
- Still open for production: decide whether to retire this legacy API or add
  production-grade authentication, TLS/service identity, abuse limits, and
  deployment gates.

Required fix:

1. Keep `scripts/check_no_network_pickle.py` in CI.
2. Keep `sse/frontend/server/*` classified as local/demo until production auth
   and transport requirements are implemented or the API is retired.
3. Treat remaining trusted-local pickle persistence as a separate lower-priority
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
- `client_value_mode=raw-int` now has committed value policy checks. Bridge
  emits `value_policy`, source summary, and output summary; production raw-int
  requires an explicit max value; validate/preflight recompute the PJC client
  CSV summary and deny negative or above-bound values.
- `docs/PJC_MTLS_OPEN_RISKS.md` still treats production PJC strength and public
  deployment evidence as partial.

Impact:

- The repo-side path now detects accidental or malicious mutation of
  bridge-generated CSVs before PJC execution, detects signed evidence/result
  substitution before public release when the strict release gate config is used,
  and prevents out-of-policy raw integer values from entering PJC.
- This is not a malicious-secure PJC protocol. A participant can still lie about
  its source data before bridge generation, choose adversarial records, or exploit
  repeated/near-duplicate windows unless the release policy and operator controls
  stop that behavior.
- Value range control is software policy validation, not a cryptographic proof.

Current status:

- Repo-side input-commitment gate, signed two-party manifest merge, and
  result-to-release binding are complete and regression-tested.
- Production claims must still say semi-honest/operator-controlled unless a real
  malicious-secure component or range-proof/value-proof package is added.

Required fix:

1. Define the exact adversary model in the protocol doc and product claims.
2. Run live two-host signed evidence and release-gate binding evidence.
3. Add stricter value validation/range proof or explicitly document the
   operational trust assumption.
4. Decide whether the product claims semi-honest security only or adds a
   malicious-secure protocol/component.

### P0-04 PJC Resource Isolation Wrapper Is Repo-Side Fail-Closed

Evidence:

- `run_pjc.sh`, `run_pjc_server_tls.sh`, and `run_pjc_client_tls.sh` now support
  `PJC_PRODUCTION_MODE=1`.
- Production mode fails before launching PJC/socat when `PJC_RESOURCE_LIMITS`
  is missing.
- Production mode rejects `PJC_GRPC_STREAM_CHUNK_ELEMENTS=0` and rejects PJC
  binaries that lack `--grpc_stream_chunk_elements` instead of silently falling
  back to unary.
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
  courier, support, buyer, field marketing, and compliance auditor workflows.
- `serve_metadata_api.py POST /v1/business-access/check` binds the requested
  business role to the authenticated identity and tenant scope.
- `serve_metadata_api.py POST /v1/business-data/read-preview` now enforces the
  same policy before reading e-commerce fact tables: denied fields return HTTP
  403, masked fields return mask markers without selecting raw values, and
  filters cannot override the authorized `scope`.
- Read-preview keeps relationship scope as authorization context and uses a
  narrow SQL filter allowlist; sensitive fields such as buyer email cannot be
  used as filters, reducing mask/deny bypass through existence queries.
- `business_data_read_preview/v1` and `business_access_api_smoke/v1` freeze the
  evidence shape. `scripts/check_business_access_api_smoke.py` covers allow,
  deny, mask, role spoofing, `order_id` filter conflict, and tenant filter
  conflict, plus sensitive-field filter rejection.
- `scripts/validate_ecommerce_fact_import.py` emits
  `ecommerce_fact_import_validation/v1` for candidate JSONL fact imports. The
  smoke covers a valid order import plus denial for hidden address fields, raw
  support transcripts, and negative monetary values.
- `scripts/import_ecommerce_fact_rows.py` now reuses that same validator before
  writing rows, applies metadata migrations, and inserts into the fact table in
  one transaction. `scripts/check_ecommerce_fact_import.py` proves the allowed
  import commits, a sensitive-column candidate is rejected before insert, and a
  duplicate-order batch rolls back without changing the table count.

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
- Full business API, deployed production ETL wiring, browser-console role
  workflow, and external OpenFGA/ABAC parity remain partial.

Required fix:

1. Treat `business-data/read-preview` as the reference gate for every new
   business read endpoint.
2. Use `import_ecommerce_fact_rows.py` or an equivalent validator-first
   transaction in every production ETL/batch import before sensitive business
   rows are accepted into fact tables.
3. Add browser-console workflows and externalized ABAC evidence if production
   claims include direct business-user access.

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
  controls, and live reverse-proxy/OIDC evidence.

Current status:

- Repo-side browser session path and browser security-header gate are complete
  for same-origin deployments. Overall production auth remains partial until
  reverse-proxy/OIDC deployment evidence, Secure-cookie TLS evidence, dependency
  gates, and reproducible console CI/release gates are run live.

Required fix:

1. Serve the console behind HTTPS/TLS with `--session-cookie-secure` and capture
   live browser evidence.
2. Keep CSP/security-header checks in CI and add dependency audit gates.
3. Keep `scripts/check_console_token_storage.py`,
   `scripts/check_console_browser_session.py`, and
   `scripts/check_identity_proxy_auth_smoke.py`, and
   `scripts/check_console_security_headers.py` in CI so token/session/header
   handling cannot regress.

### P1-05 Console Release Gate Is Not Reproducible Here

Evidence:

- No console lockfile was present in the workspace.
- `console/node_modules` existed but lacked working `.bin` executables for
  `tsc` and `vite`.
- `.github/workflows/release.yml` uses `npm install` if no lockfile exists and
  treats typecheck as advisory in release.

Impact:

- Frontend builds are less reproducible, and type errors can avoid blocking a
  release.

Current status:

- Open.

Required fix:

1. Add a committed npm lockfile.
2. Run `npm ci`, `npm run typecheck`, and `npm run build` in CI.
3. Remove advisory/continue-on-error behavior for release typecheck.

### P1-06 Static Identity Token Comparison

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
| Audit log tamper on local host | Partial. | Local chain/seal exists; external immutable anchor must be live. |
| Metadata leakage through read APIs | Improved: identity-backed audit API, operator dashboard, metadata API job/entity reads, console home/jobs/audit/observability/catalog/metadata routes, and public bucket reports receive or render public-summary/redacted schemas with redaction/static gates. | High-sensitivity padding/merge strategy and future metadata entities must stay on the same redaction contract. |
| Browser token theft after XSS | Improved: same-origin console auth now has repo-side HttpOnly/SameSite session-cookie flow, static token-storage gate, and browser-session smoke. | Fallback Bearer token mode remains for cross-origin/debug use; production still needs HTTPS/Secure-cookie evidence, CSP, and dependency/no-inline gates. |
| Exposed legacy SSE WebSocket | Improved: network pickle RCE removed and default bind is loopback. | Still local/demo only until auth, service identity, TLS, rate limits, and deployment gates are added or the service is retired. |

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
npm --prefix console run build
python3 -m pytest sse/test
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
8. Console dependency lockfile and CI build/typecheck gate.

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
5. Add a console lockfile and enforce typecheck/build in CI/release.
6. Execute and verify one real external immutable audit anchor path.
7. Decide whether to retire the legacy SSE WebSocket API or harden it with
   production auth, service identity, TLS, rate limits, and deployment gates.
8. Revisit protocol claims: explicitly choose semi-honest-only claims or add
   malicious-secure protections.

Use [REMAINING_WORK_IMPLEMENTATION_BACKLOG.md](REMAINING_WORK_IMPLEMENTATION_BACKLOG.md)
for the file/function-level implementation plan, gates, and evidence required
for each item above.
