# Person 1 Tasks And Calls

Person 1 owns coordination, the main demo evidence, and the final evidence index.

Run everything from the repository root.

## Script

```bash
bash handoff/person_1_platform_local/run_person_1.sh prepare
bash handoff/person_1_platform_local/run_person_1.sh demo
bash handoff/person_1_platform_local/run_person_1.sh smoke
bash handoff/person_1_platform_local/run_person_1.sh dashboard
```

Default evidence directory:

```text
tmp/team_evidence/person_1
```

Override it with:

```bash
PERSON1_EVIDENCE_DIR=tmp/team_evidence/person_1_pre \
  bash handoff/person_1_platform_local/run_person_1.sh demo
```

## Modes

| Mode | Purpose | Main outputs |
| --- | --- | --- |
| `prepare` | Create evidence directory and seed `EVIDENCE_LOG.md` | `tmp/team_evidence/person_1/EVIDENCE_LOG.md` |
| `demo` | Run the live SSE -> bridge -> PJC demo and collect the latest core artifacts | `live_demo_manifest.json`, `public_report.json`, `mainline_contract_check.json`, `audit_chain.json` |
| `smoke` | Run repo-level smoke checks for release confidence | `check_ci_smoke.log`, `check_json_contracts.log` |
| `dashboard` | Start the operator dashboard for Person 3 testing | foreground HTTP server |
| `all` | Run `prepare`, `demo`, then `smoke` | all local evidence |

## Dashboard Defaults

The dashboard mode defaults to:

```text
bind host: 127.0.0.1
port: 18134
out base: tmp/sse_bridge_pipeline_demo
history root: tmp
```

Override when needed:

```bash
PERSON1_DASHBOARD_HOST=0.0.0.0 \
PERSON1_DASHBOARD_PORT=18134 \
PERSON1_OUT_BASE=tmp/live_sse_bridge_demo/run-20260515 \
PERSON1_HISTORY_ROOT=tmp \
  bash handoff/person_1_platform_local/run_person_1.sh dashboard
```

Only expose `0.0.0.0` during an approved test window.

## Handoff To Other People

Give Person 2 and Person 3:

1. The latest `tmp/team_evidence/person_1/live_demo_manifest.json`.
2. The latest dashboard URL if `dashboard` mode is running.
3. The approved test window and target list.
4. The final `tmp/team_evidence/person_1/EVIDENCE_LOG.md` path.
