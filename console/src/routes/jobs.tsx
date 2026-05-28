import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Filter, Plus, RefreshCw } from "lucide-react";

import { operatorApi } from "@/api/operator";
import { useApiQuery } from "@/hooks/useApi";
import type { OperatorDashboardData, OperatorJob } from "@/api/types";
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  Field,
  Input,
  PageHeader,
  Select,
  Skeleton,
  StatusPill,
  TagList,
  inferStatusKind,
} from "@/components/ui";
import { DataTable, type Column } from "@/components/data-table";
import { formatDuration, formatRelativeTime, shortHash } from "@/lib/format";

const STATUS_OPTIONS = [
  "all",
  "running",
  "succeeded",
  "failed",
  "preparing",
  "queued",
  "released",
] as const;

export function JobsRoute() {
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [tenantFilter, setTenantFilter] = useState("");

  const dashboardQ = useApiQuery<OperatorDashboardData>(["operator", "dashboard"], () => operatorApi.dashboard(), {
    refetchInterval: 15_000,
  });

  const jobs: OperatorJob[] = dashboardQ.data?.jobs ?? dashboardQ.data?.recent_runs ?? [];

  const filtered = useMemo(() => {
    const lcSearch = search.trim().toLowerCase();
    const lcTenant = tenantFilter.trim().toLowerCase();
    return jobs.filter((j) => {
      const status = (j.status ?? j.terminal_state ?? "").toLowerCase();
      if (statusFilter !== "all" && status !== statusFilter) return false;
      if (lcSearch) {
        const haystack = [j.job_id, j.caller, j.dataset_id, j.service_id, j.tenant_id].filter(Boolean).join(" ").toLowerCase();
        if (!haystack.includes(lcSearch)) return false;
      }
      if (lcTenant && (j.tenant_id ?? "").toLowerCase() !== lcTenant) return false;
      return true;
    });
  }, [jobs, statusFilter, search, tenantFilter]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="作业 Jobs"
        description="SSE → bridge → PJC → release 主链路的运行历史。支持过滤、租户聚合、stage 时序与结果 JSON 查看。"
        actions={
          <>
            <Button variant="ghost" leftIcon={<RefreshCw className="w-4 h-4" />} onClick={() => dashboardQ.refetch()} loading={dashboardQ.isFetching}>
              刷新
            </Button>
            <Link to="/jobs/start">
              <Button variant="primary" leftIcon={<Plus className="w-4 h-4" />}>
                启动作业
              </Button>
            </Link>
          </>
        }
      />

      {dashboardQ.error && <ErrorBanner title="加载失败" message={dashboardQ.error.message} retry={() => dashboardQ.refetch()} />}

      <Card>
        <CardHeader title="过滤器" description="按状态、租户、关键字快速定位。" actions={<Filter className="w-4 h-4 text-ink-dim" />} />
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Field label="状态">
            <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="租户">
            <Input
              placeholder="tenant_id 精确匹配"
              value={tenantFilter}
              onChange={(e) => setTenantFilter(e.target.value)}
            />
          </Field>
          <Field label="关键字">
            <Input
              placeholder="job_id / caller / dataset 模糊匹配"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </Field>
        </div>
      </Card>

      <Card>
        <CardHeader
          title={`作业列表（${filtered.length} / ${jobs.length}）`}
          description="点击 job_id 进入详细 stage 时序、mainline contract 摘要、结果 JSON 视图。"
        />
        {dashboardQ.isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-9" />
            <Skeleton className="h-9" />
            <Skeleton className="h-9" />
            <Skeleton className="h-9" />
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            title="无匹配作业"
            description={jobs.length === 0 ? "history root 当前为空。" : "调整过滤器或换个时间窗口。"}
            action={
              <Link to="/jobs/start">
                <Button variant="primary">启动一个作业</Button>
              </Link>
            }
          />
        ) : (
          <JobsTable rows={filtered} />
        )}
      </Card>
    </div>
  );
}

function JobsTable({ rows }: { rows: OperatorJob[] }) {
  const columns: Column<OperatorJob>[] = [
    {
      id: "job_id",
      header: "Job",
      cell: (r) => (
        <Link to={`/jobs/${encodeURIComponent(r.job_id)}`} className="text-brand hover:underline font-mono text-2xs">
          {shortHash(r.job_id, 12, 6)}
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
      id: "tenant",
      header: "Scope",
      cell: (r) => <TagList items={[r.tenant_id, r.dataset_id, r.service_id]} />,
      sortKey: (r) => r.tenant_id ?? "",
    },
    {
      id: "caller",
      header: "Caller",
      cell: (r) => <span className="text-ink-muted text-2xs font-mono">{r.caller ?? "—"}</span>,
      sortKey: (r) => r.caller ?? "",
    },
    {
      id: "duration",
      header: "耗时",
      cell: (r) => formatDuration(r.elapsed_seconds ? r.elapsed_seconds * 1000 : null),
      sortKey: (r) => r.elapsed_seconds ?? 0,
    },
    {
      id: "exit",
      header: "Exit",
      cell: (r) => (r.exit_code === null || r.exit_code === undefined ? "—" : String(r.exit_code)),
      sortKey: (r) => r.exit_code ?? 0,
    },
    {
      id: "started",
      header: "启动",
      cell: (r) => formatRelativeTime(r.started_at_utc),
      sortKey: (r) => r.started_at_utc ?? "",
    },
    {
      id: "finished",
      header: "结束",
      cell: (r) => formatRelativeTime(r.finished_at_utc),
      sortKey: (r) => r.finished_at_utc ?? "",
    },
  ];
  return <DataTable rows={rows} columns={columns} rowKey={(r) => r.job_id} initialSort={{ id: "started", dir: "desc" }} />;
}
