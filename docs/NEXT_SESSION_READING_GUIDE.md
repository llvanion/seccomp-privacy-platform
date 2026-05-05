# 下个会话接手阅读指南

这份文档现在只做一件事：

1. 告诉接手者先读哪几份
2. 避免再次把 `docs/` 全量扫一遍

## 1. 默认入口

先读这 4 份：

1. [COMPACT_PLATFORM_BRIEF.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/COMPACT_PLATFORM_BRIEF.md)
2. [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md)
3. [POST_BASELINE_ROADMAP.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/POST_BASELINE_ROADMAP.md)
4. [TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md)

这 4 份分别解决：

1. 项目是什么、当前到了哪里
2. 当前平台基线是否还剩 block
3. 平台基线之后下一阶段先做什么
4. 主链路边界和冻结语义是什么

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

6. “平台基线做完之后，下一阶段怎么排？”
   [POST_BASELINE_ROADMAP.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/POST_BASELINE_ROADMAP.md)

## 4. 建议

以后默认不要再让接手者先读十几份 markdown。

建议顺序固定成：

1. `COMPACT_PLATFORM_BRIEF.md`
2. `PLATFORM_LEVEL_REMAINING_ESTIMATE.md`
3. `POST_BASELINE_ROADMAP.md`
4. 按角色只补读 2-4 份深文档

这样最省 token，也最不容易把主线、外围 sidecar 和远期平台化计划混在一起。

## 5. 最小可复现 Operator 流程（2026-05-03 基线）

工程师 B 全部 8 个 block 已完成。下面是一个已经可以完整执行的 operator 流程：

### 前提条件

已完成一次 pipeline 运行，产物在 `tmp/sse_bridge_pipeline_demo/` 下：

```
tmp/sse_bridge_pipeline_demo/
├── audit_chain.json
├── a_psi_run/public_report.json
└── mainline_contract_check.json   (可选)
```

### Step 1 — 导出 observability

```bash
python3 scripts/export_observability_events.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/pipeline_observability.json
```

### Step 2 — 生成 operator 面板

```bash
python3 scripts/build_observability_dashboard.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/observability_dashboard.json
```

面板：`stage_timeline` / `stage_summary` / `stage_duration` / `release_outcomes` / `failure_summary`。

### Step 3 — 运行告警检查

```bash
python3 scripts/check_observability_alerts.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/observability_alert_report.json
```

四条告警：`repeated_stage_error` / `release_failure_after_success` / `platform_health_degraded` / `stage_coverage_gap`。

### Step 3b — 启动 Web 面板（可选）

```bash
python3 scripts/serve_operator_dashboard.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --port 18094
# 浏览器打开 http://127.0.0.1:18094/
```

自动 15s 刷新，展示全部面板（Alerts / Stage Summary / Duration / Release Outcomes / Failure Summary / Stage Timeline）。

### Step 4 — 检查 platform health

```bash
python3 scripts/check_platform_health.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --metadata-db tmp/platform_metadata.db \
  --output tmp/sse_bridge_pipeline_demo/platform_health.json
```

### Step 5 — 一键 triage

```bash
python3 scripts/run_operator_triage.py \
  --out-base tmp/sse_bridge_pipeline_demo \
  --out tmp/sse_bridge_pipeline_demo/operator_triage.json
```

输出 `operator_triage_report/v1`，四个 section：`dashboard` / `alerts` / `platform_health` / `workflow_status`。

### Step 6（可选）— 查看 query workflow 状态

如果曾通过 `submit_query_workflow.py --execute` 运行过，检查状态：

```bash
python3 scripts/check_workflow_retry_eligibility.py \
  --status-file tmp/sse_bridge_pipeline_demo/query_workflow/status.json

python3 scripts/list_query_workflow_status.py \
  --search-dir tmp \
  --state failed \
  --limit 10
```

### 关键规则回顾

1. 所有上述脚本只读现有 sidecar 产物，不改变主链路语义。
2. `operator_triage_report/v1` 是整个 operator 面的顶层入口，它的 `overall_status` 汇总了 dashboard / alerts / health 三个维度。
3. 当 `retry_eligibility.recommended_action == "resubmit"` 时，必须使用新的 `job_id`，否则 duplicate-query guard 会拒绝。
4. 当 `retry_eligibility.recommended_action == "retry"` 时（仅 `launch_failed`），可以用相同的请求内容重试，但建议仍使用新的 `job_id`。

## 6. 关键契约文件（快速索引）

| Contract | Schema | 生成脚本 |
| -------- | ------ | -------- |
| `pipeline_observability/v1` | `schemas/pipeline_observability.schema.json` | `export_observability_events.py` |
| `catalog_lineage/v1` | `schemas/catalog_lineage.schema.json` | `export_catalog_lineage.py` |
| `observability_dashboard/v1` | `schemas/observability_dashboard.schema.json` | `build_observability_dashboard.py` |
| `observability_alert_report/v1` | `schemas/observability_alert_report.schema.json` | `check_observability_alerts.py` |
| `operator_triage_report/v1` | `schemas/operator_triage_report.schema.json` | `run_operator_triage.py` |
| `query_workflow_status/v1` | `schemas/query_workflow_status.schema.json` | `submit_query_workflow.py` |
| `query_workflow_status_list/v1` | `schemas/query_workflow_status_list.schema.json` | `list_query_workflow_status.py` |
| `workflow_retry_eligibility/v1` | `schemas/workflow_retry_eligibility.schema.json` | `check_workflow_retry_eligibility.py` |
| `platform_health/v1` | `schemas/platform_health.schema.json` | `check_platform_health.py` |
| Web UI (no schema) | — | `serve_operator_dashboard.py` → http://127.0.0.1:18094/ |
