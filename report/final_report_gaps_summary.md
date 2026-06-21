# 结题报告不足与遗漏总结

基于以下材料交叉阅读整理：

- `report/seccomp_privacy_platform_report.tex`
- `docs/CURRENT_SECURITY_AND_COMPLETION_AUDIT.md`
- `docs/PRODUCTION_SECURITY_COMPLETION_PLAN.md`
- `docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md`
- `docs/ONLINE_OFFLINE_SECURITY_GOVERNANCE.md`
- `docs/PJC_MTLS_OPEN_RISKS.md`
- `docs/BENCHMARK_PLAN.md`
- `docs/CODE_REVIEW_05_SCRIPTS_PIPELINE.md`
- `docs/CODE_REVIEW_12_REPLAY_AND_BENCHMARKS.md`
- `docs/ATTACKER_REVIEWER_TODO.md`
- `docs/PLATFORM_LEVEL_REMAINING_ESTIMATE.md`

本文不评价代码实现本身是否“差”，只总结**结题报告作为文档材料**仍然存在的不足、遗漏、过时口径和需要补写的部分。

## 总体判断

当前结题报告已经能覆盖“比赛版平台基线”的主链路、模块划分和基本测试证据，但它仍然存在三个明显问题：

1. **限制写得太薄。**
   `6.4 残余风险` 和 `10.2 不足与限制` 只覆盖了少数风险点，远不足以反映当前仓库真实的安全边界、协议边界和部署边界。
2. **若按当前仓库状态答辩，部分口径已经过时。**
   报告里对 duplicate-query、防差分、PJC tamper resistance、双机 mTLS、release gate 等的描述明显落后于当前 `docs/` 中的 authoritative 状态。
3. **repo-side 能力、operator-side 能力、production-certified 能力没有被系统区分。**
   这是最容易被老师或评委追问击穿的点。

## 一、报告已有但明显不足或过时的部分

### 1. `6.4 残余风险` 写得过于简化

当前报告的残余风险只列了 6 条，且多条表述已经不够准确。

主要问题：

1. “duplicate-query 主要覆盖 exact duplicate” 这一口径已经过时。
   当前仓库的 repo-side 能力已经扩展到 overlap、near-duplicate、close-window disjoint query、threshold-round probe、cross-bucket bucket-probe，并且已有 approval flow、transactional budget store、operator API 和 browser-console queue。报告若仍只写“exact duplicate”，会低估现状；但同时也没有补上“live PostgreSQL/HA evidence、deployed browser evidence、joint certification 仍未完成”的新限制。
2. “secret refs 仍依赖环境变量” 这一口径也过于粗糙。
   现在更准确的说法应该是：**本地原型仍可能使用 env-backed secret refs，但 repo-side 已具备 Vault/OpenFGA/cloud-KMS shaped adapters 和生产闸门；真实 authority/KMS lifecycle 仍依赖 operator 环境**。
3. “当前不是完整生产级多租户平台” 虽然对，但太泛。
   它没有拆开说明到底缺的是：
   - malicious-secure protocol
   - enterprise trust root
   - live HA/SRE evidence
   - deployed browser/OIDC/reverse-proxy trust chain
   - public two-host network identity evidence

### 2. `10.2 不足与限制` 只有 5 条，严重不足

目前 `10.2` 只写了：

1. 不是完整生产级多租户平台
2. 外部 Keycloak/OpenFGA/Vault/AWS KMS live 验证依赖 operator 环境
3. PJC 1M streaming 后续仍受 CPU/RSS/full-set buffering 限制
4. 电商事实层只是窄口径基线
5. duplicate-query deny 仍需扩展

这 5 条无法支撑完整结题答辩，至少遗漏了以下大类限制：

1. 协议对手模型仍然只是 `semi-honest/operator-controlled`
2. source truthfulness 仍属于 protocol-external governance，不是 malicious-secure
3. 双机 mTLS 的 repo-side control-plane 已完成，但真实公网/两机 live evidence 仍是独立欠账
4. release legitimacy、dual signoff、external immutable anchor 的生产信任根仍依赖 operator/enterprise
5. PJC resource isolation、timeout/cancel/worker supervision、streaming binary freshness 仍未做成 live production evidence
6. metadata leakage 控制虽然 repo-side 收口较多，但高敏 padding/延迟发布/自动 bucket merge 仍未完成
7. browser session / secure cookie / deployed OIDC / reverse-proxy 仍需要真实部署证据
8. malicious participant 可以提供“语义上假但结构上合法”的输入，当前系统不能从密码学上证明其真实性

### 3. 测试章节没有明确区分“本地/合成证据”和“真实部署证据”

报告第 7 章列出了很多脚本和产物，但没有系统区分：

1. 只在本机或 synthetic fixture 上通过的 repo-side smoke
2. 需要 operator 账号、VPS、AWS/Rekor、真实 PostgreSQL/HA、真实 OIDC 的 live evidence

这会导致读者误以为“脚本存在 = 部署闭环完成”。

### 4. 日期和状态快照口径不稳定

报告使用 `\today`，但正文中的限制和能力明显来自不同时间点，且没有声明“本报告状态快照基于哪一天的 authoritative audit”。  
建议冻结一个明确日期，并把 `CURRENT_SECURITY_AND_COMPLETION_AUDIT.md` 作为状态源引用，否则同一份报告会出现“日期是今天，但内容是旧状态”的问题。

## 二、报告完全缺失但当前必须补写的主题

### 1. 协议声明边界没有写透

这是整份报告目前最重要的遗漏。

必须补写的核心口径：

1. 当前 Google PJC 的安全边界只能表述为 **`semi-honest/operator-controlled`**。
2. 现在新增的 source attestation、release governance、signed evidence merge、external anchor 都是 **protocol-external governance**。
3. 这些治理能力**不会**把系统升级成 malicious-secure PSI-SUM。
4. 当前系统可以证明很多“篡改/替换/越权发布会被发现或被 gate 拒绝”，但**不能证明参与方提供的源数据一定真实**。

如果不把这一层写明，老师一问“你们是不是已经抗恶意参与方了”，报告现有文本很难稳住。

### 2. Source truthfulness / release legitimacy 完全没有形成专门叙述

当前仓库已经有一整套 source-attestation / release-governance 体系，但报告几乎没有展开。这是明显遗漏。

至少应该补写：

1. `source_export_manifest/v1`
2. `source_attestation/v1`
3. `source_truthfulness_report/v1`
4. `release_governance_report/v1`
5. dual signoff / same-identity dual-signoff deny
6. source snapshot、bridge inputs、input commitment、release decision 的绑定关系

否则报告会让人误以为“输入真实性”只靠 export policy 和审计链，而不是一套更完整的治理证据链。

### 3. 双机 PJC 控制面现状没有写

报告把 S7 只写成“未来任务”，这已经不符合当前仓库状态。

当前更准确的表述应该是：

1. 双机 PJC 的 repo-side control-plane contract 已经实现：
   - secure invite
   - CSR enrollment
   - preflight
   - role package export/import
   - role lifecycle
   - evidence verify-merge
   - negative cases
2. guided wizard、TLS diagnostic、SPIFFE/Envoy templates 已 repo-side 完成
3. **真正缺的是两台真实机器/公网/管理面/证书链的 live evidence**

也就是说，这部分不是“没做”，而是“repo-side done, operator-side evidence still required”。报告现在没有把这个区别写出来。

### 4. External immutable audit anchor 没有写成独立限制项

报告虽然提到 audit chain / seal / archive / tamper resistance，但没有充分说明：

1. 本地 append-only ledger 不是最终的 immutable trust root
2. 严格生产 release gate 现在已经能要求 uploaded external anchor report
3. 真实 S3 Object Lock / Rekor 上传、read-back、凭证和保留策略仍是 operator-side 任务

如果只写“审计链可 seal/verify”，读者会以为已经解决了不可抵赖性，这不准确。

### 5. Metadata leakage / caller-safe view 收口没有写

报告写了 public report redaction 的方向，但没有系统说明当前 repo-side 已完成的 caller-safe read surface，包括：

1. `audit_chain_public_summary/v1`
2. `pipeline_observability_public_summary/v1`
3. `catalog_lineage_public_summary/v1`
4. `operator_dashboard_public_summary/v1`
5. `caller_safe_metadata_summary`
6. `bucket_public_report/v1` 与 `operator_bucket_report/v1` 分离
7. console route-level public-summary guard

同时也没有写清楚剩余限制：

1. 高敏场景的 padding
2. delayed release
3. automatic bucket merge
4. HTTPS/Secure-cookie 部署证据

这导致报告在“信息泄漏面控制”上明显缺块。

### 6. Business field-level access control 没有展开

如果结题报告要强调“电商业务场景”，那当前报告对业务字段访问控制写得太浅。

仓库里已经存在的 repo-side 能力包括：

1. `business_access_policy/v1`
2. merchant/courier/customer_service/buyer/compliance 等角色策略
3. policy-gated read preview
4. deny/mask/allow 三态
5. validator-first fact import

这些内容没有被写进报告，会让“电商场景落地”显得更像叙事而不是带字段级控制的业务化适配。

### 7. Browser trust chain / deployed OIDC / identity proxy 现状没有写

报告提到 operator console / query workflow / metadata API，但没有说明：

1. repo-side same-origin browser session 已做成 HttpOnly/SameSite cookie path
2. identity proxy auth-configured 时 fail-closed
3. CSP/security-header gate 已 repo-side 完成
4. 真实 HTTPS、Secure cookie、reverse proxy、OIDC client registration、deployed browser evidence 仍是 operator-side

这部分如果不写，控制台相关能力很容易被理解成“浏览器侧已经生产安全”。

## 三、协议与安全边界方面的具体不足

### 1. 没有把“协议内部安全”和“协议外部治理”分开

这会带来两类风险：

1. 高估当前系统的密码学保证
2. 低估当前系统已经完成的治理链闭环

建议在报告里明确分为：

1. **Protocol-internal**：
   - active-secure / malicious-secure backend
   - proof-carrying computation
   - range/value/source proofs
2. **Protocol-external**：
   - source attestation
   - dual signoff
   - release gate
   - external anchor
   - audit accountability

### 2. 没有充分说明 malicious participant 还能做什么

报告应该明确写出当前仍未解决的三类行为：

1. 提供语义上虚假的源数据但结构合法
2. selective abort / bucket-shard manipulation / misleading evidence
3. 尝试将错误业务结论包装成“合法运行结果”

否则“残余风险”部分仍然停留在“文件落盘、密钥、exact duplicate”这一层，不够深。

### 3. 对 value truthfulness 的说明不够

当前仓库已经有：

1. input commitment
2. value policy
3. allowed value field / unit / currency
4. range-bound preflight deny

但报告只从“client value 是金额聚合字段”这种功能角度描述，没有明确写出：

1. 当前只是 software policy validation
2. 不是 cryptographic range proof
3. 也不能证明源系统金额填写真实

### 4. 没有把 PJC 资源隔离/DoS 写成独立安全主题

当前文档体系已经把这件事提升为 P0/P1 级问题，但报告中几乎没有展开。

至少应补写：

1. `PJC_PRODUCTION_MODE=1`
2. resource limits 必填
3. legacy unary fallback fail-closed
4. stale `bazel-bin` binary freshness gate
5. timeout/cancel/worker supervision 仍未形成 live evidence

## 四、性能与 benchmark 分析方面的不足

### 1. benchmark 覆盖面写得不全

报告当前 benchmark 小节主要列了：

1. sse export
2. record recovery
3. bridge
4. pipeline
5. pjc
6. live sse demo
7. read adapters
8. platform health

但遗漏了当前仓库已经存在或已计划纳入证据体系的 benchmark 面：

1. query workflow benchmark
2. audit bundle benchmark
3. derived views benchmark
4. dashboard jobs benchmark
5. mTLS overhead benchmark
6. backend comparison / SQLite vs PostgreSQL comparison

如果不补写，会让性能章节显得只关注主链路，不关注 control-plane / read-side / console / mTLS 的工程代价。

### 2. 缺少实验方法说明

当前报告给了代表性结果，但缺少完整的实验设计说明：

1. 机器配置
2. CPU / RAM / disk / OS / compiler / Bazel/Cargo/npm 版本
3. warm/cold run 区分
4. iterations 数量
5. p50 / p95 / mean / max 统计方式
6. whether synthetic fixture or live run
7. transport mode
8. chunk size
9. concurrency level

这会降低 benchmark 的可重复性和说服力。

### 3. 缺少“成功结果”和“失败上限”并列分析

报告提到了 1M streaming 成功，但没有系统补写以下边界：

1. unary path 的历史 ceiling 和失败原因
2. full-set buffering 导致的 CPU/RSS 瓶颈
3. 为什么 1M 以后需要 sharding / resource isolation / worker service
4. current success 只是 repo-side evidence，不等于 production elasticity

### 4. 缺少 mode-to-mode tradeoff 分析

报告应该至少对以下模式做一次定性比较：

1. file handoff
2. file retained
3. fifo handoff
4. loopback/local
5. two-host mTLS

目前报告有命令和少量结果，但缺少“安全性 vs 性能 vs 可运维性”的对比说明。

### 5. 缺少控制面性能与运维代价分析

当前报告基本没有分析：

1. metadata read adapters
2. query workflow dry-run / execute wrapper
3. dashboard jobs 并发能力
4. mTLS connection overhead
5. audit bundle verify/archive cost
6. derived views / observability build cost

如果结题想突出“平台化”而不是“单次 demo”，这些都是应该出现的。

## 五、测试、证据与验收方面的不足

### 1. 安全测试列举不完整

报告当前只重点写了：

1. malformed input gate
2. audit tamper resistance

但从当前仓库看，还应至少补充或在附录中索引：

1. privacy budget concurrency / approval flow
2. release policy gate smoke
3. PJC input commitment negative cases
4. public two-party smoke
5. TLS diagnostic / readiness smoke
6. console browser session / identity proxy auth smoke
7. console security headers check
8. business access API smoke
9. production handoff gate
10. production KMS gate

否则读者会以为“安全测试”只做了 HTTP malformed input 和本地 audit tamper。

### 2. 没有给出“模块状态表”

报告应至少增加一个表，将关键模块按以下状态拆开：

1. Completed
2. Repo-side complete
3. Operator-side required
4. Planned

没有这个表，就很难避免答辩时把“代码有了”和“生产可信地跑过了”混成一件事。

### 3. 没有明确列出“哪些证据是 live，哪些是 synthetic”

尤其对 benchmark 和 two-party control-plane，这一点非常重要。  
建议每条证据都标注：

1. local synthetic
2. local live
3. two-host live
4. operator-side skipped

### 4. 没有把三人联合认证从“组织流程”写成“验收约束”

报告提到三人协作和 joint certification，但没有把它提升为“某些能力未联合认证前不能写 Completed”的结题规则。

这在当前文档体系里是明确要求，报告里应该同步。

## 六、部署、运维与生产化方面的不足

### 1. 没有明确的目标部署拓扑

当前报告更多是模块图，而不是生产拓扑图。

至少应该补一张“目标生产路径”图，说明：

1. controlled network
2. SPIFFE/SPIRE
3. Envoy/service mesh
4. loopback-bound PJC binary
5. external immutable anchor
6. real identity/KMS/authority

否则读者只能看到本地 pipeline，看不到真正的 target architecture。

### 2. 对 operator-side 任务写得不够细

报告提到了外部 Keycloak/OpenFGA/Vault/AWS KMS 依赖 operator 环境，但没拆开到底需要什么：

1. 凭证
2. rotation
3. revoke
4. drift detection
5. break-glass
6. live failover drill
7. browser deployment evidence
8. WORM/Rekor execute + read-back

### 3. HA / backup / restore / SRE drill 没有进入“限制”部分

当前仓库已经有大量 related repo-side scaffolds，但报告没有明确指出：

1. real PostgreSQL HA / Patroni / pgBouncer / failover 仍需 operator evidence
2. backup/restore 的生产级闭环不是单机 smoke 就算完成
3. alerting / observability / chaos drill 与主链路 correctness 是不同维度的完成度

### 4. 没有突出“public network readiness”仍然是独立问题

双机 PJC 不只是“协议逻辑存在”，还包括：

1. management plane exposure
2. peer identity
3. public port behavior
4. TLS EOF diagnostics
5. clean-room evidence archive

这些都应该在结题报告中作为部署侧不足单列。

## 七、报告口径与表述上的风险点

### 1. 容易让人误解成“生产安全已完成”

风险表述主要出现在这些位置：

1. “工程证据链已经具备”
2. “系统不仅能算出结果，也能解释结果如何产生”
3. “平台化 sidecar 已建设完成”

这些话本身没有错，但如果不加限定，容易被理解成 production trust root 已经具备。  
建议统一改成：

1. repo-side evidence chain complete
2. verifier-facing artifact complete
3. live/operator trust root still required

### 2. “创新性”章节容易写成能力宣称而不是范围宣称

例如：

1. 恢复服务边界工程化
2. 审计链与防篡改验证
3. 平台化 sidecar

这些都应该在段尾加一句：

> 以上为 repo-side 或 baseline 能力，不等于 malicious-secure protocol 或 enterprise-grade deployment closure。

### 3. 参考文献和状态来源不够权威化

当前参考文献没有把最关键的状态源明确列为“authoritative status source”。  
建议至少显式加入或强调：

1. `docs/CURRENT_SECURITY_AND_COMPLETION_AUDIT.md`
2. `docs/ONLINE_OFFLINE_SECURITY_GOVERNANCE.md`
3. `docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md`
4. `docs/PJC_MTLS_OPEN_RISKS.md`

## 八、建议在结题报告中新增的章节或小节

建议最少新增以下内容：

1. **状态词汇表**
   - Completed
   - Repo-side complete
   - Operator-side required
   - Planned
2. **协议声明边界**
   - semi-honest/operator-controlled
   - protocol-internal vs protocol-external
3. **source truthfulness 与 release governance**
4. **双机 PJC control-plane 与 live evidence gap**
5. **PJC resource isolation / DoS / streaming fail-closed**
6. **external immutable anchor 与 release legitimacy**
7. **caller-safe metadata/audit/dashboard read surface**
8. **expanded benchmark methodology**
9. **operator-side remaining work matrix**

## 九、建议的最小改稿清单

如果只做最小修改，建议至少完成下面 12 项：

1. 重写 `6.4 残余风险`
2. 重写 `10.2 不足与限制`
3. 新增“协议安全声明边界”小节
4. 新增“source truthfulness / release governance”小节
5. 新增“repo-side vs operator-side”状态表
6. 新增“双机 PJC 现状与剩余 gap”小节
7. 新增“external anchor / immutable audit”小节
8. 在 benchmark 章节补上 query workflow、dashboard jobs、mTLS overhead、audit bundle
9. 在测试章节补上 privacy budget、release gate、two-party smoke、commitment negative cases
10. 在部署章节补上 target production topology
11. 明确 current report snapshot date 和 authoritative status source
12. 在总结中明确：当前完成的是“比赛版平台基线 + 大量 repo-side governance 收口”，不是“malicious-secure + enterprise trust-root complete”

## 十、结论

这份结题报告的主要问题，不是主链路没写，而是**限制、边界和状态分层写得不够**。

如果按当前版本直接用于答辩，最容易被追问击穿的点有四个：

1. 你们现在到底是不是 malicious-secure
2. 双机 mTLS 到底是“做完了”还是“只做了本地 wrapper”
3. 外部审计锚定和 authority/KMS 到底有没有真实跑过
4. 你们说的“平台化完成”到底是 repo-side complete 还是 production complete

只要把这四组问题用上面的方法补写清楚，整份报告的可信度会明显提升。
