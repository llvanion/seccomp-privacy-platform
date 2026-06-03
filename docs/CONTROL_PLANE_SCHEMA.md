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
4. `migrations/metadata/009_add_control_plane_deepening.sql`
5. `migrations/metadata/010_add_ecommerce_fact_tables.sql`
6. `migrations/metadata/011_add_business_identities.sql`
7. `migrations/metadata/012_add_workflow_submissions.sql`
8. `scripts/init_metadata_db.py`
9. `scripts/import_run_metadata.py`
10. `scripts/materialize_control_plane_deepening.py`
11. `scripts/query_metadata.py`
12. `scripts/serve_metadata_api.py`
13. `scripts/manage_metadata_db.py`
14. `scripts/check_metadata_schema_portability.py`

先明确一个容易误解的边界：

1. 这里的 SQL sidecar 不是完整电商业务库。
2. 它的主职责仍然是控制面、运行面和审计面的元数据，不是完整 customer 360 或企业级电商数仓。
3. 它保存的是控制面、运行面和审计面的元数据，用来解释一条隐私查询是怎么被授权、执行、审计和回放的。
4. Track-E1 已经补入一套窄口径电商事实层基线，用于支撑隐私查询 demo 的业务叙事和后续导入目标；这仍然不是完整电商数仓。

## 1.1 已落地的订单事实层基线

Track-E1 已通过 [`migrations/metadata/010_add_ecommerce_fact_tables.sql`](/home/llvanion/Desktop/seccomp-privacy-platform/migrations/metadata/010_add_ecommerce_fact_tables.sql) 落地 6 张订单中心事实表，并在 [`docs/ECOMMERCE_FACT_LAYER_PLAN.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_FACT_LAYER_PLAN.md) 中冻结设计口径。

这层的目标是让隐私计算链路可以讲清楚：

1. 用户买了什么商品
2. 在哪个平台成交
3. 从哪个广告、页面或渠道点击进来
4. 支付是否成功、退款是否发生
5. 货从哪里发、物流走到了哪里
6. 客服或售后是否介入

但它仍然只是一套可供隐私 pipeline 对接的事实层基线，不是完整电商数仓。当前正式落地的表是：

1. `orders`
2. `order_items`
3. `order_attribution`
4. `order_payment`
5. `order_fulfillment`
6. `customer_service_interactions`

这些表共享 `tenant_id` / `dataset_id` / `service_id` scope，和 `sse_export_policy/v1` 对齐。`orders.buyer_email` 是当前 bridge join key，`orders.total_amount_cents` 是 `--client-value-mode raw-int` 的金额字段。除 join key 和必要 value 外，其他事实字段不穿过 bridge / PJC 边界。

当前没有落地、也不应该在现阶段混入这份 control-plane schema 的内容包括：

1. 完整买家个人画像和地址明文。
2. 详细物流轨迹事件表。
3. 商品主数据、库存、商家主数据。
4. 实时事件流、Kafka/Debezium 这类生产数据管道。
5. 客服会话全文或任何 PII 明文字段。

下面保留字段说明，作为已落地 6 表的 schema 摘要，而不是“尚未实现清单”。

### 已落地表摘要

| 表 | 当前用途 | 关键字段 |
| --- | --- | --- |
| `orders` | 订单头表；当前隐私 join/value 的主要来源 | `order_id`, `tenant_id`, `dataset_id`, `service_id`, `buyer_email`, `campaign_id`, `total_amount_cents`, `placed_at_utc`, `status` |
| `order_items` | 订单商品行，支撑后续 SKU/类目方向的隐私聚合 | `order_id`, `tenant_id`, `dataset_id`, `sku_id`, `category_id`, `quantity`, `line_total_cents` |
| `order_attribution` | 营销归因表，支撑 campaign/channel 查询叙事 | `order_id`, `tenant_id`, `dataset_id`, `attribution_type`, `channel`, `campaign_id`, `creative_id`, `attribution_weight` |
| `order_payment` | 支付与争议基础字段，支撑风控/支付场景 | `order_id`, `tenant_id`, `dataset_id`, `payment_method`, `provider_id`, `paid_amount_cents`, `risk_score`, `is_disputed` |
| `order_fulfillment` | 履约与物流头字段，不保存快递员或地址 PII | `order_id`, `tenant_id`, `dataset_id`, `carrier_id`, `warehouse_id`, `status`, `delivery_latency_minutes` |
| `customer_service_interactions` | 客服接触元数据，不保存会话全文 | `order_id`, `tenant_id`, `dataset_id`, `interaction_type`, `channel`, `agent_id`, `resolution_status` |

### 仍属后续范围的事实层能力

以下内容曾在早期设计里作为建议字段出现，但当前不属于已冻结 migration：

1. `shipment_events` 级别的逐节点物流轨迹。
2. `buyer_identity_snapshot` / `order_address_snapshot` 级别的买家画像或地址快照。
3. `sales_after_service` / `order_risk_events` 等更宽业务域。
4. `join_key_hash`、`consent_status`、`data_retention_class` 等更完整的数据治理字段。

这些能力要作为后续 tranche 单独设计。引入时必须继续遵守两条约束：不把 PII 明文扩散到普通 sidecar 查询面，不改变 `SSE -> record recovery -> bridge -> PJC -> policy release` 主链路 contract。

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

这直接决定了当前 sidecar 更像“run metadata importer”，而不是“业务事实明细 ETL”：

1. 它能导入 job、artifact、audit、policy、permission、key access 信息。
2. 它不能凭空补出完整订单事实、商品维度、流量来源、渠道平台、物流轨迹、客服会话等业务字段。
3. 如果未来要让 SQL 层承载这些信息，需要新增明确的数据 contract、采集入口和脱敏边界，而不是继续把它们塞进当前 importer。

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

这里的 `dataset` 当前是控制面 scope 概念，不等价于“完整业务主题宽表”。
例如 `orders_analytics` 可以表示订单分析数据域，但这不意味着 sidecar 里已经直接存放订单商品明细、渠道来源和全量用户行为事实。

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

它记录的是“跑过什么查询 / 结果如何”，不是“订单本体长什么样”。

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

`metadata_json` 可以挂少量与 artifact 有关的辅助元数据，但当前设计并不把它当作业务明细字段的大仓库。

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

这张表保存的是展开后的权限键值，不是 CRM/OMS/WMS 里的人员主数据表。

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

当前 importer 不会从运行产物中自动推断下列更细的业务字段，除非未来先为这些字段单独冻结 contract：

1. 商品 SKU / SPU / 类目
2. 购买平台 / 渠道平台
3. 广告点击入口 / 页面来源 / campaign source
4. 城市 / 门店 / 履约站点
5. 物流轨迹节点
6. 客服会话或售后工单维度

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

但它仍然是“围绕隐私查询运行产物”的 sidecar，而不是“完整电商业务事实仓”的替代品。

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

### 4.7 C1-C5 deepening read models

`2026-05-05` 增加的 `009_add_control_plane_deepening.sql` 不改变主链路写入方式，而是在 sidecar 中增加五类派生读模型：

1. `job_state_transitions`
   - 由 `jobs` 与 `job_stage_status` 派生
   - 保存 `from_state -> to_state`、stage、event_type、时间、来源表与 details
   - 用于承接 query workflow / operator shell 的长期状态读取
2. `policy_versions`
   - 由 `policies`、`policy_bindings`、`caller_permissions` 派生
   - 保存 policy kind/path/sha/schema/imported time/current marker
   - metadata 中保留 binding_count / permission_count
3. `service_versions`
   - 由 `services` 派生
   - 用 service scope/config snapshot 的稳定 hash 作为 version
   - 用于记录服务配置快照，而不是让主链路依赖 DB 配置
4. `catalog_lineage_read_model`
   - 由 `catalog_lineage/v1` 与 metadata DB 的 job scope 派生
   - 保存 dataset/service/artifact/edge 四类 lineage row
   - 默认 `path_redacted=1`，除非输入 lineage 显式包含 path
5. `retention_reconcile_plan`
   - 由 jobs、policies、key_refs 等现有 control-plane 元数据派生
   - 输出 retain/review 建议、retention_class、reason_code 和 details
   - 当前不执行删除；破坏性 repair 仍必须由显式 operator 工具处理

Materialize 入口：

```bash
python3 scripts/materialize_control_plane_deepening.py \
  --db-path tmp/platform_metadata.db \
  --catalog-lineage tmp/catalog_lineage.json \
  --output tmp/control_plane_deepening.json \
  --assert-ok
```

输出 contract 为 `control_plane_deepening_report/v1`，并已纳入 `check_json_contracts.sh` 与 schema backcompat baseline。

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

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --list-entity catalog-lineage-read-model

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
5. `POST /v1/business-access/check`
6. `POST /v1/business-data/read-preview`

它只读 sidecar DB，不反查 SSE、record recovery、bridge、PJC 原始数据。`/v1/business-data/read-preview` 是当前唯一受业务字段级策略保护的事实表读取入口：请求必须带 identity-token 可解析身份，业务角色必须匹配该身份或平台管理员/审计员权限，`business_access_policy/v1` 在 SELECT 前完成 allow/mask/deny 判定，deny 字段返回 HTTP 403，mask 字段不选择原始列值，只返回 mask marker。授权 `scope` 会保留在响应中，但只有安全 allowlist 中的查询键进入 SQL `WHERE`；敏感字段不能作为 filter 使用，以减少存在性查询泄漏。该结果结构由 `business_data_read_preview/v1` 固定，API smoke 报告由 `business_access_api_smoke/v1` 固定。

## 6. 索引与查询优先级

当前 migration 已覆盖这些高频索引：

1. `idx_jobs_caller`
2. `idx_jobs_tenant_dataset`
3. `idx_jobs_service_id`
4. `idx_job_artifacts_job_id`
5. `idx_job_stage_status_job_id`
6. `idx_audit_events_job_stage`
7. `idx_key_access_events_job_id`
8. `idx_job_state_transitions_job_id`
9. `idx_policy_versions_policy_id`
10. `idx_service_versions_service_id`
11. `idx_catalog_lineage_job_id`
12. `idx_retention_reconcile_job`

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

当前 Postgres target DDL 已经覆盖 `009` 深化表，并继续做基础类型升级：

1. `*_json` 列升级为 `JSONB`
2. `*_utc` 列升级为 `TIMESTAMPTZ`
3. SQLite integer boolean 升级为 `BOOLEAN`
4. surrogate integer PK 升级为 `SERIAL`

后续生产化再补：

1. JSONB 表达式索引
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

`C1-C5` 已在 `2026-05-05` 完成第一版 sidecar-first 落点。后续如果继续深化，应聚焦下面这些生产化问题，而不是把主链路改成必须写数据库：

1. 真正 PostgreSQL 部署、迁移编排、备份恢复演练和 DBA runbook。
2. JSONB 表达式索引、cursor pagination 和查询计划验证。
3. retention/reconcile plan 的 operator approval 流程。
4. 多批次 lineage materialized view 的增量刷新策略。
5. 继续保持 importer 和 read adapter 模式，不把数据库写路径塞回主链路。

如果要把这些建议纳入统一排期，建议直接对齐 [POST_BASELINE_ROADMAP.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/POST_BASELINE_ROADMAP.md) 的 `Tranche C`：

1. `C1`：workflow transition tables / read model（已落地 `job_state_transitions`）
2. `C2`：policy / service versioning（已落地 `policy_versions` / `service_versions`）
3. `C3`：PostgreSQL `JSONB` + 索引（已同步 Postgres target DDL 与 portability gate）
4. `C4`：registry-enriched catalog / lineage read model（已落地 `catalog_lineage_read_model`）
5. `C5`：retention / reconcile / repair 收口（已落地 `retention_reconcile_plan`）

这份 schema 文档后续主要负责：

1. 给上述 `C1-C5` 提供表结构和字段语义落点
2. 保证 PostgreSQL 深化时不反向破坏 sidecar-first 边界
