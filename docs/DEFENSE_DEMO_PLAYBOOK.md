# 答辩 Demo Playbook

本文件给出一套适合答辩现场使用的 demo 方案，目标不是覆盖“生产部署细节”，而是用最稳定、最少现场风险的方式，把这个项目**已经能完成的任务**完整展示出来，并且尽量通过 **Operator Console 面板** 演示。

这份方案分三部分：

1. 演示前准备什么
2. 答辩当天按什么顺序展示
3. 每个面板页面对应证明什么能力

---

## 1. Demo 目标

建议把本项目定义成一个“**隐私计算查询平台 baseline**”，现场要证明的不是单个算法，而是整条可审计链路：

`SSE 候选导出 -> 受控记录恢复 -> Rust bridge 令牌化 -> PJC 求交 -> 策略发布 -> 审计/观测/权限/合规`

答辩时建议突出 4 件事：

1. 系统真的能跑通主链路，并且输出的是**聚合值**，不是明文用户数据。
2. 系统不只有算法，还提供了**控制面**：请求提交、审批、权限、审计、健康检查、可观测性。
3. 系统对“数据最小化、可审计、防重复查询、隐私预算、mTLS、字段级授权”这些工程问题有明确实现。
4. 前端面板不是静态 PPT，而是可以驱动任务、查看工件、查看审计与安全证据的实际操作界面。

---

## 2. 推荐 Demo 策略

答辩现场不建议所有东西都“现算一遍”。更稳的方式是：

1. **主链路准备一份已跑完的 completed run**
2. **面板里现场再触发 2-3 个轻量动作**
3. 其余能力通过面板直接查看已有工件、审计链、权限与安全报告

推荐组合：

- 主链路 completed run：`tmp/live_sse_bridge_demo/run-20260504T023757Z`
- 第二份 completed run（更轻量 dashboard fixture）：`tmp/operator_dashboard_jobtest2`
- Metadata DB：
  - 主链路/基础控制面：`tmp/platform_metadata.db`
  - 业务访问工作台：`tmp/business_access_api_smoke/metadata.sqlite`
  - 隐私预算审批：`tmp/privacy_budget_approval_api_smoke/metadata.sqlite`
- 隐私预算 store：
  - `tmp/privacy_budget_approval_api_smoke/budget.sqlite`
  - `tmp/privacy_budget_approval_api_smoke/approval_queue.jsonl`
  - `tmp/privacy_budget_approval_api_smoke/approval_decisions.jsonl`

原因：

- `tmp/live_sse_bridge_demo/run-20260504T023757Z` 已包含：
  - `public_report.json`
  - `audit_chain.json`
  - `audit_chain.seal.json`
  - `pipeline_observability.json`
  - `observability_dashboard.json`
  - `platform_health.json`
  - `mainline_contract_check.json`
  - `bridge_job/*.csv`
  - `sse_exports/*`
- 这意味着面板里的 `home`、`jobs`、`audit`、`observability`、`recovery`、`catalog lineage` 都能直接展示。

### 2.1 两机 PJC 当前状态说明

截至 `2026-06-21`，真实双机 PJC 已经在 **Tailscale 两机链路** 上跑通，并且拿到了多 bucket 的真实结果；但这次跑通**还不是通过 `/pjc-two-party` 页面一键闭环实现**，而是通过同一套真实证书、真实 host、真实 role 目录和真实 wrapper，由 shell 驱动完成。

当前机器对应关系：

- 笔记本 Tailscale IP：`100.99.96.96`
- VPS Tailscale IP：`100.101.31.53`
- VPS 公网 IP：`118.190.61.66`

本轮验证里，已经确认：

1. `100.101.31.53` 路径上的最小 mTLS `socat OPENSSL-LISTEN` 可以稳定完成 `TLSv1.3` 握手。
2. VPS 上真实 Party A PJC wrapper 可以启动：
   - PJC server loopback：`127.0.0.1:10501`
   - TLS proxy：`100.101.31.53:10594`
3. 本机真实 Party B bucketed TLS client 已成功跑通多个 bucket，并写出 `attribution_result.json`。

这意味着：

- “双机 PJC 协议不可用”已经不是事实。
- 当前剩余差距是：**把这套已经成功的 host/port/runtime 参数完全收敛回前端工作台，做到面板闭环**。

### 2.2 本轮真实双机 bucket 结果

Party B 结果目录：

- [tmp/pjc_bucketed_scale_cross-vps-008_cleanrun/party_b_job](/home/llvanion/Desktop/seccomp-privacy-platform/tmp/pjc_bucketed_scale_cross-vps-008_cleanrun/party_b_job)

已确认的 8 个 bucket 聚合结果：

- `campaign_00`: `intersection_size=63`, `intersection_sum=315077`
- `campaign_01`: `intersection_size=48`, `intersection_sum=241500`
- `campaign_02`: `intersection_size=54`, `intersection_sum=268987`
- `campaign_03`: `intersection_size=51`, `intersection_sum=231368`
- `campaign_04`: `intersection_size=48`, `intersection_sum=268900`
- `campaign_05`: `intersection_size=52`, `intersection_sum=291843`
- `campaign_06`: `intersection_size=45`, `intersection_sum=224599`
- `campaign_07`: `intersection_size=59`, `intersection_sum=294999`

总计：

- `bucket_count = 8`
- `intersection_size_total = 420`
- `intersection_sum_total = 2137273`

如果答辩当天要展示“两机真实成功”，优先展示这批现成结果与对应日志/工件，而不要退回本地单机 `pjc-only`。

### 2.3 当前可直接试用的双面板入口

为了让 reviewer 或 operator 直接“从面板尝试”双机 PJC，当前建议使用**两个面板实例**，分别代表两台机器：

- **Party A / VPS 面板**：
  - `http://100.101.31.53:18096/pjc-two-party`
- **Party B / laptop 面板**：
  - `http://127.0.0.1:18097/pjc-two-party`

说明：

1. 远端 `18096` 已经是带真实鉴权的 full operator dashboard，并且可以成功执行：
   - `session/login`
   - `roles/server/start`
2. 本地 `18097` 已经是带真实鉴权的本地专用 dashboard，并且可以成功执行：
   - `session/login`
   - `roles/client/start`

因此，如果要“从面板跑一遍”，当前推荐操作方式不是一个页面控制两台机器，而是：

1. 在 **VPS 面板** 上完成 Party A 的 `prepare / preflight / server start`
2. 在 **本地面板** 上完成 Party B 的 `enroll / preflight / client start`
3. 再根据工件位置继续查看 status、结果和后续证据

这已经属于“面板驱动真实两机链路”，但还不是“一个页面单实例控制两台机器”的最终形态。

---

## 3. 演示前准备

### 3.0 推荐直接使用自包含答辩 demo

现在仓库里已经补了一套**可重复生成**的答辩 demo 资产，不必再依赖你当前 `tmp/` 目录里已有的零散文件。

先生成：

```bash
python3 scripts/prepare_defense_demo.py --out-dir tmp/defense_demo
```

它会生成：

- `tmp/defense_demo/runs/main_completed_run`
- `tmp/defense_demo/runs/operator_fixture_run`
- `tmp/defense_demo/db/platform_metadata.db`
- `tmp/defense_demo/db/business_access.sqlite`
- `tmp/defense_demo/db/privacy_budget.sqlite.metadata`
- `tmp/defense_demo/db/privacy_budget.sqlite`
- `tmp/defense_demo/config/identity_tokens.json`
- `tmp/defense_demo/config/query_request.json`
- `tmp/defense_demo/env.demo.sh`
- `tmp/defense_demo/defense_demo_manifest.json`

然后一键启动：

```bash
bash scripts/start_defense_demo.sh "$PWD/tmp/defense_demo"
```

停止：

```bash
bash scripts/stop_defense_demo.sh "$PWD/tmp/defense_demo"
```

如果你使用这套自包含 demo，下面 3.3 到 3.7 的手工启动步骤可以作为“原理说明”保留，但实际答辩时建议直接用 `prepare + start`。

### 3.1 构建前端

```bash
cd console
npm ci
npm run build
cd ..
```

### 3.2 启动一套“答辩用” sidecar

注意：`serve_operator_dashboard.py` 只负责 dashboard、jobs、requests、PJC/mTLS 这类接口；`catalog`、`audit`、`observability`、`platform health`、`business access` 还需要单独 sidecar。

建议开两套环境：

1. **主演示环境**：围绕 `tmp/live_sse_bridge_demo/run-20260504T023757Z`
2. **业务访问/隐私预算补充环境**：按需切换 `/settings`

本答辩 demo 的默认脚本采用**本地开放模式**：

- 不强制要求浏览器先建立 identity session
- 打开面板即可直接访问 dashboard 与 sidecar
- 更适合答辩现场稳定展示

如果你要额外展示“身份令牌 / HttpOnly session / caller-safe redaction”，建议在答辩最后单独说明，或另起一套 auth 开启环境。

如果你要使用**真实鉴权模式**，请用：

```bash
DEFENSE_DEMO_REQUIRE_AUTH=1 bash scripts/start_defense_demo.sh "$PWD/tmp/defense_demo"
```

此时主面板会通过同源 `/proxy/metadata`、`/proxy/query`、`/proxy/audit`、`/proxy/health` 转发到各 sidecar，使浏览器上的 HttpOnly session cookie 可以被统一带过去。

### 3.3 主演示环境启动命令

启动 metadata：

```bash
python3 scripts/serve_metadata_api.py \
  --db-path tmp/platform_metadata.db \
  --bind-host 127.0.0.1 \
  --port 18090
```

启动 query workflow：

```bash
python3 scripts/serve_query_workflow_api.py \
  --bind-host 127.0.0.1 \
  --port 18091 \
  --allow-execute
```

启动 audit query：

```bash
python3 scripts/serve_audit_query_api.py \
  --out-base tmp/live_sse_bridge_demo/run-20260504T023757Z \
  --bind-host 127.0.0.1 \
  --port 18092
```

启动 platform health：

```bash
python3 scripts/serve_platform_health_api.py \
  --bind-host 127.0.0.1 \
  --port 18093
```

启动 operator dashboard：

```bash
python3 scripts/serve_operator_dashboard.py \
  --out-base "$PWD/tmp/live_sse_bridge_demo/run-20260504T023757Z" \
  --history-root "$PWD/tmp/live_sse_bridge_demo" \
  --metadata-db-path "$PWD/tmp/platform_metadata.db" \
  --console-dist "$PWD/console/dist" \
  --bind-host 127.0.0.1 \
  --port 18094
```

### 3.4 启动业务访问工作台环境

`/business-access` 页面依赖 `business_access/check` 和 `business_data/read-preview`，推荐单独用业务访问样例 DB：

```bash
python3 scripts/serve_metadata_api.py \
  --db-path tmp/business_access_api_smoke/metadata.sqlite \
  --bind-host 127.0.0.1 \
  --port 18190 \
  --business-access-policy config/business_access_policy.ecommerce.example.json
```

### 3.5 启动隐私预算审批环境

如果要现场演示 `/privacy-budget-approvals`，建议单独开一套 dashboard：

```bash
python3 scripts/serve_operator_dashboard.py \
  --out-base "$PWD/tmp/operator_dashboard_jobtest2" \
  --history-root "$PWD/tmp" \
  --metadata-db-path "$PWD/tmp/privacy_budget_approval_api_smoke/metadata.sqlite" \
  --privacy-budget-store "$PWD/tmp/privacy_budget_approval_api_smoke/budget.sqlite" \
  --privacy-budget-approval-queue "$PWD/tmp/privacy_budget_approval_api_smoke/approval_queue.jsonl" \
  --privacy-budget-approval-decisions "$PWD/tmp/privacy_budget_approval_api_smoke/approval_decisions.jsonl" \
  --console-dist "$PWD/console/dist" \
  --bind-host 127.0.0.1 \
  --port 18194
```

### 3.6 启动 record recovery HTTP 服务

这样 `/recovery/service` 和 `/recovery/metrics` 能展示实时状态：

```bash
export SSE_RECORD_RECOVERY_TOKEN=demo-recovery-token

python3 scripts/manage_record_recovery_service.py start \
  --config config/record_recovery_http_service.example.json
```

### 3.7 面板 Settings 怎么配

打开 `http://127.0.0.1:18094/settings`，填：

- `Operator dashboard`: 留空
- `Metadata sidecar`: `http://127.0.0.1:18090`
- `Query workflow`: `http://127.0.0.1:18091`
- `Audit query`: `http://127.0.0.1:18092`
- `Platform health`: `http://127.0.0.1:18093`
- `Record recovery HTTP`: `http://127.0.0.1:18081`

注意：

- `operator` 本身如果同源就可以留空。
- 这套答辩 demo 默认不要求 metadata/query/audit/health 额外填 token。
- `record recovery` 若使用 `config/record_recovery_http_service.example.json`，通常仍需要它自己的 token，即 `demo-recovery-token`。
- `/business-access` 演示前，把 `Metadata sidecar` 临时改到 `http://127.0.0.1:18190`。
- `/privacy-budget-approvals` 演示时建议直接打开 `http://127.0.0.1:18194` 这一套面板。

---

## 4. 答辩当天推荐展示顺序

建议 12 到 18 分钟，按下面顺序走。

### 第一段：平台总览

打开：

- `/home`

讲法：

- 这是平台总览页，不是单算法 demo。
- 能看到平台健康、最近作业、告警、contract 摘要。
- 先建立“这是一个控制面 + 审计面 + 算法执行面整合的平台”的认知。

现场重点看：

- 活跃作业
- 最近作业
- 平台健康
- 主链路 contract 摘要

### 第二段：端到端主链路

打开：

- `/jobs`
- 再点进一个 completed run 的 `/jobs/:jobId`

建议讲：

1. 用户请求不是直接给 PJC
2. 先经过 SSE 候选导出
3. 再进入 record recovery 边界
4. 再由 Rust bridge 做 join key 规范化和 HMAC 令牌化
5. 最后才进入 PJC 与策略发布

重点展示：

- Job detail 页里的 `Stage 时序`
- `结果摘要`
- `原始请求`

要强调：

- 输出是 `intersection_size` 和 `intersection_sum`
- 不暴露原始 join key
- `public_report` 和 `audit_chain` 是后续审计的依据

### 第三段：独立能力 1，SSE 检索

打开：

- `/sse-query`

演示方式：

- 直接用 `sse/example_db.json`
- keyword 填 `China`
- 执行一次

讲法：

- 这证明平台前半段不是“假装有 SSE”，而是真的能独立完成加密关键字检索。
- 它返回的是命中的 document id，不是直接暴露业务明细。

### 第四段：独立能力 2，PJC-only

打开：

- `/pjc-only`

输入建议：

- `server_csv`: `bridge/examples/server_export.csv`
- `client_csv`: `bridge/examples/client_export.csv`
- `job_meta`: `bridge/out/demo_job/job_meta.json` 或留空
- `threshold_k = 1`
- `max_queries = 5`

讲法：

- 这页跳过 SSE 和 bridge，证明 PJC + 策略发布可以独立运行。
- 如果评委问“你们是不是只是脚本拼接”，这里可以说明每一段都能单独验证。

现场重点看：

- `attribution_result.json`
- `public_report.json`
- `released / withheld`
- `reason_code`

### 第五段：请求工作流与审批

打开：

- `/requests`
- `/requests/submit`
- `/requests/:id`

讲法：

- 平台不是谁都能发起查询。
- 查询请求要进入 workflow，审批通过后才会触发执行。
- 这对应数据访问治理和 operator control plane。

如果现场时间有限：

- 只展示“提交页模板”和“详情页状态/决策/转换历史”。
- 不一定要真执行一次 approve/reject。

### 第六段：隐私预算审批

打开另一套面板：

- `http://127.0.0.1:18194/privacy-budget-approvals`

讲法：

- 这里展示的是近重复查询、差分攻击探测、预算耗尽这类 release gate。
- 说明平台不是“能算就算”，而是对重复查询和近似查询有阻断机制。

现场重点看：

- `pending_approval / approved / rejected / expired`
- request detail 中的 `reason_code`、`matched_prior_relation`、`budget`

### 第七段：审计与可观测性

打开：

- `/audit/public-report`
- `/audit/chain`
- `/audit/observability`
- `/audit/lineage`
- `/observability/overview`
- `/observability/events`

讲法：

- 任何一次运行不止产生结果，还产生审计链和观测事件。
- `audit_chain.json` 和 `audit_chain.seal.json` 可以支持篡改检测。
- `pipeline_observability`、`catalog_lineage` 用于 operator / reviewer 复盘。

现场重点看：

- `public_report/v1`
- `audit_chain/v1`
- observability 事件流
- catalog lineage

### 第八段：业务访问工作台

把 `/settings` 里的 Metadata Base URL 改成 `http://127.0.0.1:18190`，然后打开：

- `/business-access`

建议使用页面自带 role preset：

- `Merchant Staff`
- `Buyer Self-Service`
- `Support Case`
- `Courier Next Stop`
- `Fraud Review`
- `Field Marketer`

讲法：

- 这里演示的是字段级访问控制。
- 平台不仅控制“能不能发起查询”，还控制“哪些业务字段能看、哪些字段要 mask、哪些字段必须 deny”。

现场重点看：

- `Business Access Check`
- `Business Read Preview`
- 字段级 `allow / mask / deny`

这是答辩里最能体现“平台化”和“业务落地”的页面之一。

### 第九段：权限 / IAM / KMS

打开：

- `/permissions/callers`
- `/permissions/keys`
- `/permissions/kms`
- `/permissions/openfga`

讲法：

- 这里说明 caller、policy、keyring、外部 KMS、OpenFGA 适配器已经考虑进去。
- 页面里有些部分是说明型，不是前端直接写入操作，但能证明项目边界完整。

建议少讲实现细节，多讲“为什么需要这一层”：

- 防止 operator、caller、service 混用权限
- 为 token secret、mTLS 证书、外部密钥后端提供统一入口

### 第十段：Recovery / mTLS

打开：

- `/recovery/service`
- `/recovery/metrics`
- `/recovery/mtls`
- `/recovery/diagnostics`

讲法：

- record recovery 是平台里最接近“明文边界”的部分，因此必须单独治理。
- 这里可以展示服务健康、Prometheus 指标、mTLS bootstrap、TLS 诊断。

如果时间紧：

- 展示 `service` 和 `metrics`
- 再展示 `mtls bootstrap` 页里的 Party A / Party B 流程即可

### 第十一段：安全与合规

打开：

- `/security/benchmarks`
- `/security/contracts`
- `/security/tamper`
- `/security/malformed-gate`
- `/compliance/gdpr`
- `/compliance/threat-model`
- `/compliance/checklist`

讲法：

- 这部分不是“锦上添花”，而是答辩拉开差距的地方。
- 说明平台已经把 contract、tamper detection、malformed input gate、benchmark、GDPR mapping、threat model 放到同一套交付里。

---

## 5. 面板各页面能证明什么

### `/home`

证明：

- 平台有统一 operator console
- 平台健康、作业、告警、contract 摘要是可视化可追踪的

### `/jobs` 与 `/jobs/:jobId`

证明：

- 主链路真实可执行
- 有 stage 级状态与结果工件
- 输出是聚合结果，不是明文

### `/jobs/start`

证明：

- 面板可以驱动作业，而不是只读
- 主链路 payload 可配置

注意：

- 这里填的路径必须是**服务端主机路径**

### `/requests` 与 `/requests/submit`

证明：

- 查询需要 workflow 提交和审批
- 平台具备治理能力，不是裸算法接口

### `/privacy-budget-approvals`

证明：

- 有隐私预算与近重复查询审批
- 能阻止差分式数据探测

### `/sse-query`

证明：

- SSE 能独立工作
- 前端可驱动一键式加密检索流程

### `/pjc-only`

证明：

- PJC 能独立工作
- 策略发布与 PJC 是联动而非硬编码结果

### `/audit/*`

证明：

- 有 public report
- 有 audit chain
- 有 seal
- 有 observability 与 lineage

### `/catalog/*`

证明：

- 平台关注数据集、服务、血缘，不只是算子

### `/business-access`

证明：

- 业务字段级授权真实存在
- 支持 buyer / merchant / support / courier / fraud / marketer 等角色

### `/permissions/*`

证明：

- caller / policy / keyring / KMS / OpenFGA 这些控制面概念已经建模

### `/recovery/*`

证明：

- record recovery 是独立治理边界
- 有 health、metrics、mTLS、TLS 诊断

### `/observability/*`

证明：

- 系统不是黑盒
- 有平台健康、事件流、告警、Grafana/Tempo 对接、chaos drill

### `/security/*`

证明：

- 项目具备契约 smoke、篡改检测、异常输入 gate、benchmark、repo hygiene

### `/compliance/*`

证明：

- 项目已经把 GDPR、threat model、reviewer checklist、license 纳入交付

---

## 6. 建议现场实际操作的 5 个动作

建议现场只做下面 5 个真实动作，其余用已有工件展示。

### 动作 1：打开首页和作业详情

路径：

- `/home`
- `/jobs`
- `/jobs/:jobId`

作用：

- 建立全局认知

### 动作 2：运行一次 `/sse-query`

输入：

- `db_path = sse/example_db.json`
- `keyword = China`

作用：

- 证明 SSE 独立可用

### 动作 3：运行一次 `/pjc-only`

输入：

- `server_csv = bridge/examples/server_export.csv`
- `client_csv = bridge/examples/client_export.csv`

作用：

- 证明 PJC + policy release 独立可用

### 动作 4：打开 `/business-access`，切换两个 preset

建议：

- `Merchant Staff`
- `Fraud Review`

作用：

- 证明业务字段级授权

### 动作 5：打开 `/privacy-budget-approvals`

作用：

- 证明隐私预算和重复查询治理

---

## 7. 如果评委追问“你们到底完成了哪些任务”

可以归纳成下面这组：

### 已完成的核心任务

1. SSE 关键字检索
2. 受控记录恢复
3. Rust bridge 令牌化
4. PJC 私有求交与求和
5. 策略发布与公开报告
6. 审计链生成与 seal
7. Operator Console 前端
8. 请求提交、审批、作业控制
9. 隐私预算与近重复查询审批
10. 平台健康与 observability
11. 业务字段级访问控制
12. 权限 / KMS / OpenFGA 控制面建模
13. mTLS bootstrap / preflight / TLS 诊断
14. 篡改检测、异常输入 gate、contract smoke、benchmark
15. GDPR / 威胁模型 / reviewer checklist 文档化

### 还不应夸大为“生产完成”的部分

答辩时建议主动说明：

- 本仓库的 baseline 与本地/半诚实 demo 能力是完整的。
- 但“生产安全完全闭环”并不是当前主张。
- 这反而会让答辩更可信。

---

## 8. 一句话版答辩话术

如果你只剩 30 秒总结，建议这样说：

> 我们实现的不是单个隐私计算算法，而是一套从请求提交、SSE 候选导出、记录恢复、bridge 令牌化、PJC 聚合、策略发布，到审计、可观测性、权限和合规映射的完整平台 baseline；面板上既能触发任务，也能查看审计和治理证据。

---

## 9. 现场故障兜底

如果现场实时计算失败，按优先级兜底：

1. 继续展示 `tmp/live_sse_bridge_demo/run-20260504T023757Z` 的 completed run
2. 重点讲 `/jobs/:jobId`、`/audit/*`、`/observability/*`
3. `SSE` 和 `PJC-only` 至少保一个现场运行
4. `business-access` 和 `privacy-budget-approvals` 用已有样例环境展示

这套兜底不会影响你证明“平台已经具备这些能力”。
