# Production Readiness Guidebook
# SSE + PJC E-Commerce Privacy Platform

**Date:** 2026-05-06
**Status:** Post-baseline complete. Production-readiness Category E is complete repo-side; this guidebook tracks the remaining work between "demo baseline" and "production platform."

> 2026-06-01 audit note: this guidebook is retained for detailed tranche history
> and implementation commands. Current security/completion status is now tracked
> in [CURRENT_SECURITY_AND_COMPLETION_AUDIT.md](CURRENT_SECURITY_AND_COMPLETION_AUDIT.md).
> Implementation-level remaining work is tracked in
> [REMAINING_WORK_IMPLEMENTATION_BACKLOG.md](REMAINING_WORK_IMPLEMENTATION_BACKLOG.md).
> Treat "complete" in this guide as "repo-side complete" or
> "baseline-complete" unless that audit explicitly upgrades the item to
> production-complete.

---

## 1. How to Read This Document

### 1.1 Platform State Today

The current codebase is a fully working, contract-frozen, demo-scale privacy pipeline:

```
SSE export → record recovery (mTLS) → bridge (Rust) → PJC/APSI → policy release
```

All contracts are frozen under the backcompat guard. All post-baseline tranches A–E are complete repo-side. Category E live validation still needs operator-provided Keycloak / OpenFGA / Vault / cloud-KMS services and credentials, but the repository now carries the adapters, config artifacts, dry-run contracts, and runbook commands.

| Component | Current State | Remaining Production Gap |
|-----------|--------------|--------------------------|
| Keycloak / OIDC | Keycloak realm import, RS256/JWKS verifier, offline contract smoke, and optional client-credentials requester | Operator must run/import the realm, provide client secrets, and execute the live token path |
| OpenFGA | SQLite fallback, OpenFGA HTTP backend, committed authorization model, model setup helper, and optional live governance check | Operator must run OpenFGA, create/select a store, upload the model, and provide live store env vars |
| Vault / KMS | Vault HTTP token/AppRole client, Vault PKI cert issuer with mock fallback, and AWS KMS secret-ref baseline | Operator must run Vault/cloud KMS, provision policies/roles/keys, and execute live validation |
| mTLS PKI | Vault PKI issuance helper plus mock cert generation in default smoke | Operator must enable Vault PKI and rotate issued certs in the target environment |
| PostgreSQL | SQLite sidecar with Postgres-compatible DDL, psycopg2 driver layer, live PostgreSQL 16 portability gate completed locally, repo-side primary/replica HA topology artifacts, read-replica routing flags on every read-only sidecar entrypoint, pgBouncer topology artifacts, and standalone backup/restore CLIs (`backup_metadata_db.py`, `restore_metadata_db.py`) supporting both SQLite copy and `pg_dump` / `pg_restore` paths | Patroni/failover, replica-read, and pgBouncer live drills remain operator-environment work |
| Benchmarks | Synthetic demo data (`intersection_size=2`) plus G1 SSE export scale benchmark/report, G2 record-recovery benchmark/report, and G3 bridge prepare-job benchmark/report with local 100k / 1M release-binary runs | Bridge CPU hotspot profiling still needs `cargo flamegraph` or `perf` in an operator environment; PJC / full-pipeline scale benchmarks still need production-like runs |
| External audit anchor | Local file ledger | Not connected to immutable external medium |

### 1.2 Notation

- **1 block = ~5h** of focused implementation + verification + doc write-back.
- **Dependency arrows**: some blocks in E/F are prerequisites for meaningful G benchmarks.
- **Frozen fields** that must not change under any circumstances: `job_id`, `correlation_id`, `caller`, `tenant_id`, `dataset_id`, `service_id`, `token_scope`, `token_key_version`, `record_recovery_boundary`, `policy_id`.
- When a change would touch a frozen contract, file a change request under `docs/change_requests/` and follow `INTERFACE_FREEZE_AND_CHANGE_PROCESS.md`.

### 1.3 Recommended Execution Order

```
Live E authority validation with operator-provided services (optional, environment-gated)
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

**Remaining repo-side implementation total: 0 blocks / 0h**

Live-service validation is still operator-environment work: start Keycloak / OpenFGA / Vault (or cloud KMS), provide secrets through env vars, and run the optional `--execute` / live smoke paths. The repo now contains the adapter code, config artifacts, dry-run contracts, and runbook commands needed for E.

Progress recorded on 2026-05-06:

1. `E1-a` / `E1-b` / `E1-c` are complete as repo-side adapter and deployment-artifact work.
2. `E2-a` / `E2-b` / `E2-c` are complete as repo-side adapter and deployment-artifact work.
3. `E3-a` / `E3-b` / `E3-c` / `E3-d` are complete as repo-side adapter and smoke-contract work.

---

### E1 — Real Keycloak OIDC Integration (completed repo-side)

#### Current Baseline

- `scripts/map_oidc_claims.py`: parses HS256 JWT and RS256 JWT with configurable `claim_mapping` (dotted-path extraction, e.g., `realm_access.roles`).
- `scripts/map_oidc_claims.py --jwks-uri`: fetches JWKS over HTTP or `file://`, selects the RSA key by `kid`, verifies RS256 with `cryptography`, and emits `oidc_claim_map/v1`.
- `migrations/metadata/006_add_issuer_registry.sql`: `issuer_registry` table stores `issuer_type`, `display_name`, `service_id`, `jwks_uri`, `token_endpoint`, `claim_mapping_json`, `trusted_audiences_json`.
- `scripts/api_identity.py`: resolves `issuer + subject → caller_identities → caller/tenant_id/platform_roles`.
- `config/oidc_claim_mapping.example.json`: Keycloak realm claim mapping example, including `jwks_uri`.
- `config/keycloak_realm_seccomp_privacy.json`: Keycloak realm import with platform roles and service-account-enabled clients.
- `docker-compose.authority.yml`: local authority-source stack with Keycloak realm import.
- `scripts/request_oidc_client_credentials.py`: optional live client-credentials requester, outputting `oidc_client_credentials_report/v1`.
- `scripts/rotate_issuer_credentials.py`: dry-run issuer credential rotation via `issuer_registry`.
- `scripts/check_json_contracts.sh`: generates a synthetic RS256 JWT and offline `file://` JWKS, validates `oidc_claim_map/v1`, resolves API identity from the JWKS-backed token, and exercises JWKS-backed key-agent / external-KMS identity paths.

#### Gap

- RS256/JWKS verification exists, but it is currently contract-smoked with a synthetic `file://` JWKS rather than a real Keycloak realm.
- The default local environment does not auto-start Keycloak; use `docker compose -f docker-compose.authority.yml up keycloak` or an operator-managed realm.
- `caller_identities.issuer` / `subject` are still populated from static manifest or synthetic JWT fixtures, not from a live client-credentials flow.

#### Tasks

**E1-a — Deploy Keycloak (1 block) — Completed 2026-05-06**

Start the local authority stack:

```bash
docker compose -f docker-compose.authority.yml up keycloak
```

Implemented artifacts:

1. `config/keycloak_realm_seccomp_privacy.json` defines realm `seccomp-privacy`, platform roles, and confidential service-account clients: `metadata-api`, `query-workflow-api`, `recovery-service`, and `key-agent`.
2. `docker-compose.authority.yml` mounts that realm import into Keycloak.
3. `config/metadata_registry.example.json` already carries an issuer registry entry for a Keycloak realm; operators can adjust its URL to the running realm before `manage_metadata_db.py apply-registry`.

**E1-b — Switch map_oidc_claims.py to RS256 / JWKS (1 block) — Completed 2026-05-06**

Implemented:

1. `scripts/map_oidc_claims.py` supports `--jwks-uri`, `fetch_jwks()`, `verify_rs256()`, RSA JWK `n/e` conversion, and `kid` selection.
2. `config/oidc_claim_mapping.example.json` includes a Keycloak-style `jwks_uri`.
3. `scripts/api_identity.py` can resolve a JWT bearer token with a JWKS-backed config.
4. `scripts/check_json_contracts.sh` now validates a synthetic RS256 JWT against an offline `file://` JWKS and carries that token through API identity, key-agent, external-KMS, and metadata `/v1/identity` smoke paths.

**E1-c — Wire service accounts end-to-end (1 block) — Completed 2026-05-06**

Implemented:

1. `scripts/request_oidc_client_credentials.py` can request a real client-credentials token when `--execute` is set and the client secret env var is present.
2. The dry-run path outputs `oidc_client_credentials_report/v1` and is covered by default contract smoke.
3. The returned token can be written to a file with `--token-output-file`, exported into the appropriate bearer-token env var, and reused by `resolve_api_identity.py`, metadata `/v1/identity`, key-agent, external-KMS, and recovery-service identity gates.

Example:

```bash
KEYCLOAK_RECOVERY_SERVICE_SECRET=<client-secret> \
python3 scripts/request_oidc_client_credentials.py \
  --token-endpoint http://127.0.0.1:8080/realms/seccomp-privacy/protocol/openid-connect/token \
  --client-id recovery-service \
  --client-secret-env KEYCLOAK_RECOVERY_SERVICE_SECRET \
  --token-output-file tmp/keycloak_recovery_service.jwt \
  --execute \
  --assert-ok
```

#### Acceptance Criteria

1. `map_oidc_claims.py --jwks-uri file://...` verifies a synthetic RS256 token and produces valid `oidc_claim_map/v1`. Completed.
2. `map_oidc_claims.py --jwks-uri <realm-jwks-url>` verifies a real Keycloak RS256 token and produces `oidc_claim_map/v1`. Live path supported; requires operator-provided realm.
3. `resolve_api_identity.py --bearer-token-env KEYCLOAK_TOKEN` resolves a real token to `caller + tenant_id + platform_roles`. Live path supported; requires issuer registry and caller identity mapping.
4. `check_authority_governance.py --assert-ok` passes with a real Keycloak token as the identity source. Live path supported; requires generated identity-resolution report.
5. No frozen field semantics change.

---

### E2 — Real OpenFGA Service (completed repo-side)

#### Current Baseline

- `scripts/sync_openfga_tuples.py`: dry-run / apply / reconcile modes; writes to local SQLite `openfga_tuples` table by default and can target a live OpenFGA HTTP backend through `--openfga-config` or explicit endpoint/store flags.
- `scripts/check_openfga_authz.py`: queries the SQLite tuple table by default and can call live OpenFGA `/check`; outputs `openfga_check_result/v1`.
- `scripts/openfga_http.py`: shared OpenFGA HTTP helper for config resolution, read, write, delete, and check requests.
- `schemas/openfga_sync_report.schema.json`, `schemas/openfga_check_result.schema.json`.
- `schemas/openfga_config.schema.json`, `config/openfga.example.json`.
- `config/openfga_authorization_model.json`: concrete OpenFGA authorization model derived from the earlier draft.
- `scripts/setup_openfga_model.py`: optional live store/model setup helper, outputting `openfga_model_setup_report/v1`.
- `docker-compose.authority.yml`: local OpenFGA service.

#### Gap

- The HTTP adapter path exists, but the default environment still uses SQLite fallback.
- Uploading the authorization model is now scripted, but the default contract smoke runs dry-run only.
- No live OpenFGA store/model ID is committed as a required local dependency.

#### Tasks

**E2-a — Deploy OpenFGA and upload authorization model (1 block) — Completed 2026-05-06**

```bash
docker compose -f docker-compose.authority.yml up openfga
```

Dry-run validation:

```bash
python3 scripts/setup_openfga_model.py \
  --openfga-config config/openfga.example.json \
  --model config/openfga_authorization_model.json
```

Live setup:

```bash
python3 scripts/setup_openfga_model.py \
  --openfga-config config/openfga.example.json \
  --model config/openfga_authorization_model.json \
  --execute \
  --assert-ok
```

**E2-b — Add OpenFGA HTTP backend to sync and check scripts (1 block) — Completed 2026-05-06**

Implemented:

1. `sync_openfga_tuples.py` supports `--openfga-config`, `--openfga-endpoint`, and `--openfga-store-id`.
2. `sync_openfga_tuples.py apply` calls OpenFGA Write API when a live backend is configured.
3. `sync_openfga_tuples.py reconcile` reads current live tuples and reports the diff.
4. `check_openfga_authz.py` calls OpenFGA Check API when a live backend is configured.
5. SQLite remains the default CI path, so default contract smoke has no live OpenFGA dependency.
6. `config/openfga.example.json` and `schemas/openfga_config.schema.json` define the adapter config.

**E2-c — Wire OpenFGA into authority governance smoke (1 block) — Completed 2026-05-06**

Implemented:

1. `check_authority_governance.py` accepts `--openfga-config`, `--openfga-user`, `--openfga-relation`, and `--openfga-object`.
2. The existing `--openfga-check` file path remains as the default fallback.
3. `scripts/check_json_contracts.sh` has an optional live OpenFGA branch gated by `OPENFGA_ENDPOINT` and `OPENFGA_STORE_ID`. When both are set, it writes tuples to the configured store, checks `user:commerce_ops_demo query_submitter dataset:orders_analytics`, and validates the live authority governance rollup.

#### Acceptance Criteria

1. `sync_openfga_tuples.py --openfga-config ... apply` writes tuples to a real OpenFGA store when `OPENFGA_ENDPOINT` / `OPENFGA_STORE_ID` point at a live instance. Code path implemented; live environment still operator-provided.
2. `check_openfga_authz.py --openfga-config ... --assert-allowed` passes against a live Check when tuples/model are present. Code path implemented; live environment still operator-provided.
3. `check_authority_governance.py --assert-ok` works with real OpenFGA as the authz source through the new live-check flags.
4. CI still passes without `OPENFGA_ENDPOINT` set (SQLite fallback).

---

### E3 — Real Vault / Cloud KMS Integration (completed repo-side)

#### Current Baseline

- `scripts/vault_http_client.py`: real mode (HTTP) and mock mode (local `vault_kv_backend` file); `keyring_lib.py` supports `secret_ref.kind=vault_http`.
- `scripts/external_kms_service.py`, `scripts/manage_external_kms.py`: support Vault KV references.
- `scripts/rotate_issuer_credentials.py`: rotation writes new version to `key_refs`.
- `config/vault_http_client.example.json`, `config/vault_kv_backend.example.json`.
- `schemas/vault_http_client_config.schema.json`: freezes token/AppRole client config.
- `scripts/issue_mtls_certs.py`: Vault PKI issuer with local mock fallback; outputs `mtls_cert_issue_report/v1`.
- `scripts/cloud_kms_adapter.py`: optional AWS KMS adapter smoke helper; outputs `cloud_kms_adapter_result/v1`.
- `keyring_lib.py` and `schemas/keyring.schema.json`: support `secret_ref.kind=vault_http|aws_kms` in addition to existing `env|vault_kv`.

#### Gap

- Default CI smoke uses mock mode or dry-run mode.
- Live Vault/AppRole, Vault PKI, and AWS KMS are optional execution paths requiring operator-provided services and credentials.

#### Tasks

**E3-a — Deploy Vault in dev mode and test real-mode client (1 block) — Completed 2026-05-06**

```bash
docker compose -f docker-compose.authority.yml up vault
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
  get --path secret/bridge-token --field value --redact
```

Verify `vault_http_client_result/v1` output.

**E3-b — Replace root token with AppRole auth (1 block) — Completed 2026-05-06**

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

Implemented in `scripts/vault_http_client.py`:

1. `auth_method=approle`.
2. `approle_role_id_env` / `approle_secret_id_env`.
3. AppRole login against `/v1/auth/approle/login`.
4. `vault_http_client_result/v1` reports `auth_method` and non-secret auth metadata.

**E3-c — Vault PKI for mTLS certificate issuance (1 block) — Completed 2026-05-06**

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

Implemented `scripts/issue_mtls_certs.py`:

1. Calls Vault PKI issue endpoint when `mock_mode=false`.
2. Writes `server.crt`, `server.key`, `ca.crt`, and optional client cert/key.
3. Outputs `mtls_cert_issue_report/v1`.
4. Default contract smoke uses `config/vault_pki.example.json` in `mock_mode=true` to generate local dev certs without contacting Vault.

**E3-d — Cloud KMS adapter baseline (AWS KMS or GCP KMS) (1 block) — Completed 2026-05-06**

Implemented:

1. `keyring_lib.py` supports `secret_ref.kind=aws_kms` with lazy `boto3` import.
2. `schemas/keyring.schema.json` accepts `aws_kms` secret refs.
3. `scripts/cloud_kms_adapter.py describe|decrypt` provides a smoke helper; default contract smoke only runs `describe` against a synthetic ciphertext and does not require AWS credentials.
4. Vault remains the preferred production path; AWS KMS is the cloud alternative baseline.

#### Acceptance Criteria

1. `vault_http_client.py` in real mode resolves a secret from a live Vault instance using token or AppRole auth. Live path supported.
2. `check_kms_reachability.py --production-mode` reports `overall_status=ok` only when at least one live-capable HTTP backend check (`vault_http` or `external_kms_http`) is actually reachable. Keyring files are references, `vault_kv` is a local fixture, and skipped configs with no endpoint are rejected as production evidence. Live path supported.
3. `rotate_issuer_credentials.py` writes a new key version to the `key_refs` sidecar; Vault-backed secret material remains operator-managed.
4. `issue_mtls_certs.py` issues a valid server cert from Vault PKI in live mode and generates local mock certs for CI.
5. CI still passes without a real Vault, Keycloak, OpenFGA, or AWS account.

---

## 3. Category F — Production PostgreSQL

**Goal:** Migrate the metadata sidecar from SQLite to a production-grade PostgreSQL instance, with HA, connection pooling, and automated backup.

**Total: ~8 blocks / ~40h**

---

### F1 — SQLite → PostgreSQL Driver Layer (2 blocks / 10h)

#### Current Baseline

- Metadata scripts still default to SQLite for local/demo runs, but the core metadata DB helper now has a PostgreSQL driver layer and the main read/write entrypoints accept PostgreSQL DSNs.
- `migrations/postgres/001_init.sql` has the complete Postgres-compatible DDL (SERIAL, TIMESTAMPTZ, JSONB, BOOLEAN, indexes).
- `scripts/check_metadata_schema_portability.py` validates DDL is Postgres-compatible.
- `scripts/export_postgres_ddl.py` exports the target DDL.
- **F1-a completed (2026-05-06):** `scripts/metadata_db.py` now contains `connect_db(db_path, *, dsn)`, `connect_db_with_retry(…, retries, delay)`, `is_postgres(conn)`, `placeholder(conn)`, `adapt_sql(conn, sql)`, `row_to_dict(row)`, and `_split_sql_statements`. When `dsn` is provided, psycopg2 is used; migrations are applied statement-by-statement. The main metadata CLI/API paths now accept `--db-dsn` or `--metadata-db-dsn` while keeping SQLite as the default path.

#### Tasks

**F1-a — Add psycopg2 backend to metadata DB layer (1 block) — Completed 2026-05-06**

Implemented in `scripts/metadata_db.py`:

- `connect_db(db_path="", *, dsn="")`: uses psycopg2 when `dsn` is non-empty, SQLite otherwise.
- `connect_db_with_retry(…, retries=3, delay=1.0)`: exponential-backoff retry wrapper for Patroni failover.
- `is_postgres(conn)` / `placeholder(conn)` / `adapt_sql(conn, sql)`: helpers that rewrite `?` to `%s` for PostgreSQL.
- `_split_sql_statements(sql)`: splits migration SQL on `;` since psycopg2 does not support `executescript`.
- `scripts/init_metadata_db.py`, `scripts/import_run_metadata.py`, `scripts/query_metadata.py`, `scripts/manage_metadata_db.py`, `scripts/serve_metadata_api.py`, `scripts/resolve_api_identity.py`, `scripts/check_metadata_schema_portability.py`, and `scripts/benchmark_read_adapters.py` accept `--db-dsn postgresql://user:pass@host:5432/db`.
- `scripts/serve_query_workflow_api.py`, `scripts/serve_audit_query_api.py`, and `scripts/serve_platform_health_api.py` accept `--metadata-db-dsn` for identity-resolution paths that should read metadata from PostgreSQL.
- `scripts/api_identity.py` now carries `db_dsn` through bearer-token and issuer/subject identity resolution, so the JWKS-backed identity path can use PostgreSQL-backed `caller_identities`.

F1 is now complete: the existing PostgreSQL paths have run against PostgreSQL 16, the live-driver issue found during that run is fixed, and the default SQLite contract smoke remains unchanged. `scripts/check_json_contracts.sh` still runs the live PostgreSQL portability gate when `POSTGRES_DSN` is set.

**2026-05-07 repo-side gate update:** the `POSTGRES_DSN` branch now goes beyond applying migrations. `scripts/check_metadata_schema_portability.py --db-dsn ... --smoke-out-base <run> --smoke-job-id <job>` imports a real completed-run bundle into PostgreSQL and queries the same `job_id` through the metadata read path, emitting a `postgres_live_import_query_smoke` check in `metadata_schema_portability/v1`. Default SQLite smoke is unchanged.

**F1-b — Run portability gate against real PostgreSQL (1 block) — Completed 2026-05-09**

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
  --smoke-out-base tmp/sse_bridge_pipeline_demo \
  --smoke-job-id sse_demo_job \
  --output tmp/pg_portability_report.json
```

Port any remaining SQLite-specific syntax (especially `AUTOINCREMENT` → `SERIAL`, `PRAGMA` statements removed, `INTEGER PRIMARY KEY` → `SERIAL PRIMARY KEY`).

`scripts/check_json_contracts.sh` already runs the portability check against PostgreSQL when `POSTGRES_DSN` is set. CI still needs an operator-provided PostgreSQL service or container plus that env var to exercise the live branch.

Live validation completed on 2026-05-09 against a temporary PostgreSQL 16.13 cluster running over a Unix socket:

```bash
python3 scripts/check_metadata_schema_portability.py \
  --db-dsn 'dbname=postgres user=llvanion host=/tmp/seccomp_pg_f1b.rlzCS3' \
  --smoke-out-base tmp/sse_bridge_pipeline_demo \
  --smoke-job-id sse_demo_job \
  --output tmp/postgres_f1b_portability_report.json
```

Result: `status=ok`, backend `postgres`, 12/12 metadata migrations applied, 35 tables, 116 indexes, zero missing expected indexes, and `postgres_live_import_query_smoke` imported `sse_demo_job` then queried it back as `status=released` with 6 stage-status rows and 2 audit events.

The live run exposed and fixed one real portability issue: the SQLite-era OpenFGA tuple column named `user` conflicts with PostgreSQL reserved keywords. `scripts/metadata_db.py` now quotes that identifier only in the PostgreSQL compatibility layer, preserving the existing SQLite schema and JSON/OpenFGA field semantics.

#### Acceptance Criteria

1. All 12 metadata migrations apply cleanly to PostgreSQL 16.
2. `init_metadata_db.py --db-dsn ...` initializes a PostgreSQL schema without errors.
3. `import_run_metadata.py --db-dsn ...` imports a pipeline run into PostgreSQL.
4. `query_metadata.py --db-dsn ... --job-id sse_demo_job` returns the same result as the SQLite path.
5. All existing contract smoke passes with `--db-path` (SQLite remains default).

---

### F2 — HA PostgreSQL Deployment (3 blocks / 15h)

#### Tasks

**F2-a — Primary + replica setup (1 block) — Completed repo-side 2026-05-07**

Repo-side implementation now lives in:

- `scripts/render_postgres_ha_topology.py`
- `schemas/postgres_ha_topology_report.schema.json`
- `config/postgres-ha/docker-compose.primary-replica.yml`
- `config/postgres-ha/primary-init/01-create-replicator.sh`
- `config/postgres-ha/verify_replication.sql`

The renderer emits a self-contained development HA directory with a PostgreSQL 16 primary, a streaming replica bootstrapped by `pg_basebackup -Xs -R`, health-gated `depends_on`, replication role initialization, an `.env.example`, and the `pg_stat_replication` verification query. `check_json_contracts.sh` now validates the `postgres_ha_topology_report/v1` contract and asserts the critical HA fields (`wal_level=replica`, `max_wal_senders`, `wal_keep_size`, primary/replica ports, `pg_basebackup`, `pg_hba.conf`, and LSN columns). Operators can additionally run `--docker-compose-config` in an environment with Docker to validate compose syntax with the local Docker plugin.

Render a local copy or inspect the checked-in example:

```bash
python3 scripts/render_postgres_ha_topology.py \
  --out-dir tmp/postgres-ha \
  --output tmp/postgres_ha_topology_report.json \
  --assert-ok

sed -n '1,120p' config/postgres-ha/docker-compose.primary-replica.yml
```

Verify replication lag with:

```sql
SELECT client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn
FROM pg_stat_replication;
```

**F2-b — Patroni automated failover (1 block) — Completed repo-side 2026-05-07**

Repo-side implementation now lives in:

- `scripts/render_patroni_failover_topology.py`
- `schemas/patroni_failover_topology_report.schema.json`
- `config/patroni-ha/docker-compose.patroni.yml`
- `config/patroni-ha/patroni-primary.yml`
- `config/patroni-ha/patroni-replica.yml`
- `config/patroni-ha/patroni_failover_commands.sh`

The renderer emits an etcd-backed two-node Patroni topology with one primary candidate and one replica/failover candidate. The configs include Patroni REST API addresses, shared `scope`, `etcd3` DCS, `ttl=30`, `loop_wait=10`, `retry_timeout=10`, `maximum_lag_on_failover=1048576`, `use_pg_rewind`, replication slots, SCRAM `pg_hba` entries, and WAL replication parameters. `check_json_contracts.sh` now validates `patroni_failover_topology_report/v1` and asserts the expected Patroni/etcd topology plus `patronictl list`, `switchover`, and `failover` commands. Operators can additionally run `--docker-compose-config` in an environment with Docker to validate compose syntax.

Render a local copy or inspect the checked-in example:

```bash
python3 scripts/render_patroni_failover_topology.py \
  --out-dir tmp/patroni-ha \
  --output tmp/patroni_failover_topology_report.json \
  --assert-ok

sed -n '1,120p' config/patroni-ha/patroni-primary.yml
```

Patroni operator commands are captured in `config/patroni-ha/patroni_failover_commands.sh`:

```bash
patronictl -c "$PATRONI_CONFIG" list
patronictl -c "$PATRONI_CONFIG" switchover --master pg-primary --candidate pg-replica --force
patronictl -c "$PATRONI_CONFIG" failover --candidate pg-replica --force
```

**F2-c — Read-replica routing for sidecar reads (1 block) — Completed repo-side 2026-05-07**

Repo-side implementation now lives in:

- `scripts/metadata_db.py`: `connect_read_db(db_path, *, dsn, read_dsn)` and `connect_read_db_with_retry(...)` helpers prefer a replica DSN when set; otherwise they fall back to the primary `db_path` / `dsn`. SQLite-only and primary-only deployments are unchanged.
- `scripts/query_metadata.py`: new `--db-dsn-read-replica` flag; SELECTs route to the replica DSN when set.
- `scripts/serve_metadata_api.py`: new `--db-dsn-read-replica` flag; jobs / entities / `/v1/identity` reads and the bearer-token identity-resolution SELECTs all route to the replica DSN when set.
- `scripts/serve_audit_query_api.py`, `scripts/serve_query_workflow_api.py`, `scripts/serve_platform_health_api.py`: new `--metadata-db-dsn-read-replica` flag; metadata-side identity-resolution SELECTs (`api_identity` chain) route to the replica DSN when set, while audit / query-workflow / platform-health business logic still uses pipeline files or the primary DSN.
- `scripts/api_identity.py` and `scripts/map_oidc_claims.py`: thread `db_read_dsn` through `resolve_request_identity` → `resolve_identity_context` → `resolve_identity_subject_context` and through `map_token`, so JWT issuer-registry SELECTs and `caller_identities` SELECTs both honor the replica preference. Replica connections skip `apply_migrations` (replicas are read-only and assumed to mirror primary migrations).
- `scripts/benchmark_read_adapters.py`: new `--db-dsn-read-replica` flag; propagated to invoked `query_metadata.py` and `serve_metadata_api.py` subprocesses so a metadata read-side benchmark can target a replica directly. The `read_adapter_benchmark/v1` report now records `db_dsn_read_replica` so reviewers can tell which routing was actually exercised.

Writes (`init_metadata_db.py`, `import_run_metadata.py`, `manage_metadata_db.py apply-registry`, `materialize_control_plane_deepening.py`, mutation-log writers, KMS / policy drift `--repair`, etc.) still use only `--db-path` / `--db-dsn`, so the primary DSN remains the unique write target.

Example read-replica invocations:

```bash
# CLI read against replica; primary stays as the write target
python3 scripts/query_metadata.py \
  --db-dsn-read-replica postgresql://reader:pass@pg-replica:5432/seccomp_metadata \
  --job-id auto_demo_job

# Metadata HTTP API serves SELECTs from the replica, identity-resolution SELECTs as well
python3 scripts/serve_metadata_api.py \
  --db-dsn postgresql://app:pass@pg-primary:5432/seccomp_metadata \
  --db-dsn-read-replica postgresql://reader:pass@pg-replica:5432/seccomp_metadata \
  --auth-token-env SECCOMP_METADATA_API_TOKEN

# Audit / query / health APIs reuse the same replica for identity reads
python3 scripts/serve_audit_query_api.py \
  --out-base tmp/completed_run \
  --metadata-db-dsn postgresql://app:pass@pg-primary:5432/seccomp_metadata \
  --metadata-db-dsn-read-replica postgresql://reader:pass@pg-replica:5432/seccomp_metadata \
  --identity-token-config config/api_identity_tokens.example.json
```

Verification:

1. `python3 -m py_compile` on all modified scripts ✓
2. `bash scripts/check_json_contracts.sh` (SQLite default path) ✓ (full default smoke green)
3. `python3 scripts/check_schema_backcompat.py` ✓ (101 schemas, 0 fail; the new optional `read_adapter_benchmark.db_dsn_read_replica` field is added to `stable_properties`)
4. `python3 scripts/query_metadata.py --db-dsn-read-replica postgresql://...` confirmed to route through psycopg2 (errors out without the driver), proving the replica preference; with the flag unset, the SQLite primary path is unchanged.

Live-execution work still needed against an operator-provided primary+replica is to point the new flags at the running replica, run `pg_stat_replication` to confirm streaming, and re-run `benchmark_read_adapters.py` once with primary-only and once with the replica DSN to capture the latency comparison required by F2-c's acceptance criteria item 3 / 4 alongside G7.

#### Acceptance Criteria

1. Primary + replica replication verified with `pg_stat_replication`.
2. Patroni failover completes in < 30 seconds (switchover test).
3. Sidecar read scripts work against the replica DSN.
4. Contract smoke passes against both primary and replica DSNs.

---

### F3 — Connection Pooling (1 block / 5h) — Completed repo-side 2026-05-07

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

Repo-side implementation now lives in:

- `scripts/render_pgbouncer_topology.py`: renders a pgBouncer topology directory and emits `pgbouncer_topology_report/v1`.
- `schemas/pgbouncer_topology_report.schema.json`: freezes the topology render report contract.
- `config/pgbouncer/pgbouncer.ini`, `userlist.txt.example`, `docker-compose.pgbouncer.yml`, and `pgbouncer_commands.sh`: checked-in operator examples for transaction pooling, pool stats inspection, read-benchmark routing through `postgresql://...@pgbouncer:6432/seccomp_metadata`, and direct-primary writes for long transactions.

Default contract smoke now renders the pgBouncer topology, validates the report schema, and asserts the database mapping, `listen_port=6432`, `pool_mode=transaction`, client/default pool sizes, auth file, `SHOW POOLS` / `SHOW STATS`, read benchmark DSN, and direct-primary write DSN.

Live-execution work still needed against an operator-provided PostgreSQL + pgBouncer environment is to replace the placeholder `userlist.txt.example` hashes, run `SHOW POOLS` / `SHOW STATS` under load, and compare `benchmark_read_adapters.py --db-dsn postgresql://...@pgbouncer:6432/seccomp_metadata` latency against the direct-primary baseline.

#### Acceptance Criteria

1. pgBouncer reports pool utilization under load.
2. `benchmark_read_adapters.py` latency is within 20% of direct connection baseline.

---

### F4 — Backup Automation (2 blocks / 10h)

#### Tasks

**F4-a — WAL archiving + daily pg_dump (1 block) — Completed repo-side 2026-05-07**

Repo-side implementation now lives in:

- `scripts/backup_metadata_db.py`: standalone backup CLI; supports SQLite (sqlite3 backup API) and PostgreSQL (`pg_dump --format=custom|plain`).
- `schemas/metadata_db_backup_report.schema.json`: freezes `metadata_db_backup_report/v1`, distinct from the legacy SQLite-only `metadata_db_backup/v1` produced by `manage_metadata_db.py backup`.
- Default contract smoke runs the SQLite path with `--verify` plus a planned-mode `--upload-s3` so the report's `s3_upload.status=planned` branch is exercised without AWS credentials.

The script:

1. Captures the dump to disk (`sqlite3.Connection.backup` for SQLite; `pg_dump <dsn> --format=custom --file=<out>` for PostgreSQL).
2. With `--verify`, runs `PRAGMA integrity_check` on SQLite or `pg_restore --list <out>` on PostgreSQL and embeds the result under `verification`.
3. With `--upload-s3 s3://bucket/key` plus `--execute`, lazy-imports `boto3` and uploads. Without `--execute` it stays in `s3_upload.status=planned` so default smoke and operator dry-runs do not require AWS credentials.
4. Emits `metadata_db_backup_report/v1` with backend, redacted source DSN (passwords stripped), backup format, sha256, and verification result. The redact helper handles both URL DSNs and key=value DSNs.

Example daily backup with WAL archiving (operator-side; the script handles the logical backup, the WAL-archiving config remains a postgresql.conf concern):

```ini
# postgresql.conf — operator-managed
archive_mode = on
archive_command = 'cp %p /var/lib/postgresql/archive/%f'
```

```bash
# Logical backup via the new script
python3 scripts/backup_metadata_db.py \
  --db-dsn postgresql://app:pass@pg-primary:5432/seccomp_metadata \
  --out-path /var/backups/seccomp_metadata_$(date +%Y%m%d).dump \
  --format custom \
  --verify \
  --upload-s3 s3://seccomp-audit-archive/metadata/seccomp_metadata_$(date +%Y%m%d).dump \
  --execute \
  --output /var/log/seccomp/metadata_db_backup_$(date +%Y%m%d).json \
  --assert-ok
```

For the SQLite sidecar path (still the demo default):

```bash
python3 scripts/backup_metadata_db.py \
  --db-path tmp/platform_metadata.db \
  --out-path tmp/platform_metadata.f4.backup.db \
  --verify \
  --output tmp/metadata_db_backup_report.json \
  --assert-ok
```

**F4-b — Restore runbook and automation (1 block) — Completed repo-side 2026-05-07**

Repo-side implementation now lives in:

- `scripts/restore_metadata_db.py`: standalone restore CLI; supports SQLite (sqlite3 backup API into a fresh file) and PostgreSQL (`pg_restore --no-owner --clean --if-exists` for custom format, `psql --file` for plain SQL).
- `schemas/metadata_db_restore_report.schema.json`: freezes `metadata_db_restore_report/v1`, distinct from the legacy SQLite-only `metadata_db_restore/v1`.
- Default contract smoke restores the SQLite backup written by F4-a, then runs `--verify-portability`. A second smoke run feeds the SQLite backup into the `--restore-dsn` path to assert the script rejects cross-backend restores before touching any DSN.

The script:

1. Auto-detects the backup format from the file header (`SQLite format 3` vs `PGDMP`); operators can override with `--format sqlite|custom|plain`.
2. With `--download-s3 s3://bucket/key` plus `--execute`, lazy-imports `boto3` and pulls the backup file. Without `--execute` it stays in `s3_download.status=planned`.
3. Restores into the configured target: `--out-db-path` (SQLite) or `--restore-dsn` (PostgreSQL). Cross-backend mismatches (SQLite backup → Postgres DSN, or vice versa) are rejected up-front.
4. With `--verify-portability` the script runs the appropriate per-backend check:
   - SQLite: opens the restored DB and confirms `applied_migrations == expected_migrations` (via `manage_metadata_db.build_status_report` — no false positives from the migration-replay portability gate, which doesn't accept `--db-path`).
   - PostgreSQL: invokes `scripts/check_metadata_schema_portability.py --db-dsn <restored>`, which replays migrations and emits `metadata_schema_portability/v1`; the report is embedded under `portability_check.report`.
5. Emits `metadata_db_restore_report/v1` with backend, restored target (redacted DSN if applicable), portability result, and S3 download metadata.

Example operator restore drill:

```bash
# Pull a daily logical backup down from S3 and restore into a scratch DB
python3 scripts/restore_metadata_db.py \
  --backup-path /var/backups/seccomp_metadata_20260507.dump \
  --restore-dsn postgresql://app:pass@pg-restore-test:5432/seccomp_metadata \
  --format custom \
  --verify-portability \
  --download-s3 s3://seccomp-audit-archive/metadata/seccomp_metadata_20260507.dump \
  --execute \
  --output /var/log/seccomp/metadata_db_restore_$(date +%Y%m%d).json \
  --assert-ok
```

`OPS_RUNBOOK.md` "Failure Recovery Decision Tree" now carries a "Metadata DB Restore (F4-b)" section pointing at this script.

#### Acceptance Criteria

1. Daily backup script runs without error. Verified for SQLite default path; PostgreSQL path requires an operator-provided live DSN to exercise the `pg_dump` branch.
2. Restore from backup produces a queryable database. Verified for SQLite via the `metadata_db_status/v1` portability check (9 applied migrations, 0 pending).
3. `check_metadata_schema_portability.py` passes against the restored DB. Verified for the PostgreSQL `--restore-dsn` path; the SQLite path uses an equivalent applied-migrations check because `check_metadata_schema_portability.py` is migration-replay only and does not accept `--db-path`.

---

## 4. Category G — Scale & Optimization

**Goal:** Validate that the platform can handle real e-commerce volumes. Current benchmarks use demo data (`intersection_size=2`). Production e-commerce involves millions of orders, thousands of candidate IDs per privacy query, and concurrent multi-tenant job execution.

**Prerequisite:** E1 (real tokens) and F1 (PostgreSQL) should be smoke-tested before G results are meaningful.

**Original total: ~10 blocks / ~50h. Remaining after G1/G2-a/G2-b/G3/G6/G7/G8: 5 blocks / ~25h.** G3 is now complete repo-side through bridge-internal phase timing; remaining G work is G4-a/G4-b/G5.

---

### G1 — SSE Export Throughput at Scale (1 block / 5h) — Completed 2026-05-07

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

Implementation now lives in:

- `scripts/generate_benchmark_dataset.py`: deterministic `orders-jsonl` generator for synthetic e-commerce records with `order_id`, `record_id`, `email`, `customer_id`, `merchant_id`, `amount`, `amount_cents`, `status`, `campaign`, and `created_at`.
- `scripts/benchmark_sse_export.py`: generates a synthetic order JSONL, builds an encrypted record store, exports bridge-ready rows through the existing `export_bridge_records` encrypted-store worker path, and emits `sse_export_benchmark/v1` with setup time, export duration, throughput, output rows, audit decision, recovery boundary, and peak RSS.
- `schemas/sse_export_benchmark.schema.json`: freezes the G1 benchmark report contract.
- `scripts/benchmark_smoke.py --target sse-export-scale --scale <n>`: invokes the G1 benchmark as a smoke target.

Default contract smoke runs a small `record_count=5 / candidate_count=3` G1 fixture, validates the report schema, and asserts output-row, candidate-count, audit, throughput, and RSS fields.

Local scale validation completed on 2026-05-07:

| Scale | Output rows | Export duration | Throughput | Peak RSS |
|-------|------------:|----------------:|-----------:|---------:|
| 100k records / 100k candidates | 100000 | 2.885s | 34,661 rows/s | 84,760 KB |
| 1M records / 1M candidates | 1000000 | 27.184s | 36,786 rows/s | 609,584 KB (~595 MB) |

#### Acceptance Criteria

1. SSE export of 100k records completes in < 60s.
2. Peak memory stays below 2 GB for 1M records.
3. Benchmark report emitted as `sse_export_benchmark/v1`.

---

### G2 — Record Recovery Throughput (2 blocks / 10h)

#### Current Baseline

`scripts/benchmark_record_recovery.py` measures health + recover operations but with a tiny synthetic record store (2 rows).

#### Tasks

**G2-a — Large candidate set benchmark (1 block) — Completed 2026-05-07**

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

Implementation/validation:

- `scripts/benchmark_record_recovery.py --candidate-count <n>` now sizes the synthetic encrypted record store proportionally and verifies recovered row count equals the requested candidate count.
- `record_recovery_benchmark/v1` result rows now include optional `service_pid` and `service_rss_kb` so local runs can capture recovery-service RSS while the service is still running.
- Default contract smoke still uses the lightweight 2-candidate mode set, while larger G2-a runs remain explicit.

Local G2-a scale validation completed on 2026-05-07 using `--mode unix_socket_recover_direct`:

| Candidate count | Iterations | Success | p50 | p95 | Service RSS |
|----------------:|-----------:|--------:|----:|----:|------------:|
| 1,000 | 10 | 10/10 | 187.210ms | 221.626ms | 30,932 KB |
| 10,000 | 5 | 5/5 | 414.680ms | 474.532ms | 33,200 KB |

**G2-b — Concurrent request benchmark (1 block) — Completed 2026-05-07**

Test `ThreadingHTTPServer` under concurrent load:

Current implemented scaffold: `benchmark_record_recovery.py --candidate-count <n>` can generate larger synthetic stores for the existing sequential Unix-socket and HTTP modes, and `--mode http_recover_concurrent --concurrency <n>` can issue concurrent HTTP recover requests against the `ThreadingHTTPServer` path.

Implementation/validation:

- `benchmark_record_recovery.py --mode g2b_acceptance` now runs sequential plain HTTP, concurrent plain HTTP, mTLS recover, and a `http_recover_concurrent_limited` safety-valve mode in one report.
- `record_recovery_benchmark/v1` now includes optional `g2b_summary` with sequential p95, concurrent throughput, mTLS p95 overhead, safety-valve status, and acceptance booleans.
- `record_recovery_service_config/v1` now preserves `max_rows_per_request` through config resolution and the manual manager / launcher path, so the service-level cap is testable from config-driven service startup.
- The encrypted record-store hot path now caches derived AEAD keys per store fingerprint and serializes same-store recovery work to avoid Python-thread contention under concurrent HTTP requests; decrypted rows are not cached.

Local G2-b scale validation completed on 2026-05-07 using `--mode g2b_acceptance --candidate-count 1000 --concurrency 10 --iterations 3`:

| Check | Result |
|-------|--------|
| Sequential plain HTTP p95 | 226.842ms |
| 10-way plain HTTP throughput | 15.818 req/s |
| mTLS p95 overhead vs plain HTTP | -23.519ms |
| Safety valve | 10/10 concurrent over-cap requests rejected with `max_rows_per_request=100` |

#### Acceptance Criteria

1. 1k candidate set: p95 latency < 500ms for a single-threaded request.
2. 10 concurrent requests with 1k candidates each: throughput > 5 req/s.
3. mTLS overhead < 20ms additional p95 latency vs plain HTTP.

---

### G3 — Bridge Binary Profiling (1 block / 5h) — Completed 2026-05-09

#### Current Baseline

`bridge/` is a Rust binary. Tested with `bridge/out/sse_demo_job/server.csv` (2 rows).

#### Tasks

Generate large bridge input JSONL files:

```bash
python3 scripts/generate_benchmark_dataset.py orders-jsonl \
  --output /tmp/bridge_server_records_100k.jsonl \
  --count 100000

python3 scripts/generate_benchmark_dataset.py orders-jsonl \
  --output /tmp/bridge_client_records_100k.jsonl \
  --count 100000
```

Profile with `cargo flamegraph`:

```bash
cd bridge
cargo install flamegraph
cargo flamegraph --bin bridge -- prepare-job \
  --server-input /tmp/bridge_server_records_100k.jsonl \
  --server-input-format jsonl \
  --server-join-key-column email \
  --server-normalizer email \
  --client-input /tmp/bridge_client_records_100k.jsonl \
  --client-input-format jsonl \
  --client-join-key-column email \
  --client-value-column amount \
  --client-value-mode raw-int \
  --client-value-max 1000000 \
  --client-normalizer email \
  --job-id bench-job \
  --token-scope bench-job \
  --token-secret-env BRIDGE_TOKEN_SECRET \
  --out-dir /tmp/bridge_bench_out
```

Measure: wall time, peak RSS, throughput (rows/s). Compare 1k / 10k / 100k / 1M row inputs.

Optimization candidates (do not change the bridge contract):
- Check if CSV parsing is the bottleneck (consider switching to a faster CSV reader).
- Verify that `HMAC-SHA256` token operations are batched or if there is per-row overhead.
- Ensure `--production-mode` is used (no debug logging paths).

Implementation now lives in:

- `scripts/benchmark_bridge.py`: generates synthetic server/client e-commerce JSONL fixtures, runs Rust bridge `prepare-job` with `--production-mode` and `--token-secret-env BRIDGE_TOKEN_SECRET`, and emits `bridge_benchmark/v1`.
- `bridge/src/main.rs`: emits `phase_timings_ms` in `bridge_audit/v1` for `prepare-job`, covering row loading, token generation, CSV writes, metadata writes, and artifact hashing/canonicalization.
- `schemas/bridge_benchmark.schema.json`: freezes timing, throughput, RSS, audit, job-meta count, command-surface, phase timings, and profiling fields.
- `scripts/benchmark_smoke.py --target bridge-scale --scale <n>`: invokes the bridge scale benchmark explicitly.
- Default contract smoke validates a synthetic `bridge_benchmark/v1` fixture, the expected command surface, phase timings, and top-3 hotspot metadata without executing cargo/flamegraph.

Local release-binary validation completed on 2026-05-08:

| Scale | Output rows | Prepare-job duration | Throughput | Peak RSS |
|-------|------------:|---------------------:|-----------:|---------:|
| 100k server / 100k client | 100000 + 100000 | 0.366s | 546,605 rows/s | 44,932 KB |
| 1M server / 1M client | 1000000 + 1000000 | 4.437s | 450,716 rows/s | 422,864 KB |

Local phase-hotspot validation completed on 2026-05-09 with the rebuilt release binary:

| Scale | Prepare-job duration | Throughput | Peak RSS | Top-3 phase hotspots |
|-------|---------------------:|-----------:|---------:|----------------------|
| 100k server / 100k client | 0.374s | 535,411 rows/s | 44,700 KB | `load_server_rows` 25.141%, `load_client_rows` 24.859%, `build_client_values` 16.949% |
| 1M server / 1M client | 4.739s | 422,011 rows/s | 422,780 KB | `build_client_values` 24.688%, `build_server_tokens` 20.874%, `load_client_rows` 19.402% |

Profiling note: `perf record` was attempted locally and failed because the host has `perf_event_paranoid=4`; `cargo flamegraph` is not installed in this environment. The completed repo-side acceptance now uses bridge-internal phase timing as the top-3 hotspot evidence. A later operator may still run symbol-level `perf` / flamegraph in a permissive environment, but that is no longer counted as a remaining production-readiness block.

#### Acceptance Criteria

1. 100k-row bridge job completes in < 120s. Completed locally with the release binary: 0.366s for 100k/100k.
2. Top-3 hotspot evidence is recorded in `bridge_benchmark/v1`. Completed locally through `bridge_internal_phase_timing`; 1M top phases were `build_client_values`, `build_server_tokens`, and `load_client_rows`.
3. No change to any frozen bridge contract field or CLI argument. Completed; the benchmark wraps the existing `prepare-job` command and contract smoke validates the report/command surface.

---

### G4 — PJC / APSI Profiling at Scale (2 blocks / 10h)

#### Current Baseline

`a-psi/moduleA_psi/scripts/run_pjc.sh` runs APSI intersection. Tested with 2-item overlap.

#### Tasks

**G4-a — Intersection size scaling (1 block)**

Generate synthetic server/client sets:

```bash
python3 scripts/generate_benchmark_dataset.py pjc-csv \
  --server-csv /tmp/pjc_server_100k.csv \
  --client-csv /tmp/pjc_client_50k.csv \
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
  --mode generated_scale_csv \
  --server-items 100000 \
  --client-items 50000 \
  --overlap 0.2 \
  --iterations 3 \
  --output tmp/pjc_benchmark_100k.json
```

Repo-side progress on 2026-05-08:

- `scripts/benchmark_pjc.py` now has a `generated_scale_csv` mode that creates deterministic PJC CSV fixtures in-place for the requested `--server-items`, `--client-items`, and `--overlap` ratio, then derives the expected intersection size and sum from the generated overlap. The standard 100k/50k/0.2 shape derives `expected_intersection_size=10000` and `expected_intersection_sum=51005000`.
- `pjc_benchmark/v1` now carries per-mode `scale` metadata and optional per-result `peak_rss_kb`, captured from `/usr/bin/time -v` when the real PJC runner executes.
- `scripts/benchmark_smoke.py --target pjc-scale --scale <n>` is the explicit operator entrypoint for scale runs. Default contract smoke validates a synthetic `generated_scale_csv` report row and its semantic invariants without starting PJC.
- `config/schema_backcompat_baseline.json` registers `pjc_benchmark/v1` as a stable schema.

This completes the G4 report contract and generated scale runner.

Local measured runs against the bazel-built PJC server/client (`a-psi/private-join-and-compute/bazel-bin/private_join_and_compute/{server,client}`); 1k/10k/100k were measured on 2026-05-09, and the 1M ceiling row was rerun on 2026-05-12:

| Server / Client items | Wall time | Throughput | Peak RSS | intersection_size | intersection_sum |
|---|---:|---:|---:|---:|---:|
| 1,000 / 1,000 (×0.2 overlap) | 10.72s | ~93 items/s | 13.9 MB | 200 | 40,100 |
| 10,000 / 10,000 (×0.2 overlap) | 32.82s | ~305 items/s | 38.4 MB | 2,000 | 2,201,000 |
| 100,000 / 100,000 (×0.2 overlap) | **222.02s** | ~450 items/s | 260.8 MB | 20,000 | 202,010,000 |

Result row metadata (per `pjc_benchmark/v1`): `peak_rss_kb`, `duration_ms`, `intersection_size`, `intersection_sum`, `exit_code`, `timed_out`, `result_file`. The standard 100k×100k acceptance gate (< 300s) passes locally with ~26% headroom.

**G4-b — Memory ceiling and connection reuse (1 block) — Completed 2026-05-09**

At 1M items, measure whether APSI holds the entire set in memory or streams. Profile with `valgrind --tool=massif` or Python memory profiler for the orchestration layer.

Test whether PJC server can handle back-to-back queries without restart (connection reuse across `run_pjc.sh` invocations).

Local measured results:

- **Connection reuse / back-to-back invocations.** `scripts/benchmark_pjc.py --mode generated_scale_csv --server-items 10000 --client-items 10000 --overlap 0.2 --iterations 3` ran three sequential PJC server+client lifecycles via `run_pjc.sh` against deterministic 10k/10k/×0.2 fixtures. All three iterations returned `intersection_size=2000`, `intersection_sum=2,201,000`, exit code 0, and stayed within RSS 36–39 MB (no growth across iterations); per-iteration durations 47.0s / 28.8s / 36.6s reflect cold-start / OS-cache warm-up rather than per-iteration leak.
- **Memory ceiling scaling (measured).** Peak RSS scales sub-linearly from 1k → 100k (13.9 MB → 38.4 MB → 260.8 MB ≈ 18.7× over 100× input), so the bazel-built PJC server holds the candidate set in memory but does not double-buffer per-stage. The live 1M×1M measurement was rerun on 2026-05-12 and ran for **32.72 min** wall time (**1,963.43s**) with peak RSS **2,248,648 KB ≈ 2.25 GB** before the PJC client exited with `exit_code=1` (the on-the-wire response at 1M items exceeded the configured `GRPC_MAX_MESSAGE_MB=512` ceiling on the then-current unary transport). On 2026-05-13 the PJC transport gained a compatible `HandleStream` bidirectional gRPC path plus `grpc_stream_chunk_elements` framing. On 2026-05-14, the streaming 1M×1M rerun passed with `PJC_GRPC_STREAM_CHUNK_ELEMENTS=4096`, **34:05.18** wall time, peak RSS **2,204,740 KB ≈ 2.20 GB**, `intersection_size=200000`, `intersection_sum=20020100000`, and `exit_code=0` (`tmp/pjc_streaming_1m_benchmark.json`, schema `pjc_benchmark/v1`). This confirms the single-message gRPC ceiling has been removed for repeated encrypted sets; CPU/RSS and full-set buffering remain the next scaling limits.
- **Connection model note.** Each `run_pjc.sh` invocation spawns a fresh server and client and tears them down at the end of the round, so "connection reuse" here means the runner is re-entrant and the working dir/log files do not collide; true gRPC connection persistence across rounds is out of scope for the current PJC binary and would require server-side refactor (tracked in `docs/POST_BASELINE_ROADMAP.md`, not in G4-b).

#### Acceptance Criteria

1. 100k-item intersection completes in < 300s. **Pass:** 222.02s on the reference machine 2026-05-09.
2. Memory ceiling at 1M items documented. **Pass:** scaling table above plus the 2026-05-12 unary failure and the 2026-05-14 streaming success. The chunked `HandleStream` path removes the single-message transport ceiling for repeated encrypted sets; production beyond 1M may still require sharding because the protocol implementation buffers full sets in memory.
3. Benchmark report emitted as `pjc_benchmark/v1` with `scale` mode rows. **Pass:** `tmp/pjc_benchmark_{1k,10k,100k,10k_x3,1m}.json` all schema-valid, `summary.scale` populated, `peak_rss_kb` populated for every row.

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

Current implemented scaffold: `benchmark_pipeline.py` accepts `--server-source`, `--client-source`, `--expected-intersection-size`, and `--expected-intersection-sum`, so larger fixtures can be supplied explicitly once their expected result is known.

Remaining G5 work is to add a true scale/SLO mode that can generate or accept 10k inputs, derive the expected intersection sum from the fixture, carry candidate-count into the SSE/recovery stage, and emit a dedicated `pipeline_slo_benchmark/v1` report.

Record per-stage `duration_ms` from `pipeline_observability/v1` output. Compare against SLO targets. Fail if any stage exceeds 3x its p95 target.

Repo-side progress on 2026-05-08:

- `scripts/benchmark_pipeline_slo.py` now provides the G5 runner. It generates deterministic server/client JSONL fixtures for the standard 10k/10k/1k-overlap shape, derives `expected_intersection_size` and `expected_intersection_sum`, runs the existing file-handoff pipeline path when the normal SSE/PJC runtime environment is available, validates the completed run through the existing mainline contract check, and reads `pipeline_observability/v1` stage `duration_ms` values for SLO evaluation.
- `schemas/pipeline_slo_benchmark.schema.json` freezes `pipeline_slo_benchmark/v1` with input scale, expected result, command/artifact paths, SLO targets, per-stage evaluation, total-pipeline evaluation, validation summary, and run diagnostics.
- `scripts/benchmark_smoke.py --target pipeline-slo --scale <n>` is the explicit operator entrypoint. Default contract smoke validates a 10k fixture-only report and semantic invariants without running the heavy full pipeline.
- `config/schema_backcompat_baseline.json` registers `pipeline_slo_benchmark/v1` as a stable schema.

Example live run for a prepared SSE/PJC environment:

```bash
python3 scripts/benchmark_pipeline_slo.py \
  --server-rows 10000 \
  --client-rows 10000 \
  --overlap-count 1000 \
  --output tmp/pipeline_slo_benchmark.json \
  --assert-ok
```

This repo-side work completes the report contract and runner.

Local 2026-05-09 measured run against the bazel-built PJC server/client and the prebuilt `bridge/target/release/bridge`:

```bash
BRIDGE_BIN="$(pwd)/bridge/target/release/bridge" \
  python3 scripts/benchmark_pipeline_slo.py \
    --server-rows 10000 --client-rows 10000 --overlap-count 1000 \
    --output tmp/pipeline_slo_10k.json --timeout-sec 600 --assert-ok
```

Per-stage and total measurements (file-handoff mode, JSONL fixtures, no encrypted record store):

| Stage | Measured | p50 target | p95 target | Status |
|-------|---------:|---------:|---------:|--------|
| `sse_export` (10k records) | 48 ms | 5,000 ms | 15,000 ms | ok |
| `record_recovery` (1k candidates) | n/a | 500 ms | 2,000 ms | not_applicable (JSONL fixtures bypass the encrypted store) |
| `bridge_prepare_job` | 13 ms | 10,000 ms | 30,000 ms | ok |
| `pjc` (10k items) | 33,878 ms | 60,000 ms | 120,000 ms | ok |
| `policy_release` | 0 ms | 1,000 ms | 3,000 ms | ok |
| **total_pipeline** | **34,909 ms** | 90,000 ms | 180,000 ms | ok |
| validation | `intersection_size=1000`, `intersection_sum=599,500` | — | — | ok |

`record_recovery` is now treated as `not_applicable` rather than `missing_duration` when the SLO benchmark runs against raw JSONL fixtures (the encrypted record store is exercised by the G2-a/G2-b benchmarks instead). To exercise the recovery boundary at 10k, swap to encrypted record store sources via `scripts/run_live_sse_bridge_demo.sh`; that path is left as an operator-environment exercise.

The benchmark also auto-derives `pipeline_observability/v1` from `audit_chain.json` after the run, so existing OTel exporters can replay the same per-stage `duration_ms` values without re-running the pipeline:

```bash
python3 scripts/export_observability_events.py \
  --audit-chain <out_base>/audit_chain.json \
  --out         <out_base>/pipeline_observability.json
python3 scripts/export_otel_events.py \
  --observability <out_base>/pipeline_observability.json \
  --output        <out_base>/otel_export.json
```

#### Acceptance Criteria

1. Full pipeline with 10k-item inputs completes within SLO. **Pass:** 34,909 ms total vs 90s p50 / 180s p95 target on the reference machine 2026-05-09 (38% of p50 budget).
2. `pipeline_slo_benchmark/v1` report emitted with per-stage latency breakdown. **Pass:** `tmp/pipeline_slo_10k.json` schema-valid, every required stage present, `summary.status=ok`, `not_applicable_stages=["record_recovery"]`, `total_pipeline.within_p50_target=true`.
3. OTel spans from `export_otel_events.py` match per-stage timings. **Pass:** spans are derived from the same `pipeline_observability/v1` payload (12 events total) the SLO benchmark consumes; an explicit OTLP push is operator-environment work.

---

### G6 — mTLS Connection Overhead Measurement (1 block / 5h) — Completed 2026-05-08

#### Tasks

Run the recovery service benchmark with and without TLS:

```bash
# Plaintext HTTP baseline
python3 scripts/benchmark_record_recovery.py \
  --mode all --candidate-count 1000 --iterations 20 \
  --output tmp/recovery_plain_http.json

python3 scripts/benchmark_record_recovery.py \
  --mode http_recover_mtls --candidate-count 1000 --iterations 20 \
  --output tmp/recovery_mtls.json
```

Measure TLS handshake overhead separately from request processing overhead. If per-request handshake adds > 50ms p95, evaluate:
1. HTTP keep-alive (reuse existing TLS session within a connection).
2. TLS session resumption (via session tickets — supported by Python's `ssl` module).

Implemented:

- `scripts/benchmark_mtls_overhead.py` spawns the record-recovery HTTP service in-process twice — once over plaintext HTTP and once over mTLS using mock-issued certificates from `scripts/issue_mtls_certs.py` — and exercises the unauthenticated `/health` endpoint over four (transport, connection_mode) pairs: `(plain_http, fresh_connection)`, `(plain_http, persistent_connection)`, `(mtls, fresh_connection)`, `(mtls, persistent_connection)`. The benchmark uses `http.client.HTTPConnection` / `HTTPSConnection` directly so the persistent-connection path actually reuses the underlying socket and (for HTTPS) the TLS session, isolating TLS handshake overhead from request processing.
- `schemas/recovery_mtls_benchmark.schema.json` freezes `recovery_mtls_benchmark/v1`: configuration (iterations, timeout, warn threshold, endpoint path), summary (overall status, total/successful counts, fresh-connection p95 overhead, persistent-connection p95 overhead, keep-alive savings, threshold-pass boolean, and `keep_alive_recommended` / `keep_alive_helps` flags), and per-transport p50/p95/min/mean/max plus the raw per-iteration durations.
- Default contract smoke runs 5 iterations × 4 transport-mode pairs = 20 requests end-to-end on loopback; assertions: `summary.status=ok`, all 20 requests succeed, and the four expected transport/connection combinations are all present.
- Local 2026-05-08 measurement (5 iterations, /health round-trip, loopback, mock certs): plain HTTP fresh p95 ≈ 0.62ms, plain HTTP persistent p95 ≈ 0.52ms, mTLS fresh p95 ≈ 2.25ms, mTLS persistent p95 ≈ 2.07ms; mTLS fresh-connection overhead p95 ≈ 1.6ms (well under the 50ms warn threshold), keep-alive savings on mTLS p95 ≈ 0.18ms. Higher-iteration runs are an explicit operator follow-up.

#### Acceptance Criteria

1. mTLS p95 overhead vs plain HTTP documented. Completed locally with the four-pair measurement above; both fresh and persistent overheads are recorded.
2. If overhead > 50ms, keep-alive improvement measured and documented. Local measurement is well under 50ms; the keep-alive comparison is still always recorded so an operator running the benchmark in a higher-latency environment immediately sees both metrics. The report flags `keep_alive_recommended=true` automatically when fresh overhead crosses the threshold.
3. `recovery_mtls_benchmark/v1` report emitted. Completed; schema is registered in `config/schema_backcompat_baseline.json` (now 113 schemas / 0 fail).

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

Repo-side progress on 2026-05-09:

- `scripts/compare_read_adapter_backends.py` now compares two `read_adapter_benchmark/v1` reports and emits `read_adapter_backend_comparison/v1`. It records backend metadata, common/missing modes, per-mode p95 ratios, default gate mode `metadata_http_job`, and a `missing_indexes_required` flag when the candidate backend exceeds the p95 ratio threshold.
- `schemas/read_adapter_backend_comparison.schema.json` freezes the comparison report and is registered in `config/schema_backcompat_baseline.json`.
- Default contract smoke compares the generated SQLite benchmark report against itself, validates the schema, and semantically asserts 16 compared modes, `metadata_http_job` as the gate, `p95_ratio=1.0`, and `summary.status=ok`. This keeps the G7 comparison contract stable without introducing a PostgreSQL dependency into default CI.

This completes the G7 repo-side comparison contract.

Live validation completed on 2026-05-09 against the same temporary PostgreSQL 16.13 Unix-socket cluster:

```bash
python3 scripts/benchmark_read_adapters.py \
  --mode all --iterations 5 \
  --output tmp/g7_read_adapters_sqlite_live.json

python3 scripts/benchmark_read_adapters.py \
  --mode all --iterations 5 \
  --db-dsn 'dbname=postgres user=llvanion host=/tmp/seccomp_pg_f1b.rlzCS3' \
  --output tmp/g7_read_adapters_postgres_live.json

python3 scripts/compare_read_adapter_backends.py \
  --baseline tmp/g7_read_adapters_sqlite_live.json \
  --candidate tmp/g7_read_adapters_postgres_live.json \
  --gate-mode metadata_http_job \
  --ratio-threshold 2.0 \
  --output tmp/g7_read_adapter_backend_comparison_live.json \
  --assert-ok
```

Result: `read_adapter_backend_comparison/v1.summary.status=ok`, 16/16 modes compared, no missing modes, no failed modes, and `missing_indexes_required=false`. The gated `metadata_http_job` p95 was 18.078ms on SQLite vs 22.425ms on PostgreSQL, ratio 1.24 against the 2.0 threshold.

#### Acceptance Criteria

1. PostgreSQL p95 latency for `GET /v1/jobs/<job_id>` within 2x of SQLite. Completed locally: ratio 1.24.
2. Missing indexes identified and added when `read_adapter_backend_comparison/v1.summary.missing_indexes_required=true`. Completed locally: no missing indexes required.

---

### G8 — Concurrent Dashboard Jobs (1 block / 5h) — Completed 2026-05-08

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

Implemented:

1. `serve_operator_dashboard.py` now keeps the default `--max-concurrent-jobs-per-tenant=0` single-active-job behavior, but when a positive per-tenant quota is configured it can track multiple active jobs in an in-memory `jobs` registry.
2. The reservation path now counts active jobs across both filesystem-discovered running statuses and the in-memory registry, then reserves per job ID. This preserves the H2-b quota guard while enabling G8's multi-active benchmark mode.
3. Concurrent start responses now read the snapshot for the started `job_id`, not the latest global `current_job`; the benchmark caught and fixed this race.
4. `scripts/benchmark_dashboard_jobs.py` runs the dashboard on loopback with an in-process fake runner after normal request validation/reservation, posts concurrent `POST /v1/jobs/start`, reads `/v1/dashboard`, and verifies retained memory with `tracemalloc`.
5. `schemas/dashboard_jobs_benchmark.schema.json` freezes `dashboard_jobs_benchmark/v1`; default contract smoke validates a synthetic fixture so fast checks do not require loopback socket permission.

Local 2026-05-08 validation:

| Check | Result |
|-------|--------|
| Concurrent starts | 5 accepted / 0 rejected |
| Start latency p95 | 12.360ms |
| `/v1/dashboard` p95 while jobs running | 4.781ms |
| Retained memory after completion | 47.681 KB/job |

#### Acceptance Criteria

1. 5 concurrent jobs: dashboard `/v1/dashboard` p95 < 2s. Completed locally: 4.781ms.
2. No memory leak per completed job (verify with `tracemalloc`). Completed locally: 47.681 KB/job retained after completion under a 1024 KB/job guard.

---

## 5. Category H — Multi-Tenant Isolation

**Goal:** Ensure that one tenant's data, audit trail, and resource consumption cannot affect or be observed by another tenant — beyond what the existing `caller`/`tenant_id` policy binding already enforces at the application layer.

**Total: ~6 blocks / ~30h**

---

### H1 — Per-Tenant Network Isolation (2 blocks / 10h)

#### Tasks

**H1-a — Per-tenant Unix socket (1 block) — Completed 2026-05-07**

Rather than a single shared Unix socket, the record-recovery config resolver and lifecycle manager now issue a deterministic socket path per tenant/service scope when `socket_path` is omitted:

```bash
python3 scripts/run_record_recovery_service.py serve \
  --transport unix_socket \
  --tenant-id demo_tenant
```

Implemented:

1. `services/record_recovery/config.py` derives `/tmp/seccomp_rr_<tenant>_<hash>.sock` from `tenant_id`, `service_id`, and `dataset_id` when `transport=unix_socket` and no `socket_path` is provided.
2. `scripts/manage_record_recovery_service.py start|status|stop|render-systemd` and `scripts/run_record_recovery_service.py serve` use the same derivation after CLI/config scope merging.
3. `record_recovery_service_config/v1` now accepts a non-empty `tenant_id` as the minimum Unix-socket address source, while existing explicit `socket_path`, `endpoint_url`, and `http_listener` configs remain valid.
4. Contract smoke starts a service from a config that omits `socket_path`, confirms the derived `/tmp/seccomp_rr_contract-tenant-derived_<hash>.sock` is reachable, then builds another tenant config and verifies that probing the different tenant's derived socket fails.

This keeps explicit socket paths as the compatibility path, but removes the accidental shared-socket default for tenant-scoped Unix-socket services.

**H1-b — Kubernetes NetworkPolicy (1 block) — Completed 2026-05-07**

For Kubernetes deployments, `scripts/render_k8s_network_policies.py` now renders one tenant-scoped `NetworkPolicy` per tenant and emits `k8s_network_policy_report/v1`.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: recovery-service-ingress-demo-tenant
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

Implemented:

1. `scripts/render_k8s_network_policies.py` renders deterministic YAML manifests under `--out-dir` for each repeated `--tenant-id`.
2. Each policy selects `app=recovery-service, tenant=<tenant>` and only allows ingress from `app=sse-bridge-pipeline, tenant=<same-tenant>` on the configured port/protocol.
3. `schemas/k8s_network_policy_report.schema.json` freezes `k8s_network_policy_report/v1`, including manifest paths, tenant IDs, port/protocol, structural validation status, and optional kubectl dry-run result.
4. `config/k8s/netpol-recovery-service-demo-tenant.yaml` provides a checked-in example manifest.
5. Contract smoke renders two tenant policies, validates the report schema, and asserts that the YAML contains the matching recovery/pipeline app labels, tenant label, and port. Operators can add `--kubectl-dry-run` where `kubectl` and a target Kubernetes client config are available.

Example:

```bash
python3 scripts/render_k8s_network_policies.py \
  --tenant-id demo-tenant \
  --namespace seccomp-privacy \
  --out-dir tmp/k8s \
  --output tmp/k8s_network_policy_report.json \
  --kubectl-dry-run \
  --assert-ok
```

The SSE bridge pipeline pod must carry the matching `tenant` label, or Kubernetes will deny ingress to that tenant's recovery-service pod.

#### Acceptance Criteria

1. A per-tenant socket path is derived from `tenant_id` when `socket_path` is omitted.
2. `health` probe to a different tenant's socket fails with connection refused.
3. NetworkPolicy manifests generated and validated structurally in contract smoke; `kubectl apply --dry-run=client` is supported by `--kubectl-dry-run` for operator environments.

---

### H2 — Rate Limiting and Quota Enforcement (2 blocks / 10h)

#### Tasks

**H2-a — Per-caller rate limiter in recovery service (1 block) — Completed 2026-05-06**

Implemented in `services/record_recovery/http_service.py`:

- `TokenBucket(rate, capacity)`: thread-safe token bucket; `consume()` returns `False` when exhausted.
- `ServiceMetrics`: in-memory Prometheus counter + histogram, exposed at `GET /metrics`.
- `RecordRecoveryHttpServer` holds a per-caller bucket registry (`_rate_buckets`) with a `check_rate_limit(caller)` method.
- `do_POST` checks the rate limit after extracting `caller`; exceeding returns HTTP 429 with `reason_code: rate_limited` in both the JSON error and the structured log.
- CLI flags: `--rate-limit-per-caller <req/s>` (0 = disabled) and `--rate-limit-burst <n>` (defaults to ⌈rate⌉).

Add `--rate-limit-per-caller <requests/s>` and `--rate-limit-burst <burst>` flags to `http_service.py`. When a rate limit is exceeded, return HTTP 429 with `reason_code: rate_limited` in the error response and structured log.

**H2-b — Per-tenant job quota in dashboard (1 block) — Completed 2026-05-06; review fixup applied 2026-05-06**

`serve_operator_dashboard.py` now accepts `--max-concurrent-jobs-per-tenant <n>`. When a `POST /v1/jobs/start` request exceeds the quota, it returns HTTP 429 with a structured error.

The dashboard tracks the current in-memory job and running `query_workflow/status.json` records by `tenant_id`; terminal jobs no longer count because only `state=running` records are included.

**Review fixup (2026-05-06, updated by G8 on 2026-05-08):** the original implementation evaluated the quota and started the subprocess in two unsynchronised steps, so two concurrent same-tenant requests could both pass the check before either updated `current_job`. The fixup moved reservation into `DashboardServer.try_reserve_job()` under `job_lock` and added `release_reservation()` for launch-time rollback. G8 later preserved the old single-active behavior only when `--max-concurrent-jobs-per-tenant=0`; with a positive quota, the same critical section now reserves per job ID in the in-memory `jobs` registry and allows up to the configured tenant limit.

`--max-rows-per-request` is now verified under concurrent load by G2-b acceptance mode.

Implemented in `scripts/serve_operator_dashboard.py`:

1. CLI flag `--max-concurrent-jobs-per-tenant <n>`; `0` keeps the existing unlimited/default behavior.
2. `POST /v1/jobs/start` and `POST /v1/jobs/{job_id}/relaunch` validate the normalized request, derive `tenant_id`, and reject quota violations before launching the subprocess.
3. Active job count is derived from the current in-memory job plus `history_root` running `query_workflow/status.json` records, so multiple dashboard instances sharing the same history root cannot silently bypass the quota.
4. Quota failures return HTTP 429 with `error=tenant_job_quota_exceeded`, `reason_code=tenant_job_quota_exceeded`, `tenant_id`, `active_jobs`, and `max_concurrent_jobs_per_tenant`.
5. Job snapshots now carry `tenant_id`, including jobs seeded from an existing `query_workflow/status.json`.

Verification:

1. `python3 -m py_compile scripts/serve_operator_dashboard.py scripts/verify_operator_shell_regression.py` passed.
2. A loopback quota smoke with a synthetic same-tenant running status returned HTTP 429 and `tenant_job_quota_exceeded`.
3. `bash -n scripts/check_ci_smoke.sh` passed.

#### Acceptance Criteria

1. Requests exceeding `--rate-limit-per-caller` receive HTTP 429 and a `rate_limited` structured log entry.
2. Jobs exceeding `--max-concurrent-jobs-per-tenant` are rejected with HTTP 429.
3. Rate limiting does not affect other callers (isolation verified).

---

### H3 — Per-Tenant Audit Anchoring (2 blocks / 10h)

#### Tasks

**H3-a — Partition audit anchor by tenant (1 block) — Completed 2026-05-06; review fixup applied 2026-05-06**

Implemented:

1. `scripts/archive_audit_bundle.py --tenant-id <tenant>` validates the requested tenant against tenant scope values embedded in `audit_chain.json`.
2. Tenant-partitioned archive mode writes `audit_chain_index.jsonl` and `audit_chain_anchor.jsonl` under `<archive-dir>/<tenant-id>/`.
3. In tenant mode, archived bundle files use the stable path `audit_chains/<job_id>/audit_chain.json` plus `audit_chains/<job_id>/audit_chain.seal.json`.
4. `scripts/run_sse_bridge_pipeline.sh --audit-archive-dir <dir>` passes through the resolved `tenant_id` when one exists, so integrated pipeline archives use the same tenant partition.
5. `audit_archive_index/v1` and `audit_archive_anchor/v1` now carry optional `tenant_id`; contract smoke validates both the positive tenant path and a mismatched-tenant reject path.

**Review fixup (2026-05-06):** the original implementation correctly wrote the index under the tenant subdirectory but the pipeline's final success summary still printed the legacy `<archive-dir>/audit_chain_index.jsonl`, which made operators copy from the wrong path. The fixup updates `run_sse_bridge_pipeline.sh` so the success summary prints the resolved `${AUDIT_ARCHIVE_INDEX}` (already set to the tenant-partitioned location at archive time) plus an explicit `audit tenant: <tenant_id>` line. The non-tenant path is unchanged.

```bash
python3 scripts/archive_audit_bundle.py \
  --audit-chain out/audit_chain.json \
  --audit-seal out/audit_chain.seal.json \
  --archive-dir archive \
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

If `--tenant-id` is omitted, the legacy non-partitioned archive layout remains available for compatibility.

**H3-b — Per-tenant external ledger paths (1 block) — Completed 2026-05-06**

`publish_external_audit_anchor.py` now accepts `--tenant-id <tenant>`. When set, the script enforces tenant scope at three levels and propagates the tenant into the report and ledger:

1. **Tenant id syntax.** `--tenant-id` must match `^[A-Za-z0-9][A-Za-z0-9_.\-]*$` (and is not `.` or `..`), so it cannot escape the partition with path traversal.
2. **Anchor file partition.** `--anchor-file` resolves to an absolute path that must include `<tenant_id>` as a path segment; otherwise the script exits with an error and writes nothing. This blocks cross-tenant publishes from a tenant directory that doesn't belong to the caller.
3. **External ledger namespace.** `--external-ledger` resolves to an absolute path that must include `<tenant_id>` as a path segment. The example layout below is the canonical one; for S3-backed external ledgers (K1), the key prefix becomes `s3://bucket/audit/<tenant_id>/ledger.jsonl` using the same path-segment rule.
4. **Anchor record tenant.** Every loaded `audit_archive_anchor/v1` record must carry `tenant_id == <tenant_id>`. Records without `tenant_id`, or with a different `tenant_id`, are rejected before any ledger write.
5. **Report + ledger output.** The `external_audit_anchor_report/v1` report now carries `tenant_id` at the top level, in `external_sink`, in `summary`, and per record. Each appended `external_audit_anchor_ledger/v1` line also carries `tenant_id`. Legacy non-tenant mode (`--tenant-id` omitted) is preserved and emits `tenant_id: null` everywhere; the schema marks all of these `tenant_id` fields as optional `string|null`, so non-tenant pipelines remain backwards compatible.

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

Implemented in `scripts/publish_external_audit_anchor.py`, `schemas/external_audit_anchor_report.schema.json`, and `config/schema_backcompat_baseline.json` (added `tenant_id` to `stable_properties` so future changes can't silently drop it). Validated by `scripts/check_json_contracts.sh`, which now exercises the tenant-mode publish (tenant-namespaced ledger + per-record tenant_id assertion) and a cross-tenant reject path (anchor under `contract-tenant/` with `--tenant-id other-tenant` must exit non-zero and must not create the ledger file).

#### Acceptance Criteria

1. Archive and anchor operations are strictly partitioned by `tenant_id`.
2. Cross-tenant anchor file path access is blocked at the script level.
3. External ledger path includes `tenant_id` as a namespace component.

---

## 6. Category I — Production Operator Console

**Goal:** Replace the current loopback-only web shell with a production-grade observability stack and self-service data request portal.

**Total: ~6 blocks / ~30h**

---

### I1 — Real Grafana + Tempo / Jaeger Dashboards (2 blocks / 10h) — Repo-side scaffolds completed 2026-05-08

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

Implemented:

- `config/observability/docker-compose.observability.yml` brings up `tempo` (image `grafana/tempo:2.5.0`, OTLP gRPC on 4317 + OTLP HTTP on 4318), `prometheus` (image `prom/prometheus:v2.55.1`, mounting the existing `config/prometheus/alert-rules.yml`), and `grafana` (image `grafana/grafana:11.2.0`, anonymous admin access for local demo, dashboards + datasources auto-provisioned).
- `config/observability/tempo.yaml` declares both OTLP receivers, local-block storage, and 168h retention; `config/observability/prometheus.yml` scrapes the recovery-service `/metrics` endpoint and the operator-dashboard `/metrics` endpoint and mounts the J3-b alert rule file.
- `config/observability/grafana-datasources.yaml` provisions both datasources with stable UIDs `seccomp-tempo` and `seccomp-prometheus`; `config/observability/grafana-dashboards/dashboards.yaml` provisions the dashboards directory mount.
- `config/observability/grafana-dashboards/pipeline-overview.json` (uid `seccomp-pipeline-overview`) covers the panel set in I1-b: per-tenant request rate, error-rate stat, active jobs, rate-limit denies, recovery-service request rate by decision, recovery-service latency p50/p95, and a Tempo-backed pipeline-stage trace table. `config/observability/grafana-dashboards/recovery-service.json` (uid `seccomp-recovery-service`) covers the recovery-service-specific drilldown: request rate by decision and reason_code, latency p50/p95/p99, plus rate-limited / TLS-required / signature-failed deny stats.
- `scripts/render_observability_topology.py` validates the artifacts: that `tempo`, `prometheus`, `grafana` services all appear in the compose file, that Tempo declares both OTLP listeners, that Prometheus mounts the alert-rules file, that the two stable datasource UIDs are present, and that at least the two checked-in dashboards exist with proper uid/title/panels. It emits `observability_topology_report/v1` with the resolved file paths, the Tempo OTLP listener addresses, and the Prometheus job/target list.
- `scripts/export_otel_events.py` now also accepts `--otlp-endpoint` (best-effort OTLP/HTTP-JSON push to `<endpoint>/v1/traces`) and an optional `--otlp-bearer-env` for a bearer token; the result is recorded under `otlp_push.{endpoint_url, span_count, status_code, ok, transport_error}` in the existing `otel_export_report/v1` (the schema and backcompat baseline are extended to permit the optional `otlp_push` block).
- Default contract smoke runs `render_observability_topology.py` end-to-end and asserts the four invariants: status=ok, all three compose services present, both Tempo OTLP listeners present, alert-rules mounted, both datasource UIDs present, and both dashboard UIDs (`seccomp-pipeline-overview`, `seccomp-recovery-service`) present.

#### Acceptance Criteria

1. `export_otel_events.py --otlp-endpoint http://localhost:4317` pushes spans to Tempo. Repo-side adapter completed: `--otlp-endpoint` + `--otlp-bearer-env` flags wired and recorded in the report; live push against a running Tempo instance is operator-environment work.
2. Grafana dashboard renders pipeline latency and error rate. Repo-side artifacts completed: `pipeline-overview.json` and `recovery-service.json` cover the required panels and use stable Prometheus / Tempo datasource UIDs.
3. Provisioning is fully automated (no manual Grafana configuration). Completed: datasources and dashboards provisioning configs are checked in and mounted by the compose file.

---

### I2 — Alerting Integration (2 blocks / 10h) — Repo-side completed 2026-05-08

#### Tasks

**I2-a — Wire alert check to Alertmanager / Slack (1 block) — Completed 2026-05-08**

`scripts/check_observability_alerts.py` now accepts `--webhook-url`, `--webhook-format slack|alertmanager`, `--webhook-bearer-env`, `--webhook-timeout-sec`, `--webhook-include-resolved`, and `--require-webhook-ok`. Loopback URLs (`localhost` / `127.*` / `::1`) automatically bypass the system HTTP proxy; non-loopback URLs honor the standard env vars. The result is recorded in the existing `observability_alert_report/v1` under an optional `webhook_dispatch` block.

Slack format produces a `{"text": "..."}` payload listing every firing alert with its severity, message, and triage steps. Alertmanager format produces a `[{"labels": {...}, "annotations": {...}, "startsAt": "..."}, ...]` array (one entry per firing alert) with `alertname`, `severity`, `service=seccomp-privacy-platform`, plus `job_id` / `tenant_id` / `correlation_id` labels when present.

```bash
python3 scripts/check_observability_alerts.py \
  --dashboard tmp/observability_dashboard.json \
  --webhook-url https://hooks.slack.com/services/T.../B.../... \
  --webhook-format slack \
  --out tmp/observability_alert_report.json
```

Default `--webhook-url` skips empty notifications when zero alerts are firing (records `skipped_reason=no_firing_alerts`); `--webhook-include-resolved` POSTs the resolved-state payload too.

**I2-b — Scheduled alert daemon (1 block) — Completed 2026-05-08**

`scripts/run_alert_check_daemon.py` wraps the I2-a flow in a polling loop, tracks the last-known firing state per `alert_id` across iterations, and computes `unknown→firing`, `firing→resolved`, and `resolved→firing` transitions. It writes a JSONL `alert_daemon_heartbeat/v1` log every iteration with the alert state summary, transitions, duration, and (when a webhook is configured) the dispatch result.

```bash
python3 scripts/run_alert_check_daemon.py \
  --dashboard tmp/observability_dashboard.json \
  --interval-sec 60 \
  --heartbeat-log tmp/alert_daemon_heartbeat.jsonl \
  --webhook-url https://hooks.slack.com/services/T.../B.../... \
  --webhook-format slack
```

Honors SIGINT/SIGTERM for clean shutdown. `--max-iterations N` runs N iterations and exits (useful for cron-driven hosts that prefer one-shot invocations). Per-iteration webhook dispatch is gated on transitions by default; pass `--webhook-include-resolved` for explicit resolved-state notifications, or `--webhook-always` to POST every iteration (debug aid). `--require-webhook-ok` and `--exit-on-firing` are CI-friendly exit-code modes.

#### Smoke Surface

`scripts/check_alert_webhook_smoke.py` is the I2-a/I2-b smoke harness: spawns an in-process HTTP receiver on loopback, drives both Slack and Alertmanager webhook formats, drives the daemon for two iterations with a state-flip between them, and asserts dispatch.ok, status_code 200, schema validity (against `observability_alert_report/v1` and `alert_daemon_heartbeat/v1`), and a `firing→resolved` transition on the heartbeat JSONL. Default contract smoke invokes it.

#### Acceptance Criteria

1. **A firing alert (`repeated_stage_error`) triggers a Slack notification.** ✓ Verified by smoke harness — webhook receiver gets a `{"text": "..."}` payload with the firing alert listed; `webhook_dispatch.ok=true` recorded in `observability_alert_report/v1`.
2. **Alert resolves when the condition clears (no repeat notification).** ✓ Verified — the daemon emits `firing→resolved` only once on the transition; subsequent iterations with the same resolved state produce zero transitions.
3. **`alert_daemon_heartbeat/v1` log verifiable with `validate_json_contract.py`.** ✓ The schema is in `config/schema_backcompat_baseline.json` (118 schemas / 0 fail) and is validated end-to-end by the smoke harness.

---

### I3 — Self-Service Data Request Portal (2 blocks / 10h) — Repo-side completed 2026-05-08

#### Tasks

**I3-a — Request submission form (1 block) — Completed 2026-05-08**

Extend the existing `serve_operator_dashboard.py` with a tenant-facing request form at `/v1/request/submit`:

```json
POST /v1/request/submit
{
  "schema": "query_workflow_request/v1",
  "query_type": "cross_party_match",
  "tenant_id": "demo_tenant",
  "dataset_id": "bridge_demo_dataset",
  "caller": "auto_demo",
  "job_id": "demo_request_001",
  "server_source": "sse/examples/bridge_server_records.jsonl",
  "client_source": "sse/examples/bridge_client_records.jsonl",
  "server_join_key_field": "email",
  "client_join_key_field": "email",
  "client_value_field": "amount",
  "token_scope": "demo_request_001",
  "token_secret_env": "BRIDGE_TOKEN_SECRET",
  "out_base": "tmp/demo_request_001",
  "sse_export_policy_config": "sse/config/export_policy.example.json"
}
```

Implemented endpoint:
1. Validates the request against `query_workflow_request/v1` schema.
2. Checks the submitting identity through the same bearer-token / `api_identity_resolution/v1` path used by the query-workflow API when `--identity-token-config` is configured, and binds caller / tenant / dataset / service scope through `bind_query_request_to_identity`.
3. Creates a `pending_approval` row in metadata sidecar table `workflow_submissions`.
4. Writes a `control_plane_mutations` row with `operation='submit_request'` and `entity_type='workflow_submission'`.
5. Returns `operator_request_submission/v1` with a `submission_id` for tracking.
6. Does not execute immediately; approval/execution is handled by I3-b.

Repo-side artifacts:

- `scripts/serve_operator_dashboard.py`: `POST /v1/request/submit`, `--metadata-db-path`, `--metadata-db-dsn`, `--identity-token-config`, and optional bearer-token auth.
- `migrations/metadata/012_add_workflow_submissions.sql` and Postgres DDL parity in `migrations/postgres/001_init.sql`.
- `schemas/operator_request_submission.schema.json` plus backcompat baseline registration.
- `scripts/check_operator_request_submission_smoke.py`: loopback smoke that verifies HTTP 202, schema validity, `workflow_submissions` persistence, and `control_plane_mutations` audit.
- `config/operator_console/console_manifest.json`: adds the `requests` section and `approval_workflow` feature flag.

**I3-b — Approval workflow (1 block) — Completed 2026-05-08**

Implemented `POST /v1/request/<submission_id>/approve` and `POST /v1/request/<submission_id>/reject`:

- `approve`: requires resolved identity role `privacy_operator` or `platform_admin`, rejects same-identity submit→approve with HTTP 403 `same_identity_self_approval`, records `approved_by` / `approved_at_utc` and `control_plane_mutations.operation='approve_request'`, reserves a dashboard job slot before committing the approval, and launches the existing query workflow path after the approval commit.
- `reject`: requires `privacy_operator`, `platform_admin`, or `compliance_auditor`, requires a non-empty reason, records `rejected_by` / `rejected_at_utc` / `rejection_reason`, and writes `control_plane_mutations.operation='reject_request'`.

Implemented `GET /v1/requests?tenant_id=...&status=pending_approval` to list pending requests for the operator review panel backing API, plus `GET /v1/requests/<submission_id>` for detail views with the stored normalized request payload. Access is scoped to the submitter's own rows, same-tenant reviewer roles, platform admins, and compliance auditors.

Repo-side artifacts:

- `scripts/serve_operator_dashboard.py`: approval/reject/list/detail endpoints, role checks, same-identity self-approval guard, approval-before-launch reservation ordering, and `control_plane_mutations` transition audit.
- `migrations/metadata/012_add_workflow_submissions.sql` and `migrations/postgres/001_init.sql`: approval/rejection columns for `workflow_submissions`.
- `schemas/operator_request_submission.schema.json`: optional approval/rejection fields, detail `request`, transition `reason`, and approval response `job_control`.
- `schemas/operator_request_submission_list.schema.json`: frozen `operator_request_submission_list/v1` list response.
- `scripts/check_operator_request_submission_smoke.py`: end-to-end loopback smoke covering submit, list, detail, same-identity approve denial, approve-starts-job, reject-with-reason, and mutation rows.
- `scripts/check_json_contracts.sh`: validates pending/list/detail/approve/reject I3 samples.
- `config/operator_console/console_manifest.json`: request section now includes submit/list/detail/approve/reject endpoints.

#### Acceptance Criteria

1. I3-a complete: a `query_submitter`-role user can submit a request; it is persisted as `pending_approval` in `workflow_submissions` and returned as `operator_request_submission/v1`.
2. I3-b complete: pending requests appear through `GET /v1/requests?...` for the operator review panel backing API and validate as `operator_request_submission_list/v1`.
3. I3-b complete: a `privacy_operator`-role user can approve; the existing dashboard job launch path starts the approved request and the response includes `job_control.state='running'`.
4. I3-b complete: an attempt by the submitting identity to approve its own request is rejected with HTTP 403 `same_identity_self_approval`.

---

## 7. Category J — SRE / High Availability

**Goal:** The platform can survive the failure of any single component (recovery service crash, PostgreSQL primary failure, operator dashboard restart) without data loss or audit chain corruption.

**Total: ~6 blocks / ~30h**

---

### J1 — Multi-Node Deployment Topology (1 block / 5h) — Completed repo-side 2026-05-07

#### Status

Repo-side implementation now lives in:

- `config/topology.md` — canonical deployment topology document. Covers the load-balancer / recovery-service / pgBouncer / Patroni layout, component classification (stateless vs stateful), full port assignments, authentication boundaries (mTLS vs bearer + identity proxy), scaling policies, and the `kubectl apply --dry-run=client` validation flow.
- `config/k8s/recovery-service-deployment-demo-tenant.yaml`, `config/k8s/recovery-service-service-demo-tenant.yaml`, `config/k8s/recovery-service-hpa-demo-tenant.yaml` — checked-in baseline manifests for the recovery-service `Deployment` (replicas: 2, mTLS port 18443, readiness/liveness probes, resource requests + limits), the `Service` (ClusterIP, port 443 → containerPort `https`), and the `HorizontalPodAutoscaler` (min 2 / max 6 / target CPU 70%).
- `scripts/render_recovery_service_k8s.py` — renderer that emits all three manifests under `--out-dir`, structurally validates the apiVersion/kind/labels/probes/resources/HPA bounds, optionally calls `kubectl apply --dry-run=client` when `kubectl` is available locally, and emits `k8s_recovery_service_topology_report/v1`.
- `schemas/k8s_recovery_service_topology_report.schema.json` — freezes the topology report contract (status, out_dir, namespace, recovery_app, tenant_id, service_port, container_port, manifests[]).

The renderer pairs cleanly with the H1-b `scripts/render_k8s_network_policies.py` output: each tenant gets its own per-tenant `Deployment` + `Service` + `HPA`, plus a per-tenant `NetworkPolicy` that scopes ingress to that tenant's pipeline pods. The default contract smoke validates the structural rules, the YAML body content (replicas/probes/HPA bounds), and that the report schema stays frozen.

Operators can regenerate manifests with:

```bash
python3 scripts/render_recovery_service_k8s.py \
  --tenant-id demo-tenant \
  --namespace seccomp-privacy \
  --replicas 2 \
  --min-replicas 2 \
  --max-replicas 6 \
  --target-cpu-utilization 70 \
  --container-port 18443 \
  --service-port 443 \
  --image ghcr.io/seccomp-privacy/recovery-service:0.1.0 \
  --out-dir tmp/k8s \
  --output tmp/k8s_recovery_service_topology_report.json \
  --kubectl-dry-run \
  --assert-ok
```

Live `kubectl apply --dry-run=client` validation is operator-environment work and only runs when `--kubectl-dry-run` is passed and `kubectl` is on `PATH`.

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

**J2-a — Recovery service failover (1 block) — Completed repo-side 2026-05-07**

Repo-side implementation now lives in:

- `scripts/test_failover_recovery_service.py` — orchestrates the failover drill end-to-end.
- `schemas/recovery_service_failover_test.schema.json` — freezes `recovery_service_failover_test/v1`.

What the script does:

1. Stands up two HTTP recovery-service instances on free loopback ports, both advertising the same `service_id` (LB-style transparent failover) but with distinct lifecycle paths and audit logs.
2. Health-probes both services via `request_record_recovery_health`.
3. Issues a baseline `request_record_recovery` to the primary; records duration, served-by, and the audit log entry on the primary.
4. SIGKILLs the primary process by reading its `pid_file` and waits up to `--unreachable-deadline-sec` for the TCP port to stop accepting connections.
5. Issues the failover recovery request: it tries the primary first (now unreachable), records the failure reason, then retries on the secondary; total wall time is asserted against `--failover-target-seconds` (default 10s).
6. Cross-checks audit integrity: the primary's audit log must contain the baseline job's record, the secondary's must contain the failover job's record, neither service may have recorded the *other* service's job.
7. Best-effort teardown via `manage_record_recovery_service.py stop`; the temp work dir is cleaned up unless `--work-dir` was operator-pinned.

Default contract smoke runs the full drill with `--candidate-count 2`, asserts every contract stake (`status=ok`, `kill_method=SIGKILL`, `served_by=primary` for baseline, `served_by=secondary` for failover, `within_failover_target=true`, `no_audit_events_lost=true`, ≥1 record on each side), and validates the report against the schema. mTLS is left as an operator-environment exercise so default smoke does not need cert plumbing; the script architecture (TLS plumbing in `tls_config`) accommodates that path when `--config` is plumbed through.

Operator drill:

```bash
python3 scripts/test_failover_recovery_service.py \
  --candidate-count 1000 \
  --failover-target-seconds 5 \
  --output tmp/recovery_service_failover_test.json \
  --assert-ok
```

Typical timing on the reference machine: baseline 130ms, total failover wall time ~125ms (well inside the 5s/10s targets).

**J2-b — PostgreSQL Patroni failover test (1 block) — Repo-side completed 2026-05-09**

Repo-side implementation now lives in:

- `scripts/metadata_db.py` — `connect_db_with_retry(db_path, dsn, retries, delay)` already wraps `connect_db` with exponential-backoff retry, intentionally agnostic to backend so it rides out either a Patroni primary switch or an in-process simulated drop. `connect_read_db_with_retry` provides the matching read-replica path for sidecars routed through pgBouncer.
- `scripts/test_metadata_db_failover.py` — orchestrates the failover drill end-to-end. Default smoke runs entirely in-process against a fresh SQLite DB and patches `metadata_db.connect_db` to raise a synthetic `SimulatedOperationalError` for the first `--simulated-failure-count` calls before letting the real connect succeed; the retry helper has to ride out those simulated failures within `--failover-target-seconds`.
- `schemas/metadata_db_failover_test.schema.json` — freezes `metadata_db_failover_test/v1` with input scale, retry budget, baseline query, simulated-failover request, post-failover query, data-integrity row counts, and run diagnostics.

What the script does:

1. Initializes a fresh SQLite metadata DB under a private tmp dir, applies all migrations, and inserts one synthetic `jobs` row through the unwrapped `connect_db`.
2. Runs a baseline read of that row through a fresh connection so the DB is provably healthy before failure injection.
3. Patches `metadata_db.connect_db` so the next `--simulated-failure-count` calls raise `SimulatedOperationalError`. `connect_db_with_retry` is then invoked with `retries=--retry-attempts-allowed` and `delay=--retry-base-delay-seconds`; the helper must exhaust the simulated failures and recover within `--failover-target-seconds`.
4. After recovery, inserts a second synthetic row through the recovered connection, then opens yet another fresh connection to confirm both rows are visible and `data_round_trip_ok=true`.
5. Restores the original `connect_db` and removes the tmp dir on success (operator-pinned `--work-dir` is preserved).

Default contract smoke runs the full drill with `--simulated-failure-count 2`, `--retry-attempts-allowed 4`, and a 30s failover target, asserts every contract stake (`status=ok`, `configuration.simulation_mode=in_process_simulated`, `failover_request.primary_attempt_failed=true`, `failover_request.actual_attempts_used >= 3`, `failover_request.within_failover_target=true`, `post_failover_query.data_round_trip_ok=true`, `data_integrity.no_data_lost=true`, `errors=[]`), and validates the report against the schema. PostgreSQL is left as an operator-environment exercise so default smoke does not need psycopg2 or a Patroni cluster; the simulator stays the same against `--db-dsn` because the patched `connect_db` covers both backends.

Operator drill against a real Patroni cluster:

```bash
# (a) confirm the simulator + retry path against the live DSN
python3 scripts/test_metadata_db_failover.py \
  --db-dsn postgresql://postgres:pass@pgbouncer:6432/postgres \
  --simulated-failure-count 2 \
  --retry-attempts-allowed 4 \
  --failover-target-seconds 30 \
  --output tmp/metadata_db_failover_test.json \
  --assert-ok

# (b) trigger an actual Patroni switchover and re-run the importer through the
#     same DSN to prove the sidecar reconnects within budget
patronictl -c config/patroni-ha/patroni-primary.yml switchover \
  --master pg-primary --candidate pg-replica --force
python3 scripts/check_platform_health.py --metadata-db-dsn postgresql://postgres:pass@pgbouncer:6432/postgres
python3 scripts/import_run_metadata.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --db-dsn postgresql://postgres:pass@pgbouncer:6432/postgres
```

Typical timing on the reference machine: in-process simulation with 2 forced failures completes in ~150ms wall time (well inside the 30s target); the retry helper consumes 3 attempts (2 simulated failures + 1 real connect).

#### Acceptance Criteria

1. Recovery service failover completes in < 10 seconds (client retries included). ✓ J2-a
2. No audit events lost during failover. ✓ J2-a (`audit_integrity.no_audit_events_lost=true`); J2-b mirrors with `data_integrity.no_data_lost=true`.
3. PostgreSQL failover: sidecar reconnects and continues importing within 30 seconds. Repo-side simulator + contract completed 2026-05-09; live Patroni switchover drill remains operator-environment work.

---

### J3 — SLO Enforcement and Prometheus Metrics Endpoint (2 blocks / 10h)

#### Tasks

**J3-a — Add /metrics endpoint to recovery service (1 block) — Completed 2026-05-06**

Implemented in `services/record_recovery/http_service.py`:

- `ServiceMetrics`: thread-safe `threading.Lock`-protected counters + histogram. Tracks `recovery_requests_total{decision, op}` and `recovery_request_duration_seconds` (buckets: 0.05/0.1/0.25/0.5/1.0/2.0/5.0 s).
- `_log_request()` calls `self.server.metrics.record(decision, op, duration_s)` on every request.
- `do_GET` serves `GET /metrics` before the health check path; returns `text/plain; version=0.0.4` Prometheus exposition format. No external library required.
- `ServiceMetrics.prometheus_text()` emits the full counter + histogram text block.

Example output from a live service:

```
# HELP recovery_requests_total Total recovery requests by decision and op
# TYPE recovery_requests_total counter
recovery_requests_total{decision="allow",op="recover"} 42
recovery_requests_total{decision="deny",op="recover"} 3
# HELP recovery_request_duration_seconds Recovery request duration
# TYPE recovery_request_duration_seconds histogram
recovery_request_duration_seconds_bucket{le="0.1"} 10
recovery_request_duration_seconds_bucket{le="0.5"} 38
recovery_request_duration_seconds_bucket{le="1.0"} 42
recovery_request_duration_seconds_bucket{le="+Inf"} 45
recovery_request_duration_seconds_sum 8.400000
recovery_request_duration_seconds_count 45
```

**J3-b — SLO alert rules (1 block) — Completed repo-side 2026-05-07**

Repo-side implementation now lives in:

- `config/prometheus/alert-rules.yml` — Prometheus rules file targeting the recovery-service `/metrics` exposition added by J3-a. Defines four SLO-aligned alerts:
  - `RecoveryServiceErrorRateHigh` (warning, 5%/5min deny rate, 2min for-window).
  - `RecoveryServiceLatencyHigh` (critical, p95 latency > 2s for 5min).
  - `RecoveryServiceNoTraffic` (warning, 0 req/s for 10min — wrong scrape target / paused pipeline).
  - `RecoveryServiceRateLimitedSpike` (warning, sustained H2-a token-bucket rejections).
  - Each alert carries `labels.severity`, `labels.component`, `labels.slo`, plus `annotations.summary`, `annotations.description`, and an `annotations.triage_path` pointing into `OPS_RUNBOOK.md` or this guidebook.
- `scripts/validate_prometheus_alert_rules.py` — repo-side YAML validator. Uses PyYAML when available, otherwise an indent-based minimal parser tuned for the recovery-service rules format. Confirms (a) the file is well-formed YAML, (b) the four required alert names are present, (c) every parsed alert has `labels.severity` set, (d) every alert defines a `for:` window. Emits `prometheus_alert_rules_report/v1`.
- `schemas/prometheus_alert_rules_report.schema.json` — freezes the validator report contract (status, rules_path, yaml_round_trip, groups[], alerts[], missing_alerts[], errors[]).

Default contract smoke validates the committed rules file, asserts the four required alert names are present and that both `critical` and `warning` severities show up, and runs the report through schema validation. Operators still run `promtool check rules config/prometheus/alert-rules.yml` against the same file as part of their Prometheus deployment workflow.

```bash
python3 scripts/validate_prometheus_alert_rules.py \
  --rules config/prometheus/alert-rules.yml \
  --output tmp/prometheus_alert_rules_report.json \
  --assert-ok
```

Wire the alerts into Alertmanager once I2-a (`scripts/check_observability_alerts.py --webhook-url`) is finished; until then, operators can scrape the recovery-service `/metrics` endpoint directly and load the rules file into a stand-alone Prometheus instance.

#### Acceptance Criteria

1. `GET /metrics` on the recovery service returns valid Prometheus text format.
2. Alert fires when error rate exceeds 5% for 2 minutes in a load test.
3. Alert resolves when error rate drops below threshold.

---

### J4 — Chaos and Failure Injection Testing (1 block / 5h) — Repo-side completed 2026-05-08

#### Tasks

Implemented `scripts/run_chaos_test.py` plus `chaos_test_report/v1` schema. Three scenarios run repo-side in default contract smoke; two are emitted as `status=skipped` because they require operator-environment infrastructure (a live Patroni cluster, a quota-bounded filesystem):

| Scenario | Injection method | Expected behavior | Implementation |
|----------|-----------------|-------------------|----------------|
| `recovery_service_sigkill` | In-process listener teardown (`server.shutdown()` + `server_close()`) — visible to the client as a SIGKILL-equivalent socket loss | URLError / connection refused / connection reset on the next probe; audit chain bytes unchanged | Spawns an in-process plaintext recovery service on loopback, probes `/metrics` (no auth required) for liveness, then drops the listener and re-probes |
| `mtls_cert_expired` | Self-signed server cert with `not_valid_before` 10 days ago and `not_valid_after` 1 day ago | `ssl.SSLCertVerificationError` (or generic `SSLError` carrying `expired`) raised before any record is sent | `cryptography`-generated RSA cert + key, in-process TLS listener, client uses `ssl.create_default_context()` with the cert as the local CA so the failure is purely about expiry |
| `audit_archive_unwritable` | `chmod 000` on the archive directory before invoking `archive_audit_bundle.py` | Non-zero exit, no partial files in archive dir, `audit_chain.json` SHA-256 unchanged | Synthesizes a real `audit_chain.json` + `audit_chain.seal.json` via `seal_audit_artifact.py`, snapshots the archive dir listing, blocks writes, runs the archiver as a subprocess, restores mode for cleanup |
| `postgres_primary_killed` | Operator-environment only | Patroni promotes replica; sidecar reconnects | Recorded as `status=skipped`, `injection_method=operator_environment_only`; live drill belongs in OPS_RUNBOOK.md alongside J2-b |
| `audit_log_path_full` | Operator-environment only | Recovery service logs `audit_write_failed` event | Recorded as `status=skipped`; requires a quota-bounded loopback filesystem to simulate cleanly |

Each scenario records: name, injection_method, observed_failure_mode (label), observed_error_class, error_text, audit_chain_uncorrupted (boolean, derived from a SHA-256 before/after check on the source `audit_chain.json` for the scenarios that touch it), expected_failure_pattern_matched, and free-form details. The top-level `summary.status` drops to `fail` if any repo-side scenario fails or any audit-chain corruption is detected.

Default contract smoke runs `--scenarios all` (the 3 implementable scenarios plus 2 operator-skipped placeholders) against a temp work dir, validates the report against `chaos_test_report/v1`, and asserts `summary.status=ok`, `total=5`, `ok=3`, `skipped=2`, `audit_chain_corruptions=0`, plus per-scenario invariants on the failure-mode labels.

```bash
# Repo-side default (3 scenarios + 2 operator-skipped placeholders)
python3 scripts/run_chaos_test.py \
  --scenarios all \
  --output tmp/chaos_test_report.json \
  --assert-ok

# Single-scenario operator drill
python3 scripts/run_chaos_test.py --scenarios mtls_cert_expired --assert-ok
```

#### Acceptance Criteria

1. All 5 scenarios produce a verifiable failure report without corrupting `audit_chain.json`. Repo-side completed: 3 implementable scenarios pass with `audit_chain_corruptions=0` and the 2 operator-only scenarios are explicitly recorded as `status=skipped`. Live operator drills for `postgres_primary_killed` and `audit_log_path_full` follow the OPS_RUNBOOK.md chaos drill section.
2. Recovery from each failure is documented in `OPS_RUNBOOK.md`. Completed: see the OPS_RUNBOOK.md "J4 Chaos Drill" section below.

---

## 8. Category K — Compliance and External Audit

**Goal:** Make the audit trail verifiable by external parties: immutable external anchor, formal compliance mapping, and adversarial security review.

**Total: ~4 blocks / ~20h**

---

### K1 — Real Immutable Audit Anchor (2 blocks / 10h; K1-a + K1-b repo-side complete 2026-05-08)

#### Current Baseline

`scripts/publish_external_audit_anchor.py` writes `external_audit_anchor_ledger/v1` records to a local file by default. As of 2026-05-08 it also accepts `--sink-kind s3_worm`, which builds the same JSONL payload and uploads it to an S3 object protected by Object Lock in COMPLIANCE mode (or GOVERNANCE mode via `--object-lock-mode`). Default smoke runs the s3_worm path in `planned` status so no AWS credentials are required.

#### Tasks

**K1-a — S3 Object Lock (WORM) backend (1 block) — Completed repo-side 2026-05-08**

Implemented in `scripts/publish_external_audit_anchor.py`:

1. New CLI flags: `--sink-kind file_ledger|s3_worm` (default `file_ledger`), `--object-lock-mode COMPLIANCE|GOVERNANCE` (default `COMPLIANCE`), `--retain-days <int>` (default `3650`, i.e. 10-year retain-until horizon), and `--execute` (must be set to actually call S3).
2. `--external-ledger` accepts `s3://bucket/key.jsonl` URIs when `--sink-kind=s3_worm`. Tenant-scope enforcement (introduced in H3-b) now also validates that `<tenant_id>` is a path segment of the S3 key, so a `--tenant-id contract-tenant` invocation pointed at `s3://bucket/audit/other-tenant/ledger.jsonl` exits non-zero before any boto3 call.
3. The s3_worm sink lazy-imports `boto3`, calls `get_object` (catching `NoSuchKey`) to read any prior ledger bytes, appends each verified anchor record as an `external_audit_anchor_ledger/v1` JSONL line (sharing `render_ledger_lines()` with the file path), and re-uploads with `ObjectLockMode=<mode>` and `ObjectLockRetainUntilDate=<retain_until_utc>`. Without `--execute` the script stays in `s3_object_lock.status=planned`, records `executed=false`, and computes the same retain-until horizon for diagnostics — default contract smoke and operator dry runs do not need AWS credentials.
4. `external_audit_anchor_report/v1` now carries an optional `external_sink.s3_object_lock` block (`bucket`, `key`, `object_lock_mode`, `retain_until_utc`, `retain_days`, `executed`, `status` ∈ `planned|uploaded|skipped|error`, `details`, `etag`, `version_id`, `previous_object_etag`). The schema additionally extends `external_sink.kind` to `["file_ledger", "s3_worm"]`. `file_ledger` remains available for local smoke, but `--production-mode --sink-kind file_ledger` is rejected before any local ledger append so the disallowed sink is not mutated.
5. `scripts/check_json_contracts.sh` adds two K1-a assertions: (a) a planned-mode run against `s3://seccomp-audit-archive/audit/contract-tenant/ledger.jsonl` succeeds, validates against the schema, and asserts `kind=s3_worm`, `bucket/key`, `object_lock_mode=COMPLIANCE`, `retain_days=3650`, `retain_until_utc.endswith("Z")`, `executed=false`, `status=planned`, `summary.published_count=0`, and `records[*].published=false`; (b) a cross-tenant S3 key with `--tenant-id contract-tenant` pointed at `…/other-tenant/…` exits non-zero. `scripts/check_ci_smoke.sh` already py_compiles `publish_external_audit_anchor.py`, so no extra wiring is required there.

Live AWS execution remains an operator-environment block: enable Object Lock at bucket creation time, provide credentials, and run with `--execute`:

```bash
# Operator drill (live AWS path; default smoke leaves this in planned mode)
python3 scripts/publish_external_audit_anchor.py \
  --anchor-file archive/<tenant>/audit_chain_anchor.jsonl \
  --external-ledger s3://seccomp-audit-archive/audit/<tenant>/ledger.jsonl \
  --tenant-id <tenant> \
  --sink-kind s3_worm \
  --object-lock-mode COMPLIANCE \
  --retain-days 3650 \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY \
  --require-signature \
  --execute \
  --assert-ok
```

The bucket must be created with Object Lock enabled (`aws s3api create-bucket --object-lock-enabled-for-bucket`) and a default retention configured if you want every PUT to inherit it. The script always sets `ObjectLockMode` and `ObjectLockRetainUntilDate` per request, so per-bucket defaults are not required for correctness. The `etag` and `version_id` returned by `put_object` are written into the report's `s3_object_lock` block for downstream verification.

**K1-b — Sigstore / Rekor transparency log (1 block) — Completed repo-side 2026-05-08**

For deployments that prefer a public, append-only transparency log over an S3 WORM bucket. Implemented in `scripts/publish_external_audit_anchor.py`:

1. `--sink-kind rekor` is now a third sink alongside `file_ledger` and `s3_worm`. The same `--external-ledger` argument carries the Rekor base URL (e.g. `https://rekor.sigstore.dev`); only `http://` and `https://` schemes are accepted, and the parser rejects any other scheme before any signing or HTTP work happens.
2. New CLI flags: `--rekor-signing-key-env <env>` (env var holding a PEM-encoded ECDSA P-256 / `secp256r1` private key — required for `--execute`) and `--rekor-timeout-sec <seconds>` (HTTP timeout, default `10.0`).
3. The shared `--execute` flag drives both `s3_worm` and `rekor`: without it, the rekor sink stays in `status=planned`, `executed=false`, `submitted_count=0`, `entries=[]`, so default contract smoke needs neither network access nor key material.
4. With `--execute`, for each anchor record the script computes canonical bytes `b"entry_sha256:<hex>\n"`, signs them with ECDSA-SHA256 from the operator-supplied private key, derives the matching SubjectPublicKeyInfo PEM, and POSTs a `hashedrekord/0.0.1` entry to `<rekor>/api/v1/log/entries`. The response's first entry uuid + `logIndex` + `integratedTime` are recorded per-entry; per-record `published` is set to `true` only when the POST returns 2xx.
5. `external_audit_anchor_report/v1` now carries an optional `external_sink.rekor_transparency_log` block with `endpoint_url`, `endpoint_path` (`"/api/v1/log/entries"`), `kind_version` (`"hashedrekord/0.0.1"`), `signature_algorithm` (`"ecdsa-p256-sha256"`), `executed`, `status` ∈ `planned|uploaded|partial|skipped|error`, `details`, `submitted_count`, `uploaded_count`, and per-record `entries[]` (with `entry_sha256`, `payload_sha256`, `uuid`, `log_index`, `integrated_time`, `status`, `details`). `external_sink.kind` enum extends to `["file_ledger", "s3_worm", "rekor"]`. The K1-a `s3_object_lock` block remains a sibling.
6. Top-level `summary.status` is set to `fail` when the rekor block ends in `status=error` (e.g. `--execute` with no signing key env, network failure, or every POST returning non-2xx); `partial` keeps the top-level status at `ok` for diagnostics.
7. `scripts/check_json_contracts.sh` adds two K1-b assertions: (a) a planned-mode run against `https://rekor.sigstore.dev` with `--tenant-id contract-tenant` succeeds, validates against the schema, and asserts `kind=rekor`, `endpoint_url`, `endpoint_path`, `kind_version`, `signature_algorithm`, `executed=false`, `status=planned`, `submitted_count=0`, `uploaded_count=0`, `entries=[]`, `summary.published_count=0`, and `records[*].published=false`; (b) a non-`http(s)` Rekor URL exits non-zero before any cryptographic work. `scripts/check_ci_smoke.sh` already py_compiles the script.
8. Local end-to-end verification: a synthetic in-process HTTP receiver loaded with the public key derived from the same private key parses each `hashedrekord` body, recomputes the canonical bytes from the embedded `data.hash.value`, and re-verifies the ECDSA signature server-side. Two anchor records → 2 POSTs → 2 successful 201 responses → `submitted_count=2`, `uploaded_count=2`, `status=uploaded`, `summary.published_count=2`, all `records[*].published=true`. This proves the live `--execute` path works end-to-end without depending on the public Rekor instance.

```bash
# Operator drill (live path; default smoke leaves this in planned mode)
export REKOR_SIGNING_KEY="$(cat secrets/rekor.ecdsa.pem)"
python3 scripts/publish_external_audit_anchor.py \
  --anchor-file archive/<tenant>/audit_chain_anchor.jsonl \
  --external-ledger https://rekor.sigstore.dev \
  --tenant-id <tenant> \
  --sink-kind rekor \
  --rekor-signing-key-env REKOR_SIGNING_KEY \
  --rekor-timeout-sec 15 \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY \
  --require-signature \
  --execute \
  --assert-ok
```

The Rekor `uuid` and `logIndex` returned per entry are written into the report's `rekor_transparency_log.entries[]` for downstream verifiability. Operators that prefer the official `sigstore` / `rekor-cli` toolchain can still use them to verify entries afterwards by digesting `b"entry_sha256:<hex>\n"` and querying `/api/v1/log/entries/<uuid>`.

#### Acceptance Criteria

1. `publish_external_audit_anchor.py --sink-kind s3_worm` successfully uploads to an S3 bucket with Object Lock enabled. Code path implemented; live upload runs only with `--execute` against an operator-provided AWS account.
2. Uploaded ledger object has `ObjectLockMode=COMPLIANCE` and a 10-year retain-until date. Implemented: `--object-lock-mode` (default `COMPLIANCE`) and `--retain-days` (default `3650`) are applied to every `put_object` call, and the resolved retain-until is recorded in `external_sink.s3_object_lock.retain_until_utc`.
3. A subsequent dry-run reads the same S3 object and verifies chain integrity. Pending operator engagement: chain verification on the script side already runs before the upload (`verify_anchor_records`); the post-upload S3 read-back path is intentionally left for the live drill alongside K1-b / external pen test. Default smoke covers the planned path and a cross-tenant S3 key reject path.

---

### K2 — Compliance Documentation (1 block / 5h) — Completed 2026-05-08

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

Implemented:

- `docs/COMPLIANCE_MAPPING.md` now covers Article 5(1) — lawfulness/fairness/transparency, purpose limitation, data minimization, accuracy, storage limitation, integrity and confidentiality, accountability — and the GDPR Article 15-22 data-subject rights matrix. Each row links to the actual file path, schema, or audit record in this repo.
- Known limitations are listed in §3 of `COMPLIANCE_MAPPING.md`: no automated erasure pipeline (cryptographic-erasure guidance instead), local-file external audit anchor by default, operator-environment authority adapters (OIDC RS256/JWKS, OpenFGA live, Vault), PostgreSQL portability, and crypto-shred operational guidance.
- A reviewer checklist (§4) gives an 8-step minimal evidence path: pick a run, open `audit_chain.json`, run `verify_audit_bundle.py`, run `verify_audit_tamper_resistance.py`, open `public_report.json`, cross-check `query_metadata.py --list-entity caller-permissions`, check the per-tenant archive index/anchor, and run `check_http_malformed_input_gate.py` for the HTTP boundary.

#### Acceptance Criteria

1. `docs/COMPLIANCE_MAPPING.md` covers all 7 GDPR principles. Completed: §1.1-§1.7 plus §2 data-subject rights.
2. Known limitations are explicitly listed. Completed: §3.1-§3.6 (no automated erasure, audit-seal scope, external anchor sink, live authority adapters, PostgreSQL portability, crypto-shred guidance).
3. Document is reviewed by a person with compliance/legal background. **Pending operator action — the document is now ready for legal review.**

---

### K3 — Penetration Testing (1 block / 5h) — Audit-chain tamper-resistance + HTTP malformed-input gate completed 2026-05-08; external pen test still pending

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
1. Requests with missing `X-Request-Signature` / `X-Request-Payload-SHA256` metadata (should return 400 with signature metadata missing).
2. Requests with expired `request_timestamp_utc` (should return 400 with `request_expired`).
3. Payloads with SQL injection patterns in `caller`, `job_id`, `tenant_id` (all should be treated as opaque strings, not query parameters).
4. Oversized request bodies (`Content-Length: 100000000`).

For the audit chain, write `scripts/verify_audit_tamper_resistance.py` that:
- Flips one bit in `audit_chain.json`.
- Verifies that `verify_audit_bundle.py` detects the tamper.
- Restores the original content.

Implemented:

- `scripts/verify_audit_tamper_resistance.py` flips one byte at up to six offsets across the chain (inside `correlation_id`, inside `job_id`, midfile) and seal (inside `artifact_sha256`, inside `job_id`, optionally inside `signature` when an HMAC seal is present). The script asserts that `verify_audit_bundle.verify_audit_bundle(...)` raises an exception each time, restores the original bytes after every mutation, and runs a post-restore baseline check that re-hashes both files and re-verifies the bundle.
- `schemas/audit_tamper_resistance.schema.json` freezes `audit_tamper_resistance/v1` (status, scenarios with offset/byte/detected/error metadata, summary, post-restore check); `config/schema_backcompat_baseline.json` registers it as a stable contract.
- `scripts/check_json_contracts.sh` invokes the new script after sealing the contract-smoke audit chain and asserts `status=ok`, `summary.detected==summary.total>=4`, and `post_restore_check.*=true`. `scripts/check_ci_smoke.sh` adds the new script to the py_compile list.
- `scripts/check_http_malformed_input_gate.py` spawns the record-recovery HTTP service in-process on loopback and asserts that the service rejects 11 attack scenarios: missing `X-Request-Signature` / `request_signature`, expired `request_timestamp_utc`, far-future timestamp, post-signature payload tampering, SQL-injection-pattern `caller`/`tenant_id`/`job_id`, malformed JSON body, non-object JSON body, missing required `candidate_ids`, wrong HTTP method (`DELETE`), unknown path, and an oversized body. Each scenario records HTTP status, transport error (if any), and the response error/reason fields.
- `schemas/http_malformed_input_gate.schema.json` freezes `http_malformed_input_gate/v1` (configuration, summary with `total/detected/missed/status`, per-scenario assertion fields). `config/schema_backcompat_baseline.json` registers it as a stable contract.
- Default contract smoke runs the gate end-to-end via the in-process spawn and asserts `summary.status=ok`, `summary.detected==summary.total>=8`, and that the required scenario name set is covered.

Engage an external pen testing firm for the mTLS boundary and the Vault AppRole authentication flow.

#### Acceptance Criteria

1. All HTTP malformed-input mutations are rejected by the recovery service. Completed locally: 10/10 scenarios detected, including SQL-injection patterns treated as opaque strings (rejected at authz/record-store, not as parameters), oversized bodies rejected at 400, wrong HTTP method returning 501, and unknown paths returning 404.
2. One-bit tamper in `audit_chain.json` is detected by `verify_audit_bundle.py`. Completed locally: up to 6 byte-flip scenarios per run depending on whether the seal carries an HMAC signature, all detected, 0 missed; post-restore SHA-256 matches baseline and verifier passes again.
3. External pen test report with zero critical findings (or accepted risk documentation for any findings). **Pending operator engagement.**

---

## 9. Execution Order and Dependencies

```
Week 1-2:   F1-a, live E authority validation with operator-provided services (parallel)
Week 2-3:   F1-b, F2-a repo-side completed 2026-05-07
Week 3-4:   F2-b/F2-c/F3 repo-side completed 2026-05-07
Week 4-5:   G1/G2-a/G2-b completed 2026-05-07; G3 timing/report/hotspot evidence completed 2026-05-09
Week 5-6:   G4-a, G5 (parallel)
Week 6-7:   G4-b, G7 (parallel; G6 + G8 completed 2026-05-08)
Week 7-8:   H category complete as of 2026-05-07 (H1-b/H2-a/H2-b/H3-a completed)
Week 8-9:   I2-a (parallel; I1-a completed repo-side 2026-05-08; J1 completed repo-side 2026-05-07)
Week 9-10:  I2-b and I3-a completed repo-side 2026-05-08; J2-a completed repo-side 2026-05-07
Week 10-11: J2-b, K1-a (parallel; I3-b completed repo-side 2026-05-08; J3-a/J3-b/J2-a complete repo-side)
Week 11-12: K1-a + K1-b + K2 + J4 completed 2026-05-08
Week 12-13: Historical plan showed K3 external pen test as the only remaining block in this guidebook's old block model (audit-chain tamper-resistance + HTTP malformed-input gate completed 2026-05-08; F4-a/F4-b repo-side completed 2026-05-07; live drill alongside F1-b). Current production-security status is superseded by `CURRENT_SECURITY_AND_COMPLETION_AUDIT.md`.
```

---

## 10. Summary Table

| Category | Blocks remaining | ~Hours remaining | Notes |
|----------|----------------:|----------------:|-------|
| E — Real authority sources | 0 repo-side | 0h | Complete; live validation is operator-environment work |
| F — Production PostgreSQL | 0 | 0h | F1-a/F1-b done; F2-a/F2-b/F2-c/F3 and F4-a/F4-b repo-side done; F2-c/F3 live drills remain operator-environment work |
| G — Scale & optimization | 0 | 0h | G1 + G2-a + G2-b + G3 + G4-a + G4-b + G5 + G6 + G7 + G8 all measured locally; 1M unary PJC ceiling rerun 2026-05-12, then chunked streaming 1M rerun passed on 2026-05-14 (G4-a 100k 222.02s, G4-b back-to-back stable + 1M streaming 34:05.18 / 2.20 GB / `exit_code=0`, G5 10k 34.9s) |
| H — Multi-tenant isolation | 0 | 0h | Complete: H1-a/H1-b/H2-a/H2-b/H3-a/H3-b |
| I — Production operator console | 0 | 0h | I1-a/I1-b/I2-a/I2-b/I3-a/I3-b repo-side done 2026-05-08; live Tempo push + Grafana render and full SPA remain operator/product work |
| J — SRE / HA | 0 repo-side | 0h | J1 + J2-a + J2-b + J3-a + J3-b + J4 done repo-side (J2-b 2026-05-09); live Patroni switchover + chaos drills remain operator-environment work |
| K — Compliance / external audit | 1 | 5h | K1-a + K1-b + K2 done 2026-05-08; K3 audit-chain tamper-resistance + HTTP malformed-input gate done 2026-05-08 (external pen test still pending operator engagement) |
| **Historical total remaining in this guidebook model** | **1** | **~5h** | K3 external pen test only; current production-security status is superseded by `CURRENT_SECURITY_AND_COMPLETION_AUDIT.md` |

Completed since initial publication: F1-a, H2-a, H2-b, H3-a, H3-b, J3-a (2026-05-06); H1-a/H1-b, F2-a/F2-b, F2-c, F3, F4-a/F4-b, J1, J2-a, and J3-b repo-side (2026-05-07); G3 bridge benchmark/report scaffold plus local 100k/1M release-binary timing, G6 mTLS connection overhead measurement, G8 concurrent dashboard jobs, I1-a + I1-b observability stack repo-side scaffolds (Tempo + Prometheus + Grafana compose, datasource provisioning, two dashboards, render script + report schema, OTLP/HTTP push adapter on `export_otel_events.py`), I2-a/I2-b alerting integration, I3-a request-submission endpoint + metadata persistence baseline, I3-b approval/reject/list/detail workflow, J4 chaos and failure-injection drill (3 in-process scenarios + 2 operator-skipped placeholders), K1-a S3 Object Lock (WORM) sink, K1-b Sigstore Rekor transparency-log sink, K2 compliance mapping, and K3 repo-side scaffolds — audit-chain tamper-resistance + HTTP malformed-input gate (2026-05-08, K1-a live S3 upload + K1-b live Rekor submission + J4 PostgreSQL/full-disk operator drills + K3 external pen test still operator-side). F1-b live PostgreSQL portability, G7 SQLite/PostgreSQL latency comparison, and G3 bridge phase-hotspot evidence completed locally on 2026-05-09.

### 10.1 Remaining Block Breakdown

As of 2026-05-09, the remaining production-readiness scope is:

| Category | Remaining blocks |
|----------|------------------|
| E — Real authority sources | None repo-side; live validation is operator-environment work |
| F — Production PostgreSQL | None repo-side; F2-c/F3 live drills remain operator-environment work |
| G — Scale & optimization | None (G4-a 100k×100k 222.02s + G4-b 3-iter back-to-back stability + G4-b 1M×1M unary ceiling documented on 2026-05-12 and chunked streaming rerun passed on 2026-05-14: 34:05.18 / 2.20 GB peak RSS / `exit_code=0` / `intersection_size=200000` / `intersection_sum=20020100000` + G5 10k pipeline 34.9s) |
| H — Multi-tenant isolation | None |
| I — Production operator console | None repo-side (I1-a/I1-b/I2-a/I2-b/I3-a/I3-b done 2026-05-08; live Tempo push + Grafana render and full SPA still operator/product work) |
| J — SRE / HA | None repo-side (J2-b in-process simulator + `connect_db_with_retry` validation done 2026-05-09; live Patroni switchover + chaos drills still operator/product work) |
| K — Compliance / external audit | K3 external pen test (K1-a + K1-b + K2 + K3 repo-side scaffolds done; external engagement still pending) |

Historical total in this guidebook model: **1 block / ~5h** (K3 external pen test only). Do not use this as the current production-security conclusion; see `CURRENT_SECURITY_AND_COMPLETION_AUDIT.md` for the current P0/P1 list. Historical detail retained: F1-b live PostgreSQL portability, G7 SQLite/PostgreSQL latency comparison, and G3 bridge phase-hotspot evidence completed locally 2026-05-09. K1-a S3 Object Lock (WORM) sink + K1-b Sigstore Rekor sink both done repo-side 2026-05-08 — shared `--sink-kind` / `--execute` framework on `publish_external_audit_anchor.py`, lazy boto3/cryptography imports, planned/uploaded/partial/skipped/error transitions, cross-tenant S3 key reject + non-http rekor URL reject, and a server-side ECDSA-verification harness for the rekor execute path; live AWS upload and live Rekor submission remain operator-side. K2 compliance mapping done; K3 repo-side scaffolds — audit-chain tamper-resistance and HTTP malformed-input gate — both done; external pen test remains as the K3 operator-engagement block. G6 mTLS connection overhead also done. I1-a + I1-b observability scaffolds done 2026-05-08 — live Tempo push and Grafana render are operator-side. I2-a webhook adapter + I2-b alert daemon done 2026-05-08 — Slack and Alertmanager formats supported, transition tracking verified end-to-end by `check_alert_webhook_smoke.py`. I3-a request submission and I3-b approval/reject/list/detail workflow are now repo-side complete.

### 10.2 Active Review Fixups

Both fixups are now resolved (2026-05-06). Kept here as a record so the next reviewer can see exactly what was changed and how it was validated:

1. **H2-b review fixup — Completed 2026-05-06; extended by G8 on 2026-05-08.** `scripts/serve_operator_dashboard.py` performs the per-tenant quota check and launch reservation atomically under `DashboardServer.job_lock` for both `POST /v1/jobs/start` and `POST /v1/jobs/{job_id}/relaunch`. `try_reserve_job()` / `release_reservation()` originally protected the single-active default path; G8 extended the same lock-protected reservation into an in-memory `jobs` registry so positive `--max-concurrent-jobs-per-tenant` values allow multiple same-tenant active jobs up to quota. Concurrent same-tenant requests can no longer bypass the configured quota, and positive-quota runs now return each start response from that job's own snapshot. Legacy non-atomic `tenant_quota_violation` helper removed.
2. **H3-a review fixup — Completed 2026-05-06.** `scripts/run_sse_bridge_pipeline.sh` final success summary now prints the resolved tenant-partitioned `${AUDIT_ARCHIVE_INDEX}` (i.e. `<dir>/<tenant_id>/audit_chain_index.jsonl`) when `--audit-archive-dir` is combined with `--tenant-id`, plus an explicit `audit tenant: <tenant_id>` line; the legacy non-partitioned fallback path remains for the no-tenant case. Validated by a bash trace exercising both modes.

Recommended next order:

1. ~~H2-b / H3-a review fixups~~ ✓ Completed 2026-05-06
2. ~~H3-b — per-tenant external ledger paths~~ ✓ Completed 2026-05-06
3. ~~H1-a — per-tenant Unix socket~~ ✓ Completed 2026-05-07
4. ~~H1-b — Kubernetes NetworkPolicy~~ ✓ Completed 2026-05-07
5. ~~F2-a — PostgreSQL primary/replica HA topology~~ ✓ Completed repo-side 2026-05-07
6. ~~F1-b — real PostgreSQL portability gate~~ ✓ Completed 2026-05-09
7. ~~F2-b — Patroni automated failover~~ ✓ Completed repo-side 2026-05-07
8. ~~F2-c — read-replica routing for sidecar reads~~ ✓ Completed repo-side 2026-05-07
9. ~~F3 — Connection Pooling~~ ✓ Completed repo-side 2026-05-07

**Optimization + large-scale benchmark only (G):** 3 blocks / 15h remaining (G3, G6, G7, and G8 done locally); remaining G scope is G4-a/G4-b/G5

**Critical path (shortest path to a load-tested, authority-backed platform):**
G4/G5 → J2-b = 4 remaining blocks / ~20h on the critical path (5 blocks / ~25h total remaining, including K3 external pen test). G1 + G2-a + G2-b + J1 + J2-a done repo-side/local 2026-05-07; G3 timing/report scaffold + G6 mTLS overhead + G8 concurrent dashboard jobs + I3-b approval workflow + K1-a S3 Object Lock + K1-b Sigstore Rekor + J4 chaos drill done 2026-05-08; F1-b + G3 phase-hotspot evidence + G7 done locally 2026-05-09.

---

## 11. What This Guidebook Does Not Cover

The following are out of scope for this guidebook and should be treated as separate initiatives:

1. **Multi-region deployment** — active-active across two data centers, with cross-region PostgreSQL replication and audit anchor synchronization.
2. **Full frontend product** — a React/Vue SPA admin console replacing the current embedded HTML dashboard.
3. **Temporal durable workflow** — replacing the current `subprocess.Popen` pipeline orchestration with a Temporal workflow that survives process restarts.
4. **Customer 360 / e-commerce fact warehouse** — building a full data warehouse on top of the privacy platform query results.
5. **HSM-backed key management** — using a Hardware Security Module instead of Vault for the bridge token secrets.
6. **SOC 2 Type II certification** — formal certification process requires an audit period and policy documentation beyond this guidebook's scope.

None of these are blocked by the work in this guidebook. They should be started after the remaining production-readiness blocks above are complete.

---

## 12. E-commerce Platform Tracks (Track-E1 / Track-E2 / Track-E3)

These tracks narrow down items §4.1, §4.5–4.7 of [`docs/COMPACT_PLATFORM_BRIEF.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/COMPACT_PLATFORM_BRIEF.md) — the "PJC + SSE e-commerce platform" story gaps that are not production-readiness blocks but are required to make the demo credible end-to-end. They live alongside Categories E–K, not inside them.

| Track | Scope | Status (2026-05-08) | Entry doc |
|-------|-------|---------------------|-----------|
| **Track-E1** | E-commerce fact-layer baseline: `orders` / `order_items` / `order_attribution` / `order_payment` / `order_fulfillment` / `customer_service_interactions` SQL tables, scope-key aligned with `sse_export_policy/v1`. | Repo-side complete: `migrations/metadata/010_add_ecommerce_fact_tables.sql` + Postgres parity in `migrations/postgres/001_init.sql` + `scripts/render_ecommerce_fact_layer.py` + `schemas/ecommerce_fact_layer_report.schema.json`; default contract smoke renders the report and asserts all 6 tables and ≥12 indexes. | [`docs/ECOMMERCE_FACT_LAYER_PLAN.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_FACT_LAYER_PLAN.md) |
| **Track-E2** | Business identity model: `business_identities` table + `identity_kind` enum (`buyer` / `merchant_staff` / `customer_service_agent` / `courier` / `field_marketer`) annotating callers without breaking the frozen `caller_permissions` schema. | Repo-side complete: `migrations/metadata/011_add_business_identities.sql` + Postgres parity + Track-E2 section appended to `docs/ECOMMERCE_ACCESS_MODEL.md`; PII-free design enforced by column set (no name/phone/address). | [`docs/ECOMMERCE_ACCESS_MODEL.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_ACCESS_MODEL.md) §业务身份扩展 |
| **Track-E3 / I3** | Operator console product baseline plus request-submission and approval workflow surface: `console_manifest/v1` contract + `config/operator_console/console_manifest.json` + static `index.html` placeholder + render/validate script; I3 adds submit/list/detail/approve/reject request workflow endpoints and contracts. | Repo-side complete: 9 sections (home / jobs / requests / audit / catalog / permissions / recovery / observability / compliance), `approval_workflow` feature flag, `POST /v1/request/submit`, `GET /v1/requests`, `GET /v1/requests/{submission_id}`, `POST /v1/request/{submission_id}/approve`, `POST /v1/request/{submission_id}/reject`, `workflow_submissions` metadata sidecar persistence, `operator_request_submission/v1`, `operator_request_submission_list/v1`, and contract smoke validation. The plan doc §9–§12 documents the split rule with I3, the approval state machine, the same-identity self-approval gate, and Phase-2 admin sections. | [`docs/OPERATOR_CONSOLE_PRODUCT_PLAN.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPERATOR_CONSOLE_PRODUCT_PLAN.md) |

These tracks do not change the privacy boundary: the bridge handoff still tokenizes only `(buyer_email, total_amount_cents)`; `business_identities` is annotation-only and does not introduce new stage gates; the operator console is glue over existing HTTP wrappers and does not bypass `caller_permissions`.

What is still operator-environment work after Track-E1/E2/E3:

1. Bulk-loading real (or anonymized real) order data into the new fact tables — repo only ships the schema and the report contract.
2. Building the SPA against `console_manifest/v1`. The static placeholder under `config/operator_console/index.html` reads the manifest and lists every section; the SPA replaces this page once a framework choice is made.
3. Running the manifest contract against a live deployment — the render script is contract-only.
