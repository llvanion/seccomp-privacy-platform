# AWS S3 Object Lock Interface Status

Generated local verification date: 2026-05-20

This document records what is already implemented for the AWS S3 Object Lock
audit-anchor path, what was locally verified without AWS credentials, and what
remains unverified until an operator provides an AWS account, credentials, and
an Object Lock enabled bucket.

## Short Answer

The AWS-facing interface is already present in the repository.

Implemented entry point:

```bash
python3 scripts/publish_external_audit_anchor.py \
  --anchor-file <audit_chain_anchor.jsonl> \
  --external-ledger s3://<bucket>/audit/<tenant>/ledger.jsonl \
  --sink-kind s3_worm \
  --object-lock-mode GOVERNANCE \
  --retain-days 1 \
  --execute \
  --output tmp/team_evidence/person_3/s3_worm_live.json
```

Without `--execute`, the same path produces planned evidence and does not call
AWS.

## Implemented AWS Interface

`scripts/publish_external_audit_anchor.py` supports:

- `--sink-kind s3_worm`
- `--external-ledger s3://bucket/key.jsonl`
- `--object-lock-mode COMPLIANCE|GOVERNANCE`
- `--retain-days <n>`
- `--execute`

When `--execute` is present, the script lazy-imports `boto3`, reads any existing
object with `get_object`, appends verified `external_audit_anchor_ledger/v1`
JSONL lines, and uploads the new object with:

- `ObjectLockMode`
- `ObjectLockRetainUntilDate`
- `ContentType=application/x-ndjson`

The report schema already records:

- bucket
- key
- object lock mode
- retain-until timestamp
- retain days
- executed flag
- status
- etag
- version id
- previous object etag

Schema:

```text
schemas/external_audit_anchor_report.schema.json
```

## Local Verification Completed Without AWS

Command run locally:

```bash
bash scripts/verify_external_audit_anchor_gate.sh --keep-out-dir
```

Observed result:

```text
[ok] external audit anchor gate verified: case-1 (file_ledger ok) + case-2 (tamper) + case-3 (prod/file_ledger) + case-4 (prod/s3 not executed) + case-5 (schemas)
```

Preserved local evidence directory from this run:

```text
/tmp/seccomp_anchor_gate.nnbPc3
```

The local gate verified:

| Case | Result | Meaning |
| --- | --- | --- |
| valid file ledger publish | pass | baseline anchor chain verification works |
| tampered anchor JSONL | pass | tamper is rejected before any sink write |
| production + file ledger | pass | local file sink cannot satisfy production external-anchor gate |
| production + s3_worm without `--execute` | pass | planned S3 Object Lock evidence is rejected for production completion |
| schema validation | pass | generated reports match `external_audit_anchor_report/v1` |

## What Is Not Verified Without AWS

The following items are not verified until an AWS live drill is run:

- `boto3` authentication against a real AWS account
- S3 bucket existence and permissions
- bucket Object Lock enablement
- successful `put_object` with `ObjectLockMode`
- returned `ETag`
- returned `VersionId`
- retention metadata on the uploaded object
- post-upload read-back from S3

Therefore, without AWS credentials and a live bucket, the correct final-report
status is:

```text
AWS S3 Object Lock interface and production gate: repo-side verified
AWS S3 Object Lock live upload: not executed
External immutable archive completion: operator-side pending
```

Do not write:

```text
AWS S3 Object Lock live drill completed
```

unless `s3_object_lock.status` is `uploaded` in a live evidence report.

## Why This Is Still Useful

The current local verification proves that the project will not accidentally
claim production external immutability from a local file ledger or planned
status. In production mode, the script fails closed unless:

- the sink is `s3_worm` or `rekor`,
- `--execute` is provided,
- and the external sink finishes with `uploaded` status.

This is the correct behavior when AWS is not available: local evidence can
verify the control logic, but cannot substitute for live cloud evidence.

## Future AWS Live Drill

If an AWS account becomes available, use a short-retention test first.

Recommended live-test posture:

- use a dedicated test bucket
- enable Object Lock at bucket creation time
- use `GOVERNANCE`, not `COMPLIANCE`, for the first test
- use `--retain-days 1`
- use a least-privilege IAM user or role
- do not use root credentials

Expected successful live report condition:

```json
{
  "external_sink": {
    "kind": "s3_worm",
    "s3_object_lock": {
      "executed": true,
      "status": "uploaded",
      "etag": "...",
      "version_id": "..."
    }
  },
  "summary": {
    "status": "ok"
  }
}
```

Only after that result exists should the report say that the AWS S3 Object Lock
live audit-anchor drill is completed.
