import { useState, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Download, FileLock2, RefreshCw, ShieldCheck } from "lucide-react";

import { auditApi } from "@/api/sidecars";
import { useApiQuery } from "@/hooks/useApi";
import { Button, Card, CardHeader, EmptyState, ErrorBanner, Field, Input, JsonBlock, PageHeader, Skeleton, StatusPill, inferStatusKind } from "@/components/ui";
import { RouteTabs } from "@/components/tabs";
import { formatNumber, formatTimestamp, shortHash } from "@/lib/format";
import type { CatalogLineage, ObservabilityFeed, PublicReport } from "@/api/types";

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
            <JsonBlock data={q.data ?? {}} maxHeight="420px" />
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
  const q = useApiQuery(
    ["audit", "chain", outBase, includePaths],
    () => auditApi.auditChain({ out_base: outBase || undefined, include_paths: includePaths }),
    { retry: 0 },
  );

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
        {q.isLoading ? <Skeleton className="h-56" /> : q.error ? <ErrorBanner title="加载失败" message={q.error.message} /> : <JsonBlock data={q.data ?? {}} maxHeight="480px" />}
      </Card>
    </div>
  );
}

function ObservabilityTab() {
  const [outBase, setOutBase] = useState("");
  const q = useApiQuery<ObservabilityFeed>(
    ["audit", "observability", outBase],
    () => auditApi.observability({ out_base: outBase || undefined }),
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
        <CardHeader title="pipeline_observability/v1" />
        {q.isLoading ? (
          <Skeleton className="h-56" />
        ) : q.error ? (
          <ErrorBanner title="加载失败" message={q.error.message} />
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3 text-2xs">
              <Stat label="events" value={formatNumber(q.data?.events?.length)} />
              <Stat label="handoff_cleanup" value={formatNumber(q.data?.derived_handoff_cleanup?.length)} />
              <Stat label="service_audit_consistency" value={formatNumber(q.data?.derived_service_audit_consistency?.length)} />
            </div>
            <JsonBlock data={q.data ?? {}} maxHeight="380px" />
          </div>
        )}
      </Card>
    </div>
  );
}

function LineageTab() {
  const [outBase, setOutBase] = useState("");
  const q = useApiQuery<CatalogLineage>(
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
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3 text-2xs">
              <Stat label="nodes" value={formatNumber(q.data?.nodes?.length)} />
              <Stat label="edges" value={formatNumber(q.data?.edges?.length)} />
            </div>
            <JsonBlock data={q.data ?? {}} maxHeight="380px" />
          </div>
        )}
      </Card>
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
