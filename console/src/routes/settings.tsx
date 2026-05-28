import { useState } from "react";
import { RefreshCw, Save, Trash2 } from "lucide-react";

import { Button, Card, CardHeader, Field, Input, PageHeader } from "@/components/ui";
import { useToast } from "@/components/toast";
import { resetConfig, setSidecar, useConfig, type SidecarKey } from "@/api/config";

const SIDECARS: Array<{ key: SidecarKey; label: string; hint: string }> = [
  { key: "operator", label: "Operator dashboard", hint: "/v1/dashboard, /v1/jobs, /v1/requests, /v1/pjc-mtls (default: same-origin)" },
  { key: "metadata", label: "Metadata sidecar", hint: "scripts/serve_metadata_api.py (default port 18090)" },
  { key: "query", label: "Query workflow", hint: "scripts/serve_query_workflow_api.py (default port 18091)" },
  { key: "audit", label: "Audit query", hint: "scripts/serve_audit_query_api.py (default port 18092)" },
  { key: "health", label: "Platform health", hint: "scripts/serve_platform_health_api.py (default port 18093)" },
  { key: "recovery", label: "Record recovery HTTP", hint: "services/record_recovery (auto-allocated port)" },
];

export function SettingsRoute() {
  const config = useConfig();
  const toast = useToast();
  const [draft, setDraft] = useState(() => structuredClone(config));

  const save = () => {
    for (const s of SIDECARS) {
      setSidecar(s.key, draft[s.key]);
    }
    toast.pushSuccess("配置已保存", "保存在 localStorage（仅本浏览器）。");
  };

  const reset = () => {
    resetConfig();
    setDraft(structuredClone({
      operator: { baseUrl: "" },
      metadata: { baseUrl: "" },
      query: { baseUrl: "" },
      audit: { baseUrl: "" },
      health: { baseUrl: "" },
      recovery: { baseUrl: "" },
    }));
    toast.pushSuccess("已恢复默认", "所有 baseUrl / token 清空，回到 same-origin 模式。");
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="设置"
        description="为 6 个 sidecar HTTP API 配置 baseUrl + Bearer token。配置存在浏览器 localStorage，不会写回服务端。"
        actions={
          <>
            <Button variant="ghost" leftIcon={<Trash2 className="w-4 h-4" />} onClick={reset}>
              恢复默认
            </Button>
            <Button variant="primary" leftIcon={<Save className="w-4 h-4" />} onClick={save}>
              保存
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {SIDECARS.map((s) => (
          <Card key={s.key}>
            <CardHeader title={s.label} description={s.hint} />
            <Field label="Base URL" hint="留空 = same-origin (推荐部署模式)">
              <Input
                placeholder="http://127.0.0.1:18090"
                value={draft[s.key].baseUrl}
                onChange={(e) => setDraft((prev) => ({ ...prev, [s.key]: { ...prev[s.key], baseUrl: e.target.value } }))}
              />
            </Field>
            <Field label="Bearer token" hint="如服务端启用 --auth-token 校验则填入" className="mt-3">
              <Input
                type="password"
                placeholder="留空 = 不附 Authorization 头"
                value={draft[s.key].token ?? ""}
                onChange={(e) => setDraft((prev) => ({ ...prev, [s.key]: { ...prev[s.key], token: e.target.value } }))}
              />
            </Field>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader title="提示" actions={<RefreshCw className="w-4 h-4 text-ink-dim" />} />
        <ul className="text-2xs text-ink-muted space-y-1.5 leading-relaxed">
          <li>· 浏览器配置只影响当前会话；CI / 容器化部署请改用对应环境变量。</li>
          <li>· 所有 token 仅写入 localStorage，不会上送任何外部服务。</li>
          <li>· serve_operator_dashboard.py 默认在 / 路径下伺服 SPA 静态资源，并继续在 /v1/* 提供 API。</li>
        </ul>
      </Card>
    </div>
  );
}
