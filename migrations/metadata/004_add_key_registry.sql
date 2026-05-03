CREATE TABLE IF NOT EXISTS key_refs (
  key_name TEXT PRIMARY KEY,
  purpose TEXT NOT NULL,
  service_id TEXT REFERENCES services(service_id),
  backend_kind TEXT NOT NULL,
  backend_ref TEXT,
  active_version TEXT,
  allowed_callers_json TEXT,
  source TEXT,
  created_at_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS key_versions (
  id INTEGER PRIMARY KEY,
  key_name TEXT NOT NULL REFERENCES key_refs(key_name) ON DELETE CASCADE,
  version TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL,
  secret_ref_kind TEXT,
  secret_ref_name TEXT,
  backend_key_version TEXT,
  created_at_utc TEXT,
  source TEXT,
  metadata_json TEXT,
  UNIQUE(key_name, version)
);

CREATE INDEX IF NOT EXISTS idx_key_refs_service_id ON key_refs(service_id);
CREATE INDEX IF NOT EXISTS idx_key_refs_purpose ON key_refs(purpose);
CREATE INDEX IF NOT EXISTS idx_key_versions_key_name ON key_versions(key_name);
