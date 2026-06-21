# 公网双机 PJC 控制台操作手册

## 1. 文档目的

本文描述如何在两台真实机器之间，通过 `/pjc-two-party` 控制台完成一次可审计的 PJC 联合计算，包括：

- Party A / Party B 的真实登录会话
- mTLS bootstrap 与证书下发
- preflight 校验
- server / client 角色启动
- signed manifest、evidence merge、release gate
- 前端结果汇总与工件查看

本文适用于以下场景：

- Party A 位于远端 VPS 或受控机房节点
- Party B 位于本地笔记本、办公机或另一台受控服务器
- 双方通过公网互联
- 双方不希望把原始输入集中到同一台机器

## 2. 推荐拓扑

推荐把职责固定下来：

- Party A：远端节点，负责 `server` 角色与 invite 生成
- Party B：本地节点，负责 `client` 角色与最终结果接收

一个已经验证过的示例拓扑是：

- Party A 面板：`http://100.101.31.53:18096/pjc-two-party`
- Party B 面板：`http://127.0.0.1:18097/pjc-two-party`
- 数据面 TLS 端口：`10596`

你可以替换成自己的地址，但建议继续保持：

- 远端面板负责 Party A
- 本地面板负责 Party B
- `dashboard port` 与当前面板实际端口一致
- `dataplane port` 由双方共享

## 3. 为什么要这样做

### 3.1 为什么不用单机

单机模式适合 smoke / benchmark，但不适合真实协作，因为它会把：

- 双方输入准备
- 协议执行
- 结果发布

都收敛到一台机器上。这样会削弱真实边界，也不利于证明“双方原始数据没有被集中处理”。

### 3.2 为什么 Party A 远端、Party B 本地

推荐职责分配如下：

- Party A 远端负责 `server`
- Party B 本地负责 `client`

原因是：

- PJC 的最终结果天然先落在 `client` 侧
- Party A 更像“提供服务、等待连接”的一方
- Party B 更像“发起计算、接收结果”的一方
- 控制台与本机文件系统绑定后，运维动作更直观

### 3.3 为什么要走真实鉴权会话

`/pjc-two-party` 不是离线 demo 页面，而是实际 operator console 的一部分。通过真实登录会话操作有两个价值：

- 所有操作都绑定到当前 operator 身份，而不是匿名调用
- 页面和后端的行为与正式控制面一致，调试结果更接近真实环境

### 3.4 为什么还要有 signed manifest、evidence merge、release gate

PJC 只解决“如何在不交换原始数据的前提下完成联合计算”，但不自动解决：

- 双方是不是跑了同一组输入承诺
- 结果有没有被单边替换
- 公开结果是否满足隐私 / 预算 / 发布策略

因此还需要：

- signed manifest：把结果 hash、public_report hash、audit_chain hash、输入承诺、TLS 身份绑定起来
- evidence merge：校验双方证据是否一致
- release gate：在结果对外发布前再做一次 fail-closed 的策略检查

## 4. 前置条件

开始前，双方至少要准备好以下内容。

### 4.1 Party A / Party B 各自本地文件

- Party A：`server.csv`、`job_meta.json`、`input_commitments.json`
- Party B：`client.csv`、`job_meta.json`、`input_commitments.json`
- 如为 bucketed 任务：双方都应有 `bucket_*/` 目录

控制台默认示例目录是：

- Party A role_dir：`tmp/pjc_bucketed_scale_cross-vps-008_cleanrun/party_a_job`
- Party B role_dir：`tmp/pjc_bucketed_scale_cross-vps-008_cleanrun/party_b_job`

### 4.2 双边二进制与 helper

- `a-psi/private-join-and-compute/bazel-bin`
- `a-psi/moduleA_psi/scripts/run_pjc_bucketed_tls_client.sh`

### 4.3 网络与端口

- Party B 必须能访问 Party A 的 `dataplane port`
- Party B 必须能访问 Party A 的 enrollment URL
- 如果使用公网，建议先通过受控 ACL、VPN、专线或其他受控网络方式限制来源

## 5. 控制台完整操作流程

以下步骤默认双方都已经打开 `/pjc-two-party` 页面，并完成登录。

### 5.1 Step 0：共享上下文

双方先确认以下字段一致或符合职责分工：

- `job_id`
- `server_host`
- `dashboard port`
- `dataplane port`
- `cert_dir`
- `Party A role_dir`
- `Party B role_dir`

建议：

- `server_host` 填 Party A 的可达地址
- `dashboard port` 填当前 Party A 面板的真实端口
- `dataplane port` 两边完全一致

### 5.2 Step 1：Party A generate invite

在远端 Party A 面板：

1. 确认 `dashboard port` 是当前面板端口
2. 点击 `生成 invite`
3. 检查 `bootstrap_uri`

必须确认：

- `bootstrap_uri` 指向的 enrollment URL 是活着的入口
- 例如：`http://100.101.31.53:18096/v1/pjc-mtls/enroll`

如果这里还是旧端口，Party B 后续会直接 enroll 失败。

### 5.3 Step 2：Party B enroll

在本地 Party B 面板：

1. 粘贴 Party A 生成的 `bootstrap_uri`
2. 点击 `执行 enroll`

这一阶段的安全点是：

- Party B 本地生成 `client.key`
- 只把 CSR 发给 Party A
- pairing token 控制 enrollment 授权范围与有效期

### 5.4 Step 3：双边 preflight

依次执行：

- `跑 Party A preflight`
- `跑 Party B preflight`

preflight 会在真正启动角色前先拦住常见配置错误，包括：

- commit 不一致
- helper / binary 不可用
- 端口不可达
- TLS 身份不匹配
- 输入承诺不一致

这是“先 fail closed，再启动数据面”的关键步骤。

### 5.5 Step 4：role package export / import

建议把双方 role 目录都导出并导入对端验证：

- Party A package -> Party B import
- Party B package -> Party A import

这一步的价值不是传结果，而是确认双方对“将要运行的角色工件”理解一致。

### 5.6 Step 5：启动 server / client

先在 Party A 页面点击：

- `启动 server`

再在 Party B 页面点击：

- `启动 client`

然后分别刷新状态，确认：

- role state
- pid
- log_path

如果是 bucketed 任务，结果通常会先出现在 Party B 的：

- `bucket_*/attribution_result.json`

而不是单个 merged 文件。

### 5.7 Step 6：signed manifest + evidence merge + release gate

运行顺序建议如下：

1. `签 Party A manifest`
2. `签 Party B manifest`
3. `evidence merge`
4. `release gate`

其中：

- signed manifest 绑定输入承诺、结果 hash、public_report hash、audit_chain hash、TLS 身份
- evidence merge 检查双方证据是否一致
- release gate 决定结果是否允许进入发布态

### 5.8 结果查看

现在 `/pjc-two-party` 页面新增了 `结果汇总 / 公网工件` 区域。

点击：

- `刷新结果汇总`

页面会自动汇总：

- Party B `bucket_*/attribution_result.json`
- 顶层 `attribution_result.json`（如果存在）
- `public_report.json`
- `audit_chain.json`
- signed manifest
- `evidence merge`
- `release gate`

当没有 merged `attribution_result.json` 时，页面会自动从 bucket 结果聚合出：

- `bucket_count`
- `intersection_size_total`
- `intersection_sum_total`

这正是公网双机 bucketed 运行最常见的真实布局。

## 6. 为什么这种流程是安全的

### 6.1 原始输入没有被集中到一台机器

双方只在各自机器上持有本方输入文件：

- Party A 持有 `server.csv`
- Party B 持有 `client.csv`

PJC 过程中交换的是协议消息，不是原始明文输入。

### 6.2 数据面不是裸 TCP，而是 mTLS

数据面连接前已经完成：

- CSR-only enrollment
- CA fingerprint 校验
- peer identity 校验

因此不是“连上端口就信任”，而是“证书、身份、来源都对才放行”。

### 6.3 pairing token 缩小了 enroll 攻击面

Party A 不会无条件给任何来访者签发证书。Party B 只有拿到正确 bootstrap URI 与 pairing token，才能完成 enroll。

这让证书下发过程具备：

- 限时
- 限次
- 可审计

### 6.4 preflight 把错误挡在计算前

如果 commit、输入承诺、端口、TLS 身份、helper 或 binary 不对，系统会在真正启动角色前直接拒绝。

这比“先跑起来再看日志”更安全，也更容易定位问题。

### 6.5 signed manifest + evidence merge 防止单边替换结果

即使某一方声称“我已经跑完了”，另一方也不能只靠口头相信。

必须验证：

- 双方签名是否有效
- 双方的结果 hash 是否一致
- 双方记录的 peer commitment 是否交叉匹配
- 双方的策略范围 hash 是否一致

如果这些不一致，`evidence merge` 就会 fail closed。

### 6.6 release gate 把“可计算”与“可发布”分开

PJC 算出来，不代表结果就一定能公开或下游消费。

`release gate` 负责继续检查：

- public_report 是否匹配
- 预算账本是否允许
- 策略配置是否允许
- 证据 merge 是否与发布结果绑定

这一步让“协议正确”与“治理允许”成为两个独立关口。

## 7. 好处是什么

### 7.1 更接近真实生产边界

这套流程保留了真实世界最重要的两个前提：

- 双方输入分属不同机器
- 控制面与数据面都有明确身份与证据

### 7.2 更容易定位问题

出问题时，不再只有一份大日志，而是能区分：

- enroll 失败
- preflight 拒绝
- role 启动失败
- TLS 身份不匹配
- evidence merge 失败
- release gate 拒绝

### 7.3 更容易对外解释“为什么安全”

相比“我们在一台机器上跑过 demo”，这套流程能更明确地回答：

- 为什么原始数据没有集中
- 为什么网络连接不是裸连
- 为什么结果不能被单边替换
- 为什么发布前还有最后一道策略门

### 7.4 结果查看更贴近真实工件

现在前端结果区直接展示真实产物，而不是只提示你去命令行看文件。它会汇总：

- bucket 结果
- public_report
- audit_chain
- signed manifest
- merge / gate 报告

这对联调、演示、审计复核都更直接。

## 8. 推荐的最小操作顺序

如果只记最小顺序，记下面这 8 步：

1. Party A 登录并生成 invite
2. Party B enroll
3. 双边 preflight
4. Party A 启动 server
5. Party B 启动 client
6. 双边签 manifest
7. evidence merge + release gate
8. 点击 `刷新结果汇总`

## 9. 对应页面与代码

- 控制台页面：`console/src/routes/pjc-two-party.tsx`
- Operator 结果摘要接口：`POST /v1/pjc/two-party/result-summary`
- 后端实现：`scripts/serve_operator_dashboard.py`

如果你要把这套流程对外演示，建议直接以 `/pjc-two-party` 页面为主界面，再用本手册解释：

- 为什么是双机
- 为什么要有 mTLS
- 为什么需要 evidence merge / release gate
- 为什么现在前端结果区能直接说明这次运行是否真的可信
