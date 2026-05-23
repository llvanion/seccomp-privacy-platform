# TTL, Key Rotation, and Negative-Case Policy

## TTL

| Asset | Default TTL | Refresh window | Notes |
| --- | --- | --- | --- |
| Workload SVID (X.509) | 1h | every 30 min | Set via `default_x509_svid_ttl = "1h"` in `spire_server.conf`. |
| Workload SVID (JWT) | 5 min | per request | JWT SVIDs are never used for transport; only for short-lived attestation calls. |
| SPIRE CA | 7d | weekly | `ca_ttl = "168h"`. The bundle is rotated automatically by SPIRE. |
| Trust bundle distribution | continuous | every 30s | Envoy receives bundle updates over SDS; cached for 30s with watch. |

## Rotation discipline

1. SVIDs rotate inside the 30-minute refresh window so any compromised key
   becomes useless within an hour.
2. Trust bundle changes are auto-deployed by SPIRE Server's `Notifier
   "k8sbundle"`; Envoys reload via SDS without bouncing the data plane.
3. CA rotation is triggered only via the change-management process documented
   in `docs/CONTROL_PLANE_HARDENING_LOG.md`. Operator approval is required.

## Negative-case enforcement

The negative-case runner (`POST /v1/pjc-mtls/negative-cases/run`, see
`scripts/check_pjc_two_party_smoke.py`) must remain passing **also** with the
SPIFFE/SPIRE deployment. Mapping:

| Negative case (CSR fallback) | SPIFFE/SPIRE equivalent |
| --- | --- |
| `wrong_token` | Workload presents an SVID for a non-allowlisted SPIFFE ID. Envoy's RBAC denies before any payload bytes flow. |
| `expired_token` | Expired SVID; SPIRE refuses to mint and Envoy refuses to forward. |
| `wrong_ca` | Different trust bundle generation; Envoy's SDS validation context rejects. |
| `wrong_peer` | Configured `match_typed_subject_alt_names` rejects an unexpected URI SAN. |
| `closed_port` | Same — TCP refusal on the data-plane port. |
| `commit_mismatch` | Preflight gate compares `git rev-parse HEAD` on both sides. |
| `modified_csv` | Preflight gate compares input CSV SHA-256 against the manifest. |
| `privacy_denial` | Server-side policy gate fails the release (see `scripts/run_s3_privacy_budget_evidence.sh` and the `--require-dp` chain). |

## Audit storage

Every Envoy handshake emits an access log line with `peer_spiffe_id`,
`svid_sha256`, `trust_bundle_generation`, and `negotiated_cipher`. These lines
must be tailed into the PJC audit pipeline (`scripts/build_audit_chain.py`)
within 60 seconds of the handshake, otherwise the release gate fails closed.
