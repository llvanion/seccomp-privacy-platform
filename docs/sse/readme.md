# sse 分支代码阅读说明

## 1. 分支目标

`sse` 分支实现的是**可搜索对称加密（Searchable Symmetric Encryption）**系统，支持多种学术方案、客户端命令行流程、服务端会话与索引检索。

核心能力：
- 配置生成与服务创建
- 密钥生成
- 数据库加密与上传
- 单关键词搜索
- 多关键词批量搜索
- 数据删除与更新

## 2. 关键目录与文件

入口文件：
- `run_client.py`：客户端 CLI（asyncclick）
- `run_server.py`：服务端启动 CLI
- `main.py`：主入口

通信与前后端抽象：
- `frontend/client/*`：客户端命令与服务封装
- `frontend/server/*`：服务端连接与服务管理

算法与基础库：
- `schemes/`：多种 SSE 方案实现（如 CJJ14、CT14、DP17 等）
- `toolkit/`：密码学工具、结构、日志、配置管理

文档与样例：
- `API_Docs.md`：Server-Client 消息协议
- `example_db.json`、`example_multi_key_db.json`：示例数据

## 3. 客户端 CLI 能力（已实现）

`run_client.py` 已实现命令：
- `generate-config`
- `create-service`
- `upload-config`
- `generate-key`
- `encrypt-database`
- `encrypt-database-multi-key`
- `upload-encrypted-database`
- `search`
- `multi-search`
- `delete-data`
- `update-data`

这套命令构成了完整的“建服务 -> 加密 -> 上传 -> 检索 -> 维护”链路。

## 4. 通信协议要点（API_Docs）

底层通信：WebSocket 长连接。

消息格式：统一 envelope，关键字段包括：
- `type`
- `sid`
- `content`
- 可选扩展（如 `token_digest`、`request_id`）

关键消息类型：
- `init`
- `config`
- `upload_edb`
- `token`
- `multi_token`
- `delete`
- `update`

## 5. 状态管理模型

服务端对每个 `sid` 有状态机：
- `NOT_EXISTS`
- `CONFIG_UPLOADED_BUT_EDB_NOT_UPLOADED`
- `ALL_READY`

客户端需要根据状态机顺序推进操作，否则会出现时序错误。

## 6. 分支集成价值

在统一软件中，`sse` 提供：
- 密文检索与索引管理能力
- 可直接复用的 CLI 行为模型
- 可作为网关 B 侧后端的真实实现

客户端集成建议：
- 将 SSE 操作抽象为“服务实例（sid）”维度管理
- 对用户隐藏底层 token/message 细节，提供任务式工作流
- 在 WebUI 中可视化状态机与操作前置条件
