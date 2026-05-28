import { api } from "./client";
import type {
  CatalogLineage,
  Json,
  MetadataEntityResponse,
  MetadataJobsResponse,
  ObservabilityFeed,
  PlatformHealth,
  PublicReport,
  RecoveryHealth,
} from "./types";

// ---------- Metadata sidecar (default port 18090) ----------

export const metadataApi = {
  health(): Promise<Record<string, Json>> {
    return api.get("metadata", "/healthz");
  },
  listJobs(query?: { caller?: string; tenant_id?: string; dataset_id?: string; service_id?: string; stage?: string; stage_status?: string; group_by?: string; limit?: number }): Promise<MetadataJobsResponse> {
    return api.get("metadata", "/v1/jobs", { query });
  },
  getJob(jobId: string): Promise<MetadataJobsResponse["jobs"][number]> {
    return api.get("metadata", `/v1/jobs/${encodeURIComponent(jobId)}`);
  },
  entities(entity: "tenants" | "datasets" | "services" | "callers" | "policies" | "policy-bindings" | "caller-permissions", query?: Record<string, string | number | boolean | null | undefined>): Promise<MetadataEntityResponse> {
    return api.get("metadata", `/v1/entities/${entity}`, { query });
  },
};

// ---------- Query workflow sidecar (default port 18091) ----------

export const queryApi = {
  health(): Promise<Record<string, Json>> {
    return api.get("query", "/healthz");
  },
  dryRun(payload: Record<string, Json>, opts?: { baseDir?: string }): Promise<Record<string, Json>> {
    return api.post("query", "/v1/query-workflows/dry-run", payload, {
      headers: opts?.baseDir ? { "X-Request-Base-Dir": opts.baseDir } : undefined,
    });
  },
  execute(payload: Record<string, Json>, opts?: { baseDir?: string }): Promise<Record<string, Json>> {
    return api.post("query", "/v1/query-workflows/execute", payload, {
      headers: opts?.baseDir ? { "X-Request-Base-Dir": opts.baseDir } : undefined,
    });
  },
};

// ---------- Audit query sidecar (default port 18092) ----------

export const auditApi = {
  health(): Promise<Record<string, Json>> {
    return api.get("audit", "/healthz");
  },
  publicReport(query?: { out_base?: string }): Promise<PublicReport> {
    return api.get("audit", "/v1/public-report", { query });
  },
  auditChain(query?: { out_base?: string; include_paths?: boolean }): Promise<Record<string, Json>> {
    return api.get("audit", "/v1/audit-chain", { query });
  },
  observability(query?: { out_base?: string }): Promise<ObservabilityFeed> {
    return api.get("audit", "/v1/observability", { query });
  },
  catalogLineage(query?: { out_base?: string; include_paths?: boolean }): Promise<CatalogLineage> {
    return api.get("audit", "/v1/catalog-lineage", { query });
  },
};

// ---------- Platform health (default port 18093) ----------

export const healthApi = {
  health(): Promise<Record<string, Json>> {
    return api.get("health", "/healthz");
  },
  platformHealth(query?: { out_base?: string; metadata_db?: string }): Promise<PlatformHealth> {
    return api.get("health", "/v1/platform-health", { query });
  },
};

// ---------- Record recovery service ----------

export const recoveryApi = {
  health(): Promise<RecoveryHealth> {
    return api.get("recovery", "/healthz");
  },
  metrics(): Promise<string> {
    return api.get("recovery", "/metrics", { accept: "text" });
  },
};
