# 三人协作、环境与汇报计划

这份文档解决四个问题：

1. 当前项目口径如何避免漂移。
2. 三个人分别做什么、怎么交接。
3. 需要什么系统和设备，是否必须 Ubuntu。
4. 测试通过以后，如何呈现在 pre 和结题报告里。

## 1. 当前统一口径

对外描述必须统一成：

```text
这是一个面向电商场景的隐私计算平台基线，主链路是
SSE candidate export -> controlled record recovery -> Rust bridge tokenization -> A-PSI/PJC -> policy release。
```

可以说：

1. 平台基线已经完成。
2. 本地 demo、live SSE demo、contract smoke、主要 benchmark 和安全门禁都有可复现脚本。
3. SQL sidecar 已经有 control-plane metadata、audit、permission、workflow，以及 Track-E1 电商事实层 6 表基线。
4. 项目支持展示“隐私查询从请求、授权、候选恢复、token 化、PJC 计算、策略发布、审计归档”的完整闭环。

不能说：

1. 这是完整生产级多租户电商平台。
2. 已经默认接入真实 Keycloak / OpenFGA / Vault / AWS KMS 的长期生产环境。
3. 已经具备完整 customer 360、完整订单数仓、成熟前端产品和生产级 HA。
4. 外部渗透测试已经完成，除非 Person 3 已经提交正式报告。

## 2. 环境与设备建议

### 2.1 是否必须 Ubuntu

推荐 Ubuntu，原因是当前脚本、依赖和运维文档都按 Linux 本地服务边界设计：

1. Bash 脚本是主入口。
2. record recovery 使用 Unix socket / 本地 HTTP / systemd 形态。
3. Rust bridge、Python venv、Bazel/PJC、PostgreSQL/pgBouncer/Patroni 示例都更适合 Linux。
4. contract smoke 和 benchmark 的路径、权限、socket 行为在 Ubuntu 上最稳定。

最低建议：

| 用途 | 推荐系统 | 说明 |
| --- | --- | --- |
| 开发与 pre 演示 | Ubuntu 22.04 LTS 或 24.04 LTS | 最稳妥 |
| Windows 机器 | WSL2 Ubuntu 22.04/24.04 | 可以跑大部分本地脚本，但不建议承担 live 服务靶场 |
| macOS | 不推荐作为主验证机 | Bash/Python/Rust 可用，但 Unix socket、GNU 工具、Bazel/PJC、系统服务行为可能漂移 |
| 安全测试机 | Ubuntu 或 Kali | repo 内脚本用 Ubuntu 更省心；外部工具可以用 Kali |

### 2.2 三人设备分配

不强制每个人都有多台机器，但推荐至少 3 台 Ubuntu/WSL2 工作机。如果要做 live 服务边界和安全测试，最好有 4-5 个逻辑环境。

| 角色 | 最少设备 | 推荐配置 | 用途 |
| --- | --- | --- | --- |
| Person 1 | 1 台 | 8 核 CPU / 16 GB RAM / 50 GB 空间 / Ubuntu | 统筹、主链路 demo、报告汇总、pre 演示 |
| Person 2 | 1 台 | 8 核 CPU / 16-32 GB RAM / 80 GB 空间 / Ubuntu | recovery service、PostgreSQL/pgBouncer/Patroni、observability、live targets |
| Person 3 | 1 台 | 4-8 核 CPU / 16 GB RAM / 50 GB 空间 / Ubuntu 或 Kali | 安全测试、审计验证、合规证据、外部 pen-test 对接 |

如果只有一台高配 Ubuntu，也可以按目录和端口隔离三个人的任务，但结题报告里要写清楚“多人协作通过逻辑角色划分完成，live 多机验证项标记为 skipped/operator-side”。

### 2.3 基础依赖

三个人都需要：

```bash
sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  build-essential pkg-config libssl-dev libffi-dev \
  curl jq git
```

Person 1 和 Person 2 还建议有：

```bash
sudo apt-get install -y cargo rustc postgresql-client
```

Person 2 如需跑 live infra：

```bash
sudo apt-get install -y docker.io docker-compose-plugin pgbouncer
```

Bazel / PJC 二进制如果环境安装成本太高，pre 阶段可以使用已经验证过的 checked-in fixture 和 contract smoke；结题阶段再说明 PJC live benchmark 的环境限制。

## 3. 三人分工

### 3.1 Person 1：项目统筹、主链路与报告 owner

Person 1 负责“项目讲得清楚、主链路跑得通、证据收得齐”。

主要任务：

1. 固定项目口径，维护 `README.md`、`COMPACT_PLATFORM_BRIEF.md`、`NEXT_SESSION_READING_GUIDE.md`、本文件。
2. 跑主链路最小演示：

```bash
bash scripts/run_live_sse_bridge_demo.sh
```

3. 跑统一 smoke：

```bash
bash scripts/check_ci_smoke.sh
bash scripts/check_json_contracts.sh
```

4. 生成或收集主要证据：
   - `tmp/live_sse_bridge_demo/run-*/live_demo_manifest.json`
   - `tmp/live_sse_bridge_demo/run-*/a_psi_run/public_report.json`
   - `tmp/live_sse_bridge_demo/run-*/mainline_contract_check.json`
   - `tmp/live_sse_bridge_demo/run-*/audit_chain.json`
   - `tmp/team_evidence/person_1/EVIDENCE_LOG.md`

5. 维护 pre 和结题报告的主线叙事：
   - 业务问题：电商/广告跨方归因不能暴露原始用户标识。
   - 技术路线：SSE 做候选检索，recovery 控制恢复，bridge 做 HMAC token，PJC 做隐私交集聚合，policy release 做结果治理。
   - 项目边界：平台基线已完成，但不是生产级完整平台。

Person 1 的交付物：

| 交付物 | 路径建议 | 用途 |
| --- | --- | --- |
| 主链路演示 manifest | `tmp/team_evidence/person_1/live_demo_manifest.json` | pre/结题展示 demo 成功 |
| public report | `tmp/team_evidence/person_1/public_report.json` | 展示 `intersection_size=2` / `intersection_sum=425` |
| mainline contract check | `tmp/team_evidence/person_1/mainline_contract_check.json` | 展示跨阶段 contract 一致 |
| 证据索引 | `tmp/team_evidence/person_1/EVIDENCE_LOG.md` | 汇总三人证据 |

### 3.2 Person 2：环境、服务边界与性能 owner

Person 2 负责“服务真的起得来、边界真的能被测、性能证据说得过去”。

主要任务：

1. 准备 Python/Rust/SSE 环境：

```bash
cd sse
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd ..

cd bridge
cargo test
cd ..
```

2. 启动或验证 record recovery 服务：

```bash
python3 scripts/run_record_recovery_service.py serve \
  --config config/record_recovery_http_service.example.json
```

另一个终端探活：

```bash
python3 scripts/request_record_recovery_service.py \
  --config config/record_recovery_http_service.example.json \
  --health \
  --output tmp/team_evidence/person_2/recovery_service_health.json
```

3. 负责 infra 可选项，能跑则跑，不能跑就明确 skipped：
   - PostgreSQL / pgBouncer / Patroni topology。
   - observability stack。
   - read adapter backend comparison。
   - mTLS overhead benchmark。

4. 跑性能和边界 benchmark 的轻量证据：

```bash
python3 scripts/benchmark_record_recovery.py \
  --output tmp/team_evidence/person_2/record_recovery_benchmark.json

python3 scripts/benchmark_bridge.py \
  --server-rows 1000 \
  --client-rows 1000 \
  --output tmp/team_evidence/person_2/bridge_benchmark.json
```

5. 给 Person 3 提供测试目标：
   - endpoint URL
   - 端口
   - auth token 处理方式
   - TLS/mTLS 配置
   - 日志路径
   - 回滚方式

Person 2 的交付物：

| 交付物 | 路径建议 | 用途 |
| --- | --- | --- |
| recovery health | `tmp/team_evidence/person_2/recovery_service_health.json` | 展示独立服务边界 |
| recovery benchmark | `tmp/team_evidence/person_2/record_recovery_benchmark.json` | 展示恢复服务性能 |
| bridge benchmark | `tmp/team_evidence/person_2/bridge_benchmark.json` | 展示 Rust bridge 性能 |
| infra skipped/pass 记录 | `tmp/team_evidence/person_2/EVIDENCE_LOG.md` | 结题说明哪些是 repo-side，哪些是 operator-side |

### 3.3 Person 3：安全、审计与合规 owner

Person 3 负责“项目不是只会跑，还能证明边界和审计可信”。

主要任务：

1. 明确安全测试范围，使用：

```text
handoff/person_3_security_audit/SECURITY_TEST_SCOPE_TEMPLATE.md
```

2. 跑内部安全门禁：

```bash
python3 scripts/check_http_malformed_input_gate.py \
  --output tmp/team_evidence/person_3/http_malformed_input_gate.json
```

3. 跑 audit tamper resistance：

```bash
python3 scripts/seal_audit_artifact.py \
  --input tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --out tmp/team_evidence/person_3/audit_chain.seal.json \
  --job-id sse_demo_job

python3 scripts/verify_audit_tamper_resistance.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --audit-seal tmp/team_evidence/person_3/audit_chain.seal.json \
  --job-id sse_demo_job \
  --output tmp/team_evidence/person_3/audit_tamper_resistance.json
```

4. 如果 Person 2 提供 live target，做恢复服务和 dashboard/API 的安全测试：
   - 错误 token / 缺 token。
   - 过期 timestamp / replay。
   - malformed JSON。
   - path traversal。
   - 非授权 caller / tenant / dataset / service。
   - 大请求体。

5. 如果有外部凭证，执行 S6 WORM 或 Rekor live drill；没有凭证则用 `bash scripts/verify_external_audit_anchor_gate.sh` 跑 repo-side 五条断言（生产闸门 + tamper 检测 + 三种拒绝路径），把生成的 `tmp/external_audit_anchor_evidence/*.json` 与 stderr 一并归档，并在结题中明确 live drill 标记为 operator-side。

6. S7 两机 mTLS 闸门复验：在拿到对方 cert 后（无论是否做了真实跨机 1M streaming），都要为本方接收的 peer cert 跑一次 `python3 scripts/check_pjc_tls_identity.py --cert ... --ca-cert ... --expected-fingerprint-sha256 <out-of-band fp> --expected-peer-identity job-<id>.party*.example --output tmp/team_evidence/person_3/pjc_tls_identity_<job_id>.json --assert-allow`。如果只有单机环境，直接跑 `bash scripts/verify_pjc_tls_identity_gate.sh` 生成 7 条断言证据（含 expired / wrong-fingerprint / wrong-SAN / foreign-CA 反例），归档 `tmp/pjc_tls_identity_evidence/case{1..6}.json` 到本人 `team_evidence` 目录。两侧报告由 Person 1 在结题证据合并时一并打包。

Person 3 的交付物：

| 交付物 | 路径建议 | 用途 |
| --- | --- | --- |
| 安全测试范围 | `tmp/team_evidence/person_3/SECURITY_TEST_SCOPE.md` | 外部测试前置审批 |
| malformed input gate | `tmp/team_evidence/person_3/http_malformed_input_gate.json` | 展示 HTTP 输入边界 |
| tamper resistance report | `tmp/team_evidence/person_3/audit_tamper_resistance.json` | 展示审计防篡改 |
| external audit anchor gate | `tmp/team_evidence/person_3/external_audit_anchor_*.json` | S6 production gate + tamper 反例 |
| pjc mTLS identity gate | `tmp/team_evidence/person_3/pjc_tls_identity_*.json` | S7 cert 身份/有效期/CA 反例 |
| finding list | `tmp/team_evidence/person_3/FINDINGS.md` | 结题安全章节 |

## 4. 协作流程

### 4.1 每日/每轮同步

每轮同步固定回答 5 个问题：

1. 今天修改了哪些文件或配置。
2. 跑了哪些命令。
3. 产生了哪些 JSON / JSONL / 日志证据。
4. 有哪些失败，是代码问题、环境问题，还是 operator-side 条件缺失。
5. 是否影响冻结 contract。

### 4.2 分支与变更原则

1. 主链路 contract 由 Person 1 最终确认。
2. Person 2 不直接改 `policy_release.py`、bridge token 语义、record recovery scope 语义。
3. Person 3 可以提交安全修复建议，但修改主链路字段必须走 `docs/change_requests/`。
4. 所有新增证据先落 `tmp/team_evidence/<person>/`，不要混进源码目录。

### 4.3 冲突处理

| 冲突 | 处理 |
| --- | --- |
| 文档说未完成，代码已完成 | 以 migration / schema / script / smoke 证据为准，更新文档 |
| benchmark 跑不动 | 标记为环境限制，提供轻量 smoke 和历史本地结果 |
| live infra 没有凭证 | 生成 planned/dry-run report，结题写 operator-side |
| 外部测试发现问题 | 先复现并定级，再决定修复、接受风险或不复现 |

### 4.4 完整任务闭环规则

后续任务不能再按“先缓解一点、再留给下个人补”的方式交付。每次认领任务时，默认直接解决一个完整任务包；如果因为外部凭证、硬件或两机环境缺失不能完成，必须把状态写成 `repo-side complete` 或 `operator-side skipped`，不能写成 `completed`。

一个任务只有同时满足下面 7 项，才能进入 pre 或结题报告的“已完成能力”：

1. 需求边界：写清楚解决哪个问题，以及明确不解决什么。
2. 实现变更：代码、schema、脚本、配置或部署模板已经落地。
3. 验证命令：至少有一条可复现命令，复杂任务要有正例和反例。
4. 证据文件：JSON / JSONL / log / report 放入 `tmp/team_evidence/` 或对应 run 目录。
5. 审计接入：关键安全、发布、密钥、handoff 或 PJC 决策进入 audit/report schema。
6. 文档回写：更新 runbook、路线图、模块文档和本协作文档。
7. 三人联合认证：Person 1/2/3 按职责确认并记录。

建议每个完整任务用一个目录收口：

```text
tmp/team_evidence/joint_certification/<task_id>/
  TASK_SUMMARY.md
  COMMANDS.md
  EVIDENCE_INDEX.md
  JOINT_CERTIFICATION.md
```

其中 `JOINT_CERTIFICATION.md` 必须包含：

| 字段 | 要求 |
| --- | --- |
| task_id | 对齐 `S1`、`S2`、`PJC_STREAMING_1M` 这类稳定编号 |
| final_status | `completed` / `repo-side complete` / `operator-side skipped` / `partial` |
| Person 1 certification | 主链路、报告口径、用户可见结论 |
| Person 2 certification | Ubuntu 环境、服务运行、性能和运维证据 |
| Person 3 certification | 安全反例、审计、防篡改和合规证据 |
| evidence_paths | 证据文件路径列表 |
| report_wording | pre/结题报告中允许使用的文字 |

### 4.5 多人联合认证规则

多人联合认证不是形式签名，而是防止“一个人跑通就宣称完成”。所有 P0/P1 生产安全任务都必须三人共同确认。

| 角色 | 认证重点 | 不应替别人确认的内容 |
| --- | --- | --- |
| Person 1 | 主链路结果、报告叙事、contract 口径、对外承诺边界 | 不替 Person 2 确认部署稳定性，不替 Person 3 确认攻击反例 |
| Person 2 | Ubuntu/服务/端口/资源/benchmark/运维 runbook | 不替 Person 1 写对外结论，不替 Person 3 判定安全完成 |
| Person 3 | 越权、篡改、重放、错误证书、差分查询、审计可信度 | 不替 Person 2 确认性能或 HA，不替 Person 1 改报告口径 |

认证结果在报告中按下面规则呈现：

| 状态 | 报告允许写法 | 禁止写法 |
| --- | --- | --- |
| `completed` | 已完成并通过三人联合认证 | - |
| `repo-side complete` | 仓库内实现和 smoke 完成，真实外部服务由 operator 提供 | 已生产部署 |
| `operator-side skipped` | 因缺少凭证/两机/云资源，本次只完成 planned 或 dry-run 证据 | 已完成 |
| `partial` | 部分完成，不作为结题能力宣称 | 已支持 |

## 5. 测试通过后如何呈现

### 5.1 证据分层

报告里不要只写“测试通过”，要按证据层呈现：

| 层级 | 证明什么 | 推荐证据 |
| --- | --- | --- |
| L1 主链路正确性 | demo 能跑通，结果正确 | `live_demo_manifest.json`, `public_report.json` |
| L2 contract 稳定性 | 跨模块字段未漂移 | `mainline_contract_check.json`, `check_json_contracts.sh` 输出摘要 |
| L3 安全边界 | 错误输入/越权/篡改会被拒绝 | `http_malformed_input_gate.json`, `audit_tamper_resistance.json` |
| L4 性能基线 | bridge/recovery/PJC 有量化结果 | `bridge_benchmark.json`, `record_recovery_benchmark.json`, PJC benchmark 摘要 |
| L5 运维可观测 | 有 health、audit、observability、dashboard | `platform_health.json`, dashboard 截图或 `/v1/dashboard` 响应 |
| L6 生产差距 | 哪些仍是 operator-side 或后续工作 | skipped table, risk register |

### 5.2 pre 汇报建议

pre 阶段目标是“让评审相信方向正确、闭环已经跑通、剩余风险清楚”。建议 12-15 页。

推荐结构：

1. 项目背景：跨平台电商归因为什么需要隐私计算。
2. 核心问题：不能暴露明文 email/phone/device ID，也不能泄露未发布交集成员。
3. 总体架构：画 `SSE -> recovery -> bridge -> PJC -> release`。
4. 模块分工：`sse/`、`services/record_recovery/`、`bridge/`、`a-psi/`、`scripts/`、`schemas/`。
5. 当前 demo：展示 `intersection_size=2`、`intersection_sum=425`。
6. 控制面：metadata sidecar、caller/tenant/dataset/service scope、query workflow。
7. 安全设计：encrypted record store、HMAC token、FIFO handoff、audit chain。
8. 测试结果页：用表格列命令、输出文件、通过标准。
9. 三人分工页：Person 1/2/3 当前负责什么。
10. 当前限制：明确不是生产级完整平台。
11. 下一步计划：外部 pen test、真实 authority source、生产部署验证、报告收口。

pre 里适合展示的测试表：

| 测试 | 命令 | 通过标准 | 证据 |
| --- | --- | --- | --- |
| live SSE demo | `bash scripts/run_live_sse_bridge_demo.sh` | `intersection_size=2`, `intersection_sum=425` | manifest + public report |
| contract smoke | `bash scripts/check_json_contracts.sh` | exit code 0 | 终端截图/日志摘要 |
| CI smoke | `bash scripts/check_ci_smoke.sh` | exit code 0 | 终端截图/日志摘要 |
| malformed input | `check_http_malformed_input_gate.py` | detected == total | JSON report |
| audit tamper | `verify_audit_tamper_resistance.py` | status ok | JSON report |

### 5.3 结题报告建议

结题报告目标是“证明实现、验证、分工、边界、风险都闭环”。建议按工程交付写，不要只写论文式介绍。

推荐章节：

1. 摘要：项目目标、核心贡献、最终状态。
2. 需求分析：业务场景、隐私约束、角色权限。
3. 系统设计：主链路、控制面、服务边界、审计链路。
4. 详细实现：
   - SSE export 与 encrypted record store。
   - record recovery service。
   - Rust bridge tokenization。
   - A-PSI/PJC 与 policy release。
   - metadata sidecar 与 query workflow。
   - audit archive / observability / benchmark。
5. 三人协作：
   - Person 1 主链路和报告。
   - Person 2 环境、服务、性能。
   - Person 3 安全、审计、合规。
6. 测试与验证：
   - 功能测试。
   - contract/schema 测试。
   - 安全测试。
   - 性能测试。
   - 运维健康检查。
7. 结果展示：
   - public report。
   - audit chain。
   - dashboard/API。
   - benchmark 图表。
8. 风险与限制：
   - 不是生产级完整平台。
   - live authority source/operator-side 条件。
   - PJC 1M streaming 已通过，但生产级 S4 还需要 worker service、资源上限和 preflight。
   - 外部 pen test 状态。
9. 总结与后续工作。
10. 附录：
   - 命令清单。
   - JSON evidence 路径。
   - schema 列表。
   - 关键配置。

结题报告里的“通过测试”不要用口号，使用这样的证据句式：

```text
在 Ubuntu 22.04 环境下执行 bash scripts/run_live_sse_bridge_demo.sh，
输出 public_report.json 中 released=true，
intersection_size=2，intersection_sum=425；
同时生成 audit_chain.json 和 mainline_contract_check.json，
证明主链路结果、审计链和跨阶段 contract 一致。
```

## 6. 最小证据包

结题前由 Person 1 收齐：

```text
tmp/team_evidence/
  person_1/
    EVIDENCE_LOG.md
    live_demo_manifest.json
    public_report.json
    mainline_contract_check.json
    audit_chain.json
  person_2/
    EVIDENCE_LOG.md
    recovery_service_health.json
    record_recovery_benchmark.json
    bridge_benchmark.json
  person_3/
    EVIDENCE_LOG.md
    SECURITY_TEST_SCOPE.md
    http_malformed_input_gate.json
    audit_tamper_resistance.json
    FINDINGS.md
  joint_certification/
    <task_id>/
      TASK_SUMMARY.md
      COMMANDS.md
      EVIDENCE_INDEX.md
      JOINT_CERTIFICATION.md
```

如果某个文件没有生成，必须在对应 `EVIDENCE_LOG.md` 里写：

1. 是否 skipped。
2. skipped 原因。
3. 是否有替代证据。
4. 是否影响结题结论。

## 7. 任务看板

| 优先级 | 任务 | Owner | 参与者 | 完成标准 |
| --- | --- | --- | --- | --- |
| P0 | 修复文档漂移 | Person 1 | Person 2/3 review | `CONTROL_PLANE_SCHEMA.md` 与实际 migration 一致 |
| P0 | 主链路 live demo | Person 1 | Person 2 | public report 显示 `2 / 425` |
| P0 | contract smoke | Person 1 | - | `check_json_contracts.sh` exit 0 |
| P0 | recovery service target | Person 2 | Person 3 | health JSON schema-valid |
| P1 | bridge/recovery benchmark | Person 2 | Person 1 | benchmark JSON schema-valid |
| P1 | malformed input gate | Person 3 | Person 2 | detected == total |
| P1 | audit tamper resistance | Person 3 | Person 1 | status ok |
| P1 | pre PPT 证据页 | Person 1 | Person 2/3 | 每个结论都有文件或命令支撑 |
| P2 | external S3/Rekor drill | Person 3 | Person 1 | live 或 planned report |
| P2 | PostgreSQL/observability live drill | Person 2 | Person 1 | pass 或 skipped with reason |
| P2 | 结题报告附录 | Person 1 | all | 证据包路径完整 |

### 7.1 生产级安全完整任务看板

生产级安全任务以 [PRODUCTION_SECURITY_COMPLETION_PLAN.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PRODUCTION_SECURITY_COMPLETION_PLAN.md) 为总纲。下面每一项都必须按 4.4 的完整任务闭环和 4.5 的联合认证规则收口。

| 优先级 | 任务 | Owner | 联合认证重点 | 完成标准 |
| --- | --- | --- | --- | --- |
| P0 | S1 消除明文 handoff 落盘 | Person 1 | Person 2 验证 FIFO/streaming 生命周期；Person 3 验证 retained file 反例被拒绝 | 生产 gate 下 `plaintext_exposure_risk=elevated` 失败 |
| P0 | S2 正式 KMS 与密钥生命周期 | Person 2 | Person 1 验证主链路和报告口径；Person 3 验证错误 caller/禁用 version/缺 key 拒绝 | 生产路径不使用裸 `--token-secret` |
| P0 | S3 隐私预算与抗差分查询 | Person 3 | Person 1 验证 release/public report；Person 2 验证 ledger 持久化和查询 | duplicate/near-duplicate/budget exhausted 被统一裁决 |
| P1 | S4 PJC 服务化、资源隔离与 DoS 防护 | Person 2 | Person 1 验证 1M 结果入报告；Person 3 验证超限、timeout、异常 chunk 反例 | streaming gRPC 默认，资源限制写入 audit |
| P1 | S6 外部不可篡改审计 | Person 3 | Person 1 验证 report 与 bundle 对齐；Person 2 验证外部 anchor 环境 | 篡改 audit chain 后 verifier 失败 |
| P1 | S7 两机 mTLS 联合验证 | Person 2 | Person 1 验证双方结果和 audit；Person 3 验证错误证书/MITM/replay | 两台 Ubuntu 上 mTLS PJC 结果正确 |
| P2 | S5 Metadata leakage 控制 | Person 3 | Person 1 验证 public report 字段；Person 2 验证 role-based dashboard | 普通 caller 看不到 frame/shard/raw row 分布 |
| P2 | S8 抗恶意 PJC / Commit-and-Prove | Person 3 | Person 1 验证 commitment 进入报告；Person 2 验证 manifest 归档稳定 | 篡改 input/value/token-scope 被前置拒绝 |

## 8. 对外演示脚本

pre 或结题现场按这个顺序演示最稳：

1. 打开架构图，说明五段主链路。
2. 展示 `public_report.json` 的 `intersection_size=2` / `intersection_sum=425`。
3. 展示 `mainline_contract_check.json`，说明每阶段 contract 对齐。
4. 展示 `audit_chain.json` 和 seal/verify 结果，说明可审计。
5. 展示 malformed input gate，说明恶意输入被拒绝。
6. 展示 benchmark 表，说明性能有基线。
7. 展示限制和后续工作，避免过度承诺生产能力。

## 9. 与现有 handoff 包的关系

本文件是统一总纲；三个人的具体执行清单仍使用：

1. [`handoff/person_1_platform_local/README.md`](/home/llvanion/Desktop/seccomp-privacy-platform/handoff/person_1_platform_local/README.md)
2. [`handoff/person_2_live_infra/README.md`](/home/llvanion/Desktop/seccomp-privacy-platform/handoff/person_2_live_infra/README.md)
3. [`handoff/person_3_security_audit/README.md`](/home/llvanion/Desktop/seccomp-privacy-platform/handoff/person_3_security_audit/README.md)

如果 handoff 包和本文件冲突，以本文件的项目口径和报告口径为准；以 handoff 包的具体命令为执行细节。
