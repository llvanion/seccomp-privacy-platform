import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Bug, Fingerprint, GaugeCircle, ShieldCheck, ShieldOff, Sparkles, TestTube2 } from "lucide-react";

import { Card, CardHeader, PageHeader } from "@/components/ui";
import { RouteTabs } from "@/components/tabs";

export function SecurityRoute() {
  const location = useLocation();
  const tabs = [
    { to: "/security/tamper", label: "审计篡改检测" },
    { to: "/security/malformed-gate", label: "异常输入 gate" },
    { to: "/security/mtls-bench", label: "mTLS 基准" },
    { to: "/security/hygiene", label: "Repo / Dep 卫生" },
    { to: "/security/contracts", label: "契约 smoke" },
    { to: "/security/benchmarks", label: "Benchmark 画廊" },
  ];
  const onRoot = location.pathname === "/security" || location.pathname === "/security/";

  return (
    <div className="space-y-5">
      <PageHeader
        title="安全工具"
        description="本平台所有可在 SPA 触发的安全 / 性能验证工具的统一入口；多数命令需要 operator 终端执行，本视图提供契约说明 + 一键命令模板。"
      />
      <RouteTabs tabs={tabs} />
      {onRoot ? (
        <Navigate to="/security/tamper" replace />
      ) : (
        <Routes>
          <Route path="tamper" element={<TamperTab />} />
          <Route path="malformed-gate" element={<MalformedTab />} />
          <Route path="mtls-bench" element={<MtlsBenchTab />} />
          <Route path="hygiene" element={<HygieneTab />} />
          <Route path="contracts" element={<ContractsTab />} />
          <Route path="benchmarks" element={<BenchmarksTab />} />
          <Route path="*" element={<Navigate to="tamper" replace />} />
        </Routes>
      )}
    </div>
  );
}

function ToolCard({ icon, title, contract, summary, commands, links }: {
  icon: ReactNode;
  title: string;
  contract: string;
  summary: string;
  commands: string[];
  links?: Array<{ href: string; label: string }>;
}) {
  return (
    <Card>
      <CardHeader title={<span className="inline-flex items-center gap-2">{icon}{title}</span>} description={contract} />
      <p className="text-2xs text-ink-muted leading-relaxed mb-3">{summary}</p>
      <pre className="panel p-3 font-mono text-2xs overflow-x-auto whitespace-pre-wrap">
        {commands.join("\n\n")}
      </pre>
      {links && links.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2 text-2xs">
          {links.map((l) => (
            <a key={l.href} href={l.href} className="text-brand hover:underline">
              {l.label}
            </a>
          ))}
        </div>
      )}
    </Card>
  );
}

function TamperTab() {
  return (
    <ToolCard
      icon={<Fingerprint className="w-4 h-4 text-brand" />}
      title="审计篡改检测"
      contract="audit_tamper_resistance/v1"
      summary="对 audit_chain.json 与 audit_chain.seal.json 的 6 个候选位置做 single-byte bit flip，断言 verify_audit_bundle 都能检测并自愈。默认 contract smoke 直接接到主线 audit chain 上跑通。"
      commands={[
        "python3 scripts/verify_audit_tamper_resistance.py \\\n  --out-base $REPO/tmp/sse_bridge_pipeline_demo \\\n  --report /tmp/audit_tamper_resistance.json",
        "# 单字节翻转点为：chain header / seal header / chain.events[*] / seal.signature[*]\n# 每次变异后还原原始字节，保证 audit chain 不被破坏",
      ]}
    />
  );
}

function MalformedTab() {
  return (
    <ToolCard
      icon={<ShieldOff className="w-4 h-4 text-brand" />}
      title="HTTP 异常输入 gate"
      contract="http_malformed_input_gate/v1"
      summary="loopback 起 in-process record-recovery HTTP service，跑 10 个攻击 scenario（缺签名 / 过期 timestamp / SQL-injection 模式 caller-tenant-job_id / 坏 JSON / 非 object payload / 缺必填 / 错 method / 未知 path / 超大 body），断言每个都被拒绝。"
      commands={[
        "python3 scripts/check_http_malformed_input_gate.py \\\n  --report /tmp/http_malformed_input_gate.json",
        "# 期望 10/10 detected；任何 false negative 直接 fail",
      ]}
    />
  );
}

function MtlsBenchTab() {
  return (
    <ToolCard
      icon={<GaugeCircle className="w-4 h-4 text-brand" />}
      title="mTLS 基准（plaintext vs mTLS / fresh vs keep-alive）"
      contract="recovery_mtls_benchmark/v1"
      summary="loopback 起 plaintext + mTLS 两套 in-process HTTP 服务（mock 证书），用 http.client 直连分别在 fresh / persistent 连接模式下打 /health；记录 p50/p95、mTLS overhead p95 与 keep-alive savings。"
      commands={[
        "python3 scripts/benchmark_mtls_overhead.py \\\n  --iterations 5 \\\n  --report /tmp/recovery_mtls_benchmark.json",
        "# 本地参考：fresh-connection mTLS overhead p95 ≈ 1.6ms",
      ]}
    />
  );
}

function HygieneTab() {
  return (
    <div className="space-y-4">
      <ToolCard
        icon={<Bug className="w-4 h-4 text-brand" />}
        title="Repo 卫生扫描"
        contract="repo_hygiene_report/v1"
        summary="扫描 tracked 第一方文件，命中高置信度凭证（AWS / Slack / GitHub PAT / private key）或 tracked 生成产物；CI smoke 默认强制 fail。"
        commands={["bash scripts/check_ci_smoke.sh   # 含 repo_hygiene 扫描"]}
      />
      <ToolCard
        icon={<TestTube2 className="w-4 h-4 text-brand" />}
        title="依赖卫生"
        contract="dependency_hygiene_report/v1"
        summary="检查 first-party Python / Cargo 依赖锁定与可重复性，无网络访问。"
        commands={["python3 scripts/check_dependency_hygiene.py --report /tmp/dep_hygiene.json"]}
      />
    </div>
  );
}

function ContractsTab() {
  return (
    <ToolCard
      icon={<ShieldCheck className="w-4 h-4 text-brand" />}
      title="契约 smoke 全跑"
      contract="json_contracts.sh + check_ci_smoke.sh"
      summary="80+ JSON schema + schema_backcompat baseline + 主链路完整产物校验。一次跑完所有 contract 验证。"
      commands={[
        "bash scripts/check_json_contracts.sh",
        "bash scripts/check_ci_smoke.sh   # 更宽，含 cargo / shell / Python compile / hygiene",
      ]}
    />
  );
}

function BenchmarksTab() {
  const benches = [
    { name: "query_workflow_benchmark/v1", script: "scripts/benchmark_query_workflow.py" },
    { name: "read_adapter_benchmark/v1", script: "scripts/benchmark_read_adapters.py" },
    { name: "sse_export_benchmark/v1", script: "scripts/benchmark_sse_export.py" },
    { name: "record_recovery_benchmark/v1", script: "scripts/benchmark_record_recovery.py" },
    { name: "audit_bundle_benchmark/v1", script: "scripts/benchmark_audit_bundle.py" },
    { name: "platform_health_benchmark/v1", script: "scripts/benchmark_platform_health.py" },
    { name: "derived_views_benchmark/v1", script: "scripts/benchmark_derived_views.py" },
    { name: "pipeline_benchmark/v1", script: "scripts/benchmark_pipeline.py" },
    { name: "pjc_benchmark/v1", script: "scripts/benchmark_pjc.py" },
    { name: "live_sse_benchmark/v1", script: "scripts/benchmark_live_sse_demo.py" },
    { name: "bridge_benchmark/v1", script: "scripts/benchmark_bridge.py" },
    { name: "dashboard_jobs_benchmark/v1", script: "scripts/benchmark_dashboard_jobs.py" },
    { name: "smoke_benchmark/v1", script: "scripts/benchmark_smoke.py" },
  ];
  return (
    <Card>
      <CardHeader title="Benchmark 画廊" description="13+ 子 benchmark；每个 emit 自己的契约报告并被 contract smoke 校验。" />
      <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {benches.map((b) => (
          <li key={b.name} className="panel-soft p-3 rounded-lg flex items-start gap-2">
            <Sparkles className="w-4 h-4 text-brand mt-0.5 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="font-mono text-2xs text-brand truncate">{b.name}</div>
              <div className="text-2xs text-ink-muted mt-0.5 truncate">{b.script}</div>
            </div>
          </li>
        ))}
      </ul>
      <pre className="mt-4 panel p-3 font-mono text-2xs overflow-x-auto">
{`# Common usage
python3 scripts/benchmark_smoke.py --target sse-export-scale --scale 100000
python3 scripts/benchmark_record_recovery.py \\
  --mode g2b_acceptance --concurrency 10 --candidate-count 1000`}
      </pre>
    </Card>
  );
}
