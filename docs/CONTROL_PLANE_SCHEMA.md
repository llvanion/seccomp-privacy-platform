# 控制面 Schema 设计说明

## 1. 目标

这份文档定义当前仓库第一阶段 control-plane sidecar 的数据库模型。

目标只有三个：

1. 为现有 `SSE -> record recovery -> bridge -> PJC -> policy release` 运行产物提供可持久化的元数据层。
2. 复用当前已经冻结的 scope 字段，不重新发明第二套命名体系。
3. 保持 sidecar 定位，不让主链路第一阶段强依赖数据库。

当前实现对应：

1. `migrations/metadata/001_init.sql`
2. `migrations/metadata/002_add_stage_duration_columns.sql`
3. `migrations/metadata/004_add_key_registry.sql`
4. `scripts/init_metadata_db.py`
5. `scripts/import_run_metadata.py`
6. `scripts/query_metadata.py`
7. `scripts/serve_metadata_api.py`
8. `scripts/manage_metadata_db.py`
9. `scripts/check_metadata_schema_portability.py`

## 2. 设计约束

### 2.1 冻结字段

控制面 schema 必须直接复用这些字段语义：

1. `job_id`
2. `correlation_id`
3. `caller`
4. `tenant_id`
5. `dataset_id`
6. `service_id`
7. `token_scope`
8. `token_key_version`
9. `record_recovery_boundary`
10. `policy_id`

这些字段可以被补充索引、关系和查询视图，但不能被新的 `account_id`、`workspace_id`、`project_id` 一类命名替代。

### 2.2 sidecar-first

第一阶段数据库只读现有产物，不反向改主链路写库逻辑。当前 importer 只消费：

1. `out-base/sse_exports/export_audit.jsonl`
2. `out-base/sse_exports/record_recovery_service_audit.jsonl`
3. `out-base/sse_exports/record_recovery_service_health.json`
4. `out-base/sse_exports/record_recovery_service_config.json`
5. `out-base/bridge_job/job_meta.json`
6. `out-base/bridge_job/bridge_audit.jsonl`
7. `out-base/a_psi_run/pjc_audit.jsonl`
8. `out-base/a_psi_run/public_report.json`
9. `out-base/a_psi_run/audit_log.jsonl`
10. `out-base/key_access_audit.jsonl`
11. `out-base/audit_chain.json`
12. `out-base/audit_chain.seal.json`

### 2.3 SQLite now, PostgreSQL later

当前脚本使用标准库 `sqlite3`，但 schema 设计尽量保持 PostgreSQL 迁移友好：

1. 主键全部使用稳定业务键或自增 surrogate key。
2. JSON 先作为 `TEXT` 保存原始 payload。
3. 时间统一保存 ISO8601 UTC 字符串。
4. 通过 migration 文件管理 schema 版本，而不是 ORM 自动建表。

当前基线已经额外做了两件收口：

1. `migrations/metadata/001_init.sql` 不再包含 SQLite-only `PRAGMA foreign_keys = ON`，外键约束启用统一留在 Python runtime 的 `connect_db()`。
2. surrogate row id 表从 `INTEGER PRIMARY KEY AUTOINCREMENT` 收紧到 `INTEGER PRIMARY KEY`，避免在第一阶段 DDL 里继续保留不必要的 SQLite-only 关键字。

## 3. 当前表结构

### 3.1 Registry 表

#### `tenants`

用途：

1. 保存租户主键。
2. 记录首次导入时间和最近一次出现的 `job_id`。

关键列：

1. `tenant_id` `PRIMARY KEY`
2. `created_at_utc`
3. `source`
4. `last_seen_job_id`

#### `datasets`

用途：

1. 记录数据集与租户关系。
2. 为 `jobs`、`services`、policy binding 提供 scope 锚点。

关键列：

1. `dataset_id` `PRIMARY KEY`
2. `tenant_id` `REFERENCES tenants`
3. `created_at_utc`
4. `source`
5. `last_seen_job_id`

#### `services`

用途：

1. 当前主要承载 record recovery service 元数据。
2. 记录 service 与 tenant、dataset、transport 的绑定关系。

关键列：

1. `service_id` `PRIMARY KEY`
2. `tenant_id`
3. `dataset_id`
4. `service_type`
5. `transport`
6. `config_path`
7. `created_at_utc`
8. `last_seen_job_id`

#### `callers`

用途：

1. 记录主链路调用主体。
2. 作为 policy binding 和 job 查询的主外键。

关键列：

1. `caller` `PRIMARY KEY`
2. `tenant_id`
3. `created_at_utc`
4. `source`
5. `last_seen_job_id`

### 3.2 Job 表

#### `jobs`

用途：

1. 作为控制面主表。
2. 汇总一次运行的 scope、输出目录、发布结果和导入时间。

关键列：

1. `job_id` `PRIMARY KEY`
2. `correlation_id`
3. `caller`
4. `tenant_id`
5. `dataset_id`
6. `service_id`
7. `out_base`
8. `public_report_path`
9. `audit_chain_path`
10. `status`
11. `release_reason_code`
12. `public_report_released`
13. `intersection_size`
14. `intersection_sum`
15. `created_at_utc`
16. `imported_at_utc`

当前 `status` 主要来自：

1. `public_report.released`
2. `policy_audit` 最后一条 decision
3. 缺省回退值 `imported`

#### `job_artifacts`

用途：

1. 保存 job 相关产物路径、hash、格式和存在性。
2. 作为后续 catalog、lineage、审计留存查询的基础。

关键列：

1. `job_id`
2. `stage`
3. `artifact_type`
4. `path`
5. `sha256`
6. `file_format`
7. `exists_on_disk`
8. `metadata_json`

约束：

1. `UNIQUE(job_id, artifact_type, path)`

#### `job_stage_status`

用途：

1. 为每个阶段保存聚合后的状态视图。
2. 作为 `query_metadata.py --stage ...` 的直接数据源。

关键列：

1. `job_id`
2. `stage`
3. `status`
4. `ts_utc`
5. `details_json`
6. `duration_ms`

约束：

1. `UNIQUE(job_id, stage)`

`duration_ms` 来自 `002_add_stage_duration_columns.sql`，为当前统一观测字段提供只读汇总基础。

### 3.3 Audit 表

#### `audit_events`

用途：

1. 保存 SSE export、record recovery service、bridge、PJC、policy release 等阶段的原始审计事件。
2. 保留结构化常用字段和完整 payload 双轨存储。

关键列：

1. `job_id`
2. `correlation_id`
3. `stage`
4. `event_type`
5. `ts_utc`
6. `caller`
7. `tenant_id`
8. `dataset_id`
9. `service_id`
10. `decision`
11. `reason_code`
12. `artifact_path`
13. `payload_json`
14. `duration_ms`

说明：

1. 第一阶段不追求把所有审计 JSON 完全拍平。
2. 只把高频过滤和汇总字段提到列级。
3. 其余内容保留在 `payload_json`。

#### `audit_chains`

用途：

1. 持久化 `audit_chain.json` 的索引信息和完整 payload。
2. 作为审计查询和归档核对的入口。

关键列：

1. `job_id`
2. `path`
3. `sha256`
4. `generated_at_utc`
5. `counts_json`
6. `payload_json`

#### `audit_seals`

用途：

1. 保存 `audit_chain.seal.json` 的路径、hash 和签名元数据。
2. 为后续 archive / verify 流程提供控制面视图。

关键列：

1. `job_id`
2. `path`
3. `sha256`
4. `algorithm`
5. `signed`
6. `payload_json`

#### `key_access_events`

用途：

1. 保存 key agent 或 external KMS 路径上的 key access audit。
2. 把 key 使用事件纳入 job 级别审计检索面。

关键列：

1. `job_id`
2. `correlation_id`
3. `caller`
4. `tenant_id`
5. `dataset_id`
6. `service_id`
7. `key_id`
8. `key_version`
9. `purpose`
10. `decision`
11. `reason_code`
12. `ts_utc`
13. `source_file`
14. `payload_json`

### 3.4 Policy 表

#### `policies`

用途：

1. 保存导入过的 policy 文件及其 hash。
2. 作为 binding 和 permission 的父表。

关键列：

1. `policy_id` `PRIMARY KEY`
2. `policy_kind`
3. `path`
4. `sha256`
5. `schema_name`
6. `imported_at_utc`
7. `payload_json`

#### `policy_bindings`

用途：

1. 保存 policy 与 caller、tenant、dataset、service 的绑定关系。
2. 让只读查询能直接审视 scope 绑定，而不是重新解析配置文件。

关键列：

1. `policy_id`
2. `binding_kind`
3. `caller`
4. `tenant_id`
5. `dataset_id`
6. `service_id`
7. `source_file`
8. `binding_json`
9. `imported_at_utc`

约束：

1. `UNIQUE(policy_id, binding_kind, caller)`

#### `caller_permissions`

用途：

1. 把当前 `sse_export_policy/v1` 里每个 caller 的权限键展开成只读查询表。
2. 支持快速回答“某 caller 允许做什么”。

关键列：

1. `policy_id`
2. `caller`
3. `permission_key`
4. `permission_value`
5. `source_file`
6. `imported_at_utc`

约束：

1. `UNIQUE(policy_id, caller, permission_key)`

当前这两张表不仅服务于只读查询，也已经成为第一阶段关系同步源：`scripts/export_authz_tuples.py` 可以直接从 policy 文件或 sidecar DB 中的 `policy_bindings` / `caller_permissions` 重建 `authz_tuple_export/v1`，把当前 caller/tenant/dataset/service scope、平台角色和 coarse capability 映射成可供 OpenFGA 一类系统消费的 tuple baseline，而不要求主链路在线依赖外部授权服务。与此同时，`scripts/manage_metadata_db.py apply-registry` 也把它们作为受控写侧的展开目标：manifest 只显式维护 registry entities 和 policy 文件路径，不直接要求调用方手写 permission rows。

### 3.5 Key Registry 表

#### `key_refs`

用途：

1. 保存不含 secret material 的 key registry 元数据。
2. 给 keyring / external KMS / future Vault adapter 提供统一 control-plane 落点。

关键列：

1. `key_name` `PRIMARY KEY`
2. `purpose`
3. `service_id`
4. `backend_kind`
5. `backend_ref`
6. `active_version`
7. `allowed_callers_json`
8. `source`
9. `created_at_utc`
10. `updated_at_utc`

#### `key_versions`

用途：

1. 保存 key 的版本级状态视图，而不是 secret 本体。
2. 让 sidecar 可以回答“某个 key 当前有哪些 version、哪一个 active、状态是什么”。

关键列：

1. `key_name`
2. `version`
3. `enabled`
4. `status`
5. `secret_ref_kind`
6. `secret_ref_name`
7. `backend_key_version`
8. `created_at_utc`
9. `source`
10. `metadata_json`

约束：

1. `UNIQUE(key_name, version)`

当前这组表由 `migrations/metadata/004_add_key_registry.sql` 创建，第一阶段通过 `scripts/manage_metadata_db.py apply-registry` 从 `metadata_registry_manifest/v1` 的 `key_refs` 段受控写入；`scripts/query_metadata.py --list-entity key-refs|key-versions` 和 `scripts/serve_metadata_api.py /v1/entities/key-refs|key-versions` 则提供只读查询面。这个 baseline 只做 key metadata / version registry，不让 metadata sidecar 变成 secret source。

## 4. 导入映射规则

当前 importer 的核心逻辑位于 `scripts/import_run_metadata.py`。

当前 importer 输出 contract 已冻结到 `metadata_import_report/v1`：

1. apply 模式会对每个 run 标明 `action=insert|replace`
2. dry-run 模式只做 bundle 读取、scope 推断和 reconcile，不写 DB
3. 报告里会带导入前 `existing_job` 快照和各 job 级子表 `row_counts`
4. apply 完成后还会写回 `job_state_after`
5. 可通过多次 `--out-base` 或 `--out-base-file` 做批量 replay/import

### 4.1 `job_id` 与 `correlation_id`

导入优先级：

1. `audit_chain.json`
2. `public_report.json`
3. `bridge_job/job_meta.json`
4. `a_psi_run/audit_log.jsonl`
5. `sse_exports/export_audit.jsonl`

若 `correlation_id` 缺失，则回退为 `job_id`。

### 4.2 scope 推断

当前 scope 由以下产物综合推断：

1. `record_recovery_service_config.json`
2. `record_recovery_service_health.json`
3. `record_recovery_service_audit.jsonl`
4. `export_audit.jsonl`
5. `public_report.json`
6. `policy_audit`

优先保留当前仓库已经统一的字段：

1. `caller`
2. `tenant_id`
3. `dataset_id`
4. `service_id`

### 4.3 阶段状态与时长

当前阶段聚合以导入的 audit records 为准，目标是给查询层提供：

1. `timing_summary`
2. `stage_duration_summary`
3. `total_stage_duration_ms`
4. `matched_stage`
5. `stage_summary`
6. `grouped_stage_summary`
7. `grouped_status_summary`

这部分已经由 `query_metadata.py` 暴露，不要求主链路改成直接写 SQL。

### 4.4 replay / reconcile 规则

当前 importer 的运行语义是：

1. 先根据 run bundle 推断 `job_id`、`correlation_id` 和 scope。
2. 如果目标 `job_id` 已存在，则当前 run 被判定为 `replace`；否则为 `insert`。
3. `replace` 只清理该 job 的从属表：`job_artifacts`、`job_stage_status`、`audit_events`、`audit_chains`、`audit_seals`、`key_access_events`。
4. registry / policy 相关表继续走 upsert，不把 sidecar 退回成“每次 replay 都新增脏行”。
5. policy 导入已切到 shared replace/repair helper：同一路径 policy 如果内容变化，会先删除旧 `policy_id` parent row，再写入新 hash 对应的 row，并重建 `policy_bindings` / `caller_permissions`，避免 `policies.path` 唯一键冲突和陈旧 child rows 残留。
5. 同一批次里如果多个 `out_base` 推断出相同 `job_id`，当前会直接拒绝，避免批量 replay 时发生静默覆盖。

这意味着第一阶段 sidecar 已经具备：

1. 单 run dry-run reconcile
2. 单 run replace replay
3. 多 run batch replay

但它仍然没有完整的跨批次修复/差异合并策略，那部分仍属于后续 importer 治理工作。

### 4.5 DDL portability gate

当前 sidecar 还补了一条专门针对 migration/DDL 的快速检查：

```bash
python3 scripts/check_metadata_schema_portability.py \
  --output tmp/platform_metadata_schema_portability.json
```

它当前固定检查：

1. migration SQL 中是否仍然出现 `PRAGMA`、`AUTOINCREMENT` 这类 SQLite-only 关键字
2. 所有表是否都有主键
3. 所有 `*_utc` 列是否统一为 `TEXT`
4. 所有 `*_json` 列是否统一为 `TEXT`
5. 当前声明的关键索引是否都存在
6. 外键目标表是否全部存在

输出 contract 已冻结到 `metadata_schema_portability/v1`，并纳入默认 `check_json_contracts.sh`。

### 4.6 managed registry / policy apply

当前 sidecar 已经不再只有 post-run importer 一条写入路：

```bash
python3 scripts/manage_metadata_db.py apply-registry \
  --db-path tmp/platform_metadata.db \
  --manifest config/metadata_registry.example.json
```

这条入口当前语义是：

1. 输入使用 `metadata_registry_manifest/v1`
2. 显式 upsert `tenants`、`datasets`、`services`、`callers`
3. policy 文件当前按 `path` + `sha256(policy)` 推断 identity，并写入 `policies`
4. `sse_export_policy/v1` 里的 caller scope 会展开成 `policy_bindings` / `caller_permissions`
5. dry-run 只做引用校验和 reconcile，输出 `metadata_registry_apply_report/v1`
6. 重复 apply 同一 manifest 时，如果 registry 字段、policy path/hash 和 child row count 一致，会收敛成 `noop`
7. `check_json_contracts.sh` 当前固定验证空 DB dry-run、首次 apply、重复 reconcile noop，以及 sidecar DB 到 `authz_tuple_export/v1` 的贯通

## 5. 查询面

### 5.1 CLI

基础入口：

```bash
python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --job-id auto_demo_job
```

列表和聚合入口：

```bash
python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --caller auto_demo \
  --stage bridge \
  --stage-status allow \
  --stage-sort duration_desc \
  --group-by stage
```

实体只读入口：

```bash
python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --list-entity caller-permissions \
  --caller auto_demo

python3 scripts/export_authz_tuples.py \
  --db-path tmp/platform_metadata.db \
  --output tmp/platform_authz_tuples.json
```

### 5.2 本地只读 HTTP API

当前 HTTP wrapper 位于 `scripts/serve_metadata_api.py`，提供：

1. `GET /healthz`
2. `GET /v1/jobs/<job_id>`
3. `GET /v1/jobs?...`
4. `GET /v1/entities/<entity>?...`

它只读 sidecar DB，不反查 SSE、record recovery、bridge、PJC 原始数据。

## 6. 索引与查询优先级

当前 migration 已覆盖这些高频索引：

1. `idx_jobs_caller`
2. `idx_jobs_tenant_dataset`
3. `idx_jobs_service_id`
4. `idx_job_artifacts_job_id`
5. `idx_job_stage_status_job_id`
6. `idx_audit_events_job_stage`
7. `idx_key_access_events_job_id`

第一阶段优先优化的读路径是：

1. 按 `job_id` 查完整运行
2. 按 `caller` / `tenant_id` / `dataset_id` / `service_id` 查 job 列表
3. 按 stage 和 status 查看耗时分布
4. 按 entity 查看 registry 和 policy 绑定

## 7. PostgreSQL 迁移建议

如果后续切 PostgreSQL，建议保持下面不变：

1. 表名
2. 主键字段名
3. scope 字段名
4. `payload_json` 原样保留的策略
5. migration-first 工作流

建议后续再补：

1. JSONB 索引
2. 更严格的外键与检查约束
3. materialized views 或读模型
4. 分页游标和排序键
5. 审计与 registry 的行级保留策略

## 8. 非目标

这份 schema 当前不负责：

1. 直接驱动主链路执行
2. 替代 `audit_chain.json` 成为新的审计真相源
3. 定义新的 release policy 语义
4. 保存高敏明文字段
5. 让 SQL 查询绕过 SSE export policy 或 record recovery service

## 9. 下一阶段建议

1. 给 `jobs` 增加更明确的 workflow 状态迁移表，而不是只靠最终状态快照。
2. 为 `policies` 与 `services` 补 version 字段，支持后续变更治理。
3. 为 key 生命周期补 registry 视图，而不只导入 access audit。
4. 在 PostgreSQL 版本中把 `payload_json` 升级为 `JSONB`，并针对常用字段建表达式索引。
5. 继续保持 importer 和 read adapter 模式，不把数据库写路径塞回主链路。
