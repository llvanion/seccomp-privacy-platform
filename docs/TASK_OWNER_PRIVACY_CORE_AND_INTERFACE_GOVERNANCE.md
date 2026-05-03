# 任务书 0：项目负责人负责的隐私内核与接口治理

## 1. 任务定位

这份任务归项目负责人，不建议分出去。

你负责的是平台最核心、最容易因为接口漂移而失控的部分：

1. 隐私计算主语义
2. 跨模块 contract
3. 数据泄漏边界
4. release policy
5. `SSE -> record recovery -> bridge -> PJC -> policy release` 主链路

其他人可以围绕这些接口做平台能力，但不能自行重新定义这些接口。

## 2. 不能分出去的原因

这些部分不是普通工程任务，而是平台的安全语义：

1. `SSE` 到 `record recovery` 的恢复边界决定哪些记录可以从加密存储里被恢复。
2. `bridge` 的 token contract 决定跨方 join key 如何被标准化、HMAC 化和审计。
3. `PJC` 的输入 contract 决定广告商和电商平台之间实际交换什么。
4. `policy release` 决定哪些交集结果、聚合值和报告可以被发布。
5. `caller / tenant_id / dataset_id / service_id / job_id / correlation_id` 的语义必须全链路一致。

如果这些语义分散给多人各自修改，后面会出现“看起来能跑，但隐私边界已经被破坏”的问题。

## 3. 你负责的具体任务

### 任务 A：冻结核心 contract

你需要维护这些稳定字段：

1. `job_id`
2. `correlation_id`
3. `caller`
4. `tenant_id`
5. `dataset_id`
6. `service_id`
7. `record_recovery_boundary`
8. `token_scope`
9. `token_key_version`
10. `release_policy`

这些字段只允许向后兼容扩展，不允许静默改名或改变含义。

### 任务 B：维护主链路接口

你保留以下入口的最终接口定义权：

1. `scripts/run_sse_bridge_pipeline.sh`
2. `scripts/run_live_sse_bridge_demo.sh`
3. `scripts/run_record_recovery_service.py`
4. `sse/run_client.py export-bridge-records`
5. `bridge` CLI 的 `generate` / `prepare-job`
6. `a-psi/moduleA_psi/scripts/run_pjc.sh`
7. `a-psi/moduleA_psi/scripts/policy_release.py`

其他人如果需要修改这些入口，必须先提交 `docs/change_requests/<topic>.md`。

### 任务 C：定义隐私边界

你需要继续推进以下边界：

1. encrypted record store 是平台内部加密存储边界。
2. record recovery service 是受控恢复边界。
3. bridge-ready handoff 是当前仍需收紧的明文暴露边界。
4. HMAC join token 是跨机构协作输入边界。
5. PJC result 是聚合结果边界。
6. policy release 是最终对外发布边界。

重点是把“当前仍然明文的 handoff”逐步收敛到：

1. FIFO 短生命周期流式传输
2. 加密 at-rest handoff
3. 远期的服务间认证传输
4. 审计可追溯的最小字段恢复

### 任务 D：维护泄漏模型

你需要明确每个阶段允许泄漏什么：

1. SSE 阶段允许泄漏候选数量，但不泄漏原始过滤条件。
2. recovery 阶段只允许恢复被策略允许的字段。
3. bridge 阶段不接收候选 ID 和原始过滤器。
4. PJC 阶段只接收 token 化 join key 和必要 value。
5. release 阶段只允许发布满足阈值、去重、审计策略的结果。

### 任务 E：接口变更审批

所有跨模块接口变更都必须走：

1. 变更提案
2. 兼容策略
3. schema 或 contract 更新
4. demo 回放验证
5. 文档同步

参考流程文档：

```text
docs/INTERFACE_FREEZE_AND_CHANGE_PROCESS.md
```

冻结字段矩阵：

```text
docs/CORE_CONTRACT_FREEZE_MATRIX.md
```

当前 threat model / leakage model 基线文档：

```text
docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md
```

当前 bridge-ready handoff 收紧计划：

```text
docs/BRIDGE_HANDOFF_HARDENING_PLAN.md
```

owner 评审清单：

```text
docs/OWNER_MAINLINE_CHANGE_CHECKLIST.md
```

## 4. 技术栈

你主要维护当前项目已有技术栈：

1. Python 3
2. Bash
3. Rust
4. JSON / JSONL / CSV
5. Unix socket / HTTP recovery service
6. HMAC-SHA256 tokenization
7. PBKDF2HMAC-SHA256 + AES-256-GCM encrypted record store
8. A-PSI / private-join-and-compute

## 5. 可参考但不能替代核心语义的 GitHub 项目

这些项目可以作为外围能力参考，但不能替代你的隐私主链路：

| 能力 | GitHub 项目 | 用法边界 |
| --- | --- | --- |
| 通用策略引擎 | https://github.com/open-policy-agent/opa | 可做 admission / ops policy，不替代隐私 release policy |
| 细粒度授权 | https://github.com/openfga/openfga | 可表达租户、数据集、服务权限，不替代主链路字段语义 |
| 密钥与加密服务 | https://github.com/hashicorp/vault | 可替代 mock KMS，不直接改变 bridge token contract |
| 工作流编排 | https://github.com/temporalio/temporal | 可替代 shell orchestration，不改变阶段输入输出 contract |
| SQL 查询引擎 | https://github.com/apache/datafusion | 可做未来查询前端，不直接访问未经授权的隐私数据 |

## 6. 稳定接口

### 端到端 demo

```bash
bash scripts/run_live_sse_bridge_demo.sh
```

### 集成 pipeline

```bash
bash scripts/run_sse_bridge_pipeline.sh \
  --server-input <server-source> \
  --client-input <client-source> \
  --job-id <job-id> \
  --token-scope <scope> \
  --token-secret-env BRIDGE_TOKEN_SECRET
```

### record recovery 独立服务

```bash
python3 scripts/run_record_recovery_service.py serve \
  --config config/record_recovery_http_service.example.json
```

### contract smoke

```bash
bash scripts/check_json_contracts.sh
```

## 7. 禁止事项

你之外的成员默认不能直接做这些事：

1. 改 `bridge-ready` handoff 字段语义。
2. 改 PJC `server.csv` / `client.csv` 语义。
3. 改 `policy_release.py` 的发布条件。
4. 改 `record_recovery_boundary` 的含义。
5. 把主链路强制依赖新数据库或新 API。
6. 删除已有 CLI 参数。
7. 改已有 schema name。

## 8. 验收标准

你的工作完成标准：

1. 三个人的实现都只能通过冻结接口协作。
2. 主链路 demo 能持续跑通。
3. 所有新增平台能力都是 adapter / sidecar first。
4. 明文 handoff 暴露面逐步减少，但不破坏现有 demo。
5. 每次接口变化都有文档、schema、兼容策略和回放验证。

## 9. 平台级剩余工作量估算

按 [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md) 的统一口径，这条 owner 主线从”当前原型”推进到”平台基线版”还需要：

1. `0 blocks`（原 10，Block1 + Block2 + Block3 + Block4 + Block5 + Block6 均已完成）
2. 约 `0h`

这里的“平台基线版”指：

1. 主链路 contract 继续冻结。
2. recovery / handoff / replay governance 不再只是本地 demo 边界。
3. 关键敏感边界具备更正式的 deploy / authn / lifecycle / replay 形态。

已完成收口：

1. `audit seal / archive` 已经补到本地 append-only 锚点基线：`audit_chain_index.jsonl` 之外，归档流程现在还会生成 `audit_chain_anchor.jsonl`，并在 archive-backed verify 时回放整条锚点链。
2. **Block1 ✓（2026-05-01）**：
   - (1/4) record recovery 请求级时间戳反重放校验：`validate_request_timestamp(±30s)`，client 强制携带 `request_timestamp_utc`，写入审计。
   - (2/4) systemd 主机级 hardening：`render-systemd` 现输出 `ProtectSystem=strict` + `ProtectHome` + `PrivateDevices` + `ProtectKernelTunables/Modules/ControlGroups` + `LockPersonality` + `RestrictSUIDSGID` + `SystemCallFilter=@system-service`；`ReadWritePaths=` 由 `derive_writable_paths(runtime)` 自动推导；contract smoke 校验所有指令。
   - (3/4) HMAC-SHA256 请求签名：client 生成 `request_id`（UUID）并计算 `HMAC-SHA256(token, "{request_id}:{ts}:{op}")`；服务端常数时间校验（`hmac.compare_digest`）；`request_signature_verified` + `signature_algorithm` 写入审计并冻结为 stable properties；HTTP transport 通过 `X-Request-Signature` 头传递。
   - (4/4) authz SQL 后端：新增 `record_recovery_authz_source/v1`，允许 recovery service 从 metadata SQLite 重建 `sse_export_policy/v1` caller 权限视图；contract smoke 现覆盖 DB-backed authz source。
3. **Block2 ✓（2026-05-01）**：record recovery 的 external-service replay 已固定。新增 `scripts/verify_record_recovery_manual_service_replay.sh`：先启动 standalone HTTP recovery service，再让 `run_live_sse_bridge_demo.sh` 走 `--record-recovery-service-mode manual`，并校验 `record_recovery_service_health.json`、有效 runtime config、`mainline_contract_check.json`、manager-captured `record_recovery_service_log/v1`，最后 stop 服务并确认 pid/ready 生命周期文件回收。这样 recovery 线的 deploy/authn/lifecycle/replay 已不再只依赖 pipeline auto-start 路径。
4. **Block3 ✓（2026-05-01）**：bridge/PJC compatibility 与 normalization version 治理基线已完成。bridge 现在在 `job_meta.json` 和 bridge audit 中嵌入 `NORMALIZER_SCHEMA_VERSION = "normalizer-schema/v1"` 作为代码级常量（区别于调用方提供的 `normalize_version`）；`bridge_job_meta.schema.json` 现在要求 `normalizer_schema_version` 并对 `bridge.server` / `bridge.client` 的 `normalizer` 字段强制限定为已知枚举值；`validate_bridge_job.py` 在 PJC 运行前检查 `KNOWN_NORMALIZER_SCHEMA_VERSIONS` 和 `KNOWN_NORMALIZERS`，拒绝任何来自未知 normalizer 实现的 job。
5. **Block5 ✓（2026-05-01）**：FIFO handoff 回放验证与 Phase 1 文档已完成。新增 `scripts/verify_fifo_handoff_replay.sh`：运行 `--sse-export-handoff-mode fifo`，断言 `intersection_size=2`、`intersection_sum=425`、`output_file_type=fifo`、bridge 完成后 CSV 不存在、`mainline_contract_check.json` 两角色均为 `status=removed`。已接入 `check_ci_smoke.sh`（syntax check + 实际运行）。`mainline_contract_check.json` 新增顶层 `handoff_mode` 字段，schema 及 backcompat baseline 同步更新。
6. **Block6 ✓（2026-05-01）**：handoff 明文暴露评估与 Phase 2 文档已完成。`mainline_contract_check.json` 新增 `handoff_exposure_assessment`（`handoff_mode`、`plaintext_exposure_risk`、`server_exposure`、`client_exposure`），评估逻辑在 `check_mainline_contract.py:role_exposure_risk()` 中实现；schema 和 backcompat baseline 已更新；`docs/OPS_RUNBOOK.md` 补充"Bridge Handoff Exposure Assessment"段落；BRIDGE_HANDOFF_HARDENING_PLAN Phase 1 和 Phase 2 均已收口。
7. **Block6 派生视图收口 ✓（2026-05-01，归 Block6）**：handoff 暴露评估已贯通到归档与派生视图链路：`scripts/archive_audit_bundle.py:summarize_mainline_contract` 在 `audit_archive_index/v1` 的 `mainline_contract_summary` 中输出 `handoff_mode` 与 `handoff_exposure`（`plaintext_exposure_risk` + `server` + `client`）；`schemas/audit_archive_index.schema.json`、`schemas/audit_bundle_verification.schema.json`、`schemas/catalog_lineage.schema.json` 同步加 optional 字段；`scripts/check_pipeline_artifact_smoke_reports.py` 对三事件 `handoff_exposure_assessment` 与 catalog_lineage `handoff_mode`/`handoff_exposure` 增加正向断言；`scripts/benchmark_derived_views.py` 的 `EXPECTED_STAGES` 加入 `handoff_exposure_assessment`。`bash scripts/check_ci_smoke.sh` 在 file 与 FIFO 两种模式下均把 `handoff_mode`、`handoff_exposure` 写到归档索引，回放与归档链全绿。

建议拆分：

1. ~~`1 block / 5h`：继续把 record recovery 从本地受控进程推进到更独立的 service-user / external-service 边界，补更强 authn、lifecycle 和回放验证。~~ **已完成（Block2，2026-05-01）**：manual external HTTP recovery service replay 已固定到 `scripts/verify_record_recovery_manual_service_replay.sh`。
2. ~~`2 blocks / 10h`：继续收紧 `bridge-ready` 明文 handoff，至少补一条比当前 file/FIFO 更接近平台边界的受控路径。~~ **已完成（Block5 + Block6，2026-05-01）**：FIFO 回放已固定到 `scripts/verify_fifo_handoff_replay.sh` 并接入 CI smoke；`mainline_contract_check.json` 新增 `handoff_mode` 和 `handoff_exposure_assessment`；BRIDGE_HANDOFF_HARDENING_PLAN Phase 1 + Phase 2 均已收口。
3. ~~`2 blocks / 10h`：补 bridge/PJC compatibility 与 normalization version 的长期治理基线。~~ **已完成（Block3）**
4. ~~`1 block / 5h`：把 replay、benchmark、change-process 和 owner checklist 再收一轮，形成平台基线签收点。~~ **已完成（Block4，2026-05-01）**：`verify_pipeline_replay.sh` 已加入 CI smoke；benchmark fixture 修复；freeze matrix 和 owner checklist 更新了 normalizer 治理条目。

不含：

1. 完整生产级多租户硬隔离。
2. 真实 HSM/KMS 上线。
3. 大规模运维、SLO、告警体系。
