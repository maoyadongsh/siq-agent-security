# Windows profile 启用前的初始签名身份

最初增量修正真实 CLI 的 `init → state-enable-windows-resources --confirm → serve` 顺序。当时 `init` 仅建立安装元数据；Windows profile 启用会追加不可变兼容日志。若首次签名身份延迟到日志之后才创建，原有丢失身份保护会将该状态视为历史状态，正确拒绝生成替代密钥。不能通过放宽历史保护、修改运行脚本顺序或伪造旧签名解决。

显式启用命令在完整确认参数之后、首次发布启用日志之前，对兼容且具有受支持 v2 标记的状态，在主 Writer 所有权内调用既有签名身份加载器。仅初始元数据/空目录骨架可首次创建密钥；已有身份只读取验证，已有非初始历史而缺少密钥仍返回 `identity_missing_restore_required`，不新建密钥、不发布启用日志。已有损坏/不安全密钥不覆盖、不修权限。未初始化、不兼容或未确认的目录不能因这个步骤被初始化。

这一步不批准 Grant、不修改既有配置或授权语义、不产生新签名历史，也不改变 `init` 的输出合同。首次密钥按现有私密文件规则排他创建；不新增秘密存储方式或恢复后门。密钥建立后，即使后续启用失败也保留该身份，不清理或轮换。

活跃 Windows profile 兼容屏障必须继续由原显式启用恢复器验证和恢复，不能先调用会被屏障阻断的普通 signing.Load。该分支不创建或读取签名秘密、不绕过原恢复器的完整校验。恢复仅补齐原兼容转换；若密钥已丢失，恢复完成后的正常服务入口仍拒绝并要求恢复原密钥，不以兼容日志作为重新生成身份的许可。

验证要求：真实 CLI 正常顺序能达到 serve 健康响应；首次启用及幂等重试保持同一公钥；有历史但缺失/损坏密钥拒绝且不新增启用日志；合法活跃屏障显式恢复不被新前置步骤阻断，缺钥恢复后仍拒绝服务。既有 stateformat、迁移协议、消费者屏障和 identity_guard 均不改变。

## 2026-09-28 新装与已有状态分流

Windows 的全新 `init` / `start` / `client-install` 现在先在 Writer 内建立初始元数据与持久签名身份，再释放 Writer 并调用原 profile 激活事务。只有目录本来为空且本次实际初始化，才自动启用 Windows profile；这不产生业务 Grant。初始化完成后必须读回 profile 门槛，失败不能报告就绪。环境变量注入签名身份在任何初始化写入前拒绝。

已有状态不隐式迁移或启用。使用同一固定 EXE 和精确状态目录执行 `state-migrate --preview`，核对目录身份、EXE SHA-256、对象错误与停止服务要求；确认后先正式停止本实例，再运行 `state-migrate --confirm --binding <invocation_binding>`，随后显式 `state-enable-windows-resources --confirm`。绑定丢失、目录或 EXE 路径/内容变化均拒绝。中断后保持原身份和撤销记录，按原事务恢复，不创建替代密钥。

已有完整身份但 profile 未启用，或全新初始化在 profile 前中断，`init` 和 `client-install` 都明确返回恢复要求；不把 metadata 已存在当作完成。旧初始元数据缺密钥仍仅按原 identity_guard 规则准备身份；有非初始历史缺密钥仍拒绝。升级操作卡见 [Windows WorkBuddy 恢复卡](windows-workbuddy-upgrade-recovery-20260928.md)。
