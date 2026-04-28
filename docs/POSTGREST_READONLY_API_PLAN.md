# PostgREST Read-Only API Plan

## Scope

This document describes a future stage-2 PostgREST layer over the stage-1 control-plane metadata schema.

Stage-1 result:

1. The metadata schema exists.
2. The importer exists.
3. The query CLI exists.
4. PostgREST remains a design artifact only.

## Hard Boundaries

These constraints are mandatory:

1. Stage 1 must remain CLI and sidecar DB based.
2. PostgREST must not become a mandatory runtime dependency in stage 1.
3. The API plan must remain read-only.
4. The API plan must not introduce write-capable control-plane behavior in stage 1.
5. The API plan must not change frozen field meanings.

## Why PostgREST

PostgREST is a good fit for the later control-plane read surface because:

1. the schema is relational and PostgreSQL-ready
2. stage-1 queries are already centered on indexed metadata tables
3. a read-only REST layer is enough for audit and inspection use cases

This matches the current control-plane goal better than building a custom write-capable service too early.

## Planned Read Surface

Primary resources:

1. `jobs`
2. `job_stage_status`
3. `job_artifacts`
4. `audit_events`
5. `key_access_events`
6. `audit_chains`
7. `audit_seals`
8. `tenants`
9. `datasets`
10. `services`
11. `callers`
12. `policies`

Primary filters:

1. `job_id`
2. `caller`
3. `tenant_id`
4. `dataset_id`

## Recommended API Shape

### Job Lookup

Examples:

1. `/jobs?job_id=eq.auto_demo_job`
2. `/jobs?caller=eq.auto_demo`
3. `/jobs?tenant_id=eq.tenant-demo`
4. `/jobs?dataset_id=eq.dataset-demo`

### Related Read Views

Recommended SQL views for easier read-only inspection:

1. `job_summary_view`
2. `job_audit_overview_view`
3. `job_artifact_overview_view`
4. `job_key_access_view`

These views should:

1. preserve frozen field names
2. aggregate lookup-friendly data
3. avoid changing underlying semantics

## AuthN And AuthZ Position

Future PostgREST deployment should sit behind:

1. Keycloak for identity
2. OpenFGA or equivalent authorization checks
3. optional OPA only for future control-plane access-policy composition

Important boundary:

1. These checks protect metadata visibility.
2. They do not replace privacy-release semantics.

## Deployment Model

Recommended later-stage stack:

1. PostgreSQL as the authoritative metadata store
2. PostgREST configured against read-only DB roles
3. reverse proxy or API gateway in front
4. Keycloak-backed auth at the edge
5. optional OpenFGA-backed authorization decision point for route/resource access

## Read-Only DB Role

When PostgREST is added later, it should use a database role with:

1. `SELECT` on approved tables and views only
2. no `INSERT`
3. no `UPDATE`
4. no `DELETE`
5. no DDL privileges

This is critical because the stage-2 API should still preserve the stage-1 rule: inspection only, not mutation.

## Suggested Stage-2 Views

### `job_summary_view`

Should expose:

1. `job_id`
2. `correlation_id`
3. `caller`
4. `tenant_id`
5. `dataset_id`
6. `service_id`
7. `policy_id`
8. `token_scope`
9. `token_key_version`
10. `record_recovery_boundary`
11. `job_type`
12. `job_state`

### `job_audit_overview_view`

Should expose:

1. `job_id`
2. stage name
3. event source
4. decision
5. reason code
6. event timestamp

### `job_artifact_overview_view`

Should expose:

1. `job_id`
2. stage name
3. artifact type
4. file path
5. sha256
6. record count

## Optional Future OPA Use

OPA may be considered later for:

1. row-level or route-level access composition
2. admin-only or auditor-only metadata endpoints
3. tenant-aware filtering policy

OPA must not be used to:

1. reinterpret privacy-release meaning
2. rewrite stage-1 frozen field semantics
3. become a required component in stage 1

## Non-Goals

This API plan does not include:

1. write endpoints
2. mutation workflows
3. approval workflows
4. policy editing APIs
5. key rotation APIs

Those require separate approval and are outside the stage-1 TODO boundary.
