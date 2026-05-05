-- 009: Post-baseline SQL control-plane deepening.
--
-- These tables are sidecar-derived read models. They do not become the
-- runtime source of truth for query execution; they make workflow state,
-- policy/service versions, catalog lineage, and retention/reconcile actions
-- queryable from SQL.

CREATE TABLE IF NOT EXISTS job_state_transitions (
    id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    transition_ordinal INTEGER NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    stage TEXT,
    event_type TEXT,
    ts_utc TEXT,
    source TEXT,
    source_event_id INTEGER,
    details_json TEXT,
    UNIQUE(job_id, transition_ordinal)
);

CREATE INDEX IF NOT EXISTS idx_job_state_transitions_job_id ON job_state_transitions (job_id);
CREATE INDEX IF NOT EXISTS idx_job_state_transitions_state ON job_state_transitions (to_state);
CREATE INDEX IF NOT EXISTS idx_job_state_transitions_ts ON job_state_transitions (ts_utc);

CREATE TABLE IF NOT EXISTS policy_versions (
    id INTEGER PRIMARY KEY,
    policy_id TEXT NOT NULL REFERENCES policies(policy_id) ON DELETE CASCADE,
    policy_kind TEXT NOT NULL,
    path TEXT NOT NULL,
    version TEXT NOT NULL,
    sha256 TEXT,
    schema_name TEXT,
    imported_at_utc TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT,
    UNIQUE(policy_id, version)
);

CREATE INDEX IF NOT EXISTS idx_policy_versions_policy_id ON policy_versions (policy_id);
CREATE INDEX IF NOT EXISTS idx_policy_versions_path_current ON policy_versions (path, is_current);

CREATE TABLE IF NOT EXISTS service_versions (
    id INTEGER PRIMARY KEY,
    service_id TEXT NOT NULL REFERENCES services(service_id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    tenant_id TEXT,
    dataset_id TEXT,
    service_type TEXT,
    transport TEXT,
    config_path TEXT,
    effective_at_utc TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT,
    UNIQUE(service_id, version)
);

CREATE INDEX IF NOT EXISTS idx_service_versions_service_id ON service_versions (service_id);
CREATE INDEX IF NOT EXISTS idx_service_versions_current ON service_versions (service_id, is_current);

CREATE TABLE IF NOT EXISTS catalog_lineage_read_model (
    id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    correlation_id TEXT,
    caller TEXT,
    tenant_id TEXT,
    dataset_id TEXT,
    service_id TEXT,
    lineage_kind TEXT NOT NULL,
    node_id TEXT NOT NULL,
    node_type TEXT,
    display_name TEXT,
    role TEXT,
    stage TEXT,
    source_id TEXT,
    target_id TEXT,
    path_redacted INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT,
    imported_at_utc TEXT NOT NULL,
    UNIQUE(job_id, lineage_kind, node_id)
);

CREATE INDEX IF NOT EXISTS idx_catalog_lineage_job_id ON catalog_lineage_read_model (job_id);
CREATE INDEX IF NOT EXISTS idx_catalog_lineage_dataset_service ON catalog_lineage_read_model (tenant_id, dataset_id, service_id);
CREATE INDEX IF NOT EXISTS idx_catalog_lineage_kind ON catalog_lineage_read_model (lineage_kind);

CREATE TABLE IF NOT EXISTS retention_reconcile_plan (
    id INTEGER PRIMARY KEY,
    scope TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    job_id TEXT,
    retention_class TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    reviewed INTEGER NOT NULL DEFAULT 0,
    created_at_utc TEXT NOT NULL,
    details_json TEXT,
    UNIQUE(scope, entity_type, entity_id, reason_code)
);

CREATE INDEX IF NOT EXISTS idx_retention_reconcile_scope ON retention_reconcile_plan (scope);
CREATE INDEX IF NOT EXISTS idx_retention_reconcile_job ON retention_reconcile_plan (job_id);
CREATE INDEX IF NOT EXISTS idx_retention_reconcile_action ON retention_reconcile_plan (recommended_action);
