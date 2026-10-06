# 日常路由错误分类修复：候选 HTTP 复测通过

本批仅验证路由异常的 HTTP 分类，不计为日常 OpenShell 权限验收。使用当前 Research API 源码和该项目原 PostgreSQL，在独立端口 `18083` 启动候选 API，经正常登录发起请求。

原先未授权 OpenShell 选择返回 HTTP 500；修复后返回 HTTP 403、`runtime_access_denied`、`retryable=false`，不暴露底层异常。业务路由仍拒绝未授权选择。SSE 对应合同为一个明确的终态错误，关闭迭代器，不重试或回退。

真实 HTTP 预检 7 项通过；测评账户禁用且令牌失效，候选进程退出，端口关闭，原日常 API PID 保持不变。此批预期模型任务数为 0，不提供文件权限正向或负向效果证据。

16 项冻结源码测后摘要一致并已归档。相关 91 项回归测试通过；测试替身与真实 HTTP 证据分别计量，不把单元测试视为真实模型能力。

证据：[协议](../protocols/research-permissions-daily-entry-002.json)、[真实测量](research-permissions-daily-entry-002.json)、[预检核验](research-permissions-daily-entry-002-preflight.json)、[源码核对](research-permissions-daily-entry-002-source-check.json)。测量文件中的 `passed=false` 沿用入口基线的保守口径；明确通过的是独立的 HTTP 分类预检。
