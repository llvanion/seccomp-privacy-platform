import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Send } from "lucide-react";

import { operatorApi } from "@/api/operator";
import type { Json } from "@/api/types";
import { useApiMutation } from "@/hooks/useApi";
import { Button, Card, CardHeader, Field, Input, JsonBlock, PageHeader, Select, Textarea } from "@/components/ui";

const TEMPLATE = {
  query_type: "cross_party_match",
  caller: "console_submitter",
  tenant_id: "demo_tenant",
  dataset_id: "demo_dataset",
  service_id: "demo_service",
  join_key: "email",
  value_field: "amount",
  filters: { campaign: "demo" },
};

export function RequestSubmitRoute() {
  const navigate = useNavigate();
  const [requestText, setRequestText] = useState(() => JSON.stringify(TEMPLATE, null, 2));
  const [submittedBy, setSubmittedBy] = useState("");
  const [tenant, setTenant] = useState("demo_tenant");
  const [datasetService, setDatasetService] = useState("demo_dataset/demo_service");
  const [queryType, setQueryType] = useState("cross_party_match");
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
      return operatorApi.submitRequest({
        submitted_by: submittedBy || undefined,
        tenant_id: tenant || undefined,
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
        description="对应 query_workflow_request/v1 契约；会写入 workflow_submissions（pending），等待 approve 后才会启动作业。"
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
