# a-psi 分支代码阅读说明

## 1. 分支目标

`a-psi` 分支实现的是**隐私保护归因（PSI/PJC）主流程**，核心是把曝光侧与转化侧数据在不泄露明文标识的前提下完成交集计算，并输出可发布结果。

主要能力包括：
- 从原始数据生成 `server.csv` / `client.csv`
- 调用 Google PJC 二进制执行 PSI
- 支持单机验证与双机拆分部署
- 支持按业务维度分桶（bucket）计算
- 对结果执行阈值发布、频控、审计、可选鉴权签名

## 2. 关键目录与文件

顶层关键目录：
- `moduleA_psi/`：A 模块主实现
- `private-join-and-compute/`：PJC 底层工程
- `deploy/`：容器化与部署脚手架
- `benchmark/`、`data/`：数据与性能相关内容

`moduleA_psi/scripts/` 关键脚本：
- `prep_inputs.py`：数据预处理，生成协议输入与 `job_meta.json`
- `run_pipeline.sh`：端到端单入口（Prepare -> PJC -> Policy）
- `run_pjc.sh`：单机模式运行 server/client
- `run_pjc_server.sh` / `run_pjc_client.sh`：双机拆分运行
- `run_pjc_job_server.sh` / `run_pjc_job_client.sh`：基于 job 目录运行
- `run_pjc_bucketed*.sh`、`merge_bucket_results.py`：分桶执行与结果合并
- `policy_release.py`：发布策略（k 阈值、频控、审计、签名、反重放）
- `result_sink_server.py` / `push_result.py`：结果回传同步

## 3. 运行流程（代码视角）

标准链路：
1. 预处理：`prep_inputs.py`
2. 协议执行：`run_pjc*.sh`
3. 治理发布：`policy_release.py`

`run_pipeline.sh` 支持关键参数：
- 时间窗：`--start-ts` / `--end-ts`
- 统计模式：`--value-mode count|amount`
- 分桶：`--bucket-field` + 并行参数
- 发布策略：`--k`（阈值）、`--n`（频控）、`--caller`

## 4. 输入输出契约

典型 job 目录：
```
runs/<job_id>/
  server.csv
  client.csv
  job_meta.json
  attribution_result.json
  public_report.json
  audit_log.jsonl
```

语义说明：
- `attribution_result.json`：PJC 原始结果（如交集规模/求和）
- `public_report.json`：策略治理后可对外结果
- `audit_log.jsonl`：调用审计轨迹

## 5. 分支集成价值

合并到统一软件时，`a-psi` 可以提供：
- 归因任务的离线/批处理执行能力
- 可治理、可审计、可频控的发布层
- 与网关或客户端联动时的标准 job 文件边界

建议客户端集成方式：
- 以“任务编排器”形式驱动 A 模块，而不是把 A 的逻辑重写进客户端
- 客户端负责参数收集、状态跟踪、结果展示、审计追踪
- 将 A 的“结果发布”能力暴露为用户可配置策略

## 6. 当前局限与注意事项

- 依赖 PJC 二进制与运行环境配置（Bazel 或预编译分发）
- 协议结果默认在 client 侧产出，需要额外结果同步机制
- bucket 并行参数（端口、并发）需要客户端做冲突检查与提示
