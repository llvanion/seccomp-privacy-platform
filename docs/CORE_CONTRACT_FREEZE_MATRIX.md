# 核心 Contract 冻结矩阵

## 1. 目标

这份文档把项目负责人负责冻结的核心语义落到“字段 -> 载体 -> 生产者 -> 消费者”的矩阵里。

它服务两个目的：

1. 防止“字段名字还在，但含义已经漂了”。
2. 防止多人并行开发时只看单个 schema，不看全链路语义。

与 [INTERFACE_FREEZE_AND_CHANGE_PROCESS.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/INTERFACE_FREEZE_AND_CHANGE_PROCESS.md) 的关系：

1. 变更流程文档回答“怎么改”。
2. 这份矩阵回答“什么东西不能被重新解释”。

## 2. Owner 冻结字段

| 语义字段 | 当前含义 | 主要载体 | 主要生产者 | 主要消费者 | 变更规则 |
| --- | --- | --- | --- | --- | --- |
| `job_id` | 一次主链路运行的稳定作业标识 | `sse_bridge_export_audit/v1`、`bridge_job_meta/v1`、`bridge_audit/v1`、`pjc_audit/v1`、`policy_audit/v1`、`audit_chain.json`、`public_report.json` | SSE export、bridge、PJC、policy release、audit-chain builder | 全链路 | 只能新增载体，不能换语义 |
| `correlation_id` | 跨阶段审计关联标识；当前默认与 job 级别同向跟踪 | export audit、bridge audit、PJC audit、policy audit、`audit_chain.json`、public report | SSE export、bridge、PJC、policy release | 审计、观测、链路回放 | 不能改成别的 trace 概念 |
| `caller` | 发起当前查询/运行的调用主体 | export audit、policy audit、public report、service audit、metadata sidecar | SSE export、policy release、record recovery service | policy、审计、sidecar read APIs | 不能被 account/workspace 等命名替代 |
| `tenant_id` | caller 所属租户作用域 | export audit、record recovery config/health/audit、metadata sidecar | policy config、record recovery runtime、SSE export | export policy、service authz、metadata importer | 只能向后兼容扩展 |
| `dataset_id` | 当前查询与恢复边界绑定的数据集作用域 | export audit、record recovery config/health/audit、metadata sidecar | policy config、record recovery runtime、SSE export | service authz、sidecar 查询 | 不能改成 project/data_source 等别名 |
| `service_id` | 当前恢复边界或相关服务实例标识 | record recovery config/health/audit、export audit、metadata sidecar | record recovery runtime、SSE export | service health、authz、importer | 不得静默换成新的 service naming 体系 |
| `record_recovery_boundary` | 当前恢复边界类型 | `sse_bridge_export_audit/v1` | SSE export path | leakage model、audit review、pipeline hardening | 当前允许值只包括 `worker_subprocess`、`service_socket`、`service_http` |
| `token_scope` | bridge HMAC token 的作用域命名空间 | `bridge_job_meta/v1`、policy release bridge context | bridge CLI | bridge validator、policy release、审计核对 | 不能改成租户 ID 或 job ID 的别名 |
| `token_key_version` | 生成 join token 时使用的 key version | `bridge_job_meta/v1`、`bridge_audit/v1`、policy release bridge context、key access audit | bridge、key resolver | bridge validator、policy release、审计 | 只能变载体，不变含义 |
| `release_policy` | 最终结果发布规则的 owner 语义总称 | 当前以 `policy_version`、`threshold_k`、`rate_limit_*`、duplicate-query 规则、`reason_code` 共同承载 | `policy_release.py` | public report、policy audit、review/replay | 当前还不是单一顶层字段；如要新增专门字段，必须走变更提案 |

## 3. 当前主要 Contract 载体

### 3.1 SSE export

主载体：

1. `schemas/sse_bridge_export_audit.schema.json`
2. `sse/config/export_policy.example.json`

必须稳定的语义：

1. `caller`
2. `job_id`
3. `correlation_id`
4. `tenant_id`
5. `dataset_id`
6. `service_id`
7. `record_recovery_boundary`
8. handoff type / hash / row-count 审计语义

### 3.2 Record recovery

主载体：

1. `schemas/record_recovery_service_config.schema.json`
2. `schemas/sse_record_recovery_service_audit.schema.json`
3. `schemas/sse_record_recovery_health.schema.json`

必须稳定的语义：

1. `service_id`
2. `tenant_id`
3. `dataset_id`
4. recovery 仅恢复授权字段
5. recovery 审计不写 recovered plaintext

### 3.3 Bridge

主载体：

1. `schemas/bridge_job_meta.schema.json`
2. `schemas/bridge_audit.schema.json`

必须稳定的语义：

1. `token_scope`
2. `token_key_version`
3. join-key normalization contract
4. `normalizer_schema_version` — 代码级 normalizer 算法版本；当前唯一已知值为 `"normalizer-schema/v1"`；新实现必须注册新版本号，而不是复用旧值
5. `server_normalizer` / `client_normalizer` — 每侧 normalizer 类型；允许值为 `identity`、`email`、`phone`；扩展新 normalizer 必须走 change request
6. `server.csv` / `client.csv` 语义
7. FIFO 与 file handoff 的审计解释

### 3.4 PJC

主载体：

1. `schemas/pjc_audit.schema.json`
2. `a-psi/moduleA_psi/scripts/run_pjc.sh`

必须稳定的语义：

1. PJC 只消费 token 化 join key 和必要 value
2. 不回接 raw candidate IDs
3. 结果仍需进入 policy release

### 3.5 Policy release

主载体：

1. `schemas/policy_audit.schema.json`
2. `a-psi/moduleA_psi/scripts/policy_release.py`
3. `public_report.json`

必须稳定的语义：

1. 阈值 `k`
2. rate-limit / duplicate-query 防护
3. `policy_version`
4. 发布与拒绝原因
5. bridge context 在 public report / audit 中的解释

## 4. 当前允许的兼容变更

下面这些通常可以通过兼容方式完成：

1. 新增可选字段
2. 新增 sidecar 派生文件
3. 新增只读 API 包装层
4. 新增不影响旧调用的 CLI 选项
5. 新增更强的 replay / smoke / contract 校验

## 5. 必须提案的变化

任何涉及下面任一点的变化都必须先写 `docs/change_requests/...`：

1. 改上表任一冻结语义
2. 改主入口参数语义
3. 改 `server.csv` / `client.csv` 列语义
4. 改 `record_recovery_boundary` 取值或解释
5. 把 `release_policy` 从当前组合语义改成新的单体字段
6. 让主链路开始强依赖新数据库、新 API 或新执行引擎

## 6. 使用方式

做主链路变更时，先按这个顺序检查：

1. 改动是否碰到本矩阵里的语义字段
2. 改动是否只新增载体或新增可选字段
3. 是否需要补 `docs/change_requests/...`
4. 是否要更新 schema、回放验证和 threat/leakage 文档

建议与 [OWNER_MAINLINE_CHANGE_CHECKLIST.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/OWNER_MAINLINE_CHANGE_CHECKLIST.md) 一起使用。
