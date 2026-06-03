CREATE TABLE IF NOT EXISTS privacy_budget_consumption_events (
  id INTEGER PRIMARY KEY,
  created_at_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL,
  scope_key TEXT NOT NULL,
  caller TEXT NOT NULL,
  tenant_id TEXT,
  dataset_id TEXT,
  purpose TEXT,
  job_id TEXT REFERENCES jobs(job_id) ON DELETE SET NULL,
  correlation_id TEXT,
  policy_version TEXT,
  query_fingerprint TEXT NOT NULL,
  query_payload_sha256 TEXT NOT NULL,
  window_start TEXT,
  window_end TEXT,
  window_json TEXT NOT NULL,
  bucket_json TEXT,
  bucket_key TEXT,
  value_mode TEXT,
  threshold_k INTEGER NOT NULL,
  decision TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  reason TEXT NOT NULL,
  abuse_signal TEXT,
  matched_prior_fingerprint TEXT,
  matched_prior_job_id TEXT,
  matched_prior_relation TEXT,
  budget_limit REAL,
  budget_cost REAL,
  budget_used_before REAL,
  budget_used_after REAL,
  budget_consumed INTEGER NOT NULL DEFAULT 0,
  approval_request_id TEXT,
  public_report_sha256 TEXT,
  ledger_path TEXT,
  status TEXT NOT NULL DEFAULT 'committed',
  failure_reason TEXT,
  source_record_sha256 TEXT,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS privacy_budget_approval_events (
  id INTEGER PRIMARY KEY,
  created_at_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL,
  request_id TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  caller TEXT NOT NULL,
  tenant_id TEXT,
  dataset_id TEXT,
  purpose TEXT,
  job_id TEXT REFERENCES jobs(job_id) ON DELETE SET NULL,
  correlation_id TEXT,
  policy_version TEXT,
  query_fingerprint TEXT NOT NULL,
  query_payload_sha256 TEXT NOT NULL,
  matched_prior_fingerprint TEXT,
  matched_prior_job_id TEXT,
  matched_prior_relation TEXT,
  requested_at_utc TEXT NOT NULL,
  decided_at_utc TEXT,
  decided_by TEXT,
  decision_reason TEXT,
  expires_at_utc TEXT,
  consumed_at_utc TEXT,
  consumed_by_job_id TEXT,
  consuming_event_id INTEGER REFERENCES privacy_budget_consumption_events(id) ON DELETE SET NULL,
  request_payload_json TEXT NOT NULL,
  latest_decision_json TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_privacy_budget_scope_query_consumed
  ON privacy_budget_consumption_events(scope_key, query_fingerprint)
  WHERE budget_consumed = 1 AND decision = 'allow' AND status IN ('reserved', 'committed');

CREATE UNIQUE INDEX IF NOT EXISTS ux_privacy_budget_consumption_source_record
  ON privacy_budget_consumption_events(source_record_sha256)
  WHERE source_record_sha256 IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_privacy_budget_consumption_scope
  ON privacy_budget_consumption_events(scope_key, created_at_utc);

CREATE INDEX IF NOT EXISTS idx_privacy_budget_consumption_job
  ON privacy_budget_consumption_events(job_id);

CREATE INDEX IF NOT EXISTS idx_privacy_budget_consumption_decision
  ON privacy_budget_consumption_events(decision, reason_code);

CREATE INDEX IF NOT EXISTS idx_privacy_budget_approval_status
  ON privacy_budget_approval_events(status, updated_at_utc);

CREATE INDEX IF NOT EXISTS idx_privacy_budget_approval_scope
  ON privacy_budget_approval_events(caller, tenant_id, dataset_id, purpose);

CREATE INDEX IF NOT EXISTS idx_privacy_budget_approval_query
  ON privacy_budget_approval_events(query_fingerprint);
