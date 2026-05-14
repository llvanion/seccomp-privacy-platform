# Record Recovery 独立服务化方案

## 1. 目标

把 record recovery 从“由 pipeline 本地拉起的辅助进程”推进成“可单独部署、可独立健康检查、可独立审计、可被 SSE export 远程调用的服务”。

这次方案的重点不是一次性做完整平台化，而是先把下面 4 件事做实：

1. 把 transport 从 `unix_socket` 扩成正式支持 `http`
2. 把 runtime config / health / audit contract 固化下来
3. 让 pipeline 能消费“外部已运行服务”，而不是默认假设本地 orchestration
4. 在不破坏现有链路的前提下，为后续真正拆进独立部署单元留接口

## 2. 当前可用形态

当前仓库已经支持两种 record recovery transport：

1. `unix_socket`
2. `http`

对应配置 schema 仍然是：

1. `record_recovery_service_config/v1`

当前 HTTP 服务入口：

1. `sse/run_client.py serve-record-recovery-http`

当前服务管理入口：

1. `scripts/manage_record_recovery_service.py`

当前独立部署入口：

1. `scripts/run_record_recovery_service.py`

当前服务探活入口：

1. `scripts/request_record_recovery_service.py`

当前 pipeline 入口：

1. `scripts/run_sse_bridge_pipeline.sh`

## 3. 技术栈

第一阶段独立服务化继续使用仓库现有技术栈，不引入新的重量级基础设施：

1. 服务实现：Python 3
2. HTTP server：标准库 `http.server`
3. HTTP client：标准库 `urllib.request`
4. 配置：JSON + 现有 schema 校验脚本
5. 审计：JSONL
6. 主链路调用：现有 `sse` CLI / pipeline / manager

这样做的原因很简单：

1. 先冻结 contract
2. 再决定是否迁到 FastAPI / gRPC / container runtime / service mesh

## 4. 稳定接口

### 4.1 配置接口

独立服务依赖 [record_recovery_service_config.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/record_recovery_service_config.schema.json)。

HTTP 模式最小配置：

```json
{
  "schema": "record_recovery_service_config/v1",
  "transport": "http",
  "service_id": "bridge-demo-recovery-http",
  "tenant_id": "demo_tenant",
  "dataset_id": "bridge_demo_dataset",
  "endpoint_url": "http://127.0.0.1:18081",
  "auth_token_env": "SSE_RECORD_RECOVERY_TOKEN"
}
```

推荐配置样例：

1. [record_recovery_http_service.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/config/record_recovery_http_service.example.json)

Unix-socket 模式下，`socket_path` 仍然可以显式配置；如果省略 `socket_path`，但配置或 CLI 提供了非空 `tenant_id`，resolver 会从 `tenant_id` / `service_id` / `dataset_id` 派生租户隔离 socket：

```text
/tmp/seccomp_rr_<tenant>_<hash>.sock
```

这个规则由 `services/record_recovery/config.py` 统一提供，`manage_record_recovery_service.py`、`run_record_recovery_service.py` 和 `request_record_recovery_service.py --config` 都走同一解析路径。这样 operator 可以用同一份 `record_recovery_service_config/v1` 启动、探活和停止服务，同时避免多个租户意外共用单个 Unix socket。

Kubernetes 部署场景下，网络层隔离由 `scripts/render_k8s_network_policies.py` 生成 per-tenant `NetworkPolicy`：

1. recovery-service pod selector 固定为 `app=recovery-service, tenant=<tenant_id>`。
2. ingress source 固定为 `app=sse-bridge-pipeline, tenant=<same tenant_id>`。
3. 默认端口为 `18443/TCP`，可通过脚本参数调整。
4. 输出报告遵循 `k8s_network_policy_report/v1`，示例 manifest 位于 `config/k8s/netpol-recovery-service-demo-tenant.yaml`。

`authz_config` 现在有两种稳定来源：

1. 直接指向 `sse_export_policy/v1` 或 `record_recovery_service_policy/v1` JSON。
2. 指向 [record_recovery_authz_sqlite.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/config/record_recovery_authz_sqlite.example.json) 这种 `record_recovery_authz_source/v1` 文件，再由服务端从 metadata SQLite 中重建 caller 权限视图。

第二种模式的目的不是把主链路改成强依赖 SQL，而是让独立 recovery service 在不改授权语义的前提下，可以消费 sidecar/控制面已经导入好的 caller 权限切片。

### 4.2 服务接口

HTTP 服务当前暴露：

1. `GET /healthz`
2. `POST /health`
3. `POST /recover`

鉴权方式：

1. `Authorization: Bearer <token>`
2. `X-Record-Recovery-Token: <token>`
3. 兼容 payload 中的 `auth_token`

### 4.3 健康检查 contract

健康响应遵循 [record_recovery_service_health.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/record_recovery_service_health.schema.json)。

关键字段：

1. `transport`
2. `socket_path`
3. `endpoint_url`
4. `service_id`
5. `tenant_id`
6. `dataset_id`
7. `authz_policy_config`
8. `audit_log`

### 4.4 审计 contract

服务审计遵循 [sse_record_recovery_service_audit.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/sse_record_recovery_service_audit.schema.json)。

关键字段：

1. `transport`
2. `socket_path`
3. `endpoint_url`
4. `caller`
5. `job_id`
6. `tenant_id`
7. `dataset_id`
8. `service_id`
9. `decision`
10. `reason_code`

### 4.5 运行日志 contract

服务运行日志遵循 [record_recovery_service_log.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/record_recovery_service_log.schema.json)。

这个日志是 ops telemetry，不替代审计链。它只记录服务生命周期和请求处理摘要，不写原始 candidate id、record-store 明文、filter 明文或 auth token。

关键字段：

1. `event`
2. `transport`
3. `request_id`
4. `duration_ms`
5. `decision`
6. `reason_code`
7. `service_id`
8. `tenant_id`
9. `dataset_id`
10. `tls_enabled`（start 事件）
11. `tls_require_client_cert`（start 事件）

### 4.6 TLS / mTLS 配置 contract

`record_recovery_service_config/v1` 现在支持可选的 `tls` 块，字段固定为：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `tls.enabled` | bool | 是否开启 TLS |
| `tls.server_cert` | string | 服务端证书路径（PEM） |
| `tls.server_key` | string | 服务端私钥路径（PEM） |
| `tls.ca_cert` | string | 签发客户端证书的 CA 证书路径，`require_client_cert=true` 时必填 |
| `tls.require_client_cert` | bool | 是否强制要求客户端证书（mutual TLS） |
| `tls.client_cert` | string | 客户端证书路径（客户侧） |
| `tls.client_key` | string | 客户端私钥路径（客户侧） |
| `tls.verify_hostname` | bool | 是否校验 hostname，loopback 自签名证书时设 `false` |

完整 mTLS 示例见 [record_recovery_http_mtls_service.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/config/record_recovery_http_mtls_service.example.json)。

schema 已纳入 `schemas/record_recovery_service_config.schema.json`，运行日志新增 `tls_enabled` / `tls_require_client_cert` 字段（仅 start 事件），schema 已同步更新。

## 5. 已经留下的调用接口

你现在可以把 record recovery 当成外部已运行服务来接入，调用面已经有了。

### 5.1 启动独立 HTTP 服务

```bash
python3 scripts/run_record_recovery_service.py serve \
  --config config/record_recovery_http_service.example.json
```

兼容入口仍然保留：

```bash
cd sse
.venv/bin/python run_client.py serve-record-recovery-http \
  --config ../config/record_recovery_http_service.example.json
```

### 5.2 检查服务状态

```bash
python3 scripts/request_record_recovery_service.py \
  --config config/record_recovery_http_service.example.json
```

或：

```bash
python3 scripts/manage_record_recovery_service.py status \
  --config config/record_recovery_http_service.example.json
```

如果希望服务鉴权改读 metadata SQLite：

```bash
python3 scripts/run_record_recovery_service.py serve \
  --config config/record_recovery_http_service.example.json \
  --authz-config config/record_recovery_authz_sqlite.example.json
```

或把 `record_recovery_service_config/v1` 里的 `authz_config` 直接改成该 source 文件路径。

### 5.3 让 export 走外部服务

```bash
cd sse
.venv/bin/python run_client.py export-bridge-records \
  --record-store-path /tmp/records.enc.jsonl \
  --record-store-key-env SSE_RECORD_STORE_PASSPHRASE \
  --record-recovery-service-config ../config/record_recovery_http_service.example.json \
  ...
```

### 5.4 让 pipeline 走手工管理的外部服务

```bash
bash scripts/run_sse_bridge_pipeline.sh \
  --record-recovery-service-mode manual \
  --record-recovery-service-config config/record_recovery_http_service.example.json \
  ...
```

这条路径下，pipeline 不再负责定义服务实现，只负责：

1. 读取 config
2. 请求 health
3. 校验 scope / audit / transport 对齐
4. 把 export 请求发给已运行服务

### 5.6 启动 mTLS 服务

```bash
export SSE_RECORD_RECOVERY_TOKEN=test-recovery-token
python3 scripts/manage_record_recovery_service.py start \
  --config config/record_recovery_http_mtls_service.example.json \
  --pid-file tmp/record_recovery_service_http_mtls.pid \
  --log-file tmp/record_recovery_service_http_mtls.log
```

探活：

```bash
python3 scripts/request_record_recovery_service.py \
  --config config/record_recovery_http_mtls_service.example.json
```

或：

```bash
python3 scripts/manage_record_recovery_service.py status \
  --config config/record_recovery_http_mtls_service.example.json \
  --pid-file tmp/record_recovery_service_http_mtls.pid
```

停止：

```bash
python3 scripts/manage_record_recovery_service.py stop \
  --config config/record_recovery_http_mtls_service.example.json \
  --pid-file tmp/record_recovery_service_http_mtls.pid
```

客户端侧通过 `tls_config` 字典传入 `client_cert` / `client_key` / `ca_cert` / `verify_hostname` 等字段；`manage_record_recovery_service.py start` 会在等待就绪时复用同一 `tls_config`，因此 readiness polling 也走 mTLS 路径。

### 5.5 生成独立 deploy artifact

如果不想继续停留在“手工开一个 shell 跑 start/status/stop”的层级，现在可以直接从现有 config 生成基线 `systemd` unit 和 env template：

```bash
python3 scripts/manage_record_recovery_service.py render-systemd \
  --config config/record_recovery_http_service.example.json \
  --unit-name seccomp-record-recovery-http \
  --service-user record-recovery \
  --service-group record-recovery \
  --environment-file /etc/seccomp/seccomp-record-recovery-http.env \
  --output /tmp/seccomp-record-recovery-http.service \
  --env-output /tmp/seccomp-record-recovery-http.env.example
```

这个命令的作用边界很明确：

1. 继续复用 `record_recovery_service_config/v1`
2. 继续复用 `scripts/run_record_recovery_service.py serve`
3. 把 runtime config 翻译成正式 deploy unit，而不是重新定义新的服务 contract
4. 给 `auth_token_env` 生成 env template，避免把 token 直接写进 unit 文件

它不是最终的“生产部署系统”，但它把当前独立服务从“手工脚本”推进到了“可产出标准 lifecycle artifact”的阶段。

## 6. 当前边界

### 6.1 已经独立出来的部分

1. 服务 transport 已独立
2. 服务 health contract 已独立
3. 服务 audit contract 已独立
4. 服务 runtime config 已独立
5. pipeline 可以运行在 manual external service 模式
6. standalone launcher 已和 `sse/run_client.py` 解耦
7. config/runtime ownership 已从 `sse/toolkit` 下沉到 `services/record_recovery/`
8. service/authz/common/client/worker/encrypted-store 逻辑已从 `sse/toolkit` 拆到 `services/record_recovery/`
9. `scripts/manage_record_recovery_service.py render-systemd` 可以基于同一个 config 生成基线 `systemd` unit 与 env template，便于把 manual external service 模式迁到独立 service-user/lifecycle 管理
10. **mTLS 已独立**（D1，2026-05-05）：`http_service.py` 新增 `_build_server_ssl_context()`，支持服务端 TLS + 可选 client cert 校验；`client.py` 新增 `_client_ssl_context()`，readiness polling（`wait_for_http_url`）和所有 health/recover 调用统一走 `tls_config`；`record_recovery_service_config/v1` schema 新增 `tls` 块；运行日志新增 `tls_enabled` / `tls_require_client_cert` 字段；`config/record_recovery_http_mtls_service.example.json` 固定 mTLS 配置样例

### 6.2 还没有完全独立的部分

1. authn 仍然是 env token；authz 虽然已可改读 metadata SQLite，但底层仍是单机 SQLite / 已导入 caller 权限切片，不是正式多写者 control plane
2. 部署仍然主要面向单机 / demo 环境
3. service discovery 仍然是 endpoint/config 直连
4. 没有正式的持久化 control plane

### 6.3 当前代码归属

当前代码归属已经拆成两层：

1. `services/record_recovery/` 负责 deploy unit、config/runtime 组装、推荐启动入口、Unix-socket / HTTP 服务 adapter、request handling、服务审计 payload 生成、recovery-service authz evaluator、recovery common payload/row helper、recovery-service client protocol、worker subprocess 入口和 encrypted record-store 创建/读取
2. `sse/toolkit/record_recovery_service*.py`、`sse/toolkit/record_recovery_authz.py`、`sse/toolkit/record_recovery_common.py`、`sse/toolkit/record_recovery_client.py`、`sse/toolkit/record_recovery_worker.py` 与 `sse/toolkit/encrypted_record_store.py` 暂时保留兼容 shim，旧 CLI 适配仍可工作；新实现不应再写回这些 shim

当前已经下沉到 `services/record_recovery/` 的内容：

1. `config.py`
2. `runtime.py`
3. `launcher.py`
4. `service.py`
5. `http_service.py`
6. `observability.py`
7. `bootstrap.py`
8. `authz.py`
9. `common.py`
10. `client.py`
11. `worker.py`
12. `encrypted_record_store.py`

当前仍留在 `sse/toolkit/` 的 recovery 相关代码：

1. 兼容 shim

当前验证归属：

1. `scripts/check_ci_smoke.sh` 直接编译 `services/record_recovery/*.py` 的服务实现
2. `scripts/check_ci_smoke.sh` 同时继续编译 `sse/toolkit/` 下的兼容 shim
3. `scripts/check_json_contracts.sh` 直接调用 `services.record_recovery.encrypted_record_store` 和 `services.record_recovery.client` 覆盖 Unix-socket / HTTP recovery service 的 contract smoke
4. `scripts/check_record_recovery_boundary.py` 检查旧 `sse/toolkit` recovery 文件只做兼容 shim，不重新承载函数/类实现
5. boundary check 输出遵循 [record_recovery_boundary_check.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/record_recovery_boundary_check.schema.json)
6. `scripts/verify_record_recovery_manual_service_replay.sh` 固定 manual external HTTP service 回放：预启动 standalone service，再让 live SSE demo 走 `--record-recovery-service-mode manual`

最近一次验证：

1. `bash -n scripts/check_ci_smoke.sh`
2. `python3 -m py_compile services/record_recovery/*.py`
3. `git diff --check`
4. `bash scripts/check_ci_smoke.sh`
5. `bash -n scripts/check_json_contracts.sh`
6. `python3 -m py_compile services/record_recovery/encrypted_record_store.py services/record_recovery/client.py`
7. `bash scripts/check_json_contracts.sh`
8. `python3 -m py_compile services/record_recovery/__init__.py services/record_recovery/client.py services/record_recovery/encrypted_record_store.py`
9. `python3 -c 'import services.record_recovery as rr; assert rr.IMPLEMENTATION_OWNER == "services.record_recovery"; assert rr.LEGACY_SHIM_PACKAGE == "sse.toolkit"'`
10. `python3 scripts/check_record_recovery_boundary.py`
11. `python3 -m py_compile scripts/check_record_recovery_boundary.py`
12. `python3 -m json.tool schemas/record_recovery_boundary_check.schema.json`
13. `python3 scripts/validate_json_contract.py --schema schemas/record_recovery_boundary_check.schema.json --json <boundary-check-output>`
14. `bash scripts/verify_record_recovery_manual_service_replay.sh`

## 7. 分阶段迁移

### Phase 1：先把外部服务跑稳

状态：已完成基线收口，manual external service replay 已固定。

目标：

1. 默认支持 manual external service 模式
2. 保持 `unix_socket` 与 `http` 双栈兼容
3. 不要求 bridge / PJC 感知 transport 细节

验收：

1. `export-bridge-records` 只认 config / endpoint，不认本地进程细节
2. pipeline 只认 health contract，不认服务实现细节
3. 服务 start / request / stop 运行日志可按 `record_recovery_service_log/v1` 校验
4. 可以从 config 直接生成 deploy artifact，而不是靠 README 手工拼启动命令
5. `scripts/verify_record_recovery_manual_service_replay.sh` 能预启动 external HTTP recovery service，跑通 `run_live_sse_bridge_demo.sh --record-recovery-service-mode manual`，并校验 `record_recovery_service_health.json`、运行时 config、`mainline_contract_check.json` 与 manager-captured service log

### Phase 2：把服务从 `sse/` 目录逻辑上拆出来

状态：已完成逻辑拆出，剩余工作是兼容窗口和后续部署/鉴权强化。

目标：

1. 新建独立 deploy unit
2. 保留兼容 CLI adapter
3. 把服务运行参数和业务参数分层

建议动作：

1. 新增单独的 `services/record-recovery/` 或等价目录
2. 把 HTTP service、authz、audit、config loader 收口到独立模块
3. 让 `sse/run_client.py` 只保留兼容入口

### Phase 3：加强鉴权与控制面

目标：

1. token 不再仅依赖 env
2. caller / tenant / dataset / service 权限进入持久化控制面
3. 审计具备更强防篡改能力

建议动作：

1. 引入真正的 service identity
2. 把 authz policy 从本地 JSON 迁到 SQL control plane
3. 引入 metrics / tracing / alerting

## 8. 如何控制“半成品导致接口变化”的风险

这件事不能靠大家互相提醒，要靠规则：

1. 主链路 owner 只保留一个人
2. 独立服务 contract 先冻结，再迭代实现
3. 变更默认做新增，不做替换
4. pipeline 优先依赖 config / health / audit contract，不直接依赖服务内部实现

当前建议冻结的 record recovery contract：

1. `record_recovery_service_config/v1`
2. `sse_record_recovery_health/v1`
3. `sse_record_recovery_service_audit/v1`
4. `service_id`
5. `tenant_id`
6. `dataset_id`
7. `caller`
8. `job_id`
9. `transport`
10. `socket_path`
11. `endpoint_url`

如果后面必须改接口，按 [INTERFACE_FREEZE_AND_CHANGE_PROCESS.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/INTERFACE_FREEZE_AND_CHANGE_PROCESS.md) 走。

## 9. 下一阶段真正该做的事

如果继续沿“独立服务化”推进，而不是继续堆本地 orchestration，我建议后续按这个顺序做：

1. ~~把当前基线 `systemd` artifact 进一步收紧到专用 service user、专用 writable path 和更强的主机级 hardening~~ ✓ (2026-05-01)：`render-systemd` 现在生成完整的 Linux 安全指令集：`ProtectSystem=strict`, `ProtectHome=true`, `PrivateDevices=true`, `ProtectKernelTunables/Modules/ControlGroups=true`, `LockPersonality=true`, `RestrictSUIDSGID=true`, `SystemCallFilter=@system-service`；`ReadWritePaths=` 由 `derive_writable_paths(runtime)` 自动推导（audit log 目录、socket/pid/ready 文件目录、allowed output roots）；contract smoke 已校验所有指令。
2. ~~把 auth token 升级成正式 service-to-service auth，补全 mutual TLS~~ ✓ (2026-05-01 + **D1 2026-05-05**)：
   - 时间戳反重放：`validate_request_timestamp(±30s)`，client 强制携带 `request_timestamp_utc`。
   - HMAC 请求签名：client 生成 `request_id`（UUID）和 `request_payload_sha256`，并计算 `HMAC-SHA256(token, "{request_id}:{ts}:{op}:{request_payload_sha256}")`；服务端先重算 payload hash，再用常数时间校验 hash 与签名（`hmac.compare_digest`）；签名和 payload-hash 验证结果写入审计；HTTP transport 通过 `X-Request-Signature` / `X-Request-Payload-SHA256` / `X-Request-Signature-Algorithm` 传递。
   - **D1（2026-05-05）**：`http_service.py` 新增 `_build_server_ssl_context()`；`client.py` 新增 `_client_ssl_context()`；`record_recovery_service_config/v1` schema 新增 `tls` 块（`enabled/server_cert/server_key/ca_cert/require_client_cert/client_cert/client_key/verify_hostname`）；运行日志新增 `tls_enabled` / `tls_require_client_cert`；`config/record_recovery_http_mtls_service.example.json` 固定配置样例；`manage_record_recovery_service.py start` 的 readiness polling 统一走 `tls_config`。
3. ~~补 manual external service replay，确认 pipeline 只依赖 config / health / audit contract，而不是 auto-start 细节~~ ✓ (2026-05-01)：新增 `scripts/verify_record_recovery_manual_service_replay.sh`，它预启动 standalone HTTP recovery service，运行 `run_live_sse_bridge_demo.sh --record-recovery-service-mode manual`，校验 `record_recovery_service_health.json`、`record_recovery_service_config.json`、`mainline_contract_check.json` 与 `record_recovery_service_log/v1`，最后 stop 并确认 pid/ready 生命周期文件被回收。
4. ~~引入服务级 metrics / tracing / structured logs~~ ✓ **D2（2026-05-05）**：
   - 新增 `scripts/export_record_recovery_service_metrics.py`，从 `record_recovery_service_log/v1` JSONL 生成只读 `record_recovery_service_metrics/v1` 指标摘要。
   - 新增 `schemas/record_recovery_service_metrics.schema.json`，冻结 event/request counts、transport、decision、reason_code、op、method、role、status-code、candidate_count_total 和 request duration min/max/avg/p95。
   - `scripts/check_json_contracts.sh` 已在 Unix-socket 与 HTTP recovery-service smoke 中导出并校验 metrics report，同时要求 start/request/stop 三类结构化事件存在。
   - 该指标层只消费运行日志，不替代 `sse_record_recovery_service_audit/v1`，不输出 raw candidate IDs、record-store 明文或 auth token，也不改变 recovery service 的 request/health/audit contract。
5. 把 authz policy 改成 SQL-backed control plane（下一阶段）
6. ~~把 audit seal / archive 从本地文件推进到外部锚定~~ ✓ **D3（2026-05-05）**：
   - 新增 `scripts/publish_external_audit_anchor.py`：验证本地 anchor chain（payload_sha256、entry_sha256、chain 链接、HMAC 签名），再把每条记录 append 到外部 `file_ledger` JSONL（`external_audit_anchor_ledger/v1`）；支持 `--dry-run`、`--require-signature`、`--anchor-key-env`、`--assert-ok`。
   - 新增 `schemas/external_audit_anchor_report.schema.json`，冻结 `external_audit_anchor_report/v1` contract（`summary.status/anchor_record_count/published_count/verified_chain/signed_count/last_entry_sha256` + per-record 详情）。
   - 该工具是 append-only；不修改或删除已有 ledger 记录；不输出 secret material；`--require-signature` 在生产模式下拒绝无签名 anchor 条目。
7. ~~ops runbook / failure recovery 收口~~ ✓ **D4（2026-05-05）**：
   - `OPS_RUNBOOK.md` 新增 `mTLS Recovery Service` 小节（启动、探活、TLS 配置字段说明、停止命令）。
   - `OPS_RUNBOOK.md` 新增 `External Audit Anchor Publishing` 章节（dry-run、publish、schema 校验命令、key 字段说明）。
   - `OPS_RUNBOOK.md`「Failure Recovery Decision Tree」新增 mTLS 握手失败（D1）和外部锚定失败（D3）两类排障条目。

一句话总结：

现在已经不是“只能本地拉 socket 才能跑”的半成品状态了，但也还不是最终平台服务。

当前阶段最正确的策略是：

1. 先冻结独立服务 contract
2. 让主链路只依赖 contract
3. 再逐步替换部署形态和鉴权实现

如果要纳入统一排期，建议直接对齐 [POST_BASELINE_ROADMAP.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/POST_BASELINE_ROADMAP.md) 的 `Tranche D`：

1. `D1`：recovery service mutual TLS baseline
2. `D2`：service metrics / tracing / structured logs（第一版 structured-log metrics 已完成，后续可继续补外部 metrics/tracing sink）
3. `D3`：external audit anchor baseline
4. `D4`：ops runbook / failure recovery 收口

这条线后续的重点不是再堆本地 orchestration，而是把 deploy/authn/audit 三条边界逐步做成更正式的独立服务形态。
