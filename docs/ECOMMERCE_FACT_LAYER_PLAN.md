# E-commerce Fact-Layer Plan (Track-E1)

This document narrows down item §4.1 of [`docs/COMPACT_PLATFORM_BRIEF.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/COMPACT_PLATFORM_BRIEF.md): the project still has no e-commerce business fact tables, only a control-plane sidecar. To deliver a credible "PJC + SSE e-commerce platform" story, the SQL surface needs an order-centric fact baseline that the privacy pipeline can target as a real source-of-truth dataset.

## 1. Intent

| What this document is | What this document is **not** |
|-----------------------|-------------------------------|
| A frozen, narrow fact-table baseline that the privacy pipeline can run cross-party joins against. | A full e-commerce data warehouse or a customer-360 product. |
| Six tables with stable column names, types, and indexes that the bridge join key (`email`) can resolve to. | A migration to a different storage engine; this is additive on top of the existing SQLite/PostgreSQL sidecar. |
| A scope the demo run (`intersection_size=2`, `intersection_sum=425`) can be re-derived from without changing the frozen pipeline contract. | A replacement for the operator-side production data warehouse. |

## 2. Tables

Migration: [`migrations/metadata/010_add_ecommerce_fact_tables.sql`](/home/llvanion/Desktop/seccomp-privacy-platform/migrations/metadata/010_add_ecommerce_fact_tables.sql).

All six tables share a common scope key set: `tenant_id`, `dataset_id`, `service_id`. Every table carries `created_at_utc` for retention, and `ingested_at_utc` for the importer-side trace.

### 2.1 `orders`

Header table. Each row is one order placed on a single platform (Tmall, Taobao, Douyin, JD, etc.).

| Column | Type | Purpose |
|--------|------|---------|
| `order_id` | TEXT PK | Stable order identifier; tenant-scoped uniqueness via `(tenant_id, order_id)`. |
| `tenant_id` / `dataset_id` / `service_id` | TEXT NOT NULL | Scope keys; align with `sse_export_policy/v1`. |
| `buyer_email` | TEXT NOT NULL | The PJC join key. The only column the bridge tokenizes. |
| `platform_id` | TEXT | Source platform (e.g. `tmall`, `douyin`). |
| `campaign_id` | TEXT | Marketing campaign identifier; matches the existing demo `campaign=demo` filter. |
| `currency` | TEXT NOT NULL | ISO 4217 currency code. |
| `total_amount_cents` | INTEGER NOT NULL | Order total in minor currency units (matches `client_value_mode=raw-int`). |
| `placed_at_utc` | TEXT NOT NULL | ISO-8601 UTC timestamp. |
| `status` | TEXT NOT NULL | `placed` / `paid` / `shipped` / `delivered` / `cancelled` / `refunded`. |
| `created_at_utc` / `ingested_at_utc` | TEXT NOT NULL | Audit fields. |

Indexes: `(tenant_id, dataset_id, buyer_email)`, `(tenant_id, placed_at_utc)`, `(tenant_id, campaign_id)`.

### 2.2 `order_items`

Line-item table for each order. Useful for sum-by-SKU privacy joins beyond the demo total.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER PK | Surrogate key. |
| `order_id` | TEXT NOT NULL | FK to `orders(order_id)` (tenant-scoped). |
| `tenant_id` / `dataset_id` | TEXT NOT NULL | Scope keys. |
| `sku_id` | TEXT NOT NULL | SKU identifier. |
| `category_id` | TEXT | Category identifier. |
| `quantity` | INTEGER NOT NULL | |
| `unit_price_cents` | INTEGER NOT NULL | |
| `line_total_cents` | INTEGER NOT NULL | Equal to `quantity * unit_price_cents` minus line-level discounts. |
| `created_at_utc` / `ingested_at_utc` | TEXT NOT NULL | |

Indexes: `(order_id)`, `(tenant_id, sku_id)`, `(tenant_id, category_id)`.

### 2.3 `order_attribution`

Marketing attribution for each order. Powers `campaign_analyst` queries.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER PK | Surrogate key. |
| `order_id` | TEXT NOT NULL | FK to `orders(order_id)`. |
| `tenant_id` / `dataset_id` | TEXT NOT NULL | Scope keys. |
| `attribution_type` | TEXT NOT NULL | `first_touch` / `last_touch` / `multi_touch`. |
| `channel` | TEXT NOT NULL | `paid_search` / `display_ads` / `social_organic` / `email` / `direct`. |
| `campaign_id` | TEXT | |
| `creative_id` | TEXT | |
| `attribution_weight` | REAL NOT NULL | 0.0–1.0; `multi_touch` rows sum to 1.0 per order. |
| `created_at_utc` / `ingested_at_utc` | TEXT NOT NULL | |

Indexes: `(order_id)`, `(tenant_id, channel)`.

### 2.4 `order_payment`

Payment record per order. Fraud queries hit this through the buyer-email → order_id link, never through PAN-like fields.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER PK | Surrogate key. |
| `order_id` | TEXT NOT NULL | FK to `orders(order_id)`. |
| `tenant_id` / `dataset_id` | TEXT NOT NULL | Scope keys. |
| `payment_method` | TEXT NOT NULL | `alipay` / `wechat_pay` / `card` / `bank_transfer` / `cod`. |
| `provider_id` | TEXT | Acquirer / wallet identifier. |
| `paid_amount_cents` | INTEGER NOT NULL | |
| `paid_at_utc` | TEXT | |
| `risk_score` | REAL | Provider-side fraud score, 0.0–1.0; nullable. |
| `is_disputed` | INTEGER NOT NULL DEFAULT 0 | 0 / 1. |
| `created_at_utc` / `ingested_at_utc` | TEXT NOT NULL | |

Indexes: `(order_id)`, `(tenant_id, payment_method)`, `(tenant_id, is_disputed)`.

### 2.5 `order_fulfillment`

Logistics / fulfillment record per order. Powers `commerce_ops_owner` queries about delivery latency without ever exposing courier PII.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER PK | Surrogate key. |
| `order_id` | TEXT NOT NULL | FK to `orders(order_id)`. |
| `tenant_id` / `dataset_id` | TEXT NOT NULL | Scope keys. |
| `carrier_id` | TEXT | Logistics provider identifier. |
| `warehouse_id` | TEXT | Origin warehouse identifier. |
| `shipped_at_utc` / `delivered_at_utc` | TEXT | Lifecycle timestamps. |
| `status` | TEXT NOT NULL | `picking` / `shipped` / `in_transit` / `delivered` / `returned`. |
| `delivery_latency_minutes` | INTEGER | Derived; nullable for in-progress orders. |
| `created_at_utc` / `ingested_at_utc` | TEXT NOT NULL | |

Indexes: `(order_id)`, `(tenant_id, status)`, `(tenant_id, carrier_id)`.

### 2.6 `customer_service_interactions`

Customer-service tickets per order. Stays at metadata level — actual transcripts are NOT stored.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER PK | Surrogate key. |
| `order_id` | TEXT NOT NULL | FK to `orders(order_id)`. |
| `tenant_id` / `dataset_id` | TEXT NOT NULL | Scope keys. |
| `interaction_type` | TEXT NOT NULL | `complaint` / `inquiry` / `refund_request` / `delivery_issue` / `praise`. |
| `channel` | TEXT NOT NULL | `chat` / `voice` / `email` / `social`. |
| `agent_id` | TEXT | Internal agent identifier; never the agent's PII. |
| `opened_at_utc` / `closed_at_utc` | TEXT | |
| `resolution_status` | TEXT NOT NULL | `open` / `resolved` / `escalated` / `dropped`. |
| `created_at_utc` / `ingested_at_utc` | TEXT NOT NULL | |

Indexes: `(order_id)`, `(tenant_id, interaction_type)`, `(tenant_id, agent_id)`.

## 3. PJC + SSE Story Anchors

The fact tables exist so the demo expected result can be traced end-to-end:

1. **SSE export** queries `orders.buyer_email` for a given `(tenant_id, dataset_id, campaign_id)` slice → returns the same candidate set the existing demo emits.
2. **Bridge** tokenizes `buyer_email`; `orders.total_amount_cents` is the value field for `--client-value-mode raw-int`.
3. **PJC** intersects the two parties' tokenized buyer sets and sums `total_amount_cents` → `intersection_size=2 / intersection_sum=425` is reproducible against the synthetic seeded fixture in `sse/examples/bridge_*.jsonl`.
4. **Policy release** still produces `public_report/v1` exactly as today; the fact layer changes nothing on the privacy boundary.

## 4. Privacy Boundary (unchanged)

- The bridge boundary still only sees `(buyer_email, total_amount_cents)`. Every other column stays inside the tenant DB.
- `sse_export_policy/v1`'s `allowed_dataset_ids` and `allowed_service_ids` continue to gate access. The fact layer does not introduce a new authz path.
- No fact-layer column is exported through the audit chain; only join-key tokens, hash digests, and intersection metadata are sealed. The fact rows themselves stay tenant-side.

## 5. Validation Surface

[`scripts/render_ecommerce_fact_layer.py`](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/render_ecommerce_fact_layer.py) parses migration `010_*.sql`, asserts the six expected tables and their primary indexes, and emits `ecommerce_fact_layer_report/v1` (frozen schema). Default contract smoke validates that report so the fact-layer baseline cannot drift silently.

[`scripts/validate_ecommerce_fact_import.py`](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/validate_ecommerce_fact_import.py) validates candidate JSONL fact imports before rows are loaded. It checks the table-specific column allowlist, required columns, basic types, non-negative monetary fields, `business_access_policy/v1` field classification, and a denylist for unsupported sensitive column names such as address, phone, raw transcript, full route, card/account, and geo/postal fields. `orders.buyer_email` remains allowed only as the classified/protected join key. The smoke script [`scripts/check_ecommerce_fact_import_validation.py`](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/check_ecommerce_fact_import_validation.py) freezes one valid import and three rejects: hidden address, negative amount, and raw support transcript.

[`scripts/import_ecommerce_fact_rows.py`](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/import_ecommerce_fact_rows.py) is the repo-side validator-first importer. It applies metadata migrations, reuses the same validation report, inserts allowed JSONL batches in one transaction, rejects denied batches before insert, and rolls back database-level failures such as duplicate `orders(tenant_id, order_id)` rows. [`scripts/check_ecommerce_fact_import.py`](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/check_ecommerce_fact_import.py) proves all three outcomes and emits `ecommerce_fact_import_smoke/v1`.

## 6. Out of Scope (Phase-2 follow-up)

These are deliberately *not* in the current baseline; they are flagged here so a future tranche can pick them up coherently:

1. Buyer-side personal profile (real PII, name, address). The existing privacy boundary is exactly what makes the demo legal; we do not add a PII column unless the privacy story handles it.
2. Inventory / stock movement tables.
3. Real-time event stream feeding the fact layer (Kafka, Debezium). The current expectation is batch import only.
4. Vendor / merchant master data — the `ECOMMERCE_BUSINESS_IDENTITIES_PLAN.md` (E2) covers identities, not catalog.
5. Production ETL/event-stream wiring. The repo now has a validator-first batch importer, but external warehouse jobs, Kafka/Debezium flows, or managed ETL systems must call it or enforce an equivalent policy gate before writing rows.

## 7. Operator Onboarding

```bash
# 1. Apply the migration on top of an existing sidecar.
python3 scripts/init_metadata_db.py --db tmp/metadata.sqlite

# 2. Validate the fact-layer baseline.
python3 scripts/render_ecommerce_fact_layer.py --output tmp/ecommerce_fact_layer_report.json

# 3. Validate candidate fact imports.
python3 scripts/check_ecommerce_fact_import_validation.py --out-dir tmp/ecommerce_fact_import_validation

# 4. Run the validator-first transactional importer smoke.
python3 scripts/check_ecommerce_fact_import.py --out-dir tmp/ecommerce_fact_import_smoke

# 5. Import a candidate JSONL file into a metadata DB.
python3 scripts/import_ecommerce_fact_rows.py \
  --table orders \
  --input tmp/ecommerce_fact_import_smoke/orders_allow.jsonl \
  --metadata-db tmp/metadata.sqlite \
  --output tmp/orders_import_result.json

# 6. Validate against the schemas.
python3 scripts/validate_json_contract.py \
  --schema schemas/ecommerce_fact_layer_report.schema.json \
  --json tmp/ecommerce_fact_layer_report.json
python3 scripts/validate_json_contract.py \
  --schema schemas/ecommerce_fact_import_validation.schema.json \
  --json tmp/ecommerce_fact_import_validation/orders_good_report.json
python3 scripts/validate_json_contract.py \
  --schema schemas/ecommerce_fact_import_result.schema.json \
  --json tmp/orders_import_result.json
```
