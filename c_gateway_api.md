# C Gateway API

这份文档面向 A/B 协作同学，描述当前 `c-gateway` 分支对外提供的接口、请求结构、返回结构和语义说明。

## 1. 健康检查

### `GET /health`

### 说明
用于确认 C 网关服务是否正常运行。

### 请求
无请求体。

### 返回示例
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "service": "member-c-access-gateway",
    "status": "healthy"
  },
  "timestamp": "2026-03-28T07:13:51.223406+00:00"
}
```

---

## 2. Attribution 接口

### `POST /attribution/run`

### 说明
C 对 A 模块的统一归因入口。  
当前在未配置真实 A 环境时可走 mock；接入真实 A 后，这里作为对外统一 REST 接口。

### 请求示例
```json
{
  "job_id": "demo_job_001",
  "start_ts": 1596439471,
  "end_ts": 1596445871,
  "k": 20,
  "caller": "member_c_demo",
  "n": 5,
  "value_mode": "count"
}
```

### 请求字段
- `job_id`: 任务标识
- `start_ts`: 开始时间戳
- `end_ts`: 结束时间戳
- `k`: 发布阈值
- `caller`: 调用者标识
- `n`: 查询频控上限
- `value_mode`: 统计模式，当前常用 `count`
- `out_dir`: 可选，输出目录

### 返回示例
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "job_id": "demo_job_001",
    "released": true,
    "reason_code": "allow",
    "report": {
      "job_id": "demo_job_001",
      "released": true,
      "reason": "ok",
      "reason_code": "allow",
      "conversions": 12,
      "value_sum": 12,
      "aov": 1,
      "window": {
        "start_ts": 1596439471,
        "end_ts": 1596445871
      },
      "k_threshold": 20,
      "rate_limit_used": 1,
      "rate_limit_max": 5
    }
  },
  "timestamp": "2026-03-28T07:05:08.641020+00:00"
}
```

### 返回字段说明
- `released`: 是否允许发布结果
- `reason_code`: 发布决策原因
- `report`: 归因结果详情

---

## 3. SE 建索引接口

### `POST /se/index/build`

### 说明
C 对 B 模块索引构建能力的统一入口。  
当前在未配置真实 B 环境时可走 `local` fallback。

### 请求示例
```json
{
  "index_name": "demo_index",
  "records": [
    {
      "keys": ["China", "中国", "CN"],
      "values": ["enc_a1", "enc_a2"]
    },
    {
      "keys": ["Github", "代码托管"],
      "values": ["enc_g1"]
    }
  ]
}
```

### 请求字段
- `index_name`: 索引名称
- `records`: 索引数据列表
  - `keys`: 可检索关键词列表
  - `values`: 与关键词关联的结果值列表

### 返回示例
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "index_name": "demo_index",
    "indexed_count": 8,
    "backend_used": "local"
  },
  "timestamp": "2026-03-28T07:29:34.256530+00:00"
}
```

### 返回字段说明
- `indexed_count`: 实际建立的索引映射条目数
- `backend_used`: 当前使用的后端实现，例如 `local` / `python_api`

---

## 4. SE 搜索接口

### `POST /se/search`

### 说明
C 对 B 模块搜索能力的统一入口。

### 请求示例
```json
{
  "index_name": "demo_index",
  "keyword": "中国"
}
```

### 请求字段
- `index_name`: 目标索引名
- `keyword`: 检索关键词

### 返回示例
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "index_name": "demo_index",
    "keyword": "中国",
    "result_count": 2,
    "encrypted_results": ["enc_a1", "enc_a2"],
    "backend_used": "local"
  },
  "timestamp": "2026-03-28T07:31:20.123456+00:00"
}
```

### 返回字段说明
- `result_count`: 命中结果数
- `encrypted_results`: 返回结果列表
- `backend_used`: 当前使用的后端实现

---

## 5. 审计查询接口

### `GET /audit/query`

### 说明
用于查询 C 网关记录的审计日志。

### 查询参数
- `action`: 可选，按动作过滤
- `actor`: 可选，按调用者过滤
- `start_ts`: 可选，起始时间
- `end_ts`: 可选，结束时间
- `limit`: 可选，返回条数限制

### 请求示例
```text
GET /audit/query?action=se_search&actor=demo&limit=20
```

### 返回示例
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "total": 2,
    "rows": [
      {
        "ts_utc": "2026-03-28T08:00:23.070000+00:00",
        "action": "access_token_issue",
        "actor": "demo",
        "payload": {
          "jti": "6751d4d3-bc66-4f52-a9b3-fd61d4fb185c",
          "scopes": ["orders:sensitive:read"],
          "resource_id": "demo-1001",
          "expires_at": "2026-03-28T08:10:23+00:00"
        }
      }
    ]
  },
  "timestamp": "2026-03-28T08:17:00.000000+00:00"
}
```

### 返回字段说明
- `total`: 总记录数
- `rows`: 审计记录列表
- `payload`: 各动作的扩展上下文

---

## 6. Token 签发接口

### `POST /access/token/issue`

### 说明
W6 能力令牌签发接口。  
用于为调用方签发带权限范围、资源范围和有效期的 token。

### 请求示例
```json
{
  "actor": "demo",
  "scopes": ["orders:sensitive:read"],
  "resource_id": "demo-1001",
  "expire_seconds": 600
}
```

### 请求字段
- `actor`: 申请者标识
- `scopes`: 权限范围列表
- `resource_id`: 限定资源范围
- `expire_seconds`: token 有效期（秒）

### 返回示例
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9....",
    "token_type": "Bearer",
    "expires_at": "2026-03-28T08:10:23+00:00",
    "jti": "6751d4d3-bc66-4f52-a9b3-fd61d4fb185c",
    "actor": "demo",
    "scopes": ["orders:sensitive:read"],
    "resource_id": "demo-1001"
  },
  "timestamp": "2026-03-28T08:00:23.074000+00:00"
}
```

### 返回字段说明
- `access_token`: 实际 Bearer token
- `expires_at`: 过期时间
- `jti`: token 唯一编号
- `scopes`: 当前 token 权限范围
- `resource_id`: 当前 token 限定资源

---

## 7. Token 撤销接口

### `POST /access/token/revoke`

### 说明
W6 token 撤销接口。  
撤销后，同一 token 不应再被放行。

### 请求示例
```json
{
  "jti": "6751d4d3-bc66-4f52-a9b3-fd61d4fb185c",
  "revoked_by": "demo",
  "reason": "manual_test"
}
```

### 请求字段
- `jti`: 目标 token 编号
- `token`: 可选，也可直接传 token 本体
- `revoked_by`: 撤销执行者
- `reason`: 撤销原因

### 返回示例
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "revoked": true,
    "jti": "6751d4d3-bc66-4f52-a9b3-fd61d4fb185c",
    "revoked_by": "demo",
    "reason": "manual_test"
  },
  "timestamp": "2026-03-28T08:20:00.000000+00:00"
}
```

---

## 8. 敏感数据访问接口

### `GET /orders/{id}/sensitive`

### 说明
W6 受控敏感资源访问接口。  
必须携带 Bearer token 访问。  
服务端会校验：
- token 格式与签名
- 是否过期
- 是否已撤销
- scope 是否匹配
- resource_id 是否匹配

### 请求示例
```text
GET /orders/demo-1001/sensitive
Authorization: Bearer <access_token>
```

### 成功返回示例
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "order_id": "demo-1001",
    "actor": "demo",
    "masked": true,
    "allowed_scopes": ["orders:sensitive:read"],
    "data": {
      "order_id": "demo-1001",
      "user_name": "A***",
      "phone": "138****8000",
      "email": "al***@example.com",
      "shipping_address": "Shanghai Pud***",
      "id_number": "31**************34",
      "amount": 199.0,
      "currency": "CNY",
      "note": "demo order for W6 capability token flow"
    }
  },
  "timestamp": "2026-03-28T08:16:46.401498+00:00"
}
```

### 成功返回字段说明
- `masked`: 是否返回脱敏结果
- `allowed_scopes`: 本次访问使用的权限
- `data`: 实际返回的数据内容

### 失败返回示例（token 已撤销）
```json
{
  "code": 401,
  "message": "token revoked",
  "data": {
    "reason_code": "token_revoked",
    "details": {}
  },
  "timestamp": "2026-03-28T08:22:05.490572+00:00"
}
```

### 失败返回说明
- `401`: 当前 token 不再有效
- `reason_code=token_revoked`: 表示失败原因是 token 已撤销

---

## 9. 当前 C Gateway 接口职责总结

### A 相关
- `/attribution/run`
作用：统一封装归因能力

### B 相关
- `/se/index/build`
- `/se/search`
作用：统一封装检索能力

### 审计与可观测
- `/health`
- `/audit/query`
作用：系统状态检查与审计查询

### 安全控制（W6）
- `/access/token/issue`
- `/access/token/revoke`
- `/orders/{id}/sensitive`
作用：受控授权、最小披露、即时撤权
