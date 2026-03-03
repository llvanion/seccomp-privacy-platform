# 开发日志

## 2026-03-02

### 已完成
- 已将项目文件从 Windows 路径同步到 Linux 工作目录（排除 `.venv/.tmp/__pycache__/*.pyc`）。
- 已将文本文件换行从 `CRLF` 统一转换为 `LF`。
- 已清理源码/配置/文档中的 UTF-8 BOM。
- 已为 `scripts/run_local_demo.py` 添加可执行权限。
- 已在 Linux 虚拟环境安装运行与测试依赖：
  - `pip install -r requirements.txt`
  - `pip install pytest`
- 已在 Linux 下启动 `uvicorn` 并验证网关接口：
  - `GET /health`
  - `POST /se/index/build`
  - `POST /se/search`
  - `POST /attribution/run`
  上述接口均返回成功（`code=0`）。
- 已验证本地演示脚本 `scripts/run_local_demo.py` 可正常跑通。

### 备注
- `pytest` 可运行，但当前项目暂无测试用例（`no tests ran`）。
- 当前频控为内存实现（`InMemoryRateLimit`），尚未接入 Redis。
- 当前审计为 JSONL 文件写入，尚未接入数据库。

---

## 2026-03-03

### 今天完成了什么
- 完成 C 网关与 A/B 的进一步集成改造，保持“不修改 A/B 源码，仅在 C 侧适配”。
- 完成频控与审计能力升级，并补充本地验证脚本。
- 完成 README/TODO 更新，并已将分支变更推送到远端 `c-gateway`。

### 修改了什么
- 新增统一错误模型与错误返回结构：`app/errors.py`，并在 `app/main.py` 中接入统一异常处理。
- 升级 B 适配器：`app/services/b_adapter.py`
  - 支持 `B_BACKEND=auto|python_api|local`
  - 支持优先走 B Python API，失败回退本地索引。
- 升级频控：`app/services/ratelimit.py`
  - 新增 Redis 频控实现
  - 支持 `auto` 模式自动降级到内存频控。
- 升级审计：`app/services/audit.py`
  - 支持 `sqlite/jsonl` 双后端
  - 新增审计查询能力，并在 `app/main.py` 增加 `GET /audit/query`。
- 扩展配置项：`app/config.py`、`.env.example`。
- 更新请求/响应模型：`app/schemas.py`（增加 `backend_used`、审计查询数据结构）。
- 优化 A 适配器报错路径：`app/services/a_adapter.py`（缺失报告时给出明确错误码）。
- 补充本地脚本：
  - `scripts/run_local_demo.py` 增加审计查询演示
  - 新增 `scripts/verify_local_stack.py` 作为接口验收脚本。
- 更新文档：
  - `README.md` 完善使用说明（含后续补充中文版提示）
  - `TODO.md` 对齐当前代码进度状态。

### 这次改动的优点
- 集成方式稳妥：通过 C 侧适配实现与 A/B 协同，不入侵 A/B 代码。
- 运行弹性更好：Redis/SQLite 不可用时可降级，便于本地联调与演示。
- 可观测性提升：审计从“仅写日志”升级为“可查询”。
- 交付可验证：新增验收脚本，便于快速检查核心链路是否正常。

### 还可以优化的地方
- 目前缺少自动化测试（单元测试/集成测试）与 CI 校验。
- B 的 Python API 适配依赖运行时动态导入和本地状态目录，后续可抽象更稳定的适配层。
- 频控当前只按 `actor+action`，可继续增强为按窗口、按资源维度、按租户策略限流。
- 审计查询目前是基础筛选，后续可增加分页游标、聚合统计和导出能力。
- 尚未完成 W6/W7/W8（JWT 能力令牌、Dashboard、docker-compose 全量编排）。

---

## 后续追加模板

## YYYY-MM-DD
### 已完成
- ...

### 备注
- ...
