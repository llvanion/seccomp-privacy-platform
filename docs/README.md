# Documentation Map

This directory now uses a small set of authoritative entry points. Older deep
dives are preserved because they contain implementation details, but they should
not be used as the current project-status source of truth unless an entry point
below links to them for detail.

## Start Here

1. [CURRENT_SECURITY_AND_COMPLETION_AUDIT.md](CURRENT_SECURITY_AND_COMPLETION_AUDIT.md)  
   Current answer to: is the protocol safe, is the feature set complete, what
   realistic attacks remain, and how to keep finding project problems.

2. [REMAINING_WORK_IMPLEMENTATION_BACKLOG.md](REMAINING_WORK_IMPLEMENTATION_BACKLOG.md)  
   Implementation-level backlog for all known remaining work, including files
   to change, tests to add, and completion evidence.

3. [ATTACKER_REVIEWER_TODO.md](ATTACKER_REVIEWER_TODO.md)  
   Rebuttal-facing TODO list from attacker, reviewer, and production-operator
   viewpoints.

4. [NEXT_SESSION_READING_GUIDE.md](NEXT_SESSION_READING_GUIDE.md)
   Minimal handoff order for the next engineer/session.

5. [COMPACT_PLATFORM_BRIEF.md](COMPACT_PLATFORM_BRIEF.md)
   Short project overview and module map.

6. [ONLINE_OFFLINE_SECURITY_GOVERNANCE.md](ONLINE_OFFLINE_SECURITY_GOVERNANCE.md)
   Mixed repo-side / operator-side governance map for source truthfulness,
   release legitimacy, trust-root dependencies, remaining risks, and
   competition-safe wording.

7. [IDEAL_PRODUCTION_PLATFORM_NARRATIVE.md](IDEAL_PRODUCTION_PLATFORM_NARRATIVE.md)
   Detailed target-state narrative for the ideal production platform, including
   product story, security boundaries, query flow, evidence package, and claim
   limits.

8. [OPERATOR_HANDOFF_QUICKSTART.md](OPERATOR_HANDOFF_QUICKSTART.md)
   Minimal operator commands and contract index retained from the previous
   long handoff guide.

## Current Planning Documents

- [PRODUCTION_SECURITY_COMPLETION_PLAN.md](PRODUCTION_SECURITY_COMPLETION_PLAN.md): production-security task packages and three-person certification standard.
- [PJC_MTLS_OPEN_RISKS.md](PJC_MTLS_OPEN_RISKS.md): PJC/mTLS evidence, open public-network validation, and DP/PJC hardening limits.
- [POST_BASELINE_ROADMAP.md](POST_BASELINE_ROADMAP.md): post-baseline product/platform roadmap.
- [OWNER_MAINLINE_CHANGE_CHECKLIST.md](OWNER_MAINLINE_CHANGE_CHECKLIST.md): owner-side frozen-contract and mainline change checklist.
- [INTERFACE_FREEZE_AND_CHANGE_PROCESS.md](INTERFACE_FREEZE_AND_CHANGE_PROCESS.md): how to change frozen contracts safely.

## Security And Implementation Detail

- [THREAT_MODEL_AND_LEAKAGE_MODEL.md](THREAT_MODEL_AND_LEAKAGE_MODEL.md)
- [CODE_REVIEW_SUMMARY.md](CODE_REVIEW_SUMMARY.md)
- [CODE_REVIEW_01_SSE.md](CODE_REVIEW_01_SSE.md)
- [CODE_REVIEW_02_BRIDGE.md](CODE_REVIEW_02_BRIDGE.md)
- [CODE_REVIEW_03_APSI.md](CODE_REVIEW_03_APSI.md)
- [CODE_REVIEW_04_RECORD_RECOVERY.md](CODE_REVIEW_04_RECORD_RECOVERY.md)
- [CODE_REVIEW_05_SCRIPTS_PIPELINE.md](CODE_REVIEW_05_SCRIPTS_PIPELINE.md)
- [CODE_REVIEW_06_SQL_SIDECAR.md](CODE_REVIEW_06_SQL_SIDECAR.md)
- [CODE_REVIEW_07_SCHEMAS.md](CODE_REVIEW_07_SCHEMAS.md)
- [CODE_REVIEW_08_KEY_MANAGEMENT.md](CODE_REVIEW_08_KEY_MANAGEMENT.md)
- [CODE_REVIEW_09_SIDECAR_EXPORTERS.md](CODE_REVIEW_09_SIDECAR_EXPORTERS.md)
- [CODE_REVIEW_10_SECURITY_TOOLING.md](CODE_REVIEW_10_SECURITY_TOOLING.md)
- [CODE_REVIEW_11_HTTP_ADAPTERS.md](CODE_REVIEW_11_HTTP_ADAPTERS.md)
- [CODE_REVIEW_12_REPLAY_AND_BENCHMARKS.md](CODE_REVIEW_12_REPLAY_AND_BENCHMARKS.md)

## Domain And Control-Plane Detail

- [ECOMMERCE_ACCESS_MODEL.md](ECOMMERCE_ACCESS_MODEL.md)
- [ECOMMERCE_FACT_LAYER_PLAN.md](ECOMMERCE_FACT_LAYER_PLAN.md)
- [CONTROL_PLANE_SCHEMA.md](CONTROL_PLANE_SCHEMA.md)
- [CONTROL_PANEL_SPEC.md](CONTROL_PANEL_SPEC.md)
- [QUERY_INTERFACE_PLAN.md](QUERY_INTERFACE_PLAN.md)
- [CATALOG_LINEAGE_PLAN.md](CATALOG_LINEAGE_PLAN.md)
- [PRIVACY_BUDGET_PRODUCTION_CLOSED_LOOP.md](PRIVACY_BUDGET_PRODUCTION_CLOSED_LOOP.md)

## Operations, Release, And Evidence

- [OPS_RUNBOOK.md](OPS_RUNBOOK.md)
- [BENCHMARK_PLAN.md](BENCHMARK_PLAN.md)
- [RELEASE_PROCESS.md](RELEASE_PROCESS.md)
- [AWS_S3_WORM_INTERFACE_STATUS.md](AWS_S3_WORM_INTERFACE_STATUS.md)
- [S7_K3_LIVE_EVIDENCE_REPORT.md](S7_K3_LIVE_EVIDENCE_REPORT.md)
- [team/TEAM_COLLABORATION_AND_REPORTING_PLAN.md](team/TEAM_COLLABORATION_AND_REPORTING_PLAN.md)

## Historical Baseline Documents

These documents are retained for implementation history and traceability. Their
status statements may predate the current audit.

- [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](PLATFORM_LEVEL_REMAINING_ESTIMATE.md)
- [PRODUCTION_READINESS_GUIDEBOOK.md](PRODUCTION_READINESS_GUIDEBOOK.md)
- [SESSION_B3_OBSERVABILITY_DASHBOARD_2026-05-03.md](SESSION_B3_OBSERVABILITY_DASHBOARD_2026-05-03.md)
- [SESSION_B4-B8_PLATFORM_BASELINE_COMPLETE_2026-05-03.md](SESSION_B4-B8_PLATFORM_BASELINE_COMPLETE_2026-05-03.md)
