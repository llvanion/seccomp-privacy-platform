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

同一入口现在也支持：

```bash
python3 scripts/import_run_metadata.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --db-path tmp/platform_metadata.db \
  --dry-run

python3 scripts/import_run_metadata.py \
  --out-base tmp/run_a \
  --out-base tmp/run_b \
  --out-base-file tmp/run_roots.txt \
  --db-path tmp/platform_metadata.db
```

`--dry-run` 会输出 `metadata_import_report/v1` reconcile report，但不写数据库；多 `--out-base` / `--out-base-file` 则用于批量 replay/import。报告里会标明每个 run 是 `insert` 还是 `replace`，并附带导入前已有 job 及其子表 row count。

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

python3 scripts/manage_metadata_db.py restore \
  --backup-db-path tmp/platform_metadata.backup.db \
  --out-db-path tmp/platform_metadata.restored.db

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

当前 sidecar 已补充一版阶段/事件耗时导入：`job_stage_status.duration_ms` 记录阶段聚合时长，`audit_events.duration_ms` 记录原始审计事件时长；`query_metadata.py --job-id ...` 还会直接返回 `timing_summary`，而列表查询会返回 `stage_duration_summary` / `total_stage_duration_ms`。旧运行若没有这些字段，允许为 `null`。同一层 importer 现在也支持 dry-run reconcile、replace replay 和 batch replay，`metadata_import_report/v1` 会固定输出 `summary`、逐 run `action=insert|replace`、导入前 `existing_job.row_counts` 以及 apply 后 `job_state_after`。

围绕 PostgreSQL-ready baseline，metadata sidecar 现在还补了一条 DDL portability gate：

```bash
python3 scripts/check_metadata_schema_portability.py \
  --output tmp/platform_metadata_schema_portability.json
```

它会重放 metadata migrations，并检查 migration SQL 中是否还残留 SQLite-only `PRAGMA` / `AUTOINCREMENT`，同时验证关键索引、主键、外键目标、`*_utc` 与 `*_json` 列类型约束。当前 metadata DDL 已把这些 SQLite-only 关键字从 `001_init.sql` 收走。

当前 sidecar 还新增了一条“统一身份映射”的最小基线：

```bash
python3 scripts/manage_metadata_db.py apply-registry \
  --db-path tmp/platform_metadata.db \
  --manifest config/metadata_registry.example.json

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --list-entity caller-identities \
  --caller recovery_ops_demo
```

这一层会把外部主体和本地 `caller` 绑定到 `caller_identities` 表，当前字段包括：

1. `caller`
2. `issuer`
3. `subject`
4. `subject_type`
5. `service_id`
6. `platform_roles`
7. `enabled`

它的作用是先给后续 Keycloak / service account / API bearer token 解析留一个稳定落点，而不是继续只靠 `caller_permissions` 反推主体类型。

围绕 key / secret backend 的 control-plane 写侧，当前 sidecar 也已经补了一条最小 key registry 基线：

```bash
python3 scripts/manage_metadata_db.py apply-registry \
  --db-path tmp/platform_metadata.db \
  --manifest config/metadata_registry.example.json

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --list-entity key-refs \
  --service-id orders-recovery

python3 scripts/query_metadata.py \
  --db-path tmp/platform_metadata.db \
  --list-entity key-versions \
  --key-name bridge-token
```

这一层当前会把不含 secret 的 key metadata 收口到 `key_refs` / `key_versions`，固定：

1. `key_name`
2. `purpose`
3. `service_id`
4. `backend_kind`
5. `backend_ref`
6. `active_version`
7. `allowed_callers`
8. 版本级 `enabled` / `status` / `secret_ref_kind` / `secret_ref_name`

它的边界是：

1. sidecar 只登记 key reference 和 version state，不保存 secret material
2. `manage_keyring.py` / `external_kms_service.py` 仍然是 secret resolver / lifecycle 入口
3. 这给后续 Vault / external KMS adapter 留了一个稳定的 control-plane 映射层

在 API adapter 层，当前还补了一条本地 bearer token 到 `caller_identities` 的绑定路径：

```bash
python3 scripts/serve_metadata_api.py \
  --db-path tmp/platform_metadata.db \
  --identity-token-config config/api_identity_tokens.example.json

python3 scripts/serve_query_workflow_api.py \
  --metadata-db-path tmp/platform_metadata.db \
  --identity-token-config config/api_identity_tokens.example.json

python3 scripts/serve_audit_query_api.py \
  --out-base tmp/completed_run \
  --metadata-db-path tmp/platform_metadata.db \
  --identity-token-config config/api_identity_tokens.example.json

python3 scripts/serve_platform_health_api.py \
  --metadata-db-path tmp/platform_metadata.db \
  --identity-token-config config/api_identity_tokens.example.json
```

这一层不会改主链路 contract，只做：

1. token -> `issuer + subject`
2. `issuer + subject` -> `caller_identities`
3. `caller_identities` -> `caller` / `tenant_id`

这样后续接 Keycloak 或 service account 时，就不是从零开始补 API identity 解析。当前约束也更明确了：

1. metadata/query workflow 可以把身份直接收口到 caller / tenant
2. query workflow 现在还会基于 `caller_permissions` 强制检查 `can_run_bridge` / `can_run_pjc`，并按 `allowed_dataset_ids` / `allowed_service_ids` 自动补齐或拒绝越权 scope
3. audit query 对非特权主体只放行本 caller / tenant 的产物
4. platform health 对 `platform_admin` / `platform_auditor` 仍保留全量 read；`service_operator` 现在也能走 identity 路径，但只允许基于匹配自身 `service_id` 的 `record_recovery_config` 做受限健康探测，不允许顺手读 pipeline / metadata DB / arbitrary recovery endpoint
5. key agent / external KMS 的 read path 也能额外接受 identity bearer token，并把主体绑定回 `caller`
6. record recovery service 现在也支持 `--identity-token-config --metadata-db-path`，统一走 `identity token -> caller -> existing authz policy`
7. external KMS admin 的 rotate / set-status 现在也能走 identity 路径；`platform_admin` 仍可全量管理，`service_operator` 只允许管理 `allowed_callers` 包含自身 caller 的现有 key，并且不能 `create_key`
8. 本地 `scripts/manage_keyring.py` 也已经支持 `--identity-token-env --metadata-db-path --identity-token-config`；`platform_admin` 仍可全量管理，`service_operator` 只允许管理 `allowed_callers` 包含自身 caller 的现有 key，并且不能 `create_key`

如果走统一 client，`scripts/platform_api_client.py` 现在也支持 `--identity-token-env`，可以直接带 identity bearer token 调 metadata / query / audit / platform health 这四类 HTTP adapter。record recovery 的 health probe / manager 侧也补了 `--identity-token-env` / `--record-recovery-identity-auth-env`，因此平台健康和独立 service lifecycle 不会因为转到 identity-only auth 而失明。

在这条最小基线之上，当前又补了 3 个把“统一身份映射”从样例推进到平台边界的入口：

```bash
python3 scripts/resolve_api_identity.py \
  --db-path tmp/platform_metadata.db \
  --identity-token-config config/api_identity_tokens.example.json \
  --bearer-token-env SECCOMP_METADATA_COMMERCE_OPS_TOKEN

python3 scripts/resolve_api_identity.py \
  --db-path tmp/platform_metadata.db \
  --issuer keycloak:commerce \
  --subject user:marketing_analyst

python3 scripts/platform_api_client.py \
  metadata-identity \
  --base-url http://127.0.0.1:18090 \
  --identity-token-env SECCOMP_METADATA_COMMERCE_OPS_TOKEN
```

它们当前固定输出 `api_identity_resolution/v1`，把：

1. `token -> issuer + subject`
2. `issuer + subject -> caller_identities`
3. `caller_identities -> caller / tenant_id / service_id / platform_roles / permission_summary`

收敛成一条单独可验的 control-plane 解析链，而不必每次靠调用某个 sidecar API 才能侧面观察身份绑定是否正确。

围绕 sidecar API authz，这一层当前又补了更明确的统一规则：

1. `serve_metadata_api.py` 新增 `/v1/identity`，可直接返回当前解析后的 `api_identity_resolution/v1`
2. metadata job detail 现在按 `caller + tenant_id` 统一做 scope 绑定，而不是只靠 caller 粗暴拒绝
3. `serve_query_workflow_api.py` 现在把 `dry-run` 和 `execute` 分开：`query_submitter` 可 `dry-run`，但 `execute` 还要求 `privacy_operator` 或 `platform_admin`
4. `serve_audit_query_api.py` 现在把 `include_paths=true` 收紧到 `platform_admin` / `platform_auditor`，普通 caller 即使能读本 tenant 审计产物，也不能顺手拿本地路径细节
5. `serve_platform_health_api.py`、metadata/query/audit 三类 HTTP adapter 现在都复用同一套 bearer-token -> identity resolver，而不再各自散落重复解析逻辑

这一轮默认 contract smoke 已经固定验证：

1. `resolve_api_identity.py` 的 bearer-token 与 subject-lookup 两条解析路径
2. metadata `/v1/identity`
3. metadata 非特权读 `policies` 拒绝
4. query identity `dry-run` 成功、`execute` 因缺 `privacy_operator` 被拒
5. audit identity `include_paths=true` 因缺特权角色被拒
6. platform health 对普通 query caller 的拒绝

围绕 Vault / external KMS 兼容层，这一条线当前也已经不再只是“未来计划”：

1. `keyring/v1` 现支持 `secret_ref.kind=env|vault_kv`
2. 新增 `vault_kv_backend/v1`，由 `schemas/vault_kv_backend.schema.json` 与 `config/vault_kv_backend.example.json` 固定本地 Vault KV 兼容 fixture
3. `scripts/key_agent_service.py --vault-kv-file` 现在能直接解析 `vault_kv` backend 引用
4. `scripts/external_kms_service.py --vault-kv-file` 与 `external_kms_config/v1 auto_start.vault_kv_file` 现在也能解析同一类 backend 引用
5. `scripts/manage_keyring.py rotate --secret-ref-kind vault_kv ...` 与 `scripts/manage_external_kms.py rotate --secret-ref-kind vault_kv ...` 现在都能受控写入 Vault KV 风格的 backend reference，而不再只能写 `secret_env`
6. `scripts/run_sse_bridge_pipeline.sh` 的 external KMS auto-start 也已把 `vault_kv_file` 贯通到实际 service 启动参数

这一层当前默认 contract smoke 已固定验证：

1. vault-backed key agent resolve
2. external KMS 从 env-backed active version rotate 到 vault-backed active version
3. external KMS rotate 后再次 resolve 返回 vault-backed secret
4. keyring / lifecycle audit / client config schema 继续保持兼容

### A5-A6 authority governance 与回归收口（2026-05-05）

当前工程师 A 的 post-baseline 收口已经补了一条统一 operator 视角：

```bash
python3 scripts/check_authority_governance.py \
  --policy-drift tmp/policy_drift_clean.json \
  --key-drift tmp/key_backend_drift_clean.json \
  --identity-resolution tmp/api_identity_resolution_bearer.json \
  --openfga-check tmp/openfga_check_allowed.json \
  --kms-reachability tmp/kms_reachability_authority.json \
  --service-token-report tmp/service_token_verify.json \
  --issuer-rotation tmp/issuer_rotation_dry.json \
  --output tmp/authority_governance_report.json \
  --assert-ok
```

输出 contract 为 `authority_governance_report/v1`，schema 文件是 [authority_governance_report.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/authority_governance_report.schema.json)。

它汇总的不是新权限语义，而是这些既有 authority-source 结果：

1. policy drift：`policy_drift/v1`
2. key backend drift：`key_backend_drift/v1`
3. identity resolution：`api_identity_resolution/v1`
4. OpenFGA-style relation check：`openfga_check_result/v1`
5. KMS/backend reachability：`kms_reachability_report/v1`
6. service-token lifecycle：`service_token_report/v1`
7. issuer credential rotation dry-run：`issuer_credential_rotation/v1`

默认 `scripts/check_json_contracts.sh` 现在会生成上述 fixture 并校验 `authority_governance_report/v1 --assert-ok`。这就是 A5-A6 的回归和 runbook 收口点：operator 不需要分别打开 policy/key/identity/KMS 七份报告，先看 authority governance 汇总，再按 `checks[].source_path` 追到原始报告。

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

当前这层也已经不只依赖“先跑一遍 pipeline 再导入 sidecar”这一路：`scripts/manage_metadata_db.py apply-registry --manifest config/metadata_registry.example.json` 会先把 tenant / dataset / service / caller 注册进 metadata DB，再导入 policy 文件并展开 `policy_bindings` / `caller_permissions`。这意味着后续 OpenFGA / ReBAC 同步可以直接基于显式 control-plane registry 做 dry-run / apply / reconcile，而不是永远等 run importer 带出这些关系。

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

按 [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md) 的统一口径，这条线从”当前 sidecar + 方案文档 + tuple/export baseline”推进到”平台基线版”还需要：

1. `0 blocks`（全部 5 blocks 已完成）
2. 约 `0h`

这里的平台基线版，重点不是改主链路，而是把现在的 file-backed policy / SQLite sidecar / mock KMS 周边，推进到更像真正 control plane：

1. ~~`2 blocks / 10h`：给 metadata/query/audit/platform-health 这些 sidecar API 补统一身份映射入口，不再只靠本地 env token。~~ **已完成（2026-05-03）**：`scripts/api_identity.py` 现提供统一 bearer-token / issuer-subject resolver；`scripts/resolve_api_identity.py` 与 `schemas/api_identity_resolution.schema.json` 固定输出身份解析结果；metadata `/v1/identity`、query execute-vs-dry-run、audit `include_paths`、platform health role gate 也已纳入默认 contract smoke。
2. ~~`3 blocks / 15h`：把 keyring / key-agent / external-KMS 从 mock backend 再推进一档，至少形成 Vault 或外部 KMS adapter 的兼容实现与回归验证。~~ **已完成（2026-05-03）**：`keyring/v1` 现支持 `secret_ref.kind=env|vault_kv`；新增 `vault_kv_backend/v1` 本地兼容 fixture；`key_agent_service.py` / `external_kms_service.py` / `manage_keyring.py` / `manage_external_kms.py` / `run_sse_bridge_pipeline.sh` 已贯通 Vault KV 风格 backend 引用；默认 contract smoke 固定验证 vault-backed resolve 与 rotate。
3. ~~`1 block / 5h`：补 control-plane 写侧 mutation audit trail，让 apply-registry 每次 insert/update 操作都有可查审计记录。~~ **已完成（2026-05-03）**：新增 `migrations/metadata/005_add_mutation_log.sql`（`control_plane_mutations` 表 + 3 个索引）；`manage_metadata_db.py` 增加 `log_mutation()` / `log_entity_mutations()` 函数，在 `apply-registry` 的事务中自动记录所有非 noop 写操作；新增 `scripts/query_mutation_log.py` 与 `schemas/mutation_log_query.schema.json`；`check_json_contracts.sh` 固定验证 apply-registry 后 mutation log 含 ≥13 条记录，覆盖 `insert` 操作、`apply-registry` actor、`policy` + registry entity 类型。
4. ~~`1 block / 5h`：key backend change drift/reconcile。~~ **已完成（2026-05-03）**：`scripts/check_key_backend_drift.py` + `schemas/key_backend_drift.schema.json`；支持 manifest（精确字段对比）和 vault_kv（backend 级语义对比）两种参照源；检测六类漂移（key_ref 缺失/字段漂移/extra，version 缺失/字段漂移/extra）；`--repair` 安全修复 drifted 字段和缺失版本，写入 `control_plane_mutations`；contract smoke 双源全覆盖。
5. ~~`1 block / 5h`：写侧 policy mutation governance。~~ **已完成（2026-05-03）**：`scripts/check_policy_drift.py` + `schemas/policy_drift.schema.json`：sha256 对比 + 误差检测 + `--repair` 重导入并写 mutation log；`scripts/propose_policy_change.py` + `schemas/policy_change_proposal.schema.json`：4 条治理规则（`no_remove_active_bridge_callers` error、`no_remove_enabled_callers` warn、`frozen_field_semantics` error、`caller_count_regression` warn）；支持 `--existing-policy-path` 指定被替换策略，`--apply` 在无 error 时执行并写 mutation log；contract smoke 覆盖 clean drift、unchanged approval、active bridge caller removal blocking。工程师 A 全部 5 blocks 已完成平台基线。
5. ~~`2 blocks / 10h`：把当前本地 token-map / vault-compat baseline 继续推进到更真实的 issuer/claim/proxy 与远端 backend 入口，例如 Keycloak/OIDC claim 映射、service-account issuer 治理、真实 Vault/cloud KMS adapter，以及更统一的长期凭证轮换。~~ **已完成（2026-05-03）**：新增 `migrations/metadata/006_add_issuer_registry.sql`（`issuer_registry` 表，字段 `issuer_type/display_name/service_id/jwks_uri/token_endpoint/claim_mapping_json/trusted_audiences_json`，2 个索引）；`manage_metadata_db.py apply-registry` 现在支持 `issuer_registry` manifest 条目，含 `service_id`、`claim_mapping`、`trusted_audiences`，并纳入 mutation log；`api_identity.py` 现在在 `resolve_identity_record` 中查 issuer_registry 并拒绝 disabled issuer；`scripts/map_oidc_claims.py` + `schemas/oidc_claim_map.schema.json`：解析 HS256 JWT、dotted-path claim 提取（`realm_access.roles`）、audience 校验、issuer registry 查表、configurable claim_mapping；`config/oidc_claim_mapping.example.json` 记录了 Keycloak realm 的标准 claim 映射；`scripts/vault_http_client.py` + `schemas/vault_http_client_result.schema.json`：支持 real（HTTP）+ mock（本地 vault_kv_backend 文件）两种模式，`keyring_lib.py` 新增 `vault_http` 作为 `secret_ref.kind`；`scripts/rotate_issuer_credentials.py` + `schemas/issuer_credential_rotation.schema.json`：按 issuer → service_id → key_refs 路径完成凭证轮换，自动递增版本号、retire 旧版本、写入 mutation log；所有新 schema 已纳入 backcompat baseline，contract smoke 覆盖 OIDC 映射验证、Vault mock get、issuer rotation dry-run。

不含：

1. 让主链路强制在线依赖 Keycloak / OpenFGA / Vault。
2. 真正生产级 IAM、HA PostgreSQL、密钥托管集群。

## 15. 平台基线之后建议

这条线的“平台基线版”已经完成。

如果继续推进，不应再回头重开基线 block，而应直接进入 [POST_BASELINE_ROADMAP.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/POST_BASELINE_ROADMAP.md) 的 `Tranche A`。

建议按下面顺序继续：

1. **`A1` 已完成（2026-05-05）**：issuer-backed identity proxy baseline
   - `scripts/serve_identity_proxy.py`：薄 HTTP 反向代理，在 sidecar API 前统一验证 Bearer token 并注入 `X-Identity-*` headers（Caller / Tenant-Id / Service-Id / Platform-Roles / Resolved）
   - 支持静态 token-map 路径（`--identity-token-config`）和 DB-backed issuer/subject 路径（`--metadata-db-path`）
   - 支持 admin bypass token（`--admin-token-env`）映射到 platform_admin 角色
   - `schemas/identity_proxy_health.schema.json` + `config/identity_proxy.example.json` + backcompat baseline entry
   - `scripts/check_ci_smoke.sh` compile check 已补入
   - 验证：loopback `/healthz` → `identity_proxy_health/v1`，schema 校验通过，`check_json_contracts.sh` 全绿，`check_ci_smoke.sh` 全绿
2. **`A2` 已完成（2026-05-05）**：OpenFGA tuple sync + check adapter
   - `scripts/sync_openfga_tuples.py`：三模式 dry-run / apply / reconcile，从 policy file / metadata DB / 预生成 export 文件同步 tuple 到本地 SQLite tuple store（`openfga_tuples` 表，migration 007）；apply 支持 `--prune`
   - `scripts/check_openfga_authz.py`：直接 tuple 查询（user + relation + object），输出 `openfga_check_result/v1`；支持 `--assert-allowed / --assert-denied` 断言模式
   - `schemas/openfga_sync_report.schema.json` + `schemas/openfga_check_result.schema.json` + `migrations/metadata/007_add_openfga_tuples.sql`
   - Postgres DDL 同步：`migrations/postgres/001_init.sql` 新增 `openfga_tuples` 表（SERIAL/TIMESTAMPTZ，Postgres parity check 通过）
   - 验证：dry-run 33 tuple，apply 写入 33，check allowed/denied 双路径通过，schema 校验，`check_ci_smoke.sh` ✓，`check_json_contracts.sh` ✓，backcompat 85 schema 无 fail
3. **`A3` 已完成（2026-05-05）**：KMS backend reachability probe
   - `scripts/check_kms_reachability.py`：按后端类型（vault_kv_file / vault_http / external_kms_http / keyring_file / env_var）逐项探活，overall_status = ok / degraded / error；支持 `--assert-ok`
   - `schemas/kms_reachability_report.schema.json`：冻结 `kms_reachability_report/v1` contract
   - 验证：已有 fixture 全 ok，未设 env var → error，schema 校验，`check_ci_smoke.sh` ✓
   - 边界：不替代主链路 KMS resolve，只做 pre-flight 可达性探测，不加载 secret material
4. **`A4` 已完成（2026-05-05）**：service identity + token lifecycle
   - `scripts/manage_service_tokens.py`：issue / verify / revoke / list；HMAC-HS256 signed token；`jti` 撤销追踪；`service_token_report/v1` 输出
   - `schemas/service_token_report.schema.json` + `migrations/metadata/008_add_service_tokens.sql` + Postgres DDL `service_tokens` 表
   - 验证：issue → verify ok → revoke → verify revoked 四路径全通；schema 通过；`check_ci_smoke.sh` ✓；backcompat 87 schema 0 fail
5. **`A5` 已完成（2026-05-05）**：policy / key / identity mutation governance 联动
   - `scripts/check_authority_governance.py` 把 policy drift、key drift、issuer rotation、identity resolution 等既有报告收成统一 operator 视图
   - 输出 `authority_governance_report/v1`，schema 已冻结并纳入 backcompat baseline
6. **`A6` 已完成（2026-05-05）**：远端 authority smoke + runbook 收口
   - `check_json_contracts.sh` 现在固定生成 OpenFGA check、KMS reachability、service token issue/verify、identity resolution、issuer rotation dry-run、policy/key drift，再用 authority rollup 做 `--assert-ok`
   - 相关 runbook / IAM / KMS 文档已回写

这条线后续的核心原则仍然不变：

1. 先把 authority source 接到 sidecar / adapter 入口
2. 不把 Keycloak / OpenFGA / Vault 直接变成主链路必需依赖
3. 不重定义冻结字段语义
