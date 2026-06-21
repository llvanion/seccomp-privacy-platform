import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Play } from "lucide-react";

import { operatorApi } from "@/api/operator";
import type { Json } from "@/api/types";
import { useApiMutation } from "@/hooks/useApi";
import { Button, Card, CardHeader, Field, Input, JsonBlock, PageHeader, Select, Textarea } from "@/components/ui";

const DEFAULT_PAYLOAD = {
  schema: "query_workflow_request/v1",
  query_type: "cross_party_match",
  job_id: `console-${new Date().toISOString().slice(0, 19).replaceAll("-", "").replaceAll(":", "").replace("T", "")}`,
  out_base: "tmp/defense_demo/runs/adhoc_console_job",
  caller: "auto_demo",
  tenant_id: "demo_tenant",
  dataset_id: "bridge_demo_dataset",
  server_source: "$REPO/sse/examples/bridge_server_records.jsonl",
  client_source: "$REPO/sse/examples/bridge_client_records.jsonl",
  server_join_key_field: "email",
  client_join_key_field: "email",
  client_value_field: "amount",
  server_normalizer: "email",
  client_normalizer: "email",
  client_value_mode: "raw-int",
  client_value_min: 0,
  client_value_max: 1000000,
  client_allowed_value_fields: ["amount"],
  client_value_unit: "minor_currency_unit",
  client_value_currency: "USD",
  server_filters: ["campaign=demo"],
  client_filters: ["campaign=demo"],
  token_scope: "defense-demo-scope",
  token_secret_env: "BRIDGE_TOKEN_SECRET",
  sse_export_policy_config: "$REPO/sse/config/export_policy.example.json",
  deny_duplicate_query: true,
  cleanup_sse_export_handoff_files_after_bridge: true,
};

export function JobStartRoute() {
  const navigate = useNavigate();
  const [payload, setPayload] = useState(() => JSON.stringify(DEFAULT_PAYLOAD, null, 2));
  const [handoffMode, setHandoffMode] = useState("file");
  const [parseError, setParseError] = useState<string | null>(null);

  const mutation = useApiMutation(
    async () => {
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(payload);
      } catch (e) {
        setParseError((e as Error).message);
        throw new Error("payload 不是合法 JSON");
      }
      setParseError(null);
      return operatorApi.startJob({ ...parsed, sse_export_handoff_mode: handoffMode } as Record<string, Json>);
    },
    {
      successToast: "作业已提交",
      onSuccess: (data) => {
        if (data?.job_id) navigate(`/jobs/${encodeURIComponent(data.job_id)}`);
      },
    },
  );

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={
          <Link to="/jobs" className="hover:text-ink inline-flex items-center gap-1">
            <ArrowLeft className="w-3 h-3" />
            作业列表
          </Link>
        }
        title="启动主链路作业"
        description="构造一个最小可运行 payload，通过 dashboard /v1/jobs/start 进入 SSE → bridge → PJC → release。"
        actions={
          <Button
            variant="primary"
            leftIcon={<Play className="w-4 h-4" />}
            onClick={() => mutation.mutate(undefined as never)}
            loading={mutation.isPending}
          >
            提交作业
          </Button>
        }
      />

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2">
          <CardHeader
            title="作业 payload"
            description="这里直接提交 query_workflow_request/v1；模板已对齐当前后端校验，不再使用旧版 pipeline 嵌套结构。"
          />
          <Field label="JSON payload" hint="$REPO 等占位符由服务端解析" error={parseError ?? undefined}>
            <Textarea
              value={payload}
              onChange={(e) => setPayload(e.target.value)}
              spellCheck={false}
              className="min-h-[360px]"
            />
          </Field>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <Field label="handoff 模式" hint="file (cleanup) / file-retain / fifo">
              <Select value={handoffMode} onChange={(e) => setHandoffMode(e.target.value)}>
                <option value="file">file</option>
                <option value="file-retain">file-retain</option>
                <option value="fifo">fifo</option>
              </Select>
            </Field>
          </div>
        </Card>

        <Card>
          <CardHeader title="模板预览" description="左侧 payload 解析后的结构化视图。" />
          <SafePreview json={payload} />
        </Card>
      </section>
    </div>
  );
}

function SafePreview({ json }: { json: string }) {
  try {
    const parsed = JSON.parse(json);
    return <JsonBlock data={parsed} maxHeight="380px" />;
  } catch (e) {
    return <p className="text-2xs text-accent-warn">JSON 解析失败：{(e as Error).message}</p>;
  }
}
