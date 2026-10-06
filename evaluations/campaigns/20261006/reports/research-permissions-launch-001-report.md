# 日常 API 新启动与回滚入口验证

旧日常启动器绑定的历史源码清单有 12 项已发生变化，直接重启会因摘要不符失败。因此新增显式绑定当前源码清单的启动器，保留旧清单和历史启动器。

新启动器的保护模式选择 `qwen38` 请求后端和 `confidential_local`；回滚模式恢复原有 `legacy`/`host` 选择，使用本次固定的当前代码。回滚是路由配置恢复，不宣称恢复旧 Python 进程内存或修复原 Host 模型连接问题。

实启前冻结 1,644 项源码并归档，分别在独立端口 `18083` 启动保护与回滚模式。两种模式各 9 项检查全部通过：健康 HTTP、匿名请求 401、正确后端及端口、候选进程退出、端口关闭、原日常进程保持不变。独立端口明确关闭恢复所有权，不能据此推断主端口恢复或模型执行通过。

启动器另有 8 项测试，覆盖授权环境保留、配置回滚、私密文件的权限/链接拒绝、清单篡改/源码漂移拒绝，以及禁止将生产环境重新标为本地。测后 1,644 项源码再次核对一致。

证据：[预先协议](../protocols/research-permissions-launch-001.json)、[源码清单](../protocols/research-permissions-launch-001-source-manifest.json)、[实启记录](research-permissions-launch-001.json)。日常主端口切换和真实读写另见 `research-permissions-daily-permissions-*` 批次。
