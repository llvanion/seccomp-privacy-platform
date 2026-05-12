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

- Tooling summary.
- Finding list with severity.
- Reproduction steps.
- Logs or request IDs.
- Accepted-risk notes for unresolved findings.
