# Owner 主链路变更清单

## 1. 用途

这份清单只给项目负责人使用，用来评审任何触碰主链路 owner 边界的变更。

适用范围：

1. `sse/run_client.py export-bridge-records`
2. `scripts/run_sse_bridge_pipeline.sh`
3. `scripts/run_live_sse_bridge_demo.sh`
4. `scripts/run_record_recovery_service.py`
5. `bridge/src/main.rs`
6. `a-psi/moduleA_psi/scripts/run_pjc.sh`
7. `a-psi/moduleA_psi/scripts/policy_release.py`
8. `schemas/` 下主链路 contract

## 2. 变更前检查

提交代码前先确认：

1. 有没有碰到 [CORE_CONTRACT_FREEZE_MATRIX.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/CORE_CONTRACT_FREEZE_MATRIX.md) 里的冻结语义。
2. 改动是“新增兼容层”，还是“改变主语义”。
3. 如果改变主语义，是否已经写了 `docs/change_requests/<YYYYMMDD>_<topic>.md`。
4. 是否会让旧 demo、旧 run artifact、旧 schema 校验失效。

## 3. 字段语义检查

必须逐项确认没有静默漂移：

1. `job_id`
2. `correlation_id`
3. `caller`
4. `tenant_id`
5. `dataset_id`
6. `service_id`
7. `record_recovery_boundary`
8. `token_scope`
9. `token_key_version`
10. `release_policy` 现有组合语义
11. `normalizer_schema_version` — 如果改 normalizer 实现，必须同步更新 `NORMALIZER_SCHEMA_VERSION` 常量并注册到 `KNOWN_NORMALIZER_SCHEMA_VERSIONS`
12. `server_normalizer` / `client_normalizer` — 新增 normalizer 类型必须同步更新 `KNOWN_NORMALIZERS` 和 `bridge_job_meta.schema.json` 枚举

## 4. 隐私边界检查

必须确认没有突破这些边界：

1. SSE 仍然不把 raw candidate IDs 直接送进 bridge。
2. recovery audit/service log 仍然不写 recovered plaintext。
3. bridge audit 仍然不写 raw join key 或 token secret。
4. PJC 仍然只吃 token 化 join key 和必要 value。
5. release 仍然在阈值、去重、审计条件下才发布。

## 5. bridge-ready handoff 检查

任何碰到 handoff 的改动都要确认：

1. file 模式下新增的持久化明文是否真的必要。
2. FIFO 模式是否仍然可用。
3. 审计里是否还能看出 handoff 类型、hash 和 row count。
4. 是否扩大了 bridge 可见的敏感内容。

如果扩大了明文暴露面，默认视为高风险改动。

## 6. schema / contract 检查

如果改了 schema 或稳定 JSON 输出，至少要确认：

1. `$id` 没有被静默改掉。
2. 没有删除既有 required 字段。
3. 没有新增强制 required 字段导致旧记录失效。
4. 新字段优先做 optional。
5. `python3 scripts/check_schema_backcompat.py` 应该仍然通过，除非提案明确要求 baseline 变更。

## 7. CLI / 入口检查

如果改了主入口，至少要确认：

1. 没有删除旧参数。
2. 没有偷偷改旧参数含义。
3. 新增参数默认不破坏旧行为。
4. demo 命令仍然能按现有文档运行。

## 8. 回放验证清单

owner 级改动至少要附一个可复现验证包，建议包含：

1. `bash scripts/verify_pipeline_replay.sh` — 端到端 file-mode 回放，断言 `intersection_size=2`, `intersection_sum=425`
2. `bash scripts/check_ci_smoke.sh` — 全量 CI smoke（含回放、schema、hygiene、backcompat、contract）
3. `bash scripts/check_json_contracts.sh`
4. `python3 scripts/check_schema_backcompat.py`
5. 定向 smoke 或 replay 说明

如果碰到主链路语义，优先补：

1. file handoff 回放（`bash scripts/verify_pipeline_replay.sh`）
2. FIFO handoff 回放
3. record recovery service boundary 回放
4. public report / policy audit 回放

## 9. 文档同步清单

如果改动通过，至少检查这些文档是否需要同步：

1. `docs/TASK_OWNER_PRIVACY_CORE_AND_INTERFACE_GOVERNANCE.md`
2. `docs/INTERFACE_FREEZE_AND_CHANGE_PROCESS.md`
3. `docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md`
4. `docs/SSE_BRIDGE_APSI_PIPELINE.md`
5. `README.md`
6. `CODEX_CONTEXT.md`

## 10. 拒绝合并条件

出现任一情况，默认不合并：

1. 只改代码，不写兼容性说明。
2. 触碰冻结字段语义，但没有 change request。
3. 扩大明文 handoff 暴露面且没有显式说明。
4. 让主链路强依赖新数据库、新服务、新执行引擎。
5. 没有任何 replay 或 contract 验证结果。
