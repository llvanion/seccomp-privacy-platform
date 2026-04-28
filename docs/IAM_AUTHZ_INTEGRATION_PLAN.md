# IAM And AuthZ Integration Plan

## Scope

This document defines the stage-1 identity and authorization integration plan for the control-plane sidecar.

Stage-1 goal:

1. Define how identity and authorization metadata should map onto existing pipeline concepts.
2. Prepare for future integration with Keycloak and OpenFGA.
3. Keep these integrations outside the core privacy-release semantics.

## Hard Boundaries

These rules are mandatory:

1. Keycloak is the identity layer only.
2. OpenFGA is the authorization layer only.
3. OPA is optional future work only.
4. None of these systems may change stage-1 privacy-release decisions.
5. None of these systems may become mandatory runtime dependencies for the main pipeline in stage 1.
6. Stage-1 work must not replace the existing meanings of `caller`, `tenant_id`, `dataset_id`, or `service_id`.

## Current State

The current pipeline already contains partial governance inputs:

1. `caller` is used in SSE export policy and policy release.
2. `record_recovery_service` can enforce allowed callers.
3. `policy_release.py` uses caller-aware audit and release evaluation.
4. Service/runtime identities are implicit in component choice rather than centrally managed.

This means stage-1 IAM/AuthZ work should standardize identity and mapping rules without changing execution semantics.

## Identity Model

### Keycloak Role In Stage 1

Keycloak is planned as the external identity provider for:

1. Human user login
2. Service account issuance
3. Realm-role assignment
4. Token claim delivery

Keycloak must not do the following in stage 1:

1. Decide whether a privacy result is released
2. Replace `policy_release.py`
3. Become required for local demo or main pipeline execution

### Required Field Mapping

Stage-1 mapping rules:

1. Human user maps to `caller`
2. Service account maps to service principals such as recovery, bridge, and policy components
3. Realm role maps to platform roles such as admin, auditor, and operator
4. Token claim maps to `tenant_id`
5. Client ID maps to `service_id`

Interpretation:

1. `caller` remains the business-facing request principal
2. `service_id` remains the platform service identity
3. `tenant_id` remains the tenancy boundary
4. `dataset_id` remains the governed data asset identifier

## Authorization Model

### OpenFGA Role In Stage 1

OpenFGA is planned as the fine-grained authorization system for:

1. Which users administer a tenant
2. Which users or service accounts can read a dataset
3. Which service accounts can run recovery or service operations
4. Which principals can view job metadata

OpenFGA must not do the following in stage 1:

1. Override `policy_release.py`
2. Replace result-threshold or rate-limit semantics
3. Become required for the main pipeline to run

### Stage-1 OpenFGA Model

```text
type user
type service_account
type tenant
  relations
    define admin: [user]
    define auditor: [user]
type dataset
  relations
    define owner: [tenant]
    define reader: [user, service_account]
    define recovery_allowed: [service_account]
type privacy_service
  relations
    define operator: [service_account]
    define can_recover: recovery_allowed from dataset
type job
  relations
    define owner: [user, service_account]
    define viewer: [user, service_account]
```

Meaning:

1. `tenant` is the authority boundary
2. `dataset` is the data asset boundary
3. `privacy_service` is the operational service boundary
4. `job` is the unit of audit and investigation visibility

## Control-Plane Table Mapping

The metadata DB prepares the following landing points:

1. `callers` table for `caller`
2. `tenants` table for `tenant_id`
3. `datasets` table for `dataset_id`
4. `services` table for `service_id`
5. `service_bindings`, `caller_permissions`, and `service_permissions` for future derived authorization materialization

Stage-1 note:

1. These tables are metadata only.
2. They do not yet enforce live online authorization for pipeline execution.

## OPA Position

OPA is explicitly future optional work.

Allowed future use:

1. Control-plane policy evaluation for read-only APIs
2. Externalized authorization checks for admin or audit views
3. Admission checks for future write-capable control-plane workflows

Forbidden stage-1 use:

1. Do not let OPA replace privacy-release semantics.
2. Do not let OPA change thresholding, rate limiting, or release decisions.
3. Do not make OPA required for stage-1 runtime.

## Stage-1 Integration Phases

### Phase 1

1. Persist `caller`, `tenant_id`, `dataset_id`, and `service_id` in metadata when known.
2. Keep missing values nullable or operator-supplied through importer override.
3. Document mapping rules only.

### Phase 2

1. Add Keycloak realm and client configuration for human and service identities.
2. Add OpenFGA store and authorization tuples for tenant, dataset, service, and job visibility.
3. Add read-only control-plane API authorization checks.

### Phase 3

1. Introduce optional OPA-based policy composition for control-plane APIs.
2. Keep privacy-release path independent unless explicitly redesigned through a separate change request.

## Optional Local Demo Guidance

These are optional local demo snippets only. They must remain non-invasive and must not become required runtime dependencies.

### Keycloak

1. One realm for local control-plane development
2. One human user group for admins and auditors
3. One service-account client each for recovery, bridge, and policy services
4. Token claim mapping that emits `tenant_id`

### OpenFGA

1. One local store
2. The stage-1 model above loaded as the authorization model
3. Demo tuples that bind users to tenants and datasets

These local demos should be used only to validate mapping design, not to gate stage-1 pipeline execution.

## Non-Goals

This plan does not do the following:

1. It does not introduce live write-capable control-plane APIs.
2. It does not change the current pipeline contract.
3. It does not replace the local `caller` semantics with a new naming system.
4. It does not require Keycloak or OpenFGA to run demos or imports.
