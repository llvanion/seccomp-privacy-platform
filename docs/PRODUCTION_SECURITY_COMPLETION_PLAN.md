# 生产级安全完整解决方案

本文档把当前项目从“比赛版隐私计算平台基线”推进到“生产级隐私计算安全平台”所需的安全方案落成可执行任务。这里不再使用“缓解”口径；每一项都以完整解决一个安全问题为目标。

## 1. 总目标

目标状态：

```text
明文不落盘、密钥不出正式 KMS、跨方通信全程 mTLS、PJC 任务受资源隔离、
结果发布受隐私预算约束、查询滥用可检测、审计证据外部不可篡改、
关键任务必须由三人联合认证后才算完成。
```

当前项目已经具备主链路：

```text
SSE candidate export -> controlled record recovery -> Rust bridge tokenization -> A-PSI/PJC -> policy release
```

生产级安全完整方案不改变这条主链路语义，而是把每个高敏边界升级为可部署、可认证、可审计的闭环。

## 2. 任务完成原则

后续安全任务必须按“完整任务”交付。不能只提交代码、只补文档、只跑一个 smoke，或只写一个计划。

每个完整任务必须同时包含：

1. 需求边界：明确解决哪个安全问题，以及不解决什么。
2. 实现变更：代码、schema、脚本、配置或部署模板落地。
3. 验证命令：至少一条可复现命令，必要时包含大规模或两机验证。
4. 证据文件：JSON / JSONL / log / report 写入固定路径。
5. 审计接入：关键安全决策进入 audit chain 或独立 report schema。
6. 文档回写：更新本文件、runbook、team plan 和相关模块文档。
7. 三人联合认证：Person 1、Person 2、Person 3 按职责签字确认。

任何只完成其中一部分的工作，状态只能标记为 `partial`，不能进入 pre 或结题报告的“已完成能力”。

## 3. 完整任务包

### S1. 消除明文 handoff 落盘

状态（2026-05-14）：repo-side 闭环已完成，等待跨机环境的 Person 2 / Person 3 联合认证。

repo-side 已交付：

1. `scripts/check_mainline_contract.py` 新增 `--production-mode` 闸门：当 `handoff_exposure_assessment.plaintext_exposure_risk == "elevated"` 时直接产生 `production_handoff_plaintext_elevated` finding，`status=fail`，且在生产模式下 `--allow-retained-managed-handoff` 不再生效（`effective_allow_retained = allow and not production_mode`）。
2. `mainline_contract_check.json` 顶层新增 `production_mode: bool` 字段并写入 `schemas/mainline_contract_check.schema.json` 与 `config/schema_backcompat_baseline.json` 的 `stable_properties`，向后兼容。
3. `scripts/run_sse_bridge_pipeline.sh` 的 `--production-mode`：原已禁止 `--token-secret`，新增禁止 `--keep-sse-export-handoff-files`（参数校验阶段直接 `die`），并自动透传 `--production-mode` 给 mainline contract checker。
4. `scripts/verify_production_handoff_gate.sh` 提供三条断言：FIFO/removed bundle 通过、file/retained bundle 被生产闸门拒绝（含 `production_handoff_plaintext_elevated`）、pipeline 入口在 production-mode 下连配置都拒绝。
5. evidence：`tmp/production_handoff_gate_evidence/{positive,negative}_contract_check.json` + `negative_arg_pipeline.log`。
6. 文档：本文件、`docs/BRIDGE_HANDOFF_HARDENING_PLAN.md` Phase 3、`docs/OPS_RUNBOOK.md` 已同步。

仍需 operator-side：

1. 真实跨机 / 服务身份传输（对齐 Phase 4 / S7）。
2. 落盘加密 artifact 的 KEK 路径（对齐 S2 与 KMS 完整闭环）。
3. 三人联合认证签字（按下方表格）。

目标：`record recovery -> bridge -> PJC` 之间不再依赖长期存在的 `server.csv` / `client.csv` 明文中间文件。

最终状态：

1. 默认路径使用 FIFO 或 streaming handoff。
2. 如果必须落盘，只能落加密 artifact。
3. 每个 job 使用独立 data encryption key。
4. 临时明文只允许存在于进程内存、pipe 或受限 tmpfs。
5. job 结束后销毁 key，落盘 artifact 即使被复制也不可恢复。

需要修改：

1. `docs/BRIDGE_HANDOFF_HARDENING_PLAN.md`：把 Phase 3/4 从方向升级为目标态。
2. `scripts/run_sse_bridge_pipeline.sh`：默认生产路径禁止 retained file handoff。
3. `schemas/mainline_contract_check.schema.json`：保留并扩展 handoff exposure 字段。
4. `scripts/check_mainline_contract.py`：生产模式下 `plaintext_exposure_risk=elevated` 直接失败。
5. `OPS_RUNBOOK.md`：写明生产执行命令和失败处理。

验收标准：

1. FIFO/streaming 主链路 demo 通过。
2. file retained 模式在 production gate 下被拒绝。
3. `mainline_contract_check.json` 明确记录 `handoff_mode`、`plaintext_exposure_risk`、cleanup 状态。
4. Person 3 能用反例证明 retained file handoff 会被 gate 拦下。

联合认证：

| 角色 | 认证内容 |
| --- | --- |
| Person 1 | 主链路结果正确，报告口径不再宣称 file handoff 是生产默认 |
| Person 2 | FIFO/streaming 在 Ubuntu 环境稳定运行，日志和临时目录生命周期正确 |
| Person 3 | 明文 retained 反例被拒绝，审计证据完整 |

### S2. 正式 KMS 与密钥生命周期

状态（2026-05-14）：repo-side 生产闸门已收紧。`check_kms_reachability.py --production-mode` 不再把 keyring 文件、`vault_kv` 本地 fixture 或缺少 endpoint 的 skipped config 当成生产证据；必须至少有一个 `vault_http` 或 `external_kms_http` 探活结果真实可达，且 keyring active 版本只能引用 `vault_http` / `aws_kms` 这类 live-capable 后端。`scripts/verify_production_kms_gate.sh` 覆盖 reachable positive、env-only、env-keyring、skipped HTTP config 和 `vault_kv` fixture keyring 反例。

目标：生产路径不再依赖本地环境变量作为 token secret、record encryption key 或 audit seal key 的可信根。

最终状态：

1. Vault / AWS KMS / Cloud KMS 是生产唯一可信密钥源。
2. `key_id`、`version`、`tenant_id`、`dataset_id`、`purpose` 全部可审计。
3. key access、rotation、revocation 都写入审计。
4. 旧 key version 只能验证旧 job，不能继续生成新 token。
5. bridge 不通过 CLI 接收裸 secret。

需要修改：

1. `docs/KMS_SECRET_BACKEND_PLAN.md`：把真实 KMS 设为生产默认目标态。
2. `config/keyring.example.json` / `external_kms_config` 示例：生产示例不再使用裸 env secret。
3. `scripts/check_kms_reachability.py`：生产模式必须真实 backend reachable。
4. `scripts/run_sse_bridge_pipeline.sh`：`--production-mode` 下禁止 `--token-secret`。
5. `schemas/key_access_audit.schema.json`：确保 backend kind、key version、caller、job_id 完整记录。

验收标准：

1. keyring / external KMS 路径通过 contract smoke。
2. production demo 使用 `--token-secret-key-name`，不使用裸 `--token-secret`。
3. key access audit 可以追踪一次 job 的全部密钥访问。
4. 禁用 key version 后新 job 被拒绝。

联合认证：

| 角色 | 认证内容 |
| --- | --- |
| Person 1 | 主链路仍可复现，报告说明 key source 证据 |
| Person 2 | KMS 服务或 mock/real adapter 可部署、可探活、可轮换 |
| Person 3 | 错误 caller、禁用 version、缺失 key 的拒绝路径通过 |

### S3. 隐私预算与抗差分查询

状态（2026-05-14）：repo-side 第一版已落地，仍是 `partial`，不标记为三人联合认证完成。

repo-side 已交付：

1. `policy_release.py` 新增可选 `--privacy-budget-ledger`、`--privacy-budget-limit`、`--privacy-budget-cost`。默认不启用，不改变既有 demo / pipeline 行为；显式启用后，release 前会计算不含 `job_id` 的预算查询 fingerprint。
2. 新增 `privacy_budget_ledger/v1` JSONL 证据：首次合法 release 消耗 budget；exact repeated fingerprint、同 caller/bucket 的重叠/包含窗口、预算耗尽都会在 release 前拒绝，并记录 `abuse_signal`、匹配的 prior job/fingerprint、budget used/cost/limit。
3. `policy_audit/v1` 新增可选 `privacy_budget` block，记录同一裁决摘要；`public_report.json` 仍只暴露 release/deny 结果和 reason，不公开 ledger 路径或已用预算。
4. `scripts/check_privacy_budget.py` 输出 `privacy_budget_check_report/v1`，用于只读汇总 ledger、按 caller 查看 consumed/deny 计数，并断言 expected deny reason。
5. 默认 contract smoke 新增三段断言：首次 release 通过、重复查询被 `privacy_budget_duplicate_query` 拒绝、disjoint window 在 budget limit=1 时被 `privacy_budget_exhausted` 拒绝，并校验 ledger 和 check-report schema。

仍需后续完成：

1. metadata sidecar 的 budget ledger read model / operator 查询入口。
2. tenant / dataset / purpose 维度的预算配置源，而不是当前 caller-local CLI 参数。
3. near-duplicate 策略的人工审批分支，以及更丰富的集合包含 / 窗口差分样例。
4. Person 1 / Person 2 / Person 3 联合认证。

目标：结果发布不只依赖 `k-threshold`、rate limit 和 exact duplicate deny，而是由隐私预算系统统一裁决。

最终状态：

1. 每个 caller / tenant / dataset / purpose 有独立 budget。
2. 每次 release 都消耗 budget。
3. exact duplicate、near duplicate、包含关系查询、窗口差分查询都进入同一 ledger。
4. 高风险查询进入人工审批或直接拒绝。
5. `public_report.json` 只显示已批准、已预算扣减的结果。

需要修改：

1. 新增 `schemas/privacy_budget_ledger.schema.json`。
2. 新增 `scripts/check_privacy_budget.py` 或集成到 `policy_release.py`。
3. `policy_release.py`：release 前计算 canonical query signature 和 near-duplicate signature。
4. metadata sidecar：新增 budget ledger read model。
5. `docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md`：把 query-abuse 从 residual risk 升级为解决路径。

验收标准：

1. 首次合法查询可 release。
2. exact duplicate 被拒绝。
3. 近似窗口查询或集合包含查询被合并计费或拒绝。
4. budget 耗尽后 release 被拒绝。
5. ledger report schema-valid。

联合认证：

| 角色 | 认证内容 |
| --- | --- |
| Person 1 | release 结果和 public report 仍正确 |
| Person 2 | ledger 可持久化、可查询、可导入 metadata sidecar |
| Person 3 | 差分攻击样例被拦截或进入审批 |

### S4. PJC 服务化、资源隔离与 DoS 防护

目标：PJC 不再只是每次脚本 spawn 的本地二进制，而是可配额、可取消、可审计的 worker service。

最终状态：

1. 长驻 PJC worker service 或 durable wrapper。
2. job queue 管理状态。
3. 每个 job 有 CPU / memory / timeout / input row 上限。
4. streaming gRPC 是默认传输。
5. 超限前预估拒绝，而不是运行到 OOM。
6. 1M×1M streaming benchmark 作为回归基线。

需要修改：

1. `a-psi/moduleA_psi/scripts/run_pjc*.sh`：继续保留 CLI，但 production wrapper 统一设置 limits。
2. 新增 PJC job preflight：估算 rows、bytes、frame count、expected memory。
3. `schemas/pjc_audit.schema.json`：加入 transport mode、chunk size、frame count、resource limit 字段。
4. `docs/BENCHMARK_PLAN.md`：保留 1M streaming 结果并新增 2M/分片对照计划。
5. `OPS_RUNBOOK.md`：写明 timeout/cancel/retry 和资源超限处理。

验收标准：

1. `PJC_GRPC_STREAM_CHUNK_ELEMENTS=4096` 的 1M×1M benchmark 通过。
2. 超过配置上限的 job 在 preflight 阶段拒绝。
3. 资源上限、chunk size、transport mode 写入 audit。
4. worker crash 或 client 失败时 job 状态可恢复为 terminal failure。

联合认证：

| 角色 | 认证内容 |
| --- | --- |
| Person 1 | 1M benchmark 结果进入报告和证据包 |
| Person 2 | worker/runner 在 Ubuntu 上可重复运行，资源限制生效 |
| Person 3 | 超大输入、异常 chunk、timeout 反例不会导致无审计失败 |

### S5. Metadata leakage 控制

目标：行数、frame 数、bucket/shard 分布等运行元数据不对普通 caller 暴露。

最终状态：

1. public report 不显示 raw row count、frame count、shard distribution。
2. 安全管理员可查看详细运行指标。
3. 小 shard 自动合并或拒绝。
4. 可选 padding 用于高敏场景。
5. threat model 明确区分 public metadata 与 operator metadata。

需要修改：

1. `policy_release.py`：public report 只输出 release-safe fields。
2. `serve_operator_dashboard.py`：按 role 控制 detailed metrics。
3. `schemas/public_report.schema.json`：确认不加入细粒度运行分布。
4. `docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md`：新增 metadata leakage target state。

验收标准：

1. 普通 caller 的 public report 不含 frame/shard/raw row distribution。
2. platform auditor 能从 audit chain 或 dashboard 查看详细指标。
3. 小 shard 低于阈值时被合并、padding 或拒绝。

联合认证：

| 角色 | 认证内容 |
| --- | --- |
| Person 1 | 报告中只展示允许公开的聚合指标 |
| Person 2 | dashboard/API role-based view 生效 |
| Person 3 | 普通 caller 无法获得细粒度规模侧信道 |

### S6. 外部不可篡改审计

状态（2026-05-14）：repo-side 生产闸门已修正为先拒绝再写入。`publish_external_audit_anchor.py --production-mode --sink-kind file_ledger` 会在本地 ledger append 前产生 `production_file_ledger_not_external`，`summary.status=fail`，并保持 disallowed local sink 不被创建或追加；`scripts/verify_external_audit_anchor_gate.sh` 已加入“生产 file_ledger 不落本地账本”的反例断言。

目标：audit chain 不只在本地可验证，还能被外部不可变存储或透明日志验证。

最终状态：

1. 每个 job 生成 audit bundle。
2. bundle hash 写入外部 append-only ledger。
3. 支持 WORM/S3 Object Lock 或 Sigstore Rekor。
4. verifier 可独立验证 public report、policy decision、PJC result hash、key access log。
5. anchor 失败不能静默通过生产发布。

需要修改：

1. `scripts/publish_external_audit_anchor.py`：生产模式要求 external anchor success。
2. `schemas/external_audit_anchor_report.schema.json`：保持 planned/uploaded/error 状态可审计。
3. `OPS_RUNBOOK.md`：写明 WORM/Rekor live drill。
4. `docs/COMPLIANCE_MAPPING.md`：把外部锚定作为合规证据。

验收标准：

1. 本地 file ledger smoke 通过。
2. 有凭证环境下 S3 Object Lock 或 Rekor live drill 通过。
3. 篡改 audit chain 后 verifier 失败。
4. anchor report 被纳入结题证据包。

联合认证：

| 角色 | 认证内容 |
| --- | --- |
| Person 1 | audit bundle 与 public report 对齐 |
| Person 2 | external anchor 运行环境和凭证配置记录完整 |
| Person 3 | tamper test 和 external verifier 通过 |

### S7. 两机 mTLS 联合验证

目标：不能只依赖 loopback；跨机构通信必须在两台机器上以 mTLS 验证。

最终状态：

1. Party A / Party B 各自部署 worker。
2. 证书由内部 CA 或 Vault PKI 签发。
3. job_id 与证书 identity 绑定。
4. 双方通过 mTLS 执行 PJC。
5. 至少完成 1M streaming 或等比例可解释的大规模两机验证。

需要修改：

1. `docs/PJC_TLS_GUIDE.md`：加入 streaming 1M 两机验证流程。
2. `a-psi/moduleA_psi/scripts/run_pjc_server_tls.sh` / `run_pjc_client_tls.sh`：默认传递 streaming 参数。
3. `schemas/pjc_audit.schema.json`：记录 TLS/mTLS、peer identity、cert fingerprint。
4. `docs/team/TEAM_COLLABORATION_AND_REPORTING_PLAN.md`：落实多人联合认证责任。

验收标准：

1. 两机 health / cert fingerprint 检查通过。
2. mTLS 下 PJC 结果正确。
3. 错误证书、过期证书、错误 peer identity 被拒绝。
4. 两方分别保存本方 audit，并能由 Person 1 合并为结题证据。

联合认证：

| 角色 | 认证内容 |
| --- | --- |
| Person 1 | 两机结果、双方 audit、报告证据一致 |
| Person 2 | 两台 Ubuntu 环境、证书、端口、服务运行通过 |
| Person 3 | 错误证书、重放、MITM 替换反例被拒绝 |

### S8. 抗恶意 PJC / Commit-and-Prove

目标：PJC 不只假设半诚实参与方，而是绑定输入、结果和策略，防止恶意构造输入或伪造 value。

最终状态：

1. 双方在 PJC 开始前提交 input commitment。
2. normalizer version、token scope、token key version 被签名或写入 commitment。
3. PJC result 与 input commitment 绑定。
4. value range 和输入规模有证明或强校验。
5. 条件成熟后替换或增强为 malicious-secure PSI-SUM。

需要修改：

1. 新增 `schemas/pjc_input_commitment.schema.json`。
2. bridge 生成 commitment manifest。
3. PJC runner 在执行前验证双方 commitment。
4. policy release 验证 result hash 与 commitment 链接。
5. `docs/CRYPTO_COMPETITION_INSTRUCTIONS.md`：记录从半诚实到抗恶意的协议升级路径。

验收标准：

1. 正常 commitment job 通过。
2. 改动 input CSV 后 PJC 前置验证失败。
3. 改动 value range 或 token scope 后失败。
4. public report 能引用 commitment hash。

联合认证：

| 角色 | 认证内容 |
| --- | --- |
| Person 1 | commitment hash 进入报告链路 |
| Person 2 | commitment manifest 生成、传输、归档稳定 |
| Person 3 | 篡改 input/value/token-scope 的反例被拒绝 |

## 4. 优先级

推荐执行顺序：

| 优先级 | 任务 | 原因 |
| --- | --- | --- |
| P0 | S1 消除明文 handoff 落盘 | 直接解决最现实的中间数据暴露 |
| P0 | S2 正式 KMS 与密钥生命周期 | 解决 token secret 可信根 |
| P0 | S3 隐私预算与抗差分查询 | 解决发布侧推断攻击 |
| P1 | S4 PJC 服务化、资源隔离与 DoS 防护 | 解决 1M 之后的稳定性和资源风险 |
| P1 | S6 外部不可篡改审计 | 解决证据可信度 |
| P1 | S7 两机 mTLS 联合验证 | 解决跨机构实测可信度 |
| P2 | S5 Metadata leakage 控制 | 解决规模侧信道 |
| P2 | S8 抗恶意 PJC / Commit-and-Prove | 解决半诚实模型外的长期安全性 |

## 5. 报告口径

pre 和结题报告中必须区分三种状态：

| 状态 | 含义 | 可以怎么写 |
| --- | --- | --- |
| Completed | 代码、测试、证据、文档、联合认证都完成 | “已完成并通过联合认证” |
| Repo-side complete | 仓库内实现和 smoke 完成，但缺真实外部服务或凭证 | “repo-side 已完成，live 环境由 operator 提供” |
| Planned | 只有设计，没有实现和证据 | “生产化后续任务，不作为当前完成能力宣称” |

禁止把 `Planned` 写成“已支持”。禁止把只有单人自测的功能写成“已通过联合认证”。

## 6. 与其他文档关系

1. handoff：[`docs/BRIDGE_HANDOFF_HARDENING_PLAN.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/BRIDGE_HANDOFF_HARDENING_PLAN.md)
2. KMS：[`docs/KMS_SECRET_BACKEND_PLAN.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/KMS_SECRET_BACKEND_PLAN.md)
3. threat model：[`docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md)
4. PJC TLS：[`docs/PJC_TLS_GUIDE.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PJC_TLS_GUIDE.md)
5. team certification：[`docs/team/TEAM_COLLABORATION_AND_REPORTING_PLAN.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/team/TEAM_COLLABORATION_AND_REPORTING_PLAN.md)

如果这些文档与本文档冲突，以本文档的生产级安全目标态为准；模块文档负责记录实现细节和命令。
