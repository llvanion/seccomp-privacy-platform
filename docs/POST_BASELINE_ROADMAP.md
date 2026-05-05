# 平台基线之后路线图（2026-05-05）

这份文档只回答一个问题：

1. 平台基线已经完成之后，下一阶段到底该先做什么

它不再重复“当前基线已完成什么”，那部分以：

1. [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md)
2. [COMPACT_PLATFORM_BRIEF.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/COMPACT_PLATFORM_BRIEF.md)

为准。

## 1. 当前结论

截至 `2026-05-03`，owner、工程师 A、工程师 B、工程师 1、工程师 2 五条任务线都已经完成“平台基线版”定义范围内的实现。

从现在开始，新的工作不应再写成“补当前基线剩余 block”，而应单独视为“平台基线之后”的新增 tranche。

## 2. 继续推进时的边界

后续新增能力仍然必须遵守：

1. 不重定义 `SSE -> record recovery -> bridge -> PJC -> policy release` 冻结语义
2. 优先 adapter / sidecar first，而不是把新依赖强塞回主链路
3. 先让真实 authority source 接到外围入口，再考虑把这些依赖拉近主链路
4. 先把 operator / control-plane / service 边界做实，再谈“完整生产平台”

## 3. 推荐的下一阶段主 tranche

下面这四条线，是“继续把比赛版平台基线推进成更像平台”的最合理主 tranche。

| Tranche | 目标 | 约合 block | 约合工时 | 主要文档入口 |
| --- | --- | ---: | ---: | --- |
| A | 权威身份、授权与密钥来源 | 6 | 30h | `TASK_ENGINEER_A_*` / `IAM_AUTHZ_INTEGRATION_PLAN.md` / `KMS_SECRET_BACKEND_PLAN.md` |
| B | operator 工作流与 live control shell | 6 | 30h | `QUERY_INTERFACE_PLAN.md` / `OBSERVABILITY_PLAN.md` / `CONTROL_PANEL_SPEC.md` |
| C | PostgreSQL control-plane 深化 | 5 | 25h | `DELEGATION_ENGINEER_2_SQL_CONTROL_PLANE.md` / `CONTROL_PLANE_SCHEMA.md` |
| D | 独立服务强化与外部审计锚定 | 4 | 20h | `RECORD_RECOVERY_INDEPENDENT_SERVICE_PLAN.md` / `OPS_RUNBOOK.md` |

合计：

1. 核心下一阶段：`21 blocks / 105h`
2. 这不含完整生产级 HA、多机房、SRE 值班、百万级压测、正式前端产品发布

## 4. Tranche A：权威身份、授权与密钥来源

这条线的目标不是再补一层 mock，而是把当前已经存在的本地 compatibility contract，接到真实 authority source。

建议拆成：

1. `A1 / 5h`：issuer-backed identity proxy baseline
   - 在 sidecar API 前引入更正式的 bearer-token 验证入口
   - 固定 `issuer -> caller / tenant / service / roles` 注入规则
   - 不改主链路 CLI 字段语义
2. `A2 / 5h`：OpenFGA tuple sync + check adapter
   - 从 `authz_tuple_export/v1` 走 dry-run / apply / reconcile
   - 先覆盖 metadata/query/audit/platform-health 读侧
   - 不替代 release policy
3. `A3 / 5h`：真实 Vault / cloud KMS adapter baseline
   - 复用现有 `vault_kv` / `vault_http` 兼容外形
   - 把本地 fixture 换成远端 authority source
4. `A4 / 5h`：service identity + token lifecycle
   - 收紧 key agent / external KMS / recovery service 的 service-to-service 身份
   - 统一 rotation / revoke / drift 检查
5. `A5 / 5h`：policy / key / identity 三线的 mutation governance 联动
   - 把 policy drift、key drift、issuer rotation 串成统一 operator 视角
6. `A6 / 5h`：回归与 runbook 收口
   - 补 authn/authz/kms 远端 authority smoke
   - 回写 runbook 与 readme

这条线完成后，平台外围入口将不再主要依赖本地 env token 和本地 JSON backend。

## 5. Tranche B：Operator 工作流与 Live Control Shell

这条线的目标是把当前“离线 sidecar + 已完成 run 的 operator triage”，推进到“可以发起、跟踪、收敛一次 live job”的 operator shell。

建议拆成：

1. `B9 / 5h`：job start/status/result transport contract
   - 以 [CONTROL_PANEL_SPEC.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/CONTROL_PANEL_SPEC.md) 为准
   - 固定 `POST /v1/jobs/start`、`GET /v1/jobs/{job_id}`、`GET /v1/jobs/{job_id}/result`
2. `B10 / 5h`：live progress read path
   - running 态读取 live audit / status sidecar
   - 不和历史 `stage_timeline` 混用
3. `B11 / 5h`：Web control shell baseline
   - Job Setup / Live Progress / Result card 三块状态机
   - 继续隐藏 running 态下的历史 blocks
4. `B12 / 5h`：Temporal durable wrapper baseline
   - 只包装现有 CLI，不重写主链路
   - 让 submit/status/retry 有更 durable 的执行壳
5. `B13 / 5h`：Grafana / OTel bridge adapter
   - 先消费 `pipeline_observability/v1`
   - 不要求每个模块原生埋点
6. `B14 / 5h`：operator shell 回归与 handoff
   - live job control + historical triage + retry eligibility 一起验证

当前进展（`2026-05-05`）：

1. **`B9` 已完成（phase-1 local baseline）**
   - `scripts/serve_operator_dashboard.py` 已落地三条 endpoint
   - 已验证 `start -> running -> completed/result` 这一条本地回环
2. **`B10` 已完成第一版**
   - running 态现在会从 live sidecar / artifact presence 推导每阶段状态
   - 历史 blocks 在 UI 的 `running` 态下已隐藏
3. **`B11` 已完成第一版**
   - 嵌入式 Web UI 已切成 `Job Setup / Live Progress / Result`
   - 当前 form 仍是 request-file centric，而不是最终的字段级 builder
4. **`B11` 已继续推进第二版 admin shell**
   - 已接上 `Recent Runs`
   - 已支持 `--history-root` 下的 active-run 切换
   - 不需要每次改 `--out-base` 重启才能回看另一条 run
5. **`B12` 已完成第一版 local durable wrapper baseline**
   - 已落地 `POST /v1/jobs/{job_id}/relaunch`
   - 复用 `workflow_retry_eligibility/v1` 和 `submission_manifest.json`
   - 当前只支持 request-file-backed run，不支持 `<inline>` run
6. `B13-B14` 仍未推进

这条线完成后，工程师 B 方向才算从“已完成 run 的 operator 工具集”推进到“最小可用的 live operator 平台壳”。

## 6. Tranche C：PostgreSQL Control-Plane 深化

这条线的目标不是让主链路写库，而是让 sidecar 更接近长期 control-plane。

建议拆成：

1. `C1 / 5h`：workflow transition tables / read model
   - jobs 不只存最终快照
   - 补状态迁移视图，承接 query workflow / operator shell
2. `C2 / 5h`：policy / service versioning
   - 为 `policies`、`services` 补 version 语义
   - 支持更正式的变更治理
3. `C3 / 5h`：PostgreSQL JSONB + 索引
   - `payload_json -> JSONB`
   - 为高频字段补表达式索引 / 排序键 / 游标
4. `C4 / 5h`：registry-enriched catalog / lineage read model
   - 连接 metadata DB 与 file-derived lineage
   - 不默认暴露 artifact path
5. `C5 / 5h`：retention / reconcile / repair 收口
   - audit / registry / key lifecycle 的长期保留与修复策略

这条线完成后，metadata sidecar 会更接近真实 control-plane，而不是只读回放数据库。

## 7. Tranche D：独立服务强化与外部审计锚定

这条线的目标是继续把 recovery / audit 这些高敏边界从“本地可回放”推进到“更正式的独立服务与外部留痕”。

建议拆成：

1. `D1 / 5h`：recovery service mutual TLS baseline
   - 在现有时间戳反重放 + HMAC 签名之上补 mTLS
   - 不改 recovery contract
2. `D2 / 5h`：service metrics / tracing / structured logs
   - 先围绕 recovery、key agent、external KMS、operator shell
   - 不强绑主链路新 runtime 依赖
3. `D3 / 5h`：external audit anchor baseline
   - 把本地 append-only anchor 推到外部锚定介质
   - 保持 archive / verify contract 不变
4. `D4 / 5h`：ops runbook / failure recovery 收口
   - 把独立服务部署、证书轮换、外部锚定失败恢复写入 runbook

这条线完成后，平台最敏感的 deploy/authn/audit 边界会更接近长期形态。

## 8. 暂不建议优先做的事

在上述四条 tranche 完成前，不建议优先做：

1. 通用 SQL / pgwire / Flight SQL 产品化
2. 完整前端管理台重设计
3. 完整电商事实库与 customer 360 建模
4. 让主链路直接写 PostgreSQL
5. 把 OpenTelemetry / Grafana / Temporal 变成主链路必需依赖

这些方向不是没价值，而是现在会分散当前最关键的 contract-hardening 与 authority-source 工作。

## 9. 推荐执行顺序

如果只排最近两轮大任务，建议按下面顺序：

1. 先做 `A1-A3`
   - 把身份、授权、密钥 authority source 立住
2. 再做 `B9-B11`
   - 让 operator shell 真正能 live 控 job
3. 再并行推进 `C1-C3` 与 `D1-D2`
   - 一个补 control-plane 长期形态
   - 一个补独立服务正式边界
4. 最后收 `A4-A6`、`B12-B14`、`C4-C5`、`D3-D4`

## 10. 文档回写位置

推进上述 tranche 时，优先回写这些文档：

1. 身份 / 授权 / 密钥：`TASK_ENGINEER_A_CONTROL_PLANE_IDENTITY_ACCESS.md`、`IAM_AUTHZ_INTEGRATION_PLAN.md`、`KMS_SECRET_BACKEND_PLAN.md`
2. workflow / operator：`QUERY_INTERFACE_PLAN.md`、`OBSERVABILITY_PLAN.md`、`CONTROL_PANEL_SPEC.md`、`TASK_ENGINEER_B_QUERY_CATALOG_WORKFLOW_OBSERVABILITY.md`
3. SQL control-plane：`DELEGATION_ENGINEER_2_SQL_CONTROL_PLANE.md`、`CONTROL_PLANE_SCHEMA.md`
4. 独立服务 / 运维：`RECORD_RECOVERY_INDEPENDENT_SERVICE_PLAN.md`、`OPS_RUNBOOK.md`

## 11. 一句话结论

当前仓库已经完成“平台基线版”。

如果继续推进，最值得做的不是再补一层本地 sidecar，而是把：

1. authority source
2. live operator shell
3. PostgreSQL control-plane
4. 独立服务正式边界

这四条线做实。
