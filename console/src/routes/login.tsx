import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { LogIn } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { operatorApi } from "@/api/operator";
import { useApiQuery } from "@/hooks/useApi";
import { Button, Card, CardHeader, Field, Input, PageHeader } from "@/components/ui";
import { useToast } from "@/components/toast";

const DEFENSE_OPERATOR_TOKEN = "demo-console-operator-token";

export function LoginRoute() {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [token, setToken] = useState(DEFENSE_OPERATOR_TOKEN);
  const [loading, setLoading] = useState(false);
  const sessionQ = useApiQuery(["operator", "session"], () => operatorApi.sessionStatus(), { retry: 0 });

  const redirectTo = typeof location.state === "object" && location.state !== null && "from" in location.state
    ? String((location.state as { from?: string }).from || "/home")
    : "/home";

  if (sessionQ.data?.status === "authenticated") {
    return <Navigate to={redirectTo} replace />;
  }

  const login = async () => {
    const trimmed = token.trim();
    if (!trimmed) {
      toast.pushError("缺少 token", "请输入 operator identity token。");
      return;
    }
    setLoading(true);
    try {
      const session = await operatorApi.sessionLogin({ bearer_token: trimmed, max_age_seconds: 8 * 60 * 60 });
      queryClient.setQueryData(["operator", "session"], session);
      await queryClient.invalidateQueries({ queryKey: ["operator", "session"] });
      toast.pushSuccess("登录成功", `caller=${session.authenticated_identity?.caller ?? "unknown"}`);
      navigate(redirectTo, { replace: true });
    } catch (err) {
      toast.pushError("登录失败", err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen grid place-items-center px-6 py-10">
      <div className="w-full max-w-xl space-y-5">
        <PageHeader
          title="Operator Login"
          description="先建立 HttpOnly session，再进入控制台。答辩 demo 默认 token 已预填。"
        />

        <Card>
          <CardHeader
            title="登录"
            description="真实鉴权模式下，未登录不会直接进入主页。"
          />
          <div className="space-y-4">
            <Field label="Operator token" hint="答辩 demo 默认：demo-console-operator-token">
              <Input
                type="password"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                placeholder="demo-console-operator-token"
              />
            </Field>
            <div className="flex items-center gap-3">
              <Button variant="primary" leftIcon={<LogIn className="w-4 h-4" />} onClick={login} loading={loading}>
                登录并进入主页
              </Button>
              <Button variant="secondary" onClick={() => setToken(DEFENSE_OPERATOR_TOKEN)}>
                填充答辩 token
              </Button>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
