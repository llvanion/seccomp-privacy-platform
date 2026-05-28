import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, RefreshCw, PlayCircle } from "lucide-react";

import { operatorApi } from "@/api/operator";
import { useApiMutation, useApiQuery } from "@/hooks/useApi";
import { Button, Card, CardHeader, EmptyState, ErrorBanner, JsonBlock, PageHeader, Skeleton, StatusPill, TagList, inferStatusKind } from "@/components/ui";
import { formatDuration, formatRelativeTime, formatTimestamp, shortHash } from "@/lib/format";
import type { OperatorJob, Json } from "@/api/types";

export function JobDetailRoute() {
  const { jobId } = useParams<{ jobId: string }>();
  const decodedId = jobId ?? "";

  const jobQ = useApiQuery<OperatorJob>(["job", decodedId], () => operatorApi.getJob(decodedId), {
    enabled: !!decodedId,
    refetchInterval: 10_000,
  });
  const resultQ = useApiQuery<Record<string, Json>>(["job-result", decodedId], () => operatorApi.getJobResult(decodedId), {
    enabled: !!decodedId,
    retry: false,
  });

  const relaunch = useApiMutation(
    (payload: Record<string, Json>) => operatorApi.relaunchJob(decodedId, payload),
    {
      successToast: "重新发起作业成功",
      onSuccess: () => {
        jobQ.refetch();
      },
    },
  );

  const job = jobQ.data;

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={
          <Link to="/jobs" className="hover:text-ink inline-flex items-center gap-1">
            <ArrowLeft className="w-3 h-3" />
            作业列表
          </Link>
        }
        title={
          <span className="font-mono text-xl">
            {decodedId ? shortHash(decodedId, 18, 8) : "—"}
          </span>
        }
        description={job ? `${job.caller ?? "?"} · ${job.tenant_id ?? "?"} / ${job.dataset_id ?? "?"}` : undefined}
        actions={
          <>
            <Button variant="ghost" leftIcon={<RefreshCw className="w-4 h-4" />} onClick={() => jobQ.refetch()} loading={jobQ.isFetching}>
              刷新
            </Button>
            <Button
              variant="primary"
              leftIcon={<PlayCircle className="w-4 h-4" />}
              onClick={() => relaunch.mutate({})}
              loading={relaunch.isPending}
            >
              重新启动
            </Button>
          </>
        }
      />

      {jobQ.error && <ErrorBanner title="加载失败" message={jobQ.error.message} retry={() => jobQ.refetch()} />}

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card>
          <CardHeader title="基本信息" />
          {jobQ.isLoading ? (
            <Skeleton className="h-32" />
          ) : job ? (
            <dl className="grid grid-cols-2 gap-y-2 text-2xs">
              <Row label="状态">
                <StatusPill kind={inferStatusKind(job.status ?? job.terminal_state)}>
                  {job.status ?? job.terminal_state ?? "unknown"}
                </StatusPill>
              </Row>
              <Row label="退出码">{job.exit_code ?? "—"}</Row>
              <Row label="耗时">{formatDuration(job.elapsed_seconds ? job.elapsed_seconds * 1000 : null)}</Row>
              <Row label="启动">{formatTimestamp(job.started_at_utc)}</Row>
              <Row label="结束">{formatTimestamp(job.finished_at_utc)}</Row>
              <Row label="Scope">
                <TagList items={[job.tenant_id, job.dataset_id, job.service_id]} />
              </Row>
              <Row label="Caller">
                <span className="font-mono text-ink-muted">{job.caller ?? "—"}</span>
              </Row>
              <Row label="History">
                <span className="font-mono text-ink-muted truncate">{job.history_root ?? "—"}</span>
              </Row>
            </dl>
          ) : null}
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="Stage 时序" description="audit chain 衍生的 stage_status 行；duration 取自上报值。" />
          {jobQ.isLoading ? (
            <Skeleton className="h-32" />
          ) : job?.stages && job.stages.length > 0 ? (
            <ul className="relative pl-6 border-l border-line-subtle space-y-3">
              {job.stages.map((s, i) => (
                <li key={`${s.stage}-${i}`} className="relative">
                  <span
                    className={`absolute -left-[27px] top-1 w-3 h-3 rounded-full ring-2 ring-bg-panel ${
                      inferStatusKind(s.status) === "ok"
                        ? "bg-accent-ok"
                        : inferStatusKind(s.status) === "err"
                          ? "bg-accent-err"
                          : inferStatusKind(s.status) === "warn"
                            ? "bg-accent-warn"
                            : "bg-ink-dim"
                    }`}
                  />
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="text-sm font-semibold text-ink">{s.stage}</div>
                    <div className="text-2xs text-ink-muted flex items-center gap-2">
                      <StatusPill kind={inferStatusKind(s.status)}>{s.status ?? "—"}</StatusPill>
                      <span>{formatDuration(s.duration_ms)}</span>
                    </div>
                  </div>
                  <div className="text-2xs text-ink-muted mt-0.5">
                    {s.started_at_utc ? formatTimestamp(s.started_at_utc) : "—"}
                    {" → "}
                    {s.finished_at_utc ? formatTimestamp(s.finished_at_utc) : "running"}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="无 stage 数据" description="audit chain 尚未生成或未导入到 sidecar。" />
          )}
        </Card>
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader title="结果摘要" description="result_summary 优先；否则展示 attribution_result / public_report 节选。" />
          {resultQ.isLoading ? (
            <Skeleton className="h-32" />
          ) : resultQ.error ? (
            <p className="text-2xs text-ink-muted">结果 JSON 不可用：{resultQ.error.message}</p>
          ) : (
            <JsonBlock data={resultQ.data ?? job?.result_summary ?? {}} maxHeight="320px" />
          )}
        </Card>

        <Card>
          <CardHeader title="原始请求" />
          {job?.request ? <JsonBlock data={job.request} maxHeight="320px" /> : <EmptyState title="未记录原始请求" />}
        </Card>
      </section>

      <Card>
        <CardHeader title="活动 / 工件" description="跳到关联视图以便深度排查。" />
        <div className="flex flex-wrap gap-2">
          <Link to="/audit">
            <Button variant="secondary">审计链</Button>
          </Link>
          <Link to="/observability">
            <Button variant="secondary">观测事件流</Button>
          </Link>
          <Link to="/catalog">
            <Button variant="secondary">血缘 / 目录</Button>
          </Link>
          <Link to="/recovery">
            <Button variant="secondary">记录恢复 / mTLS</Button>
          </Link>
        </div>
      </Card>
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
