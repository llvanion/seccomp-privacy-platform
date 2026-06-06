# Next Session Reading Guide

This guide is the short handoff path. It deliberately avoids making the next
engineer re-read the entire `docs/` directory.

## Read First

1. [docs/README.md](README.md)
   Documentation map and which files are authoritative.

2. [CURRENT_SECURITY_AND_COMPLETION_AUDIT.md](CURRENT_SECURITY_AND_COMPLETION_AUDIT.md)
   Current answer to protocol safety, functional completeness, realistic attack
   resistance, software-security gaps, and the problem-identification plan.

3. [REMAINING_WORK_IMPLEMENTATION_BACKLOG.md](REMAINING_WORK_IMPLEMENTATION_BACKLOG.md)
   Concrete backlog for every known remaining task: target files, implementation
   steps, gates, and evidence.

4. [COMPACT_PLATFORM_BRIEF.md](COMPACT_PLATFORM_BRIEF.md)
   Project shape, main modules, and current baseline capabilities.

5. [PRODUCTION_SECURITY_COMPLETION_PLAN.md](PRODUCTION_SECURITY_COMPLETION_PLAN.md)
   Production-security work packages and completion standard.

6. [OPERATOR_HANDOFF_QUICKSTART.md](OPERATOR_HANDOFF_QUICKSTART.md)
   Minimal operator commands and contract index.

## Read By Task

| Task | Read |
| --- | --- |
| Owner/mainline privacy flow | `TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md`, `THREAT_MODEL_AND_LEAKAGE_MODEL.md`, `SSE_BRIDGE_APSI_PIPELINE.md`, `BRIDGE_HANDOFF_HARDENING_PLAN.md` |
| SSE / legacy server safety | `CODE_REVIEW_01_SSE.md`, `sse/API_Docs.md`, then inspect `sse/frontend/server/` source before making claims |
| Bridge/tokenization | `CODE_REVIEW_02_BRIDGE.md`, `bridge/README.md`, `bridge/src/main.rs` |
| PJC/APSI and mTLS | `CODE_REVIEW_03_APSI.md`, `PJC_MTLS_OPEN_RISKS.md`, `PJC_TLS_GUIDE.md` |
| Record recovery service | `CODE_REVIEW_04_RECORD_RECOVERY.md`, `RECORD_RECOVERY_INDEPENDENT_SERVICE_PLAN.md`, `services/record_recovery/` |
| Privacy budget | `PRIVACY_BUDGET_PRODUCTION_CLOSED_LOOP.md`, then inspect `a-psi/moduleA_psi/scripts/policy_release.py` and `migrations/metadata/013_add_privacy_budget_ledger_read_model.sql` |
| IAM / KMS / authority sources | `TASK_ENGINEER_A_CONTROL_PLANE_IDENTITY_ACCESS.md`, `IAM_AUTHZ_INTEGRATION_PLAN.md`, `KMS_SECRET_BACKEND_PLAN.md` |
| SQL control plane | `DELEGATION_ENGINEER_2_SQL_CONTROL_PLANE.md`, `CONTROL_PLANE_SCHEMA.md` |
| Operator dashboard / workflows | `BENCHMARK_PLAN.md`, `OPS_RUNBOOK.md`, `QUERY_INTERFACE_PLAN.md`, `OPERATOR_CONSOLE_PRODUCT_PLAN.md` |
| Release and packaging | `RELEASE_PROCESS.md`, `.github/workflows/release.yml`, `.github/workflows/json-contracts.yml` |

## Current Rule For Status Claims

Do not use older wording such as "only one block remains" or "platform complete"
without qualifying the scope. Use:

- `baseline-complete`
- `repo-side complete`
- `partial`
- `operator-side evidence required`
- `production-complete`

The definitions are in
[CURRENT_SECURITY_AND_COMPLETION_AUDIT.md](CURRENT_SECURITY_AND_COMPLETION_AUDIT.md#3-status-vocabulary).

## Minimum Verification Before Reporting Progress

```bash
bash scripts/check_ci_smoke.sh
cargo test
```

Before any release or production-readiness claim, also require:

```bash
npm --prefix console ci
npm --prefix console run typecheck
npm --prefix console run build:strict
python3 -m pytest sse/test
python3 scripts/check_supply_chain_gate.py
python3 scripts/check_release_policy_gate_smoke.py
python3 scripts/check_query_workflow_durability.py --out tmp/query_workflow_durability_check.json
python3 scripts/check_record_recovery_production_gate.py --out tmp/record_recovery_production_gate_check.json
python3 scripts/check_metadata_backup_restore_drill.py --out tmp/metadata_backup_restore_drill.json
```

As of 2026-06-03, repo-side supply-chain/test gates are available:
`console/package-lock.json` is committed, `sse/requirements-dev.txt` declares
pytest, and `scripts/check_supply_chain_gate.py` validates Python/npm/Cargo
component inventory plus CI/release workflow coverage. External release
provenance and advisory evidence remain operator-side.

Also as of 2026-06-03, query workflow sidecar and metadata-DB lifecycle
protection is repo-side gated by `scripts/check_query_workflow_durability.py`:
duplicate dry-runs, duplicate executes, stale-running overwrite attempts,
active duplicate DB claims, and terminal DB replays must fail closed; expired
leases can be explicitly stolen. The same gate now covers
`scripts/run_query_workflow_worker.py` enqueue-to-worker completion, running
cancellation, timeout termination, and expired-lease restart steal. This is
still repo-side/local worker evidence; target-host supervised worker and live
PostgreSQL/HA drills remain open.

Also as of 2026-06-03, recovery-service production HTTP startup is repo-side
gated by `scripts/check_record_recovery_production_gate.py`: direct HTTP
service, standalone launcher, and managed start/render must reject missing auth,
missing authz, identity without metadata DB, identity without HMAC/mTLS, and
public listeners without mTLS.

Also as of 2026-06-03, metadata backup/restore has repo-side integrity evidence:
`restore_metadata_db.py --backup-report` binds restore to
`metadata_db_backup_report/v1.backup.sha256`, and
`scripts/check_metadata_backup_restore_drill.py` proves backup verification,
SHA-bound restore, restored probe-row presence, schema portability, and
tampered-backup denial. This does not close live PostgreSQL/Patroni/pgBouncer HA,
external backup storage, or target-host restore/API smoke evidence.

Also as of 2026-06-03, the final release gate can require uploaded external
immutable audit anchoring: strict `config/release_policy_gate.example.json`
sets `require_external_anchor=true`; `scripts/check_release_policy_gate.py`
accepts only uploaded S3 Object Lock/Rekor `external_audit_anchor_report/v1`
reports with verified chain and no production findings; `run_sse_bridge_pipeline.sh`,
`submit_query_workflow.py`, and `benchmark_pipeline.py` fail closed when strict
production config omits the report. Live S3/Rekor credentials and read-back
evidence remain operator-side.

Also as of 2026-06-03, dashboard-visible release state is release-gate-aware:
`serve_operator_dashboard.py` maps external-anchor denials to
`pending_external_anchor`, maps other gate denials to `blocked`, exposes those
states in full/public dashboard summaries, and filters `/v1/runs?state=...`
after applying the gate overlay.

Also as of 2026-06-04, the e-commerce verifier-facing live chain understands a
dedicated logistics rollout artifact:
`tmp/logistics_live_synthetic/ecommerce_logistics_live_rollout_report.json`
is now archived into `ecommerce_live_evidence_archive/v1`, and that was enough
to move `check_ecommerce_deployment_evidence_gate.py` to `live_status=ok`. The
top-level `production_security_closure_gate/v1` now reuses standard module live
archives from `tmp/` when rerunning sub-gates, so the closure report now
surfaces `ecommerce` as `live_status=ok` instead of hiding it behind a
repo-side rerun. Since then, `control_plane`, `observability`,
`query_workflow`, `postgres_ha`, `supply_chain`, and `console` have also been
lifted with real VPS-backed rollout artifacts, and `pjc_protocol` has been
lifted with authoritative live two-host evidence plus derived signed-manifest /
release-binding reports. `public_two_host` itself now also reaches
verifier-facing `live_status=ok` by auto-consuming the authoritative
cross-vps-008 archive plus clean materialization report. Local archive state is
now explicit: `ecommerce`, `control_plane`, `observability`, `query_workflow`,
`postgres_ha`, `supply_chain`, `console`, `pjc_protocol`, `public_two_host`,
`legacy_sse`, `privacy_budget`, and `recovery_service` are verifier-facing
live-status `ok`; since then `pjc_resource_isolation` and `external_anchor`
have also now been fully lifted with refreshed canonical live archives and gate
artifacts, and `authority` has since been lifted through a real VPS-backed
docker-compose rollout for Keycloak/OpenFGA/Vault. `spiffe_envoy` has since
also been lifted through a real VPS-backed SPIRE + Envoy rollout that produced
positive-run, wrong-peer-reject, expired-SVID-reject, trust-bundle-reject,
and Envoy access-log evidence. The current authoritative closure and blocker
summary are therefore:
`tmp/production_security_closure_gate/production_security_closure_gate.json`
with `live_ok_count=16`, `live_skipped_count=0`, and
`tmp/final_live_blockers_report.json` with `remaining_live_module_count=0`.

Also as of 2026-06-04, the commerce repo-side relationship-binding tranche is
fully wired into default contracts: `business_access_api_smoke/v1` now freezes
merchant/buyer/logistics/fraud/marketer relation-spoof denials, the support
persona has a dedicated stable repo-side artifact via
`check_business_access_support_relation_binding.py`, and
`bash scripts/check_json_contracts.sh` is back to green under the current
authoritative `public_two_host` / `ecommerce` live-status semantics.

## What Not To Do

1. Do not treat session reports as the top-level project state.
2. Do not close a security issue by documenting it only; add a code gate or a
   production-mode refusal path.
3. Do not claim malicious-security for PJC unless the protocol and code are
   changed to support that claim.
4. Do not expose `sse/frontend/server/` outside loopback. The repo-side
   production decision is retirement under `SSE_PRODUCTION_MODE=1`; production
   query traffic belongs on query workflow / bridge pipeline APIs.
5. Do not claim recovery-service production networking is complete until there
   is live service-user, sandbox, firewall/NetworkPolicy, and public-network
   mTLS evidence.
6. For the next production push, start from the repo-side gates that now have
   real production remaining lists: `scripts/check_ecommerce_production_exposure_gate.py`
   for commerce data/persona/contact surfaces, `scripts/check_bucket_dp_smoke.py`
   for bucket/shard policy scope, `scripts/check_pjc_two_party_smoke.py`
   for signed two-party evidence, and
   `scripts/check_identity_jwks_evidence_gate.py` for verifier-readable
   JWKS/OIDC identity evidence. `scripts/check_live_identity_authority_evidence_gate.py`
   is the next step up: it keeps the repo-side JWKS baseline but records live
   client-credentials / live JWKS / live `/v1/identity` checks as `ok|fail|skipped`
   depending on whether operator prerequisites are present. These gates prove
   local fail-closed behavior; the remaining work is to replace local
   token/socket/file-JWKS fixtures with live
   OIDC/OpenFGA/Postgres/TLS/external-anchor evidence.
7. For public two-host PJC specifically, start with
   `scripts/check_public_two_host_production_readiness_gate.py`. It now
   combines repo-side two-party/TLS/release binding evidence, archived S7/K3
   evidence-integrity verification, and optional live management/data-plane
   probes into one verifier-facing report. If the public host is only exposing
   an HTTP-gateway pattern on candidate admin ports, treat that as a live
   blocker first rather than attempting to claim fresh two-host production
   readiness.
