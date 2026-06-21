import { useState, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Download, FileLock2, RefreshCw, ShieldCheck } from "lucide-react";

import { auditApi } from "@/api/sidecars";
import { useApiQuery } from "@/hooks/useApi";
import { Button, Card, CardHeader, EmptyState, ErrorBanner, Field, Input, JsonDetails, KeyValueGrid, PageHeader, Skeleton, StatusPill, inferStatusKind } from "@/components/ui";
import { RouteTabs } from "@/components/tabs";
import { formatNumber, formatTimestamp, shortHash } from "@/lib/format";
import type { AuditChainData, CatalogLineageData, ObservabilityData, ObservabilityFeed, PublicReport } from "@/api/types";
import {
  isAuditChainPublicSummary,
  isCatalogLineagePublicSummary,
  isPipelineObservabilityPublicSummary,
} from "@/api/types";

export function AuditRoute() {
  const location = useLocation();
  const tabs = [
    { to: "/audit/public-report", label: "公开报告", end: true },
    { to: "/audit/chain", label: "审计链 & seal" },
    { to: "/audit/observability", label: "观测事件" },
    { to: "/audit/lineage", label: "目录 / 血缘" },
    { to: "/audit/external-anchor", label: "外部 anchor" },
  ];
  // Default to public-report when hitting /audit
  const onRoot = location.pathname === "/audit" || location.pathname === "/audit/";

  return (
    <div className="space-y-5">
      <PageHeader
        title="审计中心"
        description="审计链、seal、归档 anchor、合规摘要、衍生观测事件，全部来源于 sidecar audit-query API。"
      />
      <RouteTabs tabs={tabs} />
      {onRoot ? (
        <Navigate to="/audit/public-report" replace />
      ) : (
        <Routes>
          <Route path="public-report" element={<PublicReportTab />} />
          <Route path="chain" element={<AuditChainTab />} />
          <Route path="observability" element={<ObservabilityTab />} />
          <Route path="lineage" element={<LineageTab />} />
          <Route path="external-anchor" element={<ExternalAnchorTab />} />
          <Route path="*" element={<Navigate to="public-report" replace />} />
        </Routes>
      )}
    </div>
  );
}

function OutBaseInput({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <Field label="out_base" hint="留空则使用 sidecar 默认 history root">
      <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder="$REPO/tmp/sse_bridge_pipeline_demo" />
    </Field>
  );
}

function PublicReportTab() {
  const [outBase, setOutBase] = useState("");
  const q = useApiQuery<PublicReport>(
    ["audit", "public-report", outBase],
    () => auditApi.publicReport({ out_base: outBase || undefined }),
    { retry: 0 },
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Card>
        <CardHeader title="参数" />
        <OutBaseInput value={outBase} onChange={setOutBase} />
        <div className="mt-3">
          <Button variant="secondary" leftIcon={<RefreshCw className="w-4 h-4" />} onClick={() => q.refetch()} loading={q.isFetching}>
            重新查询
          </Button>
        </div>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader title="public_report/v1" />
        {q.isLoading ? (
          <Skeleton className="h-48" />
        ) : q.error ? (
          <ErrorBanner title="加载失败" message={q.error.message} retry={() => q.refetch()} />
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3 text-2xs">
              <Stat label="released" value={String(q.data?.released ?? false)} kind={q.data?.released ? "ok" : "warn"} />
              <Stat label="intersection_size" value={formatNumber(q.data?.intersection_size as number | undefined)} />
              <Stat label="intersection_sum" value={formatNumber(q.data?.intersection_sum as number | undefined)} />
              <Stat label="generated_at" value={formatTimestamp(q.data?.generated_at_utc) ?? "—"} />
            </div>
            <KeyValueGrid
              columns={2}
              items={[
                { label: "job_id", value: String(q.data?.job_id ?? "—") },
                { label: "reason_code", value: String((q.data as Record<string, unknown> | undefined)?.reason_code ?? "—") },
                { label: "value_sum", value: String((q.data as Record<string, unknown> | undefined)?.value_sum ?? "—") },
                { label: "aov", value: String((q.data as Record<string, unknown> | undefined)?.aov ?? "—") },
              ]}
            />
            <JsonDetails title="查看原始 public_report JSON" data={q.data ?? {}} maxHeight="420px" />
          </>
        )}
      </Card>
    </div>
  );
}

function Stat({ label, value, kind = "info" }: { label: string; value: ReactNode; kind?: "ok" | "warn" | "err" | "info" | "muted" }) {
  return (
    <div className="panel-soft p-3 rounded-lg">
      <div className="field-label">{label}</div>
      <div className="text-sm font-semibold text-ink mt-1">{value}</div>
      <StatusPill kind={kind} className="mt-2">{kind}</StatusPill>
    </div>
  );
}

function AuditChainTab() {
  const [outBase, setOutBase] = useState("");
  const [includePaths, setIncludePaths] = useState(false);
  const q = useApiQuery<AuditChainData>(
    ["audit", "chain", outBase, includePaths],
    () => auditApi.auditChain({ out_base: outBase || undefined, include_paths: includePaths }),
    { retry: 0 },
  );
  const chainData = q.data;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Card>
        <CardHeader title="参数" />
        <OutBaseInput value={outBase} onChange={setOutBase} />
        <label className="mt-3 flex items-center gap-2 text-2xs text-ink-muted cursor-pointer">
          <input type="checkbox" checked={includePaths} onChange={(e) => setIncludePaths(e.target.checked)} />
          include_paths
        </label>
        <div className="mt-3 space-y-2">
          <Button variant="secondary" leftIcon={<RefreshCw className="w-4 h-4" />} onClick={() => q.refetch()} loading={q.isFetching}>
            重新查询
          </Button>
          <a
            href={`#/audit/chain/download?out_base=${encodeURIComponent(outBase)}`}
            className="hidden"
          >
            download
          </a>
        </div>
        <p className="mt-4 text-2xs text-ink-muted leading-relaxed">
          审计链 + seal 校验在本地 CLI 中由 <code className="text-brand">scripts/verify_audit_bundle.py</code> 执行；
          外部 anchor 发布走 <code className="text-brand">scripts/publish_external_audit_anchor.py</code>（见外部 anchor tab）。
        </p>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader title="audit_chain/v1" actions={<FileLock2 className="w-4 h-4 text-ink-dim" />} />
        {q.isLoading ? (
          <Skeleton className="h-56" />
        ) : q.error ? (
          <ErrorBanner title="加载失败" message={q.error.message} />
        ) : isAuditChainPublicSummary(chainData) ? (
          <AuditChainPublicSummaryPanel data={chainData} />
        ) : (
          <>
            <KeyValueGrid
              columns={3}
              items={[
                { label: "job_id", value: String((chainData as Record<string, unknown> | undefined)?.job_id ?? "—") },
                { label: "generated_at", value: formatTimestamp((chainData as Record<string, string | null | undefined> | undefined)?.generated_at_utc) },
                { label: "counts", value: formatNumber(Number((chainData as Record<string, unknown> | undefined)?.counts ? Object.keys((chainData as Record<string, unknown>).counts as object).length : 0)) },
              ]}
            />
            <JsonDetails title="查看原始 audit_chain JSON" data={chainData ?? {}} maxHeight="480px" />
          </>
        )}
      </Card>
    </div>
  );
}

function ObservabilityTab() {
  const [outBase, setOutBase] = useState("");
  const q = useApiQuery<ObservabilityData>(
    ["audit", "observability", outBase],
    () => auditApi.observability({ out_base: outBase || undefined }),
    { retry: 0 },
  );
  const observabilityData = q.data;
  const fullEvents = fullObservabilityEvents(observabilityData);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Card>
        <CardHeader title="参数" />
        <OutBaseInput value={outBase} onChange={setOutBase} />
        <Button className="mt-3" variant="secondary" leftIcon={<RefreshCw className="w-4 h-4" />} onClick={() => q.refetch()} loading={q.isFetching}>
          重新查询
        </Button>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader title="pipeline_observability/v1" />
        {q.isLoading ? (
          <Skeleton className="h-56" />
        ) : q.error ? (
          <ErrorBanner title="加载失败" message={q.error.message} />
        ) : isPipelineObservabilityPublicSummary(observabilityData) ? (
          <ObservabilityPublicSummaryPanel data={observabilityData} />
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3 text-2xs">
              <Stat label="events" value={formatNumber(fullEvents.length)} />
              <Stat label="handoff_cleanup" value={formatNumber(observabilityData?.derived_handoff_cleanup?.length)} />
              <Stat label="service_audit_consistency" value={formatNumber(observabilityData?.derived_service_audit_consistency?.length)} />
            </div>
            <JsonDetails title="查看原始 observability JSON" data={observabilityData ?? {}} maxHeight="380px" />
          </div>
        )}
      </Card>
    </div>
  );
}

function fullObservabilityEvents(data: ObservabilityData | null | undefined): NonNullable<ObservabilityFeed["events"]> {
  if (!data || isPipelineObservabilityPublicSummary(data)) {
    return [];
  }
  return data.events ?? [];
}

function LineageTab() {
  const [outBase, setOutBase] = useState("");
  const q = useApiQuery<CatalogLineageData>(
    ["audit", "lineage", outBase],
    () => auditApi.catalogLineage({ out_base: outBase || undefined }),
    { retry: 0 },
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Card>
        <CardHeader title="参数" />
        <OutBaseInput value={outBase} onChange={setOutBase} />
        <Button className="mt-3" variant="secondary" leftIcon={<RefreshCw className="w-4 h-4" />} onClick={() => q.refetch()} loading={q.isFetching}>
          重新查询
        </Button>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader title="catalog_lineage/v1" />
        {q.isLoading ? (
          <Skeleton className="h-56" />
        ) : q.error ? (
          <ErrorBanner title="加载失败" message={q.error.message} />
        ) : isCatalogLineagePublicSummary(q.data) ? (
          <CatalogPublicSummaryPanel data={q.data} />
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3 text-2xs">
              <Stat label="datasets" value={formatNumber(q.data?.summary?.dataset_count ?? q.data?.datasets?.length)} />
              <Stat label="lineage_edges" value={formatNumber(q.data?.summary?.lineage_edge_count ?? q.data?.lineage_edges?.length)} />
            </div>
            <JsonDetails title="查看原始 catalog_lineage JSON" data={q.data ?? {}} maxHeight="380px" />
          </div>
        )}
      </Card>
    </div>
  );
}

function AuditChainPublicSummaryPanel({ data }: { data: Extract<AuditChainData, { schema: "audit_chain_public_summary/v1" }> }) {
  return (
    <div className="space-y-3">
      <CallerSafeNotice />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-2xs">
        <Stat label="released" value={String(data.release.released ?? "unknown")} kind={data.release.released ? "ok" : "warn"} />
        <Stat label="reason_code" value={data.release.reason_code ?? "—"} />
        <Stat label="complete_stages" value={formatNumber(data.audit_chain.complete_stage_count)} />
        <Stat label="handoff_risk" value={data.mainline_contract.plaintext_exposure_risk ?? "—"} kind={inferStatusKind(data.mainline_contract.plaintext_exposure_risk)} />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {Object.entries(data.stage_record_counts).map(([stage, count]) => (
          <div key={stage} className="panel-soft p-3 rounded-lg">
            <div className="field-label">{stage}</div>
            <div className="text-sm font-semibold text-ink mt-1">{formatNumber(count ?? undefined)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ObservabilityPublicSummaryPanel({ data }: { data: Extract<ObservabilityData, { schema: "pipeline_observability_public_summary/v1" }> }) {
  return (
    <div className="space-y-3">
      <CallerSafeNotice />
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-2xs">
        <Stat label="status" value={data.summary.status ?? "—"} kind={inferStatusKind(data.summary.status)} />
        <Stat label="events_available" value={String(data.summary.events_available)} />
        <Stat label="stages" value={formatNumber(data.summary.stages.length)} />
      </div>
      <div className="space-y-2">
        {data.summary.stages.map((stage) => (
          <div key={stage.name} className="panel-soft p-3 rounded-lg flex items-center justify-between gap-3">
            <span className="font-mono text-2xs text-brand">{stage.name}</span>
            <div className="flex flex-wrap gap-1 justify-end">
              {stage.statuses.map((status) => (
                <StatusPill key={status} kind={inferStatusKind(status)}>{status}</StatusPill>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CatalogPublicSummaryPanel({ data }: { data: Extract<CatalogLineageData, { schema: "catalog_lineage_public_summary/v1" }> }) {
  return (
    <div className="space-y-3">
      <CallerSafeNotice />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-2xs">
        <Stat label="datasets" value={formatNumber(data.summary.dataset_count ?? undefined)} />
        <Stat label="services" value={formatNumber(data.summary.service_count ?? undefined)} />
        <Stat label="artifacts" value={formatNumber(data.summary.artifact_count ?? undefined)} />
        <Stat label="lineage_edges" value={formatNumber(data.summary.lineage_edge_count ?? undefined)} />
      </div>
      <div className="grid grid-cols-2 gap-3 text-2xs">
        <Stat label="job_status" value={data.job.status ?? "—"} kind={inferStatusKind(data.job.status)} />
        <Stat label="paths_included" value={String(data.privacy.paths_included)} />
      </div>
    </div>
  );
}

function CallerSafeNotice() {
  return (
    <div className="panel-soft p-3 rounded-lg border border-line-subtle">
      <div className="text-sm font-semibold text-ink">caller-safe summary</div>
      <div className="text-2xs text-ink-muted mt-1">
        Full audit records, paths, hashes, row counts, timing, and raw artifact lists are redacted for this identity.
      </div>
    </div>
  );
}

function ExternalAnchorTab() {
  return (
    <Card>
      <CardHeader title="外部审计 anchor sinks" description="K1-a S3 Object Lock / K1-b Sigstore Rekor。本视图给出工具入口与契约说明，实际发布需在终端执行。" />
      <div className="space-y-3 text-2xs leading-relaxed text-ink-muted">
        <p>
          外部 anchor 发布工具：<code className="text-brand">scripts/publish_external_audit_anchor.py</code>。支持 sink kind:
          <code className="ml-1 text-brand">file_ledger</code>,
          <code className="ml-1 text-brand">s3_worm</code>,
          <code className="ml-1 text-brand">rekor</code>。默认 planned 状态，加 <code className="text-brand">--execute</code> 才真正调用 boto3 / Rekor REST。
        </p>
        <pre className="panel p-3 font-mono text-2xs overflow-x-auto">
{`# S3 Object Lock (10y retention)
python3 scripts/publish_external_audit_anchor.py \\
  --tenant-id demo_tenant \\
  --sink-kind s3_worm \\
  --object-lock-mode COMPLIANCE \\
  --retain-days 3650 \\
  --execute

# Sigstore Rekor
python3 scripts/publish_external_audit_anchor.py \\
  --tenant-id demo_tenant \\
  --sink-kind rekor \\
  --rekor-signing-key-env REKOR_PRIV_KEY \\
  --execute`}
        </pre>
        <p>
          报告契约：<code className="text-brand">external_audit_anchor_report/v1</code>。
          每条 anchor record 的 canonical bytes 是 <code className="text-brand">b"entry_sha256:&lt;hex&gt;\n"</code>，使用 ECDSA-P256 / SHA256 签名后构造 hashedrekord/0.0.1 入口。
        </p>
        <div className="flex flex-wrap gap-2 pt-2">
          <Button variant="secondary" leftIcon={<Download className="w-4 h-4" />}>下载契约 schema</Button>
          <Button variant="secondary" leftIcon={<ShieldCheck className="w-4 h-4" />}>查看 anchor sink 文档</Button>
        </div>
      </div>
    </Card>
  );
}
