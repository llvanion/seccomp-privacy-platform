import { useMemo, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Activity, KeyRound, ShieldCheck, ZapOff } from "lucide-react";

import { recoveryApi } from "@/api/sidecars";
import { operatorApi } from "@/api/operator";
import { useApiMutation, useApiQuery } from "@/hooks/useApi";
import { Button, Card, CardHeader, ErrorBanner, Field, Input, JsonBlock, PageHeader, Skeleton, StatTile, StatusPill, Textarea, inferStatusKind } from "@/components/ui";
import { RouteTabs } from "@/components/tabs";
import { formatNumber } from "@/lib/format";
import type { Json } from "@/api/types";

export function RecoveryRoute() {
  const location = useLocation();
  const tabs = [
    { to: "/recovery/service", label: "服务状态" },
    { to: "/recovery/metrics", label: "Prometheus 指标" },
    { to: "/recovery/mtls", label: "PJC mTLS bootstrap" },
    { to: "/recovery/diagnostics", label: "TLS / negative cases" },
  ];
  const onRoot = location.pathname === "/recovery" || location.pathname === "/recovery/";

  return (
    <div className="space-y-5">
      <PageHeader
        title="记录恢复 / mTLS"
        description="record-recovery 服务的健康、指标、速率限制、租户配额，以及 PJC mTLS 双方 enroll 与 TLS 自检。"
      />
      <RouteTabs tabs={tabs} />
      {onRoot ? (
        <Navigate to="/recovery/service" replace />
      ) : (
        <Routes>
          <Route path="service" element={<ServiceTab />} />
          <Route path="metrics" element={<MetricsTab />} />
          <Route path="mtls" element={<MtlsTab />} />
          <Route path="diagnostics" element={<DiagnosticsTab />} />
          <Route path="*" element={<Navigate to="service" replace />} />
        </Routes>
      )}
    </div>
  );
}

function ServiceTab() {
  const q = useApiQuery(["recovery", "health"], () => recoveryApi.health(), { retry: 0, refetchInterval: 10_000 });
  return (
    <div className="space-y-4">
      <section className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <StatTile
          label="状态"
          icon={<Activity className="w-4 h-4" />}
          value={q.isLoading ? <Skeleton className="h-6 w-16" /> : <StatusPill kind={inferStatusKind(q.data?.status)}>{q.data?.status ?? "unknown"}</StatusPill>}
          hint="recovery service"
        />
        <StatTile
          label="租户 · 数据集 · 服务"
          icon={<KeyRound className="w-4 h-4" />}
          value={q.isLoading ? <Skeleton className="h-6 w-32" /> : `${q.data?.tenant_id ?? "?"} · ${q.data?.dataset_id ?? "?"}`}
          hint={q.data?.service_id ?? "service_id"}
          kind="info"
        />
        <StatTile
          label="uptime"
          icon={<ShieldCheck className="w-4 h-4" />}
          value={q.isLoading ? <Skeleton className="h-6 w-20" /> : formatNumber(q.data?.uptime_seconds ?? null) + " s"}
          hint="seconds"
          kind="ok"
        />
      </section>

      <Card>
        <CardHeader title="原始 health JSON" />
        {q.isLoading ? <Skeleton className="h-40" /> : q.error ? <ErrorBanner title="无法读取" message={q.error.message} /> : <JsonBlock data={q.data ?? {}} maxHeight="320px" />}
      </Card>
    </div>
  );
}

function MetricsTab() {
  const q = useApiQuery(["recovery", "metrics"], () => recoveryApi.metrics(), { retry: 0 });

  const parsed = useMemo(() => parsePromText(q.data ?? ""), [q.data]);

  return (
    <Card>
      <CardHeader title="Prometheus /metrics" description="文本格式 counter + histogram，无需外部 client 库即可解析。" />
      {q.isLoading ? (
        <Skeleton className="h-48" />
      ) : q.error ? (
        <ErrorBanner title="加载失败" message={q.error.message} />
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
            {parsed.slice(0, 8).map((m) => (
              <div key={m.name} className="panel-soft p-3 rounded-lg">
                <div className="field-label truncate">{m.name}</div>
                <div className="text-sm font-mono text-ink mt-1">{m.value}</div>
              </div>
            ))}
          </div>
          <details>
            <summary className="cursor-pointer text-2xs text-ink-muted hover:text-ink">原始文本</summary>
            <pre className="mt-2 panel p-3 font-mono text-2xs whitespace-pre-wrap break-words overflow-x-auto max-h-[420px]">
              {q.data}
            </pre>
          </details>
        </>
      )}
    </Card>
  );
}

function parsePromText(text: string): Array<{ name: string; value: string }> {
  const out: Array<{ name: string; value: string }> = [];
  for (const line of text.split("\n")) {
    if (!line || line.startsWith("#")) continue;
    const space = line.lastIndexOf(" ");
    if (space < 0) continue;
    const name = line.slice(0, space).trim();
    const value = line.slice(space + 1).trim();
    if (!name || !value) continue;
    out.push({ name, value });
  }
  return out;
}

function MtlsTab() {
  const [partyAPayload, setPartyAPayload] = useState(`{
  "enroll_url": "https://recovery.example.com/v1/pjc-mtls/enroll",
  "force_regenerate": false
}`);
  const [partyBPayload, setPartyBPayload] = useState(`{
  "bootstrap_uri": "seccomp+mtls://...",
  "service_id": "recovery"
}`);

  const partyA = useApiMutation(
    async () => operatorApi.mtlsPartyAPrepare(JSON.parse(partyAPayload) as Record<string, Json>),
    { successToast: "Party A 已生成 mTLS pairing" },
  );
  const partyB = useApiMutation(
    async () => operatorApi.mtlsPartyBEnroll(JSON.parse(partyBPayload) as Record<string, Json>),
    { successToast: "Party B 已 enroll" },
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card>
        <CardHeader title="Party A · prepare" description="生成 pairing token + CSR；返回 bootstrap URI 与 CA fingerprint。" />
        <Textarea value={partyAPayload} onChange={(e) => setPartyAPayload(e.target.value)} className="min-h-[120px]" spellCheck={false} />
        <Button className="mt-2" variant="primary" onClick={() => partyA.mutate(undefined as never)} loading={partyA.isPending}>
          运行
        </Button>
        {partyA.data && <JsonBlock data={partyA.data} className="mt-3" maxHeight="280px" />}
      </Card>

      <Card>
        <CardHeader title="Party B · enroll" description="接收 bootstrap URI 后完成证书签发，并将客户端证书写入 keyring。" />
        <Textarea value={partyBPayload} onChange={(e) => setPartyBPayload(e.target.value)} className="min-h-[120px]" spellCheck={false} />
        <Button className="mt-2" variant="primary" onClick={() => partyB.mutate(undefined as never)} loading={partyB.isPending}>
          运行
        </Button>
        {partyB.data && <JsonBlock data={partyB.data} className="mt-3" maxHeight="280px" />}
      </Card>
    </div>
  );
}

function DiagnosticsTab() {
  const [preflightPayload, setPreflightPayload] = useState(`{"role": "client"}`);
  const [negPayload, setNegPayload] = useState(`{"cases": ["expired_cert", "missing_signature", "bad_timestamp"]}`);
  const [diagPayload, setDiagPayload] = useState(`{"endpoint_url": "https://recovery.example.com/healthz"}`);

  const preflight = useApiMutation(
    async () => operatorApi.mtlsPreflight(JSON.parse(preflightPayload) as Record<string, Json>),
    { successToast: "preflight ok" },
  );
  const neg = useApiMutation(
    async () => operatorApi.mtlsNegativeCases(JSON.parse(negPayload) as Record<string, Json>),
    { successToast: "negative cases 完成" },
  );
  const diag = useApiMutation(
    async () => operatorApi.mtlsTlsDiagnostic(JSON.parse(diagPayload) as Record<string, Json>),
    { successToast: "TLS 诊断完成" },
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <DiagnosticCard title="mTLS preflight" desc="检查证书 / pairing token / 与服务端可达性。" payload={preflightPayload} setPayload={setPreflightPayload} run={() => preflight.mutate(undefined as never)} loading={preflight.isPending} result={preflight.data} icon={<ShieldCheck className="w-4 h-4" />} />
      <DiagnosticCard title="negative cases" desc="构造过期证书 / 缺签名 / 错时间戳，验证服务端拒绝。" payload={negPayload} setPayload={setNegPayload} run={() => neg.mutate(undefined as never)} loading={neg.isPending} result={neg.data} icon={<ZapOff className="w-4 h-4" />} />
      <DiagnosticCard title="TLS diagnostic" desc="对目标 endpoint 做 TLS handshake 与证书链验证。" payload={diagPayload} setPayload={setDiagPayload} run={() => diag.mutate(undefined as never)} loading={diag.isPending} result={diag.data} icon={<Activity className="w-4 h-4" />} />
    </div>
  );
}

function DiagnosticCard(props: {
  title: string;
  desc: string;
  payload: string;
  setPayload: (v: string) => void;
  run: () => void;
  loading: boolean;
  result?: unknown;
  icon: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader title={<span className="inline-flex items-center gap-2">{props.icon}{props.title}</span>} description={props.desc} />
      <Field label="payload">
        <Textarea value={props.payload} onChange={(e) => props.setPayload(e.target.value)} className="min-h-[100px]" spellCheck={false} />
      </Field>
      <Button className="mt-2" variant="primary" onClick={props.run} loading={props.loading}>
        运行
      </Button>
      {props.result !== undefined && <JsonBlock data={props.result} className="mt-3" maxHeight="240px" />}
    </Card>
  );
}
