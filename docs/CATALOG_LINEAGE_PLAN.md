# Catalog & Lineage Plan — Seccomp Privacy Platform

## 1. Scope

Provide a searchable catalog of datasets, schema versions, policy bindings, jobs, artifacts, and public reports — all derived from existing pipeline outputs. The catalog is privacy-safe: it never stores sensitive plaintext values.

## 2. Catalog Entities

Defined in `schemas/catalog_entry.schema.json`:

| Entry Type | Source | Description |
|-----------|--------|-------------|
| `dataset` | SSE export audit | Dataset metadata: owner, field list, source hash, record count |
| `schema_version` | SSE export audit | Schema version with field snapshots and backward-compat flag |
| `policy_binding` | SSE export audit | Which policy config is bound to which dataset |
| `job` | Bridge metadata, audit chain, public report | Job lifecycle: status, stages, timing |
| `artifact` | Audit chain paths | Output artifacts: type, hash, size |
| `public_report` | Public report JSON | Released results: intersection size/sum, k-threshold |

## 3. What the Catalog Stores

- Dataset display names and field type classifications (join_key, value, filter, metadata)
- SHA-256 hashes of source files, policies, and artifacts
- Row counts, record counts, and timing information
- Policy binding metadata (allowed roles, allowed fields, required filters)
- Job statuses and stage-level decisions
- Public report summaries (intersection_size, intersection_sum, released boolean)

## 4. What the Catalog Does NOT Store

Per the task requirements:

- User home addresses (plaintext)
- Full phone numbers (plaintext)
- Raw join keys (plaintext email, phone, device ID)
- Recovery secrets
- Bridge token secrets
- Raw record contents

The catalog only stores hashes and metadata — never the underlying sensitive data.

## 5. Usage

### Build catalog from a pipeline run

```bash
python3 scripts/catalog_adapter.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --tenant-id my_tenant
```

Outputs:
- `<out-base>/catalog.jsonl` — newline-delimited JSON catalog entries
- `<out-base>/catalog_lineage.dot` — Graphviz DOT format lineage graph

### Visualize lineage

```bash
dot -Tpng tmp/sse_bridge_pipeline_demo/catalog_lineage.dot -o catalog_lineage.png
```

### Query catalog with jq

```bash
# List all datasets
jq 'select(.entry_type == "dataset")' tmp/sse_bridge_pipeline_demo/catalog.jsonl

# List all jobs
jq 'select(.entry_type == "job") | .job' tmp/sse_bridge_pipeline_demo/catalog.jsonl

# Find all artifacts for a specific job
jq 'select(.artifact.job_id == "auto_demo_job")' tmp/sse_bridge_pipeline_demo/catalog.jsonl
```

## 6. Lineage Model

```
Dataset → SchemaVersion → PolicyBinding
                                ↓
                            Job (SSE → Bridge → PJC → Release)
                                ↓
                    Artifact (sse_export, bridge_output, pjc_result, public_report, audit_chain)
                                ↓
                           PublicReport
```

Lineage is captured through:
1. Dataset entries are linked to jobs via `job.input_datasets`
2. Artifact entries are linked to jobs via `artifact.job_id`
3. Public report entries are linked to jobs via `public_report_entry.job_id`
4. The DOT graph visualizes these links

## 7. Phase 2: Integration with OpenMetadata

When moving beyond the prototype phase:

1. Map catalog_entry schema to OpenMetadata's entity model
2. Use OpenMetadata's ingestion framework to push entries via its API
3. Leverage OpenMetadata's built-in lineage UI and search
4. Configure OpenMetadata's RBAC to match platform roles

## 8. Phase 2: Control-Plane DB Integration

If Engineer A's control-plane DB (`tmp/platform_metadata.db`) is available:

```bash
# Query metadata sidecar
python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --job-id auto_demo_job
```

The catalog adapter can also ingest from the control-plane DB to enrich entries with:
- Tenant and user metadata
- Service registry entries
- Key version history

## 9. Verification

```bash
# After a pipeline run, build catalog and verify entry counts
python3 scripts/catalog_adapter.py --out-base tmp/sse_bridge_pipeline_demo
python3 -c "
import json
with open('tmp/sse_bridge_pipeline_demo/catalog.jsonl') as f:
    entries = [json.loads(l) for l in f if l.strip()]
types = {}
for e in entries:
    t = e['entry_type']
    types[t] = types.get(t, 0) + 1
assert types.get('dataset', 0) >= 1, 'no dataset entries'
assert types.get('job', 0) >= 1, 'no job entries'
print(f'OK: {len(entries)} catalog entries across {len(types)} types')
"
```

## 10. Privacy Validation

Before deploying the catalog:

1. Verify no raw join keys appear in any catalog entry
2. Verify no token secrets appear in any catalog entry
3. Run `scripts/catalog_adapter.py` and grep for known sensitive values
4. Review schema to ensure only hashed/metadata fields are captured
