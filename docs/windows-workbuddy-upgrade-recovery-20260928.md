# Windows WorkBuddy 升级与恢复操作卡

本卡用于本次开发候选；正式签名及原生验收未完成时，不把候选当作已发行安装包。所有命令使用已独立验签的绝对 EXE 路径和同一 `SIQ_AGENT_SECURITY_STATE_DIR`。先记录版本、EXE SHA-256、state_directory_id、instance_id、签名任务名、Grant ID/revision/digest 与撤销状态；不导出凭据、签名密钥或完整私密状态。

## 新安装

在新建的专用私密状态目录中使用正式签名的 `client-install --manifest <manifest> --binary <exe> --confirm-install`。Windows 新状态自动创建初始身份和兼容 profile，随后按原安装事务暂存、注册并读回。成功后分别核对 `status`、`task-runtime`、实例诊断与首次原生 Read/Write。服务后台运行不代表登录自启、已接入宿主或业务 Grant 已批准。

若失败发生在初始元数据之后，保留该目录及其原身份，转入下面的已有状态流程；不要重新生成密钥或换目录掩盖失败。

## 已有状态：预览、停止、迁移、恢复

1. 用固定候选 EXE 执行 `state-status`、`state-migrate --preview`。预览只读，记录 `state_directory_id`、`instance_id`、`executable_path`、`executable_sha256`、`invocation_binding` 和 profile 状态。运行中的服务仍可能改变清单，提交会在五个生命周期锁内复验。
2. 若需要迁移，使用当前签名任务所属 EXE 执行 `task-stop --confirm-stop`；读回该任务空闲与 Writer 已释放。不要 kill 所有 SIQ 进程，不删除锁。
3. 保持预览时的候选 EXE 与状态目录，执行 `state-migrate --confirm --binding <原预览 invocation_binding>`。格式已兼容可返回 `up_to_date`，不重做迁移；需要 profile 时执行 `state-enable-windows-resources --confirm`。绑定不是授权令牌。
4. 每一步都检查退出码。失败或中断后先 `state-status`，根据原 journal 用同一绑定恢复原迁移；不手改 marker，不恢复旧 Grant，不清除撤销记录。真实内容/身份漂移要先查明，不能把所有失败当作硬链接。
5. 完成迁移后，若尚未切换签名系统任务，使用仍匹配当前任务且支持当前状态 reader/writer 的原 EXE 执行 `task-start --confirm-start`。随后分别检查 `task-runtime` 和 `status` 的本实例健康读回。启动失败时保留事务并报告未恢复。

活动对象多链接默认拒绝。错误码区分 multiple_links、reparse、owner_mismatch、private_check_failed、object_changed，并仅指向相对对象。产品不提供自动解绑入口；如果必须处理，需要另行审阅精确清单、对象归属、私密备份、字节摘要和 ACL 权限语义，在明确批准后建立独立单链接副本，保留外部别名。原修复批的 PowerShell 不可套用于用户目录。

## 已有服务升级和回退

使用当前任务绑定的已验签 EXE：

```text
service-upgrade --manifest <new-manifest> --binary <new-exe> --source-manifest <old-manifest> --confirm-upgrade
service-upgrade --manifest <same-new-manifest> --binary <same-new-exe> --confirm-upgrade --recover <transaction-id>
service-rollback --transaction <upgrade-id> --binary <original-old-exe> --manifest <old-manifest> --confirm-rollback
```

记录实际事务 ID，不填示例 ID。恢复时不与 `--source-manifest` 混用；旧 EXE 缺失时，仅在已审核原签名快照情况下显式追加 `--restore-missing-binary`。回退前旧版本必须支持当前状态格式/profile，不能通过回退整个状态目录恢复旧权限。系统任务切换完成仍需真实版本/目录健康检查。

## WorkBuddy 安装与卸载

先用管理台选定精确实例预览，核对配置根、Read/Write 目录、工具、有效期和实际变更摘要。共享只读预检覆盖配置、直接父目录和专属凭据对象；不合格时安装前拒绝。任何对已有 DACL 的修复必须独立说明对象和 ACE 变化，产品不递归修改或删除未知主体。

应用后重新获取实例诊断；`runtime_verified=false` 或 `effective_readback=null` 保持原含义。新 Grant 由用户完成具体批准，管理浏览器连接不代替授权。第三方插件和 hook 由事务保留；失败使用该实例原事务恢复入口。卸载不触碰其他实例，不自动撤销或恢复业务权限。卸载、重装、回滚后各用新任务验证真实加载，并保留此前失败证据。

## 常见运行结果

| 结果 | 下一步 |
| --- | --- |
| scheduler_running / 267009 | 仅调度器正在运行；另查本实例 API 健康和真实工具回执 |
| service_unavailable / enrollment unavailable | 检查同一服务；不是服务端范围拒绝，不重新发凭据 |
| identity_rejected | 检查专属身份是否有效或撤销；HTTP 401/403 不等同于已证明到期 |
| session_expired / Grant 过期 | 分别展示实际到期时间，不自动续期 |
| execution uncertain | 保留事件及调用关联，不自动重放 |
| resource identity unavailable | 检查目标是否存在；跳过非必需 memory，不扩大到整个用户目录 |
| present_files / Glob / Grep | 当前最小 Read/Write Grant 不提供该映射；UI 卡片不证明工具受控 |

只读 `task-start --help` / `task-stop --help` 不读取或修改状态。最终报告必须区分组件测试、原生任务调度测试和真实 WorkBuddy 模型业务结果。
