import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { metadataApi } from "@/api/sidecars";
import { useApiQuery } from "@/hooks/useApi";
import { Card, CardHeader, EmptyState, ErrorBanner, JsonBlock, PageHeader, Skeleton, StatusPill, inferStatusKind } from "@/components/ui";
import { DataTable, type Column } from "@/components/data-table";
import { RouteTabs } from "@/components/tabs";
import type { Json, MetadataEntityResponse } from "@/api/types";
import { truncate } from "@/lib/format";

export function PermissionsRoute() {
  const location = useLocation();
  const tabs = [
    { to: "/permissions/callers", label: "Callers" },
    { to: "/permissions/policies", label: "Policies" },
    { to: "/permissions/bindings", label: "Policy Bindings" },
    { to: "/permissions/caller-permissions", label: "权限矩阵" },
    { to: "/permissions/keys", label: "密钥环" },
    { to: "/permissions/kms", label: "KMS / Vault" },
    { to: "/permissions/openfga", label: "OpenFGA" },
  ];
  const onRoot = location.pathname === "/permissions" || location.pathname === "/permissions/";

  return (
    <div className="space-y-5">
      <PageHeader
        title="权限 / IAM / KMS"
        description="调用方画像、policy 绑定、权限矩阵、密钥环生命周期、外部 KMS 与 OpenFGA tuple sync。"
      />
      <RouteTabs tabs={tabs} />
      {onRoot ? (
        <Navigate to="/permissions/callers" replace />
      ) : (
        <Routes>
          <Route path="callers" element={<GenericEntity entity="callers" />} />
          <Route path="policies" element={<GenericEntity entity="policies" />} />
          <Route path="bindings" element={<GenericEntity entity="policy-bindings" />} />
          <Route path="caller-permissions" element={<CallerPermissionsTab />} />
          <Route path="keys" element={<KeyringTab />} />
          <Route path="kms" element={<KmsTab />} />
          <Route path="openfga" element={<OpenfgaTab />} />
          <Route path="*" element={<Navigate to="callers" replace />} />
        </Routes>
      )}
    </div>
  );
}

function GenericEntity({ entity }: { entity: "callers" | "policies" | "policy-bindings" }) {
  const q = useApiQuery<MetadataEntityResponse>(["meta-entity", entity], () => metadataApi.entities(entity), { retry: 0 });

  const columns: Column<Record<string, Json>>[] = [
    {
      id: "id",
      header: "ID",
      cell: (r) => <span className="font-mono text-2xs text-brand">{String(r.caller ?? r.policy_id ?? r.binding_id ?? Object.values(r)[0] ?? "—")}</span>,
    },
    {
      id: "tenant",
      header: "tenant_id",
      cell: (r) => <span className="text-2xs">{String(r.tenant_id ?? "—")}</span>,
    },
    {
      id: "status",
      header: "状态",
      cell: (r) =>
        r.disabled !== undefined ? (
          <StatusPill kind={inferStatusKind(r.disabled ? "denied" : "ok")}>{r.disabled ? "disabled" : "active"}</StatusPill>
        ) : (
          <span className="text-2xs text-ink-muted">—</span>
        ),
    },
    {
      id: "extra",
      header: "字段",
      cell: (r) => <span className="text-2xs text-ink-muted font-mono">{truncate(JSON.stringify(r), 100)}</span>,
    },
  ];

  return (
    <Card>
      <CardHeader title={`/v1/entities/${entity}`} description="只读视图，写操作通过 apply-registry CLI 进行。" />
      {q.isLoading ? (
        <Skeleton className="h-32" />
      ) : q.error ? (
        <ErrorBanner title="加载失败" message={q.error.message} />
      ) : !q.data?.entries || q.data.entries.length === 0 ? (
        <EmptyState title="无数据" description="metadata sidecar 尚未导入相关条目。" />
      ) : (
        <DataTable rows={q.data.entries} columns={columns} rowKey={(r, i) => `${Object.values(r)[0] ?? i}`} />
      )}
    </Card>
  );
}

function CallerPermissionsTab() {
  const q = useApiQuery<MetadataEntityResponse>(["caller-permissions"], () => metadataApi.entities("caller-permissions"), { retry: 0 });
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Card>
        <CardHeader title="权限矩阵摘要" description="permission_summary：caller 数、租户、平台角色统计。" />
        {q.isLoading ? <Skeleton className="h-24" /> : q.data?.permission_summary ? <JsonBlock data={q.data.permission_summary} maxHeight="320px" /> : <EmptyState title="无摘要" />}
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader title="权限条目" description="caller × permission_key 的展开视图。" />
        {q.isLoading ? (
          <Skeleton className="h-48" />
        ) : q.error ? (
          <ErrorBanner title="加载失败" message={q.error.message} />
        ) : (
          <DataTable
            rows={q.data?.entries ?? []}
            columns={[
              { id: "caller", header: "caller", cell: (r) => <span className="font-mono text-2xs">{String(r.caller ?? "—")}</span> },
              { id: "policy", header: "policy_id", cell: (r) => <span className="text-2xs text-ink-muted">{String(r.policy_id ?? "—")}</span> },
              { id: "key", header: "permission_key", cell: (r) => <span className="text-2xs">{String(r.permission_key ?? "—")}</span> },
              { id: "value", header: "value", cell: (r) => <span className="text-2xs text-ink-muted">{truncate(JSON.stringify(r.permission_value), 50)}</span> },
            ]}
            rowKey={(r, i) => `${r.caller}-${r.permission_key}-${i}`}
          />
        )}
      </Card>
    </div>
  );
}

function KeyringTab() {
  return (
    <Card>
      <CardHeader title="本地 keyring / 外部 KMS" description="repo 提供 keyring 生命周期 CLI + 一致的 secret_ref schema。" />
      <div className="space-y-3 text-2xs text-ink-muted leading-relaxed">
        <p>
          contract: <code className="text-brand">keyring/v1</code> · backends: <code className="text-brand">env</code> / <code className="text-brand">vault_kv</code> / <code className="text-brand">vault_http</code> / <code className="text-brand">aws_kms</code>。
        </p>
        <pre className="panel p-3 font-mono text-2xs overflow-x-auto">
{`python3 scripts/manage_keyring.py describe \\
  --keyring config/keyring.example.json

python3 scripts/manage_keyring.py rotate \\
  --keyring config/keyring.example.json \\
  --key-name bridge-token \\
  --new-version demo-v2 \\
  --secret-env BRIDGE_TOKEN_SECRET_NEXT \\
  --activate \\
  --audit-log tmp/key_lifecycle_audit.jsonl

python3 scripts/manage_keyring.py set-status \\
  --keyring config/keyring.example.json \\
  --key-name bridge-token --version demo-v1 \\
  --status retired`}
        </pre>
        <p>审计契约：<code className="text-brand">key_lifecycle_audit/v1</code>、<code className="text-brand">key_access_audit/v1</code>。</p>
      </div>
    </Card>
  );
}

function KmsTab() {
  return (
    <Card>
      <CardHeader title="外部 KMS" description="mock HTTP KMS + AWS KMS adapter + Vault PKI（issue mTLS）。" />
      <div className="space-y-3 text-2xs text-ink-muted leading-relaxed">
        <p>
          mock 服务：<code className="text-brand">scripts/external_kms_service.py</code>；管理：
          <code className="text-brand">scripts/manage_external_kms.py</code>；解析：
          <code className="text-brand">scripts/request_external_kms.py</code>；AWS adapter：
          <code className="text-brand">scripts/cloud_kms_adapter.py</code>。
        </p>
        <p>
          Vault PKI 发证：<code className="text-brand">scripts/issue_mtls_certs.py</code>，输出{" "}
          <code className="text-brand">mtls_cert_issuance/v1</code>。
        </p>
      </div>
    </Card>
  );
}

function OpenfgaTab() {
  return (
    <Card>
      <CardHeader title="OpenFGA tuple sync / check" description="repo-side adapter + live HTTP backend support。" />
      <div className="space-y-3 text-2xs text-ink-muted leading-relaxed">
        <p>
          tuple 导出：<code className="text-brand">scripts/export_authz_tuples.py</code> 输出 <code className="text-brand">authz_tuple_export/v1</code>。
        </p>
        <p>
          model bootstrap：<code className="text-brand">scripts/setup_openfga_model.py</code>。
        </p>
        <pre className="panel p-3 font-mono text-2xs overflow-x-auto">
{`# 默认走 SQLite fallback (无外部依赖)
python3 scripts/export_authz_tuples.py \\
  --db-path tmp/platform_metadata.db \\
  --output tmp/platform_authz_tuples.json

# 设置 live backend (operator env)
export OPENFGA_ENDPOINT=http://openfga:8080
export OPENFGA_STORE_ID=...
python3 scripts/setup_openfga_model.py`}
        </pre>
      </div>
    </Card>
  );
}
