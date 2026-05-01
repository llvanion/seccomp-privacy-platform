# Bridge-ready Handoff 收紧计划

## 1. 目标

这份文档只讨论一个 owner 级剩余高风险问题：

```text
record recovery -> bridge-ready plaintext handoff -> bridge
```

当前系统已经把风险降下来了，但还没有完全收口。

目标不是立刻重写主链路，而是把 handoff 的收紧方向固定下来，避免后续实现又把明文暴露面放大。

## 2. 当前状态

当前 handoff 主要有两种模式：

### 2.1 file handoff

特点：

1. `sse_exports/server.csv`
2. `sse_exports/client.csv`
3. 明文 bridge-ready 数据会以文件形式存在

优点：

1. 最稳定
2. 最容易调试
3. 与现有 demo、bridge CLI、PJC fixture 最兼容

风险：

1. 明文 at-rest 暴露时间更长
2. 同机操作者更容易直接读取
3. 清理不及时会留下敏感中间产物

### 2.2 FIFO handoff

特点：

1. 使用 `--sse-export-handoff-mode fifo`
2. 通过 named pipe 直接把 bridge-ready 行流送入 bridge

优点：

1. 不持久化 `server.csv` / `client.csv`
2. 更接近短生命周期 handoff
3. 当前已经被审计和回放覆盖

风险：

1. 仍然是本机进程边界
2. 不是最终的服务间认证传输
3. 仍然存在 bridge 可见的 plaintext row

## 3. 当前冻结原则

在没有单独审批前，必须坚持：

1. bridge 仍然只接收 bridge-ready rows，不接 raw candidate IDs。
2. recovery 仍然只返回授权字段。
3. handoff 的类型、hash、row count 仍然必须可审计。
4. 新改动不能扩大 bridge-ready plaintext 的字段集合。
5. 新改动不能把原始过滤器或候选 ID 回送到 bridge。

## 4. 风险分层

### Level 1：当前可接受的 demo 风险

1. file handoff 仅用于兼容、调试和现有 demo。
2. FIFO handoff 优先用于减少本地持久化明文。
3. 两种模式都必须有 audit evidence。

### Level 2：不应继续扩大的风险

1. 新增额外明文中间文件。
2. 新增未经审计的 bridge-ready 缓存目录。
3. 把更多高敏字段塞进 handoff。
4. 让 bridge 感知 recovery 候选 ID 或原始过滤器。

### Level 3：下一阶段需要消除的风险

1. 长生命周期明文 handoff 文件。
2. 仅靠同机 Unix user 边界保护明文 handoff。
3. 无认证的进程间数据转移假设。

## 5. 收紧路线

### Phase 0：保持现有兼容能力

保留：

1. file mode
2. FIFO mode
3. recovery subprocess mode
4. recovery service mode

要求：

1. 现有 demo 不破
2. 审计字段不漂
3. file/FIFO 回放继续可用

### Phase 1：默认优先短生命周期 handoff

原则：

1. 能用 FIFO 的路径优先 FIFO
2. file mode 保留为兼容和排障路径
3. 文档与 runbook 里明确 file mode 是更高暴露面

### Phase 2：把 file handoff 限制成显式兼容模式

方向：

1. 更明确地区分“默认安全推荐路径”和“兼容落盘路径”
2. 把 file mode 的审计和清理要求写死
3. 对新功能默认不再围绕落盘 CSV 设计

### Phase 3：加密 at-rest handoff

方向：

1. 如果必须落盘，则优先演进到加密 handoff artifact
2. bridge 前增加受控解密或最小可见恢复步骤

注意：

1. 这属于新 contract 设计，不是简单实现细节
2. 必须先走 `docs/change_requests/`

### Phase 4：服务间认证传输

目标：

1. recovery boundary 与 downstream consumer 之间具备明确服务身份
2. handoff 不再默认等价于“同机文件或 pipe”

这一步已经超出当前 demo 范围，但必须作为 owner 方向固定下来。

## 6. 当前允许的实现方向

优先允许：

1. 加强 FIFO 路径的可观测和回放能力
2. 加强 file mode 清理、审计和告警
3. 收紧 output root、生命周期文件和运行目录约束
4. 增加更强的 contract/replay 检查

默认不允许直接做：

1. 为方便调试增加更多明文导出
2. 修改 handoff 字段语义而不提案
3. 在 bridge 前后新增未经审计的中间落盘

## 7. 验收标准

owner 线在 handoff 问题上的阶段性完成标准：

1. file mode 和 FIFO mode 的边界语义有明确文档。
2. 新改动默认不扩大明文暴露面。
3. handoff 相关回放验证可重复执行。
4. 任何更强 handoff 设计都先经过 change request，而不是先写代码。

## 8. 与其他文档关系

配套阅读：

1. [docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md)
2. [docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md)
3. [docs/SSE_BRIDGE_APSI_PIPELINE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/SSE_BRIDGE_APSI_PIPELINE.md)
4. [docs/INTERFACE_FREEZE_AND_CHANGE_PROCESS.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/INTERFACE_FREEZE_AND_CHANGE_PROCESS.md)
