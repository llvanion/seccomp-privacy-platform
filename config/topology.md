# Production Deployment Topology (J1)

This document defines the canonical deployment topology for a single-region
production install of the seccomp-privacy-platform. It exists so on-call can
reason about which components are stateless, which carry state, where TLS
boundaries live, and which port speaks which protocol.

The topology is intentionally adapter-first. The privacy main chain
(`SSE export → record recovery → bridge → PJC → policy release`) keeps its
existing behaviour even when several of these components are scaled out or
moved across zones. None of the frozen contract fields change.

```
                                ┌───────────────────────────┐
                                │   Load Balancer (L4)      │
                                │   HAProxy / AWS NLB       │
                                └─────────────┬─────────────┘
                                              │ :443 (mTLS, SNI=recovery-service.<tenant>)
                              ┌───────────────┴────────────────┐
                              │                                │
                  ┌───────────▼───────────┐         ┌──────────▼────────────┐
                  │ recovery-service-A    │         │ recovery-service-B    │
                  │ Deployment (≥2 pods)  │   …     │ Deployment (≥2 pods)  │
                  │  - mTLS :18443        │         │  - mTLS :18443        │
                  │  - /metrics :18443    │         │  - /metrics :18443    │
                  │  - /healthz :18443    │         │  - /healthz :18443    │
                  └───────────┬───────────┘         └──────────┬────────────┘
                              │                                │
                              │ psycopg2 (TLS)                 │ psycopg2 (TLS)
                              └────────────────┬───────────────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │   pgBouncer :6432   │  (F3, planned)
                                    │  pool_mode=transact │
                                    └──────────┬──────────┘
                                               │
                                ┌──────────────┴──────────────┐
                                │                             │
                       ┌────────▼─────────┐         ┌─────────▼─────────┐
                       │ pg-primary :5432 │ stream  │ pg-replica :5432  │
                       │ (Patroni leader) │────────►│ (Patroni standby) │
                       │ writes only      │         │ reads via         │
                       │                  │         │ --db-dsn-read-    │
                       │                  │         │ replica           │
                       └──────────────────┘         └───────────────────┘

         ─── identity / authority sidecars ─────────────────────────────
         metadata API   :18090   read-only sidecar over PostgreSQL
         query API      :18091   query-workflow dry-run / execute
         audit API      :18092   completed-run audit/public-report read
         platform-health:18093   platform health probes
         operator dash  :18094   operator dashboard + job launcher
         identity proxy :18095   bearer-token verification adapter
         key-agent      Unix     local key-resolver, no public port
         external-KMS   :var     Vault HTTP / cloud-KMS adapter
         OpenFGA        :8080    optional live ReBAC backend
         Keycloak       :8080    optional OIDC issuer
         Vault          :8200    optional secret backend
         Prometheus     :9090    pulls /metrics (J3-a)
         Grafana/Tempo  :3000    pulls observability spans (I1, planned)
```

## Component classification

| Component | Stateless? | Scaling guidance | TLS boundary |
| --- | --- | --- | --- |
| recovery-service | yes | `replicas ≥ 2`, HPA on CPU; per-tenant `Deployment` so per-tenant `NetworkPolicy` (H1-b) and rate-limit buckets (H2-a) stay scoped | mTLS on the public port; client cert required |
| metadata-API | yes (read) | `replicas ≥ 2` behind the cluster service; read DSN routed to the Patroni replica via `--db-dsn-read-replica` (F2-c) | bearer token (identity proxy) |
| query-workflow API | yes orchestration | single `replicas: 1` per region; durable state lives in the metadata DB and the run output base | bearer token + identity proxy |
| audit-query API | yes (read) | `replicas ≥ 2`; reads completed-run files + identity DSN replica | bearer token |
| platform-health API | yes (read) | `replicas ≥ 2`; aggregates probes from sidecars | bearer token |
| operator dashboard | yes (write/launch) | single `replicas: 1` per region; uses tenant-quota lock (H2-b) | bearer token + identity proxy |
| identity proxy | yes | `replicas ≥ 2`; verifies OIDC tokens from Keycloak and injects `X-Identity-*` headers | bearer token in, bearer token out |
| key-agent / external-KMS adapter | yes (resolver) | one per recovery-service pod or a regional shared deployment | local Unix socket / mTLS to Vault |
| **PostgreSQL primary** | **stateful** | exactly one writer; Patroni-managed (F2-b) | TLS to clients, replication slot to replica |
| **PostgreSQL replica** | stateful (replica) | one or more streaming replicas; targeted for SELECTs via the read-DSN flag | TLS to clients, no writes |
| pgBouncer (F3, planned) | stateless pool | `replicas ≥ 2`; transaction-mode in front of primary, optional separate pool for replica | none extra; sits inside the cluster network |
| OpenFGA / Keycloak / Vault | external authority sources | operator-managed; the platform is adapter-first and never makes them runtime-required for the main chain | TLS to clients |

Stateful components (PostgreSQL primary, Patroni cluster) own all durable state.
Every other component can be drained, restarted, or rescheduled freely as long
as the load balancer health checks (`GET /healthz` → 200) drive the
new-pod / removed-pod cycle. The metadata sidecar follows the same rule on the
read path: replicas can come and go without re-running migrations because
F2-c routes SELECTs to a replica DSN that is assumed to mirror the primary.

## Port assignments

| Port  | Protocol | Component | Auth | Notes |
| ----: | --- | --- | --- | --- |
|   443 | TCP/HTTPS | recovery-service `Service` | mTLS | external traffic via load balancer; SNI per tenant |
| 18443 | TCP/HTTPS | recovery-service `containerPort` | mTLS | also serves `/metrics` (J3-a) and `/healthz` |
|  6432 | TCP | pgBouncer (F3, planned) | password | pool in front of pg-primary; pg-replica sits behind a separate pool when read-replica routing is enabled |
|  5432 | TCP | PostgreSQL primary / replica | scram-sha-256 + TLS | only reachable inside the cluster network |
| 18090 | TCP/HTTP | metadata API | bearer | sidecar read-only |
| 18091 | TCP/HTTP | query-workflow API | bearer + identity proxy | dry-run open to `query_submitter`, execute to `privacy_operator` |
| 18092 | TCP/HTTP | audit-query API | bearer | `include_paths=true` requires platform-admin / auditor |
| 18093 | TCP/HTTP | platform-health API | bearer | privileged roles see full report; service-operator sees scoped record-recovery state |
| 18094 | TCP/HTTP | operator dashboard | bearer + identity proxy | per-tenant job quota enforced under a single lock |
| 18095 | TCP/HTTP | identity proxy | bearer (in) | issues `X-Identity-*` headers downstream |
|  8200 | TCP/HTTPS | Vault (operator) | token / approle | optional secret backend |
|  8080 | TCP/HTTPS | Keycloak / OpenFGA (operator) | token | optional authority sources |
|  9090 | TCP/HTTP | Prometheus scrape | scrape | pulls `/metrics` from recovery-service pods |
|  3000 | TCP/HTTP | Grafana (operator, planned) | OIDC | dashboards live on the operator side |

## Authentication boundaries

The platform has two authentication primitives:

1. **mTLS** — recovery-service public port. Both server and client present
   X.509 certificates. The expected operator workflow uses Vault PKI
   (`scripts/issue_mtls_certs.py`) to issue short-lived certificates.
2. **Bearer token + identity proxy** — every other HTTP API. The identity
   proxy (`scripts/serve_identity_proxy.py`) verifies the token (static map
   or live Keycloak/OIDC) and injects `X-Identity-Caller`,
   `X-Identity-Tenant-Id`, `X-Identity-Service-Id`, and
   `X-Identity-Platform-Roles` headers downstream. Sidecars trust those
   headers when the request arrives over the cluster network.

PostgreSQL traffic uses `scram-sha-256` plus TLS on the wire. App credentials
live in Vault; recovery-service pods load them via the operator-managed
`recovery-service-config` and `recovery-service-tls` Kubernetes Secrets, both
mounted read-only into the pod (see `config/k8s/recovery-service-deployment-*.yaml`).

## Scaling policies

The recovery-service `Deployment` is the only path that takes external traffic
in production. It scales horizontally:

- `replicas: 2` minimum (matches `--min-replicas` in `render_recovery_service_k8s.py`).
- `HorizontalPodAutoscaler` targets `70%` average CPU utilisation.
- `maxReplicas: 6` keeps a single tenant from monopolising the worker pool;
  raise this only after re-tuning the per-caller token bucket
  (`--rate-limit-per-caller`, H2-a).
- All other sidecar APIs run at `replicas ≥ 2` for redundancy but do not
  auto-scale; their load is metadata-driven and stays roughly constant.

The single-writer components (operator dashboard, query-workflow API) run at
`replicas: 1` per region, with the per-tenant job quota in the dashboard
serialising launches under a single lock (H2-b).

## Health checks

- Load-balancer health: `GET /healthz` → 200 over the recovery-service
  mTLS port. The pod's `readinessProbe` and `livenessProbe` use the same
  endpoint.
- Pod-level health for the sidecar APIs: each emits its own
  `*_api_health/v1` envelope at `GET /healthz`.
- Cluster-wide health: `scripts/check_platform_health.py` aggregates the
  individual sidecar probes and emits `platform_health/v1`.

## Generating manifests

The Kubernetes manifests under `config/k8s/recovery-service-*.yaml` are
operator-friendly defaults committed for inspection. To regenerate with
different scaling or naming parameters, use:

```bash
python3 scripts/render_recovery_service_k8s.py \
  --tenant-id demo-tenant \
  --namespace seccomp-privacy \
  --replicas 2 \
  --min-replicas 2 \
  --max-replicas 6 \
  --target-cpu-utilization 70 \
  --container-port 18443 \
  --service-port 443 \
  --image ghcr.io/seccomp-privacy/recovery-service:0.1.0 \
  --out-dir tmp/k8s \
  --output tmp/k8s_recovery_service_topology_report.json \
  --kubectl-dry-run \
  --assert-ok
```

The renderer emits a structurally-validated `Deployment`, `Service`, and
`HorizontalPodAutoscaler`, and produces a `k8s_recovery_service_topology_report/v1`
report. With `--kubectl-dry-run` it additionally feeds each manifest through
`kubectl apply --dry-run=client` (when `kubectl` is available locally).

For tenant-scoped network isolation, pair the manifests with the H1-b
`scripts/render_k8s_network_policies.py` output so each tenant's recovery-service
pods only accept ingress from their own pipeline pods.
