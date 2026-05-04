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
