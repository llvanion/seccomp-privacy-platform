-- 015: Query workflow execution lifecycle state.
--
-- These rows are repo-side durable lifecycle evidence for query workflow
-- execution. Sidecar JSON remains the audit artifact; this table records
-- queued/claim/heartbeat/cancel/timeout/terminal state so duplicate launches
-- and stale leases can be rejected or explicitly stolen by policy.

CREATE TABLE IF NOT EXISTS query_workflow_executions (
    id INTEGER PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE,
    workflow TEXT NOT NULL,
    job_id TEXT NOT NULL,
    out_base TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    request_source TEXT NOT NULL,
    caller TEXT,
    tenant_id TEXT,
    dataset_id TEXT,
    mode TEXT NOT NULL,
    state TEXT NOT NULL,
    terminal INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT NOT NULL,
    lease_expires_at_utc TEXT NOT NULL,
    heartbeat_at_utc TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    finished_at_utc TEXT,
    last_exit_code INTEGER,
    status_path TEXT,
    receipts_path TEXT,
    submission_manifest_path TEXT,
    metadata_json TEXT,
    UNIQUE(job_id),
    UNIQUE(out_base)
);

CREATE INDEX IF NOT EXISTS idx_query_workflow_executions_state
    ON query_workflow_executions (state, terminal);
CREATE INDEX IF NOT EXISTS idx_query_workflow_executions_lease
    ON query_workflow_executions (lease_expires_at_utc);
CREATE INDEX IF NOT EXISTS idx_query_workflow_executions_tenant
    ON query_workflow_executions (tenant_id, state);
CREATE INDEX IF NOT EXISTS idx_query_workflow_executions_digest
    ON query_workflow_executions (request_digest);
