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

或者通过本地只读 metadata API 供 UI / SDK prototype 调用：

```bash
export SECCOMP_METADATA_API_TOKEN=local-metadata-token
python3 scripts/serve_metadata_api.py \
  --db-path tmp/platform_metadata.db \
  --bind-host 127.0.0.1 \
  --port 18090 \
  --auth-token-env SECCOMP_METADATA_API_TOKEN
```

或者通过结构化 query/workflow wrapper 先做 dry-run，再决定是否执行：

```bash
python3 scripts/submit_query_workflow.py \
  --request-file <request.json> \
  --dry-run
```

或者通过本地 HTTP submit API 给 UI / SDK prototype 调用同一个 adapter：

```bash
export SECCOMP_QUERY_WORKFLOW_API_TOKEN=local-query-token
python3 scripts/serve_query_workflow_api.py \
  --bind-host 127.0.0.1 \
  --port 18091 \
  --auth-token-env SECCOMP_QUERY_WORKFLOW_API_TOKEN
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

## 14. 当前实现状态

已落地的第一阶段 sidecar：

1. `scripts/export_observability_events.py`：从 `audit_chain.json` 导出 `pipeline_observability/v1`，覆盖 `job_id`、`correlation_id`、`caller`、`tenant_id`、`dataset_id`、`service_id`、`stage`、`status`、`duration_ms`、`row_count`、`artifact_sha256`。
2. `scripts/export_catalog_lineage.py`：从同一个 `audit_chain.json` 导出 `catalog_lineage/v1`，记录 job、dataset、service、artifact hash、row count 和跨阶段 lineage edge。
3. 这些导出器只读取现有审计链，不直接调用 SSE、record recovery、bridge、PJC 或 policy release，也不改变主链路输出语义。
4. `schemas/pipeline_observability.schema.json` 和 `schemas/catalog_lineage.schema.json` 已定义这两个 sidecar 输出的正式 contract，`scripts/check_json_contracts.sh` 现在会同时做 schema 校验和语义 smoke，确保至少覆盖 `sse_export`、`record_recovery_service`、`bridge`、`pjc`、`policy_release` 五个阶段，并继续验证默认不泄露 artifact path。
5. 当前阶段审计已原生补上 `duration_ms`：SSE export、record recovery service、bridge、PJC、policy release 都会把本阶段耗时写进各自 audit，`pipeline_observability/v1` 直接透传这些时长，不再依赖相邻阶段时间戳猜测。
6. `scripts/serve_metadata_api.py`：在已有 SQLite metadata sidecar 之上提供本地只读 HTTP API，供 UI / SDK / control-plane read adapter 调用 `jobs` 和 registry / policy 视图；它只读 `platform_metadata.db`，不直接触达隐私主链路。它的 health/success/error envelope 现在也冻结到了 `schemas/metadata_api_*.schema.json`，并纳入 contract smoke 与 schema backcompat guard。
7. `scripts/submit_query_workflow.py`：提供第一阶段结构化 query/workflow submit adapter，把受限请求 JSON 映射到现有 `scripts/run_sse_bridge_pipeline.sh` 参数，支持 `--dry-run`、`--execute` 和 redacted submission manifest；结构 contract 已冻结到 `schemas/query_workflow_request.schema.json` 与 `schemas/query_workflow_submission.schema.json`。
8. `scripts/serve_query_workflow_api.py`：在 submit adapter 之上补本地 HTTP 包装层，供 UI / SDK prototype 发起 dry-run 请求；默认不开放 execute 端点，只有显式 `--allow-execute` 才允许实际执行；health/success/error envelope 已冻结到 `schemas/query_workflow_api_*.schema.json`，并纳入 contract smoke。
9. `scripts/platform_api_client.py`：提供一个非常薄的本地 SDK/CLI prototype，同时包装 metadata read API、query submit API、audit/public-report read API 和 platform health API，方便后续 UI / SDK 直接复用统一调用姿势；它不引入新的平台语义，只转发现有 sidecar HTTP contract。默认 contract smoke 现在会直接覆盖 metadata `health/job/jobs`、audit `health/audit-chain/catalog-lineage` 这些 client 入口，还会走 query `--execute` disabled 分支与 audit `--include-paths` 分支，而不再只校验 permissions / public-report / observability。
10. `scripts/serve_audit_query_api.py`：在已完成 run 目录之上补本地只读 audit/public-report query adapter，直接暴露 `public_report.json`、`audit_chain.json`，并按需导出 `pipeline_observability/v1` 与 `catalog_lineage/v1`；health/success/error envelope 已冻结到 `schemas/audit_query_api_*.schema.json`，并纳入 contract smoke。
11. `scripts/check_schema_backcompat.py`：对已经冻结的 sidecar/public-report/audit schema 做 backward-compatibility guard，防止随手改 `$id`、删除稳定字段或新增 required 字段后才在联调时暴露问题；现在还把 `platform_health/v1`、默认 contract smoke 依赖的 benchmark/report schema、`record_recovery_service_log/v1` / `record_recovery_boundary_check/v1` / `schema_backcompat_check/v1` 这些稳定 runtime/report contract、`audit_seal/v1` / `audit_archive_index/v1` / `record_recovery_service_config/v1` / `record_recovery_service_policy/v1` / `external_kms_config/v1` / `keyring/v1` / `key_manifest/v1` 这些共享配置与保留 contract，以及 `sse_bridge_export_audit/v1` / `bridge_job_meta/v1` / `bridge_audit/v1` / `pjc_audit/v1` / `policy_audit/v1` / `key_access_audit/v1` / `key_lifecycle_audit/v1` / `sse_record_recovery_service_audit/v1` / `sse_encrypted_record_store/v1` / `sse_export_policy/v1` 这些主链路稳定 contract 一并纳入 baseline，避免这类 contract 漂移只能靠 shape 校验才发现；输出 `schema_backcompat_check/v1`，并纳入 CI smoke 与 contract smoke。
12. `scripts/benchmark_query_workflow.py`：对 query/workflow 第一阶段入口做 dry-run latency benchmark，覆盖 CLI adapter、HTTP submit API 和 `platform_api_client.py` 三种入口；输出 `query_workflow_benchmark/v1`，并纳入 contract smoke。默认 smoke 现在还会断言 `--mode all` 仍覆盖完整 3 个 dry-run mode，避免 wrapper 入口回退后只剩 schema 还在通过。
13. `scripts/benchmark_read_adapters.py`：对 metadata `job/jobs/entity` 与 audit `audit-chain/public-report/observability/catalog-lineage` read adapter 做只读 latency benchmark，基于临时 synthetic completed-run fixture 与 sidecar DB 覆盖 CLI、HTTP API 和 `platform_api_client.py` 两层入口；输出 `read_adapter_benchmark/v1`，并纳入 contract smoke。默认 smoke 现在还会断言 `--mode all` 仍覆盖完整 16 个 mode，并额外钉住 metadata `job/jobs` 路径上的 `mainline_contract_summary` 语义以及 jobs-list 顶层 `mainline_contract_summary_counts` 聚合，避免实现继续扩展后文档和校验再次脱节。
14. `scripts/benchmark_record_recovery.py`：对 record recovery 独立服务边界做 latency benchmark，覆盖 Unix-socket / HTTP 两种 transport 下的 `health` 和 `recover` 操作；基于临时 synthetic encrypted record store 与 standalone service lifecycle，输出 `record_recovery_benchmark/v1`，并纳入 contract smoke。默认 smoke 现在还会断言完整 transport/operation mode 集合和 synthetic recover 的 `output_rows=2` 语义，避免 benchmark 只剩“跑通”而不再约束结果。
15. `scripts/benchmark_pipeline.py`：对 `scripts/run_sse_bridge_pipeline.sh` 做 full pipeline latency benchmark，覆盖默认 `file` cleanup、显式 retained file handoff compatibility mode、`fifo` 三种 handoff mode，并校验每次结果仍为 `intersection_size=2` / `intersection_sum=425` 以及 handoff cleanup 状态；输出 `pipeline_benchmark/v1`。由于它直接执行 bridge + PJC 主链路，当前只作为本地可复现 benchmark，不纳入默认 contract smoke。
16. `scripts/benchmark_pjc.py`：对 `a-psi/moduleA_psi/scripts/run_pjc.sh` 做 PJC-only latency benchmark，基于已准备好的 `bridge/out/sse_demo_job/` fixture，校验 `attribution_result.json` 仍为 `intersection_size=2` / `intersection_sum=425`；输出 `pjc_benchmark/v1`。由于它直接执行 PJC server/client 路径，当前只作为本地可复现 benchmark，不纳入默认 contract smoke。
17. `scripts/benchmark_live_sse_demo.py`：对 `scripts/run_live_sse_bridge_demo.sh` 做 live SSE-backed latency benchmark，覆盖默认 `file` cleanup、显式 retained file handoff compatibility mode、`fifo` 三种 handoff mode，并校验 `live_demo_manifest.json` / `public_report.json` 最终仍可归一化为 `intersection_size=2` / `intersection_sum=425` 以及 handoff cleanup 状态；输出 `live_sse_benchmark/v1`。由于它会启动或复用本地 SSE server 并 bootstrap fresh demo service，当前只作为本地可复现 benchmark，不纳入默认 contract smoke。
18. `scripts/benchmark_audit_bundle.py`：对 `scripts/archive_audit_bundle.py` 与 `scripts/verify_audit_bundle.py` 做 audit retention / verify / restore latency benchmark，覆盖 direct verify、archive-index verify 与 restore 三种 audit readback 路径；基于临时 synthetic HMAC-sealed audit bundle，输出 `audit_bundle_benchmark/v1`，并纳入 contract smoke。默认 smoke 现在还会断言各 mode 下 `archive_index_verified` / `restored` 标志位不漂移。
19. `schemas/platform_health.schema.json`：把 `scripts/check_platform_health.py` 的 read-only health summary envelope 固化为正式 contract，覆盖 `summary` 和按 component 列表化的 `checks`。
20. `scripts/benchmark_platform_health.py`：对 platform-health 读侧入口做 synthetic latency benchmark，覆盖 `scripts/check_platform_health.py` 的 `--out-base` / `--metadata-db` / combined 三种 CLI probe，以及 `scripts/serve_platform_health_api.py` 的 direct HTTP 读取和 `platform_api_client.py platform-health` 的 client 入口；复用临时 completed-run fixture 与 imported metadata DB，输出 `platform_health_benchmark/v1`，并纳入 contract smoke。默认 smoke 现在还会断言每种 mode 的 component 集合，同时保留受限环境下 CLI-only fallback 的显式兼容。
21. `scripts/serve_platform_health_api.py`：在现有 `scripts/check_platform_health.py` 之上补本地只读 HTTP wrapper，复用同一个 `platform_health/v1` 报告生成逻辑，为 UI / SDK / ops shell 提供 loopback + bearer-token 读取面；它不新增平台语义，只把现有 read-only probe 通过 `schemas/platform_health_api_*.schema.json` 暴露出来，并纳入 contract smoke 与 schema backcompat guard。
22. `scripts/benchmark_derived_views.py`：对 `scripts/export_observability_events.py` 和 `scripts/export_catalog_lineage.py` 做 synthetic latency benchmark，覆盖 observability 导出、catalog 默认脱敏导出和 `--include-paths` 两种模式；复用临时 completed-run fixture 生成的 `audit_chain.json`，输出 `derived_views_benchmark/v1`，并纳入 contract smoke。默认 smoke 现在还会断言三种 mode、observability 事件覆盖，以及 catalog 默认脱敏和显式含路径导出的分界。

当前调用方式：

```bash
python3 scripts/export_observability_events.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --out tmp/sse_bridge_pipeline_demo/pipeline_observability.json
```

```bash
python3 scripts/export_catalog_lineage.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --out tmp/sse_bridge_pipeline_demo/catalog_lineage.json
```

```bash
python3 scripts/serve_audit_query_api.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --bind-host 127.0.0.1 \
  --port 18092 \
  --auth-token-env SECCOMP_AUDIT_QUERY_API_TOKEN
```

边界说明：

1. 旧运行里的 `duration_ms` 仍然允许为 `null`，因为历史 audit records 没有统一记录阶段耗时；按当前实现重跑后的新运行会直接带上阶段 `duration_ms`。
2. `catalog_lineage/v1` 默认不输出完整 artifact path，只输出元数据、hash、计数和 lineage 关系；只有显式传 `--include-paths` 才会写入路径。
3. 这些文件是 sidecar 输出，不是新的主链路 contract；后续若要让主链路直接生成它们，应先走接口变更流程。
4. `scripts/submit_query_workflow.py` 当前只是 adapter，不是新的 pipeline engine；第一阶段 request / manifest / HTTP envelope 结构已经用本地 schema 冻结，但如果后续要把它升级成正式对外 API，仍然需要补 compatibility policy、版本策略和更严格的语义约束说明。
5. `scripts/serve_audit_query_api.py` 只允许读取现有 completed run 产物和基于 `audit_chain.json` 的派生视图；它不是新的审计真相源，也不负责生成或修改任何主链路 artifact。

## 15. 平台级剩余工作量估算

按 [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md) 的统一口径，这条线从“当前 sidecar/read adapter 基线”推进到“平台基线版”还需要：

1. `8 blocks`
2. 约 `40h`

建议拆分：

1. `2 blocks / 10h`：把 query/workflow wrapper 的 execute 路径补成更正式的权限、兼容和审计策略，而不只是 dry-run adapter。
2. `2 blocks / 10h`：在现有 observability / catalog / audit / platform-health contract 之上补 dashboard、alert example、operator 视图或 UI 壳。
3. `2 blocks / 10h`：把 workflow wrapper 再推进到更 durable 的 job submit/status 形态，但仍然只包装现有 CLI，不重写主链路。
4. `2 blocks / 10h`：把 `platform_api_client.py`、metadata/audit/query/platform-health read adapter 再收成更完整的 SDK/admin shell baseline，并补回归样例。

不含：

1. 通用 SQL 引擎全能力。
2. 真正的 pgwire / Flight SQL 产品化。
3. 完整前端管理台发布流程。
