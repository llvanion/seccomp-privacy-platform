# 下个会话接手阅读指南

这份文档现在只做一件事：

1. 告诉接手者先读哪几份
2. 避免再次把 `docs/` 全量扫一遍

## 1. 默认入口

先读这 3 份：

1. [COMPACT_PLATFORM_BRIEF.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/COMPACT_PLATFORM_BRIEF.md)
2. [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md)
3. [TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md)

这 3 份分别解决：

1. 项目是什么、当前到了哪里
2. 还有多少剩余工作
3. 主链路边界和冻结语义是什么

## 2. 按角色读

### 2.1 如果你接 owner / 主链路

读：

1. [TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md)
2. [THREAT_MODEL_AND_LEAKAGE_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md)
3. [BRIDGE_HANDOFF_HARDENING_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/BRIDGE_HANDOFF_HARDENING_PLAN.md)
4. [SSE_BRIDGE_APSI_PIPELINE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/SSE_BRIDGE_APSI_PIPELINE.md)

### 2.2 如果你接权限 / IAM / KMS

读：

1. [ECOMMERCE_ACCESS_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_ACCESS_MODEL.md)
2. [TASK_ENGINEER_A_CONTROL_PLANE_IDENTITY_ACCESS.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_ENGINEER_A_CONTROL_PLANE_IDENTITY_ACCESS.md)
3. [IAM_AUTHZ_INTEGRATION_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/IAM_AUTHZ_INTEGRATION_PLAN.md)
4. [KMS_SECRET_BACKEND_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/KMS_SECRET_BACKEND_PLAN.md)

### 2.3 如果你接 SQL sidecar / control plane

读：

1. [DELEGATION_ENGINEER_2_SQL_CONTROL_PLANE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/DELEGATION_ENGINEER_2_SQL_CONTROL_PLANE.md)
2. [CONTROL_PLANE_SCHEMA.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/CONTROL_PLANE_SCHEMA.md)
3. [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md)

### 2.4 如果你接 benchmark / operator / audit

读：

1. [BENCHMARK_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/BENCHMARK_PLAN.md)
2. [OPS_RUNBOOK.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPS_RUNBOOK.md)
3. [DELEGATION_ENGINEER_1_AUDIT_OPS.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/DELEGATION_ENGINEER_1_AUDIT_OPS.md)

## 3. 按问题读

如果你只想回答某个问题，直接跳：

1. “这个项目现在能做什么、不能做什么？”
   [COMPACT_PLATFORM_BRIEF.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/COMPACT_PLATFORM_BRIEF.md)

2. “现在还剩多少任务？”
   [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md)

3. “电商场景的权限矩阵是什么？”
   [ECOMMERCE_ACCESS_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/ECOMMERCE_ACCESS_MODEL.md)

4. “SQL sidecar 现在做到哪里了？”
   [DELEGATION_ENGINEER_2_SQL_CONTROL_PLANE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/DELEGATION_ENGINEER_2_SQL_CONTROL_PLANE.md)

5. “benchmark 和 operator 怎么跑？”
   [BENCHMARK_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/BENCHMARK_PLAN.md)
   [OPS_RUNBOOK.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPS_RUNBOOK.md)

## 4. 建议

以后默认不要再让接手者先读十几份 markdown。

建议顺序固定成：

1. `COMPACT_PLATFORM_BRIEF.md`
2. `PLATFORM_LEVEL_REMAINING_ESTIMATE.md`
3. 按角色只补读 2-4 份深文档

这样最省 token，也最不容易把主线、外围 sidecar 和远期平台化计划混在一起。
