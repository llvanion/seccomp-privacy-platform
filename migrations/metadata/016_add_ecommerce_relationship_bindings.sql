-- 016: E-commerce business-relationship binding columns.
--
-- Extends the fact-layer baseline so business-access checks can bind caller
-- business identities to concrete commerce records instead of trusting only
-- caller-supplied relationship/scope hints.
--
-- These columns are control-plane relationship anchors. They are not part of
-- the normal business read surface and should stay behind the business access
-- gate rather than being exposed as ordinary report fields.

ALTER TABLE orders ADD COLUMN merchant_business_identity_id TEXT;
ALTER TABLE orders ADD COLUMN buyer_business_identity_id TEXT;

CREATE INDEX IF NOT EXISTS idx_orders_tenant_merchant_identity
    ON orders (tenant_id, merchant_business_identity_id);
CREATE INDEX IF NOT EXISTS idx_orders_tenant_buyer_identity
    ON orders (tenant_id, buyer_business_identity_id);

ALTER TABLE order_attribution ADD COLUMN assigned_marketer_business_identity_id TEXT;

CREATE INDEX IF NOT EXISTS idx_order_attribution_tenant_marketer
    ON order_attribution (tenant_id, assigned_marketer_business_identity_id, campaign_id);

ALTER TABLE order_payment ADD COLUMN assigned_fraud_analyst_business_identity_id TEXT;
ALTER TABLE order_payment ADD COLUMN fraud_case_id TEXT;

CREATE INDEX IF NOT EXISTS idx_order_payment_tenant_fraud_identity
    ON order_payment (tenant_id, assigned_fraud_analyst_business_identity_id);
CREATE INDEX IF NOT EXISTS idx_order_payment_tenant_fraud_case
    ON order_payment (tenant_id, fraud_case_id);

ALTER TABLE customer_service_interactions ADD COLUMN case_id TEXT;

CREATE INDEX IF NOT EXISTS idx_csi_tenant_case
    ON customer_service_interactions (tenant_id, case_id);
