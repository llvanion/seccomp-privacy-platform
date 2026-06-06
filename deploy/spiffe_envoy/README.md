# SPIFFE/SPIRE + Envoy Production Templates for PJC mTLS

This directory contains the **target** maximum-security deployment templates for
two-party PJC mTLS. The CSR-based `pjc-mtls://enroll` flow remains the
controlled fallback for laptops, demos, and CI; production cross-organisation
deployments should run a SPIFFE/SPIRE trust domain with Envoy sidecars in
front of the PJC binary.

The templates are **structural references** that ship with the repo. They are
linted by `scripts/check_spiffe_envoy_templates.py` so future refactors cannot
silently drop the required fields, but they are *not* a one-click deploy — a
production rollout still needs a real Kubernetes cluster (or systemd hosts), a
real CA, and operator-side rotation hooks.

## Files

| File | Purpose |
| --- | --- |
| `spire_server.conf` | SPIRE Server HCL with PJC trust domain, K8s/SAT node attestor, and short-lived SVIDs. |
| `spire_agent.conf` | SPIRE Agent HCL pinning the server bundle and the K8s workload attestor. |
| `envoy_party_a.yaml` | Party A (server) Envoy listener on the public TLS port, mTLS to loopback PJC. |
| `envoy_party_b.yaml` | Party B (client) Envoy outbound cluster mTLS to Party A's listener. |
| `peer_spiffe_allowlist.json` | Mutual SPIFFE ID allowlist consumed by both Envoys (and by the dashboard verifier). |
| `rotation_notes.md` | TTL, key rotation, and audit storage notes that the templates encode. |

## Trust model

1. Each party runs its own SPIRE Server inside its trust domain.
   Cross-organisation trust comes from federation, not a shared CA private key.
2. Workloads (`pjc-server`, `pjc-client`) receive 60-minute SVIDs that rotate
   automatically. PJC binaries never see private keys — Envoy terminates TLS.
3. PJC stays bound to loopback. Envoy is the only listener on the data-plane
   port, and it requires a matching peer SPIFFE ID before forwarding bytes.
4. The peer SPIFFE allowlist is committed to git and signed; any deviation
   between Envoy's deployed config and `peer_spiffe_allowlist.json` is a
   release-blocker.
5. Audit: Envoy access logs are shipped to the PJC audit pipeline. Every TLS
   handshake records peer SPIFFE ID, SVID hash, trust bundle generation, and
   the negotiated cipher.

## Local verification

```
python3 scripts/check_spiffe_envoy_templates.py \
  --templates-dir deploy/spiffe_envoy \
  --output tmp/spiffe_envoy_template_check.json
```

That command runs without a cluster: it checks every template file for the
required keys and prints a typed `spiffe_envoy_template_check/v1` report that
is wired into `scripts/check_json_contracts.sh`.

## Production migration path

1. Stand up a SPIRE Server using `spire_server.conf` as the base.
2. Register the two workload entries (`spiffe://example.org/pjc-server`,
   `spiffe://example.org/pjc-client`) with the matching K8s/SAT selectors.
3. Deploy SPIRE Agents per host using `spire_agent.conf`.
4. Wrap each PJC binary with the matching Envoy config; PJC stays loopback.
5. Replace any remaining `pjc-mtls://enroll` invocations with SPIFFE workload
   API discovery. The dashboard wizard still drives the higher-level steps
   (preflight, evidence merge, negative cases) — the only thing that changes
   is the identity provider.

## Live Evidence Archiving

When a real SPIFFE/SPIRE + Envoy deployment exists, freeze the operator-side
evidence into one verifier-facing package instead of passing loose JSON/log
paths around:

```bash
python3 scripts/archive_spiffe_envoy_live_evidence.py \
  --job-id spiffe-envoy-live-001 \
  --templates-dir deploy/spiffe_envoy \
  --live-positive-report /path/to/positive_run.json \
  --live-wrong-peer-report /path/to/wrong_peer_reject.json \
  --live-expired-svid-report /path/to/expired_svid_reject.json \
  --live-trust-bundle-reject-report /path/to/trust_bundle_reject.json \
  --live-envoy-access-log /path/to/envoy_access.log \
  --output-dir tmp/spiffe_envoy_live_archive_live_001
```

That archive can then be consumed by:

```bash
python3 scripts/check_spiffe_envoy_identity_gate.py \
  --out-dir tmp/spiffe_envoy_identity_gate_live_001 \
  --live-evidence-archive tmp/spiffe_envoy_live_archive_live_001/spiffe_envoy_live_evidence_archive.json
```

The gate intentionally keeps `live_status=skipped` when the archive exists but
contains no real deployment artifacts, so a structurally valid empty bundle
cannot be mistaken for production completion.
