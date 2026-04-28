# KMS And Secret Backend Plan

## Scope

This document defines the stage-1 plan for moving from local/mock secret sourcing toward Vault or an external KMS-backed secret backend.

Stage-1 goal:

1. Clarify the secret-management boundary.
2. Keep current runtime contracts stable.
3. Prepare an adapter model for Vault or external KMS without changing pipeline semantics.

## Hard Boundaries

These constraints are mandatory:

1. Vault or external KMS is secret sourcing only in stage 1.
2. Existing bridge call parameters must not change.
3. Existing `--token-secret-env` style usage must remain valid.
4. The main pipeline must not require Vault or any external KMS in stage 1.
5. Stage-1 work must not replace the current key-access audit semantics.

## Current Secret Model

Current pipeline behavior already uses:

1. Env-var sourced bridge token secret
2. Local key manifest plus env-var reference for key lookup
3. Encrypted record-store passphrases via env vars
4. Optional auth token env vars for record recovery service

This is acceptable for stage 1 because the goal is to formalize secret sourcing without changing the execution contract.

## Stage-1 Secret Sourcing Model

The recommended stage-1 abstraction is:

1. Control plane or deployment layer obtains the secret from Vault or external KMS.
2. That layer injects the secret into an env var or in-memory channel.
3. Existing pipeline binaries and scripts continue to read the secret through their current interface.

This preserves compatibility with:

1. `bridge --token-secret-env ...`
2. current local manifest flow
3. current encrypted record-store CLI options

## Vault Role In Stage 1

Vault may be used for:

1. storing the bridge token secret
2. storing record-store passphrases
3. storing policy-auth secrets
4. storing audit-integrity secrets

Vault must not do the following in stage 1:

1. change bridge CLI argument shape
2. become a mandatory runtime dependency for local demos
3. change key purpose meanings
4. replace key-access audit with a different event model

## Adapter Pattern

Recommended adapter pattern:

1. Resolve secret from Vault or external KMS by key reference.
2. Export secret into the expected env var just before invoking the current component.
3. Keep the secret out of command-line argument values whenever possible.
4. Preserve existing audit references to key ID, version, and source kind.

Examples:

1. Resolve bridge token secret into `BRIDGE_TOKEN_SECRET`
2. Resolve SSE record-store passphrase into `SSE_RECORD_STORE_PASSPHRASE`
3. Resolve recovery-service auth token into `SSE_RECORD_RECOVERY_TOKEN`

## Key Registry Mapping

The sidecar schema prepares for future key registry and lifecycle tracking:

1. `key_refs`
2. `key_versions`
3. `key_purposes`
4. `key_rotation_events`
5. `key_access_events`

Meaning:

1. `key_refs` identifies a logical key and backend reference
2. `key_versions` tracks versioned material identity
3. `key_purposes` constrains intended usage such as `bridge_token` or `policy_auth`
4. `key_rotation_events` tracks future controlled rotation
5. `key_access_events` preserves observed usage from current audit output

## Stage-1 Secret Backends

Supported stage-1 position:

1. Local env vars remain valid
2. Local manifest remains valid
3. Vault is optional
4. External KMS is optional

Forbidden stage-1 position:

1. Do not require Vault for every run
2. Do not require network secret lookup during every local demo
3. Do not change bridge input contract to pass key handles instead of env-var secrets

## Optional Local Demo Guidance

These demo ideas are optional only and must remain non-invasive.

### Vault Demo

1. Run a local dev Vault instance
2. Store a demo bridge token secret under a known path
3. Use a thin wrapper script to fetch the secret and export `BRIDGE_TOKEN_SECRET`
4. Invoke the existing pipeline without modifying bridge CLI contract

The wrapper is allowed to change deployment procedure, but not the bridge interface itself.

## Future External KMS Pattern

Stage-2 or later can introduce:

1. key-reference lookup in control-plane services
2. secret resolution adapters per environment
3. rotation workflows that update `key_versions`
4. audit correlation between key resolution and job execution

That later work still must go through existing component contracts unless a separate change request explicitly approves interface changes.

## Non-Goals

This plan does not do the following:

1. It does not replace current mock KMS flow in a way that changes bridge call parameters.
2. It does not change result-governance semantics.
3. It does not require Vault to be installed for stage-1 usage.
4. It does not bypass the existing key-access audit path.
