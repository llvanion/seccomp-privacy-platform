import { useMemo, useState } from "react";
import { Search, Database, RefreshCw, FileJson } from "lucide-react";

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
  Textarea,
  inferStatusKind,
} from "@/components/ui";
import { StaticTabs } from "@/components/tabs";
import { DataTable, type Column } from "@/components/data-table";
import { formatDuration, formatNumber } from "@/lib/format";
import type { SseSearchResponse } from "@/api/types";

type DbMode = "inline" | "path";
type OutputFormat = "hex" | "int" | "raw" | "utf8";

const DEFAULT_INLINE = `{
  "China": ["3A4B1ACC12AA1B2D", "2DDD1FFF1122BBCC", "1122AA4B101A2812", "C2C2C2C21010AACC"],
  "Github": ["1A1ADD2C2320A1CC", "2222CC1F1421A22A"],
  "Chen": ["1BB2BB2B1010112A", "233278781010212C", "88771ABB101AA02B"]
}`;

const DEFAULT_PATH = "$REPO/sse/example_db.json";

export function SseQueryRoute() {
  const [dbMode, setDbMode] = useState<DbMode>("inline");
  const [dbInline, setDbInline] = useState(DEFAULT_INLINE);
  const [dbPath, setDbPath] = useState(DEFAULT_PATH);
  const [keyword, setKeyword] = useState("China");
  const [outputFormat, setOutputFormat] = useState<OutputFormat>("hex");
  const [scheme, setScheme] = useState("CJJ14.PiBas");
  const [serviceName, setServiceName] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);

  const mutation = useApiMutation(
    async () => {
      const payload: Parameters<typeof operatorApi.sseSearch>[0] = {
        keyword,
        output_format: outputFormat,
        scheme,
        service_name: serviceName || undefined,
        timeout_sec: 60,
      };
      if (dbMode === "inline") {
        try {
          payload.db = JSON.parse(dbInline);
          setParseError(null);
        } catch (exc) {
          setParseError((exc as Error).message);
          throw new Error("DB JSON 不合法");
        }
      } else {
        payload.db_path = dbPath;
      }
      return operatorApi.sseSearch(payload);
    },
    { errorToast: true },
  );

  const data: SseSearchResponse | undefined = mutation.data;
  const ok = data?.status === "ok";

  const matches = useMemo<Array<{ index: number; value: string }>>(() => {
    if (!ok || !data?.matches) return [];
    return data.matches.map((value, index) => ({ index: index + 1, value }));
  }, [ok, data]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="SSE 关键字搜索"
        description={
          <>
            执行一次性的端到端 SSE 查询：临时启动 SSE 服务端、注册服务、加密上传倒排索引，运行 keyword search，并把命中文档 ID 返回。所有过程通过{" "}
            <code className="text-brand">POST /v1/sse/search</code> 调用本地{" "}
            <code className="text-brand">scripts/sse_oneshot_search.py</code>。
          </>
        }
        actions={
          <Button
            variant="primary"
            leftIcon={<Search className="w-4 h-4" />}
            onClick={() => mutation.mutate(undefined as never)}
            loading={mutation.isPending}
          >
            执行搜索
          </Button>
        }
      />

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2">
          <CardHeader title="加密数据库" description="倒排索引 keyword → [document_id...] 格式；可粘贴 JSON 或指向已有文件" actions={<Database className="w-4 h-4 text-ink-dim" />} />
          <StaticTabs<DbMode>
            tabs={[
              { id: "inline", label: "粘贴 JSON" },
              { id: "path", label: "文件路径" },
            ] as const}
            value={dbMode}
            onChange={setDbMode}
          />
          {dbMode === "inline" ? (
            <Field label="DB JSON" hint="格式：{ keyword: [doc_id, ...] }" error={parseError ?? undefined}>
              <Textarea
                value={dbInline}
                onChange={(e) => setDbInline(e.target.value)}
                spellCheck={false}
                className="min-h-[220px]"
              />
            </Field>
          ) : (
            <Field label="DB 文件路径" hint="服务端可读的绝对路径（$REPO 占位符不解析）">
              <Input value={dbPath} onChange={(e) => setDbPath(e.target.value)} placeholder="/abs/path/example_db.json" />
            </Field>
          )}
        </Card>

        <Card>
          <CardHeader title="查询参数" />
          <div className="space-y-3">
            <Field label="关键字 *">
              <Input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="China" />
            </Field>
            <Field label="输出格式">
              <Select value={outputFormat} onChange={(e) => setOutputFormat(e.target.value as OutputFormat)}>
                <option value="hex">hex</option>
                <option value="int">int</option>
                <option value="raw">raw</option>
                <option value="utf8">utf8</option>
              </Select>
            </Field>
            <Field label="SSE scheme">
              <Select value={scheme} onChange={(e) => setScheme(e.target.value)}>
                <option value="CJJ14.PiBas">CJJ14.PiBas</option>
              </Select>
            </Field>
            <Field label="服务实例名" hint="留空则自动生成 sse-oneshot-<ts>">
              <Input value={serviceName} onChange={(e) => setServiceName(e.target.value)} placeholder="自动" />
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
                  hint={data.stage ?? "search"}
                />
                <StatTile label="命中数" value={ok ? formatNumber(data.match_count) : "—"} hint="documents" kind="info" />
                <StatTile label="耗时" value={formatDuration(data.duration_ms)} hint="server bootstrap → search" />
                <StatTile label="服务端口" value={<span className="font-mono text-2xs">{data.server_endpoint ?? "—"}</span>} hint="临时" />
              </section>

              <Card>
                <CardHeader title="命中文档" actions={<RefreshCw className="w-4 h-4 text-ink-dim" />} />
                {ok && matches.length > 0 ? (
                  <DataTable
                    rows={matches}
                    columns={[
                      { id: "i", header: "#", cell: (r) => <span className="font-mono text-2xs text-ink-muted">{r.index}</span>, width: "60px" },
                      { id: "v", header: "document_id", cell: (r) => <span className="font-mono text-2xs text-brand break-all">{r.value}</span> },
                    ]}
                    rowKey={(r) => `${r.index}-${r.value}`}
                  />
                ) : ok ? (
                  <p className="text-2xs text-ink-muted">关键字 <span className="text-ink font-mono">{data.keyword}</span> 在索引中没有命中。</p>
                ) : (
                  <p className="text-2xs text-accent-warn">{data.message ?? "查询失败"}</p>
                )}
              </Card>

              <Card>
                <CardHeader title="原始响应 JSON" actions={<FileJson className="w-4 h-4 text-ink-dim" />} />
                <JsonBlock data={data} maxHeight="320px" />
              </Card>
            </>
          ) : null}
        </section>
      )}

      <Card>
        <CardHeader title="安全提示" />
        <ul className="text-2xs text-ink-muted space-y-1.5 leading-relaxed">
          <li>· 关键字 <b>明文不离开浏览器到服务端</b> 之外的范围：服务端把关键字传给本机 SSE 客户端，客户端在本地完成 token 派生后才发送到 SSE 服务端。</li>
          <li>· 每次查询起 / 停一份临时 SSE 服务（随机本地端口），上传索引完成后再做搜索；服务实例 + 临时工作目录在查询结束后被清理。</li>
          <li>· 此页面适合"一键演示 / 临时排查"。长期运行的索引应通过 <code className="text-brand">sse/run_server.py</code> 部署成常驻服务，并由 record-recovery / bridge 模块消费。</li>
        </ul>
      </Card>
    </div>
  );
}
