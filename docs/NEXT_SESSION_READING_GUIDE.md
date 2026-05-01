# 下个会话接手阅读指南

## 1. 这份文档的用途

这份文档只回答一个问题：

```text
下一个会话接手时，应该先读哪些 markdown，按什么顺序读，分别解决什么问题。
```

它不是新的设计文档，也不是任务书替代品。

它的作用是：

1. 降低接手成本。
2. 避免一上来把 `docs/` 全部读一遍。
3. 让接手者先掌握 owner 主线，再决定是否补读外围材料。

当前默认场景：

1. 你接的是 owner 主线。
2. 你关心的是主链路、冻结 contract、泄漏边界、handoff 收紧、审计与回放。
3. 你不需要先去管其他工程师的任务书。

---

## 2. 最小必读集合

如果时间有限，只读下面 8 份。

建议顺序不要乱。

### 2.1 第一份：任务边界

先读：

1. [TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md)

这份文档回答：

1. owner 到底负责什么。
2. 哪些接口和语义不能随便分给别人改。
3. 当前主线的验收标准是什么。

如果不先读这份，后面很容易把外围功能和 owner 主线混在一起。

### 2.2 第二份：冻结规则

再读：

1. [INTERFACE_FREEZE_AND_CHANGE_PROCESS.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/INTERFACE_FREEZE_AND_CHANGE_PROCESS.md)

这份文档回答：

1. 哪些 schema name 已冻结。
2. 哪些主入口参数不能静默改语义。
3. 哪些输出路径已被冻结。
4. 什么改动可以直接做，什么改动必须先提案。

这是“能不能改”的总开关文档。

### 2.3 第三份：冻结字段矩阵

然后读：

1. [CORE_CONTRACT_FREEZE_MATRIX.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/CORE_CONTRACT_FREEZE_MATRIX.md)

这份文档回答：

1. `job_id`、`correlation_id`、`caller`、`tenant_id`、`dataset_id`、`service_id`、`record_recovery_boundary`、`token_scope`、`token_key_version`、`release_policy` 这些字段分别在哪些载体里出现。
2. 谁生产这些字段。
3. 谁消费这些字段。
4. 哪种改动属于“只是新增载体”，哪种改动属于“语义漂移”。

这是“改了一个字段会不会影响全链路”的定位图。

### 2.4 第四份：风险边界

然后读：

1. [THREAT_MODEL_AND_LEAKAGE_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md)

这份文档回答：

1. 每个阶段允许泄漏什么。
2. 每个阶段不允许泄漏什么。
3. 为什么 `bridge` 不该看到 raw candidate ID。
4. 为什么 recovery 只能恢复被授权字段。
5. 为什么 release 只允许发布满足阈值和策略的结果。

这是“为什么这些 contract 要冻结”的安全理由。

### 2.5 第五份：handoff 高风险点

然后读：

1. [BRIDGE_HANDOFF_HARDENING_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/BRIDGE_HANDOFF_HARDENING_PLAN.md)

这份文档回答：

1. 当前 `file handoff` 和 `FIFO handoff` 的差异。
2. 为什么 file mode 风险更高。
3. 为什么 FIFO 只是更好，但还不是最终边界。
4. owner 这条线现在为什么持续围绕明文 handoff 清理、审计、回放、可观测性推进。

这是“当前代码推进重点为什么一直落在 handoff 和 observability 上”的解释文档。

### 2.6 第六份：主链路总览

再读：

1. [SSE_BRIDGE_APSI_PIPELINE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/SSE_BRIDGE_APSI_PIPELINE.md)

这份文档回答：

1. `SSE -> record recovery -> bridge -> PJC -> release` 主链路到底怎么跑。
2. 每个阶段输出什么文件。
3. `mainline_contract_check.json`、`audit_chain.json`、`audit_chain.seal.json` 之间是什么关系。
4. 为什么 `audit_chain.json` 现在内嵌了 `mainline_contract_check/v1`。
5. archive index 为什么现在也带 `mainline_contract_summary`。

这是从“治理文档”切到“实现形态”的关键一步。

### 2.7 第七份：运维和读侧

然后读：

1. [OPS_RUNBOOK.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPS_RUNBOOK.md)

这份文档回答：

1. completed run 怎么检查。
2. `platform_health` 现在检查什么。
3. `audit_query`、observability、catalog/lineage 这些只读 sidecar 怎么用。
4. `verify_audit_bundle.py`、archive index、restore 流程怎么跑。
5. 为什么 observability 现在有 `handoff_cleanup` stage。

这是“怎么验证当前改动真的生效”的操作手册。

### 2.8 第八份：benchmark 和 smoke

最后读：

1. [BENCHMARK_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/BENCHMARK_PLAN.md)

这份文档回答：

1. 哪些 benchmark 是默认 smoke 的一部分。
2. live SSE benchmark 验证什么。
3. audit bundle benchmark 验证什么。
4. platform health benchmark 验证什么。
5. derived views benchmark 为什么现在必须覆盖 `handoff_cleanup` stage。

这是“哪些自动化回归已经把 owner 规则钉住了”的总览。

---

## 3. 建议阅读顺序

如果你是下一个会话的接手者，按下面顺序读最稳：

1. `TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md`
2. `INTERFACE_FREEZE_AND_CHANGE_PROCESS.md`
3. `CORE_CONTRACT_FREEZE_MATRIX.md`
4. `THREAT_MODEL_AND_LEAKAGE_MODEL.md`
5. `BRIDGE_HANDOFF_HARDENING_PLAN.md`
6. `SSE_BRIDGE_APSI_PIPELINE.md`
7. `OPS_RUNBOOK.md`
8. `BENCHMARK_PLAN.md`

这个顺序的逻辑是：

1. 先搞清楚“你负责什么”。
2. 再搞清楚“什么不能乱改”。
3. 再搞清楚“冻结的是哪些语义”。
4. 再搞清楚“这些冻结背后的泄漏约束是什么”。
5. 再搞清楚“当前最敏感、最需要推进的剩余风险是什么”。
6. 再进入“主链路实现长什么样”。
7. 再进入“怎么跑、怎么查、怎么验”。
8. 最后进入“哪些 benchmark/smoke 已经把这些规则固化了”。

---

## 4. 按主题补读

如果已经读完上面的 8 份，还要继续接代码，可以按主题补读。

### 4.1 如果你要改主入口或参数

补读：

1. [OWNER_MAINLINE_CHANGE_CHECKLIST.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OWNER_MAINLINE_CHANGE_CHECKLIST.md)
2. [INTERFACE_FREEZE_AND_CHANGE_PROCESS.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/INTERFACE_FREEZE_AND_CHANGE_PROCESS.md)
3. [change_requests/README.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/change_requests/README.md)
4. [change_requests/00000000_change_request_template.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/change_requests/00000000_change_request_template.md)

原因：

1. 你需要先判断这个改动是不是必须走提案。
2. 你需要知道提案文档应该写哪些字段。
3. 你需要按 owner checklist 回看自己有没有漏掉 schema、回放、文档和 replay。

### 4.2 如果你要改 handoff / bridge-ready 明文暴露面

补读：

1. [BRIDGE_HANDOFF_HARDENING_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/BRIDGE_HANDOFF_HARDENING_PLAN.md)
2. [THREAT_MODEL_AND_LEAKAGE_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md)
3. [SSE_BRIDGE_APSI_PIPELINE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/SSE_BRIDGE_APSI_PIPELINE.md)
4. [OPS_RUNBOOK.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPS_RUNBOOK.md)

原因：

1. handoff 是 owner 主线上当前最敏感的剩余高风险点。
2. 任何扩大明文暴露面的改动都不应该先写代码后补理由。
3. 你必须同时看 threat 文档和 runbook，不然只会看到“能跑”，看不到“为什么不该这么跑”。

### 4.3 如果你要改 observability / audit / archive 验收面

补读：

1. [OPS_RUNBOOK.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPS_RUNBOOK.md)
2. [BENCHMARK_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/BENCHMARK_PLAN.md)
3. [SSE_BRIDGE_APSI_PIPELINE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/SSE_BRIDGE_APSI_PIPELINE.md)

重点看：

1. `mainline_contract_check/v1`
2. `audit_chain.json`
3. `audit_chain.seal.json`
4. `mainline_contract_summary`
5. `handoff_cleanup` stage
6. `platform_health` completed-run checks

### 4.4 如果你要改 recovery service 边界

补读：

1. [THREAT_MODEL_AND_LEAKAGE_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md)
2. [SSE_BRIDGE_APSI_PIPELINE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/SSE_BRIDGE_APSI_PIPELINE.md)
3. [RECORD_RECOVERY_INDEPENDENT_SERVICE_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/RECORD_RECOVERY_INDEPENDENT_SERVICE_PLAN.md)

原因：

1. recovery service 还不是最终独立部署边界。
2. 当前只是受控边界，不是完整服务治理边界。
3. 这是 owner 主线剩余的重要技术债之一。

---

## 5. 哪些文档先不要读

如果你接的是 owner 主线，下面这些文档不要一开始就读：

1. [TASK_ENGINEER_A_CONTROL_PLANE_IDENTITY_ACCESS.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_ENGINEER_A_CONTROL_PLANE_IDENTITY_ACCESS.md)
2. [TASK_ENGINEER_B_QUERY_CATALOG_WORKFLOW_OBSERVABILITY.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_ENGINEER_B_QUERY_CATALOG_WORKFLOW_OBSERVABILITY.md)
3. [DELEGATION_ENGINEER_1_AUDIT_OPS.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/DELEGATION_ENGINEER_1_AUDIT_OPS.md)
4. [DELEGATION_ENGINEER_2_SQL_CONTROL_PLANE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/DELEGATION_ENGINEER_2_SQL_CONTROL_PLANE.md)
5. [CONTROL_PLANE_SCHEMA.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/CONTROL_PLANE_SCHEMA.md)
6. [IAM_AUTHZ_INTEGRATION_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/IAM_AUTHZ_INTEGRATION_PLAN.md)
7. [KMS_SECRET_BACKEND_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/KMS_SECRET_BACKEND_PLAN.md)
8. [QUERY_INTERFACE_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/QUERY_INTERFACE_PLAN.md)
9. [CATALOG_LINEAGE_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/CATALOG_LINEAGE_PLAN.md)
10. [OBSERVABILITY_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OBSERVABILITY_PLAN.md)

不是说这些文档没用。

而是说：

1. 它们更多是外围能力、sidecar、平台化扩展。
2. owner 主线接手时，先把主链路 contract 和边界看懂更重要。
3. 等你确认这次要动到哪个外围能力，再有针对性补读。

---

## 6. 下个会话读完后应该能回答的问题

如果上面的最小必读集合已经读完，你应该能回答下面这些问题：

1. owner 这条线到底负责哪些文件和语义。
2. 哪些 CLI / schema / 输出路径不能静默改。
3. `job_id`、`correlation_id`、`caller` 等字段的稳定含义是什么。
4. `mainline_contract_check.json` 是做什么的。
5. 为什么 `audit_chain.json` 现在要嵌入 `mainline_contract_check/v1`。
6. 为什么 observability 里会出现 `handoff_cleanup` stage。
7. 为什么 `platform_health` 现在不只是查文件存在，还要查 embedded mainline contract。
8. 为什么 archive index / verify report 现在也要带 `mainline_contract_summary`。
9. 现在主线还没收完的风险主要是什么。
10. 如果再改 handoff、recovery boundary、release policy，是否必须先写 change request。

如果这些问题还答不上来，说明阅读顺序不对，或者前 8 份还没真正读完。

---

## 7. 当前建议的接手动作

读完之后，不要立刻写代码。

先做这 4 件事：

1. 对照 [CORE_CONTRACT_FREEZE_MATRIX.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/CORE_CONTRACT_FREEZE_MATRIX.md) 列出这次准备改动的字段和载体。
2. 对照 [THREAT_MODEL_AND_LEAKAGE_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md) 判断改动会不会扩大泄漏面。
3. 对照 [INTERFACE_FREEZE_AND_CHANGE_PROCESS.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/INTERFACE_FREEZE_AND_CHANGE_PROCESS.md) 判断是否必须先提案。
4. 对照 [BENCHMARK_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/BENCHMARK_PLAN.md) 和 [OPS_RUNBOOK.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OPS_RUNBOOK.md) 判断改完后应该跑哪类验证。

这样接手效率会比“先看代码，再猜文档”高很多。

---

## 8. 一句话版本

如果只记一句话：

```text
先读 owner 任务书、冻结流程、冻结矩阵、threat/leakage、handoff 收紧，再读主链路总览、runbook、benchmark；不要一上来先钻外围 sidecar 文档。
```
