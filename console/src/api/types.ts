// Shared API response types. Kept loose where the upstream schema evolves
// frequently; tightened where the schema is in schemas/*.schema.json.

export type Json = string | number | boolean | null | { [k: string]: Json } | Json[];

// ---------- Operator dashboard ----------

export type OperatorJob = {
  job_id: string;
  status?: string;
  terminal_state?: string;
  exit_code?: number | null;
  started_at_utc?: string | null;
  finished_at_utc?: string | null;
  elapsed_seconds?: number | null;
  out_base?: string | null;
  history_root?: string | null;
  caller?: string | null;
  tenant_id?: string | null;
  dataset_id?: string | null;
  service_id?: string | null;
  stages?: Array<{
    stage: string;
    status?: string;
    duration_ms?: number | null;
    started_at_utc?: string | null;
    finished_at_utc?: string | null;
  }>;
  result_summary?: Record<string, Json> | null;
  request?: Record<string, Json> | null;
};

export type OperatorDashboardFullData = {
  generated_at_utc: string;
  history_root: string;
  out_base?: string;
  hero?: Record<string, Json>;
  health?: Record<string, Json>;
  jobs?: OperatorJob[];
  recent_runs?: OperatorJob[];
  alerts?: Array<{
    id: string;
    severity: string;
    state: string;
    title: string;
    summary?: string;
    triggered_at_utc?: string;
    resolved_at_utc?: string;
  }>;
  audit_center?: Record<string, Json>;
  pjc_roles?: Record<string, Json>;
  bucketed_scale_test?: { jobs?: Array<Record<string, Json>> };
  release_policy_gate?: Record<string, Json> | null;
  mtls?: Record<string, Json>;
  tenant_id?: string;
  feature_flags?: string[];
};

export type OperatorDashboardPublicSummary = {
  schema: "operator_dashboard_public_summary/v1";
  generated_at_utc: string | null;
  authenticated_identity: {
    caller: string | null;
    tenant_id: string | null;
    platform_roles: string[];
  } | null;
  scope: {
    job_id: string | null;
    correlation_id: string | null;
    caller: string | null;
    tenant_id: string | null;
    dataset_id: string | null;
    service_id: string | null;
  };
  overall_status: string | null;
  job: {
    state: string | null;
    terminal: boolean | null;
    last_updated_at_utc: string | null;
    stage_statuses: Array<{
      name: string | null;
      status: string | null;
    }>;
  };
  workflow: {
    available: boolean;
    state: string | null;
    terminal: boolean | null;
    recommended_action: string | null;
  };
  health: {
    status?: string | null;
    ok?: number | null;
    warn?: number | null;
    error?: number | null;
  };
  artifacts: {
    available_count: number | null;
    total_count: number | null;
  };
  redaction: {
    operator_fields_redacted: true;
    paths_redacted: true;
    hashes_redacted: true;
    exact_results_redacted: true;
  };
};

export type OperatorDashboardData = OperatorDashboardFullData | OperatorDashboardPublicSummary;

export function isOperatorDashboardPublicSummary(data: OperatorDashboardData | null | undefined): data is OperatorDashboardPublicSummary {
  return typeof data === "object" && data !== null && "schema" in data && data.schema === "operator_dashboard_public_summary/v1";
}

export type RequestSubmission = {
  submission_id: string;
  status: "pending_approval" | "pending" | "approved" | "rejected" | string;
  submitted_at_utc: string;
  submitted_by?: string;
  caller?: string;
  tenant_id?: string;
  dataset_id?: string;
  service_id?: string;
  request?: Record<string, Json>;
  transitions?: Array<{ state: string; event: string; actor?: string | null; at_utc: string; reason?: string | null }>;
};

export type PrivacyBudgetApproval = {
  request_id: string;
  status: "pending_approval" | "approved" | "rejected" | "expired" | "consumed" | string;
  created_at_utc?: string;
  requested_at_utc?: string | null;
  decided_at_utc?: string | null;
  decided_by?: string | null;
  decision_reason?: string | null;
  expires_at_utc?: string | null;
  consumed_at_utc?: string | null;
  consumed_by_job_id?: string | null;
  caller?: string;
  tenant_id?: string | null;
  dataset_id?: string | null;
  purpose?: string | null;
  job_id?: string | null;
  correlation_id?: string | null;
  policy_version?: string | null;
  reason_code?: string;
  reason?: string;
  abuse_signal?: string | null;
  matched_prior_fingerprint?: string | null;
  matched_prior_job_id?: string | null;
  matched_prior_relation?: string | null;
  query_fingerprint?: string | null;
  query_payload_sha256?: string | null;
  window?: Record<string, Json>;
  bucket?: Json;
  value_mode?: string | null;
  threshold_k?: number;
  budget?: Record<string, Json>;
  parsed_metrics?: Record<string, Json>;
  public_report_sha256?: string | null;
  latest_decision?: Record<string, Json> | null;
};

export type PrivacyBudgetApprovalList = {
  schema: "privacy_budget_approval_list/v1";
  status: "ok";
  filter_status?: string | null;
  tenant_id?: string | null;
  caller?: string | null;
  returned_count: number;
  limit: number;
  requests: PrivacyBudgetApproval[];
};

export type PrivacyBudgetApprovalTransition = {
  schema: "privacy_budget_approval_transition/v1";
  status: "ok";
  action: "approve" | "reject" | "expire";
  request_id: string;
  approval: PrivacyBudgetApproval;
  decision: Record<string, Json>;
};

// ---------- Shared sidecar envelopes ----------

export type AuditQueryApiResponse<T extends object> = {
  schema: "audit_query_api_response/v1";
  method: string;
  path: string;
  query: Record<string, Json>;
  result_schema?: string | null;
  result: T;
  authenticated_identity?: Record<string, Json>;
  access_scope?: Record<string, Json>;
};

export function unwrapAuditQueryResult<T extends object>(payload: AuditQueryApiResponse<T> | T): T {
  if (
    typeof payload === "object" &&
    payload !== null &&
    "schema" in payload &&
    payload.schema === "audit_query_api_response/v1" &&
    "result" in payload &&
    typeof payload.result === "object" &&
    payload.result !== null
  ) {
    return payload.result as T;
  }
  return payload as T;
}

export type MetadataApiResponse<T extends object> = {
  schema: "metadata_api_response/v1";
  method: string;
  path: string;
  query: Record<string, Json>;
  result: T;
};

export type OperatorConsoleSession = {
  schema: "operator_console_session/v1";
  status: "authenticated" | "unauthenticated" | "disabled" | "cleared" | "unsupported" | "rejected";
  auth_required?: boolean;
  message?: string;
  session_cookie?: {
    name: string;
    httponly: boolean;
    same_site: string;
    secure: boolean;
    path: string;
  };
  authenticated_identity?: {
    caller?: string | null;
    tenant_id?: string | null;
    service_id?: string | null;
    platform_roles?: string[];
    auth_source?: string | null;
  };
};

export function unwrapMetadataApiResult<T extends object>(payload: MetadataApiResponse<T> | T): T {
  if (
    typeof payload === "object" &&
    payload !== null &&
    "schema" in payload &&
    payload.schema === "metadata_api_response/v1" &&
    "result" in payload &&
    typeof payload.result === "object" &&
    payload.result !== null
  ) {
    return payload.result as T;
  }
  return payload as T;
}

// ---------- Metadata sidecar ----------

export type MetadataJobsResponse = {
  redaction?: {
    view?: string;
    operator_fields_redacted?: boolean;
    paths_redacted?: boolean;
    hashes_redacted?: boolean;
    total_matching_count_redacted?: boolean;
    timing_redacted?: boolean;
  };
  jobs: Array<{
    job_id: string;
    caller?: string;
    tenant_id?: string;
    dataset_id?: string;
    service_id?: string;
    status?: string;
    started_at_utc?: string;
    finished_at_utc?: string;
    duration_total_ms?: number;
    mainline_contract_summary?: Record<string, Json>;
    matched_stage?: Record<string, Json>;
  }>;
  stage_summary?: Record<string, Json>;
  grouped_stage_summary?: Record<string, Json>;
  grouped_status_summary?: Record<string, Json>;
  mainline_contract_summary_counts?: Record<string, Json>;
};

export type MetadataEntityResponse = {
  redaction?: {
    view?: string;
    operator_fields_redacted?: boolean;
    paths_redacted?: boolean;
    hashes_redacted?: boolean;
    total_matching_count_redacted?: boolean;
    timing_redacted?: boolean;
  };
  entries: Array<Record<string, Json>>;
  items?: Array<Record<string, Json>>;
  permission_summary?: Record<string, Json>;
};

// ---------- Audit query sidecar ----------

export type PublicReport = {
  schema?: string;
  job_id?: string;
  generated_at_utc?: string;
  policy_release?: Record<string, Json>;
  attribution?: Record<string, Json>;
  intersection_size?: number;
  intersection_sum?: number;
  display_sum?: number | string;
  raw_sum?: number;
  released?: boolean;
  [k: string]: Json | undefined;
};

export type ObservabilityFeed = {
  schema?: "pipeline_observability/v1" | string;
  job_id?: string;
  generated_at_utc?: string;
  correlation_id?: string | null;
  caller?: string | null;
  tenant_id?: string | null;
  dataset_id?: string | null;
  service_id?: string | null;
  summary?: Record<string, Json>;
  events?: Array<{
    stage?: string;
    event?: string;
    status?: string;
    role?: string;
    ts_utc?: string | null;
    started_at_utc?: string;
    finished_at_utc?: string;
    duration_ms?: number;
    row_count?: number | null;
    artifact_sha256?: string | null;
    source_event?: string | null;
    extra?: Record<string, Json>;
  }>;
  derived_handoff_cleanup?: Array<Record<string, Json>>;
  derived_service_audit_consistency?: Array<Record<string, Json>>;
};

export type PipelineObservabilityPublicSummary = {
  schema: "pipeline_observability_public_summary/v1";
  generated_at_utc: string | null;
  job_id: string | null;
  correlation_id: string | null;
  caller: string | null;
  tenant_id: string | null;
  dataset_id: string | null;
  service_id: string | null;
  summary: {
    status: string | null;
    events_available: boolean;
    stages: Array<{
      name: string;
      statuses: string[];
    }>;
  };
  privacy: {
    view: "caller_safe_summary";
    operator_fields_redacted: true;
  };
};

export type ObservabilityData = ObservabilityFeed | PipelineObservabilityPublicSummary;

export type CatalogLineage = {
  schema?: "catalog_lineage/v1" | string;
  job_id?: string | null;
  generated_at_utc?: string;
  correlation_id?: string | null;
  caller?: string | null;
  tenant_id?: string | null;
  dataset_id?: string | null;
  service_id?: string | null;
  privacy?: Record<string, Json>;
  job?: Record<string, Json>;
  datasets?: Array<Record<string, Json>>;
  services?: Array<Record<string, Json>>;
  artifacts?: Array<Record<string, Json>>;
  lineage_edges?: Array<Record<string, Json>>;
  summary?: {
    dataset_count?: number | null;
    service_count?: number | null;
    artifact_count?: number | null;
    lineage_edge_count?: number | null;
  };
  mainline_contract_summary?: Record<string, Json>;
  nodes?: Array<{ kind: string; id: string; tenant?: string; dataset?: string; service?: string; extra?: Record<string, Json> }>;
  edges?: Array<{ from: string; to: string; kind: string; extra?: Record<string, Json> }>;
};

export type CatalogLineagePublicSummary = {
  schema: "catalog_lineage_public_summary/v1";
  generated_at_utc: string | null;
  job_id: string | null;
  correlation_id: string | null;
  caller: string | null;
  tenant_id: string | null;
  dataset_id: string | null;
  service_id: string | null;
  job: {
    status: string | null;
    released: boolean | null;
    reason_code: string | null;
    policy_version: string | null;
  };
  summary: {
    dataset_count: number | null;
    service_count: number | null;
    artifact_count: number | null;
    lineage_edge_count: number | null;
  };
  mainline_contract: {
    status: string | null;
    handoff_mode: string | null;
    plaintext_exposure_risk: string | null;
  };
  privacy: {
    view: "caller_safe_summary";
    operator_fields_redacted: true;
    paths_included: false;
  };
};

export type CatalogLineageData = CatalogLineage | CatalogLineagePublicSummary;

export type AuditChainPublicSummary = {
  schema: "audit_chain_public_summary/v1";
  generated_at_utc: string | null;
  job_id: string | null;
  correlation_id: string | null;
  caller: string | null;
  tenant_id: string | null;
  dataset_id: string | null;
  service_id: string | null;
  release: {
    released: boolean | null;
    reason_code: string | null;
    policy_version: string | null;
    k_threshold: number | null;
    dp_noise_applied: boolean | null;
    dp_epsilon: number | null;
    operator_fields_redacted: boolean | null;
  };
  stage_record_counts: Record<string, number | null>;
  audit_chain: {
    counts_available: boolean;
    complete_stage_count: number;
  };
  mainline_contract: {
    status: string | null;
    embedded_in_audit_chain: boolean | null;
    handoff_mode: string | null;
    plaintext_exposure_risk: string | null;
  };
  release_gate_summary?: {
    decision: string | null;
    reason_code: string | null;
  } | null;
  privacy: {
    view: "caller_safe_summary";
    operator_fields_redacted: true;
    notes: string;
  };
};

export type AuditChainData = Record<string, Json> | AuditChainPublicSummary;

export function isAuditChainPublicSummary(data: AuditChainData | null | undefined): data is AuditChainPublicSummary {
  return typeof data === "object" && data !== null && "schema" in data && data.schema === "audit_chain_public_summary/v1";
}

export function isPipelineObservabilityPublicSummary(data: ObservabilityData | null | undefined): data is PipelineObservabilityPublicSummary {
  return typeof data === "object" && data !== null && "schema" in data && data.schema === "pipeline_observability_public_summary/v1";
}

export function isCatalogLineagePublicSummary(data: CatalogLineageData | null | undefined): data is CatalogLineagePublicSummary {
  return typeof data === "object" && data !== null && "schema" in data && data.schema === "catalog_lineage_public_summary/v1";
}

// ---------- Platform health ----------

export type PlatformHealth = {
  schema?: string;
  out_base?: string;
  generated_at_utc?: string;
  components: Array<{
    component: string;
    status: "ok" | "warn" | "err" | string;
    summary?: string;
    details?: Record<string, Json>;
  }>;
  mainline_contract_check?: Record<string, Json>;
};

// ---------- SSE keyword search (one-shot helper) ----------

export type SseSearchRequest = {
  keyword: string;
  output_format?: "int" | "hex" | "raw" | "utf8";
  scheme?: string;
  service_name?: string;
  db?: Record<string, string[]>;
  db_path?: string;
  timeout_sec?: number;
};

export type SseSearchResponse = {
  schema: "sse_oneshot_search/v1";
  status: "ok" | "error";
  service_name?: string;
  scheme?: string;
  keyword?: string;
  output_format?: string;
  match_count?: number;
  matches?: string[];
  duration_ms?: number;
  server_endpoint?: string;
  db_source?: string;
  workdir?: string | null;
  raw_stdout?: string;
  stage?: string;
  message?: string;
};

// ---------- PJC run-only (skip bridge) ----------

export type PjcRunOnlyRequest = {
  server_csv: string;
  client_csv: string;
  job_meta?: string;
  out_dir?: string;
  job_id?: string;
  caller?: string;
  threshold_k?: number;
  max_queries?: number;
  deny_duplicate_query?: boolean;
  dp_epsilon?: number | null;
  dp_sensitivity?: number | null;
  round_sum_to?: number | null;
  pjc_build?: boolean;
  tenant_id?: string;
  dataset_id?: string;
  purpose?: string;
  timeout_sec?: number;
};

export type PjcRunOnlyResponse = {
  schema: "pjc_run_only/v1";
  status: "ok" | "error";
  job_id?: string;
  caller?: string;
  out_dir?: string;
  duration_ms?: number;
  inputs?: { server_csv: string; client_csv: string; job_meta?: string | null };
  policy?: Record<string, Json>;
  attribution?: Record<string, Json> | null;
  public_report?: Record<string, Json> | null;
  artifacts?: Record<string, string | null>;
  workdir_owned?: boolean;
  stage?: string;
  message?: string;
};

// ---------- Recovery service ----------

export type RecoveryHealth = {
  status?: string;
  service_id?: string;
  tenant_id?: string;
  dataset_id?: string;
  endpoint?: string;
  uptime_seconds?: number;
  rate_limit?: Record<string, Json>;
  metrics_url?: string;
};
