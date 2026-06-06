# 平台压缩总览

这份文档用于替代“先把 `docs/` 全读一遍”的做法。

> 2026-06-01 更新：如果要判断协议安全、功能完整性、真实攻击防护或当前剩余问题，先读 [CURRENT_SECURITY_AND_COMPLETION_AUDIT.md](CURRENT_SECURITY_AND_COMPLETION_AUDIT.md)；如果要开始补齐任务，读 [REMAINING_WORK_IMPLEMENTATION_BACKLOG.md](REMAINING_WORK_IMPLEMENTATION_BACKLOG.md)。本文件只负责快速建立项目上下文。
>
> 2026-06-05 更新：如果当前任务是解释“哪些问题已经靠 repo-side 收口、哪些必须线上+线下双管齐下、哪些只剩 malicious-secure backend 或外部 trust-root 才能解决”，直接读 [ONLINE_OFFLINE_SECURITY_GOVERNANCE.md](ONLINE_OFFLINE_SECURITY_GOVERNANCE.md)。

目标：

1. 用一份 markdown 说明项目是什么
2. 说明当前代码已经推进到哪里
3. 说明当前能做什么、不能做什么
4. 给出最少量的后续深读入口

如果只想快速建立上下文，优先读这份。

如果当前任务是三人协作、环境准备、pre 汇报或结题报告，请同时读 [TEAM_COLLABORATION_AND_REPORTING_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/team/TEAM_COLLABORATION_AND_REPORTING_PLAN.md)。它是当前协作分工、Ubuntu/设备建议、测试证据包和报告呈现方式的统一口径。

如果当前任务是“安全问题要完整解决，不要只缓解”，请同时读 [PRODUCTION_SECURITY_COMPLETION_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PRODUCTION_SECURITY_COMPLETION_PLAN.md)。它固定 S1-S8 生产级安全任务包、完整任务闭环规则和三人联合认证标准。

## 1. 项目是什么

这个仓库当前最准确的定位是：

一个**面向电商隐私分析场景**的比赛版隐私计算平台基线，其中
**数据库/控制面 + SSE + Google PJC** 是技术内核，电商订单/归因/
物流/客服/审批流是关键业务适配场景，而不是替代技术内核的项目本体。

主链路：

```text
metadata / encrypted record store
-> SSE candidate export
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

这里的“数据库”主要指两层：

1. `migrations/metadata/` + metadata sidecar：控制面 / workflow / policy /
   audit / privacy-budget 状态库
2. `services/record_recovery/encrypted_record_store.py`：用于敏感记录恢复的
   加密记录库

这里的 `SSE` 不是演示壳，而是 candidate selection 的核心能力；被退休的是
旧的 legacy WebSocket 暴露面，而不是 searchable encryption 本身。

这里的 `PJC` 计算内核来自 Google 开源实现。当前项目的重点不是重写 PJC
协议，而是在它前后增加控制面、输入约束、证据绑定、发布门控和 live
verifier evidence。

## 2. 当前状态

当前代码已经超过“原型 demo”，但不应被描述成“完整商业电商平台”。
更准确的说法是：

1. 面向电商场景的隐私计算平台工程已经成型
2. 顶层 verifier-facing live 收口已经完成
3. 核心计算安全边界仍然应按 `semi-honest/operator-controlled` 表述

截至当前 authoritative 汇总，16 个顶层 verifier-facing 模块都已达到：

- `status=ok`
- `repo_side_status=ok`
- `live_status=ok`

顶层 authoritative 结果见：

- `tmp/production_security_closure_gate/production_security_closure_gate.json`
- `tmp/final_live_blockers_report.json`

关键摘要：

- `module_count=16`
- `live_ok_count=16`
- `live_fail_count=0`
- `live_skipped_count=0`
- `remaining_live_module_count=0`

这说明当前项目已经从“平台基线版”推进到了“平台级收口已绿”的状态。

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
4. protocol-external governance 基线已新增并接通：
   - `source_export_manifest/v1`
   - `source_attestation/v1`
   - `source_truthfulness_report/v1`
   - `release_governance_report/v1`
   - query request / submit / worker / pipeline / release gate / audit chain
     之间已经能透传并绑定 source-truthfulness、signoff、input commitment
   - 2026-06-06：strict source-attestation 进一步收紧为
     dual-signoff / reviewer-separation / source-export-manifest scope binding；
     strict release gate 进一步收紧为 dual-signoff requirement、truthfulness
     report strictness binding、external-anchor job binding；privacy-budget
     heuristics 进一步覆盖 close-window / threshold-round / cross-bucket
     differencing deny；HTTP recovery production gate 进一步要求
     output-root / record-store-root / max_rows_per_request 全部存在
   - 这属于 protocol-external governance，不是 `malicious-secure` 计算声明

安全上还没完成的，当前应只按两类表述：

1. **协议内 / 架构内强化**
   - `PJC` 从当前 `semi-honest` 计算内核推进到更强的恶意方安全等级
   - 更强的 `SSE` 搜索模式 / 访问模式泄露缓解（如 ORAM、forward-private
     SSE、OPRF-blinded query 等）
2. **真实外部 operator / enterprise trust root**
   - 真实 Keycloak / OpenFGA / Vault / cloud KMS 的长期生产托管、
     轮换、吊销、回滚和 SRE 值守流程
   - 真实 immutable anchor、企业身份根、live HA / worker / SRE 证据

更完整的电商事实域与 customer 360 仍然只是业务扩展方向，不是当前平台技
术内核安全闭环的剩余 blocker。

电商平台这个词在答辩叙事里是重要的，但应表述为：

> 我们做的是一个面向电商隐私分析场景的隐私计算平台；
> 电商是关键业务适配场景，数据库/控制面 + SSE + Google PJC 是技术主线。

当前剩余问题和生产安全判断以 [CURRENT_SECURITY_AND_COMPLETION_AUDIT.md](CURRENT_SECURITY_AND_COMPLETION_AUDIT.md) 为准；具体实现级任务以 [REMAINING_WORK_IMPLEMENTATION_BACKLOG.md](REMAINING_WORK_IMPLEMENTATION_BACKLOG.md) 为准；历史 block 估算只作为追溯资料保留在 [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md)。

平台基线之后的继续推进顺序以 [POST_BASELINE_ROADMAP.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/POST_BASELINE_ROADMAP.md) 为准。

## 3. 当前能做什么

### 3.1 主链路

1. 跑完整 `SSE -> recovery -> bridge -> PJC -> release`
2. 支持 file handoff、retained file handoff、FIFO handoff
3. 支持 standalone recovery service，Unix socket / HTTP 两种 transport
4. 支持 request timestamp anti-replay、HMAC request signing
5. 支持 replay 验证、mainline contract check、audit chain / seal / archive
6. 支持 source-truthfulness / release legitimacy 的 repo-side 治理闭环：
   source export manifest、signed source attestation、strict verifier、
   release gate 绑定、release governance report

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
15. **Track-E3 / I3（operator console 产品基线 + request workflow）**：`config/operator_console/console_manifest.json` 现在有 `console_manifest/v1` 9 个 section（home / jobs / requests / audit / catalog / permissions / recovery / observability / compliance）和 `approval_workflow` feature flag；`serve_operator_dashboard.py` 支持 submit/list/detail/approve/reject request workflow，把 `query_workflow_request/v1` 写入 `workflow_submissions` 并返回 `operator_request_submission/v1` / `operator_request_submission_list/v1`；approve 会校验 `privacy_operator` / `platform_admin`、阻止 same-identity self-approval、写 `control_plane_mutations` 并启动现有 dashboard job path；默认 contract smoke 校验 manifest、request-submission/list/detail/approve/reject 样本、DB row 和 mutation row；详见 [OPERATOR_CONSOLE_PRODUCT_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPERATOR_CONSOLE_PRODUCT_PLAN.md)
16. **I2-a / I2-b（alerting integration）**：`scripts/check_observability_alerts.py --webhook-url --webhook-format slack|alertmanager` 把 firing alert 推到 Slack incoming-webhook 或 Alertmanager `/api/v1/alerts`；零 firing 时默认 skip。`scripts/run_alert_check_daemon.py` 在轮询循环里跟踪每条 alert 的 firing 状态、计算 `unknown→firing` / `firing→resolved` / `resolved→firing` 三类 transition、写 `alert_daemon_heartbeat/v1` JSONL，并按 transition 触发 webhook；支持 `--max-iterations` cron one-shot、SIGINT/SIGTERM 干净退出；详见 [OPS_RUNBOOK.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPS_RUNBOOK.md) 的 alert 章节
17. **K1-a（S3 Object Lock 外部审计 anchor sink）**：`scripts/publish_external_audit_anchor.py` 新增 `--sink-kind file_ledger|s3_worm`（默认 `file_ledger`，旧路径不变）、`--object-lock-mode COMPLIANCE|GOVERNANCE`、`--retain-days <int>`（默认 3650 = 10 年 retain-until）、`--execute`（默认 planned 状态、不调用 boto3）。`s3_worm` sink 把现有 `external_audit_anchor_ledger/v1` JSONL 上传到 S3 Object Lock 对象，租户路径校验同时检查 S3 key 的 path segment（`s3://bucket/audit/<tenant>/ledger.jsonl`）。`external_audit_anchor_report/v1` 新增可选 `external_sink.s3_object_lock`（bucket / key / object_lock_mode / retain_until_utc / retain_days / executed / status / etag / version_id / previous_object_etag）。默认 contract smoke 跑 planned-mode + cross-tenant key reject 两条 K1-a 路径，无 AWS 凭证；live `--execute` 上传归 operator 环境
18. **K1-b（Sigstore Rekor 透明日志外部审计 anchor sink）**：同一脚本扩展 `--sink-kind rekor`（与 `file_ledger` / `s3_worm` 共用 `--external-ledger` 与 `--execute`）、`--rekor-signing-key-env <env>`、`--rekor-timeout-sec`。Rekor URL 仅接受 `http(s)://`。带 `--execute` 时对每条 anchor record 把 canonical bytes `b"entry_sha256:<hex>\n"` 用 ECDSA-P256 / SHA256 签名，构造 `hashedrekord/0.0.1` payload，POST 到 `<rekor>/api/v1/log/entries`，把回包 uuid + `logIndex` + `integratedTime` 写回 `external_audit_anchor_report/v1` 的 `external_sink.rekor_transparency_log.entries[]`；不带 `--execute` 时 `status=planned` / `submitted_count=0`，默认 contract smoke 不需要网络也不需要密钥。本地用 in-process loopback HTTP receiver + cryptography 服务端验签的 2 条 records 跑通 `--execute` 路径（2/2 uploaded）；live Sigstore Rekor 提交归 operator 环境
19. **J4（chaos / failure-injection 工具链）**：`scripts/run_chaos_test.py` + `chaos_test_report/v1` 覆盖 5 个 chaos 场景。3 个 in-process 场景默认跑：`recovery_service_sigkill`（spawn 可观测的 record-recovery HTTP service，用 server shutdown 模拟 SIGKILL，断言客户端拿到 connection refused / reset 等干净 transport-level 错误）、`mtls_cert_expired`（cryptography 现场签发 `not_valid_after` 已过期的自签证书，把它当作 client trust anchor 加载，断言 `ssl.SSLCertVerificationError`）、`audit_archive_unwritable`（先用 `seal_audit_artifact.py` 合成真实 `audit_chain.json` + seal，对 archive dir `chmod 0` 后 subprocess 调 `archive_audit_bundle.py`，断言非 0 退出 + 无残留写入 + 源 chain SHA-256 不变）。2 个 operator-environment 场景（`postgres_primary_killed`、`audit_log_path_full`）恒定 `status=skipped`，沿用 OPS_RUNBOOK 的 chaos drills 章节。默认 contract smoke 用 `--scenarios all --assert-ok` 验证 5 总数 / 3 ok / 2 skipped / 0 audit_chain corruption / 受控的 observed_failure_mode 集合

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
