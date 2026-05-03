# Code Review — Step 6: SQL Metadata Sidecar

**Scope:** `migrations/metadata/`, `scripts/metadata_db.py`, `scripts/init_metadata_db.py`, `scripts/import_run_metadata.py`, `scripts/query_metadata.py`, `scripts/serve_metadata_api.py`, `scripts/manage_metadata_db.py`, `scripts/export_authz_tuples.py`, `scripts/metadata_registry.py`

---

## 1. Module Purpose

The SQL metadata sidecar is a read-oriented control-plane overlay for the main pipeline. It does **not** change the main pipeline's write path — the pipeline still emits JSON/JSONL artifacts first. The sidecar imports those artifacts after the fact and exposes them for query, audit review, and authz analysis.

Design principles:
- The pipeline is not database-dependent.
- Import is idempotent and auditable.
- The sidecar is a SQLite file; migration to PostgreSQL is planned but not yet required.
- Only the `apply-registry` write path touches the registry tables; everything else is read-only relative to the main pipeline.

---

## 2. Database Schema (`migrations/metadata/001_init.sql`)

### 2.1 Registry Tables

| Table | Key | Purpose |
|---|---|---|
| `tenants` | `tenant_id` | Top-level multi-tenant isolation unit |
| `datasets` | `dataset_id` | Dataset scoped to a tenant |
| `services` | `service_id` | Recovery service instances |
| `callers` | `caller` | Caller identities |

### 2.2 Job Tables

| Table | Key | Purpose |
|---|---|---|
| `jobs` | `job_id` | One row per completed pipeline run |
| `job_artifacts` | `(job_id, artifact_type, path)` | Per-stage artifact paths and SHA-256 hashes |
| `job_stage_status` | `(job_id, stage)` | Per-stage decision (allow/deny/error) and duration |

### 2.3 Audit Tables

| Table | Key | Purpose |
|---|---|---|
| `audit_events` | auto-id | Imported stage audit records |
| `audit_chains` | `job_id` | Imported `audit_chain.json` payloads |
| `audit_seals` | `job_id` | Imported `audit_chain.seal.json` payloads |

### 2.4 Policy Tables

| Table | Key | Purpose |
|---|---|---|
| `policies` | `policy_id` | Imported policy files |
| `policy_bindings` | `(policy_id, binding_kind, caller)` | Per-caller scope bindings |
| `caller_permissions` | `(policy_id, caller, permission_key)` | Flat permission key-value store |
| `key_access_events` | auto-id | Imported key access audit records |

### 2.5 Schema Migrations

`schema_migrations` table tracks applied migrations by filename. The migration runner in `metadata_db.py:apply_migrations` scans `migrations/metadata/*.sql` in sorted order and applies any not yet recorded.

**Portability:** `001_init.sql` uses standard ANSI SQL with no SQLite-specific extensions except `INTEGER PRIMARY KEY` (rowid alias). A PostgreSQL portability check (`scripts/check_metadata_schema_portability.py`) validates this baseline.

### 2.6 Migration 002: Stage Duration Columns

```sql
ALTER TABLE job_stage_status ADD COLUMN duration_ms INTEGER;
ALTER TABLE audit_events      ADD COLUMN duration_ms INTEGER;
```

This two-line migration adds `duration_ms` to both stage-status and audit-event rows. The query layer uses these columns to surface stage timing in:
- Per-job `timing_summary` (stage-by-stage duration map)
- `--stage` filter matched-stage duration
- `--stage-sort duration_desc|duration_asc` ordering
- `grouped_stage_summary` rollup with per-stage timing

Since `ALTER TABLE ... ADD COLUMN` is a non-destructive DDL in both SQLite and PostgreSQL, this migration is safe to run against a populated database. Existing rows get `NULL` for the new column, which the query layer handles gracefully via `COALESCE(duration_ms, 0)`.

---

## 3. `metadata_db.py` — Shared DB Helpers

Key decisions:
- `PRAGMA foreign_keys = ON` is set on every connection — enforces referential integrity.
- `conn.row_factory = sqlite3.Row` for named column access.
- `sha256_file` is included here as a shared helper used by both the importer and the query layer.

---

## 4. Import: `import_run_metadata.py`

### 4.1 Artifact-to-Stage Mapping

The importer uses an explicit `ARTIFACT_TYPE_STAGE_MAP` that maps artifact types to their owning pipeline stage:

```python
ARTIFACT_TYPE_STAGE_MAP = {
    "sse_export_audit":               "sse_export",
    "record_recovery_service_audit":  "record_recovery_service",
    "record_recovery_service_health": "record_recovery_service",
    "record_recovery_service_config": "record_recovery_service",
    "bridge_job_meta":                "bridge",
    "bridge_audit":                   "bridge",
    "pjc_audit":                      "pjc",
    "public_report":                  "policy_release",
    "policy_audit":                   "policy_release",
    "audit_chain":                    "audit",
    "audit_seal":                     "audit",
    "key_access_audit":               "key_access",
}
```

Any artifact not in this map is assigned to a default stage. This mapping allows the query layer to filter by stage without parsing each artifact's schema.

### 4.2 Import Steps

1. Loads `audit_chain.json` to identify the job (required — import fails without it).
2. Upserts `tenants`, `datasets`, `services`, `callers` registry rows from the audit chain's scope fields.
3. Creates a `jobs` row with key fields from the public report and audit chain.
4. Imports stage artifacts as `job_artifacts` rows, checking file existence and computing SHA-256.
5. Imports stage audit records as `audit_events` rows (one per JSONL line per audit file).
6. Imports the `audit_chain` and `audit_seal` full payloads.
7. Optionally: imports policy files via `apply_policy_plan` / `plan_policy_file` as `policies` + `policy_bindings` + `caller_permissions` rows.

### 4.3 Dry-Run and Replay

The importer supports:
- `--dry-run`: computes and prints what would be imported without writing anything.
- `--replay`: deletes all rows from `JOB_DEPENDENT_TABLES` for the existing job_id before re-importing.

`JOB_DEPENDENT_TABLES` is an explicit tuple ensuring cascading cleanup happens in dependency order:
```python
JOB_DEPENDENT_TABLES = (
    "job_artifacts", "job_stage_status", "audit_events",
    "audit_chains", "audit_seals", "key_access_events",
)
```

**Observation:** The `--replay` path deletes job-dependent rows but does not roll back if the re-import fails partway through. A job left in a partially-imported state after a failed replay would need to be manually cleaned or replayed again. For the current read-only sidecar this is acceptable.

### 4.4 Policy Import Integration

The importer delegates policy import to `metadata_registry.py:plan_policy_file` / `apply_policy_plan`. This means policy rows imported from a pipeline run's policy config undergo the same validation as the managed `apply-registry` write path. A policy file change between runs would result in updated `caller_permissions` rows for that job's policy, with a new `imported_at_utc` timestamp.

---

## 5. Query: `query_metadata.py`

The query CLI supports multiple query modes:

### 5.1 By job ID
Returns full job detail including:
- Core job fields.
- Stage artifact paths.
- Stage status breakdown.
- `timing_summary` (stage-by-stage duration from `job_stage_status`).
- `mainline_contract_summary` (loaded from recorded `audit_chain_path`).

### 5.2 By caller / scope
Returns a list of jobs matching the given `--caller`, `--tenant-id`, `--dataset-id`, `--service-id`.

### 5.3 Stage filtering
`--stage <name>`: adds `matched_stage` record and `stage_summary` per job.
`--stage-status`: filters by stage decision.
`--stage-sort duration_desc|duration_asc`: ranks by stage duration.

### 5.4 Grouping and rollups
`--group-by stage`: `grouped_stage_summary` bucketed by stage.
`--group-by status`: `grouped_status_summary` bucketed by overall job status.
Both rollups include `mainline_contract_summary_counts` for handoff cleanup and service audit consistency distributions.

### 5.5 Entity listing
`--list-entity tenants|datasets|services|callers|policies|policy-bindings|caller-permissions`: exposes registry and policy tables.

`caller-permissions` entity responses include a rich `permission_summary` with caller count, resolved tenant/dataset/service IDs, coarse permission booleans, `platform_role_counts`, and per-caller `access_profiles`.

### 5.6 Output formats
`--output-format csv|tsv`: renders grouped rollups and entity lists as delimited reports.
`--columns`: narrows which columns appear in delimited output.
`--output-file`: writes to a file instead of stdout.

---

## 6. HTTP API: `serve_metadata_api.py`

Thin read-only HTTP wrapper over the metadata sidecar:

- `GET /healthz` — unauthenticated health check.
- `GET /v1/jobs/:job_id` — job detail.
- `GET /v1/jobs?caller=...&stage=...&limit=N` — jobs list.
- `GET /v1/entities/:entity?...` — entity listing.

Auth: `Authorization: Bearer <token>` header. The server reads the token from an environment variable (`--auth-token-env`).

The API is read-only by design. It does not expose any write path and does not query the live SSE server, bridge, or PJC process.

Envelope schemas (`metadata_api_health.schema.json`, `metadata_api_response.schema.json`, `metadata_api_error.schema.json`) are frozen in the schema backcompat baseline.

---

## 7. Managed Write Path: `metadata_registry.py` + `manage_metadata_db.py apply-registry`

The `apply-registry` subcommand is the only write path that targets registry tables (tenants, datasets, services, callers, policies). It reads a `metadata_registry_manifest/v1` JSON document specifying registry entries and policy bindings, then applies them as upserts.

This is designed as a deliberate, operator-initiated action — not an automatic sidecar write path. The manifest format is validated against `schemas/metadata_registry_manifest.schema.json` before application.

---

## 8. Authz Tuple Export: `export_authz_tuples.py`

Exports the current caller/tenant/dataset/service policy as `authz_tuple_export/v1`, suitable for import into OpenFGA-style relationship stores:

- Reads policy from `sse_export_policy/v1` file or from the metadata DB's `caller_permissions` table.
- Emits relation tuples: `(caller, tenant, dataset, service, permission)`.
- Disabled callers appear in the `subjects` inventory but do not emit active tuples.
- The export is append-only in concept — subsequent imports into an OpenFGA system would add tuples, not overwrite.

---

## 9. `metadata_registry.py` — Managed Policy Write Path (Full Analysis)

### 9.1 `plan_policy_file` — Dry-Run Planning

The planner is called before any writes. It computes a `plan` dict that describes what action will be taken:

| Action | Condition |
|---|---|
| `noop` | Policy file SHA-256, path, binding count, and permission count all match what is already in the DB |
| `repair` | Policy ID matches but counts diverged (e.g. a previous import was partial) |
| `replace` | Policy file SHA-256 changed (new content = new ID = old record is obsolete) |
| `insert` | Policy not in DB at all |

**Policy ID = SHA-256 of the policy file.** This means the same file content always gets the same `policy_id`, making the `noop` check a single SHA-256 comparison. When the file changes, the new SHA-256 is the new `policy_id`, and the old record is treated as a different entry to be replaced.

```python
policy_id = sha256_file(path) or str(path)
```

The `or str(path)` fallback handles the unlikely case of an unreadable file after the existence check — it falls back to path string, ensuring the plan does not fail silently.

### 9.2 `apply_policy_plan` — Atomic Upsert with Cascade

The `apply_policy_plan` function applies the plan within the caller-provided connection (the caller wraps it in a transaction):

1. If the existing `policy_id` differs from the incoming `policy_id`, the old policy row is deleted via `DELETE FROM policies WHERE policy_id = ?`. This triggers CASCADE delete of `policy_bindings` and `caller_permissions`.

2. The new policy row is upserted:
```sql
INSERT INTO policies(...) VALUES (...)
ON CONFLICT(policy_id) DO UPDATE SET ...
```

3. `policy_bindings` and `caller_permissions` are deleted and re-inserted for the new policy_id:
```python
conn.execute("DELETE FROM policy_bindings WHERE policy_id = ?", (policy_id,))
conn.execute("DELETE FROM caller_permissions WHERE policy_id = ?", (policy_id,))
_insert_policy_children(...)
```

**Observation:** Delete-then-reinsert on every non-noop action (including `repair`) means the `caller_permissions` rows are atomically replaced. There is no partial-update path where old permissions survive alongside new ones. This is the correct approach for an idempotent write path.

### 9.3 `_insert_policy_children` — Flattening the Policy Dict

The caller policy dict is flattened into individual `caller_permissions` rows, one per `(caller, permission_key)` pair:

```python
for caller, caller_policy in callers.items():
    # 1. Insert one policy_binding row per caller with tenant/dataset/service scope
    # 2. Insert one caller_permissions row per key in caller_policy
    for key, value in caller_policy.items():
        conn.execute("INSERT INTO caller_permissions(...) VALUES (...)",
                     (policy_id, caller, key, serialize_permission_value(value), ...))
```

`serialize_permission_value` serializes non-string values as JSON:
```python
def serialize_permission_value(value):
    if isinstance(value, (dict, list, bool, int, float)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
```

This means boolean values like `can_run_bridge: true` are stored as the string `"true"` (JSON serialized). The query layer's `_parse_permission_value` handles the round-trip deserialization.

For `policy_bindings`, multi-dataset and multi-service callers get a single binding row with `dataset_id=None` and `service_id=None`, because the `datasets[0] if len(datasets) == 1 else None` logic only populates the binding-level column when the caller has exactly one allowed value. This preserves the binding row's purpose (scope metadata) without trying to flatten multi-value lists into a single column.

---

## 10. `check_metadata_schema_portability.py` — PostgreSQL Portability Gate

This script applies all migrations to a temporary in-memory SQLite DB and runs six structural checks against the resulting schema:

| Check | What it verifies |
|---|---|
| `sqlite_only_constructs` | No `PRAGMA` or `AUTOINCREMENT` in any `.sql` migration file |
| `primary_keys_present` | Every table has at least one primary key column |
| `utc_columns_use_text` | All `*_utc` columns have type `TEXT` (not `DATETIME`, `TIMESTAMP`, etc.) |
| `json_columns_use_text` | All `*_json` columns have type `TEXT` |
| `expected_indexes_present` | All seven named performance indexes exist |
| `foreign_key_targets_present` | All FK reference tables exist |

**Rationale for `TEXT` columns:** PostgreSQL has native `TIMESTAMP WITH TIME ZONE` and `JSONB` types that are more efficient, but both SQLite and PostgreSQL accept `TEXT` for these columns without schema changes. The convention of storing timestamps as ISO8601 strings in `TEXT` columns is the most portable approach across both engines.

**`SQLITE_ONLY_TOKENS`** lists `PRAGMA` and `AUTOINCREMENT` as SQLite-only constructs. The `INTEGER PRIMARY KEY` alias for rowid (used in `schema_migrations`) is intentionally **not** flagged — SQLite and PostgreSQL both accept `INTEGER PRIMARY KEY` syntax, though with different semantics (rowid alias vs. standard sequence).

The check uses a `tempfile.TemporaryDirectory` so it never touches the production DB. The output is validated against `schemas/metadata_schema_portability.schema.json` and included in the pre-release gate.

---

## 11. Identified Gaps / Observations

| Item | Severity | Note |
|---|---|---|
| Import is not atomic (no rollback on partial failure) | Medium | Acceptable for sidecar-only use; `--replay` handles re-runs |
| `caller_permissions.permission_value` stored as TEXT | Low | Parsed as JSON on read; not typed in the schema |
| `jobs.intersection_sum` stored as INTEGER | Low | Works for cents-scale values; may not be adequate for non-integer sums |
| `audit_events.payload_json` stores full payload as TEXT | Informational | Efficient for portability; not queryable without JSON path operators |
| No pagination in `apply_migrations` | Informational | Not needed for the current migration count |
| `serve_metadata_api.py` has no rate limiting | Low | Fine for local/internal use; needs rate limiting if exposed publicly |
| `--list-entity caller-permissions` exposes all permissions for a policy | Informational | Only accessible with auth token; appropriate for operator use |

---

## 11. Summary

The SQL metadata sidecar is well-designed for its stated purpose: a post-run, read-oriented control-plane overlay. The schema is normalized, foreign key constraints are enforced, and the import/query/API layers are cleanly separated. The managed registry write path is appropriately gated by manifest validation. The main remaining gaps are the non-atomic import (acceptable for sidecar use) and the lack of full Postgres compatibility testing (planned). The PostgreSQL portability check validates the DDL but not the full query layer.
