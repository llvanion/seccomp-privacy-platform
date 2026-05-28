import { useState } from "react";
import { Calculator, FileJson, FileSpreadsheet, Play, Shield } from "lucide-react";

import { operatorApi } from "@/api/operator";
import { useApiMutation } from "@/hooks/useApi";
import {
  Button,
  Card,
  CardHeader,
  Field,
  Input,
  JsonBlock,
  PageHeader,
  Select,
  Skeleton,
  StatTile,
  StatusPill,
  inferStatusKind,
} from "@/components/ui";
import { formatDuration, formatNumber } from "@/lib/format";
import type { PjcRunOnlyResponse } from "@/api/types";

export function PjcOnlyRoute() {
  const [serverCsv, setServerCsv] = useState("/tmp/pjc_only_demo/server.csv");
  const [clientCsv, setClientCsv] = useState("/tmp/pjc_only_demo/client.csv");
  const [jobMeta, setJobMeta] = useState("/tmp/pjc_only_demo/job_meta.json");
  const [outDir, setOutDir] = useState("");
  const [jobId, setJobId] = useState("console-pjc-1");
  const [caller, setCaller] = useState("console-operator");
  const [tenantId, setTenantId] = useState("demo_tenant");
  const [datasetId, setDatasetId] = useState("demo_dataset");
  const [purpose, setPurpose] = useState("");
  const [thresholdK, setThresholdK] = useState("1");
  const [maxQueries, setMaxQueries] = useState("5");
  const [dpEpsilon, setDpEpsilon] = useState("");
  const [dpSensitivity, setDpSensitivity] = useState("");
  const [roundSumTo, setRoundSumTo] = useState("");
  const [denyDup, setDenyDup] = useState(false);
  const [pjcBuild, setPjcBuild] = useState<"prebuilt" | "rebuild">("prebuilt");

  const mutation = useApiMutation(
    async () => {
      return operatorApi.pjcRunOnly({
        server_csv: serverCsv,
        client_csv: clientCsv,
        job_meta: jobMeta || undefined,
        out_dir: outDir || undefined,
        job_id: jobId || undefined,
        caller: caller || undefined,
        tenant_id: tenantId || undefined,
        dataset_id: datasetId || undefined,
        purpose: purpose || undefined,
        threshold_k: numOr(thresholdK, 1),
        max_queries: numOr(maxQueries, 5),
        dp_epsilon: dpEpsilon ? Number(dpEpsilon) : null,
        dp_sensitivity: dpSensitivity ? Number(dpSensitivity) : null,
        round_sum_to: roundSumTo ? Number(roundSumTo) : null,
        deny_duplicate_query: denyDup,
        pjc_build: pjcBuild === "rebuild",
        timeout_sec: 900,
      });
    },
    { errorToast: true },
  );

  const data: PjcRunOnlyResponse | undefined = mutation.data;
  const ok = data?.status === "ok";
  const attribution = data?.attribution ?? {};
  const publicReport = data?.public_report ?? {};
  const intersectionSize = (attribution as { intersection_size?: number }).intersection_size;
  const intersectionSum = (attribution as { intersection_sum?: number }).intersection_sum;
  const released = (publicReport as { released?: boolean }).released;
  const reasonCode = (publicReport as { reason_code?: string }).reason_code;

  return (
    <div className="space-y-5">
      <PageHeader
        title="PJC 私有求交（独立运行）"
        description={
          <>
            跳过 SSE / bridge，直接对已有的 <code className="text-brand">server.csv</code> + <code className="text-brand">client.csv</code> 做 Private Intersection-Sum，跑完后再走策略发布门。后端通过{" "}
            <code className="text-brand">POST /v1/pjc/run-only</code> 调用本地{" "}
            <code className="text-brand">scripts/pjc_run_only.py</code>。
          </>
        }
        actions={
          <Button variant="primary" leftIcon={<Play className="w-4 h-4" />} onClick={() => mutation.mutate(undefined as never)} loading={mutation.isPending}>
            执行 PJC
          </Button>
        }
      />

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader title="bridge 输入" actions={<FileSpreadsheet className="w-4 h-4 text-ink-dim" />} description="bridge prepare-job 生成的两份 CSV + job_meta.json" />
          <div className="space-y-3">
            <Field label="server.csv 路径 *" hint="只含 HMAC 后的 join key 一列">
              <Input value={serverCsv} onChange={(e) => setServerCsv(e.target.value)} />
            </Field>
            <Field label="client.csv 路径 *" hint="HMAC join key + value 列">
              <Input value={clientCsv} onChange={(e) => setClientCsv(e.target.value)} />
            </Field>
            <Field label="job_meta.json 路径（可选）">
              <Input value={jobMeta} onChange={(e) => setJobMeta(e.target.value)} />
            </Field>
            <Field label="输出目录" hint="留空则使用 mkdtemp 临时目录">
              <Input value={outDir} onChange={(e) => setOutDir(e.target.value)} placeholder="/tmp/pjc_only_run" />
            </Field>
            <Field label="PJC 二进制">
              <Select value={pjcBuild} onChange={(e) => setPjcBuild(e.target.value as "prebuilt" | "rebuild")}>
                <option value="prebuilt">使用已编译产物（推荐，秒级）</option>
                <option value="rebuild">强制重新 bazel build（首次或更新时）</option>
              </Select>
            </Field>
          </div>
        </Card>

        <Card>
          <CardHeader title="作业 + 策略发布" actions={<Shield className="w-4 h-4 text-ink-dim" />} description="进入 policy_release.py 的 k-阈值 / 重复查询 / 隐私预算 / DP 噪声门" />
          <div className="grid grid-cols-2 gap-3">
            <Field label="job_id">
              <Input value={jobId} onChange={(e) => setJobId(e.target.value)} />
            </Field>
            <Field label="caller">
              <Input value={caller} onChange={(e) => setCaller(e.target.value)} />
            </Field>
            <Field label="tenant_id">
              <Input value={tenantId} onChange={(e) => setTenantId(e.target.value)} />
            </Field>
            <Field label="dataset_id">
              <Input value={datasetId} onChange={(e) => setDatasetId(e.target.value)} />
            </Field>
            <Field label="purpose" className="col-span-2">
              <Input value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="cross-party-attribution" />
            </Field>
            <Field label="k-阈值">
              <Input type="number" value={thresholdK} onChange={(e) => setThresholdK(e.target.value)} />
            </Field>
            <Field label="max_queries">
              <Input type="number" value={maxQueries} onChange={(e) => setMaxQueries(e.target.value)} />
            </Field>
            <Field label="DP epsilon" hint="留空 = 不加 Laplace 噪声">
              <Input type="number" value={dpEpsilon} onChange={(e) => setDpEpsilon(e.target.value)} placeholder="例如 1.0" />
            </Field>
            <Field label="DP sensitivity" hint="DP epsilon 启用时必填">
              <Input type="number" value={dpSensitivity} onChange={(e) => setDpSensitivity(e.target.value)} />
            </Field>
            <Field label="round_sum_to" hint="可选：把 intersection_sum 四舍五入到此粒度">
              <Input type="number" value={roundSumTo} onChange={(e) => setRoundSumTo(e.target.value)} />
            </Field>
            <Field label="重复查询拒绝">
              <label className="flex items-center gap-2 text-2xs text-ink-muted h-9 px-3 rounded-lg bg-bg-subtle border border-line cursor-pointer">
                <input type="checkbox" checked={denyDup} onChange={(e) => setDenyDup(e.target.checked)} />
                deny-duplicate-query
              </label>
            </Field>
          </div>
        </Card>
      </section>

      {(mutation.isPending || data) && (
        <section className="space-y-4">
          {mutation.isPending ? (
            <Card>
              <CardHeader title="结果" />
              <div className="space-y-2">
                <Skeleton className="h-6 w-1/3" />
                <Skeleton className="h-6 w-2/3" />
                <Skeleton className="h-32" />
              </div>
            </Card>
          ) : data ? (
            <>
              <section className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <StatTile
                  label="状态"
                  value={<StatusPill kind={inferStatusKind(data.status)}>{data.status}</StatusPill>}
                  hint={data.stage ?? "release"}
                />
                <StatTile label="intersection_size" value={ok ? formatNumber(intersectionSize) : "—"} hint="两方求交大小" kind="info" />
                <StatTile label="intersection_sum" value={ok ? formatNumber(intersectionSum) : "—"} hint="client value 求和" kind="info" />
                <StatTile label="耗时" value={formatDuration(data.duration_ms)} hint="run_pjc + policy_release" />
              </section>

              <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <Card>
                  <CardHeader title="attribution_result.json" actions={<Calculator className="w-4 h-4 text-ink-dim" />} description="PJC 求交原始输出（仅聚合值）" />
                  <JsonBlock data={data.attribution ?? {}} maxHeight="360px" />
                </Card>

                <Card>
                  <CardHeader
                    title={<span className="inline-flex items-center gap-2">public_report.json <StatusPill kind={released ? "ok" : "warn"}>{released ? "released" : "withheld"}</StatusPill></span>}
                    description={reasonCode ? `reason_code = ${reasonCode}` : "policy_release 决策"}
                    actions={<Shield className="w-4 h-4 text-ink-dim" />}
                  />
                  <JsonBlock data={data.public_report ?? {}} maxHeight="360px" />
                </Card>
              </section>

              <Card>
                <CardHeader title="工件路径" actions={<FileJson className="w-4 h-4 text-ink-dim" />} description="供后续 verify_audit_bundle / external anchor 引用" />
                <ul className="text-2xs font-mono space-y-1">
                  {data.artifacts &&
                    Object.entries(data.artifacts).map(([key, val]) =>
                      val ? (
                        <li key={key} className="flex justify-between gap-3 border-b border-line-subtle pb-1">
                          <span className="text-ink-muted">{key}</span>
                          <span className="text-ink truncate">{val}</span>
                        </li>
                      ) : null,
                    )}
                </ul>
              </Card>
            </>
          ) : null}
        </section>
      )}

      <Card>
        <CardHeader title="使用提示" />
        <ul className="text-2xs text-ink-muted space-y-1.5 leading-relaxed">
          <li>· 输入必须 <b>来自 bridge prepare-job</b>：原始 email/phone 永远不直接喂给 PJC。</li>
          <li>· 首次运行（或 PJC 源码更新后）选 "强制重新 bazel build"。常规重跑保持 "已编译产物" 即可，本机示例耗时 ~3 秒。</li>
          <li>· DP epsilon + DP sensitivity 同时填入才会注入 Laplace 噪声；epsilon 越小噪声越大。</li>
          <li>· 完整审计链需要在外层 <code className="text-brand">scripts/run_sse_bridge_pipeline.sh</code> 里跑——本页面只覆盖 PJC + policy_release 两步。</li>
        </ul>
      </Card>
    </div>
  );
}

function numOr(value: string, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}
