# PJC 双机拆分与部署方案说明

## 1. 背景

本项目基于 Google `private-join-and-compute` 开源库实现广告平台与电商平台之间的隐私保护归因。当前仓库中的单机执行脚本 [run_pjc.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc.sh) 适合本地验证，但不符合真实业务场景，因为真实场景中：

- 广告平台与电商平台通常位于两台不同机器或两个不同受控环境中
- 双方各自持有本方用户数据，不应将原始数据集中到同一台机器
- 双方希望在不泄露原始用户标识的前提下完成转化归因或交集统计

因此，需要将协议执行层拆分为双机部署模式：

- 广告平台机器运行 `server`
- 电商平台机器运行 `client`

本仓库已新增以下双机入口脚本：

- [run_pjc_server.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_server.sh)
- [run_pjc_client.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_client.sh)
- [run_pjc_bucketed_server.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_bucketed_server.sh)
- [run_pjc_bucketed_client.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_bucketed_client.sh)
- [result_sink_server.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/result_sink_server.py)
- [push_result.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/push_result.py)

## 2. 当前代码现状

### 2.0 推荐的职责分层

对于双机协作场景，不建议继续沿用“单机总控 pipeline”作为正式入口。更清晰的做法是将代码分为三层：

- 数据准备层：负责把原始业务数据整理为 `server.csv` / `client.csv`
- 协议执行层：负责双机运行 PJC `server` / `client`
- 结果治理层：负责结果同步、审计、阈值、频控和后续发布

在这一分层下：

- 单机旧 pipeline 继续保留，用于实验和本地验证
- 双机正式流程应以“双方已经准备好 CSV”为前提
- 不应让某一台机器继续承担两边数据准备、协议执行和结果发布的全部职责

### 2.1 单机执行逻辑

[run_pjc.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc.sh) 的行为是：

- 在本机启动 `server`
- 等待本机端口就绪
- 在本机启动 `client`
- 从 `client.log` 中提取 `intersection_size` 和 `intersection_sum`
- 在同一输出目录中生成 `attribution_result.json`

该脚本适合单机测试，但不适合双机部署。

### 2.2 已新增的双机脚本

[run_pjc_server.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_server.sh) 只负责：

- 读取 `SERVER_CSV`
- 启动 PJC `server`
- 监听 `SERVER_ADDR`
- 将服务端日志写入 `OUT_DIR/server.log`

[run_pjc_client.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_client.sh) 只负责：

- 读取 `CLIENT_CSV`
- 连接远端 `SERVER_ADDR`
- 执行 PJC `client`
- 从 `client.log` 提取结果
- 在 `OUT_DIR/attribution_result.json` 生成结果文件

### 2.3 更适合正式双机流程的入口

如果双方已经各自整理好了 CSV，更推荐使用“作业初始化 + 双机执行”的模式，而不是重新写一份新的单机 pipeline。

本仓库已新增：

- [init_pjc_job.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/init_pjc_job.py)
- [run_pjc_job_server.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_job_server.sh)
- [run_pjc_job_client.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_job_client.sh)

它的职责是：

- 从已经准备好的 `server.csv` / `client.csv` 初始化一个标准 job 目录
- 为双机执行生成最小 `job_meta.json`
- 支持单桶 job
- 支持通过 bucket manifest 初始化分桶 job

推荐原因如下：

- 更符合“两台机器分别持有本方输入”的真实场景
- 不要求双方共享原始业务数据
- 不把双机问题错误地包装成“再写一份新的单机 pipeline”
- 更适合小规模联调，再逐步扩展到大数据量

## 3. 推荐的角色分配

建议采用：

- 广告平台作为 `server`
- 电商平台作为 `client`

原因如下：

- 该开源库的结果默认输出在 `client` 侧
- 电商平台通常更需要获得最终转化结果用于分析、核算、报表或内部查询
- 广告平台以 `server` 身份提供协议服务更符合“暴露服务、等待连接”的部署方式

## 4. 双机执行的最小方案

### 4.0 推荐的标准流程

双机正式流程建议采用以下顺序：

1. 双方各自整理本方 CSV
2. 使用 [init_pjc_job.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/init_pjc_job.py) 初始化标准 job 目录
3. 服务端机器运行 [run_pjc_server.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_server.sh)
4. 客户端机器运行 [run_pjc_client.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_client.sh)
5. 如有需要，由客户端通过回调或共享目录同步结果

这个流程的重点是：

- 双方先准备好各自 CSV
- 再进入协议执行阶段
- 不再把原始 TSV 预处理、协议执行、结果发布混成一个单机入口

其中更推荐的执行入口是：

- 服务端：[run_pjc_job_server.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_job_server.sh)
- 客户端：[run_pjc_job_client.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_job_client.sh)

它们会根据 `job_meta.json` 自动判断当前 job 是单桶还是分桶。

### 4.0.1 单桶 job 初始化示例

当双方已经准备好 CSV 时，可以先初始化 job：

```bash
python3 moduleA_psi/scripts/init_pjc_job.py \
  --out runs/job_csv_ready \
  --server-csv /path/to/server.csv \
  --client-csv /path/to/client.csv
```

这会生成：

- `runs/job_csv_ready/server.csv`
- `runs/job_csv_ready/client.csv`
- `runs/job_csv_ready/job_meta.json`

初始化后，建议直接按 job 目录执行。

服务端机器：

```bash
export SERVER_ADDR=0.0.0.0:10501
bash moduleA_psi/scripts/run_pjc_job_server.sh runs/job_csv_ready
```

客户端机器：

```bash
export SERVER_ADDR=<server_ip>:10501
bash moduleA_psi/scripts/run_pjc_job_client.sh runs/job_csv_ready
```

### 4.0.2 分桶 job 初始化示例

如果双方已经按桶准备好了 CSV，可先写 bucket manifest，再初始化 job。

示例 manifest 见：

- [bucket_manifest.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/examples/bucket_manifest.example.json)

初始化示例：

```bash
python3 moduleA_psi/scripts/init_pjc_job.py \
  --out runs/job_bucketed_ready \
  --bucket-manifest moduleA_psi/examples/bucket_manifest.example.json
```

这会生成：

- `runs/job_bucketed_ready/job_meta.json`
- `runs/job_bucketed_ready/bucket_<field>=<value>/server.csv`
- `runs/job_bucketed_ready/bucket_<field>=<value>/client.csv`

初始化后，双方可以直接按同一个 job 目录执行：

服务端机器：

```bash
export SERVER_ADDR=0.0.0.0:10501
bash moduleA_psi/scripts/run_pjc_job_server.sh runs/job_bucketed_ready
```

客户端机器：

```bash
export SERVER_ADDR=<server_ip>:10501
bash moduleA_psi/scripts/run_pjc_job_client.sh runs/job_bucketed_ready
```

### 4.1 服务端机器

服务端机器准备：

- PJC `server` 二进制
- 本方输入文件 `server.csv`
- 启动脚本 [run_pjc_server.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_server.sh)

示例：

```bash
cd /path/to/seccomp-privacy-platform
export SERVER_CSV=/path/to/server.csv
export SERVER_ADDR=0.0.0.0:10501
export OUT_DIR=/path/to/server_job
bash moduleA_psi/scripts/run_pjc_server.sh
```

### 4.2 客户端机器

客户端机器准备：

- PJC `client` 二进制
- 本方输入文件 `client.csv`
- 启动脚本 [run_pjc_client.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_client.sh)

示例：

```bash
cd /path/to/seccomp-privacy-platform
export CLIENT_CSV=/path/to/client.csv
export SERVER_ADDR=<server_ip>:10501
export OUT_DIR=/path/to/client_job
bash moduleA_psi/scripts/run_pjc_client.sh
```

### 4.3 最小执行链路

双机执行流程如下：

1. 广告平台生成并保存 `server.csv`
2. 电商平台生成并保存 `client.csv`
3. 广告平台启动 `server`
4. 电商平台启动 `client`
5. 协议执行完成后，结果先落在电商平台的 `attribution_result.json`

## 5. 双机拆分后可能出现的问题

### 5.1 结果只在 `client` 侧可见

当前 Google PJC 默认行为是：

- `server` 参与协议
- `client` 驱动协议
- 结果输出在 `client` 侧

因此，若广告平台和电商平台都需要同样的结果，则需要增加协议外同步机制。推荐做法：

- 方案 A：`client` 执行后回调 `server` 的结果接收接口
- 方案 B：`client` 将结果写入双方共享的结果存储

不建议优先修改底层 PJC 代码以让 `server` 直接输出同样结果，因为这会增加协议实现修改风险。

本仓库已提供两种可直接使用的同步方式：

- 在 `client` 侧设置 `RESULT_CALLBACK_URL`，由 [push_result.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/push_result.py) 回调上传结果
- 在任一侧运行 [result_sink_server.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/result_sink_server.py)，作为结果接收服务

### 5.2 网络联通性问题

双机部署后，需要解决以下网络问题：

- `server` 不能再监听 `127.0.0.1`
- `client` 必须能访问 `server_ip:port`
- 两台机器之间的防火墙、内网 ACL、NAT 或容器网络必须放通

如果 `server` 仍然监听 `127.0.0.1:10501`，则远端 `client` 无法连接。

### 5.3 环境一致性问题

当前底层二进制来自 Bazel 构建，新的机器若直接从源码运行，需要：

- 安装 Bazel 或 Bazelisk
- 成功编译 `server` / `client`

如果不希望每台机器都安装 Bazel，则应考虑：

- 先编译好二进制，再分发到目标机器
- 或进一步封装为服务镜像并进行容器化部署

### 5.4 超大消息的工程风险

将 `grpc_max_message_mb` 从默认值提升到更大数值，通常不会直接削弱密码学安全性，但会带来工程层面的风险：

- 单次请求内存占用更高
- 异常大包可能导致 DoS 风险提升
- 日志、缓冲和序列化开销变大

因此，扩容通常应配合：

- 输入大小限制
- 作业分桶或分片
- 并发限制
- 身份认证与网络白名单
- 资源隔离和监控告警

### 5.5 结果治理问题

即使协议本身保护了双方原始标识，输出结果仍然可能泄露统计信息。典型风险包括：

- 交集过小时容易被推断
- 多次重复查询可能被用于差分分析
- 分桶过细可能导致单桶样本过少

这也是本项目引入 [policy_release.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/policy_release.py) 的原因。双机部署后，阈值、频控、审计不应省略。

## 6. 分桶对双机模式的影响

本仓库已有分桶和分片脚本：

- [run_pjc_bucketed.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_bucketed.sh)
- [run_pjc_sharded_parallel.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_sharded_parallel.sh)
- [merge_bucket_results.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/merge_bucket_results.py)

但是当前这些脚本的实现默认仍面向单机模式，例如：

- 每个桶默认使用 `127.0.0.1:<port>`
- 通过本地端口并发启动多个 bucket 或 shard
- 假设 `server` 和 `client` 在同一主机上完成交互

因此，不能直接将现有分桶脚本原封不动用于双机生产部署。

### 6.1 双机场景下的分桶原则

双机模式下，分桶应改为：

1. 双方约定一致的 `bucket_field`
2. 双方各自在本地按同样规则生成各桶输入
3. 对每个桶单独发起一次跨机器 PJC 执行
4. 在 `client` 侧合并所有 bucket 结果
5. 再将聚合结果同步给 `server` 或共享结果层

本仓库已新增：

- [run_pjc_bucketed_server.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_bucketed_server.sh)
- [run_pjc_bucketed_client.sh](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/run_pjc_bucketed_client.sh)

其工作方式为：

- 双方基于同一个 `job_meta.json` 顺序遍历 bucket
- `server` 端按 bucket 顺序逐个启动服务
- `client` 端按同样顺序逐个连接
- 全部 bucket 完成后由 `client` 侧调用 [merge_bucket_results.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/merge_bucket_results.py) 聚合结果

### 6.2 分桶带来的额外问题

分桶会带来新的工程问题：

- 桶数量过多时，执行耗时上升
- 桶粒度过细时，隐私风险升高
- 双方必须严格保持桶划分一致
- 多桶运行的失败恢复和重试更加复杂
- 跨机器模式下，多桶并发会增加端口和调度管理复杂度

因此，建议先完成“单桶双机跑通”，再演进到“双机分桶”。

## 7. 是否应立即容器化

不建议在“双机链路尚未验证成功”之前立刻进行容器化。

推荐顺序如下：

1. 先完成双机脚本拆分
2. 先在两台真实机器上手工跑通单桶流程
3. 明确结果回传或共享结果方案
4. 再将 `server` 和 `client` 分别服务化
5. 最后进行容器化部署

原因是：

- 若协议本身未跑通，容器化只会增加排障难度
- 只有在角色、输入、输出、网络、结果流转都清晰后，容器化才有意义

## 8. 容器化的成熟方案

对正式系统，推荐架构不是“把脚本打包成桌面软件”，而是：

- `server` 侧做成一个后端服务
- `client` 侧做成一个后端服务
- 每个服务将协议执行脚本或二进制封装在受控进程内
- 使用 Docker 或其他容器运行时部署
- 前端只面向业务人员提供任务提交、结果查询、审计查看能力

容器化的收益包括：

- 运行环境一致
- 部署和升级标准化
- 可添加 CPU/内存限制
- 更容易做日志、监控、健康检查

本仓库已新增最小运行时容器骨架：

- [server.Dockerfile](/home/llvanion/Desktop/seccomp-privacy-platform/deploy/docker/server.Dockerfile)
- [client.Dockerfile](/home/llvanion/Desktop/seccomp-privacy-platform/deploy/docker/client.Dockerfile)
- [deploy/docker/README.md](/home/llvanion/Desktop/seccomp-privacy-platform/deploy/docker/README.md)

## 9. 推荐实施顺序

建议按以下顺序推进：

1. 先用小规模 CSV 初始化单桶 job
2. 使用双机脚本完成单桶联调
3. 验证双方网络、端口、防火墙和日志链路
4. 增加结果同步，使双方都能获取同一份结果
5. 再初始化分桶 job，并验证双机分桶链路
6. 将 `client` 和 `server` 分别封装为服务
7. 最后再考虑容器化和前端集成

这里强调“小规模 CSV”是因为当前阶段的目标是先验证：

- 双机角色拆分是否正确
- job 目录结构是否稳定
- 结果同步是否可靠
- 分桶调度是否可复现

而不是一开始就追求成千上万甚至上百万条数据的压测。

## 10. 结论

本项目从单机 demo 走向真实平台合作场景时，拆分 `server` / `client` 是必要步骤。当前仓库中：

- 单机脚本适合验证功能
- 新增双机脚本适合真实双机角色拆分
- [init_pjc_job.py](/home/llvanion/Desktop/seccomp-privacy-platform/moduleA_psi/scripts/init_pjc_job.py) 更适合作为“双机正式入口”的前置步骤
- 分桶脚本目前仍偏单机实现，不能直接作为双机生产方案

从工程成熟度来看，正确路线不是“直接容器化”，而是：

- 先用小规模 CSV 初始化标准 job
- 再双机跑通
- 再补齐结果同步
- 再改造分桶执行链路
- 最后服务化和容器化

这一路线改动风险最小，也最符合电商平台与广告平台协作时对隐私、可审计性和部署稳定性的要求。
