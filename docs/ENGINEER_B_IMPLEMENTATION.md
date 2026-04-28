# Engineer B Implementation — Query, Catalog, Workflow, Observability

## Overview

This document covers all artifacts produced for Task 2 (Engineer B): query entry, data catalog, durable workflow, observability & alerting, admin UI / SDK prototype, and benchmark / security scanning.

All implementations call existing CLI and JSON/JSONL contracts — no privacy-compute logic was rewritten.

---

## 1. Observability

### Telemetry Pipeline

Generate OTLP-compatible metrics from any completed pipeline run:

```bash
# OTLP JSONL format (default)
python3 scripts/telemetry_pipeline.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --tenant-id my_tenant

# Prometheus text format
python3 scripts/telemetry_pipeline.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --format prometheus
```

Outputs: `telemetry_metrics.jsonl`, `telemetry_manifest.json`

### Runbook

Generate a human-readable stage-by-stage runbook:

```bash
python3 scripts/generate_observability_runbook.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --job-id auto_demo_job
```

Output: `runbook.md` — stage summaries, deny decisions, audit integrity, action items.

### Telemetry Fields

Defined in `config/telemetry_fields.yaml`:

| Field | Source |
|-------|--------|
| `job_id`, `correlation_id`, `caller` | All audit records |
| `stage` | Derived from audit event type |
| `status` | Audit decision (allow/deny) |
| `row_count` | Audit output_rows |
| `artifact_sha256` | Audit output_sha256 |
| `intersection_size`, `intersection_sum` | PJC result |
| `released` | Public report |

**Never recorded**: raw join keys, token secrets, recovery passphrases, raw record contents.

### Alerts

| Alert | Severity | Condition |
|-------|----------|-----------|
| `HighStageDenyRate` | warning | Deny rate > 10% over 5m |
| `StageDurationHigh` | warning | Any stage > 60s |
| `ArtifactHashMismatch` | critical | Hash mismatch in audit chain |
| `NoRecentJobs` | warning | No jobs in 10m |

---

## 2. Temporal Workflow Wrapper

Each activity wraps an existing CLI call:

| Activity | CLI Called |
|----------|-----------|
| `validate_policy_activity` | `scripts/validate_pipeline_policy.py` |
| `run_sse_export_activity` | `sse/.venv/bin/python run_client.py export-bridge-records` |
| `run_record_recovery_health_check_activity` | `scripts/validate_json_contract.py` (recovery audit) |
| `run_bridge_prepare_job_activity` | `cargo run -- prepare-job` |
| `run_pjc_activity` | `bash a-psi/moduleA_psi/scripts/run_pjc.sh` |
| `run_policy_release_activity` | `python3 a-psi/moduleA_psi/scripts/policy_release.py` |
| `build_audit_chain_activity` | `scripts/build_audit_chain.py` + `scripts/seal_audit_artifact.py` |
| `run_telemetry_activity` | `scripts/telemetry_pipeline.py` |
| `run_runbook_activity` | `scripts/generate_observability_runbook.py` |

### Starting a Worker

```bash
# Requires: pip install temporalio
python3 scripts/temporal/worker.py \
  --temporal-host localhost:7233 \
  --temporal-namespace seccomp-dev \
  --task-queue seccomp-pipeline
```

### Submitting a Workflow

```bash
export BRIDGE_TOKEN_SECRET=<secret>
python3 scripts/temporal/run_workflow.py \
  --server-source sse/examples/bridge_server_records.jsonl \
  --client-source sse/examples/bridge_client_records.jsonl \
  --server-join-key-field email \
  --client-join-key-field email \
  --client-value-field amount \
  --token-scope temporal-demo \
  --token-secret-env BRIDGE_TOKEN_SECRET \
  --job-id temporal_demo_job \
  --out-base tmp/temporal_demo \
  --sse-export-policy-config sse/config/export_policy.example.json \
  --k 20 --n 5 \
  --wait
```

### Policy-Validation-Only Workflow

```bash
python3 scripts/temporal/run_workflow.py \
  --workflow validate-policy-only \
  --sse-export-policy-config sse/config/export_policy.example.json \
  --caller auto_demo \
  --job-id policy_check \
  --out-base tmp/policy_check \
  --wait
```

---

## 3. Catalog & Lineage

### Building a Catalog

```bash
python3 scripts/catalog_adapter.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --tenant-id my_tenant
```

Outputs:
- `catalog.jsonl` — entries for datasets, schema versions, policy bindings, jobs, artifacts, reports
- `catalog_lineage.dot` — Graphviz DOT format lineage graph

### Querying the Catalog

```bash
# List all datasets
jq 'select(.entry_type == "dataset")' tmp/sse_bridge_pipeline_demo/catalog.jsonl

# List all jobs
jq 'select(.entry_type == "job") | .job' tmp/sse_bridge_pipeline_demo/catalog.jsonl

# Find artifacts for a specific job
jq 'select(.artifact.job_id == "auto_demo_job")' tmp/sse_bridge_pipeline_demo/catalog.jsonl

# Visualize lineage
dot -Tpng tmp/sse_bridge_pipeline_demo/catalog_lineage.dot -o lineage.png
```

### What the Catalog Does NOT Store

- User home addresses, full phone numbers, raw join keys
- Recovery secrets or bridge token secrets
- Raw record contents

Only hashed values and metadata.

---

## 4. Query Interface

### Query Types

| Type | Path | Privacy Boundary |
|------|------|-----------------|
| `internal_fine_grained` | SSE export + record recovery | Policy-validated field export |
| `merchant_aggregate` | SSE export → k-anonymity aggregate | No raw PII in output |
| `ad_collaboration` | Bridge + PJC + Release | Thresholded intersection only |

### Generate Templates

```bash
# All three types
python3 scripts/query_adapter.py template --out-base tmp/query_templates

# Single type
python3 scripts/query_adapter.py template \
  --template-type ad_collaboration \
  --out-base tmp/query_templates
```

### Validate a Query

```bash
python3 scripts/query_adapter.py validate \
  --query-file tmp/query_templates/query_ad_collaboration.json \
  --policy-config sse/config/export_policy.example.json
```

### Submit a Query

```bash
export BRIDGE_TOKEN_SECRET=<secret>
python3 scripts/query_adapter.py submit \
  --query-file tmp/query_templates/query_ad_collaboration.json \
  --policy-config sse/config/export_policy.example.json \
  --out-base tmp/query_run
```

### Query Routing Rules

```
Query → Policy Validate → Route by query_type:
  internal_fine_grained → SSE export + record recovery
  merchant_aggregate     → SSE export + k-anonymity aggregation
  ad_collaboration       → SSE export + Bridge + PJC + Release
                        → Audit Chain + Seal
```

---

## 5. Benchmark & Security

### Pipeline Benchmark

```bash
python3 scripts/benchmark_pipeline.py run \
  --iterations 5 \
  --out-base tmp/benchmark \
  --policy-config sse/config/export_policy.example.json
```

Measures e2e latency with min/max/mean/median/P95/stdev.

### Generate Report

```bash
python3 scripts/benchmark_pipeline.py report --benchmark-dir tmp/benchmark
```

### Security Scan

```bash
# Full scan (secrets, dependencies, schema compatibility)
python3 scripts/security_scan.py scan --repo-root .

# Generate malformed input fuzz fixtures
python3 scripts/security_scan.py fuzz-fixtures --out-dir tmp/fuzz_fixtures

# Check schema backward compatibility
python3 scripts/security_scan.py schema-check --schema-dir schemas/
```

14 fuzz fixtures generated covering:
- CSV: empty join key, missing header, non-integer value, empty file
- JSONL: non-JSON, missing fields, null keys, non-int values, binary content
- PJC CSV: short hash, missing value column

---

## 6. Admin CLI & SDK

### Admin CLI

```bash
# Job status
python3 scripts/admin_cli.py job status --out-base tmp/sse_bridge_pipeline_demo

# Audit chain summary
python3 scripts/admin_cli.py audit show --out-base tmp/sse_bridge_pipeline_demo

# Audit integrity verification
python3 scripts/admin_cli.py audit verify --out-base tmp/sse_bridge_pipeline_demo

# Public report
python3 scripts/admin_cli.py report public --out-base tmp/sse_bridge_pipeline_demo

# Catalog listing (all types)
python3 scripts/admin_cli.py catalog list --out-base tmp/sse_bridge_pipeline_demo

# Catalog filtered by type
python3 scripts/admin_cli.py catalog list --out-base tmp/sse_bridge_pipeline_demo --entry-type artifact

# Generate runbook
python3 scripts/admin_cli.py runbook generate --out-base tmp/sse_bridge_pipeline_demo

# Telemetry summary
python3 scripts/admin_cli.py telemetry summary --out-base tmp/sse_bridge_pipeline_demo

# Submit a pipeline job (ad_collaboration path)
export BRIDGE_TOKEN_SECRET=<secret>
python3 scripts/admin_cli.py pipeline submit \
  --out-base tmp/admin_job \
  --caller admin_demo \
  --server-filters campaign=demo \
  --client-filters campaign=demo \
  --k 20 --n 5 \
  --policy-config sse/config/export_policy.example.json
```

### Python SDK

```python
from scripts.sdk_client import SeccompClient

with SeccompClient(out_base="tmp/sse_bridge_pipeline_demo") as client:
    # Job status
    job = client.job_status()
    print(f"{job.job_id}: released={job.released}, "
          f"intersection_size={job.intersection_size}")

    # Public report
    report = client.public_report()

    # PJC result
    pjc = client.pjc_result()

    # Audit integrity
    ok = client.verify_audit_integrity()

    # Catalog
    for ds in client.get_datasets():
        print(ds.display_name)

    # Lineage graph (DOT format)
    dot = client.get_lineage_dot()

    # Telemetry
    manifest = client.generate_telemetry()

    # Runbook
    runbook = client.generate_runbook()

    # Submit a new ad collaboration query
    result = client.submit_collaboration(
        server_filters=[{"field": "campaign", "value": "demo"}],
        client_filters=[{"field": "campaign", "value": "demo"}],
        k_threshold=20,
    )

    # Submit a merchant aggregate query
    result = client.submit_aggregate(
        group_by_field="store_id",
        metrics=[{"type": "count", "field": "*"}, {"type": "sum", "field": "amount"}],
        k_threshold=50,
    )

    # Submit an internal export query
    result = client.submit_internal_export(
        role="client",
        fields=["email", "amount"],
        filters=[{"field": "campaign", "value": "demo"}],
    )
```

---

## 7. File Map

```
config/
├── telemetry_fields.yaml              ← Unified telemetry field definitions + alerts + dashboard layout

docs/
├── OBSERVABILITY_PLAN.md              ← Observability plan
├── CATALOG_LINEAGE_PLAN.md            ← Catalog & lineage plan
├── QUERY_INTERFACE_PLAN.md            ← Query interface plan
├── BENCHMARK_PLAN.md                  ← Benchmark & security scan plan

schemas/
├── catalog_entry.schema.json          ← Catalog entry schema (dataset, job, artifact, report, etc.)
├── query_template.schema.json         ← Declarative query template schema

scripts/
├── telemetry_pipeline.py              ← OTLP/Prometheus metrics from audit JSONL
├── generate_observability_runbook.py  ← Markdown runbook generator
├── catalog_adapter.py                 ← Catalog JSONL + lineage DOT from pipeline outputs
├── query_adapter.py                   ← Query validate/submit/template across 3 query types
├── benchmark_pipeline.py              ← Pipeline latency benchmark suite
├── security_scan.py                   ← Secret scan, dependency scan, schema check, fuzz fixtures
├── admin_cli.py                       ← Admin CLI (job, audit, report, catalog, runbook, telemetry, pipeline)
├── sdk_client.py                      ← Python SDK (SeccompClient class)
└── temporal/
    ├── activities.py                  ← Temporal activities wrapping existing CLI
    ├── workflow.py                    ← Workflow definitions
    ├── worker.py                      ← Temporal worker entrypoint
    └── run_workflow.py                ← Client to submit workflows
```

---

## 8. Privacy Boundaries Preserved

All implementations respect the following constraints:

- Never directly read encrypted record store without recovery service
- Never bypass SSE export policy
- Never expose bridge token secrets in logs, metrics, or catalog
- Never return high-sensitivity fields (home address, full phone, raw join keys) in query results
- Never modify PJC input format or bridge token generation
- Temporal activities only wrap existing CLI — no logic rewrite

---

## 9. Quick Verification

```bash
# 1. Existing contracts still pass
bash scripts/check_json_contracts.sh

# 2. All schemas are valid
python3 scripts/security_scan.py schema-check --schema-dir schemas/

# 3. Query templates generate and validate
python3 scripts/query_adapter.py template --template-type ad_collaboration --out-base tmp/verify_query
python3 scripts/query_adapter.py validate \
  --query-file tmp/verify_query/query_ad_collaboration.json \
  --policy-config sse/config/export_policy.example.json \
  --out-base tmp/verify_query

# 4. Fuzz fixtures are created
python3 scripts/security_scan.py fuzz-fixtures --out-dir tmp/verify_fuzz

# 5. Python compilation check
for f in scripts/telemetry_pipeline.py scripts/generate_observability_runbook.py \
         scripts/catalog_adapter.py scripts/query_adapter.py \
         scripts/benchmark_pipeline.py scripts/security_scan.py \
         scripts/admin_cli.py scripts/sdk_client.py \
         scripts/temporal/activities.py scripts/temporal/workflow.py \
         scripts/temporal/worker.py scripts/temporal/run_workflow.py; do
    python3 -m py_compile "$f" && echo "OK $f"
done
```
