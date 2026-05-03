# Record Recovery Service

这个目录是 record recovery 的独立 deploy unit 入口层。

目标不是立刻重写全部底层能力，而是先把“服务启动入口”和主要服务端请求处理从 `sse/run_client.py` / `sse/toolkit` 中解耦：

1. Unix-socket / HTTP 服务 adapter 和 request/audit payload 处理收口到 `services/record_recovery/`
2. 部署入口收口到独立 launcher
3. 现有 `sse` CLI 和 `sse/toolkit/record_recovery_service*.py` / `record_recovery_authz.py` / `record_recovery_common.py` / `record_recovery_client.py` / `record_recovery_worker.py` / `encrypted_record_store.py` 仅保留兼容 adapter 角色
4. 加密 record-store 创建和读取也收口到 `services/record_recovery/`

## 当前入口

推荐入口：

```bash
python3 scripts/run_record_recovery_service.py serve \
  --config config/record_recovery_http_service.example.json
```

如果要把当前 config 直接落成独立 deploy artifact，而不是继续手工 `start/status/stop`，现在也可以生成一个基线 `systemd` unit 和 env template：

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

这个命令不会启动服务；它只把现有 `record_recovery_service_config/v1` 解析成可部署的 `ExecStart`、`EnvironmentFile` 和最小 lifecycle 建议，保持 deploy unit 仍然调用现有 `scripts/run_record_recovery_service.py serve`。

也可以显式传 transport 和运行参数：

```bash
python3 scripts/run_record_recovery_service.py serve \
  --transport http \
  --bind-host 127.0.0.1 \
  --port 18081 \
  --endpoint-url http://127.0.0.1:18081 \
  --service-id bridge-demo-recovery-http \
  --tenant-id demo_tenant \
  --dataset-id bridge_demo_dataset \
  --auth-token-env SSE_RECORD_RECOVERY_TOKEN
```

## 当前边界

这个目录只负责：

1. 启动参数解析
2. transport 选择
3. config 合并
4. `record_recovery_service_log/v1` 结构化运行日志 helper
5. Unix-socket 与 HTTP 服务端 adapter
6. request handling、health/audit payload 生成
7. recovery result / health / error payload helpers 和 bridge-row 输出 helper
8. recovery-service client protocol helper
9. worker subprocess 入口
10. encrypted record-store 创建和候选行读取
11. 兼容旧接口

`sse/toolkit/` 下的 recovery 相关文件现在主要是兼容 shim；新的实现归属在 `services/record_recovery/`。
后续新增或修改 recovery 业务逻辑时，应改 `services/record_recovery/`，不要把实现重新写回 `sse/toolkit/` 的 shim。
`scripts/check_record_recovery_boundary.py` 会自动检查这些旧 shim 仍然只从 `services.record_recovery.*` 转发，且不包含新的函数/类实现。
`scripts/check_ci_smoke.sh` 现在会直接编译 `services/record_recovery/*.py` 的真实实现，同时继续编译 `sse/toolkit/` 下的兼容 shim，避免验证入口只覆盖旧路径。
`scripts/check_json_contracts.sh` 的 recovery contract smoke 也直接调用 `services.record_recovery.encrypted_record_store` 和 `services.record_recovery.client`，旧 shim 只作为兼容路径保留。

运行日志写到服务 stdout；通过 `scripts/manage_record_recovery_service.py start` 启动时，如果 config 的 `lifecycle.log_file` 存在，则会被捕获到该文件。通过 `render-systemd` 生成 unit 时，stdout/stderr 默认走 journald，不再复用这个 manager 专用 `log_file` 捕获路径。日志 contract 为 [record_recovery_service_log.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/record_recovery_service_log.schema.json)，记录 start/request/stop 事件、耗时、decision、reason code 和非敏感 scope 信息。
