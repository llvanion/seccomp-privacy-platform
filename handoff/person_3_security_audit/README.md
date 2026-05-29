# Person 3 - Security Testing and External Audit Owner

## Scope

Owner: Person 3

Machines:

- PC-5: security test runner / external-audit workstation.
- Shared targets: PC-2 from Person 1 and PC-3/PC-4 from Person 2.

Goal:

- Own the unfinished multi-person security task: K3 external/security test.
- Run internal pre-test gates that directly support K3.
- Package final security evidence under `tmp/team_evidence/person_3/`.

Use [docs/team/TEAM_COLLABORATION_AND_REPORTING_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/team/TEAM_COLLABORATION_AND_REPORTING_PLAN.md) as the shared three-person plan for target readiness, evidence packaging, and pre/final report structure.

This pack intentionally excludes completed scale and local-only work.

## Unfinished Multi-Person Tasks

| Task | People needed | Person 3 role |
| --- | --- | --- |
| K3 external pen test | Person 1 + Person 2 + Person 3 + external tester | security owner, tester interface, report owner |
| Recovery-service boundary test | Person 2 + Person 3 | run malformed/replay/auth tests and record findings |
| Dashboard/API boundary test | Person 1 + Person 3 | test authz and request workflow if exposed |
| Live external-anchor drill if credentials exist | Person 1 + Person 3 | verify S3/Rekor publish evidence |

## Setup

Run from repo root:

```bash
mkdir -p tmp/team_evidence/person_3
cp handoff/person_3_security_audit/EVIDENCE_LOG.md tmp/team_evidence/person_3/EVIDENCE_LOG.md
cp handoff/person_3_security_audit/SECURITY_TEST_SCOPE_TEMPLATE.md tmp/team_evidence/person_3/SECURITY_TEST_SCOPE.md
```

Fill and get approval for:

```text
tmp/team_evidence/person_3/SECURITY_TEST_SCOPE.md
```

Do not start external testing before Person 1 approves the scope and Person 2 confirms target readiness.

## Internal Pre-Test Gates

These are not the external pen test itself; they are local evidence that the existing defensive checks still work before the test window.

```bash
python3 scripts/seal_audit_artifact.py \
  --input tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --out tmp/team_evidence/person_3/audit_chain.seal.json \
  --job-id sse_demo_job

python3 scripts/verify_audit_tamper_resistance.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --audit-seal tmp/team_evidence/person_3/audit_chain.seal.json \
  --job-id sse_demo_job \
  --output tmp/team_evidence/person_3/audit_tamper_resistance.json

python3 scripts/check_http_malformed_input_gate.py \
  --output tmp/team_evidence/person_3/http_malformed_input_gate.json
```

Validate:

```bash
python3 scripts/validate_json_contract.py \
  --schema schemas/audit_tamper_resistance.schema.json \
  --json tmp/team_evidence/person_3/audit_tamper_resistance.json

python3 scripts/validate_json_contract.py \
  --schema schemas/http_malformed_input_gate.schema.json \
  --json tmp/team_evidence/person_3/http_malformed_input_gate.json
```

## External Pen-Test Scope

Minimum target scope:

- Recovery-service HTTP/mTLS boundary.
- Operator dashboard/API boundary if Person 1 exposes it in staging.
- Vault/AppRole or Vault mock-to-live configuration if Person 2 has a live Vault target.
- OIDC/JWKS identity mapping if Person 2 has a live IdP target.
- Audit-chain sealing, archive verification, and external-anchor publish flow.

Out of scope unless explicitly approved:

- destructive data deletion
- production tenant data
- AWS account-wide testing outside the named S3 bucket
- public Rekor load testing

## External Anchor Live Drill

This is only needed if credentials/endpoints exist. Otherwise mark `skipped` with reason.

Create a local anchor file:

```bash
export SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY=local-audit-anchor

python3 scripts/archive_audit_bundle.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --audit-seal tmp/team_evidence/person_3/audit_chain.seal.json \
  --archive-dir tmp/team_evidence/person_3/audit_archive \
  --job-id sse_demo_job \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY
```

Planned S3/Rekor reports, no external credentials:

```bash
python3 scripts/publish_external_audit_anchor.py \
  --anchor-file tmp/team_evidence/person_3/audit_archive/audit_chain_anchor.jsonl \
  --external-ledger s3://seccomp-audit-archive/audit/ledger.jsonl \
  --sink-kind s3_worm \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY \
  --output tmp/team_evidence/person_3/s3_worm_planned.json

python3 scripts/publish_external_audit_anchor.py \
  --anchor-file tmp/team_evidence/person_3/audit_archive/audit_chain_anchor.jsonl \
  --external-ledger https://rekor.sigstore.dev \
  --sink-kind rekor \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY \
  --output tmp/team_evidence/person_3/rekor_planned.json
```

Live S3:

```bash
python3 scripts/publish_external_audit_anchor.py \
  --anchor-file tmp/team_evidence/person_3/audit_archive/audit_chain_anchor.jsonl \
  --external-ledger s3://<bucket>/audit/<tenant>/ledger.jsonl \
  --sink-kind s3_worm \
  --object-lock-mode COMPLIANCE \
  --retain-days 3650 \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY \
  --execute \
  --output tmp/team_evidence/person_3/s3_worm_live.json
```

Live Rekor:

```bash
export SECCOMP_REKOR_SIGNING_KEY_PEM="$(cat <path-to-ecdsa-p256-private-key.pem>)"

python3 scripts/publish_external_audit_anchor.py \
  --anchor-file tmp/team_evidence/person_3/audit_archive/audit_chain_anchor.jsonl \
  --external-ledger https://rekor.sigstore.dev \
  --sink-kind rekor \
  --anchor-key-env SECCOMP_AUDIT_ARCHIVE_ANCHOR_KEY \
  --rekor-signing-key-env SECCOMP_REKOR_SIGNING_KEY_PEM \
  --execute \
  --output tmp/team_evidence/person_3/rekor_live.json
```

## Finding Workflow

For every finding:

1. Assign severity.
2. Record target, request, timestamp, and reproduction steps.
3. Ask Person 1 for owner assignment.
4. Ask Person 2 for service logs if infrastructure-related.
5. Mark final disposition: `fixed`, `accepted risk`, or `not reproducible`.

## Source Documents

- `docs/PRODUCTION_READINESS_GUIDEBOOK.md`
- `docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md`
- `docs/COMPLIANCE_MAPPING.md`
- `docs/OPS_RUNBOOK.md`
- `docs/IAM_AUTHZ_INTEGRATION_PLAN.md`
- `docs/KMS_SECRET_BACKEND_PLAN.md`

## Handoff Criteria

* Security scope is approved and documented, including in-scope services, APIs, data flows, trust boundaries, and explicitly out-of-scope items.
* Internal K3 pre-test gates are completed and schema-valid, including audit-chain validation, malformed-input checks, access-control checks, and JSON contract validation.
* External pen-test report or internal security test report is stored or linked, with test date, tester, environment, commit hash, and tested endpoints clearly recorded.
* Critical and high-severity findings are fixed, retested, and linked to evidence, or explicitly accepted as risk with owner, reason, mitigation, and expiration/review date.
* Medium and low-severity findings are triaged, assigned an owner, and either fixed, deferred with reason, or added to the follow-up backlog.
* Live S3/Rekor drills are completed or explicitly marked skipped with reason, including whether evidence upload, transparency-log submission, and verification steps were successful.
* All security evidence is stored under the agreed evidence directory, including logs, reports, command outputs, schema validation results, and audit-chain artifacts.
* The final evidence log is updated with timestamp, environment, command, output artifact path, result, and short conclusion for each validation step.
* No unexplained local-only changes remain before handoff; `git status` is reviewed and only intended tracked/untracked files are committed or documented.
* Required runtime secrets, tokens, and credentials are not committed to the repository, and secret handling assumptions are documented.
* The handoff README includes the exact reproduction commands for the latest validation run.
* The receiving person can rerun the documented checks from a clean checkout and obtain the same pass/fail result.
* Any skipped, flaky, or environment-dependent checks are clearly marked with reason, impact, and recommended next action.
* Final handoff status is explicitly marked as `ready`, `blocked`, or `ready with accepted risks`.

