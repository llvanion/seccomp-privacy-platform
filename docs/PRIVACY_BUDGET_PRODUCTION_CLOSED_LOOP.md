# Privacy Budget Production Closed Loop

Generated local verification date: 2026-05-20
Latest repo-side update: 2026-06-01

This document records the current production-style closure for the S3
privacy-budget / differencing-attack defense. It is repo-local evidence; it
does not claim a live metadata-sidecar deployment until the operator query
entry point uses the same required mode.

## Implemented

`policy_release.py` now supports production privacy-budget mode:

- `--privacy-budget-required`: fail closed when release mode is enabled without
  a ledger.
- `--privacy-budget-config`: load `privacy_budget_config/v1` scope rules.
- `--tenant-id`, `--dataset-id`, `--purpose`: bind budget consumption to a
  caller + tenant + dataset + purpose scope.
- `--privacy-budget-store`: optional transactional SQLite store path. By
  default, enabling `--privacy-budget-ledger` also enables a store at
  `<privacy-budget-ledger>.sqlite`.
- `--privacy-budget-disable-transactional-store`: explicit legacy/debug escape
  hatch for JSONL-only behavior.
- Missing scope is denied as `privacy_budget_missing_scope` when the configured
  default has `max_queries=0`.
- The ledger now records `tenant_id`, `dataset_id`, and `purpose`, so repeated
  and near-duplicate checks are scoped to the production privacy boundary.
- The default release path now treats the SQL store as the write authority:
  existing JSONL rows are bootstrapped by record hash, same-scope prior records
  are read under `BEGIN IMMEDIATE`, the decision is reserved before report
  publication, and JSONL remains an audit/export format.

## Local Evidence

Run:

```bash
bash scripts/run_s3_privacy_budget_production_evidence.sh
```

Evidence directory:

```text
tmp/s3_privacy_budget_production_evidence/
```

Cases covered:

| Case | Expected | Reason |
| --- | --- | --- |
| required without ledger | fail closed | production release cannot run without budget ledger |
| configured scope first release | allow | first release consumes one budget unit |
| exact duplicate | deny | `privacy_budget_duplicate_query` |
| overlapping window | deny | `privacy_budget_near_duplicate` |
| budget exhausted | deny | `privacy_budget_exhausted` |
| missing scope | deny | `privacy_budget_missing_scope` |

Additional concurrency gate:

```bash
python3 scripts/check_privacy_budget_concurrency.py
```

This launches two simultaneous policy releases with budget headroom for one.
The expected result is one `released=true` report, one
`privacy_budget_exhausted` deny, two JSONL ledger events, and SQL store rows
showing one committed consumed allow plus one committed deny.

## Consolidated Gate

The consolidated attack-surface evidence runner now includes this case as:

```text
s3_privacy_budget_production_evidence
```

Run:

```bash
bash scripts/run_attack_surface_hardening_evidence.sh
```

## Production Status

Current status: local production-style closed loop completed for default
release, with repo-side operator/query submission wiring now passing the same
required/config/ledger/approval-queue and scope fields into Stage4 release.
Concurrent budget double-spend and one-time near-duplicate approval consumption
are covered by the SQLite transactional store and default smoke gates. The
remaining production gap is first-class operator HTTP/API wiring and live
PostgreSQL/HA evidence.

Suggested final-report wording:

```text
S3 privacy-budget / differencing-attack defense has a local production-style
closed loop. The release path now supports fail-closed required mode, scoped
budget configuration, scoped ledger accounting, exact-duplicate denial,
overlapping-window denial, budget-exhaustion denial, and missing-scope denial.
The evidence package passed locally with 6/6 cases.
```

Do not use this stronger wording yet:

```text
S3 is fully production deployed and jointly certified.
```

Repo-side update on 2026-05-26:

- `query_workflow_request/v1` accepts `privacy_budget_required`,
  `privacy_budget_config`, `privacy_budget_ledger`,
  `privacy_budget_purpose`, `privacy_budget_limit`, and
  `privacy_budget_cost`.
- `submit_query_workflow.py` validates required/config/ledger coupling and
  includes those fields in the pipeline command.
- `run_sse_bridge_pipeline.sh` forwards tenant / dataset / purpose and privacy
  budget controls to `policy_release.py`.
- Default contract smoke includes a dry-run command assertion for this wiring.

Remaining before claiming live production closure:

- Persist and operate the consumption table in the metadata sidecar or
  equivalent production storage, then run the same concurrency evidence against
  that live store.
- Run deployed browser-console evidence for approval approve/reject/expire/list;
  the authenticated operator HTTP API and repo-side SPA controls now exist.
- Run the same evidence flow on the VPS/public deployment.
- Add joint certification evidence for the live deployment run.

## 2026-06-01: Transactional Budget Consumption

The JSONL ledger is no longer the default write authority for budget
consumption. `policy_release.py` now uses `PrivacyBudgetStore` when a privacy
budget ledger is configured:

- Store path: explicit `--privacy-budget-store`, otherwise
  `<privacy-budget-ledger>.sqlite`.
- Transaction boundary: `BEGIN IMMEDIATE`, evaluate prior same-scope records,
  insert a `reserved` event for allowed consumes, write reports and audit
  outputs, then mark the event `committed`.
- Failure handling: if output writing fails after a reserve, the row is marked
  `failed_after_reserve` before commit so the failed attempt remains visible.
- Uniqueness: a partial unique index rejects a second reserved/committed
  allowed consume for the same `(scope_key, query_fingerprint)`.
- Migration: `migrations/metadata/014_add_privacy_budget_consumption.sql`
  defines `privacy_budget_consumption_events`; PostgreSQL bootstrap DDL has the
  same table and indexes for parity.
- Gate: `scripts/check_privacy_budget_concurrency.py` is included in
  `scripts/check_ci_smoke.sh`.

## 2026-06-01 v2: Approval Consume Close-Loop

Near-duplicate approvals now have repo-side lifecycle state:

- Pending queue records remain `privacy_budget_approval_request/v1`.
- Decisions are recorded as `privacy_budget_approval_decision/v1` JSONL events.
- `privacy_budget_approval_events` stores pending, approved, rejected, expired,
  and consumed states in the same transactional SQLite store.
- `scripts/manage_privacy_budget_approval.py` handles approve/reject/expire and
  rejects same-identity self approval.
- `policy_release.py --privacy-budget-approval-id` validates approved status,
  scope, query fingerprint, expiry, and actor separation, then consumes the
  approval in the same transaction as the budget consume.
- `scripts/check_privacy_budget_approval_flow.py` proves approve + one-time
  consume, rejected/expired approvals not consumable, and consumed approvals
  not reusable. It is included in `scripts/check_ci_smoke.sh`.

## 2026-06-01 v3: Operator Approval HTTP API

Approval review is no longer limited to `manage_privacy_budget_approval.py`.
`serve_operator_dashboard.py` now exposes:

- `GET /v1/privacy-budget/approvals`
- `POST /v1/privacy-budget/approval/{request_id}/approve`
- `POST /v1/privacy-budget/approval/{request_id}/reject`
- `POST /v1/privacy-budget/approval/{request_id}/expire`

The API requires resolved identity-token authentication, enforces caller/tenant
view scope, allows platform admins/auditors to review globally, allows tenant
privacy operators/compliance auditors to review matching-tenant requests, blocks
same-identity self approval, and requires reasons for reject/expire. Successful
approve/reject/expire transitions write `privacy_budget_approval_decision/v1`
JSONL evidence and update the same `privacy_budget_approval_events` store used
by `policy_release.py`.

New contracts and gates:

- `privacy_budget_approval_list/v1`
- `privacy_budget_approval_transition/v1`
- `scripts/check_privacy_budget_approval_api_smoke.py`

The operator console SPA also has `/privacy-budget-approvals` for queue
filtering, request inspection, and approve/reject/expire actions, and
`console_manifest/v1` advertises `privacy_budget_approvals` with the
`privacy_budget_approval_workflow` feature flag.

## 2026-05-23 v2: Server-Side Release Policy Gate

The CLI bypass risk in `policy_release.py` (an operator forgetting
`--require-dp` or `--privacy-budget-required`) is now closed by a
server-side gate that runs independently of the CLI:

- `POST /v1/release/policy-gate` on `scripts/serve_operator_dashboard.py`
  delegates to `scripts/check_release_policy_gate.py`.
- The gate consumes a `release_policy_gate_config/v1` file
  (`config/release_policy_gate.example.json` for strict production, or
  `config/release_policy_gate.local-contract.example.json` for local contract
  fixtures) plus the candidate `public_report.json` (and optional operator
  report + privacy budget ledger). It enforces:
  - `require_dp` → released reports must carry `dp_noise_applied=true` and
    an `dp_epsilon` within `[min_dp_epsilon, max_dp_epsilon]`.
  - `min_k` → released reports must declare `k_threshold >= min_k`.
  - `require_privacy_budget` → the ledger must exist and must contain an
    `allow` record for the released `job_id`.
  - `allowed_deny_reason_codes` → denied releases must use a configured
    reason code; out-of-policy denials are rejected.
  - `duplicate_query_denied` → defense in depth — fails the gate if the
    operator report shows a duplicate-query budget decision that was
    nevertheless released.
  - `require_pjc_evidence_merge` → production config requires
    `pjc_two_party_evidence_merge/v1` and checks its result hashes against the
    `policy_audit/v1` `pjc_result_sha256` before public release.
  - `require_external_anchor` → strict production config requires an uploaded
    S3 Object Lock/Rekor `external_audit_anchor_report/v1`; missing, local,
    planned, unuploaded, or production-finding anchor reports deny release.
- Output: `release_policy_gate/v1` with per-check status, first failing
  finding, public-report SHA-256, PJC evidence path, policy-audit path, and
  external-anchor report path. Wired into the contracts gate via the new schemas
  in `scripts/check_json_contracts.sh`.
- Smoke: `scripts/check_release_policy_gate_smoke.py` (11/11 cases pass locally
  on 2026-06-03) — missing ledger, low-k, missing DP, allowed release,
  duplicate-query leak, public operator-field leak, bound PJC evidence allow,
  PJC result replacement denial, missing external anchor denial, planned/local
  external anchor denial, and uploaded S3 Object Lock anchor allow. Registered
  in `scripts/check_ci_smoke.sh`.
- Operator-visible state is tied to the same decision. `serve_operator_dashboard.py`
  maps external-anchor release-gate denials to `pending_external_anchor`, maps
  other gate denials to `blocked`, exposes that state in both full and
  caller-safe dashboard summaries, and uses it for `/v1/runs?state=...`
  filtering.

Use this gate as the canonical "should this release become public" check;
the CLI flags remain useful for ergonomics but they are no longer the
trust boundary.
