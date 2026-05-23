# Attack Surface Hardening Status

Generated local verification date: 2026-05-20

This document records the current defensive hardening state for bounded attack
scenarios in this repository. It intentionally excludes destructive load tests,
brute force, credential stuffing, and third-party target scanning.

## Implemented In This Round

### PJC mTLS Certificate Reuse Defense

New per-job session tooling:

- `scripts/create_pjc_mtls_session.py`
- `scripts/check_pjc_mtls_session_manifest.py`
- `scripts/verify_pjc_mtls_reuse_defense.sh`

Wrapper integration:

- `a-psi/moduleA_psi/scripts/run_pjc_server_tls.sh`
- `a-psi/moduleA_psi/scripts/run_pjc_client_tls.sh`

The wrappers now validate `CERT_DIR/session_manifest.json` when present. Set
`PJC_MTLS_REQUIRE_SESSION_MANIFEST=1` to fail closed if the manifest is absent.

Result:

```text
old client certificate reuse across jobs is rejected by job-bound session manifest checks
```

Evidence:

```text
tmp/pjc_mtls_reuse_defense/
```

### PJC Resource Preflight Integration

The PJC TLS server/client wrappers now run `scripts/preflight_pjc_job.py` before
launch when `PJC_RESOURCE_LIMITS` is set. Set `PJC_PREFLIGHT_REQUIRED=1` to fail
closed if resource limits are not configured.

Useful environment variables:

```bash
PJC_RESOURCE_LIMITS=config/pjc_resource_limits.example.json
PJC_PREFLIGHT_REQUIRED=1
PJC_PREFLIGHT_CALLER=auto_demo
PJC_PREFLIGHT_PURPOSE=bridge_token
```

Party A can optionally provide:

```bash
PJC_PREFLIGHT_CLIENT_ROWS=<expected-client-rows>
PJC_PREFLIGHT_CLIENT_CSV=<client.csv-if-known>
```

Party B can optionally provide:

```bash
PJC_PREFLIGHT_SERVER_ROWS=<expected-server-rows>
PJC_PREFLIGHT_SERVER_CSV=<server.csv-if-known>
```

Result:

```text
oversized PJC jobs can be rejected before launching the PJC binary
```

## Consolidated Local Evidence

Run:

```bash
bash scripts/run_attack_surface_hardening_evidence.sh
```

Latest result:

```json
{
  "status": "pass",
  "case_count": 12,
  "pass_count": 12,
  "fail_count": 0
}
```

Evidence directory:

```text
tmp/attack_surface_hardening_evidence/
```

Cases covered:

| Case | Attack Surface |
| --- | --- |
| `pjc_mtls_reuse_defense` | old client cert / job manifest reuse |
| `pjc_preflight_gate` | oversized rows / bytes / frame-count resource abuse |
| `s3_privacy_budget_repo_evidence` | duplicate, overlap, and budget-exhaustion query abuse |
| `s3_privacy_budget_production_evidence` | fail-closed production budget mode and caller/tenant/dataset/purpose scoped budget abuse |
| `production_handoff_gate` | retained plaintext handoff in production mode |
| `production_kms_gate` | env/local fixture pretending to be production KMS |
| `external_audit_anchor_gate` | audit tamper and local ledger pretending to be external immutability |
| `http_malformed_input_gate` | malformed recovery-service HTTP requests |
| `schema_malformed_input_gate` | malformed JSON contract payloads |
| `enrollment_only_mode_smoke` | dashboard surface exposed during mTLS enrollment |
| `metadata_api_rate_limit_smoke` | metadata API per-caller rate-limit bypass |
| `bucket_dp_smoke` | bucket-level k suppression / DP metadata / public-report redaction |

## Remaining Boundaries

The local hardening package does not prove:

- live AWS S3 Object Lock upload
- live AWS/Vault KMS
- third-party external penetration test
- resistance to theft of the current job's private key during the active session window
- malicious-secure PSI/PJC against arbitrary adversarial protocol participants

Report those as operator-side or future work unless separate live evidence
exists.
