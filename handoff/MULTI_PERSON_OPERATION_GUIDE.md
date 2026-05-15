# Multi-Person Operation Guide

This is the entry point for the three-person test and certification workflow.
Run commands from the repository root.

## Directories

| Area | Path | Purpose |
| --- | --- | --- |
| Person 1 | `handoff/person_1_platform_local/` | Local platform smoke, bridge pipeline, dashboard, evidence merge. |
| Person 2 | `handoff/person_2_live_infra/` | Live service, infra topology, health checks, benchmark/operator evidence. |
| Person 3 | `handoff/person_3_security_audit/` | Security pretest, malformed input, tamper resistance, external-anchor and TLS identity gates. |
| Joint certification | `handoff/joint_certification/` | S-level repo gates, final task status packets, certification tables. |

## One-Command Role Runs

```bash
PERSON1_EVIDENCE_DIR=tmp/team_evidence/person_1 \
  bash handoff/person_1_platform_local/run_person_1.sh all

PERSON2_EVIDENCE_DIR=tmp/team_evidence/person_2 \
  bash handoff/person_2_live_infra/run_person_2.sh all

PERSON3_EVIDENCE_DIR=tmp/team_evidence/person_3 \
  bash handoff/person_3_security_audit/run_person_3.sh all
```

`all` is enough only for repo-side/local evidence. Live KMS, real WORM/Rekor credentials,
two Ubuntu PJC hosts, external penetration testing, and human sign-off still require the
operators named in the generated certification packet.

## Joint Certification

```bash
JOINT_CERT_DIR=tmp/team_evidence/joint_certification \
  bash handoff/joint_certification/run_joint_certification.sh all
```

This writes one packet per S-level task:

```text
tmp/team_evidence/joint_certification/S1/
tmp/team_evidence/joint_certification/S2/
...
tmp/team_evidence/joint_certification/S8/
```

Each packet contains:

| File | Purpose |
| --- | --- |
| `TASK_SUMMARY.md` | Task status and missing work. |
| `COMMANDS.md` | Repo-side commands for that task. |
| `EVIDENCE_INDEX.md` | Evidence locations to review and fill. |
| `JOINT_CERTIFICATION.md` | Three-person sign-off table and final wording. |

Blank reusable forms are tracked in:

```text
handoff/joint_certification/templates/
```

Use those when a manually filled form must be committed or attached outside `tmp/`.

## Current Honest S-Level Status

| Task | Repo-side status before live sign-off |
| --- | --- |
| S1 | repo-side complete |
| S2 | repo-side complete |
| S3 | partial |
| S4 | partial |
| S5 | planned |
| S6 | repo-side complete |
| S7 | repo-side complete |
| S8 | planned |

Do not mark a task as `completed` until all required live/operator evidence and all three
person sign-offs are filled.
