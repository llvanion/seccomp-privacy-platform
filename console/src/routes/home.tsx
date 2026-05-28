import { Link } from "react-router-dom";
import { Activity, AlertTriangle, FileLock2, GanttChartSquare, KeyRound, Network, ShieldCheck, Timer } from "lucide-react";

import { operatorApi } from "@/api/operator";
import { healthApi } from "@/api/sidecars";
import { useApiQuery } from "@/hooks/useApi";
import { Button, Card, CardHeader, EmptyState, ErrorBanner, JsonBlock, PageHeader, Skeleton, StatTile, StatusPill, TagList, inferStatusKind } from "@/components/ui";
import { DataTable, type Column } from "@/components/data-table";
import type { OperatorDashboardData, OperatorJob, PlatformHealth } from "@/api/types";
import { formatDuration, formatNumber, formatRelativeTime, shortHash, truncate } from "@/lib/format";

export function HomeRoute() {
  const dashboardQ = useApiQuery<OperatorDashboardData>(
    ["operator", "dashboard"],
    () => operatorApi.dashboard(),
    { refetchInterval: 20_000 },
  );
  const healthQ = useApiQuery<PlatformHealth>(["platform", "health"], () => healthApi.platformHealth(), {
    retry: 0,
  });

  const data = dashboardQ.data;
  const recentJobs: OperatorJob[] = data?.recent_runs ?? data?.jobs ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="平台健康概览"
        description="跨租户的实时健康状态、最近 jobs、告警快照与关键控制入口。所有数据来自本地各 sidecar API。"
        actions={
          <>
            <Link to="/jobs/start"><Button variant="primary">启动新作业</Button></Link>
            <Link to="/requests/submit"><Button variant="secondary">提交请求</Button></Link>
          </>
        }
      />

      {dashboardQ.error && (
        <ErrorBanner
          title="无法读取 Operator Dashboard"
          message={dashboardQ.error.message}
          retry={() => dashboardQ.refetch()}
        />
      )}

      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile
          label="活跃作业"
          icon={<GanttChartSquare className="w-4 h-4" />}
          value={dashboardQ.isLoading ? <Skeleton className="h-7 w-20" /> : formatNumber(countJobsByState(recentJobs, ["running", "preparing", "queued"]))}
          hint="running / preparing"
          kind="warn"
        />
        <StatTile
          label="近 24h 成功率"
          icon={<ShieldCheck className="w-4 h-4" />}
          value={dashboardQ.isLoading ? <Skeleton className="h-7 w-20" /> : `${calcSuccessRate(recentJobs)}%`}
          hint="基于最近 runs"
          kind={calcSuccessRate(recentJobs) >= 90 ? "ok" : "warn"}
        />
        <StatTile
          label="告警"
          icon={<AlertTriangle className="w-4 h-4" />}
          value={dashboardQ.isLoading ? <Skeleton className="h-7 w-20" /> : formatNumber((data?.alerts ?? []).filter((a) => a.state === "firing").length)}
          hint="firing"
          kind={(data?.alerts ?? []).some((a) => a.state === "firing") ? "err" : "ok"}
        />
        <StatTile
          label="租户"
          icon={<Network className="w-4 h-4" />}
          value={dashboardQ.isLoading ? <Skeleton className="h-7 w-20" /> : truncate(data?.tenant_id ?? "default", 20)}
          hint="active tenant"
          kind="info"
        />
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2">
          <CardHeader
            title="最近作业"
            description="dashboard /v1/dashboard 返回的最近运行；点击行进入详情。"
            actions={<Link to="/jobs"><Button variant="ghost" size="sm">全部 →</Button></Link>}
          />
          {dashboardQ.isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-9" />
              <Skeleton className="h-9" />
              <Skeleton className="h-9" />
            </div>
          ) : recentJobs.length === 0 ? (
            <EmptyState title="还没有运行" description="启动一个新作业，或从 Settings 里指向已有的 history root。" />
          ) : (
            <RecentJobsTable rows={recentJobs.slice(0, 8)} />
          )}
        </Card>

        <Card>
          <CardHeader title="平台健康" description="component-level checks from /v1/platform-health" />
          {healthQ.isLoading && <Skeleton className="h-32" />}
          {healthQ.error && (
            <p className="text-2xs text-ink-muted">
              健康端点不可达：<span className="text-accent-warn">{healthQ.error.message}</span>
            </p>
          )}
          {healthQ.data && <HealthComponents data={healthQ.data} />}
        </Card>
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader
            title="活跃告警"
            description="firing 状态的 alerts；点击进入 Observability 查看 transition 历史。"
            actions={<Link to="/observability"><Button variant="ghost" size="sm">全部 →</Button></Link>}
          />
          {dashboardQ.isLoading ? (
            <Skeleton className="h-24" />
          ) : (data?.alerts ?? []).length === 0 ? (
            <EmptyState title="无告警" description="所有 alert rules 当前都处于 resolved。" />
          ) : (
            <ul className="divide-y divide-line-subtle">
              {(data!.alerts ?? []).slice(0, 6).map((a) => (
                <li key={a.id} className="py-2 flex items-start gap-3">
                  <StatusPill kind={a.state === "firing" ? "err" : "ok"}>{a.state}</StatusPill>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-ink truncate">{a.title}</div>
                    {a.summary && <div className="text-2xs text-ink-muted truncate">{a.summary}</div>}
                  </div>
                  <span className="text-2xs text-ink-muted shrink-0">
                    {a.triggered_at_utc ? formatRelativeTime(a.triggered_at_utc) : "—"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader title="主链路 contract 摘要" description="audit_chain.json 中嵌入的 mainline_contract_check/v1。" />
          {dashboardQ.isLoading ? (
            <Skeleton className="h-24" />
          ) : data?.audit_center ? (
            <JsonBlock data={data.audit_center} maxHeight="240px" />
          ) : (
            <EmptyState title="无 contract 摘要" description="还没有完成的运行，或当前 history root 里没有 audit_chain.json。" />
          )}
        </Card>
      </section>

      <section>
        <Card>
          <CardHeader
            title="关键能力快捷入口"
            description="按角色 / 任务类型聚合的导航。所有视图均来自本地 sidecar API，不出工作目录。"
          />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <QuickLink to="/jobs/start" icon={<GanttChartSquare className="w-4 h-4" />} label="启动主链路作业" hint="SSE → bridge → PJC → release" />
            <QuickLink to="/requests" icon={<Timer className="w-4 h-4" />} label="审批请求队列" hint="pending / approved / rejected" />
            <QuickLink to="/audit" icon={<FileLock2 className="w-4 h-4" />} label="审计中心" hint="chain, seal, archive, anchor" />
            <QuickLink to="/permissions" icon={<KeyRound className="w-4 h-4" />} label="权限 / 密钥" hint="OpenFGA / keyring / KMS" />
            <QuickLink to="/recovery" icon={<Network className="w-4 h-4" />} label="记录恢复 / mTLS" hint="service status + PJC mTLS" />
            <QuickLink to="/observability" icon={<Activity className="w-4 h-4" />} label="可观测性" hint="metrics, traces, chaos" />
            <QuickLink to="/security" icon={<ShieldCheck className="w-4 h-4" />} label="安全工具" hint="tamper, gate, benchmark" />
            <QuickLink to="/compliance" icon={<FileLock2 className="w-4 h-4" />} label="合规" hint="GDPR + threat model" />
          </div>
        </Card>
      </section>
    </div>
  );
}

function countJobsByState(rows: OperatorJob[], states: string[]): number {
  const set = new Set(states.map((s) => s.toLowerCase()));
  return rows.filter((r) => set.has((r.status ?? r.terminal_state ?? "").toLowerCase())).length;
}

function calcSuccessRate(rows: OperatorJob[]): number {
  const terminal = rows.filter((r) => ["succeeded", "success", "failed", "fail", "rejected"].includes((r.status ?? r.terminal_state ?? "").toLowerCase()));
  if (terminal.length === 0) return 100;
  const ok = terminal.filter((r) => ["succeeded", "success"].includes((r.status ?? r.terminal_state ?? "").toLowerCase())).length;
  return Math.round((ok / terminal.length) * 100);
}

function RecentJobsTable({ rows }: { rows: OperatorJob[] }) {
  const columns: Column<OperatorJob>[] = [
    {
      id: "job_id",
      header: "Job",
      cell: (r) => (
        <Link to={`/jobs/${encodeURIComponent(r.job_id)}`} className="text-brand hover:underline font-mono text-2xs">
          {shortHash(r.job_id, 10, 6)}
        </Link>
      ),
      sortKey: (r) => r.job_id,
    },
    {
      id: "status",
      header: "状态",
      cell: (r) => <StatusPill kind={inferStatusKind(r.status ?? r.terminal_state)}>{r.status ?? r.terminal_state ?? "unknown"}</StatusPill>,
      sortKey: (r) => r.status ?? r.terminal_state ?? "",
    },
    {
      id: "scope",
      header: "Scope",
      cell: (r) => <TagList items={[r.tenant_id, r.dataset_id, r.service_id]} />,
    },
    {
      id: "duration",
      header: "耗时",
      cell: (r) => formatDuration(r.elapsed_seconds ? r.elapsed_seconds * 1000 : null),
      sortKey: (r) => r.elapsed_seconds ?? 0,
    },
    {
      id: "started",
      header: "启动",
      cell: (r) => formatRelativeTime(r.started_at_utc),
      sortKey: (r) => r.started_at_utc ?? "",
    },
  ];
  return <DataTable rows={rows} columns={columns} rowKey={(r) => r.job_id} />;
}

function HealthComponents({ data }: { data: PlatformHealth }) {
  if (!data.components || data.components.length === 0) {
    return <p className="text-2xs text-ink-muted">没有 component 数据。</p>;
  }
  return (
    <ul className="space-y-2">
      {data.components.map((c) => (
        <li key={c.component} className="flex items-start gap-3">
          <StatusPill kind={inferStatusKind(c.status)}>{c.status}</StatusPill>
          <div className="flex-1 min-w-0">
            <div className="text-sm text-ink">{c.component}</div>
            {c.summary && <div className="text-2xs text-ink-muted">{c.summary}</div>}
          </div>
        </li>
      ))}
    </ul>
  );
}

function QuickLink({ to, icon, label, hint }: { to: string; icon: React.ReactNode; label: string; hint: string }) {
  return (
    <Link
      to={to}
      className="panel-soft p-3 flex items-start gap-3 hover:border-brand/40 transition-colors focus-ring rounded-card"
    >
      <div className="w-8 h-8 rounded-lg bg-brand/12 text-brand grid place-items-center">{icon}</div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-ink">{label}</div>
        <div className="text-2xs text-ink-muted">{hint}</div>
      </div>
    </Link>
  );
}
