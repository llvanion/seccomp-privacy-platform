-- Postgres DDL target for seccomp-privacy-platform metadata sidecar.
-- Equivalent to SQLite migrations 001 through 004 combined.
-- Key differences from SQLite DDL:
--   - Surrogate integer PKs use SERIAL (auto-increment sequence)
--   - Boolean columns use BOOLEAN instead of INTEGER
--   - Timestamp/date columns use TIMESTAMPTZ instead of TEXT
--   - JSON columns use JSONB for indexable structured storage
--   - Foreign keys are enforced by default (no PRAGMA needed)

CREATE TABLE IF NOT EXISTS tenants (
  tenant_id TEXT PRIMARY KEY,
  created_at_utc TIMESTAMPTZ NOT NULL,
  source TEXT,
  last_seen_job_id TEXT
);

CREATE TABLE IF NOT EXISTS datasets (
  dataset_id TEXT PRIMARY KEY,
  tenant_id TEXT REFERENCES tenants(tenant_id),
  created_at_utc TIMESTAMPTZ NOT NULL,
  source TEXT,
  last_seen_job_id TEXT
);

CREATE TABLE IF NOT EXISTS services (
  service_id TEXT PRIMARY KEY,
  tenant_id TEXT REFERENCES tenants(tenant_id),
  dataset_id TEXT REFERENCES datasets(dataset_id),
  service_type TEXT,
  transport TEXT,
  config_path TEXT,
  created_at_utc TIMESTAMPTZ NOT NULL,
  last_seen_job_id TEXT
);

CREATE TABLE IF NOT EXISTS callers (
  caller TEXT PRIMARY KEY,
  tenant_id TEXT REFERENCES tenants(tenant_id),
  created_at_utc TIMESTAMPTZ NOT NULL,
  source TEXT,
  last_seen_job_id TEXT
);

CREATE TABLE IF NOT EXISTS caller_identities (
  id SERIAL PRIMARY KEY,
  caller TEXT NOT NULL REFERENCES callers(caller) ON DELETE CASCADE,
  issuer TEXT NOT NULL DEFAULT '',
  subject TEXT NOT NULL,
  subject_type TEXT NOT NULL,
  service_id TEXT REFERENCES services(service_id),
  display_name TEXT,
  platform_roles_json JSONB,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  metadata_json JSONB,
  source TEXT,
  created_at_utc TIMESTAMPTZ NOT NULL,
  UNIQUE(caller, issuer, subject)
);

CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  correlation_id TEXT,
  caller TEXT REFERENCES callers(caller),
  tenant_id TEXT REFERENCES tenants(tenant_id),
  dataset_id TEXT REFERENCES datasets(dataset_id),
  service_id TEXT REFERENCES services(service_id),
  out_base TEXT NOT NULL,
  public_report_path TEXT,
  audit_chain_path TEXT,
  status TEXT,
  release_reason_code TEXT,
  public_report_released BOOLEAN,
  intersection_size INTEGER,
  intersection_sum INTEGER,
  created_at_utc TIMESTAMPTZ,
  imported_at_utc TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS job_artifacts (
  id SERIAL PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  path TEXT NOT NULL,
  sha256 TEXT,
  file_format TEXT,
  exists_on_disk BOOLEAN NOT NULL DEFAULT FALSE,
  metadata_json JSONB,
  UNIQUE(job_id, artifact_type, path)
);

CREATE TABLE IF NOT EXISTS job_stage_status (
  id SERIAL PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  ts_utc TIMESTAMPTZ,
  duration_ms INTEGER,
  details_json JSONB,
  UNIQUE(job_id, stage)
);

CREATE TABLE IF NOT EXISTS audit_events (
  id SERIAL PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
  correlation_id TEXT,
  stage TEXT NOT NULL,
  event_type TEXT NOT NULL,
  ts_utc TIMESTAMPTZ,
  duration_ms INTEGER,
  caller TEXT,
  tenant_id TEXT,
  dataset_id TEXT,
  service_id TEXT,
  decision TEXT,
  reason_code TEXT,
  artifact_path TEXT,
  payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_chains (
  job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  sha256 TEXT,
  generated_at_utc TIMESTAMPTZ,
  counts_json JSONB,
  payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_seals (
  job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  sha256 TEXT,
  algorithm TEXT,
  signed BOOLEAN,
  payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS policies (
  policy_id TEXT PRIMARY KEY,
  policy_kind TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  sha256 TEXT,
  schema_name TEXT,
  imported_at_utc TIMESTAMPTZ NOT NULL,
  payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_bindings (
  id SERIAL PRIMARY KEY,
  policy_id TEXT NOT NULL REFERENCES policies(policy_id) ON DELETE CASCADE,
  binding_kind TEXT NOT NULL,
  caller TEXT,
  tenant_id TEXT,
  dataset_id TEXT,
  service_id TEXT,
  source_file TEXT NOT NULL,
  binding_json JSONB,
  imported_at_utc TIMESTAMPTZ NOT NULL,
  UNIQUE(policy_id, binding_kind, caller)
);

CREATE TABLE IF NOT EXISTS caller_permissions (
  id SERIAL PRIMARY KEY,
  policy_id TEXT NOT NULL REFERENCES policies(policy_id) ON DELETE CASCADE,
  caller TEXT NOT NULL,
  permission_key TEXT NOT NULL,
  permission_value TEXT,
  source_file TEXT NOT NULL,
  imported_at_utc TIMESTAMPTZ NOT NULL,
  UNIQUE(policy_id, caller, permission_key)
);

CREATE TABLE IF NOT EXISTS key_access_events (
  id SERIAL PRIMARY KEY,
  job_id TEXT REFERENCES jobs(job_id) ON DELETE CASCADE,
  correlation_id TEXT,
  caller TEXT,
  tenant_id TEXT,
  dataset_id TEXT,
  service_id TEXT,
  key_id TEXT,
  key_version TEXT,
  purpose TEXT,
  decision TEXT,
  reason_code TEXT,
  ts_utc TIMESTAMPTZ,
  source_file TEXT,
  payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS key_refs (
  key_name TEXT PRIMARY KEY,
  purpose TEXT NOT NULL,
  service_id TEXT REFERENCES services(service_id),
  backend_kind TEXT NOT NULL,
  backend_ref TEXT,
  active_version TEXT,
  allowed_callers_json JSONB,
  source TEXT,
  created_at_utc TIMESTAMPTZ NOT NULL,
  updated_at_utc TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS key_versions (
  id SERIAL PRIMARY KEY,
  key_name TEXT NOT NULL REFERENCES key_refs(key_name) ON DELETE CASCADE,
  version TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  status TEXT NOT NULL,
  secret_ref_kind TEXT,
  secret_ref_name TEXT,
  backend_key_version TEXT,
  created_at_utc TIMESTAMPTZ,
  source TEXT,
  metadata_json JSONB,
  UNIQUE(key_name, version)
);

CREATE TABLE IF NOT EXISTS control_plane_mutations (
  id SERIAL PRIMARY KEY,
  mutation_id TEXT NOT NULL UNIQUE,
  operation TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  actor TEXT,
  source TEXT,
  old_state_json JSONB,
  new_state_json JSONB,
  status TEXT NOT NULL DEFAULT 'applied',
  applied_at_utc TIMESTAMPTZ NOT NULL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS issuer_registry (
  issuer TEXT PRIMARY KEY,
  issuer_type TEXT NOT NULL,
  display_name TEXT,
  service_id TEXT REFERENCES services(service_id),
  jwks_uri TEXT,
  token_endpoint TEXT,
  claim_mapping_json JSONB,
  trusted_audiences_json JSONB,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  source TEXT,
  created_at_utc TIMESTAMPTZ NOT NULL,
  updated_at_utc TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_issuer_registry_type ON issuer_registry(issuer_type);
CREATE INDEX IF NOT EXISTS idx_issuer_registry_enabled ON issuer_registry(enabled);

CREATE INDEX IF NOT EXISTS idx_jobs_caller ON jobs(caller);
CREATE INDEX IF NOT EXISTS idx_jobs_tenant_dataset ON jobs(tenant_id, dataset_id);
CREATE INDEX IF NOT EXISTS idx_jobs_service_id ON jobs(service_id);
CREATE INDEX IF NOT EXISTS idx_job_artifacts_job_id ON job_artifacts(job_id);
CREATE INDEX IF NOT EXISTS idx_job_stage_status_job_id ON job_stage_status(job_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_job_stage ON audit_events(job_id, stage);
CREATE INDEX IF NOT EXISTS idx_key_access_events_job_id ON key_access_events(job_id);
CREATE INDEX IF NOT EXISTS idx_key_refs_service_id ON key_refs(service_id);
CREATE INDEX IF NOT EXISTS idx_key_refs_purpose ON key_refs(purpose);
CREATE INDEX IF NOT EXISTS idx_key_versions_key_name ON key_versions(key_name);
CREATE INDEX IF NOT EXISTS idx_caller_identities_caller ON caller_identities(caller);
CREATE INDEX IF NOT EXISTS idx_caller_identities_service_id ON caller_identities(service_id);
CREATE INDEX IF NOT EXISTS idx_control_plane_mutations_entity ON control_plane_mutations(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_control_plane_mutations_actor ON control_plane_mutations(actor);
CREATE INDEX IF NOT EXISTS idx_control_plane_mutations_applied_at ON control_plane_mutations(applied_at_utc);
