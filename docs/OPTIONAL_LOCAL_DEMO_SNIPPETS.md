# Optional Local Demo Snippets

## Scope

This document provides optional local demo snippets for:

1. Keycloak
2. OpenFGA
3. Vault

These snippets exist only to validate the stage-1 design documents in a local environment.

## Hard Boundaries

These snippets are optional and non-invasive.

They must not be interpreted as:

1. required runtime dependencies for stage 1
2. replacements for the existing pipeline contract
3. proof that the main pipeline should now depend on Keycloak, OpenFGA, or Vault
4. approval to change `bridge` contract or `policy_release.py` semantics

## Files

1. [optional_local_control_plane_demo.compose.yaml](optional_local_control_plane_demo.compose.yaml)
2. [optional_openfga_model.fga](optional_openfga_model.fga)
3. [optional_openfga_tuples.json](optional_openfga_tuples.json)

## Intended Use

These snippets support local design validation only:

1. Validate Keycloak realm/client mapping ideas for `caller`, `tenant_id`, and `service_id`
2. Validate the stage-1 OpenFGA authorization model
3. Validate the idea of resolving a secret from Vault and exporting it into the env vars expected by the current pipeline

## Keycloak Demo Notes

Keycloak is used here only as a local identity provider example.

Suggested mapping:

1. Human user principal maps to `caller`
2. Client or service account maps to `service_id`
3. Token custom claim maps to `tenant_id`
4. Realm roles map to `admin`, `auditor`, and `operator`

Important boundary:

1. Keycloak does not decide whether privacy results are released
2. Keycloak does not replace `policy_release.py`

## OpenFGA Demo Notes

The demo model mirrors the stage-1 fine-grained authorization design:

1. `user`
2. `service_account`
3. `tenant`
4. `dataset`
5. `privacy_service`
6. `job`

The tuple seed file demonstrates:

1. tenant admins
2. dataset readers
3. recovery-allowed service accounts
4. job viewers

Important boundary:

1. This is metadata authorization only
2. It does not change stage-1 privacy-release semantics

## Vault Demo Notes

Vault is used here only as a local secret-source example.

Suggested usage:

1. Store a bridge token secret in Vault
2. Read it through a wrapper or shell step
3. Export it into `BRIDGE_TOKEN_SECRET`
4. Run the existing pipeline unchanged

Important boundary:

1. Vault does not change current bridge call parameters
2. Vault does not replace the current key-access audit model

## Suggested Validation Flow

1. Start the optional compose services
2. Load the OpenFGA model and tuples
3. Create a Keycloak realm, roles, and demo clients
4. Store a demo secret in Vault
5. Keep using the current pipeline entrypoints unchanged

Example principle:

1. The secret backend may change
2. The current pipeline CLI contract must not change

## Non-Goals

These snippets do not provide:

1. production deployment manifests
2. mandatory auth enforcement
3. write-capable control-plane APIs
4. runtime integration into the main pipeline
