# KMS 与 Secret Backend 方案

## 1. 目标

这份文档定义当前仓库里 bridge token secret 及相关密钥材料的第一阶段来源、替换路径和后续演进方向。

目标：

1. 保持当前 `bridge` CLI 与主链路参数语义不变。
2. 把 secret source 从“直接命令行传值”逐步收敛到受控解析路径。
3. 为后续接 Vault 或真实外部 KMS 预留兼容接口。

## 2. 当前实现基线

当前仓库已经有三条 secret sourcing 路径：

### 2.1 直接环境变量

主链路可继续通过：

```bash
--token-secret-env BRIDGE_TOKEN_SECRET
```

特点：

1. 最简单
2. 与当前 `bridge` `--production-mode` 兼容
3. 仍然要求 secret 已经落到本地进程环境

### 2.2 本地 keyring + Unix socket key agent

当前实现文件：

1. `config/keyring.example.json`
2. `schemas/keyring.schema.json`
3. `scripts/keyring_lib.py`
4. `scripts/key_agent_service.py`
5. `scripts/request_key_agent.py`
6. `scripts/manage_keyring.py`

能力：

1. `keyring/v1` 记录 key name、purpose、active_version、allowed_callers 和版本状态。
2. 每个版本的 secret 仍然通过 `secret_ref.kind=env` 指向环境变量。
3. key agent 通过 Unix socket 暴露受控解析接口。
4. key access 会写入 `key_access_audit/v1`。
5. key rotation / status 变更会写入 `key_lifecycle_audit/v1`。

### 2.3 外部 HTTP KMS

当前实现文件：

1. `config/external_kms.example.json`
2. `schemas/external_kms_config.schema.json`
3. `scripts/external_kms_lib.py`
4. `scripts/external_kms_service.py`
5. `scripts/request_external_kms.py`
6. `scripts/manage_external_kms.py`

能力：

1. client 通过 `external_kms_config/v1` 指向 HTTP endpoint。
2. service 提供 `/healthz`、`/v1/resolve`、`/v1/admin/rotate`、`/v1/admin/set-status`。
3. 解析结果仍沿用 keyring 的 `purpose`、`allowed_callers`、`active_version` 语义。
4. HTTP 模式也会写 key access / lifecycle audit。

## 3. 当前模型的核心约束

### 3.1 不能改 bridge contract

后续即使接入 Vault 或真实 KMS，也不要改掉这些主链路语义：

1. `bridge` 仍然消费一个实际 secret 值
2. `token_scope`、`token_key_version` 语义保持不变
3. `scripts/run_sse_bridge_pipeline.sh` 的 secret source 参数保持兼容

当前允许的 secret source 模式应继续共存：

1. `--token-secret`
2. `--token-secret-env`
3. `--token-secret-key-id`
4. `--token-secret-key-name`

### 3.2 不能让 KMS 取代隐私策略

KMS 只负责：

1. secret 解析
2. 生命周期管理
3. access audit

KMS 不负责：

1. SSE export policy
2. record recovery policy
3. release policy

### 3.3 审计不可丢

无论 secret 从哪里来，都必须保留：

1. `key_id`
2. `key_version`
3. `purpose`
4. `caller`
5. `job_id`
6. `decision`
7. `reason_code`
8. `resolver.kind`

## 4. 当前 secret backend 语义

## 4.1 `keyring/v1`

当前 schema 表达的是“元数据 + secret 引用”，不是 secret 本体存储。

一个 key 由这些部分构成：

1. `key_name`
2. `purpose`
3. `active_version`
4. `allowed_callers`
5. `versions.<version>.enabled`
6. `versions.<version>.status`
7. `versions.<version>.secret_ref`

当前 `secret_ref` 只支持：

1. `kind=env`
2. `name=<ENV_VAR>`

这意味着本地 keyring 当前更像：

1. 访问控制和版本目录
2. 不是最终安全存储

## 4.2 `external_kms_config/v1`

当前外部 KMS client config 包含：

1. `endpoint_url`
2. `auth_token_env`
3. `admin_auth_token_env`
4. `request_timeout_sec`
5. `auto_start`

`auto_start` 目前仍然依赖一个本地 state file：

1. `state_file`

这说明当前 external KMS 仍是 mock service / adapter，而不是独立可信根。

## 5. 风险与缺口

当前实现已经比直接 `--token-secret` 更好，但仍有明显缺口：

### 5.1 secret 仍可回落到本地 env

无论是 key agent 还是 external KMS，最终解析仍来自环境变量。

风险：

1. 同 Unix user 下进程环境泄露
2. 本地 shell 历史或调试习惯导致暴露
3. 容器/主机级隔离不足时 secret 边界偏弱

### 5.2 解析结果仍返回明文 secret

当前 resolver 返回：

1. `key_id`
2. `key_version`
3. `secret`

这是兼容现有 bridge 的必要做法，但意味着调用进程仍能看到明文 secret。

### 5.3 缺少硬件或远端可信根

当前没有：

1. HSM
2. Vault Transit
3. cloud KMS decrypt/sign
4. mTLS 级别服务身份

### 5.4 生命周期仍偏本地文件模式

当前 rotation / status 变更以 JSON 文件为状态源，适合本地 demo，不适合多实例生产环境。

## 6. 演进原则

### 6.1 先抽象 source，不改 consumer

优先保证：

1. `bridge` 继续拿到同样的 secret 值
2. `scripts/run_sse_bridge_pipeline.sh` 继续支持同样的参数
3. `key_access_audit` 和 `key_lifecycle_audit` 继续保留

### 6.2 先替换 backend，再增强协议

演进顺序建议：

1. 先把 env-backed `secret_ref` 替换为更正式的 secret backend 引用
2. 再增强 resolver 的身份认证和服务部署方式
3. 最后再考虑 bridge 是否能升级到“远端签名/HMAC 服务”模式

第三步属于更高风险接口变化，必须单独走变更流程。

## 7. 推荐 backend 目标态

## 7.1 Vault 路线

适用目标：

1. 本地或私有部署环境
2. 需要统一 secret、rotation、audit、policy

推荐接入模式：

1. `keyring/v1` 继续存在，但 `secret_ref.kind` 扩展为 `vault`
2. `secret_ref.name` 保存 Vault path 或 key reference
3. key agent / external KMS adapter 读取 Vault，再返回兼容结果

这样做的好处：

1. 不改桥接层参数
2. 可保留现有 key name / version / caller allowlist 语义
3. 可继续写统一 access audit

### 7.2 Cloud / 外部 KMS 路线

适用目标：

1. 真实外部服务边界
2. 多服务实例共享 key state

推荐接入模式：

1. `external_kms_service.py` 从 mock service 升级为 adapter
2. `state_file` 被远端 KMS / key registry 替代
3. `resolve_secret_via_external_kms()` 继续返回兼容结构

说明：

1. 第一阶段不要求 remote HMAC。
2. 仍以“解析 secret 并交给 bridge”作为兼容路径。

## 8. 兼容扩展建议

如果要在 `keyring/v1` 上逐步演进，建议只做向后兼容扩展。

### 8.1 `secret_ref.kind`

当前只有：

1. `env`

后续可扩展：

1. `vault`
2. `external_kms`
3. `file`

但新 kind 上线前需要：

1. resolver 实现
2. 兼容测试
3. schema 更新
4. change request 审批

### 8.2 lifecycle metadata

后续可新增但不替代现有字段：

1. `rotated_by`
2. `rotation_reason`
3. `expires_at_utc`
4. `backend_ref`
5. `backend_key_version`

## 9. 分阶段落地计划

### Phase 0：保持当前三种来源并统一文档

保留：

1. env
2. key agent
3. external KMS

目标：

1. 所有路径都能被 `scripts/check_platform_health.py` 探测
2. 所有路径都能产出 access audit
3. 主链路 demo 保持可跑

### Phase 1：把 keyring 从“env 索引”升级为“backend 引用索引”

动作：

1. 扩展 `secret_ref.kind`
2. 保留 `key_name`、`purpose`、`active_version`、`allowed_callers`
3. 新 backend 先由 key agent / external KMS adapter 消费

目标：

1. `manage_keyring.py` 仍能做版本切换
2. importer 仍能导入 `key_access_audit`
3. pipeline 参数不变

### Phase 2：服务身份与认证增强

动作：

1. 给 key agent 和 external KMS 引入更正式的 service identity
2. bearer token 逐步换成 OIDC 或 mTLS 绑定主体
3. 服务端限制 allowed callers / operators

目标：

1. 让 resolver 边界更接近真实服务
2. 不再默认信任同机任意本地进程

### Phase 3：远端可信根

动作：

1. 将 secret material 从本地 env 挪到 Vault 或真实 KMS
2. resolver 不再依赖本地 state file 存真实 secret source

目标：

1. rotation 可集中管理
2. access audit 可集中留存
3. 更适合多实例服务部署

### Phase 4：评估 remote tokenization

这是后续可选增强，不属于第一阶段。

方向：

1. 让 `bridge` 不再直接接收明文 token secret
2. 改为 remote HMAC/tokenization service

注意：

1. 这会改变主链路安全边界
2. 需要单独 change request
3. 需要重新审视 `bridge_job_meta`、审计和性能影响

## 10. 对现有入口的建议

### `scripts/run_sse_bridge_pipeline.sh`

继续支持当前 secret source 模式，但推荐优先级调整为：

1. `--token-secret-key-name` + `--external-kms-config`
2. `--token-secret-key-name` + `--keyring`
3. `--token-secret-env`
4. `--token-secret`

### `scripts/run_live_sse_bridge_demo.sh`

继续保留 demo 友好路径，但建议：

1. 默认文档优先演示 keyring / external KMS 路径
2. 仅在最简 smoke 示例里保留裸 env 模式

### `scripts/manage_keyring.py`

作为本地 lifecycle CLI 保留，后续可扩展：

1. backend 校验
2. version expiry
3. policy guard

### `scripts/manage_external_kms.py`

继续作为 admin adapter 保留，后续优先让它面向真实远端 KMS，而不是本地 JSON state。

## 11. 审计与控制面联动

当前 metadata sidecar 已有 `key_access_events` 表，建议后续继续补：

1. key registry 只读视图
2. key version 状态导入
3. key backend 类型统计
4. rotation 历史只读查询

但第一阶段不要让 metadata DB 成为 secret 读取依赖。

## 12. 非目标

这份方案当前不做：

1. 在仓库里直接实现 Vault 完整集成
2. 改写 bridge 让其调用远端 HSM API
3. 让 release policy 依赖 KMS 决策
4. 把 secret material 落入 metadata sidecar

## 13. 建议的下一步

1. 先把 keyring 文档和 external KMS 文档固定为统一 backend 语义。
2. 再为 `secret_ref.kind` 扩展准备 change request。
3. 然后实现 Vault 或真实 KMS adapter，复用现有 access/lifecycle audit contract。
4. 只有在上述路径稳定后，再评估是否值得推动 remote tokenization 取代本地 secret 暴露。
