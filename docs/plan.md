# 统一隐私平台客户端架构规划（CLI + WebUI）

> 目标：将 `a-psi`、`c-gateway`、`sse` 三个分支能力整合为一个可落地的软件客户端方案。
>
> 当前阶段仅做架构设计，不做代码实现。

## 1. 设计目标与范围

### 1.1 目标

客户端要同时满足：
- 同一套业务能力既可通过 CLI 操作，也可通过 WebUI 操作
- 尽量优先对接 C 网关（统一鉴权、审计、频控）
- 在网关不可用时，支持必要的降级直连（主要面向研发/联调）
- 提供“任务化”的用户体验，屏蔽底层脚本与协议细节

### 1.2 范围

本客户端覆盖三类能力：
- A：隐私归因任务发起、状态查看、结果读取
- B：SSE 索引构建、检索、更新、删除
- C：令牌申请/撤销、审计查询、敏感数据访问

### 1.3 非目标（本阶段）

- 不改动 A/C/SSE 后端核心算法实现
- 不替换现有后端协议
- 不引入复杂调度系统（先以本地任务队列 + 远端调用为主）

## 2. 核心架构原则

1. **内核复用**：CLI 与 WebUI 共享同一应用内核（UseCase 层）
2. **适配器隔离**：A/C/SSE 分别封装 Adapter，避免 UI 直接依赖后端细节
3. **任务驱动**：所有长流程统一抽象为 Job（提交/运行/完成/失败）
4. **可观测性优先**：每次动作都具备日志、审计关联 ID、可追踪状态
5. **最小披露默认开启**：默认通过 C 网关访问敏感能力

## 3. 客户端总体分层

建议采用单仓内多模块结构：

```
client/
  core/
    domain/
    usecases/
    ports/
  adapters/
    gateway/
    a_psi/
    sse/
    storage/
  interfaces/
    cli/
    webui/
  app/
    bootstrap/
    config/
    telemetry/
```

分层职责：
- `core/domain`：领域模型（Job、Token、AuditEvent、SseService 等）
- `core/usecases`：业务编排（发起归因、构建索引、查询审计等）
- `core/ports`：抽象接口（GatewayPort、SsePort、ApsiPort、StorePort）
- `adapters/*`：具体实现（HTTP、WebSocket、脚本调用、本地缓存）
- `interfaces/cli`：命令解析与输出渲染
- `interfaces/webui`：页面路由、表单、状态展示
- `app/bootstrap`：配置加载、依赖注入、生命周期

## 4. 能力组织（按业务域）

### 4.1 归因域（Attribution）

面向用户能力：
- 创建归因任务（job_id、时间窗、k、n、value_mode）
- 查看任务状态
- 查看可发布报告与原因码

建议优先路径：
- 通过 C 网关 `POST /attribution/run`

降级路径（研发模式）：
- 直接调用 A 分支脚本入口（`run_pipeline.sh` 或 job 化脚本）

### 4.2 检索域（Search/SSE）

面向用户能力：
- 创建/管理 SSE 服务实例
- 构建索引、执行单词/多词检索
- 更新/删除密文记录

建议优先路径：
- 通过 C 网关 `POST /se/index/build`、`POST /se/search`

扩展路径：
- 需要高级操作时，直连 SSE 客户端 API（WebSocket）

### 4.3 访问治理域（Access & Audit）

面向用户能力：
- 签发 token、撤销 token
- 查询审计日志
- 按 scope 访问敏感数据并展示脱敏效果

访问路径：
- 统一走 C 网关 `/access/*`、`/audit/query`、`/orders/{id}/sensitive`

## 5. CLI 与 WebUI 的统一模型

### 5.1 统一命令/动作词表

建议统一动作名，保证 CLI 与 WebUI 一一对应：
- `attribution.run`
- `se.index.build`
- `se.search`
- `token.issue`
- `token.revoke`
- `audit.query`
- `sensitive.read`

### 5.2 参数模型统一

所有动作先映射到同一 `Request DTO`，再由 UseCase 层处理；避免 CLI 与 WebUI 分别维护两份业务参数校验逻辑。

### 5.3 输出模型统一

统一输出结构：
- `request_id`
- `status`
- `message`
- `data`
- `trace`（可选，研发模式）

CLI 负责文本渲染，WebUI 负责表格/卡片渲染，但数据结构一致。

## 6. 任务与状态设计

### 6.1 Job 抽象

统一 Job 字段建议：
- `job_id`
- `type`（attribution/se_build/se_search/...）
- `status`（pending/running/succeeded/failed/cancelled）
- `created_at` / `updated_at`
- `input_snapshot`
- `result_ref`
- `error`

### 6.2 状态机（客户端侧）

```
pending -> running -> succeeded
                 \-> failed
pending -> cancelled
running -> cancelled
```

### 6.3 持久化建议

MVP 阶段先使用本地 sqlite 或 json 文件，保存：
- 历史任务
- 最近连接配置
- 非敏感 UI 偏好

敏感信息（如 token）默认仅短期内存保存，可选本机加密存储。

## 7. 交互协议与适配层设计

API 基线说明：本节的接口设计以 `docs/api.md` 为准；后续实现与联调统一按该清单推进。

### 7.1 GatewayAdapter

负责：
- REST 调用封装
- 统一错误映射（HTTP/业务码 -> 客户端错误码）
- 重试与超时策略

MVP 必接 API：
- `GET /health`
- `POST /attribution/run`
- `POST /se/index/build`
- `POST /se/search`
- `POST /access/token/issue`
- `POST /access/token/revoke`
- `GET /audit/query`
- `GET /orders/{order_id}/sensitive`

### 7.2 SseAdapter

两种模式：
- `gateway` 模式：经 C 网关访问 SSE 能力
- `native` 模式：直连 SSE WebSocket 协议（用于高级能力）

`native` 模式最小消息集合：
- `init`
- `config`
- `upload_edb`
- `token`
- `multi_token`
- `delete`
- `update`

### 7.3 ApsiAdapter

两种模式：
- `gateway` 模式：通过 C 发起归因
- `script` 模式：直接触发 A 脚本（本地调试）

## 8. WebUI 页面规划（最小可用）

建议页面：
1. 仪表盘（最近任务、服务健康）
2. 归因任务页（创建任务、查看报告）
3. SSE 检索页（建索引、检索、结果展示）
4. 访问控制页（签发/撤销 token、敏感数据访问）
5. 审计页（筛选与导出）

设计约束：
- 仅提供与 CLI 对应的最小操作
- 不引入复杂可视化组件
- 以可操作、可追踪、可审计为优先

## 9. CLI 命令规划（最小可用）

命令组建议：
- `client health`
- `client attribution run`
- `client se build-index`
- `client se search`
- `client token issue`
- `client token revoke`
- `client audit query`
- `client sensitive read`

命令到 API 映射统一以 `docs/api.md` 第 6 节为准，CLI 与 WebUI 共用同一 UseCase 与 Port。

统一支持参数：
- `--profile`（环境配置）
- `--output json|table`
- `--request-id`
- `--timeout`

## 10. 配置与环境策略

建议采用 profile 文件：
- `dev`：本地联调
- `staging`：集成测试
- `prod`：生产

关键配置项：
- `gateway.base_url`
- `gateway.auth_mode`
- `sse.mode`（gateway/native）
- `apsi.mode`（gateway/script）
- `storage.path`
- `telemetry.level`

## 11. 安全与合规要点

- 默认走 C 网关，统一执行最小披露与鉴权
- 客户端日志对敏感字段做脱敏
- token 不写入明文日志
- 审计查询与任务执行的 `actor/request_id` 保持一致，便于追踪

## 12. 实施路线图（仅规划）

### Phase 1：客户端内核骨架
- 建立分层结构
- 定义领域模型、UseCase、Port 接口
- 完成基础配置加载与错误模型

### Phase 2：CLI MVP
- 接入 GatewayAdapter
- 实现核心命令（归因、SE 搜索、token、审计）
- 实现统一输出与任务记录

### Phase 3：WebUI MVP
- 基于同一 UseCase 接入页面
- 实现最小页面集与任务状态展示

### Phase 4：降级与高级模式
- 增加 A script 模式
- 增加 SSE native 模式
- 完善重试、超时、可观测性

## 13. 风险与缓解

主要风险：
- 三分支接口语义尚未完全统一
- SSE native 协议与网关协议并存会增加复杂度
- A 模块运行依赖（二进制/环境）可能导致平台差异

缓解策略：
- 先以 C 网关契约作为统一上层 API
- 高级模式作为显式开关，不默认开启
- 客户端内置“环境自检”步骤，提前发现依赖问题

## 14. 对后续实现的直接指导

实现阶段应严格按以下顺序推进：
1. 先实现 `core`（领域 + 用例 + 端口）
2. 再实现 `GatewayAdapter`
3. 先交付 CLI，再交付 WebUI
4. 最后再补充 A/SSE 直连降级模式

这样可以最小化耦合，保证每一步都可独立验证。

## 15. API 契约治理（新增）

为避免三分支能力合并时接口漂移，客户端开发阶段执行以下规则：

1. **单一 API 真相源**：以 `docs/api.md` 为客户端 API 基线文档。
2. **实现前校对**：每个 UseCase 落地前，先对照 `docs/api.md` 检查请求/响应字段。
3. **变更同步**：新增或变更接口时，必须同步修改 `docs/api.md` 与本计划文档。
4. **双入口一致性**：CLI 与 WebUI 禁止分别定义不同 API 参数语义。

