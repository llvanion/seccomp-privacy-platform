# 实验报告用详细总结

本文给出一版可直接写入实验报告的详细总结，重点说明本项目在答辩演示中展示了哪些能力、各模块承担什么职责、实验环境如何搭建、系统实际完成了哪些任务，以及目前能力边界和局限性。

---

## 1. 实验目标

本实验的目标不是单独验证某一个密码学原语，而是验证一套**面向隐私数据合作场景的端到端平台 baseline** 是否已经建立完成。平台围绕以下核心问题展开：

1. 如何在不交换用户明细的前提下完成跨方联合计算。
2. 如何把密文候选检索、受控恢复、令牌化、私有求交、策略发布组织成一条完整主链路。
3. 如何为这条主链路补齐控制面、审计面、可观测性、安全门禁与合规映射。

本项目最终要证明的是：系统已经不仅仅停留在“可以运行一个 PJC 算法”，而是形成了一套从**查询请求进入、隐私计算执行、结果发布、证据留存到治理复盘**的完整工程链路。

---

## 2. 系统总体思路

系统采用分阶段流水线设计，主链路为：

`SSE 候选导出 -> 记录恢复服务 -> Rust Bridge 令牌化 -> PJC 私有求交与聚合 -> 策略发布 -> 审计链与观测导出`

各阶段职责如下：

### 2.1 SSE 候选导出

SSE 模块负责对倒排索引进行加密并支持关键字搜索。其作用不是直接完成统计，而是先将潜在相关记录收缩到一个较小候选集，为后续桥接和求交降低暴露面和计算量。

### 2.2 记录恢复服务

记录恢复服务位于“最接近明文”的边界位置，负责在策略约束下恢复有限字段，并通过独立服务边界、审计日志、权限检查和 mTLS 机制降低明文暴露风险。

### 2.3 Rust Bridge

Bridge 模块负责对 join key 做标准化处理，并生成带作用域限制的 HMAC token。它的核心目标是：**绝不把原始 join key 直接送入 PJC**，而是通过桥接层将身份关联信息转化为可计算但不可逆的令牌。

### 2.4 PJC 私有求交

PJC 模块完成双方隐私集合求交与聚合求和。该模块输出的是交集大小、聚合值等结果，而不是参与方的原始数据明细。

### 2.5 策略发布

策略发布阶段负责对 PJC 输出执行二次治理，包括：

- k 阈值检查
- 重复查询拒绝
- 隐私预算检查
- 近重复/差分探测
- 可选差分隐私参数约束

最终生成对外可展示的 `public_report.json`，并写入可重放的策略审计记录。

### 2.6 审计链与派生视图

系统在运行完成后，还会进一步生成：

- `audit_chain.json`
- `audit_chain.seal.json`
- `pipeline_observability.json`
- `catalog_lineage.json` 或其派生摘要
- `mainline_contract_check.json`

这保证系统不仅“算出了结果”，还能够复盘每一步、验证工件完整性，并向 reviewer 提供最小必要证据。

---

## 3. 实验平台组成

本项目的实验平台由以下几个部分构成：

### 3.1 计算主链路模块

- `sse/`：密文关键字检索、加密记录存储、导出策略
- `services/record_recovery/`：独立记录恢复服务
- `bridge/`：Rust 令牌化桥接器
- `a-psi/`：PJC 与策略发布逻辑

### 3.2 控制面与读侧 sidecar

- `scripts/serve_operator_dashboard.py`：operator dashboard 与前端静态资源服务
- `scripts/serve_metadata_api.py`：metadata 只读侧边车
- `scripts/serve_query_workflow_api.py`：查询工作流入口
- `scripts/serve_audit_query_api.py`：审计与公开报告查询接口
- `scripts/serve_platform_health_api.py`：平台健康聚合接口

### 3.3 前端面板

前端位于 `console/`，是基于 Vite + React + TypeScript 的单页应用，提供统一的 Operator Console。该面板覆盖：

- 平台首页
- 作业管理
- 请求提交与审批
- 隐私预算审批
- SSE 独立查询
- PJC 独立运行
- 审计与公开报告
- 目录与血缘
- 业务访问工作台
- 权限 / IAM / KMS
- Recovery / mTLS
- Observability
- Security
- Compliance

因此，本实验展示的是一个“可操作的控制台”，而不是一个只展示结果的静态页面。

---

## 4. 实验环境与样例数据

为保证答辩演示稳定，本实验采用“**已有 completed run + 少量现场轻量触发**”的策略。

此外，为避免演示依赖开发期间残留的临时目录，本项目还补充了一套可重复生成的自包含 demo 资产：

```bash
python3 scripts/prepare_defense_demo.py --out-dir tmp/defense_demo
bash scripts/start_defense_demo.sh "$PWD/tmp/defense_demo"
```

其中：

- `prepare_defense_demo.py` 负责复制 completed run、整理 metadata/审批样例、补充 registry 与 identity token 配置、生成统一 manifest。
- `start_defense_demo.sh` 负责一键启动 metadata/query/audit/platform-health/dashboard 等 sidecar。
- `stop_defense_demo.sh` 负责统一停止演示环境。

答辩默认启动方式采用“本地开放模式”，即：

- dashboard 与读侧 sidecar 默认不强制浏览器先提交 bearer token
- 这样可以避免现场一打开主界面就因鉴权配置而中断演示
- 如需展示 identity token / session cookie / redaction 行为，可另行开启鉴权版环境

因此，本实验环境既可以基于已有 `tmp/` 样例目录手工启动，也可以通过上述脚本自动生成并拉起。

### 4.1 主演示 completed run

使用目录：

`tmp/live_sse_bridge_demo/run-20260504T023757Z`

该目录包含：

- `a_psi_run/public_report.json`
- `a_psi_run/attribution_result.json`
- `audit_chain.json`
- `audit_chain.seal.json`
- `pipeline_observability.json`
- `observability_dashboard.json`
- `platform_health.json`
- `mainline_contract_check.json`
- `bridge_job/server.csv`
- `bridge_job/client.csv`
- `sse_exports/export_audit.jsonl`
- `sse_exports/record_recovery_service_audit.jsonl`

这说明主链路已经真实跑通，并留下了完整运行证据。

### 4.2 辅助 metadata 与审批样例

实验中还使用以下样例数据库和目录：

- 基础 metadata：`tmp/platform_metadata.db`
- 业务访问样例：`tmp/business_access_api_smoke/metadata.sqlite`
- 隐私预算审批样例：`tmp/privacy_budget_approval_api_smoke/metadata.sqlite`
- 隐私预算存储：`tmp/privacy_budget_approval_api_smoke/budget.sqlite`

### 4.3 SSE 与 PJC 轻量输入

独立演示时使用仓库内自带小样例：

- SSE 检索：
  - `sse/example_db.json`
- PJC-only：
  - `bridge/examples/server_export.csv`
  - `bridge/examples/client_export.csv`

这些样例的优点是规模小、可重复、可快速完成现场触发。

### 4.4 两机 PJC 实测补充

除本地 completed run 与轻量样例外，本项目在 `2026-06-21` 还完成了一轮**真实两机 PJC** 补充验证：

- Party A / VPS Tailscale IP：`100.101.31.53`
- Party B / laptop Tailscale IP：`100.99.96.96`
- VPS 公网 IP：`118.190.61.66`

这轮验证的重要意义在于，它不再是“同机伪双机”或单纯 `pjc-only`，而是：

1. 使用真实 Party A / Party B 主机；
2. 使用真实 mTLS 证书与真实网络路径；
3. 使用真实 `run_pjc_bucketed_tls_server.sh` / `run_pjc_bucketed_tls_client.sh` 包装链；
4. 实际写出 Party B 各 bucket 的 `attribution_result.json`。

需要如实说明的是：

- 当前**不是通过 `/pjc-two-party` 页面一键闭环跑通**；
- 而是前端工作台已经把真实鉴权和相关端点接上，随后通过 shell 驱动同一套真实运行参数把两机链路跑通。

### 4.5 两机 PJC 当前实测结果

Party B 结果目录：

- [tmp/pjc_bucketed_scale_cross-vps-008_cleanrun/party_b_job](/home/llvanion/Desktop/seccomp-privacy-platform/tmp/pjc_bucketed_scale_cross-vps-008_cleanrun/party_b_job)

8 个 bucket 的结果为：

- `campaign_00`: `intersection_size=63`, `intersection_sum=315077`
- `campaign_01`: `intersection_size=48`, `intersection_sum=241500`
- `campaign_02`: `intersection_size=54`, `intersection_sum=268987`
- `campaign_03`: `intersection_size=51`, `intersection_sum=231368`
- `campaign_04`: `intersection_size=48`, `intersection_sum=268900`
- `campaign_05`: `intersection_size=52`, `intersection_sum=291843`
- `campaign_06`: `intersection_size=45`, `intersection_sum=224599`
- `campaign_07`: `intersection_size=59`, `intersection_sum=294999`

合计：

- `bucket_count = 8`
- `intersection_size_total = 420`
- `intersection_sum_total = 2137273`

这组结果表明：项目不仅在本地 completed run 场景下可演示，也已经在真实两机 Tailscale 场景下拿到了有效聚合输出。

### 4.6 当前面板测试建议

当前若要从面板侧试用真实双机 PJC，推荐使用两套 operator dashboard：

- VPS / Party A 面板：`http://100.101.31.53:18096/pjc-two-party`
- 本地 / Party B 面板：`http://127.0.0.1:18097/pjc-two-party`

这两套面板都已接入真实鉴权，其中：

- 远端面板已验证 `session/login` 与 `roles/server/start`
- 本地面板已验证 `session/login` 与 `roles/client/start`

因此，“面板测试”在当前阶段的正确表述是：

> 已经可以通过两套真实鉴权面板分别驱动 Party A 和 Party B 的角色启动；但还没有收敛成一个单页面实例统一控制两台机器的最终形态。

---

## 5. 实验演示环境搭建方式

实验采用构建后模式，即先构建前端，再由 dashboard server 提供静态页面。

### 5.1 前端构建

执行：

```bash
cd console
npm ci
npm run build
cd ..
```

构建后产物位于 `console/dist/`。

### 5.2 读侧 API 与 dashboard 启动

实验通过以下组件共同构成面板后端：

1. Metadata API
2. Query Workflow API
3. Audit Query API
4. Platform Health API
5. Operator Dashboard
6. Record Recovery HTTP Service

这样做的原因是：前端面板虽然通过同一个 UI 展示各模块能力，但其底层实际依赖多个控制面 sidecar，而不是一个单体进程。

### 5.3 配置方式

启动服务后，在 `/settings` 页面中填写：

- metadata API 地址
- query workflow API 地址
- audit query API 地址
- platform health API 地址
- record recovery 地址

从而让前端能统一访问这些后端。

---

## 6. 实验演示流程与可完成任务

本实验把系统能力分为“主链路能力”和“控制/治理能力”两大类。

### 6.1 主链路能力

#### 6.1.1 端到端主链路执行

通过 `/jobs` 和 `/jobs/:jobId` 页面，可以展示系统完整执行过一次：

`SSE -> recovery -> bridge -> PJC -> release`

在作业详情页中可以看到：

- 作业状态
- stage 时序
- 结果摘要
- 原始请求
- 关联工件

这证明系统具备完整流程调度能力，而不是单独执行某一步骤。

#### 6.1.2 SSE 独立关键字检索

通过 `/sse-query` 页面，可对 `sse/example_db.json` 执行关键字搜索，例如关键字 `China`。

该实验展示：

- 系统确实支持密文检索式预筛选
- 结果返回的是匹配文档标识，而不是业务明文
- SSE 可作为后续隐私计算主链路的前置环节独立运行

#### 6.1.3 PJC 独立运行

通过 `/pjc-only` 页面，输入现成的 `server.csv` 和 `client.csv`，可以单独触发：

- PJC 求交
- 聚合求和
- 策略发布

该实验展示：

- PJC 部分可以独立工作
- 策略发布不依赖整条主链路才能成立
- 输出以 `attribution_result.json` 和 `public_report.json` 的形式呈现

#### 6.1.4 聚合结果发布

在 `public_report.json` 中可以看到：

- `intersection_size`
- `intersection_sum`
- `released`
- `reason_code`

这说明系统对外发布的是**受治理的聚合结果**，而不是裸输出。

### 6.2 控制面与治理能力

#### 6.2.1 查询请求工作流

通过 `/requests`、`/requests/submit` 和 `/requests/:id` 页面，可以展示：

- 查询请求以结构化 payload 形式进入系统
- 请求需要先提交，再审批
- 审批动作有状态流转和历史记录

这说明平台具有基础工作流能力，而不是“任何人都能随时发起一次隐私查询”。

#### 6.2.2 隐私预算审批

通过 `/privacy-budget-approvals` 页面，可以展示：

- 待审批请求
- 已批准请求
- 已拒绝请求
- 已过期请求

并且每条记录可查看：

- `reason_code`
- `matched_prior_relation`
- `budget`
- `latest_decision`

这表明系统已经实现了近重复查询、差分探测、预算消耗等治理逻辑。

#### 6.2.3 业务字段级访问控制

通过 `/business-access` 页面，系统可演示不同角色的字段级权限决策。例如：

- Merchant Staff
- Buyer Self-Service
- Support Case
- Courier Next Stop
- Fraud Review
- Field Marketer

系统支持输出字段级的：

- `allow`
- `mask`
- `deny`

并可直接预览筛选后的业务读取结果。

这说明平台的权限控制已经细化到“字段级业务暴露”，而不仅是接口级允许/拒绝。

#### 6.2.4 权限 / IAM / KMS / OpenFGA

通过 `/permissions/*` 页面，可以展示：

- caller 列表
- policy / bindings
- caller-permissions 摘要
- keyring 与 KMS 说明
- OpenFGA tuple/export 集成说明

这表明平台已经对身份、策略、密钥与外部授权后端做出统一建模。

---

## 7. 审计、可观测性与证据能力

### 7.1 审计链

通过 `/audit/chain` 页面，可以查看 `audit_chain.json`。

该能力表明：

- 系统每次运行都有结构化审计记录
- 审计链可用于 reviewer 复核
- 审计结果不是只存在于日志文本，而是进入固定契约结构

### 7.2 审计密封

通过 `audit_chain.seal.json` 及其相关安全页说明，可以证明：

- 审计链支持 seal
- 后续可以进行篡改检测和归档验证

### 7.3 公开报告

通过 `/audit/public-report` 页面，可以展示最终外部可见的公开报告内容，反映：

- 发布与否
- 原因码
- 聚合结果

这对答辩非常关键，因为它体现了“系统最终对外输出的是什么”。

### 7.4 Observability 事件流

通过 `/observability/events` 与 `/audit/observability` 页面，可以查看：

- stage 事件流
- 状态变化
- 组件健康
- 失败/告警情况

这说明平台具备可运维性和故障分析能力。

### 7.5 Catalog / Lineage

通过 `/audit/lineage` 和 `/catalog/*` 页面，可以展示：

- 数据集与服务之间的关系
- 派生视图
- 作业与工件之间的血缘

这表明平台具备“结果从何而来”的可解释性。

---

## 8. Recovery 与 mTLS 能力

通过 `/recovery/*` 页面，可以展示 record recovery 服务的独立治理能力，包括：

1. 服务健康状态
2. Prometheus 指标
3. Party A / Party B 的 mTLS bootstrap
4. TLS 诊断与负面案例检查

该模块证明：

- 记录恢复边界并非直接嵌入主进程，而是独立服务
- 系统已经考虑明文边界保护
- 系统支持 mTLS、preflight、diagnostic 等工程化安全功能

---

## 9. 安全与合规能力

### 9.1 安全工具页

通过 `/security/*` 页面，可以展示以下能力已经被纳入平台交付：

- 审计篡改检测
- HTTP 异常输入 gate
- mTLS benchmark
- repo / dependency hygiene
- 契约 smoke
- benchmark 画廊

这说明平台不仅“有功能”，还具备验证这些功能正确性与安全性的配套机制。

### 9.2 合规页

通过 `/compliance/*` 页面，可以展示：

- GDPR Article 5(1) 映射
- Article 15-22 数据主体权利映射
- threat model 摘要
- reviewer checklist
- license 与依赖说明

这说明项目已经把法律与合规要求显式整理进系统交付，而不是停留在代码和脚本层面。

---

## 10. 实验结果总结

从答辩 demo 的整体展示来看，本项目已经完成以下任务：

1. 完成了 SSE 关键字检索与候选导出能力。
2. 完成了记录恢复服务及其服务边界管理。
3. 完成了 Rust Bridge 对 join key 的标准化和 HMAC 令牌化。
4. 完成了 PJC 求交与聚合求和。
5. 完成了策略发布与公开报告生成。
6. 完成了审计链、密封与可重放审计记录。
7. 完成了基于 Web 的 Operator Console。
8. 完成了请求提交、审批、状态流转等控制面能力。
9. 完成了隐私预算审批和近重复查询治理。
10. 完成了业务字段级访问控制工作台。
11. 完成了平台健康、审计读侧、可观测性与血缘读侧接口。
12. 完成了 recovery/mTLS 诊断、preflight 与 bootstrap 流程。
13. 完成了多类安全 gate、contract smoke 与 benchmark 工具。
14. 完成了合规映射、威胁模型与 reviewer checklist 的文档化。

换句话说，本项目已经形成一个**可运行、可演示、可治理、可审计、可复盘**的隐私计算平台 baseline。

---

## 11. 项目当前边界与局限性

虽然本项目的 baseline 和本地演示能力已经较为完整，但实验中也应如实说明其边界：

1. 当前仓库中的结论主要证明“本地/半诚实 demo 假设下主链路可用并可验证”。
2. 某些“生产安全完全闭环”的目标仍不应夸大为已经全部完成。
3. 前端中的部分页面属于“说明型运维入口”或“证据展示入口”，并不是每个页面都直接提供写操作。
4. sidecar 架构表明系统是平台化设计，但也意味着部署时需要同时启动多个组件。

因此，本实验的正确表述应是：

> 本项目已经实现了一套结构完整、能力闭环的隐私计算平台原型与 baseline，能够通过统一面板展示并驱动主链路、治理链路和审计链路；但“生产级安全完成声明”仍需基于更严格的部署证据和运行验证来做出。

---

## 12. 结论

通过本次实验与答辩演示，可以得出以下结论：

1. 系统已经不再是单点算法验证，而是形成了完整的隐私计算平台结构。
2. 主链路从 SSE 到 PJC 再到策略发布已经真实可运行。
3. 平台已经补齐了与真实应用场景相关的工程能力，包括请求治理、字段级授权、健康检查、审计链、观测、安全 gate 与合规映射。
4. Operator Console 使这些能力能够以统一界面进行演示和操作，显著增强了系统的可展示性、可验证性和可运维性。

因此，从实验报告角度，本项目可以被总结为：

> 一个面向隐私数据合作场景的、具备主链路执行、控制面治理、审计追踪、安全验证与合规映射能力的隐私计算平台 baseline。
