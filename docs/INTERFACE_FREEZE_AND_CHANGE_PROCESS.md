# 接口冻结与变更流程

## 1. 目标

这个文档的目标只有一个：

在项目还是半成品的阶段，允许继续快速推进，但禁止多人并行时随意改主链路接口。

当前仓库最重要的不是“功能数量”，而是下面这条链路的稳定性：

```text
SSE export / record recovery -> bridge -> A-PSI / PJC -> policy release
```

任何会影响这条链路的参数、产物、schema、状态语义的改动，都必须走统一变更流程。

## 2. 当前冻结边界

在没有单独批准之前，下面这些接口视为冻结：

### 2.1 关键字段语义冻结

下面字段不能被重新解释：

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

这些字段当前的主要载体、生产者和消费者矩阵见：

```text
docs/CORE_CONTRACT_FREEZE_MATRIX.md
```

### 2.2 关键 schema 名冻结

下面这些 schema 名不能改名：

1. `sse_export_policy/v1`
2. `sse_bridge_export_audit/v1`
3. `record_recovery_service_config/v1`
4. `sse_record_recovery_health/v1`
5. `sse_record_recovery_service_audit/v1`
6. `bridge_job_meta/v1`
7. `bridge_audit/v1`
8. `pjc_audit/v1`
9. `policy_audit/v1`
10. `mainline_contract_check/v1`
11. `audit_chain.schema.json` 对应的输出结构

### 2.3 主入口冻结

下面入口的参数语义不能直接改：

1. `sse/run_client.py`
2. `scripts/run_sse_bridge_pipeline.sh`
3. `scripts/run_live_sse_bridge_demo.sh`
4. `scripts/manage_record_recovery_service.py`
5. `scripts/request_record_recovery_service.py`
6. `bridge/src/main.rs`
7. `a-psi/moduleA_psi/scripts/policy_release.py`

### 2.4 主输出路径冻结

下面这些输出文件的存在意义不能改：

1. `sse_exports/export_audit.jsonl`
2. `sse_exports/record_recovery_service_health.json`
3. `sse_exports/record_recovery_service_config.json`
4. `sse_exports/record_recovery_service_audit.jsonl`
5. `bridge_job/job_meta.json`
6. `bridge_job/bridge_audit.jsonl`
7. `a_psi_run/pjc_audit.jsonl`
8. `a_psi_run/public_report.json`
9. `mainline_contract_check.json`
10. `audit_chain.json`
11. `audit_chain.seal.json`

## 3. 哪些改动不需要审批

下面这些改动可以直接做：

1. 新增 sidecar 工具
2. 新增只读查询工具
3. 新增 benchmark / CI / lint / scan 脚本
4. 新增文档
5. 新增不影响旧逻辑的可选字段
6. 新增完全向后兼容的 CLI 选项

原则：

1. 旧命令还能跑
2. 旧产物还能被旧脚本读取
3. 旧 schema 记录还能通过校验

## 4. 哪些改动必须走变更流程

下面这些改动必须先提案，再写代码：

1. 删除 CLI 参数
2. 修改 CLI 参数语义
3. 删除现有输出文件
4. 修改现有 JSON 字段含义
5. 修改 schema 名或版本名
6. 修改 bridge 输入/输出 contract
7. 修改 PJC 结果治理语义
8. 让主链路开始强依赖新的数据库、服务或外部系统
9. 让旧 pipeline 无法在兼容模式下继续运行

## 5. 变更提案格式

所有接口变更提案统一放到：

```text
docs/change_requests/
```

文件命名：

```text
docs/change_requests/<YYYYMMDD>_<topic>.md
```

每份提案必须包含：

1. 变更目标
2. 当前接口
3. 拟议接口
4. 兼容性影响
5. 回滚方案
6. 需要谁配合
7. 验证方法

目录说明和模板见：

```text
docs/change_requests/README.md
docs/change_requests/00000000_change_request_template.md
```

## 6. 兼容性规则

默认遵守下面 4 条：

1. 能新增字段，就不改旧字段。
2. 能新增文件，就不删旧文件。
3. 能做 adapter，就不直接改主链路。
4. 能先做 sidecar，就不要立刻让主链路强依赖新模块。

## 7. 三个人的职责边界

### 你

你是主链路 owner，负责：

1. `sse -> recovery -> bridge -> pjc -> release` 主链路接口定义
2. policy / scope / audit 主语义
3. 任何破坏兼容性的最终批准

### 工程师 1

负责：

1. 审计 sidecar
2. 运维工具
3. benchmark / scan / CI

默认不能改主链路 contract。

### 工程师 2

负责：

1. SQL control-plane sidecar
2. migration / import / query 工具

第一阶段默认不能让主链路直接写数据库。

## 8. 合并规则

任何 PR 如果碰到下面任意一点，必须你亲自 review：

1. `schemas/`
2. `sse/run_client.py`
3. `sse/frontend/client/commands.py`
4. `scripts/run_sse_bridge_pipeline.sh`
5. `bridge/src/main.rs`
6. `a-psi/moduleA_psi/scripts/policy_release.py`

## 9. 验证规则

任何接口相关 PR，至少要附上下面其中一类验证：

1. `python3 -m py_compile ...`
2. `bash -n scripts/run_sse_bridge_pipeline.sh`
3. `bash scripts/check_json_contracts.sh`
4. `python3 scripts/check_schema_backcompat.py`
5. 定向 smoke test
6. 新旧接口兼容性说明

如果 PR 触碰 owner 主链路边界，建议额外使用：

```text
docs/OWNER_MAINLINE_CHANGE_CHECKLIST.md
```

对已经冻结的 schema，仓库现在还有一个默认 guard：

```bash
python3 scripts/check_schema_backcompat.py
```

它会读取 `config/schema_backcompat_baseline.json`，阻止下面几类未审批的 breaking change：

1. 改 schema `$id`
2. 删稳定 top-level 字段
3. 删既有 required 字段
4. 新增 required 字段

## 10. 当前推荐策略

在主链路还没完全收口前，统一采用：

1. 主链路保守
2. sidecar 激进
3. adapter 优先
4. 兼容优先

一句话总结：

1. 别人可以围着主链路加东西。
2. 但不能擅自改主链路的接口定义权。
