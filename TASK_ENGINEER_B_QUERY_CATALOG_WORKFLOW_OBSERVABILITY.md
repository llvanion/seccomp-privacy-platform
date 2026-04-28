# 任务书 2：工程师 B 负责的查询入口、目录、工作流、观测与产品壳

## 1. 任务定位

你负责把当前原型包装成更像“数据库平台”的使用体验。

你的任务不是重写隐私计算内核，而是在冻结接口之上补：

1. 查询入口
2. 数据目录
3. 作业工作流
4. 观测和告警
5. 管理 UI / SDK 原型
6. benchmark 和安全扫描

你的工作应该尽量通过 adapter 调用现有 CLI 和现有产物，不要改主链路语义。

## 2. 任务边界

### 你可以做

1. 设计 SQL-like 或 declarative query API 的外层接口。
2. 调研并试接 DataFusion / pgwire / Arrow Flight SQL。
3. 设计 catalog 和 lineage 页面或 API。
4. 用 Temporal 设计 durable workflow 版本的 pipeline。
5. 用 OpenTelemetry Collector 和 Grafana 做 metrics / traces / dashboard。
6. 做 SDK 或管理后台原型。
7. 做 benchmark、dependency scan、secret scan、malformed input 测试。

### 你不能做

1. 不能直接让 SQL 绕过 SSE export policy。
2. 不能直接读取 encrypted record store 并绕过 record recovery service。
3. 不能改 PJC 输入格式。
4. 不能改 `bridge` token 生成逻辑。
5. 不能把查询接口设计成能返回高敏感字段明文。
6. 不能把 Temporal 工作流改成新的事实接口，第一阶段只能包装现有 CLI。

## 3. 推荐技术栈

第一阶段：

1. Python 3
2. Bash adapter
3. JSON / JSONL / CSV contract
4. OpenTelemetry text / JSON export
5. Markdown runbook
6. GitHub Actions

第二阶段：

1. Rust DataFusion
2. pgwire
3. Arrow Flight SQL / ADBC
4. Temporal
5. OpenTelemetry Collector
6. Grafana
7. OpenMetadata
8. Hasura 或 PostgREST

## 4. 对应 GitHub 库

| 能力 | 推荐项目 | GitHub |
| --- | --- | --- |
| SQL parser / planner / execution engine | Apache DataFusion | https://github.com/apache/datafusion |
| PostgreSQL wire protocol | pgwire | https://github.com/sunng87/pgwire |
| Arrow / Flight SQL / ADBC 生态 | Apache Arrow | https://github.com/apache/arrow |
| Durable workflow | Temporal | https://github.com/temporalio/temporal |
| Telemetry collector | OpenTelemetry Collector | https://github.com/open-telemetry/opentelemetry-collector |
| Dashboard / visualization | Grafana | https://github.com/grafana/grafana |
| Metadata catalog / lineage / governance UI | OpenMetadata | https://github.com/open-metadata/OpenMetadata |
| GraphQL API for control plane | Hasura | https://github.com/hasura/graphql-engine |

优先级建议：

1. 先做观测和 runbook，因为对主链路侵入最小。
2. 再做 Temporal workflow wrapper，只包装现有 CLI。
3. 再做 catalog / metadata UI，读取工程师 A 的 control-plane DB。
4. 最后再做 SQL / pgwire / DataFusion 原型。

## 5. 查询入口边界

未来 SQL-like 接口必须遵守：

1. 查询必须先经过 policy validation。
2. 细粒度查询只能调用 SSE export，不允许直接扫明文。
3. 跨机构协作查询只能走 bridge + PJC。
4. 查询结果必须进入 policy release。
5. 查询审计必须写入 `audit_chain`。

建议把查询分成三类：

| 查询类型 | 允许路径 | 例子 |
| --- | --- | --- |
| 平台内部细粒度查询 | SSE export + record recovery | 查询某时间段内允许字段 |
| 商家分析查询 | policy-filtered aggregate | 查询店铺维度聚合，不返回家庭地址 |
| 广告协作查询 | bridge + PJC + release | 计算广告曝光用户和购买用户交集 |

不要第一阶段就实现通用 SQL 全能力。先做受限查询模板。

## 6. Temporal 工作流边界

Temporal 第一阶段只做 wrapper。

一个 workflow 可以拆成：

1. `ValidatePolicyActivity`
2. `RunSseExportActivity`
3. `RunRecordRecoveryHealthCheckActivity`
4. `RunBridgePrepareJobActivity`
5. `RunPjcActivity`
6. `RunPolicyReleaseActivity`
7. `BuildAuditChainActivity`

每个 activity 第一阶段都调用现有 CLI：

```bash
bash scripts/run_sse_bridge_pipeline.sh ...
```

或者调用更细粒度脚本。不要在 Temporal activity 里重写隐私计算逻辑。

## 7. Observability 边界

你需要围绕现有阶段定义统一 telemetry 字段：

1. `job_id`
2. `correlation_id`
3. `caller`
4. `tenant_id`
5. `dataset_id`
6. `service_id`
7. `stage`
8. `status`
9. `duration_ms`
10. `row_count`
11. `artifact_sha256`

第一阶段可以从现有 audit JSONL 生成 metrics，不要求修改每个模块直接打点。

## 8. Catalog 边界

OpenMetadata 或自研 catalog adapter 只记录：

1. dataset 元数据
2. schema 版本
3. policy 绑定
4. job lineage
5. artifact lineage
6. public report lineage

Catalog 不保存：

1. 用户家庭地址明文
2. 完整手机号明文
3. 原始 join key 明文
4. recovery secret
5. bridge token secret

## 9. 现有接口和调用方式

### 跑端到端 demo

```bash
bash scripts/run_live_sse_bridge_demo.sh
```

### 跑 contract smoke

```bash
bash scripts/check_json_contracts.sh
```

### 运行 pipeline

```bash
bash scripts/run_sse_bridge_pipeline.sh \
  --server-input <server-source> \
  --client-input <client-source> \
  --job-id <job-id> \
  --token-scope <scope> \
  --token-secret-env BRIDGE_TOKEN_SECRET
```

### 读取 audit chain

```bash
python3 scripts/build_audit_chain.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --job-id auto_demo_job
```

### 查询 metadata sidecar

如果工程师 A 的 sidecar 已完成，可以读取：

```bash
python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --job-id auto_demo_job
```

## 10. UI / SDK 原型边界

UI 或 SDK 只能调用：

1. control-plane read API
2. job submit adapter
3. audit query adapter
4. public report query adapter

不能直接调用：

1. encrypted record store reader
2. bridge token secret
3. PJC raw binary
4. raw recovery service without policy

## 11. Benchmark 和安全检查

你可以补：

1. pipeline latency benchmark
2. record recovery latency benchmark
3. PJC run latency benchmark
4. dependency scanning
5. secret scanning
6. malformed CSV / JSONL fuzz fixtures
7. schema backward-compatibility check

建议输出：

1. `docs/BENCHMARK_PLAN.md`
2. `docs/OBSERVABILITY_PLAN.md`
3. `docs/QUERY_INTERFACE_PLAN.md`
4. `docs/CATALOG_LINEAGE_PLAN.md`

## 12. 变更规则

如果你需要主链路新增字段：

1. 不直接改代码。
2. 先写 `docs/change_requests/<topic>.md`。
3. 说明新增字段、来源、消费者、兼容方式。
4. 等项目负责人批准后再实现。

## 13. 验收标准

完成定义：

1. 有一版查询入口设计，不绕过隐私策略。
2. 有一版 workflow wrapper 设计，不重写主链路。
3. 有一版 observability 字段和 dashboard 设计。
4. 有 catalog / lineage 方案，且不保存敏感明文。
5. 有 benchmark / security scan 计划。
6. 所有实现都通过现有 CLI 和 JSON/JSONL contract 协作。
