# Operator Handoff Quickstart

This file preserves the concrete operator commands that used to live inside the
long next-session reading guide. It is intentionally operational, not a current
security-status document. For security status, read
[CURRENT_SECURITY_AND_COMPLETION_AUDIT.md](CURRENT_SECURITY_AND_COMPLETION_AUDIT.md).

## Minimal Reproducible Operator Flow

Assumption: a pipeline run already exists under `tmp/sse_bridge_pipeline_demo/`
with at least:

```text
tmp/sse_bridge_pipeline_demo/
├── audit_chain.json
├── a_psi_run/public_report.json
└── mainline_contract_check.json   (optional)
```

### 1. Export Observability

```bash
python3 scripts/export_observability_events.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/pipeline_observability.json
```

### 2. Build Operator Dashboard JSON

```bash
python3 scripts/build_observability_dashboard.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/observability_dashboard.json
```

Dashboard sections:

- `stage_timeline`
- `stage_summary`
- `stage_duration`
- `release_outcomes`
- `failure_summary`

### 3. Run Alert Checks

```bash
python3 scripts/check_observability_alerts.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/observability_alert_report.json
```

Alert rules:

- `repeated_stage_error`
- `release_failure_after_success`
- `platform_health_degraded`
- `stage_coverage_gap`

### 4. Start Web Dashboard

```bash
python3 scripts/serve_operator_dashboard.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --port 18094
```

Open `http://127.0.0.1:18094/`.

### 5. Check Platform Health

```bash
python3 scripts/check_platform_health.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --metadata-db tmp/platform_metadata.db \
  --output tmp/sse_bridge_pipeline_demo/platform_health.json
```

### 6. Run Operator Triage

```bash
python3 scripts/run_operator_triage.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/operator_triage.json
```

Output contract: `operator_triage_report/v1`.

Sections:

- `dashboard`
- `alerts`
- `platform_health`
- `workflow_status`

### 7. Check Query Workflow Status

If a request has been submitted through `submit_query_workflow.py --execute`:

```bash
python3 scripts/check_workflow_retry_eligibility.py \
  --status-file tmp/sse_bridge_pipeline_demo/query_workflow/status.json

python3 scripts/list_query_workflow_status.py \
  --search-dir tmp \
  --state failed \
  --limit 10
```

Retry rules:

- `retry_eligibility.recommended_action == "resubmit"` requires a new `job_id`
  because duplicate-query guard will reject the same query.
- `retry_eligibility.recommended_action == "retry"` applies only to
  `launch_failed`; using a new `job_id` is still safer for audit clarity.

## Key Contract Index

| Contract | Schema | Generator |
| --- | --- | --- |
| `pipeline_observability/v1` | `schemas/pipeline_observability.schema.json` | `export_observability_events.py` |
| `catalog_lineage/v1` | `schemas/catalog_lineage.schema.json` | `export_catalog_lineage.py` |
| `observability_dashboard/v1` | `schemas/observability_dashboard.schema.json` | `build_observability_dashboard.py` |
| `observability_alert_report/v1` | `schemas/observability_alert_report.schema.json` | `check_observability_alerts.py` |
| `operator_triage_report/v1` | `schemas/operator_triage_report.schema.json` | `run_operator_triage.py` |
| `query_workflow_status/v1` | `schemas/query_workflow_status.schema.json` | `submit_query_workflow.py` |
| `query_workflow_status_list/v1` | `schemas/query_workflow_status_list.schema.json` | `list_query_workflow_status.py` |
| `workflow_retry_eligibility/v1` | `schemas/workflow_retry_eligibility.schema.json` | `check_workflow_retry_eligibility.py` |
| `platform_health/v1` | `schemas/platform_health.schema.json` | `check_platform_health.py` |
| Web UI | no schema | `serve_operator_dashboard.py -> http://127.0.0.1:18094/` |

## Rules To Preserve

1. These operator scripts read existing sidecar/run artifacts unless explicitly
   documented otherwise.
2. `operator_triage_report/v1` is the top-level operator status surface.
3. The `overall_status` field summarizes dashboard, alerts, and health status.
4. Keep schema IDs stable unless a change request is filed under
   `docs/change_requests/`.
