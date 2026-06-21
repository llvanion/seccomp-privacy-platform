import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Send } from "lucide-react";

import { operatorApi } from "@/api/operator";
import type { Json } from "@/api/types";
import { useApiMutation, useApiQuery } from "@/hooks/useApi";
import { useStoredState } from "@/hooks/useStoredState";
import { Button, Card, CardHeader, Field, Input, JsonBlock, PageHeader, Select, Textarea } from "@/components/ui";

const TEMPLATE = {
  schema: "query_workflow_request/v1",
  query_type: "cross_party_match",
  caller: "console_operator",
  tenant_id: "demo_tenant",
  dataset_id: "bridge_demo_dataset",
  record_recovery_service_id: "bridge-demo-recovery",
  server_source: "sse/examples/bridge_server_records.jsonl",
  client_source: "sse/examples/bridge_client_records.jsonl",
  server_join_key_field: "email",
  client_join_key_field: "email",
  client_value_field: "amount",
  server_normalizer: "email",
  client_normalizer: "email",
  client_value_mode: "raw-int",
  token_scope: "defense-demo-scope",
  token_secret_env: "BRIDGE_TOKEN_SECRET",
  job_id: "request-demo-job",
  out_base: "tmp/defense_demo/runs/request_demo_job",
  sse_export_policy_config: "sse/config/export_policy.example.json",
  server_filters: ["campaign=demo"],
  client_filters: ["campaign=demo"],
  k: 1,
  n: 5,
  deny_duplicate_query: true,
  sse_export_handoff_mode: "fifo",
  cleanup_sse_export_handoff_files_after_bridge: true,
};

export function RequestSubmitRoute() {
  const navigate = useNavigate();
  const sessionQ = useApiQuery(["operator", "session"], () => operatorApi.sessionStatus(), { retry: 0 });
  const [requestText, setRequestText] = useStoredState("console.requests_submit.request_text", JSON.stringify(TEMPLATE, null, 2));
  const [submittedBy, setSubmittedBy] = useStoredState("console.requests_submit.submitted_by", "");
  const [tenant, setTenant] = useStoredState("console.requests_submit.tenant", "demo_tenant");
  const [datasetService, setDatasetService] = useStoredState("console.requests_submit.dataset_service", "bridge_demo_dataset/bridge-demo-recovery");
  const [queryType, setQueryType] = useStoredState("console.requests_submit.query_type", "cross_party_match");
  const [parseError, setParseError] = useState<string | null>(null);

  const submit = useApiMutation(
    async () => {
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(requestText);
      } catch (e) {
        setParseError((e as Error).message);
        throw new Error("payload 不是合法 JSON");
      }
      setParseError(null);
      const [dataset_id, service_id] = datasetService.split("/").map((s) => s.trim());
      const sessionCaller = sessionQ.data?.authenticated_identity?.caller ?? "console_operator";
      const sessionTenant = sessionQ.data?.authenticated_identity?.tenant_id ?? (tenant || "demo_tenant");
      const nextJobId = String(parsed.job_id || `request-demo-${Date.now()}`);
      parsed.schema = "query_workflow_request/v1";
      parsed.caller = sessionCaller;
      parsed.tenant_id = sessionTenant;
      parsed.dataset_id = dataset_id;
      parsed.record_recovery_service_id = service_id;
      parsed.query_type = queryType;
      parsed.server_source = String(parsed.server_source || "sse/examples/bridge_server_records.jsonl");
      parsed.client_source = String(parsed.client_source || "sse/examples/bridge_client_records.jsonl");
      parsed.server_join_key_field = String(parsed.server_join_key_field || "email");
      parsed.client_join_key_field = String(parsed.client_join_key_field || "email");
      parsed.client_value_field = String(parsed.client_value_field || "amount");
      parsed.server_normalizer = String(parsed.server_normalizer || "email");
      parsed.client_normalizer = String(parsed.client_normalizer || "email");
      parsed.client_value_mode = String(parsed.client_value_mode || "raw-int");
      parsed.token_scope = String(parsed.token_scope || "defense-demo-scope");
      parsed.token_secret_env = String(parsed.token_secret_env || "BRIDGE_TOKEN_SECRET");
      parsed.job_id = nextJobId;
      parsed.out_base = String(parsed.out_base || `tmp/defense_demo/runs/${nextJobId}`);
      parsed.sse_export_policy_config = String(parsed.sse_export_policy_config || "sse/config/export_policy.example.json");
      if (!Array.isArray(parsed.server_filters)) parsed.server_filters = ["campaign=demo"];
      if (!Array.isArray(parsed.client_filters)) parsed.client_filters = ["campaign=demo"];
      if (parsed.k === undefined) parsed.k = 1;
      if (parsed.n === undefined) parsed.n = 5;
      if (parsed.deny_duplicate_query === undefined) parsed.deny_duplicate_query = true;
      if (parsed.sse_export_handoff_mode === undefined) parsed.sse_export_handoff_mode = "fifo";
      if (parsed.cleanup_sse_export_handoff_files_after_bridge === undefined) parsed.cleanup_sse_export_handoff_files_after_bridge = true;
      return operatorApi.submitRequest({
        submitted_by: submittedBy || undefined,
        tenant_id: sessionTenant,
        dataset_id,
        service_id,
        query_type: queryType,
        request: parsed,
      } as Record<string, Json>);
    },
    {
      successToast: "请求已提交",
      onSuccess: (data) => {
        if (data?.submission_id) navigate(`/requests/${encodeURIComponent(data.submission_id)}`);
      },
    },
  );

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={
          <Link to="/requests" className="hover:text-ink inline-flex items-center gap-1">
            <ArrowLeft className="w-3 h-3" />
            请求列表
          </Link>
        }
        title="提交请求"
        description="对应 query_workflow_request/v1 契约；会写入 workflow_submissions（pending），等待 approve 后才会启动作业。默认模板已对齐答辩 demo 中当前登录身份的允许 scope。"
        actions={
          <Button variant="primary" leftIcon={<Send className="w-4 h-4" />} onClick={() => submit.mutate(undefined as never)} loading={submit.isPending}>
            提交
          </Button>
        }
      />

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card>
          <CardHeader title="元数据" />
          <div className="space-y-3">
            <Field label="提交人 submitted_by">
              <Input value={submittedBy} onChange={(e) => setSubmittedBy(e.target.value)} placeholder="user@org" />
            </Field>
            <Field label="租户">
              <Input value={tenant} onChange={(e) => setTenant(e.target.value)} placeholder="tenant_id" />
            </Field>
            <Field label="数据集 / 服务" hint="格式：dataset_id/service_id">
              <Input value={datasetService} onChange={(e) => setDatasetService(e.target.value)} />
            </Field>
            <Field label="Query 类型">
              <Select value={queryType} onChange={(e) => setQueryType(e.target.value)}>
                <option value="cross_party_match">cross_party_match</option>
              </Select>
            </Field>
          </div>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="请求 payload" description="query_workflow_request/v1 的 request 字段；可自定义 filters、join_key、value_field 等。" />
          <Field label="JSON" error={parseError ?? undefined}>
            <Textarea
              value={requestText}
              onChange={(e) => setRequestText(e.target.value)}
              spellCheck={false}
              className="min-h-[280px]"
            />
          </Field>
        </Card>
      </section>

      <Card>
        <CardHeader title="预览" description="左侧 JSON 解析后的结构化视图。" />
        <SafePreview json={requestText} />
      </Card>
    </div>
  );
}

function SafePreview({ json }: { json: string }) {
  try {
    return <JsonBlock data={JSON.parse(json)} maxHeight="320px" />;
  } catch (e) {
    return <p className="text-2xs text-accent-warn">解析失败：{(e as Error).message}</p>;
  }
}
