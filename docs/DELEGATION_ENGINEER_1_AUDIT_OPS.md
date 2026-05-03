# 工程师 1 任务书：审计、运维与稳定性工具

## 1. 你的任务定位

你负责的是平台的外围稳定性建设，不负责改动核心隐私计算主链路。

当前主链路已经存在：

```text
SSE export / record recovery -> bridge -> A-PSI / PJC -> policy release
```

你要做的是围绕这条链路补齐：

1. 运维健康检查
2. 审计产物归档与恢复工具
3. benchmark / 安全检查 / CI 稳定性工具
4. 运行手册与故障排查手册

你的工作应该尽量只消费现有产物、现有 CLI、现有 JSON/JSONL contract，不要反向改动核心接口。

## 2. 你负责的具体任务

### 任务 A：统一健康检查与状态探针

目标：

1. 把当前零散的 service health/status 检查整理成统一入口。
2. 对 recovery service、key agent、external KMS、pipeline run 形成一致的健康检查输出。

你可以直接复用的现有入口：

1. `python3 scripts/request_record_recovery_service.py --config <config>`
2. `python3 scripts/manage_record_recovery_service.py status --config <config>`
3. `python3 scripts/request_key_agent.py ...`
4. `python3 scripts/request_external_kms.py ...`
5. `bash scripts/run_live_sse_bridge_demo.sh`

建议交付：

1. 一个统一的健康检查脚本，比如 `scripts/check_platform_health.py`
2. 一个汇总 JSON 输出，方便 CI 和人工排障
3. 一份运行文档，比如 `docs/OPS_RUNBOOK.md`

### 任务 B：审计归档、恢复、校验工具加强

目标：

1. 让一次运行产生的审计包更容易保存、恢复、核对。
2. 不改变现有 `audit_chain.json` / `audit_chain.seal.json` 语义。

你可以直接复用的现有入口：

1. `python3 scripts/build_audit_chain.py --out-base <dir> --job-id <id>`
2. `python3 scripts/seal_audit_artifact.py --input <audit_chain.json> --out <audit_chain.seal.json> --job-id <id>`
3. `python3 scripts/archive_audit_bundle.py --audit-chain <...> --audit-seal <...> --archive-dir <...> --job-id <id>`

建议交付：

1. 审计包导出/恢复脚本
2. 审计包完整性核对脚本
3. 审计包目录约定文档

### 任务 C：benchmark、安全检查、CI 稳定性补强

目标：

1. 把现在散落的 contract check、smoke check、benchmark 变成可重复执行的流程。
2. 做不会影响主链路语义的安全检查。

你可以直接复用的现有入口：

1. `bash scripts/check_json_contracts.sh`
2. `bash -n scripts/run_sse_bridge_pipeline.sh`
3. `python3 -m py_compile ...`
4. `.github/workflows/json-contracts.yml`

建议交付：

1. benchmark 脚本和报告模板
2. dependency / secret scanning 脚本
3. fuzzing 或 malformed-input 测试补充
4. CI workflow 增强

## 3. 技术栈要求

优先使用当前仓库已经在用的技术栈：

1. Python 3
2. Bash
3. JSON / JSONL
4. GitHub Actions
5. 现有 `schemas/*.json` contract

不要额外引入新的后端服务框架、消息队列、数据库框架，除非先提变更说明并获得批准。

## 4. 我给你留下的稳定接口

你可以把下面这些当成当前冻结接口：

### 核心编排入口

1. `scripts/run_sse_bridge_pipeline.sh`
2. `scripts/run_live_sse_bridge_demo.sh`

### 审计与 contract 入口

1. `scripts/build_audit_chain.py`
2. `scripts/seal_audit_artifact.py`
3. `scripts/archive_audit_bundle.py`
4. `scripts/validate_json_contract.py`
5. `scripts/validate_tabular_contract.py`
6. `scripts/check_json_contracts.sh`

### recovery service 入口

1. `scripts/request_record_recovery_service.py`
2. `scripts/manage_record_recovery_service.py`
3. `sse/run_client.py serve-record-recovery`

### 现有关键输出文件

1. `out-base/sse_exports/export_audit.jsonl`
2. `out-base/sse_exports/record_recovery_service_health.json`
3. `out-base/sse_exports/record_recovery_service_config.json`
4. `out-base/sse_exports/record_recovery_service_audit.jsonl`
5. `out-base/bridge_job/job_meta.json`
6. `out-base/bridge_job/bridge_audit.jsonl`
7. `out-base/a_psi_run/pjc_audit.jsonl`
8. `out-base/a_psi_run/public_report.json`
9. `out-base/audit_chain.json`
10. `out-base/audit_chain.seal.json`

## 5. 调用方式示例

### 跑一次完整 demo

```bash
bash scripts/run_live_sse_bridge_demo.sh
```

### 校验 recovery service 健康状态

```bash
python3 scripts/request_record_recovery_service.py \
  --config config/record_recovery_service.example.json
```

### 构建和归档审计链

```bash
python3 scripts/build_audit_chain.py --out-base tmp/sse_bridge_pipeline_demo --job-id auto_demo_job
python3 scripts/seal_audit_artifact.py \
  --input tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --out tmp/sse_bridge_pipeline_demo/audit_chain.seal.json \
  --job-id auto_demo_job
python3 scripts/archive_audit_bundle.py \
  --audit-chain tmp/sse_bridge_pipeline_demo/audit_chain.json \
  --audit-seal tmp/sse_bridge_pipeline_demo/audit_chain.seal.json \
  --archive-dir tmp/audit_archive \
  --job-id auto_demo_job
```

## 6. 你不要碰的边界

下面这些不是你的任务，不要主动改：

1. `sse/frontend/client/commands.py` 里的 export / recovery 核心逻辑
2. `bridge/src/main.rs` 的 bridge contract
3. `a-psi/moduleA_psi/scripts/policy_release.py` 的结果治理语义
4. `schemas/` 下已经在主链路使用的字段名和 schema name
5. `scripts/run_sse_bridge_pipeline.sh` 的主参数语义

如果确实需要改这些边界，先写变更提案，不要直接改代码。

## 7. 变更规则

你提交的代码必须遵守：

1. 不能删现有 CLI 参数。
2. 不能改现有 JSON schema 名称。
3. 不能改变已有输出文件路径语义，除非保留兼容层。
4. 新增能力优先做成 sidecar 工具，而不是侵入主链路。
5. 如果发现现有接口不够用，先写 `docs/change_requests/<topic>.md` 说明需要新增什么，不要直接破坏兼容。

## 8. 验收标准

你这边完成的定义是：

1. 不改主链路语义的前提下，新增的健康检查 / 审计 / CI 工具可独立运行。
2. 能用现有 demo 输出做审计包构建、校验和归档。
3. 新增文档能指导别人复现一次检查流程。
4. 改动通过现有 contract check，不引入新的主链路接口漂移。

## 9. 当前实现状态

已落地的第一阶段 sidecar：

1. `scripts/check_platform_health.py`：统一输出 `platform_health/v1`，覆盖 recovery service、key agent、external KMS、pipeline run artifacts、metadata DB。
2. `scripts/verify_audit_bundle.py`：校验直接审计包或 archive index 中的审计包，并可恢复已验证副本。
3. `scripts/scan_repo_hygiene.py`：离线扫描高置信 secret 模式和 tracked generated artifacts。
4. `scripts/check_dependency_hygiene.py`：离线检查 first-party Python/Cargo dependency manifest 的基础可复现性。
5. `scripts/check_ci_smoke.sh`：统一本地/CI preflight，串联 py_compile、shell syntax、hygiene、dependency hygiene、contract smoke。
6. `scripts/check_bridge_rust.sh`：对 bridge 执行 `cargo fmt --check` 和 `cargo test`，使用 `/tmp` 下临时 target 目录避免污染仓库。
7. `scripts/benchmark_smoke.py`：对现有 smoke entrypoint 生成 `smoke_benchmark/v1` 耗时报告。
8. `scripts/benchmark_read_adapters.py`：对 metadata `job/entity` 与 audit `audit-chain/public-report/observability/catalog-lineage` 只读 adapter 生成 `read_adapter_benchmark/v1` 耗时报告，基于临时 synthetic completed-run fixture 与 sidecar DB，不触发主链路执行；默认 contract smoke 还会校验 `--mode all` 的完整 mode 集合。
9. `scripts/benchmark_record_recovery.py`：对 record recovery 独立服务边界生成 `record_recovery_benchmark/v1` 耗时报告，基于临时 synthetic encrypted record store 与 standalone service lifecycle，覆盖 Unix-socket / HTTP 两种 transport；默认 contract smoke 还会校验完整 transport/operation mode 集合和 synthetic recover 的 `output_rows=2`。
10. `scripts/benchmark_pipeline.py`：对 `scripts/run_sse_bridge_pipeline.sh` 生成 `pipeline_benchmark/v1` 耗时报告，覆盖默认 file cleanup、显式 retained file handoff compatibility mode、FIFO handoff 三种主链路模式，并校验 handoff cleanup 状态；它直接执行 bridge + PJC，因此用于本地可复现 benchmark，不纳入默认 contract smoke。
11. `scripts/benchmark_pjc.py`：对 `a-psi/moduleA_psi/scripts/run_pjc.sh` 生成 `pjc_benchmark/v1` 耗时报告，基于已准备好的 `bridge/out/sse_demo_job/` fixture；它直接执行 PJC server/client，因此用于本地可复现 benchmark，不纳入默认 contract smoke。
12. `scripts/benchmark_live_sse_demo.py`：对 `scripts/run_live_sse_bridge_demo.sh` 生成 `live_sse_benchmark/v1` 耗时报告，覆盖默认 file cleanup、显式 retained file handoff compatibility mode、FIFO handoff 三种 live SSE-backed 路径，并校验 handoff cleanup 状态；它会把 public report 的 display/raw/cents 金额统一归一化回 `425` cents，因此用于本地可复现 live benchmark，不纳入默认 contract smoke。
13. `scripts/benchmark_audit_bundle.py`：对 `scripts/archive_audit_bundle.py` 和 `scripts/verify_audit_bundle.py` 生成 `audit_bundle_benchmark/v1` 耗时报告，覆盖 archive、direct verify、archive-index verify、archive-index restore 四种审计保留/恢复路径；它基于临时 synthetic HMAC-sealed audit bundle，纳入默认 contract smoke，并额外校验各 mode 的 `archive_index_verified` / `restored` 标志，以及 archive-backed mode 的 `anchor_log_verified` / `anchor_signature_verified` / `anchor_log_path` 结果。
14. `schemas/platform_health.schema.json` + `scripts/benchmark_platform_health.py`：把 `platform_health/v1` 读侧健康报告 contract 固化下来，并对 `scripts/check_platform_health.py` 的 `pipeline_run` / `metadata_db` synthetic probe 生成 `platform_health_benchmark/v1` 耗时报告；纳入默认 contract smoke，并额外校验各 mode 的 component 集合以及受限环境下的 CLI-only fallback。
15. `scripts/benchmark_derived_views.py`：对 `scripts/export_observability_events.py` 与 `scripts/export_catalog_lineage.py` 生成 `derived_views_benchmark/v1` 耗时报告，覆盖 observability、catalog 默认脱敏导出和 `--include-paths` 显式路径导出；它基于临时 synthetic audit_chain fixture，纳入默认 contract smoke，并额外校验 observability 事件覆盖与 catalog 路径脱敏分界。
16. `docs/OPS_RUNBOOK.md`：记录健康检查、审计包校验/恢复、hygiene、dependency、benchmark、CI smoke 和 troubleshooting。
17. `scripts/check_malformed_input_gate.py` + `schemas/malformed_input_gate.schema.json`（2026-05-01）：系统性负向测试门禁（fuzz/malformed-input block 收口）。对 8 个核心 schema（`platform_health/v1`、`schema_backcompat_check/v1`、`audit_seal/v1`、`bridge_job_meta/v1`、`sse_bridge_export_audit/v1`、`mainline_contract_check/v1`、`pipeline_observability/v1`、`audit_archive_index/v1`）各构造 minimal valid reference payload，然后系统性生成突变（missing_required、const_violation、enum_violation、wrong_type、extra_property、min_length_violation、minimum_violation、invalid_json、null/array/string/number root）；共生成 191 个突变体并全部被拒绝；输出 `malformed_input_gate/v1` 报告并用自身 schema 校验；已接入 `check_ci_smoke.sh` + `check_json_contracts.sh` 双重门禁。
18. `scripts/check_pre_release_gate.py` + `schemas/pre_release_gate.schema.json` + `schemas/repo_hygiene_scan.schema.json` + `schemas/dependency_hygiene.schema.json`（2026-05-01）：统一发布前检查门禁（benchmark/CI gate block 收口）。单一入口串联 11 个子检查：`repo_hygiene`、`dependency_hygiene`、`schema_backcompat`、`malformed_input`、`record_recovery_boundary`、`query_workflow_benchmark`、`read_adapter_benchmark`、`record_recovery_benchmark`、`audit_bundle_benchmark`、`platform_health_benchmark`、`derived_views_benchmark`；每个子检查有独立计时、exit_code 和 output_schema_valid 标志；输出 `pre_release_gate/v1` 报告，自身用 schema 校验；同时为 `repo_hygiene_scan/v1` 和 `dependency_hygiene/v1` 补写了 schema 文件（此前只有运行时输出、无 schema 约束）；已接入 `check_ci_smoke.sh` + `check_json_contracts.sh` 双重门禁，CI 中 `check_json_contracts.sh` 现在也验证 `repo_hygiene_scan.json` 的 schema。
19. `scripts/check_operator_readiness.py` + `schemas/operator_readiness.schema.json`（2026-05-01）：Operator 部署前就绪检查门禁（platform health/backup/restore/SLO/checklist block 收口，Block A）。检查 9 个 example config 文件的 schema 合规性、4 个 bridge example 数据文件的存在性、完整 pre_release_gate 子调用；同时输出 8 个 `SECCOMP_*` env var 的 catalog（含是否在当前 shell 已设置）；输出 `operator_readiness/v1` 报告并用 schema 校验；已接入 `check_ci_smoke.sh` + `check_json_contracts.sh` 双重门禁。
20. `docs/OPS_RUNBOOK.md` 大幅扩展（2026-05-01）：补齐 deployment package runbook（Block B）。新增章节：Operator Readiness Check（运行方式与报告解读）、Pre-Deployment Checklist（6 步部署前清单，含 replay 验证、审计包归档与校验、部署后健康检查）、Failure Recovery Decision Tree（CI smoke 失败分支、审计包完整性失败、Recovery Service 失败、Platform Health Error 四大决策树）、SLO Baseline（12 个 gate 的预期耗时下界）。

已处理的仓库卫生问题：

1. `.gitignore` 已忽略 `target/` 和 `bridge/target/`。
2. `bridge/target/` 已从 Git 索引移除，保留本地构建文件。

当前验证入口：

```bash
bash scripts/check_ci_smoke.sh
```

## 10. 平台级剩余工作量估算

按 [PLATFORM_LEVEL_REMAINING_ESTIMATE.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md) 的统一口径，这条线从”当前 ops/audit sidecar 基线”推进到”平台基线版”还需要：

1. `0 blocks`（原 4 blocks；全部已完成）
2. 约 `0h`

已完成收口：

1. `audit bundle` 已经补到本地 append-only 锚点基线：归档流程除了 `audit_archive_index/v1`，现在还会生成 `audit_archive_anchor/v1`，`verify_audit_bundle.py` 会在 archive-backed verify 时回放整条锚点链，并可选校验 anchor HMAC。
2. `fuzz / malformed-input / security scan block ✓（2026-05-01）`：`scripts/check_malformed_input_gate.py` 已落地，191 个突变体全部被拒绝，接入 CI double-gate。
3. `benchmark / CI gate block ✓（2026-05-01）`：`scripts/check_pre_release_gate.py` 已落地，11 个子检查（hygiene × 2、contract × 3、benchmark × 6）全部带计时和 schema 验证，接入 CI double-gate；同时补写了 `repo_hygiene_scan/v1` 和 `dependency_hygiene/v1` 的 schema 文件，`check_json_contracts.sh` 现在额外验证 hygiene scan output。
4. `platform health / backup / restore / SLO / checklist block ✓（2026-05-01）`：`scripts/check_operator_readiness.py` 已落地（Operator 部署前就绪检查，含 config 合规、bridge example 数据、pre_release_gate 子调用、8 个 env var catalog）；`docs/OPS_RUNBOOK.md` 新增 Operator Readiness Check、Pre-Deployment Checklist（6 步）、Failure Recovery Decision Tree（4 个决策树）、SLO Baseline（12 条）。工程师 1 全部 4 个 block 已完成。

建议拆分（已全部完成）：

1. ~~`2 blocks / 10h`：把 platform health、backup/restore、failure recovery、SLO/checklist 再整理成更像 deployment package 的 runbook 和 smoke gate。~~ **已完成（2026-05-01）**
2. ~~`1 block / 5h`：把 fuzz / malformed input / security scan 再补一轮，避免只停留在 dependency/secret hygiene。~~ **已完成（2026-05-01）**
3. ~~`1 block / 5h`：把 benchmark/CI gate 再收成更稳定的发布前检查面，减少”脚本都在但没有固定门禁”的状态。~~ **已完成（2026-05-01）**

不含：

1. 真正的集中式日志、指标、告警平台建设。
2. 生产级备份编排、值班体系、SRE 运维流程。
