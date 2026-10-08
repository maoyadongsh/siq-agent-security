# enterprise-upgrade-completed/v1

Linux 用户级 Edge 服务的显式配置切换与恢复。固定 publisher 验签，不注册设备、不启动/停止服务、不授予业务权限。

## 命令

- `upgrade-capabilities`：只读输出 schema_version=enterprise-upgrade-capabilities/v1、version、pending_protocol=enterprise-upgrade-pending/v1、confirmation_protocol=enterprise-upgrade-intent/v1、task_lock=true。
- `apply-enterprise-upgrade --plan FILE --from-stage DIR --to-stage DIR --tenant ID --confirm-upgrade-sha256 DIGEST`：使用 review 完整 intent 的确认摘要。
- `recover-enterprise-upgrade --direction target|previous --confirm-upgrade-sha256 DIGEST`：只恢复磁盘 pending 绑定的事务，显式选择完成或还原。

服务须由操作员事先停止。固定 `/usr/bin/systemctl --user show` 必须显示 loaded、inactive/dead 或 failed/failed、MainPID=ControlPID=0、准确 FragmentPath、无 DropInPaths。未知/不可读/活动服务拒绝。不会自动停止服务。
两份来源须固定发布公钥验签并完整核对暂存制品；使用对应发行清单中的 Edge 摘要打开、保持 FD 后探测上述能力，匹配发行版本。缺少 pending 协议的旧程序拒绝升级；不从 PATH 或制品自带公钥取信任。

## 事务

持有任务锁，复验确认摘要和停服条件，在修改配置前持久 pending。周期旧确认和其他未完成事务不得覆盖。
依次原子替换 State、原子替换 unit、同步文件/目录、执行 daemon-reload、重新确认停服和准确配置。
每次写入前重新核对日志、状态、unit、签名暂存和停服条件；任何错误保留 pending，普通任务保持拒绝。
恢复选择 target 时新计划必须仍有效；previous 允许旧安装窗口已过期。保留设备身份、凭据、执行台账及历史记录。

完成记录先排他持久到 `enterprise-upgrade-completed-<confirmation_sha256>.json`，包含 schema_version、status=configured_not_started、direction、journal（原完整 pending）、state_sha256、unit_sha256、service_started=false、business_permissions_granted=false。
相同完成记录可重试清理；不同恢复方向或第三份配置不能覆盖原完成记录。读回后才删除 pending 并同步目录。
删除后目录同步失败仍报错，不声称 durable completion；配置检查和归档支持人工核对。
成功输出完整完成 JSON；输出失败不回滚已持久配置，可根据完成文件核对。后续服务启动是另一步操作，不计入此回执。

同 UID/root 仍是信任边界。无通用防降级、签名包撤回列表或已完成业务的保证。Windows/macOS 拒绝本组受管命令。
