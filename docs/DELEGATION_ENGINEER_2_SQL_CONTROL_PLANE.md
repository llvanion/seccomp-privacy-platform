# 工程师 2 任务书：SQL 控制面侧车

## 1. 你的任务定位

你负责做的是控制面的 SQL 基础设施，但第一阶段只做 sidecar，不接管主链路。

这点非常重要：

1. 现在主链路仍然以文件、脚本、JSON/JSONL contract 为主。
2. 你做的 SQL 部分先作为持久化元数据层和查询层存在。
3. 第一阶段不要把 `sse`、`bridge`、`a-psi` 的运行流程改成“必须依赖数据库”。

你的目标不是重写现有系统，而是给现有系统补一个稳定的 control-plane 基础。

## 2. 你负责的具体任务

### 任务 A：设计控制面数据库 schema

你需要先给出一版数据库 schema，至少覆盖：

1. `tenants`
2. `datasets`
3. `services`
4. `callers`
5. `jobs`
6. `job_artifacts`
7. `audit_events`
8. `policy_bindings`
9. `key_access_events`

这版 schema 必须围绕当前已有字段设计，不要自己发明第二套命名体系。

当前已经在主链路里稳定存在的核心字段：

1. `job_id`
2. `correlation_id`
3. `caller`
4. `tenant_id`
5. `dataset_id`
6. `service_id`

### 任务 B：实现 migration / init / import 工具

你需要做：

1. 初始化数据库脚本
2. schema migration 脚本
3. 从现有运行产物导入数据库的脚本

第一阶段建议做成：

1. 纯 SQL migration 文件
2. Python 3 `sqlite3` 驱动的初始化和导入脚本

不要第一阶段就引入大型 ORM。

### 任务 C：做只读查询入口

你需要提供一个只读查询层，至少支持：

1. 按 `job_id` 查一次运行的全部元数据
2. 按 `caller` 查任务列表
3. 按 `tenant_id` / `dataset_id` 查任务列表
4. 查某次运行的审计产物路径
5. 查某次运行的 public report 摘要

这个查询层第一阶段可以是：

1. Python CLI
2. 或一个非常薄的本地只读 HTTP API

如果做 HTTP API，先提方案；默认优先 CLI。

## 3. 技术栈要求

第一阶段只允许使用下面的栈：

1. Python 3
2. 标准库 `sqlite3`
3. 纯 SQL migration 文件
4. `argparse`
5. JSON / JSONL 文件读取

原因：

1. 当前仓库还没有稳定的数据库框架选型。
2. 你这部分必须尽量减少依赖，避免控制面反向绑死主链路。
3. 后续如果从 SQLite 切到 PostgreSQL，需要尽量保证 schema 和 SQL 兼容迁移。

## 4. 我给你留下的稳定输入接口

你第一阶段只能消费这些已有产物，不要直接改主链路写库逻辑。

### 主运行入口

1. `scripts/run_sse_bridge_pipeline.sh`
2. `scripts/run_live_sse_bridge_demo.sh`

### 你应该读取的现有输出

1. `out-base/sse_exports/export_audit.jsonl`
2. `out-base/sse_exports/record_recovery_service_audit.jsonl`
3. `out-base/sse_exports/record_recovery_service_health.json`
4. `out-base/sse_exports/record_recovery_service_config.json`
5. `out-base/bridge_job/job_meta.json`
6. `out-base/bridge_job/bridge_audit.jsonl`
7. `out-base/a_psi_run/pjc_audit.jsonl`
8. `out-base/a_psi_run/public_report.json`
9. `out-base/a_psi_run/audit_log.jsonl`
10. `out-base/audit_chain.json`
11. `out-base/audit_chain.seal.json`

### 你应该复用的现有 scope 语义

1. `caller`
2. `tenant_id`
3. `dataset_id`
4. `service_id`
5. `job_id`
6. `correlation_id`

这些字段的语义你要跟当前代码保持一致，不要自己重新解释。

## 5. 推荐表结构方向

第一版建议按下面思路拆表：

### 业务边界表

1. `tenants`
2. `datasets`
3. `services`
4. `callers`

### 运行控制表

1. `jobs`
2. `job_artifacts`
3. `job_stage_status`

### 审计表

1. `audit_events`
2. `audit_chains`
3. `audit_seals`
4. `key_access_events`

### 策略表

1. `policies`
2. `policy_bindings`
3. `caller_permissions`

注意：

1. `jobs` 是控制面主表。
2. `audit_events` 不要试图把所有 JSON 字段拍平成几十列，第一版保留原始 payload 列是可以接受的。
3. `job_artifacts` 里要保存文件路径、文件类型、sha256、stage。

## 6. 调用方式建议

你需要最终提供类似下面的入口。

### 初始化数据库

```bash
python3 scripts/init_metadata_db.py --db-path tmp/platform_metadata.db
```

### 导入一次已有运行

```bash
python3 scripts/import_run_metadata.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --db-path tmp/platform_metadata.db
```

### 查询某个 job

```bash
python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --job-id auto_demo_job
```

### sidecar 生命周期工具

除了 init/import/query 之外，当前 sidecar 也已经补了一层最小 lifecycle 工具：

```bash
python3 scripts/manage_metadata_db.py status \
  --db-path tmp/platform_metadata.db

python3 scripts/manage_metadata_db.py backup \
  --db-path tmp/platform_metadata.db \
  --out-path tmp/platform_metadata.backup.db

python3 scripts/manage_metadata_db.py export-json \
  --db-path tmp/platform_metadata.db \
  --out-path tmp/platform_metadata.export.json
```

这三个入口的边界是：

1. `status`：检查 migration、核心表计数、最近导入时间和 DB 文件摘要
2. `backup`：通过 SQLite backup API 生成一致性副本，不要求主链路停机
3. `export-json`：导出一份便于审计/迁移/对外检查的 sidecar JSON snapshot

它们不让主链路直接写库，也不改变 importer/query 的冻结语义。

当前 sidecar migration 已扩展到阶段/事件耗时：`job_stage_status.duration_ms` 保存阶段聚合时长，`audit_events.duration_ms` 保存原始审计记录里的阶段时长；`query_metadata.py` 当前已经直接输出 `timing_summary`、`stage_duration_summary` 和 `total_stage_duration_ms`，便于只读查询层直接展示 stage timing；新增 `--stage <name>` 后，列表查询还会返回每个 job 的 `matched_stage` 和整个结果集的 `stage_summary`，并支持再叠加 `--stage-status` 过滤和 `--stage-sort duration_desc|duration_asc` 排序；`--group-by stage` 会把当前返回 jobs 的各 stage 汇总成 `grouped_stage_summary`，`--group-by status` 会把这些 jobs 的整体状态汇总成 `grouped_status_summary`，`--output-format csv|tsv` 则可以把这两类聚合直接导出成分隔文本，`--columns` 可裁剪 grouped delimited 字段，`--output-file` 可直接写结果文件。

### 按 caller 查询任务

```bash
python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --stage bridge

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --stage bridge \
  --stage-status allow \
  --stage-sort duration_desc

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --group-by stage

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --group-by status

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --group-by stage \
  --output-format tsv

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --group-by status \
  --output-format csv

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --group-by stage \
  --output-format tsv \
  --columns stage,duration_total

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --group-by status \
  --output-format csv \
  --columns status,duration_total \
  --output-file tmp/platform_metadata_status.csv

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --list-entity tenants \
  --tenant-id demo_tenant

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --list-entity services \
  --service-id bridge-demo-recovery

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --list-entity policies

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --list-entity policy-bindings \
  --caller auto_demo

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --list-entity caller-permissions \
  --caller auto_demo
```

### 本地只读 HTTP API

在保留 CLI 为第一入口的前提下，当前 sidecar 也补了一层非常薄的本地只读 HTTP API：

```bash
export SECCOMP_METADATA_API_TOKEN=local-metadata-token
python3 scripts/serve_metadata_api.py \
  --db-path tmp/platform_metadata.db \
  --bind-host 127.0.0.1 \
  --port 18090 \
  --auth-token-env SECCOMP_METADATA_API_TOKEN
```

当前端点：

1. `GET /healthz`
2. `GET /v1/jobs/<job_id>`
3. `GET /v1/jobs?...`
4. `GET /v1/entities/<entity>?...`

这个 API 直接复用 `query_metadata.py` 的查询函数，读取同一个 SQLite sidecar；它不让主链路写库，也不绕过已有 JSON/JSONL import contract。它的 health/success/error envelope 现在也冻结到了 `schemas/metadata_api_*.schema.json`，并纳入默认 contract smoke 与 schema backcompat guard。

当前仓库还补了一个相邻但不同职责的 sidecar：`scripts/submit_query_workflow.py`。它不读数据库，而是把受限请求 JSON 转成 `scripts/run_sse_bridge_pipeline.sh` 的现有 CLI 调用，供后续 UI / SDK 做 job submit adapter。这个 wrapper 属于查询入口 / workflow 侧车，不属于 SQL metadata sidecar 自身。

当前 `manage_metadata_db.py` 也已经纳入默认 contract smoke：synthetic imported DB 会额外验证 `metadata_db_status/v1`、`metadata_db_backup/v1` 和 `metadata_db_export/v1` 三种输出，不再只验证 init/import/query/read API。

## 7. 你不要碰的边界

第一阶段不允许你主动改这些地方的运行逻辑：

1. `sse/run_client.py`
2. `sse/frontend/client/commands.py`
3. `bridge/src/main.rs`
4. `a-psi/moduleA_psi/scripts/run_pjc.sh`
5. `a-psi/moduleA_psi/scripts/policy_release.py`
6. `scripts/run_sse_bridge_pipeline.sh` 的主控制流
7. `schemas/` 下已在主链路中使用的 contract 字段和 schema 名

如果你认为某个主链路环节应该“直接写数据库”，先出设计文档，不要直接改。

## 8. 你怎么避免和主链路冲突

你的实现必须遵守这几个原则：

1. sidecar first：先读文件产物，再入库。
2. read-only first：先做只读查询，不抢写入控制权。
3. adapter first：如果现有 JSON 字段不够整齐，在导入层做适配，不要反向改源产物格式。
4. backward compatible：后续即使主链路开始写库，你这版导入器也应该还能工作。

## 9. 变更规则

如果你发现现有文件产物不够用：

1. 先写变更提案，文件放到 `docs/change_requests/<topic>.md`
2. 说明缺哪个字段
3. 说明建议在哪个现有产物里增加
4. 说明是否会破坏现有 contract
5. 没批准前不要直接改运行路径

## 10. 验收标准

你这边完成的定义是：

1. 新数据库可以从零初始化。
2. 可以导入一轮现有 pipeline 输出。
3. 能按 `job_id`、`caller`、`tenant_id`、`dataset_id` 查到结果。
4. 不要求第一阶段接管主链路写入。
5. 不破坏现有 CLI、JSON schema、运行目录结构。

## 11. 平台级剩余工作量估算

按 [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md) 的统一口径，这条线从“当前 SQLite sidecar/read-only 基线”推进到“平台基线版”还需要：

1. `8 blocks`
2. 约 `40h`

建议拆分：

1. `2 blocks / 10h`：把 migration、DDL、初始化流程进一步收成 PostgreSQL-ready baseline，同时保留 SQLite sidecar 兼容。
2. `2 blocks / 10h`：把 importer 做到更稳定的 idempotent / reconcile / replay 形态，而不只是“一次性导入一个 run”。
3. `1 block / 5h`：把只读 CLI / HTTP API 的分页、筛选、输出 contract 和回归样例再收一轮。
4. `2 blocks / 10h`：补 registry / policy / permission 的写侧 ownership 或受控管理入口，避免 sidecar 永远只有只读视角。
5. `1 block / 5h`：补 metadata DB 的 health/export/backup 基线和运维文档，形成可长期运行的 sidecar 包。

不含：

1. 让主链路直接写数据库。
2. 完整 HA PostgreSQL、迁移编排和生产级 DBA 运维流程。
