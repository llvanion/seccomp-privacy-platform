# Production Readiness Guidebook
# SSE + PJC E-Commerce Privacy Platform

**Date:** 2026-05-05  
**Status:** Post-baseline complete. This guidebook covers everything between "demo baseline" and "production platform."

---

## 1. How to Read This Document

### 1.1 Platform State Today

The current codebase is a fully working, contract-frozen, demo-scale privacy pipeline:

```
SSE export → record recovery (mTLS) → bridge (Rust) → PJC/APSI → policy release
```

All contracts are frozen (88 schemas with backcompat guard). All post-baseline tranches A–D are complete. The gap is that every authority source is a local adapter:

| Component | Current State | Production Gap |
|-----------|--------------|----------------|
| Keycloak / OIDC | HS256 claim mapper, static token map | No real OIDC server; no RS256 asymmetric signing |
| OpenFGA | Local SQLite `openfga_tuples` table | Not connected to real OpenFGA service |
| Vault / KMS | File-based KV compatibility layer | No real Vault; no cloud KMS |
| mTLS PKI | Manually generated self-signed certs | No cert automation or rotation |
| PostgreSQL | SQLite sidecar with Postgres-compatible DDL | No live PostgreSQL connection |
| Benchmarks | Synthetic demo data (`intersection_size=2`) | Never tested at e-commerce scale |
| External audit anchor | Local file ledger | Not connected to immutable external medium |

### 1.2 Notation

- **1 block = ~5h** of focused implementation + verification + doc write-back.
- **Dependency arrows**: some blocks in E/F are prerequisites for meaningful G benchmarks.
- **Frozen fields** that must not change under any circumstances: `job_id`, `correlation_id`, `caller`, `tenant_id`, `dataset_id`, `service_id`, `token_scope`, `token_key_version`, `record_recovery_boundary`, `policy_id`.
- When a change would touch a frozen contract, file a change request under `docs/change_requests/` and follow `INTERFACE_FREEZE_AND_CHANGE_PROCESS.md`.

### 1.3 Recommended Execution Order

```
E1 → E2 → E3 (authority sources first — prerequisites for meaningful G)
F1 → F2 → F3 (PostgreSQL migration, parallel with E)
G1–G6 (start after E1+F1 are at least smoke-tested)
H1–H3 (parallel with G)
I1–I2 (after G, after E1)
J1–J4 (after F2)
K1–K3 (after J)
```

---

## 2. Category E — Real Authority Sources

**Goal:** Replace all local adapter shims with real, running authority services. The main chain must still be able to run without these services (adapter-first principle), but the platform's identity and key resolution must not depend on static env tokens or file-backed KV in any non-demo environment.

**Total: ~12 blocks / ~60h**

---

### E1 — Real Keycloak OIDC Integration (3 blocks / 15h)

#### Current Baseline

- `scripts/map_oidc_claims.py`: parses HS256 JWT with configurable `claim_mapping` (dotted-path extraction, e.g., `realm_access.roles`).
- `migrations/metadata/006_add_issuer_registry.sql`: `issuer_registry` table stores `issuer_type`, `display_name`, `service_id`, `jwks_uri`, `token_endpoint`, `claim_mapping_json`, `trusted_audiences_json`.
- `scripts/api_identity.py`: resolves `issuer + subject → caller_identities → caller/tenant_id/platform_roles`.
- `config/oidc_claim_mapping.example.json`: Keycloak realm claim mapping example.
- `scripts/rotate_issuer_credentials.py`: dry-run issuer credential rotation via `issuer_registry`.

#### Gap

- Token signing is HS256 with shared secret. Keycloak uses RS256 asymmetric signing; `map_oidc_claims.py` does not fetch JWKS from `jwks_uri`.
- No real Keycloak realm, clients, or service accounts exist.
- `caller_identities.issuer` / `subject` are populated from static manifest, not from a live token flow.

#### Tasks

**E1-a — Deploy Keycloak (1 block)**

```bash
# Docker Compose (local dev)
docker run -d --name keycloak \
  -p 8080:8080 \
  -e KEYCLOAK_ADMIN=admin \
  -e KEYCLOAK_ADMIN_PASSWORD=admin \
  quay.io/keycloak/keycloak:latest start-dev
```

Realm configuration (via Admin UI or `kcadm.sh`):

1. Create realm: `seccomp-privacy`.
2. Create realm roles: `platform_admin`, `platform_auditor`, `privacy_operator`, `query_submitter`, `service_operator`.
3. Create clients:
   - `metadata-api` (confidential, service account enabled) → maps to `service_id: metadata`
   - `query-workflow-api` (confidential)
   - `recovery-service` (confidential) → maps to `service_id: bridge-demo-recovery`
   - `key-agent` (confidential)
4. Map `realm_access.roles` claim into tokens (already the default in Keycloak).
5. Create test users and assign roles.

Register the realm in the metadata DB:

```bash
python3 scripts/manage_metadata_db.py apply-registry \
  --db-path tmp/platform_metadata.db \
  --manifest config/metadata_registry.example.json
```

Add an `issuer_registry` entry for the new realm:

```json
{
  "issuer_type": "keycloak",
  "display_name": "seccomp-privacy realm",
  "service_id": "keycloak-seccomp",
  "jwks_uri": "http://localhost:8080/realms/seccomp-privacy/protocol/openid-connect/certs",
  "token_endpoint": "http://localhost:8080/realms/seccomp-privacy/protocol/openid-connect/token",
  "claim_mapping": {
    "caller": "preferred_username",
    "tenant_id": "tenant_id",
    "platform_roles": "realm_access.roles"
  },
  "trusted_audiences": ["metadata-api", "query-workflow-api"]
}
```

**E1-b — Switch map_oidc_claims.py to RS256 / JWKS (1 block)**

Current: `map_oidc_claims.py` verifies HS256 using shared secret.  
Required change: When `issuer_registry.jwks_uri` is non-empty, fetch the JWKS and verify with the matching RS256 public key.

```python
# In scripts/map_oidc_claims.py
import urllib.request, json as _json

def fetch_jwks(jwks_uri: str) -> dict:
    with urllib.request.urlopen(jwks_uri, timeout=5) as r:
        return _json.loads(r.read())

def verify_rs256(token: str, jwks: dict) -> dict:
    # Use PyJWT or cryptography library to verify RS256
    # Select key by kid header
    ...
```

Add `--jwks-uri` flag to `map_oidc_claims.py`; when present, skip HS256 and use RS256. Add `PyJWT>=2.0` and `cryptography` to requirements.

Update `config/oidc_claim_mapping.example.json` to include a `jwks_uri` field.

Add a new contract smoke assertion that JWKS-backed resolution produces a valid `oidc_claim_map/v1`.

**E1-c — Wire service accounts end-to-end (1 block)**

For each service that accepts `--identity-token-config`:

1. Recovery service: use Keycloak client credentials flow to obtain a service account token; pass via `--record-recovery-identity-auth-env`.
2. Key agent: wire `--identity-token-config` to real issuer.
3. Metadata API: verify that `GET /v1/identity` resolves a real Keycloak token to the correct `caller`.

Run the full authority governance smoke with a real Keycloak token:

```bash
python3 scripts/check_authority_governance.py \
  --identity-resolution tmp/api_identity_resolution_keycloak.json \
  ... \
  --assert-ok
```

#### Acceptance Criteria

1. `map_oidc_claims.py --jwks-uri <realm-jwks-url>` verifies a real Keycloak RS256 token and produces `oidc_claim_map/v1`.
2. `resolve_api_identity.py --bearer-token-env KEYCLOAK_TOKEN` resolves a real token to `caller + tenant_id + platform_roles`.
3. `check_authority_governance.py --assert-ok` passes with a real Keycloak token as the identity source.
4. No frozen field semantics change.

---

### E2 — Real OpenFGA Service (3 blocks / 15h)

#### Current Baseline

- `scripts/sync_openfga_tuples.py`: dry-run / apply / reconcile modes; writes to local SQLite `openfga_tuples` table (migration 007).
- `scripts/check_openfga_authz.py`: queries the same SQLite table; outputs `openfga_check_result/v1`.
- `schemas/openfga_sync_report.schema.json`, `schemas/openfga_check_result.schema.json`.
- The authorization model draft is in `TASK_ENGINEER_A_CONTROL_PLANE_IDENTITY_ACCESS.md` §9.

#### Gap

- Both scripts talk to a local SQLite store, not an OpenFGA service.
- The authorization model (FGA model definition) has never been uploaded to a real OpenFGA instance.

#### Tasks

**E2-a — Deploy OpenFGA and upload authorization model (1 block)**

```bash
docker run -d --name openfga \
  -p 8080:8080 \
  -p 8081:8081 \
  openfga/openfga run
```

Create a store and upload the authorization model:

```bash
# Create store
curl -X POST http://localhost:8080/stores \
  -H "Content-Type: application/json" \
  -d '{"name": "seccomp-privacy"}'

# Upload model (translate the draft from TASK_ENGINEER_A doc into JSON DSL)
curl -X POST http://localhost:8080/stores/<store-id>/authorization-models \
  -H "Content-Type: application/json" \
  -d @config/openfga_authorization_model.json
```

Create `config/openfga_authorization_model.json` from the §9 draft:

```json
{
  "type_definitions": [
    {"type": "user", "relations": {}},
    {"type": "service_account", "relations": {}},
    {"type": "tenant", "relations": {
      "admin": {"this": {}},
      "auditor": {"this": {}}
    }},
    {"type": "dataset", "relations": {
      "owner": {"this": {}},
      "reader": {"this": {}},
      "recovery_allowed": {"this": {}}
    }},
    {"type": "privacy_service", "relations": {
      "operator": {"this": {}},
      "can_recover": {"computedUserset": {"object": "", "relation": "recovery_allowed"}}
    }},
    {"type": "job", "relations": {
      "owner": {"this": {}},
      "viewer": {"this": {}}
    }}
  ]
}
```

**E2-b — Add OpenFGA HTTP backend to sync and check scripts (1 block)**

Add `--openfga-endpoint <url>` and `--openfga-store-id <id>` flags to both scripts.

When `--openfga-endpoint` is provided:
- `sync_openfga_tuples.py apply`: call `POST /stores/<id>/write` (Write API) instead of writing to SQLite.
- `sync_openfga_tuples.py reconcile`: call `POST /stores/<id>/read` (Read API) to get current tuples, diff, then Write/Delete.
- `check_openfga_authz.py`: call `POST /stores/<id>/check` (Check API) instead of querying SQLite.

Keep the SQLite path as the default for CI (no live service dependency).

Add `config/openfga.example.json` to record store ID and endpoint:

```json
{
  "schema": "openfga_config/v1",
  "endpoint": "http://localhost:8080",
  "store_id": "<store-id>",
  "authorization_model_id": "<model-id>"
}
```

**E2-c — Wire OpenFGA into authority governance smoke (1 block)**

Update `check_authority_governance.py` to accept `--openfga-config config/openfga.example.json` and perform a live Check against the real service. The existing `--openfga-check` file path remains as a fallback.

Add a new contract smoke variant that runs against a real OpenFGA instance (gated by `OPENFGA_ENDPOINT` env var; skipped if not set).

#### Acceptance Criteria

1. `sync_openfga_tuples.py --openfga-endpoint ... apply` writes tuples to a real OpenFGA store.
2. `check_openfga_authz.py --openfga-endpoint ... --assert-allowed` passes against a live Check.
3. `check_authority_governance.py --assert-ok` works with real OpenFGA as the authz source.
4. CI still passes without `OPENFGA_ENDPOINT` set (SQLite fallback).

---

### E3 — Real Vault / Cloud KMS Integration (4 blocks / 20h)

#### Current Baseline

- `scripts/vault_http_client.py`: real mode (HTTP) and mock mode (local `vault_kv_backend` file); `keyring_lib.py` supports `secret_ref.kind=vault_http`.
- `scripts/external_kms_service.py`, `scripts/manage_external_kms.py`: support Vault KV references.
- `scripts/rotate_issuer_credentials.py`: rotation writes new version to `key_refs`.
- `config/vault_http_client.example.json`, `config/vault_kv_backend.example.json`.

#### Gap

- All CI smoke uses mock mode (local file). Real Vault has never been connected.
- `vault_http_client.py` uses a static `vault_token` (root token equivalent). Production needs AppRole or Kubernetes auth.
- No cloud KMS (AWS KMS / GCP KMS) adapter.

#### Tasks

**E3-a — Deploy Vault in dev mode and test real-mode client (1 block)**

```bash
docker run -d --name vault \
  --cap-add=IPC_LOCK \
  -p 8200:8200 \
  -e VAULT_DEV_ROOT_TOKEN_ID=dev-root-token \
  hashicorp/vault server -dev
```

Initialize KV v2 and create test secrets:

```bash
export VAULT_ADDR=http://localhost:8200
export VAULT_TOKEN=dev-root-token
vault secrets enable -path=secret kv-v2
vault kv put secret/bridge-token value=my-bridge-secret
vault kv put secret/recovery-token value=my-recovery-secret
```

Test `vault_http_client.py` in real mode:

```bash
export VAULT_TOKEN=dev-root-token
python3 scripts/vault_http_client.py \
  --config config/vault_http_client.example.json \
  --secret-path secret/bridge-token \
  --field value
```

Verify `vault_http_client_result/v1` output.

**E3-b — Replace root token with AppRole auth (1 block)**

AppRole allows each service to authenticate with a role ID and secret ID rather than a root token.

```bash
vault auth enable approle
vault write auth/approle/role/bridge-service \
  token_policies="bridge-policy" \
  token_ttl=1h \
  token_max_ttl=4h
vault read auth/approle/role/bridge-service/role-id
vault write -f auth/approle/role/bridge-service/secret-id
```

Update `vault_http_client.py`:

```python
def _approle_login(config: dict) -> str:
    role_id = os.environ.get(config["approle_role_id_env"])
    secret_id = os.environ.get(config["approle_secret_id_env"])
    response = _http_post(f"{config['vault_addr']}/v1/auth/approle/login",
                          {"role_id": role_id, "secret_id": secret_id})
    return response["auth"]["client_token"]
```

Add `approle_role_id_env` and `approle_secret_id_env` fields to `vault_http_client_config/v1` schema (alongside existing `vault_token_env`). Token caching with TTL-aware refresh.

**E3-c — Vault PKI for mTLS certificate issuance (1 block)**

Replace the manual `openssl` cert generation workflow with Vault PKI:

```bash
vault secrets enable pki
vault secrets tune -max-lease-ttl=87600h pki
vault write pki/root/generate/internal common_name="seccomp-ca" ttl=87600h
vault write pki/roles/recovery-service \
  allowed_domains="localhost,127.0.0.1" \
  allow_ip_sans=true \
  max_ttl=720h

# Issue a cert
vault write pki/issue/recovery-service common_name="127.0.0.1" ip_sans="127.0.0.1" ttl=720h
```

Create `scripts/issue_mtls_certs.py`:
- Calls Vault PKI issue endpoint.
- Writes `server.crt`, `server.key`, `ca.crt` to `tmp/mtls/`.
- Optionally writes client cert.
- Outputs a `mtls_cert_issue_report/v1` JSON.

Wire into `manage_record_recovery_service.py start` via `--vault-pki-config`.

**E3-d — Cloud KMS adapter baseline (AWS KMS or GCP KMS) (1 block)**

For cloud deployments, add a `secret_ref.kind=aws_kms` or `secret_ref.kind=gcp_kms` path to `keyring_lib.py`.

AWS KMS example:

```python
def resolve_aws_kms(secret_ref: dict) -> str:
    import boto3
    client = boto3.client("kms", region_name=secret_ref["region"])
    response = client.decrypt(
        CiphertextBlob=base64.b64decode(secret_ref["ciphertext_b64"]),
        KeyId=secret_ref["key_id"],
    )
    return response["Plaintext"].decode()
```

Add `secret_ref.kind=aws_kms` to `schemas/keyring.schema.json`. Keep Vault as the primary path; cloud KMS as an alternative for organizations without a Vault deployment.

#### Acceptance Criteria

1. `vault_http_client.py` in real mode resolves a secret from a live Vault instance using AppRole auth.
2. `check_kms_reachability.py` reports `overall_status=ok` against a real Vault endpoint.
3. `rotate_issuer_credentials.py` writes a new key version to Vault KV and the `key_refs` sidecar.
4. `issue_mtls_certs.py` issues a valid server cert from Vault PKI and the recovery service starts with it.
5. CI still passes without a real Vault (mock mode fallback).

---

## 3. Category F — Production PostgreSQL

**Goal:** Migrate the metadata sidecar from SQLite to a production-grade PostgreSQL instance, with HA, connection pooling, and automated backup.

**Total: ~8 blocks / ~40h**

---

### F1 — SQLite → PostgreSQL Driver Layer (2 blocks / 10h)

#### Current Baseline

- All metadata scripts use `sqlite3` (Python stdlib).
- `migrations/postgres/001_init.sql` has the complete Postgres-compatible DDL (SERIAL, TIMESTAMPTZ, JSONB, BOOLEAN, indexes).
- `scripts/check_metadata_schema_portability.py` validates DDL is Postgres-compatible.
- `scripts/export_postgres_ddl.py` exports the target DDL.

#### Tasks

**F1-a — Add psycopg2 backend to metadata DB layer (1 block)**

Introduce a thin DB abstraction in a new module `scripts/metadata_db.py`:

```python
import os, sqlite3
try:
    import psycopg2
    _PSYCOPG2 = True
except ImportError:
    _PSYCOPG2 = False

def connect(db_path: str = "", dsn: str = "") -> "Connection":
    if dsn:
        if not _PSYCOPG2:
            raise RuntimeError("psycopg2 is required for PostgreSQL; pip install psycopg2-binary")
        return psycopg2.connect(dsn)
    return sqlite3.connect(db_path)
```

Add `--db-dsn postgresql://user:password@host:5432/dbname` to:
- `scripts/init_metadata_db.py`
- `scripts/import_run_metadata.py`
- `scripts/query_metadata.py`
- `scripts/manage_metadata_db.py`
- `scripts/serve_metadata_api.py`
- `scripts/serve_query_workflow_api.py`
- `scripts/serve_audit_query_api.py`

When `--db-dsn` is provided: use psycopg2; use `%s` placeholders instead of `?`; use `RETURNING` for inserts.

**F1-b — Run portability gate against real PostgreSQL (1 block)**

```bash
# Start PostgreSQL
docker run -d --name pg-test \
  -e POSTGRES_PASSWORD=test \
  -p 5432:5432 postgres:16

# Apply the target DDL
psql postgresql://postgres:test@localhost:5432/postgres \
  -f migrations/postgres/001_init.sql

# Apply all metadata migrations (ported to PostgreSQL syntax)
# migrations/metadata/001_init.sql through 009 need PostgreSQL-compatible versions

# Run portability gate against real PostgreSQL
python3 scripts/check_metadata_schema_portability.py \
  --db-dsn postgresql://postgres:test@localhost:5432/postgres \
  --output tmp/pg_portability_report.json
```

Port any remaining SQLite-specific syntax (especially `AUTOINCREMENT` → `SERIAL`, `PRAGMA` statements removed, `INTEGER PRIMARY KEY` → `SERIAL PRIMARY KEY`).

Add a CI gate that runs the portability check against a PostgreSQL container if `POSTGRES_DSN` env var is set.

#### Acceptance Criteria

1. All 9 metadata migrations apply cleanly to PostgreSQL 16.
2. `init_metadata_db.py --db-dsn ...` initializes a PostgreSQL schema without errors.
3. `import_run_metadata.py --db-dsn ...` imports a pipeline run into PostgreSQL.
4. `query_metadata.py --db-dsn ... --job-id auto_demo_job` returns the same result as the SQLite path.
5. All existing contract smoke passes with `--db-path` (SQLite remains default).

---

### F2 — HA PostgreSQL Deployment (3 blocks / 15h)

#### Tasks

**F2-a — Primary + replica setup (1 block)**

```yaml
# docker-compose.yml (development HA)
services:
  pg-primary:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: primary_pass
      POSTGRES_REPLICATION_USER: replicator
      POSTGRES_REPLICATION_PASSWORD: repl_pass
    command: >
      postgres
        -c wal_level=replica
        -c max_wal_senders=3
        -c wal_keep_size=64
    ports: ["5432:5432"]

  pg-replica:
    image: postgres:16
    environment:
      PGUSER: replicator
      PGPASSWORD: repl_pass
    command: >
      bash -c "
        pg_basebackup -h pg-primary -D /var/lib/postgresql/data -U replicator -P -Xs -R
        postgres
      "
    depends_on: [pg-primary]
    ports: ["5433:5432"]
```

Verify replication lag with:

```sql
SELECT client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn
FROM pg_stat_replication;
```

**F2-b — Patroni automated failover (1 block)**

Add Patroni cluster config (`config/patroni.yml`):

```yaml
scope: seccomp-privacy
name: pg-primary

restapi:
  listen: 0.0.0.0:8008
  connect_address: pg-primary:8008

etcd3:
  hosts: etcd:2379

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576
  pg_hba:
    - host replication replicator 0.0.0.0/0 md5
    - host all all 0.0.0.0/0 md5

postgresql:
  listen: 0.0.0.0:5432
  connect_address: pg-primary:5432
  data_dir: /var/lib/postgresql/data
  authentication:
    replication:
      username: replicator
      password: repl_pass
    superuser:
      username: postgres
      password: primary_pass
```

Add a runbook section in `OPS_RUNBOOK.md` for Patroni failover commands:

```bash
patronictl -c config/patroni.yml list
patronictl -c config/patroni.yml switchover
patronictl -c config/patroni.yml failover
```

**F2-c — Read-replica routing for sidecar reads (1 block)**

For `query_metadata.py`, `serve_metadata_api.py`, `serve_audit_query_api.py` (read-only): route to the replica DSN. For `import_run_metadata.py`, `manage_metadata_db.py` (write): use the primary DSN.

Add `--db-dsn-read-replica` flag to read-only scripts. When set, use it for SELECT queries; fall back to `--db-dsn` for writes.

#### Acceptance Criteria

1. Primary + replica replication verified with `pg_stat_replication`.
2. Patroni failover completes in < 30 seconds (switchover test).
3. Sidecar read scripts work against the replica DSN.
4. Contract smoke passes against both primary and replica DSNs.

---

### F3 — Connection Pooling (1 block / 5h)

#### Tasks

Deploy pgBouncer in front of PostgreSQL:

```ini
# pgbouncer.ini
[databases]
seccomp_metadata = host=pg-primary port=5432 dbname=postgres

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
pool_mode = transaction
max_client_conn = 200
default_pool_size = 20
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt
```

Update all scripts to use `--db-dsn postgresql://user:pass@pgbouncer:6432/seccomp_metadata`.

For write operations that use transactions longer than a single statement (e.g., `apply-registry`), use session-mode pooling or connect directly to the primary.

#### Acceptance Criteria

1. pgBouncer reports pool utilization under load.
2. `benchmark_read_adapters.py` latency is within 20% of direct connection baseline.

---

### F4 — Backup Automation (2 blocks / 10h)

#### Tasks

**F4-a — WAL archiving + daily pg_dump (1 block)**

```bash
# WAL archiving to local archive (extend to S3/GCS in production)
postgresql.conf:
  archive_mode = on
  archive_command = 'cp %p /var/lib/postgresql/archive/%f'

# Daily logical backup
pg_dump postgresql://postgres:pass@localhost:5432/postgres \
  --format=custom \
  --file=/var/backups/seccomp_metadata_$(date +%Y%m%d).dump
```

Create `scripts/backup_metadata_db.py` that:
- Issues `pg_dump` via subprocess.
- Verifies the dump with `pg_restore --list`.
- Emits `metadata_db_backup/v1` (reuse existing schema, add `backend` field for `postgres`).
- Optionally uploads to S3 with `boto3`.

**F4-b — Restore runbook and automation (1 block)**

Create `scripts/restore_metadata_db.py`:
- Downloads backup from S3 (optional).
- Issues `pg_restore` to a new database.
- Runs `check_metadata_schema_portability.py` against the restored DB.
- Emits `metadata_db_restore/v1`.

Add PostgreSQL restore steps to `OPS_RUNBOOK.md > Failure Recovery Decision Tree`.

#### Acceptance Criteria

1. Daily backup script runs without error.
2. Restore from backup produces a queryable database.
3. `check_metadata_schema_portability.py` passes against the restored DB.

---

## 4. Category G — Scale & Optimization

**Goal:** Validate that the platform can handle real e-commerce volumes. Current benchmarks use demo data (`intersection_size=2`). Production e-commerce involves millions of orders, thousands of candidate IDs per privacy query, and concurrent multi-tenant job execution.

**Prerequisite:** E1 (real tokens) and F1 (PostgreSQL) should be smoke-tested before G results are meaningful.

**Total: ~10 blocks / ~50h**

---

### G1 — SSE Export Throughput at Scale (1 block / 5h)

#### Current Baseline

`sse/run_client.py export-bridge-records` exports encrypted order records to a JSONL. Performance has only been tested with demo-size datasets.

#### Tasks

Generate a synthetic 1M-record e-commerce dataset:

```python
# scripts/generate_benchmark_dataset.py
import json, random, uuid
from pathlib import Path

def generate_order_record(i: int) -> dict:
    return {
        "order_id": f"ORD-{i:08d}",
        "customer_id": f"CUST-{random.randint(1, 500000):07d}",
        "merchant_id": f"MERCH-{random.randint(1, 10000):05d}",
        "amount_cents": random.randint(100, 1000000),
        "status": random.choice(["completed", "refunded", "pending"]),
        "created_at": f"2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
    }
```

Profile the SSE export with `cProfile`:

```bash
python3 -m cProfile -o tmp/sse_export_profile.pstats \
  sse/.venv/bin/python sse/run_client.py export-bridge-records \
  --record-store-path tmp/benchmark_records.enc.jsonl \
  --record-store-key-env SSE_RECORD_STORE_PASSPHRASE \
  ...

python3 -m pstats tmp/sse_export_profile.pstats
```

Measure:
- Records exported per second at 10k, 100k, 1M records.
- Peak memory usage (`/usr/bin/time -v`).
- Bottleneck function (typically the encrypted store read loop).

Optimization candidates:
- Chunked streaming: avoid loading all records into memory before filtering.
- Batch AES-GCM decryption (reuse cipher context per chunk).
- Output buffering: increase `io.BufferedWriter` buffer size.

Add a new benchmark target to `benchmark_smoke.py`:

```bash
python3 scripts/benchmark_smoke.py --target sse-export-scale --scale 100000
```

#### Acceptance Criteria

1. SSE export of 100k records completes in < 60s.
2. Peak memory stays below 2 GB for 1M records.
3. Benchmark report emitted as `sse_export_benchmark/v1`.

---

### G2 — Record Recovery Throughput (2 blocks / 10h)

#### Current Baseline

`scripts/benchmark_record_recovery.py` measures health + recover operations but with a tiny synthetic record store (2 rows).

#### Tasks

**G2-a — Large candidate set benchmark (1 block)**

Extend `benchmark_record_recovery.py` with `--candidate-count` flag:

```bash
python3 scripts/benchmark_record_recovery.py \
  --mode all \
  --candidate-count 1000 \
  --iterations 10 \
  --output tmp/recovery_benchmark_1k.json

python3 scripts/benchmark_record_recovery.py \
  --candidate-count 10000 \
  --iterations 5 \
  --output tmp/recovery_benchmark_10k.json
```

Measure: throughput (requests/s), p50/p95/p99 latency, memory on the server side.

The benchmark must create a proportionally sized encrypted record store:

```python
def generate_record_store(candidate_count: int, path: Path) -> None:
    # Write candidate_count records with known join_key_field values
    ...
```

**G2-b — Concurrent request benchmark (1 block)**

Test `ThreadingHTTPServer` under concurrent load:

```bash
python3 scripts/benchmark_record_recovery.py \
  --mode concurrent \
  --concurrency 10 \
  --candidate-count 1000 \
  --iterations 20 \
  --output tmp/recovery_concurrent_10.json
```

Implement using `concurrent.futures.ThreadPoolExecutor`. Measure:
- Throughput degradation vs sequential baseline.
- Whether `--max-rows-per-request` provides a meaningful safety valve under concurrency.
- mTLS handshake overhead (compare plain HTTP vs HTTPS with `--tls-cert-file`).

If TLS handshake dominates: enable HTTP/1.1 keep-alive in `RecordRecoveryHttpServer` (`server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)` + `allow_reuse_address = True` is already set; also add `Connection: keep-alive` response header).

#### Acceptance Criteria

1. 1k candidate set: p95 latency < 500ms for a single-threaded request.
2. 10 concurrent requests with 1k candidates each: throughput > 5 req/s.
3. mTLS overhead < 20ms additional p95 latency vs plain HTTP.

---

### G3 — Bridge Binary Profiling (1 block / 5h)

#### Current Baseline

`bridge/` is a Rust binary. Tested with `bridge/out/sse_demo_job/server.csv` (2 rows).

#### Tasks

Generate large bridge input CSVs:

```bash
python3 scripts/generate_benchmark_dataset.py \
  --output-format bridge-csv \
  --server-rows 100000 \
  --client-rows 100000 \
  --overlap 0.3
```

Profile with `cargo flamegraph`:

```bash
cd bridge
cargo install flamegraph
cargo flamegraph --bin bridge -- prepare-job \
  --server-csv /tmp/server_100k.csv \
  --client-csv /tmp/client_100k.csv \
  --job-id bench-job \
  --out /tmp/bridge_bench_out
```

Measure: wall time, peak RSS, throughput (rows/s). Compare 1k / 10k / 100k / 1M row inputs.

Optimization candidates (do not change the bridge contract):
- Check if CSV parsing is the bottleneck (consider switching to a faster CSV reader).
- Verify that `HMAC-SHA256` token operations are batched or if there is per-row overhead.
- Ensure `--production-mode` is used (no debug logging paths).

#### Acceptance Criteria

1. 100k-row bridge job completes in < 120s.
2. Flame graph identifies the top-3 CPU hot spots.
3. No change to any frozen bridge contract field or CLI argument.

---

### G4 — PJC / APSI Profiling at Scale (2 blocks / 10h)

#### Current Baseline

`a-psi/moduleA_psi/scripts/run_pjc.sh` runs APSI intersection. Tested with 2-item overlap.

#### Tasks

**G4-a — Intersection size scaling (1 block)**

Generate synthetic server/client sets:

```bash
python3 scripts/generate_benchmark_dataset.py \
  --output-format pjc-csv \
  --server-items 100000 \
  --client-items 50000 \
  --overlap 0.2   # 10k overlap
```

Benchmark across sizes: 1k, 10k, 100k, 1M items. Measure:
- Setup time (key exchange).
- Query time.
- Network bandwidth between server and client processes.
- Peak memory on each side.

```bash
python3 scripts/benchmark_pjc.py \
  --mode scale \
  --server-count 100000 \
  --client-count 50000 \
  --iterations 3 \
  --output tmp/pjc_benchmark_100k.json
```

**G4-b — Memory ceiling and connection reuse (1 block)**

At 1M items, measure whether APSI holds the entire set in memory or streams. Profile with `valgrind --tool=massif` or Python memory profiler for the orchestration layer.

Test whether PJC server can handle back-to-back queries without restart (connection reuse across `run_pjc.sh` invocations).

#### Acceptance Criteria

1. 100k-item intersection completes in < 300s.
2. Memory ceiling at 1M items documented.
3. Benchmark report emitted as `pjc_benchmark/v1` with `scale` mode rows.

---

### G5 — End-to-End Pipeline Latency SLO (1 block / 5h)

#### Tasks

Define and measure SLO targets for a standard 10k-item privacy query:

| Stage | p50 target | p95 target |
|-------|-----------|-----------|
| SSE export (10k records) | < 5s | < 15s |
| Record recovery (1k candidates) | < 500ms | < 2s |
| Bridge prepare-job | < 10s | < 30s |
| PJC (10k items) | < 60s | < 120s |
| Policy release | < 1s | < 3s |
| **Total pipeline** | **< 90s** | **< 180s** |

Automate with an extended `benchmark_pipeline.py`:

```bash
python3 scripts/benchmark_pipeline.py \
  --mode scale \
  --server-rows 10000 \
  --client-rows 10000 \
  --candidate-count 1000 \
  --iterations 3 \
  --output tmp/pipeline_slo_benchmark.json
```

Record per-stage `duration_ms` from `pipeline_observability/v1` output. Compare against SLO targets. Fail if any stage exceeds 3x its p95 target.

#### Acceptance Criteria

1. Full pipeline with 10k-item inputs completes within SLO.
2. `pipeline_slo_benchmark/v1` report emitted with per-stage latency breakdown.
3. OTel spans from `export_otel_events.py` match per-stage timings.

---

### G6 — mTLS Connection Overhead Measurement (1 block / 5h)

#### Tasks

Run the recovery service benchmark with and without TLS:

```bash
# Plaintext HTTP baseline
python3 scripts/benchmark_record_recovery.py \
  --mode all --candidate-count 1000 --iterations 20 \
  --output tmp/recovery_plain_http.json

# mTLS
python3 scripts/benchmark_record_recovery.py \
  --mode mtls --candidate-count 1000 --iterations 20 \
  --tls-config tmp/mtls \
  --output tmp/recovery_mtls.json
```

Measure TLS handshake overhead separately from request processing overhead. If per-request handshake adds > 50ms p95, evaluate:
1. HTTP keep-alive (reuse existing TLS session within a connection).
2. TLS session resumption (via session tickets — supported by Python's `ssl` module).

Add `Connection: keep-alive` and `Keep-Alive: timeout=30` response headers to `RecordRecoveryHttpHandler._write_json`. Verify that the Python `urllib.request` client benefits from keep-alive (it does with HTTP/1.1 persistent connections).

#### Acceptance Criteria

1. mTLS p95 overhead vs plain HTTP documented.
2. If overhead > 50ms, keep-alive improvement measured and documented.
3. `recovery_mtls_benchmark/v1` report emitted.

---

### G7 — SQLite vs PostgreSQL Latency Comparison (1 block / 5h)

#### Tasks

Run `benchmark_read_adapters.py` against both backends once F1 is complete:

```bash
# SQLite baseline (existing)
python3 scripts/benchmark_read_adapters.py \
  --mode all --iterations 5 \
  --output tmp/read_adapters_sqlite.json

# PostgreSQL
python3 scripts/benchmark_read_adapters.py \
  --mode all --iterations 5 \
  --db-dsn postgresql://postgres:test@localhost:5432/postgres \
  --output tmp/read_adapters_postgres.json
```

Expected: PostgreSQL latency should be within 2x of SQLite for small datasets (sidecar metadata is not large). If PostgreSQL is significantly slower, profile with `EXPLAIN ANALYZE` and add missing indexes.

#### Acceptance Criteria

1. PostgreSQL p95 latency for `GET /v1/jobs/<job_id>` within 2x of SQLite.
2. Missing indexes identified and added.

---

### G8 — Concurrent Dashboard Jobs (1 block / 5h)

#### Tasks

Stress-test `serve_operator_dashboard.py` with concurrent `POST /v1/jobs/start` requests:

```bash
# Start dashboard
python3 scripts/serve_operator_dashboard.py \
  --out-base tmp/live_sse_bridge_demo \
  --bind-host 127.0.0.1 --port 18094

# Concurrent load (using ab or wrk)
ab -n 20 -c 5 \
  -T application/json \
  -p /tmp/job_start_body.json \
  http://127.0.0.1:18094/v1/jobs/start
```

Measure:
- Dashboard response time under N simultaneous running jobs.
- Whether `/v1/dashboard` cache (5-second TTL) degrades under load.
- Memory growth per active job.

#### Acceptance Criteria

1. 5 concurrent jobs: dashboard `/v1/dashboard` p95 < 2s.
2. No memory leak per completed job (verify with `tracemalloc`).

---

## 5. Category H — Multi-Tenant Isolation

**Goal:** Ensure that one tenant's data, audit trail, and resource consumption cannot affect or be observed by another tenant — beyond what the existing `caller`/`tenant_id` policy binding already enforces at the application layer.

**Total: ~6 blocks / ~30h**

---

### H1 — Per-Tenant Network Isolation (2 blocks / 10h)

#### Tasks

**H1-a — Per-tenant Unix socket (1 block)**

Rather than a single shared Unix socket, issue one socket per tenant or per `service_id`:

```bash
# Instead of:
python3 scripts/run_record_recovery_service.py serve \
  --socket-path /tmp/seccomp_recovery.sock

# Per-tenant:
python3 scripts/run_record_recovery_service.py serve \
  --socket-path /tmp/seccomp_recovery_tenant_demo.sock \
  --tenant-id demo_tenant
```

Modify `manage_record_recovery_service.py start` to generate `socket_path` from `tenant_id` when not explicitly set. Update `pipeline_configs` that reference socket paths accordingly.

**H1-b — Kubernetes NetworkPolicy (1 block)**

For Kubernetes deployments, add `NetworkPolicy` manifests:

```yaml
# config/k8s/netpol-recovery-service.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: recovery-service-ingress
spec:
  podSelector:
    matchLabels:
      app: recovery-service
      tenant: demo-tenant
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: sse-bridge-pipeline
              tenant: demo-tenant
      ports:
        - port: 18443
          protocol: TCP
```

One NetworkPolicy per tenant. The SSE bridge pipeline pod must carry the matching `tenant` label.

#### Acceptance Criteria

1. A per-tenant socket path is derived from `tenant_id` when `socket_path` is omitted.
2. `health` probe to a different tenant's socket fails with connection refused.
3. NetworkPolicy manifests generated and validated with `kubectl apply --dry-run`.

---

### H2 — Rate Limiting and Quota Enforcement (2 blocks / 10h)

#### Tasks

**H2-a — Per-caller rate limiter in recovery service (1 block)**

Add a token bucket rate limiter to `RecordRecoveryHttpHandler`. The limiter is keyed by `caller` extracted from the request payload:

```python
# In services/record_recovery/http_service.py
import threading, time

class TokenBucket:
    def __init__(self, rate: float, capacity: int):
        self._tokens = capacity
        self._rate = rate   # tokens per second
        self._capacity = capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, n: int = 1) -> bool:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self._capacity,
                               self._tokens + (now - self._last) * self._rate)
            self._last = now
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False
```

Add `--rate-limit-per-caller <requests/s>` and `--rate-limit-burst <burst>` flags to `http_service.py`. When a rate limit is exceeded, return HTTP 429 with `reason_code: rate_limited` in the error response and structured log.

**H2-b — Per-tenant job quota in dashboard (1 block)**

Add `--max-concurrent-jobs-per-tenant <n>` to `serve_operator_dashboard.py`. When a `POST /v1/jobs/start` request exceeds the quota, return HTTP 429 with a structured error.

Track active jobs per `tenant_id` in the dashboard's in-memory job table. The count is decremented when a job reaches a terminal state.

`--max-rows-per-request` is already implemented in the recovery service HTTP handler; verify it is enforced even under concurrent load (G2-b).

#### Acceptance Criteria

1. Requests exceeding `--rate-limit-per-caller` receive HTTP 429 and a `rate_limited` structured log entry.
2. Jobs exceeding `--max-concurrent-jobs-per-tenant` are rejected with HTTP 429.
3. Rate limiting does not affect other callers (isolation verified).

---

### H3 — Per-Tenant Audit Anchoring (2 blocks / 10h)

#### Tasks

**H3-a — Partition audit anchor by tenant (1 block)**

Current: single `audit_chain_anchor.jsonl` for all jobs.

Add `--tenant-id` filter to `archive_audit_bundle.py`:

```bash
python3 scripts/archive_audit_bundle.py \
  --audit-chain out/audit_chain.json \
  --audit-seal out/audit_chain.seal.json \
  --archive-dir archive/tenant_demo \
  --job-id auto_demo_job \
  --tenant-id demo_tenant \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY
```

The archive directory structure becomes:

```
archive/
  demo_tenant/
    audit_chain_anchor.jsonl
    audit_chains/
      <job_id>/
        audit_chain.json
        audit_chain.seal.json
  other_tenant/
    audit_chain_anchor.jsonl
    ...
```

Add tenant validation in `archive_audit_bundle.py`: if `tenant_id` does not match the `audit_chain.json` payload's `tenant_id`, reject with an error.

**H3-b — Per-tenant external ledger paths (1 block)**

Update `publish_external_audit_anchor.py` to accept `--tenant-id` and use a tenant-namespaced external ledger path:

```bash
python3 scripts/publish_external_audit_anchor.py \
  --anchor-file archive/demo_tenant/audit_chain_anchor.jsonl \
  --external-ledger external_audit/demo_tenant/ledger.jsonl \
  --tenant-id demo_tenant \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY \
  --require-signature \
  --assert-ok
```

For S3-backed external ledgers (K1), the key prefix becomes `s3://bucket/audit/<tenant_id>/ledger.jsonl`.

#### Acceptance Criteria

1. Archive and anchor operations are strictly partitioned by `tenant_id`.
2. Cross-tenant anchor file path access is blocked at the script level.
3. External ledger path includes `tenant_id` as a namespace component.

---

## 6. Category I — Production Operator Console

**Goal:** Replace the current loopback-only web shell with a production-grade observability stack and self-service data request portal.

**Total: ~6 blocks / ~30h**

---

### I1 — Real Grafana + Tempo / Jaeger Dashboards (2 blocks / 10h)

#### Current Baseline

`scripts/export_otel_events.py` produces OTLP-compatible span JSONL (`otel_spans.jsonl`). The file can be imported into Grafana Tempo or Jaeger, but no dashboards or collectors are configured.

#### Tasks

**I1-a — Deploy Grafana + Tempo OTLP collector (1 block)**

```yaml
# docker-compose.observability.yml
services:
  tempo:
    image: grafana/tempo:latest
    command: ["-config.file=/etc/tempo.yaml"]
    volumes: ["./config/tempo.yaml:/etc/tempo.yaml"]
    ports: ["3200:3200", "4317:4317"]  # gRPC OTLP on 4317

  grafana:
    image: grafana/grafana:latest
    environment:
      GF_AUTH_ANONYMOUS_ENABLED: "true"
    ports: ["3000:3000"]
    volumes: ["./config/grafana-datasources.yaml:/etc/grafana/provisioning/datasources/datasources.yaml"]
```

```yaml
# config/tempo.yaml
server:
  http_listen_port: 3200
distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
```

Add `--otlp-endpoint` to `export_otel_events.py` to push spans directly via gRPC OTLP instead of writing JSONL:

```python
# Add alongside existing JSONL output
if args.otlp_endpoint:
    _export_via_otlp(spans, args.otlp_endpoint)
```

**I1-b — Build Grafana dashboards (1 block)**

Create `config/grafana-dashboards/pipeline-overview.json` with panels:

| Panel | Query |
|-------|-------|
| Pipeline latency heatmap | Histogram of `pipeline.stage.duration_ms` by stage name |
| Per-stage error rate | Error count / total count by stage, 5-minute rolling window |
| Recovery service request rate | Count of `recovery.request` spans per minute |
| PJC intersection size | Distribution of `pjc.intersection_size` attribute |
| Active jobs | Count of `status=running` jobs from the operator dashboard |

Provision dashboards via Grafana's provisioning API (no manual UI clicks required for deployment).

#### Acceptance Criteria

1. `export_otel_events.py --otlp-endpoint http://localhost:4317` pushes spans to Tempo.
2. Grafana dashboard renders pipeline latency and error rate.
3. Provisioning is fully automated (no manual Grafana configuration).

---

### I2 — Alerting Integration (2 blocks / 10h)

#### Tasks

**I2-a — Wire alert check to Alertmanager / Slack (1 block)**

Current: `check_observability_alerts.py` emits `observability_alert_report/v1` JSON but does not notify anyone.

Add `--webhook-url` flag to `check_observability_alerts.py`:

```python
def post_alert_webhook(url: str, firing_alerts: list[dict]) -> None:
    for alert in firing_alerts:
        payload = {
            "text": f":rotating_light: *{alert['alert_id']}* ({alert['severity']})\n{alert['message']}\nTriage: {alert['triage_path']}"
        }
        urllib.request.urlopen(
            urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                   headers={"Content-Type": "application/json"}),
            timeout=5,
        )
```

For Alertmanager, post to `POST /api/v1/alerts` with Prometheus alert format. Support both Slack (simple webhook) and Alertmanager (structured alert JSON) via `--webhook-format slack|alertmanager`.

**I2-b — Scheduled alert check via cron (1 block)**

Add `scripts/run_alert_check_daemon.py` that:
1. Loops on a configurable interval (default 60s).
2. Calls `check_observability_alerts.py` logic internally.
3. Posts alerts to webhook on state change (firing → not firing, or new alert).
4. Emits a heartbeat `alert_daemon_heartbeat/v1` log entry every interval.

This replaces the need for a Prometheus scrape target until a full metrics endpoint is built (J3).

#### Acceptance Criteria

1. A firing alert (`repeated_stage_error`) triggers a Slack notification within 120s.
2. Alert resolves when the condition clears (no repeat notification).
3. `alert_daemon_heartbeat/v1` log verifiable with `validate_json_contract.py`.

---

### I3 — Self-Service Data Request Portal (2 blocks / 10h)

#### Tasks

**I3-a — Request submission form (1 block)**

Extend the existing `serve_operator_dashboard.py` with a tenant-facing request form at `/v1/request/submit`:

```json
POST /v1/request/submit
{
  "tenant_id": "demo_tenant",
  "dataset_id": "bridge_demo_dataset",
  "purpose": "marketing_attribution",
  "candidate_ids": ["C001", "C002", ...],
  "join_key_field": "order_id",
  "value_field": "amount_cents"
}
```

The endpoint:
1. Validates the request against `query_workflow_request/v1` schema.
2. Checks the submitting identity (via identity proxy `X-Identity-*` headers) has `query_submitter` role.
3. Creates a pending submission record in the metadata sidecar.
4. Returns a `submission_id` for tracking.
5. Does not execute immediately — requires an approver with `privacy_operator` role.

**I3-b — Approval workflow (1 block)**

Add `POST /v1/request/<submission_id>/approve` and `POST /v1/request/<submission_id>/reject`:

- `approve`: requires `X-Identity-Platform-Roles` to contain `privacy_operator` or `platform_admin`. Calls `submit_query_workflow.py --execute`. Records approval in `control_plane_mutations`.
- `reject`: records rejection reason in `control_plane_mutations`. Notifies submitter (via webhook).

Add `GET /v1/requests?tenant_id=...&status=pending` to list pending requests for the operator review panel.

Wire the existing dashboard HTML to render a "Pending Requests" card when the operator is authenticated as `privacy_operator`.

#### Acceptance Criteria

1. A `query_submitter`-role user can submit a request; it appears in the operator panel as pending.
2. A `privacy_operator`-role user can approve; the job executes and the result appears in the dashboard.
3. An attempt by `query_submitter` to approve their own request is rejected with 403.

---

## 7. Category J — SRE / High Availability

**Goal:** The platform can survive the failure of any single component (recovery service crash, PostgreSQL primary failure, operator dashboard restart) without data loss or audit chain corruption.

**Total: ~6 blocks / ~30h**

---

### J1 — Multi-Node Deployment Topology (1 block / 5h)

#### Tasks

Define the canonical deployment topology for a single-region production deployment:

```
                        ┌───────────────────────┐
                        │   Load Balancer (L4)  │
                        │  (HAProxy / AWS NLB)  │
                        └──────────┬────────────┘
                                   │ :18443 (mTLS)
                     ┌─────────────┴──────────────┐
                     │                            │
           ┌─────────▼──────────┐      ┌──────────▼─────────┐
           │ recovery-service-1 │      │ recovery-service-2 │
           │  (mTLS, tenant A)  │      │  (mTLS, tenant B)  │
           └─────────┬──────────┘      └──────────┬─────────┘
                     │                            │
                     └──────────┬─────────────────┘
                                │ PostgreSQL (psycopg2)
                     ┌──────────▼──────────┐
                     │   pgBouncer :6432   │
                     └──────────┬──────────┘
                                │
                 ┌──────────────┴─────────────┐
                 │                            │
        ┌────────▼────────┐         ┌─────────▼───────┐
        │  pg-primary:5432│◄────────│  pg-replica:5432│
        │  (Patroni)      │ streaming│  (Patroni)      │
        └─────────────────┘         └─────────────────┘
```

Create `config/topology.md` documenting:
- Port assignments for each component.
- Which components are stateless (recovery service → multiple replicas OK) vs stateful (PostgreSQL → single primary with replicas).
- Which components use mTLS (recovery service) vs bearer token (metadata API).

Create `config/k8s/` directory with baseline Kubernetes manifests: `Deployment`, `Service`, `HorizontalPodAutoscaler` for the recovery service.

#### Acceptance Criteria

1. `config/topology.md` defines all component ports, protocols, and scaling policies.
2. Recovery service `Deployment` with `replicas: 2` passes `kubectl apply --dry-run`.
3. Load balancer health check uses `GET /healthz` → 200.

---

### J2 — Automated Failover Testing (2 blocks / 10h)

#### Tasks

**J2-a — Recovery service failover (1 block)**

Write `scripts/test_failover_recovery_service.py`:

1. Start two recovery service instances (primary + secondary).
2. Start a simulated pipeline job that sends requests every 2 seconds.
3. Kill the primary service mid-request.
4. Verify the client retries and succeeds against the secondary within 5 seconds.
5. Verify the audit log has no missing events for the completed requests.

```bash
python3 scripts/test_failover_recovery_service.py \
  --primary-config config/record_recovery_http_mtls_service.example.json \
  --secondary-endpoint https://127.0.0.1:18444 \
  --output tmp/failover_test_result.json
```

**J2-b — PostgreSQL Patroni failover test (1 block)**

```bash
# Trigger Patroni switchover
patronictl -c config/patroni.yml switchover --master pg-primary --candidate pg-replica --force

# Verify sidecar reconnects
python3 scripts/check_platform_health.py --metadata-db tmp/platform_metadata.db

# Verify import still works after failover
python3 scripts/import_run_metadata.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --db-dsn postgresql://postgres:pass@pgbouncer:6432/postgres
```

Document the expected reconnection behavior for psycopg2 (it does not auto-reconnect; the scripts must handle `OperationalError` and retry with backoff).

Add retry logic to `metadata_db.py`:

```python
def connect_with_retry(dsn: str, retries: int = 3, delay: float = 1.0):
    for attempt in range(retries):
        try:
            return psycopg2.connect(dsn)
        except psycopg2.OperationalError:
            if attempt == retries - 1:
                raise
            time.sleep(delay * (2 ** attempt))
```

#### Acceptance Criteria

1. Recovery service failover completes in < 10 seconds (client retries included).
2. No audit events lost during failover.
3. PostgreSQL failover: sidecar reconnects and continues importing within 30 seconds.

---

### J3 — SLO Enforcement and Prometheus Metrics Endpoint (2 blocks / 10h)

#### Tasks

**J3-a — Add /metrics endpoint to recovery service (1 block)**

Add Prometheus text-format `/metrics` endpoint to `RecordRecoveryHttpHandler`:

```
# HELP recovery_requests_total Total recovery requests by decision
# TYPE recovery_requests_total counter
recovery_requests_total{decision="allow",op="recover"} 42
recovery_requests_total{decision="deny",op="recover"} 3

# HELP recovery_request_duration_seconds Recovery request latency
# TYPE recovery_request_duration_seconds histogram
recovery_request_duration_seconds_bucket{le="0.1"} 10
recovery_request_duration_seconds_bucket{le="0.5"} 38
recovery_request_duration_seconds_bucket{le="1.0"} 42
recovery_request_duration_seconds_sum 8.4
recovery_request_duration_seconds_count 42
```

Use `threading.Lock`-protected in-memory counters; no external Prometheus client library required.

Add to `GET /metrics` handler in `RecordRecoveryHttpHandler.do_GET`.

**J3-b — SLO alert rules (1 block)**

Create `config/prometheus/alert-rules.yml`:

```yaml
groups:
  - name: seccomp-privacy-slo
    rules:
      - alert: RecoveryServiceErrorRateHigh
        expr: |
          rate(recovery_requests_total{decision="deny"}[5m])
          / rate(recovery_requests_total[5m]) > 0.05
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Recovery service error rate > 5%"

      - alert: RecoveryServiceLatencyHigh
        expr: |
          histogram_quantile(0.95,
            rate(recovery_request_duration_seconds_bucket[5m])
          ) > 2.0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Recovery service p95 latency > 2s"
```

Wire alert rules to Alertmanager (from I2-a).

#### Acceptance Criteria

1. `GET /metrics` on the recovery service returns valid Prometheus text format.
2. Alert fires when error rate exceeds 5% for 2 minutes in a load test.
3. Alert resolves when error rate drops below threshold.

---

### J4 — Chaos and Failure Injection Testing (1 block / 5h)

#### Tasks

Create `scripts/run_chaos_test.py` with injected failure scenarios:

| Scenario | Injection method | Expected behavior |
|----------|-----------------|-------------------|
| Recovery service OOM | `os.kill(pid, SIGKILL)` | Client retries, audit log captures partial run |
| mTLS cert expiry | Use a cert with 1-second TTL | Client receives `SSL: CERTIFICATE_VERIFY_FAILED`; logs error with `tls_error` reason code |
| PostgreSQL primary killed | `docker stop pg-primary` | Patroni promotes replica; sidecar reconnects |
| Audit archive write failure | `chmod 000` on archive dir | `archive_audit_bundle.py` fails with clear error; no partial writes |
| Full disk on audit log path | `truncate -s <(df tmp --output=avail -B1 | tail -1)` dummy file | Recovery service logs `audit_write_failed` event |

Each scenario must produce a verifiable error report and not corrupt any frozen contract file.

#### Acceptance Criteria

1. All 5 scenarios produce a verifiable failure report without corrupting `audit_chain.json`.
2. Recovery from each failure is documented in `OPS_RUNBOOK.md`.

---

## 8. Category K — Compliance and External Audit

**Goal:** Make the audit trail verifiable by external parties: immutable external anchor, formal compliance mapping, and adversarial security review.

**Total: ~4 blocks / ~20h**

---

### K1 — Real Immutable Audit Anchor (2 blocks / 10h)

#### Current Baseline

`scripts/publish_external_audit_anchor.py` writes `external_audit_anchor_ledger/v1` records to a local file. The ledger is locally append-only (no deletion API), but is not truly immutable.

#### Tasks

**K1-a — S3 Object Lock (WORM) backend (1 block)**

Add `external_sink.kind=s3_worm` to `publish_external_audit_anchor.py`:

```python
def append_s3_worm_ledger(bucket: str, key: str, records: list[dict]) -> int:
    import boto3
    s3 = boto3.client("s3")
    # Read existing ledger (if any)
    try:
        existing = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode()
    except s3.exceptions.NoSuchKey:
        existing = ""
    new_content = existing + "".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records
    )
    # PUT with Object Lock COMPLIANCE mode
    s3.put_object(
        Bucket=bucket, Key=key, Body=new_content.encode(),
        ObjectLockMode="COMPLIANCE",
        ObjectLockRetainUntilDate=datetime.now(timezone.utc) + timedelta(days=3650),
    )
    return len(records)
```

Update `schemas/external_audit_anchor_report.schema.json` to add `"s3_worm"` to `external_sink.kind` enum.

Example usage:

```bash
python3 scripts/publish_external_audit_anchor.py \
  --anchor-file tmp/audit_archive/audit_chain_anchor.jsonl \
  --external-ledger s3://seccomp-audit-archive/ledger.jsonl \
  --sink-kind s3_worm \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY \
  --require-signature \
  --assert-ok
```

**K1-b — Sigstore / Rekor transparency log (1 block)**

For deployments that prefer a public, append-only transparency log over an S3 WORM bucket:

```bash
pip install sigstore
```

Add `external_sink.kind=rekor` to `publish_external_audit_anchor.py`:

```python
def append_rekor_ledger(records: list[dict]) -> int:
    from sigstore.sign import Signer, SigningContext
    from sigstore.transparency import LogEntry
    # Sign the anchor payload and upload to Rekor
    ...
```

Each `entry_sha256` from the anchor file is uploaded as a `hashedrekord` entry. The Rekor `logIndex` and `uuid` are stored back in the report for verifiability.

#### Acceptance Criteria

1. `publish_external_audit_anchor.py --sink-kind s3_worm` successfully uploads to an S3 bucket with Object Lock enabled.
2. Uploaded ledger object has `ObjectLockMode=COMPLIANCE` and a 10-year retain-until date.
3. A subsequent dry-run reads the same S3 object and verifies chain integrity.

---

### K2 — Compliance Documentation (1 block / 5h)

#### Tasks

Create `docs/COMPLIANCE_MAPPING.md` documenting how the platform satisfies each GDPR principle:

| GDPR Principle | Platform Mechanism | Evidence |
|---------------|-------------------|---------|
| Data minimization | SSE export returns only records matching the query scope; PJC reveals only intersection, not individual records | `sse/run_client.py export-bridge-records` scope enforcement; `policy_release.py` intersection-only result |
| Purpose limitation | `caller_permissions.allowed_service_ids` + `policy_bindings` enforce per-caller purpose | `check_policy_drift.py`, `propose_policy_change.py` governance rules |
| Storage limitation | `retention_reconcile_plan` (C5) generates a retention plan for audit / registry / key lifecycle records | `materialize_control_plane_deepening.py --list-entity retention-reconcile-plan` |
| Integrity and confidentiality | mTLS on recovery service; HMAC-signed audit chain; encrypted record store | `record_recovery_service_config/v1 tls`; `seal_audit_artifact.py`; `encrypted_record_store.py` |
| Accountability | Immutable external audit anchor; mutation log for all control-plane writes | `publish_external_audit_anchor.py`; `control_plane_mutations` table (migration 005) |
| Right to erasure | `retention_reconcile_plan` action=`review` identifies records with configurable TTL | Extend to add `action=delete` path (not yet implemented) |

The right-to-erasure gap (no automated delete path) must be flagged as a known limitation.

#### Acceptance Criteria

1. `docs/COMPLIANCE_MAPPING.md` covers all 7 GDPR principles.
2. Known limitations are explicitly listed.
3. Document is reviewed by a person with compliance/legal background.

---

### K3 — Penetration Testing (1 block / 5h)

#### Scope

| Surface | Attack vectors to test |
|---------|----------------------|
| Recovery service (mTLS) | Cert replay, MITM without valid client cert, payload injection via `X-Request-Signature` bypass |
| Metadata API (bearer token) | Token replay, scope escalation (`tenant_id` override), path traversal in `--include-paths` |
| Audit chain | SHA-256 collision resistance (theoretical), seal key brute force, anchor log truncation |
| Dashboard | SSRF via `request_file` path, command injection via `--out-base`, authentication bypass |
| External KMS (Vault) | AppRole secret ID leakage, token privilege escalation |

#### Tasks

Extend `check_malformed_input_gate.py` to cover the HTTP surfaces:

```bash
python3 scripts/check_malformed_input_gate.py \
  --target recovery-service \
  --endpoint https://127.0.0.1:18443 \
  --out tmp/http_malformed_gate.json
```

The gate should test:
1. Requests with missing `X-Request-Signature` header (should return 400 with `request_signature_missing`).
2. Requests with expired `request_timestamp_utc` (should return 400 with `request_expired`).
3. Payloads with SQL injection patterns in `caller`, `job_id`, `tenant_id` (all should be treated as opaque strings, not query parameters).
4. Oversized request bodies (`Content-Length: 100000000`).

For the audit chain, write `scripts/verify_audit_tamper_resistance.py` that:
- Flips one bit in `audit_chain.json`.
- Verifies that `verify_audit_bundle.py` detects the tamper.
- Restores the original content.

Engage an external pen testing firm for the mTLS boundary and the Vault AppRole authentication flow.

#### Acceptance Criteria

1. All HTTP malformed-input mutations are rejected by the recovery service.
2. One-bit tamper in `audit_chain.json` is detected by `verify_audit_bundle.py`.
3. External pen test report with zero critical findings (or accepted risk documentation for any findings).

---

## 9. Execution Order and Dependencies

```
Week 1-2:   E1-a, E1-b, F1-a (parallel)
Week 2-3:   E1-c, F1-b, E2-a (parallel)
Week 3-4:   E2-b, E2-c, F2-a (parallel)
Week 4-5:   E3-a, E3-b, F2-b (parallel)
Week 5-6:   E3-c, E3-d, F2-c, F3 (parallel)
Week 6-7:   G1, G2-a, G3 (parallel, F1 prerequisite met)
Week 7-8:   G2-b, G4-a, G5 (parallel)
Week 8-9:   G4-b, G6, G7, G8, H1-a (parallel)
Week 9-10:  H1-b, H2-a, H2-b, H3-a (parallel)
Week 10-11: H3-b, I1-a, I2-a, J1 (parallel)
Week 11-12: I1-b, I2-b, I3-a, J2-a (parallel)
Week 12-13: I3-b, J2-b, J3-a, K1-a (parallel)
Week 13-14: J3-b, J4, K1-b, K2 (parallel)
Week 14-15: K3, F4-a, F4-b (parallel)
```

---

## 10. Summary Table

| Category | Blocks | ~Hours | Key prerequisite |
|----------|-------:|-------:|-----------------|
| E — Real authority sources | 12 | 60h | None |
| F — Production PostgreSQL | 8 | 40h | None |
| G — Scale & optimization | 10 | 50h | E1 + F1 smoke-tested |
| H — Multi-tenant isolation | 6 | 30h | E1 |
| I — Production operator console | 6 | 30h | E1, G complete |
| J — SRE / HA | 6 | 30h | F2 |
| K — Compliance / external audit | 4 | 20h | J complete |
| **Total** | **52** | **~260h** | |

**Optimization + large-scale benchmark only (G):** 10 blocks / 50h

**Critical path (shortest path to a load-tested, authority-backed platform):**
E1 → E3-a → F1 → G1–G5 → J1 → J2 → K1 = 26 blocks / 130h

---

## 11. What This Guidebook Does Not Cover

The following are out of scope for this guidebook and should be treated as separate initiatives:

1. **Multi-region deployment** — active-active across two data centers, with cross-region PostgreSQL replication and audit anchor synchronization.
2. **Full frontend product** — a React/Vue SPA admin console replacing the current embedded HTML dashboard.
3. **Temporal durable workflow** — replacing the current `subprocess.Popen` pipeline orchestration with a Temporal workflow that survives process restarts.
4. **Customer 360 / e-commerce fact warehouse** — building a full data warehouse on top of the privacy platform query results.
5. **HSM-backed key management** — using a Hardware Security Module instead of Vault for the bridge token secrets.
6. **SOC 2 Type II certification** — formal certification process requires an audit period and policy documentation beyond this guidebook's scope.

None of these are blocked by the work in this guidebook. They should be started after the 52 blocks above are complete.
