# SIQ 业务安全事件 Connector

`siq-connector` 读取 SIQ 业务 API 产生的 `siq.business-security-event/v1` 本地投影，并通过 Connector v1 子进程协议输出 `siq_hub` candidate 与 `gateway` evidence。

该边界不接收业务凭据，也不访问 HTTP、IAM、Hub、Gateway 或业务数据库。业务 API 先完成身份校验、数据 scope 复验和模型路由选择，再把 tenant、subject、session、run 与 audit trace 转换为带域分离的 SHA-256 引用。授权快照、数据 scope 和模型路由只保留既有摘要；提示词、回复、Bearer token 和业务记录不得进入事件。

输入目录必须由运行用户拥有且权限不宽于 `0700`，事件文件必须是 `0600`、单链接普通文件。Connector 拒绝空范围、根目录、通配符、符号链接、硬链接、重复 JSON key、未知字段、超限文件、跨租户引用不一致、run/audit 关联不一致，以及未确认写静默的成功终态。Connector 只产生观察证据，不输出 `effective` permission fact。

本地构建和扫描示例：

```bash
go -C connectors/siq build -o .tmp/bin/siq-connector .
go -C edge/agent build -o .tmp/bin/siq-edge .
.tmp/bin/siq-edge run-once \
  --connector siq \
  --connector-bin .tmp/bin/siq-connector \
  --scope '{"roots":["/absolute/owner-only/security-export"]}'
```

研究 API 侧使用 `SIQ_SECURITY_EXPORT_ENABLED=1` 显式开启，`SIQ_SECURITY_EXPORT_ROOT` 可覆盖默认的 `var/security-export`。生产部署应让 API 写入、Edge 只读挂载该目录，并为两个进程配置能满足 owner-only 约束的同一服务身份或等价受控身份映射。当前 Edge 远程注册能力仍未声明 `siq`；本模块已完成本地 `run-once` 与跨仓 canary，不能据此宣称远程调度或生产 IAM 已验收。
