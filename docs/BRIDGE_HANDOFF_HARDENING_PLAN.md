# Bridge-ready Handoff 收紧计划

## 1. 目标

这份文档只讨论一个 owner 级剩余高风险问题：

```text
record recovery -> bridge-ready plaintext handoff -> bridge
```

当前系统已经把风险降下来了，但生产级目标不是“风险缓解”，而是彻底消除 retained plaintext handoff 作为默认路径。

目标不是立刻重写主链路，而是把 handoff 的完整解决方向固定下来，避免后续实现又把明文暴露面放大。生产级完整任务以 [PRODUCTION_SECURITY_COMPLETION_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PRODUCTION_SECURITY_COMPLETION_PLAN.md) 的 `S1` 为准。

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

### Phase 1：默认优先短生命周期 handoff ✓（2026-05-01）

原则：

1. 能用 FIFO 的路径优先 FIFO
2. file mode 保留为兼容和排障路径
3. 文档与 runbook 里明确 file mode 是更高暴露面

已完成：

1. `scripts/verify_fifo_handoff_replay.sh` 新增独立 FIFO 回放验证：断言 `intersection_size=2`、`intersection_sum=425`、`output_file_type=fifo`、bridge 完成后 `sse_exports/server.csv` 和 `client.csv` 不存在、`mainline_contract_check.json` 两角色均为 `status=removed`。
2. FIFO 回放已接入 `scripts/check_ci_smoke.sh`（syntax check + 实际运行），与 file-mode 回放并列运行。
3. `mainline_contract_check.json` 新增顶层 `handoff_mode`（`”file”` | `”fifo”` | `null`），由 SSE export audit 中 `output_file_type` 字段派生，消费方可不解析 `handoff_cleanup` 子树直接读取。
4. `mainline_contract_check.json` 新增 `handoff_exposure_assessment` 对象（见 Phase 2），同步完成，写操作者和读消费方均可从顶层字段判断明文暴露风险，不必再推断。
5. `schemas/mainline_contract_check.schema.json` 更新（`handoff_mode` 和 `handoff_exposure_assessment` 为 optional 新字段，backward-compatible）。
6. `config/schema_backcompat_baseline.json` 已将两个新字段加入 `stable_properties`，`check_schema_backcompat.py` 继续通过。
7. file mode 的明文暴露说明已在 OPS_RUNBOOK.md 中补充（见 Phase 2 文档同步部分）。

### Phase 2：把 file handoff 限制成显式兼容模式 ✓（2026-05-01）

方向：

1. 更明确地区分”默认安全推荐路径”和”兼容落盘路径”
2. 把 file mode 的审计和清理要求写死
3. retained file mode 必须带显式 `handoff_retention_reason`
4. 对新功能默认不再围绕落盘 CSV 设计

已完成：

1. `handoff_exposure_assessment` 写入 `mainline_contract_check.json`，字段含义：
   - `handoff_mode`：当前 handoff 模式（`”file”` 或 `”fifo”`）
   - `plaintext_exposure_risk`：整体明文暴露风险（`”none”` / `”low”` / `”elevated”` / `”unknown”`）
   - `server_exposure` / `client_exposure`：每角色的 `output_file_type`、`cleanup_status`、`exposure_risk`
2. 暴露风险计算规则（已在 `check_mainline_contract.py` 中实现，见 `role_exposure_risk`）：
   - FIFO + removed → `”none”`（明文未落盘）
   - file + cleaned → `”low”`（瞬时明文，已清除）
   - file + retained → `”elevated”`（明文仍在磁盘）
   - 其他 → `”unknown”`
   - 整体：任一角色 `”elevated”` → 整体 `”elevated”`；全为 `”none”` → 整体 `”none”`；其余无 elevated → `”low”`；否则 `”unknown”`
3. 每次 owner 级 handoff 改动须在 `mainline_contract_check.json` 中检查 `handoff_exposure_assessment.plaintext_exposure_risk`，不得静默让 file retained 路径变成新默认。
4. 已在 `docs/OPS_RUNBOOK.md` 补充”Handoff Exposure Assessment”段落，说明如何解读 `plaintext_exposure_risk` 字段。
5. 暴露评估已被 downstream 派生视图全面承接（2026-05-01 同次完成，归属仍为 Phase 2 收口）：
   - `scripts/archive_audit_bundle.py:summarize_mainline_contract` 在归档索引 `audit_archive_index/v1` 的 `mainline_contract_summary` 中加入 `handoff_mode` 和 `handoff_exposure`（含 `plaintext_exposure_risk`、`server`、`client` 风险），归档与回溯审计可同步携带暴露断言。
   - `schemas/audit_archive_index.schema.json`、`schemas/audit_bundle_verification.schema.json`、`schemas/catalog_lineage.schema.json` 同步添加 optional `handoff_mode`/`handoff_exposure` 子字段，验证脚本继续通过。
   - `scripts/check_pipeline_artifact_smoke_reports.py` 在 observability smoke 中新增对 `handoff_exposure_assessment` 三个事件（overall + 每角色）以及 catalog_lineage `handoff_mode`/`handoff_exposure` 的正向断言；`scripts/benchmark_derived_views.py` 的 `EXPECTED_STAGES` 加入 `handoff_exposure_assessment`。
   - `bash scripts/check_ci_smoke.sh` 在两种 handoff 模式（file 与 FIFO）下均在归档索引中正确写出 `handoff_mode` 与 `handoff_exposure`，回放与归档链全绿。

### Phase 3：生产默认取消明文 at-rest handoff ✓ repo-side（2026-05-14）

目标态（生产闸门部分已落地）：

1. 生产路径默认使用 FIFO 或 streaming handoff。✓ pipeline `--production-mode` 拒绝 `--keep-sse-export-handoff-files`。
2. retained file handoff 在 production gate 下直接失败。✓ `check_mainline_contract.py --production-mode` 在 `plaintext_exposure_risk == "elevated"` 时返回 `status=fail` 与 `production_handoff_plaintext_elevated` finding，且生产模式下 `--allow-retained-managed-handoff` 不再生效。
3. 如果必须落盘，只能落加密 artifact。⏳ S1 完整闭环的剩余部分（KEK 派发、加密 artifact 文件格式）随 S2 KMS 落地。
4. 每个 job 使用独立 data encryption key。⏳ 同上，待 S2。
5. 临时明文只允许存在于进程内存、pipe 或受限 tmpfs。✓ 当前 FIFO 路径已满足；落盘加密 artifact 路径仍待 S2。

repo-side 已交付：

1. `scripts/check_mainline_contract.py`：新增 `--production-mode` 闸门，在生产模式下忽略 `--allow-retained-managed-handoff` 并基于 `handoff_exposure_assessment.plaintext_exposure_risk` 直接判定。
2. `mainline_contract_check.json` 顶层新增 `production_mode: bool` 字段；schema 与 backcompat baseline 同步更新（`schemas/mainline_contract_check.schema.json`、`config/schema_backcompat_baseline.json:stable_properties`）。
3. `scripts/run_sse_bridge_pipeline.sh --production-mode`：除原已禁止 `--token-secret`，新增禁止 `--keep-sse-export-handoff-files`，并自动把 `--production-mode` 透传给 contract checker。
4. `scripts/verify_production_handoff_gate.sh`：三条断言（FIFO 通过 / file+retained 被拒 / pipeline 入口直接拒绝），无需 PJC 真实运行即可重复验证。
5. evidence：`tmp/production_handoff_gate_evidence/`。

注意：

1. 这属于 `S1` 完整任务，不是只补一个清理脚本。
2. 必须同时交付 production gate、反例验证、audit 字段、runbook 和三人联合认证。
3. 如果改动 contract，必须先走 `docs/change_requests/`。

### Phase 4：服务间认证传输

目标：

1. recovery boundary 与 downstream consumer 之间具备明确服务身份
2. handoff 不再默认等价于“同机文件或 pipe”
3. 两机或跨服务传输必须绑定 mTLS/service identity/job_id
4. 传输模式、peer identity、cert fingerprint 和 handoff exposure 必须进入审计

这一步已经超出当前 demo 范围，但必须作为 owner 方向固定下来；跨机验证对齐 `S7` 两机 mTLS 联合验证。

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
5. [docs/PRODUCTION_SECURITY_COMPLETION_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PRODUCTION_SECURITY_COMPLETION_PLAN.md)
