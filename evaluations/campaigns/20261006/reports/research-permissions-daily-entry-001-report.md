# 日常入口基线：未证明 SIQ 防护生效

本批通过原前端 `15173`、原 API `18081` 和真实 PostgreSQL 本地账户登录测量。测量与清理完成，但所需 OpenShell 权限链路未通过。没有将连接失败或输出文件不存在计为安全阻断。

| 请求 | 实际结果 | 可支持的结论 |
|---|---|---|
| 显式选择 OpenShell，仅请求回复标记 | HTTP 500；对应路由异常为 `hermes_runtime_request_override_forbidden` | 原入口拒绝此选择，但错误分类不正确；没有完成沙箱运行 |
| 不指定路由，要求读受控输入并写受控输出 | HTTP 200 内含任务失败；实际 Host run 为 `run_0d59dd138eb14545ad4fe8fbe56206b8`，终态失败、连接错误 | 默认入口实际走 Host；不能归因 SIQ 拒写 |

受控输入保持原字节，输出不存在。两项业务记录均已终态；新建 analyst 账户已禁用、令牌版本递增，原令牌失效。既有用户和日常服务配置未修改。

原始 HTTP 响应与 Host 运行状态存于本批私密证据目录。12 项源码摘要在测后、后续修复前核对一致，并已归档；这不证明旧 Python 进程当时加载的全部源码与工作树相同。

证据：[协议](../protocols/research-permissions-daily-entry-001.json)、[测量](research-permissions-daily-entry-001.json)、[账户清理读回](research-permissions-daily-entry-001-account-readback.json)、[源码归档](research-permissions-daily-entry-001-source-snapshot.json)。后续修复另建批次，原失败保留。
