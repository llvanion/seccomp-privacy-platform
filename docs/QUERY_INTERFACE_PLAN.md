# Query Interface Plan — Seccomp Privacy Platform

## 1. Scope

Design a declarative query interface that provides "database platform" UX without bypassing privacy constraints. The interface routes queries through policy-validated paths — SSE export, bridge tokenization, PJC — depending on the query type.

## 2. Query Types (Phase 1)

Three restricted query templates cover the core use cases:

| Query Type | Path | Example |
|-----------|------|---------|
| `internal_fine_grained` | SSE export + record recovery | "Export fields X, Y, Z for campaign=demo in time range T" |
| `merchant_aggregate` | SSE export → k-anonymity-gated aggregate | "SUM(amount) GROUP BY store_id for campaign=spring_sale with k≥50" |
| `ad_collaboration` | Bridge + PJC + release | "Compute intersection of ad-exposed users and purchasers for campaign=spring_sale" |

### Phase 2: SQL / DataFusion / pgwire

When the platform matures beyond Phase 1:

- **Apache DataFusion**: SQL parser, planner, and execution engine. Extend with custom table providers that route through SSE export and bridge.
- **pgwire**: PostgreSQL wire protocol so standard SQL clients (psql, JDBC, etc.) can connect.
- **Arrow Flight SQL / ADBC**: High-performance columnar transport for BI tools.

Phase 1 explicitly does NOT implement general SQL. It implements restricted query templates that map to existing CLI paths.

## 3. Privacy Constraints (Non-Negotiable)

Every query, regardless of type, must:

1. Pass policy validation before execution
2. Route through the appropriate privacy boundary
3. Never return high-sensitivity fields in plaintext (home address, full phone, raw join keys)
4. Write audit records at every stage (`audit_chain`)
5. Respect k-anonymity thresholds for all released aggregates
6. Never bypass SSE export policy
7. Never read encrypted record stores directly without the record recovery service
8. Never expose bridge token secrets or recovery passphrases

### Query Routing Rules

```
┌─────────────────────────────────────────────────────────┐
│                   Query Submission                      │
└─────────────────────┬───────────────────────────────────┘
                      │
              ┌───────▼────────┐
              │ Policy Validate │
              └───────┬────────┘
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
  ┌──────────┐ ┌───────────┐ ┌──────────┐
  │Internal  │ │Merchant   │ │Ad        │
  │Fine-Grain│ │Aggregate  │ │Collab    │
  └────┬─────┘ └─────┬─────┘ └────┬─────┘
       │              │            │
       ▼              ▼            ▼
  ┌────────┐   ┌──────────┐  ┌───────────┐
  │SSE     │   │SSE Export│  │SSE Export │
  │Export  │   │+ k-anon  │  │+ Bridge   │
  │+ Recov.│   │Aggregate │  │+ PJC      │
  └───┬────┘   └────┬─────┘  │+ Release  │
      │             │         └─────┬─────┘
      ▼             ▼               ▼
  ┌────────────────────────────────────┐
  │        Audit Chain + Seal          │
  └────────────────────────────────────┘
```

## 4. Query Template Schema

Defined in `schemas/query_template.schema.json`. All queries use this JSON format:

```json
{
  "schema": "query_template/v1",
  "query_type": "ad_collaboration",
  "caller": "ad_partner",
  "job_id": "ad_collab_abc123",
  "ad_collaboration": {
    "server_filters": [{"field": "campaign", "value": "spring_sale"}],
    "client_filters": [{"field": "campaign", "value": "spring_sale"}],
    "join_key_field": "email",
    "value_field": "amount",
    "value_mode": "raw-int",
    "k_threshold": 20,
    "rate_limit": 5
  }
}
```

### Query type parameters

**internal_fine_grained**:
- `role`: server or client
- `fields`: allowed export fields (policy-validated)
- `filters`: field=value pairs
- `sse_keyword`: optional SSE candidate keyword
- `record_store_path`: optional encrypted record store
- `time_range`: optional time window

**merchant_aggregate**:
- `group_by_field`: grouping dimension (store_id, campaign_id)
- `metrics`: aggregation functions (count, sum, avg)
- `filters`: field=value pairs with optional operators
- `k_threshold`: minimum group size

**ad_collaboration**:
- `server_filters` / `client_filters`: per-side filter predicates
- `join_key_field` / `value_field`: join and value semantics
- `value_mode`: count or raw-int
- `k_threshold`: PJC result threshold
- `rate_limit`: caller rate limit

## 5. Usage

### Generate query templates

```bash
python3 scripts/query_adapter.py template --out-base tmp/query_templates
```

### Validate a query

```bash
python3 scripts/query_adapter.py validate \
  --query-file query_ad_collaboration.json \
  --policy-config sse/config/export_policy.example.json
```

### Submit and execute a query

```bash
export BRIDGE_TOKEN_SECRET=<secret>
python3 scripts/query_adapter.py submit \
  --query-file query_ad_collaboration.json \
  --policy-config sse/config/export_policy.example.json \
  --out-base tmp/query_run
```

### Query results

The adapter returns:
- `submitted`: whether the query was accepted
- `job_id`: the job identifier
- `path`: which pipeline path was used
- `public_report`: released aggregates (ad_collaboration path only)
- `validation`: all validation check results

## 6. Audit Trail

Every query submission produces:
1. `submission.json` — original query template (filters are hashed, not plaintext)
2. Standard pipeline audit outputs under `<out-base>/`
3. `query_result.json` — adapter execution result

## 7. Phase 2: DataFusion Integration

When the platform is ready for general SQL:

```rust
// Conceptual: DataFusion custom table provider
struct SseTableProvider {
    sse_endpoint: String,
    policy_config: PathBuf,
    caller: String,
}

impl TableProvider for SseTableProvider {
    async fn scan(&self, projection: &Option<Vec<usize>>,
                  filters: &[Expr], limit: Option<usize>)
        -> Result<Arc<dyn RecordBatch>>
    {
        // 1. Serialize query to JSON query_template
        // 2. Call scripts/query_adapter.py validate
        // 3. Route through SSE export boundary
        // 4. Return results as Arrow RecordBatch
        // 5. Write audit records
    }
}
```

And a pgwire server:

```rust
// Conceptual: pgwire server that accepts SQL, translates to query templates
async fn handle_query(sql: &str, session: &Session) -> Result<QueryResponse> {
    let plan = parse_and_validate_sql(sql)?;
    let query_template = plan_to_query_template(&plan, &session.caller)?;
    let result = call_query_adapter(&query_template).await?;
    Ok(encode_as_postgres_response(result))
}
```

## 8. Verification

```bash
# Generate and validate all template types
python3 scripts/query_adapter.py template --out-base tmp/query_templates

for t in internal_fine_grained merchant_aggregate ad_collaboration; do
  echo "=== Validating $t ==="
  python3 scripts/query_adapter.py validate \
    --query-file "tmp/query_templates/query_${t}.json" \
    --policy-config sse/config/export_policy.example.json \
    --out-base "tmp/query_validate_${t}"
done
```
