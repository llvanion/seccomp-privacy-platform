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
| Production security | Repo-side gates are strong for a prototype. | Live KMS/IAM, public mTLS, external audit anchor, HA backup/restore, observability, and supply-chain evidence. |

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
   `--client-value-max`, `validate_bridge_job.py` and `preflight_pjc_job.py`
   reject negative or above-bound client values before PJC launch.
9. PJC preflight can bind `input_commitments.json` to `job_meta.json`; the local
   smoke denies token-scope, normalizer, and normalizer-schema-version drift
   before PJC launch.

Missing:

1. Live two-host evidence proving the signed manifest exchange runs outside
   the local repo smoke.
2. Live two-host evidence for value policy denial in the operational PJC role
   package path.
3. Explicit proof/claim choice:
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

Current status: `partial`.

Already done:

1. Network pickle removed from legacy WebSocket frames.
2. Default bind host is `127.0.0.1`.
3. Wide bind requires explicit demo override.

Missing:

1. A production decision: retire legacy SSE WebSocket or harden it.
2. If hardened:
   - bearer/JWT/service identity
   - TLS/mTLS
   - per-caller policy binding
   - request limits
   - audit logs with no raw query leakage
3. Contract smoke proving unauthenticated search is denied.

Acceptance:

1. Rebuttal can say the legacy SSE UI is not a production attack surface, or it
   can prove production authentication and transport controls.

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

Current status: `partial`.

Missing:

1. Durable job state outside local subprocess/status files.
2. Retry/resume semantics for non-file-backed inline runs.
3. Crash recovery evidence.

### TODO-P1-06 Supply Chain And Full Test Gate

Current status: `partial`.

Missing:

1. Python test dependencies and `pytest` gate.
2. Console lockfile plus `npm ci`, typecheck, and build gate.
3. SBOM/provenance/advisory checks.

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
4. Harden or retire the legacy SSE WebSocket production claim.
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
