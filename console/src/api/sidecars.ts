import { api } from "./client";
import type {
  AuditChainData,
  AuditQueryApiResponse,
  BusinessAccessCheckReport,
  BusinessDataReadPreview,
  CatalogLineageData,
  Json,
  MetadataApiResponse,
  MetadataEntityResponse,
  MetadataJobsResponse,
  ObservabilityData,
  PlatformHealth,
  PublicReport,
  RecoveryHealth,
} from "./types";
import { unwrapAuditQueryResult, unwrapMetadataApiResult } from "./types";

// ---------- Metadata sidecar (default port 18090) ----------

export const metadataApi = {
  health(): Promise<Record<string, Json>> {
    return api.get("metadata", "/healthz");
  },
  async listJobs(query?: { caller?: string; tenant_id?: string; dataset_id?: string; service_id?: string; stage?: string; stage_status?: string; group_by?: string; limit?: number }): Promise<MetadataJobsResponse> {
    const payload = await api.get<MetadataApiResponse<MetadataJobsResponse> | MetadataJobsResponse>("metadata", "/v1/jobs", { query });
    return unwrapMetadataApiResult(payload);
  },
  async getJob(jobId: string): Promise<Record<string, Json>> {
    const payload = await api.get<MetadataApiResponse<Record<string, Json>> | Record<string, Json>>("metadata", `/v1/jobs/${encodeURIComponent(jobId)}`);
    return unwrapMetadataApiResult(payload);
  },
  async entities(entity: "tenants" | "datasets" | "services" | "callers" | "policies" | "policy-bindings" | "caller-permissions", query?: Record<string, string | number | boolean | null | undefined>): Promise<MetadataEntityResponse> {
    const payload = await api.get<MetadataApiResponse<MetadataEntityResponse> | MetadataEntityResponse>("metadata", `/v1/entities/${entity}`, { query });
    const result = unwrapMetadataApiResult(payload);
    if (!result.entries && result.items) {
      return { ...result, entries: result.items };
    }
    return result;
  },
  async businessAccessCheck(payload: Record<string, Json>): Promise<BusinessAccessCheckReport> {
    const result = await api.post<MetadataApiResponse<BusinessAccessCheckReport> | BusinessAccessCheckReport>("metadata", "/v1/business-access/check", payload);
    return unwrapMetadataApiResult(result);
  },
  async businessDataReadPreview(payload: Record<string, Json>): Promise<BusinessDataReadPreview> {
    const result = await api.post<MetadataApiResponse<BusinessDataReadPreview> | BusinessDataReadPreview>("metadata", "/v1/business-data/read-preview", payload);
    return unwrapMetadataApiResult(result);
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
  async publicReport(query?: { out_base?: string }): Promise<PublicReport> {
    const payload = await api.get<AuditQueryApiResponse<PublicReport> | PublicReport>("audit", "/v1/public-report", { query });
    return unwrapAuditQueryResult(payload);
  },
  async auditChain(query?: { out_base?: string; include_paths?: boolean }): Promise<AuditChainData> {
    const payload = await api.get<AuditQueryApiResponse<AuditChainData> | AuditChainData>("audit", "/v1/audit-chain", { query });
    return unwrapAuditQueryResult(payload);
  },
  async observability(query?: { out_base?: string }): Promise<ObservabilityData> {
    const payload = await api.get<AuditQueryApiResponse<ObservabilityData> | ObservabilityData>("audit", "/v1/observability", { query });
    return unwrapAuditQueryResult(payload);
  },
  async catalogLineage(query?: { out_base?: string; include_paths?: boolean }): Promise<CatalogLineageData> {
    const payload = await api.get<AuditQueryApiResponse<CatalogLineageData> | CatalogLineageData>("audit", "/v1/catalog-lineage", { query });
    return unwrapAuditQueryResult(payload);
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
