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
npm --prefix console run build
python3 -m pytest sse/test
```

In this workspace on 2026-06-01, the console and pytest commands are known
environment gaps: no committed console lockfile/working `.bin` tools, and no
active `pytest` install.

## What Not To Do

1. Do not treat session reports as the top-level project state.
2. Do not close a security issue by documenting it only; add a code gate or a
   production-mode refusal path.
3. Do not claim malicious-security for PJC unless the protocol and code are
   changed to support that claim.
4. Do not expose `sse/frontend/server/` outside loopback unless the legacy/demo
   API is retired or hardened with production auth, TLS/service identity, abuse
   limits, and deployment gates.
