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

最安全实现方式：

1. 生产环境只允许 `vault_http`、`aws_kms` 或等价云 KMS 后端作为 active key version；`env`、`keyring_file`、`vault_kv` fixture 只能用于 demo / contract smoke。
2. 所有主链路入口统一传 `--token-secret-key-name`，由 key-agent / external-KMS adapter 按 `caller + tenant_id + dataset_id + purpose + job_id` 解析 key version。
3. KMS 服务端必须使用 mTLS 或 service-token/HMAC request signing；key access audit 必须记录 `backend_kind`、`key_ref`、`key_version`、`caller`、`scope`、`decision` 和 `reason_code`。
4. key rotation 走 metadata registry 的 managed mutation：新 version 先进入 `enabled=false`，reachability + dry-run 通过后再启用；旧 version 进入 verify-only / disabled 状态，不再允许新 job mint token。
5. 生产闸门执行顺序固定为：KMS reachability `--production-mode` -> keyring active backend kind check -> disabled-version negative test -> pipeline production demo。
6. live 证据目录固定保存：KMS reachability report、key access audit、rotation mutation log、disabled-version deny report、pipeline public report。

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

状态（2026-05-20）：本机 production-style 闭环已落地并通过证据脚本验证。`policy_release.py` 支持 `--privacy-budget-required`、`--privacy-budget-config`、`--tenant-id`、`--dataset-id`、`--purpose`；生产预算模式缺 ledger 会 fail closed，缺匹配 scope 会拒绝为 `privacy_budget_missing_scope`。新增 `scripts/run_s3_privacy_budget_production_evidence.sh`，覆盖 required-without-ledger、configured first release、exact duplicate、overlap near duplicate、budget exhausted、missing scope 六个 case。该证据可写为“本机生产式隐私预算闭环完成”，但在 operator 查询入口、metadata sidecar 持久化、VPS/公网部署和联合认证完成前，不写为“真实生产部署闭环完成”。

状态（2026-05-26）：metadata sidecar 的 budget ledger read model / operator 查询入口已 repo-side 推进。新增 `privacy_budget_ledger_events` 表；`import_run_metadata.py` 会在 run bundle 中发现 `a_psi_run/privacy_budget_ledger.jsonl` 或根目录 `privacy_budget_ledger.jsonl` 时导入 ledger 记录；`query_metadata.py --list-entity privacy-budget-ledger` 支持按 caller / tenant / dataset / purpose 查询，job detail 也会返回该 run 关联的 privacy-budget ledger events。默认 contract smoke 已覆盖导入、scope 查询和 job-detail 查询。S3 仍保持 `partial`：operator query submission 透传、人工审批分支、VPS/公网证据和三人联合认证尚未完成。

状态（2026-05-26 v2）：operator/query submission 的 repo-side 透传已补齐。`query_workflow_request/v1` 新增可选 `privacy_budget_required`、`privacy_budget_config`、`privacy_budget_ledger`、`privacy_budget_purpose`、`privacy_budget_limit`、`privacy_budget_cost`；`submit_query_workflow.py` 会做 required/config/ledger fail-closed 校验并透传到 `run_sse_bridge_pipeline.sh`；pipeline Stage4 会把 tenant / dataset / purpose scope 和 budget 参数传给 `policy_release.py`。默认 contract smoke 新增 dry-run command 断言，并覆盖 required 模式缺 config / 缺 ledger 的提交入口拒绝负例，证明 operator/query submission 入口不会再停在手工 `policy_release.py` 调用层。S3 仍保持 `partial`：人工审批分支、VPS/公网证据和三人联合认证尚未完成。

repo-side 已交付：

1. `policy_release.py` 新增可选 `--privacy-budget-ledger`、`--privacy-budget-limit`、`--privacy-budget-cost`。默认不启用，不改变既有 demo / pipeline 行为；显式启用后，release 前会计算不含 `job_id` 的预算查询 fingerprint。
2. 新增 `privacy_budget_ledger/v1` JSONL 证据：首次合法 release 消耗 budget；exact repeated fingerprint、同 caller/bucket 的重叠/包含窗口、预算耗尽都会在 release 前拒绝，并记录 `abuse_signal`、匹配的 prior job/fingerprint、budget used/cost/limit。
3. `policy_audit/v1` 新增可选 `privacy_budget` block，记录同一裁决摘要；`public_report.json` 仍只暴露 release/deny 结果和 reason，不公开 ledger 路径或已用预算。
4. `scripts/check_privacy_budget.py` 输出 `privacy_budget_check_report/v1`，用于只读汇总 ledger、按 caller 查看 consumed/deny 计数，并断言 expected deny reason。
5. 默认 contract smoke 新增三段断言：首次 release 通过、重复查询被 `privacy_budget_duplicate_query` 拒绝、disjoint window 在 budget limit=1 时被 `privacy_budget_exhausted` 拒绝，并校验 ledger 和 check-report schema。
6. production-style 本机闭环新增 scope 维度：caller / tenant / dataset / purpose 进入 canonical budget payload 和 ledger；`privacy_budget_config/v1` 用 default `max_queries=0` 实现未配置 scope 默认拒绝。
7. 新增证据包：`tmp/s3_privacy_budget_production_evidence/verification_summary.json`，最近运行结果 `status=pass`、`cases=6`、`ledger_records=5`。
8. consolidated attack-surface gate 已包含 `s3_privacy_budget_production_evidence`，最近运行结果 `tmp/attack_surface_hardening_evidence/verification_summary.json` 为 `status=pass`、`case_count=12`、`pass_count=12`、`fail_count=0`。
9. metadata sidecar read model 已完成 repo-side：`migrations/metadata/013_add_privacy_budget_ledger_read_model.sql`、PostgreSQL DDL parity、`import_run_metadata.py` ledger import、`query_metadata.py --list-entity privacy-budget-ledger`，以及 default contract smoke 查询断言。
10. operator/query submission wiring 已完成 repo-side：`query_workflow_request/v1`、`submit_query_workflow.py`、`run_sse_bridge_pipeline.sh` 和 default contract smoke 会把 privacy budget required/config/ledger/scope/limit/cost 送入 Stage4 release，并断言 required 模式缺 config / ledger 会在提交入口 fail closed。

仍需后续完成：

1. near-duplicate 策略的人工审批分支，以及更丰富的集合包含 / 窗口差分样例。
2. 在 VPS/公网部署运行同一闭环证据，确认生产部署路径与本机证据一致。
3. Person 1 / Person 2 / Person 3 联合认证。

目标：结果发布不只依赖 `k-threshold`、rate limit 和 exact duplicate deny，而是由隐私预算系统统一裁决。

最终状态：

1. 每个 caller / tenant / dataset / purpose 有独立 budget。
2. 每次 release 都消耗 budget。
3. exact duplicate、near duplicate、包含关系查询、窗口差分查询都进入同一 ledger。
4. 高风险查询进入人工审批或直接拒绝。
5. `public_report.json` 只显示已批准、已预算扣减的结果。

最安全实现方式：

1. 把 `privacy_budget_config/v1` 作为 release 的强制输入，而不是可选 CLI 参数；生产 release 缺 config 或 ledger 一律 fail closed。
2. budget ledger 从 JSONL 过渡到 metadata sidecar / PostgreSQL read-write model：按 `caller_id + tenant_id + dataset_id + purpose + query_fingerprint` 建唯一索引，避免并发重复扣减。
3. query submission API 必须透传并冻结 `tenant_id`、`dataset_id`、`purpose`、filter window、bucket/shard scope；release 侧只接受由 submission manifest 派生的 canonical budget payload。
4. exact duplicate、窗口 overlap、集合包含、相邻时间窗、低 k/high epsilon 统一进入 budget evaluator；低风险合并计费，高风险进入 approval queue 或直接 deny。
5. budget decision 写入 `policy_audit/v1`，operator 侧可看 matched prior query 摘要；public report 只暴露 `released/denied` 和公开 reason，不暴露 ledger path、prior fingerprint 或剩余额度。
6. 回归证据必须包含：首次通过、exact duplicate、overlap、subset/superset、budget exhausted、missing scope、concurrent duplicate 两请求只有一个扣减成功。

需要修改：

1. 新增 `schemas/privacy_budget_ledger.schema.json`。
2. 新增 `scripts/check_privacy_budget.py` 或集成到 `policy_release.py`。
3. `policy_release.py`：release 前计算 canonical query signature 和 near-duplicate signature。
4. ~~metadata sidecar：新增 budget ledger read model。~~ ✓ repo-side 完成（2026-05-26）。
5. `docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md`：把 query-abuse 从 residual risk 升级为解决路径。

验收标准：

1. 首次合法查询可 release。
2. exact duplicate 被拒绝。
3. 近似窗口查询或集合包含查询被合并计费或拒绝。
4. budget 耗尽后 release 被拒绝。
5. ledger report schema-valid。
6. production required 模式缺 ledger 时 fail closed。
7. 未匹配 caller / tenant / dataset / purpose scope 时拒绝为 `privacy_budget_missing_scope`。

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

最安全实现方式：

1. PJC 不再由裸 shell 直接长期暴露端口；生产由 `systemd` service、Kubernetes Job，或轻量 worker daemon 启动，统一设置 CPU/memory/pids/no-new-privileges/private-tmp/read-only-rootfs 等资源边界。
2. 所有 PJC job 先进入 queue，状态机固定为 `submitted -> preflighted -> running -> succeeded|failed|cancelled|rejected`；每个状态迁移写 audit。
3. preflight 读取双方 `job_meta.json`、CSV row count、byte size、bucket count、chunk size 和 configured resource limits；超过阈值在启动 PJC binary 前拒绝。
4. 默认使用 streaming gRPC；如果二进制不支持 `--grpc_stream_chunk_elements`，生产 wrapper 必须 fail closed，不能静默降级到 unary。
5. worker 必须支持 timeout/cancel：超时后终止 PJC child、清理 socat/proxy、写 terminal failure，并保留 server/client log hash。
6. 证据包固定保存：preflight allow/deny report、resource limit config、PJC audit、server/client logs、worker status transitions、1M streaming benchmark、oversized negative case。

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

状态（2026-05-17）：字段级 redaction 半部已 repo-side 完成（见
[`CONTROL_PLANE_HARDENING_LOG.md`](/home/llvanion/Desktop/seccomp-privacy-platform/docs/CONTROL_PLANE_HARDENING_LOG.md)
§ Round 7）；小 shard 自动合并 / padding 仍为 Owner / Engineer B 任务。整体仍标记为
`partial`，待两半都完成并联合认证后才能升级为 `Completed`。

repo-side 已交付（Round 7 / 2026-05-17）：

1. `a-psi/moduleA_psi/scripts/policy_release.py` 新增 `--public-report-redact-operator-fields`：
   开启后 `public_report.json` 不再携带 `input_sizes` / `rate_limit_used` / `rate_limit_max` /
   `bridge` / `details` 五个 operator-only 字段，并在报告体上加 `operator_fields_redacted: true` 标记。
2. 同一开关下，`policy_release.py` 写出 sibling `operator_release_report/v1` 文档
   （路径由 `--operator-report-path` 指定，缺省 `<out>.operator.json`），完整字段仍可由 operator 控制台读取。
3. `policy_postprocess_buckets.py` 新增同名开关：开启后不再把 `debug.per_bucket_results` /
   `debug.bucket_policy` 注入 `public_report.json`，只留 `debug.bucket_results_redacted: true` 标记；
   独立的 `bucket_public_report.json` 不受影响，operator 控制台仍可看到完整 per-bucket 数据。
4. `run_bucketed_scale_test.sh` 默认带 `--public-report-redact-operator-fields` 与
   `--operator-report-path "$OUT_DIR/operator_report.json"`，所以打包的 bucket 化 scale test 不会再无意泄露。
5. `scripts/check_bucket_dp_smoke.py` 扩展出第二轮 redacted run：断言
   redacted `public_report.json` 不含任何 operator-only key、sibling `operator_report.json`
   仍带完整集合且 schema 为 `operator_release_report/v1`、bucket 后处理在 redacted 模式下不写 per-bucket 详情。
   该 smoke 默认通过 `scripts/check_json_contracts.sh` 在每次 contract smoke 都执行。

目标（保持不变）：行数、frame 数、bucket/shard 分布等运行元数据不对普通 caller 暴露。

最终状态：

1. ~~public report 不显示 raw row count、frame count、shard distribution。~~ ✓ repo-side 完成。
2. ~~安全管理员可查看详细运行指标。~~ ✓ 经由 `operator_release_report/v1` + 现有 audit chain / dashboard。
3. 小 shard 自动合并或拒绝。**仍未完成**（Owner / Engineer B 任务）。
4. 可选 padding 用于高敏场景。**仍未完成**。
5. ~~threat model 明确区分 public metadata 与 operator metadata。~~ ✓
   `docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md` §8 已更新。

最安全实现方式：

1. public report schema 采用 allowlist，只输出 release-safe 聚合字段；任何新增字段默认只能进 operator report，不能自动进入 public report。
2. dashboard / metadata API 按 identity role 分层：普通 caller 只能读 public report；`platform_auditor` 可读 audit 摘要；`privacy_operator` / `platform_admin` 才能读 raw row count、bucket distribution、timing 和 debug fields。
3. bucket/shard 低于公开阈值时，不仅结果 suppression，还要在 metadata 层合并到 `other` bucket、延迟发布或 padding；不能暴露“某个小 bucket 被 suppressed”的精确规模侧信道。
4. bucketed reports 分两份：`bucket_public_report.json` 只含 release-safe bucket labels 与 DP 后结果；`operator_bucket_report.json` 含原始 per-bucket debug，仅 role-gated。
5. contract smoke 增加普通 caller API 请求负例：不能通过 `/v1/dashboard`、metadata job detail、audit include-paths 或 public-report API 拿到 operator-only 字段。

仍需修改：

1. ~~`policy_release.py`：public report 只输出 release-safe fields。~~ ✓ repo-side 完成。
2. `serve_operator_dashboard.py`：按 role 控制 detailed metrics。**仍未完成** — 当前 redacted
   字段直接走 sibling JSON，没有按 dashboard role gate。
3. `schemas/public_report.schema.json`：确认不加入细粒度运行分布。需要核对 schema 是否需要把
   `operator_fields_redacted` 列入可选字段。
4. ~~`docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md`：新增 metadata leakage target state。~~ ✓

验收标准：

1. ~~普通 caller 的 public report 不含 frame/shard/raw row distribution。~~ ✓ — 经 `check_bucket_dp_smoke.py` 断言。
2. ~~platform auditor 能从 audit chain 或 dashboard 查看详细指标。~~ ✓ — operator_release_report/v1 + audit。
3. 小 shard 低于阈值时被合并、padding 或拒绝。**仍未完成**。

联合认证：

| 角色 | 认证内容 |
| --- | --- |
| Person 1 | 报告中只展示允许公开的聚合指标（字段级 redaction 已 repo-side 完成） |
| Person 2 | dashboard/API role-based view 生效（仍待 Engineer B） |
| Person 3 | 普通 caller 无法获得细粒度规模侧信道（字段级已闭环；小 shard 仍待 Owner） |

### S6. 外部不可篡改审计

状态（2026-05-14）：repo-side 生产闸门已修正为先拒绝再写入。`publish_external_audit_anchor.py --production-mode --sink-kind file_ledger` 会在本地 ledger append 前产生 `production_file_ledger_not_external`，`summary.status=fail`，并保持 disallowed local sink 不被创建或追加；`scripts/verify_external_audit_anchor_gate.sh` 已加入“生产 file_ledger 不落本地账本”的反例断言。

边界口径（2026-05-23）：审计可信度不是要求学生项目自建外部不可变基础设施。
项目侧必须生成稳定的 audit bundle、evidence merge、policy-gate report、hash
和 external-anchor request/report；外部不可变可信根由部署方提供。可选可信根包括
Rekor/Sigstore、AWS S3 Object Lock、企业 WORM storage、timestamp authority
或内部审计平台。没有 AWS 企业账号时，不能把 S3 live drill 未完成写成项目安全缺陷；
应写成 `operator-provided external sink unavailable`，并保留接口、schema、hash
和本地 negative gate 证据。

目标：audit chain 不只在本地可验证，还能被外部不可变存储或透明日志验证。

最终状态：

1. 每个 job 生成 audit bundle。
2. bundle hash 写入外部 append-only ledger。
3. 支持 WORM/S3 Object Lock 或 Sigstore Rekor。
4. verifier 可独立验证 public report、policy decision、PJC result hash、key access log。
5. anchor 失败不能静默通过生产发布。

最安全实现方式：

1. 生产只允许 `s3_worm`、`rekor`、企业 WORM storage、timestamp authority
   或内部审计平台这类部署方提供的外部不可变 sink；`file_ledger` 在
   `--production-mode` 下只能作为 negative case。
2. release gate 必须在 public report 进入 completed 前完成 external anchor；anchor report 状态不是 `uploaded/verified` 时，release 状态保持 `blocked` 或 `pending_external_anchor`。
3. 如部署方选择 S3 Object Lock，bucket 必须启用 versioning + Object Lock，默认 COMPLIANCE mode，tenant id 必须出现在 S3 key path segment；跨租户 key path 直接拒绝。没有企业账号时，该 live drill 标记为 operator-provided。
4. Rekor 路径必须使用独立 signing key，签名 canonical anchor payload，并保存 uuid/logIndex/integratedTime；verify 路径必须重新拉取或校验 transparency log inclusion。
5. 证据包固定保存：audit bundle hash、anchor report、external sink object/version/uuid、tamper negative report、production local-file deny report。

需要修改：

1. `scripts/publish_external_audit_anchor.py`：生产模式要求 external anchor success。
2. `schemas/external_audit_anchor_report.schema.json`：保持 planned/uploaded/error 状态可审计。
3. `OPS_RUNBOOK.md`：写明 WORM/Rekor live drill。
4. `docs/COMPLIANCE_MAPPING.md`：把外部锚定作为合规证据。

验收标准：

1. 本地 file ledger smoke 通过。
2. 有凭证环境下 S3 Object Lock、Rekor 或部署方等价 external sink live drill 通过；无企业账号时记录 `operator-provided external sink unavailable`，不阻塞学生侧 repo-side 完成状态。
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

最安全实现方式：

1. 生产目标态不再依赖“双方交换 IP/端口后临时互信”。双方先进入受控网络（WireGuard/Tailscale/private VPC），PJC data-plane 不直接暴露到全公网。
2. workload identity 由 SPIFFE/SPIRE 签发短期 X.509 SVID，Envoy sidecar 或 service mesh 负责 mTLS。临时 `pjc-mtls://enroll` / pairing-token CSR enrollment 只作为两机 demo 和过渡方案。
3. SPIFFE trust domain、Party A/B workload selector、允许的 peer SPIFFE ID、证书 TTL、rotation policy 固定写入 deployment config；业务脚本不直接持有长期 CA key。
4. 每个 PJC job 仍生成 job-bound evidence：`job_id`、peer SPIFFE ID 或 job-bound SAN、cert fingerprint、trust bundle fingerprint、notBefore/notAfter、TLS decision、server/client log hash。
5. 两机证据分三类：positive mTLS PJC result、wrong peer identity deny、expired/wrong CA deny。没有 negative cases 不能升级为 Completed。
6. 当前 `socat` TLS wrapper 保留为 local/demo fallback；生产 wrapper 应改为 Envoy listener -> loopback PJC binary，并由 readiness probe 确认 peer auth policy 已加载。

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

最安全实现方式：

1. 在 bridge 输出 CSV 的同时生成 `pjc_input_commitment/v1`：包含 input file SHA-256、row count、value range summary、normalizer schema version、token scope、token key id/version、bucket/shard scope 和生成时间。
2. 双方在 PJC 开始前交换 commitment manifest，只交换 hash/metadata，不交换 raw rows；PJC runner 在启动前验证本地 CSV hash 与对方 commitment digest 链接。
3. PJC result 文件必须引用双方 commitment hash；policy release 验证 `pjc_result_sha256 + server_commitment_sha256 + client_commitment_sha256 + job_id` 一致后才可 release。
4. 对 value 字段增加强校验：非负、上限、整数单位、允许币种/单位、bucket field allowlist；超出范围 preflight deny。
5. 短期采用 commit-and-verify 防篡改；长期评估 malicious-secure PSI-SUM 或 ZK/range-proof 方案。未完成协议升级前，报告必须写明仍假设 PJC 参与方半诚实。
6. 负例证据必须覆盖：改 input CSV、改 value、改 token_scope、改 normalizer version、替换 result hash，均在 PJC 前或 release 前被拒绝。

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

### S9. 双方一步到位开箱即用

目标：Party A 和 Party B 不再依赖人工拼命令、手动 scp 证书、猜端口、
手动比对日志。双方只需要准备运行环境、确认对方身份渠道、粘贴一次安全邀请，
就能完成 enrollment、preflight、PJC 运行、证据合并和反例验证。

最终状态：

1. Party A 在 X-UI 创建 job-bound secure invite；Party B 在 X-UI 粘贴 invite。
2. UI 自动完成 CSR enrollment：Party B 私钥只在本机生成，Party A 只签 CSR。
3. UI 自动运行 preflight：commit、脚本版本、PJC binary、端口、TLS、peer identity、manifest hash、资源限制、输出路径全部通过后才能启动。
4. UI 支持 Party A server role 与 Party B client role 的 start/status/cancel。
5. UI 支持 role package export/import，所有包都有 schema、hash manifest、expected peer、端口和 job policy。
6. UI 支持 evidence verify-merge；双方证据不一致时不能 release。
7. UI 支持强制 negative cases：wrong token、expired token、wrong CA、wrong peer、closed port、commit mismatch、modified CSV、privacy denial。
8. 生产部署默认 SPIFFE/SPIRE + Envoy/service mesh；裸机 `pjc-mtls://enroll` 只作为 controlled fallback。

最安全实现方式：

Repo-side 状态（2026-05-23）：S9 控制面代码已在
`scripts/serve_operator_dashboard.py` 实现，新增 schema 已进入 `schemas/`，
`scripts/check_pjc_two_party_smoke.py` 覆盖 helper/endpoints 的 happy/deny
路径，`scripts/check_json_contracts.sh` 已校验五个新 schema。仍未完成的是
真实两机/VPS 证据；guided frontend wizard、SPIFFE/SPIRE + Envoy
生产部署模板、TLS diagnostic 和 release policy gate 已 repo-side 完成。

1. 控制台已新增稳定接口：
   - `POST /v1/pjc-mtls/preflight`
   - `POST /v1/pjc/role-package/export`
   - `POST /v1/pjc/role-package/import`
   - `POST /v1/pjc/roles/server/start`
   - `POST /v1/pjc/roles/client/start`
   - `GET /v1/pjc/roles/{role}/status`
   - `POST /v1/pjc/roles/{role}/cancel`
   - `POST /v1/pjc/evidence/verify-merge`
   - `POST /v1/pjc-mtls/negative-cases/run`
2. `preflight` 已生成 `pjc_two_party_preflight/v1`：记录双方 commit、helper hash、binary hash、TCP/TLS probe、peer identity decision、manifest hash、resource limits 和 output path。
3. role package 已生成 `pjc_role_package/v1`：只包含执行所需的 manifest、hash、job policy、端口、peer identity、redacted notes，不包含对方 raw data；import 会拒绝 hash mismatch 和 undeclared files。
4. role lifecycle 已生成 `pjc_role_status/v1`：记录 pid、命令摘要、env allowlist digest、端口、日志路径、退出码、cancel reason 和 log hash。
5. evidence merge 已生成 `pjc_two_party_evidence_merge/v1`：验证 Party A/B 的 job id、commit、input commitment、TLS identity、CA/trust-bundle fingerprint、result hash、policy decision 和 audit-chain hash。
6. negative-case runner 已生成 `pjc_two_party_negative_cases/v1`：每个反例都有 expected deny reason；缺任一反例不能进入 Completed。
7. ~~待完成：前端把这些接口做成同一个 guided wizard~~ Repo-side done (2026-05-23 v2)：`scripts/serve_operator_dashboard.py` 的 `#s9-wizard` 把 `Invite → Enroll → Preflight → Run → Verify → Negative cases → Archive` 串成同一个流程，按 endpoint 返回的 `decision=allow` / `status=ok` 才能进入下一步；所有 typed reports 在面板内直显。
8. ~~待完成：生产部署模板~~ Repo-side done (2026-05-23 v2)：`deploy/spiffe_envoy/` 提供 SPIRE Server/Agent、Envoy Party A/B、`peer_spiffe_allowlist.json`（`spiffe_envoy_peer_allowlist/v1`）和 `rotation_notes.md`；`scripts/check_spiffe_envoy_templates.py` 输出 `spiffe_envoy_template_check/v1`，已接入 `scripts/check_json_contracts.sh --assert-allow`。
9. Repo-side done (2026-05-23 v2)：`POST /v1/pjc-mtls/tls-diagnostic` + `pjc_tls_diagnostic/v1` 把 VPS `10502` TLS EOF 的 TCP / TLS / 本地证书 / 服务端日志症状捕成 typed report；`scripts/check_pjc_tls_diagnostic_smoke.py` 覆盖 closed-port、`tls_eof`、缺失本地证书三种确定性本地场景。
10. Repo-side done (2026-05-23 v2)：服务端 release policy gate `POST /v1/release/policy-gate` + `scripts/check_release_policy_gate.py` 通过 `config/release_policy_gate.example.json`（`release_policy_gate_config/v1`）强制 `require_dp` + DP epsilon 范围 + `min_k` + privacy budget ledger + duplicate-query 防护，关闭 `policy_release.py --require-dp` CLI 旁路；`scripts/check_release_policy_gate_smoke.py` 覆盖缺 ledger / 低 k / 缺 DP / allow / duplicate leak 五种场景。

需要修改：

1. ~~`scripts/serve_operator_dashboard.py`：新增 preflight、role package、role lifecycle、evidence merge、negative-case endpoints。~~ Repo-side done.
2. ~~`schemas/`：新增 `pjc_two_party_preflight.schema.json`、`pjc_role_package.schema.json`、`pjc_role_status.schema.json`、`pjc_two_party_evidence_merge.schema.json`、`pjc_two_party_negative_cases.schema.json`。~~ Repo-side done.
3. ~~`scripts/check_pjc_two_party_smoke.py`：新增 focused smoke，并接入 `scripts/check_ci_smoke.sh`；五个 schema 接入 `scripts/check_json_contracts.sh`。~~ Repo-side done.
4. 待完成：`a-psi/moduleA_psi/scripts/` 与真实 Party A/B runner 的 live VPS 证据归档（不是 wrapper —— `_role_command` 现在默认指向 `run_pjc_bucketed_tls_server.sh` / `run_pjc_bucketed_tls_client.sh`，包含 `PJC_DIR` / `PJC_RESOURCE_LIMITS` / `PJC_PREFLIGHT_*` 等环境透传与 fail-closed cert / role_dir 校验；仍欠真实双机执行的证据。）
5. ~~待完成：完整 guided frontend wizard。~~ Repo-side done (2026-05-23 v2)。
6. 持续维护：`docs/CONTROL_PANEL_SPEC.md`、`docs/PJC_TLS_GUIDE.md`、`docs/PJC_MTLS_OPEN_RISKS.md` 必须区分 repo-side done 与 live production certified。

双机验证优先使用脚本和 typed endpoints，不以手工查看日志作为主要证据：

1. 两台机器先同步到同一 commit；VPS 不能直接访问 GitHub 时，从本机运行
   `scripts/sync_vps_github_via_local_proxy.sh`。
2. Party A 用 `a-psi/moduleA_psi/scripts/serve_pjc_mtls_enrollment_party_a.sh`
   发起 enrollment；Party B 用
   `a-psi/moduleA_psi/scripts/enroll_pjc_mtls_party_b.sh` 和
   `PJC_MTLS_BOOTSTRAP` 完成 CSR enrollment。
3. bucketed job 由
   `a-psi/moduleA_psi/scripts/generate_bucketed_pjc_dataset.py` 生成，并由
   `a-psi/moduleA_psi/scripts/split_bucketed_pjc_job_for_parties.py` 拆成双方
   role package。
4. 控制台 wizard 或 direct API 依次调用 preflight、role package
   export/import、role start/status、evidence merge、release policy gate 和
   negative cases。
5. 如果 `10502` 或其他 data-plane TLS 失败，先调用
   `POST /v1/pjc-mtls/tls-diagnostic` 产出 `pjc_tls_diagnostic/v1`，再修改配置。
6. 归档 `pjc_two_party_preflight/v1`、`pjc_role_package/v1`、
   `pjc_role_status/v1`、`pjc_two_party_evidence_merge/v1`、
   `release_policy_gate/v1`、`pjc_two_party_negative_cases/v1` 和必要的
   `pjc_tls_diagnostic/v1`。

验收标准：

1. 两台真实机器从空证书目录开始，只通过 secure invite 完成 enrollment。
2. preflight 在正常场景 allow，在 closed port / wrong CA / wrong peer / commit mismatch / modified CSV 场景 deny。
3. Party A/B 通过 UI 启动各自 role，PJC result 与 expected result 一致。
4. evidence merge 通过，并能拒绝任意一侧替换日志、manifest 或 result。
5. negative-case summary 中所有强制反例均为 expected denial。
6. 所有证据 schema 校验通过，报告中明确标识 SPIFFE/SPIRE production path 或 CSR fallback path。

联合认证：

| 角色 | 认证内容 |
| --- | --- |
| Person 1 | UI wizard、role lifecycle、evidence merge 的端到端证据 |
| Person 2 | role package、manifest hash、bucketed PJC result 一致性 |
| Person 3 | identity/preflight/negative cases、安全部署模板 |

## 4. 优先级

推荐执行顺序：

| 优先级 | 任务 | 原因 |
| --- | --- | --- |
| P0 | S1 消除明文 handoff 落盘 | 直接解决最现实的中间数据暴露 |
| P0 | S2 正式 KMS 与密钥生命周期 | 解决 token secret 可信根 |
| P0 | S3 隐私预算与抗差分查询 | 解决发布侧推断攻击 |
| P0 | S9 双方一步到位开箱即用 | 解决产品可用性与两机安全闭环，不能只靠脚本文档 |
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
