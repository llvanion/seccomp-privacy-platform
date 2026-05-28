# seccomp-privacy-platform

基于 **PJC（Private Join and Compute）** 与 **SSE（Searchable Symmetric Encryption）** 的电商隐私数据查询平台。

让商家与平台在 **不交换用户明细** 的前提下，完成跨方归因、复购、客服回访、风控拼图等典型数据合作场景。原始 join key 全程经 SSE / HMAC / KMS 保护，输出仅暴露聚合结果（交集大小、求和金额等）。

主链路：

```text
SSE 候选导出  →  受控记录恢复  →  Rust Bridge 令牌化  →  A-PSI / PJC 求交  →  策略发布
```

许可证：GPL-3.0-or-later（详见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)）。

---

## 功能

- **可搜索对称加密存储**（`sse/`）：加密记录存储（PBKDF2HMAC-SHA256 + AES-256-GCM）、SSE 关键字搜索、加密候选记录恢复服务（Unix socket / HTTP 双 transport）。
- **令牌化桥接器**（`bridge/`，Rust）：join-key 规范化（email / phone / id）、作用域受控 HMAC token 生成、作业元数据生成与审计。编译为单一可执行二进制。
- **隐私求交与策略发布**（`a-psi/`）：基于 Google private-join-and-compute 的两方求交、重复查询拒绝、阈值控制、公开报告生成、审计链密封。
- **SQL 控制面 Sidecar**（`migrations/` + `scripts/`）：SQLite / PostgreSQL 双后端，记录租户 / 数据集 / 服务 / 调用方 / 作业 / 审计 / 策略 / 密钥注册等；附只读 HTTP API。
- **Operator Console SPA**（`console/`，Vite + React + TypeScript）：覆盖 home / jobs / requests / audit / catalog / permissions / recovery / observability / compliance / security 全部 10 个 section，配套 6 个本地 sidecar HTTP API（operator dashboard、metadata、query workflow、audit query、platform health、record recovery）。
- **可观测性与运维**：80+ JSON 契约校验、13+ benchmark 工具、Prometheus `/metrics`、Grafana / Tempo dashboard、chaos 注入、HTTP 异常输入 gate、审计篡改检测、外部审计 anchor（S3 Object Lock / Sigstore Rekor）。
- **三种触发方式都可被 SPA 一键驱动**：(1) 端到端 `SSE→bridge→PJC→release`（`/jobs/start`），(2) 独立 SSE 关键字搜索（`/sse-query`），(3) 独立 PJC 求交（`/pjc-only`，跳过 SSE / bridge，对已有 bridge 输出直接跑 PJC + 策略发布）。

更详细的功能边界、合规映射与电商业务身份模型请见 [docs/COMPACT_PLATFORM_BRIEF.md](docs/COMPACT_PLATFORM_BRIEF.md)。

---

## 安装与使用

提供三种部署方式，按"上手成本 从低到高"排列。

### 方式 1 — 从 GitHub Releases 下载预构建工件（推荐）

发 tag 触发 `.github/workflows/release.yml` 后，Releases 页面会自带以下工件，每个配套 `.sha256`：

| 工件 | 内容 | 体积参考 |
| --- | --- | --- |
| `bridge-<target>.tar.gz` / `.zip` | Rust bridge 单文件二进制；6 个目标：Linux x86_64 gnu+musl、Linux aarch64、Windows MSVC、macOS arm64+x86_64 | ~640 KB |
| `seccomp-privacy-cli-<host>.tar.gz` / `.zip` | PyInstaller 打包的三个 Python CLI：`seccomp-sse-client`、`seccomp-record-recovery-service`、`seccomp-init-metadata-db`（Linux / Windows / macOS） | ~43 MB |
| `console-static-<tag>.tar.gz` | Operator Console SPA 构建产物（Vite + React + Tailwind） | ~1 MB |
| `seccomp-privacy-platform-<tag>-source.tar.gz` | 源码 tarball（`git archive`） | ~1.8 MB |
| `ghcr.io/<owner>/<repo>:<tag>` | Docker 镜像（Rust builder + Node builder + Python venv + SPA dist） | 多 MB |

最小用法（Linux x86_64）：

```bash
# 1. 解压 bridge
tar -xzf bridge-x86_64-unknown-linux-gnu.tar.gz
cd bridge-x86_64-unknown-linux-gnu
./bridge --help

# 2. 校验工件完整性
sha256sum -c bridge-x86_64-unknown-linux-gnu.tar.gz.sha256

# 3. 解压 Python CLI 三件套
tar -xzf seccomp-privacy-cli-x86_64-unknown-linux-gnu.tar.gz
seccomp-privacy-cli-x86_64-unknown-linux-gnu/seccomp-sse-client/seccomp-sse-client --help
seccomp-privacy-cli-x86_64-unknown-linux-gnu/seccomp-record-recovery-service/seccomp-record-recovery-service --help
seccomp-privacy-cli-x86_64-unknown-linux-gnu/seccomp-init-metadata-db/seccomp-init-metadata-db --help

# 4. 展开前端静态产物（用任意 HTTP 服务器伺服 / 或交给本仓库 dashboard 服务器）
tar -xzf console-static-<tag>.tar.gz
# (a) 用本仓库 dashboard server（推荐）：
python3 -m pip install -r sse-requirements.txt   # 若选择带服务端能力
python3 scripts/serve_operator_dashboard.py \
  --out-base "$PWD/tmp/run" \
  --console-dist "$PWD/console-static-<tag>" \
  --port 18094
# (b) 或任何静态 HTTP server (nginx, caddy, python http.server)
python3 -m http.server -d console-static-<tag> 8080
```

完整发布流程参见 [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md)。

### 方式 2 — Docker 镜像（一键全栈）

```bash
# 拉取一个 tagged release
docker pull ghcr.io/<owner>/seccomp-privacy-platform:v0.1.0

# 直接跑端到端 demo
docker run --rm ghcr.io/<owner>/seccomp-privacy-platform:v0.1.0

# 启动 operator dashboard + 浏览器打开 console SPA
docker run --rm -p 18094:18094 \
  ghcr.io/<owner>/seccomp-privacy-platform:v0.1.0 \
  python3 scripts/serve_operator_dashboard.py \
    --out-base /var/lib/seccomp/run \
    --bind-host 0.0.0.0 \
    --port 18094
# 然后浏览器访问 http://localhost:18094/

# 进入容器做运维操作
docker run --rm -it ghcr.io/<owner>/seccomp-privacy-platform:v0.1.0 bash

# 或用 compose
IMAGE=ghcr.io/<owner>/seccomp-privacy-platform:v0.1.0 \
  docker compose -f docker-compose.release.yml up
```

镜像内含：

- `/usr/local/bin/bridge`（Rust 二进制）
- `/opt/seccomp/venv`（Python 依赖 venv）
- `/opt/seccomp/platform/console/dist`（SPA 静态资源）
- `/opt/seccomp/platform/{sse, scripts, services, a-psi/moduleA_psi, migrations, schemas, config, docs}`

### 方式 3 — 从源码本地构建

```bash
# 0. 准备：node 20、Rust 稳定版、Python 3.11、bazelisk（PJC 可选）

# 1. Python 环境（SSE + 编排脚本）
cd sse && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ..

# 2. Rust bridge
cd bridge && cargo build --release && cd ..

# 3. Operator Console SPA
cd console && npm ci && npm run build && cd ..
# 产物：console/dist/

# 4. 一键端到端 live demo（输出 intersection_size=2、intersection_sum=425）
bash scripts/run_live_sse_bridge_demo.sh

# 5. 启动 operator console + 浏览器访问
python3 scripts/serve_operator_dashboard.py \
  --out-base "$PWD/tmp/run" \
  --console-dist "$PWD/console/dist" \
  --port 18094
# 打开 http://127.0.0.1:18094/
```

#### 本地一键复刻 Releases 工件

```bash
# 默认产出 dist/release/{bridge,cli,console,source}-*.tar.gz + .sha256
bash scripts/build_release_bundle.sh
RELEASE_TAG=v0.1.0 bash scripts/build_release_bundle.sh

# 跳过 / 加项：
bash scripts/build_release_bundle.sh --skip-pyinstaller --skip-console
bash scripts/build_release_bundle.sh --docker    # 同时构建 docker 镜像（需要 daemon）

# 缺什么工具就跳过哪个（不会让整个脚本失败）：
#   cargo 缺失       → skip bridge
#   pyinstaller 缺失 → skip Python CLI bundle
#   npm 缺失 / 离线  → skip console SPA
#   git 缺失         → skip source tarball
#   docker 缺失      → skip docker (仅 --docker 启用时)
```

输出示例（本地 Linux x86_64 工作站，已构建过的工件）：

```text
dist/release/
├── bridge-x86_64-unknown-linux-gnu.tar.gz         (~640 KB)
├── bridge-x86_64-unknown-linux-gnu.tar.gz.sha256
├── seccomp-privacy-cli-x86_64-unknown-linux-gnu.tar.gz   (~43 MB)
├── seccomp-privacy-cli-x86_64-unknown-linux-gnu.tar.gz.sha256
├── console-static-<tag>.tar.gz                    (~1 MB)
├── console-static-<tag>.tar.gz.sha256
├── seccomp-privacy-platform-<tag>-source.tar.gz   (~1.8 MB)
├── seccomp-privacy-platform-<tag>-source.tar.gz.sha256
└── release-manifest.json
```

---

## Operator Console（前端 SPA）

`console/` 是一份基于 Vite + React + TypeScript + Tailwind 的单页 SPA，覆盖以下路由：

| 路由 | 内容 |
| --- | --- |
| `/home` | 平台健康概览、最近作业、告警、快速入口 |
| `/jobs/*` | 作业列表（带过滤）、stage 时序、结果 JSON、启动 + 重启表单 |
| `/requests/*` | 请求提交、列表、详情、批准 / 拒绝、转换历史 |
| `/sse-query` | **独立 SSE 关键字搜索**：临时启服务、加密索引、search、返回命中文档 ID（驱动 `scripts/sse_oneshot_search.py`） |
| `/pjc-only` | **独立 PJC 私有求交**：对已有 bridge CSV 跑 `run_pjc.sh` + 策略发布，返回 attribution + public_report（驱动 `scripts/pjc_run_only.py`） |
| `/audit/*` | 公开报告、审计链 + seal、观测事件、目录 / 血缘、外部 anchor |
| `/catalog/*` | 租户 / 数据集 / 服务 / 血缘 / 电商事实层 |
| `/permissions/*` | 调用方 / 策略 / 绑定 / 权限矩阵 / 密钥环 / KMS / OpenFGA |
| `/recovery/*` | 记录恢复服务状态、Prometheus 指标、PJC mTLS 双方 enroll、TLS 诊断 |
| `/observability/*` | 组件健康、事件流、告警、Grafana/Tempo 入口、chaos drills |
| `/compliance/*` | GDPR Article 5(1) / 15-22 矩阵、威胁模型、reviewer 8 步、许可证 |
| `/security/*` | 篡改检测、异常输入 gate、mTLS benchmark、卫生扫描、契约 smoke、benchmark 画廊 |
| `/settings` | 配置 6 个 sidecar 的 baseUrl + Bearer token（localStorage 本地） |

部署模式：

- **同源（推荐）**：`scripts/serve_operator_dashboard.py --console-dist` 同时伺服 SPA 静态资源（`/`）与 sidecar API（`/v1/*`、`/healthz`、`/metrics`）。SPA 客户端路由通过 history 模式回退到 `index.html`。
- **跨源开发**：`npm --prefix console run dev` 启动 Vite dev server（默认 5173），通过 `vite.config.ts` 把 `/v1/*` `/healthz` `/metrics` 代理到 `CONSOLE_DEV_PROXY_TARGET`（默认 `http://127.0.0.1:18094`）。

更多前端细节：[console/README.md](console/README.md)。

---

## 分步实操：SSE 查询 与 PJC 计算

下面把"如何运行"拆成 **三个独立子流程**：先单独跑 SSE 关键字查询，再单独跑 PJC 求交，最后跑一键串联的 SSE → bridge → PJC → release。

前置：已完成上文 **方式 3** 的源码安装（Python venv + Rust release + 可选 SPA build）。

---

### A. SSE 关键字查询（独立流程）

SSE 模块做的是 **加密关键字索引 + 服务端搜索 + 客户端解密**。下面的例子直接使用仓库自带的 `sse/example_db.json`（关键字 → 文档 ID 列表的倒排索引）。

```bash
cd sse
source .venv/bin/activate

# 1) 启动 SSE 服务端（默认本地，CJJ14.PiBas scheme）
python run_server.py start &
SSE_SERVER_PID=$!
sleep 1

# 2) 生成一份 SSE config（选择 scheme + 参数）
python run_client.py generate-config \
  --scheme CJJ14.PiBas \
  --save-path /tmp/sse-config.json

# 3) 在服务端注册一个加密服务实例
python run_client.py create-service \
  --config /tmp/sse-config.json \
  --sname demo-service

# 4) 生成对称密钥 + 加密 example_db.json + 上传配置 + 上传加密数据库
python run_client.py generate-key --sname demo-service
python run_client.py encrypt-database \
  --sname demo-service \
  --db-path example_db.json
python run_client.py upload-config --sname demo-service
python run_client.py upload-encrypted-database --sname demo-service

# 5) 关键字搜索（在 example_db.json 中，"China" 对应 4 条记录 ID）
python run_client.py search \
  --sname demo-service \
  --keyword China \
  --output-format hex

# 期望输出（4 个文档 ID）：
#   3A4B1ACC12AA1B2D
#   2DDD1FFF1122BBCC
#   1122AA4B101A2812
#   C2C2C2C21010AACC

# 收尾
kill $SSE_SERVER_PID
cd ..
```

要点：

- 服务端只看到加密后的索引；**关键字明文从未离开客户端**。
- `--output-format` 支持 `int / hex / raw / utf8`，匹配上传时 value 的实际编码。
- 多关键字同时检索：把 `search` 换成 `multi-search`；倒排索引每个 value 可绑定多个 key 的玩法见 `sse/example_usage.py`。
- 想把加密索引绑回真实业务数据（订单/客户/凭证），换用 `create-encrypted-record-store` + `export-bridge-records`（见 SSE → bridge → PJC 串联部分）。

---

### B. PJC 私有求交（独立流程）

A-PSI 模块基于 Google **private-join-and-compute** 做两方 **Private Intersection-Sum**：双方各持一组 join key，求交集大小 + 交集上 client 侧某个数值字段（如 amount）的和，**全程不暴露明细**。

主链路的 PJC 输入必须是 **bridge 令牌化之后** 的 CSV：每行是 `HMAC(join_key)` 之类的不可逆 token，而不是明文 join key。Bridge 完成这步。

```bash
# 仓库自带的 server / client 演示数据
cat bridge/examples/server_export.csv     # join key 一列
cat bridge/examples/client_export.csv     # join key + amount 两列

# 1) 用 Rust bridge 将明文 join_key 规范化 + HMAC，输出 PJC 可吃的两份 CSV + job 元数据
./bridge/target/release/bridge prepare-job \
  --server-input  bridge/examples/server_export.csv \
  --server-input-format csv \
  --server-join-key-column email \
  --server-normalizer email \
  --client-input  bridge/examples/client_export.csv \
  --client-input-format csv \
  --client-join-key-column email \
  --client-value-column amount \
  --client-value-mode raw-int \
  --client-normalizer email \
  --out-dir bridge/out/pjc_demo \
  --job-id pjc_demo \
  --token-scope demo-scope \
  --token-secret local-dev-secret

# bridge 产物：bridge/out/pjc_demo/{server.csv,client.csv,job_meta.json,bridge_audit.jsonl}

# 2) 跑 PJC 服务端 + 客户端（Google PJC 的 bazel 构建产物）
#    run_pjc.sh 通过环境变量接收输入；首次运行设 PJC_BUILD=1 让脚本自动编译 PJC 二进制
SERVER_CSV="$PWD/bridge/out/pjc_demo/server.csv" \
CLIENT_CSV="$PWD/bridge/out/pjc_demo/client.csv" \
OUT_DIR="$PWD/a-psi/runs/pjc_demo" \
JOB_ID="pjc_demo" \
PJC_BUILD=1 \
  bash a-psi/moduleA_psi/scripts/run_pjc.sh

# 产物：a-psi/runs/pjc_demo/attribution_result.json，里面是 {intersection_size, intersection_sum}

# 3) 走"策略发布"门——含 k-阈值、重复查询拒绝、隐私预算、可选 DP 噪声、审计封印
python3 a-psi/moduleA_psi/scripts/policy_release.py \
  --input        a-psi/runs/pjc_demo/attribution_result.json \
  --job-meta     bridge/out/pjc_demo/job_meta.json \
  --out          a-psi/runs/pjc_demo/public_report.json \
  --audit-log    a-psi/runs/pjc_demo/policy_audit.jsonl \
  --caller       demo \
  --job-id       pjc_demo \
  --threshold-k  1 \
  --max-queries  5

# 4) 查看结果（脱敏后的公开报告）
cat a-psi/runs/pjc_demo/public_report.json
# 期望:
#   intersection_size = 2
#   intersection_sum  = 425
#   released          = true
```

要点：

- 不要直接把明文 join key 喂给 PJC——总是先过 `bridge prepare-job`，由 bridge 做 HMAC 令牌化 + scope 隔离 + 审计。
- `policy_release.py` 不仅写出公开报告，还会写 **可重放的审计行**（`policy_audit.jsonl`）；这条审计被外层主链路串成 `audit_chain.json`。
- 生产模式下 `--token-secret` 必须改为 `--token-secret-env BRIDGE_TOKEN_SECRET`（命令行明文密钥会被拒绝）。
- k-匿名阈值（`--threshold-k`）、查询次数限制（`--max-queries`）、重复查询拒绝（`--deny-duplicate-query`）、DP 噪声（`--dp-epsilon`）等都在策略发布这一步生效。

---

### C. 一键端到端：SSE → bridge → PJC → release

把 A + B 串起来，再叠加 SSE 候选导出 + 加密记录恢复，就是仓库主链路。下面是同一份 demo 的"完整链路"版：

```bash
# 1) 用 SSE 服务过滤候选 + 加密记录存储恢复明细（可选；不需要可以跳过，直接用明文 JSONL）
export SSE_RECORD_STORE_PASSPHRASE=<passphrase>
sse/.venv/bin/python sse/run_client.py create-encrypted-record-store \
  --source-path sse/examples/bridge_client_records.jsonl \
  --out-path sse/exports/client_records.enc.jsonl \
  --source-format jsonl \
  --record-id-field email_hex \
  --key-env SSE_RECORD_STORE_PASSPHRASE

# 2) 跑整条主链路（自动覆盖 SSE 导出 → bridge 令牌化 → PJC → 策略发布 → 审计链密封）
bash scripts/run_sse_bridge_pipeline.sh \
  --server-source "$PWD/sse/examples/bridge_server_records.jsonl" \
  --client-source "$PWD/sse/examples/bridge_client_records.jsonl" \
  --server-join-key-field email \
  --client-join-key-field email \
  --client-value-field amount \
  --token-scope demo-scope \
  --token-secret local-dev-secret \
  --job-id demo_job \
  --out-base "$PWD/tmp/demo_run"

# 3) 用 Operator Console + dashboard 在浏览器观察运行结果
python3 scripts/serve_operator_dashboard.py \
  --out-base "$PWD/tmp/demo_run" \
  --console-dist "$PWD/console/dist" \
  --port 18094 &
# 浏览器访问 http://127.0.0.1:18094/jobs

# 4) 命令行查看公开报告与审计链
cat tmp/demo_run/a_psi_run/public_report.json
cat tmp/demo_run/audit_chain.json
```

期望输出：`intersection_size=2`，`intersection_sum=425`。

更多变体（FIFO handoff、加密记录恢复、KMS 取 token secret、跨方 mTLS）见 `scripts/run_sse_bridge_pipeline.sh --help` 与 `scripts/run_live_sse_bridge_demo.sh`。

---

## 模块结构

```text
.
├── bridge/                 # Rust：join-key 规范化 + HMAC 令牌 + 作业元数据
├── sse/                    # Python：SSE 服务端/客户端、加密记录存储、受控导出
├── services/               # Python：长期运行服务（记录恢复 HTTP / Unix socket）
├── a-psi/                  # PJC 求交 + 策略发布 + 公开报告
│   ├── moduleA_psi/        # 第一方调度与策略层
│   └── private-join-and-compute/  # Google PJC 上游（Apache-2.0）
├── console/                # Operator Console SPA（Vite + React + TypeScript）
├── scripts/                # 编排、契约 smoke、benchmark、observability、KMS / IAM adapter、dashboard 服务
├── migrations/             # SQL 控制面 schema（SQLite / PostgreSQL）
├── schemas/                # JSON 契约 schema 文件（80+）
├── config/                 # 示例配置（导出策略、密钥环、KMS、observability、HA）
├── packaging/pyinstaller/  # Python CLI 打包配置
├── docs/                   # 70+ 篇深度文档
└── .github/workflows/      # CI smoke + release 流水线
```

---

## 文档入口

- 平台压缩总览：[docs/COMPACT_PLATFORM_BRIEF.md](docs/COMPACT_PLATFORM_BRIEF.md)
- 主链路详细指南：[docs/SSE_BRIDGE_APSI_PIPELINE.md](docs/SSE_BRIDGE_APSI_PIPELINE.md)
- 威胁模型与泄露模型：[docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md](docs/THREAT_MODEL_AND_LEAKAGE_MODEL.md)
- 电商隐私场景：[docs/ECOMMERCE_PRIVACY_PLATFORM_SCENARIO.md](docs/ECOMMERCE_PRIVACY_PLATFORM_SCENARIO.md)
- 电商业务身份模型：[docs/ECOMMERCE_ACCESS_MODEL.md](docs/ECOMMERCE_ACCESS_MODEL.md)
- 电商事实层：[docs/ECOMMERCE_FACT_LAYER_PLAN.md](docs/ECOMMERCE_FACT_LAYER_PLAN.md)
- 运维 runbook：[docs/OPS_RUNBOOK.md](docs/OPS_RUNBOOK.md)
- 合规映射（GDPR）：[docs/COMPLIANCE_MAPPING.md](docs/COMPLIANCE_MAPPING.md)
- 发布流程：[docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md)
- 前端 SPA：[console/README.md](console/README.md)

---

## 开发与测试

```bash
# 全量本地预检（Python / shell / Rust / 契约 / 依赖卫生 / repo 卫生）
bash scripts/check_ci_smoke.sh

# 仅跑契约 smoke
bash scripts/check_json_contracts.sh

# Rust bridge 单元测试
cd bridge && cargo test

# 前端类型检查
cd console && npm run typecheck
```

---

## 当前发布状态

`.github/workflows/release.yml` 在收到形如 `v*` 的 tag 后会自动构建全部工件并发布到 GitHub Releases。本机构建的工件（`dist/release/`）与 CI 工件一致，差异仅在于 CI 跑了完整的 6-target 跨平台 bridge 矩阵与 3-OS PyInstaller 矩阵；本机仅产出本机 target 的子集。

首次发布：

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

---

## 许可证

GPL-3.0-or-later。第三方组件许可证及范围见 [NOTICE](NOTICE)。

Google private-join-and-compute（Apache-2.0）作为第三方上游组件存在于 `a-psi/private-join-and-compute/`，按 FSF 许可证兼容性矩阵与 GPL-3.0 兼容；组合作品按 GPL-3.0 分发。
