import { useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Activity, AlertTriangle, ExternalLink, Radar, Zap } from "lucide-react";

import { auditApi, healthApi, recoveryApi } from "@/api/sidecars";
import { useApiQuery } from "@/hooks/useApi";
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  JsonBlock,
  PageHeader,
  Skeleton,
  StatTile,
  StatusPill,
  inferStatusKind,
} from "@/components/ui";
import { RouteTabs } from "@/components/tabs";
import { DataTable, type Column } from "@/components/data-table";
import { formatDuration, formatNumber, formatTimestamp } from "@/lib/format";
import type { Json, ObservabilityFeed, PlatformHealth } from "@/api/types";

export function ObservabilityRoute() {
  const location = useLocation();
  const tabs = [
    { to: "/observability/overview", label: "概览" },
    { to: "/observability/events", label: "事件流" },
    { to: "/observability/alerts", label: "告警" },
    { to: "/observability/metrics", label: "指标 / Grafana" },
    { to: "/observability/chaos", label: "Chaos drills" },
  ];
  const onRoot = location.pathname === "/observability" || location.pathname === "/observability/";

  return (
    <div className="space-y-5">
      <PageHeader
        title="可观测性"
        description="pipeline_observability/v1 事件流、告警状态、Prometheus + Tempo + Grafana 入口、chaos 演练。"
      />
      <RouteTabs tabs={tabs} />
      {onRoot ? (
        <Navigate to="/observability/overview" replace />
      ) : (
        <Routes>
          <Route path="overview" element={<OverviewTab />} />
          <Route path="events" element={<EventsTab />} />
          <Route path="alerts" element={<AlertsTab />} />
          <Route path="metrics" element={<MetricsTab />} />
          <Route path="chaos" element={<ChaosTab />} />
          <Route path="*" element={<Navigate to="overview" replace />} />
        </Routes>
      )}
    </div>
  );
}

function OverviewTab() {
  const health = useApiQuery<PlatformHealth>(["platform", "health"], () => healthApi.platformHealth(), { retry: 0 });

  return (
    <div className="space-y-4">
      <section className="grid grid-cols-1 sm:grid-cols-4 gap-3">
        <StatTile icon={<Radar className="w-4 h-4" />} label="components" value={health.isLoading ? <Skeleton className="h-6 w-12" /> : formatNumber(health.data?.components?.length ?? 0)} hint="platform_health" />
        <StatTile icon={<Activity className="w-4 h-4" />} label="ok" value={health.isLoading ? <Skeleton className="h-6 w-12" /> : formatNumber((health.data?.components ?? []).filter((c) => c.status === "ok").length)} kind="ok" hint="healthy" />
        <StatTile icon={<AlertTriangle className="w-4 h-4" />} label="warn" value={health.isLoading ? <Skeleton className="h-6 w-12" /> : formatNumber((health.data?.components ?? []).filter((c) => c.status === "warn").length)} kind="warn" hint="warning" />
        <StatTile icon={<Zap className="w-4 h-4" />} label="err" value={health.isLoading ? <Skeleton className="h-6 w-12" /> : formatNumber((health.data?.components ?? []).filter((c) => c.status === "err").length)} kind="err" hint="error" />
      </section>

      <Card>
        <CardHeader title="平台 component 状态" description="/v1/platform-health 全部 component。" />
        {health.isLoading ? (
          <Skeleton className="h-32" />
        ) : health.error ? (
          <ErrorBanner title="无法读取" message={health.error.message} retry={() => health.refetch()} />
        ) : (
          <DataTable
            rows={health.data?.components ?? []}
            columns={[
              { id: "name", header: "component", cell: (c) => <span className="font-mono text-2xs">{c.component}</span> },
              { id: "status", header: "status", cell: (c) => <StatusPill kind={inferStatusKind(c.status)}>{c.status}</StatusPill> },
              { id: "summary", header: "summary", cell: (c) => <span className="text-2xs text-ink-muted">{c.summary ?? "—"}</span> },
            ]}
            rowKey={(c) => c.component}
          />
        )}
      </Card>
    </div>
  );
}

function EventsTab() {
  const [outBase, setOutBase] = useState("");
  const q = useApiQuery<ObservabilityFeed>(["obs", "events", outBase], () => auditApi.observability({ out_base: outBase || undefined }), { retry: 0 });

  const columns: Column<NonNullable<ObservabilityFeed["events"]>[number]>[] = [
    { id: "stage", header: "stage", cell: (e) => <span className="font-mono text-2xs">{e.stage ?? "—"}</span>, sortKey: (e) => e.stage ?? "" },
    { id: "event", header: "event", cell: (e) => <span className="text-2xs">{e.event ?? "—"}</span>, sortKey: (e) => e.event ?? "" },
    { id: "status", header: "status", cell: (e) => <StatusPill kind={inferStatusKind(e.status)}>{e.status ?? "—"}</StatusPill>, sortKey: (e) => e.status ?? "" },
    { id: "role", header: "role", cell: (e) => <span className="text-2xs text-ink-muted">{e.role ?? "—"}</span>, sortKey: (e) => e.role ?? "" },
    { id: "duration", header: "duration", cell: (e) => formatDuration(e.duration_ms), sortKey: (e) => e.duration_ms ?? 0 },
    { id: "started", header: "started_at", cell: (e) => <span className="text-2xs">{formatTimestamp(e.started_at_utc)}</span>, sortKey: (e) => e.started_at_utc ?? "" },
  ];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="参数" />
        <div className="flex items-end gap-3">
          <Field label="out_base" className="flex-1">
            <Input value={outBase} onChange={(e) => setOutBase(e.target.value)} placeholder="$REPO/tmp/sse_bridge_pipeline_demo" />
          </Field>
          <Button variant="secondary" onClick={() => q.refetch()} loading={q.isFetching}>
            重新查询
          </Button>
        </div>
      </Card>
      <Card>
        <CardHeader title={`events ${q.data?.events ? `(${q.data.events.length})` : ""}`} />
        {q.isLoading ? (
          <Skeleton className="h-48" />
        ) : q.error ? (
          <ErrorBanner title="加载失败" message={q.error.message} />
        ) : (
          <DataTable rows={q.data?.events ?? []} columns={columns} rowKey={(_, i) => String(i)} empty="无事件" initialSort={{ id: "started", dir: "desc" }} />
        )}
      </Card>
    </div>
  );
}

function AlertsTab() {
  return (
    <Card>
      <CardHeader title="告警 daemon" description="alert webhook + Slack/Alertmanager 推送，按状态 transition 触发。" />
      <div className="space-y-3 text-2xs text-ink-muted leading-relaxed">
        <p>
          运行模式：<code className="text-brand">scripts/run_alert_check_daemon.py</code>；契约：
          <code className="text-brand">alert_daemon_heartbeat/v1</code>。
        </p>
        <pre className="panel p-3 font-mono text-2xs overflow-x-auto">
{`# 单跑一次（cron one-shot）
python3 scripts/check_observability_alerts.py \\
  --webhook-url $SLACK_INCOMING_WEBHOOK \\
  --webhook-format slack

# 长驻 daemon（带 firing → resolved transition 追踪）
python3 scripts/run_alert_check_daemon.py \\
  --interval-seconds 30 \\
  --webhook-url $ALERTMANAGER \\
  --webhook-format alertmanager`}
        </pre>
      </div>
    </Card>
  );
}

function MetricsTab() {
  const q = useApiQuery(["recovery", "metrics"], () => recoveryApi.metrics(), { retry: 0 });
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Card>
        <CardHeader title="Grafana / Tempo / Prometheus" description="一键起：config/observability/docker-compose.observability.yml" />
        <ul className="space-y-2 text-2xs">
          <li>
            <ExternalLinkRow href="http://localhost:3000" label="Grafana" hint="dashboards: pipeline-overview / recovery-service" />
          </li>
          <li>
            <ExternalLinkRow href="http://localhost:3200" label="Tempo" hint="OTLP/HTTP traces" />
          </li>
          <li>
            <ExternalLinkRow href="http://localhost:9090" label="Prometheus" hint="scrape /metrics" />
          </li>
        </ul>
        <p className="mt-4 text-2xs text-ink-muted">校验：<code className="text-brand">scripts/render_observability_topology.py</code> 输出 <code className="text-brand">observability_topology_report/v1</code>。</p>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader title="record-recovery /metrics 实时" description="同 /recovery/metrics 视图，方便此处对齐 panel。" />
        {q.isLoading ? <Skeleton className="h-48" /> : q.error ? <ErrorBanner title="无法读取" message={q.error.message} /> : <pre className="panel p-3 font-mono text-2xs overflow-x-auto max-h-[420px] whitespace-pre-wrap">{q.data}</pre>}
      </Card>
    </div>
  );
}

function ExternalLinkRow({ href, label, hint }: { href: string; label: string; hint: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="flex items-center gap-2 panel-soft p-3 rounded-lg hover:border-brand/40 transition-colors">
      <ExternalLink className="w-4 h-4 text-brand" />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold text-ink">{label}</div>
        <div className="text-2xs text-ink-muted">{hint}</div>
      </div>
      <span className="text-2xs text-ink-dim font-mono">{href.replace(/^https?:\/\//, "")}</span>
    </a>
  );
}

function ChaosTab() {
  const scenarios = [
    { id: "recovery_service_sigkill", desc: "spawn record-recovery HTTP service, simulate SIGKILL, assert clean transport-level error." },
    { id: "mtls_cert_expired", desc: "issue self-signed expired cert, assert ssl.SSLCertVerificationError." },
    { id: "audit_archive_unwritable", desc: "synthesize real audit_chain + seal, chmod 0 archive dir, assert non-zero exit + no partial write." },
    { id: "postgres_primary_killed", desc: "operator-environment only; skipped in default smoke." },
    { id: "audit_log_path_full", desc: "operator-environment only; skipped in default smoke." },
  ];

  return (
    <Card>
      <CardHeader title="Chaos drill" description="scripts/run_chaos_test.py 输出 chaos_test_report/v1。5 个场景 / 3 in-process / 2 operator-env-only。" />
      <ul className="space-y-2">
        {scenarios.map((s) => (
          <li key={s.id} className="panel-soft p-3 rounded-lg flex items-start gap-3">
            <Zap className="w-4 h-4 text-brand mt-0.5" />
            <div>
              <div className="font-mono text-2xs text-brand">{s.id}</div>
              <div className="text-2xs text-ink-muted mt-1">{s.desc}</div>
            </div>
          </li>
        ))}
      </ul>
      <pre className="mt-4 panel p-3 font-mono text-2xs overflow-x-auto">
{`# 默认 smoke
python3 scripts/run_chaos_test.py \\
  --scenarios all \\
  --assert-ok

# 单独一项
python3 scripts/run_chaos_test.py \\
  --scenarios mtls_cert_expired`}
      </pre>
    </Card>
  );
}
