# Security Test Scope

## Dates

- Start:
- End:

## People

- Internal coordinator:
- External tester(s):
- Emergency contact:

## Targets

| Target | URL/host | Owner | Auth method | Allowed tests |
| --- | --- | --- | --- | --- |
| Recovery service |  | Person 2 | mTLS/bearer | malformed input, auth bypass, replay |
| Operator dashboard |  | Person 1 | bearer/local | authz, request workflow, job control |
| Vault/OIDC/OpenFGA |  | Person 2 | operator-provided | config validation, auth boundary |
| Audit anchor flow |  | Person 3 | local key / external sink creds | tamper, replay, signature checks |

## Out Of Scope

- Destructive data deletion.
- Production tenant data.
- AWS account-wide testing outside the named S3 bucket.
- Public Rekor load testing.

## Evidence Required

* Tooling summary, including tools used, versions, configuration, test environment, and any known limitations.
* Tested commit hash, branch name, runtime environment, deployment target, and test timestamp.
* Security scope, including in-scope endpoints, services, data flows, trust boundaries, and explicitly excluded areas.
* Finding list with severity, affected component, impact, likelihood, status, owner, and final disposition.
* Reproduction steps for each finding, including commands, request payloads, expected behavior, and observed behavior.
* Logs, request IDs, job IDs, trace IDs, audit-chain IDs, or other identifiers needed to reproduce and verify each result.
* Evidence artifacts, including screenshots, command outputs, JSON reports, audit logs, schema validation results, and generated files.
* Validation results for fixed findings, including retest commands, retest timestamp, and pass/fail conclusion.
* Accepted-risk notes for unresolved findings, including reason for acceptance, mitigation plan, responsible owner, and review/expiration date.
* False-positive or not-reproducible notes, including why the issue was dismissed and what evidence supports that decision.
* Residual risks and assumptions that remain after testing.
* Follow-up actions, prioritized by severity and operational impact.
* Final security handoff conclusion, marked as `pass`, `blocked`, or `pass with accepted risks`.

