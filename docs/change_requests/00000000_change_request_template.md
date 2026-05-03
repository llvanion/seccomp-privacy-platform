# 变更提案模板：<topic>

## 1. 变更目标

一句话写清为什么要改，以及不改会卡住什么。

## 2. 当前接口

列出当前实际存在的接口、字段、文件或 schema：

1. 入口：
2. 字段：
3. 输出：
4. 相关 schema：

## 3. 拟议接口

明确写出准备怎么改：

1. 新增什么
2. 修改什么
3. 删除什么
4. 哪些保持不变

## 4. 冻结语义影响

逐项说明是否碰到这些字段：

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

如果碰到，必须写清：

1. 当前含义
2. 新含义
3. 为什么不算破坏兼容，或者为什么必须破坏兼容

## 5. 兼容性策略

必须回答：

1. 旧命令还能不能跑
2. 旧产物还能不能读
3. 旧 schema 记录还能不能过校验
4. 是否需要 adapter / compatibility shim

## 6. 泄漏边界影响

必须说明：

1. 是否扩大了明文暴露面
2. 是否改变了 recovery boundary
3. 是否改变了 bridge 可见内容
4. 是否改变了 release 可发布内容

## 7. 回滚方案

写清：

1. 怎么回退
2. 回退后哪些旧路径继续有效
3. 是否需要数据迁移或 artifact 兼容处理

## 8. 需要谁配合

列出需要同步的模块或角色：

1. SSE
2. recovery
3. bridge
4. PJC
5. policy release
6. 文档 / runbook / schema

## 9. 验证方法

至少列出准备怎么验证：

1. `bash -n scripts/run_sse_bridge_pipeline.sh`
2. `bash scripts/check_json_contracts.sh`
3. `python3 scripts/check_schema_backcompat.py`
4. file handoff replay
5. FIFO handoff replay
6. 定向 smoke test

## 10. 文档同步

准备更新哪些文档：

1. `docs/INTERFACE_FREEZE_AND_CHANGE_PROCESS.md`
2. `docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md`
3. `docs/SSE_BRIDGE_APSI_PIPELINE.md`
4. `README.md`
5. `CODEX_CONTEXT.md`

## 11. Owner 决策

### 结论

- [ ] 批准
- [ ] 有条件批准
- [ ] 拒绝

### 备注

写清批准条件、阻塞点或额外要求。
