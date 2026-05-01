# 平台级剩余工作量估算

## 1. 估算口径

这里的“平台级别”指的是：

1. 不再只是 demo / sidecar 拼装。
2. 关键敏感边界有独立 deploy/lifecycle/authn 形态。
3. control plane 不再只是 post-run SQLite 查询壳。
4. query / audit / metadata / platform-health 这些外围入口具备稳定平台入口形态。
5. KMS / authz / audit retention / ops 不再只停留在本地 mock 或单机脚本。

这里**不**把下面这些一起算进来：

1. 完整生产级多租户硬隔离。
2. 真正的 HSM / 云 KMS 落地。
3. 多机房、SLO、告警轮值、容量规划。
4. 完整管理员 UI、SDK 发布、长期兼容支持。

如果把这些也一起算进来，工时会明显更大。

## 2. 5h 口径

统一按下面口径估算：

1. `1 block = 5h`
2. 一个 block 默认应该能完成一段“代码/验证/文档”闭环，而不是只做分析。
3. 估算是剩余实现量，不含多人排期等待。

## 3. 总表

| 任务 | 剩余 block | 约合工时 | 说明 |
| --- | ---: | ---: | --- |
| owner：隐私内核与接口治理 | 10 | 50h | 还差独立敏感边界、handoff 进一步收紧、兼容/回放治理 |
| 工程师 A：控制面、身份、权限与密钥 | 10 | 50h | 还差统一身份映射、Vault/KMS、control-plane 写路径 |
| 工程师 B：查询入口、目录、工作流、观测 | 8 | 40h | 还差 execute 级权限、durable workflow、dashboard/UI 壳 |
| 工程师 1：审计、运维与稳定性工具 | 4 | 20h | 还差部署/恢复/SLO 包、fuzz/安全门禁收口 |
| 工程师 2：SQL 控制面侧车 | 8 | 40h | 还差 Postgres-ready、写侧 ownership、导入一致性与运维化 |

合计：

1. 串行视角：`40 blocks = 200h`
2. 并行视角：如果 5 条线都有人并行推进，关键路径大致落在 `10-12 blocks = 50h-60h`，再加联调缓冲

## 4. 解释

为什么 owner 和工程师 A 仍然高：

1. 当前真正没补齐的，不再是“能不能跑通”，而是“能不能作为平台边界长期存在”。
2. owner 线已经补完本地 append-only 审计锚点，剩下更贵的是 recovery deploy/handoff/compatibility/replay 治理。
3. 工程师 A 这条线也已经越过 demo 阶段，剩下的是最贵的 authz/KMS/control-plane 写路径工作。

为什么工程师 B、工程师 1、工程师 2 稍低：

1. 这三条线现在已经有明显 sidecar 基线。
2. 工程师 1 的 append-only 审计归档基线已经补上，剩余工作主要是把 sidecar 升成更像 deployment package 的入口与门禁，而不是从零起步。
3. 其余两条线剩余工作也主要是把 sidecar 升成平台入口，而不是从零起步。

## 5. 使用方式

建议后续所有“公布工作量”统一写成：

1. 本次完成了哪个任务的第几个 `5h block`
2. 该 block 的入口、验证、文档回写位置
3. 剩余 block 数

这样后面的节奏会更清楚，也更方便判断哪个任务已经接近平台级收口。
