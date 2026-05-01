# 变更提案目录说明

这个目录只放会影响主链路冻结接口的变更提案。

适用场景：

1. 改主入口参数语义
2. 改冻结字段含义
3. 改 schema 名或主输出语义
4. 改 bridge / PJC / release contract
5. 让主链路强依赖新的数据库、服务或 API

文件命名规则：

```text
docs/change_requests/<YYYYMMDD>_<topic>.md
```

建议流程：

1. 复制 [00000000_change_request_template.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/change_requests/00000000_change_request_template.md)
2. 改成当天日期和主题
3. 写清当前接口、拟议接口、兼容策略、回滚方案、验证方法
4. 获得 owner 批准后再改代码

这个目录不是：

1. 普通需求说明目录
2. benchmark 计划目录
3. sidecar-only 小改动目录

如果只是新增文档、只读 adapter、benchmark、scan、完全向后兼容的可选参数，通常不需要进入这里。
