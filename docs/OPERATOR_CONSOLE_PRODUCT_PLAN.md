# Operator Console Product Plan (Track-E3)

This document narrows down item §4.4 of [`docs/COMPACT_PLATFORM_BRIEF.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/COMPACT_PLATFORM_BRIEF.md): the project does not yet ship a "mature operator dashboard / workflow / admin UI as a product." The repo today exposes loopback HTTP wrappers (`serve_operator_dashboard.py`, `serve_query_workflow_api.py`, `serve_audit_query_api.py`, `serve_metadata_api.py`, `serve_platform_health_api.py`), but operators interact with them via curl or a thin static page. To deliver a credible "PJC + SSE e-commerce platform" story we need a product-grade console.

This document defines the scope so an engineer (or a downstream product team) can build it without re-deriving the contracts every time.

## 1. Intent

| What this document is | What this document is **not** |
|-----------------------|-------------------------------|
| The product spec for the operator console: what screens exist, which existing HTTP endpoints back them, what role gates apply, what the navigation looks like. | A frontend framework choice. The spec is framework-neutral. |
| A frozen UI manifest (`config/operator_console/console_manifest.json`) that the console SPA can read at startup to know which API surfaces are live. | A SPA implementation; the SPA itself is operator-environment work. |
| A baseline static index page (`config/operator_console/index.html`) that links the existing HTTP wrappers and serves as a smoke entry. | A polished design system. |

## 2. Information Architecture

| Section | Purpose | Backing endpoint(s) | Role gate |
|---------|---------|---------------------|-----------|
| **Home / Health** | Per-tenant platform-health snapshot, alert stripe. | `serve_platform_health_api.py` `GET /v1/platform-health`; `services/record_recovery/http_service.py` `GET /metrics` | All authenticated operators |
| **Jobs** | Submit a privacy query (cross_party_match), monitor running jobs, drill into a finished job's audit chain. | `serve_query_workflow_api.py` `POST /v1/query-workflow`; `serve_operator_dashboard.py` `POST /v1/jobs/start`, `GET /v1/dashboard`, `GET /v1/jobs/{job_id}`; `serve_audit_query_api.py` `GET /v1/audit-chain` | `query_submitter` to submit; everyone else read-only |
| **Requests** | Submit tenant-facing privacy query requests into the pending approval queue, review pending submissions, approve or reject. | `serve_operator_dashboard.py` `POST /v1/request/submit`, `GET /v1/requests`, `GET /v1/requests/{submission_id}`, `POST /v1/request/{submission_id}/approve`, `POST /v1/request/{submission_id}/reject` | `query_submitter` to submit; `privacy_operator` / `platform_admin` to approve; `privacy_operator` / `platform_admin` / `compliance_auditor` to reject |
| **Audit & Public Reports** | Browse public reports; verify a sealed audit bundle; spot-check tamper resistance. | `serve_audit_query_api.py` `GET /v1/public-report`, `GET /v1/audit-chain`, `GET /v1/observability`, `GET /v1/catalog-lineage`; CLI `verify_audit_bundle.py`, `verify_audit_tamper_resistance.py` | `compliance_auditor` for full-detail; others see redacted |
| **Catalog & Lineage** | Browse `catalog_lineage/v1` per job; explore the dataset/service registry. | `serve_audit_query_api.py` `GET /v1/catalog-lineage`; `serve_metadata_api.py` `GET /v1/jobs`, `GET /v1/policies`, `GET /v1/services`, `GET /v1/business-identities` | All authenticated operators |
| **Permissions** | View `caller_permissions`, `policy_bindings`, business identities; trigger `apply-registry` proposals. | `serve_metadata_api.py` `GET /v1/caller-permissions`, `GET /v1/policy-bindings`, `GET /v1/business-identities`; `manage_metadata_db.py` `apply-registry` | `commerce_ops_owner` and `compliance_auditor` |
| **Recovery Service** | Health, lifecycle, mTLS state, rate-limit metrics. | `services/record_recovery/http_service.py` `GET /health`, `GET /metrics`; `manage_record_recovery_service.py` `start`/`status`/`stop`/`render-systemd` | `recovery_service_operator` |
| **Observability** | Pipeline-stage trace browser via the checked-in Grafana dashboards (linked, not embedded). | `config/observability/grafana-dashboards/*.json` (Grafana provisioned), `scripts/render_observability_topology.py` report | All authenticated operators |
| **Compliance** | GDPR mapping, retention plan, archive index, external anchor publish. | `docs/COMPLIANCE_MAPPING.md`; `materialize_control_plane_deepening.py --list-entity retention-reconcile-plan`; `archive_audit_bundle.py`, `publish_external_audit_anchor.py` | `compliance_auditor` |

The console manifest (`config/operator_console/console_manifest.json`) freezes this matrix — the SPA reads it at startup and renders only the sections whose backing HTTP endpoints are reachable.

## 3. Manifest Contract

`console_manifest/v1` (frozen schema: [`schemas/console_manifest.schema.json`](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/console_manifest.schema.json)) maps each console section to:

- `section`: stable section id (`home`, `jobs`, `requests`, `audit`, `catalog`, `permissions`, `recovery`, `observability`, `compliance`).
- `title`: display title.
- `endpoints`: list of `{method, path, role}` triples.
- `feature_flags`: list of capability strings the SPA branches on (`mtls`, `rate_limit`, `multi_tenant_quota`, `external_anchor`).
- `roles_allowed`: which `platform_roles` may see this section.
- `external_links`: optional list of links into Grafana / runbook docs.

The SPA never hard-codes URLs. It hits `GET /v1/console-manifest` (served by `serve_operator_dashboard.py`) and renders accordingly. This means an operator deploying with a subset of services (e.g. no Grafana) gets a coherent UI instead of broken links.

## 4. Role Gates

The console reads `api_identity_resolution/v1` for the current bearer token to decide which sections to render. Mapping:

| platform_role | Sections shown |
|---------------|----------------|
| `commerce_ops_owner` | Home, Jobs, Requests, Audit (read), Catalog, Permissions, Recovery (read), Observability |
| `campaign_analyst` | Home, Jobs (no release), Requests, Audit (read), Catalog |
| `fraud_analyst` | Home, Jobs (no release), Requests, Audit (read), Catalog |
| `privacy_operator` | Home, Jobs (approve-only workflow actions), Requests (review / approve / reject), Audit (read), Catalog, Observability |
| `platform_admin` | Home, Jobs, Requests (review / approve / reject), Audit (full), Catalog, Permissions, Recovery, Observability, Compliance |
| `compliance_auditor` | Home, Requests (review / reject), Audit (full), Catalog, Permissions, Compliance |
| `recovery_service_operator` | Home, Recovery, Observability |

`can_release` is enforced by the existing pipeline gate; the console mirrors it by hiding the "release" button on jobs the caller cannot release.

## 5. Workflow Story

The "story" the console must support, end to end, mirrors the demo run:

1. `commerce_ops_owner` lands on Home, sees `platform_health.status=ok`, picks "New job".
2. Fills a form backed by `query_workflow_request/v1`: dataset, services, scope, join key, filters.
3. The console dry-runs (`POST /v1/query-workflow` with `--execute=false`), shows the resolved policy, the bridge job-meta preview, the SSE export decision.
4. Operator confirms; the console hits `POST /v1/jobs/start`, then polls `GET /v1/jobs/{job_id}` until terminal.
5. Once done, the console renders the public report, links to the audit chain, and offers a "Verify tamper" button (CLI fallback for now).
6. `compliance_auditor` later opens the same job through the Audit section, runs `verify_audit_bundle` and `verify_audit_tamper_resistance` over it (or sees their pre-computed reports), and exports the GDPR evidence pack.
7. `recovery_service_operator` separately watches the Recovery section for `/metrics` rate-limit denies, signature failures, and TLS state.

Every step is already implemented as an HTTP endpoint or CLI today; the console is glue.

## 6. Smoke Surface

[`scripts/render_operator_console_manifest.py`](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/render_operator_console_manifest.py) materializes the checked-in manifest, validates it against the schema, and emits `operator_console_manifest_report/v1` (frozen). Default contract smoke validates that report and asserts every required section exists, every backing endpoint references one of the existing HTTP wrappers, and every role-gate value matches a known `platform_role`.

This means even before the SPA exists, operators have a contract that captures:

- Which sections will exist.
- Which HTTP endpoints back each section.
- Which roles see what.
- Which capability flags the SPA must branch on.

The static checked-in [`config/operator_console/index.html`](/home/llvanion/Desktop/seccomp-privacy-platform/config/operator_console/index.html) is a minimal single-page placeholder that lists every section, links to its backing endpoint(s), and reads `console_manifest.json` at runtime via `fetch`. It is the bridge that makes the spec concrete without committing to a framework.

## 7. Operator Onboarding

```bash
# 1. Validate the console manifest contract.
python3 scripts/render_operator_console_manifest.py \
  --output tmp/operator_console_manifest_report.json

# 2. Validate against the schema.
python3 scripts/validate_json_contract.py \
  --schema schemas/operator_console_manifest_report.schema.json \
  --json tmp/operator_console_manifest_report.json

# 3. Open the static console placeholder while the SPA is being built.
python3 -m http.server 18099 --directory config/operator_console
# then visit http://127.0.0.1:18099/index.html
```

## 8. Out of Scope (Phase-2)

These are deliberately *not* in the current baseline:

1. Framework choice (React / Vue / Svelte). The manifest contract makes this swappable.
2. Realtime push (SSE / WebSocket) for live job state. The polling approach used by the existing dashboard is sufficient for the demo story.
3. Self-service tenant onboarding. The existing `apply-registry` CLI flow stays authoritative.
4. Custom theme / brand. The static placeholder is intentionally plain.

## 9. Overlap with I3 — Workflow & Approval

The production-readiness backlog item §4.4 ("No mature operator dashboard / workflow / admin UI as a product") partially overlaps with the production-readiness block **I3 — Self-Service Data Request Portal** in [`docs/PRODUCTION_READINESS_GUIDEBOOK.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PRODUCTION_READINESS_GUIDEBOOK.md). Track-E3 carves up the overlap as follows:

| Concern | Track-E3 (this doc) | I3 (production-readiness) |
|---------|---------------------|---------------------------|
| Section + endpoint inventory across the whole console | **Owns** — `console_manifest/v1` is the source of truth. | Reads the manifest; does not redefine it. |
| Information architecture (9 baseline sections) | **Owns** — section list is frozen here. | Adds the *contents* of the `requests` workflow inside the existing `jobs` / `permissions` sections. |
| Submit / approve / reject lifecycle (durable workflow) | Documents the lifecycle here for completeness; implementation is I3. | **Owns** — endpoints, role gates, durable receipts. |
| Identity → role gate enforcement | Documents the matrix here; the manifest's `roles_allowed` is contractually stable. | **Owns** — runtime enforcement against `api_identity_resolution/v1`. |
| Existing operator dashboard (Tranche B `PJC X-UI`) | Documents the dashboard's place in the manifest's `jobs` section. | Not in scope — the X-UI shell stays under [`docs/CONTROL_PANEL_SPEC.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/CONTROL_PANEL_SPEC.md). |

The split rule: **Track-E3 freezes the surface; I3 fills the surface in.** A change to the section/endpoint inventory must update the manifest (Track-E3); a change to the approval workflow inside the existing `jobs` / `permissions` sections is an I3 change and does not need a Track-E3 doc revision.

## 10. Approval / Workflow Lifecycle (I3 repo-side implementation)

This section is now repo-side implemented as of 2026-05-08. I3-a (`POST /v1/request/submit`) persists pending requests; I3-b adds list/detail/approve/reject and starts the existing dashboard job path after approval. The lifecycle uses `operator_request_submission/v1` for each request record, `operator_request_submission_list/v1` for the review queue, and reuses the existing dashboard/query workflow sidecars once an approved request launches.

### 10.1 States

```
draft (client-only)
  └─[POST /v1/request/submit]─► pending_approval
                                  ├─[approve]─► approved ──► running ──► completed | failed
                                  └─[reject]──► rejected
running ──[stage gate failure]──► failed
completed | failed | rejected ──[immutable: write-once]──► ARCHIVED
```

| State | Source of truth | Visible to |
|-------|-----------------|-----------|
| `pending_approval` | `metadata_db.workflow_submissions` row + `control_plane_mutations` audit | submitter (own row), approvers in same tenant, `compliance_auditor` |
| `approved` | `workflow_submissions.approved_by/approved_at_utc` + `control_plane_mutations.operation='approve_request'` + dashboard job launch | submitter, approvers, auditor |
| `running` / `completed` / `failed` | existing `jobs/{job_id}` lifecycle in the operator dashboard | same as `jobs` section role gates |
| `rejected` | `workflow_submissions.rejection_reason` + `control_plane_mutations.operation='reject_request'` with `reason` text | submitter, approvers, auditor |

### 10.2 Endpoints

| Method | Path | Service | Role |
|--------|------|---------|------|
| `POST` | `/v1/request/submit` | `serve_operator_dashboard` | `query_submitter` — **implemented 2026-05-08** |
| `POST` | `/v1/request/{submission_id}/approve` | `serve_operator_dashboard` | `privacy_operator` or `platform_admin` (NOT same resolved caller as submitter; see §10.3) — **implemented 2026-05-08** |
| `POST` | `/v1/request/{submission_id}/reject` | `serve_operator_dashboard` | `privacy_operator`, `platform_admin`, or `compliance_auditor` — **implemented 2026-05-08** |
| `GET` | `/v1/requests?tenant_id=&status=` | `serve_operator_dashboard` | submitter own rows; `commerce_ops_owner`, `compliance_auditor`, `privacy_operator`, `platform_admin` per tenant/scope — **implemented 2026-05-08** |
| `GET` | `/v1/requests/{submission_id}` | `serve_operator_dashboard` | submitter (own row), reviewers in same tenant, platform admins, auditors — **implemented 2026-05-08** |

Submitted requests are persisted in `metadata_db.workflow_submissions`, write a matching `control_plane_mutations` row with `operation='submit_request'`, and return `operator_request_submission/v1`. The submit path validates the normalized request against `query_workflow_request/v1` and redacts `token_secret` in `request_summary`. Approval/rejection transitions append state history, write mutation rows, and expose the latest state through detail/list responses. The approval path reserves a dashboard job slot before the approval commit and starts the job after commit, so a launch quota conflict does not leave a request falsely approved.

### 10.3 Separation of Duties

Same-identity submit→approve must be rejected at the HTTP boundary with `403 same_identity_self_approval`. The check is on the resolved `caller_id` from `api_identity_resolution/v1`, NOT on bearer-token equality, so identity providers that mint multiple tokens for the same caller do not silently bypass it.

### 10.4 Audit Integration

Every state transition now:

1. Writes a `control_plane_mutations` row with `entity_type='workflow_submission'` and the action verb (`submit_request`, `approve_request`, `reject_request`).
2. Reuse the existing `audit_chain/v1` record once the approved job runs — no separate "approval audit" stream is introduced.
3. Surface the most recent transition in `GET /v1/requests/{submission_id}` so the SPA can render a state-history timeline without reading the metadata DB directly.

### 10.5 Console Manifest Hook (Phase-2)

I3-a added the `requests` section to `console_manifest/v1` and the `approval_workflow` feature flag. I3-b expanded that section with submit/list/detail/approve/reject endpoints. The schema (`schemas/console_manifest.schema.json`) already permits arbitrary additional sections, and the contract smoke expected-section set now includes `requests`, so the manifest and smoke are aligned.

## 11. Admin Surfaces (Admin-as-Product)

This section narrows item §4 of the platform brief: **"admin UI as a product"**. It distinguishes operator-day-to-day work (already covered by the 9 baseline sections) from rarer, governance-grade administrative work that needs a separate surface.

### 11.1 Admin Sections (Phase-2 manifest extensions)

| Section id | Title | Purpose | Backing CLI today | Role gate |
|-----------|-------|---------|-------------------|-----------|
| `admin_registry` | Registry & Policy Apply | Drive `apply-registry` runs against `metadata_registry/v1` manifests, view the diff, mutation log, and rollback. | `manage_metadata_db.py apply-registry` + `query_mutation_log.py` | `platform_admin`, `compliance_auditor` |
| `admin_keys` | Keys & Issuers | Lifecycle: rotate keyring versions, mark `key_versions` deactivated, rotate issuer credentials, run `check_key_backend_drift.py --repair`. | `manage_keyring.py`, `rotate_issuer_credentials.py`, `check_key_backend_drift.py` | `platform_admin` |
| `admin_authority` | Authority Adapters | Live OpenFGA tuple sync, Vault PKI cert rotate, OIDC client-credentials rotate, KMS reachability check. | `sync_openfga_tuples.py`, `issue_mtls_certs.py`, `request_oidc_client_credentials.py`, `check_kms_reachability.py` | `platform_admin` |
| `admin_workflow` | Workflow Approvals | The I3 approval queue (see §10). | `serve_operator_dashboard.py` (post-I3) | `privacy_operator`, `compliance_auditor` |
| `admin_retention` | Retention & Reconcile | Drive `materialize_control_plane_deepening.py --list-entity retention-reconcile-plan`, mark items reviewed, schedule archive moves. | `materialize_control_plane_deepening.py`, `archive_audit_bundle.py`, `publish_external_audit_anchor.py` | `compliance_auditor`, `platform_admin` |
| `admin_external_anchor` | External Anchors | Publish/verify external audit anchor; manage tenant ledger paths. | `publish_external_audit_anchor.py` | `compliance_auditor` |

### 11.2 Why a Separate Admin Surface (and Not More Buttons in the Operator Console)

1. **Different review frequency.** Operator-day actions (run a query, check audit) happen many times per day; admin actions (apply registry, rotate keys, approve a workflow) happen weekly or monthly and need an audit trail per click.
2. **Different role gate.** `platform_admin` and `compliance_auditor` have powers `commerce_ops_owner` does not. Folding them into the operator console would force every section to ship a `platform_admin`-only sub-button, which is a recipe for accidental UI exposure.
3. **Different change-control discipline.** Admin actions are mutations; the registry / policy / key changes go through `control_plane_mutations` and the change-request process under `docs/change_requests/`. Mixing them with read-mostly operator actions weakens that discipline.
4. **Different deployment surface.** The admin console can be reachable only on the operator-bastion subnet (or behind step-up auth), while the day-to-day operator console can sit behind standard SSO.

### 11.3 Forward Plan

When the I3 work picks up, the SPA should render `admin_*` sections as a separate top-level "Admin" group with its own role gate at the layout level — not as additional cards inside Home / Jobs. The `console_manifest/v1` schema already supports this without any structural change: each admin section is just another entry in the `sections` array with a stricter `roles_allowed`.

## 12. Relation to Existing Documents

| Document | What it owns | What this doc adds |
|----------|--------------|--------------------|
| [`docs/CONTROL_PANEL_SPEC.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/CONTROL_PANEL_SPEC.md) | The PJC X-UI loopback shell layout (Tranche B `B9-B12`): UI state machine, four operator blocks, embedded HTML structure. | Wraps that shell as one section (`jobs`) of the larger console product and sets the role-gate matrix above it. |
| [`docs/QUERY_INTERFACE_PLAN.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/QUERY_INTERFACE_PLAN.md) | The `query_workflow_request/v1` and `query_workflow_submission/v1` contracts, plus the submit/execute split. | Documents how the console renders each contract field and which role gates which path. |
| [`docs/OPS_RUNBOOK.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPS_RUNBOOK.md) | Operator-side runbook commands (deploy, recover, alert). | Documents how the console exposes those commands as buttons (or hides them behind admin-only sections). |
| [`docs/PRODUCTION_READINESS_GUIDEBOOK.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PRODUCTION_READINESS_GUIDEBOOK.md) §6 | The I1/I2/I3 production-readiness blocks. | This doc is the surface contract; I3 is the workflow implementation. The split rule is documented in §9 above. |
| [`docs/CATALOG_LINEAGE_PLAN.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/CATALOG_LINEAGE_PLAN.md) | The `catalog_lineage/v1` contract used by the `catalog` console section. | None — Track-E3 just references the contract; lineage stays under that plan. |
