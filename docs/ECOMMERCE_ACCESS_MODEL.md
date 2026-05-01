# 电商数据库平台访问角色矩阵

这份文档把当前仓库第一阶段 file-backed authz 基线，落成一个更具体的“电商数据库平台谁会访问、访问什么、最小权限是什么”的角色矩阵。

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

## 当前落地方式

当前仓库没有第二套独立 RBAC 表。第一阶段仍然通过 `sse_export_policy/v1` 里的 caller 记录承载这些角色语义：

1. `tenant_id`、`allowed_dataset_ids`、`allowed_service_ids` 定义 scope。
2. `can_run_bridge`、`can_run_pjc`、`can_use_record_recovery_service`、`can_release` 定义阶段权限。
3. `platform_roles` 和 `access_profile` 负责把这些 caller 标成更容易审计的电商角色画像。

对应示例文件：

1. [sse/config/ecommerce_access_policy.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/sse/config/ecommerce_access_policy.example.json)
2. [sse/config/export_policy.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/sse/config/export_policy.example.json)

## 为什么这样分

1. `platform_roles` 解决“这个人为什么能进平台”的 coarse-grained 角色问题。
2. `can_*` 解决“这个 caller 能不能走某个隐私阶段”的 pipeline 权限问题。
3. `tenant_id` / `dataset_id` / `service_id` 解决“这个 caller 能碰哪些数据和恢复边界”的 scope 问题。

三层叠加，才能避免只有角色没有 scope，或者只有 scope 没有职责语义。
