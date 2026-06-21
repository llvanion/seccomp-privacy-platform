import { api } from "./client";
import type {
  Json,
  OperatorAlert,
  OperatorDashboardData,
  OperatorDashboardFullData,
  OperatorConsoleSession,
  OperatorJob,
  PjcRunOnlyRequest,
  PjcRunOnlyResponse,
  PrivacyBudgetApprovalList,
  PrivacyBudgetApprovalTransition,
  RequestSubmission,
  SseSearchRequest,
  SseSearchResponse,
} from "./types";

function normalizeOperatorJob(raw: Record<string, Json>): OperatorJob {
  return {
    ...(raw as unknown as OperatorJob),
    status: typeof raw.status === "string" ? raw.status : typeof raw.state === "string" ? raw.state : undefined,
    terminal_state:
      typeof raw.terminal_state === "string"
        ? raw.terminal_state
        : typeof raw.state === "string" && raw.terminal === true
          ? raw.state
          : undefined,
    elapsed_seconds:
      typeof raw.elapsed_seconds === "number"
        ? raw.elapsed_seconds
        : typeof raw.elapsed_sec === "number"
          ? raw.elapsed_sec
          : null,
    exit_code: typeof raw.exit_code === "number" ? raw.exit_code : null,
    stages: Array.isArray(raw.stages)
      ? raw.stages
          .filter((stage): stage is Record<string, Json> => typeof stage === "object" && stage !== null)
          .map((stage) => ({
            stage: typeof stage.stage === "string" ? stage.stage : typeof stage.name === "string" ? stage.name : "stage",
            status: typeof stage.status === "string" ? stage.status : undefined,
            duration_ms: typeof stage.duration_ms === "number" ? stage.duration_ms : null,
            started_at_utc: typeof stage.started_at_utc === "string" ? stage.started_at_utc : null,
            finished_at_utc: typeof stage.finished_at_utc === "string" ? stage.finished_at_utc : null,
          }))
      : undefined,
  };
}

function normalizeOperatorAlert(raw: Record<string, Json>): OperatorAlert {
  const firing = raw.firing === true;
  const state = typeof raw.state === "string" ? raw.state : firing ? "firing" : "resolved";
  return {
    ...(raw as unknown as OperatorAlert),
    id:
      typeof raw.id === "string"
        ? raw.id
        : typeof raw.alert_id === "string"
          ? raw.alert_id
          : typeof raw.name === "string"
            ? raw.name
            : undefined,
    title:
      typeof raw.title === "string"
        ? raw.title
        : typeof raw.name === "string"
          ? raw.name
          : typeof raw.alert_id === "string"
            ? raw.alert_id
            : undefined,
    summary:
      typeof raw.summary === "string"
        ? raw.summary
        : typeof raw.message === "string"
          ? raw.message
          : undefined,
    state,
    firing,
  };
}

function normalizeDashboard(data: OperatorDashboardData): OperatorDashboardData {
  if (typeof data !== "object" || data === null) {
    return data;
  }
  if ("schema" in data && data.schema === "operator_dashboard_public_summary/v1") {
    return data;
  }
  if (!("history_root" in data)) {
    return data;
  }

  const full: OperatorDashboardFullData = { ...data };
  const recentRuns = Array.isArray(full.recent_runs)
    ? full.recent_runs
    : full.recent_runs && Array.isArray(full.recent_runs.statuses)
      ? full.recent_runs.statuses
      : [];
  const currentJob =
    typeof full.job_control === "object" && full.job_control !== null
      ? normalizeOperatorJob(full.job_control as unknown as Record<string, Json>)
      : null;
  const jobs = Array.isArray(full.jobs) ? full.jobs : [];
  const normalizedCurrentJob = currentJob && currentJob.job_id ? currentJob : null;
  const mergedJobs = normalizedCurrentJob
    ? [normalizedCurrentJob, ...recentRuns.map((job: OperatorJob) => normalizeOperatorJob(job as unknown as Record<string, Json>)).filter((job: OperatorJob) => job.job_id !== normalizedCurrentJob.job_id)]
    : recentRuns.map((job: OperatorJob) => normalizeOperatorJob(job as unknown as Record<string, Json>));
  const normalizedJobs = jobs.length > 0
    ? jobs.map((job: OperatorJob) => normalizeOperatorJob(job as unknown as Record<string, Json>))
    : mergedJobs;
  const alertRows = Array.isArray(full.alerts)
    ? full.alerts
    : full.alerts && Array.isArray(full.alerts.alerts)
      ? full.alerts.alerts
      : [];

  return {
    ...full,
    jobs: normalizedJobs,
    recent_runs: mergedJobs,
    alerts: alertRows.map((alert: OperatorAlert) => normalizeOperatorAlert(alert as unknown as Record<string, Json>)),
  };
}

export const operatorApi = {
  sessionStatus(opts?: { signal?: AbortSignal }): Promise<OperatorConsoleSession> {
    return api.get<OperatorConsoleSession>("operator", "/v1/session", { signal: opts?.signal });
  },

  sessionLogin(payload: { bearer_token: string; max_age_seconds?: number }): Promise<OperatorConsoleSession> {
    return api.post("operator", "/v1/session/login", payload);
  },

  sessionLogout(): Promise<OperatorConsoleSession> {
    return api.post("operator", "/v1/session/logout", {});
  },

  dashboard(opts?: { signal?: AbortSignal }): Promise<OperatorDashboardData> {
    return api.get<OperatorDashboardData>("operator", "/v1/dashboard", { signal: opts?.signal }).then(normalizeDashboard);
  },

  listRuns(): Promise<{ runs: Array<Record<string, Json>>; history_root: string }> {
    return api.get("operator", "/v1/runs");
  },

  listRunsRaw(query?: { state?: string; job_id?: string; limit?: number }): Promise<Record<string, Json>> {
    return api.get("operator", "/v1/runs", { query });
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

  listPrivacyBudgetApprovals(query?: { status?: string; caller?: string; tenant_id?: string; limit?: number }): Promise<PrivacyBudgetApprovalList> {
    return api.get("operator", "/v1/privacy-budget/approvals", { query });
  },

  approvePrivacyBudgetApproval(requestId: string, payload: Record<string, Json>): Promise<PrivacyBudgetApprovalTransition> {
    return api.post("operator", `/v1/privacy-budget/approval/${encodeURIComponent(requestId)}/approve`, payload);
  },

  rejectPrivacyBudgetApproval(requestId: string, payload: Record<string, Json>): Promise<PrivacyBudgetApprovalTransition> {
    return api.post("operator", `/v1/privacy-budget/approval/${encodeURIComponent(requestId)}/reject`, payload);
  },

  expirePrivacyBudgetApproval(requestId: string, payload: Record<string, Json>): Promise<PrivacyBudgetApprovalTransition> {
    return api.post("operator", `/v1/privacy-budget/approval/${encodeURIComponent(requestId)}/expire`, payload);
  },

  bucketedScaleTestList(): Promise<Record<string, Json>> {
    return api.get("operator", "/v1/bucketed-scale-test");
  },

  bucketedScaleTestRun(payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", "/v1/bucketed-scale-test/run", payload);
  },

  pjcRoleStatus(role: string, jobId: string): Promise<Record<string, Json>> {
    return api.get("operator", `/v1/pjc/roles/${encodeURIComponent(role)}/status`, {
      query: { job_id: jobId },
    });
  },

  pjcRoleStart(role: string, payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", `/v1/pjc/roles/${encodeURIComponent(role)}/start`, payload);
  },

  pjcRoleCancel(role: string, payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", `/v1/pjc/roles/${encodeURIComponent(role)}/cancel`, payload);
  },

  pjcRunManifestSign(payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", "/v1/pjc/run-manifest/sign", payload);
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

  pjcTwoPartyResultSummary(payload: Record<string, Json>): Promise<Record<string, Json>> {
    return api.post("operator", "/v1/pjc/two-party/result-summary", payload);
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
