# Joint Certification Tasks And Calls

This directory is the three-person closeout layer for S-level production security tasks.

It does not replace Person 1 / Person 2 / Person 3 evidence scripts. It gathers their evidence and creates the certification packet required by `docs/team/TEAM_COLLABORATION_AND_REPORTING_PLAN.md`.

Run everything from the repository root.

## Script

```bash
bash handoff/joint_certification/run_joint_certification.sh init all
bash handoff/joint_certification/run_joint_certification.sh repo-gates
bash handoff/joint_certification/run_joint_certification.sh evaluate all
```

Static blank forms are also tracked under:

```text
handoff/joint_certification/templates/
```

Use those templates when the team needs a manually filled certification form before or after the generated `tmp/team_evidence/joint_certification` packet is produced.

Default output directory:

```text
tmp/team_evidence/joint_certification
```

Override it with:

```bash
JOINT_CERT_DIR=tmp/team_evidence/pre_joint \
  bash handoff/joint_certification/run_joint_certification.sh all
```

## Modes

| Mode | Purpose |
| --- | --- |
| `init <task|all>` | Create `TASK_SUMMARY.md`, `COMMANDS.md`, `EVIDENCE_INDEX.md`, and `JOINT_CERTIFICATION.md` templates. |
| `repo-gates` | Run every available repo-side S gate and preserve logs/evidence under `repo_gates/`. |
| `evaluate <task|all>` | Write the current honest final status for each S task based on repo-side coverage and required external evidence. |
| `all` | Run `init all`, `repo-gates`, then `evaluate all`. |

Valid task IDs:

```text
S1 S2 S3 S4 S5 S6 S7 S8
```

## Status Rules

The script intentionally does not force `completed`.

Per project rules, `completed` requires all of:

1. implementation
2. reproducible verification
3. evidence files
4. audit/report schema coverage
5. documentation
6. Person 1 certification
7. Person 2 certification
8. Person 3 certification

If a task still needs live KMS, S3/Rekor credentials, two Ubuntu hosts, external penetration testing, production PJC worker service, or human sign-off, the generated packet must say `repo-side complete`, `operator-side skipped`, `partial`, or `planned`.

## Current Expected Evaluation

| Task | Expected honest status before live sign-off |
| --- | --- |
| `S1` | `repo-side complete` |
| `S2` | `repo-side complete` |
| `S3` | `partial` |
| `S4` | `partial` |
| `S5` | `planned` |
| `S6` | `repo-side complete` |
| `S7` | `repo-side complete` |
| `S8` | `planned` |

Use these packets to drive the remaining human and operator-side work. Do not edit them to `completed` unless all certification fields are filled with real evidence.
