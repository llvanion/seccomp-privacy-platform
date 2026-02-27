# seccomp-privacy-platform

## 浮动数（Amount）问题

在使用 **Private Join and Compute (PJC)** 进行计算时，出现了 **浮动数问题**，特别是在处理 **金额**（amount）数据时。

**问题描述：**
- PJC 协议默认假定金额是 **整数** 类型。如果你使用浮动数（例如 `0.5` 欧元），系统会尝试将其强制转换为整数，可能导致数据误差（例如 `0.5` 转换为 `0`）。
- 这是由于 **PJC 协议中没有明确处理浮动数** 的问题。

**解决方案：**
- 如果你必须使用浮动数类型，可以 **手动将其转换为整数**，并进行 **乘以 1000** 处理（假设最小单位为分）。然后，将转换后的整数传入 PJC。
- **注意**：在转换浮动数为整数时，请确保不会造成 **精度丢失**，并在计算结束后，必要时将结果转回浮动数。

**临时解决方案**：
- 强制将所有金额转换为 **整数**，并在计算后恢复浮动数。


## 使用方法（W1 / W2 / W3）

本仓库提供一条最小可跑通的端到端流水线（Prep → Run PJC → Policy Release），并支持一键脚本 `run_pipeline.sh`。

---

### 目录与产物

一次运行会在 `runs/<job_id>/` 下生成如下文件：

```text
runs/<job_id>/
  server.csv
  client.csv
  job_meta.json
  attribution_result.json
  public_report.json

全局审计日志（默认）：

```text
runs/audit_log.jsonl
```

---

## W1：准备输入（`prep_inputs.py`）

**作用**：从 Criteo 数据中切出指定时间窗口，生成 PJC 需要的输入文件：

* `server.csv`（server 侧集合）
* `client.csv`（client 侧集合 + value）
* `job_meta.json`（窗口、模式等元信息）

**命令行：**

```bash
python3 moduleA_psi/scripts/prep_inputs.py \
  --criteo-tsv <path_to_criteo_file> \
  --out <job_dir> \
  --value-mode <count|amount> \
  --start-ts <start_unix_seconds> \
  --end-ts <end_unix_seconds>
```

**示例（count 模式，1 天窗口）：**

```bash
python3 moduleA_psi/scripts/prep_inputs.py \
  --criteo-tsv data/extracted/criteo/latest/Criteo_Conversion_Search/CriteoSearchData \
  --out runs/w1_criteo_count_day_int \
  --value-mode count \
  --start-ts 1596439471 --end-ts 1596525871
```

---

## 运行 PJC（`run_pjc.sh`）

**作用**：在本机启动 PJC server + client，执行协议并输出 `attribution_result.json`。

**输入方式**：`run_pjc.sh` 通过环境变量读取输入路径：

* `SERVER_CSV`（默认 `/tmp/server.csv`）
* `CLIENT_CSV`（默认 `/tmp/client.csv`）
* `OUT_DIR`（默认 `./runs/<job_id>`）

**推荐调用：**

```bash
SERVER_CSV="<job_dir>/server.csv" \
CLIENT_CSV="<job_dir>/client.csv" \
OUT_DIR="<job_dir>" \
JOB_ID="<job_id>" \
bash moduleA_psi/scripts/run_pjc.sh
```

**输出：**

```text
<job_dir>/attribution_result.json
```

---

## W2：发布策略与审计（`policy_release.py`）

**作用**：对 `attribution_result.json` 做最小安全发布（k-threshold 等），输出 `public_report.json`，并记录审计日志。

**命令行：**

```bash
python3 moduleA_psi/scripts/policy_release.py \
  --input <job_dir>/attribution_result.json \
  --out <job_dir>/public_report.json \
  --threshold-k <k> \
  --audit-log runs/audit_log.jsonl \
  --query-id <job_id>
```

**示例：**

```bash
python3 moduleA_psi/scripts/policy_release.py \
  --input runs/w1_criteo_count_day_int/attribution_result.json \
  --out runs/w1_criteo_count_day_int/public_report.json \
  --threshold-k 20 \
  --audit-log runs/audit_log.jsonl \
  --query-id w1_criteo_count_day_int
```

---

## W3：一键流水线（`run_pipeline.sh`）

**作用**：一条命令执行 **Prep → Run PJC → Policy Release**，最终产出 `public_report.json`。

**命令行：**

```bash
bash moduleA_psi/scripts/run_pipeline.sh \
  --criteo-tsv <path_to_criteo_file> \
  --start-ts <start_unix_seconds> \
  --end-ts <end_unix_seconds> \
  --value-mode <count|amount> \
  --out <job_dir> \
  --job-id <job_id> \
  --k <threshold_k>
```

**示例（count 模式，1 天窗口）：**

```bash
bash moduleA_psi/scripts/run_pipeline.sh \
  --criteo-tsv data/extracted/criteo/latest/Criteo_Conversion_Search/CriteoSearchData \
  --start-ts 1596439471 \
  --end-ts   1596525871 \
  --value-mode count \
  --out runs/w3_criteo_count_day \
  --job-id w3_criteo_count_day \
  --k 20
```

运行完成后检查：

```text
runs/w3_criteo_count_day/public_report.json
```

---

## amount 模式说明（欧元 → 欧分整数）

PJC 不支持/不可靠处理浮点金额，因此 amount 模式内部使用 **欧分（cents, int）** 表示金额：

* 在 `prep_inputs.py` 中将 `SalesAmountInEuro` 转为 `cents = round(euro * 100)`（建议用 `Decimal` 避免浮点误差）
* PJC 聚合得到的 sum 为 **欧分整数**
* 最终在 `public_report.json` 中可同时给出：

  * `intersection_sum_cents`（int，便于复核）
  * `intersection_sum_eur`（string，保留两位小数，便于展示）

---

## 常见问题排查

### 1）gRPC 消息过大（4MB 限制）

报错示例：

```text
Received message larger than max (6037379 vs. 4194304)
```

**解决办法**：缩小窗口（减少数据规模），例如把 24h 改为 3h：

```bash
bash moduleA_psi/scripts/run_pipeline.sh \
  --criteo-tsv data/extracted/criteo/latest/Criteo_Conversion_Search/CriteoSearchData \
  --start-ts 1596439471 \
  --end-ts   1596450271 \
  --value-mode count \
  --out runs/w3_criteo_count_3h \
  --job-id w3_criteo_count_3h \
  --k 20
```

### 2）产物缺失

若缺少 `public_report.json`：

1. 确认 `prep_inputs.py` 已生成 `server.csv/client.csv/job_meta.json`
2. 确认 `run_pjc.sh` 已生成 `attribution_result.json`
3. 再单独运行 `policy_release.py` 生成 `public_report.json`


