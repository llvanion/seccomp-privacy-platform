-- 010: E-commerce fact-layer baseline (Track-E1).
--
-- Six tables that the privacy pipeline can target as a real source-of-truth
-- dataset. The bridge join key stays `email` (here aliased to `buyer_email`)
-- and the value column for `--client-value-mode raw-int` is
-- `orders.total_amount_cents`. Every other column stays tenant-side and is
-- never exported through the bridge/PJC boundary.
--
-- Scope keys (`tenant_id`, `dataset_id`, `service_id`) match
-- `sse_export_policy/v1`. Audit fields (`created_at_utc`, `ingested_at_utc`)
-- exist on every row for retention and importer trace.
--
-- See docs/ECOMMERCE_FACT_LAYER_PLAN.md for the full design rationale.

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    service_id TEXT,
    buyer_email TEXT NOT NULL,
    platform_id TEXT,
    campaign_id TEXT,
    currency TEXT NOT NULL,
    total_amount_cents INTEGER NOT NULL,
    placed_at_utc TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL,
    UNIQUE(tenant_id, order_id)
);

CREATE INDEX IF NOT EXISTS idx_orders_tenant_dataset_email
    ON orders (tenant_id, dataset_id, buyer_email);
CREATE INDEX IF NOT EXISTS idx_orders_tenant_placed_at
    ON orders (tenant_id, placed_at_utc);
CREATE INDEX IF NOT EXISTS idx_orders_tenant_campaign
    ON orders (tenant_id, campaign_id);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    category_id TEXT,
    quantity INTEGER NOT NULL,
    unit_price_cents INTEGER NOT NULL,
    line_total_cents INTEGER NOT NULL,
    created_at_utc TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_order_items_order_id
    ON order_items (order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_tenant_sku
    ON order_items (tenant_id, sku_id);
CREATE INDEX IF NOT EXISTS idx_order_items_tenant_category
    ON order_items (tenant_id, category_id);

CREATE TABLE IF NOT EXISTS order_attribution (
    id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    attribution_type TEXT NOT NULL,
    channel TEXT NOT NULL,
    campaign_id TEXT,
    creative_id TEXT,
    attribution_weight REAL NOT NULL,
    created_at_utc TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_order_attribution_order_id
    ON order_attribution (order_id);
CREATE INDEX IF NOT EXISTS idx_order_attribution_tenant_channel
    ON order_attribution (tenant_id, channel);

CREATE TABLE IF NOT EXISTS order_payment (
    id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    provider_id TEXT,
    paid_amount_cents INTEGER NOT NULL,
    paid_at_utc TEXT,
    risk_score REAL,
    is_disputed INTEGER NOT NULL DEFAULT 0,
    created_at_utc TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_order_payment_order_id
    ON order_payment (order_id);
CREATE INDEX IF NOT EXISTS idx_order_payment_tenant_method
    ON order_payment (tenant_id, payment_method);
CREATE INDEX IF NOT EXISTS idx_order_payment_tenant_disputed
    ON order_payment (tenant_id, is_disputed);

CREATE TABLE IF NOT EXISTS order_fulfillment (
    id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    carrier_id TEXT,
    warehouse_id TEXT,
    shipped_at_utc TEXT,
    delivered_at_utc TEXT,
    status TEXT NOT NULL,
    delivery_latency_minutes INTEGER,
    created_at_utc TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_order_fulfillment_order_id
    ON order_fulfillment (order_id);
CREATE INDEX IF NOT EXISTS idx_order_fulfillment_tenant_status
    ON order_fulfillment (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_order_fulfillment_tenant_carrier
    ON order_fulfillment (tenant_id, carrier_id);

CREATE TABLE IF NOT EXISTS customer_service_interactions (
    id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    interaction_type TEXT NOT NULL,
    channel TEXT NOT NULL,
    agent_id TEXT,
    opened_at_utc TEXT,
    closed_at_utc TEXT,
    resolution_status TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_csi_order_id
    ON customer_service_interactions (order_id);
CREATE INDEX IF NOT EXISTS idx_csi_tenant_type
    ON customer_service_interactions (tenant_id, interaction_type);
CREATE INDEX IF NOT EXISTS idx_csi_tenant_agent
    ON customer_service_interactions (tenant_id, agent_id);
