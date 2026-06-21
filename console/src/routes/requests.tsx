import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, ClipboardList, Filter, Plus, RefreshCw, XCircle } from "lucide-react";

import { operatorApi } from "@/api/operator";
import { useApiQuery } from "@/hooks/useApi";
import { useStoredState } from "@/hooks/useStoredState";
import { Button, Card, CardHeader, EmptyState, ErrorBanner, Field, Input, JsonDetails, KeyValueGrid, PageHeader, Select, Skeleton, StatusPill, inferStatusKind } from "@/components/ui";
import { DataTable, type Column } from "@/components/data-table";
import { formatRelativeTime, formatTimestamp, shortHash, truncate } from "@/lib/format";
import type { RequestSubmission } from "@/api/types";

const STATUS_FILTERS = ["all", "pending_approval", "approved", "rejected"] as const;

export function RequestsRoute() {
  const [status, setStatus] = useStoredState<string>("console.requests.status", "all");
  const [search, setSearch] = useStoredState("console.requests.search", "");
  const [tenant, setTenant] = useStoredState("console.requests.tenant", "");
  const [selectedId, setSelectedId] = useStoredState<string | null>("console.requests.selected_id", null);

  const query = useApiQuery<{ submissions: RequestSubmission[] }>(
    ["requests", { status, tenant }],
    () => operatorApi.listRequests({ status: status === "all" ? undefined : status, tenant_id: tenant || undefined, limit: 200 }),
    { refetchInterval: 12_000 },
  );

  const submissions = query.data?.submissions ?? [];
  const filtered = useMemo(() => {
    if (!search.trim()) return submissions;
    const lc = search.trim().toLowerCase();
    return submissions.filter((s) =>
      [s.submission_id, s.caller, s.dataset_id, s.service_id, s.submitted_by].filter(Boolean).some((v) => v!.toLowerCase().includes(lc)),
    );
  }, [submissions, search]);

  const counts = useMemo(
    () => ({
      pending: submissions.filter((s) => s.status === "pending_approval").length,
      approved: submissions.filter((s) => s.status === "approved").length,
      rejected: submissions.filter((s) => s.status === "rejected").length,
    }),
    [submissions],
  );
  const selected = filtered.find((item) => item.submission_id === selectedId) ?? submissions.find((item) => item.submission_id === selectedId) ?? filtered[0] ?? null;

  return (
    <div className="space-y-5">
      <PageHeader
        title="请求工作流 Requests"
        description="提交、列出、批准、拒绝隐私查询请求。带 platform_admin / privacy_operator 角色校验与 same-identity self-approval 拦截。"
        actions={
          <>
            <Button variant="ghost" leftIcon={<RefreshCw className="w-4 h-4" />} onClick={() => query.refetch()} loading={query.isFetching}>
              刷新
            </Button>
            <Link to="/requests/submit">
              <Button variant="primary" leftIcon={<Plus className="w-4 h-4" />}>
                提交请求
              </Button>
            </Link>
          </>
        }
      />

      <section className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <StatusTile kind="warn" icon={<ClipboardList className="w-4 h-4" />} label="待审批" count={counts.pending} />
        <StatusTile kind="ok" icon={<CheckCircle2 className="w-4 h-4" />} label="已批准" count={counts.approved} />
        <StatusTile kind="err" icon={<XCircle className="w-4 h-4" />} label="已拒绝" count={counts.rejected} />
      </section>

      {query.error && <ErrorBanner title="加载失败" message={query.error.message} retry={() => query.refetch()} />}

      <Card>
        <CardHeader title="过滤" actions={<Filter className="w-4 h-4 text-ink-dim" />} />
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Field label="状态">
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUS_FILTERS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="租户">
            <Input value={tenant} onChange={(e) => setTenant(e.target.value)} placeholder="tenant_id" />
          </Field>
          <Field label="关键字">
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="caller / submission_id / dataset" />
          </Field>
        </div>
      </Card>

      <section className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_420px] gap-4">
        <Card>
          <CardHeader title={`请求列表（${filtered.length} / ${submissions.length}）`} />
          {query.isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-9" />
              <Skeleton className="h-9" />
              <Skeleton className="h-9" />
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState title="无匹配请求" description="改一下过滤器，或提交一个新请求。" action={
              <Link to="/requests/submit"><Button variant="primary">提交请求</Button></Link>
            } />
          ) : (
            <RequestsTable rows={filtered} selectedId={selected?.submission_id ?? null} onSelect={setSelectedId} />
          )}
        </Card>

        <Card>
          <CardHeader title="请求详情" actions={selected ? <StatusPill kind={inferStatusKind(selected.status)}>{selected.status}</StatusPill> : undefined} />
          {selected ? (
            <div className="space-y-4">
              <KeyValueGrid
                columns={2}
                items={[
                  { label: "submission_id", value: selected.submission_id },
                  { label: "status", value: selected.status },
                  { label: "caller", value: selected.caller ?? selected.submitted_by ?? "—" },
                  { label: "submitted_at", value: formatTimestamp(selected.submitted_at_utc) },
                  { label: "tenant", value: selected.tenant_id ?? "—" },
                  { label: "dataset", value: selected.dataset_id ?? "—" },
                  { label: "service", value: selected.service_id ?? "—" },
                  { label: "submitted_by", value: selected.submitted_by ?? "—" },
                ]}
              />
              <JsonDetails title="查看 request JSON" data={selected.request ?? {}} maxHeight="260px" />
              <div className="flex gap-2">
                <Link to={`/requests/${encodeURIComponent(selected.submission_id)}`}>
                  <Button variant="primary">进入详情页</Button>
                </Link>
              </div>
            </div>
          ) : (
            <EmptyState title="选择一条请求" description="右侧会展示 scope、提交人、原始 request 与跳转入口。" />
          )}
        </Card>
      </section>
    </div>
  );
}

function StatusTile({ kind, icon, label, count }: { kind: "warn" | "ok" | "err"; icon: ReactNode; label: string; count: number }) {
  return (
    <Card className="flex items-center gap-3">
      <div className="w-10 h-10 rounded-xl bg-bg-elevated grid place-items-center text-brand">{icon}</div>
      <div className="flex-1 min-w-0">
        <div className="field-label">{label}</div>
        <div className="text-2xl font-bold text-ink">{count}</div>
      </div>
      <StatusPill kind={kind}>{kind}</StatusPill>
    </Card>
  );
}

function RequestsTable({ rows, selectedId, onSelect }: { rows: RequestSubmission[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const columns: Column<RequestSubmission>[] = [
    {
      id: "id",
      header: "Submission",
      cell: (r) => (
        <button onClick={() => onSelect(r.submission_id)} className="text-brand hover:underline font-mono text-2xs">
          {shortHash(r.submission_id, 12, 4)}
        </button>
      ),
      sortKey: (r) => r.submission_id,
    },
    {
      id: "status",
      header: "状态",
      cell: (r) => <StatusPill kind={inferStatusKind(r.status)}>{r.status}</StatusPill>,
      sortKey: (r) => r.status,
    },
    {
      id: "caller",
      header: "Caller",
      cell: (r) => <span className="font-mono text-ink-muted text-2xs">{r.caller ?? r.submitted_by ?? "—"}</span>,
      sortKey: (r) => r.caller ?? r.submitted_by ?? "",
    },
    {
      id: "scope",
      header: "Scope",
      cell: (r) => <span className="text-2xs text-ink-muted">{truncate(`${r.tenant_id ?? "?"} · ${r.dataset_id ?? "?"} / ${r.service_id ?? "?"}`, 36)}</span>,
    },
    {
      id: "submitted",
      header: "提交",
      cell: (r) => <span className="text-2xs">{formatTimestamp(r.submitted_at_utc)}</span>,
      sortKey: (r) => r.submitted_at_utc,
    },
    {
      id: "age",
      header: "Age",
      cell: (r) => <span className="text-2xs text-ink-muted">{formatRelativeTime(r.submitted_at_utc)}</span>,
      sortKey: (r) => r.submitted_at_utc,
    },
    {
      id: "view",
      header: "查看",
      cell: (r) => (
        <Button size="sm" variant={selectedId === r.submission_id ? "primary" : "ghost"} onClick={() => onSelect(r.submission_id)}>
          选择
        </Button>
      ),
    },
  ];
  return <DataTable rows={rows} columns={columns} rowKey={(r) => r.submission_id} initialSort={{ id: "submitted", dir: "desc" }} />;
}
