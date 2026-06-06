# Attacker And Reviewer TODO

Date: 2026-06-01

This is the current rebuttal-facing TODO list for the gaps that matter most
from an attacker, reviewer, and production-operator point of view. It should be
read together with:

1. [CURRENT_SECURITY_AND_COMPLETION_AUDIT.md](CURRENT_SECURITY_AND_COMPLETION_AUDIT.md)
2. [REMAINING_WORK_IMPLEMENTATION_BACKLOG.md](REMAINING_WORK_IMPLEMENTATION_BACKLOG.md)
3. [THREAT_MODEL_AND_LEAKAGE_MODEL.md](THREAT_MODEL_AND_LEAKAGE_MODEL.md)

Status terms:

- `done`: implementation and regression gate exist in this repository.
- `repo-side`: code/config/schema/checks exist, but live production evidence is
  not available in this workspace.
- `operator-side`: needs real infrastructure, credentials, or two-host evidence.
- `open`: not implemented enough to depend on.

## 1. Rebuttal-Safe Claim Boundary

| Claim | Current safe wording | TODO to strengthen |
| --- | --- | --- |
| Malicious participants | Semi-honest/operator-controlled PJC with repo-side input commitment checks. | Signed two-party manifests, result-to-commitment binding, value proof/range policy, and a decision whether to add malicious-secure PSI-SUM. |
| SSE query frontend | Legacy/demo WebSocket is loopback-only by default and no longer accepts network pickle. | Either retire it from production claims, or add production authn/authz, TLS/service identity, rate limits, and deployment fail-closed gates. |
| Business-role access | Platform caller scope exists; business field-level policy now has repo-side check/read-preview enforcement plus validator-first fact import. | Integrate the field-level policy into every future live read API/external ETL and add real ABAC/OpenFGA decisions if production claims require them. |
| Privacy-budget approvals | Transactional SQLite store plus authenticated operator HTTP list/approve/reject/expire API and repo-side browser-console queue controls are implemented. | Add deployed browser evidence and live PostgreSQL/HA evidence. |
| Real e-commerce data | Narrow order-centric fact layer supports privacy joins and has a repo-side validator-first transactional JSONL importer. | Add customer profile/consent, address/logistics route, support case, product, inventory, and deployed external ETL wiring if the product claim includes those domains. |
| Production security | Repo-side gates are strong for a prototype; metadata backup/restore now has a SHA-bound local drill; final release can require uploaded external-anchor evidence. | Live KMS/IAM, public mTLS, live S3/Rekor anchor execution, live PostgreSQL/HA failover/restore, observability, and external supply-chain evidence. |

## 2. P0 Tasks

### TODO-P0-01 Malicious PJC Boundary

Current status: `repo-side`.

Already done:

1. Bridge emits `pjc_input_commitment/v1`.
2. PJC preflight can require the commitment.
3. Stage audit records commitment path/hash.
4. CSV mutation after bridge is detected.
5. `pjc_two_party_signed_run_manifest/v1` signs Party A / Party B run
   manifests with Ed25519 over canonical JSON.
6. `pjc_two_party_evidence_merge/v1` now verifies manifest signatures,
   cross-party commitment exchange, peer TLS identity exchange, result hash,
   policy decision, and audit-chain hash.
7. `release_policy_gate/v1` can require a bound two-party evidence merge and
   compares the merge result hashes with the `policy_audit/v1`
   `pjc_result_sha256` before public release.
8. `client_value_mode=raw-int` now has committed value policy and summary
   checks: bridge records source/output summaries, production raw-int requires
   `--client-value-max`, an allowed value field, value unit, and currency for
   minor currency units; `validate_bridge_job.py` and `preflight_pjc_job.py`
   reject negative, above-bound, or semantically unallowlisted client values
   before PJC launch.
9. PJC preflight can bind `input_commitments.json` to `job_meta.json`; the local
   smoke denies token-scope, normalizer, and normalizer-schema-version drift
   before PJC launch.
10. `release_policy_gate/v1` can require `require_external_anchor=true`; strict
    production config now denies released reports unless an uploaded S3
    Object Lock/Rekor `external_audit_anchor_report/v1` is supplied. Local/planned
    anchor reports remain negative cases.
11. Operator dashboard visible state is release-gate-aware: external-anchor
    denials surface as `pending_external_anchor`, other gate denials surface as
    `blocked`, and run-history filtering applies that overlay before returning
    state lists.

Missing:

1. Live two-host evidence proving the signed manifest exchange runs outside
   the local repo smoke.
2. Live two-host evidence for value policy denial in the operational PJC role
   package path.
3. Live S3 Object Lock/Rekor upload evidence passed through the final release
   gate.
4. Explicit proof/claim choice:
   - document semi-honest only, or
   - add malicious-secure protocol/proof component.

Acceptance:

1. A forged signed run manifest is denied.
2. A mismatched result hash is denied before release.
3. A value outside policy range is denied.
4. Rebuttal text can honestly state the exact malicious-party boundary:
   repo-side tamper/result substitution resistance is implemented, but
   malicious-secure PSI-SUM / range proof is not.

### TODO-P0-02 Business Field-Level Access Control

Current status: `repo-side`.

Goal:

Model the roles the user called out directly:

1. merchant staff must not receive buyer address/contact fields
2. courier must only receive next-stop delivery data
3. customer service must receive only protected support fields
4. auditors/operators receive broader metadata only under privileged roles

Implementation scope:

1. Add `business_access_policy/v1`.
2. Add a complete e-commerce policy example for:
   - `buyer`
   - `merchant_staff`
   - `customer_service_agent`
   - `courier`
   - `field_marketer`
   - `compliance_auditor`
3. Add a checker that evaluates requested fields and returns:
   - `allow`
   - `mask`
   - `deny`
4. Add smoke cases:
   - merchant denied address/contact fields
   - courier denied full address and allowed next stop
   - customer service receives protected contact only
   - buyer self-view can receive own address/contact
   - auditor/operator-only fields are denied to normal roles

Acceptance:

1. Policy config validates against schema.
2. Checker report validates against schema.
3. CI fails if the core role examples drift.

Current repo-side evidence:

1. `business_access_policy/v1` and
   `config/business_access_policy.ecommerce.example.json`.
2. `scripts/check_business_access_policy.py` and
   `scripts/check_business_access_policy_smoke.py`.
3. `serve_metadata_api.py POST /v1/business-access/check` with identity-token
   role binding and tenant-scope enforcement.
4. `serve_metadata_api.py POST /v1/business-data/read-preview`, a narrow
   policy-gated read path over the e-commerce fact tables. It reuses the same
   business policy and identity binding before SELECT, rejects denied fields
   with HTTP 403, returns mask markers for masked fields without selecting raw
   values, rejects filter/scope conflicts, and rejects sensitive-field filters
   such as buyer email.
5. `business_data_read_preview/v1` and `business_access_api_smoke/v1` schemas.
6. `scripts/check_business_access_api_smoke.py`, covering allow, deny, mask,
   role spoofing, order filter conflict, tenant filter conflict, and
   sensitive-field filter rejection.
7. `scripts/validate_ecommerce_fact_import.py` and
   `ecommerce_fact_import_validation/v1`, covering candidate JSONL imports for
   the current fact tables. The smoke rejects hidden address fields, raw support
   transcript fields, and negative monetary values before fact loading.
8. `scripts/import_ecommerce_fact_rows.py`,
   `ecommerce_fact_import_result/v1`, and
   `scripts/check_ecommerce_fact_import.py`, covering validator-first
   transaction import, pre-insert sensitive-column denial, and duplicate-batch
   rollback.

Remaining:

1. Route every future business data read endpoint through the same
   pre-SELECT gate; the current enforced path is the metadata API read-preview,
   not a full business API surface.
2. Add browser-console workflow for support/customer/logistics role access.
3. Require production external ETL/event-stream jobs to call
   `import_ecommerce_fact_rows.py` or an equivalent validator-first transaction.
4. Add OpenFGA/ABAC parity if production claims require externalized authz.

### TODO-P0-02B Privacy-Budget Approval Operator Surface

Current status: `repo-side`.

Already done:

1. `privacy_budget_approval_events` transactional state.
2. `privacy_budget_approval_decision/v1` JSONL evidence.
3. `serve_operator_dashboard.py` endpoints:
   - `GET /v1/privacy-budget/approvals`
   - `POST /v1/privacy-budget/approval/{request_id}/approve`
   - `POST /v1/privacy-budget/approval/{request_id}/reject`
   - `POST /v1/privacy-budget/approval/{request_id}/expire`
4. Identity-token authentication, tenant/caller view scope, same-identity
   approval denial, and reason requirements for reject/expire.
5. `privacy_budget_approval_list/v1`,
   `privacy_budget_approval_transition/v1`, and
   `scripts/check_privacy_budget_approval_api_smoke.py`.

Remaining:

1. Deployed browser-console evidence for the approval queue.
2. Live PostgreSQL/HA evidence for the same state machine.
3. Deployment runbook entries for operator review, expiry policy, and incident
   rollback.

### TODO-P0-03 SSE Production Entry Decision

Current status: `repo-side retired`.

Already done:

1. Network pickle removed from legacy WebSocket frames.
2. Default bind host is `127.0.0.1`.
3. Wide bind requires explicit demo override.
4. `SSE_PRODUCTION_MODE=1` now retires the legacy WebSocket for production: it
   refuses startup on loopback and also refuses the demo wide-bind override.
5. `sse/Dockerfile` sets `SSE_PRODUCTION_MODE=1`, so the historical container
   command fails closed instead of becoming an accidental production listener.
6. `scripts/check_legacy_sse_production_gate.py` is schema-backed and wired into
   CI/contracts/pre-release gates.

Missing:

1. Live deployment evidence that no production host routes traffic to this
   legacy WebSocket.
2. Production docs/runbooks must continue to name query workflow / bridge
   pipeline APIs as the production query surface.

Acceptance:

1. Rebuttal can say the legacy SSE WebSocket is not a production attack surface:
   repo-side gates retire it under production mode, and live deployment evidence
   must show it is not exposed.

### TODO-P0-04 Privacy Budget Live Close-Loop

Current status: `repo-side`.

Already done:

1. Transactional SQLite budget consumption.
2. Duplicate/overlap/budget exhaustion checks.
3. Approval lifecycle and one-time approval consume.

Missing:

1. First-class HTTP operator API for approve/reject/expire/list.
2. PostgreSQL/HA live evidence for the same semantics.
3. Dashboard flow that cannot bypass the release gate.

Acceptance:

1. Two concurrent production-style releases produce one allow and one deny.
2. Approval cannot be self-approved or reused.
3. Same behavior is shown against live PostgreSQL.

## 3. P1 Tasks

### TODO-P1-01 Real KMS/IAM/Authority Live Evidence

Current status: `operator-side`.

Missing:

1. Real Vault/cloud KMS/Keycloak/OpenFGA evidence.
2. Rotation, revoke, drift, and outage tests.
3. Production release path that fails closed on unavailable authority source.

### TODO-P1-02 Public mTLS And Peer Identity Evidence

Current status: `operator-side`.

Missing:

1. Two-host public-network run.
2. Peer certificate identity verification evidence.
3. Negative evidence for wrong CA, wrong peer identity, expired token, and EOF
   handling.

### TODO-P1-03 External Immutable Audit Anchor

Current status: `repo-side`.

Missing:

1. Live write-and-verify to immutable storage or an equivalent WORM target.
2. Release gate that refuses silent publication on required-anchor failure.

### TODO-P1-04 Dashboard/Console Caller-Safe Split

Current status: `partial`.

Already done:

1. Audit API normal identity callers receive public summaries.
2. Recursive redaction scan blocks paths, hashes, row counts, exact timing, raw
   audit arrays, and debug fields for those summaries.
3. Operator dashboard normal identity callers receive
   `operator_dashboard_public_summary/v1`; unauthenticated dashboard requests
   are denied when auth is configured, and full dashboard output is role-gated
   to privileged operator/auditor roles.
4. `scripts/check_operator_dashboard_public_summary.py` verifies dashboard
   public-summary redaction, privileged full view, and normal-caller denial on
   `/v1/runs`, job detail, exact result, and direct dashboard job start bypasses.
5. Console home/jobs routes now branch on `operator_dashboard_public_summary/v1`
   and `scripts/check_console_dashboard_public_summary.py` blocks regressions
   where those routes read un-narrowed full dashboard fields.
6. Console audit/observability/catalog routes now unwrap
   `audit_query_api_response/v1.result`, branch on
   `audit_chain_public_summary/v1`,
   `pipeline_observability_public_summary/v1`, and
   `catalog_lineage_public_summary/v1`, and
   `scripts/check_console_audit_public_summary.py` blocks regressions where
   those routes read un-narrowed full audit/lineage fields.
7. Metadata API normal identity callers now receive
   `caller_safe_metadata_summary` redacted job/entity payloads for job list,
   job detail, caller-permissions, and policy-bindings; the recursive
   `scripts/check_metadata_api_public_redaction.py` gate blocks paths, hashes,
   exact timing, raw counts, secret refs, and artifact payloads.
8. Console metadata routes unwrap `metadata_api_response/v1.result` and show
   metadata redaction notices instead of rendering full operator envelopes.
9. `bucket_public_report/v1` no longer publishes below-k bucket labels/counts,
   exact bucket sizes, or sampled `dp_noise`; `operator_bucket_report/v1`
   retains the full raw/noise evidence for privileged audit.

Missing:

1. A high-sensitivity production choice is still needed for padding,
   delayed release, or automatic bucket merge beyond report-layer redaction.
2. Same-origin browser token handling now has a repo-side HttpOnly/SameSite
   session-cookie path: `serve_operator_dashboard.py` issues
   `seccomp_identity_session`, console fetch sends same-origin credentials, and
   `check_console_browser_session.py` plus `check_identity_proxy_auth_smoke.py`
   verify cookie-only reads and proxy fail-closed behavior. Remaining console
   serving now also has a repo-side CSP/security-header gate:
   `check_console_security_headers.py` verifies no script/style inline/eval,
   same-origin `connect-src`, no framing, no-sniff, no-referrer, permissions
   denial, source-level inline-style/raw-HTML rejection, and HSTS under
   Secure-cookie mode. Remaining console work is HTTPS/Secure-cookie deployed
   evidence, reproducible console CI/release, and dependency audit gates.

### TODO-P1-05 Workflow Durability

Current status: `repo-side sidecar + DB lifecycle + local DB-backed worker complete; live deployed worker evidence partial`.

Already done:

1. `submit_query_workflow.py` now refuses to overwrite an existing workflow
   sidecar. A dry-run `accepted` sidecar may be claimed by `execute` only when
   the request digest, job ID, and out_base match.
2. Existing `running`, `completed`, `failed`, or `rejected` sidecars require a
   new out_base/job ID or the approved relaunch path.
3. `serve_operator_dashboard.py` uses the same guard before starting an async
   job from an approved request or relaunch.
4. `scripts/check_query_workflow_durability.py` emits
   `query_workflow_durability_check/v1` and covers duplicate dry-run denial,
   execute-from-accepted receipt preservation, duplicate execute denial,
   stale-running visibility, schema-validated retry/status evidence, active
   duplicate DB claim denial, terminal replay denial, and expired-lease steal
   semantics.
5. `query_workflow_executions` metadata rows record execution claim, lease
   owner, lease expiry, heartbeat, terminal state, exit code, and sidecar
   artifact paths.
6. CLI execute, query workflow API execute, and approved operator-dashboard
   launches can all write the same DB lifecycle rows.
7. `submit_query_workflow.py --enqueue`, `POST /v1/query-workflows/enqueue`,
   and `serve_operator_dashboard.py --enqueue-approved-requests` can queue an
   approved execution instead of running it inside an HTTP request thread.
8. `scripts/run_query_workflow_worker.py` owns DB leases, emits heartbeats,
   writes sidecar receipts/status, honors cancellation requests, enforces
   timeout termination, and can steal expired leases for restart recovery.
9. `scripts/cancel_query_workflow_execution.py` gives operators an explicit DB
   cancellation entrypoint and writes matching sidecar status/receipt evidence
   for queued cancellations.
10. `scripts/check_query_workflow_durability.py` now covers enqueue-to-worker
    completion, queued cancellation, running cancellation, timeout termination,
    and expired-lease worker restart in addition to duplicate/terminal replay
    checks.

Missing:

1. Live deployed worker supervision on the target hosts, not only repo-side
   local worker evidence.
2. Multi-worker concurrency and retry policy evidence under real PostgreSQL/HA.
3. Production restart/cancel/timeout drills with operator logs from the target
   deployment.

### TODO-P1-05B Record Recovery Production HTTP Gate

Current status: `repo-side production gate complete; live deployment evidence partial`.

Already done:

1. Direct HTTP service, standalone launcher, and managed start/systemd render
   now enforce the same production-mode runtime policy.
2. Production HTTP recovery requires request authentication, authz policy, and
   either signed requests or mTLS client certificates.
3. Non-loopback HTTP listeners require mTLS client certificates.
4. Identity-token auth requires a metadata DB path and still needs signed
   requests or mTLS.
5. `RECORD_RECOVERY_PRODUCTION_MODE=1`, config `production_mode: true`, and CLI
   `--production-mode` all trigger fail-closed checks.
6. `scripts/check_record_recovery_production_gate.py` emits
   `record_recovery_production_gate_check/v1` with negative cases for missing
   auth, missing authz, identity without metadata DB, identity without HMAC/mTLS,
   public listener without mTLS, and positive render cases for loopback signed
   requests and public mTLS.

Missing:

1. Live service-user/systemd sandbox evidence from a deployed unit.
2. Host firewall or Kubernetes NetworkPolicy evidence.
3. Public-network mTLS request evidence against a deployed recovery service.

Acceptance:

1. Rebuttal can say repo entrypoints cannot launch an unauthenticated production
   HTTP recovery endpoint. Full production claims still require the live network
   and sandbox evidence above.

### TODO-P1-06 Metadata DB Backup / Restore / HA Evidence

Current status: `repo-side backup/restore integrity complete; live HA operator-side`.

Already done:

1. `restore_metadata_db.py --backup-report` binds restore to
   `metadata_db_backup_report/v1.backup.sha256` or to
   `--expect-backup-sha256`.
2. Restore refuses to proceed when the current backup file SHA-256 differs from
   the expected backup report hash.
3. `metadata_db_restore_report/v1.backup` records actual SHA-256, expected
   SHA-256, match result, and source report path.
4. `scripts/check_metadata_backup_restore_drill.py` emits
   `metadata_backup_restore_drill/v1` and proves local SQLite backup
   verification, SHA-bound restore, restored `jobs`/`audit_events` probe rows,
   schema portability, and tampered-backup denial.
5. The drill is wired into JSON contracts, CI smoke, pre-release gate, and schema
   backcompat.

Missing:

1. Live PostgreSQL primary/replica or Patroni failover evidence on target hosts.
2. pgBouncer transaction-pooling and long-write bypass evidence.
3. External immutable or cloud backup storage evidence, including restore from
   that target into a fresh database.
4. Metadata API/query workflow smoke against the restored production-style DB.

Acceptance:

1. Local restore cannot accept a tampered backup file when a backup report hash is
   supplied.
2. A restored DB must retain critical probe rows and have no pending metadata
   migrations.
3. Full production wording remains blocked until live HA/failover/restore drills
   are recorded outside this repo.

### TODO-P1-07 Supply Chain And Full Test Gate

Current status: `repo-side`.

Missing:

1. Live GitHub Actions evidence for the Python pytest and console `npm ci` /
   typecheck / strict-build path.
2. External signed provenance/attestation for release artifacts.
3. Online or pinned-offline advisory enforcement for Python/npm/Rust
   dependencies.

Repo-side evidence now present:

1. `sse/requirements-dev.txt` declares `pytest`, and CI runs
   `python3 -m pytest sse/test`.
2. `console/package-lock.json` is committed.
3. Release workflow uses `npm ci`, blocking `npm run typecheck`, and
   `npm run build:strict`.
4. CI smoke workflow runs console `npm ci`, typecheck, and strict build.
5. `scripts/check_console_release_gate.py` emits
   `console_release_gate_check/v1` and rejects lockfile/workflow regressions.
6. `scripts/check_supply_chain_gate.py` emits `supply_chain_evidence/v1` with
   artifact hashes, Python/npm/Cargo component inventory, local provenance
   materials, and explicit operator-side status for external advisory/provenance
   evidence.

## 4. P2 Product Completeness

Current status: `partial`.

Missing if the claim is a real e-commerce platform:

1. customer profile and consent
2. address/contact tables with protected-field handling
3. logistics route / next-stop model
4. support ticket authorization and transcript exclusion/redaction
5. product/SKU hierarchy and inventory
6. anonymized or realistic importer validation
7. business-role OpenFGA/ABAC integration in API handlers

If those are not implemented, product wording must stay narrow:

> Order-centric privacy query platform with narrow e-commerce fact-layer
> support, not a full commerce, logistics, support, or customer-360 platform.

## 5. Immediate Execution Order

1. Complete `TODO-P0-02` repo-side business field-level access policy.
2. Bind PJC result hash and input commitments into the release gate.
3. Add privacy-budget approval HTTP endpoints.
4. Collect live deployment evidence that the repo-side retired legacy SSE
   WebSocket is not exposed as a production query surface.
5. Decide whether high-sensitivity deployments need padding, delayed release,
   or automatic merge-to-other beyond report-layer bucket redaction. Dashboard
   API, metadata API job/entity reads, console home/jobs/audit/observability/
   catalog/metadata public-summary/redaction handling, and public bucket report
   label/noise redaction are now repo-side covered by
   `operator_dashboard_public_summary/v1`,
   `scripts/check_operator_dashboard_public_summary.py`,
   `scripts/check_console_dashboard_public_summary.py`, and
   `scripts/check_console_audit_public_summary.py`,
   `metadata_api_public_redaction_check/v1`, and
   `scripts/check_metadata_api_public_redaction.py`,
   `bucket_public_report/v1`, `operator_bucket_report/v1`, and
   `scripts/check_bucket_dp_smoke.py`.
6. Collect operator-side two-host mTLS and real KMS/IAM evidence.
