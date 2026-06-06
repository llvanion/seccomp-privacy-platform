# 电商数据库平台访问角色矩阵

这份文档把当前仓库第一阶段 file-backed authz 基线，落成一个更具体的“电商数据库平台谁会访问、访问什么、最小权限是什么”的角色矩阵。

边界先说清楚：

1. 当前建模的是“平台调用主体 / 隐私查询流程参与者”，不是完整电商公司所有人员与终端用户身份树。
2. 所以这里的 `caller` 目前更接近运营负责人、营销分析师、风控分析师、审计员、恢复服务运维，而不是买家、快递员、客服、商家店员这类业务末端角色。
3. 如果后续要支持更真实的企业组织与业务一线角色，需要在 identity source、role mapping、scope policy 和查询模板上再细化一层。

## 角色

1. `commerce_ops_owner`
职责：负责隐私查询运行、结果复核、最终发布。
最小权限：`query_submitter` + `privacy_operator`；限定 `tenant_id`、`allowed_dataset_ids`、`allowed_service_ids`；允许 `can_run_bridge`、`can_run_pjc`、`can_use_record_recovery_service`、`can_release`。

2. `campaign_analyst`
职责：做营销归因、活动复盘、受众分析。
最小权限：`query_submitter`；限定到营销数据集和 recovery service；允许 `can_run_bridge`、`can_run_pjc`、`can_use_record_recovery_service`；默认不允许 `can_release`。

3. `fraud_analyst`
职责：做欺诈命中分析、风险分层对比。
最小权限：`query_submitter`；限定到风险数据集和 recovery service；允许 `can_run_bridge`、`can_run_pjc`、`can_use_record_recovery_service`；默认不允许 `can_release`。

4. `compliance_auditor`
职责：审计 caller、scope、policy、job、audit chain 是否符合流程。
最小权限：`platform_auditor`；默认不直接跑隐私查询，不直接调用 recovery service，不具备 `can_release`。

5. `recovery_service_operator`
职责：维护 record recovery service、socket/HTTP listener、health、lifecycle、密钥和审计。
最小权限：`service_operator`；可管理 service 边界，但不应默认拥有 `can_run_bridge`、`can_run_pjc` 或 `can_release`。

## 当前没细到的角色

下面这些更贴近日常电商业务的人群，目前还没有直接作为一等 `caller` 画像建模：

1. 买家 / 消费者
2. 商家店员 / 店铺运营
3. 客服
4. 快递员 / 物流履约人员
5. 地推 / 渠道投放执行人员

原因不是“不能存在这些人”，而是当前平台边界更聚焦于隐私查询和审计链路，优先建模的是能发起、审核、运维这条链路的人。

## 业务字段级访问策略（2026-06-01）

为了补上“商户不能拿用户地址、快递员只能拿下一站、客服只能拿受保护信息”这一类 reviewer 会直接追问的缺口，仓库新增独立的业务字段级策略层：

1. 策略 schema：[schemas/business_access_policy.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/business_access_policy.schema.json)
2. 检查报告 schema：[schemas/business_access_check_report.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/business_access_check_report.schema.json)
3. 电商示例策略：[config/business_access_policy.ecommerce.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/config/business_access_policy.ecommerce.example.json)
4. 检查器：[scripts/check_business_access_policy.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/check_business_access_policy.py)
5. 反例 smoke：[scripts/check_business_access_policy_smoke.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/check_business_access_policy_smoke.py)
6. 受策略保护的 metadata API 读取预览：`POST /v1/business-data/read-preview`
7. 读取预览 schema：[schemas/business_data_read_preview.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/business_data_read_preview.schema.json)
8. API smoke schema：[schemas/business_access_api_smoke.schema.json](/home/llvanion/Desktop/seccomp-privacy-platform/schemas/business_access_api_smoke.schema.json)
9. 候选事实导入校验：[scripts/validate_ecommerce_fact_import.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/validate_ecommerce_fact_import.py)
10. 验证优先的事务导入：[scripts/import_ecommerce_fact_rows.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/import_ecommerce_fact_rows.py)
11. Console 业务访问工作台：[console/src/routes/business-access.tsx](/home/llvanion/Desktop/seccomp-privacy-platform/console/src/routes/business-access.tsx)
12. Validator-first ETL import job wrapper：[scripts/run_ecommerce_fact_import_job.py](/home/llvanion/Desktop/seccomp-privacy-platform/scripts/run_ecommerce_fact_import_job.py)

这层是 repo-side field-level contract，不改变冻结的 `SSE -> record recovery -> bridge -> PJC -> policy release` 主链路，也不替代平台 caller 权限。它用于把业务角色的字段级 allow/mask/deny 明确下来，并让 CI 能发现策略漂移。

2026-06-02 更新：metadata API 已有一个受策略保护的事实表读取路径 `POST /v1/business-data/read-preview`。该入口在 SELECT 前复用同一个 `business_access_policy/v1` 和 identity-token 角色绑定：

1. deny 字段直接 HTTP 403，不进入事实表读取。
2. mask 字段只返回 `{ "masked": true, "masking": "...", "value": null }` marker，不选择原始列值。
3. `scope` 是授权上下文；只有显式 `filters` 和安全投影后的 `tenant_id` / `dataset_id` / `order_id` 等字段进入 SQL `WHERE`。
4. `scope` 中已授权的 `tenant_id` / `order_id` 不能被 `filters` 覆盖；冲突会 HTTP 403。
5. 敏感字段不能作为查询 filter，例如 `orders.buyer_email` / `buyer_email` 会被拒绝，避免通过存在性查询绕过 mask/deny。
6. role spoofing 在 check endpoint 和 read-preview endpoint 都会被拒绝。

当前策略覆盖：

| 角色 | 当前字段级结果 |
| --- | --- |
| `buyer` | 仅在 `relationship=self` 且 purpose 合法时允许自助订单/自助联系方式字段。 |
| `merchant_staff` | 允许订单、商品、履约状态；拒绝买家地址、联系方式、快递路线、operator-only 字段。 |
| `customer_service_agent` | 允许工单/履约状态；买家联系方式只能 mask；拒绝地址、内部 operator 字段。 |
| `courier` | 只允许 `delivery_route.next_stop_*` 和履约状态；拒绝完整路线、最终地址、收件电话、订单/买家字段。 |
| `station_operator` | 只允许当前站点交接腿和站内交接字段；拒绝最终地址、下游腿地址和买家联系信息。 |
| `last_mile_courier` | 只在 `assigned_last_mile_leg` 下允许读取最终投递腿的真实投递地址；收件电话默认只给 masked 版本。 |
| `field_marketer` | 只允许 campaign attribution 字段；拒绝买家、物流、客服和 operator-only 字段。 |
| `fraud_analyst` | 允许支付方式、风险分、争议状态等 payment status 字段；拒绝买家联系方式、地址、完整路线、raw support 和 operator-only 字段。 |
| `compliance_auditor` | 允许审计目的下的业务元数据；买家地址/联系方式只能 mask；拒绝 raw operator-only 和完整路线。 |

验证命令：

```bash
python3 scripts/check_business_access_policy_smoke.py
python3 scripts/check_business_access_api_smoke.py --out-dir tmp/business_access_api_smoke
python3 scripts/check_ecommerce_fact_import_validation.py --out-dir tmp/ecommerce_fact_import_validation
python3 scripts/check_ecommerce_fact_import.py --out-dir tmp/ecommerce_fact_import_smoke
python3 scripts/check_ecommerce_production_exposure_gate.py --out-dir tmp/ecommerce_production_exposure_gate
python3 scripts/validate_json_contract.py \
  --schema schemas/business_data_read_preview.schema.json \
  --json tmp/business_access_api_smoke/business_read_preview_masked.json
python3 scripts/validate_json_contract.py \
  --schema schemas/ecommerce_fact_import_validation.schema.json \
  --json tmp/ecommerce_fact_import_validation/orders_address_report.json
python3 scripts/validate_json_contract.py \
  --schema schemas/ecommerce_fact_import_result.schema.json \
  --json tmp/ecommerce_fact_import_smoke/orders_duplicate_rollback_import.json
bash scripts/check_json_contracts.sh
```

2026-06-03 更新：新增 `ecommerce_production_exposure_gate/v1` 作为验证者可读的 repo-side 聚合门禁。它会同时检查：

1. 六张事实表和索引仍在 migration 中。
2. `business_access_policy/v1` 覆盖 buyer / merchant / support / courier / field_marketer / fraud_analyst / compliance_auditor，并保护 `orders.buyer_email`、地址和 raw support transcript。
3. metadata API read-preview 的 allow / deny / mask / sensitive-filter / role-spoof / fraud payment allow / fraud contact deny / field marketer attribution allow / field marketer contact deny 路径，以及 `business-identities` 目录对非特权 caller 的 caller-scoped / cross-tenant denial。
4. operator request workflow 的 submit / detail / approve / reject / self-approval deny 证据，以及 submitter 不能伪造 caller/tenant/dataset、不能无权限开启 recovery 路径或漂移 `record_recovery_service_id`、non-review analyst 不可见/不可批、compliance auditor 可拒绝但不可批准 的权限负例。direct query/workflow API 的 identity-bound dry-run 也覆盖了同一个 recovery service scope 约束，避免绕过 request workflow 走旁路。
5. console manifest 没有把直接 job/PJC mutation endpoint 暴露给 campaign/fraud analyst 角色。
6. 一个结构化 `exposure_matrix`：把 attacker、internal adversary、verifier 三种视角各自要看的风险、控制与证据文件固定下来，便于 release 归档和验证者复核。
7. 独立的 `identity_jwks_evidence_gate/v1` 证明 repo-side RS256/JWKS claim mapping、JWKS-backed `/v1/identity`、以及 JWKS-backed key-agent / external-KMS 身份路径可被验证者单独复核；它仍是 synthetic/file-JWKS 证据，不是 live Keycloak 证据。
8. `live_identity_authority_evidence_gate/v1` 在此基础上再上一层：它保留 repo-side JWKS 基线，同时把 live client-credentials、live JWKS claim verification、live `resolve_api_identity`、以及 live metadata `/v1/identity` 组织成 `ok|fail|skipped` 的 verifier-facing 报告；缺少 operator 提供的 live endpoint/secret 时会明确标记为 `skipped`，而不是冒充生产完成。
9. 新增物流分段可见性基线：`delivery_route_legs` 事实表现在承载 `leg_id / route_id / leg_sequence / leg_kind / assigned_courier_id / assigned_station_id / next_stop_* / pickup_station_* / final_*` 字段。repo-side smoke 已证明：
   - `courier` 在 `assigned_delivery_leg` + `delivery_next_stop` 下可以读取当前腿的 `next_stop`，但不能读取 `final_address_line1`
   - `station_operator` 在 `assigned_station_leg` + `station_handoff` 下可以读取站点交接字段，但不能读取 `final_address_line1`
   - `last_mile_courier` 在 `assigned_last_mile_leg` + `last_mile_delivery` 下可以读取最终投递地址，但 `recipient_phone` 仍默认以 masked 形式返回
   - 因此“北京小区站 -> 城市中转站 -> 北京末端站 / 楼栋”这类分段物流权限现在不再只是策略占位，而是有数据模型、导入校验和 metadata read-preview 验证
10. As of 2026-06-04, the repo-side gate no longer trusts caller-supplied
    `relationship` / `scope` hints by themselves for the main commerce personas.
    The fact layer now carries explicit relationship-binding columns:
    - `orders.merchant_business_identity_id`
    - `orders.buyer_business_identity_id`
    - `order_attribution.assigned_marketer_business_identity_id`
    - `order_payment.assigned_fraud_analyst_business_identity_id`
    - `order_payment.fraud_case_id`
    - `customer_service_interactions.case_id`
    and `serve_metadata_api.py` binds those back to `business_identities`
    before returning `business_access_check_report/v1` or
    `business_data_read_preview/v1`.
11. The resulting repo-side hardening is:
    - `merchant_staff` can no longer self-assert `merchant_of_order`; the order
      row must already point at the caller's `merchant_business_identity_id`.
    - `buyer` self-service can no longer self-assert another buyer; the order
      row must already point at the caller's `buyer_business_identity_id`.
    - `courier` / `station_operator` / `last_mile_courier` can no longer pivot
      by swapping `assigned_*` scope fields; the delivery leg row must already
      be assigned to the caller's business identity, and the caller-supplied
      scope anchor must match that bound identity.
    - `fraud_analyst` and `field_marketer` now require a bound fraud case /
      assigned campaign record in the fact rows, rather than only a declared
      `case_id` / `campaign_id`.
12. `customer_service_agent` relation binding is now implemented in the same
    repo-side handler path and yields a valid
    `business_access_check_report/v1` with `relationship_binding.status=ok`.
    The loopback HTTP smoke now also proves the same non-privileged support
    caller path: support sees masked buyer contact on its assigned case, and
    spoofing another `case_id` is rejected with HTTP 403. This is still
    repo-side evidence, not deployment proof.
13. As of 2026-06-05, the operator console now has a dedicated repo-side
    `Business Access Workbench` route. It calls
    `POST /v1/business-access/check` and
    `POST /v1/business-data/read-preview` through the metadata sidecar client,
    and ships curated merchant/support/courier/last-mile/fraud presets so
    reviewer-facing browser flows stay on the same contract as the API smoke.
14. As of 2026-06-05, external ETL/event-stream style imports also have a
    verifier-facing wrapper:
    `ecommerce_fact_import_job/v1` via
    `scripts/run_ecommerce_fact_import_job.py`.
    It is a manifest-driven wrapper around
    `import_ecommerce_fact_rows.py`; the smoke proves an allowed batch commits
    and a protected-column batch is denied without mutating final row count.

这个 gate 是 repo-side production exposure evidence，不是 live deployment evidence。真实生产仍要补真实 OIDC/JWKS 身份、OpenFGA/ABAC 或等价外部授权、真实/批准的电商数据导入报告、TLS/mTLS 和 NetworkPolicy 部署证据、Postgres backup/restore/failover、以及外部 immutable audit anchor。

边界仍然保留：

1. 这还不是完整业务 API ABAC；当前强制读取路径是 metadata API 的 read-preview。
2. 新增业务读 endpoint 必须复用 read-preview 的 pre-SELECT policy gate 和安全 filter allowlist，否则会重新打开绕过面。
3. repo-side 已有验证优先的事务批量导入命令；生产外部 ETL、事件流或数据仓库任务仍必须调用该命令或实现等价 policy gate，才能支撑生产 ingest 声明。
4. 还需要 OpenFGA/ABAC 决策，才能支撑外部化生产授权声明。
5. 真实地址、物流路线、客服 transcript 仍未进入当前 fact-layer；如果加入，必须先扩展策略、schema、read gate、import validator 和事务 importer。
6. Console `Business Access Workbench` 和 `ecommerce_fact_import_job/v1`
   目前都只是 repo-side evidence：它们证明浏览器接触面和 ETL wrapper
   已经接到同一套 gate，不代表已经存在 live browser session evidence 或
   真实 external ETL deployment evidence。

## 业务身份扩展（Track-E2，2026-05-08 落基线）

为了把上面这五类业务身份接入隐私平台、又不破坏 `caller_permissions` 已经冻结的 schema，新增一张 `business_identities` 表（迁移 [`migrations/metadata/011_add_business_identities.sql`](/home/llvanion/Desktop/seccomp-privacy-platform/migrations/metadata/011_add_business_identities.sql)），把"业务一线身份"作为 `caller` 的可选画像挂在已有的 `caller_permissions` 上。

设计原则：

1. **业务身份不是 caller**。买家、客服、快递员、商家店员不直接发起隐私查询；他们的身份只用于解释为什么某个 caller 能在某个 scope 内活动。
2. **`caller_permissions` 不变**。`tenant_id` / `allowed_dataset_ids` / `allowed_service_ids` / `can_*` 仍是隐私阶段的唯一权限源；`business_identities` 不引入新的 stage gate。
3. **PII 不进库**。表只存“业务身份的脱敏 ID + 角色 + 关联的 caller_id”，不存姓名、地址、电话、身份证。

业务身份枚举（`identity_kind`）：

| identity_kind | 谁 | 关联到 |
|---------------|----|--------|
| `buyer` | 买家 / 消费者 | `caller` 一般是 `commerce_ops_owner` 或 `compliance_auditor` 代查；`subject_external_id` 是脱敏买家 ID（不等同于明文 email） |
| `merchant_staff` | 商家店员 / 店铺运营 | `caller` 一般是 `commerce_ops_owner` |
| `customer_service_agent` | 客服 | `caller` 一般是 `compliance_auditor` 或专门的 supervisor |
| `courier` | 快递员 / 物流履约人员 | 不发起查询；只在 `customer_service_interactions.agent_id` / `order_fulfillment.carrier_id` 里出现 |
| `field_marketer` | 地推 / 渠道投放执行人员 | `caller` 一般是 `campaign_analyst` |
| `fraud_analyst` | 风控 / 支付争议分析 | `caller` 一般是 `fraud_analyst` 或带同等业务身份的审计/风控服务账号 |

字段定义（详见迁移）：`id` / `business_identity_id` / `tenant_id` / `dataset_id` / `identity_kind` / `caller_id` / `subject_external_id` / `display_label` / `enabled` / `created_at_utc` / `updated_at_utc` / `metadata_json`。约束：

- `(tenant_id, business_identity_id)` 唯一。
- `caller_id` 可空；非空时必须能在 `caller_permissions` 找到匹配 row。
- `identity_kind` 受控集合：`buyer` / `merchant_staff` / `customer_service_agent` / `courier` / `field_marketer` / `fraud_analyst`。

读取入口：`query_metadata.py --list-entity business-identities`（与现有 `caller-permissions` 视图同形态）。对非特权 identity，这个目录现在按 `caller_id` fail-closed 收窄，并拒绝 caller/tenant 冒充；只有特权 platform 角色保留广域枚举能力。

边界保留：

1. 这一层不替代 OpenFGA 关系建模；它是 RBAC + scope 模型之上的一层"业务身份注解"。
2. 不引入新的 stage gate（`can_*` 仍然只在 `caller_permissions` 上）。
3. 不存 PII；任何把姓名/手机号/地址写入 `display_label` 或 `metadata_json` 的行为都属于策略违规，应该在导入路径上加校验（operator-side 实施）。

## 当前落地方式

当前仓库没有第二套独立 RBAC 表。第一阶段仍然通过 `sse_export_policy/v1` 里的 caller 记录承载这些角色语义：

1. `tenant_id`、`allowed_dataset_ids`、`allowed_service_ids` 定义 scope。
2. `can_run_bridge`、`can_run_pjc`、`can_use_record_recovery_service`、`can_release` 定义阶段权限。
3. `platform_roles` 和 `access_profile` 负责把这些 caller 标成更容易审计的电商角色画像。

这也意味着当前 `caller` 粒度主要是“查询主体”而不是“业务对象”。例如买家是否来自某平台、从哪个广告入口点击、购买了哪些 SKU，这些不是 `caller` 表达的内容，而应该属于业务数据与查询模板层。

对应示例文件：

1. [sse/config/ecommerce_access_policy.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/sse/config/ecommerce_access_policy.example.json)
2. [sse/config/export_policy.example.json](/home/llvanion/Desktop/seccomp-privacy-platform/sse/config/export_policy.example.json)

## 为什么这样分

1. `platform_roles` 解决“这个人为什么能进平台”的 coarse-grained 角色问题。
2. `can_*` 解决“这个 caller 能不能走某个隐私阶段”的 pipeline 权限问题。
3. `tenant_id` / `dataset_id` / `service_id` 解决“这个 caller 能碰哪些数据和恢复边界”的 scope 问题。

三层叠加，才能避免只有角色没有 scope，或者只有 scope 没有职责语义。
