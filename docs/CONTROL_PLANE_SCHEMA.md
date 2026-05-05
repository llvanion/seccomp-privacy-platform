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
5. `scripts/init_metadata_db.py`
6. `scripts/import_run_metadata.py`
7. `scripts/materialize_control_plane_deepening.py`
8. `scripts/query_metadata.py`
9. `scripts/serve_metadata_api.py`
10. `scripts/manage_metadata_db.py`
11. `scripts/check_metadata_schema_portability.py`

先明确一个容易误解的边界：

1. 这里的 SQL sidecar 不是完整电商业务库。
2. 它当前不以保存“买了什么商品”“在哪个平台购买”“从哪个广告或页面点击进来”“物流流转到了哪里”为目标。
3. 它保存的是控制面、运行面和审计面的元数据，用来解释一条隐私查询是怎么被授权、执行、审计和回放的。
4. 截至当前版本，下面这套“每订单业务事实层”仍然没有正式落地到 migration 或 importer 中，只能视为后续应该补齐的业务数仓 / 事实库设计目标。

## 1.1 尚未落地的订单事实层

如果未来要让 SQL 层真的能回答：

1. 用户买了什么商品
2. 在哪个平台成交
3. 从哪个广告、页面或渠道点击进来
4. 支付是否成功、退款是否发生
5. 货从哪里发、物流走到了哪里
6. 客服或售后是否介入

那么至少需要补下面这些业务表。当前仓库里这些表**都还没做成正式 schema**。

### `orders`

一笔订单一行，保存订单头信息。建议至少包括：

1. `order_id`
2. `parent_order_id`
3. `tenant_id`
4. `merchant_id`
5. `store_id`
6. `platform_name`
7. `platform_order_id`
8. `order_status`
9. `order_created_at`
10. `order_paid_at`
11. `order_completed_at`
12. `order_cancelled_at`
13. `currency`
14. `total_amount`
15. `item_amount`
16. `shipping_amount`
17. `discount_amount`
18. `coupon_amount`
19. `refund_amount`
20. `payable_amount`
21. `payment_status`
22. `fulfillment_status`
23. `refund_status`
24. `buyer_id`
25. `buyer_hash_id`
26. `region_code`
27. `source_system`
28. `etl_batch_id`
29. `data_version`

### `order_items`

一笔订单对应的商品行。建议至少包括：

1. `order_item_id`
2. `order_id`
3. `sku_id`
4. `spu_id`
5. `product_id`
6. `product_name_snapshot`
7. `brand_id`
8. `category_lv1`
9. `category_lv2`
10. `category_lv3`
11. `sku_attrs_snapshot`
12. `quantity`
13. `list_price`
14. `sale_price`
15. `discount_amount`
16. `item_total_amount`
17. `cost_amount`
18. `is_gift`
19. `is_preorder`
20. `item_status`

### `order_attribution`

回答“从哪里点击进来”和“在哪个平台转化”的归因表。建议至少包括：

1. `order_id`
2. `session_id`
3. `visit_id`
4. `traffic_source`
5. `traffic_medium`
6. `campaign_id`
7. `campaign_name`
8. `ad_group_id`
9. `creative_id`
10. `channel_platform`
11. `landing_page`
12. `referrer_url`
13. `referrer_domain`
14. `entry_page_type`
15. `click_id`
16. `impression_id`
17. `conversion_path`
18. `is_first_touch`
19. `is_last_touch`
20. `attribution_model`
21. `attributed_at`

### `order_payment`

支付与支付失败信息。建议至少包括：

1. `payment_id`
2. `order_id`
3. `payment_channel`
4. `payment_method`
5. `payment_provider_txn_id`
6. `payment_status`
7. `paid_amount`
8. `paid_at`
9. `payment_fail_reason`
10. `installment_flag`
11. `risk_review_result`

### `order_fulfillment`

履约与物流头信息。建议至少包括：

1. `fulfillment_id`
2. `order_id`
3. `warehouse_id`
4. `fulfillment_mode`
5. `shipment_id`
6. `carrier_name`
7. `tracking_no_hash`
8. `shipped_at`
9. `delivered_at`
10. `delivery_status`
11. `delivery_region_code`
12. `pickup_flag`
13. `sign_status`
14. `return_requested_at`
15. `return_completed_at`

### `shipment_events`

更细的物流轨迹节点。建议至少包括：

1. `shipment_id`
2. `event_time`
3. `event_type`
4. `event_city`
5. `event_station`
6. `event_desc`

### `buyer_identity_snapshot`

订单关联的买家身份快照。建议至少包括：

1. `buyer_id`
2. `buyer_hash_id`
3. `platform_buyer_id`
4. `phone_hash`
5. `email_hash`
6. `device_hash`
7. `name_tokenized`
8. `default_region_code`
9. `registration_channel`
10. `member_level`
11. `is_new_customer`
12. `risk_segment`

### `order_address_snapshot`

收货信息快照。建议至少包括：

1. `order_id`
2. `receiver_name_tokenized`
3. `receiver_phone_hash`
4. `province_code`
5. `city_code`
6. `district_code`
7. `street_tokenized`
8. `postal_code`
9. `geo_hash_approx`

### `sales_after_service`

售后工单。建议至少包括：

1. `service_ticket_id`
2. `order_id`
3. `ticket_type`
4. `ticket_status`
5. `opened_at`
6. `closed_at`
7. `reason_code`
8. `responsible_team`

### `customer_service_interactions`

客服接触记录。建议至少包括：

1. `interaction_id`
2. `order_id`
3. `buyer_id`
4. `channel`
5. `agent_id`
6. `opened_at`
7. `closed_at`
8. `intent_label`
9. `resolution_label`
10. `satisfaction_score`

### `order_risk_events`

风控和拒付信息。建议至少包括：

1. `order_id`
2. `risk_case_id`
3. `risk_score`
4. `risk_tags`
5. `device_hash`
6. `ip_hash`
7. `geo_risk_level`
8. `payment_risk_level`
9. `chargeback_flag`
10. `chargeback_amount`
11. `manual_review_flag`
12. `manual_review_result`

### 对当前隐私平台特别重要的补充字段

为了让这套事实层真正接到当前 `dataset_id / service_id / caller / policy` 模型上，还需要预留：

1. `join_key_type`
2. `join_key_normalized`
3. `join_key_hash`
4. `consent_status`
5. `consent_version`
6. `data_retention_class`
7. `data_sensitivity_level`
8. `allowed_query_profile`
9. `dataset_id`
10. `service_id`

其中高敏字段不应该在普通查询路径里以明文广泛铺开，更适合：

1. 用 hash / token / normalized join key 保存联结标识
2. 用 snapshot 保存订单时点信息
3. 把真实明文限制在更小的恢复边界或专门服务里

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
