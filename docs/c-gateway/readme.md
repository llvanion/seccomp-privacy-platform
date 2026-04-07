# c-gateway 分支代码阅读说明

## 1. 分支目标

`c-gateway` 分支实现的是**统一访问网关**，聚焦最小披露与访问控制，作为 A（归因）与 B（可搜索加密）能力的统一 REST 接入层。

核心职责：
- 对外提供统一 API
- 统一错误格式与响应结构
- 审计日志记录
- 访问频控
- 能力令牌签发/校验/撤销
- 敏感数据最小披露（按 scope 控制脱敏）

## 2. 关键目录与文件

主要代码位于 `app/`：
- `app/main.py`：FastAPI 入口与路由编排
- `app/config.py`：配置管理
- `app/schemas.py`：请求/响应模型
- `app/errors.py`：统一错误定义

服务层（`app/services/`）：
- `a_adapter.py`：A 模块适配（归因调用）
- `b_adapter.py`：B 模块适配（SE 建索引与搜索）
- `ratelimit.py`：限流，支持 redis/memory/auto
- `audit.py`：审计落库，支持 sqlite/jsonl
- `token.py`：令牌服务（签发、解析校验、撤销）
- `sensitive_data.py`：敏感资源与脱敏逻辑

辅助脚本：
- `scripts/run_local_demo.py`
- `scripts/verify_local_stack.py`

## 3. 已实现 API（核心）

- `GET /health`
- `POST /attribution/run`
- `POST /se/index/build`
- `POST /se/search`
- `GET /audit/query`
- `POST /access/token/issue`
- `POST /access/token/revoke`
- `GET /orders/{id}/sensitive`

其中 `orders/{id}/sensitive` 流程为：
1. Bearer Token 解析
2. 令牌签名与有效期校验
3. scope/resource 校验
4. 根据权限决定全量或脱敏返回

## 4. 安全与治理机制

令牌机制（`token.py`）：
- HS256 风格签名
- 支持 `jti/sub/scope/resource_id/exp/iss`
- 支持撤销列表（sqlite 或 jsonl）

治理能力：
- 频控：按 actor + action 维度限流
- 审计：记录关键动作、调用者与扩展 payload
- 错误统一：通过 `GatewayError` 与统一响应体输出

## 5. 与 A/B 的集成方式

当前分支采用“适配器”模式：
- A 侧：调用 A 模块 pipeline 并读取报告
- B 侧：优先调用 B 的 Python API，失败可回退 local

这使网关可以在真实后端尚未完全就绪时继续提供稳定接口。

## 6. 分支集成价值

在统一软件中，`c-gateway` 是服务中枢：
- 统一入口与鉴权策略承载点
- 跨模块审计与频控的共性层
- 对客户端提供更稳定、低耦合的 API 契约

建议客户端优先对接 C 网关，而不是直接耦合 A/B 原生实现。
