CREATE TABLE IF NOT EXISTS issuer_registry (
  issuer TEXT PRIMARY KEY,
  issuer_type TEXT NOT NULL,
  display_name TEXT,
  service_id TEXT REFERENCES services(service_id),
  jwks_uri TEXT,
  token_endpoint TEXT,
  claim_mapping_json TEXT,
  trusted_audiences_json TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  source TEXT,
  created_at_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_issuer_registry_type ON issuer_registry(issuer_type);
CREATE INDEX IF NOT EXISTS idx_issuer_registry_enabled ON issuer_registry(enabled);
