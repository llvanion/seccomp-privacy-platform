# 平台压缩总览

这份文档用于替代“先把 `docs/` 全读一遍”的做法。

目标：

1. 用一份 markdown 说明项目是什么
2. 说明当前代码已经推进到哪里
3. 说明当前能做什么、不能做什么
4. 给出最少量的后续深读入口

如果只想快速建立上下文，优先读这份。

## 1. 项目是什么

这个仓库当前是一个面向电商隐私数据场景的比赛版平台基线。

主链路：

```text
SSE candidate export
-> controlled record recovery
-> Rust bridge tokenization
-> A-PSI / PJC
-> policy release
```

模块分工：

1. `sse/`：加密存储、SSE candidate export、record recovery
2. `bridge/`：join key normalizer、HMAC token、bridge job
3. `a-psi/`：PJC、result governance、public report
4. `scripts/`：pipeline orchestration、sidecar API、benchmark、验证工具
5. `migrations/metadata/` + SQLite sidecar：控制面 metadata / audit / policy 查询与管理

## 2. 当前状态

当前代码已经超过“原型 demo”，但还没到“真实生产电商平台”。

截至 `2026-05-03`，五条任务线都已经完成“平台基线版”定义范围内的实现。继续推进时，请不要再把工作描述成“补当前基线剩余 block”，而应改读 [POST_BASELINE_ROADMAP.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/POST_BASELINE_ROADMAP.md) 里的下一阶段 tranche 规划。

已经完成：

1. owner 主线完成：主链路 contract、recovery replay、normalizer 治理、FIFO handoff、exposure assessment 已收口
2. 审计/运维基线完成：malformed-input gate、benchmark gate、operator readiness、runbook 已收口
3. SQL sidecar 已完成多项基线：
   - metadata import/replay/dry-run
   - query CLI / HTTP 分页与聚合
   - PostgreSQL-ready portability gate
   - registry/policy/permission managed write baseline
   - key registry / key version managed write + read baseline

还没完成（2026-05-08 之后更新）：

1. 真实 Keycloak / OpenFGA / Vault / cloud KMS 的长期运行环境和凭证托管（repo 内 adapter、compose、dry-run/live 工具已完成；默认不启动外部服务）
2. authority source 的生产凭证轮换和 SRE 托管流程
3. durable workflow / 真实 SPA 壳：Track-E3 已落 `console_manifest/v1` 契约 + 静态占位页 + 渲染/校验脚本，并在 [OPERATOR_CONSOLE_PRODUCT_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPERATOR_CONSOLE_PRODUCT_PLAN.md) §9–§12 补完了与生产就绪 I3 的边界划分（Track-E3 拥 surface，I3 拥 lifecycle）、submit/approve/reject 状态机、同身份自审禁令，以及 Phase-2 admin section（`admin_registry` / `admin_keys` / `admin_authority` / `admin_workflow` / `admin_retention` / `admin_external_anchor`）；完整 SPA 实现与 I3 endpoint 上线仍属 operator 环境工作
4. SQL sidecar 更深的 Postgres 迁移与 importer repair
5. caller 画像仍然主要停留在"平台操作者 / 查询发起者"层级，但 Track-E2 已经把买家、商家店员、客服、快递员、地推这五类业务身份作为 `business_identities` 注解层落基线；详见 [ECOMMERCE_ACCESS_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_ACCESS_MODEL.md) §业务身份扩展
6. ~~SQL sidecar 当前保存的是 control-plane metadata / audit / policy / permission，而不是完整电商业务事实表~~ → Track-E1 已落 `orders / order_items / order_attribution / order_payment / order_fulfillment / customer_service_interactions` 六张事实表（`migrations/metadata/010_*.sql`，Postgres DDL 同步），当前限制是仍需要 operator 提供真实/脱敏数据导入；详见 [ECOMMERCE_FACT_LAYER_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_FACT_LAYER_PLAN.md)
7. ~~面向真实电商订单分析的一整套 SQL 事实层还没落地~~ → Track-E1 fact-layer 基线已完成（同上）

剩余估算以 [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md) 为准。

平台基线之后的继续推进顺序以 [POST_BASELINE_ROADMAP.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/POST_BASELINE_ROADMAP.md) 为准。

## 3. 当前能做什么

### 3.1 主链路

1. 跑完整 `SSE -> recovery -> bridge -> PJC -> release`
2. 支持 file handoff、retained file handoff、FIFO handoff
3. 支持 standalone recovery service，Unix socket / HTTP 两种 transport
4. 支持 request timestamp anti-replay、HMAC request signing
5. 支持 replay 验证、mainline contract check、audit chain / seal / archive

### 3.2 权限与授权

1. 用 `sse_export_policy/v1` 做 caller 级别权限控制
2. 约束 `tenant_id / dataset_id / service_id`
3. 约束 `can_use_record_recovery_service / can_run_bridge / can_run_pjc / can_release`
4. 约束 join key、value field、filter field、required filter
5. 把 file-backed policy 展开成 `policy_bindings / caller_permissions`
6. 导出 `authz_tuple_export/v1`，给 OpenFGA 风格系统做关系同步基线
7. 用 `caller_identities` + `api_identity_resolution/v1` 做 token -> identity -> caller 映射
8. `map_oidc_claims.py` 已支持 RS256/JWKS token 验证；默认 contract smoke 用 synthetic RS256 JWT + `file://` JWKS 覆盖该 adapter，不强制依赖真实 Keycloak
9. metadata/query/audit/platform-health sidecar API 已统一走 identity resolver，并收紧 query execute / audit include_paths / platform health role gate
10. `request_oidc_client_credentials.py` 可对真实 Keycloak/OIDC issuer 执行 client-credentials token 请求；默认 smoke 只跑 dry-run contract
11. `keyring/v1` 现支持 `secret_ref.kind=env|vault_kv|vault_http|aws_kms`，key agent / external KMS / pipeline auto-start 已贯通 Vault KV 兼容 backend
12. OpenFGA tuple sync / check adapter 已支持 live HTTP backend；默认仍走 SQLite fallback，`OPENFGA_ENDPOINT` + `OPENFGA_STORE_ID` 才启用 live smoke
13. `setup_openfga_model.py`、`issue_mtls_certs.py`、`cloud_kms_adapter.py` 分别覆盖 OpenFGA model setup、Vault PKI/mTLS 发证、AWS KMS adapter baseline

14. HTTP recovery service 支持 `--rate-limit-per-caller`（token bucket 速率限制）；超限请求返回 HTTP 429 并写入结构化日志
15. HTTP recovery service 暴露 `GET /metrics`（Prometheus 文本格式 counter + histogram），无需外部 client 库
16. Operator dashboard 支持 `--max-concurrent-jobs-per-tenant`，可按 `tenant_id` 限制同一 history root 下的 running job 数；超限 start/relaunch 返回 HTTP 429 `tenant_job_quota_exceeded`
17. `scripts/metadata_db.py` 已包含 psycopg2 driver layer：`connect_db(dsn=…)` 支持 PostgreSQL；`adapt_sql` / `placeholder` / `is_postgres` / `row_to_dict` 适配参数占位符和行读取；`init/import/query/manage/metadata API` 已支持 `--db-dsn`，query/audit/platform-health API 的 identity resolution 已支持 `--metadata-db-dsn`，`benchmark_read_adapters.py --db-dsn` 可做 SQLite/PostgreSQL 读侧对比；`POSTGRES_DSN` live gate 现在还会导入真实 run bundle 并查询同一 job，真实 PostgreSQL 执行仍归 F1-b operator 环境验证
18. `archive_audit_bundle.py --tenant-id <tenant>` 支持按租户分区本地审计归档：参数必须匹配 `audit_chain.json` 内的 tenant scope，索引与 anchor 写入 `<archive-dir>/<tenant-id>/`
19. Unix-socket record-recovery service 在配置省略 `socket_path` 时可从 `tenant_id` / `service_id` / `dataset_id` 派生 `/tmp/seccomp_rr_<tenant>_<hash>.sock`，manager、standalone launcher 和 contract smoke 使用同一规则，避免多租户服务误落到共享 socket 默认值
20. `scripts/render_k8s_network_policies.py` 可按租户生成 Kubernetes `NetworkPolicy`：只允许同租户 `sse-bridge-pipeline` pod 访问同租户 `recovery-service` pod；示例在 `config/k8s/netpol-recovery-service-demo-tenant.yaml`，报告 contract 为 `k8s_network_policy_report/v1`
21. `scripts/render_postgres_ha_topology.py` 可生成 PostgreSQL 16 primary/replica HA 目录：`config/postgres-ha/docker-compose.primary-replica.yml` 是 checked-in 示例，包含 `pg_basebackup -Xs -R` replica bootstrap、health-gated `depends_on`、复制 role init、`.env.example` 和 `verify_replication.sql`；报告 contract 为 `postgres_ha_topology_report/v1`
22. `scripts/render_patroni_failover_topology.py` 可生成 F2-b Patroni automated failover 拓扑：`config/patroni-ha/` 是 checked-in 示例，包含 etcd DCS、`patroni-primary.yml`、`patroni-replica.yml`、REST API 端口、`use_pg_rewind`、replication slots、SCRAM `pg_hba` 和 `patronictl list/switchover/failover` 命令；报告 contract 为 `patroni_failover_topology_report/v1`
23. `scripts/render_pgbouncer_topology.py` 可生成 F3 pgBouncer connection-pooling 拓扑：`config/pgbouncer/` 是 checked-in 示例，包含 `pgbouncer.ini`、`userlist.txt.example`、`docker-compose.pgbouncer.yml` 和 `pgbouncer_commands.sh`；报告 contract 为 `pgbouncer_topology_report/v1`，默认 contract smoke 断言 `:6432` transaction pooling、pool sizing、`SHOW POOLS` / `SHOW STATS`、读 benchmark pooled DSN 和长写事务 direct-primary DSN

当前这一层更像”谁能发起或审核隐私查询”的平台权限模型，而不是完整电商业务人员身份模型。

### 3.3 SQL sidecar

1. 初始化 metadata DB
2. 导入 run artifact 到 sidecar
3. dry-run / replay / reconcile
4. CLI / HTTP 查询 jobs、audit、policy、permission
5. `apply-registry` 受控写 tenant / dataset / service / caller / policy
6. `apply-registry` 受控写 key registry / key version metadata
7. backup / restore / export-json / status
8. migration portability check

当前 SQL sidecar 主要回答：

1. 哪个 caller 在什么 scope 下跑过什么 job
2. 哪个阶段 allow / deny、耗时多少、产物 hash 是什么
3. 当前 policy、permission、key registry 是什么状态

它当前不直接充当电商事实库，不默认保存完整订单明细、商品维度、投放来源、点击链路、物流节点或客服工单明细。

### 3.4 验证与 benchmark

1. `check_json_contracts.sh`
2. `check_ci_smoke.sh`
3. query / read adapter / recovery / bridge / pipeline / PJC / audit bundle / platform health / derived views benchmark
4. record-recovery benchmark 支持 `--candidate-count`、`--mode http_recover_concurrent --concurrency <n>`、显式 `--mode http_recover_mtls` 和 `--mode g2b_acceptance`，可对候选规模、并发批次、mTLS recover 与 `max_rows_per_request` 安全阀测量；本地已跑通 G2-a 的 1k / 10k Unix-socket recover，以及 G2-b 的 1k candidates / 10 HTTP 并发 acceptance（15.818 req/s）
5. `scripts/benchmark_sse_export.py` 输出 `sse_export_benchmark/v1`，可对 synthetic e-commerce encrypted record store 的 SSE export worker path 做规模测试；本地已跑通 100k / 1M candidates，`benchmark_smoke.py --target sse-export-scale --scale <n>` 可作为入口
6. `scripts/benchmark_bridge.py` 输出 `bridge_benchmark/v1`，可对 Rust bridge `prepare-job` 的 JSONL 输入规模测试；本地 release binary 已跑通 100k/100k（0.366s）和 1M/1M（4.437s），`benchmark_smoke.py --target bridge-scale --scale <n>` 可作为入口；CPU top-hotspot 仍需 operator 环境跑 `cargo flamegraph` / `perf`
7. `scripts/benchmark_dashboard_jobs.py` 输出 `dashboard_jobs_benchmark/v1`，可对 operator dashboard 并发 job start 和 `/v1/dashboard` 读取做压测；本地 5 并发 run 已跑通，dashboard p95 4.781ms，tracemalloc retained memory 47.681 KB/job
8. `scripts/verify_audit_tamper_resistance.py` 输出 `audit_tamper_resistance/v1`，会在 `audit_chain.json` 与 `audit_chain.seal.json` 的 6 个候选位置做 single-byte bit flip，断言 `verify_audit_bundle` 都能检测出篡改并在每次变异后恢复原始字节；默认 contract smoke 把它接到主线 audit chain 上跑通；操作员复核单个 run 也可以直接调
9. `scripts/check_http_malformed_input_gate.py` 输出 `http_malformed_input_gate/v1`，默认在 loopback 启 in-process record-recovery HTTP service 并跑 10 个攻击 scenario（缺 X-Request-Signature、过期/未来 timestamp、SQL-injection-pattern caller/tenant_id/job_id、坏 JSON、非 object payload、缺 required field、错 HTTP method、未知 path、超大 body），断言每个都被服务拒绝；本地 10/10 detected
10. `scripts/benchmark_mtls_overhead.py` 输出 `recovery_mtls_benchmark/v1`，在 loopback 起 plaintext + mTLS 两套 in-process HTTP 服务（使用 mock 证书），用 `http.client` 直连分别在 fresh-connection / persistent-connection 两种连接模式下打 `/health`，记录 p50/p95、mTLS overhead p95 与 keep-alive savings；本地 5 iter × 4 transport-mode = 20 个请求全成功，mTLS fresh-connection overhead p95 ≈ 1.6ms（远低于 50ms 警戒值）
11. `config/observability/` 提供完整的可观测栈静态产物：`docker-compose.observability.yml`（Tempo + Prometheus + Grafana 自动 provisioning、scrape 复用 J3-a `/metrics`）、`tempo.yaml`、`prometheus.yml`、`grafana-datasources.yaml`、以及两份 dashboard JSON（`pipeline-overview.json`、`recovery-service.json`）；`scripts/render_observability_topology.py` 输出 `observability_topology_report/v1` 校验各部件齐备；`scripts/export_otel_events.py --otlp-endpoint` 提供 OTLP/HTTP-JSON 推送适配
12. `docs/COMPLIANCE_MAPPING.md` 现已覆盖 GDPR Article 5(1) 七条原则、Article 15-22 数据主体权利、已知限制（无自动 erasure 管线、audit-seal 保护字段范围、external audit anchor 默认 local-file、live authority adapter 是 operator 环境工作、PostgreSQL portability、crypto-shred 流程指引）以及 reviewer 8 步最小取证路径，可作为合规/法务复核的入口文档
13. **Track-E1（电商事实层基线）**：`migrations/metadata/010_add_ecommerce_fact_tables.sql` 落基线 6 张事实表（`orders` / `order_items` / `order_attribution` / `order_payment` / `order_fulfillment` / `customer_service_interactions`），`migrations/postgres/001_init.sql` 已同步对齐；`scripts/render_ecommerce_fact_layer.py` 输出 `ecommerce_fact_layer_report/v1`；默认 contract smoke 渲染并断言 6 表全在 + indexes ≥ 12，详见 [ECOMMERCE_FACT_LAYER_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_FACT_LAYER_PLAN.md)
14. **Track-E2（业务身份基线）**：`migrations/metadata/011_add_business_identities.sql` 落基线 `business_identities` 注解层（`identity_kind` ∈ `buyer` / `merchant_staff` / `customer_service_agent` / `courier` / `field_marketer`），不破坏已冻结的 `caller_permissions` schema、不引入新的 stage gate、PII-free，详见 [ECOMMERCE_ACCESS_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_ACCESS_MODEL.md) §业务身份扩展
15. **Track-E3（operator console 产品基线）**：`config/operator_console/console_manifest.json` 落基线 `console_manifest/v1`（home / jobs / audit / catalog / permissions / recovery / observability / compliance 共 8 个 section、25 个 endpoint、5 个 platform_role），`config/operator_console/index.html` 静态占位页运行时 fetch manifest，`scripts/render_operator_console_manifest.py` 输出 `operator_console_manifest_report/v1`；默认 contract smoke 校验 manifest、断言 8 个 section + manifest 引用都在；详见 [OPERATOR_CONSOLE_PRODUCT_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPERATOR_CONSOLE_PRODUCT_PLAN.md)

## 4. 当前不能做什么

当前不应该把这个仓库描述成“真实生产电商平台”。

还不能：

1. 作为完整生产级多租户平台上线
2. 默认依赖真实 Keycloak / OpenFGA / Vault / AWS KMS 作为在线权威源；当前 repo 提供 adapter 和 live 工具，但不托管生产服务本身
3. 作为 HA PostgreSQL control plane 运行
4. 提供成熟 dashboard、workflow、admin UI
5. 提供完整的大规模真实性能压测体系
6. 作为完整电商业务明细仓库或统一 customer 360 数据底座使用
7. 用当前 caller 模型直接覆盖所有真实业务身份，如买家、客服、快递员、门店运营、商家店员等

这不是缺陷陈述，而是当前阶段边界。

## 5. 当前权限模型

当前已经有一版电商场景权限矩阵，不是空文档。

角色画像：

1. `commerce_ops_owner`
2. `campaign_analyst`
3. `fraud_analyst`
4. `compliance_auditor`
5. `recovery_service_operator`

这套画像已经够支撑“比赛版隐私查询平台”，但还不是完整电商组织身份树。

权限层次：

1. `platform_roles`：平台角色
2. `access_profile`：业务画像
3. `tenant_id / allowed_dataset_ids / allowed_service_ids`：scope
4. `can_*`：阶段能力

最直接入口：

1. [ECOMMERCE_ACCESS_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_ACCESS_MODEL.md)
2. [sse/config/ecommerce_access_policy.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/sse/config/ecommerce_access_policy.example.json)

## 6. SQL sidecar 的正确定位

当前 SQL 不是主链路真值源，而是 control-plane sidecar。

这意味着：

1. 不要求主链路直接写库
2. 当前重心是 import/query/manage，而不是 DB-first 重构
3. 未来可以迁移到 PostgreSQL，但现在不强绑主链路
4. 当前不把完整电商事实字段作为 sidecar 查询目标，例如商品 SKU、类目、成交平台、投放平台、点击来源、收货地址、物流节点、客服会话明细

最重要的现有入口：

1. `scripts/init_metadata_db.py`
2. `scripts/import_run_metadata.py`
3. `scripts/query_metadata.py`
4. `scripts/serve_metadata_api.py`
5. `scripts/manage_metadata_db.py`

## 7. benchmark 的正确理解

当前 benchmark 分两类：

1. 轻量 sidecar / adapter / contract 基线
2. 重路径 pipeline / PJC / live SSE 基线

它们当前更偏：

1. 可重复功能回归
2. 性能趋势对比
3. 比赛与本地验证

而不是：

1. 完整生产级压测平台
2. 百万级真实业务流量验证体系

## 8. 如果你只读 5 份文档

按顺序读：

1. [COMPACT_PLATFORM_BRIEF.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/COMPACT_PLATFORM_BRIEF.md)
2. [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md)
3. [POST_BASELINE_ROADMAP.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/POST_BASELINE_ROADMAP.md)
4. [TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md)
5. [ECOMMERCE_ACCESS_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_ACCESS_MODEL.md)

## 9. 按问题找文档

如果你关心：

1. 主链路与安全边界：
   [TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md)
   [THREAT_MODEL_AND_LEAKAGE_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md)
   [BRIDGE_HANDOFF_HARDENING_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/BRIDGE_HANDOFF_HARDENING_PLAN.md)

2. 权限/IAM/KMS：
   [ECOMMERCE_ACCESS_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_ACCESS_MODEL.md)
   [TASK_ENGINEER_A_CONTROL_PLANE_IDENTITY_ACCESS.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_ENGINEER_A_CONTROL_PLANE_IDENTITY_ACCESS.md)
   [IAM_AUTHZ_INTEGRATION_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/IAM_AUTHZ_INTEGRATION_PLAN.md)
   [KMS_SECRET_BACKEND_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/KMS_SECRET_BACKEND_PLAN.md)

3. SQL sidecar：
   [DELEGATION_ENGINEER_2_SQL_CONTROL_PLANE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/DELEGATION_ENGINEER_2_SQL_CONTROL_PLANE.md)
   [CONTROL_PLANE_SCHEMA.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/CONTROL_PLANE_SCHEMA.md)

4. benchmark / operator / runbook：
   [BENCHMARK_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/BENCHMARK_PLAN.md)
   [OPS_RUNBOOK.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPS_RUNBOOK.md)

5. “平台基线已经做完，下一阶段先做什么？”
   [POST_BASELINE_ROADMAP.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/POST_BASELINE_ROADMAP.md)

6. PJC + SSE 电商平台叙事补完（Track-E1 / Track-E2 / Track-E3）：
   [ECOMMERCE_FACT_LAYER_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_FACT_LAYER_PLAN.md)
   [ECOMMERCE_ACCESS_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_ACCESS_MODEL.md) §业务身份扩展
   [OPERATOR_CONSOLE_PRODUCT_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPERATOR_CONSOLE_PRODUCT_PLAN.md)
   生产就绪 vs Track-E 范围对照：[PRODUCTION_READINESS_GUIDEBOOK.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PRODUCTION_READINESS_GUIDEBOOK.md) §12

## 10. 建议

后续会话不要默认把 `docs/*.md` 全读一遍。

建议流程：

1. 先读这份压缩总览
2. 再读剩余工作量估算
3. 如果目的是继续推进，立刻读 `POST_BASELINE_ROADMAP.md`
4. 再按问题跳转到 1-2 份深文档

这样最省 token，也最不容易把外围材料和主线边界混在一起。
