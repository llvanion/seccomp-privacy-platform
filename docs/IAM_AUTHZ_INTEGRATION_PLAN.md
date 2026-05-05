# IAM 与授权集成方案

## 1. 目标

这份文档定义 control-plane 身份认证与细粒度授权的第一阶段接入方案。

目标不是重写当前隐私主链路，而是把外围身份和授权补齐，同时保持下面几条不变：

1. 不改变 `caller`、`tenant_id`、`dataset_id`、`service_id` 的语义。
2. 不让 `SSE -> record recovery -> bridge -> PJC -> policy release` 第一阶段强依赖外部 IAM 服务才能运行。
3. 不让通用 IAM/授权系统替代当前 `policy_release.py` 的隐私发布语义。

## 2. 当前基线

当前仓库已经存在一条本地 scope 基线：

1. `sse/config/export_policy.example.json` 以 `caller` 为中心定义 `tenant_id`、`allowed_dataset_ids`、`allowed_service_ids` 和阶段权限。
2. `scripts/validate_pipeline_policy.py`、SSE export 路径和 record recovery service authz 已对齐这些字段语义。
3. `record_recovery_service_config/v1` 已把 `service_id`、`tenant_id`、`dataset_id` 绑定到恢复边界。
4. SQLite metadata sidecar 已能导入 `callers`、`tenants`、`datasets`、`services`、`policies`、`policy_bindings`、`caller_permissions`。
5. `scripts/serve_metadata_api.py`、`scripts/serve_query_workflow_api.py`、`scripts/serve_audit_query_api.py`、`scripts/serve_platform_health_api.py` 已经是天然适合接外层 authn/authz 的 read/write adapter。

当前 sidecar 现在还补了一条 `caller_identities` 基线，通过 `metadata_registry_manifest/v1` 导入外部主体到本地 `caller` 的映射，支持：

1. `issuer`
2. `subject`
3. `subject_type`
4. `service_id`
5. `platform_roles`
6. `enabled`

对应入口：

1. `config/metadata_registry.example.json`
2. `scripts/manage_metadata_db.py apply-registry`
3. `scripts/query_metadata.py --list-entity caller-identities`

针对本地 adapter/API 层，当前还补了一条更接近真实接入前形态的 bearer token 适配：

1. `schemas/api_identity_token_map.schema.json`
2. `config/api_identity_tokens.example.json`
3. `scripts/api_identity.py`
4. `scripts/serve_metadata_api.py --identity-token-config`
5. `scripts/serve_query_workflow_api.py --identity-token-config --metadata-db-path`
6. `scripts/serve_audit_query_api.py --identity-token-config --metadata-db-path`
7. `scripts/serve_platform_health_api.py --identity-token-config --metadata-db-path`
8. `scripts/key_agent_service.py --identity-token-config --metadata-db-path`
9. `scripts/external_kms_service.py --identity-token-config --metadata-db-path`
10. `services/record_recovery/service.py` / `services/record_recovery/http_service.py --identity-token-config --metadata-db-path`

这条路径的语义是：

1. bearer token 先映射到 `issuer + subject`
2. 再通过 `caller_identities` 解析成当前平台里的 `caller`
3. 最后把 `caller` / `tenant_id` 绑定回 metadata query、query workflow request 或 read-service / key-service request

它仍然是本地 demo / adapter-first 基线，不等于真实 OIDC 登录流，但已经把“API token 直接等于平台权限”的粗糙模型推进成了“token -> identity -> caller -> policy”的分层路径。

当前已经落下来的约束是：

1. metadata API 和 query workflow API 会把 identity 绑定回 caller / tenant
2. query workflow API 现在还会从 sidecar 里的 `caller_permissions` 读 `allowed_dataset_ids` / `allowed_service_ids` / `can_*`，对 query submit 做 scope auto-fill 和越权拒绝
3. audit query API 会对非特权主体限制为本 caller / tenant 的 completed-run 产物
4. platform health API 现在对 `platform_admin` / `platform_auditor` 保留全量 read；对 `service_operator` 只开放匹配自身 `service_id` 的 recovery-side health scope，不再是一刀切拒绝
5. key agent / external KMS read path 也可以接受 identity bearer token，再映射回本地 `caller`
6. `scripts/platform_api_client.py` 已支持 `--identity-token-env`，便于用统一 CLI 走这条链路
7. record recovery service 的 unix/http transport 也已经支持 identity bearer token，并继续复用现有 `allowed_callers + authz policy + tenant/service/dataset` 边界
8. external KMS admin 写路径也已经支持 identity：`platform_admin` 可全量管理，`service_operator` 只允许管理 caller 归属到自身的既有 key，且不能 create-key
9. 本地 `scripts/manage_keyring.py` 也已经支持 identity admin：`platform_admin` 可全量管理，`service_operator` 只允许管理 `allowed_callers` 包含自身 caller 的既有 key，且不能 create-key

这意味着第一阶段并不缺字段，而是缺统一的身份来源和授权编排。

当前这条线又往前推进了一档，已经不再只是“sidecar 可以认 token”：

1. `scripts/api_identity.py` 现在提供统一的 bearer-token -> `issuer + subject` -> `caller_identities` -> `caller/tenant/service/permission_summary` resolver，metadata/query/audit/platform-health 四个 HTTP adapter 复用同一套入口
2. `scripts/resolve_api_identity.py` 与 `schemas/api_identity_resolution.schema.json` 已固定一条可单独验证的 identity resolution contract，可直接对账 bearer token 或 issuer/subject 映射
3. `serve_metadata_api.py` 新增 `/v1/identity`，用于把当前 authenticated identity 和 derived access summary 直接暴露成只读 control-plane 视图
4. `serve_query_workflow_api.py` 现在把 `dry-run` 与 `execute` 分开治理：`query_submitter` 可做 `dry-run`，`execute` 还要求 `privacy_operator` 或 `platform_admin`
5. `serve_audit_query_api.py` 现在把 `include_paths=true` 收紧到 `platform_admin` / `platform_auditor`
6. 这套规则已经被默认 contract smoke 固化，不再只是文档约定

## 3. 设计原则

### 3.1 认证与隐私语义分层

身份系统负责回答：

1. 你是谁
2. 你属于哪个 tenant
3. 你是人还是服务
4. 你具备哪些外围平台角色

隐私主链路继续负责回答：

1. 你能不能发起这类隐私查询
2. 能访问哪个 dataset
3. 能用哪个 record recovery service
4. 能不能运行 bridge / PJC / release
5. 结果能不能发布

### 3.2 adapter-first

第一阶段优先给这些入口加 authn/authz：

1. `scripts/serve_metadata_api.py`
2. `scripts/serve_query_workflow_api.py`
3. `scripts/serve_audit_query_api.py`
4. `scripts/serve_platform_health_api.py`
5. `scripts/run_record_recovery_service.py`
6. `scripts/key_agent_service.py`
7. `scripts/external_kms_service.py`

不要直接把 Keycloak、OpenFGA、OPA 调用塞进 `bridge`、`PJC` 或 `policy_release.py`。

### 3.3 frozen field first

所有 token claim、subject mapping、关系模型都必须优先映射到：

1. `caller`
2. `tenant_id`
3. `dataset_id`
4. `service_id`
5. `job_id`
6. `correlation_id`

## 4. 身份模型

### 4.1 主体类型

建议把身份分成三类：

1. human user
2. service account
3. local operator

推荐映射：

1. human user -> `caller`
2. service account -> `caller` 或 `service_id` 绑定的机器主体
3. local operator -> 仅限开发/运维模式下的 bearer token 或本地 socket token

### 4.2 角色层

建议保留外围平台角色，而不要把它们直接写死为 release 逻辑：

1. `platform_admin`
2. `platform_auditor`
3. `privacy_operator`
4. `query_submitter`
5. `service_operator`

这些角色的作用范围：

1. 决定能否访问 metadata、audit、platform health 之类 sidecar API。
2. 决定能否发起 query dry-run 或 execute。
3. 决定能否管理 record recovery service、key agent、external KMS。

它们不应直接替代 `can_release` 或 `k` 阈值判断。

### 4.3 电商平台最小角色矩阵

把上面的角色映射到一个电商数据库平台，当前建议至少区分：

1. `commerce_ops_owner`
职责：跑主查询、复核结果、决定是否发布。
建议平台角色：`query_submitter` + `privacy_operator`
建议阶段权限：`can_run_bridge=true`、`can_run_pjc=true`、`can_use_record_recovery_service=true`、`can_release=true`

2. `campaign_analyst`
职责：营销归因、活动效果分析。
建议平台角色：`query_submitter`
建议阶段权限：可跑 query / bridge / PJC，可用 recovery service，但默认 `can_release=false`

3. `fraud_analyst`
职责：欺诈样本对比、风险分层分析。
建议平台角色：`query_submitter`
建议阶段权限：和营销分析员类似，但 scope 应单独落在风险数据集和 recovery service

4. `compliance_auditor`
职责：看 metadata、policy、audit、public report 是否符合流程。
建议平台角色：`platform_auditor`
建议阶段权限：默认不跑 query，不直接调用 recovery service，不具备 `can_release`

5. `recovery_service_operator`
职责：维护 recovery service、listener、密钥和审计。
建议平台角色：`service_operator`
建议阶段权限：默认不具备 `can_run_bridge`、`can_run_pjc`、`can_release`

第一阶段当前通过 `sse_export_policy/v1` 中的 `platform_roles`、`access_profile`、`tenant_id`、`allowed_dataset_ids`、`allowed_service_ids` 和 `can_*` 字段共同表达这层矩阵。一个更具体的示例见 [docs/ECOMMERCE_ACCESS_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_ACCESS_MODEL.md) 和 [sse/config/ecommerce_access_policy.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/sse/config/ecommerce_access_policy.example.json)。

## 5. Keycloak 集成方案

## 5.1 目标

Keycloak 只做身份来源，不做隐私发布判断。

### 5.2 claim 映射

建议统一映射：

1. `sub` -> 外围 identity 主键
2. `preferred_username` 或 `client_id` -> `caller`
3. 自定义 claim `tenant_id` -> `tenant_id`
4. service client id -> `service_id`
5. realm/client roles -> 平台角色

建议 token 中显式携带：

1. `caller`
2. `tenant_id`
3. `allowed_service_ids` 或可派生 service 关系
4. `entity_type`

### 5.3 第一阶段接入位置

第一阶段不要求仓库内直接嵌入完整 OIDC 登录流。建议先做：

1. sidecar API 前置反向代理或薄适配层，校验 bearer token。
2. 校验通过后，把解析后的 `caller`、`tenant_id`、`service_id` 注入请求上下文。
3. 请求再交给现有 Python adapter。

这样做的原因：

1. 不改主链路 CLI 参数语义。
2. 允许本地 demo 继续使用 env token 模式。
3. 后续可平滑切到真实 OIDC。

## 6. OpenFGA 授权模型

## 6.1 作用边界

OpenFGA 负责外围资源访问关系，不直接替代主链路里的 release policy。

适合表达：

1. 哪个 caller 属于哪个 tenant
2. 哪个 caller 可以读取哪个 dataset 的元数据
3. 哪个 service account 可以操作哪个 recovery service
4. 哪个 caller 可以查看哪个 job / audit / report

不适合直接替代：

1. `policy_release.py` 的阈值逻辑
2. PJC 结果发布判断
3. bridge token contract

## 6.2 推荐对象模型

建议模型延续任务书中的最小集合：

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

### 6.3 与当前表结构的映射

SQLite / PostgreSQL sidecar 可作为关系同步源：

1. `tenants` -> `tenant`
2. `datasets` -> `dataset`
3. `services` -> `privacy_service`
4. `callers` -> `user` 或 `service_account`
5. `jobs` -> `job`
6. `policy_bindings`、`caller_permissions` -> 同步策略输入

第一阶段建议先做单向同步：

1. metadata DB / policy files -> OpenFGA tuples
2. 查询 API 在入口做 FGA check

不要反过来让主链路阶段执行时必须同步依赖 OpenFGA 才能跑。

### 6.4 当前 tuple/export 基线

仓库当前已经补了一条第一阶段关系同步入口：

```bash
python3 scripts/export_authz_tuples.py \
  --policy-config sse/config/ecommerce_access_policy.example.json

python3 scripts/export_authz_tuples.py \
  --db-path tmp/platform_metadata.db \
  --output tmp/platform_authz_tuples.json
```

当前输出 contract 固定为 `authz_tuple_export/v1`，来源可以是 policy 文件，也可以是已导入的 metadata sidecar。它做的事情是：

1. 保留 `subjects` 级别的 caller / tenant / dataset / service / role / capability 清单，便于审计当前 file-backed policy。
2. 只为 `enabled=true` 的主体生成 active tuples，避免把 disabled caller 误同步成可授权关系。
3. 默认把 caller 视为 `user`；只有当前 `platform_roles` / `access_profile` 基线明显表示 service operator 时，才推断成 `service_account`。
4. 先导出 `tenant member/admin/auditor`、`dataset reader/query_submitter/privacy_operator/recovery_allowed`、`privacy_service can_recover/operator` 和 capability grant 这些稳定关系，不尝试替代 `policy_release.py` 的发布语义。

默认 contract smoke 现在会同时验证：

1. 直接从 `sse/config/ecommerce_access_policy.example.json` 导出的 tuple 基线。
2. synthetic `contract_export_policy.json` 的 direct policy export。
3. 同一份 policy 经 `import_run_metadata.py` 导入 sidecar DB 后，再通过 `--db-path` 导出的关系结果。

## 7. OPA 作用边界

OPA 更适合做 admission / routing / API-gate 规则，而不是替代 release policy。

适合用在：

1. sidecar API 的 coarse-grained allow/deny
2. 某些 execute 请求是否允许进入 query workflow adapter
3. 运维操作白名单

不适合用在：

1. PJC 结果对外发布真正规则
2. 审计字段语义定义
3. 桥接 token 的生成约束

推荐分工：

1. Keycloak 提供身份
2. OpenFGA 提供关系授权
3. OPA 提供 API 边界 admission
4. 现有 export policy + pipeline policy + policy release 继续负责隐私语义

## 8. 分阶段接入路线

### Phase 0：保持当前本地基线

保留：

1. `sse_export_policy/v1`
2. 本地 bearer token / env token
3. Unix socket / HTTP service token
4. metadata importer 和只读 API

### Phase 1：认证前置到 sidecar API

目标：

1. metadata/query/audit/platform-health API 能接受来自 OIDC 的 bearer token。
2. adapter 解析 token 后统一写入 `caller`、`tenant_id`、`service_id`。

输出：

1. sidecar API auth middleware 或反向代理方案
2. token claim mapping 文档
3. 本地 dev realm / mock token 约定

### Phase 2：把只读查询和提交流程接入 FGA

目标：

1. metadata entity/job 读取走 FGA 判断
2. query workflow submit 先做 coarse-grained relation check
3. audit/public-report 查看走 `job.viewer` 或 dataset 级关系

注意：

1. 只拦 sidecar API。
2. 不拦本地主链路 CLI。

### Phase 3：服务边界主体化

目标：

1. record recovery service、key agent、external KMS 都有独立 service account。
2. 它们对外暴露的 auth token 逐步替换成 OIDC 或 mTLS 绑定主体。

优先顺序：

1. record recovery service
2. external KMS
3. key agent

### Phase 4：控制面写接口

前提：

1. 只读 sidecar DB 和 API 稳定
2. 身份和授权映射稳定
3. 变更流程明确

这时才适合引入：

1. policy binding 管理 API
2. service registration API
3. key reference registration API

如果要纳入统一排期，建议把这些 phase 对齐到 [POST_BASELINE_ROADMAP.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/POST_BASELINE_ROADMAP.md) 的 `Tranche A`：

1. `A1` 对应 Phase 1：issuer-backed identity proxy baseline
2. `A2` 对应 Phase 2：OpenFGA tuple sync + check adapter
3. `A4` 对应 Phase 3：service identity + token lifecycle
4. `A5-A6` 对应 Phase 4 之前的治理、回归与 runbook 收口

这份 IAM 文档后续主要负责：

1. 固定 identity / relation / admission 三层分工
2. 明确哪些入口先接 OIDC / FGA，哪些仍保留本地主链路独立性

## 9. 对各入口的建议授权策略

### `serve_metadata_api.py`

检查：

1. bearer token 必须映射出 `caller`
2. `tenant_id` 必须匹配被查询 scope
3. `policy-bindings` 和 `caller-permissions` 默认仅 auditor / admin 可读

### `serve_query_workflow_api.py`

检查：

1. `caller` 必须来自 token，不允许请求体覆盖
2. `tenant_id`、`dataset_id` 必须与 token / FGA scope 一致
3. `dry-run` 至少要求 `query_submitter`；`execute` 还要求 `privacy_operator` 或 `platform_admin`

### `serve_audit_query_api.py`

检查：

1. 默认只允许 job owner、tenant auditor、platform auditor 读取
2. `--include-paths` 等高敏选项只开放给 `platform_admin` / `platform_auditor`

### `serve_platform_health_api.py`

检查：

1. 仅限运维、审计或平台管理员
2. 不对普通 query caller 暴露组件路径和错误细节

### record recovery service

检查：

1. `caller` 需要与认证主体一致
2. `tenant_id`、`dataset_id`、`service_id` 需要与 service runtime config 和 policy 一致
3. 服务端仍以现有 `sse_export_policy/v1` / `record_recovery_service_policy/v1` 作为最终本地授权依据

## 10. 审计要求

认证和授权接入后，仍要保证审计链语义不变。

建议新增但不替代当前字段：

1. `auth_subject`
2. `auth_issuer`
3. `auth_entity_type`
4. `auth_mechanism`

注意：

1. 这些字段应作为向后兼容新增字段。
2. 不得替换已有 `caller`、`tenant_id`、`service_id`。
3. 如需落入冻结 schema，应先走 `docs/change_requests/`。

## 11. 非目标

这份方案当前不做：

1. 把主链路改成必须在线访问 Keycloak/OpenFGA/OPA
2. 用 IAM 结果替代 `policy_release.py`
3. 定义新的 query/result contract
4. 让 SQL sidecar 直接接管隐私执行

## 12. 推荐实施顺序

1. ~~先完成 metadata/query/audit/platform-health API 的统一身份映射。~~ **已完成（2026-05-03）**：四类 sidecar API 现已复用统一 identity resolver，metadata `/v1/identity` 与 `resolve_api_identity.py` 可直接验证 token 映射与 access summary，query/audit/platform health 的角色门限也已收口到默认 contract smoke。
2. 再把 metadata sidecar 中的 registry / policy 数据同步到 FGA。
3. 再给 execute、service admin、health read 等高风险入口补角色和关系限制。
4. 继续把 record recovery service、key agent、external KMS 的 service/admin 路径从共享 token 过渡到更正式的身份方案。
