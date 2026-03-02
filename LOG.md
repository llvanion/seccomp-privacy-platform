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

## 后续追加模板

## YYYY-MM-DD
### 已完成
- ...

### 备注
- ...
