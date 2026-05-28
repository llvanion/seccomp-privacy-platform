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

export type OperatorDashboardData = {
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

export type RequestSubmission = {
  submission_id: string;
  status: "pending" | "approved" | "rejected" | string;
  submitted_at_utc: string;
  submitted_by?: string;
  caller?: string;
  tenant_id?: string;
  dataset_id?: string;
  service_id?: string;
  request?: Record<string, Json>;
  transitions?: Array<{ state: string; event: string; actor?: string | null; at_utc: string; reason?: string | null }>;
};

// ---------- Metadata sidecar ----------

export type MetadataJobsResponse = {
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
  entries: Array<Record<string, Json>>;
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
  schema?: string;
  job_id?: string;
  events: Array<{
    stage?: string;
    event?: string;
    status?: string;
    role?: string;
    started_at_utc?: string;
    finished_at_utc?: string;
    duration_ms?: number;
    extra?: Record<string, Json>;
  }>;
  derived_handoff_cleanup?: Array<Record<string, Json>>;
  derived_service_audit_consistency?: Array<Record<string, Json>>;
};

export type CatalogLineage = {
  schema?: string;
  job_id?: string;
  nodes: Array<{ kind: string; id: string; tenant?: string; dataset?: string; service?: string; extra?: Record<string, Json> }>;
  edges: Array<{ from: string; to: string; kind: string; extra?: Record<string, Json> }>;
  mainline_contract_summary?: Record<string, Json>;
};

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
