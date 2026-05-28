import { api } from "./client";
import type {
  Json,
  OperatorDashboardData,
  OperatorJob,
  PjcRunOnlyRequest,
  PjcRunOnlyResponse,
  RequestSubmission,
  SseSearchRequest,
  SseSearchResponse,
} from "./types";

export const operatorApi = {
  dashboard(opts?: { signal?: AbortSignal }): Promise<OperatorDashboardData> {
    return api.get<OperatorDashboardData>("operator", "/v1/dashboard", { signal: opts?.signal });
  },

  listRuns(): Promise<{ runs: Array<Record<string, Json>>; history_root: string }> {
    return api.get("operator", "/v1/runs");
  },

  selectRun(payload: { out_base: string }): Promise<OperatorDashboardData> {
    return api.post("operator", "/v1/runs/select", payload);
  },

  getJob(jobId: string): Promise<OperatorJob> {
    return api.get("operator", `/v1/jobs/${encodeURIComponent(jobId)}`);
  },

  getJobResult(jobId: string): Promise<Record<string, Json>> {
    return api.get("operator", `/v1/jobs/${encodeURIComponent(jobId)}/result`);
  },

  startJob(payload: Record<string, Json>): Promise<{ job_id: string }> {
    return api.post("operator", "/v1/jobs/start", payload);
  },

  relaunchJob(jobId: string, payload: Record<string, Json>): Promise<{ job_id: string }> {
    return api.post("operator", `/v1/jobs/${encodeURIComponent(jobId)}/relaunch`, payload);
  },

  listRequests(query?: { status?: string; caller?: string; tenant_id?: string; limit?: number }): Promise<{ submissions: RequestSubmission[] }> {
    return api.get("operator", "/v1/requests", { query });
  },

  getRequest(submissionId: string): Promise<RequestSubmission> {
    return api.get("operator", `/v1/requests/${encodeURIComponent(submissionId)}`);
  },

  submitRequest(payload: Record<string, Json>): Promise<RequestSubmission> {
    return api.post("operator", "/v1/request/submit", payload);
  },

  approveRequest(submissionId: string, payload: Record<string, Json>): Promise<RequestSubmission> {
    return api.post("operator", `/v1/request/${encodeURIComponent(submissionId)}/approve`, payload);
  },

  rejectRequest(submissionId: string, payload: Record<string, Json>): Promise<RequestSubmission> {
    return api.post("operator", `/v1/request/${encodeURIComponent(submissionId)}/reject`, payload);
  },

  bucketedScaleTestList(): Promise<Record<string, Json>> {
    return api.get("operator", "/v1/bucketed-scale-test");
  },

  bucketedScaleTestRun(payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", "/v1/bucketed-scale-test/run", payload);
  },

  pjcRoleStatus(role: string): Promise<Record<string, Json>> {
    return api.get("operator", `/v1/pjc/roles/${encodeURIComponent(role)}/status`);
  },

  pjcRoleStart(role: string, payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", `/v1/pjc/roles/${encodeURIComponent(role)}/start`, payload);
  },

  pjcRoleCancel(role: string, payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", `/v1/pjc/roles/${encodeURIComponent(role)}/cancel`, payload);
  },

  mtlsPartyAPrepare(payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", "/v1/pjc-mtls/party-a/prepare", payload);
  },

  mtlsEnroll(payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", "/v1/pjc-mtls/enroll", payload);
  },

  mtlsPartyBEnroll(payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", "/v1/pjc-mtls/party-b/enroll", payload);
  },

  mtlsPreflight(payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", "/v1/pjc-mtls/preflight", payload);
  },

  mtlsTlsDiagnostic(payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", "/v1/pjc-mtls/tls-diagnostic", payload);
  },

  mtlsNegativeCases(payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", "/v1/pjc-mtls/negative-cases/run", payload);
  },

  releasePolicyGate(payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", "/v1/release/policy-gate", payload);
  },

  pjcEvidenceVerifyMerge(payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", "/v1/pjc/evidence/verify-merge", payload);
  },

  pjcRolePackageExport(payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", "/v1/pjc/role-package/export", payload);
  },

  pjcRolePackageImport(payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", "/v1/pjc/role-package/import", payload);
  },

  sseSearch(payload: SseSearchRequest): Promise<SseSearchResponse> {
    return api.post("operator", "/v1/sse/search", payload as unknown as Record<string, Json>);
  },

  pjcRunOnly(payload: PjcRunOnlyRequest): Promise<PjcRunOnlyResponse> {
    return api.post("operator", "/v1/pjc/run-only", payload as unknown as Record<string, Json>);
  },
};
