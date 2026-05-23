# Privacy Budget Production Closed Loop

Generated local verification date: 2026-05-20

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
- Missing scope is denied as `privacy_budget_missing_scope` when the configured
  default has `max_queries=0`.
- The ledger now records `tenant_id`, `dataset_id`, and `purpose`, so repeated
  and near-duplicate checks are scoped to the production privacy boundary.

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

Current status: local production-style closed loop completed.

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

Remaining before claiming live production closure:

- Wire `--privacy-budget-required`, `--privacy-budget-config`, and scope fields
  into the operator query submission path.
- Persist the ledger and config source in the metadata sidecar or equivalent
  production storage instead of local files.
- Run the same evidence flow on the VPS/public deployment.
- Add joint certification evidence for the live deployment run.

## 2026-05-23 v2: Server-Side Release Policy Gate

The CLI bypass risk in `policy_release.py` (an operator forgetting
`--require-dp` or `--privacy-budget-required`) is now closed by a
server-side gate that runs independently of the CLI:

- `POST /v1/release/policy-gate` on `scripts/serve_operator_dashboard.py`
  delegates to `scripts/check_release_policy_gate.py`.
- The gate consumes a `release_policy_gate_config/v1` file
  (`config/release_policy_gate.example.json`) plus the candidate
  `public_report.json` (and optional operator report + privacy budget
  ledger). It enforces:
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
- Output: `release_policy_gate/v1` with per-check status, first failing
  finding, and the public-report SHA-256. Wired into the contracts gate
  via the new schemas in `scripts/check_json_contracts.sh`.
- Smoke: `scripts/check_release_policy_gate_smoke.py` (5/5 cases pass
  locally on 2026-05-23) — missing ledger, low-k, missing DP, allowed
  release, duplicate-query leak. Registered in `scripts/check_ci_smoke.sh`.

Use this gate as the canonical "should this release become public" check;
the CLI flags remain useful for ergonomics but they are no longer the
trust boundary.
