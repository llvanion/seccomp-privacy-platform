import { useState } from "react";
import { LogIn, LogOut, RefreshCw, Save, Trash2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, Field, Input, PageHeader } from "@/components/ui";
import { useToast } from "@/components/toast";
import { resetConfig, setSidecar, useConfig, type ConsoleConfig, type SidecarKey } from "@/api/config";
import { operatorApi } from "@/api/operator";

const SIDECARS: Array<{ key: SidecarKey; label: string; hint: string }> = [
  { key: "operator", label: "Operator dashboard", hint: "/v1/dashboard, /v1/jobs, /v1/requests, /v1/pjc-mtls (default: same-origin)" },
  { key: "metadata", label: "Metadata sidecar", hint: "scripts/serve_metadata_api.py (default port 18090)" },
  { key: "query", label: "Query workflow", hint: "scripts/serve_query_workflow_api.py (default port 18091)" },
  { key: "audit", label: "Audit query", hint: "scripts/serve_audit_query_api.py (default port 18092)" },
  { key: "health", label: "Platform health", hint: "scripts/serve_platform_health_api.py (default port 18093)" },
  { key: "recovery", label: "Record recovery HTTP", hint: "services/record_recovery (auto-allocated port)" },
];

const DEFENSE_PROXY_DEFAULTS: Partial<Record<SidecarKey, string>> = {
  metadata: "/proxy/metadata",
  query: "/proxy/query",
  audit: "/proxy/audit",
  health: "/proxy/health",
};

const DEFENSE_OPERATOR_TOKEN = "demo-console-operator-token";
const DEFENSE_RECOVERY_URL = "http://127.0.0.1:18081";

const DEFENSE_PROFILE: ConsoleConfig = {
  operator: { baseUrl: "", token: DEFENSE_OPERATOR_TOKEN },
  metadata: { baseUrl: DEFENSE_PROXY_DEFAULTS.metadata ?? "" },
  query: { baseUrl: DEFENSE_PROXY_DEFAULTS.query ?? "" },
  audit: { baseUrl: DEFENSE_PROXY_DEFAULTS.audit ?? "" },
  health: { baseUrl: DEFENSE_PROXY_DEFAULTS.health ?? "" },
  recovery: { baseUrl: DEFENSE_RECOVERY_URL },
};

export function SettingsRoute() {
  const config = useConfig();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(() => {
    const next = structuredClone(config);
    for (const [key, baseUrl] of Object.entries(DEFENSE_PROXY_DEFAULTS)) {
      const sidecarKey = key as SidecarKey;
      if (!next[sidecarKey].baseUrl) {
        next[sidecarKey].baseUrl = baseUrl;
      }
    }
    return next;
  });
  const [sessionLoading, setSessionLoading] = useState(false);

  const persistDraft = (next: ConsoleConfig) => {
    for (const s of SIDECARS) {
      setSidecar(s.key, next[s.key]);
    }
  };

  const save = () => {
    persistDraft(draft);
    toast.pushSuccess("配置已保存", "Base URL 长期保存；Bearer token 仅作为跨域/CLI fallback。");
  };

  const reset = () => {
    resetConfig();
    setDraft(structuredClone({
      operator: { baseUrl: "" },
      metadata: { baseUrl: DEFENSE_PROXY_DEFAULTS.metadata ?? "" },
      query: { baseUrl: DEFENSE_PROXY_DEFAULTS.query ?? "" },
      audit: { baseUrl: DEFENSE_PROXY_DEFAULTS.audit ?? "" },
      health: { baseUrl: DEFENSE_PROXY_DEFAULTS.health ?? "" },
      recovery: { baseUrl: "" },
    }));
    for (const [key, baseUrl] of Object.entries(DEFENSE_PROXY_DEFAULTS)) {
      setSidecar(key as SidecarKey, { baseUrl });
    }
    toast.pushSuccess("已恢复默认", "sidecar 默认改回同源 /proxy/*；token 清空，回到 browser session 模式。");
  };

  const applyDefenseProfile = () => {
    setDraft(structuredClone(DEFENSE_PROFILE));
    persistDraft(DEFENSE_PROFILE);
    toast.pushSuccess("已填充答辩模式", "已设置 /proxy/*、Recovery 地址和演示 token。下一步可直接点“一键登录”。");
  };

  const loginSession = async () => {
    const token = draft.operator.token?.trim();
    if (!token) {
      toast.pushError("缺少 token", "输入一次性 operator identity token 后再换取 HttpOnly session。");
      return;
    }
    setSessionLoading(true);
    try {
      const session = await operatorApi.sessionLogin({ bearer_token: token, max_age_seconds: 8 * 60 * 60 });
      setDraft((prev) => ({ ...prev, operator: { ...prev.operator, token: "" } }));
      setSidecar("operator", { ...draft.operator, token: "" });
      queryClient.setQueryData(["operator", "session"], session);
      await queryClient.invalidateQueries({ queryKey: ["operator", "session"] });
      toast.pushSuccess("Session 已建立", `caller=${session.authenticated_identity?.caller ?? "unknown"}；Bearer token 已从 console 配置清空。`);
    } catch (err) {
      toast.pushError("Session 登录失败", err instanceof Error ? err.message : String(err));
    } finally {
      setSessionLoading(false);
    }
  };

  const loginDefenseMode = async () => {
    const next = structuredClone(DEFENSE_PROFILE);
    setDraft(next);
    persistDraft(next);
    setSessionLoading(true);
    try {
      const session = await operatorApi.sessionLogin({ bearer_token: DEFENSE_OPERATOR_TOKEN, max_age_seconds: 8 * 60 * 60 });
      const persisted = { ...next, operator: { ...next.operator, token: "" } };
      setDraft(persisted);
      persistDraft(persisted);
      queryClient.setQueryData(["operator", "session"], session);
      await queryClient.invalidateQueries({ queryKey: ["operator", "session"] });
      toast.pushSuccess("答辩模式已登录", `caller=${session.authenticated_identity?.caller ?? "unknown"}；已写入同源 /proxy 配置。`);
    } catch (err) {
      toast.pushError("答辩模式登录失败", err instanceof Error ? err.message : String(err));
    } finally {
      setSessionLoading(false);
    }
  };

  const logoutSession = async () => {
    setSessionLoading(true);
    try {
      const session = await operatorApi.sessionLogout();
      queryClient.setQueryData(["operator", "session"], session);
      await queryClient.invalidateQueries({ queryKey: ["operator", "session"] });
      toast.pushSuccess("Session 已清除", "HttpOnly session cookie 已过期。");
    } catch (err) {
      toast.pushError("Session 清除失败", err instanceof Error ? err.message : String(err));
    } finally {
      setSessionLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="设置"
        description="生产推荐 same-origin HttpOnly session；Base URL 可持久化，Bearer token 只作为跨域/CLI fallback。"
        actions={
          <>
            <Button variant="secondary" onClick={applyDefenseProfile}>
              答辩模式填充
            </Button>
            <Button variant="secondary" leftIcon={<LogIn className="w-4 h-4" />} onClick={loginDefenseMode} loading={sessionLoading}>
              一键登录
            </Button>
            <Button variant="ghost" leftIcon={<Trash2 className="w-4 h-4" />} onClick={reset}>
              恢复默认
            </Button>
            <Button variant="primary" leftIcon={<Save className="w-4 h-4" />} onClick={save}>
              保存
            </Button>
          </>
        }
      />

      <Card>
        <CardHeader
          title="Browser session"
          description={`同源 dashboard 可把一次性 identity token 换成 HttpOnly/SameSite cookie，后续请求不需要 JS 持有 Bearer token。答辩 demo token：${DEFENSE_OPERATOR_TOKEN}`}
          actions={
            <div className="flex gap-2">
              <Button variant="secondary" leftIcon={<LogOut className="w-4 h-4" />} onClick={logoutSession} loading={sessionLoading}>
                登出
              </Button>
              <Button variant="primary" leftIcon={<LogIn className="w-4 h-4" />} onClick={loginSession} loading={sessionLoading}>
                建立 session
              </Button>
            </div>
          }
        />
      </Card>

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
            <Field label="Bearer token" hint="fallback：跨域 sidecar 或 CLI 调试；同源生产请用 Browser session" className="mt-3">
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
          <li>· same-origin 部署下，console fetch 默认发送 HttpOnly session cookie。</li>
          <li>· Base URL 存入 localStorage；fallback Bearer token 不做跨会话持久化。</li>
          <li>· serve_operator_dashboard.py 默认在 / 路径下伺服 SPA 静态资源，并继续在 /v1/* 提供 API。</li>
        </ul>
      </Card>
    </div>
  );
}
