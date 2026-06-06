import { useMemo, useState, type ReactNode } from "react";
import { Eye, Search, ShieldCheck, Truck, UserRound, Store, BadgeAlert, Megaphone, Warehouse } from "lucide-react";

import { metadataApi } from "@/api/sidecars";
import type { BusinessAccessCheckReport, BusinessDataReadPreview, Json } from "@/api/types";
import { useApiMutation } from "@/hooks/useApi";
import { Button, Card, CardHeader, ErrorBanner, Field, JsonBlock, PageHeader, Select, StatusPill, Textarea, inferStatusKind } from "@/components/ui";
import { DataTable, type Column } from "@/components/data-table";
import { truncate } from "@/lib/format";

const ROLE_PRESETS: Array<{
  key: string;
  label: string;
  summary: string;
  icon: ReactNode;
  payload: Record<string, Json>;
  previewPayload: Record<string, Json>;
}> = [
  {
    key: "merchant_staff",
    label: "Merchant Staff",
    summary: "订单运营可见，买家联系信息必须 deny。",
    icon: <Store className="w-4 h-4" />,
    payload: {
      role: "merchant_staff",
      entity: "orders",
      fields: ["orders.order_id", "orders.total_amount_cents", "orders.buyer_email"],
      purpose: "merchant_order_ops",
      relationship: "merchant_of_order",
      scope: { tenant_id: "commerce_tenant", order_id: "o-1" },
    },
    previewPayload: {
      role: "merchant_staff",
      entity: "orders",
      fields: ["orders.order_id", "orders.status", "orders.total_amount_cents"],
      purpose: "merchant_order_ops",
      relationship: "merchant_of_order",
      scope: { tenant_id: "commerce_tenant", order_id: "o-1" },
    },
  },
  {
    key: "buyer",
    label: "Buyer Self-Service",
    summary: "买家只看自己的订单，不允许 buyer_id 漂移。",
    icon: <UserRound className="w-4 h-4" />,
    payload: {
      role: "buyer",
      entity: "orders",
      fields: ["orders.order_id", "orders.status", "orders.buyer_email"],
      purpose: "self_service",
      relationship: "self",
      scope: { tenant_id: "commerce_tenant", order_id: "o-1", buyer_id: "buyer-1" },
    },
    previewPayload: {
      role: "buyer",
      entity: "orders",
      fields: ["orders.order_id", "orders.status"],
      purpose: "self_service",
      relationship: "self",
      scope: { tenant_id: "commerce_tenant", order_id: "o-1", buyer_id: "buyer-1" },
    },
  },
  {
    key: "customer_service_agent",
    label: "Support Case",
    summary: "客服看到 masked 联系信息，case 绑定必须收紧。",
    icon: <ShieldCheck className="w-4 h-4" />,
    payload: {
      role: "customer_service_agent",
      entity: "orders",
      fields: ["orders.order_id", "orders.buyer_email"],
      purpose: "support_case",
      relationship: "assigned_support_case",
      scope: { tenant_id: "commerce_tenant", order_id: "o-1", case_id: "case-1" },
    },
    previewPayload: {
      role: "customer_service_agent",
      entity: "orders",
      fields: ["orders.order_id", "orders.buyer_email"],
      purpose: "support_case",
      relationship: "assigned_support_case",
      scope: { tenant_id: "commerce_tenant", order_id: "o-1", case_id: "case-1" },
    },
  },
  {
    key: "courier",
    label: "Courier Next Stop",
    summary: "上游腿只见 next-stop，不见最终地址。",
    icon: <Truck className="w-4 h-4" />,
    payload: {
      role: "courier",
      entity: "delivery_route_legs",
      fields: ["delivery_route.leg_id", "delivery_route.next_stop_label", "delivery_route.final_address_line1"],
      purpose: "delivery_next_stop",
      relationship: "assigned_delivery_leg",
      scope: { tenant_id: "commerce_tenant", leg_id: "leg-1", assigned_courier_id: "courier-1" },
    },
    previewPayload: {
      role: "courier",
      entity: "delivery_route_legs",
      fields: ["delivery_route.leg_id", "delivery_route.next_stop_label", "delivery_route.leg_sequence"],
      purpose: "delivery_next_stop",
      relationship: "assigned_delivery_leg",
      scope: { tenant_id: "commerce_tenant", leg_id: "leg-1", assigned_courier_id: "courier-1" },
    },
  },
  {
    key: "station_operator",
    label: "Station Handoff",
    summary: "站点交接可见 pickup/handoff 字段，最终地址继续 deny。",
    icon: <Warehouse className="w-4 h-4" />,
    payload: {
      role: "station_operator",
      entity: "delivery_route_legs",
      fields: ["delivery_route.pickup_station_label", "delivery_route.assigned_station_id", "delivery_route.final_address_line1"],
      purpose: "station_handoff",
      relationship: "assigned_station_leg",
      scope: { tenant_id: "commerce_tenant", leg_id: "leg-2", assigned_station_id: "station-1" },
    },
    previewPayload: {
      role: "station_operator",
      entity: "delivery_route_legs",
      fields: ["delivery_route.pickup_station_label", "delivery_route.assigned_station_id"],
      purpose: "station_handoff",
      relationship: "assigned_station_leg",
      scope: { tenant_id: "commerce_tenant", leg_id: "leg-2", assigned_station_id: "station-1" },
    },
  },
  {
    key: "last_mile_courier",
    label: "Last Mile",
    summary: "末端腿可见最终投递地址，但手机号保持 masked。",
    icon: <Truck className="w-4 h-4" />,
    payload: {
      role: "last_mile_courier",
      entity: "delivery_route_legs",
      fields: ["delivery_route.final_address_line1", "delivery_route.recipient_phone"],
      purpose: "last_mile_delivery",
      relationship: "assigned_last_mile_leg",
      scope: { tenant_id: "commerce_tenant", leg_id: "leg-3", assigned_courier_id: "last-mile-1" },
    },
    previewPayload: {
      role: "last_mile_courier",
      entity: "delivery_route_legs",
      fields: ["delivery_route.final_address_line1", "delivery_route.recipient_phone"],
      purpose: "last_mile_delivery",
      relationship: "assigned_last_mile_leg",
      scope: { tenant_id: "commerce_tenant", leg_id: "leg-3", assigned_courier_id: "last-mile-1" },
    },
  },
  {
    key: "fraud_analyst",
    label: "Fraud Review",
    summary: "支付风险字段 allow，买家联系方式 deny。",
    icon: <BadgeAlert className="w-4 h-4" />,
    payload: {
      role: "fraud_analyst",
      entity: "order_payment",
      fields: ["order_payment.payment_method", "order_payment.risk_score", "orders.buyer_email"],
      purpose: "fraud_review",
      relationship: "fraud_review_queue",
      scope: { tenant_id: "commerce_tenant", order_id: "o-1", case_id: "fraud-1" },
    },
    previewPayload: {
      role: "fraud_analyst",
      entity: "order_payment",
      fields: ["order_payment.payment_method", "order_payment.risk_score"],
      purpose: "fraud_review",
      relationship: "fraud_review_queue",
      scope: { tenant_id: "commerce_tenant", order_id: "o-1", case_id: "fraud-1" },
    },
  },
  {
    key: "field_marketer",
    label: "Field Marketer",
    summary: "归因字段 allow，买家联系方式 deny，campaign 绑定必须一致。",
    icon: <Megaphone className="w-4 h-4" />,
    payload: {
      role: "field_marketer",
      entity: "order_attribution",
      fields: ["order_attribution.campaign_id", "order_attribution.attribution_weight", "orders.buyer_email"],
      purpose: "campaign_analysis",
      relationship: "campaign_assignee",
      scope: { tenant_id: "commerce_tenant", order_id: "o-1", campaign_id: "campaign-demo" },
    },
    previewPayload: {
      role: "field_marketer",
      entity: "order_attribution",
      fields: ["order_attribution.channel", "order_attribution.campaign_id", "order_attribution.attribution_weight"],
      purpose: "campaign_analysis",
      relationship: "campaign_assignee",
      scope: { tenant_id: "commerce_tenant", order_id: "o-1", campaign_id: "campaign-demo" },
    },
  },
];

export function BusinessAccessRoute() {
  const [selectedKey, setSelectedKey] = useState(ROLE_PRESETS[0].key);
  const selected = useMemo(() => ROLE_PRESETS.find((item) => item.key === selectedKey) ?? ROLE_PRESETS[0], [selectedKey]);
  const [checkPayload, setCheckPayload] = useState(JSON.stringify(selected.payload, null, 2));
  const [previewPayload, setPreviewPayload] = useState(JSON.stringify(selected.previewPayload, null, 2));

  const check = useApiMutation<BusinessAccessCheckReport, void>(
    async () => metadataApi.businessAccessCheck(JSON.parse(checkPayload) as Record<string, Json>),
    { successToast: "业务字段访问检查完成" },
  );
  const preview = useApiMutation<BusinessDataReadPreview, void>(
    async () => metadataApi.businessDataReadPreview(JSON.parse(previewPayload) as Record<string, Json>),
    { successToast: "业务读取预览完成" },
  );

  const fieldRows = check.data?.field_decisions ?? [];
  const previewRows = preview.data?.rows ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        title="业务访问工作台"
        description="直接走 metadata sidecar 的 business-access/check 与 business-data/read-preview，覆盖 buyer / merchant / support / courier / station / last-mile / fraud / marketer 的 reviewer-facing 场景，确认字段级 gate 不会被浏览器接触面绕过。"
      />

      <Card>
        <CardHeader title="Role Preset" description="加载 reviewer-facing 角色场景。" />
        <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-3">
          <Field label="Preset">
            <Select
              value={selectedKey}
              onChange={(event) => {
                const preset = ROLE_PRESETS.find((item) => item.key === event.target.value) ?? ROLE_PRESETS[0];
                setSelectedKey(preset.key);
                setCheckPayload(JSON.stringify(preset.payload, null, 2));
                setPreviewPayload(JSON.stringify(preset.previewPayload, null, 2));
              }}
            >
              {ROLE_PRESETS.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </Select>
          </Field>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Stat title="relationship" value={String((selected.payload.relationship as string) ?? "—")} icon={<ShieldCheck className="w-4 h-4" />} />
            <Stat title="entity" value={String((selected.previewPayload.entity as string) ?? "—")} icon={<Eye className="w-4 h-4" />} />
            <Stat title="persona" value={selected.label} icon={selected.icon} />
          </div>
        </div>
        <p className="text-2xs text-ink-muted mt-3">{selected.summary}</p>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card>
          <CardHeader
            title="Business Access Check"
            description="字段级 allow / mask / deny 决策。"
            actions={
              <Button variant="primary" onClick={() => check.mutate()} loading={check.isPending}>
                运行检查
              </Button>
            }
          />
          <Field label="Request payload">
            <Textarea value={checkPayload} onChange={(event) => setCheckPayload(event.target.value)} className="min-h-[220px]" spellCheck={false} />
          </Field>
          {check.error && <ErrorBanner title="检查失败" message={check.error.message} />}
          {check.data && (
            <div className="space-y-3 mt-3">
              <div className="flex items-center gap-2 text-sm">
                <StatusPill kind={inferStatusKind(check.data.decision)}>{check.data.decision}</StatusPill>
                <span className="text-ink-muted font-mono text-2xs">{check.data.reason_code}</span>
              </div>
              <FieldDecisionTable rows={fieldRows} />
              <JsonBlock data={check.data.relationship_binding ?? { status: "missing" }} maxHeight="180px" />
            </div>
          )}
        </Card>

        <Card>
          <CardHeader
            title="Business Read Preview"
            description="受策略保护的事实表读取预览。"
            actions={
              <Button variant="primary" onClick={() => preview.mutate()} loading={preview.isPending} leftIcon={<Search className="w-4 h-4" />}>
                读取预览
              </Button>
            }
          />
          <Field label="Request payload">
            <Textarea value={previewPayload} onChange={(event) => setPreviewPayload(event.target.value)} className="min-h-[220px]" spellCheck={false} />
          </Field>
          {preview.error && <ErrorBanner title="读取失败" message={preview.error.message} />}
          {preview.data && (
            <div className="space-y-3 mt-3">
              <div className="flex items-center gap-2 text-sm">
                <StatusPill kind={inferStatusKind(preview.data.decision)}>{preview.data.decision}</StatusPill>
                <span className="text-ink-muted font-mono text-2xs">rows={preview.data.count}</span>
              </div>
              <PreviewRowsTable rows={previewRows} />
              <JsonBlock data={{ scope: preview.data.scope, filters: preview.data.filters, relationship_binding: preview.data.relationship_binding }} maxHeight="220px" />
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function Stat({ title, value, icon }: { title: string; value: string; icon: ReactNode }) {
  return (
    <div className="panel-soft p-3 rounded-lg">
      <div className="field-label flex items-center gap-1.5">{icon}{title}</div>
      <div className="text-sm font-semibold text-ink mt-1">{value}</div>
    </div>
  );
}

function FieldDecisionTable({ rows }: { rows: BusinessAccessCheckReport["field_decisions"] }) {
  const columns: Column<BusinessAccessCheckReport["field_decisions"][number]>[] = [
    { id: "field", header: "Field", cell: (row) => <span className="font-mono text-2xs text-brand">{row.field}</span>, sortKey: (row) => row.field },
    { id: "class", header: "Class", cell: (row) => <span className="text-2xs text-ink-muted">{row.field_class ?? "—"}</span>, sortKey: (row) => row.field_class ?? "" },
    { id: "decision", header: "Decision", cell: (row) => <StatusPill kind={inferStatusKind(row.decision)}>{row.decision}</StatusPill>, sortKey: (row) => row.decision },
    { id: "masking", header: "Masking", cell: (row) => <span className="text-2xs">{row.masking ?? "—"}</span> },
    { id: "reason", header: "Reason", cell: (row) => <span className="text-2xs text-ink-muted">{row.reason_code}</span>, sortKey: (row) => row.reason_code },
  ];
  return <DataTable rows={rows} columns={columns} rowKey={(row, index) => `${row.field}-${index}`} />;
}

function PreviewRowsTable({ rows }: { rows: BusinessDataReadPreview["rows"] }) {
  const keys = useMemo(() => {
    const seen = new Set<string>();
    rows.forEach((row) => Object.keys(row).forEach((key) => seen.add(key)));
    return [...seen];
  }, [rows]);
  const columns: Column<BusinessDataReadPreview["rows"][number]>[] = keys.map((key) => ({
    id: key,
    header: key,
    cell: (row) => <span className="text-2xs font-mono text-ink-muted">{truncate(JSON.stringify(row[key] ?? null), 80)}</span>,
    sortKey: (row) => String(row[key] ?? ""),
  }));
  return <DataTable rows={rows} columns={columns} rowKey={(_, index) => `preview-row-${index}`} empty="没有返回行" />;
}
