# Compliance Mapping (GDPR + General Privacy Principles)

This document maps the platform's enforcement points to the seven core GDPR principles plus the most relevant data-subject rights, so a compliance reviewer can trace each claim back to a concrete file, schema, or audit record. It is the K2 deliverable from `docs/PRODUCTION_READINESS_GUIDEBOOK.md`.

It is intentionally narrow: it documents what the platform *does today*, not what is delegated to operators (Vault, OpenFGA, Keycloak, immutable external ledger). Operator-environment work is called out where applicable.

## 1. GDPR Article 5(1) Principles

### 1.1 Lawfulness, fairness, transparency

| Mechanism | Evidence |
|-----------|----------|
| Every cross-party query goes through a structured request envelope (`query_workflow_request/v1`) and is dry-run validated before any data is touched. | `schemas/query_workflow_request.schema.json`, `scripts/submit_query_workflow.py`. |
| Each pipeline run produces a public report (`public_report/v1`) and a signed audit chain (`audit_chain/v1` + `audit_seal/v1`); the public report is the lawful, transparent output that may be shown to data subjects or auditors. | `schemas/public_report.schema.json`, `schemas/audit_chain.schema.json`, `scripts/seal_audit_artifact.py`. |
| Caller identity comes from a configurable identity proxy (default file-backed; OIDC/Keycloak optional via `map_oidc_claims.py --jwks-uri`); identity resolution is recorded in `api_identity_resolution/v1` so every action is attributable. | `scripts/serve_identity_proxy.py`, `scripts/map_oidc_claims.py`, `schemas/api_identity_resolution.schema.json`. |

### 1.2 Purpose limitation

| Mechanism | Evidence |
|-----------|----------|
| `caller_permissions.allowed_service_ids`, `policy_bindings`, and the unified export policy gate every export, recovery, bridge, PJC, and release operation per (caller, tenant, dataset, service). | `sse/config/export_policy.example.json`, `schemas/sse_export_policy.schema.json`, `services/record_recovery/authz.py`, `scripts/check_authority_governance.py`. |
| OpenFGA tuple sync exports the same permission tuples for cross-checking against an external authoritative source (operator-environment). | `scripts/sync_openfga_tuples.py`, `scripts/check_openfga_authz.py`, `migrations/metadata/007_add_openfga_tuples.sql`. |
| `policy_release.py --deny-duplicate-query` rejects exact repeated canonical query signatures from the same caller, blocking trivial re-purposing of an approved query. | `a-psi/moduleA_psi/scripts/policy_release.py`, `schemas/policy_audit.schema.json`. |
| All policy/binding mutations are recorded in `control_plane_mutations` (migration 005), so a purpose change can always be attributed to a principal and a time. | `migrations/metadata/005_add_control_plane_mutation_log.sql`. |

### 1.3 Data minimization

| Mechanism | Evidence |
|-----------|----------|
| SSE candidate export returns only records whose tokenized join key matches the query scope; the encrypted record store never decrypts more rows than the worker subprocess actually needs. | `sse/run_client.py export-bridge-records`, `services/record_recovery/encrypted_record_store.py`, `services/record_recovery/worker.py`. |
| The bridge tokenizes join keys (HMAC-SHA256 with token secret) before any data leaves the boundary; the bridge handoff carries tokens plus values, not raw join keys. | `bridge/src/main.rs prepare-job`, `schemas/bridge_job_meta.schema.json`. |
| The PJC stage emits only intersection-level outputs (count, sum) and never reveals individual records to the receiving party. | `a-psi/moduleA_psi/scripts/run_pjc.sh`, `schemas/pjc_audit.schema.json`. |
| `--sse-export-handoff-mode fifo` plus `cleanup_sse_export_handoff_files_after_bridge=true` (default) ensures plaintext handoff is removed after bridge prepare-job, leaving only the tokenized output on disk. | `scripts/run_sse_bridge_pipeline.sh`. |

### 1.4 Accuracy

| Mechanism | Evidence |
|-----------|----------|
| Bridge `prepare-job` requires per-side `normalizer` and `normalize_version`; `validate_bridge_job.py` rejects unknown normalizer schema versions before PJC runs, so the same join-key normalization runs on both sides. | `a-psi/moduleA_psi/scripts/validate_bridge_job.py`, `schemas/bridge_job_meta.schema.json`. |
| `mainline_contract_check/v1` reconciles SSE export, recovery service, bridge, PJC, and policy stages by `job_id`/`correlation_id`; mismatched scope, hashes, or counts fail the run before release. | `scripts/check_mainline_contract.py`, `schemas/mainline_contract_check.schema.json`. |
| Schema backcompat baseline freezes 110+ contract schemas; `check_schema_backcompat.py` rejects breaking field renames or required-key removals, so audit/policy fields cannot silently drift. | `config/schema_backcompat_baseline.json`, `scripts/check_schema_backcompat.py`. |
| Tamper resistance is now actively verified: `verify_audit_tamper_resistance.py` flips one byte in the audit chain or seal and asserts that `verify_audit_bundle.py` rejects it. The HTTP boundary is also actively probed: `check_http_malformed_input_gate.py` spawns the record-recovery HTTP service in-process and asserts that 10 malformed-request scenarios are all rejected. | `scripts/verify_audit_tamper_resistance.py`, `schemas/audit_tamper_resistance.schema.json`, `scripts/check_http_malformed_input_gate.py`, `schemas/http_malformed_input_gate.schema.json`. |

### 1.5 Storage limitation

| Mechanism | Evidence |
|-----------|----------|
| `retention_reconcile_plan/v1` (C5) generates a retention plan covering audit, registry, and key-lifecycle records; configurable TTLs flag records for review. | `scripts/materialize_control_plane_deepening.py --list-entity retention-reconcile-plan`. |
| Backups have explicit primitives now: `backup_metadata_db.py` (SQLite copy or `pg_dump`, optional S3 upload, emits `metadata_db_backup_report/v1`) and `restore_metadata_db.py` (auto-detects format, optional portability re-check). | `scripts/backup_metadata_db.py`, `scripts/restore_metadata_db.py`. |
| Encrypted record-store keys are derived per-store (PBKDF2HMAC-SHA256 over a passphrase); rotation/deactivation lifecycle is logged in `key_lifecycle_audit/v1`. | `services/record_recovery/encrypted_record_store.py`, `scripts/manage_keyring.py`, `schemas/key_lifecycle_audit.schema.json`. |
| **Known limitation:** `retention_reconcile_plan` produces a `review` action only. There is no automated `delete` path yet — the data subject erasure operation is still operator-driven (see §3.1). |

### 1.6 Integrity and confidentiality

| Mechanism | Evidence |
|-----------|----------|
| Encrypted record store: AES-256-GCM payloads, HMAC-SHA256 record-id tags (no raw record IDs on disk), passphrase from env var only. | `services/record_recovery/encrypted_record_store.py`. |
| Record-recovery service supports mTLS (D1) with optional `ProtectSystem=strict` systemd hardening; `record_recovery_service_log/v1` records `tls_enabled` and `tls_require_client_cert` per request. | `services/record_recovery/http_service.py`, `services/record_recovery/launcher.py`, `config/record_recovery_http_mtls_service.example.json`. |
| Recovery client signs every `recover` request with HMAC-SHA256 over `request_id:request_timestamp_utc:op` and the server enforces a 30 s skew window; signature and timestamp fields are recorded in `sse_record_recovery_service_audit/v1`. | `services/record_recovery/client.py`, `services/record_recovery/http_service.py`, `schemas/sse_record_recovery_service_audit.schema.json`. |
| Audit chain is sealed with SHA-256 plus optional HMAC-SHA256 (`audit_seal/v1`); archived bundles add a per-tenant append-only anchor log (`audit_archive_anchor/v1`); tamper-resistance is now actively asserted in default contract smoke. | `scripts/seal_audit_artifact.py`, `scripts/archive_audit_bundle.py`, `scripts/verify_audit_bundle.py`, `scripts/verify_audit_tamper_resistance.py`. |
| Key management: local key-agent (Unix socket) and external HTTP KMS adapter; AWS KMS secret-ref baseline is checked in (`secret_ref.kind=aws_kms`). Vault HTTP token/AppRole client and Vault PKI cert issuer are wired with mock fallback for default smoke. | `scripts/key_agent_service.py`, `scripts/external_kms_service.py`, `scripts/cloud_kms_adapter.py`, `scripts/vault_http_client.py`, `scripts/issue_mtls_certs.py`. |

### 1.7 Accountability

| Mechanism | Evidence |
|-----------|----------|
| Every stage emits a typed audit record: `sse_bridge_export_audit/v1`, `sse_record_recovery_service_audit/v1`, `bridge_audit/v1`, `pjc_audit/v1`, `policy_audit/v1`, `key_access_audit/v1`. The audit chain (`audit_chain/v1`) correlates them by `job_id` + `correlation_id`. | `schemas/*audit*.schema.json`, `scripts/build_audit_chain.py`. |
| Local archive ledger (`audit_archive_anchor/v1`) is append-only and HMAC-signed; the external publisher (`publish_external_audit_anchor.py`) writes per-tenant ledger entries (`external_audit_anchor_ledger/v1`). The current external sink is a local file ledger. | `scripts/archive_audit_bundle.py`, `scripts/publish_external_audit_anchor.py`, `schemas/external_audit_anchor_report.schema.json`. |
| Control-plane mutations (`control_plane_mutations` table; migration 005) record who changed which policy/permission/binding and when. | `migrations/metadata/005_add_control_plane_mutation_log.sql`. |
| OTel bridge (`scripts/export_otel_events.py`) emits structured spans/events from the audit chain so an observability backend can correlate the same accountability evidence. | `scripts/export_otel_events.py`, `schemas/otel_export_report.schema.json`. |

## 2. Data-Subject Rights Coverage

| Right (GDPR Art. 15-22) | Current Status | Operator/Engineering Action Required |
|-------------------------|----------------|--------------------------------------|
| Access (Art. 15) | Public report + audit chain plus metadata sidecar (`scripts/query_metadata.py`) provide per-job evidence; per-data-subject lookup is not yet implemented end-to-end because the platform never persists raw join keys server-side. | Operator must combine the original tenant data sources with the audit chain to satisfy a subject-access request. |
| Rectification (Art. 16) | Source records live with the tenant; the platform itself does not store rectifiable PII. | Tenant-side correction outside the platform. |
| Erasure (Art. 17) | **Known limitation.** `retention_reconcile_plan` flags candidates for review; no automated delete path. Encrypted record store can be discarded by destroying the passphrase (key-erasure approach). | Engineering follow-up for an automated delete pipeline; operationally, key-destruction can serve as cryptographic erasure today. |
| Restriction (Art. 18) | Caller permissions can be set to `enabled=false`; `export_authz_tuples.py` preserves the disabled subject in the export but emits no active tuples for it. | Operator disables the affected caller and re-syncs OpenFGA tuples. |
| Portability (Art. 20) | Public report + `metadata_db_export/v1` JSON export provide portable, schema-validated records. | None platform-side; tenant decides how to forward. |
| Objection (Art. 21) | Same as restriction — caller permission disable is the enforcement primitive. | Operator action. |
| Automated decision-making (Art. 22) | The platform performs a private set intersection plus aggregate; it does not produce per-subject automated decisions on its own. | Out of scope for this codebase. |

## 3. Known Limitations

These are the items a reviewer should explicitly weigh; they are not bugs but explicit trade-offs.

### 3.1 No automated erasure pipeline

`retention_reconcile_plan/v1` produces an `action=review` plan. The platform does not currently execute an automated erasure step. Recommended approaches:

1. **Cryptographic erasure** — destroy the encrypted record store passphrase (held in a KMS-backed env var) for the affected tenant slice; rows become permanently undecryptable.
2. **Sidecar truncation** — operator drops the affected `runs` / `audits` / `archive` rows in the metadata DB, then re-derives the public report.

Both paths are operator-driven today. A future engineering block (post-K3) is expected to add an automated `action=delete` path with a control-plane mutation record.

### 3.2 Audit seal protects integrity, not all seal metadata fields

The seal's integrity check covers `artifact_sha256` (which re-hashes the entire `audit_chain.json`) plus `signature` when an HMAC key is supplied. Other seal fields — `artifact_file`, `ts_utc`, `signature_algorithm` — are descriptive metadata and are not bound by the seal's own SHA-256 / HMAC. `verify_audit_tamper_resistance.py` is therefore deliberately scoped to flip bytes inside the protected fields (`correlation_id` and `job_id` and any byte of the chain; `artifact_sha256`, `job_id`, and the optional `signature` value of the seal). Reviewers should not interpret tamper-resistance success as a guarantee that descriptive seal metadata fields are protected.

### 3.3 External audit anchor is local-file by default

`publish_external_audit_anchor.py` writes to a local append-only ledger (`external_audit_anchor_ledger/v1`). For real immutable storage, an operator must connect this sink to a write-once medium (object lock, transparency log, blockchain). K1-a / K1-b cover that integration.

### 3.4 Live identity / authz adapters are operator-environment work

OIDC RS256/JWKS validation, OpenFGA live HTTP, and Vault KV/AppRole/PKI all have repo-side adapters and example configs (`docker-compose.authority.yml`, `config/keycloak_realm_seccomp_privacy.json`, `config/openfga_authorization_model.json`, `config/vault_http_client.example.json`). Default contract smoke runs offline; live validation is operator-side under `OPENFGA_ENDPOINT`, `VAULT_ADDR`, etc.

### 3.5 PostgreSQL portability

The metadata sidecar runs on SQLite by default. PostgreSQL is supported through the psycopg2 driver layer (`scripts/metadata_db.py`); F1-b's repo-side gate (`check_metadata_schema_portability.py --smoke-out-base ...`) is in place but real Postgres execution is operator-environment work.

### 3.6 Right-to-erasure crypto-shred guidance

If a tenant exercises the right to erasure under §3.1 by destroying a passphrase, the operator should:

1. Record a `control_plane_mutation` entry with `kind=key_destruction` and the affected `tenant_id`/`dataset_id`.
2. Mark the matching `keyring_lifecycle_audit/v1` entry as `deactivated` with reason `crypto_erasure_request`.
3. Verify that any newer pipeline run for that tenant fails the SSE export policy gate, demonstrating the data is no longer reachable.

## 4. Reviewer Checklist

For a compliance/legal reviewer, the minimal evidence path (now 8 steps) is:

1. Pick a recent run directory (`tmp/sse_bridge_pipeline_demo` or any operator run).
2. Open `audit_chain.json` — confirm `job_id`, `correlation_id`, `caller`, `tenant_id`, `dataset_id`, `service_id` align with the policy used (`sse/config/export_policy.example.json`).
3. Run `scripts/verify_audit_bundle.py --audit-chain ... --audit-seal ...` to confirm signed integrity.
4. Run `scripts/verify_audit_tamper_resistance.py --audit-chain ... --audit-seal ... --job-id <id>` to confirm tamper detection works against the chosen run.
5. Open `public_report.json` — confirm `intersection_size`, `pjc_result_sha256`, and the deny-duplicate-query state.
6. Cross-check `query_metadata.py --list-entity caller-permissions` for the caller's `permission_summary` (allowed datasets, services, role).
7. Check `archive_audit_bundle.py` output for the per-tenant index/anchor; the anchor entries chain cryptographically and are HMAC-signed when `--anchor-key-env` is set.

8. Run `scripts/check_http_malformed_input_gate.py --output tmp/http_malformed_input_gate.json` to confirm the HTTP boundary still rejects the documented attack scenarios end-to-end. The report should show `summary.status=ok` and `summary.detected==summary.total>=8`.

If all eight steps complete without error, the run satisfies the principles in §1 with the limitations in §3.
