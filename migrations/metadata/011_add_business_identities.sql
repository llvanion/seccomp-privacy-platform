-- 011: Business identities baseline (Track-E2).
--
-- Adds a `business_identities` table that records the e-commerce business
-- personas (buyer / merchant_staff / customer_service_agent / courier /
-- field_marketer / fraud_analyst) without breaking the frozen
-- `caller_permissions` shape.
--
-- Business identities are NOT callers. They cannot run privacy stages on
-- their own; they only annotate which platform `caller` (if any) is acting
-- on their behalf, and they appear in fact-table fields like
-- `customer_service_interactions.agent_id` and `order_fulfillment.carrier_id`.
--
-- The table is deliberately PII-free: it stores a tenant-scoped external
-- subject ID and an optional non-PII display label; it never stores names,
-- phone numbers, addresses, or identity documents.
--
-- See docs/ECOMMERCE_ACCESS_MODEL.md (Track-E2 section) for the full design.

CREATE TABLE IF NOT EXISTS business_identities (
    id INTEGER PRIMARY KEY,
    business_identity_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    identity_kind TEXT NOT NULL,
    caller_id TEXT,
    subject_external_id TEXT NOT NULL,
    display_label TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    metadata_json TEXT,
    UNIQUE(tenant_id, business_identity_id)
);

CREATE INDEX IF NOT EXISTS idx_business_identities_tenant_kind
    ON business_identities (tenant_id, identity_kind);
CREATE INDEX IF NOT EXISTS idx_business_identities_caller
    ON business_identities (caller_id);
CREATE INDEX IF NOT EXISTS idx_business_identities_subject
    ON business_identities (tenant_id, subject_external_id);
