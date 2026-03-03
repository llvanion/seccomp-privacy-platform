信安赛项目：成员 C（Access 网关 + 审计 + 频控 + Dashboard + 部署）完整工作清单与进度标注   
March 2026  

## 今日完成标注（2026-03-02）

- [x] `moduleC_gateway` Windows -> Linux 兼容处理完成（统一 LF 换行、清理 UTF-8 BOM、脚本可执行权限校正）
- [x] Linux 依赖安装验证完成（`requirements.txt` + `pytest`）
- [x] 网关运行验证完成：`/health`、`/se/index/build`、`/se/search`、`/attribution/run` 全部返回 `code=0`
- [x] 本地演示脚本验证完成：`scripts/run_local_demo.py` 可在 Linux 下跑通

## 今日完成标注（2026-03-03）

- [x] 完成统一错误结构与 `reason_code` 映射（A/B 网关侧）
- [x] 完成 B 适配器升级：`python_api`（优先）+ `local` fallback
- [x] 完成频控升级：`redis` + `memory` fallback（可配置）
- [x] 完成审计升级：`sqlite/jsonl` 双后端 + `GET /audit/query`
- [x] 完成本地验收脚本：`scripts/verify_local_stack.py`

### 状态说明

- 本清单按“代码实现状态”勾选，不等同于“线上生产验收状态”。
- 需要外部依赖（如 Redis、B 服务）的项，若代码已具备且可通过配置启用，则记为已完成；上线验收另行标注。


---

# 1 你当前的职责边界（成员 C）

你的任务是把 “各模块能运行” 升级为 “一个可交付、可展示、可部署的系统平台”，并提供：

• 统一对外 API 网关：屏蔽 A/B 内部细节，提供稳定 REST 接口；  
• 安全控制层：频控、审计、能力令牌、最小披露；  
• 模块集成层：对接 A（PSI）与 B（SE）；  
• 可视化展示层：Dashboard 展示指标与安全状态；  
• 一键部署能力：docker-compose 启动全系统；  
• 协作契约执行者：确保 A/B 接口符合 contract。  

---

# 2 总流程与模块结构关系

## 2.1 系统整体结构

1. 用户 → Dashboard  
2. Dashboard → Access Gateway（你）  
3. Access Gateway → A（PSI）  
4. Access Gateway → B（SE）  
5. 所有操作 → Audit 日志 → DB  
6. 频控逻辑 → Redis  

## 2.2 推荐仓库目录结构（C 负责部分）

• moduleC_gateway/  
• dashboard/  
• docker-compose.yml  

---

# 3 你需要完成的全部工作（详细清单 + 交付物）

---

# 4.1 W1：统一网关骨架搭建

目标：搭建 Access Gateway 基础服务框架。

技术选型：

• FastAPI  
• Uvicorn  
• Pydantic  

交付物：

• moduleC_gateway/app/main.py  
• Dockerfile  

### 任务清单

- [x] 初始化 FastAPI 项目结构  
- [x] 实现统一响应结构（code/message/data/timestamp）  
- [x] 实现 /health 健康检查接口  
- [x] 配置日志输出  
- [x] 编写 Dockerfile 并成功构建镜像  

验收标准：

- [x] 启动后访问 /health 返回 200  

---

# 4.2 W2：对接 A（PSI 模块）

目标：通过网关调用 A 的 pipeline 或读取其输出。

实现方式：

• subprocess 调用 run_pipeline.sh  
• 读取 runs/<job_id>/public_report.json  

交付物：

• app/services/a_adapter.py  

### 任务清单

- [x] 封装 run_psi(job_id, start, end, k, caller, n)  
- [x] 在网关实现 POST /attribution/run  
- [x] 调用 run_pipeline.sh（在配置 `A_PIPELINE_SCRIPT` + `A_CRITEO_TSV` 时启用）  
- [x] 解析 public_report.json  
- [x] 写入审计日志（action=psi_run）  
- [x] 返回统一格式响应  

验收标准：

- [x] 调用接口后成功返回 conversions  
- [x] intersection_size < k 时不发布（由 A 的 `policy_release` 决策，C 透传 `released/reason_code`）  

---

# 4.3 W3：对接 B（SE 模块）

目标：将 SE 服务封装成 REST 能力。

技术选型：

• websockets（若使用 WS）  
• 或直接调用 B Python API  

交付物：

• app/services/b_adapter.py  

### 任务清单

- [x] 实现 POST /se/index/build  
- [x] 实现 POST /se/search  
- [x] 封装 WS 或 Python API 调用逻辑  
- [x] 记录 latency 与 result_count  
- [x] 写入审计日志（action=se_search）  

验收标准：

- [x] 能通过 REST 返回 encrypted_results  

---

# 4.4 W4：频控系统（Rate Limit）

目标：防止多次查询推断攻击。

技术选型：

• Redis  

交付物：

• app/services/ratelimit.py  

### 任务清单

- [x] 配置 Redis 连接  
- [x] 实现按 caller 限流  
- [x] 实现按 action 限流  
- [x] 超限返回 429  
- [x] 将频控命中写入审计日志  

验收标准：

- [x] 连续调用超过阈值自动拒绝  

---

# 4.5 W5：审计系统（Audit）

目标：所有关键操作必须可追溯。

技术选型：

• PostgreSQL 或 SQLite  
• SQLAlchemy  

交付物：

• app/services/audit.py  
• 审计表结构  

### 任务清单

- [x] 设计 audit 表结构  
- [x] 实现写入审计函数  
- [x] 实现 GET /audit/query  
- [x] 支持按 action / actor / 时间过滤  
- [x] 将 PSI / SE / 频控操作写入日志  

验收标准：

- [x] 可以查询历史访问记录  

---

# 4.6 W6：能力令牌 + 最小披露

目标：实现受控敏感信息访问。

技术选型：

• JWT（PyJWT）  

交付物：

• app/services/token.py  

### 任务清单

- [ ] 实现 POST /access/token/issue  
- [ ] 实现 POST /access/token/revoke  
- [ ] 实现 GET /orders/{id}/sensitive  
- [ ] 校验 token 有效期  
- [ ] 校验 scope 权限  
- [ ] 实现字段脱敏  
- [ ] 撤销后拒绝访问  

验收标准：

- [ ] token 撤销后立即失效  

---

# 4.7 W7：Dashboard

目标：可展示安全与性能指标。

技术选型：

• React / Next.js  
• 或 Streamlit（快速实现）  

交付物：

• dashboard/  

### 任务清单

- [ ] 展示 PSI 转化人数  
- [ ] 展示 PSI latency  
- [ ] 展示 SE 搜索次数  
- [ ] 展示 频控命中次数  
- [ ] 展示 敏感字段访问记录  
- [ ] 实现自动刷新  

验收标准：

- [ ] 页面可正常访问并展示实时数据  

---

# 4.8 W8：docker-compose 一键部署

目标：评委只执行一条命令即可运行系统。

交付物：

• docker-compose.yml  

### 任务清单

- [ ] 编排 psi-service  
- [ ] 编排 se-service  
- [ ] 编排 access-gateway  
- [ ] 编排 redis  
- [ ] 编排 db  
- [ ] 编排 dashboard  
- [ ] 编写 README 启动说明  

验收标准：

- [ ] docker-compose up 后系统正常运行  
- [ ] 所有服务健康  

---

# 5 里程碑计划

W1：网关骨架  
W2：对接 A  
W3：对接 B  
W4：频控 + 审计  
W5：Dashboard  
W6：部署  

---

# 6 你的最终交付目标

你负责让整个系统：

• 可运行  
• 可展示  
• 可审计  
• 可控制  
• 可复现  

你是系统的稳定器与安全控制层。
