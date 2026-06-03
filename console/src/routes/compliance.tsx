import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { BookOpen, CheckCircle2, FileCode2, ScrollText, ShieldQuestion } from "lucide-react";

import { Card, CardHeader, PageHeader } from "@/components/ui";
import { RouteTabs } from "@/components/tabs";

export function ComplianceRoute() {
  const location = useLocation();
  const tabs = [
    { to: "/compliance/gdpr", label: "GDPR 矩阵" },
    { to: "/compliance/threat-model", label: "威胁模型" },
    { to: "/compliance/checklist", label: "审查 8 步" },
    { to: "/compliance/license", label: "许可证" },
  ];
  const onRoot = location.pathname === "/compliance" || location.pathname === "/compliance/";

  return (
    <div className="space-y-5">
      <PageHeader
        title="合规"
        description="GDPR Article 5(1) / 15-22 映射、威胁与泄露模型、reviewer 8 步最小取证路径、许可证总览。"
      />
      <RouteTabs tabs={tabs} />
      {onRoot ? (
        <Navigate to="/compliance/gdpr" replace />
      ) : (
        <Routes>
          <Route path="gdpr" element={<GdprMatrix />} />
          <Route path="threat-model" element={<ThreatModel />} />
          <Route path="checklist" element={<ReviewerChecklist />} />
          <Route path="license" element={<LicenseTab />} />
          <Route path="*" element={<Navigate to="gdpr" replace />} />
        </Routes>
      )}
    </div>
  );
}

const ARTICLE_5_1 = [
  { id: "a", title: "lawfulness, fairness and transparency", control: "approval workflow + audit chain + public report" },
  { id: "b", title: "purpose limitation", control: "caller-scoped tenant/dataset/service + query_workflow contract" },
  { id: "c", title: "data minimisation", control: "SSE candidate export + HMAC token + PJC aggregate-only output" },
  { id: "d", title: "accuracy", control: "join_key normalizer + duplicate-query denial" },
  { id: "e", title: "storage limitation", control: "handoff cleanup + retention reason + archive anchor TTL" },
  { id: "f", title: "integrity and confidentiality", control: "AES-256-GCM + HMAC + mTLS + audit seal" },
  { id: "g", title: "accountability", control: "audit_chain/v1 + mainline contract check + external anchor (S3 WORM / Rekor)" },
];

const ARTICLES_15_22 = [
  { article: "15", title: "Right of access", note: "subject 列表通过 metadata sidecar 暴露；明细查询走 query workflow" },
  { article: "16", title: "Right to rectification", note: "operator dashboard 内只读；变更经 apply-registry CLI" },
  { article: "17", title: "Right to erasure", note: "不提供自动 erasure 管线；流程指引在 OPS_RUNBOOK §crypto-shred" },
  { article: "18", title: "Right to restriction", note: "policy approve/reject workflow + caller disable 字段" },
  { article: "19", title: "Notification obligations", note: "alert daemon webhook to Slack / Alertmanager" },
  { article: "20", title: "Right to portability", note: "metadata export-json + audit anchor ledger" },
  { article: "21", title: "Right to object", note: "approval workflow reject path" },
  { article: "22", title: "Automated decision-making", note: "PJC 求交输出聚合值；不存在面向个人的自动决策路径" },
];

function GdprMatrix() {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="GDPR Article 5(1) — 数据处理原则"
          description="七条核心原则与本平台对应控制点。"
        />
        <table className="data-grid">
          <thead>
            <tr>
              <th className="w-[40px]">§</th>
              <th>原则</th>
              <th>本平台对应控制</th>
            </tr>
          </thead>
          <tbody>
            {ARTICLE_5_1.map((r) => (
              <tr key={r.id}>
                <td className="font-mono text-2xs text-brand">5(1)({r.id})</td>
                <td className="text-sm">{r.title}</td>
                <td className="text-2xs text-ink-muted">{r.control}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card>
        <CardHeader title="GDPR Article 15-22 — 数据主体权利" />
        <table className="data-grid">
          <thead>
            <tr>
              <th className="w-[60px]">Art.</th>
              <th>条款</th>
              <th>实现状态 / 备注</th>
            </tr>
          </thead>
          <tbody>
            {ARTICLES_15_22.map((r) => (
              <tr key={r.article}>
                <td className="font-mono text-2xs text-brand">Art. {r.article}</td>
                <td className="text-sm">{r.title}</td>
                <td className="text-2xs text-ink-muted">{r.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

const THREATS = [
  { actor: "外部攻击者", surface: "HTTP API / mTLS endpoint", mitigations: ["mTLS + HMAC 签名 + 时间戳反重放", "rate limit + tenant quota", "malformed input gate"] },
  { actor: "内部 caller 越权", surface: "导出 / bridge / PJC / release", mitigations: ["caller-scoped tenant/dataset/service", "policy approve gate", "key access audit"] },
  { actor: "上游数据污染", surface: "SSE / record store", mitigations: ["AES-256-GCM 加密存储 + HMAC tag", "join_key normalizer", "duplicate-query denial"] },
  { actor: "审计篡改", surface: "audit_chain / seal / archive", mitigations: ["seal HMAC + tamper detection", "external anchor (S3 Object Lock 10y / Rekor)", "schema_backcompat baseline"] },
  { actor: "依赖/供应链", surface: "Cargo + pip + Bazel", mitigations: ["dependency hygiene", "lockfile + version pin", "repo hygiene scan for secrets"] },
];

function ThreatModel() {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="威胁矩阵" description="docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md 摘要。" />
        <table className="data-grid">
          <thead>
            <tr>
              <th>Actor</th>
              <th>攻击面</th>
              <th>缓解措施</th>
            </tr>
          </thead>
          <tbody>
            {THREATS.map((t) => (
              <tr key={t.actor}>
                <td className="text-sm font-semibold">{t.actor}</td>
                <td className="text-2xs text-ink-muted">{t.surface}</td>
                <td>
                  <ul className="text-2xs text-ink-muted space-y-0.5">
                    {t.mitigations.map((m) => (
                      <li key={m}>· {m}</li>
                    ))}
                  </ul>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

const CHECKLIST = [
  "确认主链路输出仅含聚合结果（intersection_size / intersection_sum）",
  "校验 audit_chain.json + audit_chain.seal.json 完整性 (verify_audit_bundle.py)",
  "检视 caller 权限范围与 tenant_id / dataset_id / service_id 是否匹配",
  "确认 record-recovery handoff cleanup 状态（cleaned / removed / retained）",
  "确认 mainline_contract_check 嵌入摘要状态",
  "确认 schema_backcompat 基线无 breaking",
  "如发布到外部 anchor，校验 S3 Object Lock 模式与 retain-days，或 Rekor uuid",
  "回看 alert 状态：firing / resolved transition 是否符合预期",
];

function ReviewerChecklist() {
  return (
    <Card>
      <CardHeader
        title="reviewer 8 步最小取证路径"
        description="法务 / 合规 / 安全 reviewer 拿到一份运行结果时的最少检查清单。"
      />
      <ol className="space-y-2 text-2xs">
        {CHECKLIST.map((c, i) => (
          <li key={i} className="flex items-start gap-2.5">
            <span className="w-5 h-5 rounded-full bg-brand/15 text-brand grid place-items-center text-2xs font-bold shrink-0">{i + 1}</span>
            <span className="text-ink leading-relaxed">{c}</span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function LicenseTab() {
  return (
    <Card>
      <CardHeader title="许可证 / 依赖" />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-2xs">
        <LicenseCard icon={<ShieldQuestion className="w-4 h-4" />} title="本仓库" body="GNU General Public License v3.0 or later" path="LICENSE" />
        <LicenseCard icon={<BookOpen className="w-4 h-4" />} title="第三方组件清单" body="Apache-2.0 / BSD / MIT 上游依赖逐项列出" path="NOTICE" />
        <LicenseCard icon={<FileCode2 className="w-4 h-4" />} title="上游 PJC" body="Google private-join-and-compute (Apache-2.0)，与 GPL-3.0 兼容；组合作品按 GPL-3.0 分发" path="a-psi/private-join-and-compute/LICENSE" />
        <LicenseCard icon={<ScrollText className="w-4 h-4" />} title="依赖 hygiene" body="scripts/check_dependency_hygiene.py 校验第一方 Python/Cargo 依赖锁定" path="docs/" />
      </div>
      <p className="mt-4 text-2xs text-ink-muted">
        合规摘要详见{" "}
        <code className="text-brand">docs/COMPLIANCE_MAPPING.md</code> 与{" "}
        <code className="text-brand">NOTICE</code>。
      </p>
    </Card>
  );
}

function LicenseCard({ icon, title, body, path }: { icon: ReactNode; title: string; body: string; path: string }) {
  return (
    <div className="panel-soft p-3 rounded-lg">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-brand/12 text-brand grid place-items-center">{icon}</div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-ink">{title}</div>
          <div className="text-2xs text-ink-muted mt-1">{body}</div>
          <div className="mt-2 text-2xs text-ink-dim font-mono">{path}</div>
        </div>
      </div>
    </div>
  );
}
