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

1. **`A1` 已完成（2026-05-05）**：issuer-backed identity proxy baseline
   - `scripts/serve_identity_proxy.py`：薄 HTTP 反向代理，验证 Bearer token（静态 token map 或 DB-backed issuer/subject），注入 `X-Identity-*` headers（Caller / Tenant-Id / Service-Id / Platform-Roles / Resolved），再转发到上游 sidecar；admin bypass token 支持 platform_admin 角色
   - `schemas/identity_proxy_health.schema.json`：冻结 `identity_proxy_health/v1` contract，纳入 backcompat baseline（共 82 个 schema）
   - `config/identity_proxy.example.json`：标准配置示例（metadata / query / audit / health 四个上游）
   - `scripts/check_ci_smoke.sh` 新增 `serve_identity_proxy.py` compile check
   - loopback smoke 验证：`/healthz` 返回 `identity_proxy_health/v1`，schema 校验通过
   - 边界：当前只做 bearer-token 验证 + 注入；上游 sidecar 仍可独立校验；不改主链路 CLI 字段语义
2. **`A2` 已完成（2026-05-05）**：OpenFGA tuple sync + check adapter
   - `scripts/sync_openfga_tuples.py`：三模式（dry-run / apply / reconcile），从 `authz_tuple_export/v1` 源同步 tuple 到本地 SQLite tuple store；apply 模式支持 `--prune`
   - `scripts/check_openfga_authz.py`：直接 tuple 查询，输出 `openfga_check_result/v1`；支持 `--assert-allowed / --assert-denied`
   - `schemas/openfga_sync_report.schema.json` + `schemas/openfga_check_result.schema.json` + `migrations/metadata/007_add_openfga_tuples.sql` + Postgres DDL `openfga_tuples` 表
   - 验证：dry-run 33 个 tuple，apply 写入 33 个，check allowed/denied 均通过，schema 校验，Postgres DDL parity check ✓
3. **`A3` 已完成（2026-05-05）**：KMS backend reachability probe
   - `scripts/check_kms_reachability.py`：按后端类型（vault_kv_file / vault_http / external_kms_http / keyring_file / env_var）逐项探活；overall_status = ok / degraded / error；支持 `--assert-ok`
   - `schemas/kms_reachability_report.schema.json`：冻结 `kms_reachability_report/v1` contract
   - 验证：已有 fixture 全 ok，未设 env var → error，schema 校验通过
4. **`A4` 已完成（2026-05-05）**：service identity + token lifecycle
   - `scripts/manage_service_tokens.py`：issue / verify / revoke / list 四个子命令；token 格式 `base64url(header).base64url(payload).hmac_sha256_hex`，携带 `jti/svc/iat/exp/scp` 五字段；撤销检查通过 store 内 `status` 字段实现；输出 `service_token_report/v1`
   - `schemas/service_token_report.schema.json`：冻结 `service_token_report/v1` contract
   - `migrations/metadata/008_add_service_tokens.sql` + Postgres DDL `service_tokens` 表（SERIAL/TIMESTAMPTZ）
   - 验证：issue → verify ok → revoke → verify revoked 四路径 schema 均通过；`check_ci_smoke.sh` ✓；backcompat 87 schema 0 fail
   - 边界：不替代主链路 bridge HMAC token；只给 key agent / KMS / recovery service 提供可撤销的 service-to-service 身份凭证
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
5. **`B13` 已完成（2026-05-05）**：Grafana / OTel bridge adapter
   - `scripts/export_otel_events.py`：将 `pipeline_observability/v1` 转换为 OTLP-兼容 span JSONL；trace_id / root span 由 `job_id` 确定性派生；每个 stage event 成为一个 child span，携带 stage/role/status/duration_ms/row_count 等 attributes；输出 `otel_export_report/v1` 报告 + `otel_spans.jsonl`
   - `schemas/otel_export_report.schema.json`：冻结 `otel_export_report/v1` contract
   - 验证：5 阶段合成 fixture → 6 个 span（1 root + 5 stage）全部含必要字段，schema 校验通过；不要求每个模块原生埋点；产物可直接导入 Grafana Tempo / Jaeger
6. **`B14` 已完成（2026-05-05）**：operator shell 回归与 handoff
   - `scripts/verify_operator_shell_regression.py`：15 项端到端检查，串联 dashboard 服务启动 → `POST /v1/jobs/start` → 轮询至 terminal → `GET /v1/jobs/{id}/result`（intersection=2, sum=425, released）→ `GET /v1/runs` → `GET /v1/dashboard` audit_center → retry_eligibility → operator_triage → OTel span export → relaunch endpoint，全部 15/15 通过，schema `operator_shell_regression_report/v1` 校验通过
   - `schemas/operator_shell_regression_report.schema.json`：冻结 `operator_shell_regression_report/v1` contract
   - 验证：`check_ci_smoke.sh` ✓，backcompat 88 schema 0 fail，全流程 8.9s 内完成

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
6. **`B13` 已完成**（OTel bridge adapter）
7. **`B14` 已完成**（operator shell regression — 15/15 checks, 8.9s）

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
