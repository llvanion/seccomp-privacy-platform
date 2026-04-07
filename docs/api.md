# 客户端 API 清单（CLI + WebUI）

> 本文定义统一客户端在 MVP 阶段需要使用的 API。
>
> 设计原则：默认优先走 C 网关；A 脚本与 SSE Native 仅作为降级/高级模式。

## 1. API 分层与优先级

客户端使用三层 API：

1. **P0（默认）Gateway REST API**
   - 面向 CLI 与 WebUI 主路径
   - 统一鉴权、审计、频控、错误语义

2. **P1（可选）SSE Native WebSocket API**
   - 用于网关未覆盖的高级 SSE 操作
   - 研发/联调或高级功能开关启用

3. **P2（降级）A-PSI Script API（本地脚本接口）**
   - 网关不可用时的本地执行兜底
   - 主要用于开发、实验、故障旁路

## 2. P0：Gateway REST API（客户端必须支持）

### 2.1 服务健康

- `GET /health`
- 用途：启动前连通性探测、WebUI 仪表盘状态

### 2.2 归因任务

- `POST /attribution/run`
- 请求字段：
  - `job_id`
  - `start_ts`
  - `end_ts`
  - `k`
  - `caller`
  - `n`
  - `value_mode`
  - `out_dir`（可选）
- 响应关键字段：
  - `released`
  - `reason_code`
  - `report`

### 2.3 SSE 索引与检索

- `POST /se/index/build`
  - 请求字段：`index_name`、`records[]`（含 `keys[]`、`values[]`）
  - 响应字段：`indexed_count`、`backend_used`

- `POST /se/search`
  - 请求字段：`index_name`、`keyword`
  - 响应字段：`result_count`、`encrypted_results[]`、`backend_used`

### 2.4 访问控制（Token）

- `POST /access/token/issue`
  - 请求字段：`actor`、`scopes[]`、`resource_id`、`expire_seconds`
  - 响应字段：`access_token`、`expires_at`、`jti`、`scopes[]`

- `POST /access/token/revoke`
  - 请求字段：`jti` 或 `token`、`revoked_by`、`reason`
  - 响应字段：`revoked`、`jti`

### 2.5 审计查询

- `GET /audit/query`
- 查询参数：`action`、`actor`、`start_ts`、`end_ts`、`limit`
- 响应字段：`total`、`rows[]`

### 2.6 敏感数据最小披露

- `GET /orders/{order_id}/sensitive`
- 请求头：`Authorization: Bearer <token>`
- 响应关键字段：`masked`、`allowed_scopes[]`、`data`

## 3. P1：SSE Native WebSocket API（高级模式）

> 协议来源：SSE 分支 `API_Docs.md`。

### 3.1 连接与消息封装

- 连接：WebSocket
- 统一 envelope 字段：
  - `type`
  - `sid`
  - `content`
  - 可选：`token_digest`、`request_id`

### 3.2 客户端需支持的消息类型

- `init`
- `config`
- `upload_edb`
- `token`
- `multi_token`
- `delete`
- `update`

### 3.3 对应能力映射

- `init`：服务会话初始化
- `config`：上传 SSE 配置
- `upload_edb`：上传加密数据库
- `token`：单关键词检索
- `multi_token`：多关键词检索
- `delete`：删除密文数据
- `update`：更新/插入密文数据

## 4. P2：A-PSI Script API（降级模式）

> 本质是脚本参数契约，不是 HTTP API。

### 4.1 端到端入口

- `moduleA_psi/scripts/run_pipeline.sh`
- 关键参数：
  - `--criteo-tsv`
  - `--start-ts`
  - `--end-ts`
  - `--out`
  - `--job-id`
  - `--value-mode`
  - `--k`
  - `--n`
  - `--caller`
  - `--bucket-field`（可选）

### 4.2 job 化双机入口（推荐）

- `moduleA_psi/scripts/init_pjc_job.py`
- `moduleA_psi/scripts/run_pjc_job_server.sh`
- `moduleA_psi/scripts/run_pjc_job_client.sh`

### 4.3 输出文件契约

- `runs/<job_id>/job_meta.json`
- `runs/<job_id>/attribution_result.json`
- `runs/<job_id>/public_report.json`
- `runs/<job_id>/audit_log.jsonl`

## 5. 客户端内部 Port 接口（实现层契约）

为统一 CLI 与 WebUI，客户端内核定义以下 Port：

### 5.1 GatewayPort

- `health()`
- `runAttribution(req)`
- `buildSeIndex(req)`
- `searchSe(req)`
- `issueToken(req)`
- `revokeToken(req)`
- `queryAudit(req)`
- `getSensitiveOrder(req)`

### 5.2 SsePort

- `initService(req)`
- `uploadConfig(req)`
- `uploadEncryptedDb(req)`
- `search(req)`
- `multiSearch(req)`
- `delete(req)`
- `update(req)`

### 5.3 ApsiPort

- `runAttributionByGateway(req)`
- `runAttributionByScript(req)`
- `readAttributionResult(jobRef)`

## 6. CLI / WebUI 功能映射（MVP）

- `client health` -> `GET /health`
- `client attribution run` -> `POST /attribution/run`
- `client se build-index` -> `POST /se/index/build`
- `client se search` -> `POST /se/search`
- `client token issue` -> `POST /access/token/issue`
- `client token revoke` -> `POST /access/token/revoke`
- `client audit query` -> `GET /audit/query`
- `client sensitive read` -> `GET /orders/{order_id}/sensitive`

WebUI 使用同一 UseCase，不单独定义第二套 API。

## 7. 错误与超时约定（客户端侧）

- 默认请求超时：30s（可配置）
- 可重试动作：`health`、`se/search`、`audit/query`
- 不自动重试动作：`attribution/run`、`token/issue`、`token/revoke`
- 统一错误分类：
  - `network_error`
  - `auth_error`
  - `rate_limit`
  - `validation_error`
  - `backend_error`

## 8. 版本与演进规则

- 本文为客户端 API 基线 v1
- 新增 API 时必须同步更新：
  - `docs/api.md`
  - `docs/plan.md`
- CLI 与 WebUI 均以 `core/usecases` 的 Port 契约为单一事实来源
