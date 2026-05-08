-- 012: I3 self-service request submission and approval baseline.
--
-- This is a sidecar control-plane table for tenant-facing request forms.
-- It stores the validated query_workflow_request/v1 payload as a pending
-- approval record; approval/rejection transitions are appended here while
-- approved execution still reuses the existing query workflow sidecars.

CREATE TABLE IF NOT EXISTS workflow_submissions (
    id INTEGER PRIMARY KEY,
    submission_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    submitted_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    workflow TEXT NOT NULL,
    query_type TEXT,
    job_id TEXT,
    caller TEXT,
    tenant_id TEXT,
    dataset_id TEXT,
    service_id TEXT,
    request_digest TEXT NOT NULL,
    request_source TEXT NOT NULL,
    request_json TEXT NOT NULL,
    request_summary_json TEXT NOT NULL,
    submitted_by_identity_json TEXT,
    approved_by TEXT,
    approved_at_utc TEXT,
    rejected_by TEXT,
    rejected_at_utc TEXT,
    rejection_reason TEXT,
    transition_history_json TEXT NOT NULL,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_workflow_submissions_submission_id
    ON workflow_submissions (submission_id);
CREATE INDEX IF NOT EXISTS idx_workflow_submissions_status
    ON workflow_submissions (status);
CREATE INDEX IF NOT EXISTS idx_workflow_submissions_tenant_status
    ON workflow_submissions (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_workflow_submissions_caller
    ON workflow_submissions (caller);
CREATE INDEX IF NOT EXISTS idx_workflow_submissions_job_id
    ON workflow_submissions (job_id);
