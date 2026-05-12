# Person 1 - Internal Coordinator and App Target Owner

## Scope

Owner: Person 1

Machines:

- PC-1: coordinator workstation, repo checkout, evidence index, meeting notes.
- PC-2: staging application target for dashboard/API/recovery-service exposure.

Goal:

- Coordinate the unfinished multi-person work.
- Prepare a stable staging target for Person 3's external/security testing.
- Collect final evidence from Person 2 and Person 3 into one handoff packet.

This pack intentionally excludes completed scale and local-only work.

## Unfinished Multi-Person Tasks

| Task | People needed | Person 1 role |
| --- | --- | --- |
| K3 external pen test | Person 1 + Person 2 + Person 3 + external tester | coordinator, scope owner, evidence owner |
| Live recovery/dashboard target for testing | Person 1 + Person 2 + Person 3 | expose and monitor target services |
| External-anchor live drill if credentials exist | Person 1 + Person 3 | approve scope, store report |
| Final remediation verification | all 3 | collect fixes, rerun focused checks |

## Setup

Run from repo root:

```bash
mkdir -p tmp/team_evidence/person_1
cp handoff/person_1_platform_local/EVIDENCE_LOG.md tmp/team_evidence/person_1/EVIDENCE_LOG.md
```

Confirm the repo state before testing:

```bash
git status --short
bash scripts/check_ci_smoke.sh
```

If full contract smoke is requested before the pen-test window:

```bash
bash scripts/check_json_contracts.sh
```

## Staging Target For Person 3

Start the operator dashboard on PC-2:

```bash
python3 scripts/serve_operator_dashboard.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --history-root tmp \
  --bind-host 127.0.0.1 \
  --port 18134
```

If the tester is not on the same machine, put this behind the approved staging network path. Do not expose it to the public internet without an explicit test window and auth plan.

Health checks to record:

```bash
curl -i http://127.0.0.1:18134/
curl -i http://127.0.0.1:18134/v1/dashboard
```

Optional request/approval DB for workflow testing:

```bash
python3 scripts/init_metadata_db.py --db tmp/team_evidence/person_1/platform_metadata.db

python3 scripts/serve_operator_dashboard.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --history-root tmp \
  --metadata-db-path tmp/team_evidence/person_1/platform_metadata.db \
  --bind-host 127.0.0.1 \
  --port 18134
```

## Coordination Checklist

1. Confirm Person 2 has provided target URLs, ports, credentials handling notes, and rollback contact.
2. Confirm Person 3 has filled `SECURITY_TEST_SCOPE.md` from the template.
3. Freeze the test window start/end time.
4. Record exactly which targets are in scope.
5. Keep logs and command outputs under `tmp/team_evidence/person_1/`.
6. After testing, track each finding as `fixed`, `accepted risk`, or `not reproducible`.

## Evidence To Collect

- Final approved security scope.
- Dashboard target URL and `/v1/dashboard` response.
- Recovery-service target URL and `/health` or `/healthz` response from Person 2.
- Person 3's pen-test report or internal test report.
- Any remediation commits and focused rerun output.

## Source Documents

- `docs/PRODUCTION_READINESS_GUIDEBOOK.md`
- `docs/OPS_RUNBOOK.md`
- `docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md`
- `docs/CONTROL_PANEL_SPEC.md`

## Handoff Criteria

- External/security test scope is approved before testing starts.
- Target list and test window are recorded.
- All findings have an owner and disposition.
- Final report path is recorded in `tmp/team_evidence/person_1/EVIDENCE_LOG.md`.
