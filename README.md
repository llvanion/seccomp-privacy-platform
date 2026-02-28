# Module A 使用说明

本文档描述项目中 **A 模块（PSI 归因流水线）** 的职责、接口、调用方式、输出文件含义，以及可选的认证与防重放机制。

A 模块的目标是：从原始点击 / 转化数据中构造 PSI/PJC 输入，运行隐私保护计算协议，并对结果进行带治理的发布（阈值、频控、审计、可选认证）。

---

# 1. 模块结构

A 模块当前由以下四个脚本组成：

- `moduleA_psi/scripts/prep_inputs.py`
- `moduleA_psi/scripts/run_pjc.sh`
- `moduleA_psi/scripts/policy_release.py`
- `moduleA_psi/scripts/run_pipeline.sh`

四个脚本的职责如下：

## 1.1 `prep_inputs.py`
负责输入准备（W1）：

- 从原始 Criteo TSV 中读取数据
- 根据时间窗口过滤
- 根据配置做去重
- 构造 `server.csv` / `client.csv`
- 输出 `job_meta.json`

## 1.2 `run_pjc.sh`
负责协议执行：

- 读取 `server.csv` / `client.csv`
- 调用 PJC / PSI 执行程序
- 生成 `attribution_result.json`

## 1.3 `policy_release.py`
负责发布层治理（W2）：

- 读取 `attribution_result.json`
- 读取 `job_meta.json`
- 应用阈值发布
- 应用频控
- 记录审计日志
- 可选支持 API key / HMAC / timestamp / nonce 防重放
- 输出 `public_report.json`
- 输出 / 追加 `audit_log.jsonl`

## 1.4 `run_pipeline.sh`
负责端到端总控（W3）：

- 先调用 `prep_inputs.py`
- 再调用 `run_pjc.sh`
- 最后调用 `policy_release.py`

---

# 2. 角色说明

本模块中有三类不同角色，必须区分：

## 2.1 server / client
这是 **协议执行层** 的角色，不是 API 调用身份。

在本模块里推荐的业务解释为：

- `server`：曝光 / 点击侧输入
- `client`：购买 / 转化侧输入

对应文件：

- `server.csv`
- `client.csv`

## 2.2 caller
这是 **发布治理层** 的调用者身份。

caller 用于：

- 频控（rate limit）
- 审计（audit）
- 可选认证（API key / HMAC）
- 记录“谁请求释放结果”

caller 不等于 PSI/PJC 协议中的 server 或 client。

## 2.3 key_id
这是 **认证层** 的身份索引。

典型关系为：

- `key_id -> caller -> secret`

---

# 3. 输出目录结构

每次任务统一组织在一个 `job_dir` 下，例如：

    runs/<job_id>/
      server.csv
      client.csv
      job_meta.json
      attribution_result.json
      public_report.json
      audit_log.jsonl

说明如下：

## 3.1 `server.csv`
协议 server 侧输入文件。

通常表示曝光 / 点击侧集合。

## 3.2 `client.csv`
协议 client 侧输入文件。

通常表示购买 / 转化侧集合。

## 3.3 `job_meta.json`
任务元信息文件，记录本次任务的上下文。推荐至少包含：

- `job_id`
- `window_start`
- `window_end`
- `value_mode`
- `value_unit`
- `input_sizes`
- `bucket_field`
- `bucket_count`
- `dedup`
- `window_semantics`
- `canonical_query_signature`
- `generated_at_utc`

## 3.4 `attribution_result.json`
PSI/PJC 的直接协议输出。

注意：该文件不是最终对外发布结果。

## 3.5 `public_report.json`
最终对外发布结果。

该文件经过发布层治理控制，不会直接等于协议原始输出。

## 3.6 `audit_log.jsonl`
审计日志，每次发布尝试都应追加一条记录。

---

# 4. 数据语义与处理规则

## 4.1 输入数据来源
当前 `prep_inputs.py` 支持从 Criteo TSV 输入构造任务。

## 4.2 时间窗口
任务使用：

- `--start-ts`
- `--end-ts`

指定窗口范围。

## 4.3 value mode
当前支持两种模式：

- `count`
- `amount`

### `count`
表示按次数统计。

### `amount`
表示按金额统计。

内部实现中，金额以 **整数 euro_cent** 表示，最终在发布层中再格式化为欧元显示。

## 4.4 去重规则
当前实现中，推荐固定为：

- exposure：窗口内每用户最多记一次
- purchase：窗口内每用户最多记一次，金额模式下保留最大值

具体规则会写入 `job_meta.json` 的 `dedup` 字段。

## 4.5 conversion 时间
如果启用：

- `--purchase-use-conversion-ts`

则购买时间使用：

- `click_timestamp + time_delay_for_conversion`

否则默认使用 click timestamp 语义。

---

# 5. Stage 1：输入准备（W1）

## 5.1 调用方式

    python3 moduleA_psi/scripts/prep_inputs.py \
      --criteo-tsv data/extracted/criteo/latest/Criteo_Conversion_Search/CriteoSearchData \
      --out runs/w3_criteo_count_day \
      --start-ts 1596439471 \
      --end-ts 1596445871 \
      --value-mode count \
      --job-id w3_criteo_count_day

## 5.2 主要参数

- `--criteo-tsv`
  - 原始输入 TSV 路径

- `--out`
  - 输出目录（job_dir）

- `--start-ts`
  - 窗口开始时间（Unix timestamp）

- `--end-ts`
  - 窗口结束时间（Unix timestamp）

- `--value-mode`
  - `count` 或 `amount`

- `--job-id`
  - 任务 ID（建议显式提供）

- `--bucket-field`
  - 可选分桶字段

- `--hmac-secret`
  - 可选，对用户 ID 做 HMAC 匿名化

- `--purchase-use-conversion-ts`
  - 可选，是否使用 conversion 时间语义

## 5.3 主要输出
- `server.csv`
- `client.csv`
- `job_meta.json`

---

# 6. Stage 2：协议执行（PJC / PSI）

## 6.1 调用方式

在 pipeline 模式下，推荐由 `run_pipeline.sh` 自动调用。

单独运行时，当前 `run_pjc.sh` 依赖以下环境变量：

- `SERVER_CSV`
- `CLIENT_CSV`
- `OUT_DIR`
- `JOB_ID`

例如：

    export SERVER_CSV="runs/w3_criteo_count_day/server.csv"
    export CLIENT_CSV="runs/w3_criteo_count_day/client.csv"
    export OUT_DIR="runs/w3_criteo_count_day"
    export JOB_ID="w3_criteo_count_day"

    bash moduleA_psi/scripts/run_pjc.sh

## 6.2 说明
`run_pjc.sh` 的旧版默认值可能仍然指向：

- `/tmp/server.csv`
- `/tmp/client.csv`

因此在 pipeline 模式下，必须由 `run_pipeline.sh` 通过环境变量覆盖。

## 6.3 输出
- `attribution_result.json`

---

# 7. Stage 3：发布治理（W2）

## 7.1 基础调用方式

    python3 moduleA_psi/scripts/policy_release.py \
      --job-dir runs/w3_criteo_count_day \
      --caller demo \
      --k 20 \
      --n 5

## 7.2 主要参数

- `--job-dir`
  - 任务目录，里面应包含：
    - `job_meta.json`
    - `attribution_result.json`

- `--caller`
  - 发布层调用者身份

- `--k`
  - 阈值发布门槛

- `--n`
  - 同一 `caller + window` 允许的最大请求次数

## 7.3 功能
W2 当前负责：

- 阈值发布（threshold release）
- 频控（rate limiting）
- 审计（audit logging）
- 可选认证（API key / HMAC）
- 可选防重放（timestamp + nonce）

## 7.4 输出
- `public_report.json`
- `audit_log.jsonl`

---

# 8. `public_report.json` 含义

## 8.1 allow 时
若请求被允许发布，则 `public_report.json` 应包含完整结果，例如：

- `released`
- `reason`
- `reason_code`
- `conversions`
- `value_sum`
- `aov`
- `window`
- `k_threshold`
- `rate_limit_used`
- `rate_limit_max`
- 可选 `bucket`
- 可选 `input_sizes`
- `details`

## 8.2 deny 时
若请求被拒绝（例如 `below_k`、`bad_signature`、`replay_detected`），则推荐使用瘦身版 `public_report.json`，只保留：

- `schema`
- `generated_at_utc`
- `policy_version`
- `job_id`
- `caller`
- `released`
- `reason`
- `reason_code`
- 可选 `window`
- 可选 `k_threshold`

敏感统计值应置空或不返回：

- `conversions`
- `value_sum`
- `aov`
- `details`

---

# 9. `audit_log.jsonl` 含义

`audit_log.jsonl` 用于内部审计，应保留比 `public_report.json` 更完整的记录。

推荐每条记录包含：

- `ts_utc`
- `job_id`
- `caller`
- `window`
- `input_sizes`
- `decision`
- `reason`
- `reason_code`
- `k_threshold`
- `rate_limit_used`
- `rate_limit_max`
- `canonical_query_signature`

如果开启认证，还建议记录：

- `key_id`
- `timestamp`
- `nonce`

注意：

- 审计日志是内部日志
- 对外响应可以瘦身
- 审计日志不应跟着对外响应一起裁剪

---

# 10. 一键全流程调用（W3）

## 10.1 调用方式

    bash moduleA_psi/scripts/run_pipeline.sh \
      --criteo-tsv data/extracted/criteo/latest/Criteo_Conversion_Search/CriteoSearchData \
      --start-ts 1596439471 \
      --end-ts 1596445871 \
      --value-mode count \
      --out runs/w3_criteo_count_day \
      --job-id w3_criteo_count_day \
      --k 20 \
      --caller demo

## 10.2 说明
该脚本负责：

1. 调用 `prep_inputs.py`
2. 调用 `run_pjc.sh`
3. 调用 `policy_release.py`

因此适合：

- 新任务
- 新窗口
- 新参数
- 端到端 demo

---

# 11. 为什么不是每次都要重新跑 `prep_inputs.py`

如果是以下情况，建议重新跑全流程：

- 原始数据变化
- 时间窗口变化
- `value-mode` 变化
- `bucket-field` 变化
- `purchase-use-conversion-ts` 变化
- 匿名化参数变化

如果只是对同一个 `job_dir` 做：

- 重复发布
- 认证测试
- 重放测试
- 阈值测试
- 频控测试

则不需要重新运行 `prep_inputs.py`，也不需要重新运行 PJC，只需要重新执行：

    python3 moduleA_psi/scripts/policy_release.py --job-dir ...

这可以避免不必要的计算资源浪费。

---

# 12. 认证与防重放（可选增强）

## 12.1 认证配置文件
推荐在仓库中提供示例文件：

    moduleA_psi/config/auth_config.example.json

示例内容：

    {
      "demo-key-001": {
        "caller": "judge_demo",
        "secret": "replace_with_a_long_random_secret_value",
        "enabled": true
      }
    }

说明：

- `key_id`
  - 即 `demo-key-001`

- `caller`
  - 认证通过后映射得到的调用者身份

- `secret`
  - 用于 HMAC 验签

- `enabled`
  - 是否启用该 key

## 12.2 启用认证时的调用方式

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

## 12.3 认证参数含义

- `--auth-config`
  - 认证配置文件路径

- `--auth-required`
  - 开启认证检查

- `--key-id`
  - 本次请求使用的 key 标识

- `--timestamp`
  - UTC 时间戳，用于防旧包重放

- `--nonce`
  - 一次性随机串，用于防重放

- `--signature`
  - HMAC 签名结果

---

# 13. nonce / timestamp / rate limit 的区别

## 13.1 nonce
nonce 的作用是：

- 防重放
- 一次性使用

同一个 `key_id + nonce` 不能重复使用。

这并不表示“一个 secret 只能调用一次”，而是表示：

- **每次请求必须使用新的 nonce**
- **每次请求都应重新签名**

## 13.2 timestamp
timestamp 的作用是：

- 限制请求有效时间窗口
- 防止旧包被长期重放

如果当前系统设置的是 300 秒容差，那么：

- 当前时间与 timestamp 相差超过 300 秒
- 请求会被拒绝

## 13.3 rate limit
rate limit 的作用是：

- 控制同一 caller 在同一窗口上最多允许查看多少次

例如：

- `n = 5`

则表示：

- 同一 `caller + window` 最多允许 5 次独立请求

注意：

- 不是“一个签名可用 5 次”
- 而是“最多允许 5 次重新签名、重新提交的独立请求”

---

# 14. 推荐演示流程

建议至少准备 3 类演示：

## 14.1 正常发布
目标：

- 证明端到端 pipeline 可运行
- 证明 `released = true`

## 14.2 阈值拒绝
方法：

- 提高 `k`

目标：

- 演示 `below_k`

## 14.3 认证 / 防重放拒绝
方法：

- 故意使用错误签名，触发 `bad_signature`
- 或重复使用相同 nonce，触发 `replay_detected`

目标：

- 演示发布治理层不仅有 PSI/PJC，还有认证与重放防护

---

# 15. 当前推荐的稳定接口

## 15.1 推荐给开发同学的入口
一键执行：

    bash moduleA_psi/scripts/run_pipeline.sh ...

## 15.2 推荐给平台 / 后续集成人员的分阶段入口

### Stage 1
    python3 moduleA_psi/scripts/prep_inputs.py ...

### Stage 2
    bash moduleA_psi/scripts/run_pjc.sh

### Stage 3
    python3 moduleA_psi/scripts/policy_release.py ...

这种分阶段接口适合：

- 单测某一层
- 重用已有 job_dir
- 避免重复运行输入准备和协议执行

---

# 16. 建议稳定下来的 JSON 字段

## 16.1 `job_meta.json`
建议固定：

- `job_id`
- `window_start`
- `window_end`
- `value_mode`
- `value_unit`
- `input_sizes`
- `bucket_field`
- `bucket_count`
- `dedup`
- `window_semantics`
- `canonical_query_signature`
- `generated_at_utc`

## 16.2 `public_report.json`
建议固定：

- `released`
- `reason`
- `reason_code`
- `conversions`
- `value_sum`
- `aov`
- `window`
- `k_threshold`

deny 时可裁剪为瘦身版。

## 16.3 `audit_log.jsonl`
建议固定：

- `ts_utc`
- `job_id`
- `caller`
- `window`
- `input_sizes`
- `decision`
- `reason`
- `reason_code`
- `k_threshold`
- `rate_limit_used`
- `rate_limit_max`
- `canonical_query_signature`

认证开启时再补：

- `key_id`
- `timestamp`
- `nonce`

---

# 17. 总结

A 模块的核心价值不只是“跑出 PSI/PJC 结果”，而是：

- 标准化输入准备
- 稳定 job_dir 目录约定
- 端到端流水线
- 结果发布治理
- 可选认证与防重放
- 可审计、可展示、可被其他模块调用

因此，推荐将 A 模块视为一个具备以下能力的归因服务：

- Prepare
- Run
- Release
- Audit
- Optional Auth