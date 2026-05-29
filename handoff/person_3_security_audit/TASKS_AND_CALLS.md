# Person 3 Tasks And Calls

Person 3 owns security scope, internal security gates, audit verification, and final finding evidence.

Run everything from the repository root.

## Script

```bash
bash handoff/person_3_security_audit/run_person_3.sh prepare
bash handoff/person_3_security_audit/run_person_3.sh pretest
bash handoff/person_3_security_audit/run_person_3.sh external-anchor-planned
bash handoff/person_3_security_audit/run_person_3.sh gates
```

Default evidence directory:

```text
tmp/team_evidence/person_3
```

Override it with:

```bash
PERSON3_EVIDENCE_DIR=tmp/team_evidence/person_3_k3 \
  bash handoff/person_3_security_audit/run_person_3.sh pretest
```

## Modes

| Mode | Purpose | Main outputs |
| --- | --- | --- |
| `prepare` | Create evidence directory, seed `EVIDENCE_LOG.md`, copy security scope template | `SECURITY_TEST_SCOPE.md`, `FINDINGS.md` |
| `pretest` | Run local malformed-input and audit-tamper evidence | `http_malformed_input_gate.json`, `audit_tamper_resistance.json` |
| `external-anchor-planned` | Produce planned S3 Object Lock and Rekor reports without external credentials | `s3_worm_planned.json`, `rekor_planned.json` |
| `gates` | Run repo-side production/security gate scripts for S1/S2/S6/S7 evidence | gate logs and evidence directories |
| `all` | Run `prepare`, `pretest`, `external-anchor-planned`, and `gates` | all local security evidence |

## Required Input For `pretest`

`pretest` needs an audit chain. By default it reads:

```text
tmp/sse_bridge_pipeline_demo/audit_chain.json
```

Override it when Person 1 gives you a fresh run:

```bash
PERSON3_AUDIT_CHAIN=tmp/live_sse_bridge_demo/run-20260515/audit_chain.json \
PERSON3_JOB_ID=live_demo_job \
  bash handoff/person_3_security_audit/run_person_3.sh pretest
```

## External Testing Rule

Do not start external testing until:

1. `tmp/team_evidence/person_3/SECURITY_TEST_SCOPE.md` is filled.
2. Person 1 approves the scope and time window.
3. Person 2 confirms the target list and rollback/contact path.

## Finding Format

Append findings to:

```text
tmp/team_evidence/person_3/FINDINGS.md
```

Use this shape:

```text
## Finding <id>

- Severity:
- Target:
- Timestamp:
- Reproduction:
- Evidence:
- Owner:
- Disposition: open | fixed | accepted risk | not reproducible
```
