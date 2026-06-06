# 线上+线下双管齐下的安全治理口径

Date: 2026-06-05

这份文档专门回答一个容易在答辩和审查里被问穿的问题：

> 哪些安全问题已经靠 repo-side / protocol-external governance 收口，
> 哪些必须线上实现 + 线下治理共同成立，
> 哪些最后只剩 protocol-internal / malicious-secure backend 才能解决。

它不是替代主文档，而是把 `database/control-plane + SSE + Google PJC`
这一条技术主线下的**混合型安全任务**集中整理成可直接引用的答辩口径。

## 1. 先把边界说死

本项目当前必须坚持以下表述：

1. 技术内核是 **database/control-plane + SSE + Google PJC**
2. `ecommerce` 是**关键业务适配/验证场景**，不是技术内核替代品
3. 当前 PJC 计算边界只能表述为 **`semi-honest/operator-controlled`**
4. 已新增的 source-attestation、release gate、governance archive、external
   anchor hook 都属于 **protocol-external governance**
5. 这些治理能力**不会**把 Google PJC 变成 `malicious-secure`

这里的关键区分是：

- **Protocol-internal**
  指真正改变计算对手模型的能力，例如 active-secure / malicious-secure
  backend、proof-carrying computation、range/value/source proofs。
- **Protocol-external**
  指围绕输入真实性、审批合法性、结果发布、追责性、外部审计锚点的治理层。
  它能显著收紧风险，但不改变 Google PJC 的密码学安全等级。

## 2. 如何理解“线上+线下双管齐下”

本文把控制分成两类：

1. **Repo-side / 系统内控制**
   仓库里已经实现、可以由 contract/gate/smoke 直接验证的 typed artifact、
   workflow、release gate、redaction、audit、binding。
2. **Operator-side / 线下治理控制**
   真实部署、企业账号、密钥托管、人员审批、SRE 值守、外部 WORM / OIDC /
   reverse-proxy / HA 基础设施等，必须由 operator 或 enterprise 环境提供。

很多高价值安全性质必须两边同时成立。单靠其中一边，不足以支撑生产级说法。

## 3. 权威状态如何解读

当前 authoritative 顶层状态是：

- `tmp/production_security_closure_gate/production_security_closure_gate.json`
  - `status=ok`
  - `repo_side_status=ok`
  - `live_status=ok`
  - `module_count=16`
  - `live_ok_count=16`
- `tmp/final_live_blockers_report.json`
  - `remaining_live_module_count=0`

这表示：

1. verifier-facing 顶层模块已经完成 repo-side + 已定义 live artifact 的收口
2. 这**不等于**项目已经拿到全部企业级 trust-root
3. 这**更不等于**项目已经变成 malicious-secure compute platform

正确口径是：

> 我们已经把 repo-side 可实现的 protocol-external governance 和
> verifier-facing artifact 收口做完；剩余问题只剩两类：
> 一类是 protocol-internal 的 malicious-secure / active-secure 计算问题，
> 一类是 operator / enterprise 持有的外部 trust-root 问题。

## 4. 混合任务总表

| 安全问题 | repo-side / 系统内控制 | operator-side / 线下治理控制 | 当前状态 | 剩余风险 | 答辩推荐说法 |
| --- | --- | --- | --- | --- | --- |
| source truthfulness / 输入真实性 | `source_export_manifest/v1`、`source_attestation/v1`、`source_truthfulness_report/v1`、`release_governance_report/v1`；query request / submit / worker / pipeline / release gate / audit chain 全链路透传；strict mode 可拒绝缺 attestation、manifest 缺失、manifest scope drift、hash drift、missing signoff、single-signoff、same-identity dual-signoff、planned/local/manual/stale evidence | 真实 source system 导出流程、分权审批、dual signoff、导出清单保管、异常流程、人员问责 | **Repo-side complete；operator-side required** | 参与方仍可提供“语义上假但结构上合法”的数据；如果线下流程松散，治理证据会失去约束力 | “我们已经把输入真实性问题在 repo-side 做成 typed governance 闭环，但它属于 protocol-external governance，不是 malicious-secure.” |
| release legitimacy / 发布合法性 | `release_policy_gate/v1`、`operator_request_submission/v1`、privacy-budget approval flow、same-identity self-approval deny、public/operator report binding、truthfulness-report binding、policy audit binding、dual-signoff requirement、external-anchor job binding | 真实审批名单、职责分离、变更窗口、审批留痕、法务/合规签字、事后追责 | **Repo-side complete；operator-side required** | 审批链如果在组织层面可被绕过，repo-side gate 只能证明“系统可拒绝”，不能证明“组织一定不越权” | “发布合法性已经在系统内 fail-closed，但最终合法性仍需 operator roster 与组织流程共同成立.” |
| immutable external audit anchoring | `external_audit_anchor_report/v1`、S3 Object Lock / Rekor publisher、release gate 对 anchor report 的绑定检查、audit chain / seal / archive；2026-06-06 起 release gate 还要求 anchor `records[].job_id` 绑定当前 release job | 真实 AWS Object Lock / Rekor / enterprise WORM 账号、保留策略、凭证托管、读回验证、审计保全流程 | **Repo-side complete；external trust-root required** | 本地 file ledger 或 planned report 不能充当真正 immutable trust root | “仓库已经具备外部不可变锚点接口和 gate，但真正不可抵赖的 trust root 由 operator/enterprise 基础设施提供.” |
| enterprise identity / authority / KMS lifecycle | OIDC/JWKS、identity proxy、OpenFGA / Vault / cloud KMS adapters、authority / identity / KMS evidence gates、service-token flow、metadata identity resolution | 真实 Keycloak/OpenFGA/Vault/KMS 部署，issuer/secret/role rotation，revocation，break-glass，运维托管，值班响应 | **Repo-side complete or repo-side ready；operator-side required** | 适配器存在不代表真实 authority lifecycle 已经落地 | “身份与密钥 authority 的代码接口和 verifier gate 已就位，但生产可信根仍由企业身份/KMS 平台提供.” |
| live HA / worker / SRE evidence | query workflow durable worker、lease/cancel/timeout/restart-steal、resource isolation gate、PostgreSQL HA topology renderer、chaos / failover contract、live archive schemas | 真实 Patroni/pgBouncer/PostgreSQL failover drill、worker supervision、retry policy、capacity planning、SLO / paging / oncall、灾备演练 | **Repo-side complete；live operator evidence required** | 没有真实主备切换、worker supervision、SRE runbook 执行，就不能把 repo-side durability 说成 production HA | “我们把 HA / worker / chaos 的系统内 contract 做完了，但生产级可靠性仍取决于真实 operator 环境演练.” |
| deployed browser / OIDC / reverse-proxy / secure-cookie trust chain | `console_browser_session_check/v1`、`identity_proxy_auth_smoke/v1`、`console_security_headers_check/v1`、public-summary redaction、caller-safe views、release-gate-driven job state | HTTPS/TLS termination、Secure cookie、reverse proxy、真实 OIDC client registration、deployed CSP/header policy、browser session recording、部署后验证 | **Repo-side complete；deployed trust chain required** | 本地 same-origin / HttpOnly / CSP smoke 不证明线上 reverse-proxy、cookie、OIDC 链路无误 | “浏览器侧安全边界在 repo-side 已 fail-closed，但真正上线可信链仍依赖 HTTPS / reverse-proxy / OIDC 部署与 operator 验证.” |
| cross-host PJC / network identity | TLS diagnostic、TLS readiness、signed two-party manifest/evidence merge、negative cases、public two-host readiness gate、clean materialization report | 真实两机网络、管理面、SPIFFE/SPIRE 或等价 identity、public host 运维面、真实证书与信任链 | **Repo-side complete；operator-side required** | 公网 listener、管理入口、证书生命周期、peer identity 仍需真实环境证明 | “两机协议包装和 verifier artifact 已完成，但公网网络身份与管理面可信性必须靠真实 operator 部署闭环.” |

## 5. 哪些已经靠 repo-side 收口

下面这些问题，当前可以明确说已经在**仓库能力层**收口：

1. bridge 后 CSV / input commitment 篡改
2. source attestation 缺失、manifest 缺失、scope 不匹配、hash 不匹配、single-signoff / same-identity dual-signoff
3. strict mode 下 planned/local/manual/stale attestation 误放行
4. public/operator report 与 policy audit / release gate / truthfulness report / external anchor job 的绑定缺失
5. same-origin browser session / identity proxy fail-closed / basic security headers
6. query workflow request -> submit -> worker -> release 的治理透传
7. public report redaction、bucket public report redaction、caller-safe audit/metadata/dashboard views
8. privacy-budget close-window / threshold-round / cross-bucket differencing probe

这些都可以被称为：

> repo-side complete protocol-external governance controls

但不要把它们说成：

- production trust-root complete
- malicious-secure complete
- fully unforgeable source truth

## 6. 哪些必须“线上实现 + 线下治理”共同成立

以下任务不应该被表述成“代码写了就算解决”：

1. 真实 source export 与审批职责分离
2. 真实外部不可变审计锚点
3. 企业身份 / KMS / authority lifecycle
4. 真实 PostgreSQL HA / worker supervision / SRE drills
5. 真实浏览器 + OIDC + reverse-proxy + secure-cookie 部署链
6. 真实两机 / 公网 / 管理面 / 证书 / peer identity 证明

对于这些任务，正确说法是：

> repo-side 已经提供 typed artifact、gate、archive shape、negative tests 和
> verifier-facing bundle；但只有当 operator-side 的真实部署、账号、流程、
> 轮换、审计、演练也成立时，相关生产级安全结论才成立。

## 7. 剩余问题最后只剩两类

项目文档里的“未解决问题”最终应只保留两类。

### A. Protocol-internal / malicious-secure 才能解决的问题

1. malicious protocol deviation
2. active-secure / malicious-secure backend 缺失
3. 对 source/value truth 的真正密码学证明
4. 更强的 SSE 泄露模型缓解（ORAM / forward-private SSE / OPRF-blinded query 等）

这些不能靠新增审批、签字、archive、WORM、browser cookie、reverse proxy 来解决。

### B. 真实外部 operator / enterprise trust-root 问题

1. 真正的 immutable external anchor
2. 企业级 identity / KMS / authority lifecycle
3. 真实 HA / worker / SRE evidence
4. 部署后的 browser / OIDC / reverse-proxy / secure-cookie trust chain
5. 真实两机 / 公网 / 管理面 / peer identity / live certificate chain

这些不是学生仓库单方面能“本机完成”的事项。

## 8. 答辩推荐说法

下面这段可以直接作为稳定口径：

> 我们的技术内核是 database/control-plane + SSE + Google PJC。
> 当前 Google PJC 的计算边界明确保持在 `semi-honest/operator-controlled`。
>  
> 对于不需要更换协议就能完成的安全问题，我们已经把 source truthfulness、
> release legitimacy、approval binding、audit binding、public-report redaction、
> workflow governance 这些 protocol-external governance 能力做成了 typed artifact、
> gate、archive 和 negative tests，并且接到了 verifier-facing evidence。
>  
> 剩余问题现在只分两类：一类是必须靠 active-secure / malicious-secure
> backend 才能解决的 protocol-internal 问题；另一类是必须依赖真实外部
> operator / enterprise 基础设施才能成立的 trust-root 问题，例如真实 immutable
> anchor、enterprise identity / KMS lifecycle、live HA / worker / SRE、deployed
> browser / OIDC trust chain。

答辩时不要说的话：

1. “我们已经 malicious-secure”
2. “有 source attestation 就能证明输入一定真实”
3. “live module 全绿就代表企业 trust-root 也完整”
4. “部署一个 proof layer 就自动解决 malicious participant”

## 9. 建议引用顺序

如果老师追问，建议按这个顺序回答并给文档：

1. 项目定位与统一口径：
   [COMPACT_PLATFORM_BRIEF.md](COMPACT_PLATFORM_BRIEF.md)
2. 当前 authoritative 安全判断：
   [CURRENT_SECURITY_AND_COMPLETION_AUDIT.md](CURRENT_SECURITY_AND_COMPLETION_AUDIT.md)
3. 具体泄露与威胁边界：
   [THREAT_MODEL_AND_LEAKAGE_MODEL.md](THREAT_MODEL_AND_LEAKAGE_MODEL.md)
4. 两机 / mTLS / protocol claim 的细边界：
   [PJC_MTLS_OPEN_RISKS.md](PJC_MTLS_OPEN_RISKS.md)
5. 混合任务总表与答辩口径：
   [ONLINE_OFFLINE_SECURITY_GOVERNANCE.md](ONLINE_OFFLINE_SECURITY_GOVERNANCE.md)

## 10. 这份文档不负责什么

这份文档不替代：

1. 具体实现 backlog
2. 具体 live rollout runbook
3. 具体 operator 组织制度
4. protocol-internal malicious-secure 设计文档

它只负责把**线上+线下双管齐下**这一类最容易说乱的安全任务，整理成一致、
可审查、可答辩的口径。
