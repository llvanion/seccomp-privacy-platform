# Remaining Work Implementation Backlog

Date: 2026-06-01

This is the implementation-level backlog for all known remaining work. It
answers: what still needs to be built, which source files are involved, what
tests/gates must be added, and what evidence is required before the task can be
called complete.

Current status source:

- [CURRENT_SECURITY_AND_COMPLETION_AUDIT.md](CURRENT_SECURITY_AND_COMPLETION_AUDIT.md)
- [PRODUCTION_SECURITY_COMPLETION_PLAN.md](PRODUCTION_SECURITY_COMPLETION_PLAN.md)
- [PJC_MTLS_OPEN_RISKS.md](PJC_MTLS_OPEN_RISKS.md)
- [PRIVACY_BUDGET_PRODUCTION_CLOSED_LOOP.md](PRIVACY_BUDGET_PRODUCTION_CLOSED_LOOP.md)
- [PRODUCTION_READINESS_GUIDEBOOK.md](PRODUCTION_READINESS_GUIDEBOOK.md)

## Completion Rules

A task is complete only when all of these are true:

1. The unsafe or incomplete path is removed, replaced, or fails closed in
   production mode.
2. An automated gate fails if the problem regresses.
3. Evidence files and commands are recorded.
4. Alternate paths cannot bypass the gate: CLI, HTTP API, dashboard, workflow
   wrapper, and release script must agree.
5. Status wording is precise: `production-complete`, `repo-side complete`,
   `operator-side evidence required`, `partial`, or `planned`.

## Priority Summary

| ID | Priority | Workstream | Current Status |
| --- | --- | --- | --- |
| RW-P0-01 | P0 | Remove or fail-close legacy SSE network pickle protocol | Repo-side production retirement complete; live deployment exposure evidence still operator-side |
| RW-P0-02 | P0 | Transactional privacy-budget consumption and approval close-loop | Repo-side SQLite consume + approval close-loop complete; live Postgres/operator API evidence still partial |
| RW-P0-03 | P0 | PJC malicious-participant boundary and input commitments | Repo-side input-commitment gate complete; malicious-secure protocol still partial |
| RW-P0-04 | P0 | PJC resource isolation and streaming fail-closed production mode | Repo-side wrapper fail-closed complete; live resource-isolated run evidence still partial |
| RW-P0-05 | P0 | Two-host public mTLS/SPIFFE evidence and TLS EOF resolution | Operator evidence missing |
| RW-P0-06 | P0 | Public release gate centralization | Repo-side production pipeline/query-workflow gate complete, including required uploaded external-anchor report binding; live same-run anchor execution remains operator-side |
| RW-P1-01 | P1 | Real KMS/IAM/authority live operation and lifecycle evidence | Repo-side complete, operator-side missing |
| RW-P1-02 | P1 | External immutable audit anchor live write-and-verify | Repo-side tool/gate/release binding complete; live S3/Rekor credentials and upload evidence missing |
| RW-P1-03 | P1 | Metadata leakage controls across all read APIs | Audit API, operator dashboard, metadata API job/entity reads, console home/jobs/audit/observability/catalog/metadata caller-safe views, and public bucket report label/noise redaction complete; high-sensitivity padding/merge strategy partial |
| RW-P1-04 | P1 | Console production auth, token handling, and reproducible CI | Repo-side session/header/release reproducibility gates complete; live HTTPS/OIDC and SBOM/provenance evidence still partial |
| RW-P1-05 | P1 | Production workflow durability and job state lifecycle | Repo-side sidecar + DB execution lifecycle complete; durable worker executor still partial |
| RW-P1-06 | P1 | PostgreSQL/HA/backup/restore live drills | Repo-side SHA-bound backup/restore drill complete; live HA missing |
| RW-P1-07 | P1 | Observability/alerting live operation | Repo-side complete, live missing |
| RW-P1-08 | P1 | Recovery service production deployment hardening | Repo-side production gate complete; live deployment evidence partial |
| RW-P1-09 | P1 | Supply-chain, dependency, SBOM, and full test gates | Repo-side full-test/supply-chain evidence gate complete; external provenance/advisory live evidence remains operator-side |
| RW-P2-01 | P2 | Product/data-model completeness for real e-commerce use | Business field-level policy repo-side; live API/data-model integration partial |
| RW-P2-02 | P2 | Production-scale benchmarks and SLO enforcement | Partial |
| RW-P2-03 | P2 | Documentation status hygiene and stale-claim prevention | In progress |

## RW-P0-01: Remove Or Fail-Close Legacy SSE Network Pickle Protocol

Status on 2026-06-01 / 2026-06-02 / 2026-06-03:

- Network-facing pickle has been removed from the legacy SSE WebSocket client
  and server paths.
- The replacement wire format is implemented in
  `sse/frontend/common/wire.py` as schema `sse.frontend.ws/v1`.
- WebSocket frames are JSON envelopes; bytes are encoded with explicit base64
  markers.
- Structured message content is encoded with `encode_content()` and decoded
  with `decode_content()`, preserving binary fields such as tokens, token
  digests, serialized EDBs, and serialized results.
- `scripts/check_no_network_pickle.py` now fails if `pickle.loads`,
  `pickle.dumps`, `pickle.load`, or `pickle.dump` appears under
  `sse/frontend/server/` or `sse/frontend/client/` except trusted local
  `service_meta` persistence files.
- `sse/global_config.py` still defaults to `127.0.0.1`; explicit wide binding
  still requires `SSE_ALLOW_LEGACY_PICKLE_WS=1` because this API remains a
  legacy/demo interface without production auth or transport hardening.
- `SSE_PRODUCTION_MODE=1` now retires the legacy WebSocket for production. It
  refuses startup on loopback and also refuses the demo wide-bind override.
- `sse/Dockerfile` sets `SSE_PRODUCTION_MODE=1`, so the historical container
  command fails closed instead of opening a production listener.
- `scripts/check_legacy_sse_production_gate.py` emits
  `legacy_sse_production_gate/v1` and is wired into JSON contracts, CI smoke,
  and pre-release gates.

Changed files:

- `sse/frontend/common/wire.py`
- `sse/frontend/server/connector.py`
- `sse/frontend/server/services/service.py`
- `sse/frontend/server/services/comm.py`
- `sse/frontend/client/services/service.py`
- `sse/frontend/client/commands.py`
- `sse/example_usage.py`
- `sse/global_config.py`
- `sse/API_Docs.md`
- `scripts/check_no_network_pickle.py`
- `scripts/check_legacy_sse_production_gate.py`
- `schemas/legacy_sse_production_gate.schema.json`
- `sse/Dockerfile`
- `scripts/check_ci_smoke.sh`

Implementation details retained for future maintainers:

1. `dumps_message()` emits `{"schema": "sse.frontend.ws/v1", "payload": ...}`.
2. `_encode_value()` recursively converts every `bytes` value into
   `{"__sse_wire_type__": "bytes", "base64": "..."}`.
3. `loads_message()` rejects non-JSON, unsupported schema values, invalid
   payload shapes, and invalid base64.
4. `encode_content()` is used for structured `content` dictionaries; raw
   serialized SSE objects still travel as bytes inside the JSON envelope.
5. Internal `sse/schemes/*/structures.py` pickle serialization and
   `frontend/*/services/file_manager.py` local `service_meta` persistence remain
   classified as trusted local persistence. They are not accepted from a socket.
6. Production refusal remains present: `run_server.py start` and
   `frontend.server.connector.run_server` reject non-loopback hosts unless
   `SSE_ALLOW_LEGACY_PICKLE_WS=1`.
7. Production retirement is stronger than the demo bind guard:
   `SSE_PRODUCTION_MODE=1` rejects every legacy WebSocket startup path,
   including loopback and `SSE_ALLOW_LEGACY_PICKLE_WS=1`.

Acceptance gates:

```bash
python3 -m py_compile sse/run_server.py sse/frontend/server/connector.py
python3 scripts/check_no_network_pickle.py
python3 scripts/check_legacy_sse_production_gate.py --out tmp/legacy_sse_production_gate.json
bash scripts/check_ci_smoke.sh
```

Done criteria:

- No network-facing server path uses pickle.
- No matching client command path uses network pickle.
- Non-loopback legacy mode is opt-in and documented as unsafe.
- Production mode retires the legacy WebSocket instead of attempting to harden
  it as a production query API.
- CI prevents network pickle from returning.
- Remaining security work for this API is live/operator evidence that deployed
  production traffic uses query workflow / bridge pipeline APIs and does not
  expose the retired legacy WebSocket.

## RW-P0-02: Transactional Privacy-Budget Consumption And Approval Close-Loop

Status on 2026-06-03:

- The default `policy_release.py` privacy-budget release path now uses a
  transactional SQLite store instead of using the JSONL ledger as the write
  authority.
- Unless `--privacy-budget-disable-transactional-store` is set, enabling
  `--privacy-budget-ledger` also creates/uses a store at
  `<privacy-budget-ledger>.sqlite`; operators may override this with
  `--privacy-budget-store`.
- The store opens a `BEGIN IMMEDIATE` transaction, bootstraps any existing
  `privacy_budget_ledger/v1` JSONL rows into SQL by source-record hash, loads
  prior records for the same scope inside the transaction, evaluates duplicate,
  overlap, missing-scope, and exhausted-budget decisions, then reserves the
  decision before reports become final.
- `privacy_budget_consumption_events` stores scope key, canonical query
  fingerprint, caller/tenant/dataset/purpose, bucket/window, budget cost/limit,
  used before/after, decision, reason, approval ID, job ID, public report hash,
  source JSONL record hash, status, and payload JSON.
- A partial unique index prevents a second committed/reserved allowed consume
  with the same `(scope_key, query_fingerprint)`. JSONL ledger export remains
  for audit compatibility, not as the production write authority.
- If public/operator report or ledger/audit write fails after a store reserve,
  the row is marked `failed_after_reserve` as a compensating failure event
  before the transaction commits.
- `scripts/check_privacy_budget_concurrency.py` launches two concurrent
  releases with budget headroom for one and asserts exactly one `allow` /
  `released=true`, exactly one `privacy_budget_exhausted` deny, two JSONL
  ledger rows, and matching SQL store statuses.
- `migrations/metadata/014_add_privacy_budget_consumption.sql` and the
  PostgreSQL bootstrap DDL both define the same consumption table/read model
  shape for metadata-sidecar parity.
- `privacy_budget_approval_events` persists pending/approved/rejected/expired/
  consumed review state in the same SQLite store. `privacy_budget_approval_decision/v1`
  records approve/reject/expire/consume decisions as JSONL audit events.
- `scripts/manage_privacy_budget_approval.py` bootstraps pending queue records
  into the store, rejects same-identity self approval, writes decision events,
  and transitions requests.
- `serve_operator_dashboard.py` now exposes the same approval state machine
  through authenticated operator HTTP endpoints:
  `GET /v1/privacy-budget/approvals` and
  `POST /v1/privacy-budget/approval/{request_id}/{approve|reject|expire}`.
  The endpoints require resolved identity tokens, enforce tenant/caller view
  scope, reject same-identity approval, require reasons for reject/expire, write
  `privacy_budget_approval_decision/v1` JSONL evidence, and bootstrap pending
  queue/decision logs into the transactional store.
- `policy_release.py --privacy-budget-approval-id` validates an approved
  request inside the same transaction, checks scope/fingerprint/expiry, converts
  the near-duplicate denial into an approved release, reserves budget, writes
  reports/ledger/audit, and marks the approval consumed.
- `scripts/check_privacy_budget_approval_flow.py` proves pending request
  creation, self-approval rejection, approve + one-time consume, and rejected /
  expired approvals being impossible to consume.
- `scripts/check_privacy_budget_approval_api_smoke.py` proves the HTTP approval
  list/approve/reject/expire path and validates the decision log. Its list and
  transition outputs are frozen as `privacy_budget_approval_list/v1` and
  `privacy_budget_approval_transition/v1`.
- The operator console SPA now includes `/privacy-budget-approvals`, with
  filtering, row inspection, and approve/reject/expire actions wired to the
  dashboard endpoints. `console_manifest/v1` includes a
  `privacy_budget_approvals` section and
  `privacy_budget_approval_workflow` feature flag.

Why this still remains partial:

- Query workflow, operator HTTP paths, and the repo-side SPA can pass and
  review privacy-budget queue/store files; deployed browser-console evidence
  against a live environment is still missing.
- The new SQL consumption/approval tables have repository DDL and SQLite
  concurrency/approval evidence; live PostgreSQL/HA deployment evidence is
  still missing.

Files to change:

- `a-psi/moduleA_psi/scripts/policy_release.py`
- `migrations/metadata/013_add_privacy_budget_ledger_read_model.sql`
- `migrations/metadata/014_add_privacy_budget_consumption.sql`
- `scripts/import_run_metadata.py`
- `scripts/query_metadata.py`
- `scripts/submit_query_workflow.py`
- `scripts/serve_operator_dashboard.py`
- `scripts/check_privacy_budget_concurrency.py`
- `scripts/manage_privacy_budget_approval.py`
- `scripts/check_privacy_budget_approval_flow.py`
- `scripts/check_privacy_budget_approval_api_smoke.py`
- `schemas/privacy_budget_approval_decision.schema.json`
- `schemas/privacy_budget_approval_list.schema.json`
- `schemas/privacy_budget_approval_transition.schema.json`

Implemented details:

1. Add transactional budget-consumption tables separate from imported JSONL read
   model. Store scope key, query fingerprint, window, bucket, budget cost/limit,
   used before/after, decision, approval ID, job ID, timestamps, public-report
   hash, source-record hash, status, and payload JSON.
2. SQLite path uses `BEGIN IMMEDIATE` with a short busy-timeout/retry loop
   around WAL/schema initialization. PostgreSQL DDL parity exists; live
   transaction evidence remains open.
3. Exact duplicate prevention is enforced with a uniqueness rule for allowed
   consumed releases under the same scope.
4. Same/contains/contained-by/overlap/unknown-window checks run against SQL
   prior records loaded inside the consume transaction.
5. Allowed releases reserve/consume budget before final report publication.
   Report or ledger write failure after reserve is persisted as
   `failed_after_reserve`.
6. JSONL ledger export is preserved for audit compatibility and metadata import,
   but the default release path no longer trusts JSONL as the write authority.
7. Approval state is stored in `privacy_budget_approval_events`; decision JSONL
   is evidence, not the source of truth.
8. Approved near-duplicate releases consume both budget and approval in one
   transaction; consumed/rejected/expired approvals cannot be reused.

Remaining implementation steps:

1. Add metadata sidecar read queries for approval state if operators need a
   unified metadata API view beyond the dashboard endpoint.
2. Run the same consume semantics against live PostgreSQL/HA storage and record
   evidence.

Acceptance gates:

```bash
python3 scripts/check_privacy_budget_concurrency.py
python3 scripts/check_privacy_budget_approval_flow.py
python3 scripts/check_privacy_budget_approval_api_smoke.py --out-dir tmp/privacy_budget_approval_api_smoke
bash scripts/run_s3_privacy_budget_production_evidence.sh
bash scripts/check_json_contracts.sh
bash scripts/check_ci_smoke.sh
```

Done criteria:

- Two concurrent releases with budget headroom for one result in exactly one
  allowed consume and one deterministic deny.
- Approval queue has approve/reject/expire/consume semantics.
- Query workflow, dashboard/operator API, and release paths use the same budget
  transaction.
- PostgreSQL/live deployment evidence proves the same behavior outside the
  local SQLite gate.

## RW-P0-03: PJC Malicious-Participant Boundary And Input Commitments

Status on 2026-06-01:

- Repo-side input commitments are implemented. The Rust bridge writes
  `input_commitments.json` with schema `pjc_input_commitment/v1` beside
  generated `server.csv` and `client.csv`.
- The commitment records `job_id`, token scope/key version, normalizer,
  source-input hash where available, output CSV hash, output row count, and
  client value summary (`sum`, `min`, `max`, `non_negative`).
- `bridge_job_meta/v1` records `inputs.input_commitment_file` and
  `inputs.input_commitment_sha256`.
- `bridge_audit/v1` and `pjc_audit/v1` carry the input commitment path/hash for
  evidence lookup.
- `validate_bridge_job.py` validates commitment file hash, per-party output CSV
  hash, row count, join-key column, normalizer, and client value metadata.
- `preflight_pjc_job.py` accepts `--input-commitment` and
  `--job-meta` plus `--require-input-commitment`; production PJC wrappers
  require it and deny missing commitments, mismatched CSV hashes, mismatched
  commitment file hashes, and mismatched commitment/job-meta semantics before
  launching PJC.
- `run_sse_bridge_pipeline.sh` passes the bridge commitment into Stage3 PJC and
  passes `job_meta.json` into Stage3 preflight, then records the commitment in
  the PJC audit.
- `scripts/check_pjc_input_commitment.py` verifies the good path, post-bridge CSV
  mutation denial, commitment-hash mutation denial, token-scope mismatch denial,
  normalizer mismatch denial, and normalizer-schema-version mismatch denial.
- `pjc_two_party_signed_run_manifest/v1` is now implemented for Ed25519-signed
  Party A / Party B run manifests. The signed canonical payload binds job id,
  repo commit, local input commitment hash, peer input commitment hash,
  optional bucket-policy/shard-manifest hashes, PJC result hash, policy
  decision, public-report hash, audit-chain hash, and TLS peer identity
  metadata.
- `pjc_two_party_evidence_merge/v1` now verifies signed manifests, cross-matches
  A.local <-> B.peer and B.local <-> A.peer commitment hashes, cross-matches TLS
  identities, cross-matches optional bucket-policy and shard-manifest hashes,
  and rejects result/hash/policy/audit-chain/scope mismatches.
- Bucketed/sharded PJC now has a repo-side production allowlist gate. `bucket_policy/v1`
  validates `job_meta.bucket.outputs`, attribution buckets, and shard manifests,
  computes `bucket_policy_sha256` / `shard_manifest_sha256`, and production
  bucketed/sharded runners fail closed when the policy is missing or drifts.
  Public/operator bucket reports carry the policy hash without publishing the
  allowed label set.
- `release_policy_gate/v1` now has `require_pjc_evidence_merge`; when enabled,
  the gate requires a merge report and a `policy_audit/v1` log and checks that
  the merge result hashes match the released `pjc_result_sha256`.
- `config/release_policy_gate.example.json` is the strict production example
  (`require_pjc_evidence_merge: true`); `config/release_policy_gate.local-contract.example.json`
  keeps local contract fixtures runnable without pretending to have live
  two-party evidence.
- Value policy is now enforced in the repo-side path. `bridge` records
  `value_policy`, `source_value_summary`, and output `value_summary` in
  `pjc_input_commitment/v1`; production `raw-int` requires
  `--client-value-max`, `--client-allowed-value-field`,
  `--client-value-unit`, and currency when the unit is `minor_currency_unit`;
  `validate_bridge_job.py` and `preflight_pjc_job.py` recompute the client CSV
  summary, verify the committed value semantics, and deny negative,
  above-bound, or unallowlisted value fields.

Why this still remains:

- The commitment gate prevents post-bridge artifact tampering; it does not prove
  a party supplied truthful source data before bridge generation.
- The underlying PJC path remains a semi-honest/operational-trust design unless a
  malicious-secure PSI-SUM component, ZK/range proof, or equivalent proof system
  is added. The new signed-manifest path is tamper/result-substitution evidence,
  not a cryptographic proof that a party's pre-bridge source data was truthful.
- Value fields now have production software policy checks for range, allowed
  field, unit, and currency, but they are not a cryptographic range proof. A
  party that controls the source system can still choose false but
  policy-shaped input values.

Files to change:

- `bridge/src/main.rs` for any future commitment fields or bridge hash binding
- `schemas/pjc_input_commitment.schema.json`
- `schemas/bridge_job_meta.schema.json`
- `schemas/bridge_audit.schema.json`
- `schemas/pjc_audit.schema.json`
- `schemas/pjc_preflight.schema.json`
- `a-psi/moduleA_psi/scripts/validate_bridge_job.py`
- `scripts/preflight_pjc_job.py`
- `a-psi/moduleA_psi/scripts/run_pjc*.sh`
- `scripts/run_sse_bridge_pipeline.sh`
- `scripts/write_pjc_audit.py`
- `scripts/serve_operator_dashboard.py` PJC role env allowlist and two-party
  endpoints
- `schemas/pjc_two_party_signed_run_manifest.schema.json`
- `schemas/pjc_two_party_evidence_merge.schema.json`
- `scripts/check_release_policy_gate.py`
- `docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md`

Implemented steps:

1. Added `pjc_input_commitment/v1` per party with CSV SHA-256, row count, value
   summary, normalizer schema version, token scope/key version, tenant/dataset
   scope, bucket scope, and generated CSV digest.
2. The Rust bridge writes commitments next to generated PJC CSVs.
3. Production PJC preflight requires and validates the commitment.
4. Production PJC preflight binds `input_commitments.json` to `job_meta.json`
   when the job meta is available, so standalone wrapper/preflight entrypoints
   cannot accept a semantically drifted commitment that still matches the CSVs.
5. Negative tests cover modified CSV, modified commitment hash, token-scope
   mismatch, normalizer mismatch, normalizer-schema-version mismatch, negative
   values, and over-max values.
6. Bucket/shard negative tests cover unknown bucket labels, bucket-field drift,
   above-policy bucket count, missing bucket policy before production PJC,
   shard targets outside the allowlist, and signed two-party bucket-policy hash
   mismatch.

Remaining implementation steps:

1. Run and archive live two-host evidence for the signed manifest exchange and
   release gate binding.
2. Add live two-host/role-package evidence for value-policy denial and signed
   manifest exchange outside the local smoke harness.
3. Keep public two-host reruns on clean-room staging. The repo now has
   `public_two_host_live_materialization_report/v1` to strip inherited bucket
   outputs before a fresh Party A / Party B run, but a verifier-readable live
   archive still needs to be generated from that clean staging step.
4. Replace raw TCP bucket handoff probes with typed TLS readiness. The current
   clean-room run is already proving multi-bucket success, and the repeated
   `SSL_accept unexpected eof` records on Party A are now attributable to the
   old plain-TCP readiness touch rather than a confirmed workload failure.
5. Update protocol docs to either claim semi-honest plus operational
   commitments or document a real malicious-secure proof/component.

Acceptance gates:

```bash
cargo test
python3 scripts/check_pjc_input_commitment.py
python3 scripts/check_pjc_two_party_smoke.py
python3 scripts/check_release_policy_gate_smoke.py
bash scripts/verify_pjc_preflight_gate.sh
bash scripts/check_ci_smoke.sh
```

Done criteria:

- Release evidence can verify input commitment hashes.
- CSV mutation after bridge output is detected.
- Production PJC cannot start without a valid commitment manifest.
- Docs do not overclaim malicious security.
- For full production-complete status, live two-host signed evidence must be
  archived, value range policy/proof must be added, and the adversary model must
  remain explicit.

## RW-P0-04: PJC Resource Isolation And Streaming Fail-Closed Production Mode

Status on 2026-06-01:

- `a-psi/moduleA_psi/scripts/run_pjc.sh`,
  `a-psi/moduleA_psi/scripts/run_pjc_server_tls.sh`, and
  `a-psi/moduleA_psi/scripts/run_pjc_client_tls.sh` now support explicit
  `PJC_PRODUCTION_MODE=1`.
- In production mode the wrappers fail before launching PJC/socat unless
  `PJC_RESOURCE_LIMITS` is set.
- Production mode forbids `PJC_GRPC_STREAM_CHUNK_ELEMENTS=0` and fails closed
  if the selected PJC binary does not support `--grpc_stream_chunk_elements`.
- `pjc_binary_capability_gate/v1` now also checks whether the selected
  `PJC_BIN_DIR` is really current. If the workspace convenience `bazel-bin`
  directory drifts behind the real Bazel output tree, the gate records a
  `stale_convenience_bazel_bin` / `binary_source_drift` blocker instead of
  letting production wrappers rely on stale artifacts.
- Legacy unary fallback is now explicit demo-only behavior via
  `PJC_ALLOW_LEGACY_UNARY=1`.
- TLS wrappers require `PJC_MTLS_REQUIRE_SESSION_MANIFEST=1` in production
  mode, so reusable-cert legacy mode is not silently accepted.
- Broad TLS server bind (`0.0.0.0`/`::`) in production mode requires explicit
  `PJC_ALLOW_PRODUCTION_WIDE_BIND=1`.
- `scripts/run_sse_bridge_pipeline.sh --production-mode` now requires
  `--pjc-resource-limits`, passes production/preflight env into the Stage3 PJC
  wrapper, and rejects unsupported streaming before wrapper invocation.
- `scripts/verify_pjc_production_fail_closed.sh` verifies missing limits,
  forbidden unary mode, non-loopback plain gRPC, missing session-manifest
  requirement, broad TLS bind without override, and TLS client missing limits.
- `scripts/serve_operator_dashboard.py` now passes `PJC_PRODUCTION_MODE`,
  `PJC_ALLOW_LEGACY_UNARY`, and `PJC_ALLOW_PRODUCTION_WIDE_BIND` through the
  PJC role env allowlist when explicitly requested.

Why this still remains partial:

- This is a wrapper-level fail-closed gate, not live evidence of a full
  resource-isolated worker deployment.
- CPU/memory/pids/no-new-privileges enforcement still needs live systemd,
  Kubernetes, or worker evidence.
- The 1M streaming benchmark and production timeout/cancel drill are still
  separate P1/P2 evidence items.

Files to change:

- `a-psi/moduleA_psi/scripts/run_pjc.sh`
- `a-psi/moduleA_psi/scripts/run_pjc_server_tls.sh`
- `a-psi/moduleA_psi/scripts/run_pjc_client_tls.sh`
- `a-psi/moduleA_psi/scripts/pjc_tls_proxy.py`
- `scripts/preflight_pjc_job.py`
- `scripts/run_sse_bridge_pipeline.sh`
- `scripts/submit_query_workflow.py`
- `schemas/query_workflow_request.schema.json`
- `scripts/serve_operator_dashboard.py`
- `config/pjc_resource_limits*.json` or equivalent
- `scripts/verify_pjc_production_fail_closed.sh`

Implemented details:

1. Add explicit `PJC_PRODUCTION_MODE=1`.
2. In production mode require `PJC_RESOURCE_LIMITS`, preflight report, row/byte
   limits, bucket limits, and session manifest requirement.
3. Reject unsupported streaming in production instead of falling back to unary.
4. Keep unary fallback only for local demo mode with explicit
   `PJC_ALLOW_LEGACY_UNARY=1`.
5. Require explicit wide bind plus mTLS/session checks for production TLS
   listeners.
6. Add negative wrapper tests for missing limits, forbidden unary, broad bind,
   and missing session-manifest requirement.
7. Require pipeline-level `--pjc-resource-limits` in production mode so the
   main orchestrator cannot bypass the wrapper preflight gate.

Remaining implementation steps:

1. Surface preflight report in dashboard job details for every PJC run.
2. Add live worker evidence for CPU/memory/pids/timeouts.
3. Add production streaming success evidence with actual PJC binaries.

Acceptance gates:

```bash
python3 scripts/preflight_pjc_job.py --help
bash scripts/verify_pjc_preflight_gate.sh
bash scripts/verify_pjc_production_fail_closed.sh
bash scripts/check_json_contracts.sh
python3 scripts/check_pjc_two_party_smoke.py
bash scripts/check_ci_smoke.sh
```

Done criteria:

- Production PJC cannot start without passing preflight.
- Production PJC cannot silently downgrade transport/resource behavior.
- Live resource-isolated worker evidence proves limits outside wrapper
  argument validation.

## RW-P0-05: Two-Host Public mTLS / SPIFFE Evidence And TLS EOF Resolution

Why this remains:

- Repo-side two-party helpers exist.
- Real public-network bucketed run evidence now exists for the current
  worktree (`cross-vps-008` clean-room public archive), but the readiness and
  reporting stack must preserve that conclusion by using typed TLS readiness
  instead of raw TCP liveness and by keeping the verifier-facing archive path
  stable.
- SPIFFE/SPIRE + Envoy templates exist but need live evidence.

Files/evidence paths:

- `a-psi/moduleA_psi/scripts/serve_pjc_mtls_enrollment_party_a.sh`
- `a-psi/moduleA_psi/scripts/enroll_pjc_mtls_party_b.sh`
- `a-psi/moduleA_psi/scripts/run_pjc_bucketed_tls_server.sh`
- `a-psi/moduleA_psi/scripts/run_pjc_bucketed_tls_client.sh`
- `scripts/serve_operator_dashboard.py` PJC mTLS endpoints
- `deploy/spiffe_envoy/`
- `handoff/joint_certification/`

Implementation/evidence steps:

1. Keep the completed public clean-room archive (`public_two_host_live_evidence_archive/v1`)
   and `public_two_host_production_readiness_gate/v1` in sync with the current
   worktree.
2. Use `pjc_tls_readiness/v1` rather than raw TCP probes before each bucketed
   public handoff so verifier-facing logs no longer record probe-induced EOF
   noise as if it were a workload blocker.
3. Run SPIFFE/SPIRE + Envoy path or explicitly record operator unavailability.
4. Archive `pjc_two_party_preflight/v1`, `pjc_role_package/v1`,
   `pjc_role_status/v1`, `pjc_two_party_evidence_merge/v1`,
   `pjc_two_party_negative_cases/v1`, `release_policy_gate/v1`, and
   `pjc_tls_diagnostic/v1` / `pjc_tls_readiness/v1` when diagnostics or
   readiness probes were used.

Acceptance gates:

```bash
python3 scripts/check_pjc_two_party_smoke.py
python3 scripts/check_pjc_tls_diagnostic_smoke.py
python3 scripts/check_spiffe_envoy_templates.py --assert-allow
bash handoff/joint_certification/run_joint_certification.sh repo-gates
```

Done criteria:

- Two real hosts produce matching evidence for the same job.
- Current-worktree public clean-room archive proves the completed bucketed mTLS
  run and the readiness gate reports `live_status=ok`.
- Negative cases include wrong token, expired token, wrong CA, wrong peer,
  commit mismatch, modified CSV, and privacy denial.
- TLS EOF is resolved or the task remains open with diagnostic evidence.

## RW-P0-06: Public Release Gate Centralization

Status on 2026-06-01:

- `scripts/check_release_policy_gate.py` is the centralized server-side release
  gate for `release_policy_gate_config/v1`.
- The gate now covers DP metadata/epsilon range, minimum k, privacy-budget
  ledger decision, duplicate-query leak detection, allowed deny reason codes, and
  public-report redaction.
- `scripts/run_sse_bridge_pipeline.sh --production-mode` requires
  `--release-policy-gate-config` and runs `check_release_policy_gate.py` after
  Stage4 policy release. In production mode it uses `--assert-allow`, so the
  pipeline fails before audit-chain completion when the gate denies.
- `run_sse_bridge_pipeline.sh` writes
  `<out-base>/a_psi_run/release_policy_gate.json` by default and passes it into
  `build_audit_chain.py`; `audit_chain/v1` now embeds the release gate report and
  its SHA-256.
- `submit_query_workflow.py` and `query_workflow_request/v1` now accept and
  forward release-gate config/report, DP knobs, `--require-dp`, public-report
  redaction, operator-report path, `pjc_evidence_merge`, and
  `external_anchor_report`.
- `release_policy_gate_config/v1` now supports `require_external_anchor`. The
  strict production example enables it, and `check_release_policy_gate.py` denies
  released reports unless an `external_audit_anchor_report/v1` proves an uploaded
  `s3_worm` or Rekor anchor with verified chain, non-empty immutable reference,
  published records, and no production findings.
- `run_sse_bridge_pipeline.sh`, `submit_query_workflow.py`, and
  `benchmark_pipeline.py` fail closed in production when a strict release-gate
  config requires an external anchor but no report is supplied.
- `scripts/verify_release_policy_gate_pipeline.sh` verifies the production
  pipeline fails closed when the release gate config is missing. The existing
  smoke now covers eleven release-gate cases: missing ledger, low k, missing DP,
  allowed redacted release, duplicate-query leak, operator-only public-field
  leak, bound PJC evidence allow, PJC result replacement denial, missing external
  anchor denial, planned/local external anchor denial, and uploaded S3 Object
  Lock anchor allow.

Why this still remains partial for production:

- Live external-anchor write/verify still requires operator credentials and
  deployed sink evidence. The repo can now require an uploaded anchor report, but
  it cannot manufacture AWS Object Lock/Rekor evidence in this workspace.
- Operator dashboard and caller-safe public summaries now derive visible job
  state from `release_policy_gate/v1`: external-anchor denials surface as
  `pending_external_anchor`, other gate denials surface as `blocked`, and
  release-gate-aware `/v1/runs?state=...` filtering prevents a raw sidecar
  `completed` state from hiding a blocked release.
- Direct manual use of low-level scripts remains possible outside the supported
  production pipeline; production docs must keep treating the pipeline/query
  workflow/dashboard gate as the supported path.

Files to change:

- `a-psi/moduleA_psi/scripts/policy_release.py`
- `a-psi/moduleA_psi/scripts/policy_postprocess_buckets.py`
- `a-psi/moduleA_psi/scripts/run_bucketed_scale_test.sh`
- `scripts/check_release_policy_gate.py`
- `scripts/run_sse_bridge_pipeline.sh`
- `scripts/submit_query_workflow.py`
- `scripts/serve_operator_dashboard.py`
- `scripts/build_audit_chain.py`
- `scripts/verify_release_policy_gate_pipeline.sh`
- `schemas/release_policy_gate_config.schema.json`
- `schemas/query_workflow_request.schema.json`
- `schemas/audit_chain.schema.json`
- public/operator report schemas

Implemented steps:

1. Defined one repo-side release gate covering k threshold, DP requirement,
   privacy-budget ledger, duplicate-query leak, deny reason allow-list, and
   public report redaction.
2. Made production pipeline completion depend on the release gate.
3. Added query-workflow forwarding so API/dry-run submission cannot omit the
   production gate fields when using structured requests.
4. Embedded release-gate evidence in `audit_chain/v1`.
5. Added bypass negative tests for missing budget, no DP, low k, duplicate leak,
   operator-only public report fields, missing production pipeline gate config,
   PJC result replacement, missing external anchor, and planned/local anchor
   reports.
6. Bound uploaded external immutable anchor evidence into the final release gate.
7. Made dashboard job snapshots, public summaries, and run-history filtering
   release-gate-aware so blocked or anchor-pending releases do not present as
   completed.

Remaining implementation steps:

1. Run and archive live S3 Object Lock/Rekor upload evidence with operator
   credentials, then pass that report into the final release gate.

Acceptance gates:

```bash
python3 scripts/check_release_policy_gate_smoke.py
bash scripts/verify_release_policy_gate_pipeline.sh
bash scripts/check_json_contracts.sh
bash scripts/check_ci_smoke.sh
```

Done criteria:

- No documented production path can write a completed public report without a
  passing release gate.
- Production pipeline refuses to run without release-gate config.
- Audit chain embeds the release-gate report.

## RW-P1-01: Real KMS / IAM / Authority Live Operation

Why this remains:

- Keycloak, OpenFGA, Vault, Vault PKI, AWS KMS, and external KMS adapters exist.
- Default smoke uses offline, dry-run, mock, or local-service paths.
- Production needs live rotation, revocation, and authorization evidence.

Files/tools:

- `docker-compose.authority.yml`
- `config/keycloak_realm_seccomp_privacy.json`
- `config/openfga_authorization_model.json`
- `config/vault_http_client.example.json`
- `config/keyring.production.example.json`
- `scripts/request_oidc_client_credentials.py`
- `scripts/setup_openfga_model.py`
- `scripts/check_openfga_authz.py`
- `scripts/check_authority_governance.py`
- `scripts/check_kms_reachability.py`
- `scripts/issue_mtls_certs.py`
- `scripts/cloud_kms_adapter.py`

Implementation/evidence steps:

1. Run live Keycloak/OpenFGA/Vault/cloud KMS.
2. Import realm/model/policies.
3. Issue and verify live OIDC tokens through JWKS.
4. Run OpenFGA allow and deny checks.
5. Resolve secrets through Vault/AppRole or cloud KMS without env fallback.
6. Rotate a key, disable the old version, prove disabled version cannot be used.
7. Archive identity, authz, KMS reachability, key access audit, rotation log,
   disabled-version deny, and pipeline public report.

Acceptance gates:

```bash
bash scripts/verify_production_kms_gate.sh
python3 scripts/check_authority_governance.py --help
python3 scripts/check_kms_reachability.py --production-mode ...
```

Done criteria:

- Live authority evidence exists and local/mock-only authority is rejected in
  production mode.

## RW-P1-02: External Immutable Audit Anchor Live Write-And-Verify

Why this remains:

- S3 Object Lock and Rekor paths are scaffolded and local production gates reject
  `file_ledger`, dry-run, and unuploaded external reports.
- The strict release gate can now require a schema-valid uploaded S3/Rekor anchor
  report before a public release is allowed.
- Live S3/Rekor execution is not present in this workspace.
- Local file ledger is not production immutability.

Files/tools:

- `scripts/publish_external_audit_anchor.py`
- `scripts/verify_external_audit_anchor_gate.sh`
- `scripts/archive_audit_bundle.py`
- `scripts/verify_audit_bundle.py`
- `docs/AWS_S3_WORM_INTERFACE_STATUS.md`

Implementation/evidence steps:

1. Provision a real external sink: S3 Object Lock COMPLIANCE bucket, Rekor, or
   deployment-equivalent immutable ledger.
2. Publish with `--execute`.
3. Read back and verify content, object version/log index, tenant path, and
   audit-chain hash.
4. Prove local file ledger and planned mode are rejected in production.
5. Link anchor result to production release gating. Repo-side binding is now
   implemented; the remaining work is live evidence from the external sink.

Acceptance gates:

```bash
bash scripts/verify_external_audit_anchor_gate.sh --keep-out-dir
python3 scripts/publish_external_audit_anchor.py --production-mode --sink-kind s3_worm --execute ...
```

Done criteria:

- Evidence contains uploaded/verified external status, immutable identifier,
  and negative tamper/local-file reports.

## RW-P1-03: Metadata Leakage Controls Across All Read APIs

Status on 2026-06-01:

- Audit/public-report HTTP read surfaces now distinguish operator evidence from
  caller-safe views.
- `scripts/serve_audit_query_api.py` keeps full `audit_chain/v1`,
  `pipeline_observability/v1`, and `catalog_lineage/v1` available to legacy
  shared-token local smoke and to identity-backed `platform_admin` /
  `platform_auditor` callers.
- Identity-backed non-privileged callers receive public summaries instead:
  `audit_chain_public_summary/v1`,
  `pipeline_observability_public_summary/v1`, and
  `catalog_lineage_public_summary/v1`.
- The public report API now applies a strict allowlist before returning
  `public_report/v2` and marks the response with
  `operator_fields_redacted: true`.
- `scripts/check_audit_api_public_redaction.py` recursively rejects
  operator-only keys in caller-safe audit API responses, including raw audit
  arrays, artifact paths, hashes, exact row counts, detailed timing,
  `bridge`, `details`, and query fingerprints.
- `scripts/materialize_platform_api_smoke_reports.py` now materializes
  identity-backed public-report, audit-chain, observability, and catalog-lineage
  calls for a normal caller.
- `scripts/check_platform_api_smoke_reports.py` validates those normal-caller
  responses use public-summary schemas and pass the recursive leak scan.
- `scripts/check_json_contracts.sh` validates the new schemas and runs the
  public-redaction gate.
- `serve_operator_dashboard.py GET /v1/dashboard` now requires auth when
  dashboard auth/identity auth is configured. Normal identity callers receive
  `operator_dashboard_public_summary/v1`; full operator dashboard output is
  role-gated to `platform_admin`, `platform_auditor`, `privacy_operator`, and
  `compliance_auditor`.
- `scripts/check_operator_dashboard_public_summary.py` verifies unauthenticated
  dashboard denial, normal-caller redaction, privileged full view, and denial
  for normal callers attempting to bypass via `/v1/runs`,
  `/v1/jobs/{job_id}`, `/v1/jobs/{job_id}/result`, or direct `/v1/jobs/start`.
- `console/src/routes/home.tsx` and `console/src/routes/jobs.tsx` now branch on
  `operator_dashboard_public_summary/v1` and render only coarse summary fields
  for normal callers. `scripts/check_console_dashboard_public_summary.py` and
  `console_dashboard_public_summary_check/v1` block regressions where those
  routes read un-narrowed full dashboard fields.
- `console/src/api/sidecars.ts` now unwraps `audit_query_api_response/v1.result`
  before rendering. `console/src/routes/audit.tsx`,
  `console/src/routes/observability.tsx`, and `console/src/routes/catalog.tsx`
  branch on `audit_chain_public_summary/v1`,
  `pipeline_observability_public_summary/v1`, and
  `catalog_lineage_public_summary/v1`, rendering caller-safe summaries instead
  of raw audit events, paths, hashes, row/timing fields, or lineage artifacts.
  `scripts/check_console_audit_public_summary.py` and
  `console_audit_public_summary_check/v1` freeze this route-level guard.
- `scripts/serve_metadata_api.py` now redacts identity-backed normal-caller job
  list, job detail, caller-permissions, and policy-bindings responses into a
  `caller_safe_metadata_summary` view. It strips paths, hashes, exact timing,
  raw counts, secret/backend refs, artifact payloads, and operator-only fields
  while preserving caller-safe scope and permission-summary context.
- `scripts/check_metadata_api_public_redaction.py` and
  `metadata_api_public_redaction_check/v1` are wired into
  `scripts/check_json_contracts.sh`; the platform API smoke materializes normal
  caller metadata payloads and validates the redaction marker.
- `console/src/api/sidecars.ts` unwraps `metadata_api_response/v1.result`, and
  console catalog/permissions routes display metadata redaction notices instead
  of treating the envelope as a full operator payload.
- `policy_postprocess_buckets.py` now writes release-safe
  `bucket_public_report/v1` and operator-only `operator_bucket_report/v1`.
  Public bucket output omits below-k bucket labels/counts, redacts exact bucket
  sizes and sampled `dp_noise`, and keeps raw/noise evidence only in the
  operator report. `scripts/check_bucket_dp_smoke.py` plus JSON contract
  validation reject regressions.

Why this still remains partial:

- Public report redaction exists for key fields.
- Audit API caller-safe views are role-gated and regression-tested. The
  operator dashboard HTTP entrypoint, identity-backed metadata API job/entity
  reads, and console home, jobs, audit, observability, catalog, permissions
  metadata paths now have a caller-safe summary/redaction path.
- Tiny bucket/shard metadata can still leak if future dashboard, metadata, or
  console views add exact bucket distributions without going through the same
  allowlist discipline.
- High-sensitivity deployments may still choose padding, delayed release, or
  automatic merge-to-other; the repo-side public report no longer exposes
  below-k labels or sampled DP noise.

Files to change:

- `a-psi/moduleA_psi/scripts/policy_release.py`
- `a-psi/moduleA_psi/scripts/policy_postprocess_buckets.py`
- `scripts/serve_audit_query_api.py`
- `scripts/materialize_platform_api_smoke_reports.py`
- `scripts/check_platform_api_smoke_reports.py`
- `scripts/check_audit_api_public_redaction.py`
- `scripts/serve_metadata_api.py`
- `scripts/query_metadata.py`
- `scripts/serve_operator_dashboard.py`
- `scripts/check_operator_dashboard_public_summary.py`
- `scripts/check_console_dashboard_public_summary.py`
- `scripts/check_console_audit_public_summary.py`
- `scripts/check_metadata_api_public_redaction.py`
- `console/src/routes/*`
- `schemas/public_report.schema.json`
- `schemas/audit_chain_public_summary.schema.json`
- `schemas/pipeline_observability_public_summary.schema.json`
- `schemas/catalog_lineage_public_summary.schema.json`
- `schemas/operator_dashboard_public_summary.schema.json`
- `schemas/operator_dashboard_public_summary_smoke.schema.json`
- `schemas/console_dashboard_public_summary_check.schema.json`
- `schemas/console_audit_public_summary_check.schema.json`
- `schemas/metadata_api_public_redaction_check.schema.json`
- `schemas/bucket_public_report.schema.json`
- `schemas/operator_bucket_report.schema.json`

Implementation steps:

1. ~~Maintain strict public-report allowlist.~~ Done for audit API public report.
2. ~~Split caller-safe audit/operator evidence schemas for audit-chain,
   observability, and catalog-lineage read surfaces.~~ Done for audit API.
3. Decide and implement any high-sensitivity padding, delayed-release, or
   automatic merge-to-other policy beyond report-layer bucket redaction.
4. ~~Add regression scan for operator-only keys in public audit API payloads.~~
   Done for audit API, operator dashboard, and console
   home/jobs/audit/observability/catalog plus metadata API public/redacted
   payload handling.

Acceptance gates:

```bash
python3 scripts/check_bucket_dp_smoke.py
python3 scripts/check_platform_api_smoke_reports.py ...
python3 scripts/check_audit_api_public_redaction.py ...
python3 scripts/check_metadata_api_public_redaction.py ...
python3 scripts/check_bucket_dp_smoke.py ...
bash scripts/check_json_contracts.sh
```

Done criteria:

- Normal caller audit API responses do not contain raw row counts, frame
  counts, bucket distributions, file paths, hashes, detailed timing, raw audit
  arrays, or debug fields.
- Normal caller operator dashboard responses do not contain artifact paths,
  hashes, raw artifact lists, or exact intersection results.
- Normal caller cannot bypass through dashboard runs/job detail/result/direct
  start endpoints when dashboard auth is configured.
- Console home/jobs routes render dashboard public summaries without reading
  un-narrowed full dashboard fields.
- Console audit/observability/catalog routes render audit public summaries
  without reading un-narrowed full audit event or lineage fields.
- Metadata API/console normal-caller paths render redacted metadata summaries
  without paths, hashes, exact timing, raw counts, secret refs, or artifact
  payloads.
- Public bucket reports omit below-k labels/counts, exact bucket sizes, and
  sampled DP noise; operator bucket reports retain full evidence.
- Remaining completion requires a production choice for optional padding,
  delayed release, or automatic bucket merge in high-sensitivity deployments.

## RW-P1-04: Console Production Auth, Token Handling, And Reproducible CI

Why this remains:

- `console/src/api/config.ts` no longer stores bearer tokens in `localStorage`;
  it persists only sidecar base URLs. Bearer tokens remain available only as a
  session-only fallback for cross-origin/debug sidecars.
- Same-origin console auth now has a repo-side HttpOnly/SameSite session path:
  `serve_operator_dashboard.py` exposes `/v1/session/login|logout` and
  `/v1/session`, sets `seccomp_identity_session` with `HttpOnly` and
  `SameSite=Strict`, and `console/src/api/client.ts` sends
  `credentials: "same-origin"`.
- `api_identity.py` and `serve_identity_proxy.py` both accept the same session
  cookie; the proxy now fails closed when identity auth is configured and strips
  spoofed `X-Identity-*` headers before injecting resolved identity.
- `scripts/check_console_token_storage.py` and
  `console_token_storage_check/v1` now block regressions that write token,
  Bearer, or Authorization material to `localStorage`, and assert same-origin
  credentials are sent.
- `scripts/check_console_browser_session.py` and
  `console_browser_session_check/v1` verify the HttpOnly session flow.
- `scripts/check_identity_proxy_auth_smoke.py` and
  `identity_proxy_auth_smoke/v1` verify proxy fail-closed, spoofed-header
  overwrite, and cookie-only proxy auth.
- `serve_operator_dashboard.py` now emits CSP/security headers on JSON API and
  SPA static responses. `script-src`, `style-src`, and `connect-src` are
  same-origin only with no `unsafe-inline` or `unsafe-eval`, framing and object
  embedding are blocked, and Secure-cookie mode emits HSTS.
- `scripts/check_console_security_headers.py` and
  `console_security_headers_check/v1` verify `/healthz`, `/v1/dashboard`, SPA
  index/asset headers, HSTS under `--session-cookie-secure`, and a source scan
  that rejects inline style/raw HTML sinks in `console/src`.
- `console/package-lock.json` is now committed and checked against
  `console/package.json`.
- `.github/workflows/release.yml` installs with `npm ci`, runs blocking
  typecheck, and builds with `npm run build:strict`.
- `.github/workflows/json-contracts.yml` now runs Node 20, console `npm ci`,
  typecheck, and strict build before the repo smoke.
- `scripts/check_console_release_gate.py` and
  `console_release_gate_check/v1` reject workflow or lockfile regressions,
  including `npm install` fallback and advisory release typecheck.

Files to change:

- `console/package.json`
- new `console/package-lock.json`
- `console/src/api/config.ts`
- `console/src/api/client.ts`
- `console/src/routes/settings.tsx`
- `scripts/api_identity.py`
- `scripts/serve_operator_dashboard.py`
- `scripts/serve_identity_proxy.py`
- `scripts/check_console_token_storage.py`
- `scripts/check_console_browser_session.py`
- `scripts/check_console_security_headers.py`
- `scripts/check_identity_proxy_auth_smoke.py`
- `schemas/console_token_storage_check.schema.json`
- `schemas/console_browser_session_check.schema.json`
- `schemas/console_security_headers_check.schema.json`
- `schemas/identity_proxy_auth_smoke.schema.json`
- `.github/workflows/json-contracts.yml`
- `.github/workflows/release.yml`
- `console/package-lock.json`
- `scripts/check_console_release_gate.py`
- `schemas/console_release_gate_check.schema.json`

Implementation steps:

1. ~~Commit a clean lockfile.~~ Done:
   `console/package-lock.json` is committed and validated by
   `console_release_gate_check/v1`.
2. ~~Use `npm ci` in CI and release.~~ Done:
   release and CI workflows use `npm ci`, and the release gate rejects
   `npm install` fallback.
3. ~~Make `npm run typecheck` blocking.~~ Done:
   release typecheck no longer uses `continue-on-error`.
4. ~~Add `npm run build` to normal CI.~~ Done:
   normal CI runs `npm --prefix console run build:strict`.
5. ~~Remove cross-session `localStorage` token persistence from the SPA.~~ Done:
   base URLs persist, bearer tokens are session-only fallback.
6. ~~Replace same-origin production token handling with backend session /
   HttpOnly/SameSite cookie.~~ Repo-side done:
   `console_browser_session_check/v1` verifies login emits an HttpOnly cookie
   and cookie-only dashboard reads work.
7. ~~Add CSP/security-header production serving policy.~~ Repo-side done:
   `console_security_headers_check/v1` verifies CSP, no script/style
   inline/eval, same-origin connect-src, anti-framing, no-sniff, referrer,
   permissions policy, source-level inline-style/raw-HTML rejection, and HSTS
   in Secure-cookie mode.

Acceptance gates:

```bash
npm --prefix console ci
npm --prefix console run typecheck
npm --prefix console run build:strict
python3 scripts/check_console_release_gate.py
bash scripts/check_ci_smoke.sh
```

Done criteria:

- Console dependencies are reproducible.
- TypeScript failures block release.
- Browser bearer tokens are not persisted in `localStorage`.
- Same-origin browser session auth has repo-side HttpOnly/SameSite evidence.
- Full production completion also requires `--session-cookie-secure` behind TLS,
  live OIDC/reverse-proxy evidence, live release run evidence, and
  SBOM/provenance/dependency-advisory gates.

## RW-P1-05: Production Workflow Durability And Job State Lifecycle

Why this remains:

- Query workflow, receipts, approval DB rows, and dashboard jobs exist.
- Query workflow sidecars now fail closed against accidental overwrite:
  `submit_query_workflow.py` refuses duplicate dry-run/execute on an existing
  out_base, while allowing `execute` to claim only a matching accepted dry-run.
- Metadata DB execution lifecycle rows now record execute claim, lease owner,
  lease expiry, heartbeat timestamp, terminal state, and artifact paths in
  `query_workflow_executions`.
- `submit_query_workflow.py --execute` can write DB-backed lifecycle state via
  `--metadata-db-path` / `--metadata-db-dsn`.
- `serve_query_workflow_api.py --allow-execute` can write the same lifecycle
  rows via `--workflow-execution-db-path` / `--workflow-execution-db-dsn`.
- `serve_operator_dashboard.py` writes the same lifecycle rows for approved
  request launches when a metadata DB is configured.
- `submit_query_workflow.py --enqueue`, the query workflow API enqueue endpoint,
  and `serve_operator_dashboard.py --enqueue-approved-requests` can now queue
  approved work in `query_workflow_executions` instead of running it inside the
  submitter or HTTP request thread.
- `scripts/run_query_workflow_worker.py` claims queued rows, owns the lease,
  heartbeats, writes sidecar status/receipts, honors DB cancellation requests,
  enforces timeout termination, and can steal expired leases after a worker
  crash/restart.
- `scripts/cancel_query_workflow_execution.py` records operator cancellation
  requests against the DB-backed execution row and writes matching sidecar
  receipt/status evidence for queued cancellations.
- `serve_operator_dashboard.py` uses the same guard before starting approved
  async jobs or relaunches.
- `scripts/check_query_workflow_durability.py` emits
  `query_workflow_durability_check/v1` and proves duplicate dry-run denial,
  execute-from-accepted receipt preservation, duplicate execute denial,
  stale-running visibility, retry/status schema validity, active duplicate DB
  claim denial, terminal replay denial, expired-lease steal semantics,
  enqueue-to-worker completion, queued cancellation, running cancellation,
  timeout termination, and expired-lease worker restart, including cancelled
  takeover when a dead worker leaves a `cancel_requested` lease.
- Orchestration is still local-process/subprocess oriented.
- Live deployed worker supervision and PostgreSQL/HA evidence remain incomplete.

Files to change:

- `scripts/submit_query_workflow.py`
- `scripts/serve_query_workflow_api.py`
- `scripts/serve_operator_dashboard.py`
- `migrations/metadata/*workflow*`
- `scripts/list_query_workflow_status.py`
- `scripts/check_workflow_retry_eligibility.py`
- `scripts/query_workflow_execution_store.py`
- `scripts/run_query_workflow_worker.py`
- `scripts/cancel_query_workflow_execution.py`
- `scripts/check_query_workflow_durability.py`
- `migrations/metadata/015_add_query_workflow_executions.sql`
- `schemas/query_workflow_durability_check.schema.json`
- optional Temporal/Celery/RQ-style worker wrapper for later managed queues

Implementation steps:

1. Make metadata DB the durable source of truth for submission, approval,
   execution, retry, cancellation, and terminal state.
2. ~~Enforce sidecar-level duplicate start/overwrite refusal by out_base/job
   ID/request digest.~~ Repo-side done for the file-sidecar path:
   `assert_workflow_sidecar_start_allowed()` rejects overwriting existing
   running/terminal state and allows execute to claim only a matching accepted
   dry-run.
3. ~~Add repo-side execution claim/lease/heartbeat/terminal rows in metadata
   DB.~~ Done for CLI execute, query workflow API execute, and operator
   dashboard approved launches through `query_workflow_executions`.
4. ~~Move long-running work out of HTTP request threads.~~ Repo-side done:
   `--enqueue`/`/enqueue`/`--enqueue-approved-requests` persist queued work for
   `scripts/run_query_workflow_worker.py`.
5. ~~Add worker heartbeat ownership, cancellation, timeout, and stale-running
   recovery.~~ Repo-side local worker done; live deployment evidence remains.
6. ~~Keep sidecar JSON artifacts as audit outputs, not sole job state.~~ Done:
   DB rows are the lifecycle source for queued/running/terminal ownership, while
   sidecar JSON remains the audit artifact.
7. ~~Add crash/restart tests for worker death and duplicate start.~~ Repo-side
   done for expired-lease restart steal and duplicate/terminal replay denial.
8. Add live multi-worker retry policy evidence after launch failure, and prove
   it against PostgreSQL/HA rather than only SQLite/local subprocesses.

Acceptance gates:

```bash
python3 scripts/verify_operator_shell_regression.py
python3 scripts/check_operator_request_submission_smoke.py
python3 scripts/check_query_workflow_durability.py --out tmp/query_workflow_durability_check.json
bash scripts/check_json_contracts.sh
```

Done criteria:

- Repo-side current state: duplicate or accidental re-run cannot silently
  overwrite query workflow sidecar evidence; execute/enqueue paths can persist
  queued/claim/lease/heartbeat/cancel/timeout/terminal state to metadata DB
  rows; a local worker can own and complete/cancel/timeout/restart executions.
- Full production done criteria: process crash cannot silently lose or
  duplicate an approved job because supervised deployed workers own DB leases,
  emit heartbeats, support cancellation/timeout/retry, and demonstrate restart
  recovery against live PostgreSQL/HA on the target hosts.

## RW-P1-06: PostgreSQL / HA / Backup / Restore Live Drills

Why this remains:

- DDL, HA topology, Patroni, pgBouncer, backup, and restore helpers exist.
- Repo-side backup/restore integrity evidence now exists:
  `restore_metadata_db.py` can bind a restore to `metadata_db_backup_report/v1`
  `backup.sha256`, and `scripts/check_metadata_backup_restore_drill.py` proves
  backup verification, SHA-bound restore, restored probe-row presence,
  portability check, and tampered-backup denial.
- Live switchover, pooling behavior, restore drill, and chaos evidence are
  operator-side.

Files/tools:

- `config/postgres-ha/`
- `config/patroni-ha/`
- `config/pgbouncer/`
- `scripts/render_postgres_ha_topology.py`
- `scripts/render_patroni_failover_topology.py`
- `scripts/render_pgbouncer_topology.py`
- `scripts/backup_metadata_db.py`
- `scripts/restore_metadata_db.py`
- `scripts/test_metadata_db_failover.py`
- `scripts/check_metadata_backup_restore_drill.py`
- `schemas/metadata_backup_restore_drill.schema.json`

Implementation/evidence steps:

1. ~~Bind restore to a backup report/hash and reject tampered backups.~~
   Repo-side done: `restore_metadata_db.py --backup-report` checks the current
   backup SHA-256 before restore.
2. ~~Run local backup-to-restore probe-row drill.~~ Done:
   `metadata_backup_restore_drill/v1` proves restored `jobs`/`audit_events`
   probe rows and schema portability.
3. Run PostgreSQL primary/replica with real credentials.
4. Run Patroni switchover/failover and record downtime.
5. Route reads through replica DSN and writes to primary.
6. Run pgBouncer transaction pooling and verify long-write bypass.
7. Backup to external storage and restore into a fresh DB.
8. Run metadata API/query smoke against restored DB.

Acceptance gates:

```bash
POSTGRES_DSN=... bash scripts/check_json_contracts.sh
python3 scripts/test_metadata_db_failover.py --help
python3 scripts/backup_metadata_db.py --execute ...
python3 scripts/restore_metadata_db.py --execute ...
python3 scripts/check_metadata_backup_restore_drill.py --out tmp/metadata_backup_restore_drill.json
```

Done criteria:

- Repo-side current state: SQLite metadata backup/restore is SHA-bound to its
  backup report, schema-portability checked, and tampered backup files are
  rejected before restore.
- Full production done criteria: live failover and restore evidence exist, and
  restored PostgreSQL/HA DB passes query/API smoke against the target
  environment.

## RW-P1-07: Observability / Alerting Live Operation

Why this remains:

- Grafana/Tempo/Prometheus configs and alert scripts exist.
- Live Tempo push, Grafana dashboard render, Slack/Alertmanager delivery, and
  operator walkthrough evidence are missing.

Files/tools:

- `config/observability/`
- `scripts/export_otel_events.py`
- `scripts/check_observability_alerts.py`
- `scripts/dispatch_alert_webhook.py`
- `scripts/run_alert_daemon.py`
- `console/src/routes/observability.tsx`

Implementation/evidence steps:

1. Start live observability services.
2. Push a real pipeline trace to Tempo.
3. Render Grafana dashboards and prove panels are non-empty.
4. Trigger firing -> resolved alert transition.
5. Send webhook to Slack or Alertmanager-compatible receiver.
6. Record screenshots or JSON evidence plus exact service versions.

Acceptance gates:

```bash
python3 scripts/check_observability_alerts.py --help
python3 scripts/dispatch_alert_webhook.py --help
python3 scripts/run_alert_daemon.py --help
```

Done criteria:

- Operators can inspect a real run and receive at least one alert transition.

## RW-P1-08: Recovery Service Production Deployment Hardening

Why this remains:

- Recovery service has Unix/HTTP transports, authz, request signing, mTLS,
  metrics, systemd rendering, and failover tests.
- Repo-side production HTTP startup is now fail-closed: direct HTTP adapter,
  standalone launcher, and `manage_record_recovery_service.py start` /
  `render-systemd` all call the same production gate.
- Full production still needs live dedicated service-user evidence, live
  sandbox evidence, host firewall or Kubernetes NetworkPolicy evidence, and
  deployed public-network mTLS traffic evidence.

Files/tools:

- `services/record_recovery/`
- `services/record_recovery/production.py`
- `scripts/run_record_recovery_service.py`
- `scripts/manage_record_recovery_service.py`
- `scripts/check_record_recovery_production_gate.py`
- `schemas/record_recovery_production_gate_check.schema.json`
- `scripts/test_failover_recovery_service.py`
- `config/k8s/`
- generated systemd units

Implementation steps:

1. Deploy under dedicated OS user with rendered systemd hardening.
2. Verify `ReadWritePaths` are minimal for the configured tenant/service.
3. ~~Enforce mTLS or signed requests for HTTP transport in production.~~
   Repo-side done: production HTTP requires request authentication, authz
   policy, and either signed requests or mTLS client certificates; non-loopback
   listeners require mTLS client certificates.
4. Apply Kubernetes NetworkPolicy or host firewall.
5. Run failover test against two service instances.
6. Keep compatibility entrypoints routed to the managed launcher or marked
   non-production unless they pass the same production gate.

Acceptance gates:

```bash
python3 scripts/check_record_recovery_production_gate.py --out tmp/record_recovery_production_gate_check.json
python3 scripts/test_failover_recovery_service.py
python3 scripts/check_recovery_service_deployment_evidence_gate.py --out-dir tmp/recovery_service_deployment_evidence_gate
bash scripts/check_json_contracts.sh
```

Done criteria:

- Repo-side current state: production-mode HTTP recovery cannot start or render
  an unsafe unit when request auth, authz, signed-request/mTLS, identity
  metadata DB, or public-listener mTLS controls are missing.
- This boundary is now packaged as `recovery_service_deployment_evidence_gate/v1`
  plus `recovery_service_live_evidence_archive/v1`. Remaining work is the live
  archive contents, not another round of repo-side deployment-gate scaffolding.
- Full production done criteria: production traffic cannot reach an
  unauthenticated or non-mTLS public recovery endpoint, and this is backed by
  live service-user, sandbox, network-policy/firewall, and deployed mTLS
  evidence.

## RW-P1-09: Supply-Chain, Dependency, SBOM, And Full Test Gates

Why this remains:

- Repo-side full-test/supply-chain evidence is now implemented:
  `sse/requirements-dev.txt` declares pytest, CI runs `python3 -m pytest
  sse/test`, console release/CI uses `npm ci` plus strict typecheck/build,
  `scripts/check_console_release_gate.py` blocks console workflow regressions,
  and `scripts/check_supply_chain_gate.py` emits a schema-validated
  `supply_chain_evidence/v1` report with Python/npm/Cargo component inventory,
  artifact hashes, local provenance materials, and advisory-policy status.
- This is still not external provenance or live advisory enforcement. Production
  completion needs a real CI/release run artifact, signed/provenance-backed
  release materials, and either online or pinned-offline advisory checks.

Files to change:

- `.github/workflows/json-contracts.yml`
- `.github/workflows/release.yml`
- `sse/requirements.txt`
- `sse/requirements-dev.txt`
- `console/package-lock.json`
- `bridge/Cargo.lock`
- `scripts/check_console_release_gate.py`
- `scripts/check_supply_chain_gate.py`
- `schemas/console_release_gate_check.schema.json`
- `schemas/supply_chain_evidence.schema.json`

Implementation steps:

1. ~~Make Python test dependencies explicit.~~ Done:
   `sse/requirements-dev.txt` pins `pytest`.
2. ~~Add `python3 -m pytest sse/test` to CI.~~ Done:
   `.github/workflows/json-contracts.yml` installs dev requirements and runs
   the SSE test suite.
3. ~~Add console `npm ci`, `npm run typecheck`, and `npm run build` to CI.~~
   Done repo-side through `.github/workflows/json-contracts.yml`,
   `.github/workflows/release.yml`, and
   `scripts/check_console_release_gate.py`; live Actions evidence still needs
   to be captured.
4. ~~Generate repo-side SBOM/dependency inventory.~~ Done:
   `scripts/check_supply_chain_gate.py` emits `local_component_inventory/v1`
   inside `supply_chain_evidence/v1` for Python/npm/Cargo components and hashes
   the supply-chain artifacts.
5. ~~Add local provenance interface.~~ Done:
   `supply_chain_evidence/v1` records git commit/tree and CI/release workflow
   materials while marking external attestation `operator-side`.
6. Add Rust/npm/Python advisory enforcement through online scanners or a pinned
   offline advisory database.
7. Capture and archive real GitHub Actions CI/release evidence, checksums, and
   external provenance/attestation.

Acceptance gates:

```bash
python3 -m pytest sse/test
npm --prefix console ci
npm --prefix console run typecheck
npm --prefix console run build:strict
python3 scripts/check_console_release_gate.py
python3 scripts/check_supply_chain_gate.py
cargo test
bash scripts/check_ci_smoke.sh
```

Done criteria:

- A clean checkout can run all major language build/test gates.
- Repo-side supply-chain evidence validates under schema and pre-release gate.
- Full production-complete status still requires external provenance and
  advisory-enforcement evidence from the real release environment.

## RW-P2-01: Product / Data-Model Completeness For Real E-Commerce Use

Why this remains:

- The repository supports a privacy-query platform baseline and a narrow
  e-commerce fact layer.
- It is not a full customer 360, inventory, logistics, or real-time warehouse
  platform.
- `business_access_policy/v1` now makes merchant / courier / support / buyer /
  field-marketing / fraud / auditor field-level allow-mask-deny decisions
  explicit. The metadata API now
  has one enforced read path, `POST /v1/business-data/read-preview`, which runs
  the policy and identity binding before reading fact rows, masks protected
  fields without selecting raw values, and rejects scope/filter conflicts.
  As of 2026-06-04, this is no longer only "relationship string + caller
  scope" logic: the fact layer now carries bound relationship anchors for
  merchant, buyer, marketer, fraud, and support workflows, and the repo-side
  handler binds those back to `business_identities` before returning a decision
  or preview. Candidate JSONL fact imports therefore now require those relation
  columns as part of the fact-layer baseline, rather than treating them as
  ad-hoc request metadata.
  Candidate JSONL fact imports now have a repo-side validator and
  validator-first transactional importer. The importer applies metadata
  migrations, refuses unknown/sensitive columns before insert, commits allowed
  batches, and rolls back failed batches. This is still not a full production
  business API, event-stream ingest, or external ETL deployment.

Files to change:

- `docs/ECOMMERCE_ACCESS_MODEL.md`
- `docs/ECOMMERCE_FACT_LAYER_PLAN.md`
- `config/business_access_policy.ecommerce.example.json`
- `schemas/business_access_policy.schema.json`
- `schemas/business_access_check_report.schema.json`
- `schemas/business_data_read_preview.schema.json`
- `schemas/business_access_api_smoke.schema.json`
- `schemas/ecommerce_fact_import_validation.schema.json`
- `schemas/ecommerce_fact_import_validation_smoke.schema.json`
- `schemas/ecommerce_fact_import_result.schema.json`
- `schemas/ecommerce_fact_import_smoke.schema.json`
- `scripts/check_business_access_policy.py`
- `scripts/check_business_access_policy_smoke.py`
- `scripts/check_business_access_api_smoke.py`
- `scripts/validate_ecommerce_fact_import.py`
- `scripts/check_ecommerce_fact_import_validation.py`
- `scripts/import_ecommerce_fact_rows.py`
- `scripts/check_ecommerce_fact_import.py`
- `scripts/check_ecommerce_production_exposure_gate.py`
- `schemas/ecommerce_production_exposure_gate.schema.json`
- `scripts/serve_metadata_api.py`
- `migrations/metadata/010_*`
- `console/src/routes/catalog*`
- importers for real or anonymized business data

Implementation steps:

1. Keep product claim scope explicit: privacy query platform only, or broader
   e-commerce analytics platform.
2. Maintain the field-level business policy for merchant, courier, support,
   buyer, field marketing, fraud analyst, and auditor personas.
3. Reuse `POST /v1/business-data/read-preview` as the reference implementation
   for any new business read API: policy check first, denied fields fail before
   SELECT, masked fields never select raw values, and request filters cannot
   override authorized scope.
   The current repo-side baseline now also requires business-relationship
   binding against fact rows for `merchant_of_order`, buyer `self`,
   `assigned_delivery_leg`, `assigned_station_leg`, `assigned_last_mile_leg`,
   `fraud_review_queue`, and `campaign_assignee`.
4. Use `scripts/import_ecommerce_fact_rows.py` or an equivalent
   validator-first transaction in any production ETL/batch importer before it
   writes rows, so protected fields cannot enter unsupported fact tables without
   an explicit policy class and mask/deny decision.
5. If broader, add customer profile/consent, product/SKU hierarchy, inventory,
   fulfillment, logistics trace, and customer service outcome facts.
6. Add sample anonymized datasets.
7. Add role mapping for buyer, merchant, support, logistics, and platform ops.
8. Update console catalog views to match actual data support.
9. Keep the production exposure gate green before claiming production readiness
   for commerce data/persona contact surfaces.
10. Keep the console `Business Access Workbench` and
    `ecommerce_fact_import_job/v1` wrapper green so browser-facing persona
    review and ETL-style validator-first ingest stay on the same contract as
    the metadata API and importer.

Acceptance gates:

```bash
python3 scripts/check_business_access_policy_smoke.py
python3 scripts/check_business_access_api_smoke.py --out-dir tmp/business_access_api_smoke
python3 scripts/check_ecommerce_fact_import_validation.py --out-dir tmp/ecommerce_fact_import_validation
python3 scripts/check_ecommerce_fact_import.py --out-dir tmp/ecommerce_fact_import_smoke
python3 scripts/check_ecommerce_production_exposure_gate.py --out-dir tmp/ecommerce_production_exposure_gate
python3 scripts/check_metadata_schema_portability.py
bash scripts/check_json_contracts.sh
```

Done criteria:

- Documentation and UI claims match the supported business schema.
- Fact-layer relationship anchors, validator-first imports, and repo-side
  business-access checks agree on the same merchant/buyer/logistics/fraud/
  marketer identity bindings, including the console workbench and ETL wrapper.
- Non-privileged support callers must also be covered on the same loopback HTTP
  path: masked buyer-contact preview on the assigned case and `case_id` spoof
  rejection both need to stay green beside the direct support
  `business_access_check_report/v1` relation-binding artifact.
- `ecommerce_production_exposure_gate/v1` is archived for the release and lists
  any live OIDC/OpenFGA/Postgres/TLS/external-anchor evidence still missing.
- The archived gate includes an `exposure_matrix` with attacker, internal
  adversary, and verifier artifact indexes, rather than only a flat status
  summary.

## RW-P2-02: Production-Scale Benchmarks And SLO Enforcement

Why this remains:

- Local benchmark reports exist.
- Production-like multi-host, large-input, and sustained-concurrency SLO
  evidence is incomplete.

Files/tools:

- `scripts/benchmark_pipeline.py`
- `scripts/benchmark_pjc.py`
- `scripts/benchmark_live_sse_demo.py`
- `scripts/benchmark_dashboard_jobs.py`
- `scripts/run_chaos_test.py`
- `docs/BENCHMARK_PLAN.md`

Implementation steps:

1. Define production SLOs for data-size tiers, max latency, peak memory,
   recovery RTO/RPO, and alert thresholds.
2. Run scale benchmarks on production-like hosts.
3. Capture resource metrics, not only wall time.
4. Add regression thresholds for CI-safe small/medium cases.
5. Keep large benchmarks as scheduled/operator gates.

Acceptance gates:

```bash
python3 scripts/benchmark_smoke.py
python3 scripts/benchmark_pipeline.py --help
python3 scripts/benchmark_pjc.py --help
```

Done criteria:

- SLOs are measurable and tied to health/alerting.

## RW-P2-03: Documentation Status Hygiene And Stale-Claim Prevention

Why this remains:

- The repository had conflicting "baseline complete", "repo-side complete", and
  "production remaining" statements.
- Historical docs must preserve implementation detail without becoming current
  status truth.

Files to change:

- `docs/README.md`
- `docs/NEXT_SESSION_READING_GUIDE.md`
- `docs/CURRENT_SECURITY_AND_COMPLETION_AUDIT.md`
- this file
- historical docs with completion claims
- optional doc-lint script

Implementation steps:

1. Maintain a doc status map: authoritative current status, implementation
   detail, historical record.
2. Add grep/doc-lint gate for risky phrases:
   - "production complete"
   - "only X remains"
   - "0 blocks" without historical/baseline context
3. Require new docs discussing remaining work to link to this backlog.
4. Preserve implementation snippets in deep docs; do not delete details unless
   the replacement links to them.

Acceptance gates:

```bash
rg -n "production complete|only .* remains|0 blocks|Current total" docs README.md
git diff --check
```

Done criteria:

- A new engineer can identify current project problems from `docs/README.md`,
  the current audit, and this backlog without reading every old session report.

## Recommended Execution Order

1. RW-P0-02 remaining branch: privacy-budget operator HTTP API and live
   PostgreSQL/HA evidence.
2. RW-P0-04 remaining branch: live resource-isolated PJC worker evidence.
3. RW-P0-03 remaining branch: signed two-party commitment exchange,
   result-to-commitment release binding, and malicious-boundary claims.
4. RW-P0-06: central release gate.
5. RW-P0-05: two-host evidence and TLS EOF resolution.
6. RW-P1-04 and RW-P1-09: console/CI reproducibility.
7. RW-P1-01 and RW-P1-02: live authority and external anchor.
8. PostgreSQL / HA boundary is now split into `postgres_ha_evidence_gate/v1`
   (repo-side drill/topology evidence) and `postgres_ha_live_evidence_archive/v1`
   (operator live failover/restore/pooling artifacts). Remaining work is the
   operator archive contents, not another round of repo-side script scaffolding.
9. Supply-chain / provenance is now split into `supply_chain_evidence_gate/v1`
   (repo-side workflow/SBOM/provenance interface evidence) and
   `supply_chain_live_evidence_archive/v1` (operator live GitHub Actions run,
   release checksum, provenance, and advisory artifacts). Remaining work is the
   operator archive contents, not more local inventory scripting.
10. Authority / KMS / identity is now split into `authority_evidence_gate/v1`
    (repo-side governance + live-capable adapter evidence) and
    `authority_live_evidence_archive/v1` (operator live Keycloak/OpenFGA/Vault/
    cloud-KMS artifacts). Remaining work is the operator archive contents, not
    another round of repo-side authority adapter scaffolding.
11. Observability / alerting is now split into `observability_evidence_gate/v1`
    (repo-side topology + webhook/daemon smoke evidence) and
    `observability_live_evidence_archive/v1` (operator live Tempo/Grafana/
    webhook/heartbeat artifacts). Remaining work is the operator archive
    contents, not more local topology or webhook scaffolding.
12. Recovery-service deployment hardening is now split into
    `recovery_service_deployment_evidence_gate/v1` (repo-side HTTP
    production/failover/Kubernetes topology evidence) and
    `recovery_service_live_evidence_archive/v1` (operator live service-user,
    sandbox, firewall/NetworkPolicy, public-mTLS, and target-host failover
    artifacts). Remaining work is the operator archive contents, not more local
    deployment-hardening scaffolding.
13. Privacy-budget deployment is now split into
    `privacy_budget_deployment_evidence_gate/v1` (repo-side transactional
    concurrency/approval/session/proxy evidence) and
    `privacy_budget_live_evidence_archive/v1` (operator live PostgreSQL/HA,
    browser-console, approval API, and duplicate-denial artifacts). Remaining
    work is the operator archive contents, not more local queue/store
    scaffolding.
14. Retired legacy SSE query surface is now split into
    `legacy_sse_query_surface_evidence_gate/v1` (repo-side retirement proof)
    and `legacy_sse_live_evidence_archive/v1` (operator live route/socket/
    ingress artifacts). Remaining work is the operator archive contents, not
    another round of local retirement gating.
15. PJC resource isolation is now split into
    `pjc_resource_isolation_evidence_gate/v1` (repo-side preflight/binary/
    fail-closed worker isolation evidence) and
    `pjc_resource_isolation_live_evidence_archive/v1` (operator live
    systemd/Kubernetes limits, timeout/cancel, and production streaming
    artifacts). Remaining work is the operator archive contents, not more local
    wrapper/preflight scaffolding.
16. Query-workflow deployment durability is now split into
    `query_workflow_deployment_evidence_gate/v1` (repo-side DB-backed
    durability/lease/cancel/timeout/restart-steal evidence) and
    `query_workflow_live_evidence_archive/v1` (operator live worker
    supervision/retry/restart/PostgreSQL-HA artifacts). Remaining work is the
    operator archive contents, not more local queue/sidecar semantics
    scaffolding.
17. E-commerce deployment exposure is now split into
    `ecommerce_deployment_evidence_gate/v1` (repo-side fact/persona/request/
    console exposure evidence) and `ecommerce_live_evidence_archive/v1`
    (operator live identity/ABAC, import, TLS/NetworkPolicy, and
    Postgres/anchor artifacts). Remaining work is the operator archive
    contents, not more local persona/fact exposure scaffolding.
    As of 2026-06-05, `collect_ecommerce_live_rollout.py` now gives this module
    the same typed verifier-facing rollout-collection entrypoint already used
    by `spiffe_envoy` and `authority`: a single
    `live_rollout_collection_report/v1` can now declare which e-commerce live
    artifacts were supplied, archive them, build the verifier gate, and emit a
    stable blocked-vs-ok status before public verification work starts.
    As of 2026-06-05, those remaining live artifacts also have explicit typed
    contracts instead of free-form placeholders:
    `ecommerce_live_oidc_abac_report/v1`,
    `ecommerce_live_fact_import_report/v1`,
    `ecommerce_live_tls_network_policy_report/v1`,
    `ecommerce_live_postgres_anchor_report/v1`, and
    `ecommerce_logistics_live_rollout_report/v1`. Public/live verification
    should now target those report shapes directly.
18. Console/browser deployment is now split into
    `console_deployment_evidence_gate/v1` (repo-side token/session/header/
    release evidence) and `console_live_evidence_archive/v1` (operator live
    HTTPS/Secure-cookie, reverse-proxy/OIDC, browser exercise, and release-run
    artifacts). Remaining work is the operator archive contents, not more local
    console auth/header scaffolding.
19. Control-plane deployment is now split into
    `control_plane_deployment_evidence_gate/v1` (repo-side readiness /
    malformed-input / read-model / redaction evidence) and
    `control_plane_live_evidence_archive/v1` (operator live runbook,
    metadata/platform API, and reverse-proxy artifacts). Remaining work is the
    operator archive contents, not more local control-plane hardening
    scaffolding.
20. PJC protocol-security claims are now split into
    `pjc_protocol_security_evidence_gate/v1` (repo-side commitment / signed
    evidence / release-binding plus explicit claim boundary) and
    `pjc_protocol_live_evidence_archive/v1` (operator live two-host signed
    manifest / release-binding / value-policy denial / malicious-secure
    artifacts). Remaining work is the operator archive contents, not more local
    protocol-claim prose.
21. Top-level closure is now summarized by
    `production_security_closure_gate/v1`, which aggregates the module-level
    gates instead of replacing them. Remaining work is still the operator live
    artifacts exposed by those submodules, not another round of local summary
    prose.
22. `ecommerce`, `console`, and `control_plane` now distinguish
    `live_foundation_status` from module `live_status`. Their current repo-side
    verifier evidence is archived by default, but operator rollout artifacts
    are still required before those modules can move from `live_status=skipped`
    to `live_status=ok`.
23. As of 2026-06-04, `ecommerce` is no longer blocked on more repo-side
    logistics scaffolding. The real remote
    `tmp/logistics_live_synthetic/ecommerce_logistics_live_rollout_report.json`
    has now been landed into the local authoritative worktree, re-archived into
    `ecommerce_live_evidence_archive/v1`, and propagated into
    `production_security_closure_gate/v1`. In validated local replay, that
    logistics rollout artifact is sufficient to move the `ecommerce` module
    from `live_status=skipped` to `live_status=ok` while preserving
    `live_foundation_status=ok`.
24. The next production push after logistics should focus on the other
    foundation-aware modules that are already repo-side complete but still
    operator-artifact incomplete: `authority`, `console`, `control_plane`,
    `postgres_ha`, `observability`, `query_workflow`, `supply_chain`, and
    `pjc_protocol`. Current remote VPS inventory only exposed
    `tmp/logistics_live_synthetic` plus existing public-two-host/PJC artifacts,
    so their remaining work is still to archive real operator rollout evidence,
    not to add more local repo-side scaffolding.
25. The local live archives already prove the ingestion path is ready for those
    modules: `authority`, `console`, `control_plane`, `observability`,
    `postgres_ha`, `query_workflow`, and `supply_chain` each started from
    `live_repo_side_*_foundation` only, while `ecommerce` already carried a
    real logistics rollout report. Since then, `control_plane`,
    `observability`, `query_workflow`, `postgres_ha`, `supply_chain`, and now
    `console` have all crossed into real live rollout evidence through
    VPS-produced artifacts, `pjc_protocol` has now crossed through the
    authoritative public-two-host live archive plus signed-manifest/release-
    binding reports, and `public_two_host` itself now auto-consumes that same
    authoritative archive plus clean materialization report to reach
    `live_status=ok`. `legacy_sse` now also carries real VPS socket/route/
    ingress retirement evidence, and `privacy_budget` now carries real
    approval-API / duplicate-denial evidence combined with already-collected
    browser-console and restore/API evidence. `recovery_service` now also
    carries a real VPS failover report, `pjc_resource_isolation` now carries
    timeout/cancel plus streaming-success rollout evidence, `external_anchor`
    now carries a real Rekor upload report, `authority` has since been
    lifted through a real VPS-backed docker-compose rollout for Keycloak,
    OpenFGA, and Vault, and `spiffe_envoy` has since also been lifted through
    a real VPS-backed SPIRE + Envoy rollout with positive-run, wrong-peer,
    expired-SVID, trust-bundle, and access-log evidence. The current typed
    completion summary is therefore
    `tmp/production_security_closure_gate/production_security_closure_gate.json`
    with `live_ok_count=16`, `live_skipped_count=0`, and
    `tmp/final_live_blockers_report.json` with
    `remaining_live_module_count=0`.
8. RW-P1-05 through RW-P1-08: durability, HA, observability, recovery
   hardening.
9. P2 product, benchmark, and documentation hygiene work.

## Not Remaining By Itself

These are already closed or only historical:

1. Static identity-token comparison in `scripts/api_identity.py` uses
   `hmac.compare_digest`.
2. Legacy SSE server default bind address is `127.0.0.1`.
3. Local CI smoke currently passes Rust bridge tests, JSON contracts, file-mode
   replay, and FIFO replay.
4. Historical baseline block counts remain traceability records, not current
   production-security completion claims.
