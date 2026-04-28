# Control Plane Schema

## Scope

This document defines the stage-1 metadata schema for the control plane sidecar database.

The purpose of this schema is:

1. Persist metadata produced by the existing pipeline.
2. Support read-only lookup by `job_id`, `caller`, `tenant_id`, and `dataset_id`.
3. Prepare a PostgreSQL-ready relational model while keeping the current stage-1 runtime on SQLite.

This schema is a governance layer around the existing pipeline. It is not a replacement for the current `SSE -> record recovery -> bridge -> PJC -> policy release` execution path.

## Hard Boundaries

The following constraints are mandatory:

1. The main pipeline must not require the database in stage 1.
2. The schema must not redefine the meaning of frozen fields.
3. The schema must not force any changes to `bridge/src/main.rs` token contract.
4. The schema must not force any changes to `a-psi/moduleA_psi/scripts/policy_release.py`.
5. Missing metadata in current artifacts must remain nullable or require explicit importer overrides.
6. The schema must not introduce write-capable control-plane behavior in stage 1.

## Frozen Fields

These fields are preserved exactly and must not be renamed or redefined:

1. `job_id`
2. `correlation_id`
3. `caller`
4. `tenant_id`
5. `dataset_id`
6. `service_id`
7. `token_scope`
8. `token_key_version`
9. `record_recovery_boundary`
10. `policy_id`

## Design Principles

1. Keep business-resource registry tables separate from event/audit tables.
2. Store normalized relational columns for stable lookup fields.
3. Keep raw JSON payloads for stage-1 fidelity and future backfill.
4. Prefer nullable fields over fabricated semantics.
5. Keep table names and field meanings compatible with future PostgreSQL deployment.

## Table Groups

### Registry

- `tenants`
- `datasets`
- `services`
- `callers`
- `service_bindings`

Purpose:

1. Represent tenant, dataset, service, and caller identities.
2. Provide stable foreign-key anchors for job and audit records.
3. Support later IAM/AuthZ integration.

Stage-1 behavior:

1. These rows may be sparse.
2. Some rows are created from explicit importer overrides rather than pipeline artifacts.
3. Registry completeness is not required for the main pipeline to run.

### Jobs

- `jobs`
- `job_stage_status`
- `job_artifacts`
- `job_state_transitions`

Purpose:

1. Represent one pipeline run as a first-class record.
2. Track stage-level observation status.
3. Track artifact file paths and hashes.
4. Capture import-time state transitions without changing pipeline behavior.

Important columns in `jobs`:

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
12. `source_out_base`

### Policies

- `policies`
- `policy_bindings`
- `caller_permissions`
- `service_permissions`

Purpose:

1. Prepare a durable place for policy identity and future binding data.
2. Keep stage-1 policy references explicit.
3. Support future IAM/AuthZ integration without changing current policy-release semantics.

Stage-1 behavior:

1. `policy_id` may come from explicit importer override.
2. `policy_version` may be inferred from `public_report.json` or policy audit.
3. These tables do not change release decisions in stage 1.

### Audit

- `audit_events`
- `audit_chains`
- `audit_seals`
- `key_access_events`
- `key_lifecycle_events`

Purpose:

1. Persist stage-level JSON/JSONL audit output in relational form.
2. Support read-only investigation and traceability.
3. Preserve artifact-level integrity references.

Stage-1 behavior:

1. `audit_events` stores normalized lookup columns plus raw event JSON.
2. `audit_chains` stores the correlated `audit_chain.json` artifact.
3. `audit_seals` stores the `audit_chain.seal.json` artifact.
4. `key_access_events` stores current key access audit output without changing key usage flow.

### Keys

- `key_refs`
- `key_versions`
- `key_purposes`
- `key_rotation_events`

Purpose:

1. Prepare a durable model for future KMS-backed key registry.
2. Track which key IDs and versions appear in audit output.
3. Separate key identity from future secret backend implementation.

Stage-1 behavior:

1. Existing pipeline still relies on env-based or local-manifest secret resolution.
2. These tables are governance metadata only.
3. They do not change runtime key injection in stage 1.

## Artifact Mapping

The importer reads only the approved stage-1 artifact set:

1. `sse_exports/export_audit.jsonl`
2. `sse_exports/record_recovery_service_audit.jsonl`
3. `sse_exports/record_recovery_service_health.json`
4. `sse_exports/record_recovery_service_config.json`
5. `bridge_job/job_meta.json`
6. `bridge_job/bridge_audit.jsonl`
7. `a_psi_run/pjc_audit.jsonl`
8. `a_psi_run/public_report.json`
9. `a_psi_run/audit_log.jsonl`
10. `key_access_audit.jsonl`
11. `audit_chain.json`
12. `audit_chain.seal.json`

Stage-1 mapping summary:

1. `bridge_job/job_meta.json` feeds `jobs` and `job_artifacts`.
2. `export_audit.jsonl`, `record_recovery_service_audit.jsonl`, `bridge_audit.jsonl`, `pjc_audit.jsonl`, `audit_log.jsonl`, and `key_access_audit.jsonl` feed `audit_events`.
3. `key_access_audit.jsonl` also feeds `key_access_events`.
4. `audit_chain.json` feeds `audit_chains`.
5. `audit_chain.seal.json` feeds `audit_seals`.

## Nullability Rules

Current artifacts do not reliably contain all frozen resource fields. Therefore:

1. `tenant_id` may be null.
2. `dataset_id` may be null.
3. `service_id` may be null.
4. `policy_id` may be null.

Allowed stage-1 behavior:

1. Use explicit importer overrides when the operator knows the right value.
2. Leave the field null when the artifact set does not provide a trustworthy value.

Forbidden stage-1 behavior:

1. Invent default business values such as `default`, `demo`, or `workspace-1` as if they were authoritative.
2. Rename these fields to another model such as `account_id` or `workspace_id`.

## Query Model

Stage-1 read-only queries are centered on the `jobs` table and expanded with related rows from:

1. `job_stage_status`
2. `job_artifacts`
3. `job_state_transitions`
4. `audit_events`
5. `key_access_events`
6. `audit_chains`
7. `audit_seals`

Supported lookups:

1. `job_id`
2. `caller`
3. `tenant_id`
4. `dataset_id`

## PostgreSQL Readiness

The stage-1 SQL schema is written to stay close to PostgreSQL deployment needs:

1. Narrow primitive column types are avoided for fields that may evolve.
2. Time values are stored as ISO-8601 text in SQLite and can map to `timestamptz` later.
3. Raw JSON payload columns are stored as text in SQLite and can map to `jsonb` in PostgreSQL.
4. Table and index layout already assumes relational access patterns suitable for PostgREST later.

## Stage-1 Non-Goals

This schema intentionally does not do the following:

1. It does not replace filesystem artifacts as the primary runtime handoff.
2. It does not become the source of truth for privacy-release decisions.
3. It does not force online writes from pipeline stages into the database.
4. It does not provide write APIs.
5. It does not make Keycloak, OpenFGA, Vault, PostgREST, or OPA mandatory runtime dependencies.

## Current Implementation

The current stage-1 implementation lives in:

1. [schemas/platform_metadata.sql](../schemas/platform_metadata.sql)
2. [scripts/init_metadata_db.py](../scripts/init_metadata_db.py)
3. [scripts/import_run_metadata.py](../scripts/import_run_metadata.py)
4. [scripts/query_metadata.py](../scripts/query_metadata.py)
