# seccomp-privacy-platform

> Note
> This module now lives under `a-psi/` in the workspace root.
> Unless otherwise stated, run the examples from the `a-psi/` directory.

本项目基于 Google `private-join-and-compute` 实现广告平台与电商平台之间的隐私保护归因实验，当前仓库主要包含：

- 原始数据到 `server.csv` / `client.csv` 的输入准备
- 单机 PJC/PSI 实验流水线
- 双机 `server` / `client` 拆分执行
- 结果同步与发布治理
- 分桶执行与结果合并
- 运行时容器化骨架

当前工作分支为 `a-psi`。

## 1. 目录概览

- [moduleA_psi/scripts/prep_inputs.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/prep_inputs.py)
  从 Criteo TSV 生成 `server.csv`、`client.csv` 和 `job_meta.json`
- [moduleA_psi/scripts/run_pjc.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc.sh)
  单机模式下本地同时运行 PJC `server` 和 `client`
- [moduleA_psi/scripts/run_pipeline.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pipeline.sh)
  单机端到端流程：Prepare -> PJC -> Policy
- [moduleA_psi/scripts/policy_release.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/policy_release.py)
  阈值发布、频控、审计、可选认证与防重放
- [moduleA_psi/scripts/init_pjc_job.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/init_pjc_job.py)
  从已经准备好的 CSV 初始化双机标准 job 目录
- [moduleA_psi/scripts/run_pjc_job_server.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_job_server.sh)
  按 job 目录运行服务端，自动识别单桶或分桶
- [moduleA_psi/scripts/run_pjc_job_client.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_job_client.sh)
  按 job 目录运行客户端，自动识别单桶或分桶
- [moduleA_psi/scripts/run_pjc_server.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_server.sh)
  双机模式下只运行 PJC `server`
- [moduleA_psi/scripts/run_pjc_client.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_client.sh)
  双机模式下只运行 PJC `client`
- [moduleA_psi/scripts/run_pjc_bucketed_server.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_bucketed_server.sh)
  双机模式下按桶顺序运行服务端
- [moduleA_psi/scripts/run_pjc_bucketed_client.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_bucketed_client.sh)
  双机模式下按桶顺序运行客户端并合并结果
- [moduleA_psi/scripts/merge_bucket_results.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/merge_bucket_results.py)
  合并各桶 `attribution_result.json`
- [moduleA_psi/scripts/result_sink_server.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/result_sink_server.py)
  接收客户端回传结果的轻量 HTTP 服务
- [moduleA_psi/scripts/push_result.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/push_result.py)
  将客户端结果 POST 到回调地址
- [moduleA_psi/docs/pjc_split_deployment_plan.md](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/docs/pjc_split_deployment_plan.md)
  双机拆分、结果同步、分桶和容器化说明
- [moduleA_psi/docs/pjc_public_two_host_console_runbook.md](/home/llvanion/Desktop/seccomp-privacy-platform/a-psi/moduleA_psi/docs/pjc_public_two_host_console_runbook.md)
  公网双机 PJC 的控制台操作手册，包含 mTLS、preflight、结果查看与安全说明
- [deploy/docker/README.md](/home/llvanion/Desktop/seccomp-privacy-platform/deploy/docker/README.md)
  运行时 Docker 骨架说明

## 2. 角色说明

协议层角色：

- `server`：通常表示广告平台或曝光侧，持有 `server.csv`
- `client`：通常表示电商平台或转化侧，持有 `client.csv`

治理层角色：

- `caller`：发起结果发布请求的业务身份
- `key_id`：认证时使用的密钥标识

注意：

- `server/client` 是 PJC 协议角色，不等于 `caller`
- 当前开源库默认由 `client` 获得最终 `intersection_size` 和 `intersection_sum`

## 3. 构建依赖

底层 PJC 子项目位于 [private-join-and-compute](/home/llvanion/Desktop/seccomp-privacy-platform/private-join-and-compute)，使用 Bazel 构建。

推荐先在 `private-join-and-compute` 下编译：

```bash
cd /home/llvanion/Desktop/seccomp-privacy-platform/private-join-and-compute
bazel build -c opt //private_join_and_compute:server //private_join_and_compute:client
```

如果目标机器不想安装 Bazel，可以：

- 在一台机器上预编译二进制
- 将 `private_join_and_compute/server` 和 `private_join_and_compute/client` 所在目录分发到目标机器
- 运行时设置 `PJC_BIN_DIR`

## 4. 标准输出目录

一个标准 job 目录通常为：

```text
runs/<job_id>/
  server.csv
  client.csv
  job_meta.json
  attribution_result.json
  public_report.json
  audit_log.jsonl
```

分桶 job 目录通常为：

```text
runs/<job_id>/
  job_meta.json
  bucket_<field>=<value>/
    server.csv
    client.csv
    attribution_result.json
  attribution_result.json
```

关键文件：

- `server.csv`：PJC 服务端输入
- `client.csv`：PJC 客户端输入
- `job_meta.json`：任务元信息
- `attribution_result.json`：协议执行直接输出
- `public_report.json`：治理后的公开结果
- `audit_log.jsonl`：审计日志

## 5. 单机实验流程

适合：

- 本地功能验证
- 单机 benchmark
- 原始 Criteo TSV 端到端实验

### 5.1 从 Criteo TSV 生成输入

```bash
cd /home/llvanion/Desktop/seccomp-privacy-platform
python3 moduleA_psi/scripts/prep_inputs.py \
  --criteo-tsv data/extracted/criteo/latest/Criteo_Conversion_Search/CriteoSearchData \
  --out runs/w3_criteo_count_day \
  --start-ts 1596439471 \
  --end-ts 1596445871 \
  --value-mode count \
  --job-id w3_criteo_count_day
```

可选参数：

- `--bucket-field`
- `--hmac-secret`
- `--purchase-use-conversion-ts`

### 5.2 单机运行 PJC

```bash
cd /home/llvanion/Desktop/seccomp-privacy-platform
export PJC_DIR="$PWD/private-join-and-compute"
export SERVER_CSV="runs/w3_criteo_count_day/server.csv"
export CLIENT_CSV="runs/w3_criteo_count_day/client.csv"
export OUT_DIR="runs/w3_criteo_count_day"
export JOB_ID="w3_criteo_count_day"
export GRPC_MAX_MESSAGE_MB="512"
bash moduleA_psi/scripts/run_pjc.sh
```

### 5.3 发布治理

```bash
cd /home/llvanion/Desktop/seccomp-privacy-platform
python3 moduleA_psi/scripts/policy_release.py \
  --job-dir runs/w3_criteo_count_day \
  --caller demo \
  --k 20 \
  --n 5
```

### 5.4 一键端到端

```bash
cd /home/llvanion/Desktop/seccomp-privacy-platform
bash moduleA_psi/scripts/run_pipeline.sh \
  --criteo-tsv data/extracted/criteo/latest/Criteo_Conversion_Search/CriteoSearchData \
  --start-ts 1596439471 \
  --end-ts 1596445871 \
  --value-mode count \
  --out runs/w3_criteo_count_day \
  --job-id w3_criteo_count_day \
  --k 20 \
  --caller demo
```

## 6. 双机流程

双机场景下，不建议再把单机 pipeline 当正式入口。更推荐的流程是：

1. 双方各自准备本方 CSV
2. 使用 [init_pjc_job.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/init_pjc_job.py) 初始化标准 job
3. 服务端机器运行 [run_pjc_job_server.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_job_server.sh)
4. 客户端机器运行 [run_pjc_job_client.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_job_client.sh)
5. 如有需要，由客户端回传结果

### 6.1 初始化单桶 job

```bash
cd /home/llvanion/Desktop/seccomp-privacy-platform
python3 moduleA_psi/scripts/init_pjc_job.py \
  --out runs/job_csv_ready \
  --server-csv /path/to/server.csv \
  --client-csv /path/to/client.csv
```

### 6.2 运行服务端

```bash
cd /home/llvanion/Desktop/seccomp-privacy-platform
export SERVER_ADDR=0.0.0.0:10501
bash moduleA_psi/scripts/run_pjc_job_server.sh runs/job_csv_ready
```

### 6.3 运行客户端

```bash
cd /home/llvanion/Desktop/seccomp-privacy-platform
export SERVER_ADDR=<server_ip>:10501
bash moduleA_psi/scripts/run_pjc_job_client.sh runs/job_csv_ready
```

### 6.4 预编译二进制运行

如果不依赖 Bazel，额外设置：

```bash
export PJC_BIN_DIR=/path/to/runtime_bin
```

要求：

- `$PJC_BIN_DIR/private_join_and_compute/server`
- `$PJC_BIN_DIR/private_join_and_compute/client`

## 7. 结果同步

由于当前开源库默认由 `client` 获得结果，若双方都需要同样结果，可使用以下方式。

### 7.1 回调到结果接收服务

先在服务端或协调端启动接收服务：

```bash
cd /home/llvanion/Desktop/seccomp-privacy-platform
mkdir -p runs/result_sink
python3 moduleA_psi/scripts/result_sink_server.py \
  --host 0.0.0.0 \
  --port 18080 \
  --out-dir runs/result_sink
```

客户端执行时添加：

```bash
export RESULT_CALLBACK_URL=http://<result_sink_host>:18080/results
export RESULT_CALLBACK_TOKEN=<optional_token>
```

### 7.2 共享结果目录

客户端执行时添加：

```bash
export SHARED_RESULT_DIR=/path/to/shared_results
```

执行完成后会额外生成：

```text
$SHARED_RESULT_DIR/<job_id>.json
```

## 8. 分桶执行

现有单机分桶脚本：

- [run_pjc_bucketed.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_bucketed.sh)
- [run_pjc_sharded_parallel.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_sharded_parallel.sh)

主要仍面向单机本地并发实验。

双机分桶推荐使用：

- [run_pjc_bucketed_server.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_bucketed_server.sh)
- [run_pjc_bucketed_client.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_bucketed_client.sh)
- [run_pjc_job_server.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_job_server.sh)
- [run_pjc_job_client.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_job_client.sh)

### 8.1 bucket manifest

示例见：

- [bucket_manifest.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/examples/bucket_manifest.example.json)

### 8.2 初始化分桶 job

```bash
cd /home/llvanion/Desktop/seccomp-privacy-platform
python3 moduleA_psi/scripts/init_pjc_job.py \
  --out runs/job_bucketed_ready \
  --bucket-manifest moduleA_psi/examples/bucket_manifest.example.json
```

### 8.3 双机执行分桶 job

服务端机器：

```bash
cd /home/llvanion/Desktop/seccomp-privacy-platform
export SERVER_ADDR=0.0.0.0:10501
bash moduleA_psi/scripts/run_pjc_job_server.sh runs/job_bucketed_ready
```

客户端机器：

```bash
cd /home/llvanion/Desktop/seccomp-privacy-platform
export SERVER_ADDR=<server_ip>:10501
bash moduleA_psi/scripts/run_pjc_job_client.sh runs/job_bucketed_ready
```

客户端完成后会自动调用 [merge_bucket_results.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/merge_bucket_results.py) 合并结果。

## 9. 发布治理

[policy_release.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/policy_release.py) 负责：

- 阈值发布
- 频控
- 审计
- 可选认证
- 可选防重放

基础用法：

```bash
cd /home/llvanion/Desktop/seccomp-privacy-platform
python3 moduleA_psi/scripts/policy_release.py \
  --job-dir runs/w3_criteo_count_day \
  --caller demo \
  --k 20 \
  --n 5
```

认证模式示例：

```bash
cd /home/llvanion/Desktop/seccomp-privacy-platform
python3 moduleA_psi/scripts/policy_release.py \
  --job-dir runs/w3_criteo_count_day \
  --caller judge_demo \
  --k 20 \
  --n 5 \
  --auth-config moduleA_psi/config/auth_config.example.json \
  --auth-required \
  --key-id demo-key-001 \
  --timestamp 2026-02-28T12:00:00Z \
  --nonce nonce-demo-001 \
  --signature <hex_hmac>
```

## 10. 建议的使用顺序

当前建议按以下顺序推进：

1. 先用小规模 CSV 验证双机单桶
2. 再验证结果同步
3. 再验证双机分桶
4. 再接入 `policy_release.py`
5. 最后再做容器化和前端集成

当前不建议一开始就用百万级数据压测，也不建议先为了双机场景去重写一个新的单机总 pipeline。

## 11. 容器化

运行时 Docker 骨架位于：

- [deploy/docker/server.Dockerfile](/home/llvanion/Desktop/seccomp-privacy-platform/deploy/docker/server.Dockerfile)
- [deploy/docker/client.Dockerfile](/home/llvanion/Desktop/seccomp-privacy-platform/deploy/docker/client.Dockerfile)
- [deploy/docker/README.md](/home/llvanion/Desktop/seccomp-privacy-platform/deploy/docker/README.md)

它们用于：

- 以预编译二进制运行 `server` / `client`
- 固化运行环境
- 为后续服务化和部署提供基础骨架

## 12. 进一步说明

更详细的双机拆分、风险、分桶和容器化说明见：

- [pjc_split_deployment_plan.md](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/docs/pjc_split_deployment_plan.md)
