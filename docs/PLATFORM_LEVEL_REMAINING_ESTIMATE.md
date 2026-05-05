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

## 5. 平台基线之后已完成 block 记录（2026-05-05）

| 完成时间 | Tranche/Block | 入口 | 验证 |
| --- | --- | --- | --- |
| 2026-05-05 | Tranche B / B9-B12（工程师 B）：PJC X-UI control shell + multi-run admin + durable relaunch | `scripts/serve_operator_dashboard.py`（POST /v1/jobs/start + GET /v1/jobs/{id} + GET /v1/jobs/{id}/result + POST /v1/jobs/{id}/relaunch + GET /v1/runs + POST /v1/runs/select），`docs/CONTROL_PANEL_SPEC.md` | loopback smoke ✓，`intersection_size=2` ✓ |
| 2026-05-05 | Tranche A / A1（工程师 A）：issuer-backed identity proxy baseline | `scripts/serve_identity_proxy.py`，`schemas/identity_proxy_health.schema.json`，`config/identity_proxy.example.json`，backcompat baseline entry | `check_ci_smoke.sh` ✓，`check_json_contracts.sh` ✓，schema validation ✓ |
| 2026-05-05 | Tranche A / A2（工程师 A）：OpenFGA tuple sync + check adapter | `scripts/sync_openfga_tuples.py`，`scripts/check_openfga_authz.py`，`schemas/openfga_sync_report.schema.json`，`schemas/openfga_check_result.schema.json`，`migrations/metadata/007_add_openfga_tuples.sql`，Postgres DDL | `check_ci_smoke.sh` ✓，`check_json_contracts.sh` ✓（85 schema 0 fail），Postgres parity ✓ |
| 2026-05-05 | Tranche A / A3（工程师 A）：KMS backend reachability probe | `scripts/check_kms_reachability.py`，`schemas/kms_reachability_report.schema.json` | `check_ci_smoke.sh` ✓，schema validation ✓，ok/degraded/error 三路径验证 ✓ |
| 2026-05-05 | Tranche A / A4（工程师 A）：service identity token lifecycle | `scripts/manage_service_tokens.py`，`schemas/service_token_report.schema.json`，`migrations/metadata/008_add_service_tokens.sql`，Postgres DDL | `check_ci_smoke.sh` ✓（87 schema 0 fail），issue/verify/revoke/list 四路径 schema 通过 ✓ |
| 2026-05-05 | Tranche B / B13（工程师 B）：Grafana/OTel bridge adapter | `scripts/export_otel_events.py`，`schemas/otel_export_report.schema.json` | `check_ci_smoke.sh` ✓，6 spans，schema validation ✓ |
| 2026-05-05 | Tranche B / B14（工程师 B）：operator shell 回归与 handoff | `scripts/verify_operator_shell_regression.py`，`schemas/operator_shell_regression_report.schema.json` | 15/15 checks，8.9s，schema ✓，`check_ci_smoke.sh` ✓（88 schema 0 fail） |

## 7. 使用方式

建议后续所有”公布工作量”统一写成：

1. 本次完成了哪个任务的第几个 `5h block`
2. 该 block 的入口、验证、文档回写位置
3. 剩余 block 数

这样后面的节奏会更清楚，也更方便判断哪个任务已经接近平台级收口。
