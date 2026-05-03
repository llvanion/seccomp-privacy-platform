# 项目背景、需求与分支地图

这份文档的目标只有四个：

1. 用一份文档说明项目处在什么业务情景里
2. 说明当前仓库真正要做的需求、任务和目标
3. 说明当前还缺什么功能
4. 说明其他 branch 分别做了什么，以及哪些值得参考、哪些不该直接并进当前主线

当前推荐工作基线：`integrate-sse-bridge`

## 1. 项目情景

这个仓库当前最准确的定位是：

1. 面向电商高敏感数据场景的隐私协作平台基线
2. 用 `SSE -> controlled record recovery -> bridge tokenization -> A-PSI/PJC -> policy release` 串起“查询、协作、发布”三段边界

它不是普通数据库，也不是让多方直接交换明文用户数据的系统。

最匹配的业务情景有三类：

1. 平台内部细粒度查询：先用 `SSE` 缩小候选集，再恢复最小必要字段
2. 商家分析：只允许在授权范围内拿到聚合结果，不允许导出平台级高敏感明细
3. 平台与广告主交集分析：双方都不暴露全量用户明文，只得到满足策略的交集统计或归因结果

对应角色主要是：

1. 平台数据控制者
2. 商家
3. 广告主 / 广告平台
4. 履约 / 物流方
5. 审计 / 合规 / 策略管理员

## 2. 当前项目需求

当前仓库真正要保住的不是“某个脚本能跑”，而是以下平台语义：

1. `SSE` 只能做候选筛选和受控导出，不能绕过策略直接暴露高敏数据
2. `record recovery` 必须是受控恢复边界，只恢复被策略允许的字段
3. `bridge` 只接收最小必要字段，并把 join key 规范化、HMAC token 化
4. `A-PSI / PJC` 只处理安全求交和允许的聚合计算
5. `policy release` 只允许发布满足阈值、审计、去重和治理要求的结果

当前冻结语义的核心字段包括：

1. `job_id`
2. `correlation_id`
3. `caller`
4. `tenant_id`
5. `dataset_id`
6. `service_id`
7. `record_recovery_boundary`
8. `token_scope`
9. `token_key_version`
10. `release_policy`

## 3. 当前任务与具体目标

当前仓库的主任务可以分成 4 条：

1. 维护主链路：`SSE -> recovery -> bridge -> PJC -> release`
2. 维护控制面：metadata sidecar、policy/permission、导入/查询/只读 API
3. 维护审计与运维：contract smoke、benchmark、runbook、archive/seal/replay
4. 把 demo 逐步抬升到平台基线，但不把主链路强绑到数据库或新服务

当前阶段的具体目标是：

1. 保持端到端 demo 持续可回放、可审计、可验证
2. 把高敏字段暴露压缩到最小边界
3. 让 caller、tenant、dataset、service 语义在全链路一致
4. 让 control plane 先成为 sidecar，再决定是否平台化
5. 给后续 KMS、IAM、workflow、dashboard 留稳定接口

## 4. 当前已经完成的能力

当前分支已经不是“只有几个 demo 脚本”的状态，已完成的主能力包括：

1. 完整 `SSE -> recovery -> bridge -> A-PSI/PJC -> release` 本地集成链路
2. file handoff、retained file handoff、FIFO handoff
3. encrypted record store + standalone recovery service
4. Unix socket / HTTP recovery transport
5. request timestamp anti-replay 和 HMAC request signing
6. audit chain、seal、archive、replay 校验
7. SQLite sidecar 的 init/import/query/manage 基线
8. metadata read API、query workflow adapter、platform health adapter
9. benchmark / malformed-input gate / operator readiness / runbook 基线

## 5. 当前还需要补充的功能

结合当前文档和代码状态，真正还没补齐的是下面几类能力：

1. unified identity mapping
2. 更正式的 Keycloak / OpenFGA / Vault / external KMS 对接基线
3. durable workflow 与 dashboard / UI 壳
4. SQL sidecar 更深的 PostgreSQL 迁移与 importer repair
5. 更成熟的 control-plane 写路径与长期运维基线

如果要判断“下一阶段最该做什么”，优先级建议是：

1. 身份、授权、密钥这条线
2. durable workflow / query shell / dashboard 这条线
3. SQL sidecar 的 PostgreSQL-ready 深化

## 6. Branch 地图

下面是当前可见 branch 的实际功能定位。

| Branch | 功能定位 | 当前价值 | 建议 |
| --- | --- | --- | --- |
| `main` | 初始仓库 | 只保留历史起点价值 | 不作为工作基线 |
| `sse` | 早期独立 SSE 实现、API 文档、测试与 benchmark | `sse/` 目录的来源分支 | 已被当前仓库结构吸收，无需再单独 merge |
| `a-psi` | 早期独立 PJC/A-PSI 模块、双机流程、vendored `private-join-and-compute` | `a-psi/` 目录的来源分支 | 已被当前仓库结构吸收，无需再单独 merge |
| `integrate-sse-bridge` | 当前集成主线，含 bridge、recovery service、policy、audit、sidecar、benchmark | 当前最完整、最适合继续开发的分支 | 继续以它为主线 |
| `engineer-a-control-plane` | 第一版 control-plane metadata sidecar、schema、import/query 工具与设计文档 | 思路上有价值，但当前主线已做得更完整 | 不建议直接 merge；当前主线已概念性超集化 |
| `eng-b` | Temporal workflow、query/catalog/observability/product shell 原型 | 对“平台入口壳”很有参考价值 | 不建议直接 merge；只建议手工吸收设计思路 |
| `client` | 早期统一客户端 MVP，带 CLI/WebUI | 可作为外部客户端原型参考 | 只做参考，不建议直接并入 |
| `c-gateway` | A/B 模块统一 REST gateway，补审计、频控、能力令牌、最小披露 | 对外 API 壳有参考价值 | 只做参考，不建议直接并入当前主线 |
| `ad-client` | 广告主侧独立客户端，基于 gateway 发起任务和查结果 | 广告侧产品壳参考 | 只做参考，不建议直接并入当前主线 |

## 7. 哪些 branch 真正有帮助

### 7.1 已经被当前主线吸收的

1. `sse`
2. `a-psi`
3. `engineer-a-control-plane`

这三类内容在当前 `integrate-sse-bridge` 里已经有更完整版本或更成熟替代，不值得再做一次 raw merge。

### 7.2 值得参考但不应直接 merge 的

1. `eng-b`
2. `c-gateway`
3. `ad-client`
4. `client`

原因很简单：

1. 这些分支大多建立在更早的接口面上
2. 直接 cherry-pick 会把当前已冻结的 contract、runbook、schema、sidecar 语义冲乱
3. 它们更适合作为“产品壳/工作流/UI/外部访问层”的参考实现

建议保留的参考点：

1. 从 `eng-b` 吸收 Temporal workflow wrapper、telemetry 字段设计、query shell 思路
2. 从 `c-gateway` 吸收统一 REST gateway、rate limit、audit、capability token 的接口外形
3. 从 `ad-client` / `client` 吸收广告主侧 CLI/WebUI 的产品化外形

## 8. 关于“是否需要 clone 进来”

这次我没有把其他 branch 再额外 checkout 成工作目录副本，原因是：

1. 当前仓库已经能直接读取这些 branch 的 git 对象和远程跟踪引用
2. `sse` / `a-psi` / `engineer-a-control-plane` 的有用内容已经被当前主线吸收或超集化
3. `eng-b` / `c-gateway` / `ad-client` / `client` 更适合人工择点吸收，而不是整体并进

结论是：

1. 当前不需要额外 clone branch 到工作区
2. 当前更需要的是文档收口和后续需求优先级明确化

## 9. 文档治理建议

当前文档结构里最明显的问题不是“缺文档”，而是“上下文入口重复”。

建议把入口固定成：

1. 本文档：场景、需求、任务、branch 地图
2. `docs/COMPACT_PLATFORM_BRIEF.md`：快速平台概览
3. `docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md`：剩余工作量
4. 按角色继续读任务书和专项计划

根目录里与 `docs/` 内容重复、且状态较旧的文档应逐步移除，避免接手者误读旧结论。

## 10. 推荐阅读顺序

如果下一次会话要最快接手，建议按这个顺序读：

1. `docs/PROJECT_CONTEXT_AND_BRANCH_MAP.md`
2. `docs/COMPACT_PLATFORM_BRIEF.md`
3. `docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md`
4. `docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md`
5. 按角色继续读 `TASK_ENGINEER_A_*`、`TASK_ENGINEER_B_*`、`DELEGATION_ENGINEER_2_SQL_CONTROL_PLANE.md`
