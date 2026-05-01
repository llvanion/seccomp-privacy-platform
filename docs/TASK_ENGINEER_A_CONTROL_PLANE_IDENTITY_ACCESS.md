# 任务书 1：工程师 A 负责的控制面、身份、权限与密钥

## 1. 任务定位

你负责把当前文件和脚本驱动的原型，补成可持久化、可授权、可审计的 control plane。

你不负责隐私计算主链路，不直接修改 `SSE -> record recovery -> bridge -> PJC -> policy release` 的核心语义。

你的第一阶段目标是：

1. PostgreSQL-ready 的元数据模型
2. control-plane API 草案
3. 身份认证接入方案
4. 细粒度授权模型
5. KMS / secret backend 替代方案
6. 从现有运行产物导入数据库

## 2. 任务边界

### 你可以做

1. 设计 `tenants / datasets / services / callers / jobs / policies / audit_events / key_refs` 表。
2. 做 SQLite 或 PostgreSQL 兼容 migration。
3. 做现有 `out-base` 运行产物到数据库的 importer。
4. 做只读 query CLI 或只读 REST API。
5. 给 Keycloak / OpenFGA / Vault 写集成设计和本地 demo compose。
6. 给现有 `caller / tenant_id / dataset_id / service_id` 设计权限映射。

### 你不能做

1. 不能让主链路第一阶段强制依赖数据库。
2. 不能直接改 `bridge/src/main.rs` 的 token contract。
3. 不能直接改 `policy_release.py` 的发布逻辑。
4. 不能把 `caller / tenant_id / dataset_id / service_id` 换成另一套命名。
5. 不能把 mock KMS 替换成 Vault 后改变现有 bridge 调用参数。
6. 不能绕过接口冻结流程直接改 schema 字段含义。

## 3. 推荐技术栈

第一阶段优先用轻量栈：

1. Python 3
2. SQL migration
3. SQLite sidecar
4. PostgreSQL-compatible schema
5. JSON / JSONL importer
6. `argparse`

第二阶段再接入：

1. PostgreSQL
2. PostgREST
3. Keycloak
4. OpenFGA
5. Vault
6. OPA

## 4. 对应 GitHub 库

| 能力 | 推荐项目 | GitHub |
| --- | --- | --- |
| 关系型元数据库 | PostgreSQL | https://github.com/postgres/postgres |
| Postgres 自动 REST API | PostgREST | https://github.com/PostgREST/postgrest |
| 身份认证 / OIDC / service account | Keycloak | https://github.com/keycloak/keycloak |
| 细粒度权限 / ReBAC / Zanzibar-like | OpenFGA | https://github.com/openfga/openfga |
| 通用策略引擎 | OPA | https://github.com/open-policy-agent/opa |
| secrets / transit encryption / KMS facade | Vault | https://github.com/hashicorp/vault |

优先级建议：

1. 先做数据库 schema 和 importer。
2. 再做 PostgREST 只读 API。
3. 再做 Keycloak 登录和 service account 映射。
4. 再做 OpenFGA 权限模型。
5. 最后把 mock KMS 路径抽象到 Vault 或外部 KMS。

## 5. 你需要对齐的稳定字段

数据库和权限模型必须直接复用这些字段：

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

不要自己发明 `account_id`、`project_id`、`workspace_id` 来替代它们。可以新增字段，但不能替换冻结字段。

## 6. 推荐数据库模型

### Registry 表

1. `tenants`
2. `datasets`
3. `services`
4. `callers`
5. `service_bindings`

### Job 表

1. `jobs`
2. `job_stage_status`
3. `job_artifacts`
4. `job_state_transitions`

### Policy 表

1. `policies`
2. `policy_bindings`
3. `caller_permissions`
4. `service_permissions`

### Audit 表

1. `audit_events`
2. `audit_chains`
3. `audit_seals`
4. `key_access_events`
5. `key_lifecycle_events`

### Key 表

1. `key_refs`
2. `key_versions`
3. `key_purposes`
4. `key_rotation_events`

## 7. 现有接口和调用方式

### 初始化已有 sidecar DB

如果当前仓库已经存在 metadata sidecar 脚本，优先复用：

```bash
python3 scripts/init_metadata_db.py --db-path tmp/platform_metadata.db
```

### 导入一次 pipeline 输出

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

### metadata sidecar 生命周期

当前 metadata sidecar 不只是 init/import/query/read-only API，还补了一层最小 lifecycle 管理：

```bash
python3 scripts/manage_metadata_db.py status \
  --db-path tmp/platform_metadata.db

python3 scripts/manage_metadata_db.py backup \
  --db-path tmp/platform_metadata.db \
  --out-path tmp/platform_metadata.backup.db

python3 scripts/manage_metadata_db.py export-json \
  --db-path tmp/platform_metadata.db \
  --out-path tmp/platform_metadata.export.json

python3 scripts/export_authz_tuples.py \
  --db-path tmp/platform_metadata.db \
  --output tmp/platform_authz_tuples.json
```

这层工具仍然是 sidecar-first：

1. 不让主链路变成直接写库
2. 不改 `job_id / caller / tenant_id / dataset_id / service_id` 的冻结语义
3. 只负责 DB 状态、备份、便携导出和关系同步基线

当前 sidecar 已补充一版阶段/事件耗时导入：`job_stage_status.duration_ms` 记录阶段聚合时长，`audit_events.duration_ms` 记录原始审计事件时长；`query_metadata.py --job-id ...` 还会直接返回 `timing_summary`，而列表查询会返回 `stage_duration_summary` / `total_stage_duration_ms`。旧运行若没有这些字段，允许为 `null`。

### 查询某个 caller 的任务

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

当前列表查询还支持 `--stage <name>`，会把结果限制在导入过该 stage 的 jobs，并附带每个 job 的 `matched_stage` 和整批结果的 `stage_summary`，便于直接按阶段查看耗时和状态聚合；进一步加上 `--stage-status <status>` 和 `--stage-sort duration_desc|duration_asc` 后，可以直接做 stage 状态筛选和按阶段耗时排序。新增 `--group-by stage` 后，还能对当前返回 jobs 的所有 stage 产出 `grouped_stage_summary` 聚合视图；新增 `--group-by status` 后，还能直接看 job 级别的 `grouped_status_summary` 状态分布。`--list-entity tenants|datasets|services|callers|policies|policy-bindings|caller-permissions` 现在把导入后的 registry / policy 表也开放为只读查询入口，便于直接检查 scope 实体、policy 绑定和 caller 权限。新增 `--output-format csv|tsv` 后，还能把这些聚合视图和实体列表直接导出成表格文本；新增 `--columns` 和 `--output-file` 后，还能进一步裁字段并直接落盘。

### 本地只读 HTTP API

在 CLI 之外，当前 sidecar 还补了一层非常薄的本地只读 HTTP API，适合后续 UI / SDK / control-plane read adapter 直接复用：

```bash
export SECCOMP_METADATA_API_TOKEN=local-metadata-token
python3 scripts/serve_metadata_api.py \
  --db-path tmp/platform_metadata.db \
  --bind-host 127.0.0.1 \
  --port 18090 \
  --auth-token-env SECCOMP_METADATA_API_TOKEN
```

可用端点：

1. `GET /healthz`
2. `GET /v1/jobs/<job_id>`
3. `GET /v1/jobs?caller=...&tenant_id=...&dataset_id=...&service_id=...&stage=...`
4. `GET /v1/entities/<entity>?...`

其中 `<entity>` 当前支持：

1. `tenants`
2. `datasets`
3. `services`
4. `callers`
5. `policies`
6. `policy-bindings`
7. `caller-permissions`

这个 HTTP API 只读 SQLite metadata sidecar，不回查 SSE / recovery / bridge / PJC 原始数据，也不会让主链路开始依赖数据库。它的 health/success/error envelope 现在已经冻结到 `schemas/metadata_api_*.schema.json`，并纳入默认 contract smoke 与 schema backcompat guard。

### 运行完整 demo 生成可导入产物

```bash
bash scripts/run_live_sse_bridge_demo.sh
```

## 8. 需要读取的现有产物

你第一阶段只读这些文件：

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

## 9. OpenFGA 权限模型草案

第一版权限可以这样映射：

```text
type user
type service_account
type tenant
  relations
    define admin: [user]
    define auditor: [user]
type dataset
  relations
    define owner: [tenant]
    define reader: [user, service_account]
    define recovery_allowed: [service_account]
type privacy_service
  relations
    define operator: [service_account]
    define can_recover: recovery_allowed from dataset
type job
  relations
    define owner: [user, service_account]
    define viewer: [user, service_account]
```

注意：这只是外围授权模型，不改变主链路里已有的 policy release 语义。

当前仓库已经把这条草案落成最小可执行 baseline：

```bash
python3 scripts/export_authz_tuples.py \
  --policy-config sse/config/ecommerce_access_policy.example.json
```

它输出 `authz_tuple_export/v1`，把当前 `caller_permissions` / `policy_bindings` 能表达的 caller、tenant、dataset、service、role 和 capability，同步成一份可供 OpenFGA 或等价 ReBAC 系统消费的 tuple 清单。当前策略是：disabled caller 只保留在 `subjects` 清单里，不进入 active tuples；`service_account` 只在当前 role/profile 基线明确指向 service operator 时才做推断。

## 10. Keycloak 接入草案

Keycloak 只负责身份，不负责隐私发布判断。

建议映射：

1. human user -> `caller`
2. service account -> recovery service / bridge / policy service
3. realm role -> platform admin / auditor / operator
4. token claim -> `tenant_id`
5. client id -> `service_id`

## 11. Vault 接入草案

Vault 第一阶段只替代 secret sourcing，不改变 bridge contract。

现有 bridge 推荐使用：

```bash
--token-secret-env BRIDGE_TOKEN_SECRET
```

Vault adapter 应该把 secret 注入环境变量或临时 in-memory channel，而不是改 bridge CLI。

## 12. 文档交付

你需要补这些文档：

1. `docs/CONTROL_PLANE_SCHEMA.md`
2. `docs/IAM_AUTHZ_INTEGRATION_PLAN.md`
3. `docs/KMS_SECRET_BACKEND_PLAN.md`
4. `docs/change_requests/<topic>.md`，如果你需要改主接口

## 13. 验收标准

完成定义：

1. 可以从零初始化 metadata DB。
2. 可以导入一次现有 pipeline 运行。
3. 可以按 `job_id / caller / tenant_id / dataset_id` 查询。
4. 有 Keycloak / OpenFGA / Vault 的接入方案和边界说明。
5. 没有把主链路改成强依赖数据库。
6. 没有改变任何冻结字段语义。

## 14. 平台级剩余工作量估算

按 [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md) 的统一口径，这条线从“当前 sidecar + 方案文档 + tuple/export baseline”推进到“平台基线版”还需要：

1. `10 blocks`
2. 约 `50h`

这里的平台基线版，重点不是改主链路，而是把现在的 file-backed policy / SQLite sidecar / mock KMS 周边，推进到更像真正 control plane：

1. `2 blocks / 10h`：把现有 metadata schema、migration、导入路径再收成 PostgreSQL-ready baseline，并保留 SQLite 兼容验证。
2. `2 blocks / 10h`：给 metadata/query/audit/platform-health 这些 sidecar API 补统一身份映射入口，不再只靠本地 env token。
3. `3 blocks / 15h`：把 keyring / key-agent / external-KMS 从 mock backend 再推进一档，至少形成 Vault 或外部 KMS adapter 的兼容实现与回归验证。
4. `3 blocks / 15h`：补 control-plane 写侧 ownership，包括 registry / policy / key-ref 的管理入口或导入治理入口，不再只有 post-run read path。

不含：

1. 让主链路强制在线依赖 Keycloak / OpenFGA / Vault。
2. 真正生产级 IAM、HA PostgreSQL、密钥托管集群。
