# Person 2 Tasks And Calls

Person 2 owns live/staging service boundaries, recovery-service readiness, infrastructure notes, and performance evidence.

Run everything from the repository root.

## Script

```bash
bash handoff/person_2_live_infra/run_person_2.sh prepare
bash handoff/person_2_live_infra/run_person_2.sh service
bash handoff/person_2_live_infra/run_person_2.sh health
bash handoff/person_2_live_infra/run_person_2.sh benchmarks
```

Default evidence directory:

```text
tmp/team_evidence/person_2
```

Override it with:

```bash
PERSON2_EVIDENCE_DIR=tmp/team_evidence/person_2_live \
  bash handoff/person_2_live_infra/run_person_2.sh benchmarks
```

## Modes

| Mode | Purpose | Main outputs |
| --- | --- | --- |
| `prepare` | Create evidence directory and seed `EVIDENCE_LOG.md` | `tmp/team_evidence/person_2/EVIDENCE_LOG.md` |
| `service` | Start the recovery-service target in the foreground | service stdout/stderr in terminal |
| `health` | Probe the configured recovery service | `recovery_service_health.json` |
| `benchmarks` | Run lightweight recovery and bridge benchmark evidence | `record_recovery_benchmark.json`, `bridge_benchmark.json` |
| `infra-plan` | Render repo-side infra topology reports when generators exist | topology reports under evidence dir |
| `all` | Run `prepare`, `health`, `benchmarks`, and `infra-plan` | all non-foreground evidence |

## Recovery Service Defaults

The script uses:

```text
config/record_recovery_http_service.example.json
```

Override with:

```bash
PERSON2_RECOVERY_CONFIG=config/record_recovery_http_mtls_service.example.json \
  bash handoff/person_2_live_infra/run_person_2.sh health
```

Use `service` in a dedicated terminal:

```bash
bash handoff/person_2_live_infra/run_person_2.sh service
```

Then run health/benchmarks from another terminal.

## Handoff To Person 3

Record in `tmp/team_evidence/person_2/EVIDENCE_LOG.md`:

1. Recovery-service URL, transport, auth method, cert paths, and log path.
2. Any PostgreSQL / pgBouncer / Patroni / observability target that is in scope.
3. Which live drills are `pass`, `fail`, or `skipped`.
4. Request IDs or log paths for any security finding Person 3 reproduces.
