# 平台级剩余工作量估算

## 1. 估算口径

这里的“平台级别”指的是：

1. 不再只是 demo / sidecar 拼装。
2. 关键敏感边界有独立 deploy/lifecycle/authn 形态。
3. control plane 不再只是 post-run SQLite 查询壳。
4. query / audit / metadata / platform-health 这些外围入口具备稳定平台入口形态。
5. KMS / authz / audit retention / ops 不再只停留在本地 mock 或单机脚本。

这里**不**把下面这些一起算进来：

1. 完整生产级多租户硬隔离。
2. 真正的 HSM / 云 KMS 落地。
3. 多机房、SLO、告警轮值、容量规划。
4. 完整管理员 UI、SDK 发布、长期兼容支持。

如果把这些也一起算进来，工时会明显更大。

## 2. 5h 口径

统一按下面口径估算：

1. `1 block = 5h`
2. 一个 block 默认应该能完成一段“代码/验证/文档”闭环，而不是只做分析。
3. 估算是剩余实现量，不含多人排期等待。

## 3. 总表

| 任务 | 剩余 block | 约合工时 | 说明 |
| --- | ---: | ---: | --- |
| owner：隐私内核与接口治理 | 0 | 0h | ~~Block1~~ ✓, ~~Block2~~ ✓, ~~Block3~~ ✓, ~~Block4~~ ✓, ~~Block5~~ ✓, ~~Block6~~ ✓；owner 主线已完成平台基线 |
| 工程师 A：控制面、身份、权限与密钥 | 0 | 0h | ~~mutation governance log~~ ✓, ~~OIDC + issuer registry~~ ✓, ~~Vault HTTP + rotation~~ ✓, ~~key backend drift~~ ✓, ~~policy mutation governance~~ ✓（全部 2026-05-03）；工程师 A 主线已完成平台基线 |
| 工程师 B：查询入口、目录、工作流、观测 | 0 | 0h | ~~B1~~ ✓, ~~B2~~ ✓, ~~B3~~ ✓, ~~B4~~ ✓, ~~B5~~ ✓, ~~B6~~ ✓, ~~B7~~ ✓, ~~B8~~ ✓；工程师 B 主线已完成平台基线 |
| 工程师 1：审计、运维与稳定性工具 | 0 | 0h | ~~fuzz/安全门禁~~ ✓, ~~benchmark CI gate~~ ✓, ~~部署/恢复/SLO 包~~ ✓；工程师 1 主线已完成平台基线 |
| 工程师 2：SQL 控制面侧车 | 0 | 0h | ~~Postgres DDL target~~ ✓（2026-05-03）, ~~cross-batch reconcile~~ ✓（2026-05-03）；工程师 2 全部 block 已完成 |

合计：

1. 串行视角：`0 blocks = 0h`（owner 已完成 Block1~6；工程师 1 全部已完成；工程师 2 全部已完成；工程师 A 全部 5 blocks 已完成；工程师 B 全部 8 blocks 已完成）
2. 并行视角：所有任务线均已完成平台基线，无剩余关键路径

## 工程师 B 已完成 block 拆分（2026-05-03 收口）

| Block | 约合工时 | 目标 | 主要回写 |
| --- | ---: | --- | --- |
| ~~B1~~ ✓ | 5h | execute 治理边界：固化 submit/execute 差异、身份绑定、允许的请求形态与失败分类 | `docs/QUERY_INTERFACE_PLAN.md`、工程师 B 任务书 |
| ~~B2~~ ✓ | 5h | execution receipt / status sidecar：围绕 `query_workflow_submission/v1` 定义 started/completed/failed 回执与只读状态面 | `docs/QUERY_INTERFACE_PLAN.md`、`docs/BENCHMARK_PLAN.md` |
| ~~B3~~ ✓ | 5h | observability dashboard example：围绕 `pipeline_observability/v1` 与 `platform_health/v1` 形成固定 operator 面板 | `docs/OBSERVABILITY_PLAN.md`、`docs/OPS_RUNBOOK.md` |
| ~~B4~~ ✓ | 5h | alert / triage baseline：明确 repeated failure、release failure、health degraded 等联动排障路径 | `docs/OBSERVABILITY_PLAN.md`、`docs/OPS_RUNBOOK.md` |
| ~~B5~~ ✓ | 5h | durable submit/status baseline：围绕现有 CLI wrapper 补 submit receipt 与状态查询闭环 | `docs/QUERY_INTERFACE_PLAN.md`、工程师 B 任务书 |
| ~~B6~~ ✓ | 5h | retry / recovery lifecycle：定义哪些失败可重试、哪些必须 operator 重新提交 | `docs/QUERY_INTERFACE_PLAN.md`、`docs/OPS_RUNBOOK.md` |
| ~~B7~~ ✓ | 5h | admin shell / SDK baseline：把 metadata/query/audit/platform-health/status 收成统一 operator shell 场景 | `docs/CATALOG_LINEAGE_PLAN.md`、工程师 B 任务书 |
| ~~B8~~ ✓ | 5h | regression / handoff baseline：把 execute、status、dashboard、lineage、health 串成最小可复现交接流 | `docs/BENCHMARK_PLAN.md`、`docs/NEXT_SESSION_READING_GUIDE.md` |

## owner 已完成 block 记录

| 完成时间 | Block | 入口 | 验证 |
| --- | --- | --- | --- |
| 2026-05-01 | Block3 (1/2): bridge_audit schema + normalizer fields | `bridge_audit/v1` schema, `config/schema_backcompat_baseline.json` | `check_ci_smoke.sh` ✓ |
| 2026-05-01 | Block3 (2/2): normalizer_schema_version + validator | `NORMALIZER_SCHEMA_VERSION` const, `validate_bridge_job.py` | `check_ci_smoke.sh` ✓ |
| 2026-05-01 | Block4 (1/1): replay verification, governance docs sign-off | `verify_pipeline_replay.sh`, benchmark fix, freeze matrix, owner checklist | `check_ci_smoke.sh` ✓ |
| 2026-05-01 | Block1 (1/4): request timestamp anti-replay on recovery service | `validate_request_timestamp`, client timestamp injection, audit schema | `check_ci_smoke.sh` ✓ |
| 2026-05-01 | Block1 (2/4): systemd host-level hardening for recovery service | `derive_writable_paths`, full Linux security directives, smoke assertions | `check_ci_smoke.sh` ✓ |
| 2026-05-01 | Block1 (3/4): HMAC-SHA256 request signing for recovery service | `sign_request`, `verify_request_signature`, client request_id+sig, audit fields | `check_ci_smoke.sh` ✓ |
| 2026-05-01 | Block1 (4/4): SQLite-backed recovery authz source | `record_recovery_authz_source/v1`, `services/record_recovery/authz.py`, contract smoke | `check_json_contracts.sh` ✓ |
| 2026-05-01 | Block2 (1/1): manual external recovery-service replay | `verify_record_recovery_manual_service_replay.sh`, `run_live_sse_bridge_demo.sh --record-recovery-service-mode manual` | targeted replay ✓ |
| 2026-05-01 | Block5 (1/2): FIFO handoff replay + handoff_mode field | `verify_fifo_handoff_replay.sh`, `handoff_mode` in `mainline_contract_check.json`, schema + backcompat baseline update | `check_ci_smoke.sh` ✓ |
| 2026-05-01 | Block6 (2/2): handoff_exposure_assessment + Phase 2 docs | `handoff_exposure_assessment` in `mainline_contract_check.json`, OPS_RUNBOOK handoff section, BRIDGE_HANDOFF_HARDENING_PLAN Phase 1+2 sign-off | `check_ci_smoke.sh` ✓ |
| 2026-05-01 | Block6 派生视图收口（同次完成，归 Block6）：handoff exposure 贯通归档/派生视图链路 | `archive_audit_bundle.py` summary fields `handoff_mode`/`handoff_exposure`, schema updates (`audit_archive_index`, `audit_bundle_verification`, `catalog_lineage`), positive smoke assertions in `check_pipeline_artifact_smoke_reports.py`, `EXPECTED_STAGES` += `handoff_exposure_assessment` in `benchmark_derived_views.py` | `check_ci_smoke.sh` ✓ |

## 工程师 1 已完成 block 记录

| 完成时间 | Block | 入口 | 验证 |
| --- | --- | --- | --- |
| 2026-05-01 | fuzz/malformed-input/security scan gate（1/3）：系统性负向测试门禁 | `scripts/check_malformed_input_gate.py`, `schemas/malformed_input_gate.schema.json`, `config/schema_backcompat_baseline.json` backcompat entry | `check_ci_smoke.sh` ✓ (`check_json_contracts.sh` double-gate ✓) |
| 2026-05-01 | benchmark/CI gate（2/3）：统一发布前检查门禁 | `scripts/check_pre_release_gate.py`, `schemas/pre_release_gate.schema.json`, `schemas/repo_hygiene_scan.schema.json`, `schemas/dependency_hygiene.schema.json`, backcompat baseline entries × 3 | `check_ci_smoke.sh` ✓ (`check_json_contracts.sh` double-gate ✓) |
| 2026-05-01 | platform health/backup/restore/SLO/checklist block（3/3 + runbook Block B）：Operator 就绪门禁 + deployment package runbook | `scripts/check_operator_readiness.py`, `schemas/operator_readiness.schema.json`, backcompat baseline entry; OPS_RUNBOOK.md 新增 Operator Readiness Check、Pre-Deployment Checklist、Failure Recovery Decision Tree、SLO Baseline 四章 | `check_ci_smoke.sh` ✓ (`check_json_contracts.sh` double-gate ✓) |

## 工程师 2 已完成 block 记录

| 完成时间 | Block | 入口 | 验证 |
| --- | --- | --- | --- |
| 2026-05-01 | read-only CLI / HTTP API pagination + output contract baseline | `scripts/query_metadata.py`, `scripts/serve_metadata_api.py`, metadata pagination smoke/benchmark assertions | `check_json_contracts.sh` ✓ |
| 2026-05-01 | importer dry-run / reconcile / replay baseline | `scripts/import_run_metadata.py`, `schemas/metadata_import_report.schema.json`, import dry-run + replay smoke assertions | `check_json_contracts.sh` ✓ |
| 2026-05-01 | Postgres-ready DDL portability baseline | `migrations/metadata/001_init.sql`, `scripts/check_metadata_schema_portability.py`, `schemas/metadata_schema_portability.schema.json` | `check_json_contracts.sh` ✓ |
| 2026-05-01 | managed registry / policy / permission write baseline | `scripts/manage_metadata_db.py apply-registry`, `scripts/metadata_registry.py`, `schemas/metadata_registry_manifest.schema.json`, `schemas/metadata_registry_apply_report.schema.json`, example manifest + DB->tuple smoke | `check_json_contracts.sh` ✓ |
| 2026-05-03 | key registry / key version control-plane baseline | `migrations/metadata/004_add_key_registry.sql`, `config/metadata_registry.example.json`, `scripts/manage_metadata_db.py`, `scripts/query_metadata.py`, `scripts/serve_metadata_api.py` | `check_json_contracts.sh` ✓ |
| 2026-05-03 | metadata DB restore / ops lifecycle baseline | `scripts/manage_metadata_db.py restore`, `schemas/metadata_db_restore.schema.json`, `scripts/check_json_contracts.sh`, `docs/OPS_RUNBOOK.md` | `check_json_contracts.sh` ✓ |
| 2026-05-03 | unified identity resolution + sidecar API authz baseline | `scripts/api_identity.py`, `scripts/resolve_api_identity.py`, metadata `/v1/identity`, query execute-vs-dry-run gate, audit `include_paths` gate, identity contract smoke | `check_json_contracts.sh` ✓ |
| 2026-05-03 | Vault KV / external KMS compatibility baseline | `schemas/vault_kv_backend.schema.json`, `scripts/keyring_lib.py`, `scripts/key_agent_service.py`, `scripts/external_kms_service.py`, `scripts/manage_keyring.py`, `scripts/manage_external_kms.py`, pipeline auto-start + vault-backed smoke | `check_json_contracts.sh` ✓ |
| 2026-05-03 | Postgres DDL target ownership（Block A）：完整 Postgres 类型升级 DDL + 导出验证工具 | `migrations/postgres/001_init.sql`（SERIAL/TIMESTAMPTZ/JSONB/BOOLEAN），`scripts/export_postgres_ddl.py`，`schemas/postgres_ddl_export.schema.json`，portability gate + backcompat baseline 同步更新 | `check_json_contracts.sh` ✓ |
| 2026-05-03 | Cross-batch reconcile/repair（Block B）：跨批次对账与修复工具 | `scripts/reconcile_metadata_batches.py`，`schemas/metadata_batch_reconcile.schema.json`，backcompat baseline entry，contract smoke 验证新导入的 DB 为 clean 状态 | `check_json_contracts.sh` ✓ |

## 工程师 A 已完成 block 记录

| 完成时间 | Block | 入口 | 验证 |
| --- | --- | --- | --- |
| 2026-05-03 | Control-plane mutation governance log（Block 1/5）：写操作审计日志 | `migrations/metadata/005_add_mutation_log.sql`，`log_mutation()` / `log_entity_mutations()` 集成进 `manage_metadata_db.py apply-registry`，`scripts/query_mutation_log.py`，`schemas/mutation_log_query.schema.json`，backcompat baseline entry，contract smoke 验证 apply-registry 后 mutation log 含 ≥13 条记录 | `check_json_contracts.sh` ✓ |
| 2026-05-03 | OIDC claim mapper + issuer registry（Block 2A/5）：JWT 解析 + 发行方注册 | `migrations/metadata/006_add_issuer_registry.sql`（含 `service_id` FK），`manage_metadata_db.py` 支持 `issuer_registry` manifest 条目，`api_identity.py` 新增 issuer registry 查表，`scripts/map_oidc_claims.py` + `schemas/oidc_claim_map.schema.json`，`config/oidc_claim_mapping.example.json`；Postgres DDL 同步更新；contract smoke 验证 HS256 JWT 映射全链路 | `check_json_contracts.sh` ✓ |
| 2026-05-03 | Vault HTTP adapter + credential rotation governance（Block 2B/5）：远端 KMS 适配器 + 凭证轮换 | `scripts/vault_http_client.py` + `schemas/vault_http_client_result.schema.json`（real/mock 两模式），`keyring_lib.py` 新增 `vault_http` secret_ref kind，`config/vault_http_client.example.json`，`scripts/rotate_issuer_credentials.py` + `schemas/issuer_credential_rotation.schema.json`（按 issuer→key_refs 轮换版本 + mutation log）；backcompat baseline + contract smoke 全覆盖 | `check_json_contracts.sh` ✓ |
| 2026-05-03 | Key backend drift detection + reconcile（Block 3A/5）：key_refs/key_versions 漂移检测与修复 | `scripts/check_key_backend_drift.py` + `schemas/key_backend_drift.schema.json`；支持 manifest 和 vault_kv 两种参照源；检测 `key_ref_missing/field_drift/version_missing/version_field_drift/key_ref_extra/version_extra` 六类漂移；`--repair` 安全修复 drifted 字段和缺失版本并写入 mutation log；contract smoke 验证 clean manifest → `status=clean`，vault_kv 源 → schema 有效 | `check_json_contracts.sh` ✓ |
| 2026-05-03 | Write-side policy mutation governance（Block 3B/5）：策略变更治理 | `scripts/check_policy_drift.py` + `schemas/policy_drift.schema.json`（sha256 比对、`--repair` 重新导入并写 mutation log）；`scripts/propose_policy_change.py` + `schemas/policy_change_proposal.schema.json`（4 条治理规则：no_remove_active_bridge_callers(error), no_remove_enabled_callers(warn), frozen_field_semantics(error), caller_count_regression(warn)；`--existing-policy-path` 指定被替换策略；`--apply` 在无 error 时执行并写 mutation log）；contract smoke 验证 clean drift、unchanged file → approved、移除 active bridge caller → blocked | `check_json_contracts.sh` ✓ |

## 4. 当前结论

1. 截至 2026-05-03，owner、工程师 A、工程师 B、工程师 1、工程师 2 五条任务线均已完成”平台基线版”定义范围内的实现。
2. 本文继续保留各 block 的完成记录，是为了让后续接手者能快速追溯每个 block 的入口、验证方式和文档回写位置，而不是表示当前仍有剩余实现量。
3. 如果后续继续推进，应按”平台基线之后”的新增范围单独立项，例如真实 Temporal durable workflow、Grafana / Web dashboard 壳、真实 OIDC / OpenFGA / Vault 权威源、PostgreSQL 长期运维，而不是再把这些工作混写成当前基线的剩余 block。

平台基线之后的统一路线图见：

1. [POST_BASELINE_ROADMAP.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/POST_BASELINE_ROADMAP.md)

## 4.1 生产就绪剩余 block 快照（2026-05-06）

这个快照按 [PRODUCTION_READINESS_GUIDEBOOK.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PRODUCTION_READINESS_GUIDEBOOK.md) 的生产就绪口径统计，不改变上方“平台基线已完成”的结论。

当前剩余：**20 blocks / 约 100h**。

| 类别 | 剩余 block 数 | 具体 block |
| --- | ---: | --- |
| E — Real authority sources | 0 repo-side | repo-side 已完成；live validation 是 operator 环境工作 |
| F — Production PostgreSQL | 1 | F1-b（F2-c/F3 live drill 属于 operator 环境验证） |
| G — Scale & optimization | 7 | G3；G4-a；G4-b；G5；G6；G7；G8 |
| H — Multi-tenant isolation | 0 | H 类已完成（H1-a / H1-b / H2-a / H2-b / H3-a / H3-b） |
| I — Production operator console | 6 | I1-a；I1-b；I2-a；I2-b；I3-a；I3-b |
| J — SRE / HA | 2 | J2-b；J4 |
| K — Compliance / external audit | 4 | K1-a；K1-b；K2；K3 |

### 当前 review 返工项

这些返工项属于已完成 block 的缺陷修复，不新增生产就绪 block；应先于下一块新任务处理：

1. ~~**H2-b 返工：**~~ ✓ 2026-05-06 — dashboard per-tenant quota 的 check/start reservation 已原子化，覆盖 start 和 relaunch；新增 `try_reserve_job` / `release_reservation`，并发同租户请求不再绕过 `--max-concurrent-jobs-per-tenant`。
2. ~~**H3-a 返工：**~~ ✓ 2026-05-06 — `run_sse_bridge_pipeline.sh` 在 tenant archive 模式下最终 summary 现在打印 resolved `AUDIT_ARCHIVE_INDEX`（`<dir>/<tenant-id>/audit_chain_index.jsonl`）并新增 `audit tenant` 行，operator 不会再复制到旧的非分区路径。

返工完成时间：2026-05-06，详情见 §8 的对应记录条目。

建议下一步顺序：

1. ~~H2-b / H3-a review 返工~~ ✓ 已完成（2026-05-06）
2. ~~H3-b：per-tenant external ledger paths~~ ✓ 已完成（2026-05-06）
3. F1-b：real PostgreSQL portability gate
4. ~~H1-a：per-tenant Unix socket~~ ✓ 已完成（2026-05-07）
5. ~~H1-b：Kubernetes NetworkPolicy~~ ✓ 已完成（2026-05-07）
6. ~~F2-a：PostgreSQL primary/replica HA topology~~ ✓ repo-side 已完成（2026-05-07）
7. ~~F2-b：Patroni automated failover~~ ✓ repo-side 已完成（2026-05-07）
8. ~~F2-c：read-replica routing for sidecar reads~~ ✓ repo-side 已完成（2026-05-07）
9. ~~F3：Connection Pooling / pgBouncer topology~~ ✓ repo-side 已完成（2026-05-07）
10. ~~G1：SSE Export Throughput at Scale~~ ✓ 本地 100k / 1M benchmark 已完成（2026-05-07）
11. ~~G2-a：Record Recovery Large Candidate Set Benchmark~~ ✓ 本地 1k / 10k benchmark 已完成（2026-05-07）
12. ~~G2-b：Record Recovery Concurrent Request Benchmark~~ ✓ 本地 1k / 10 并发 benchmark 已完成（2026-05-07）

2026-05-07 进展：F1-b 的 repo-side live gate 已加强。`POSTGRES_DSN` 分支现在会通过 `check_metadata_schema_portability.py --smoke-out-base --smoke-job-id` 在 PostgreSQL 上完成 migration + import_run_metadata + query_metadata job detail 三段检查，并输出 `postgres_live_import_query_smoke`；真实 PostgreSQL 16 环境执行仍未在本地完成，因此剩余 block 数暂不下调。

2026-05-07 进展：F2-a repo-side 已完成。新增 `scripts/render_postgres_ha_topology.py`、`postgres_ha_topology_report/v1`、`config/postgres-ha/docker-compose.primary-replica.yml`、`primary-init/01-create-replicator.sh`、`.env.example` 与 `verify_replication.sql`；contract smoke 会渲染 HA 目录、校验 report schema，并断言 PostgreSQL 16 primary/replica、`wal_level=replica`、`pg_basebackup -Xs -R`、health-gated `depends_on`、复制 role init 和 `pg_stat_replication` LSN 查询。

2026-05-07 进展：F2-b repo-side 已完成。新增 `scripts/render_patroni_failover_topology.py`、`patroni_failover_topology_report/v1`、`config/patroni-ha/docker-compose.patroni.yml`、`patroni-primary.yml`、`patroni-replica.yml` 与 `patroni_failover_commands.sh`；contract smoke 会渲染 Patroni/etcd 拓扑、校验 report schema，并断言 `etcd3` DCS、`ttl/loop_wait/retry_timeout`、`maximum_lag_on_failover`、`use_pg_rewind`、replication slots、SCRAM `pg_hba`、REST API 端口和 `patronictl list/switchover/failover` 命令。

2026-05-07 进展：F3 repo-side 已完成。新增 `scripts/render_pgbouncer_topology.py`、`pgbouncer_topology_report/v1`、`config/pgbouncer/pgbouncer.ini`、`userlist.txt.example`、`docker-compose.pgbouncer.yml` 与 `pgbouncer_commands.sh`；contract smoke 会渲染 pgBouncer 拓扑、校验 report schema，并断言 `seccomp_metadata` 到 `pg-primary:5432` 的映射、`listen_port=6432`、`pool_mode=transaction`、pool sizing、auth file、`SHOW POOLS` / `SHOW STATS`、读 benchmark 使用 pooled DSN，以及长写事务保留 direct-primary DSN。真实 pool utilization 与 direct baseline 20% 延迟对比留给 operator 环境。

2026-05-07 进展：G1 已完成本地 benchmark 验收。新增 `scripts/generate_benchmark_dataset.py`、`scripts/benchmark_sse_export.py` 与 `sse_export_benchmark/v1`；`benchmark_smoke.py --target sse-export-scale --scale <n>` 可直接触发 SSE export scale benchmark。默认 contract smoke 使用 5 records / 3 candidates 的轻量 fixture 验证 contract；本地实际跑通 100k records / 100k candidates（2.885s，约 34,661 rows/s，RSS 84,760 KB）和 1M records / 1M candidates（27.184s，约 36,786 rows/s，RSS 609,584 KB），满足 G1 的 100k < 60s 与 1M < 2GB 验收。

2026-05-07 进展：G2-a 已完成本地 benchmark 验收。`record_recovery_benchmark/v1` 结果行新增可选 `service_pid` / `service_rss_kb`，用于记录恢复服务进程 RSS；本地 `unix_socket_recover_direct` 跑通 1k candidates × 10 iterations（p50 187.210ms，p95 221.626ms，RSS 30,932 KB）和 10k candidates × 5 iterations（p50 414.680ms，p95 474.532ms，RSS 33,200 KB），满足 G2-a 的 1k p95 < 500ms 验收并补齐 10k 测量。

2026-05-07 进展：G2-b 已完成本地 benchmark 验收。`benchmark_record_recovery.py --mode g2b_acceptance` 会在一个报告中覆盖 plain HTTP sequential、plain HTTP concurrent、mTLS recover 和 `http_recover_concurrent_limited` 安全阀路径；`record_recovery_benchmark/v1` 新增可选 `g2b_summary`。本地 `candidate_count=1000 / concurrency=10 / iterations=3` 跑通：sequential HTTP p95 226.842ms、10 并发吞吐 15.818 req/s、mTLS p95 overhead -23.519ms、`max_rows_per_request=100` 下 10/10 并发超限请求被拒绝。为达成该指标，record-store 热路径新增派生 AEAD key 缓存，并对同一 store 的恢复工作做服务端串行化，避免 Python 线程争用；不缓存解密行。

## 5. 平台基线之后已完成 block 记录（2026-05-05）

| 完成时间 | Tranche/Block | 入口 | 验证 |
| --- | --- | --- | --- |
| 2026-05-05 | Tranche B / B9-B12（工程师 B）：PJC X-UI control shell + multi-run admin + durable relaunch | `scripts/serve_operator_dashboard.py`（POST /v1/jobs/start + GET /v1/jobs/{id} + GET /v1/jobs/{id}/result + POST /v1/jobs/{id}/relaunch + GET /v1/runs + POST /v1/runs/select），`docs/CONTROL_PANEL_SPEC.md` | loopback smoke ✓，`intersection_size=2` ✓ |
| 2026-05-05 | Tranche A / A1（工程师 A）：issuer-backed identity proxy baseline | `scripts/serve_identity_proxy.py`，`schemas/identity_proxy_health.schema.json`，`config/identity_proxy.example.json`，backcompat baseline entry | `check_ci_smoke.sh` ✓，`check_json_contracts.sh` ✓，schema validation ✓ |
| 2026-05-05 | Tranche A / A2（工程师 A）：OpenFGA tuple sync + check adapter | `scripts/sync_openfga_tuples.py`，`scripts/check_openfga_authz.py`，`schemas/openfga_sync_report.schema.json`，`schemas/openfga_check_result.schema.json`，`migrations/metadata/007_add_openfga_tuples.sql`，Postgres DDL | `check_ci_smoke.sh` ✓，`check_json_contracts.sh` ✓（85 schema 0 fail），Postgres parity ✓ |
| 2026-05-05 | Tranche A / A3（工程师 A）：KMS backend reachability probe | `scripts/check_kms_reachability.py`，`schemas/kms_reachability_report.schema.json` | `check_ci_smoke.sh` ✓，schema validation ✓，ok/degraded/error 三路径验证 ✓ |
| 2026-05-05 | Tranche A / A4（工程师 A）：service identity token lifecycle | `scripts/manage_service_tokens.py`，`schemas/service_token_report.schema.json`，`migrations/metadata/008_add_service_tokens.sql`，Postgres DDL | `check_ci_smoke.sh` ✓（87 schema 0 fail），issue/verify/revoke/list 四路径 schema 通过 ✓ |
| 2026-05-05 | Tranche A / A5-A6（工程师 A）：authority governance rollup + remote authority smoke/runbook 收口 | `scripts/check_authority_governance.py`，`schemas/authority_governance_report.schema.json`，`check_json_contracts.sh` authority smoke | policy/key/identity/OpenFGA/KMS/service-token/issuer 七类检查聚合，`authority_governance_report/v1` schema ✓，`check_json_contracts.sh` ✓ |
| 2026-05-05 | Tranche B / B13（工程师 B）：Grafana/OTel bridge adapter | `scripts/export_otel_events.py`，`schemas/otel_export_report.schema.json` | `check_ci_smoke.sh` ✓，6 spans，schema validation ✓ |
| 2026-05-05 | Tranche B / B14（工程师 B）：operator shell 回归与 handoff | `scripts/verify_operator_shell_regression.py`，`schemas/operator_shell_regression_report.schema.json` | 15/15 checks，8.9s，schema ✓，`check_ci_smoke.sh` ✓（88 schema 0 fail） |
| 2026-05-05 | Tranche D / D2 第一版：record-recovery service structured-log metrics baseline | `scripts/export_record_recovery_service_metrics.py`，`schemas/record_recovery_service_metrics.schema.json`，`record_recovery_service_log/v1` | Unix-socket + HTTP contract smoke 导出并校验 metrics report，start/request/stop event coverage ✓ |
| 2026-05-05 | Tranche C / C1-C5：PostgreSQL control-plane deepening sidecar read models | `migrations/metadata/009_add_control_plane_deepening.sql`，`scripts/materialize_control_plane_deepening.py`，`schemas/control_plane_deepening_report.schema.json`，Postgres DDL parity | workflow transitions、policy/service versions、JSONB/index parity、catalog lineage read model、retention/reconcile plan 全部纳入 contract smoke ✓ |
| 2026-05-05 | Tranche D / D1：recovery service mutual TLS baseline | `services/record_recovery/http_service.py`（`_build_server_ssl_context()`，TLS CLI flags，start log `tls_enabled/tls_require_client_cert`），`services/record_recovery/client.py`（`_client_ssl_context()`，proxy bypass），`services/record_recovery/config.py`（`_resolve_tls_config()`），`services/record_recovery/launcher.py`，`scripts/manage_record_recovery_service.py`（`wait_for_http_url` 走 tls_config），`scripts/request_record_recovery_service.py`，`schemas/record_recovery_service_config.schema.json`（`tls` block），`schemas/record_recovery_service_log.schema.json`（`tls_enabled/tls_require_client_cert`），`config/record_recovery_http_mtls_service.example.json` | mTLS 服务端+客户端联通，readiness polling 走 tls_config，schema 校验 ✓ |
| 2026-05-05 | Tranche D / D3：external audit anchor baseline | `scripts/publish_external_audit_anchor.py`（chain verify + append to `external_audit_anchor_ledger/v1`；dry-run / publish / --require-signature / --assert-ok），`schemas/external_audit_anchor_report.schema.json`（冻结 `external_audit_anchor_report/v1`） | chain 完整性验证（payload_sha256、entry_sha256、chain linkage、HMAC）通过；dry-run / publish 两路径 schema 校验 ✓ |
| 2026-05-05 | Tranche D / D4：ops runbook / failure recovery 收口 | `docs/OPS_RUNBOOK.md`（新增 mTLS Recovery Service 小节、External Audit Anchor Publishing 章节、Failure Recovery Decision Tree 新增 D1/D3 排障条目），`docs/RECORD_RECOVERY_INDEPENDENT_SERVICE_PLAN.md`（D1/D2/D3/D4 完成状态回写，4.6 TLS contract，5.6 mTLS 启动样例，6.1 mTLS 独立说明） | 文档回写覆盖 Tranche D 全部 4 块 ✓ |

## 6. 生产就绪阶段新增完成记录（2026-05-06）

这些记录属于 [PRODUCTION_READINESS_GUIDEBOOK.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PRODUCTION_READINESS_GUIDEBOOK.md) 的 E 类 authority-source 生产化任务，不再计入平台基线或 post-baseline A-D tranche。

| 完成时间 | Production Block | 入口 | 验证 |
| --- | --- | --- | --- |
| 2026-05-06 | E1-b：RS256 / JWKS OIDC claim mapper adapter | `scripts/map_oidc_claims.py --jwks-uri`，`config/oidc_claim_mapping.example.json`，`scripts/api_identity.py` JWKS bearer path | `check_json_contracts.sh` 生成 synthetic RS256 JWT + `file://` JWKS，校验 `oidc_claim_map/v1`、API identity、key-agent、external-KMS、metadata `/v1/identity` JWKS 路径 ✓ |
| 2026-05-06 | E2-b：OpenFGA HTTP backend for sync/check adapters | `scripts/openfga_http.py`，`scripts/sync_openfga_tuples.py --openfga-config`，`scripts/check_openfga_authz.py --openfga-config`，`config/openfga.example.json` | SQLite fallback 仍为默认；live HTTP backend code path 由 `openfga_config/v1` 控制，schema 已纳入 contract smoke ✓ |
| 2026-05-06 | E2-c：authority governance live OpenFGA gate | `scripts/check_authority_governance.py --openfga-config ... --openfga-user ...`，`scripts/check_json_contracts.sh` optional live branch | 默认 CI 不依赖 OpenFGA；当 `OPENFGA_ENDPOINT` + `OPENFGA_STORE_ID` 存在时，contract smoke 会 apply tuples、live check、并验证 `authority_governance_report/v1` ✓ |
| 2026-05-06 | E1-a / E1-c：Keycloak realm + client-credentials wiring artifacts | `docker-compose.authority.yml`，`config/keycloak_realm_seccomp_privacy.json`，`scripts/request_oidc_client_credentials.py`，`schemas/oidc_client_credentials_report.schema.json` | 默认 smoke 走 dry-run contract；live token 请求由 `--execute` + client secret env 显式启用 ✓ |
| 2026-05-06 | E2-a：OpenFGA authorization model setup artifact | `config/openfga_authorization_model.json`，`scripts/setup_openfga_model.py`，`schemas/openfga_model_setup_report.schema.json` | 默认 smoke 验证 model setup dry-run；live store/model upload 由 `--execute` 显式启用 ✓ |
| 2026-05-06 | E3-a/E3-b：Vault HTTP real-mode + AppRole config | `scripts/vault_http_client.py`，`schemas/vault_http_client_config.schema.json`，`config/vault_http_client.example.json` | token/AppRole config schema 冻结；默认 smoke 仍使用 mock fallback ✓ |
| 2026-05-06 | E3-c：Vault PKI / mTLS cert issue baseline | `scripts/issue_mtls_certs.py`，`config/vault_pki.example.json`，`schemas/mtls_cert_issue_report.schema.json` | 默认 smoke mock-mode 生成 CA/server/client certs 并校验 report schema；live Vault PKI 由 `mock_mode=false` 启用 ✓ |
| 2026-05-06 | E3-d：cloud KMS adapter baseline | `scripts/cloud_kms_adapter.py`，`scripts/keyring_lib.py`，`schemas/keyring.schema.json`，`schemas/cloud_kms_adapter_result.schema.json` | `secret_ref.kind=aws_kms` schema + lazy boto3 decrypt path；默认 smoke 只跑 synthetic describe，不需要 AWS 凭证 ✓ |

## 8. 生产就绪 F/H/J 初始 block 完成记录（2026-05-06）

这些记录属于 [PRODUCTION_READINESS_GUIDEBOOK.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PRODUCTION_READINESS_GUIDEBOOK.md) 的 F/H/J 类任务，独立于平台基线和 post-baseline A-D tranche。

| 完成时间 | Production Block | 入口 | 验证 |
| --- | --- | --- | --- |
| 2026-05-06 | F1-a：psycopg2 PostgreSQL driver layer | `scripts/metadata_db.py`（`connect_db(dsn=…)`、`is_postgres`、`placeholder`、`adapt_sql`、`row_to_dict`、`connect_db_with_retry`），`scripts/init_metadata_db.py --db-dsn`，`scripts/import_run_metadata.py --db-dsn`，`scripts/query_metadata.py --db-dsn`，`scripts/manage_metadata_db.py --db-dsn`，`scripts/serve_metadata_api.py --db-dsn`，query/audit/platform-health API `--metadata-db-dsn` identity paths，`scripts/benchmark_read_adapters.py --db-dsn` | `python3 -m py_compile` ✓；SQLite 默认路径不受影响；`check_ci_smoke.sh` ✓；真实 PostgreSQL live gate 仍归 F1-b |
| 2026-05-06 | G2-b 第一版：record-recovery HTTP concurrent benchmark scaffold | `scripts/benchmark_record_recovery.py --mode http_recover_concurrent --concurrency <n>`，`schemas/record_recovery_benchmark.schema.json`，`scripts/check_benchmark_smoke_reports.py` | 最小 HTTP 并发 smoke ✓（2 concurrent requests / 4 total output rows）；schema/backcompat ✓；真实 1k candidates × 10 concurrency 阈值验证已在 2026-05-07 G2-b 完成 |
| 2026-05-06 | G6 第一版：record-recovery mTLS benchmark scaffold | `scripts/benchmark_record_recovery.py --mode http_recover_mtls`，mock-issued recovery-service mTLS certs，`record_recovery_benchmark/v1` transport `https_mtls` | 最小 mTLS recover smoke ✓（output_rows=2）；默认 benchmark mode 不强制跑 TLS |
| 2026-05-06 | H2-a：per-caller token bucket rate limiter | `services/record_recovery/http_service.py`（`TokenBucket`、`RecordRecoveryHttpServer.check_rate_limit`、`do_POST` rate-limit gate → HTTP 429 `rate_limited`），CLI flags `--rate-limit-per-caller` / `--rate-limit-burst` | `python3 -m py_compile` ✓；`check_ci_smoke.sh` ✓ |
| 2026-05-06 | H2-b：per-tenant dashboard job quota | `scripts/serve_operator_dashboard.py --max-concurrent-jobs-per-tenant <n>`；`POST /v1/jobs/start` 与 `POST /v1/jobs/{job_id}/relaunch` 在启动 subprocess 前按 `tenant_id` 检查当前 in-memory job + `history_root` running status；超限返回 HTTP 429 `tenant_job_quota_exceeded` | `python3 -m py_compile` ✓；loopback quota smoke 返回 429 ✓；`bash -n scripts/check_ci_smoke.sh` ✓ |
| 2026-05-06 | H3-a：per-tenant audit archive partition | `scripts/archive_audit_bundle.py --tenant-id <tenant>`；租户模式写入 `<archive-dir>/<tenant-id>/audit_chain_anchor.jsonl`、`audit_chain_index.jsonl` 和 `audit_chains/<job_id>/audit_chain*.json`；归档前校验 `audit_chain.json` 中的 tenant scope 与参数一致 | `python3 -m py_compile` ✓；`check_json_contracts.sh` 正向租户分区 + mismatched tenant reject ✓；`check_ci_smoke.sh` ✓ |
| 2026-05-06 | J3-a：Prometheus /metrics endpoint | `services/record_recovery/http_service.py`（`ServiceMetrics`、`GET /metrics`），`_log_request` 自动记录 counter + histogram | `python3 -m py_compile` ✓；`check_ci_smoke.sh` ✓ |
| 2026-05-06 | H2-b 返工：dashboard per-tenant quota 原子化 | `scripts/serve_operator_dashboard.py` 新增 `DashboardServer.try_reserve_job()` / `release_reservation()`，统一覆盖 `POST /v1/jobs/start` 与 `POST /v1/jobs/{job_id}/relaunch` 的「检查 + 占位」流程；占位记录带 `reservation=True`，`_start_job_thread` 失败时由 handler 回滚；旧的非原子 `tenant_quota_violation` helper 已移除 | `python3 -m py_compile scripts/serve_operator_dashboard.py` ✓；in-process 8-thread 并发 smoke：1 success / 7 × HTTP 409 `job_already_running`，且占位释放后其他租户可继续 reserve ✓；`bash -n scripts/check_ci_smoke.sh` ✓ |
| 2026-05-06 | H3-a 返工：tenant archive summary 路径修正 | `scripts/run_sse_bridge_pipeline.sh` 最终成功 summary 现在打印 `${AUDIT_ARCHIVE_INDEX}`（tenant 模式 = `<dir>/<tenant>/audit_chain_index.jsonl`），并新增 `audit tenant: <tenant_id>` 行，避免 operator 复制到旧的非分区路径 | `bash -n scripts/run_sse_bridge_pipeline.sh` ✓；trace harness：non-tenant 输出 `…/audit_chain_index.jsonl`，tenant 模式输出 `…/<tenant_id>/audit_chain_index.jsonl` ✓ |
| 2026-05-06 | H3-b：per-tenant external ledger paths | `scripts/publish_external_audit_anchor.py` 新增 `--tenant-id`（语法白名单 `^[A-Za-z0-9][A-Za-z0-9_.\-]*$`），强制 `--anchor-file` 与 `--external-ledger` 路径都包含 `<tenant_id>` 段，且每条 `audit_archive_anchor/v1` 记录的 `tenant_id` 必须等于命令行 tenant；report 与 `external_audit_anchor_ledger/v1` 行均带 `tenant_id`；非-tenant 旧调用保持兼容（`tenant_id: null`）。`schemas/external_audit_anchor_report.schema.json` 在顶层、`external_sink`、`summary`、`records[*]` 各加可选 `tenant_id`；`config/schema_backcompat_baseline.json` 把 `tenant_id` 加入 `external_audit_anchor_report/v1` 的 `stable_properties` | `python3 scripts/check_schema_backcompat.py`：98 schema / 0 fail ✓；`scripts/check_json_contracts.sh` 新增 tenant-mode 正向 + cross-tenant reject 两条断言并通过 ✓；本地 6 路径功能 smoke（tenant 正常、anchor 路径缺段拒绝、ledger 路径缺段拒绝、record tenant mismatch 拒绝、tenant-id 路径穿越拒绝、legacy 兼容）全绿 ✓ |
| 2026-05-07 | H1-a：per-tenant Unix socket | `services/record_recovery/config.py` 新增 tenant/service/dataset 作用域派生 socket（`/tmp/seccomp_rr_<tenant>_<hash>.sock`）；`manage_record_recovery_service.py` 与 `run_record_recovery_service.py` 在 Unix-socket 模式下复用同一派生逻辑；`record_recovery_service_config/v1` 支持非空 `tenant_id` 作为省略 `socket_path` 时的最小地址来源 | `python3 -m py_compile` ✓；schema/backcompat ✓；`check_json_contracts.sh` 新增 omit-socket config 启动、health 成功、other-tenant 派生 socket 不可达断言 ✓ |
| 2026-05-07 | H1-b：Kubernetes NetworkPolicy | `scripts/render_k8s_network_policies.py` 按 `tenant_id` 渲染 recovery-service ingress NetworkPolicy；每个 manifest 只允许同租户 `app=sse-bridge-pipeline` 访问同租户 `app=recovery-service`；新增 `k8s_network_policy_report/v1` schema 和 `config/k8s/netpol-recovery-service-demo-tenant.yaml` 示例 | `python3 -m py_compile` ✓；schema/backcompat ✓；`check_json_contracts.sh` 渲染双租户 manifest、校验报告、断言 tenant/app/port 字段 ✓；operator 环境可加 `--kubectl-dry-run` |
| 2026-05-07 | F2-a：PostgreSQL primary/replica HA topology | `scripts/render_postgres_ha_topology.py` 生成 PostgreSQL 16 primary/replica compose 目录；`config/postgres-ha/docker-compose.primary-replica.yml`、`primary-init/01-create-replicator.sh`、`.env.example`、`verify_replication.sql` 作为 checked-in operator 示例；新增 `postgres_ha_topology_report/v1` schema | `python3 -m py_compile` ✓；schema/backcompat 100 / 0 fail ✓；`check_json_contracts.sh` 渲染 HA 目录、校验 report schema、断言 `wal_level=replica`、`max_wal_senders`、`wal_keep_size`、`pg_basebackup -Xs -R`、health-gated `depends_on`、复制 role init 和 `pg_stat_replication` 查询 ✓；真实容器启动/复制滞后观测留给 operator 环境 |
| 2026-05-07 | F2-b：Patroni automated failover | `scripts/render_patroni_failover_topology.py` 生成 etcd-backed two-node Patroni 拓扑；`config/patroni-ha/docker-compose.patroni.yml`、`patroni-primary.yml`、`patroni-replica.yml`、`patroni_failover_commands.sh` 作为 checked-in operator 示例；新增 `patroni_failover_topology_report/v1` schema | `python3 -m py_compile` ✓；schema/backcompat 101 / 0 fail ✓；`check_json_contracts.sh` 渲染 Patroni HA 目录、校验 report schema、断言 `etcd3`、`ttl/loop_wait/retry_timeout`、`maximum_lag_on_failover`、`use_pg_rewind`、replication slots、SCRAM `pg_hba`、REST API 端口和 `patronictl list/switchover/failover` 命令 ✓；真实 switchover/failover 时长验证留给 operator 环境 |

## 7. 使用方式

建议后续所有”公布工作量”统一写成：

1. 本次完成了哪个任务的第几个 `5h block`
2. 该 block 的入口、验证、文档回写位置
3. 剩余 block 数

这样后面的节奏会更清楚，也更方便判断哪个任务已经接近平台级收口。
