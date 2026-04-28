BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY,
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    external_ref TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datasets (
    dataset_id TEXT PRIMARY KEY,
    tenant_id TEXT,
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    dataset_kind TEXT,
    external_ref TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id)
);

CREATE TABLE IF NOT EXISTS services (
    service_id TEXT PRIMARY KEY,
    tenant_id TEXT,
    service_type TEXT,
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    endpoint_ref TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id)
);

CREATE TABLE IF NOT EXISTS callers (
    caller TEXT PRIMARY KEY,
    tenant_id TEXT,
    caller_type TEXT NOT NULL DEFAULT 'human_user',
    display_name TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id)
);

CREATE TABLE IF NOT EXISTS service_bindings (
    binding_id INTEGER PRIMARY KEY,
    tenant_id TEXT,
    dataset_id TEXT,
    service_id TEXT,
    caller TEXT,
    binding_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    external_principal TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id),
    FOREIGN KEY (dataset_id) REFERENCES datasets (dataset_id),
    FOREIGN KEY (service_id) REFERENCES services (service_id),
    FOREIGN KEY (caller) REFERENCES callers (caller)
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    correlation_id TEXT,
    caller TEXT,
    tenant_id TEXT,
    dataset_id TEXT,
    service_id TEXT,
    policy_id TEXT,
    token_scope TEXT,
    token_key_version TEXT,
    record_recovery_boundary TEXT,
    job_type TEXT,
    job_state TEXT NOT NULL DEFAULT 'observed',
    source_out_base TEXT,
    bridge_generator TEXT,
    raw_metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (caller) REFERENCES callers (caller),
    FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id),
    FOREIGN KEY (dataset_id) REFERENCES datasets (dataset_id),
    FOREIGN KEY (service_id) REFERENCES services (service_id)
);

CREATE TABLE IF NOT EXISTS job_stage_status (
    stage_status_id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL,
    decision TEXT,
    reason_code TEXT,
    stage_ts TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs (job_id),
    UNIQUE (job_id, stage_name)
);

CREATE TABLE IF NOT EXISTS job_artifacts (
    artifact_id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    file_path TEXT,
    sha256 TEXT,
    media_type TEXT,
    record_count INTEGER,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs (job_id)
);

CREATE TABLE IF NOT EXISTS job_state_transitions (
    transition_id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    reason_code TEXT,
    actor_type TEXT,
    actor_id TEXT,
    details_json TEXT,
    transitioned_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs (job_id)
);

CREATE TABLE IF NOT EXISTS policies (
    policy_id TEXT PRIMARY KEY,
    tenant_id TEXT,
    policy_kind TEXT,
    policy_version TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    source_path TEXT,
    description TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id)
);

CREATE TABLE IF NOT EXISTS policy_bindings (
    policy_binding_id INTEGER PRIMARY KEY,
    policy_id TEXT NOT NULL,
    tenant_id TEXT,
    dataset_id TEXT,
    service_id TEXT,
    caller TEXT,
    binding_scope TEXT NOT NULL,
    binding_target TEXT,
    effect TEXT NOT NULL DEFAULT 'allow',
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (policy_id) REFERENCES policies (policy_id),
    FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id),
    FOREIGN KEY (dataset_id) REFERENCES datasets (dataset_id),
    FOREIGN KEY (service_id) REFERENCES services (service_id),
    FOREIGN KEY (caller) REFERENCES callers (caller)
);

CREATE TABLE IF NOT EXISTS caller_permissions (
    caller_permission_id INTEGER PRIMARY KEY,
    caller TEXT NOT NULL,
    tenant_id TEXT,
    dataset_id TEXT,
    service_id TEXT,
    policy_id TEXT,
    permission TEXT NOT NULL,
    effect TEXT NOT NULL DEFAULT 'allow',
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (caller) REFERENCES callers (caller),
    FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id),
    FOREIGN KEY (dataset_id) REFERENCES datasets (dataset_id),
    FOREIGN KEY (service_id) REFERENCES services (service_id),
    FOREIGN KEY (policy_id) REFERENCES policies (policy_id)
);

CREATE TABLE IF NOT EXISTS service_permissions (
    service_permission_id INTEGER PRIMARY KEY,
    service_id TEXT NOT NULL,
    tenant_id TEXT,
    dataset_id TEXT,
    caller TEXT,
    policy_id TEXT,
    permission TEXT NOT NULL,
    effect TEXT NOT NULL DEFAULT 'allow',
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (service_id) REFERENCES services (service_id),
    FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id),
    FOREIGN KEY (dataset_id) REFERENCES datasets (dataset_id),
    FOREIGN KEY (caller) REFERENCES callers (caller),
    FOREIGN KEY (policy_id) REFERENCES policies (policy_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_event_id INTEGER PRIMARY KEY,
    job_id TEXT,
    correlation_id TEXT,
    caller TEXT,
    tenant_id TEXT,
    dataset_id TEXT,
    service_id TEXT,
    policy_id TEXT,
    event_schema TEXT,
    event_source TEXT,
    event_name TEXT NOT NULL,
    stage_name TEXT,
    event_ts TEXT,
    decision TEXT,
    reason_code TEXT,
    record_recovery_boundary TEXT,
    raw_event_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs (job_id),
    FOREIGN KEY (caller) REFERENCES callers (caller),
    FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id),
    FOREIGN KEY (dataset_id) REFERENCES datasets (dataset_id),
    FOREIGN KEY (service_id) REFERENCES services (service_id),
    FOREIGN KEY (policy_id) REFERENCES policies (policy_id)
);

CREATE TABLE IF NOT EXISTS audit_chains (
    audit_chain_id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL,
    correlation_id TEXT,
    chain_schema TEXT,
    generated_at TEXT,
    chain_file TEXT,
    chain_sha256 TEXT,
    raw_chain_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs (job_id),
    UNIQUE (job_id, chain_file)
);

CREATE TABLE IF NOT EXISTS audit_seals (
    audit_seal_id INTEGER PRIMARY KEY,
    job_id TEXT,
    correlation_id TEXT,
    artifact_file TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    signature_algorithm TEXT,
    signature TEXT,
    secret_source_kind TEXT,
    secret_source_name TEXT,
    sealed_at TEXT,
    raw_seal_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs (job_id)
);

CREATE TABLE IF NOT EXISTS key_access_events (
    key_access_event_id INTEGER PRIMARY KEY,
    job_id TEXT,
    correlation_id TEXT,
    caller TEXT,
    tenant_id TEXT,
    dataset_id TEXT,
    service_id TEXT,
    policy_id TEXT,
    key_id TEXT NOT NULL,
    key_version TEXT NOT NULL,
    purpose TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason_code TEXT,
    manifest_file TEXT,
    manifest_sha256 TEXT,
    secret_source_kind TEXT,
    secret_source_name TEXT,
    event_ts TEXT,
    raw_event_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs (job_id),
    FOREIGN KEY (caller) REFERENCES callers (caller),
    FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id),
    FOREIGN KEY (dataset_id) REFERENCES datasets (dataset_id),
    FOREIGN KEY (service_id) REFERENCES services (service_id),
    FOREIGN KEY (policy_id) REFERENCES policies (policy_id)
);

CREATE TABLE IF NOT EXISTS key_lifecycle_events (
    key_lifecycle_event_id INTEGER PRIMARY KEY,
    key_id TEXT NOT NULL,
    key_version TEXT,
    event_name TEXT NOT NULL,
    event_ts TEXT,
    actor_type TEXT,
    actor_id TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS key_refs (
    key_id TEXT PRIMARY KEY,
    tenant_id TEXT,
    service_id TEXT,
    backend_type TEXT,
    backend_key_ref TEXT,
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id),
    FOREIGN KEY (service_id) REFERENCES services (service_id)
);

CREATE TABLE IF NOT EXISTS key_versions (
    key_version_id INTEGER PRIMARY KEY,
    key_id TEXT NOT NULL,
    key_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    activated_at TEXT,
    retired_at TEXT,
    secret_source_kind TEXT,
    secret_source_name TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (key_id) REFERENCES key_refs (key_id),
    UNIQUE (key_id, key_version)
);

CREATE TABLE IF NOT EXISTS key_purposes (
    key_purpose_id INTEGER PRIMARY KEY,
    key_id TEXT NOT NULL,
    key_version TEXT,
    purpose TEXT NOT NULL,
    allowed INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (key_id) REFERENCES key_refs (key_id),
    UNIQUE (key_id, key_version, purpose)
);

CREATE TABLE IF NOT EXISTS key_rotation_events (
    key_rotation_event_id INTEGER PRIMARY KEY,
    key_id TEXT NOT NULL,
    key_version TEXT,
    rotated_to_version TEXT,
    event_ts TEXT,
    reason_code TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (key_id) REFERENCES key_refs (key_id)
);

CREATE INDEX IF NOT EXISTS idx_datasets_tenant_id ON datasets (tenant_id);
CREATE INDEX IF NOT EXISTS idx_services_tenant_id ON services (tenant_id);
CREATE INDEX IF NOT EXISTS idx_callers_tenant_id ON callers (tenant_id);
CREATE INDEX IF NOT EXISTS idx_service_bindings_lookup ON service_bindings (tenant_id, dataset_id, service_id, caller);
CREATE INDEX IF NOT EXISTS idx_jobs_correlation_id ON jobs (correlation_id);
CREATE INDEX IF NOT EXISTS idx_jobs_caller ON jobs (caller);
CREATE INDEX IF NOT EXISTS idx_jobs_tenant_id ON jobs (tenant_id);
CREATE INDEX IF NOT EXISTS idx_jobs_dataset_id ON jobs (dataset_id);
CREATE INDEX IF NOT EXISTS idx_jobs_service_id ON jobs (service_id);
CREATE INDEX IF NOT EXISTS idx_jobs_policy_id ON jobs (policy_id);
CREATE INDEX IF NOT EXISTS idx_job_stage_status_job_stage ON job_stage_status (job_id, stage_name);
CREATE INDEX IF NOT EXISTS idx_job_artifacts_job_stage ON job_artifacts (job_id, stage_name);
CREATE INDEX IF NOT EXISTS idx_job_state_transitions_job_id ON job_state_transitions (job_id);
CREATE INDEX IF NOT EXISTS idx_policy_bindings_scope ON policy_bindings (policy_id, tenant_id, dataset_id, service_id, caller);
CREATE INDEX IF NOT EXISTS idx_caller_permissions_scope ON caller_permissions (caller, tenant_id, dataset_id, service_id);
CREATE INDEX IF NOT EXISTS idx_service_permissions_scope ON service_permissions (service_id, tenant_id, dataset_id, caller);
CREATE INDEX IF NOT EXISTS idx_audit_events_job_id ON audit_events (job_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_correlation_id ON audit_events (correlation_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_caller ON audit_events (caller);
CREATE INDEX IF NOT EXISTS idx_audit_events_tenant_id ON audit_events (tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_dataset_id ON audit_events (dataset_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_service_id ON audit_events (service_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_policy_id ON audit_events (policy_id);
CREATE INDEX IF NOT EXISTS idx_key_access_events_job_id ON key_access_events (job_id);
CREATE INDEX IF NOT EXISTS idx_key_access_events_caller ON key_access_events (caller);
CREATE INDEX IF NOT EXISTS idx_key_access_events_key_ref ON key_access_events (key_id, key_version);
CREATE INDEX IF NOT EXISTS idx_key_versions_key_ref ON key_versions (key_id, key_version);
CREATE INDEX IF NOT EXISTS idx_key_purposes_key_ref ON key_purposes (key_id, key_version);

COMMIT;
