# 电商数据库平台访问角色矩阵

这份文档把当前仓库第一阶段 file-backed authz 基线，落成一个更具体的“电商数据库平台谁会访问、访问什么、最小权限是什么”的角色矩阵。

边界先说清楚：

1. 当前建模的是“平台调用主体 / 隐私查询流程参与者”，不是完整电商公司所有人员与终端用户身份树。
2. 所以这里的 `caller` 目前更接近运营负责人、营销分析师、风控分析师、审计员、恢复服务运维，而不是买家、快递员、客服、商家店员这类业务末端角色。
3. 如果后续要支持更真实的企业组织与业务一线角色，需要在 identity source、role mapping、scope policy 和查询模板上再细化一层。

## 角色

1. `commerce_ops_owner`
职责：负责隐私查询运行、结果复核、最终发布。
最小权限：`query_submitter` + `privacy_operator`；限定 `tenant_id`、`allowed_dataset_ids`、`allowed_service_ids`；允许 `can_run_bridge`、`can_run_pjc`、`can_use_record_recovery_service`、`can_release`。

2. `campaign_analyst`
职责：做营销归因、活动复盘、受众分析。
最小权限：`query_submitter`；限定到营销数据集和 recovery service；允许 `can_run_bridge`、`can_run_pjc`、`can_use_record_recovery_service`；默认不允许 `can_release`。

3. `fraud_analyst`
职责：做欺诈命中分析、风险分层对比。
最小权限：`query_submitter`；限定到风险数据集和 recovery service；允许 `can_run_bridge`、`can_run_pjc`、`can_use_record_recovery_service`；默认不允许 `can_release`。

4. `compliance_auditor`
职责：审计 caller、scope、policy、job、audit chain 是否符合流程。
最小权限：`platform_auditor`；默认不直接跑隐私查询，不直接调用 recovery service，不具备 `can_release`。

5. `recovery_service_operator`
职责：维护 record recovery service、socket/HTTP listener、health、lifecycle、密钥和审计。
最小权限：`service_operator`；可管理 service 边界，但不应默认拥有 `can_run_bridge`、`can_run_pjc` 或 `can_release`。

## 当前没细到的角色

下面这些更贴近日常电商业务的人群，目前还没有直接作为一等 `caller` 画像建模：

1. 买家 / 消费者
2. 商家店员 / 店铺运营
3. 客服
4. 快递员 / 物流履约人员
5. 地推 / 渠道投放执行人员

原因不是“不能存在这些人”，而是当前平台边界更聚焦于隐私查询和审计链路，优先建模的是能发起、审核、运维这条链路的人。

## 业务身份扩展（Track-E2，2026-05-08 落基线）

为了把上面这五类业务身份接入隐私平台、又不破坏 `caller_permissions` 已经冻结的 schema，新增一张 `business_identities` 表（迁移 [`migrations/metadata/011_add_business_identities.sql`](/home/llvanion/Desktop/seccomp-privacy-platform/migrations/metadata/011_add_business_identities.sql)），把"业务一线身份"作为 `caller` 的可选画像挂在已有的 `caller_permissions` 上。

设计原则：

1. **业务身份不是 caller**。买家、客服、快递员、商家店员不直接发起隐私查询；他们的身份只用于解释为什么某个 caller 能在某个 scope 内活动。
2. **`caller_permissions` 不变**。`tenant_id` / `allowed_dataset_ids` / `allowed_service_ids` / `can_*` 仍是隐私阶段的唯一权限源；`business_identities` 不引入新的 stage gate。
3. **PII 不进库**。表只存“业务身份的脱敏 ID + 角色 + 关联的 caller_id”，不存姓名、地址、电话、身份证。

业务身份枚举（`identity_kind`）：

| identity_kind | 谁 | 关联到 |
|---------------|----|--------|
| `buyer` | 买家 / 消费者 | `caller` 一般是 `commerce_ops_owner` 或 `compliance_auditor` 代查；`subject_external_id` 是脱敏买家 ID（不等同于明文 email） |
| `merchant_staff` | 商家店员 / 店铺运营 | `caller` 一般是 `commerce_ops_owner` |
| `customer_service_agent` | 客服 | `caller` 一般是 `compliance_auditor` 或专门的 supervisor |
| `courier` | 快递员 / 物流履约人员 | 不发起查询；只在 `customer_service_interactions.agent_id` / `order_fulfillment.carrier_id` 里出现 |
| `field_marketer` | 地推 / 渠道投放执行人员 | `caller` 一般是 `campaign_analyst` |

字段定义（详见迁移）：`id` / `business_identity_id` / `tenant_id` / `dataset_id` / `identity_kind` / `caller_id` / `subject_external_id` / `display_label` / `enabled` / `created_at_utc` / `updated_at_utc` / `metadata_json`。约束：

- `(tenant_id, business_identity_id)` 唯一。
- `caller_id` 可空；非空时必须能在 `caller_permissions` 找到匹配 row。
- `identity_kind` 受控集合：`buyer` / `merchant_staff` / `customer_service_agent` / `courier` / `field_marketer`。

读取入口：`query_metadata.py --list-entity business-identities`（与现有 `caller-permissions` 视图同形态）。

边界保留：

1. 这一层不替代 OpenFGA 关系建模；它是 RBAC + scope 模型之上的一层"业务身份注解"。
2. 不引入新的 stage gate（`can_*` 仍然只在 `caller_permissions` 上）。
3. 不存 PII；任何把姓名/手机号/地址写入 `display_label` 或 `metadata_json` 的行为都属于策略违规，应该在导入路径上加校验（operator-side 实施）。

## 当前落地方式

当前仓库没有第二套独立 RBAC 表。第一阶段仍然通过 `sse_export_policy/v1` 里的 caller 记录承载这些角色语义：

1. `tenant_id`、`allowed_dataset_ids`、`allowed_service_ids` 定义 scope。
2. `can_run_bridge`、`can_run_pjc`、`can_use_record_recovery_service`、`can_release` 定义阶段权限。
3. `platform_roles` 和 `access_profile` 负责把这些 caller 标成更容易审计的电商角色画像。

这也意味着当前 `caller` 粒度主要是“查询主体”而不是“业务对象”。例如买家是否来自某平台、从哪个广告入口点击、购买了哪些 SKU，这些不是 `caller` 表达的内容，而应该属于业务数据与查询模板层。

对应示例文件：

1. [sse/config/ecommerce_access_policy.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/sse/config/ecommerce_access_policy.example.json)
2. [sse/config/export_policy.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/sse/config/export_policy.example.json)

## 为什么这样分

1. `platform_roles` 解决“这个人为什么能进平台”的 coarse-grained 角色问题。
2. `can_*` 解决“这个 caller 能不能走某个隐私阶段”的 pipeline 权限问题。
3. `tenant_id` / `dataset_id` / `service_id` 解决“这个 caller 能碰哪些数据和恢复边界”的 scope 问题。

三层叠加，才能避免只有角色没有 scope，或者只有 scope 没有职责语义。
