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

CREATE TABLE IF NOT EXISTS privacy_budget_ledger_events (
  id SERIAL PRIMARY KEY,
  job_id TEXT REFERENCES jobs(job_id) ON DELETE CASCADE,
  ledger_job_id TEXT,
  correlation_id TEXT,
  policy_version TEXT,
  ts_utc TIMESTAMPTZ,
  caller TEXT,
  tenant_id TEXT,
  dataset_id TEXT,
  purpose TEXT,
  decision TEXT,
  reason_code TEXT,
  abuse_signal TEXT,
  matched_prior_job_id TEXT,
  matched_prior_relation TEXT,
  budget_limit DOUBLE PRECISION,
  budget_cost DOUBLE PRECISION,
  budget_used_before DOUBLE PRECISION,
  budget_used_after DOUBLE PRECISION,
  budget_consumed BOOLEAN,
  query_fingerprint TEXT,
  query_payload_sha256 TEXT,
  window_json JSONB,
  bucket_json JSONB,
  parsed_metrics_json JSONB,
  public_report_sha256 TEXT,
  ledger_path TEXT,
  payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS privacy_budget_consumption_events (
  id SERIAL PRIMARY KEY,
  created_at_utc TIMESTAMPTZ NOT NULL,
  updated_at_utc TIMESTAMPTZ NOT NULL,
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
  window_json JSONB NOT NULL,
  bucket_json JSONB,
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
  budget_limit DOUBLE PRECISION,
  budget_cost DOUBLE PRECISION,
  budget_used_before DOUBLE PRECISION,
  budget_used_after DOUBLE PRECISION,
  budget_consumed BOOLEAN NOT NULL DEFAULT FALSE,
  approval_request_id TEXT,
  public_report_sha256 TEXT,
  ledger_path TEXT,
  status TEXT NOT NULL DEFAULT 'committed',
  failure_reason TEXT,
  source_record_sha256 TEXT,
  payload_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS privacy_budget_approval_events (
  id SERIAL PRIMARY KEY,
  created_at_utc TIMESTAMPTZ NOT NULL,
  updated_at_utc TIMESTAMPTZ NOT NULL,
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
  requested_at_utc TIMESTAMPTZ NOT NULL,
  decided_at_utc TIMESTAMPTZ,
  decided_by TEXT,
  decision_reason TEXT,
  expires_at_utc TIMESTAMPTZ,
  consumed_at_utc TIMESTAMPTZ,
  consumed_by_job_id TEXT,
  consuming_event_id INTEGER REFERENCES privacy_budget_consumption_events(id) ON DELETE SET NULL,
  request_payload_json JSONB NOT NULL,
  latest_decision_json JSONB
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
CREATE INDEX IF NOT EXISTS idx_privacy_budget_source_job_id ON privacy_budget_ledger_events(job_id);
CREATE INDEX IF NOT EXISTS idx_privacy_budget_ledger_job_id ON privacy_budget_ledger_events(ledger_job_id);
CREATE INDEX IF NOT EXISTS idx_privacy_budget_scope ON privacy_budget_ledger_events(caller, tenant_id, dataset_id, purpose);
CREATE INDEX IF NOT EXISTS idx_privacy_budget_decision ON privacy_budget_ledger_events(decision, reason_code);
CREATE UNIQUE INDEX IF NOT EXISTS ux_privacy_budget_scope_query_consumed
  ON privacy_budget_consumption_events(scope_key, query_fingerprint)
  WHERE budget_consumed = TRUE AND decision = 'allow' AND status IN ('reserved', 'committed');
CREATE UNIQUE INDEX IF NOT EXISTS ux_privacy_budget_consumption_source_record
  ON privacy_budget_consumption_events(source_record_sha256)
  WHERE source_record_sha256 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_privacy_budget_consumption_scope ON privacy_budget_consumption_events(scope_key, created_at_utc);
CREATE INDEX IF NOT EXISTS idx_privacy_budget_consumption_job ON privacy_budget_consumption_events(job_id);
CREATE INDEX IF NOT EXISTS idx_privacy_budget_consumption_decision ON privacy_budget_consumption_events(decision, reason_code);
CREATE INDEX IF NOT EXISTS idx_privacy_budget_approval_status ON privacy_budget_approval_events(status, updated_at_utc);
CREATE INDEX IF NOT EXISTS idx_privacy_budget_approval_scope ON privacy_budget_approval_events(caller, tenant_id, dataset_id, purpose);
CREATE INDEX IF NOT EXISTS idx_privacy_budget_approval_query ON privacy_budget_approval_events(query_fingerprint);
CREATE INDEX IF NOT EXISTS idx_key_access_events_job_id ON key_access_events(job_id);
CREATE INDEX IF NOT EXISTS idx_key_refs_service_id ON key_refs(service_id);
CREATE INDEX IF NOT EXISTS idx_key_refs_purpose ON key_refs(purpose);
CREATE INDEX IF NOT EXISTS idx_key_versions_key_name ON key_versions(key_name);
CREATE INDEX IF NOT EXISTS idx_caller_identities_caller ON caller_identities(caller);
CREATE INDEX IF NOT EXISTS idx_caller_identities_service_id ON caller_identities(service_id);
CREATE INDEX IF NOT EXISTS idx_control_plane_mutations_entity ON control_plane_mutations(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_control_plane_mutations_actor ON control_plane_mutations(actor);
CREATE INDEX IF NOT EXISTS idx_control_plane_mutations_applied_at ON control_plane_mutations(applied_at_utc);

-- A2: OpenFGA-style local tuple store (authz sidecar, not main-chain policy)
CREATE TABLE IF NOT EXISTS openfga_tuples (
    id SERIAL PRIMARY KEY,
    user TEXT NOT NULL,
    relation TEXT NOT NULL,
    object TEXT NOT NULL,
    user_type TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    source_policy_id TEXT,
    synced_at_utc TIMESTAMPTZ NOT NULL,
    UNIQUE (user, relation, object)
);

CREATE INDEX IF NOT EXISTS idx_openfga_tuples_user ON openfga_tuples ("user");
CREATE INDEX IF NOT EXISTS idx_openfga_tuples_object ON openfga_tuples (object);
CREATE INDEX IF NOT EXISTS idx_openfga_tuples_relation ON openfga_tuples (relation);
CREATE INDEX IF NOT EXISTS idx_openfga_tuples_synced ON openfga_tuples (synced_at_utc);

-- A4: Service identity token registry (metadata only; never stores raw secrets)
CREATE TABLE IF NOT EXISTS service_tokens (
    id SERIAL PRIMARY KEY,
    jti TEXT NOT NULL UNIQUE,
    service_id TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'service',
    issued_at_utc TIMESTAMPTZ NOT NULL,
    expires_at_utc TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    token_hash TEXT NOT NULL,
    issuer TEXT,
    notes TEXT,
    revoked_at_utc TIMESTAMPTZ,
    revocation_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_service_tokens_service_id ON service_tokens (service_id);
CREATE INDEX IF NOT EXISTS idx_service_tokens_status ON service_tokens (status);
CREATE INDEX IF NOT EXISTS idx_service_tokens_expires ON service_tokens (expires_at_utc);

-- C1-C5: Post-baseline SQL control-plane read models.
CREATE TABLE IF NOT EXISTS job_state_transitions (
    id SERIAL PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    transition_ordinal INTEGER NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    stage TEXT,
    event_type TEXT,
    ts_utc TIMESTAMPTZ,
    source TEXT,
    source_event_id INTEGER,
    details_json JSONB,
    UNIQUE(job_id, transition_ordinal)
);

CREATE INDEX IF NOT EXISTS idx_job_state_transitions_job_id ON job_state_transitions (job_id);
CREATE INDEX IF NOT EXISTS idx_job_state_transitions_state ON job_state_transitions (to_state);
CREATE INDEX IF NOT EXISTS idx_job_state_transitions_ts ON job_state_transitions (ts_utc);

CREATE TABLE IF NOT EXISTS policy_versions (
    id SERIAL PRIMARY KEY,
    policy_id TEXT NOT NULL REFERENCES policies(policy_id) ON DELETE CASCADE,
    policy_kind TEXT NOT NULL,
    path TEXT NOT NULL,
    version TEXT NOT NULL,
    sha256 TEXT,
    schema_name TEXT,
    imported_at_utc TIMESTAMPTZ NOT NULL,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_json JSONB,
    UNIQUE(policy_id, version)
);

CREATE INDEX IF NOT EXISTS idx_policy_versions_policy_id ON policy_versions (policy_id);
CREATE INDEX IF NOT EXISTS idx_policy_versions_path_current ON policy_versions (path, is_current);

CREATE TABLE IF NOT EXISTS service_versions (
    id SERIAL PRIMARY KEY,
    service_id TEXT NOT NULL REFERENCES services(service_id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    tenant_id TEXT,
    dataset_id TEXT,
    service_type TEXT,
    transport TEXT,
    config_path TEXT,
    effective_at_utc TIMESTAMPTZ NOT NULL,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_json JSONB,
    UNIQUE(service_id, version)
);

CREATE INDEX IF NOT EXISTS idx_service_versions_service_id ON service_versions (service_id);
CREATE INDEX IF NOT EXISTS idx_service_versions_current ON service_versions (service_id, is_current);

CREATE TABLE IF NOT EXISTS catalog_lineage_read_model (
    id SERIAL PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    correlation_id TEXT,
    caller TEXT,
    tenant_id TEXT,
    dataset_id TEXT,
    service_id TEXT,
    lineage_kind TEXT NOT NULL,
    node_id TEXT NOT NULL,
    node_type TEXT,
    display_name TEXT,
    role TEXT,
    stage TEXT,
    source_id TEXT,
    target_id TEXT,
    path_redacted BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_json JSONB,
    imported_at_utc TIMESTAMPTZ NOT NULL,
    UNIQUE(job_id, lineage_kind, node_id)
);

CREATE INDEX IF NOT EXISTS idx_catalog_lineage_job_id ON catalog_lineage_read_model (job_id);
CREATE INDEX IF NOT EXISTS idx_catalog_lineage_dataset_service ON catalog_lineage_read_model (tenant_id, dataset_id, service_id);
CREATE INDEX IF NOT EXISTS idx_catalog_lineage_kind ON catalog_lineage_read_model (lineage_kind);

CREATE TABLE IF NOT EXISTS retention_reconcile_plan (
    id SERIAL PRIMARY KEY,
    scope TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    job_id TEXT,
    retention_class TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    reviewed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at_utc TIMESTAMPTZ NOT NULL,
    details_json JSONB,
    UNIQUE(scope, entity_type, entity_id, reason_code)
);

CREATE INDEX IF NOT EXISTS idx_retention_reconcile_scope ON retention_reconcile_plan (scope);
CREATE INDEX IF NOT EXISTS idx_retention_reconcile_job ON retention_reconcile_plan (job_id);
CREATE INDEX IF NOT EXISTS idx_retention_reconcile_action ON retention_reconcile_plan (recommended_action);

-- E-commerce fact-layer baseline (Track-E1; mirrors migrations/metadata/010_add_ecommerce_fact_tables.sql).
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    order_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    service_id TEXT,
    buyer_email TEXT NOT NULL,
    platform_id TEXT,
    campaign_id TEXT,
    currency TEXT NOT NULL,
    total_amount_cents BIGINT NOT NULL,
    placed_at_utc TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL,
    ingested_at_utc TIMESTAMPTZ NOT NULL,
    UNIQUE(tenant_id, order_id)
);

CREATE INDEX IF NOT EXISTS idx_orders_tenant_dataset_email ON orders (tenant_id, dataset_id, buyer_email);
CREATE INDEX IF NOT EXISTS idx_orders_tenant_placed_at ON orders (tenant_id, placed_at_utc);
CREATE INDEX IF NOT EXISTS idx_orders_tenant_campaign ON orders (tenant_id, campaign_id);

CREATE TABLE IF NOT EXISTS order_items (
    id SERIAL PRIMARY KEY,
    order_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    category_id TEXT,
    quantity INTEGER NOT NULL,
    unit_price_cents BIGINT NOT NULL,
    line_total_cents BIGINT NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL,
    ingested_at_utc TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items (order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_tenant_sku ON order_items (tenant_id, sku_id);
CREATE INDEX IF NOT EXISTS idx_order_items_tenant_category ON order_items (tenant_id, category_id);

CREATE TABLE IF NOT EXISTS order_attribution (
    id SERIAL PRIMARY KEY,
    order_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    attribution_type TEXT NOT NULL,
    channel TEXT NOT NULL,
    campaign_id TEXT,
    creative_id TEXT,
    attribution_weight DOUBLE PRECISION NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL,
    ingested_at_utc TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_order_attribution_order_id ON order_attribution (order_id);
CREATE INDEX IF NOT EXISTS idx_order_attribution_tenant_channel ON order_attribution (tenant_id, channel);

CREATE TABLE IF NOT EXISTS order_payment (
    id SERIAL PRIMARY KEY,
    order_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    provider_id TEXT,
    paid_amount_cents BIGINT NOT NULL,
    paid_at_utc TIMESTAMPTZ,
    risk_score DOUBLE PRECISION,
    is_disputed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at_utc TIMESTAMPTZ NOT NULL,
    ingested_at_utc TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_order_payment_order_id ON order_payment (order_id);
CREATE INDEX IF NOT EXISTS idx_order_payment_tenant_method ON order_payment (tenant_id, payment_method);
CREATE INDEX IF NOT EXISTS idx_order_payment_tenant_disputed ON order_payment (tenant_id, is_disputed);

CREATE TABLE IF NOT EXISTS order_fulfillment (
    id SERIAL PRIMARY KEY,
    order_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    carrier_id TEXT,
    warehouse_id TEXT,
    shipped_at_utc TIMESTAMPTZ,
    delivered_at_utc TIMESTAMPTZ,
    status TEXT NOT NULL,
    delivery_latency_minutes INTEGER,
    created_at_utc TIMESTAMPTZ NOT NULL,
    ingested_at_utc TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_order_fulfillment_order_id ON order_fulfillment (order_id);
CREATE INDEX IF NOT EXISTS idx_order_fulfillment_tenant_status ON order_fulfillment (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_order_fulfillment_tenant_carrier ON order_fulfillment (tenant_id, carrier_id);

CREATE TABLE IF NOT EXISTS customer_service_interactions (
    id SERIAL PRIMARY KEY,
    order_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    interaction_type TEXT NOT NULL,
    channel TEXT NOT NULL,
    agent_id TEXT,
    opened_at_utc TIMESTAMPTZ,
    closed_at_utc TIMESTAMPTZ,
    resolution_status TEXT NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL,
    ingested_at_utc TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_csi_order_id ON customer_service_interactions (order_id);
CREATE INDEX IF NOT EXISTS idx_csi_tenant_type ON customer_service_interactions (tenant_id, interaction_type);
CREATE INDEX IF NOT EXISTS idx_csi_tenant_agent ON customer_service_interactions (tenant_id, agent_id);

-- Business identities baseline (Track-E2; mirrors migrations/metadata/011_add_business_identities.sql).
CREATE TABLE IF NOT EXISTS business_identities (
    id SERIAL PRIMARY KEY,
    business_identity_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    identity_kind TEXT NOT NULL,
    caller_id TEXT,
    subject_external_id TEXT NOT NULL,
    display_label TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at_utc TIMESTAMPTZ NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL,
    metadata_json JSONB,
    UNIQUE(tenant_id, business_identity_id)
);

CREATE INDEX IF NOT EXISTS idx_business_identities_tenant_kind ON business_identities (tenant_id, identity_kind);
CREATE INDEX IF NOT EXISTS idx_business_identities_caller ON business_identities (caller_id);
CREATE INDEX IF NOT EXISTS idx_business_identities_subject ON business_identities (tenant_id, subject_external_id);

-- I3 self-service request submission and approval baseline.
CREATE TABLE IF NOT EXISTS workflow_submissions (
    id SERIAL PRIMARY KEY,
    submission_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    submitted_at_utc TIMESTAMPTZ NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL,
    workflow TEXT NOT NULL,
    query_type TEXT,
    job_id TEXT,
    caller TEXT,
    tenant_id TEXT,
    dataset_id TEXT,
    service_id TEXT,
    request_digest TEXT NOT NULL,
    request_source TEXT NOT NULL,
    request_json JSONB NOT NULL,
    request_summary_json JSONB NOT NULL,
    submitted_by_identity_json JSONB,
    approved_by TEXT,
    approved_at_utc TIMESTAMPTZ,
    rejected_by TEXT,
    rejected_at_utc TIMESTAMPTZ,
    rejection_reason TEXT,
    transition_history_json JSONB NOT NULL,
    metadata_json JSONB
);

CREATE INDEX IF NOT EXISTS idx_workflow_submissions_submission_id ON workflow_submissions (submission_id);
CREATE INDEX IF NOT EXISTS idx_workflow_submissions_status ON workflow_submissions (status);
CREATE INDEX IF NOT EXISTS idx_workflow_submissions_tenant_status ON workflow_submissions (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_workflow_submissions_caller ON workflow_submissions (caller);
CREATE INDEX IF NOT EXISTS idx_workflow_submissions_job_id ON workflow_submissions (job_id);
