PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tenants (
  tenant_id TEXT PRIMARY KEY,
  created_at_utc TEXT NOT NULL,
  source TEXT,
  last_seen_job_id TEXT
);

CREATE TABLE IF NOT EXISTS datasets (
  dataset_id TEXT PRIMARY KEY,
  tenant_id TEXT REFERENCES tenants(tenant_id),
  created_at_utc TEXT NOT NULL,
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
  created_at_utc TEXT NOT NULL,
  last_seen_job_id TEXT
);

CREATE TABLE IF NOT EXISTS callers (
  caller TEXT PRIMARY KEY,
  tenant_id TEXT REFERENCES tenants(tenant_id),
  created_at_utc TEXT NOT NULL,
  source TEXT,
  last_seen_job_id TEXT
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
  public_report_released INTEGER,
  intersection_size INTEGER,
  intersection_sum INTEGER,
  created_at_utc TEXT,
  imported_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  path TEXT NOT NULL,
  sha256 TEXT,
  file_format TEXT,
  exists_on_disk INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT,
  UNIQUE(job_id, artifact_type, path)
);

CREATE TABLE IF NOT EXISTS job_stage_status (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  ts_utc TEXT,
  details_json TEXT,
  UNIQUE(job_id, stage)
);

CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
  correlation_id TEXT,
  stage TEXT NOT NULL,
  event_type TEXT NOT NULL,
  ts_utc TEXT,
  caller TEXT,
  tenant_id TEXT,
  dataset_id TEXT,
  service_id TEXT,
  decision TEXT,
  reason_code TEXT,
  artifact_path TEXT,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_chains (
  job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  sha256 TEXT,
  generated_at_utc TEXT,
  counts_json TEXT,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_seals (
  job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  sha256 TEXT,
  algorithm TEXT,
  signed INTEGER,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policies (
  policy_id TEXT PRIMARY KEY,
  policy_kind TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  sha256 TEXT,
  schema_name TEXT,
  imported_at_utc TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_bindings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  policy_id TEXT NOT NULL REFERENCES policies(policy_id) ON DELETE CASCADE,
  binding_kind TEXT NOT NULL,
  caller TEXT,
  tenant_id TEXT,
  dataset_id TEXT,
  service_id TEXT,
  source_file TEXT NOT NULL,
  binding_json TEXT,
  imported_at_utc TEXT NOT NULL,
  UNIQUE(policy_id, binding_kind, caller)
);

CREATE TABLE IF NOT EXISTS caller_permissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  policy_id TEXT NOT NULL REFERENCES policies(policy_id) ON DELETE CASCADE,
  caller TEXT NOT NULL,
  permission_key TEXT NOT NULL,
  permission_value TEXT,
  source_file TEXT NOT NULL,
  imported_at_utc TEXT NOT NULL,
  UNIQUE(policy_id, caller, permission_key)
);

CREATE TABLE IF NOT EXISTS key_access_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
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
  ts_utc TEXT,
  source_file TEXT,
  payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_caller ON jobs(caller);
CREATE INDEX IF NOT EXISTS idx_jobs_tenant_dataset ON jobs(tenant_id, dataset_id);
CREATE INDEX IF NOT EXISTS idx_jobs_service_id ON jobs(service_id);
CREATE INDEX IF NOT EXISTS idx_job_artifacts_job_id ON job_artifacts(job_id);
CREATE INDEX IF NOT EXISTS idx_job_stage_status_job_id ON job_stage_status(job_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_job_stage ON audit_events(job_id, stage);
CREATE INDEX IF NOT EXISTS idx_key_access_events_job_id ON key_access_events(job_id);
