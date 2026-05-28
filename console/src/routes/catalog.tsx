import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { metadataApi, auditApi } from "@/api/sidecars";
import { useApiQuery } from "@/hooks/useApi";
import { Card, CardHeader, EmptyState, ErrorBanner, JsonBlock, PageHeader, Skeleton } from "@/components/ui";
import { DataTable, type Column } from "@/components/data-table";
import { RouteTabs } from "@/components/tabs";
import { useState } from "react";
import { Field, Input, Button } from "@/components/ui";
import type { CatalogLineage, Json, MetadataEntityResponse } from "@/api/types";
import { formatTimestamp, truncate } from "@/lib/format";

export function CatalogRoute() {
  const location = useLocation();
  const tabs = [
    { to: "/catalog/tenants", label: "租户" },
    { to: "/catalog/datasets", label: "数据集" },
    { to: "/catalog/services", label: "服务" },
    { to: "/catalog/lineage", label: "血缘" },
    { to: "/catalog/fact-layer", label: "电商事实层" },
  ];
  const onRoot = location.pathname === "/catalog" || location.pathname === "/catalog/";

  return (
    <div className="space-y-5">
      <PageHeader
        title="目录 / 血缘"
        description="租户 / 数据集 / 服务注册表、电商事实层 6 表概览、catalog_lineage/v1 边视图。"
      />
      <RouteTabs tabs={tabs} />
      {onRoot ? (
        <Navigate to="/catalog/tenants" replace />
      ) : (
        <Routes>
          <Route path="tenants" element={<EntityTab entity="tenants" idKey="tenant_id" label="租户" />} />
          <Route path="datasets" element={<EntityTab entity="datasets" idKey="dataset_id" label="数据集" />} />
          <Route path="services" element={<EntityTab entity="services" idKey="service_id" label="服务" />} />
          <Route path="lineage" element={<LineageTab />} />
          <Route path="fact-layer" element={<FactLayerTab />} />
          <Route path="*" element={<Navigate to="tenants" replace />} />
        </Routes>
      )}
    </div>
  );
}

function EntityTab({ entity, idKey, label }: { entity: "tenants" | "datasets" | "services"; idKey: string; label: string }) {
  const q = useApiQuery<MetadataEntityResponse>(["metadata", entity], () => metadataApi.entities(entity), {
    retry: 0,
  });

  const columns: Column<Record<string, Json>>[] = [
    {
      id: "id",
      header: label,
      cell: (r) => <span className="font-mono text-2xs text-brand">{String(r[idKey] ?? "—")}</span>,
      sortKey: (r) => String(r[idKey] ?? ""),
    },
    {
      id: "tenant",
      header: "tenant_id",
      cell: (r) => <span className="text-2xs text-ink-muted">{String(r.tenant_id ?? "—")}</span>,
      sortKey: (r) => String(r.tenant_id ?? ""),
    },
    {
      id: "status",
      header: "status",
      cell: (r) => <span className="text-2xs">{String(r.status ?? "—")}</span>,
      sortKey: (r) => String(r.status ?? ""),
    },
    {
      id: "extra",
      header: "其他字段",
      cell: (r) => (
        <span className="text-2xs text-ink-muted font-mono">
          {truncate(
            Object.entries(r)
              .filter(([k]) => k !== idKey && k !== "tenant_id" && k !== "status")
              .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
              .join(", "),
            80,
          )}
        </span>
      ),
    },
  ];

  return (
    <Card>
      <CardHeader title={`${label}列表`} description={`/v1/entities/${entity} from metadata sidecar`} />
      {q.isLoading ? (
        <Skeleton className="h-32" />
      ) : q.error ? (
        <ErrorBanner title="加载失败" message={q.error.message} />
      ) : !q.data?.entries || q.data.entries.length === 0 ? (
        <EmptyState title={`暂无 ${label}`} description="metadata sidecar 尚未导入相关条目。" />
      ) : (
        <DataTable rows={q.data.entries} columns={columns} rowKey={(r, i) => `${r[idKey] ?? i}`} />
      )}
    </Card>
  );
}

function LineageTab() {
  const [outBase, setOutBase] = useState("");
  const q = useApiQuery<CatalogLineage>(
    ["catalog", "lineage", outBase],
    () => auditApi.catalogLineage({ out_base: outBase || undefined }),
    { retry: 0 },
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Card>
        <CardHeader title="参数" />
        <Field label="out_base">
          <Input value={outBase} onChange={(e) => setOutBase(e.target.value)} placeholder="$REPO/tmp/sse_bridge_pipeline_demo" />
        </Field>
        <Button className="mt-3" variant="secondary" onClick={() => q.refetch()} loading={q.isFetching}>
          重新查询
        </Button>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader title="catalog_lineage/v1" />
        {q.isLoading ? (
          <Skeleton className="h-48" />
        ) : q.error ? (
          <ErrorBanner title="加载失败" message={q.error.message} />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 text-2xs mb-3">
              <Stat label="nodes" value={q.data?.nodes?.length ?? 0} />
              <Stat label="edges" value={q.data?.edges?.length ?? 0} />
            </div>
            <JsonBlock data={q.data ?? {}} maxHeight="380px" />
          </>
        )}
      </Card>
    </div>
  );
}

function FactLayerTab() {
  const tables = [
    { name: "orders", purpose: "订单事实", indices: 4 },
    { name: "order_items", purpose: "订单商品行", indices: 2 },
    { name: "order_attribution", purpose: "归因（投放 / 渠道）", indices: 2 },
    { name: "order_payment", purpose: "支付明细", indices: 2 },
    { name: "order_fulfillment", purpose: "履约 / 物流", indices: 2 },
    { name: "customer_service_interactions", purpose: "客服会话", indices: 2 },
  ];
  return (
    <Card>
      <CardHeader
        title="电商事实层（Track-E1）"
        description="migrations/metadata/010_add_ecommerce_fact_tables.sql 已落基线 6 张事实表；migrations/postgres/001_init.sql 已同步对齐。"
      />
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {tables.map((t) => (
          <div key={t.name} className="panel-soft p-4 rounded-card">
            <div className="font-mono text-sm text-brand">{t.name}</div>
            <div className="text-2xs text-ink-muted mt-1">{t.purpose}</div>
            <div className="text-2xs text-ink-dim mt-3">索引 ≥ {t.indices}</div>
          </div>
        ))}
      </div>
      <p className="mt-4 text-2xs text-ink-muted leading-relaxed">
        渲染脚本：<code className="text-brand">scripts/render_ecommerce_fact_layer.py</code> 输出{" "}
        <code className="text-brand">ecommerce_fact_layer_report/v1</code>；默认 contract smoke 渲染并断言 6 表全在 + indexes ≥ 12。
        当前限制：仍需 operator 提供真实 / 脱敏数据导入，不是完整电商数仓。
      </p>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="panel-soft p-3 rounded-lg">
      <div className="field-label">{label}</div>
      <div className="text-sm font-semibold text-ink mt-1">{value}</div>
    </div>
  );
}
