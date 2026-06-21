import { useMemo, useState, type ReactNode } from "react";
import { CheckCircle2, Clock3, Eye, Filter, RefreshCw, Search, ShieldAlert, TimerOff, XCircle } from "lucide-react";

import { operatorApi } from "@/api/operator";
import type { Json, PrivacyBudgetApproval, PrivacyBudgetApprovalList, PrivacyBudgetApprovalTransition } from "@/api/types";
import { DataTable, type Column } from "@/components/data-table";
import { Modal } from "@/components/modal";
import { useApiMutation, useApiQuery } from "@/hooks/useApi";
import { useStoredState } from "@/hooks/useStoredState";
import { Button, Card, CardHeader, EmptyState, ErrorBanner, Field, Input, JsonDetails, KeyValueGrid, PageHeader, Select, Skeleton, StatusPill, Textarea, inferStatusKind } from "@/components/ui";
import { formatRelativeTime, formatTimestamp, shortHash, truncate } from "@/lib/format";

const STATUS_FILTERS = ["all", "pending_approval", "approved", "rejected", "expired", "consumed"] as const;
type ApprovalAction = "approve" | "reject" | "expire";

export function PrivacyBudgetApprovalsRoute() {
  const [status, setStatus] = useStoredState<string>("console.privacy_budget.status", "pending_approval");
  const [tenant, setTenant] = useStoredState("console.privacy_budget.tenant", "");
  const [caller, setCaller] = useStoredState("console.privacy_budget.caller", "");
  const [search, setSearch] = useStoredState("console.privacy_budget.search", "");
  const [selected, setSelected] = useStoredState<PrivacyBudgetApproval | null>("console.privacy_budget.selected", null);
  const [action, setAction] = useState<ApprovalAction | null>(null);
  const [reason, setReason] = useState("");
  const [expiresAt, setExpiresAt] = useState("");

  const query = useApiQuery<PrivacyBudgetApprovalList>(
    ["privacy-budget-approvals", { status, tenant, caller }],
    () =>
      operatorApi.listPrivacyBudgetApprovals({
        status: status === "all" ? undefined : status,
        tenant_id: tenant || undefined,
        caller: caller || undefined,
        limit: 200,
      }),
    { refetchInterval: 12_000 },
  );

  const transition = useApiMutation<PrivacyBudgetApprovalTransition, { request: PrivacyBudgetApproval; action: ApprovalAction; reason: string; expires_at_utc?: string }>(
    ({ request, action, reason, expires_at_utc }) => {
      const payload: Record<string, Json> = {};
      if (reason.trim()) payload.reason = reason.trim();
      if (expires_at_utc?.trim()) payload.expires_at_utc = expires_at_utc.trim();
      if (action === "approve") return operatorApi.approvePrivacyBudgetApproval(request.request_id, payload);
      if (action === "reject") return operatorApi.rejectPrivacyBudgetApproval(request.request_id, payload);
      return operatorApi.expirePrivacyBudgetApproval(request.request_id, payload);
    },
    {
      successToast: "审批状态已更新",
      onSuccess: (data) => {
        setSelected(data.approval);
        setAction(null);
        setReason("");
        setExpiresAt("");
        query.refetch();
      },
    },
  );

  const approvals = query.data?.requests ?? [];
  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return approvals;
    return approvals.filter((item) =>
      [
        item.request_id,
        item.caller,
        item.tenant_id,
        item.dataset_id,
        item.purpose,
        item.job_id,
        item.query_fingerprint,
        item.reason_code,
        item.matched_prior_relation,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle)),
    );
  }, [approvals, search]);

  const counts = useMemo(
    () => ({
      pending: approvals.filter((item) => item.status === "pending_approval").length,
      approved: approvals.filter((item) => item.status === "approved").length,
      rejected: approvals.filter((item) => item.status === "rejected").length,
      expired: approvals.filter((item) => item.status === "expired").length,
    }),
    [approvals],
  );

  const openAction = (request: PrivacyBudgetApproval, nextAction: ApprovalAction) => {
    setSelected(request);
    setAction(nextAction);
    setReason("");
    setExpiresAt(nextAction === "approve" ? request.expires_at_utc ?? "" : "");
  };

  const activeAction = action && selected ? action : null;
  const actionNeedsReason = activeAction === "reject" || activeAction === "expire";
  const actionDisabled = !selected || (actionNeedsReason && !reason.trim());

  return (
    <div className="space-y-5">
      <PageHeader
        title="隐私预算审批"
        description="Review near-duplicate / differencing approval requests; approve/reject/expire transitions write privacy_budget_approval_decision/v1 evidence."
        actions={
          <Button variant="ghost" leftIcon={<RefreshCw className="w-4 h-4" />} onClick={() => query.refetch()} loading={query.isFetching}>
            刷新
          </Button>
        }
      />

      <section className="grid grid-cols-1 sm:grid-cols-4 gap-3">
        <StatusTile kind="warn" icon={<Clock3 className="w-4 h-4" />} label="待复核" count={counts.pending} />
        <StatusTile kind="ok" icon={<CheckCircle2 className="w-4 h-4" />} label="已批准" count={counts.approved} />
        <StatusTile kind="err" icon={<XCircle className="w-4 h-4" />} label="已拒绝" count={counts.rejected} />
        <StatusTile kind="muted" icon={<TimerOff className="w-4 h-4" />} label="已过期" count={counts.expired} />
      </section>

      {query.error && (
        <ErrorBanner
          title="加载失败"
          message={query.error.message === "privacy_budget_approval_unavailable"
            ? "隐私预算审批 API 当前不可用。请确认主面板已用最新答辩 demo 重启，或直接访问 18194 端口那套审批面板。"
            : query.error.message}
          retry={() => query.refetch()}
        />
      )}

      <Card>
        <CardHeader title="过滤" actions={<Filter className="w-4 h-4 text-ink-dim" />} />
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <Field label="状态">
            <Select value={status} onChange={(event) => setStatus(event.target.value)}>
              {STATUS_FILTERS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="租户">
            <Input value={tenant} onChange={(event) => setTenant(event.target.value)} placeholder="tenant_id" />
          </Field>
          <Field label="Caller">
            <Input value={caller} onChange={(event) => setCaller(event.target.value)} placeholder="caller" />
          </Field>
          <Field label="关键字">
            <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="request / job / fingerprint" />
          </Field>
        </div>
      </Card>

      <section className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_380px] gap-4">
        <Card>
          <CardHeader title={`审批队列（${filtered.length} / ${approvals.length}）`} description="行内操作只对 pending_approval 有效；同一 resolved caller 自批会在服务端返回 403。" />
          {query.isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-9" />
              <Skeleton className="h-9" />
              <Skeleton className="h-9" />
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState icon={<Search className="w-5 h-5" />} title="无匹配审批请求" description="调整过滤器或等待 policy_release 写入新的 near-duplicate approval queue。" />
          ) : (
            <ApprovalsTable rows={filtered} selectedId={selected?.request_id} onInspect={setSelected} onAction={openAction} />
          )}
        </Card>

        <Card>
          <CardHeader title="请求详情" actions={selected && <StatusPill kind={inferStatusKind(selected.status)}>{selected.status}</StatusPill>} />
          {selected ? (
            <div className="space-y-4">
              <KeyValueGrid
                columns={2}
                items={[
                  { label: "request_id", value: selected.request_id },
                  { label: "status", value: selected.status },
                  { label: "caller", value: selected.caller ?? "—" },
                  { label: "job_id", value: selected.job_id ?? "—" },
                  { label: "tenant", value: selected.tenant_id ?? "—" },
                  { label: "dataset", value: selected.dataset_id ?? "—" },
                  { label: "purpose", value: selected.purpose ?? "—" },
                  { label: "created_at", value: formatTimestamp(selected.created_at_utc ?? selected.requested_at_utc) },
                ]}
              />
              <Card className="p-3">
                <CardHeader title="审查结论" className="mb-2 pb-2" />
                <KeyValueGrid
                  columns={2}
                  items={[
                    { label: "reason_code", value: selected.reason_code ?? "—" },
                    { label: "relation", value: selected.matched_prior_relation ?? "—" },
                    { label: "abuse_signal", value: selected.abuse_signal ?? "—" },
                    { label: "fingerprint", value: shortHash(selected.query_fingerprint ?? "—", 10, 6) },
                  ]}
                />
              </Card>
              <div>
                <div className="field-label mb-1.5">Budget</div>
                <KeyValueGrid
                  columns={2}
                  items={[
                    { label: "limit", value: String((selected.budget as Record<string, unknown> | undefined)?.limit ?? "—") },
                    { label: "cost", value: String((selected.budget as Record<string, unknown> | undefined)?.cost ?? "—") },
                    { label: "used_before", value: String((selected.budget as Record<string, unknown> | undefined)?.used_before ?? "—") },
                    { label: "used_after", value: String((selected.budget as Record<string, unknown> | undefined)?.used_after ?? "—") },
                  ]}
                />
                <JsonDetails title="查看完整 budget JSON" data={selected.budget ?? {}} maxHeight="160px" />
              </div>
              <div>
                <div className="field-label mb-1.5">Latest decision</div>
                <JsonDetails title="查看最近一次决策 JSON" data={selected.latest_decision ?? {}} maxHeight="220px" defaultOpen />
              </div>
              <JsonDetails title="查看完整审批请求 JSON" data={selected} maxHeight="260px" />
            </div>
          ) : (
            <EmptyState icon={<Eye className="w-5 h-5" />} title="选择一条审批请求" description="详情会显示 scope、fingerprint、budget 与最近一次决策。" />
          )}
        </Card>
      </section>

      <Modal
        open={!!activeAction}
        onClose={() => setAction(null)}
        title={activeAction ? actionTitle(activeAction) : undefined}
        description={selected ? `${selected.request_id} · ${selected.caller ?? "unknown caller"}` : undefined}
        footer={
          <>
            <Button variant="ghost" onClick={() => setAction(null)}>
              取消
            </Button>
            <Button
              variant={activeAction === "approve" ? "primary" : "danger"}
              loading={transition.isPending}
              disabled={actionDisabled}
              onClick={() => selected && activeAction && transition.mutate({ request: selected, action: activeAction, reason, expires_at_utc: expiresAt || undefined })}
            >
              {activeAction ? actionVerb(activeAction) : "提交"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {activeAction === "approve" && (
            <div className="rounded-lg border border-accent-warn/30 bg-accent-warn/8 p-3 text-2xs text-ink-muted flex gap-2">
              <ShieldAlert className="w-4 h-4 text-accent-warn shrink-0 mt-0.5" />
              <span>Approve only after checking the overlap relation and requester scope. The server will reject same-identity approval.</span>
            </div>
          )}
          <Field label={actionNeedsReason ? "理由" : "理由"} hint={actionNeedsReason ? "reject / expire 必填" : "可选，写入 decision.reason"}>
            <Textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="manual review result" />
          </Field>
          <Field label="Expires at UTC" hint="approve 可选；expire 留空时服务端会使用当前时间">
            <Input value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} placeholder="2026-12-31T00:00:00Z" />
          </Field>
          {selected && <JsonDetails title="查看完整审批请求 JSON" data={selected} maxHeight="260px" />}
        </div>
      </Modal>
    </div>
  );
}

function ApprovalsTable({
  rows,
  selectedId,
  onInspect,
  onAction,
}: {
  rows: PrivacyBudgetApproval[];
  selectedId?: string;
  onInspect: (row: PrivacyBudgetApproval) => void;
  onAction: (row: PrivacyBudgetApproval, action: ApprovalAction) => void;
}) {
  const columns: Column<PrivacyBudgetApproval>[] = [
    {
      id: "request",
      header: "Request",
      cell: (row) => (
        <button className="font-mono text-2xs text-brand hover:underline" onClick={() => onInspect(row)}>
          {shortHash(row.request_id, 10, 4)}
        </button>
      ),
      sortKey: (row) => row.request_id,
    },
    {
      id: "status",
      header: "状态",
      cell: (row) => <StatusPill kind={inferStatusKind(row.status)}>{row.status}</StatusPill>,
      sortKey: (row) => row.status,
    },
    {
      id: "scope",
      header: "Scope",
      cell: (row) => (
        <span className="text-2xs text-ink-muted">
          {truncate(`${row.tenant_id ?? "?"} · ${row.dataset_id ?? "?"} · ${row.purpose ?? "?"}`, 44)}
        </span>
      ),
      sortKey: (row) => `${row.tenant_id ?? ""}:${row.dataset_id ?? ""}:${row.purpose ?? ""}`,
    },
    {
      id: "caller",
      header: "Caller",
      cell: (row) => <span className="font-mono text-2xs text-ink-muted">{row.caller ?? "—"}</span>,
      sortKey: (row) => row.caller ?? "",
    },
    {
      id: "relation",
      header: "Relation",
      cell: (row) => <span className="text-2xs">{row.matched_prior_relation ?? "—"}</span>,
      sortKey: (row) => row.matched_prior_relation ?? "",
    },
    {
      id: "created",
      header: "Created",
      cell: (row) => <span className="text-2xs">{formatRelativeTime(row.created_at_utc ?? row.requested_at_utc)}</span>,
      sortKey: (row) => row.created_at_utc ?? row.requested_at_utc ?? "",
    },
    {
      id: "actions",
      header: "操作",
      className: "whitespace-nowrap",
      cell: (row) => {
        const pending = row.status === "pending_approval";
        return (
          <div className="flex items-center gap-1">
            <Button size="sm" variant={selectedId === row.request_id ? "primary" : "ghost"} onClick={() => onInspect(row)} leftIcon={<Eye className="w-3.5 h-3.5" />}>
              查看
            </Button>
            <Button size="sm" variant="primary" disabled={!pending} onClick={() => onAction(row, "approve")} leftIcon={<CheckCircle2 className="w-3.5 h-3.5" />}>
              批准
            </Button>
            <Button size="sm" variant="danger" disabled={!pending} onClick={() => onAction(row, "reject")} leftIcon={<XCircle className="w-3.5 h-3.5" />}>
              拒绝
            </Button>
            <Button size="sm" variant="outline" disabled={!pending && row.status !== "approved"} onClick={() => onAction(row, "expire")} leftIcon={<TimerOff className="w-3.5 h-3.5" />}>
              过期
            </Button>
          </div>
        );
      },
    },
  ];
  return <DataTable rows={rows} columns={columns} rowKey={(row) => row.request_id} initialSort={{ id: "created", dir: "desc" }} />;
}

function StatusTile({ kind, icon, label, count }: { kind: "warn" | "ok" | "err" | "muted"; icon: ReactNode; label: string; count: number }) {
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

function actionTitle(action: ApprovalAction): string {
  if (action === "approve") return "批准隐私预算审批";
  if (action === "reject") return "拒绝隐私预算审批";
  return "使隐私预算审批过期";
}

function actionVerb(action: ApprovalAction): string {
  if (action === "approve") return "批准";
  if (action === "reject") return "拒绝";
  return "过期";
}
