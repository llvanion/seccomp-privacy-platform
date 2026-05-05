# Observability Plan

## 1. Goal

This document defines the first-stage observability shape for the privacy pipeline:

```text
SSE export -> record recovery -> bridge -> PJC -> policy release
```

The goal is not to retrofit a new metrics system into every module immediately.
The goal is to derive a stable, queryable stage-level view from the audit artifacts that already exist.

Current implementation anchors:

1. `scripts/export_observability_events.py`
2. `schemas/pipeline_observability.schema.json`
3. `scripts/serve_audit_query_api.py`
4. `scripts/benchmark_derived_views.py`
5. `docs/OPS_RUNBOOK.md`

## 2. Boundary

This observability layer is:

1. sidecar-only
2. derived from `audit_chain.json`
3. backward compatible with the frozen pipeline
4. safe to evolve faster than the main execution path

It is not:

1. a new source of truth for pipeline semantics
2. a replacement for stage-owned audit logs
3. a permission bypass around the existing audit/public-report boundary

## 3. Current Export Contract

The current output schema is:

```text
pipeline_observability/v1
```

It is generated from:

1. `sse_export_audit`
2. `record_recovery_service_audit`
3. `bridge_audit`
4. `pjc_audit`
5. `policy_audit`

The exporter reads:

```bash
python3 scripts/export_observability_events.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --out tmp/sse_bridge_pipeline_demo/pipeline_observability.json
```

Or:

```bash
python3 scripts/export_observability_events.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/pipeline_observability.json
```

## 4. Stable Fields

The stage-level event contract is built around these fields:

1. `job_id`
2. `correlation_id`
3. `caller`
4. `tenant_id`
5. `dataset_id`
6. `service_id`
7. `stage`
8. `status`
9. `ts_utc`
10. `role`
11. `decision`
12. `reason_code`
13. `duration_ms`
14. `row_count`
15. `artifact_sha256`
16. `source_event`

These fields are intentionally scoped to operational visibility rather than plaintext data exposure.

## 5. Stage Coverage

The exporter currently derives events for these stages:

1. `sse_export`
2. `record_recovery_service`
3. `bridge`
4. `pjc`
5. `policy_release`

This matches the current contract smoke expectation. Default validation also asserts that these five stages remain present.

## 6. Status Model

The current derived `status` is normalized from stage-local audit semantics:

1. `decision=allow` maps to `ok`
2. `decision=deny` maps to `error`
3. non-zero `exit_code` maps to `error`
4. release `released=true` maps to `ok`
5. release `released=false` maps to `error`
6. otherwise the exporter falls back to `unknown`

This keeps the read-side surface stable without changing the original audit payloads.

## 7. Duration Model

The preferred source of timing is now native stage-owned `duration_ms` fields:

1. SSE export audit writes `duration_ms`
2. record recovery service audit writes `duration_ms`
3. bridge audit writes `duration_ms`
4. PJC audit writes `duration_ms`
5. policy audit writes `duration_ms`

This is an important boundary rule:

1. new runs should expose actual stage durations directly
2. older runs may legitimately show `duration_ms=null`
3. the exporter should not invent pseudo-precise timings by subtracting adjacent timestamps

## 8. Row Count Model

Current `row_count` usage is intentionally conservative:

1. SSE export events use `output_rows`
2. record recovery service events use `output_rows`
3. policy release events may use `intersection_size` or equivalent parsed metrics
4. bridge and PJC events may leave `row_count=null` when the stage audit does not expose a stable row-count concept

This avoids introducing fake precision or new stage semantics just for observability.

## 9. Privacy Rules

The observability export must not become a new leakage surface.

Allowed:

1. stage name
2. scope fields
3. duration
4. row counts
5. artifact hash
6. allow/deny outcome
7. reason code

Not allowed:

1. raw join keys
2. recovered plaintext rows
3. record-store passphrases
4. token secrets
5. unhashed sensitive filters
6. high-sensitivity artifact contents

## 10. Read Surfaces

The current observability export is available through:

1. direct CLI generation with `scripts/export_observability_events.py`
2. read-only completed-run access through `scripts/serve_audit_query_api.py`
3. thin client access through `scripts/platform_api_client.py`

This is the intended first-stage architecture:

1. completed run artifacts stay on disk
2. audit chain remains the source artifact
3. observability is derived on demand or materialized as a sidecar file

## 11. Benchmark Coverage

Current derived-view benchmark coverage lives in:

1. `scripts/benchmark_derived_views.py`
2. `schemas/derived_views_benchmark.schema.json`

The benchmark currently covers:

1. observability export
2. default catalog export
3. catalog export with `--include-paths`

For observability specifically, the semantic assertions keep these invariants stable:

1. the output still conforms to `pipeline_observability/v1`
2. the expected stage set remains covered
3. the export remains synthetic and read-only in benchmark mode

## 12. Recommended Dashboard Shape

The first useful operator views are:

1. per-job stage timeline
2. per-stage success/error counts
3. per-stage duration distribution
4. per-caller recent job outcomes
5. per-tenant recent release outcomes

Recommended grouping keys:

1. `stage`
2. `status`
3. `caller`
4. `tenant_id`
5. `dataset_id`
6. `service_id`

## 13. Future Integration

Later integrations may push this export into:

1. local SQLite/PostgreSQL read models
2. OpenTelemetry Collector
3. Grafana dashboards
4. alerting rules over repeated stage failures

But the near-term rule should remain:

1. derive from frozen audit artifacts first
2. avoid injecting new mandatory runtime dependencies into the pipeline

## 14. Non-Goals

This plan does not currently propose:

1. changing stage-owned audit schemas
2. making OpenTelemetry mandatory for local runs
3. adding metric emission directly inside every module before the read-side contract is stable
4. storing sensitive plaintext in observability payloads

## 15. Next Steps

1. Keep `pipeline_observability/v1` stable and backward compatible.
2. Continue validating stage coverage and timing propagation in contract smoke.
3. Add dashboard and alert examples around the existing export rather than around raw audit JSONL.
4. When a stronger telemetry stack is introduced, make it consume this derived contract first instead of redefining the fields.

## 16. Post-Baseline Extension Directions

The first-stage observability baseline is already complete:

1. `pipeline_observability/v1` is stable
2. dashboard export is present
3. alert report is present
4. operator triage report is present

So this document no longer treats observability as having an unfinished baseline block.

If work continues, the next steps should be:

1. live-job telemetry for the running state, without mixing it with historical dashboard blocks
2. OTel / Grafana adapters that consume `pipeline_observability/v1` instead of redefining fields
3. stronger service-level metrics, tracing, and structured log bridges for recovery service / key agent / external KMS / operator shell

Those are post-baseline operator-platform steps, not missing pieces of the current baseline.

Unified prioritization for that next tranche lives in [POST_BASELINE_ROADMAP.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/POST_BASELINE_ROADMAP.md).

### ~~Block O1: Dashboard Example Pack~~ ✓

Implemented `2026-05-03` as engineer B `B3`.

Entry: `scripts/build_observability_dashboard.py`

The dashboard consumes `pipeline_observability/v1` and the optional `platform_health/v1` and produces `observability_dashboard/v1` with five panels:

1. `stage_timeline` — chronological per-stage events with timing, status, role, decision
2. `stage_summary` — per-stage `ok / error / unknown` count table
3. `stage_duration` — per-stage duration stats: min / mean / p50 / p95 / max (only for stages with non-null `duration_ms`)
4. `release_outcomes` — per-`tenant_id` policy-release counts and last outcome
5. `failure_summary` — all `status=error` events sorted by `ts_utc` descending, attributed to `caller`

Plus an optional `health_summary` block drawn from `platform_health/v1` when provided.

The contract is frozen in `schemas/observability_dashboard.schema.json` and covered by `scripts/check_json_contracts.sh` (two smoke paths: with and without `platform_health`).

```bash
python3 scripts/build_observability_dashboard.py \
  --observability tmp/sse_bridge_pipeline_demo/pipeline_observability.json \
  --platform-health tmp/sse_bridge_pipeline_demo/platform_health.json \
  --out tmp/sse_bridge_pipeline_demo/observability_dashboard.json
```

Or using a completed run directory directly:

```bash
python3 scripts/build_observability_dashboard.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/observability_dashboard.json
```

(The `--out-base` form automatically reads both `pipeline_observability.json` and `platform_health.json` from the directory if they exist.)

### ~~Block O2: Alert And Triage Pack~~ ✓

Implemented `2026-05-03` as engineer B `B4`.

Entry: `scripts/check_observability_alerts.py`

Four alert conditions are evaluated, each producing an entry in `observability_alert_report/v1`:

| Alert ID | Fires When | Severity | Triage Read Path |
| -------- | ---------- | -------- | ---------------- |
| `repeated_stage_error` | Same stage appears with `status=error` in ≥2 events | error | `failure_summary` panel → audit read adapter → stage audit records |
| `release_failure_after_success` | `policy_release` is error but `bridge` and `pjc` were all ok | error | `release_outcomes` panel → `GET /v1/public-report` → release policy config |
| `platform_health_degraded` | `health_summary.status` is `warn` or `error` | warn/error | `GET /v1/platform-health` → `check_platform_health.py --verbose` |
| `stage_coverage_gap` | Any core stage (sse_export, record_recovery_service, bridge, pjc, policy_release) is absent | warn | Re-export observability → verify audit_chain.json was built after full pipeline |

Contract frozen in `schemas/observability_alert_report.schema.json`. Two smoke paths in `check_json_contracts.sh` (with and without platform health). Backcompat baseline entry added.

```bash
python3 scripts/check_observability_alerts.py \
  --dashboard tmp/sse_bridge_pipeline_demo/observability_dashboard.json \
  --platform-health tmp/sse_bridge_pipeline_demo/platform_health.json \
  --out tmp/sse_bridge_pipeline_demo/observability_alert_report.json

# or via out-base
python3 scripts/check_observability_alerts.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/observability_alert_report.json
```

## 17. Operator Triage Report

`scripts/run_operator_triage.py` chains dashboard + alert check + platform health + workflow status into a single `operator_triage_report/v1` document.

```bash
python3 scripts/run_operator_triage.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/operator_triage.json
```

Or with explicit paths:

```bash
python3 scripts/run_operator_triage.py \
  --observability tmp/sse_bridge_pipeline_demo/pipeline_observability.json \
  --platform-health tmp/sse_bridge_pipeline_demo/platform_health.json \
  --dashboard tmp/sse_bridge_pipeline_demo/observability_dashboard.json \
  --out tmp/sse_bridge_pipeline_demo/operator_triage.json
```

The triage report has four sections: `dashboard`, `alerts`, `platform_health`, `workflow_status`. Each section reports `available: true/false` (so it works even when some sidecar files are absent) and a compact summary.

Contract frozen in `schemas/operator_triage_report.schema.json` and covered by contract smoke.
