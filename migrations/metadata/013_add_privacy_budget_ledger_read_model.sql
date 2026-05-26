CREATE TABLE IF NOT EXISTS privacy_budget_ledger_events (
  id INTEGER PRIMARY KEY,
  job_id TEXT REFERENCES jobs(job_id) ON DELETE CASCADE,
  ledger_job_id TEXT,
  correlation_id TEXT,
  policy_version TEXT,
  ts_utc TEXT,
  caller TEXT,
  tenant_id TEXT,
  dataset_id TEXT,
  purpose TEXT,
  decision TEXT,
  reason_code TEXT,
  abuse_signal TEXT,
  matched_prior_job_id TEXT,
  matched_prior_relation TEXT,
  budget_limit REAL,
  budget_cost REAL,
  budget_used_before REAL,
  budget_used_after REAL,
  budget_consumed INTEGER,
  query_fingerprint TEXT,
  query_payload_sha256 TEXT,
  window_json TEXT,
  bucket_json TEXT,
  parsed_metrics_json TEXT,
  public_report_sha256 TEXT,
  ledger_path TEXT,
  payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_privacy_budget_source_job_id ON privacy_budget_ledger_events(job_id);
CREATE INDEX IF NOT EXISTS idx_privacy_budget_ledger_job_id ON privacy_budget_ledger_events(ledger_job_id);
CREATE INDEX IF NOT EXISTS idx_privacy_budget_scope ON privacy_budget_ledger_events(caller, tenant_id, dataset_id, purpose);
CREATE INDEX IF NOT EXISTS idx_privacy_budget_decision ON privacy_budget_ledger_events(decision, reason_code);
