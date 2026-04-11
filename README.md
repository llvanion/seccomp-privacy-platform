# Module C 使用说明

本文档描述项目中 **C 模块（Access Gateway / 审计 / 频控 / 能力令牌）** 的职责、接口、调用方式、配置项，以及与 A/B 模块的集成边界。

C 模块的目标是：为 A（PSI 归因流水线）和 B（SSE 检索能力）提供统一 REST 访问层，并补充统一响应格式、错误处理、频控、审计、能力令牌和最小披露能力，便于本地演示、联调和后续平台集成。

---

# 1. 模块结构

C 模块当前主要由以下文件组成：

- `app/main.py`
- `app/config.py`
- `app/schemas.py`
- `app/errors.py`
- `app/services/a_adapter.py`
- `app/services/b_adapter.py`
- `app/services/ratelimit.py`
- `app/services/audit.py`
- `app/services/token.py`
- `app/services/sensitive_data.py`
- `scripts/run_local_demo.py`
- `scripts/verify_local_stack.py`

各部分职责如下：

## 1.1 `app/main.py`
负责网关入口与路由注册：

- 定义对外 REST 接口
- 接入统一异常处理
- 接入审计、频控、token 校验
- 编排 A/B 适配器

## 1.2 `app/services/a_adapter.py`
负责 A 模块适配：

- 调用 A 的 `run_pipeline.sh`
- 读取 `public_report.json`
- 在未配置真实 A 时返回本地 mock 结果

## 1.3 `app/services/b_adapter.py`
负责 B 模块适配：

- 优先走 B 的 Python API
- 失败时回退到本地 `local` 索引
- 暴露统一的 build/search 能力

## 1.4 `app/services/ratelimit.py`
负责频控：

- 支持 `redis`
- 支持 `memory`
- 支持 `auto` 自动降级

## 1.5 `app/services/audit.py`
负责审计：

- 支持 `sqlite`
- 支持 `jsonl`
- 提供写入和查询能力

## 1.6 `app/services/token.py`
负责 W6 能力令牌：

- 签发 token
- 校验 token
- 撤销 token
- 检查有效期、scope、资源范围

## 1.7 `app/services/sensitive_data.py`
负责示例敏感资源：

- 提供示例订单数据
- 提供字段脱敏逻辑

## 1.8 `scripts/run_local_demo.py`
负责本地演示：

- 调用健康检查
- 演示 SE 建索引/搜索
- 演示 attribution run
- 演示 token 签发/敏感访问/撤销

## 1.9 `scripts/verify_local_stack.py`
负责本地验收：

- 自动验证 C 侧核心接口是否可用

---

# 2. 职责边界

C 模块要解决的不是具体 PSI 或 SSE 算法实现，而是系统层能力。

## 2.1 对 A 的边界

C 不修改 A 的协议和发布治理实现，只负责：

- 接收统一 REST 请求
- 调用 A 的 pipeline
- 读取 A 的 `public_report.json`
- 对外返回统一响应
- 补充 C 自己的审计和频控

## 2.2 对 B 的边界

C 不修改 B 的检索算法实现，只负责：

- 对外暴露统一 REST 接口
- 尝试调用 B Python API
- 在联调或演示阶段提供 `local` fallback

## 2.3 对平台/演示层的边界

C 负责提供：

- 稳定的对外 API
- 统一错误格式
- 审计与频控
- W6 能力令牌和最小披露

---

# 3. 当前接口列表

C 模块当前对外提供以下接口：

- `GET /health`
- `POST /attribution/run`
- `GET /attribution/report/{job_id}`
- `POST /se/index/build`
- `POST /se/search`
- `GET /audit/query`
- `POST /access/token/issue`
- `POST /access/token/revoke`
- `GET /orders/{id}/sensitive`

统一成功响应格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "timestamp": "2026-03-03T00:00:00+00:00"
}
```

统一错误响应格式：

```json
{
  "code": 429,
  "message": "rate limit exceeded",
  "data": {
    "reason_code": "rate_limit_exceeded",
    "details": {}
  },
  "timestamp": "2026-03-03T00:00:00+00:00"
}
```

更详细的请求/返回示例见：

- `c_gateway_api.md`

---

# 4. 与 A/B 的集成方式

## 4.1 A 模块集成

如果同时配置了以下环境变量：

- `A_PIPELINE_SCRIPT`
- `A_CRITEO_TSV`

则 `/attribution/run` 会执行 A 的真实 pipeline，并读取：

- `runs/<job_id>/public_report.json`

广告商场景下，`/attribution/run` 还支持直接接收 `exposure_records`，用于由广告商侧上传曝光集合后触发 PSI 归因。当前分支也新增了独立广告商客户端：

- `ad_client/`
- `ad_client_main.py`

广告商客户端只聚焦 PSI，支持：

- 上传曝光集合并发起任务
- 查询 `job_id` 对应的可发布结果报告

如果未配置，则 C 返回本地 mock report，便于独立验证和演示。

## 4.2 B 模块集成

`B_BACKEND` 支持：

- `auto`
- `python_api`
- `local`

含义如下：

- `auto`：优先尝试 `python_api`，失败后回退到 `local`
- `python_api`：严格走 B 的 Python API 集成
- `local`：C 侧本地 fallback，仅用于 demo / 本地验证

若使用 `python_api`，需要配置：

- `B_SSE_ROOT`
- `B_SERVER_URI`
- `B_SCHEME`

---

# 5. 安全与治理能力

## 5.1 频控

支持以下后端：

- `RATE_LIMIT_BACKEND=auto|redis|memory`

相关配置：

- `REDIS_URL`
- `RATE_LIMIT_MAX_PER_ACTOR_ACTION`
- `RATE_LIMIT_WINDOW_SECONDS`

当前策略是按：

- `actor + action`

进行限流。

## 5.2 审计

支持以下后端：

- `AUDIT_BACKEND=sqlite|jsonl`

相关配置：

- `AUDIT_DB_PATH`
- `AUDIT_JSONL_PATH`

查询接口：

- `GET /audit/query?action=&actor=&start_ts=&end_ts=&limit=`

当前会记录的典型动作包括：

- `psi_run`
- `se_index_build`
- `se_search`
- `rate_limit`
- `access_token_issue`
- `access_token_revoke`
- `orders_sensitive_read`

## 5.3 W6：能力令牌 + 最小披露

当前已支持：

- `POST /access/token/issue`
- `POST /access/token/revoke`
- `GET /orders/{id}/sensitive`

token 支持：

- 有效期校验
- scope 校验
- 资源范围校验
- 撤销后立即失效

敏感资源默认返回脱敏字段，体现最小披露原则。

---

# 6. 配置项

建议先复制环境文件：

```bash
cp .env.example .env
```

当前主要配置如下。

## 6.1 基础配置

- `LOG_LEVEL`
- `RUNS_ROOT`

## 6.2 A 适配配置

- `A_PIPELINE_SCRIPT`
- `A_CRITEO_TSV`

## 6.3 B 适配配置

- `B_BACKEND`
- `B_SSE_ROOT`
- `B_SERVER_URI`
- `B_SCHEME`

## 6.4 频控配置

- `RATE_LIMIT_BACKEND`
- `REDIS_URL`
- `RATE_LIMIT_MAX_PER_ACTOR_ACTION`
- `RATE_LIMIT_WINDOW_SECONDS`

## 6.5 审计配置

- `AUDIT_BACKEND`
- `AUDIT_DB_PATH`
- `AUDIT_JSONL_PATH`

## 6.6 Token 配置

- `TOKEN_SECRET`
- `TOKEN_ISSUER`
- `TOKEN_DEFAULT_EXPIRE_SECONDS`
- `TOKEN_DB_PATH`
- `TOKEN_JSONL_PATH`

---

# 7. 本地启动方式

## 7.1 Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## 7.2 本地 demo

```bash
python scripts/run_local_demo.py
```

## 7.3 本地验收

```bash
python scripts/verify_local_stack.py
```

如果本机设置了代理，而 Python 请求 `127.0.0.1` 失败，可先执行：

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
export no_proxy=127.0.0.1,localhost
export NO_PROXY=127.0.0.1,localhost
```

---

# 8. 当前本地验收范围

`scripts/verify_local_stack.py` 当前验证：

- `GET /health`
- `POST /se/index/build`
- `POST /se/search`
- `POST /attribution/run`
- `GET /attribution/report/{job_id}`
- `GET /audit/query`
- `POST /access/token/issue`
- `GET /orders/demo-1001/sensitive`
- `POST /access/token/revoke`
- 撤销后 token 再访问被拒绝

---

# 9. 当前推荐给协作同学的稳定入口

## 9.1 给 A/B 联调同学的入口

直接调用 C 的 REST 接口：

- `POST /attribution/run`
- `GET /attribution/report/{job_id}`
- `POST /se/index/build`
- `POST /se/search`

## 9.2 给平台 / 展示层的入口

- `GET /health`
- `GET /audit/query`
- `POST /access/token/issue`
- `POST /access/token/revoke`
- `GET /orders/{id}/sensitive`

---

# 10. 当前实现状态

当前已完成：

- 统一网关骨架
- A 适配
- B 适配
- 频控
- 审计
- W6 能力令牌与最小披露
- 本地 demo / 验收脚本

当前尚未完成：

- W7 Dashboard
- W8 docker-compose 全量编排

---

# 11. 总结

C 模块的核心价值不只是“把接口暴露出来”，而是：

- 统一 A/B 对外访问方式
- 统一错误模型和响应格式
- 提供频控和审计
- 提供能力令牌与最小披露
- 支持本地独立验证和演示

因此，推荐将 C 模块视为一个具备以下能力的网关服务：

- Access
- Adapt
- Rate Limit
- Audit
- Token
- Minimal Disclosure
