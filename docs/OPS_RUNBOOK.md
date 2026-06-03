# Ops Runbook

This runbook covers sidecar checks around the current privacy pipeline. It does not change the frozen `SSE -> record recovery -> bridge -> PJC -> policy release` path.

## Scope

Use these checks for:

1. Recovery-service reachability and health.
2. Key-agent and external-KMS reachability.
3. Completed pipeline artifact sanity checks.
4. Metadata sidecar DB sanity checks.

Do not use these tools to bypass policy validation, read encrypted record stores directly, or modify bridge/PJC/release contracts.

## Unified Health Check

The unified sidecar probe is:

```bash
python3 scripts/check_platform_health.py
```

With no arguments it returns a `platform_health/v1` warning that no checks were requested. Add one or more targets to make it useful.

### Recovery Service

For a Unix-socket or HTTP service described by the shared config:

```bash
python3 scripts/check_platform_health.py \
  --record-recovery-config config/record_recovery_service.example.json
```

For the HTTP example:

```bash
python3 scripts/check_platform_health.py \
  --record-recovery-config config/record_recovery_http_service.example.json
```

If the service uses `auth_token_env`, the corresponding environment variable must be set before probing.

### Per-Tenant Unix Socket

For Unix-socket recovery services, `record_recovery_service_config/v1` can omit `socket_path` when `tenant_id` is set. The config resolver derives a deterministic tenant-scoped socket:

```text
/tmp/seccomp_rr_<tenant>_<hash>.sock
```

The hash includes `tenant_id`, `service_id`, and `dataset_id`, so two tenant/service scopes do not silently share the same socket. `manage_record_recovery_service.py start|status|stop|render-systemd`, `run_record_recovery_service.py serve`, and `request_record_recovery_service.py --config` all resolve the same path.

Minimal tenant-derived Unix config:

```json
{
  "schema": "record_recovery_service_config/v1",
  "transport": "unix_socket",
  "service_id": "orders-recovery",
  "tenant_id": "tenant_demo",
  "dataset_id": "orders_analytics",
  "auth_token_env": "SSE_RECORD_RECOVERY_TOKEN",
  "lifecycle": {
    "pid_file": "tmp/tenant_demo_rr.pid",
    "ready_file": "tmp/tenant_demo_rr.ready",
    "log_file": "tmp/tenant_demo_rr.log"
  }
}
```

Start and probe:

```bash
export SSE_RECORD_RECOVERY_TOKEN=<token>
python3 scripts/manage_record_recovery_service.py start \
  --config tmp/tenant_demo_record_recovery.json

python3 scripts/request_record_recovery_service.py \
  --config tmp/tenant_demo_record_recovery.json
```

If an operator probes a config for a different `tenant_id` with no explicit `socket_path`, it resolves to a different socket and should be unreachable unless that tenant's service is running.

### Kubernetes NetworkPolicy

For Kubernetes deployments, render one ingress `NetworkPolicy` per tenant:

```bash
python3 scripts/render_k8s_network_policies.py \
  --tenant-id demo-tenant \
  --namespace seccomp-privacy \
  --out-dir tmp/k8s \
  --output tmp/k8s_network_policy_report.json \
  --assert-ok

python3 scripts/validate_json_contract.py \
  --schema schemas/k8s_network_policy_report.schema.json \
  --json tmp/k8s_network_policy_report.json
```

The generated policy selects recovery-service pods with:

```text
app=recovery-service
tenant=<tenant-id>
```

and allows ingress only from pipeline pods with:

```text
app=sse-bridge-pipeline
tenant=<same-tenant-id>
```

Use `--kubectl-dry-run` in an operator environment with `kubectl` configured:

```bash
python3 scripts/render_k8s_network_policies.py \
  --tenant-id demo-tenant \
  --namespace seccomp-privacy \
  --out-dir tmp/k8s \
  --output tmp/k8s_network_policy_report.json \
  --kubectl-dry-run \
  --assert-ok
```

Checked-in example:

```text
config/k8s/netpol-recovery-service-demo-tenant.yaml
```

### PostgreSQL Primary/Replica Topology

Render the F2-a development HA topology for the metadata PostgreSQL backend:

```bash
python3 scripts/render_postgres_ha_topology.py \
  --out-dir tmp/postgres-ha \
  --output tmp/postgres_ha_topology_report.json \
  --assert-ok

python3 scripts/validate_json_contract.py \
  --schema schemas/postgres_ha_topology_report.schema.json \
  --json tmp/postgres_ha_topology_report.json
```

Checked-in examples:

```text
config/postgres-ha/docker-compose.primary-replica.yml
config/postgres-ha/primary-init/01-create-replicator.sh
config/postgres-ha/.env.example
config/postgres-ha/verify_replication.sql
```

The generated compose topology uses PostgreSQL 16, `wal_level=replica`, `max_wal_senders`, `wal_keep_size`, a health-gated replica dependency, and `pg_basebackup -Xs -R` for standby bootstrap. In an operator environment with Docker available, add `--docker-compose-config` to run `docker compose -f <compose> config` as an extra syntax check before starting containers.

After the containers are running, verify replication from the primary with:

```bash
psql "$POSTGRES_PRIMARY_DSN" -f config/postgres-ha/verify_replication.sql
```

F2-a is a repo-side topology and contract artifact. Live startup, credential rotation, failover behavior, and lag SLOs remain operator-environment work and the later F2-b/F2-c/J blocks.

### Patroni Automated Failover

Render the F2-b Patroni/etcd topology:

```bash
python3 scripts/render_patroni_failover_topology.py \
  --out-dir tmp/patroni-ha \
  --output tmp/patroni_failover_topology_report.json \
  --assert-ok

python3 scripts/validate_json_contract.py \
  --schema schemas/patroni_failover_topology_report.schema.json \
  --json tmp/patroni_failover_topology_report.json
```

Checked-in examples:

```text
config/patroni-ha/docker-compose.patroni.yml
config/patroni-ha/patroni-primary.yml
config/patroni-ha/patroni-replica.yml
config/patroni-ha/patroni_failover_commands.sh
```

The generated Patroni configs share `scope=seccomp-privacy`, use `etcd3` as the DCS, expose REST APIs on `8008` / `8009`, set `ttl=30`, `loop_wait=10`, `retry_timeout=10`, and cap `maximum_lag_on_failover` at `1048576` bytes. They also enable `use_pg_rewind`, replication slots, WAL replica parameters, and SCRAM `pg_hba` entries.

In an operator environment with Docker available, add `--docker-compose-config` before startup to validate compose syntax:

```bash
python3 scripts/render_patroni_failover_topology.py \
  --out-dir tmp/patroni-ha \
  --output tmp/patroni_failover_topology_report.json \
  --docker-compose-config \
  --assert-ok
```

After the cluster is running, execute the checked-in command file from the topology directory or run the commands directly:

```bash
cd config/patroni-ha
PATRONI_CONFIG=patroni-primary.yml bash patroni_failover_commands.sh
```

F2-b is a repo-side topology and contract artifact. Actual switchover/failover timing, production credentials, quorum sizing, and HA SLO evidence remain operator-environment work.

### Metadata DB Failover Drill (J2-b)

`scripts/test_metadata_db_failover.py` is the repo-side scaffold for the J2-b PostgreSQL/Patroni failover drill. Default smoke runs entirely in-process against a fresh SQLite DB and patches `metadata_db.connect_db` so the first `--simulated-failure-count` calls raise a synthetic `OperationalError`; `connect_db_with_retry` has to ride those out within `--failover-target-seconds`. The script then writes a post-failover row through the recovered connection and confirms a fresh read sees both rows.

Run the default scaffold (covered by `bash scripts/check_json_contracts.sh`):

```bash
python3 scripts/test_metadata_db_failover.py \
  --simulated-failure-count 2 \
  --retry-attempts-allowed 4 \
  --retry-base-delay-seconds 0.05 \
  --failover-target-seconds 30 \
  --output tmp/metadata_db_failover_test.json \
  --assert-ok

python3 scripts/validate_json_contract.py \
  --schema schemas/metadata_db_failover_test.schema.json \
  --json tmp/metadata_db_failover_test.json
```

For the live operator drill, point the same script at the live DSN and pair it with a Patroni switchover:

```bash
# (a) verify retry path against the live DSN (still uses the in-process simulator)
python3 scripts/test_metadata_db_failover.py \
  --db-dsn postgresql://postgres:pass@pgbouncer:6432/postgres \
  --simulated-failure-count 2 \
  --retry-attempts-allowed 4 \
  --failover-target-seconds 30 \
  --output tmp/metadata_db_failover_test.json \
  --assert-ok

# (b) trigger a real Patroni switchover and re-run the importer through the same DSN
patronictl -c config/patroni-ha/patroni-primary.yml switchover \
  --master pg-primary --candidate pg-replica --force
python3 scripts/check_platform_health.py \
  --metadata-db-dsn postgresql://postgres:pass@pgbouncer:6432/postgres
python3 scripts/import_run_metadata.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --db-dsn postgresql://postgres:pass@pgbouncer:6432/postgres
```

J2-b acceptance: `failover_request.within_failover_target=true`, `post_failover_query.data_round_trip_ok=true`, `data_integrity.no_data_lost=true`, sidecar reconnects within 30s post-Patroni-switchover.

### Scale Benchmarks (G4-a / G4-b / G5)

These three benchmarks share the same `a-psi/private-join-and-compute/bazel-bin/private_join_and_compute/{server,client}` binary plus the prebuilt `bridge/target/release/bridge`. Default contract smoke does not run them — they are explicit operator measurements. Each writes a schema-validated JSON report under `tmp/`.

**G4-a — PJC intersection scaling**

```bash
# 1k smoke
python3 scripts/benchmark_pjc.py --mode generated_scale_csv \
  --server-items 1000 --client-items 1000 --overlap 0.2 --iterations 1 \
  --output tmp/pjc_benchmark_1k.json --timeout-sec 120

# 100k acceptance (must be < 300s)
python3 scripts/benchmark_pjc.py --mode generated_scale_csv \
  --server-items 100000 --client-items 100000 --overlap 0.2 --iterations 1 \
  --output tmp/pjc_benchmark_100k.json --timeout-sec 1800
```

Local 2026-05-09 reference timings: 1k=10.7s/14 MB, 10k=32.8s/38 MB, **100k=222.0s/261 MB ✓**.

**G4-b — Memory ceiling + connection reuse**

```bash
# Three back-to-back invocations to verify runner re-entrancy and absence of leak
python3 scripts/benchmark_pjc.py --mode generated_scale_csv \
  --server-items 10000 --client-items 10000 --overlap 0.2 --iterations 3 \
  --output tmp/pjc_benchmark_10k_x3.json --timeout-sec 600

# 1M memory ceiling (multi-hour wall time; budget for ~30-60 minutes per iteration)
python3 scripts/benchmark_pjc.py --mode generated_scale_csv \
  --server-items 1000000 --client-items 1000000 --overlap 0.2 --iterations 1 \
  --output tmp/pjc_benchmark_1m.json --timeout-sec 7200 --allow-failures
```

Acceptance: per-iteration `intersection_size` and `intersection_sum` constant across 10k iterations; `peak_rss_kb` does not grow across 10k iterations; 1M `peak_rss_kb` and failure mode are documented. The 2026-05-12 1M rerun wrote `tmp/pjc_benchmark_1m.json` with `duration_ms=1963428.32`, `peak_rss_kb=2248648`, `exit_code=1`, `timed_out=false`, and null intersection metrics, confirming the old unary single-machine gRPC message-size ceiling rather than a timeout. The 2026-05-14 streaming transport rerun wrote `tmp/pjc_streaming_1m_benchmark.json` with `duration_ms=2045196.066`, `peak_rss_kb=2204740`, `exit_code=0`, `intersection_size=200000`, and `intersection_sum=20020100000`.

**G5 — End-to-end pipeline SLO at 10k**

```bash
BRIDGE_BIN="$(pwd)/bridge/target/release/bridge" \
  python3 scripts/benchmark_pipeline_slo.py \
    --server-rows 10000 --client-rows 10000 --overlap-count 1000 \
    --output tmp/pipeline_slo_10k.json --timeout-sec 600 --assert-ok

python3 scripts/validate_json_contract.py \
  --schema schemas/pipeline_slo_benchmark.schema.json \
  --json   tmp/pipeline_slo_10k.json
```

The benchmark spawns `scripts/run_sse_bridge_pipeline.sh` (file-handoff mode) over deterministic JSONL fixtures, validates `intersection_size=1000` / `intersection_sum=599,500`, auto-derives `pipeline_observability/v1` from `audit_chain.json`, and evaluates per-stage `duration_ms` against the `SLO_TARGETS_MS` table. SLO targets:

| Stage | p50 | p95 |
|-------|----:|----:|
| sse_export | 5s | 15s |
| record_recovery (encrypted store only) | 500ms | 2s |
| bridge_prepare_job | 10s | 30s |
| pjc | 60s | 120s |
| policy_release | 1s | 3s |
| **total_pipeline** | **90s** | **180s** |

`record_recovery` is reported as `not_applicable` when the fixture skips the encrypted record store (the default JSONL path); to exercise the recovery boundary, swap to `scripts/run_live_sse_bridge_demo.sh` with an encrypted record store. Local 2026-05-09 reference run: total **34.9s** ✓ (38% of p50 budget); per-stage sse 48ms / bridge 13ms / pjc 33,878ms / policy 0ms.

### Recovery Service Runtime Logs

When the recovery service is started through `scripts/manage_record_recovery_service.py start` with a `log_file` in its config lifecycle block, stdout/stderr are captured there. The service now writes one JSON object per line using `record_recovery_service_log/v1`.

The log records:

- service start and stop events
- health and recover request events
- request ID, transport, service scope, decision, reason code, and `duration_ms`
- non-sensitive caller/job/role/candidate-count context when present

Validate a captured log with:

```bash
python3 scripts/validate_json_contract.py \
  --schema schemas/record_recovery_service_log.schema.json \
  --jsonl tmp/record_recovery_service.log
```

Derive a compact metrics report from the same log with:

```bash
python3 scripts/export_record_recovery_service_metrics.py \
  --log-jsonl tmp/record_recovery_service.log \
  --out tmp/record_recovery_service_metrics.json \
  --expect-event record_recovery_service_start \
  --expect-event record_recovery_service_request \
  --expect-event record_recovery_service_stop \
  --expect-min-requests 1

python3 scripts/validate_json_contract.py \
  --schema schemas/record_recovery_service_metrics.schema.json \
  --json tmp/record_recovery_service_metrics.json
```

The metrics contract is `record_recovery_service_metrics/v1`. It summarizes event/request counts, transport coverage, decisions, reason codes, ops, roles, status-code buckets, candidate counts, and request-duration min/max/avg/p95. It intentionally does not list raw candidate IDs, record-store contents, auth tokens, or per-caller sensitive payloads.

These runtime logs are operational telemetry. They do not replace `sse_record_recovery_service_audit/v1`, which remains the audit stream used by `audit_chain.json`.

### mTLS Recovery Service

To start the recovery service with mutual TLS, use the mTLS example config or add a `tls` block to any `record_recovery_service_config/v1` file:

```bash
# Generate self-signed test certs (one-time, not for production)
mkdir -p tmp/mtls
openssl req -x509 -newkey rsa:2048 -keyout tmp/mtls/ca.key -out tmp/mtls/ca.crt -days 365 -nodes -subj "/CN=test-ca"
openssl req -newkey rsa:2048 -keyout tmp/mtls/server.key -out tmp/mtls/server.csr -nodes -subj "/CN=localhost"
openssl x509 -req -in tmp/mtls/server.csr -CA tmp/mtls/ca.crt -CAkey tmp/mtls/ca.key -CAcreateserial -out tmp/mtls/server.crt -days 365
openssl req -newkey rsa:2048 -keyout tmp/mtls/client.key -out tmp/mtls/client.csr -nodes -subj "/CN=test-client"
openssl x509 -req -in tmp/mtls/client.csr -CA tmp/mtls/ca.crt -CAkey tmp/mtls/ca.key -CAcreateserial -out tmp/mtls/client.crt -days 365

export SSE_RECORD_RECOVERY_TOKEN=test-recovery-token
python3 scripts/manage_record_recovery_service.py start \
  --config config/record_recovery_http_mtls_service.example.json \
  --pid-file tmp/record_recovery_service_http_mtls.pid \
  --log-file tmp/record_recovery_service_http_mtls.log
```

Probe health over mTLS:

```bash
python3 scripts/request_record_recovery_service.py \
  --config config/record_recovery_http_mtls_service.example.json
```

The TLS config block in `record_recovery_service_config/v1` accepts:

| Field | Required | Description |
| ----- | -------- | ----------- |
| `tls.enabled` | yes | Set `true` to enable TLS |
| `tls.server_cert` | yes | Path to server certificate (PEM) |
| `tls.server_key` | yes | Path to server private key (PEM) |
| `tls.ca_cert` | when `require_client_cert=true` | CA cert used to verify client certs |
| `tls.require_client_cert` | no | Set `true` to enforce mutual TLS |
| `tls.client_cert` | no | Client certificate for the client side |
| `tls.client_key` | no | Client private key |
| `tls.verify_hostname` | no | Default `true`; set `false` for loopback self-signed certs |

The service emits `tls_enabled` and `tls_require_client_cert` in the `record_recovery_service_start` log entry so operators can confirm TLS state from the structured log without parsing process arguments.

Stop the mTLS service:

```bash
python3 scripts/manage_record_recovery_service.py stop \
  --config config/record_recovery_http_mtls_service.example.json \
  --pid-file tmp/record_recovery_service_http_mtls.pid
```

### External KMS

```bash
python3 scripts/check_platform_health.py \
  --external-kms-config config/external_kms.example.json
```

If the KMS config uses auth tokens, set the referenced env vars first.

### Authority Governance Smoke

Use this when you want one operator-facing summary over identity, authz, KMS, service-token, issuer, policy-drift, and key-drift checks:

```bash
python3 scripts/check_authority_governance.py \
  --policy-drift tmp/policy_drift_clean.json \
  --key-drift tmp/key_backend_drift_clean.json \
  --identity-resolution tmp/api_identity_resolution_bearer.json \
  --openfga-check tmp/openfga_check_allowed.json \
  --kms-reachability tmp/kms_reachability_authority.json \
  --service-token-report tmp/service_token_verify.json \
  --issuer-rotation tmp/issuer_rotation_dry.json \
  --output tmp/authority_governance_report.json \
  --assert-ok
```

The report contract is `authority_governance_report/v1`. It is a read-only rollup over existing reports; use `checks[].source_path` to drill into the original authority report. A warning means at least one input is degraded but not directly blocking; an error means at least one authority check failed and should be fixed before execute/release workflows are trusted.

For a live OpenFGA-backed check, pass `--openfga-config config/openfga.example.json` together with `--openfga-user`, `--openfga-relation`, and `--openfga-object`. The default contract smoke keeps using the SQLite fallback; setting `OPENFGA_ENDPOINT` and `OPENFGA_STORE_ID` enables the optional live OpenFGA branch in `scripts/check_json_contracts.sh`, which applies tuples, performs a live check, and validates the authority-governance rollup.

### Authority Service Stack

For local production-readiness validation of the E tranche, start the optional authority stack:

```bash
docker compose -f docker-compose.authority.yml up keycloak openfga vault
```

The stack imports `config/keycloak_realm_seccomp_privacy.json`, exposes OpenFGA for `config/openfga.example.json`, and starts Vault dev mode. Repo smoke remains offline by default; live operations require explicit `--execute` or `OPENFGA_ENDPOINT` / `OPENFGA_STORE_ID`.

Useful live/dry-run helpers:

```bash
python3 scripts/request_oidc_client_credentials.py \
  --token-endpoint http://127.0.0.1:8080/realms/seccomp-privacy/protocol/openid-connect/token \
  --client-id recovery-service

python3 scripts/setup_openfga_model.py \
  --openfga-config config/openfga.example.json \
  --model config/openfga_authorization_model.json

python3 scripts/issue_mtls_certs.py \
  --config config/vault_pki.example.json \
  --out-dir tmp/mtls \
  --assert-ok
```

### Key Agent

Probe a running key agent over its Unix socket:

```bash
python3 scripts/check_platform_health.py \
  --key-agent-socket /tmp/seccomp_key_agent.sock \
  --key-name bridge-token \
  --key-purpose bridge_token \
  --caller auto_demo
```

The probe redacts the returned secret and only reports whether a secret was present plus the resolved key version.

### Completed Pipeline Run

Check a completed run directory for the expected artifacts and public report summary:

```bash
python3 scripts/check_platform_health.py \
  --out-base tmp/sse_bridge_pipeline_demo
```

The probe verifies the expected files exist and parses `a_psi_run/public_report.json` plus `audit_chain.json` when present.
For completed runs it now also reports whether `audit_chain.json` embeds `mainline_contract_check/v1`, whether that owner-scope contract check is `status=ok`, whether managed server/client handoff artifacts ended in `removed` / `cleaned` state, and a compact `service_audit_consistency` summary that tells you whether the per-role `server` / `client` recovery-service audit path is `ok`, `fail`, or `not_applicable` relative to the matching SSE export audit records for scope fields, join/value fields, filter hashes, record-store path/hash, and output path/hash/row counts.

### Privacy Budget Release Gate

Policy release can optionally write and enforce a local privacy-budget ledger. This is the S3 repo-side first gate; it is disabled unless `--privacy-budget-ledger` is passed.

```bash
python3 a-psi/moduleA_psi/scripts/policy_release.py \
  --input tmp/a_psi_run/attribution_result.json \
  --job-meta tmp/bridge_job/job_meta.json \
  --out tmp/a_psi_run/public_report.json \
  --audit-log tmp/a_psi_run/audit_log.jsonl \
  --caller commerce_ops_demo \
  --threshold-k 20 \
  --max-queries 5 \
  --privacy-budget-ledger tmp/privacy_budget_ledger.jsonl \
  --privacy-budget-limit 5
```

When enabled, the gate computes a budget fingerprint that excludes `job_id`, so re-submitting the same query under a new job ID is still treated as the same privacy query. It denies exact repeats, overlapping or containing windows for the same caller/bucket, and exhausted budget before writing an allowed public report. Validate evidence with:

```bash
python3 scripts/validate_json_contract.py \
  --schema schemas/privacy_budget_ledger.schema.json \
  --jsonl tmp/privacy_budget_ledger.jsonl
```

Summarize the ledger and assert expected deny paths with:

```bash
python3 scripts/check_privacy_budget.py \
  --ledger tmp/privacy_budget_ledger.jsonl \
  --expect-consumed-min 1 \
  --expect-deny-reason privacy_budget_duplicate_query \
  --expect-deny-reason privacy_budget_exhausted \
  --output tmp/privacy_budget_check_report.json
```

The policy audit record also carries a `privacy_budget` summary. The public report intentionally does not expose ledger path, budget used, or prior-query identifiers.

### Bridge Handoff Exposure Assessment

Every completed pipeline run embeds a `handoff_exposure_assessment` object in `mainline_contract_check.json`. Read it to determine whether plaintext bridge-ready rows ever touched disk:

```bash
python3 -c "
import json, sys
p = json.load(open(sys.argv[1]))
ea = p.get('handoff_exposure_assessment') or {}
print('handoff_mode          :', ea.get('handoff_mode'))
print('plaintext_exposure_risk:', ea.get('plaintext_exposure_risk'))
for role in ('server', 'client'):
    r = ea.get(f'{role}_exposure') or {}
    print(f'  {role}: type={r.get(\"output_file_type\")} cleanup={r.get(\"cleanup_status\")} risk={r.get(\"exposure_risk\")}')
" tmp/sse_bridge_pipeline_demo/mainline_contract_check.json
```

`plaintext_exposure_risk` interpretation:

| Value | Meaning |
| ----- | ------- |
| `none` | FIFO handoff used for all roles; no plaintext CSV was written to disk. |
| `low` | File handoff used, but both roles cleaned up (CSV deleted after `bridge prepare-job`). Transient exposure only. |
| `elevated` | File handoff retained on disk (`--keep-sse-export-handoff-files`). Plaintext still present. Investigate `retention_reason`. |
| `unknown` | Handoff mode or cleanup status could not be determined from audit records. |

For normal pipeline runs the expected value is `none` (FIFO mode) or `low` (default file mode with cleanup). `elevated` should only appear when `--keep-sse-export-handoff-files --handoff-retention-reason <text>` was explicitly passed, in which case `retention_reason` is also recorded in `handoff_cleanup.*.retention_reason`.

File mode carries higher plaintext exposure than FIFO mode. When both modes are available, prefer `--sse-export-handoff-mode fifo`. File mode is kept as the compatibility and debugging path; it is not the recommended production path.

### Metadata DB

Check a sidecar metadata DB:

```bash
python3 scripts/check_platform_health.py \
  --metadata-db tmp/platform_metadata.db
```

This verifies the required tables exist and reports row counts for jobs, artifacts, and audit events.

For sidecar lifecycle actions beyond the read-only health probe:

```bash
python3 scripts/manage_metadata_db.py status \
  --db-path tmp/platform_metadata.db

python3 scripts/manage_metadata_db.py backup \
  --db-path tmp/platform_metadata.db \
  --out-path tmp/platform_metadata.backup.db

python3 scripts/manage_metadata_db.py restore \
  --backup-db-path tmp/platform_metadata.backup.db \
  --out-db-path tmp/platform_metadata.restored.db

python3 scripts/manage_metadata_db.py export-json \
  --db-path tmp/platform_metadata.db \
  --out-path tmp/platform_metadata.export.json

python3 scripts/export_authz_tuples.py \
  --db-path tmp/platform_metadata.db \
  --output tmp/platform_authz_tuples.json

python3 scripts/materialize_control_plane_deepening.py \
  --db-path tmp/platform_metadata.db \
  --catalog-lineage tmp/catalog_lineage.json \
  --output tmp/control_plane_deepening.json \
  --assert-ok
```

Use them as follows:

1. `status`: inspect applied/pending migrations, table counts, latest imported job, and DB file digest through `metadata_db_status/v1`
2. `backup`: create a consistent SQLite copy via the backup API, emitting `metadata_db_backup/v1`
3. `restore`: restore a fresh SQLite copy from a backup DB, emitting `metadata_db_restore/v1` with embedded `restored_status`
4. `export-json`: materialize a portable sidecar snapshot with status, job list, registry/policy entities, and sample artifacts as `metadata_db_export/v1`
5. `export_authz_tuples.py`: materialize the current caller/tenant/dataset/service authz slice as `authz_tuple_export/v1`, either from the sidecar DB or directly from a policy file, for OpenFGA-style relationship sync without changing the frozen pipeline contracts
6. `materialize_control_plane_deepening.py`: rebuild C1-C5 sidecar read models (`job_state_transitions`, `policy_versions`, `service_versions`, `catalog_lineage_read_model`, `retention_reconcile_plan`) and emit `control_plane_deepening_report/v1`; this is non-runtime metadata materialization, not a main-chain DB write path

## Combined Check

Multiple probes can be combined into one report:

```bash
python3 scripts/check_platform_health.py \
  --record-recovery-config config/record_recovery_service.example.json \
  --external-kms-config config/external_kms.example.json \
  --out-base tmp/sse_bridge_pipeline_demo \
  --metadata-db tmp/platform_metadata.db \
  --output tmp/platform_health.json
```

The command exits non-zero if any requested check has `status=error`. Use `--allow-errors` when collecting diagnostics should not fail the surrounding script.

## Operator Dashboard Web UI

Start the local admin shell (`PJC X-UI`) — a self-contained web UI that reads sidecar artifacts and renders live control and audit panels in the browser:

```bash
# Step 1: generate the required sidecar files (if not already present)
python3 scripts/export_observability_events.py \
  --out-base tmp/live_sse_bridge_demo/run-<timestamp> \
  --out tmp/live_sse_bridge_demo/run-<timestamp>/pipeline_observability.json

python3 scripts/check_platform_health.py \
  --out-base tmp/live_sse_bridge_demo/run-<timestamp> \
  --output tmp/live_sse_bridge_demo/run-<timestamp>/platform_health.json

# Step 2: start the dashboard server
python3 scripts/serve_operator_dashboard.py \
  --out-base tmp/live_sse_bridge_demo/run-<timestamp> \
  --history-root tmp \
  --bind-host 127.0.0.1 \
  --port 18094
```

Then open **http://127.0.0.1:18094/** in a browser.

The admin shell auto-refreshes every 15 seconds and shows:

| Panel | Content |
| ----- | ------- |
| **Control Center** | Request-file centric launch form plus live/result job state |
| **Audit Center** | SSE audit summaries, wrapper receipt/status summary, artifact inventory, and mainline contract summary |
| **Recent Runs** | Multi-run job list with active-run switching under `--history-root` |
| **Alerts** | 4 alert conditions with firing/ok status and triage message |
| **Platform Health** | Per-component health badges (ok / warn / error) |
| **Job Setup** | Request-file centric start form for a live query workflow job |
| **Live Progress** | Per-stage live state from `GET /v1/jobs/{job_id}` while a job is running |
| **Result** | `intersection_size` / `intersection_sum` / `released` / `reason_code` for the terminal job |
| **Stage Summary** | Per-stage ok/error mini bar chart |
| **Stage Duration** | min / mean / p50 / p95 / max per stage |
| **Release Outcomes** | Per-tenant policy-release counts and last outcome |
| **Failure Summary** | All `status=error` events with caller, stage, reason_code |
| **Stage Timeline** | Chronological event list with timestamps and durations |
| **Workflow Status** | Still present in `/v1/dashboard` JSON for backward compatibility, but no longer rendered as a standalone UI card |

Endpoints:

| Route | Returns |
| ----- | ------- |
| `GET /` | The `PJC X-UI` admin HTML shell. Use loopback-only unless dashboard auth is explicitly configured. |
| `GET /healthz` | `{"status":"ok","schema":"operator_dashboard_health/v1"}` |
| `GET /v1/dashboard` | Aggregated dashboard JSON. With auth configured, unauthenticated reads are denied, normal identity callers receive `operator_dashboard_public_summary/v1`, and privileged operator/auditor roles receive the full dashboard. |
| `GET /v1/runs` | Recent-run list derived from `query_workflow/status.json` discovery under `--history-root` |
| `POST /v1/runs/select` | Switches the active admin-shell `out_base` to another discovered run |
| `POST /v1/jobs/{job_id}/relaunch` | Retry / re-submit a selected terminal run using its recorded request file and retry-eligibility recommendation |
| `POST /v1/jobs/start` | Starts a background pipeline job from `request_file` or inline `query_workflow_request/v1` |
| `GET /v1/jobs/{job_id}` | Live job state, elapsed seconds, per-stage status list |
| `GET /v1/jobs/{job_id}/result` | Terminal result summary (`intersection_size`, `intersection_sum`, `released`, `reason_code`) |

The `/v1/dashboard` response is cached for 5 seconds. If neither
`--auth-token-env` nor identity-token auth is configured, the dashboard is a
local admin-only sidecar and must stay on loopback. If auth is configured,
`/v1/dashboard` first authenticates the caller: normal identity callers get a
caller-safe public summary with paths, hashes, raw artifact inventory, and exact
intersection metrics redacted; `platform_admin`, `platform_auditor`,
`privacy_operator`, and `compliance_auditor` can read the full dashboard. A
shared bearer token remains an admin channel, so do not distribute it to normal
business callers. With auth configured, the full-read/admin endpoints
`/v1/runs`, `/v1/jobs/{job_id}`, `/v1/jobs/{job_id}/result`, `/v1/runs/select`,
`/v1/jobs/{job_id}/relaunch`, and direct `/v1/jobs/start` require privileged
operator/auditor roles or the shared admin bearer token. Historical dashboard
reads remain sidecar-only, but `POST /v1/jobs/start` now launches a local
background pipeline job and the UI exposes SSE audit + artifact inventory
directly, so do not expose this server outside a trusted admin environment
without identity-backed auth.

Phase-1 start example:

```bash
curl --noproxy '*' \
  -X POST http://127.0.0.1:18094/v1/jobs/start \
  -H 'Content-Type: application/json' \
  --data '{
    "request_file":"docs/examples/query_request.json",
    "overrides":{
      "job_id":"dashboard_job_demo",
      "out_base":"tmp/operator_dashboard_demo"
    }
  }'
```

Poll live state:

```bash
curl --noproxy '*' http://127.0.0.1:18094/v1/jobs/dashboard_job_demo
curl --noproxy '*' http://127.0.0.1:18094/v1/jobs/dashboard_job_demo/result
```

List or switch recent runs:

```bash
curl --noproxy '*' http://127.0.0.1:18094/v1/runs?limit=10

curl --noproxy '*' \
  -X POST http://127.0.0.1:18094/v1/runs/select \
  -H 'Content-Type: application/json' \
  --data '{"out_base":"tmp/operator_dashboard_jobtest2"}'

curl --noproxy '*' \
  -X POST http://127.0.0.1:18094/v1/jobs/dashboard_run_failed_smoke/relaunch \
  -H 'Content-Type: application/json' \
  --data '{}'
```

## Platform Health HTTP API

For local UI / SDK / operations tooling that should reuse the existing `platform_health/v1` report over HTTP instead of shelling out directly:

```bash
export SECCOMP_PLATFORM_HEALTH_API_TOKEN=local-platform-health-token
python3 scripts/serve_platform_health_api.py \
  --bind-host 127.0.0.1 \
  --port 18093 \
  --auth-token-env SECCOMP_PLATFORM_HEALTH_API_TOKEN
```

Health:

```bash
curl http://127.0.0.1:18093/healthz
```

Combined report:

```bash
curl -H "Authorization: Bearer $SECCOMP_PLATFORM_HEALTH_API_TOKEN" \
  "http://127.0.0.1:18093/v1/platform-health?out_base=$PWD/tmp/sse_bridge_pipeline_demo&metadata_db=$PWD/tmp/platform_metadata.db"
```

This API is read-only. It does not invent a new health schema or a second implementation path; it wraps the same `scripts/check_platform_health.py` component checks and returns the same `platform_health/v1` result inside HTTP envelopes.

## Existing Focused Tools

Use focused tools when you need lifecycle actions rather than read-only health summaries:

```bash
python3 scripts/manage_record_recovery_service.py status \
  --config config/record_recovery_service.example.json
```

```bash
python3 scripts/request_record_recovery_service.py \
  --config config/record_recovery_service.example.json
```

```bash
python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --job-id auto_demo_job
```

`query_metadata.py --job-id ...` now returns per-stage `duration_ms` in `stage_status` plus per-event `duration_ms` in `audit_events` when the imported run was produced by the current audit writers.
It also carries a compact `mainline_contract_summary` derived from the recorded `audit_chain_path`, so metadata readers can see handoff cleanup state and per-role `service_audit_consistency` without reopening `audit_chain.json` themselves.
It now also returns `timing_summary`, and list queries such as `--caller` / `--tenant-id` include `stage_duration_summary` plus `total_stage_duration_ms` for each returned job, along with a top-level `mainline_contract_summary_counts` rollup for embedded-mainline, handoff-cleanup, and per-role `service_audit_consistency` distributions across the current result set. `grouped_status_summary` and `grouped_stage_summary` buckets now carry the same owner-summary rollup per bucket, and status/stage CSV/TSV exports include those count fields directly. `caller-permissions` entity reads now also return a richer `permission_summary` with `enabled_counts`, `platform_role_counts`, `callers_by_platform_role`, and per-caller `access_profiles`, so operators can inspect the current file-backed authz slice as a compact role matrix instead of manually decoding raw permission rows. Add `--stage bridge` (or any imported stage name) to restrict the job list to runs that imported that stage and to emit a stage-scoped `matched_stage` plus top-level `stage_summary`; add `--stage-status allow|deny|observed|missing` and `--stage-sort duration_desc|duration_asc` when you need to further narrow or rank that stage view; add `--group-by stage` when you want a `grouped_stage_summary` rollup over the returned jobs; add `--group-by status` when you want a `grouped_status_summary` rollup by overall job outcome; add `--list-entity tenants|datasets|services|callers|policies|policy-bindings|caller-permissions` when you want to inspect imported scope entities or policy tables directly; add `--output-format csv|tsv` to export those grouped rollups or entity lists as shell-friendly delimited output; add `--columns` to restrict delimited output to selected fields and `--output-file` to write the rendered report directly to disk.

### Metadata HTTP API

For local UI / SDK / adapter testing, serve the same metadata through a read-only HTTP API:

```bash
export SECCOMP_METADATA_API_TOKEN=local-metadata-token
python3 scripts/serve_metadata_api.py \
  --db-path tmp/platform_metadata.db \
  --bind-host 127.0.0.1 \
  --port 18090 \
  --auth-token-env SECCOMP_METADATA_API_TOKEN
```

Probe health:

```bash
curl http://127.0.0.1:18090/healthz
```

Fetch one job:

```bash
curl -H "Authorization: Bearer $SECCOMP_METADATA_API_TOKEN" \
  "http://127.0.0.1:18090/v1/jobs/auto_demo_job"
```

Fetch filtered jobs or registry/policy entities:

```bash
curl -H "Authorization: Bearer $SECCOMP_METADATA_API_TOKEN" \
  "http://127.0.0.1:18090/v1/jobs?caller=auto_demo&stage=bridge&limit=5"
curl -H "Authorization: Bearer $SECCOMP_METADATA_API_TOKEN" \
  "http://127.0.0.1:18090/v1/entities/policies?limit=10"
```

This API is read-only and DB-backed. It does not re-run imports, query SSE, or bypass the frozen privacy pipeline.
Its health/success/error envelopes are now frozen in `schemas/metadata_api_*.schema.json` and validated by default contract smoke together with the existing API behavior checks.
When you want lifecycle hooks for a local supervisor, pass `--pid-file` and `--ready-file`; the service now removes those files during graceful `SIGTERM` / `SIGINT` shutdown.

## Query Workflow Wrapper

For local query-submit adapter testing without changing the main pipeline entrypoint:

```bash
python3 scripts/submit_query_workflow.py \
  --request-file docs/examples/query_request.json \
  --dry-run
```

This validates a limited JSON request, resolves relative paths against the request file, and emits a redacted submission manifest instead of executing the pipeline immediately.

The request and manifest structures are also pinned in `schemas/query_workflow_request.schema.json` and `schemas/query_workflow_submission.schema.json`. Secret-mode exclusivity and KMS dependency checks still happen in the adapter runtime, not just in schema validation.

To actually run the workflow after inspection:

```bash
python3 scripts/submit_query_workflow.py \
  --request-file docs/examples/query_request.json \
  --execute
```

This wrapper is still adapter-only. It ultimately calls `scripts/run_sse_bridge_pipeline.sh` and does not define a new privacy-computing core contract.

For a local HTTP wrapper over the same adapter:

```bash
export SECCOMP_QUERY_WORKFLOW_API_TOKEN=local-query-token
python3 scripts/serve_query_workflow_api.py \
  --bind-host 127.0.0.1 \
  --port 18091 \
  --auth-token-env SECCOMP_QUERY_WORKFLOW_API_TOKEN
```

Health:

```bash
curl http://127.0.0.1:18091/healthz
```

Dry-run submit:

```bash
curl -X POST \
  -H "Authorization: Bearer $SECCOMP_QUERY_WORKFLOW_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Request-Base-Dir: $PWD/docs/examples" \
  --data @docs/examples/query_request.json \
  http://127.0.0.1:18091/v1/query-workflows/dry-run
```

By default, `/v1/query-workflows/execute` is disabled. Only enable it with `--allow-execute` when you explicitly want the server to run the integrated pipeline.

For a thin local SDK/CLI shell over the metadata, query, audit/public-report, and platform-health APIs:

```bash
python3 scripts/platform_api_client.py query-submit \
  --request-file docs/examples/query_request.json
python3 scripts/platform_api_client.py query-status \
  --out-base /abs/path/to/query_out_base \
  --job-id query_demo_job
python3 scripts/platform_api_client.py metadata-entity \
  --entity caller-permissions \
  --param caller=auto_demo \
  --param limit=20
python3 scripts/platform_api_client.py audit-public-report
python3 scripts/platform_api_client.py platform-health \
  --param out_base=tmp/sse_bridge_pipeline_demo \
  --param metadata_db=tmp/platform_metadata.db
```

The local contract smoke now validates:

1. `docs/examples/query_request.json` against `schemas/query_workflow_request.schema.json`
2. CLI dry-run output against `schemas/query_workflow_submission.schema.json`
3. `submission_manifest.json`, `execution_receipts.jsonl`, and `status.json` under `out_base/query_workflow/` against the frozen query-workflow sidecar schemas
4. `/healthz`, dry-run success envelopes, status envelopes, execute run-failed envelopes, and API error envelopes against `schemas/query_workflow_api_*.schema.json`
5. `scripts/platform_api_client.py` against the query submit API including the disabled `--execute` path, status reads, execute run-failed status reads, metadata health/job/jobs/entity reads, audit health/audit-chain/public-report/observability/catalog-lineage reads including `--include-paths`, and the platform-health API

Those metadata job/job-list reads now also preserve the compact `mainline_contract_summary`, and jobs-list reads also expose `mainline_contract_summary_counts`, so both direct HTTP callers and `platform_api_client.py metadata-job` / `metadata-jobs` can see the owner-scope handoff cleanup and recovery-service consistency verdicts through the metadata surface without client-side rescans.

### Execute Governance Checklist

When moving from `dry-run` to `execute`, use the wrapper as an operator gate, not as a shortcut around the frozen pipeline.

Recommended checklist:

1. run `dry-run` first using the same request body or request file
2. confirm the authenticated identity is allowed to execute, not just submit
3. confirm `caller`, `tenant_id`, `dataset_id`, and `record_recovery_service_id` remain within the identity-bound scope
4. prefer `token_secret_env` or KMS-backed secret resolution over inline `token_secret`
5. prefer FIFO handoff; treat retained file handoff as an exceptional debugging path only
6. do not execute requests that rely on `unsafe_allow_no_sse_export_policy`

For the current repo baseline, execute is still limited to the same `cross_party_match` wrapper shape described in `docs/QUERY_INTERFACE_PLAN.md`. It is not a general SQL execute surface.

### Current Execute Triage

The wrapper now has a dedicated receipt/status sidecar, so use this triage order after an execute attempt:

1. inspect the returned `receipt` / `status` pair and the resolved sidecar paths from the API or CLI response
2. inspect `<out_base>/query_workflow/status.json` and `<out_base>/query_workflow/execution_receipts.jsonl`
3. inspect the redacted `query_workflow_submission/v1` manifest and command
4. inspect `audit_chain.json` and `public_report.json` when the pipeline actually launched
5. inspect `platform_health/v1` if launch/runtime failure looks environmental rather than request-specific

Use the following failure classes as the operator mental model:

| Class | Meaning | First place to inspect |
| --- | --- | --- |
| `validation_rejected` | request/secret/semantic validation failed before launch | wrapper stderr or API error envelope |
| `authz_rejected` | role/permission/scope gate failed before launch | wrapper stderr or API error envelope |
| `launch_failed` | wrapper could not start the pipeline command | wrapper stderr, process environment, `platform_health/v1` |
| `run_failed` | pipeline launched but exited non-zero | `out_base`, `audit_chain.json`, stage-local audit files |
| `completed` | pipeline exited zero | `public_report.json`, `audit_chain.json`, derived views |

### Current Receipt/Status Layout

The wrapper currently materializes lifecycle state under:

1. `<out_base>/query_workflow/submission_manifest.json`
2. `<out_base>/query_workflow/execution_receipts.jsonl`
3. `<out_base>/query_workflow/status.json`

That layout is a sidecar convenience for operators. It does not replace:

1. `audit_chain.json`
2. `public_report.json`
3. `mainline_contract_check.json`

Current read path:

1. `GET /v1/query-workflows/status?out_base=<abs-path>[&job_id=<job-id>]`
2. `python3 scripts/platform_api_client.py query-status --out-base <abs-path> --job-id <job-id>`

## Audit/Public-Report Query Adapter

Serve a completed run directory through a read-only HTTP adapter:

```bash
export SECCOMP_AUDIT_QUERY_API_TOKEN=local-audit-token
python3 scripts/serve_audit_query_api.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --bind-host 127.0.0.1 \
  --port 18092 \
  --auth-token-env SECCOMP_AUDIT_QUERY_API_TOKEN
```

Health:

```bash
curl http://127.0.0.1:18092/healthz
```

Public report:

```bash
curl -H "Authorization: Bearer $SECCOMP_AUDIT_QUERY_API_TOKEN" \
  http://127.0.0.1:18092/v1/public-report
```

Observability:

```bash
curl -H "Authorization: Bearer $SECCOMP_AUDIT_QUERY_API_TOKEN" \
  http://127.0.0.1:18092/v1/observability
```

Catalog/lineage:

```bash
curl -H "Authorization: Bearer $SECCOMP_AUDIT_QUERY_API_TOKEN" \
  http://127.0.0.1:18092/v1/catalog-lineage
```

This adapter is read-only. It serves the existing `a_psi_run/public_report.json` and `audit_chain.json` directly, and derives `pipeline_observability/v1` plus `catalog_lineage/v1` on demand from the same audit chain. The observability export now prefers the embedded `mainline_contract_check/v1` payload and emits two derived `handoff_cleanup` events plus two derived `service_audit_consistency` events, so read-side consumers can see both whether managed plaintext handoff artifacts were removed and whether each role's recovery-service boundary was `ok`, `fail`, or `not_applicable` without opening sidecar files separately. The catalog export now also carries the compact `mainline_contract_summary`, including the per-role `service_audit_consistency` verdicts, so lineage consumers can read the same owner-scope recovery-service summary without reparsing the full finding list. It does not touch SSE, bridge, record recovery, or PJC directly.

## Audit Bundle Verification

Build and seal an audit chain from a completed run:

```bash
python3 scripts/build_audit_chain.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --job-id auto_demo_job
python3 scripts/seal_audit_artifact.py \
  --input tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --out tmp/sse_bridge_pipeline_demo/audit_chain.seal.json \
  --job-id auto_demo_job
```

Archive the sealed bundle:

```bash
export SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY=local-audit-anchor
python3 scripts/archive_audit_bundle.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --audit-seal tmp/sse_bridge_pipeline_demo/audit_chain.seal.json \
  --archive-dir tmp/audit_archive \
  --job-id auto_demo_job \
  --tenant-id demo_tenant \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY
```

Verify a direct bundle:

```bash
python3 scripts/verify_audit_bundle.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --audit-seal tmp/sse_bridge_pipeline_demo/audit_chain.seal.json \
  --job-id auto_demo_job
```

Verify and restore from the archive index:

```bash
python3 scripts/verify_audit_bundle.py \
  --archive-index tmp/audit_archive/demo_tenant/audit_chain_index.jsonl \
  --job-id auto_demo_job \
  --restore-dir tmp/restored_audit_bundle \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY
```

`archive_audit_bundle.py` now appends an `audit_archive_anchor/v1` record to `audit_chain_anchor.jsonl` for each archived bundle. When `--tenant-id` is set, the tool first verifies that the requested tenant matches tenant scope values inside `audit_chain.json`, then writes the local index and anchor log under `tmp/audit_archive/<tenant-id>/`. The anchor log is locally append-only: every entry carries the previous entry hash plus the current index-record hash, and `--anchor-key-env` adds an HMAC over the anchor entry without logging the secret value.

If the seal was created with `--hmac-key-env`, pass the same env var to `verify_audit_bundle.py` to verify the seal HMAC signature. If the archive anchor was created with `--anchor-key-env`, pass the same env var to verify the anchor signature as well. Without those env vars, the tool still verifies artifact SHA-256 values and the anchor-chain linkage, but reports `signature_verified` or `anchor_signature_verified` as `null`. Archive index records and verification reports now also expose a compact `mainline_contract_summary`, including whether `mainline_contract_check/v1` was embedded in `audit_chain.json`, the final `server` / `client` handoff cleanup states, and the per-role `service_audit_consistency` summary for recovery-service runs.

## External Audit Anchor Publishing

After archiving a bundle, push the local anchor log to an external sink using `scripts/publish_external_audit_anchor.py`. The script verifies the anchor chain (payload hashes, entry hashes, chain linkage, and optional HMAC signature) before writing anything to the external sink.

Dry-run (verify only, no write):

```bash
export SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY=local-audit-anchor
python3 scripts/publish_external_audit_anchor.py \
  --anchor-file tmp/audit_archive/demo_tenant/audit_chain_anchor.jsonl \
  --external-ledger tmp/external_audit_ledger.jsonl \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY \
  --require-signature \
  --dry-run
```

Publish (append to external ledger):

```bash
python3 scripts/publish_external_audit_anchor.py \
  --anchor-file tmp/audit_archive/demo_tenant/audit_chain_anchor.jsonl \
  --external-ledger tmp/external_audit_ledger.jsonl \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY \
  --require-signature \
  --output tmp/external_audit_anchor_report.json \
  --assert-ok
```

Validate the report:

```bash
python3 scripts/validate_json_contract.py \
  --schema schemas/external_audit_anchor_report.schema.json \
  --json tmp/external_audit_anchor_report.json
```

The output schema is `external_audit_anchor_report/v1`. Key fields:

| Field | Meaning |
| ----- | ------- |
| `summary.status` | `ok` if at least one anchor record was verified and the chain is intact |
| `summary.anchor_record_count` | Total records verified from the anchor file |
| `summary.published_count` | Records actually appended to the external ledger (`0` in dry-run mode) |
| `summary.verified_chain` | `true` if the hash chain is unbroken |
| `summary.signed_count` | Records carrying a verified HMAC-SHA256 signature |
| `summary.last_entry_sha256` | Hash of the last anchor entry, for continuity verification |

The external ledger writes `external_audit_anchor_ledger/v1` records. Each record carries `job_id`, `chain_position`, `entry_sha256`, `payload_sha256`, `index_record_sha256`, and `signature_algorithm` — no secret material. The script is append-only; it does not modify or delete existing ledger records.

Use `--require-signature` in production to reject any unsigned anchor entries before they reach the external sink. Without it, unsigned entries pass through with `signature_verified: null`.

## Repository Hygiene Scan

Run the lightweight secret/build-artifact scan:

```bash
python3 scripts/scan_repo_hygiene.py
```

The scan fails on high-confidence secret material such as private-key blocks, cloud access keys, and common provider tokens. It reports tracked generated artifacts as warnings by default. Use `--fail-on-warn` if a CI job should also fail on warnings, or `--allow-findings` when collecting diagnostics only.

Run the dependency manifest hygiene check:

```bash
python3 scripts/check_dependency_hygiene.py
```

This check is intentionally offline. It verifies first-party Python requirement files and Cargo manifests for basic reproducibility hygiene, while skipping vendored/generated external dependency snapshots.

## Malformed-Input Gate

Run the negative-test (fuzz) gate to verify that the repo's JSON schema validators actively reject all known classes of malformed input:

```bash
python3 scripts/check_malformed_input_gate.py --out /tmp/malformed_gate.json
```

This gate systematically mutates minimal-valid reference payloads for eight core schemas and asserts every mutation is rejected:

| Mutation type | What it tests |
| --- | --- |
| `missing_required` | Validator catches missing required field |
| `const_violation` | `const`-typed fields (e.g. `schema`, `event`) reject wrong values |
| `enum_violation` | Enum-constrained fields reject out-of-enum values |
| `wrong_type_*` | Type-mismatched values are rejected (string→int, int→string, etc.) |
| `extra_property` | `additionalProperties: false` schemas reject unknown keys |
| `min_length_violation` | `minLength` fields reject the empty string |
| `minimum_violation` | `minimum` numeric constraints reject below-floor values |
| `invalid_json` | Truncated/malformed JSON is rejected |
| `null_root` / `array_root` / `string_root` / `number_root` | Non-object roots are rejected |

The gate exits non-zero if any mutation is **not** rejected. The output is a `malformed_input_gate/v1` JSON report validated against `schemas/malformed_input_gate.schema.json`. Both `check_ci_smoke.sh` and `check_json_contracts.sh` run this gate automatically.

## Pre-Release Gate

Run the consolidated pre-release gate to verify all fast contract-check and benchmark sub-checks pass before shipping:

```bash
python3 scripts/check_pre_release_gate.py --out /tmp/pre_release_gate.json --verbose
```

This runs 11 sub-checks and produces a `pre_release_gate/v1` machine-readable report:

| Gate | What it checks |
| --- | --- |
| `repo_hygiene` | `scan_repo_hygiene.py` — secrets and tracked generated artifacts |
| `dependency_hygiene` | `check_dependency_hygiene.py` — Python/Cargo manifest reproducibility |
| `schema_backcompat` | `check_schema_backcompat.py` — frozen schema fields haven't disappeared |
| `malformed_input` | `check_malformed_input_gate.py` — 191 malformed-input mutations all rejected |
| `record_recovery_boundary` | `check_record_recovery_boundary.py` — boundary contract check |
| `query_workflow_benchmark` | `benchmark_query_workflow.py` — dry-run workflow timing contract |
| `read_adapter_benchmark` | `benchmark_read_adapters.py` — read adapter timing contract |
| `record_recovery_benchmark` | `benchmark_record_recovery.py` — recovery service timing contract |
| `audit_bundle_benchmark` | `benchmark_audit_bundle.py` — archive/verify timing contract |
| `platform_health_benchmark` | `benchmark_platform_health.py` — health check timing contract |
| `derived_views_benchmark` | `benchmark_derived_views.py` — observability/catalog timing contract |

Each gate is timed (`duration_ms`), its output validated against its registered schema (`output_schema_valid: true`), and the consolidated report is itself validated against `schemas/pre_release_gate.schema.json`. Both `check_ci_smoke.sh` and `check_json_contracts.sh` run the full gate automatically.

Attach the output JSON to release artifacts to document gate state at the time of release.

## Schema Backward-Compatibility Check

Run the frozen-schema compatibility check:

```bash
python3 scripts/check_schema_backcompat.py
```

This compares the committed schema files against `config/schema_backcompat_baseline.json` and emits a `schema_backcompat_check/v1` report. The check is intentionally conservative:

1. schema `$id` must not change
2. stable top-level properties must not disappear
3. existing required fields must not disappear
4. new required fields are treated as breaking until the baseline is deliberately updated

## Smoke Benchmark

Measure existing smoke-check entrypoints without introducing a new runtime path:

```bash
python3 scripts/benchmark_smoke.py --target hygiene --iterations 5
```

Supported targets:

1. `hygiene`: runs `scripts/scan_repo_hygiene.py`.
2. `schema-backcompat`: runs `scripts/check_schema_backcompat.py`.
3. `dependency-hygiene`: runs `scripts/check_dependency_hygiene.py`.
4. `contracts`: runs `scripts/check_json_contracts.sh`.
5. `ci-smoke`: runs `scripts/check_ci_smoke.sh`.

Write a reusable report:

```bash
python3 scripts/benchmark_smoke.py \
  --target contracts \
  --iterations 3 \
  --output tmp/contract_smoke_benchmark.json
```

Benchmark the query-workflow dry-run entrypoints directly:

```bash
python3 scripts/benchmark_query_workflow.py \
  --request-file docs/examples/query_request.json \
  --iterations 3 \
  --mode all \
  --output tmp/query_workflow_benchmark.json
```

This emits `query_workflow_benchmark/v1` and currently compares:

1. `scripts/submit_query_workflow.py --dry-run`
2. `scripts/serve_query_workflow_api.py` + `POST /v1/query-workflows/dry-run`
3. `scripts/platform_api_client.py query-submit`

Default contract smoke now also asserts that the `--mode all` report still covers all three dry-run entrypoints and that each one succeeds.

Benchmark the completed-run metadata and audit read adapters:

```bash
python3 scripts/benchmark_read_adapters.py \
  --iterations 3 \
  --mode all \
  --output tmp/read_adapter_benchmark.json
```

This emits `read_adapter_benchmark/v1` and currently compares:

1. `scripts/query_metadata.py --job-id ...`
2. `scripts/query_metadata.py --caller ... --stage bridge ...`
3. `scripts/serve_metadata_api.py` + `GET /v1/jobs/<job_id>`
4. `scripts/serve_metadata_api.py` + `GET /v1/jobs?...`
5. `scripts/platform_api_client.py metadata-job`
6. `scripts/platform_api_client.py metadata-jobs`
7. `scripts/serve_metadata_api.py` + `GET /v1/entities/caller-permissions?...`
8. `scripts/platform_api_client.py metadata-entity`
9. `scripts/serve_audit_query_api.py` + `GET /v1/audit-chain`
10. `scripts/serve_audit_query_api.py` + `GET /v1/public-report`
11. `scripts/serve_audit_query_api.py` + `GET /v1/observability`
12. `scripts/serve_audit_query_api.py` + `GET /v1/catalog-lineage`
13. `scripts/platform_api_client.py audit-chain`
14. `scripts/platform_api_client.py audit-public-report`
15. `scripts/platform_api_client.py audit-observability`
16. `scripts/platform_api_client.py audit-catalog-lineage`

The benchmark materializes a temporary completed-run bundle plus sidecar metadata DB, then tears them down after the run. It does not require a pre-existing pipeline output directory, and the default contract smoke asserts that the `--mode all` report still contains the full 16-mode surface. The metadata job and jobs-list modes now also pin the embedded `mainline_contract_summary`, and jobs-list modes also pin `mainline_contract_summary_counts`, so the benchmark fails if metadata readers stop carrying handoff cleanup or per-role `service_audit_consistency` verdicts through that read surface.

Benchmark the standalone record-recovery boundary over Unix-socket and HTTP transports:

```bash
python3 scripts/benchmark_record_recovery.py \
  --iterations 3 \
  --mode all \
  --output tmp/record_recovery_benchmark.json
```

This emits `record_recovery_benchmark/v1` and currently compares:

1. `scripts/request_record_recovery_service.py --config ...` health checks
2. `services.record_recovery.client.request_record_recovery_health`
3. `services.record_recovery.client.request_record_recovery`

The benchmark generates a temporary encrypted record store, starts a temporary standalone recovery service through `scripts/manage_record_recovery_service.py`, measures health and recover operations, and then tears the service back down.

Default contract smoke now also asserts the full Unix-socket/HTTP mode set and that the synthetic recover calls still return `output_rows=2`.

Benchmark the integrated file-mode pipeline entrypoint:

```bash
python3 scripts/benchmark_pipeline.py \
  --iterations 1 \
  --mode all \
  --output tmp/pipeline_benchmark.json
```

This emits `pipeline_benchmark/v1` and currently compares:

1. `scripts/run_sse_bridge_pipeline.sh` with normal file handoff
2. `scripts/run_sse_bridge_pipeline.sh --keep-sse-export-handoff-files --handoff-retention-reason ops_retained_handoff_debug`
3. `scripts/run_sse_bridge_pipeline.sh --sse-export-handoff-mode fifo`

The benchmark runs the real pipeline against the example bridge inputs and validates that the output still produces `intersection_size=2` and `intersection_sum=425`. It also verifies that managed `server` / `client` handoff artifacts end in the expected owner-visible state for the selected mode: `cleaned` for default file handoff, `retained` for the explicit compatibility mode, and `removed` for FIFO. In the retained mode it also expects `mainline_contract_check.json` to carry the explicit `retention_reason`. The result rows now also emit `mainline_contract_check_embedded` plus per-role `handoff_cleanup_*` status and `exists_after_run` fields, so retained-vs-cleaned-vs-removed outcomes remain visible after the run instead of only being enforced internally by the benchmark script. It is intentionally not part of default contract smoke because it is slower and more environment-sensitive than the sidecar-only benchmarks.

Benchmark the standalone PJC runner over a prepared bridge fixture:

```bash
python3 scripts/benchmark_pjc.py \
  --iterations 1 \
  --mode all \
  --output tmp/pjc_benchmark.json
```

This emits `pjc_benchmark/v1` and currently measures:

1. `a-psi/moduleA_psi/scripts/run_pjc.sh`
2. checked-in `bridge/out/sse_demo_job/server.csv`
3. checked-in `bridge/out/sse_demo_job/client.csv`

The benchmark starts the local PJC server on a random loopback port, runs the client, and validates that the resulting `attribution_result.json` still produces `intersection_size=2` and `intersection_sum=425`.

For scale-oriented PJC measurements, use the generated CSV mode:

```bash
python3 scripts/benchmark_pjc.py \
  --mode generated_scale_csv \
  --server-items 100000 \
  --client-items 50000 \
  --overlap 0.2 \
  --iterations 3 \
  --output tmp/pjc_benchmark_100k.json
```

This emits the same `pjc_benchmark/v1` contract with a `scale` row. The 100k/50k/0.2 example derives `intersection_size=10000` and `intersection_sum=51005000`; `peak_rss_kb` is populated when `/usr/bin/time -v` is present.

Benchmark the live SSE-backed demo wrapper over default cleanup, retained compatibility, and FIFO handoff modes:

```bash
python3 scripts/benchmark_live_sse_demo.py \
  --iterations 1 \
  --mode all \
  --output tmp/live_sse_benchmark.json
```

This emits `live_sse_benchmark/v1` and currently measures:

1. `scripts/run_live_sse_bridge_demo.sh`
2. `scripts/run_live_sse_bridge_demo.sh --keep-sse-export-handoff-files --handoff-retention-reason ops_live_retained_handoff_debug`
3. `scripts/run_live_sse_bridge_demo.sh --sse-export-handoff-mode fifo`

The benchmark starts or reuses the local SSE server, bootstraps a fresh demo service, runs the live pipeline, and validates that the final result still normalizes to `intersection_size=2` and `intersection_sum=425`. It also verifies that managed `server` / `client` handoff artifacts end in the expected owner-visible state for the selected mode: `cleaned` for default file handoff, `retained` for the explicit compatibility mode, and `removed` for FIFO. In the retained mode it also expects `mainline_contract_check.json` to carry the explicit `retention_reason`. The result rows now also emit `mainline_contract_check_embedded` plus per-role `handoff_cleanup_*` status and `exists_after_run` fields, so retained-vs-cleaned-vs-removed outcomes stay visible in the benchmark report itself. It accepts the public-report amount whether it appears as display value, raw integer, or cents field, but it is intentionally not part of default contract smoke because it is the most environment-sensitive local benchmark path.

Benchmark the audit archive and verification entrypoints:

```bash
python3 scripts/benchmark_audit_bundle.py \
  --iterations 1 \
  --mode all \
  --output tmp/audit_bundle_benchmark.json
```

This emits `audit_bundle_benchmark/v1` and currently measures:

1. `scripts/archive_audit_bundle.py`
2. `scripts/verify_audit_bundle.py --audit-chain ... --audit-seal ...`
3. `scripts/verify_audit_bundle.py --archive-index ...`
4. `scripts/verify_audit_bundle.py --archive-index ... --restore-dir ...`

The benchmark materializes a temporary synthetic `audit_chain.json`, seals it through `scripts/seal_audit_artifact.py`, validates the fixture, and then measures archive, direct verify, archive-index verify, and archive-index restore operations. It now also asserts that archive index records and verification reports preserve the embedded owner-scope `mainline_contract_check/v1` summary, including the expected `server=removed` and `client=cleaned` handoff cleanup states, and that archive-backed modes report the expected `anchor_log_verified` / `anchor_signature_verified` results. Because it is self-contained and does not require bridge/PJC/SSE services, it is part of default contract smoke.

The same smoke run now also asserts the expected `archive_index_verified`, `restored`, and anchor-log-path flags for each benchmark mode.

Benchmark the read-only platform health sidecar:

```bash
python3 scripts/benchmark_platform_health.py \
  --iterations 1 \
  --mode all \
  --output tmp/platform_health_benchmark.json
```

This emits `platform_health_benchmark/v1` and currently measures:

1. `scripts/check_platform_health.py --out-base ...`
2. `scripts/check_platform_health.py --metadata-db ...`
3. `scripts/check_platform_health.py --out-base ... --metadata-db ...`
4. `scripts/serve_platform_health_api.py` + `GET /v1/platform-health?out_base=...`
5. `scripts/serve_platform_health_api.py` + `GET /v1/platform-health?metadata_db=...`
6. `scripts/serve_platform_health_api.py` + `GET /v1/platform-health?out_base=...&metadata_db=...`
7. `scripts/platform_api_client.py platform-health`

The benchmark reuses a synthetic completed-run bundle plus imported SQLite metadata DB, seals the synthetic `audit_chain.json` so the pipeline-run probe sees the full expected artifact set, starts the local platform-health HTTP adapter when API/client modes are selected, and validates that each resulting health report still conforms to `platform_health/v1`. Direct HTTP and client responses must also preserve the `platform_health_api_response/v1` envelope. Pipeline-run health now additionally requires the embedded `mainline_contract_check/v1` summary and valid managed handoff cleanup states. Because it is synthetic and read-only, it is part of default contract smoke.

The same smoke run now also asserts the expected component set per mode, while allowing the documented CLI-only fallback when loopback HTTP startup is unavailable in restricted environments.

Benchmark concurrent operator dashboard job starts:

```bash
python3 scripts/benchmark_dashboard_jobs.py \
  --concurrency 5 \
  --dashboard-reads 10 \
  --job-runtime-sec 0.5 \
  --output tmp/dashboard_jobs_benchmark.json
```

This emits `dashboard_jobs_benchmark/v1`. The benchmark starts the dashboard on loopback and replaces the heavy pipeline runner with an in-process fake runner after normal request validation and reservation, so it exercises the HTTP `POST /v1/jobs/start` path, positive per-tenant quota mode, `/v1/dashboard` reads, and `tracemalloc` retained-memory checks without launching multiple full privacy pipelines. It is an explicit local/operator benchmark because restricted environments may block loopback socket creation; default contract smoke validates a synthetic fixture instead.

Benchmark the derived observability and catalog exporters:

```bash
python3 scripts/benchmark_derived_views.py \
  --iterations 1 \
  --mode all \
  --output tmp/derived_views_benchmark.json
```

This emits `derived_views_benchmark/v1` and currently measures:

1. `scripts/export_observability_events.py`
2. `scripts/export_catalog_lineage.py`
3. `scripts/export_catalog_lineage.py --include-paths`

The benchmark reuses the synthetic completed-run fixture, points both exporters at the derived `audit_chain.json`, and validates that observability still carries full stage coverage while catalog export still keeps path redaction off by default unless `--include-paths` is explicitly requested. Observability coverage now explicitly includes both the derived `handoff_cleanup` stage and the derived `service_audit_consistency` stage from the embedded mainline contract payload. Because it is synthetic and read-only, it is part of default contract smoke.

The same smoke run now also asserts the three benchmark modes explicitly and keeps the default-vs-include-paths catalog redaction split pinned semantically.

## Observability Export

Export stage-level observability events from an existing audit chain:

```bash
python3 scripts/export_observability_events.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --out tmp/sse_bridge_pipeline_demo/pipeline_observability.json
```

The output schema is `pipeline_observability/v1`. It is derived from existing audit records and contains the stable telemetry fields called out in the task plan: `job_id`, `correlation_id`, `caller`, `tenant_id`, `dataset_id`, `service_id`, `stage`, `status`, `duration_ms`, `row_count`, and `artifact_sha256`. Current stage-owned audit writers now emit `duration_ms` for SSE export, recovery service, bridge, PJC, and policy release, so new runs surface stage timings directly; older runs can still show `duration_ms=null`. The exporter now also emits a derived `handoff_cleanup` stage for `server` and `client`, plus a derived `service_audit_consistency` stage for `server` and `client`, both sourced from the embedded `mainline_contract_check/v1` payload inside `audit_chain.json`.
Validate it with:

```bash
python3 scripts/validate_json_contract.py \
  --schema schemas/pipeline_observability.schema.json \
  --json tmp/sse_bridge_pipeline_demo/pipeline_observability.json
```

## Observability Dashboard

Build operator-facing panels from `pipeline_observability/v1`:

```bash
python3 scripts/build_observability_dashboard.py \
  --observability tmp/sse_bridge_pipeline_demo/pipeline_observability.json \
  --platform-health tmp/sse_bridge_pipeline_demo/platform_health.json \
  --out tmp/sse_bridge_pipeline_demo/observability_dashboard.json
```

Or point at a completed run directory and let the script infer both inputs:

```bash
python3 scripts/build_observability_dashboard.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/observability_dashboard.json
```

The output schema is `observability_dashboard/v1`. It contains five fixed panels:

| Panel | Content |
| ----- | ------- |
| `stage_timeline` | Chronological stage events: stage name, role, status, ts_utc, duration_ms, row_count, decision |
| `stage_summary` | Per-stage `ok / error / unknown / total` event counts |
| `stage_duration` | Per-stage min / mean / p50 / p95 / max `duration_ms` (only stages with at least one non-null timing) |
| `release_outcomes` | Per-`tenant_id` policy-release ok/error/unknown counts and last outcome |
| `failure_summary` | All `status=error` events, sorted `ts_utc` descending, showing `caller`, `stage`, `reason_code` |

The optional `health_summary` block is populated when `platform_health/v1` is provided; otherwise it is `null`.

Validate with:

```bash
python3 scripts/validate_json_contract.py \
  --schema schemas/observability_dashboard.schema.json \
  --json tmp/sse_bridge_pipeline_demo/observability_dashboard.json
```

The dashboard is sidecar-only. It derives from `pipeline_observability/v1` and does not change the frozen audit contracts or the main pipeline.

## Alert Check

Evaluate the four standard operator alert conditions against an existing dashboard:

```bash
python3 scripts/check_observability_alerts.py \
  --dashboard tmp/sse_bridge_pipeline_demo/observability_dashboard.json \
  --platform-health tmp/sse_bridge_pipeline_demo/platform_health.json \
  --out tmp/sse_bridge_pipeline_demo/observability_alert_report.json
```

Or via `--out-base` to infer both inputs:

```bash
python3 scripts/check_observability_alerts.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/observability_alert_report.json
```

The output schema is `observability_alert_report/v1`. Each alert entry has `alert_id`, `severity`, `firing`, `message`, and `triage_path`.

| Alert ID | Fires When |
| -------- | ---------- |
| `repeated_stage_error` | Same stage has ≥2 `status=error` events |
| `release_failure_after_success` | Policy release failed but bridge and PJC succeeded |
| `platform_health_degraded` | `health_summary.status` is `warn` or `error` |
| `stage_coverage_gap` | Any of the 5 core pipeline stages is absent from the dashboard |

Send firing alerts to a Slack or Alertmanager webhook (I2-a):

```bash
# Slack incoming-webhook
python3 scripts/check_observability_alerts.py \
  --dashboard tmp/sse_bridge_pipeline_demo/observability_dashboard.json \
  --webhook-url "$SECCOMP_SLACK_WEBHOOK" \
  --webhook-format slack \
  --out tmp/sse_bridge_pipeline_demo/observability_alert_report.json

# Alertmanager
python3 scripts/check_observability_alerts.py \
  --dashboard tmp/sse_bridge_pipeline_demo/observability_dashboard.json \
  --webhook-url "$SECCOMP_ALERTMANAGER_URL/api/v1/alerts" \
  --webhook-format alertmanager \
  --webhook-bearer-env SECCOMP_ALERTMANAGER_TOKEN \
  --out tmp/sse_bridge_pipeline_demo/observability_alert_report.json
```

The result is recorded in `observability_alert_report/v1` under an optional `webhook_dispatch` block (`endpoint_url`, `format`, `ok`, `status_code`, `transport_error`, `payload_byte_count`, `firing_count`, `skipped_reason`). When zero alerts are firing, the script records `skipped_reason=no_firing_alerts` and does not POST; pass `--webhook-include-resolved` to override. Loopback URLs (`localhost` / `127.*` / `::1`) automatically bypass the system HTTP proxy.

Run the alert check on a polling interval (I2-b):

```bash
python3 scripts/run_alert_check_daemon.py \
  --dashboard tmp/sse_bridge_pipeline_demo/observability_dashboard.json \
  --interval-sec 60 \
  --heartbeat-log tmp/alert_daemon_heartbeat.jsonl \
  --webhook-url "$SECCOMP_SLACK_WEBHOOK" \
  --webhook-format slack
```

Each iteration appends one `alert_daemon_heartbeat/v1` record to the heartbeat log. The daemon tracks the last-known firing state per `alert_id` and posts only on transitions (`unknown→firing`, `firing→resolved`, `resolved→firing`). Pass `--max-iterations N` for a cron-driven one-shot, `--webhook-include-resolved` to emit explicit resolved-state notifications, or `--exit-on-firing` to make CI runs fail when any alert fires. SIGINT/SIGTERM cleanly terminates the loop. Heartbeat JSONL can be tailed for incident-review with `tail -f tmp/alert_daemon_heartbeat.jsonl | jq '.transitions[]'`.

## Query Workflow Status List

Scan a directory tree for `query_workflow/status.json` files:

```bash
python3 scripts/list_query_workflow_status.py \
  --search-dir tmp \
  --limit 20 \
  --out tmp/workflow_status_list.json
```

Filter by state:

```bash
python3 scripts/list_query_workflow_status.py \
  --search-dir tmp \
  --state failed \
  --limit 20 \
  --out tmp/workflow_status_list_failed.json
```

The output schema is `query_workflow_status_list/v1`. Each entry includes `out_base`, `job_id`, `state`, `terminal`, `last_exit_code`, and `last_updated_at_utc`. Results are sorted by `last_updated_at_utc` descending.

## Retry Eligibility Check

Determine whether a failed job can be retried or must be re-submitted:

```bash
python3 scripts/check_workflow_retry_eligibility.py \
  --status-file tmp/my_job/query_workflow/status.json \
  --out tmp/my_job/retry_eligibility.json
```

The output schema is `workflow_retry_eligibility/v1`. It carries:

| Field | Values |
| ----- | ------ |
| `recommended_action` | `none` (completed), `wait` (running), `retry` (launch_failed), `resubmit` (run_failed / validation / authz), `investigate` |
| `retryable` | `true` only for `launch_failed` transient errors |
| `resubmit_required` | `true` for all failures that need a new job_id or a corrected request |
| `triage_steps` | Ordered list of steps to diagnose and resolve the issue |

## Operator Triage Report

Run the full triage chain — dashboard + alerts + health + workflow status — in one call:

```bash
python3 scripts/run_operator_triage.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/operator_triage.json
```

Or with explicit paths when sidecar files are not in a standard layout:

```bash
python3 scripts/run_operator_triage.py \
  --observability tmp/sse_bridge_pipeline_demo/pipeline_observability.json \
  --platform-health tmp/sse_bridge_pipeline_demo/platform_health.json \
  --dashboard tmp/sse_bridge_pipeline_demo/observability_dashboard.json \
  --out tmp/sse_bridge_pipeline_demo/operator_triage.json
```

The output schema is `operator_triage_report/v1`. It has four sections:

| Section | Source | Available When |
| ------- | ------ | -------------- |
| `dashboard` | `pipeline_observability.json` | `pipeline_observability.json` exists |
| `alerts` | `observability_dashboard.json` | Dashboard can be built or was provided |
| `platform_health` | `platform_health.json` | `platform_health.json` exists |
| `workflow_status` | `query_workflow/status.json` | A query workflow was submitted under `out_base` |

Each section sets `available: true` or `available: false` so the report is always structurally valid even when some sidecar files are absent.

## Catalog And Lineage Export

Export catalog and lineage metadata from the same audit chain:

```bash
python3 scripts/export_catalog_lineage.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --out tmp/sse_bridge_pipeline_demo/catalog_lineage.json
```

The output schema is `catalog_lineage/v1`. By default it records job, dataset, service, artifact-hash, row-count, and stage-edge metadata without full artifact paths and without sensitive plaintext. Use `--include-paths` only when the operator explicitly needs path-level lineage in a controlled environment.
Validate it with:

```bash
python3 scripts/validate_json_contract.py \
  --schema schemas/catalog_lineage.schema.json \
  --json tmp/sse_bridge_pipeline_demo/catalog_lineage.json
```

## Operator Readiness Check

Before any deployment, run the operator readiness gate to verify configuration, example data, and the full pre-release gate:

```bash
python3 scripts/check_operator_readiness.py --out /tmp/operator_readiness.json --verbose
```

This produces an `operator_readiness/v1` JSON report covering:

| Check | What it validates |
| --- | --- |
| `config_example_files` | All 9 example config files in `config/` and `sse/config/` validate against their schemas |
| `bridge_example_data` | Bridge example CSVs and JSONL input files are present |
| `pre_release_gate` | Full 11-gate pre-release gate passes |

The report also catalogs all 8 platform `SECCOMP_*` env vars and shows which are set in the current shell. Use this to identify any missing secrets before deployment. The check exits non-zero if any check fails. Attach the output JSON as a deployment artifact.

## Pre-Deployment Checklist

Run through this checklist before deploying a new version or configuration:

**Step 1 — Validate the codebase**

```bash
bash scripts/check_ci_smoke.sh
```

Expected: `[ok] CI smoke checks passed`

**Step 2 — Run the operator readiness gate**

```bash
python3 scripts/check_operator_readiness.py --out /tmp/operator_readiness_$(date +%Y%m%d).json --verbose
```

Expected: `3 checks, 3 passed, 0 failed → ok`

Check the `env_var_catalog` in the report — any `"set": false` entry that is required for your deployment scenario must be exported before proceeding.

**Step 3 — Verify replay contracts**

```bash
bash scripts/verify_pipeline_replay.sh
bash scripts/verify_fifo_handoff_replay.sh
```

Expected: both replays pass with `intersection_size=2` and `intersection_sum=425`.

**Step 4 — Archive the audit bundle from the verification run**

After any pipeline run produces `audit_chain.json` + `audit_chain.seal.json`:

```bash
SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY="<anchor-key>" \
python3 scripts/archive_audit_bundle.py \
  --audit-chain <out-base>/audit_chain.json \
  --audit-seal  <out-base>/audit_chain.seal.json \
  --archive-dir <archive-dir> \
  --job-id      <job-id> \
  --tenant-id   <tenant-id> \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY
```

**Step 5 — Verify the archived bundle**

```bash
python3 scripts/verify_audit_bundle.py \
  --archive-index <archive-dir>/<tenant-id>/audit_chain_index.jsonl \
  --job-id <job-id> \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY
```

Expected: `signature_verified: true`, `anchor_log_verified: true`.

**Step 6 — Confirm platform health after deploy**

```bash
python3 scripts/check_platform_health.py --output /tmp/post_deploy_health.json
```

Inspect `summary.status` — `"ok"` or `"warn"` is acceptable; `"error"` requires investigation before declaring the deployment complete.

## Failure Recovery Decision Tree

Use this tree when a check or service reports an unexpected failure.

### CI Smoke Fails

1. **`py_compile` error** → fix the syntax error in the named script; rerun.
2. **Schema validation error** → check the output file against the schema diff; if the schema changed, update `config/schema_backcompat_baseline.json` and re-validate.
3. **`scan_repo_hygiene.py --fail-on-warn`** → open findings, remove or `.gitignore` tracked generated artifacts.
4. **`check_schema_backcompat.py` failed** → a stable property was removed or a required field disappeared from a frozen schema; restore it or file a change request.
5. **`verify_pipeline_replay.sh` failed** → check `intersection_size` and `intersection_sum`; if wrong, the bridge binary or normalizer changed; compare against last known-good fixture.
6. **`verify_fifo_handoff_replay.sh` failed** → check `handoff_mode=fifo` and `exposure_risk=none`; if FIFO artifacts still exist after the run, the cleanup path broke.

### Audit Bundle Integrity Failure

1. **`artifact_sha256_verified: false`** → the audit chain was modified after sealing.
   - If source files are intact: `python3 scripts/seal_audit_artifact.py --input <chain> --out <seal> --job-id <id>` and re-archive.
   - If chain is corrupted: restore from `<archive-dir>/audit_chains/` using `verify_audit_bundle.py --restore-dir <dir>`.
2. **`signature_verified: false`** → the HMAC seal key does not match; confirm the `--hmac-key-env` value is identical to what was used at seal time.
3. **`anchor_log_verified: false`** → the anchor chain was tampered; review `audit_chain_anchor.jsonl` for gaps and compare with archived copies.
4. **Spot-check tamper resistance for a specific run** → `python3 scripts/verify_audit_tamper_resistance.py --audit-chain <chain> --audit-seal <seal> --job-id <id> --hmac-key-env <env> --output tmp/audit_tamper_resistance.json`. The report should show `status=ok`, `summary.detected==summary.total>=4`, and `post_restore_check.{audit_chain_sha256_matches_baseline,audit_seal_sha256_matches_baseline,verifier_passes_after_restore}=true`. The script restores the original bytes after every mutation; a non-zero exit means either tamper was missed (verifier issue) or the bundle was not restored (filesystem issue).
5. **HTTP malformed-input gate spot-check** → `python3 scripts/check_http_malformed_input_gate.py --output tmp/http_malformed_input_gate.json`. Default mode spawns the record-recovery HTTP service in-process on loopback and runs 11 malformed-request scenarios, including post-signature payload tampering; report should show `summary.status=ok` and `summary.detected==summary.total>=8`. Operators can target an existing service with `--endpoint https://...` and pass `--auth-token` if the service requires bearer auth.
6. **mTLS connection-overhead spot-check** → `python3 scripts/benchmark_mtls_overhead.py --iterations 50 --output tmp/recovery_mtls_benchmark.json`. Spawns plaintext + mTLS record-recovery HTTP services on loopback and probes `/health` in both fresh- and persistent-connection modes. Report fields to watch: `summary.fresh_connection_mtls_overhead_p95_ms` (target < 50ms; auto-flagged), `summary.keep_alive_savings_mtls_p95_ms` (positive when keep-alive helps), and the four `(transport, connection_mode)` p50/p95 entries.
7. **Bring up observability stack** → `cd config/observability && docker compose -f docker-compose.observability.yml up -d`. Tempo serves OTLP gRPC on 4317 and OTLP HTTP on 4318; Prometheus is on 9090 (mounting the J3-b `alert-rules.yml`); Grafana is on 3000 with anonymous admin access enabled for the local demo. Datasources (`seccomp-tempo`, `seccomp-prometheus`) and dashboards (`seccomp-pipeline-overview`, `seccomp-recovery-service`) auto-provision. Push spans with `python3 scripts/export_otel_events.py --observability <pipeline_observability.json> --spans-out tmp/spans.jsonl --otlp-endpoint http://localhost:4318` (the JSONL output and the `otlp_push` block in `otel_export_report/v1` are kept side-by-side). Verify the stack with `python3 scripts/render_observability_topology.py --output tmp/observability_topology_report.json` (must report `summary.status=ok`).

### Record Recovery Service Failure

1. **Service does not start** → check `record_recovery_service_health.json` for `status` and `pid_file` errors; verify socket path and directory permissions.
2. **`request_signature_verified: false` or `request_payload_sha256_verified: false`** → the client HMAC key does not match the service's `hmac_key_env`, the payload changed after signing, or the client omitted `X-Request-Payload-SHA256`; re-export the correct key and recompute the signature from the exact request body.
3. **`reason_code: request_expired`** → the client's `request_timestamp_utc` is more than 30 s away from server time; sync clocks or widen the window in the service config.
4. **`authz: deny`** → the caller is not listed in the recovery policy; add the caller to `sse_export_policy/v1` or the SQLite authz source.
5. **TLS handshake failure (mTLS)** → verify that `tls.ca_cert` on the server matches the CA that signed the client cert; confirm `tls.client_cert` / `tls.client_key` paths are correct in the config; check that `tls.verify_hostname` is `false` when using loopback self-signed certs.
6. **`ssl.SSLCertVerificationError`** → the server certificate is not trusted by the client's CA; re-check `tls.ca_cert` on the client side; if `require_client_cert=true`, also verify the client cert is signed by the same CA.

### External Audit Anchor Failure

1. **`payload_sha256 mismatch`** → the anchor entry was modified after it was written; restore the anchor file from a backup or re-archive from the original `audit_chain.json`.
2. **`entry_sha256 mismatch`** → the chain linkage is broken; the anchor file was truncated or reordered; compare against the original archive index.
3. **`HMAC signature mismatch`** → the anchor key does not match what was used at archive time; confirm the env var named by `--anchor-key-env` holds the original secret.
4. **`unsigned anchor line`** (with `--require-signature`) → an anchor entry was written without an HMAC key; either remove the unsigned entry or re-archive with a key set.
5. **External ledger file not writable** → the `--external-ledger` path or its parent directory does not exist or is read-only; create the directory or fix permissions before publishing.

### J4 Chaos Drill

`scripts/run_chaos_test.py` drives the chaos and failure-injection drill defined in `docs/PRODUCTION_READINESS_GUIDEBOOK.md` §J4. It emits `chaos_test_report/v1`. Default contract smoke runs `--scenarios all --assert-ok`; the report should always carry `summary.status=ok`, `summary.audit_chain_corruptions=0`, three `ok` scenarios, and two `skipped` operator-only scenarios.

```bash
python3 scripts/run_chaos_test.py \
  --scenarios all \
  --output tmp/chaos_test_report.json \
  --assert-ok
```

Per-scenario triage:

1. **`recovery_service_sigkill` flips to `fail`** → either the in-process recovery service did not become healthy before injection (look at `details=service did not become healthy before injection`; the auth path probably regressed and `/metrics` is no longer unauthenticated), or the post-shutdown probe unexpectedly succeeded (the listener was not torn down — investigate `RecordRecoveryHttpServer.shutdown()`/`server_close()` ordering). Recovery: rerun the drill once; if the failure persists, file a regression and quarantine the affected `services/record_recovery/http_service.py` change.
2. **`mtls_cert_expired` flips to `fail`** → the operator host either lacks `cryptography` (`pip install cryptography`) or the client TLS context now silently accepts expired certs (a `ssl` library regression). The expected failure mode is `certificate_expired` / `certificate_verify_failed` / `ssl_error`; anything else means the script took a non-TLS error path and should be triaged before further smokes.
3. **`audit_archive_unwritable` flips to `fail`** → either `seal_audit_artifact.py` arguments changed (the synthesizer uses `--input/--out/--job-id`; if those names move you'll see `could not synthesize audit chain/seal`), or the `chmod 000` injection no longer blocks writes (the underlying filesystem may be a tmpfs run as root with permissive mounts). Recovery: rerun the drill on a non-root host.
4. **`postgres_primary_killed` is recorded as `skipped`** → expected. The live drill is operator-environment work and shares the same Patroni step-by-step with J2-b; once a Patroni cluster is available, run `patronictl -c config/patroni-ha/patroni-primary.yml switchover --force` and verify `scripts/check_platform_health.py` reports `ok` within 30 s.
5. **`audit_log_path_full` is recorded as `skipped`** → expected. The live drill requires a quota-bounded loopback filesystem (e.g. an `xfs_quota`-managed mount or a dedicated `tmpfs` with `size=`); see operator notes. Once a small loopback mount is available, point `record_recovery_service_config.audit_log` at it, fill the FS, and submit a single `/recover` to verify the service surfaces `audit_write_failed` without corrupting in-memory state.

After any chaos drill (passing or failing), re-run `bash scripts/check_ci_smoke.sh` to confirm the pipeline replay still produces `intersection_size=2 / intersection_sum=425`. The chaos drill never modifies pipeline contract files, but a misbehaving scenario could leak a temporary work dir; clean up `/tmp/seccomp_chaos_*` directories with `rm -rf /tmp/seccomp_chaos_*` if `--work-dir` was pinned.

### Platform Health Reports Error

```bash
python3 scripts/check_platform_health.py | python3 -c \
  "import sys,json; d=json.load(sys.stdin); [print(c['name'], c['status'], c.get('error','')) for c in d['checks'] if c['status']!='ok']"
```

Follow the component-specific guidance above for each failing check name.

### Deployment Topology (J1)

The canonical multi-node topology is documented in `config/topology.md`. It covers the load-balancer → recovery-service → pgBouncer → Patroni layout, lists every port in use, classifies each component as stateless or stateful, and spells out the mTLS vs bearer-token authentication boundaries.

The recovery-service Kubernetes manifests live under `config/k8s/recovery-service-*.yaml` (one `Deployment`, one `Service`, one `HorizontalPodAutoscaler` per tenant). To regenerate them with different scaling parameters or for a new tenant, use the renderer:

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

The renderer emits a structurally-validated `Deployment`, `Service`, and `HorizontalPodAutoscaler`, plus a `k8s_recovery_service_topology_report/v1` report. Pair the manifests with `scripts/render_k8s_network_policies.py` (H1-b) so each tenant's recovery-service pods only accept ingress from their own pipeline pods. Running with `--kubectl-dry-run` additionally feeds each manifest through `kubectl apply --dry-run=client` when `kubectl` is on `PATH`; default contract smoke runs structural validation only.

Triage:

1. **`spec.replicas mismatch`** → the `--replicas` flag conflicts with the existing manifest; regenerate with the same value or update `--replicas`.
2. **`container.readinessProbe is required` / `livenessProbe is required`** → a hand-edited manifest dropped the health probes; load balancers will not be able to drain/restart the pod cleanly. Restore the probes from the renderer output.
3. **`container.resources.{requests,limits} are required for HPA scheduling`** → the HPA cannot scale on CPU without resource requests + limits. Restore the `resources:` block.
4. **`hpa.scaleTargetRef.kind must be Deployment`** → the HPA was retargeted at a different workload; this is almost always a copy/paste mistake.
5. **`kubectl_dry_run.status=fail`** → run `kubectl apply --dry-run=client -f <manifest> -o yaml` directly to see the API-server validation error; common causes are namespace mismatch and missing `app=recovery-service` / `tenant=<tenant-id>` labels on Secrets the pod mounts.

### SLO Alerts (J3-b)

`config/prometheus/alert-rules.yml` carries the recovery-service SLO alert set targeting the J3-a `/metrics` endpoint:

| Alert | Severity | For | What it means |
| --- | --- | --- | --- |
| `RecoveryServiceErrorRateHigh` | warning | 2m | deny rate > 5% over 5min — authz drift, expired tokens, or upstream policy change |
| `RecoveryServiceLatencyHigh` | critical | 5m | p95 `recovery_request_duration_seconds` > 2s — SLO breach |
| `RecoveryServiceNoTraffic` | warning | 10m | 0 req/s for 10min — load balancer mis-routed or scrape target wrong |
| `RecoveryServiceRateLimitedSpike` | warning | 5m | sustained `decision="rate_limited"` rejections from H2-a token-bucket — re-tune `--rate-limit-per-caller` or investigate the caller |

Validate the rules file structurally with the repo-side validator:

```bash
python3 scripts/validate_prometheus_alert_rules.py \
  --rules config/prometheus/alert-rules.yml \
  --output tmp/prometheus_alert_rules_report.json \
  --assert-ok
```

The validator emits `prometheus_alert_rules_report/v1` and confirms (a) YAML is well-formed, (b) the four required alert names are present, (c) every alert has `labels.severity` and a `for:` window. For full Prometheus-side validation, operators run `promtool check rules config/prometheus/alert-rules.yml` against the same file; once I2-a (`scripts/check_observability_alerts.py --webhook-url`) is finished, the alerts route into the existing operator notification path.

### Recovery Service Failover Drill (J2-a)

`scripts/test_failover_recovery_service.py` runs a full recovery-service failover drill: it spawns two HTTP recovery-service instances on free loopback ports, issues a baseline recovery to the primary, SIGKILLs the primary, then issues a follow-up recovery that exercises the client retry path against the secondary. The script emits `recovery_service_failover_test/v1` and is suitable for both CI smoke and operator drills.

```bash
python3 scripts/test_failover_recovery_service.py \
  --candidate-count 1000 \
  --failover-target-seconds 5 \
  --output tmp/recovery_service_failover_test.json \
  --assert-ok
```

Acceptance bar (built into `--assert-ok`):

1. Both services start cleanly via `manage_record_recovery_service.py start`.
2. Primary serves the baseline request and writes one `record_recovery_service_request` audit entry with `decision=allow`.
3. Primary is SIGKILLed and its TCP port stops accepting connections within `--unreachable-deadline-sec`.
4. Secondary serves the failover request within `--failover-target-seconds` (target derived from the J2-a SLO of < 10s end-to-end including client retry).
5. Audit-log integrity holds: each side's audit log carries exactly its own job's recover record; neither service contaminates the other side's log.

Triage:

1. **`primary start failed: ... port already in use`** → another service has the loopback port; rerun with a fresh free port (the script auto-selects one, but a stuck previous run can leak a port). Check `lsof -i :<port>`.
2. **`baseline recovery failed: HTTP error 400 service_id ... does not match`** → a stale config snuck a different `service_id`; use the rendered config exactly as the script writes it.
3. **`primary endpoint still reachable after SIGKILL`** → the primary process did not terminate; check the audit `service.log` and `pid_file`. May indicate the process forked beyond what `pid_file` tracks.
4. **`failover request was served by the primary even after SIGKILL`** → the kill happened too early or the secondary URL was wrong; rerun and inspect the report's `primary.killed_at_utc`.
5. **`failover recovery request failed: <error>`** → both primary and secondary failed; check the secondary's `service.log` for the underlying cause (TLS, authz, allowed-roots).
6. **`audit_integrity.errors`** → the report flags exactly which side is missing the expected record. Cross-check against `<work-dir>/<role>/audit.jsonl` (use `--work-dir` to keep the temp dir for inspection).

Use `--work-dir <path>` to pin the work directory if you want to inspect the audit logs and per-service `service.log` post-run; without `--work-dir` the script cleans up its temp directory on exit.

### Metadata DB Backup / Restore (F4)

Use `scripts/backup_metadata_db.py` and `scripts/restore_metadata_db.py` for sidecar metadata backups and disaster-recovery drills. Both emit signed-off reports (`metadata_db_backup_report/v1`, `metadata_db_restore_report/v1`) for audit; `--assert-ok` makes them safe to chain in cron jobs and CI gates.

Daily backup (PostgreSQL):

```bash
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

Daily backup (SQLite sidecar — demo / non-HA path):

```bash
python3 scripts/backup_metadata_db.py \
  --db-path tmp/platform_metadata.db \
  --out-path tmp/platform_metadata.backup.db \
  --verify \
  --output tmp/metadata_db_backup_report.json \
  --assert-ok
```

Restore drill into a scratch database (PostgreSQL):

```bash
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

Triage:

1. **`pg_dump exited 1`** → check the source DSN credentials, network reachability, and the user's `pg_dump` privileges (`CONNECT` + `USAGE` on schemas + `SELECT` on all tables).
2. **`pg_restore --list returned 0 TOC entries`** → the dump file is empty or truncated; do not delete the previous backup until a successful re-run.
3. **`backup verification failed: PRAGMA integrity_check`** → the SQLite source DB is corrupt; restore from the last good backup before retrying.
4. **`SQLite restore requires a SQLite backup file; got pg_dump_custom`** (or vice versa) → backend mismatch between `--backup-path` and `--out-db-path` / `--restore-dsn`; pick the matching target.
5. **`portability_check.status=error: restored DB is missing migrations`** → the backup predates the current migration baseline; either re-run on a recent backup or apply pending migrations to the restored DB before swapping it in.
6. **`s3_upload.status=error` / `s3_download.status=error`** → check `boto3` credentials (`AWS_PROFILE` / `AWS_ACCESS_KEY_ID`), the S3 bucket policy, and Object Lock retention if applicable.
7. **`s3_upload.status=planned`** without an error → `--upload-s3` was supplied without `--execute`; the report is a dry-run plan, not a real upload. Add `--execute` once the destination is verified.

Both scripts redact passwords from any DSN they emit (`db_dsn_redacted`), so the JSON reports are safe to upload to a long-term audit archive.

## SLO Baseline

The table below documents the **expected performance floor** for each benchmark gate, derived from the pre-release gate's `--iterations 1` timing on the reference machine. Values are soft targets: exceeding them in CI does not automatically fail a gate, but a 5× regression warrants investigation.

| Gate | Typical duration | Notes |
| --- | ---: | --- |
| `repo_hygiene` | < 500 ms | Scales with tracked-file count |
| `dependency_hygiene` | < 500 ms | Reads manifests only |
| `schema_backcompat` | < 100 ms | In-memory comparison |
| `malformed_input` | < 10 s | 191 subprocess validator calls |
| `record_recovery_boundary` | < 100 ms | JSON read only |
| `query_workflow_benchmark` | < 5 s | Dry-run only, no bridge |
| `read_adapter_benchmark` | < 5 s | Synthetic DB fixture |
| `record_recovery_benchmark` | < 5 s | Synthetic record store |
| `audit_bundle_benchmark` | < 3 s | Synthetic HMAC bundle |
| `platform_health_benchmark` | < 5 s | Synthetic probe only |
| `derived_views_benchmark` | < 3 s | Synthetic audit_chain fixture |
| `operator_readiness (full)` | < 20 s | Runs pre_release_gate internally |

To capture a fresh baseline after environment changes:

```bash
python3 scripts/check_pre_release_gate.py --out /tmp/gate_baseline_$(date +%Y%m%d).json --verbose
```

Store the output alongside release artifacts so future comparisons have a concrete reference point.

## Troubleshooting

Common failures:

1. `environment variable ... is not set`: export the auth or secret env var referenced by the config before probing.
2. `connection refused` or `No such file or directory`: the target service is not running, or the config points at the wrong socket or endpoint.
3. `metadata DB does not exist`: initialize and import first with `scripts/init_metadata_db.py` and `scripts/import_run_metadata.py`.
4. Missing pipeline artifacts: rerun the integrated demo or check that `--out-base` points to the root run directory, not a nested artifact directory.
5. `audit seal artifact_sha256 does not match`: the audit chain changed after the seal was created; rebuild the seal or restore the archived copy.
6. `repo_hygiene_scan/v1` warns about tracked generated artifacts: add the generated path to `.gitignore` and remove it from the Git index with `git rm --cached`, preserving local files when needed.

## Baseline Verification

Use the unified CI smoke entrypoint for local preflight:

```bash
bash scripts/check_ci_smoke.sh
```

Use the bridge Rust check when touching `bridge/` or when validating the full preflight locally:

```bash
bash scripts/check_bridge_rust.sh
```

This runs `cargo fmt --check` and `cargo test` with a temporary `/tmp/bridge_cargo_test.*` target directory so local checks do not repopulate tracked repository paths.

Use the contract smoke suite after code or contract changes:

```bash
bash scripts/check_json_contracts.sh
```

Use shell syntax checks after orchestration edits:

```bash
bash -n scripts/run_sse_bridge_pipeline.sh
```
