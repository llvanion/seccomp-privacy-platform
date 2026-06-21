import { useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, XCircle, RefreshCw } from "lucide-react";

import { operatorApi } from "@/api/operator";
import { useApiMutation, useApiQuery } from "@/hooks/useApi";
import { Button, Card, CardHeader, ErrorBanner, Field, Input, JsonDetails, PageHeader, Skeleton, StatusPill, Textarea, inferStatusKind } from "@/components/ui";
import { formatTimestamp, shortHash } from "@/lib/format";
import type { RequestSubmission } from "@/api/types";

export function RequestDetailRoute() {
  const { submissionId } = useParams<{ submissionId: string }>();
  const id = submissionId ?? "";

  const detailQ = useApiQuery<RequestSubmission>(["request", id], () => operatorApi.getRequest(id), {
    enabled: !!id,
    refetchInterval: 8_000,
  });

  const approve = useApiMutation(
    (vars: { reason?: string; actor?: string }) =>
      operatorApi.approveRequest(id, vars as Record<string, never>),
    {
      successToast: "已批准",
      onSuccess: () => detailQ.refetch(),
    },
  );

  const reject = useApiMutation(
    (vars: { reason?: string; actor?: string }) =>
      operatorApi.rejectRequest(id, vars as Record<string, never>),
    {
      successToast: "已拒绝",
      onSuccess: () => detailQ.refetch(),
    },
  );

  const [reason, setReason] = useState("");
  const [actor, setActor] = useState("");

  const submission = detailQ.data;
  const pending = submission?.status === "pending_approval";

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={
          <Link to="/requests" className="hover:text-ink inline-flex items-center gap-1">
            <ArrowLeft className="w-3 h-3" />
            请求列表
          </Link>
        }
        title={<span className="font-mono">{shortHash(id, 14, 6)}</span>}
        description={submission ? `${submission.submitted_by ?? "?"} · ${submission.caller ?? "?"}` : undefined}
        actions={
          <Button variant="ghost" leftIcon={<RefreshCw className="w-4 h-4" />} onClick={() => detailQ.refetch()} loading={detailQ.isFetching}>
            刷新
          </Button>
        }
      />

      {detailQ.error && <ErrorBanner title="加载失败" message={detailQ.error.message} retry={() => detailQ.refetch()} />}

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card>
          <CardHeader title="状态" />
          {detailQ.isLoading ? (
            <Skeleton className="h-32" />
          ) : submission ? (
            <dl className="grid grid-cols-2 gap-y-2 text-2xs">
              <Row label="状态">
                <StatusPill kind={inferStatusKind(submission.status)}>{submission.status}</StatusPill>
              </Row>
              <Row label="Submission">
                <span className="font-mono">{submission.submission_id}</span>
              </Row>
              <Row label="提交时间">{formatTimestamp(submission.submitted_at_utc)}</Row>
              <Row label="提交人">
                <span className="font-mono">{submission.submitted_by ?? "—"}</span>
              </Row>
              <Row label="Caller">
                <span className="font-mono">{submission.caller ?? "—"}</span>
              </Row>
              <Row label="租户 / 数据集 / 服务">
                <span className="text-ink-muted">
                  {submission.tenant_id ?? "?"} · {submission.dataset_id ?? "?"} / {submission.service_id ?? "?"}
                </span>
              </Row>
            </dl>
          ) : null}
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="决策" description="approve / reject 写入 control_plane_mutations，并启动作业（仅 approve 时）。" />
          {!pending && (
            <p className="text-2xs text-ink-muted">当前状态为 <b>{submission?.status}</b>，无可执行操作。</p>
          )}
          {pending && (
            <div className="space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Field label="审批人 actor">
                  <Input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="operator/identity" />
                </Field>
                <Field label="理由" hint="可选，会写入 transitions">
                  <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="reason" />
                </Field>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="primary"
                  leftIcon={<CheckCircle2 className="w-4 h-4" />}
                  loading={approve.isPending}
                  onClick={() => approve.mutate({ reason: reason || undefined, actor: actor || undefined })}
                >
                  批准
                </Button>
                <Button
                  variant="danger"
                  leftIcon={<XCircle className="w-4 h-4" />}
                  loading={reject.isPending}
                  onClick={() => reject.mutate({ reason: reason || undefined, actor: actor || undefined })}
                >
                  拒绝
                </Button>
              </div>
            </div>
          )}
        </Card>
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader title="转换历史" description="approve/reject 等 transitions，倒序展示。" />
          {submission?.transitions && submission.transitions.length > 0 ? (
            <ul className="relative pl-6 border-l border-line-subtle space-y-3">
              {[...submission.transitions].reverse().map((t, i) => (
                <li key={i} className="relative">
                  <span className="absolute -left-[27px] top-1 w-3 h-3 rounded-full bg-brand ring-2 ring-bg-panel" />
                  <div className="flex justify-between items-baseline gap-2">
                    <div className="text-sm font-semibold text-ink">{t.event}</div>
                    <div className="text-2xs text-ink-muted">{formatTimestamp(t.at_utc)}</div>
                  </div>
                  <div className="text-2xs text-ink-muted mt-0.5">
                    state <StatusPill kind={inferStatusKind(t.state)} className="ml-1">{t.state}</StatusPill>
                    {t.actor && <span className="ml-2 font-mono">by {t.actor}</span>}
                  </div>
                  {t.reason && <div className="text-2xs text-ink-muted mt-1 italic">{t.reason}</div>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-2xs text-ink-muted">尚无 transitions。</p>
          )}
        </Card>

        <Card>
          <CardHeader title="原始请求 payload" />
          <JsonDetails title="查看原始请求 JSON" data={submission?.request ?? {}} maxHeight="320px" defaultOpen />
        </Card>
      </section>
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="text-ink">{children}</dd>
    </>
  );
}
