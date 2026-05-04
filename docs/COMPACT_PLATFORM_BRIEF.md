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

已经完成：

1. owner 主线完成：主链路 contract、recovery replay、normalizer 治理、FIFO handoff、exposure assessment 已收口
2. 审计/运维基线完成：malformed-input gate、benchmark gate、operator readiness、runbook 已收口
3. SQL sidecar 已完成多项基线：
   - metadata import/replay/dry-run
   - query CLI / HTTP 分页与聚合
   - PostgreSQL-ready portability gate
   - registry/policy/permission managed write baseline
   - key registry / key version managed write + read baseline

还没完成：

1. 真实 OIDC / issuer-backed identity source 与长期凭证治理
2. 真实远端 Vault / cloud KMS 权威源与 service identity
3. durable workflow / dashboard 壳
4. SQL sidecar 更深的 Postgres 迁移与 importer repair
5. caller 画像仍然主要停留在“平台操作者 / 查询发起者”层级，还没细化成买家、商家店员、客服、快递员这类更贴近日常电商业务的人群模型
6. SQL sidecar 当前保存的是 control-plane metadata / audit / policy / permission，而不是完整电商业务事实表；像“买了什么商品”“在哪个平台成交”“从哪个投放入口点击进来”这类字段目前不作为 sidecar 的主存储目标
7. 面向真实电商订单分析的一整套 SQL 事实层还没落地；当前没有正式的 `orders / order_items / order_attribution / order_payment / order_fulfillment / customer_service_interactions` 这类业务表基线

剩余估算以 [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md) 为准。

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
8. metadata/query/audit/platform-health sidecar API 已统一走 identity resolver，并收紧 query execute / audit include_paths / platform health role gate
9. `keyring/v1` 现支持 `secret_ref.kind=env|vault_kv`，key agent / external KMS / pipeline auto-start 已贯通 Vault KV 兼容 backend

当前这一层更像“谁能发起或审核隐私查询”的平台权限模型，而不是完整电商业务人员身份模型。

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
3. query / read adapter / recovery / pipeline / PJC / audit bundle / platform health / derived views benchmark

## 4. 当前不能做什么

当前不应该把这个仓库描述成“真实生产电商平台”。

还不能：

1. 作为完整生产级多租户平台上线
2. 依赖真实 Keycloak / OpenFGA / Vault 作为在线权威源
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
3. [TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md)
4. [ECOMMERCE_ACCESS_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_ACCESS_MODEL.md)
5. [DELEGATION_ENGINEER_2_SQL_CONTROL_PLANE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/DELEGATION_ENGINEER_2_SQL_CONTROL_PLANE.md)

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

## 10. 建议

后续会话不要默认把 `docs/*.md` 全读一遍。

建议流程：

1. 先读这份压缩总览
2. 再读剩余工作量估算
3. 再按问题跳转到 1-2 份深文档

这样最省 token，也最不容易把外围材料和主线边界混在一起。
