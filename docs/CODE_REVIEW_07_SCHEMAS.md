# Code Review — Step 7: Schema and Contract System

**Scope:** `schemas/` (66 files), `config/schema_backcompat_baseline.json`, `scripts/check_schema_backcompat.py`, `scripts/validate_json_contract.py`, `scripts/validate_tabular_contract.py`

---

## 1. Schema Organization

The `schemas/` directory contains 66 JSON Schema files grouped by functional domain:

### 1.1 Main Pipeline Audit Schemas

| Schema | Version | Purpose |
|---|---|---|
| `sse_bridge_export_audit.schema.json` | `sse_bridge_export_audit/v1` | SSE export stage audit record |
| `sse_record_recovery_service_audit.schema.json` | `sse_record_recovery_service_audit/v1` | Recovery service per-request audit |
| `bridge_audit.schema.json` | `bridge_audit/v1` | Bridge tokenization stage audit |
| `bridge_job_meta.schema.json` | `bridge_job_meta/v1` | Bridge job metadata including normalizer governance |
| `pjc_audit.schema.json` | `pjc_audit/v1` | PJC execution stage audit |
| `policy_audit.schema.json` | `policy_audit/v1` | Policy release decision audit |
| `public_report.schema.json` | `public_report/v2` | Released intersection result report |

### 1.2 Audit Chain / Archive Schemas

| Schema | Version | Purpose |
|---|---|---|
| `audit_chain.schema.json` | `audit_chain/v1` | Correlated cross-stage audit view |
| `audit_seal.schema.json` | `audit_seal/v1` | HMAC/Ed25519 seal over audit chain |
| `audit_archive_index.schema.json` | `audit_archive_index/v1` | Append-only archive index entry |
| `audit_archive_anchor.schema.json` | `audit_archive_anchor/v1` | Append-only anchor log entry for chain replay |
| `audit_bundle_verification.schema.json` | `audit_bundle_verification/v1` | Archive bundle verification report |
| `mainline_contract_check.schema.json` | `mainline_contract_check/v1` | Cross-stage consistency report |

### 1.3 Recovery Service Runtime Schemas

| Schema | Version | Purpose |
|---|---|---|
| `record_recovery_service_config.schema.json` | `record_recovery_service_config/v1` | Shared runtime config (socket/HTTP) |
| `record_recovery_service_health.schema.json` | `record_recovery_service_health/v1` | Service health response |
| `record_recovery_service_log.schema.json` | `record_recovery_service_log/v1` | Structured service lifecycle log |
| `record_recovery_service_policy.schema.json` | `record_recovery_service_policy/v1` | Legacy narrow authz policy |
| `record_recovery_authz_source.schema.json` | `record_recovery_authz_source/v1` | SQL-backed authz source config |
| `record_recovery_boundary_check.schema.json` | `record_recovery_boundary_check/v1` | Shim boundary check output |

### 1.4 Key Management Schemas

| Schema | Version | Purpose |
|---|---|---|
| `key_manifest.schema.json` | `key_manifest/v1` | Static key manifest |
| `keyring.schema.json` | `keyring/v1` | Live keyring with active-version lifecycle |
| `external_kms_config.schema.json` | `external_kms_config/v1` | External HTTP KMS client config |
| `key_access_audit.schema.json` | `key_access_audit/v1` | Key resolution audit record |
| `key_lifecycle_audit.schema.json` | `key_lifecycle_audit/v1` | Key rotation/deactivation audit |

### 1.5 Policy and Access Model Schemas

| Schema | Version | Purpose |
|---|---|---|
| `sse_export_policy.schema.json` | `sse_export_policy/v1` | Unified caller/tenant/dataset/service policy |
| `sse_encrypted_record_store.schema.json` | `sse_encrypted_record_store/v1` | Encrypted store header |
| `authz_tuple_export.schema.json` | `authz_tuple_export/v1` | OpenFGA-style tuple export |

### 1.6 Sidecar / API Schemas

| Schema Group | Covers |
|---|---|
| `metadata_api_*.schema.json` | Metadata sidecar HTTP API envelopes |
| `metadata_db_*.schema.json` | Metadata DB lifecycle operations |
| `metadata_import_report.schema.json` | Import dry-run/replay report |
| `metadata_registry_*.schema.json` | Registry write path manifests and reports |
| `metadata_schema_portability.schema.json` | PostgreSQL portability check report |
| `audit_query_api_*.schema.json` | Audit/public-report HTTP adapter envelopes |
| `query_workflow_*.schema.json` | Query/workflow adapter request, manifest, API envelopes |
| `platform_health*.schema.json` | Platform health API and report |
| `platform_health_api_*.schema.json` | Platform health HTTP adapter envelopes |

### 1.7 Benchmark Schemas

| Schema | Version | Benchmark |
|---|---|---|
| `pipeline_benchmark.schema.json` | `pipeline_benchmark/v1` | Full pipeline end-to-end |
| `live_sse_benchmark.schema.json` | `live_sse_benchmark/v1` | Live SSE-backed pipeline |
| `pjc_benchmark.schema.json` | `pjc_benchmark/v1` | PJC-only |
| `query_workflow_benchmark.schema.json` | `query_workflow_benchmark/v1` | Query workflow dry-run |
| `read_adapter_benchmark.schema.json` | `read_adapter_benchmark/v1` | Metadata/audit read adapters |
| `record_recovery_benchmark.schema.json` | `record_recovery_benchmark/v1` | Record recovery service |
| `audit_bundle_benchmark.schema.json` | `audit_bundle_benchmark/v1` | Audit archive/verify |
| `platform_health_benchmark.schema.json` | `platform_health_benchmark/v1` | Platform health check |
| `derived_views_benchmark.schema.json` | `derived_views_benchmark/v1` | Derived observability/catalog views |

### 1.8 Gate Schemas

| Schema | Version | Purpose |
|---|---|---|
| `malformed_input_gate.schema.json` | `malformed_input_gate/v1` | Systematic negative-test gate |
| `pre_release_gate.schema.json` | `pre_release_gate/v1` | Unified pre-release check |
| `operator_readiness.schema.json` | `operator_readiness/v1` | Deployment readiness check |
| `repo_hygiene_scan.schema.json` | `repo_hygiene_scan/v1` | Repository hygiene scan report |
| `dependency_hygiene.schema.json` | `dependency_hygiene/v1` | Dependency reproducibility check |
| `schema_backcompat_check.schema.json` | `schema_backcompat_check/v1` | Schema backward-compat check report |

---

## 2. Backward Compatibility System

### 2.1 `config/schema_backcompat_baseline.json`

Every schema that is "frozen" appears in this file with:
- `path`: relative path to the schema file.
- `schema_id`: the `$id` value that must not change.
- `required`: the `required` array that must not lose entries.
- `stable_properties`: properties that must continue to exist in the schema's `properties` object.

### 2.2 `check_schema_backcompat.py`

For each entry in the baseline:
1. Verifies the schema file still exists.
2. Verifies the `$id` has not changed.
3. Verifies no `required` properties have been removed.
4. Warns if new `required` properties have been added (breaking for old consumers).
5. Verifies all `stable_properties` still appear in the `properties` object.

This is the mechanism that prevents silent breaking changes to frozen contract schemas. It runs as part of `check_json_contracts.sh`.

---

## 3. `validate_json_contract.py`

Validates a JSON file or each line of a JSONL file against a named schema. Used by:
- The integrated pipeline (for every stage output).
- The contract smoke suite (for all example configs and synthetic fixtures).
- The benchmark wrappers (for their output reports).

---

## 4. `validate_tabular_contract.py`

Validates CSV and JSONL files for non-JSON structural contracts (e.g. bridge handoff CSVs). Checks:
- Column presence and order.
- Row count lower bounds.
- Required column value constraints.

The contract smoke suite includes negative fixtures for malformed bridge/PJC tabular inputs.

---

## 5. Schema Design Observations

### Strengths
- All 66 schemas have a `$id` field with a versioned identifier (e.g. `bridge_audit/v1`).
- The `schema` field is present and required in all audit/governance schemas, enabling self-description.
- All schemas use `"additionalProperties": false` or equivalent tightening where appropriate.
- The `normalizer_schema_version` field in `bridge_job_meta/v1` correctly distinguishes the algorithm contract version from the caller-supplied run version.
- The `request_signature_verified` and `signature_algorithm` fields in `sse_record_recovery_service_audit/v1` are listed in `stable_properties` — these are correctly treated as non-removable.

### Gaps / Observations

| Item | Severity | Note |
|---|---|---|
| Schema versioning is string-based (e.g. `v1`) with no semantic versioning | Low | Adequate for prototype; production should use proper schema registry or semver |
| No formal schema registry for external consumers | Low | Schemas are in-repo only; external consumers cannot query a registry endpoint |
| Some schemas use `"type": "object"` without `additionalProperties: false` | Low | May accept unexpected extra fields; not a breaking issue for read-only consumers |
| `stable_properties` in baseline is manually curated | Low | Could become stale if a property is renamed rather than removed |
| No JSON Schema `$defs` reuse for common fields | Low | `job_id`, `correlation_id`, `caller` are redefined in many schemas; refactoring to `$defs` would reduce drift |

---

## 6. Summary

The schema system is comprehensive and correctly used as a contract enforcement mechanism throughout the platform. The backward-compatibility baseline covers all stable schemas with field-level granularity. The schema backcompat check runs as part of CI. The main gaps are the lack of a formal schema registry and the manual curation of `stable_properties`, both of which are acceptable for a competition-scale prototype.
