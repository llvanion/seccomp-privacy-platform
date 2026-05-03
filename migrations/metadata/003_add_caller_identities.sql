CREATE TABLE IF NOT EXISTS caller_identities (
  id INTEGER PRIMARY KEY,
  caller TEXT NOT NULL REFERENCES callers(caller) ON DELETE CASCADE,
  issuer TEXT NOT NULL DEFAULT '',
  subject TEXT NOT NULL,
  subject_type TEXT NOT NULL,
  service_id TEXT REFERENCES services(service_id),
  display_name TEXT,
  platform_roles_json TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  metadata_json TEXT,
  source TEXT,
  created_at_utc TEXT NOT NULL,
  UNIQUE(caller, issuer, subject)
);

CREATE INDEX IF NOT EXISTS idx_caller_identities_caller ON caller_identities(caller);
CREATE INDEX IF NOT EXISTS idx_caller_identities_service_id ON caller_identities(service_id);
