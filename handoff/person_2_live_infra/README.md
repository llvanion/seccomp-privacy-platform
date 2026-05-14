# Person 2 - Live Boundary and Infrastructure Owner

## Scope

Owner: Person 2

Machines:

- PC-3: recovery-service / database / pgBouncer / primary target host.
- PC-4: replica / observability / auxiliary service host.

Goal:

- Provide the live or staging service boundaries that require more than one person to validate.
- Support Person 3 during K3 external/security testing.
- Record infrastructure evidence and blockers under `tmp/team_evidence/person_2/`.

Use [docs/team/TEAM_COLLABORATION_AND_REPORTING_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/team/TEAM_COLLABORATION_AND_REPORTING_PLAN.md) as the shared three-person plan for Ubuntu/environment requirements, evidence packaging, and pre/final report structure.

This pack excludes completed repo-side and local-only work unless needed as support evidence. Focus on live targets that Person 3 can test.

## Unfinished Multi-Person Tasks

| Task | People needed | Person 2 role |
| --- | --- | --- |
| K3 external pen test | Person 1 + Person 2 + Person 3 + external tester | target owner for live boundaries |
| Recovery service mTLS/bearer boundary test | Person 2 + Person 3 | start service, provide cert/auth details, collect logs |
| Live Patroni / pgBouncer drill if available | Person 1 + Person 2 | operate infra, record failover/pool evidence |
| Live observability render if available | Person 1 + Person 2 | start stack, confirm dashboards/traces |
| Live Vault/OIDC/OpenFGA boundary if available | Person 2 + Person 3 | provide endpoint and test credentials |

## Setup

Run from repo root:

```bash
mkdir -p tmp/team_evidence/person_2
cp handoff/person_2_live_infra/EVIDENCE_LOG.md tmp/team_evidence/person_2/EVIDENCE_LOG.md
```

## Recovery Service Target

Start a recovery-service target for Person 3. Use the real staging config when available:

```bash
python3 scripts/run_record_recovery_service.py serve \
  --config config/record_recovery_http_service.example.json
```

If using a different endpoint, record:

- bind host and port
- transport: HTTP, HTTPS, or mTLS
- auth method: none, bearer, identity token, mTLS
- config path
- log path

Basic health check:

```bash
python3 scripts/request_record_recovery_service.py \
  --config config/record_recovery_http_service.example.json \
  --health \
  --output tmp/team_evidence/person_2/recovery_service_health.json
```

## PostgreSQL / pgBouncer / Patroni Live Drill

Run this only if the live infrastructure exists. Otherwise record `skipped` with reason.

Minimum evidence:

```bash
pg_isready -h <db-host> -p <port>
psql "<dsn>" -c "select version();"
```

For pgBouncer:

```bash
psql "<pgbouncer-admin-dsn>" -c "SHOW POOLS;"
psql "<pgbouncer-admin-dsn>" -c "SHOW STATS;"
```

For Patroni:

```bash
patronictl -c <patroni-config.yml> list
patronictl -c <patroni-config.yml> switchover --force
patronictl -c <patroni-config.yml> list
```

Application retry-path evidence:

```bash
python3 scripts/test_metadata_db_failover.py \
  --db-dsn "<live-or-pooled-dsn>" \
  --output tmp/team_evidence/person_2/metadata_db_failover_live.json \
  --failover-target-seconds 30
```

## Observability Live Drill

Run this only if Docker or the staging observability stack is available:

```bash
cd config/observability
docker compose -f docker-compose.observability.yml up -d
cd ../..

python3 scripts/export_otel_events.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --spans-out tmp/team_evidence/person_2/spans.jsonl \
  --otlp-endpoint http://127.0.0.1:4318 \
  --output tmp/team_evidence/person_2/otel_export_report.json
```

Record whether Grafana dashboards render:

- `seccomp-pipeline-overview`
- `seccomp-recovery-service`

## Support During Person 3 Testing

During the test window:

1. Keep recovery-service logs available.
2. Keep database and proxy logs available if those targets are in scope.
3. Do not rotate test credentials during active testing unless Person 1 approves.
4. Record every restart, config change, and incident in `EVIDENCE_LOG.md`.

## Source Documents

- `docs/OPS_RUNBOOK.md`
- `docs/PRODUCTION_READINESS_GUIDEBOOK.md`
- `config/topology.md`
- `config/record_recovery_http_service.example.json`
- `config/observability/`
- `config/patroni-ha/`
- `config/pgbouncer/`

## Handoff Criteria

- Target service list is complete and shared with Person 1 and Person 3.
- Each live drill is marked `pass`, `fail`, or `skipped` with reason.
- Logs and JSON reports are stored under `tmp/team_evidence/person_2/`.
- Any service-side finding from Person 3 has a reproducible log or request ID.
