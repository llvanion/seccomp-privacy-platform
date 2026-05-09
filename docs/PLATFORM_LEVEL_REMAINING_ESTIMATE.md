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

## 4.1 生产就绪剩余 block 快照（2026-05-09 更新 / F1-b + G3 + G7 + J2-b + G4-a + G4-b + G5 收口）

这个快照按 [PRODUCTION_READINESS_GUIDEBOOK.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PRODUCTION_READINESS_GUIDEBOOK.md) 的生产就绪口径统计，不改变上方“平台基线已完成”的结论。

当前剩余：**1 block / 约 5h**（仅 K3 external pen test）。

| 类别 | 剩余 block 数 | 具体 block |
| --- | ---: | --- |
| E — Real authority sources | 0 repo-side | repo-side 已完成；live validation 是 operator 环境工作 |
| F — Production PostgreSQL | 0 | F1-b 已完成；F2-c/F3 live drill 属于 operator 环境验证 |
| G — Scale & optimization | 0 | G1/G2-a/G2-b/G3/G4-a/G4-b/G5/G6/G7/G8 全部本地完成（G4-a 100k 222s、G4-b 三轮 back-to-back 稳定、G5 10k pipeline 34.9s 均在 2026-05-09 收口；live 1M memory-ceiling row 完成后追加在 §10 表后） |
| H — Multi-tenant isolation | 0 | H 类已完成（H1-a / H1-b / H2-a / H2-b / H3-a / H3-b） |
| I — Production operator console | 0 | I1-a / I1-b / I2-a / I2-b / I3-a / I3-b 均已完成 repo-side 2026-05-08；live Tempo push、Grafana 渲染与完整 SPA 仍是 operator/product 工作 |
| J — SRE / HA | 0 repo-side | J 类 repo-side 已完成（J1 / J2-a / J2-b / J3-a / J3-b / J4 均已纳入默认 contract smoke）；J2-b 真实 Patroni switchover live drill 与 J4 真实 chaos drills 仍属 operator 环境验证 |
| K — Compliance / external audit | 1 | K3 external pen test（K1-a S3 Object Lock + K1-b Sigstore Rekor + K2 + K3 repo-side scaffolds — audit-chain tamper-resistance + HTTP malformed-input gate — 均已完成 2026-05-08；剩余 K1-a live AWS execute 与 K1-b live Rekor submission 仍属 operator-side 工作，K1 整体已不再计入；external pen test 仍按 1 个 block 计入） |

### 当前 review 返工项

这些返工项属于已完成 block 的缺陷修复，不新增生产就绪 block；应先于下一块新任务处理：

1. ~~**H2-b 返工：**~~ ✓ 2026-05-06 — dashboard per-tenant quota 的 check/start reservation 已原子化，覆盖 start 和 relaunch；新增 `try_reserve_job` / `release_reservation`，并发同租户请求不再绕过 `--max-concurrent-jobs-per-tenant`。
2. ~~**H3-a 返工：**~~ ✓ 2026-05-06 — `run_sse_bridge_pipeline.sh` 在 tenant archive 模式下最终 summary 现在打印 resolved `AUDIT_ARCHIVE_INDEX`（`<dir>/<tenant-id>/audit_chain_index.jsonl`）并新增 `audit tenant` 行，operator 不会再复制到旧的非分区路径。

返工完成时间：2026-05-06，详情见 §8 的对应记录条目。

建议下一步顺序：

1. ~~H2-b / H3-a review 返工~~ ✓ 已完成（2026-05-06）
2. ~~H3-b：per-tenant external ledger paths~~ ✓ 已完成（2026-05-06）
3. ~~F1-b：real PostgreSQL portability gate~~ ✓ 已完成（2026-05-09）
4. ~~H1-a：per-tenant Unix socket~~ ✓ 已完成（2026-05-07）
5. ~~H1-b：Kubernetes NetworkPolicy~~ ✓ 已完成（2026-05-07）
6. ~~F2-a：PostgreSQL primary/replica HA topology~~ ✓ repo-side 已完成（2026-05-07）
7. ~~F2-b：Patroni automated failover~~ ✓ repo-side 已完成（2026-05-07）
8. ~~F2-c：read-replica routing for sidecar reads~~ ✓ repo-side 已完成（2026-05-07）
9. ~~F3：Connection Pooling / pgBouncer topology~~ ✓ repo-side 已完成（2026-05-07）
10. ~~G1：SSE Export Throughput at Scale~~ ✓ 本地 100k / 1M benchmark 已完成（2026-05-07）
11. ~~G2-a：Record Recovery Large Candidate Set Benchmark~~ ✓ 本地 1k / 10k benchmark 已完成（2026-05-07）
12. ~~G2-b：Record Recovery Concurrent Request Benchmark~~ ✓ 本地 1k / 10 并发 benchmark 已完成（2026-05-07）
13. ~~G3：Bridge Binary Profiling~~ ✓ 已完成（2026-05-09，repo-side phase timing top-3 hotspot evidence 已纳入 `bridge_benchmark/v1`）
14. ~~G8：Concurrent Dashboard Jobs~~ ✓ 本地 5 并发 dashboard job benchmark 已完成（2026-05-08）
15. ~~K2：Compliance Documentation~~ ✓ `docs/COMPLIANCE_MAPPING.md` 已完成（2026-05-08），覆盖 GDPR Article 5(1) 7 条原则 + Article 15-22 数据主体权利 + 已知限制 + reviewer checklist；legal review 仍是 operator-side 工作
16. K3：Penetration Testing — audit-chain tamper-resistance 脚本+schema+contract smoke 已完成（2026-05-08），HTTP malformed-input gate 也已完成（2026-05-08，10 scenario / 10 detected）；外部渗透测试仍是 operator-side 工作
17. ~~G6：mTLS Connection Overhead Measurement~~ ✓ 本地 4×5 transport-mode 测量已完成（2026-05-08，loopback /health 上 mTLS fresh p95 ≈ 1.6ms，远低于 50ms 警戒值）
18. ~~I1-a：Grafana + Tempo + Prometheus 部署拓扑~~ ✓ repo-side compose / Tempo / Prometheus / Grafana datasource provisioning + `export_otel_events.py --otlp-endpoint` HTTP/JSON 推送适配 已完成（2026-05-08）；live push / live render 仍属 operator 环境工作
19. ~~I1-b：Grafana 仪表盘 provision~~ ✓ `pipeline-overview.json` 与 `recovery-service.json` 两个 dashboard、`dashboards.yaml` provider、render/validate 脚本与 `observability_topology_report/v1` schema 已完成（2026-05-08）
20. ~~I3-a：Request submission form~~ ✓ `serve_operator_dashboard.py POST /v1/request/submit`、`workflow_submissions` metadata sidecar 表、`operator_request_submission/v1` schema、console manifest `requests` section 与 contract smoke 已完成（2026-05-08）
21. ~~I3-b：approval / reject / pending request list workflow~~ ✓ `serve_operator_dashboard.py` approve/reject/list/detail endpoints、same-identity self-approval 403、approval-starts-job、`operator_request_submission_list/v1` 与 contract smoke 已完成（2026-05-08）
22. ~~J2-b：PostgreSQL Patroni failover repo-side scaffold~~ ✓ `scripts/test_metadata_db_failover.py` + `metadata_db_failover_test/v1` + `connect_db_with_retry` 已纳入默认 contract smoke（2026-05-09）；live Patroni switchover 仍属 operator 环境工作
23. ~~G4-a：PJC 100k×100k 实测~~ ✓ 222.02s / 260.8 MB peak RSS，本地 bazel-built PJC binary（2026-05-09）；100k < 300s SLO ✓
24. ~~G4-b：connection reuse + memory ceiling~~ ✓ 三轮 back-to-back 10k PJC 生命周期稳定、RSS 36-39 MB 无 leak；scaling 表 1k→10k→100k 落入 `pjc_benchmark/v1`，1M live ceiling 实测 33.68 min / 2.20 GB peak RSS / `exit_code=1`（grpc 512MB cap 限制 single-machine 1M 部署）（2026-05-09）
25. ~~G5：10k 全链路 SLO~~ ✓ total 34.9s / 90s p50 SLO（38% 预算）、per-stage sse 48ms / bridge 13ms / pjc 33.9s / policy 0ms（2026-05-09）；`pipeline_slo_benchmark/v1` schema 加 `not_applicable` 状态以正确表达 JSONL fixture 不走加密 record store

2026-05-07 进展：F1-b 的 repo-side live gate 已加强。`POSTGRES_DSN` 分支现在会通过 `check_metadata_schema_portability.py --smoke-out-base --smoke-job-id` 在 PostgreSQL 上完成 migration + import_run_metadata + query_metadata job detail 三段检查，并输出 `postgres_live_import_query_smoke`；真实 PostgreSQL 16 环境执行仍未在本地完成，因此剩余 block 数暂不下调。

2026-05-07 进展：F2-a repo-side 已完成。新增 `scripts/render_postgres_ha_topology.py`、`postgres_ha_topology_report/v1`、`config/postgres-ha/docker-compose.primary-replica.yml`、`primary-init/01-create-replicator.sh`、`.env.example` 与 `verify_replication.sql`；contract smoke 会渲染 HA 目录、校验 report schema，并断言 PostgreSQL 16 primary/replica、`wal_level=replica`、`pg_basebackup -Xs -R`、health-gated `depends_on`、复制 role init 和 `pg_stat_replication` LSN 查询。

2026-05-07 进展：F2-b repo-side 已完成。新增 `scripts/render_patroni_failover_topology.py`、`patroni_failover_topology_report/v1`、`config/patroni-ha/docker-compose.patroni.yml`、`patroni-primary.yml`、`patroni-replica.yml` 与 `patroni_failover_commands.sh`；contract smoke 会渲染 Patroni/etcd 拓扑、校验 report schema，并断言 `etcd3` DCS、`ttl/loop_wait/retry_timeout`、`maximum_lag_on_failover`、`use_pg_rewind`、replication slots、SCRAM `pg_hba`、REST API 端口和 `patronictl list/switchover/failover` 命令。

2026-05-07 进展：F3 repo-side 已完成。新增 `scripts/render_pgbouncer_topology.py`、`pgbouncer_topology_report/v1`、`config/pgbouncer/pgbouncer.ini`、`userlist.txt.example`、`docker-compose.pgbouncer.yml` 与 `pgbouncer_commands.sh`；contract smoke 会渲染 pgBouncer 拓扑、校验 report schema，并断言 `seccomp_metadata` 到 `pg-primary:5432` 的映射、`listen_port=6432`、`pool_mode=transaction`、pool sizing、auth file、`SHOW POOLS` / `SHOW STATS`、读 benchmark 使用 pooled DSN，以及长写事务保留 direct-primary DSN。真实 pool utilization 与 direct baseline 20% 延迟对比留给 operator 环境。

2026-05-07 进展：G1 已完成本地 benchmark 验收。新增 `scripts/generate_benchmark_dataset.py`、`scripts/benchmark_sse_export.py` 与 `sse_export_benchmark/v1`；`benchmark_smoke.py --target sse-export-scale --scale <n>` 可直接触发 SSE export scale benchmark。默认 contract smoke 使用 5 records / 3 candidates 的轻量 fixture 验证 contract；本地实际跑通 100k records / 100k candidates（2.885s，约 34,661 rows/s，RSS 84,760 KB）和 1M records / 1M candidates（27.184s，约 36,786 rows/s，RSS 609,584 KB），满足 G1 的 100k < 60s 与 1M < 2GB 验收。

2026-05-07 进展：G2-a 已完成本地 benchmark 验收。`record_recovery_benchmark/v1` 结果行新增可选 `service_pid` / `service_rss_kb`，用于记录恢复服务进程 RSS；本地 `unix_socket_recover_direct` 跑通 1k candidates × 10 iterations（p50 187.210ms，p95 221.626ms，RSS 30,932 KB）和 10k candidates × 5 iterations（p50 414.680ms，p95 474.532ms，RSS 33,200 KB），满足 G2-a 的 1k p95 < 500ms 验收并补齐 10k 测量。

2026-05-07 进展：G2-b 已完成本地 benchmark 验收。`benchmark_record_recovery.py --mode g2b_acceptance` 会在一个报告中覆盖 plain HTTP sequential、plain HTTP concurrent、mTLS recover 和 `http_recover_concurrent_limited` 安全阀路径；`record_recovery_benchmark/v1` 新增可选 `g2b_summary`。本地 `candidate_count=1000 / concurrency=10 / iterations=3` 跑通：sequential HTTP p95 226.842ms、10 并发吞吐 15.818 req/s、mTLS p95 overhead -23.519ms、`max_rows_per_request=100` 下 10/10 并发超限请求被拒绝。为达成该指标，record-store 热路径新增派生 AEAD key 缓存，并对同一 store 的恢复工作做服务端串行化，避免 Python 线程争用；不缓存解密行。

2026-05-08 进展：G3 的 repo-side timing/report scaffold 已完成。新增 `scripts/benchmark_bridge.py` 与 `bridge_benchmark/v1`，`benchmark_smoke.py --target bridge-scale --scale <n>` 可显式触发 Rust bridge `prepare-job` 规模测试；默认 contract smoke 只校验 synthetic report fixture 和命令面，不执行 cargo/flamegraph。release binary 本地跑通 100k server / 100k client（0.366s，约 546,605 rows/s，RSS 44,932 KB）和 1M server / 1M client（4.437s，约 450,716 rows/s，RSS 422,864 KB），满足 100k < 120s 的 G3 timing 验收。本机 `perf record` 因 `perf_event_paranoid=4` 被拒，且未安装 `cargo flamegraph`，所以 top-3 CPU hotspot 证据仍保留为 operator profiling follow-up；剩余 block 数暂不下调。

2026-05-08 进展：G8 已完成本地 benchmark 验收。`serve_operator_dashboard.py` 在默认 `--max-concurrent-jobs-per-tenant=0` 时保留 single-active-job 行为；显式设置正数 quota 时可在 in-memory `jobs` registry 中跟踪多个 active jobs，并按 job ID 返回 start response，修复并发 start 时读取最新 `current_job` 导致回包 job_id 错乱的问题。新增 `scripts/benchmark_dashboard_jobs.py` 与 `dashboard_jobs_benchmark/v1`，默认 contract smoke 校验 synthetic fixture。实际本地 G8 run：5 concurrent starts 全部 accepted、start p95 12.360ms、10 次 `/v1/dashboard` 读取 p95 4.781ms、tracemalloc retained memory 47.681 KB/job，满足 dashboard p95 < 2s 和无明显 per-job memory leak 验收。剩余 block 数下调 1。

2026-05-08 进展：K2 已完成。新增 `docs/COMPLIANCE_MAPPING.md`，按 GDPR Article 5(1) 的七条原则（合法性/公平/透明、目的限制、数据最小化、准确性、存储限制、完整性与保密、问责）和 Article 15-22 的数据主体权利逐条对应到本仓库的 schema、脚本、迁移与示例配置；§3 显式列出已知限制（无自动 erasure 管线、external audit anchor 默认是 local-file、live identity/authz adapter 是 operator 环境工作、PostgreSQL portability、crypto-shred 流程指引）；§4 给出 reviewer 7 步最小取证路径。Legal/compliance 实际复核仍是 operator-side。剩余 block 数下调 1。

2026-05-08 进展：K3 的 audit-chain tamper-resistance 段已完成 repo-side。新增 `scripts/verify_audit_tamper_resistance.py` 与 `schemas/audit_tamper_resistance.schema.json`：脚本会按 6 个候选位置做单字节 bit flip——audit_chain 中 `correlation_id`、`job_id` 值字节、midfile 字节，audit_seal 中 `artifact_sha256`、`job_id`、可选 `signature` 值字节——断言 `verify_audit_bundle.verify_audit_bundle(...)` 在每个 reachable 场景都抛异常，并在每次变异后立即恢复原始字节；最后做 post-restore SHA-256 baseline 复核以及一次 full re-verify。`scripts/check_json_contracts.sh` 在 seal 完成后调用脚本并断言 `status=ok`、`summary.detected==summary.total>=4`、`post_restore_check` 三项均 true；`scripts/check_ci_smoke.sh` 把脚本加入 py_compile 列表；`config/schema_backcompat_baseline.json` 把 `audit_tamper_resistance/v1` 加入 stable schema 集。HTTP malformed-input gate 扩展和外部 pen test 当时仍开放，因此 K3 不下调，K 类剩余从 4 → 3 主要来自 K2。

2026-05-08 进展：K3 的 HTTP malformed-input gate 已完成 repo-side。新增 `scripts/check_http_malformed_input_gate.py` 与 `schemas/http_malformed_input_gate.schema.json`：脚本默认在 loopback 启 in-process 的 record-recovery HTTP 服务，并跑 10 个攻击 scenario——missing `X-Request-Signature`、过期 `request_timestamp_utc`、未来 `request_timestamp_utc`、SQL-injection-pattern caller/tenant_id/job_id（必须被当作 opaque string）、坏 JSON、非 object JSON、缺 required `candidate_ids`、错误 HTTP method（DELETE）、未知 path、超大 body——每个 scenario 记录 HTTP status、transport_error、response error/reason 字段。`scripts/check_json_contracts.sh` 把它接入默认 contract smoke 并断言 `summary.status=ok` / `summary.detected==summary.total>=8` 以及必要 scenario 名集；`scripts/check_ci_smoke.sh` 把脚本加入 py_compile；`config/schema_backcompat_baseline.json` 把 `http_malformed_input_gate/v1` 加入 stable schema 集。本地 in-process run 跑通：10/10 scenario 全部 detected，oversized body 在 400 被拒，wrong method 返回 501，unknown path 返回 404。外部 pen testing 仍是 operator-side，因此 K3 仍按 1 个 block 计入剩余（与 F1-b 把 operator 环境执行计入同一口径），K 类剩余从 4 → 3 主要来自 K2。

2026-05-08 进展：G6 已完成本地 benchmark 验收。新增 `scripts/benchmark_mtls_overhead.py` 与 `schemas/recovery_mtls_benchmark.schema.json`：脚本会在 loopback 起两份 in-process record-recovery HTTP 服务（一份 plaintext、一份用 `scripts/issue_mtls_certs.py` 生成的 mock 证书做 mTLS），用 `http.client.HTTPConnection` / `HTTPSConnection` 直连，分别在 fresh-connection 与 persistent-connection 两种连接模式下打 N 次 `/health` 测延迟，输出每对 (transport, connection_mode) 的 p50/p95/min/mean/max 和原始结果，并计算 mTLS fresh/persistent overhead p95、keep-alive savings p95，自动判断是否触发 50ms 警戒值。默认 contract smoke 跑 5 iterations × 4 transport-mode = 20 个请求并断言 status=ok / 全部成功 / 四个 transport-mode 组合都出现；`scripts/check_ci_smoke.sh` 加入 py_compile，`config/schema_backcompat_baseline.json` 加入 stable schema 集。本地 5 iter loopback 测得：plain HTTP fresh p95 ≈ 0.62ms、plain HTTP persistent p95 ≈ 0.52ms、mTLS fresh p95 ≈ 2.25ms、mTLS persistent p95 ≈ 2.07ms；mTLS fresh-connection overhead p95 ≈ 1.6ms（远低于 50ms 警戒值），keep-alive 在 mTLS p95 上节省 0.18ms。剩余 block 数下调 1（G 类 6 → 5）。

2026-05-08 进展：I2-a + I2-b alerting integration 同步完成 repo-side。

- **I2-a（webhook adapter）**：`scripts/check_observability_alerts.py` 新增 `--webhook-url` / `--webhook-format slack|alertmanager` / `--webhook-bearer-env` / `--webhook-timeout-sec` / `--webhook-include-resolved` / `--require-webhook-ok`。Slack 格式输出 `{"text": "..."}` 列出每条 firing alert 的 severity / message / triage；Alertmanager 格式输出 `[{"labels": {alertname, severity, service, job_id?, tenant_id?, correlation_id?}, "annotations": {summary, description, triage_path}, "startsAt"}]` 数组（每条 firing alert 一项）。结果写入 `observability_alert_report/v1` 的可选 `webhook_dispatch` block；loopback URL 自动 bypass 系统 HTTP proxy；零 firing alert 时默认 skip 通知。
- **I2-b（alert daemon）**：`scripts/run_alert_check_daemon.py` 在轮询循环中跟踪每个 `alert_id` 的上一轮 firing 状态，计算 `unknown→firing` / `firing→resolved` / `resolved→firing` 三类 transition，每轮写一条 JSONL `alert_daemon_heartbeat/v1`；新增 `schemas/alert_daemon_heartbeat.schema.json`。Webhook dispatch 默认按 transition 触发；`--webhook-include-resolved` 显式发已恢复通知；`--webhook-always` 用于 debug；`--max-iterations N` 支持 cron one-shot；SIGINT/SIGTERM 干净退出。
- **I2 smoke 接入**：新增 `scripts/check_alert_webhook_smoke.py`，启用 in-process loopback HTTP receiver、跑 Slack + Alertmanager 两种 format、跑 daemon 两次迭代并在中途 flip dashboard，断言 dispatch.ok / status_code=200 / 两 schema 通过 / `firing→resolved` transition 写到 heartbeat JSONL。默认 contract smoke 调用它。
- 验收对照 [`docs/PRODUCTION_READINESS_GUIDEBOOK.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PRODUCTION_READINESS_GUIDEBOOK.md) §6.I2 的三条 acceptance 全部通过。
- backcompat baseline 同步从 117 → 118 schemas，0 fail。CI smoke + JSON contract smoke 全绿；replay 仍 `intersection_size=2 / intersection_sum=425`（file mode + FIFO mode）。

剩余 block 从 15 → 13（~75h → ~65h）；I 类从 4 → 2。随后 I3-a 与 I3-b 均已在 2026-05-08 完成，当前 I 类 repo-side 剩余为 0。

2026-05-08 进展：I3-a request submission form 已完成 repo-side。

- `serve_operator_dashboard.py` 新增 `POST /v1/request/submit`，接受 inline `query_workflow_request/v1` 或 `{request: ...}` body，支持 `X-Request-Base-Dir` 路径解析，按现有 `api_identity_resolution/v1` bearer-token 路径绑定 caller/tenant/dataset/service scope。
- 新增 `migrations/metadata/012_add_workflow_submissions.sql` 和 Postgres DDL parity：`workflow_submissions` 存储 `pending_approval` 请求，`control_plane_mutations` 记录 `submit_request`。
- 新增 `schemas/operator_request_submission.schema.json`（`operator_request_submission/v1`）与 backcompat baseline entry；contract smoke 运行 `scripts/check_operator_request_submission_smoke.py`，验证 HTTP 202、schema、DB row 和 mutation row。
- `config/operator_console/console_manifest.json` 新增 `requests` section 和 `approval_workflow` feature flag；`render_operator_console_manifest.py` 与 contract smoke 现在断言 9 个 section。

剩余 block 从 13 → 12（~65h → ~60h）；I 类从 2 → 1。随后 I3-b 已完成，当前 I 类 repo-side 剩余为 0。

2026-05-08 进展：I3-b approval / reject / pending request list workflow 已完成 repo-side。

- `serve_operator_dashboard.py` 新增 `GET /v1/requests`、`GET /v1/requests/{submission_id}`、`POST /v1/request/{submission_id}/approve`、`POST /v1/request/{submission_id}/reject`；审批要求 `privacy_operator` 或 `platform_admin`，拒绝要求 `privacy_operator` / `platform_admin` / `compliance_auditor`，同一 resolved caller submit→approve 返回 HTTP 403 `same_identity_self_approval`。
- `workflow_submissions` 新增 approval/rejection 字段并同步 Postgres DDL；每次 approve/reject 都写 `control_plane_mutations`，审批提交前先预留 dashboard job slot，提交后复用现有 job launch path 启动 approved request。
- 新增 `schemas/operator_request_submission_list.schema.json`；`operator_request_submission/v1` 扩展 approval/rejection/detail/job_control 字段；`scripts/check_operator_request_submission_smoke.py` 现在覆盖 submit、list、detail、same-identity deny、approve-starts-job、reject-with-reason 和 mutation rows。
- `scripts/check_json_contracts.sh` 校验 pending/list/detail/approve/reject 五个 I3 样本；`config/operator_console/console_manifest.json` 的 requests section 纳入 submit/list/detail/approve/reject endpoints。

剩余 block 从 12 → 11（~60h → ~55h）；I 类从 1 → 0。下一步建议回到 F1-b、G3 hotspot/G4/G5、J2-b、K1 或 K3 external pen test。

2026-05-08 进展：K1-a S3 Object Lock (WORM) 外部审计 anchor sink 已完成 repo-side。

- `scripts/publish_external_audit_anchor.py` 新增 `--sink-kind file_ledger|s3_worm`（默认 `file_ledger`，旧路径不变）、`--object-lock-mode COMPLIANCE|GOVERNANCE`（默认 `COMPLIANCE`）、`--retain-days <int>`（默认 `3650`，10 年 retain-until 视野）、`--execute`（默认不上传，仅在显式 `--execute` 时调用 boto3）。
- `--external-ledger` 在 `--sink-kind=s3_worm` 时接受 `s3://bucket/key.jsonl`，H3-b 引入的租户路径校验扩展到 S3 key path segments：`--tenant-id contract-tenant` 指向 `s3://bucket/audit/other-tenant/ledger.jsonl` 时在调用 boto3 之前就被拒绝。
- s3_worm sink 复用与 file_ledger 相同的 `render_ledger_lines()`（两路径生成的 `external_audit_anchor_ledger/v1` 字节完全一致），先 `get_object`（捕获 `NoSuchKey`）读已有 ledger 内容、追加新 anchor 行，然后 `put_object` 时同时设置 `ObjectLockMode=<mode>` 和 `ObjectLockRetainUntilDate=<retain_until_utc>`；不带 `--execute` 时 sink 停留在 `s3_object_lock.status=planned` 并写 `executed=false`，默认 contract smoke 与 operator dry-run 不需要 AWS 凭证。
- `external_audit_anchor_report/v1` 新增可选 `external_sink.s3_object_lock`（`bucket` / `key` / `object_lock_mode` / `retain_until_utc` / `retain_days` / `executed` / `status` ∈ `planned|uploaded|skipped|error` / `details` / `etag` / `version_id` / `previous_object_etag`）；`external_sink.kind` enum 扩展为 `["file_ledger", "s3_worm"]`；`additionalProperties: false` 仍保持，`stable_properties` baseline 无需调整（新字段都是 optional）。
- `scripts/check_json_contracts.sh` 新增 K1-a 两条断言：(a) planned-mode `s3://seccomp-audit-archive/audit/contract-tenant/ledger.jsonl` 跑通、schema 通过、`kind=s3_worm`、`bucket/key`、`object_lock_mode=COMPLIANCE`、`retain_days=3650`、`retain_until_utc.endswith("Z")`、`executed=false`、`status=planned`、`summary.published_count=0`、`records[*].published=false`；(b) cross-tenant S3 key 在 `--tenant-id contract-tenant` 指向 `…/other-tenant/…` 时 exit 非 0。`scripts/check_ci_smoke.sh` 已经把脚本列入 py_compile，无需额外接入。
- 验证：`bash scripts/check_json_contracts.sh` ✓（120 schemas / 0 fail）；`scripts/check_schema_backcompat.py` ✓；本地多模式手工 smoke 跑通 planned / file_ledger 兼容 / dry-run + s3_worm（status=skipped）/ cross-tenant reject 五条路径。Live AWS Object Lock execute 仍属 operator 环境，比照 F1-b。

剩余 block 从 11 → 10（~55h → ~50h）；K 类从 3 → 2。下一步建议回到 F1-b、G3 hotspot/G4/G5、J2-b、K1-b（Sigstore/Rekor）或 K3 external pen test。

2026-05-08 进展：K1-b Sigstore Rekor 透明日志外部审计 anchor sink 已完成 repo-side。

- `scripts/publish_external_audit_anchor.py` 新增 `--sink-kind rekor`（与 `file_ledger` / `s3_worm` 共用 `--external-ledger` 与 `--execute` framework）、`--rekor-signing-key-env <env>`（PEM 编码的 ECDSA P-256 / `secp256r1` 私钥 env）、`--rekor-timeout-sec`（HTTP 超时，默认 10s）。
- Rekor URL 解析仅接受 `http://` / `https://`（其他 scheme 在签名/HTTP 之前直接拒绝）。Tenant 校验沿用 `verify_anchor_records` 的 record-level enforcement，不要求把 tenant 段写到 Rekor URL（透明日志 URL 是公共端点）。
- 不带 `--execute` 时 sink 停留在 `status=planned`、`executed=false`、`submitted_count=0`、`entries=[]`，默认 contract smoke 与 operator dry-run 不需要网络也不需要密钥。
- 带 `--execute` 时：对每条 anchor record 计算 canonical bytes `b"entry_sha256:<hex>\n"`，用 operator 提供的 ECDSA-P256 私钥做 ECDSA-SHA256 签名，从私钥派生对应 SubjectPublicKeyInfo PEM，按 `hashedrekord/0.0.1` 规格 POST 到 `<rekor>/api/v1/log/entries`；解析回包的 first entry 的 uuid + `logIndex` + `integratedTime`，每条 record 只在 2xx 响应时把 `published` 标 `true`。
- `external_audit_anchor_report/v1` 新增可选 `external_sink.rekor_transparency_log`（`endpoint_url` / `endpoint_path` / `kind_version` / `signature_algorithm` / `executed` / `status` ∈ `planned|uploaded|partial|skipped|error` / `details` / `submitted_count` / `uploaded_count` / `entries[]`，每条 entry 包含 `entry_sha256`/`payload_sha256`/`uuid`/`log_index`/`integrated_time`/`status`/`details`）；`external_sink.kind` enum 扩展为 `["file_ledger", "s3_worm", "rekor"]`，与 K1-a 的 `s3_object_lock` 互为兄弟字段。
- top-level `summary.status` 仅在 rekor 块 `status=error` 时降为 `fail`；`partial`（部分上传）不降级，便于 operator 重试。
- `scripts/check_json_contracts.sh` 新增 K1-b 两条断言：(a) planned-mode `https://rekor.sigstore.dev` smoke 跑通、schema 通过、`kind=rekor`、`endpoint_url`、`endpoint_path=/api/v1/log/entries`、`kind_version=hashedrekord/0.0.1`、`signature_algorithm=ecdsa-p256-sha256`、`executed=false`、`status=planned`、`submitted_count=0`、`uploaded_count=0`、`entries=[]`、`summary.published_count=0`、`records[*].published=false`；(b) 非 `http(s)` Rekor URL（`ftp://...`）必须 exit 非 0。`scripts/check_ci_smoke.sh` 已经把脚本列入 py_compile，无需额外接入。
- 本地端到端验证：用 `cryptography` 现场生成 ECDSA-P256 keypair、起 in-process loopback HTTP receiver 用同一公钥重算 canonical bytes 并 server-side 验签；2 条 anchor records → 2 次 POST → 2 次 201 → `submitted_count=2`、`uploaded_count=2`、`status=uploaded`、`summary.published_count=2`、所有 `records[*].published=true`。证明 `--execute` live path 正确，无需依赖公网 Rekor。
- 验证：`bash scripts/check_json_contracts.sh` ✓（120 schemas / 0 fail）；`scripts/check_schema_backcompat.py` ✓；`bash scripts/check_ci_smoke.sh` ✓（仍 `intersection_size=2 / intersection_sum=425`）。Live Rekor submission 仍属 operator 环境（需要长期 ECDSA 密钥托管 + 公网 Rekor 接入）。

剩余 block 从 10 → 9（~50h → ~45h）；K 类从 2 → 1。下一步建议回到 F1-b、G3 hotspot/G4/G5、J2-b、J4 chaos 或 K3 external pen test。

2026-05-08 进展：J4 chaos and failure-injection 工具链已完成 repo-side。

- 新增 `scripts/run_chaos_test.py` 与 `schemas/chaos_test_report.schema.json`（`chaos_test_report/v1`），覆盖 5 个场景；其中 3 个在 default contract smoke 内 in-process 跑通：
  - `recovery_service_sigkill`：spawn in-process record-recovery HTTP service，先用 `/metrics` 探活（无需 auth），用 `server.shutdown()` + `server_close()` 模拟 SIGKILL 让 listener 撤掉，再发一次 `/metrics`，断言客户端拿到 connection refused / connection reset / 其他干净 transport-level 错误。
  - `mtls_cert_expired`：用 `cryptography` 现场生成 `not_valid_before` 10 天前 / `not_valid_after` 1 天前的 RSA 自签证书，启 in-process TLS listener，client 用 `ssl.create_default_context()` 把同一证书当作 trust anchor 加载（即排除 unknown-CA 干扰），断言握手前抛 `ssl.SSLCertVerificationError`（或 SSLError）。注意 `_ExpiredCertHTTPSServer` 的内部 Event 字段必须避开 `_stop` 名字以免与 `threading.Thread._stop` 冲突。
  - `audit_archive_unwritable`：用 `seal_audit_artifact.py --input/--out/--job-id` 合成真实的 `audit_chain.json` + `audit_chain.seal.json`，对 archive dir `chmod 0`，subprocess 调 `archive_audit_bundle.py`，断言非 0 退出 + dir 内容前后一致 + 源 chain SHA-256 不变。
- 另外 2 个属于 operator-environment 场景，恒定输出 `status=skipped`、`injection_method=operator_environment_only`：
  - `postgres_primary_killed`：依赖 Patroni cluster；live drill 与 J2-b 走同一 OPS_RUNBOOK 章节。
  - `audit_log_path_full`：依赖 quota-bounded 文件系统；in-process 模拟会污染 host。
- `summary.status` 在任意 in-process 场景失败或检测到 audit chain 损坏时降为 `fail`；skipped 不影响 ok 状态。
- `scripts/check_json_contracts.sh` 用 `--scenarios all --assert-ok` 跑全套，校验 schema、`summary.status=ok`、`total=5`、`ok=3`、`skipped=2`、`audit_chain_corruptions=0`、`expected_pattern_matched=3`，并断言 3 个 in-process 场景的 observed_failure_mode 落在受控集合内（`connection_refused/connection_error/transport_error/url_error`、`certificate_expired/certificate_verify_failed/ssl_error`、`archive_dir_unwritable`）。
- `scripts/check_ci_smoke.sh` 把 `scripts/run_chaos_test.py` 加入 py_compile；`config/schema_backcompat_baseline.json` 注册 `chaos_test_report/v1` 为 stable schema。
- 验证：`bash scripts/check_json_contracts.sh` ✓（121 schemas / 0 fail）；`scripts/check_schema_backcompat.py` ✓；`bash scripts/check_ci_smoke.sh` ✓（仍 `intersection_size=2 / intersection_sum=425`）。
- live `postgres_primary_killed` 与 `audit_log_path_full` 的实际复演归 operator 环境，沿用 OPS_RUNBOOK §J4 chaos drills 章节。

剩余 block 从 9 → 8（~45h → ~40h）；J 类从 2 → 1。下一步建议聚焦 F1-b、G3 hotspot/G4/G5、J2-b 或 K3 external pen test。

2026-05-08 进展：G5 end-to-end pipeline latency SLO 的 repo-side runner/contract 已完成，但不下调剩余 block。新增 `scripts/benchmark_pipeline_slo.py` 与 `schemas/pipeline_slo_benchmark.schema.json`：脚本生成 deterministic 10k/10k/1k-overlap JSONL fixture，自动推导 `expected_intersection_size` / `expected_intersection_sum`，复用现有 `run_sse_bridge_pipeline.sh` file-handoff 路径，成功后读取 `pipeline_observability/v1` 的核心 stage `duration_ms`，按 G5 SLO 表输出 per-stage 与 total-pipeline 的 p50/p95/3×p95 判定；失败时保留 stdout/stderr tail 方便定位。`benchmark_smoke.py --target pipeline-slo --scale <n>` 已接入显式入口；默认 contract smoke 走 `--fixture-only` 校验 10k SLO report contract，不执行重型 pipeline；`config/schema_backcompat_baseline.json` 注册 `pipeline_slo_benchmark/v1` 为 stable schema。G5 的最终 10k live timing 仍需要在装好 SSE Python dependencies 与 PJC binaries 的标准 runtime 环境补跑，因此 G 类剩余仍按 5 blocks 统计。

2026-05-08 进展：G4 PJC/APSI profiling 的 repo-side scale runner/contract 已完成，但不下调剩余 block。`scripts/benchmark_pjc.py --mode generated_scale_csv` 现在可按 `--server-items` / `--client-items` / `--overlap` 生成 deterministic PJC CSV fixture，自动推导 expected intersection metrics，并在 real run 时通过 `/usr/bin/time -v` 记录 `peak_rss_kb`；`pjc_benchmark/v1` 增加 per-mode `scale` 元数据，`benchmark_smoke.py --target pjc-scale --scale <n>` 已接入显式 operator 入口；默认 contract smoke 校验 synthetic generated-scale row。G4-a/G4-b 的 100k/1M 实测 timing、memory ceiling、connection reuse 仍需要在装好 PJC binaries 的标准 runtime 环境补跑，因此 G 类剩余仍按 5 blocks 统计。

2026-05-09 进展：F1-b 与 G7 已完成本地 live PostgreSQL 验收，剩余 block 从 8 → 6。F1-b 使用临时 PostgreSQL 16.13 Unix-socket cluster 跑通 `scripts/check_metadata_schema_portability.py --db-dsn ... --smoke-out-base tmp/sse_bridge_pipeline_demo --smoke-job-id sse_demo_job`：12/12 metadata migrations、35 tables、116 indexes、`postgres_live_import_query_smoke` 查询 `sse_demo_job` 为 `released`，6 个 stage-status rows、2 个 audit events。过程中修复了真实 PostgreSQL 兼容问题：OpenFGA tuple 表的裸列名 `user` 在 PostgreSQL 中与保留字冲突，现由 `scripts/metadata_db.py` 的 PostgreSQL compatibility layer 自动 quote，不改变 SQLite schema 或 OpenFGA JSON 字段语义。G7 新增 `scripts/compare_read_adapter_backends.py` 与 `schemas/read_adapter_backend_comparison.schema.json`，并完成 live SQLite/PostgreSQL 对比：16/16 modes compared，`metadata_http_job` p95 SQLite 18.078ms vs PostgreSQL 22.425ms，ratio 1.24 < 2.0，`missing_indexes_required=false`。

2026-05-09 进展：G3 Bridge Binary Profiling 已完成整块 repo-side 验收，剩余 block 从 6 → 5，G 类从 4 → 3。`bridge/src/main.rs` 的 `prepare-job` 审计现在输出 `phase_timings_ms`，覆盖 row loading、server/client token generation、CSV writes、job-meta writes 与 artifact hash/canonicalize；`scripts/benchmark_bridge.py` 会从成功迭代的 phase timings 汇总 `profile.method=bridge_internal_phase_timing` 与 top-3 hotspots，`bridge_benchmark/v1` schema 和 benchmark smoke fixture/semantic check 已同步。重建 release binary 后本地跑通 100k/100k：0.374s、535,411 rows/s、RSS 44,700 KB，top-3 为 `load_server_rows` 25.141%、`load_client_rows` 24.859%、`build_client_values` 16.949%；1M/1M：4.739s、422,011 rows/s、RSS 422,780 KB，top-3 为 `build_client_values` 24.688%、`build_server_tokens` 20.874%、`load_client_rows` 19.402%。`perf` / flamegraph 的 symbol-level 栈仍可作为 operator 环境补充材料，但不再计入当前生产就绪剩余 block。

2026-05-09 进展：G4-a / G4-b / G5 已完成本地 measured benchmark 验收，剩余 block 从 4 → 1，G 类从 3 → 0。

- **G4-a (PJC 100k 验收)**：`scripts/benchmark_pjc.py --mode generated_scale_csv --server-items 100000 --client-items 100000 --overlap 0.2 --iterations 1 --timeout-sec 1800` 跑通 `a-psi/private-join-and-compute/bazel-bin/private_join_and_compute/{server,client}` real binary，`intersection_size=20000`、`intersection_sum=202010000`、wall time **222.02s** ✓ < 300s SLO（约 26% 余量）、peak RSS 260.8 MB。同时记录了 1k/10k 段的 baseline：1k=10.72s/13.9MB、10k=32.82s/38.4MB；scaling 表已写入 `docs/PRODUCTION_READINESS_GUIDEBOOK.md` §G4。
- **G4-b (memory ceiling + connection reuse)**：`scripts/benchmark_pjc.py --mode generated_scale_csv --server-items 10000 --client-items 10000 --overlap 0.2 --iterations 3` 跑了三轮 back-to-back PJC server+client 生命周期，每轮 `intersection_size=2000`、`intersection_sum=2,201,000`、exit_code=0，per-iter dur 47.0s/28.8s/36.6s（首轮 cold-start，后两轮 OS cache 暖），peak RSS 36-39 MB 稳定无 leak；100k peak RSS 260.8 MB 表明 server 持单倍候选集而非双缓冲。1M×1M live measurement 收口：33.68 min wall time、peak RSS 2,250,084 KB ≈ **2.20 GB**、`exit_code=1`（PJC 客户端超过 `GRPC_MAX_MESSAGE_MB=512` 上限，单机 PJC binary 实测在 100k 与 1M 之间存在边界）、`intersection_size=null` / `intersection_sum=null`（temp dir 已被 benchmark 清理，无 log tail，但 schema 字段确认了失败模式）。`run_pjc.sh` 每轮 spawn / teardown server，"connection reuse" 在当前 PJC binary 下指 runner 可重入、log/work dir 不冲突；真正的 gRPC 连接持久化与 1M 级生产部署属 server 重构 / grpc tuning 范畴（已在 `docs/POST_BASELINE_ROADMAP.md`）。
- **G5 (10k pipeline SLO 验收)**：`BRIDGE_BIN=$(pwd)/bridge/target/release/bridge python3 scripts/benchmark_pipeline_slo.py --server-rows 10000 --client-rows 10000 --overlap-count 1000 --output tmp/pipeline_slo_10k.json --timeout-sec 600 --assert-ok` 跑通 file-handoff 全链路，total **34,909 ms** ✓ < 90s p50 / 180s p95 SLO（38% 预算）；per-stage：sse_export 48ms / record_recovery `not_applicable`（JSONL fixture 不经过加密 record store，已在 schema 中加 `not_applicable` 状态以正确表达 stage 缺席）/ bridge_prepare_job 13ms / pjc 33,878ms / policy_release 0ms；`intersection_size=1000` / `intersection_sum=599500`、`mainline_contract_check_embedded=true`、`handoff_cleanup` 双侧 `cleaned`。SLO benchmark 现在自动用 `export_observability_events.py --audit-chain` 派生 `pipeline_observability/v1`（12 events），不再依赖 pipeline 直接写盘。
- **Schema 更新**：`schemas/pipeline_slo_benchmark.schema.json` `stage.status` enum 新增 `not_applicable`，summary 新增 `not_applicable_stages`，`validation` 新增 `handoff_cleanup_*` 四字段；`scripts/benchmark_pipeline_slo.py` 在 mainline contract check 之后自动渲染 `pipeline_observability.json`。`config/schema_backcompat_baseline.json` 仍 125 schemas / 0 fail（schema property 是 additive 扩展，未触发 backcompat 失败）。
- **下一步建议**：剩余只有 K3 external pen test，详细资源清单见 `docs/PRODUCTION_READINESS_GUIDEBOOK.md` §K3 + 上一轮 K3 资源 Q&A 记录。

2026-05-09 进展：J2-b PostgreSQL Patroni failover 的 repo-side 脚手架已完成，剩余 block 从 5 → 4，J 类从 1 → 0。`scripts/metadata_db.py` 的 `connect_db_with_retry` / `connect_read_db_with_retry` 已是退避重试的现成入口；新增 `scripts/test_metadata_db_failover.py` 与 `schemas/metadata_db_failover_test.schema.json`：脚本默认在 in-process 模式下用一个 fresh SQLite metadata DB + 自动 tmp 工作目录跑完整链路——apply_migrations、插入一条预先 `jobs` 行、读基线、把 `metadata_db.connect_db` 临时打补丁让前 `--simulated-failure-count` 次调用抛 `SimulatedOperationalError`、再用 `connect_db_with_retry` 在 `--retry-attempts-allowed` / `--retry-base-delay-seconds` / `--failover-target-seconds` 预算内复连、插入第二条 `jobs` 行，最后用一条全新读连接确认两行都在并 `data_round_trip_ok=true`。`scripts/check_json_contracts.sh` 在 J2-a 之后立即跑该脚本（`--simulated-failure-count 2 --retry-attempts-allowed 4 --failover-target-seconds 30`），断言 `status=ok`、`configuration.simulation_mode=in_process_simulated`、`failover_request.primary_attempt_failed=true`、`failover_request.actual_attempts_used >= 3`、`failover_request.within_failover_target=true`、`post_failover_query.data_round_trip_ok=true`、`data_integrity.no_data_lost=true`、`errors=[]`；`scripts/check_ci_smoke.sh` 把脚本加入 py_compile 列表；`config/schema_backcompat_baseline.json` 把 `metadata_db_failover_test/v1` 加入 stable schema 集（124 → 125 schemas / 0 fail）。本地默认 smoke 跑通：模拟 2 次 transient failure 时实际重试 3 次、wall time ≈ 150ms（远低于 30s 目标）；live Patroni switchover 仍属 operator 环境工作（`--db-dsn` 透传到 `connect_db_with_retry` 的同一路径）。

2026-05-08 进展：Track-E1 / Track-E2 / Track-E3 e-commerce 平台叙事三块同步完成 repo-side。

- **Track-E1（fact-layer baseline）**：`docs/ECOMMERCE_FACT_LAYER_PLAN.md` 已落基线，`migrations/metadata/010_add_ecommerce_fact_tables.sql` 新增六张事实表（`orders` / `order_items` / `order_attribution` / `order_payment` / `order_fulfillment` / `customer_service_interactions`），`migrations/postgres/001_init.sql` 同步对齐，新增 `scripts/render_ecommerce_fact_layer.py` 与 `schemas/ecommerce_fact_layer_report.schema.json`。默认 contract smoke 渲染并校验 `ecommerce_fact_layer_report/v1`，断言六表全在、indexes 总数 ≥ 12。
- **Track-E2（业务身份基线）**：`docs/ECOMMERCE_ACCESS_MODEL.md` 新增 Track-E2 章节，`migrations/metadata/011_add_business_identities.sql` 新增 `business_identities` 表（`identity_kind` 受控集合 `buyer` / `merchant_staff` / `customer_service_agent` / `courier` / `field_marketer`）；表结构刻意 PII-free，不引入新的 stage gate，不破坏已冻结的 `caller_permissions` schema；Postgres DDL 同步对齐。
- **Track-E3（operator console 基线）**：`docs/OPERATOR_CONSOLE_PRODUCT_PLAN.md` 落基线；`config/operator_console/console_manifest.json`（`console_manifest/v1`，I3-b 后为 9 个 section、31 个 endpoint、7 个 platform_role）和 `config/operator_console/index.html` 静态占位页（运行时 fetch manifest），`schemas/console_manifest.schema.json`、`schemas/operator_console_manifest_report.schema.json`，`scripts/render_operator_console_manifest.py`。默认 contract smoke 校验 manifest、渲染 `operator_console_manifest_report/v1`、断言 9 个 section 全在、`static_index_references_manifest=true`、`commerce_ops_owner` / `compliance_auditor` / `recovery_service_operator` 三类 role 都在。

backcompat baseline 同步从 114 → 117 schemas，0 fail。CI smoke + JSON contract smoke 全绿；replay 仍 `intersection_size=2 / intersection_sum=425`。Track-E 三块属于"PJC + SSE e-commerce 平台叙事"补完，不计入 §4.1 的生产就绪 block 表，详细对照见 [`docs/PRODUCTION_READINESS_GUIDEBOOK.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PRODUCTION_READINESS_GUIDEBOOK.md) §12 Track-E 表。

2026-05-08 进展：I1-a 与 I1-b 的 repo-side 脚手架均已完成。新增 `config/observability/docker-compose.observability.yml`（Tempo 2.5 + Prometheus 2.55 + Grafana 11，OTLP gRPC 4317 + HTTP 4318，alert-rules.yml mount，datasources / dashboards 自动 provisioning），`config/observability/tempo.yaml`、`config/observability/prometheus.yml`（scrape 复用 J3-a `/metrics`）、`config/observability/grafana-datasources.yaml`（stable UID `seccomp-tempo` / `seccomp-prometheus`）、`config/observability/grafana-dashboards/dashboards.yaml`、以及两份 dashboard JSON：`pipeline-overview.json`（uid `seccomp-pipeline-overview`，包含 per-tenant 请求量/错误率 stat、active jobs、rate-limit denies、recovery service 请求量与延迟 p50/p95、Tempo 后端 pipeline-stage trace 表）和 `recovery-service.json`（uid `seccomp-recovery-service`，按 decision / reason_code 拆分请求率，包含 p50/p95/p99 延迟和 rate_limited / TLS / signature 失败统计）。新增 `scripts/render_observability_topology.py` 与 `schemas/observability_topology_report.schema.json`：脚本会校验 compose 文件包含 tempo/prometheus/grafana、Tempo 同时声明 gRPC 与 HTTP OTLP receiver、Prometheus mount alert-rules.yml、两个 stable datasource UID 都在场、checked-in dashboards 都有 uid/title/panels，并输出 `observability_topology_report/v1`。同时给 `scripts/export_otel_events.py` 增加 `--otlp-endpoint` / `--otlp-bearer-env` / `--otlp-timeout-sec`：会把 spans 包成最小 OTLP/HTTP-JSON ExportTraceServiceRequest 并 POST 到 `<endpoint>/v1/traces`，结果写入 `otel_export_report/v1` 的可选 `otlp_push` 字段（schema 已扩展，backcompat baseline 仍 114 schema / 0 fail）。默认 contract smoke 调用 render 脚本并断言：status=ok、三 service 都在、两 OTLP listener 都在、alert-rules 已 mount、两 datasource 与两 dashboard uid 都在；`scripts/check_ci_smoke.sh` 加入 render 脚本的 py_compile。Live Tempo push 与 Grafana 渲染仍是 operator 环境工作。剩余 block 数下调 2（I 类 6 → 4）。

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
| 2026-05-06 | H2-b 返工：dashboard per-tenant quota 原子化（2026-05-08 G8 扩展） | `scripts/serve_operator_dashboard.py` 新增 `DashboardServer.try_reserve_job()` / `release_reservation()`，统一覆盖 `POST /v1/jobs/start` 与 `POST /v1/jobs/{job_id}/relaunch` 的「检查 + 占位」流程；2026-05-08 G8 又把正数 `--max-concurrent-jobs-per-tenant` 扩展为 in-memory `jobs` registry 多 active job 模式，默认 quota=0 仍保留 single-active 行为；旧的非原子 `tenant_quota_violation` helper 已移除 | 原 H2-b race smoke ✓；G8 5 并发 start 全 accepted、dashboard p95 4.781ms、tracemalloc retained 47.681 KB/job ✓ |
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
