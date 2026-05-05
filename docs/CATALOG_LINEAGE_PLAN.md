# Catalog And Lineage Plan

## 1. Goal

This document defines the first-stage catalog and lineage view for the privacy platform.

The goal is to expose useful metadata about datasets, services, artifacts, and job flow without turning the catalog into a second copy of sensitive plaintext.

Current implementation anchors:

1. `scripts/export_catalog_lineage.py`
2. `schemas/catalog_lineage.schema.json`
3. `scripts/serve_audit_query_api.py`
4. `scripts/platform_api_client.py`
5. `scripts/benchmark_derived_views.py`

## 2. Boundary

The catalog/lineage layer is:

1. read-only
2. derived from `audit_chain.json`
3. adapter-first
4. compatible with the frozen pipeline

It is not:

1. a metadata write plane for the main pipeline
2. a replacement for policy enforcement
3. a place to store recovered plaintext or raw join keys

## 3. Current Output Contract

The current schema label is:

```text
catalog_lineage/v1
```

The exporter currently supports:

```bash
python3 scripts/export_catalog_lineage.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --out tmp/sse_bridge_pipeline_demo/catalog_lineage.json
```

Or:

```bash
python3 scripts/export_catalog_lineage.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/catalog_lineage.json
```

Optional path disclosure:

```bash
python3 scripts/export_catalog_lineage.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --include-paths \
  --out tmp/sse_bridge_pipeline_demo/catalog_lineage_with_paths.json
```

## 4. Current Top-Level Shape

The current contract includes:

1. `job_id`
2. `correlation_id`
3. `caller`
4. `tenant_id`
5. `dataset_id`
6. `service_id`
7. `privacy`
8. `job`
9. `datasets`
10. `services`
11. `artifacts`
12. `lineage_edges`
13. `summary`

This is enough to drive a first-stage catalog, run browser, or lineage explorer without redefining the main execution semantics.

## 5. Entity Model

### 5.1 Job

The catalog exposes one normalized job object with:

1. stable job identity
2. release status
3. release reason
4. policy version
5. scope fields

This is the anchor node for a completed-run lineage graph.

### 5.2 Dataset

The current dataset nodes represent:

1. `tenant_id`
2. `dataset_id`
3. source audit schema/version hint
4. originating audit source

They are not a full schema registry yet.

### 5.3 Service

The current service nodes are primarily intended for record recovery service visibility and currently expose:

1. `service_id`
2. `tenant_id`
3. `dataset_id`
4. `service_type`
5. `transport`

### 5.4 Artifact

Artifacts are the most important lineage nodes for this stage.
They expose:

1. `artifact_type`
2. `stage`
3. `role`
4. `sha256`
5. `row_count`
6. `format`
7. `source_event`
8. `path` or `path_included=false`

The default design treats artifact hash and stage metadata as the safe primary identifiers.

## 6. Relationship Model

Current `lineage_edges` use a lightweight relationship graph rather than a full metadata platform ontology.

Examples of relationships the exporter derives:

1. dataset `exported_to` SSE export artifact
2. recovered artifact `input_to` bridge job
3. service `authorized_recovery` recovered artifact
4. bridge inputs `prepared_for` bridge outputs
5. PJC result artifact `released_as` public report artifact

This is intentionally simple:

1. enough for tracing lineage
2. easy to keep backward compatible
3. not a premature enterprise metadata taxonomy

## 7. Privacy Model

The current export contains an explicit `privacy` block with:

1. `stores_sensitive_plaintext`
2. `paths_included`
3. `notes`

Default policy:

1. no raw join keys
2. no household address plaintext
3. no record-store secret material
4. no full artifact paths unless explicitly requested

This is one of the most important catalog rules in the repo today.

## 8. Path Redaction Rule

Default export behavior:

1. omit full artifact paths
2. emit `path_included=false`
3. still retain useful lineage through hash, stage, role, and row-count metadata

Explicit operator override:

1. `--include-paths`

This should only be used in controlled environments, for example:

1. local debugging
2. audited operator troubleshooting
3. controlled asset inventory work

It should not become the default catalog behavior.

## 9. Data Sources

The exporter derives its view from:

1. `sse_export_audit`
2. `record_recovery_service_audit`
3. `bridge_audit`
4. `pjc_audit`
5. `policy_audit`
6. `public_report`
7. optional `key_access_audit`

That design is deliberate:

1. catalog data follows audited artifacts
2. no direct reach into raw SSE state
3. no direct read of encrypted record-store internals beyond audited metadata

## 10. Integration With Metadata Sidecar

The current catalog exporter is file-derived, while the metadata sidecar is database-derived.
These layers are complementary:

1. metadata DB is good for querying imported jobs, scope entities, and policy bindings
2. catalog lineage export is good for artifact graph views over a completed run

Recommended near-term pattern:

1. continue deriving lineage from `audit_chain.json`
2. optionally join with metadata DB for registry enrichment in a read adapter
3. do not make the pipeline write directly into a lineage database yet

## 11. Read Surfaces

Current ways to access catalog/lineage data:

1. direct CLI export with `scripts/export_catalog_lineage.py`
2. completed-run HTTP access with `scripts/serve_audit_query_api.py`
3. thin local client access with `scripts/platform_api_client.py`

This keeps the first-stage product shell aligned with the sidecar-first design.

## 12. Benchmark Coverage

Current benchmark coverage lives in:

1. `scripts/benchmark_derived_views.py`
2. `schemas/derived_views_benchmark.schema.json`

Current semantic checks preserve:

1. default redacted export behavior
2. explicit `--include-paths` behavior
3. compatibility of the derived contract

This matters because lineage tools often drift into over-exposing paths or payload hints unless the contract is pinned.

## 13. Recommended UI Shape

The first useful UI or SDK views are:

1. completed job summary
2. dataset-to-artifact lineage graph
3. service-to-artifact recovery graph
4. released-report provenance view
5. per-stage artifact list filtered by role

Useful filters:

1. `job_id`
2. `caller`
3. `tenant_id`
4. `dataset_id`
5. `service_id`
6. `stage`
7. `artifact_type`

## 14. Future Extension

Likely next additions, still as sidecar work:

1. schema-version enrichment from metadata DB
2. policy-binding references on job and dataset nodes
3. archive-index lineage for retained audit bundles
4. public-report-to-audit-chain provenance shortcuts
5. service inventory views over imported metadata tables

Possible later integration targets:

1. OpenMetadata
2. Postgres-backed catalog API
3. UI graph explorer

But the rule should remain:

1. adapter-first
2. path-redacted by default
3. no sensitive plaintext in the catalog

## 15. Non-Goals

This plan does not currently propose:

1. a general-purpose enterprise metadata model
2. storing raw records in the catalog
3. exposing encrypted record-store contents
4. bypassing record recovery policy for lineage generation
5. redefining stage contracts to satisfy a catalog tool

## 16. Next Steps

1. Keep `catalog_lineage/v1` stable and path-redacted by default.
2. Continue validating default redaction and `--include-paths` behavior in contract smoke.
3. Add read adapters or UI views that consume this derived contract rather than scraping raw run directories.
4. If richer catalog entities are needed, enrich from metadata sidecar data first instead of expanding the main pipeline outputs.

## 17. Post-Baseline Extension Directions

The first-stage catalog/lineage baseline is already complete:

1. `catalog_lineage/v1` is stable
2. default path-redacted export is fixed
3. `--include-paths` remains explicit and non-default
4. benchmark and contract smoke cover both modes

So this document no longer treats catalog/lineage as having an unfinished baseline block.

If work continues, the next useful steps are:

1. registry-enriched read views that join `catalog_lineage/v1` with metadata-sidecar registry entities
2. operator shell views that consume the existing contract instead of scraping run directories
3. release provenance and troubleshooting views with separately gated path-inclusive access

The rule remains unchanged:

1. enrich from metadata DB first
2. keep path redaction as the default
3. do not turn the catalog into a second plaintext storage surface

Unified prioritization for that next tranche lives in [POST_BASELINE_ROADMAP.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/POST_BASELINE_ROADMAP.md).
