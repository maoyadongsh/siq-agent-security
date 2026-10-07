# 原生宿主跨进程控制 v1

本接口只面向已授权的宿主业务监管器。它通过独立私有 Unix SOCK_SEQPACKET socket 控制既有 HostSession，不提供 HTTP 注册、容器命令、审批或权限签发功能。沙箱不得获得控制配置或控制凭据。

## 部署配置与认证

私有配置精确包含 `schema_version=native-host-control-config/v1`、`credential=nhc-<64位小写hex>` 和 `control_socket`。配置及 socket 必须是当前非 root 用户拥有的 0600 对象，父目录0700；路径不得含符号链接或不可信可写祖先。启动不覆盖既有 socket；关闭不删除替换对象。凭据独立于 Go native-host 发布凭据和运行身份凭据。

服务绑定后固定 socket 与配置的内容/对象身份。控制方逐次核验私有配置、socket 和响应内核凭据；服务端核对连接 SO_PEERCRED 与每包 SCM_CREDENTIALS 相同、UID/GID 与服务一致，并保持调用者 pidfd。Fork 后借用父连接、额外 fd、坏包、截断、重复键、NaN、错误凭据或对象替换均拒绝。控制 JSON 不能自报 supervisor_pid；HostSession 的监管者 PID 只取自上述内核凭据。

此接口仍属于可信宿主边界，不宣称隔离同 UID 的恶意宿主进程。信任来自受控宿主部署、私有凭据不进入沙箱及已验证的运行时隔离。

## 消息

每次连接只处理一包请求和一包响应，最大64KiB。请求精确包含 `schema_version=native-host-control/v1`、`request_id`（32位hex）、`credential`、`operation`、`handle`（`nhs-`加32位hex）、`arguments`。有效操作如下：

| operation | arguments | 行为 |
| --- | --- | --- |
| start | backend、runtime、subject、installs、channel_directory、credential、expires_at、authorization_expires_at | 固定启动材料；两个日期为UTC ISO8601 Z字符串；调用已实现 HostSession |
| renew | authorization_expires_at | 仅原监管进程在旧心跳有效时报告复查后的期限，最多90秒、不超整体期限 |
| status | 空对象 | 核对原监管进程及实际会话状态，不续期 |
| stop | 空对象 | 仅停止该handle对应的会话，不回收容器、不关闭共享Verifier |

start 的内层 credential 是宿主保管的请求级运行身份 token，外层 credential 是控制认证；均不得打印、保存到公开证据或传入容器。daemon端点、发布配置、Verifier和可调用实现由服务启动时固定，不接受请求覆盖。

调用方在首次发送前生成 handle。handle 一旦使用即不再允许 start，包括启动失败/已关闭的情形，避免响应丢失后恢复不确定的旧启动。客户端不得自动重试 start 或 renew；可使用原 handle 显式查询/停止。不提供跨进程接管、续租或恢复旧任务。已关闭handle只保留无权限的终态，不能复活。

成功响应精确为 `schema_version=native-host-controlled/v1`、原 `request_id`、原 `handle`、`state=running|closed`；running只表示宿主会话可用，不是业务结果或effective权限。错误仅为 `error=native_host_control_unavailable`。服务端接收超时5秒，业务消费者整次控制等待上限30秒；状态不确定时不回退旧插件或另开未受管运行。

## 并发与清理

最多4个并发控制处理器、16个未关闭会话、4096个已使用handle，超出拒绝；同一handle控制串行且忙时拒绝，不排无限队列。调用者退出或心跳到期时，原 HostLoop/BusinessGuard 立即在下一核验边界拒绝；宿主服务定期回收其会话资源，失败保留清理待确认状态，不能声称已关闭。

服务停止先停止接收并封锁各会话，然后有界等待在途处理器和宿主循环。处理器/线程退出未确认时报告失败并保留仍需使用的资源。只有已确认所有会话清理完成，才可关闭共享Verifier。配置漂移和服务失联均失败关闭。日常业务Supervisor仍负责业务授权复查、执行租约及精确容器回收。
